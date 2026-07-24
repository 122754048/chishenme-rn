"""Evidence-bound source-speech and opaque-media audio mixing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any
import wave


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION = "evidence-bound-audio-mix/v1"
_SAMPLE_RATE = 48_000
_CHANNELS = 2
_DEFAULT_POLICY = {
    "duck_gain_db": -12.0,
    "source_gain_db": 0.0,
    "fade_in_ms": 20.0,
    "fade_out_ms": 20.0,
    "limiter_true_peak_db": -1.0,
}
_POLICY_BOUNDS = {
    "duck_gain_db": (-24.0, -3.0),
    "source_gain_db": (-6.0, 6.0),
    "fade_in_ms": (5.0, 100.0),
    "fade_out_ms": (5.0, 100.0),
    "limiter_true_peak_db": (-3.0, -0.1),
}
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "region_id",
        "source_wav_sha256",
        "opaque_wav_sha256",
        "request_sha256",
        "output_wav_sha256",
        "source_media_sha256",
        "opaque_media_sha256",
        "mixed_region_sha256",
        "final_output_sha256",
        "duck_curve",
        "speech_windows",
        "sample_rate",
        "channels",
        "source_start_us",
        "source_end_us",
        "target_active_duration_us",
        "mix_policy",
        "capability_identity",
    }
)


class AudioMixerError(RuntimeError):
    """Raised when an evidence-bound mix cannot be produced safely."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _run(command: list[str], *, label: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AudioMixerError(f"{label} failed: {result.stderr.strip()}")


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AudioMixerError(f"media probe failed: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise AudioMixerError("media probe returned invalid JSON") from exc
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise AudioMixerError("media probe returned no stream inventory")
    return payload


def _stream_types(probe: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("codec_type") or "")
        for item in probe.get("streams", [])
        if isinstance(item, Mapping)
    }


def _declared_media_sha(
    path: Path,
    declared: str | None,
    *,
    label: str,
    production: bool,
) -> str:
    normalized = str(declared or "").lower()
    if production and not _SHA256.fullmatch(normalized):
        raise AudioMixerError(
            f"production evidence-bound mix requires immutable {label} SHA-256"
        )
    if normalized and not _SHA256.fullmatch(normalized):
        raise AudioMixerError(f"{label} SHA-256 is invalid")
    actual = _sha256_file(path)
    if normalized and normalized != actual:
        raise AudioMixerError(f"{label} SHA-256 does not match verified media bytes")
    return actual


def _policy(value: Mapping[str, Any] | None) -> dict[str, float]:
    raw = dict(value or {})
    unknown = sorted(set(raw) - set(_DEFAULT_POLICY))
    if unknown:
        raise AudioMixerError(
            f"evidence-bound mix policy contains unsupported fields: {', '.join(unknown)}"
        )
    result: dict[str, float] = {}
    for field, default in _DEFAULT_POLICY.items():
        candidate = raw.get(field, default)
        if isinstance(candidate, bool):
            raise AudioMixerError(f"evidence-bound mix policy {field} is invalid")
        try:
            number = float(candidate)
        except (TypeError, ValueError) as exc:
            raise AudioMixerError(
                f"evidence-bound mix policy {field} is invalid"
            ) from exc
        lower, upper = _POLICY_BOUNDS[field]
        if not math.isfinite(number) or not lower <= number <= upper:
            raise AudioMixerError(
                f"evidence-bound mix policy {field} is outside supported bounds"
            )
        result[field] = number
    return result


def _active_bounds(active_window: Any) -> tuple[float, float, int]:
    try:
        start = float(
            active_window.get("active_start")
            if isinstance(active_window, Mapping)
            else active_window.active_start
        )
        end = float(
            active_window.get("active_end")
            if isinstance(active_window, Mapping)
            else active_window.active_end
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise AudioMixerError("opaque active-window authority is invalid") from exc
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise AudioMixerError("opaque active-window authority is invalid")
    return start, end, round((end - start) * 1_000_000)


def _speech_windows(
    values: Sequence[Mapping[str, Any]],
    *,
    region_start_us: int,
    region_end_us: int,
    target_duration_us: int,
    policy: Mapping[str, float],
) -> list[dict[str, Any]]:
    if not values or len(values) > 64:
        raise AudioMixerError("evidence-bound mix requires frozen source speech windows")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in values:
        if not isinstance(item, Mapping):
            raise AudioMixerError("source speech window is invalid")
        event_id = str(item.get("event_id") or item.get("segment_id") or "").strip()
        try:
            start_us = int(item.get("start_us"))
            end_us = int(item.get("end_us"))
        except (TypeError, ValueError) as exc:
            raise AudioMixerError("source speech window is invalid") from exc
        if not event_id or event_id in seen_ids or end_us <= start_us:
            raise AudioMixerError("source speech window is invalid")
        if start_us < region_start_us or end_us > region_end_us:
            raise AudioMixerError("source speech window is outside its opaque region")
        local_start_us = start_us - region_start_us
        local_end_us = end_us - region_start_us
        if local_end_us > target_duration_us:
            raise AudioMixerError(
                "source speech extends past the opaque target active duration"
            )
        duration_ms = (local_end_us - local_start_us) / 1000.0
        if policy["fade_in_ms"] + policy["fade_out_ms"] > duration_ms:
            raise AudioMixerError("source speech fades exceed the evidenced speech window")
        seen_ids.add(event_id)
        result.append(
            {
                "event_id": event_id,
                "start_us": start_us,
                "end_us": end_us,
                "local_start_us": local_start_us,
                "local_end_us": local_end_us,
            }
        )
    result.sort(key=lambda item: (item["start_us"], item["end_us"], item["event_id"]))
    for left, right in zip(result, result[1:]):
        if left["end_us"] > right["start_us"]:
            raise AudioMixerError("source speech windows overlap")
    return result


def _request_payload(
    *,
    region_id: str,
    source_media_sha256: str,
    opaque_media_sha256: str,
    source_wav_sha256: str,
    opaque_wav_sha256: str,
    source_start_us: int,
    source_end_us: int,
    target_active_duration_us: int,
    speech_windows: Sequence[Mapping[str, Any]],
    mix_policy: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "region_id": region_id,
        "source_media_sha256": source_media_sha256,
        "opaque_media_sha256": opaque_media_sha256,
        "source_wav_sha256": source_wav_sha256,
        "opaque_wav_sha256": opaque_wav_sha256,
        "source_start_us": source_start_us,
        "source_end_us": source_end_us,
        "target_active_duration_us": target_active_duration_us,
        "speech_windows": [dict(item) for item in speech_windows],
        "mix_policy": dict(mix_policy),
    }


def _receipt_speech_windows(
    windows: Sequence[Mapping[str, Any]],
    *,
    policy: Mapping[str, float],
) -> list[dict[str, Any]]:
    return [
        {
            "event_id": item["event_id"],
            "start_us": item["start_us"],
            "end_us": item["end_us"],
            "local_start_us": item["local_start_us"],
            "local_end_us": item["local_end_us"],
            "fade_in_ms": policy["fade_in_ms"],
            "fade_out_ms": policy["fade_out_ms"],
        }
        for item in windows
    ]


def _duck_intervals(
    windows: Sequence[Mapping[str, Any]],
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for item in windows:
        start_us = int(item["local_start_us"])
        end_us = int(item["local_end_us"])
        if result and start_us <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end_us))
        else:
            result.append((start_us, end_us))
    return result


def _sample_index_at_or_after(time_us: int) -> int:
    return (int(time_us) * _SAMPLE_RATE + 999_999) // 1_000_000


def _duck_gain_expression(
    windows: Sequence[Mapping[str, Any]],
    *,
    policy: Mapping[str, Any],
) -> str:
    canonical_policy = _policy(policy)
    duck_linear = 10 ** (canonical_policy["duck_gain_db"] / 20.0)
    active_sum = "+".join(
        f"gte(n,{_sample_index_at_or_after(start_us)})*"
        f"lt(n,{_sample_index_at_or_after(end_us)})"
        for start_us, end_us in _duck_intervals(windows)
    )
    return f"if(gt({active_sum},0),{duck_linear:.9f},1)"


def _receipt_duck_curve(
    windows: Sequence[Mapping[str, Any]],
    *,
    policy: Mapping[str, float],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for start_us, end_us in _duck_intervals(windows):
        if not result and start_us > 0:
            result.append({"time_us": 0, "gain_db": 0.0})
        result.extend(
            [
                {"time_us": start_us, "gain_db": policy["duck_gain_db"]},
                {"time_us": end_us, "gain_db": 0.0},
            ]
        )
    return result


def _required_sha(value: Any, field: str) -> str:
    digest = str(value or "").lower()
    if not _SHA256.fullmatch(digest):
        raise AudioMixerError(f"audio mixer receipt {field} is invalid")
    return digest


def _wav_duration_us(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as handle:
            if handle.getframerate() != _SAMPLE_RATE or handle.getnchannels() != _CHANNELS:
                raise AudioMixerError("decoded PCM WAV format is invalid")
            return round(handle.getnframes() * 1_000_000 / handle.getframerate())
    except (EOFError, wave.Error) as exc:
        raise AudioMixerError("decoded PCM WAV bytes are invalid") from exc


def validate_evidence_bound_mix_receipt_media(
    *,
    receipt: Mapping[str, Any],
    source_media: Path,
    opaque_media: Path,
    mixed_media: Path,
    active_window: Any,
    region_id: str,
    source_start_us: int,
    source_end_us: int,
    frozen_speech_windows: Sequence[Mapping[str, Any]],
    mix_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Recompute receipt media/WAV/request evidence from current verified bytes."""

    source_media = Path(source_media).resolve()
    opaque_media = Path(opaque_media).resolve()
    mixed_media = Path(mixed_media).resolve()
    for path, label in (
        (source_media, "source"),
        (opaque_media, "opaque"),
        (mixed_media, "mixed"),
    ):
        if not path.is_file():
            raise AudioMixerError(f"current verified {label} media is unavailable")
    active_start, _active_end, target_duration_us = _active_bounds(active_window)
    target_duration = target_duration_us / 1_000_000.0
    source_duration = (source_end_us - source_start_us) / 1_000_000.0
    policy = _policy(mix_policy)
    windows = _speech_windows(
        frozen_speech_windows,
        region_start_us=source_start_us,
        region_end_us=source_end_us,
        target_duration_us=target_duration_us,
        policy=policy,
    )
    speech_receipt = _receipt_speech_windows(windows, policy=policy)
    with tempfile.TemporaryDirectory(prefix="verify-evidence-audio-mix-") as tmp:
        work = Path(tmp)
        source_wav = work / "source.wav"
        opaque_wav = work / "opaque.wav"
        output_wav = work / "output.wav"
        _decode_wav(
            source_media,
            source_wav,
            start=source_start_us / 1_000_000.0,
            duration=source_duration,
            label="publication source interval decode",
        )
        _decode_wav(
            opaque_media,
            opaque_wav,
            start=active_start,
            duration=target_duration,
            label="publication opaque active decode",
        )
        _decode_wav(
            mixed_media,
            output_wav,
            start=0.0,
            duration=target_duration,
            label="publication mixed carrier decode",
        )
        for wav_path, label in (
            (opaque_wav, "opaque"),
            (output_wav, "output"),
        ):
            if abs(_wav_duration_us(wav_path) - target_duration_us) > 5_000:
                raise AudioMixerError(
                    f"publication {label} PCM duration does not match active duration"
                )
        source_wav_sha256 = _sha256_file(source_wav)
        opaque_wav_sha256 = _sha256_file(opaque_wav)
        output_wav_sha256 = _sha256_file(output_wav)

    source_media_sha256 = _sha256_file(source_media)
    opaque_media_sha256 = _sha256_file(opaque_media)
    mixed_region_sha256 = _sha256_file(mixed_media)
    request_sha256 = _canonical_sha256(
        _request_payload(
            region_id=region_id,
            source_media_sha256=source_media_sha256,
            opaque_media_sha256=opaque_media_sha256,
            source_wav_sha256=source_wav_sha256,
            opaque_wav_sha256=opaque_wav_sha256,
            source_start_us=source_start_us,
            source_end_us=source_end_us,
            target_active_duration_us=target_duration_us,
            speech_windows=speech_receipt,
            mix_policy=policy,
        )
    )
    derived = {
        "source_media_sha256": source_media_sha256,
        "opaque_media_sha256": opaque_media_sha256,
        "mixed_region_sha256": mixed_region_sha256,
        "source_wav_sha256": source_wav_sha256,
        "opaque_wav_sha256": opaque_wav_sha256,
        "output_wav_sha256": output_wav_sha256,
        "request_sha256": request_sha256,
        "target_active_duration_us": target_duration_us,
        "speech_windows": speech_receipt,
        "mix_policy": policy,
        "duck_curve": _receipt_duck_curve(windows, policy=policy),
    }
    for field in (
        "source_media_sha256",
        "opaque_media_sha256",
        "mixed_region_sha256",
        "source_wav_sha256",
        "opaque_wav_sha256",
        "output_wav_sha256",
        "request_sha256",
    ):
        if str(receipt.get(field) or "").lower() != derived[field]:
            if field.endswith("wav_sha256") or field == "request_sha256":
                raise AudioMixerError(
                    "decoded PCM SHA-256 or canonical request does not match current media"
                )
            raise AudioMixerError(f"receipt {field} does not match current media")
    return derived


def validate_evidence_bound_mix_receipts(
    *,
    receipts: Any,
    regions: Sequence[Mapping[str, Any]],
    audio_route_guard: Mapping[str, Any],
    placements: Any,
    source_media_sha256: str,
    final_output_sha256: str,
    expected_mixer_identity: Mapping[str, Any] | None = None,
    expected_mixer_identity_by_region: Mapping[
        str, Mapping[str, Any]
    ] | None = None,
) -> list[dict[str, Any]]:
    """Validate renderer-produced receipts against current frozen media bindings."""

    expected_regions: dict[str, dict[str, Any]] = {}
    for raw in regions:
        metadata = raw.get("metadata")
        region = (
            {**dict(metadata), **dict(raw)}
            if isinstance(metadata, Mapping)
            else dict(raw)
        )
        if str(region.get("audio_policy") or "").strip().lower() != "evidence_bound_mix":
            continue
        region_id = str(region.get("region_id") or "").strip()
        if not region_id or region_id in expected_regions:
            raise AudioMixerError("evidence-bound mix region coverage is invalid")
        expected_regions[region_id] = region
    if not isinstance(receipts, list) or len(receipts) != len(expected_regions):
        raise AudioMixerError("audio mixer receipt coverage is incomplete")
    typed_receipts = [dict(item) for item in receipts if isinstance(item, Mapping)]
    if len(typed_receipts) != len(receipts):
        raise AudioMixerError("audio mixer receipt is invalid")
    for receipt in typed_receipts:
        unknown_fields = set(receipt) - _RECEIPT_FIELDS
        if unknown_fields:
            raise AudioMixerError("audio mixer receipt contains unknown fields")
    receipt_by_id = {
        str(item.get("region_id") or ""): item for item in typed_receipts
    }
    if set(receipt_by_id) != set(expected_regions) or len(receipt_by_id) != len(
        typed_receipts
    ):
        raise AudioMixerError("audio mixer receipt coverage does not match mix regions")

    guard_rows = audio_route_guard.get("regions")
    if not isinstance(guard_rows, list):
        raise AudioMixerError("audio route guard is missing mixer coverage")
    guard_by_id = {
        str(item.get("region_id") or ""): item
        for item in guard_rows
        if isinstance(item, Mapping)
    }
    if not isinstance(placements, list):
        raise AudioMixerError("timeline manifest is missing placement coverage")
    placement_by_id = {
        str(item.get("region_id") or ""): item
        for item in placements
        if isinstance(item, Mapping)
    }
    source_sha = _required_sha(source_media_sha256, "source_media_sha256")
    final_sha = _required_sha(final_output_sha256, "final_output_sha256")
    validated: list[dict[str, Any]] = []
    for region_id, region in expected_regions.items():
        receipt = receipt_by_id[region_id]
        if receipt.get("schema_version") != _SCHEMA_VERSION:
            raise AudioMixerError("audio mixer receipt schema_version is invalid")
        identity = receipt.get("capability_identity")
        if not isinstance(identity, Mapping):
            raise AudioMixerError("audio mixer receipt capability identity is missing")
        if (
            identity.get("capability_kind") != "audio_mixer"
            or identity.get("audio_policy") != "evidence_bound_mix"
            or not str(identity.get("implementation") or "").strip()
            or not str(identity.get("version") or "").strip()
            or not _SHA256.fullmatch(str(identity.get("sha256") or ""))
        ):
            raise AudioMixerError("audio mixer receipt capability identity is invalid")
        region_expected_identity = expected_mixer_identity
        if expected_mixer_identity_by_region is not None:
            region_expected_identity = expected_mixer_identity_by_region.get(region_id)
        if region_expected_identity is not None and dict(identity) != dict(
            region_expected_identity
        ):
            raise AudioMixerError("audio mixer receipt capability identity is stale")
        for field in (
            "source_wav_sha256",
            "opaque_wav_sha256",
            "request_sha256",
            "output_wav_sha256",
            "source_media_sha256",
            "opaque_media_sha256",
            "mixed_region_sha256",
            "final_output_sha256",
        ):
            _required_sha(receipt.get(field), field)
        if receipt["output_wav_sha256"] in {
            receipt["source_wav_sha256"],
            receipt["opaque_wav_sha256"],
        }:
            raise AudioMixerError(
                "audio mixer receipt output PCM does not evidence a real mix"
            )
        if receipt["source_media_sha256"] != source_sha:
            raise AudioMixerError("audio mixer receipt binds the wrong source media")
        if receipt["final_output_sha256"] != final_sha:
            raise AudioMixerError("audio mixer receipt binds a stale final output")
        declared_opaque_sha = str(
            region.get("media_sha256")
            or region.get("media_artifact_sha256")
            or region.get("artifact_sha256")
            or ""
        ).lower()
        if declared_opaque_sha and (
            not _SHA256.fullmatch(declared_opaque_sha)
            or receipt["opaque_media_sha256"] != declared_opaque_sha
        ):
            raise AudioMixerError("audio mixer receipt binds the wrong opaque media")
        try:
            source_start_us = int(region.get("source_start_us"))
            source_end_us = int(region.get("source_end_us"))
        except (TypeError, ValueError) as exc:
            raise AudioMixerError("evidence-bound mix region bounds are invalid") from exc
        try:
            receipt_source_start_us = int(receipt.get("source_start_us", -1))
            receipt_source_end_us = int(receipt.get("source_end_us", -1))
        except (TypeError, ValueError) as exc:
            raise AudioMixerError("audio mixer receipt region bounds are invalid") from exc
        if (
            receipt_source_start_us != source_start_us
            or receipt_source_end_us != source_end_us
        ):
            raise AudioMixerError("audio mixer receipt binds the wrong region")
        if (
            type(receipt.get("sample_rate")) is not int
            or type(receipt.get("channels")) is not int
            or receipt.get("sample_rate") != _SAMPLE_RATE
            or receipt.get("channels") != _CHANNELS
        ):
            raise AudioMixerError("audio mixer receipt PCM format is invalid")
        target_duration_us = receipt.get("target_active_duration_us")
        if type(target_duration_us) is not int or target_duration_us <= 0:
            raise AudioMixerError("audio mixer receipt target duration is invalid")
        policy = _policy(
            receipt.get("mix_policy")
            if isinstance(receipt.get("mix_policy"), Mapping)
            else None
        )
        if receipt.get("mix_policy") != policy:
            raise AudioMixerError("audio mixer receipt policy is not canonical")
        speech = receipt.get("speech_windows")
        if not isinstance(speech, list) or not speech:
            raise AudioMixerError("audio mixer receipt speech windows are missing")
        guard = guard_by_id.get(region_id)
        guarded_speech = guard.get("speech_windows") if isinstance(guard, Mapping) else None
        if not isinstance(guarded_speech, list):
            raise AudioMixerError("audio mixer receipt lacks frozen guard speech windows")
        observed_guard_binding = [
            {
                "event_id": str(item.get("event_id") or ""),
                "start_us": item.get("start_us"),
                "end_us": item.get("end_us"),
            }
            for item in speech
            if isinstance(item, Mapping)
        ]
        expected_guard_binding = [
            {
                "event_id": str(item.get("event_id") or ""),
                "start_us": item.get("start_us"),
                "end_us": item.get("end_us"),
            }
            for item in guarded_speech
            if isinstance(item, Mapping)
        ]
        if observed_guard_binding != expected_guard_binding:
            raise AudioMixerError("audio mixer receipt speech windows are stale or forged")
        for item in speech:
            if not isinstance(item, Mapping):
                raise AudioMixerError("audio mixer receipt speech window is invalid")
            try:
                start_us = int(item.get("start_us"))
                end_us = int(item.get("end_us"))
                local_start_us = int(item.get("local_start_us"))
                local_end_us = int(item.get("local_end_us"))
                fade_in_ms = float(item.get("fade_in_ms"))
                fade_out_ms = float(item.get("fade_out_ms"))
            except (TypeError, ValueError) as exc:
                raise AudioMixerError(
                    "audio mixer receipt speech window is invalid"
                ) from exc
            if (
                local_start_us != start_us - source_start_us
                or local_end_us != end_us - source_start_us
                or local_start_us < 0
                or local_end_us <= local_start_us
                or local_end_us > target_duration_us
                or fade_in_ms != policy["fade_in_ms"]
                or fade_out_ms != policy["fade_out_ms"]
            ):
                raise AudioMixerError(
                    "audio mixer receipt speech timing is stale or forged"
                )
        expected_duck_curve = _receipt_duck_curve(speech, policy=policy)
        if receipt.get("duck_curve") != expected_duck_curve:
            raise AudioMixerError("audio mixer receipt duck curve is stale or forged")
        request = _request_payload(
            region_id=region_id,
            source_media_sha256=receipt["source_media_sha256"],
            opaque_media_sha256=receipt["opaque_media_sha256"],
            source_wav_sha256=receipt["source_wav_sha256"],
            opaque_wav_sha256=receipt["opaque_wav_sha256"],
            source_start_us=source_start_us,
            source_end_us=source_end_us,
            target_active_duration_us=target_duration_us,
            speech_windows=speech,
            mix_policy=policy,
        )
        if receipt["request_sha256"] != _canonical_sha256(request):
            raise AudioMixerError("audio mixer receipt request SHA-256 is forged")
        placement = placement_by_id.get(region_id)
        active_audit = None
        if isinstance(placement, Mapping):
            active_audit = placement.get("ui_media_audit") or placement.get(
                "tail_media_audit"
            )
        try:
            placement_active_duration_us = round(
                float(active_audit.get("active_duration")) * 1_000_000
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise AudioMixerError(
                "mixed region placement is missing its active-window audit"
            ) from exc
        if placement_active_duration_us != target_duration_us:
            raise AudioMixerError(
                "audio mixer receipt target duration does not match active-window authority"
            )
        carrier_receipts = (
            placement.get("carrier_receipts")
            if isinstance(placement, Mapping)
            else None
        )
        if not isinstance(carrier_receipts, list) or len(carrier_receipts) != 1:
            raise AudioMixerError("mixed region carrier receipt coverage is invalid")
        carrier = carrier_receipts[0]
        if not isinstance(carrier, Mapping) or any(
            str(carrier.get(field) or "").lower()
            != receipt["mixed_region_sha256"]
            for field in ("media_sha256", "carrier_sha256")
        ):
            raise AudioMixerError("audio mixer receipt does not bind mixed region bytes")
        if str(carrier.get("final_output_sha256") or "").lower() != final_sha:
            raise AudioMixerError("mixed region carrier does not bind the final output")
        validated.append(receipt)
    return validated


def _decode_wav(
    media: Path,
    destination: Path,
    *,
    start: float,
    duration: float,
    label: str,
) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(media),
            "-vn",
            "-af",
            (
                f"atrim=start={start:.6f}:end={start + duration:.6f},"
                "asetpts=PTS-STARTPTS,aresample=48000,"
                "aformat=sample_fmts=s16:channel_layouts=stereo"
            ),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        label=label,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise AudioMixerError(f"{label} produced no PCM WAV bytes")


class EvidenceBoundAudioMixer:
    """Small bundled FFmpeg mixer with an immutable capability identity."""

    capability_kind = "audio_mixer"
    supports_evidence_bound_mix = True

    def __init__(
        self,
        *,
        production: bool = False,
        implementation: str = "server.audio_mixer:EvidenceBoundAudioMixer",
        version: str = "1.0.0",
        sha256: str | None = None,
    ) -> None:
        self.production = bool(production)
        self.implementation = implementation
        self.version = version
        digest = str(sha256 or "").lower()
        if self.production and not _SHA256.fullmatch(digest):
            raise ValueError("production audio mixer requires an explicit SHA-256")
        self.sha256 = digest or hashlib.sha256(
            f"{implementation}:{version}".encode("utf-8")
        ).hexdigest()

    def capability_identity(self) -> dict[str, Any]:
        return {
            "capability_kind": self.capability_kind,
            "implementation": self.implementation,
            "version": self.version,
            "sha256": self.sha256,
            "audio_policy": "evidence_bound_mix",
        }

    def mix_region(
        self,
        *,
        source_media: Path,
        opaque_media: Path,
        output_path: Path,
        region_id: str,
        source_start_us: int,
        source_end_us: int,
        speech_windows: Sequence[Mapping[str, Any]],
        mix_policy: Mapping[str, Any] | None,
        active_window: Any,
        source_media_sha256: str | None,
        opaque_media_sha256: str | None,
    ) -> dict[str, Any]:
        source_media = Path(source_media).resolve()
        opaque_media = Path(opaque_media).resolve()
        output_path = Path(output_path).resolve()
        if not source_media.is_file() or not opaque_media.is_file():
            raise AudioMixerError("evidence-bound mix media is unavailable")
        if not str(region_id).strip():
            raise AudioMixerError("evidence-bound mix region_id is required")
        if source_start_us < 0 or source_end_us <= source_start_us:
            raise AudioMixerError("evidence-bound mix source bounds are invalid")

        source_probe = _probe(source_media)
        opaque_probe = _probe(opaque_media)
        if "audio" not in _stream_types(source_probe):
            raise AudioMixerError("verified source media has no audio stream")
        if "video" not in _stream_types(opaque_probe) or "audio" not in _stream_types(
            opaque_probe
        ):
            raise AudioMixerError("opaque target media requires audio and video streams")

        source_sha = _declared_media_sha(
            source_media,
            source_media_sha256,
            label="source media",
            production=self.production,
        )
        opaque_sha = _declared_media_sha(
            opaque_media,
            opaque_media_sha256,
            label="opaque media",
            production=self.production,
        )
        active_start, active_end, target_duration_us = _active_bounds(active_window)
        target_duration = target_duration_us / 1_000_000.0
        source_duration = (source_end_us - source_start_us) / 1_000_000.0
        canonical_policy = _policy(mix_policy)
        canonical_windows = _speech_windows(
            speech_windows,
            region_start_us=source_start_us,
            region_end_us=source_end_us,
            target_duration_us=target_duration_us,
            policy=canonical_policy,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="evidence-audio-mix-", dir=str(output_path.parent)
        ) as tmp:
            work = Path(tmp)
            source_wav = work / "source-interval.wav"
            opaque_wav = work / "opaque-active.wav"
            mixed_wav = work / "mixed.wav"
            output_wav = work / "output-decoded.wav"
            _decode_wav(
                source_media,
                source_wav,
                start=source_start_us / 1_000_000.0,
                duration=source_duration,
                label="source interval extraction",
            )
            _decode_wav(
                opaque_media,
                opaque_wav,
                start=active_start,
                duration=target_duration,
                label="opaque active audio extraction",
            )
            source_wav_duration_us = _wav_duration_us(source_wav)
            opaque_wav_duration_us = _wav_duration_us(opaque_wav)
            if source_wav_duration_us + 5_000 < max(
                item["local_end_us"] for item in canonical_windows
            ):
                raise AudioMixerError(
                    "verified source audio does not contain every frozen speech window"
                )
            if abs(opaque_wav_duration_us - target_duration_us) > 5_000:
                raise AudioMixerError(
                    "opaque target audio does not cover its full active duration"
                )
            source_wav_sha = _sha256_file(source_wav)
            opaque_wav_sha = _sha256_file(opaque_wav)

            source_linear = 10 ** (canonical_policy["source_gain_db"] / 20.0)
            limiter_linear = 10 ** (
                canonical_policy["limiter_true_peak_db"] / 20.0
            )
            duck_expression = _duck_gain_expression(
                canonical_windows,
                policy=canonical_policy,
            )
            mix_command = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(opaque_wav),
            ]
            for _window in canonical_windows:
                mix_command.extend(["-i", str(source_wav)])
            filters = [
                "[0:a]aresample=48000,aformat=sample_fmts=fltp:"
                "channel_layouts=stereo,"
                f"aeval='val(0)*{duck_expression}|val(1)*{duck_expression}':"
                "c=same[opaque]"
            ]
            labels = ["[opaque]"]
            for index, item in enumerate(canonical_windows, start=1):
                local_start = item["local_start_us"] / 1_000_000.0
                local_end = item["local_end_us"] / 1_000_000.0
                fade_in = canonical_policy["fade_in_ms"] / 1000.0
                fade_out = canonical_policy["fade_out_ms"] / 1000.0
                fade_out_start = local_end - fade_out
                local_start_sample = _sample_index_at_or_after(
                    item["local_start_us"]
                )
                local_end_sample = _sample_index_at_or_after(item["local_end_us"])
                label = f"speech{index}"
                filters.append(
                    f"[{index}:a]aresample=48000,"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"aeval='val(0)*if(gte(n,{local_start_sample})*"
                    f"lt(n,{local_end_sample}),{source_linear:.9f},0)|"
                    f"val(1)*if(gte(n,{local_start_sample})*"
                    f"lt(n,{local_end_sample}),{source_linear:.9f},0)':c=same,"
                    f"afade=t=in:st={local_start:.6f}:d={fade_in:.6f},"
                    f"afade=t=out:st={fade_out_start:.6f}:d={fade_out:.6f},"
                    f"atrim=duration={target_duration:.6f}[{label}]"
                )
                labels.append(f"[{label}]")
            filters.append(
                f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:"
                "dropout_transition=0:normalize=0,"
                "aresample=192000,"
                f"alimiter=limit={limiter_linear:.9f}:attack=5:release=50:"
                "level=false:latency=true,aresample=48000:first_pts=0,"
                f"atrim=duration={target_duration:.6f}[mixed]"
            )
            mix_command.extend(
                [
                    "-filter_complex",
                    ";".join(filters),
                    "-map",
                    "[mixed]",
                    "-ar",
                    str(_SAMPLE_RATE),
                    "-ac",
                    str(_CHANNELS),
                    "-c:a",
                    "pcm_s16le",
                    str(mixed_wav),
                ]
            )
            _run(mix_command, label="evidence-bound audio mix")

            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(opaque_media),
                    "-i",
                    str(mixed_wav),
                    "-filter_complex",
                    f"[0:v]trim=start={active_start:.6f}:end={active_end:.6f},"
                    "setpts=PTS-STARTPTS[v]",
                    "-map",
                    "[v]",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-ar",
                    str(_SAMPLE_RATE),
                    "-ac",
                    str(_CHANNELS),
                    "-t",
                    f"{target_duration:.6f}",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ],
                label="mixed region assembly",
            )
            output_probe = _probe(output_path)
            if _stream_types(output_probe) != {"audio", "video"}:
                raise AudioMixerError("mixed region does not contain complete audio/video streams")
            _decode_wav(
                output_path,
                output_wav,
                start=0.0,
                duration=target_duration,
                label="mixed output PCM decode",
            )
            if abs(_wav_duration_us(output_wav) - target_duration_us) > 5_000:
                raise AudioMixerError(
                    "mixed output audio does not preserve target active duration"
                )
            output_wav_sha = _sha256_file(output_wav)

        speech_receipt = _receipt_speech_windows(
            canonical_windows,
            policy=canonical_policy,
        )
        request = _request_payload(
            region_id=str(region_id),
            source_media_sha256=source_sha,
            opaque_media_sha256=opaque_sha,
            source_wav_sha256=source_wav_sha,
            opaque_wav_sha256=opaque_wav_sha,
            source_start_us=source_start_us,
            source_end_us=source_end_us,
            target_active_duration_us=target_duration_us,
            speech_windows=speech_receipt,
            mix_policy=canonical_policy,
        )
        duck_curve = _receipt_duck_curve(
            canonical_windows,
            policy=canonical_policy,
        )
        return {
            "schema_version": _SCHEMA_VERSION,
            "region_id": str(region_id),
            "source_wav_sha256": source_wav_sha,
            "opaque_wav_sha256": opaque_wav_sha,
            "request_sha256": _canonical_sha256(request),
            "output_wav_sha256": output_wav_sha,
            "source_media_sha256": source_sha,
            "opaque_media_sha256": opaque_sha,
            "mixed_region_sha256": _sha256_file(output_path),
            "final_output_sha256": "",
            "duck_curve": duck_curve,
            "speech_windows": speech_receipt,
            "sample_rate": _SAMPLE_RATE,
            "channels": _CHANNELS,
            "source_start_us": source_start_us,
            "source_end_us": source_end_us,
            "target_active_duration_us": target_duration_us,
            "mix_policy": canonical_policy,
            "capability_identity": self.capability_identity(),
        }


class SourceAudioPerformanceAssembler:
    """Deterministically refill generated visuals from source-global audio.

    This is intentionally a postproduction-only carrier.  It consumes neither
    a Provider audio reference nor opaque UI/tail contents beyond their
    immutable media files.  Generated media audio is discarded; each generated
    region receives one exact source window, while opaque media keeps only its
    own original audio.
    """

    _FORBIDDEN_OPERATIONS = (
        "atempo",
        "loop",
        "stretch",
        "freeze",
        "black_padding",
        "audio_padding",
    )

    def __init__(self, *, production: bool = False) -> None:
        self.production = bool(production)

    @staticmethod
    def _duration_us(probe: Mapping[str, Any], *, label: str) -> int:
        raw = (probe.get("format") or {}).get("duration") if isinstance(probe.get("format"), Mapping) else None
        try:
            value = int(round(float(raw) * 1_000_000))
        except (TypeError, ValueError) as exc:
            raise AudioMixerError(f"{label} duration is unavailable") from exc
        if value <= 0:
            raise AudioMixerError(f"{label} duration is invalid")
        return value

    @staticmethod
    def _source_window(region: Mapping[str, Any]) -> tuple[int, int]:
        try:
            start = int(region.get("source_start_us"))
            end = int(region.get("source_end_us"))
        except (TypeError, ValueError) as exc:
            raise AudioMixerError("source-master region requires source bounds") from exc
        if start < 0 or end <= start:
            raise AudioMixerError("source-master region has invalid source bounds")
        return start, end

    def assemble(
        self,
        *,
        source_media: Path,
        output_path: Path,
        source_media_sha256: str | None,
        regions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        source_media = Path(source_media).resolve()
        output_path = Path(output_path).resolve()
        if not source_media.is_file():
            raise AudioMixerError("source performance media is unavailable")
        if not isinstance(regions, Sequence) or isinstance(regions, (str, bytes, bytearray)) or not regions:
            raise AudioMixerError("source performance assembly requires timeline regions")
        source_probe = _probe(source_media)
        if "audio" not in _stream_types(source_probe):
            raise AudioMixerError("source performance media has no audio stream")
        source_duration_us = self._duration_us(source_probe, label="source performance media")
        source_sha = _declared_media_sha(
            source_media,
            source_media_sha256,
            label="source performance media",
            production=self.production,
        )
        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(regions, start=1):
            if not isinstance(raw, Mapping):
                raise AudioMixerError("source performance timeline regions must be objects")
            region_id = str(raw.get("region_id") or "").strip()
            if not region_id or region_id in seen_ids:
                raise AudioMixerError("source performance region IDs must be unique and non-empty")
            seen_ids.add(region_id)
            mode = str(raw.get("audio_mode") or "").strip()
            if mode not in {"source_master", "opaque_audio_keep"}:
                raise AudioMixerError("source performance region has unsupported audio mode")
            media = Path(raw.get("media") or "").resolve()
            if not media.is_file():
                raise AudioMixerError(f"source performance region {region_id} media is unavailable")
            probe = _probe(media)
            types = _stream_types(probe)
            if "video" not in types:
                raise AudioMixerError(f"source performance region {region_id} requires video")
            if mode == "opaque_audio_keep" and "audio" not in types:
                raise AudioMixerError(f"opaque source performance region {region_id} requires audio")
            media_duration_us = self._duration_us(probe, label=f"source performance region {region_id}")
            row: dict[str, Any] = {
                "region_id": region_id,
                "audio_mode": mode,
                "media": media,
                "media_sha256": _sha256_file(media),
                "media_duration_us": media_duration_us,
            }
            if mode == "source_master":
                start, end = self._source_window(raw)
                if end > source_duration_us:
                    raise AudioMixerError(f"source performance region {region_id} exceeds source audio duration")
                target_duration_us = end - start
                if media_duration_us + 5_000 < target_duration_us:
                    raise AudioMixerError(f"generated source performance region {region_id} is shorter than its source-audio window")
                row.update({"source_start_us": start, "source_end_us": end, "target_duration_us": target_duration_us})
            else:
                row["target_duration_us"] = media_duration_us
            normalized.append(row)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="source-audio-performance-", dir=str(output_path.parent)) as tmp:
            work = Path(tmp)
            source_wav = work / "source-performance.wav"
            output_wav = work / "output-performance.wav"
            _decode_wav(
                source_media,
                source_wav,
                start=0.0,
                duration=source_duration_us / 1_000_000.0,
                label="source performance master decode",
            )
            filters: list[str] = []
            concat_inputs: list[str] = []
            command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source_media)]
            for item in normalized:
                command.extend(["-i", str(item["media"])])
            for index, item in enumerate(normalized, start=1):
                duration = int(item["target_duration_us"]) / 1_000_000.0
                filters.append(
                    f"[{index}:v]trim=duration={duration:.6f},setpts=PTS-STARTPTS[v{index}]"
                )
                if item["audio_mode"] == "source_master":
                    start = int(item["source_start_us"]) / 1_000_000.0
                    end = int(item["source_end_us"]) / 1_000_000.0
                    filters.append(
                        f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,"
                        f"aresample={_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
                    )
                else:
                    filters.append(
                        f"[{index}:a]atrim=duration={duration:.6f},asetpts=PTS-STARTPTS,"
                        f"aresample={_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
                    )
                concat_inputs.extend((f"[v{index}]", f"[a{index}]"))
            filters.append(
                f"{''.join(concat_inputs)}concat=n={len(normalized)}:v=1:a=1[vout][aout]"
            )
            command.extend(
                [
                    "-filter_complex", ";".join(filters),
                    "-map", "[vout]", "-map", "[aout]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", str(_SAMPLE_RATE), "-ac", str(_CHANNELS),
                    "-movflags", "+faststart", str(output_path),
                ]
            )
            _run(command, label="source performance timeline assembly")
            output_probe = _probe(output_path)
            if _stream_types(output_probe) != {"audio", "video"}:
                raise AudioMixerError("source performance output does not contain complete audio/video streams")
            _decode_wav(
                output_path,
                output_wav,
                start=0.0,
                duration=sum(int(item["target_duration_us"]) for item in normalized) / 1_000_000.0,
                label="source performance output decode",
            )
            output_duration_us = self._duration_us(output_probe, label="source performance output")
            expected_duration_us = sum(int(item["target_duration_us"]) for item in normalized)
            if abs(output_duration_us - expected_duration_us) > 50_000:
                raise AudioMixerError("source performance output duration drift exceeds 50ms")
            output_wav_sha = _sha256_file(output_wav)
            source_wav_sha = _sha256_file(source_wav)

        receipt_regions = [
            {
                key: value
                for key, value in item.items()
                if key not in {"media"}
            }
            for item in normalized
        ]
        receipt_payload = {
            "schema_version": "source-audio-performance-assembly/v1",
            "source_media_sha256": source_sha,
            "source_wav_sha256": source_wav_sha,
            "regions": receipt_regions,
            "forbidden_operations": list(self._FORBIDDEN_OPERATIONS),
        }
        return {
            **receipt_payload,
            "request_sha256": _canonical_sha256(receipt_payload),
            "output_wav_sha256": output_wav_sha,
            "final_output_sha256": _sha256_file(output_path),
            "output_duration_us": output_duration_us,
        }

    @staticmethod
    def _placement_window(
        placement: Mapping[str, Any], *, region_id: str) -> tuple[int, int]:
        try:
            start = int(round(float(placement.get("output_start")) * 1_000_000))
            end = int(round(float(placement.get("output_end")) * 1_000_000))
        except (TypeError, ValueError) as exc:
            raise AudioMixerError(
                f"source performance placement {region_id} requires output bounds"
            ) from exc
        if start < 0 or end <= start:
            raise AudioMixerError(
                f"source performance placement {region_id} has invalid output bounds"
            )
        return start, end

    @staticmethod
    def _opaque_active_window(
        placement: Mapping[str, Any], *, media_duration_us: int, region_id: str) -> tuple[int, int]:
        audit = placement.get("ui_media_audit")
        if not isinstance(audit, Mapping):
            audit = placement.get("tail_media_audit")
        values = audit if isinstance(audit, Mapping) else placement
        try:
            start = int(round(float(values.get("active_start", values.get("audio_active_start", 0))) * 1_000_000))
            end_value = values.get("active_end", values.get("audio_active_end"))
            end = (
                int(round(float(end_value) * 1_000_000))
                if end_value is not None
                else media_duration_us
            )
        except (TypeError, ValueError) as exc:
            raise AudioMixerError(
                f"opaque source performance region {region_id} has invalid active audio bounds"
            ) from exc
        if start < 0 or end <= start or end > media_duration_us:
            raise AudioMixerError(
                f"opaque source performance region {region_id} active audio bounds are invalid"
            )
        return start, end

    @staticmethod
    def _asr_source_audio_sha256(source_media: Path, *, work_dir: Path) -> str:
        """Recreate the Stage-3 mono PCM extraction used to bind ASR evidence."""

        wav = work_dir / "source-audio-contract.wav"
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source_media),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            label="source performance contract audio extraction",
        )
        if not wav.is_file() or wav.stat().st_size == 0:
            raise AudioMixerError("source performance contract audio extraction produced no bytes")
        return _sha256_file(wav)

    def remux_rendered_timeline(
        self,
        *,
        source_media: Path,
        rendered_video: Path,
        output_path: Path,
        source_media_sha256: str | None,
        regions: Sequence[Mapping[str, Any]],
        placements: Sequence[Mapping[str, Any]],
        source_audio_sha256: str | None = None,
        transition_receipts: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Replace only a rendered timeline's audio, leaving its visual bytes intact.

        The bundled timeline renderer has already rendered the source transition
        shell before this method is called.  This method therefore never joins
        or re-encodes visual segments: it maps the rendered video stream as-is
        and builds one deterministic audio carrier from source-global windows
        and opaque media's own audio.  Audio overlaps require an output-bound
        source-transition receipt; unreceipted overlaps are rejected rather
        than silently mixing, looping, or time-warping either carrier.
        """

        source_media = Path(source_media).resolve()
        rendered_video = Path(rendered_video).resolve()
        output_path = Path(output_path).resolve()
        if not source_media.is_file() or not rendered_video.is_file():
            raise AudioMixerError("source performance remux media is unavailable")
        if not isinstance(regions, Sequence) or isinstance(regions, (str, bytes, bytearray)):
            raise AudioMixerError("source performance remux requires timeline regions")
        if not isinstance(placements, Sequence) or isinstance(placements, (str, bytes, bytearray)):
            raise AudioMixerError("source performance remux requires timeline placements")
        if not isinstance(transition_receipts, Sequence) or isinstance(
            transition_receipts, (str, bytes, bytearray)
        ):
            raise AudioMixerError("source performance remux transition receipts are invalid")
        if not regions or not placements:
            raise AudioMixerError("source performance remux requires non-empty timeline coverage")

        source_probe = _probe(source_media)
        rendered_probe = _probe(rendered_video)
        if "audio" not in _stream_types(source_probe):
            raise AudioMixerError("source performance media has no audio stream")
        if "video" not in _stream_types(rendered_probe):
            raise AudioMixerError("rendered performance timeline has no video stream")
        source_duration_us = self._duration_us(source_probe, label="source performance media")
        rendered_duration_us = self._duration_us(rendered_probe, label="rendered performance timeline")
        rendered_visual_sha256 = _sha256_file(rendered_video)
        source_sha = _declared_media_sha(
            source_media,
            source_media_sha256,
            label="source performance media",
            production=self.production,
        )
        declared_source_audio_sha = str(source_audio_sha256 or "").strip().lower()
        if declared_source_audio_sha and not _SHA256.fullmatch(declared_source_audio_sha):
            raise AudioMixerError("source performance contract has an invalid source audio SHA-256")

        placement_by_id: dict[str, Mapping[str, Any]] = {}
        ordered_placements: list[tuple[int, int, Mapping[str, Any]]] = []
        for raw in placements:
            if not isinstance(raw, Mapping):
                raise AudioMixerError("source performance placements must be objects")
            region_id = str(raw.get("region_id") or "").strip()
            if not region_id or region_id in placement_by_id:
                raise AudioMixerError("source performance placement IDs must be unique and non-empty")
            start, end = self._placement_window(raw, region_id=region_id)
            placement_by_id[region_id] = raw
            ordered_placements.append((start, end, raw))
        ordered_placements.sort(key=lambda item: item[0])
        receipt_by_boundary: dict[int, Mapping[str, Any]] = {}
        for raw in transition_receipts:
            if not isinstance(raw, Mapping):
                raise AudioMixerError("source performance transition receipt is invalid")
            try:
                boundary_index = int(raw.get("boundary_index"))
            except (TypeError, ValueError) as exc:
                raise AudioMixerError("source performance transition receipt boundary is invalid") from exc
            if boundary_index in receipt_by_boundary:
                raise AudioMixerError("source performance transition receipts contain duplicate boundaries")
            receipt_by_boundary[boundary_index] = raw
        boundaries: list[dict[str, Any]] = []
        cursor = 0
        for index, (start, end, raw) in enumerate(ordered_placements):
            if start > cursor + 5_000:
                raise AudioMixerError(
                    "source performance remux placements contain an audio gap"
                )
            overlap_us = max(0, cursor - start)
            if overlap_us > 5_000:
                if index == 0 or end <= cursor:
                    raise AudioMixerError("source performance remux has an unsupported nested audio overlap")
                receipt = receipt_by_boundary.get(index - 1)
                if not isinstance(receipt, Mapping):
                    raise AudioMixerError(
                        "source performance remux overlap has no approved transition audio receipt"
                    )
                if receipt.get("rendered") is not True or receipt.get("audio_rendered") is not True:
                    raise AudioMixerError("source performance remux overlap transition receipt is not rendered")
                if not _SHA256.fullmatch(str(receipt.get("source_shell_sha256") or "").lower()):
                    raise AudioMixerError("source performance remux overlap receipt has no source-shell evidence")
                transition = str(receipt.get("audio_transition") or "").strip().lower()
                if transition not in {"crossfade", "preserve"}:
                    raise AudioMixerError("source performance remux overlap has an unsupported transition audio policy")
                try:
                    fade_us = int(round(float(receipt.get("audio_fade_duration")) * 1_000_000))
                except (TypeError, ValueError) as exc:
                    raise AudioMixerError("source performance remux overlap fade duration is invalid") from exc
                if transition == "crossfade" and not 0 < fade_us <= overlap_us:
                    raise AudioMixerError("source performance remux overlap fade is outside the visual overlap")
                if transition == "preserve" and fade_us != 0:
                    raise AudioMixerError("source performance remux preserve transition must not fade")
                boundaries.append(
                    {
                        "boundary_index": index - 1,
                        "left_region_id": str(ordered_placements[index - 1][2].get("region_id") or ""),
                        "right_region_id": str(raw.get("region_id") or ""),
                        "overlap_us": overlap_us,
                        "audio_transition": transition,
                        "audio_fade_duration_us": fade_us,
                        "source_shell_sha256": str(receipt["source_shell_sha256"]).lower(),
                    }
                )
            cursor = max(cursor, end)
        if abs(cursor - rendered_duration_us) > 50_000:
            raise AudioMixerError("source performance remux placement duration differs from rendered video")

        normalized: list[dict[str, Any]] = []
        seen_regions: set[str] = set()
        opaque_inputs: list[Path] = []
        for raw in regions:
            if not isinstance(raw, Mapping):
                raise AudioMixerError("source performance remux regions must be objects")
            region_id = str(raw.get("region_id") or "").strip()
            if not region_id or region_id in seen_regions:
                raise AudioMixerError("source performance remux region IDs must be unique and non-empty")
            seen_regions.add(region_id)
            placement = placement_by_id.get(region_id)
            if placement is None:
                raise AudioMixerError(f"source performance region {region_id} is missing a rendered placement")
            output_start_us, output_end_us = self._placement_window(placement, region_id=region_id)
            output_duration_us = output_end_us - output_start_us
            mode = str(raw.get("audio_mode") or "").strip()
            row: dict[str, Any] = {
                "region_id": region_id,
                "audio_mode": mode,
                "output_start_us": output_start_us,
                "output_end_us": output_end_us,
                "output_duration_us": output_duration_us,
            }
            if mode == "source_master":
                source_start_us, source_end_us = self._source_window(raw)
                if source_end_us > source_duration_us:
                    raise AudioMixerError(
                        f"source performance region {region_id} exceeds source audio duration"
                    )
                if abs((source_end_us - source_start_us) - output_duration_us) > 20_000:
                    raise AudioMixerError(
                        f"source performance region {region_id} would require audio stretching or padding"
                    )
                row.update(
                    {
                        "source_start_us": source_start_us,
                        "source_end_us": source_end_us,
                    }
                )
            elif mode == "opaque_audio_keep":
                media_value = raw.get("media") or raw.get("media_path")
                media = Path(str(media_value or "")).resolve()
                if not media.is_file():
                    raise AudioMixerError(
                        f"opaque source performance region {region_id} media is unavailable"
                    )
                media_probe = _probe(media)
                if "audio" not in _stream_types(media_probe):
                    raise AudioMixerError(
                        f"opaque source performance region {region_id} requires audio"
                    )
                media_duration_us = self._duration_us(
                    media_probe,
                    label=f"opaque source performance region {region_id}",
                )
                active_start_us, active_end_us = self._opaque_active_window(
                    placement,
                    media_duration_us=media_duration_us,
                    region_id=region_id,
                )
                if abs((active_end_us - active_start_us) - output_duration_us) > 20_000:
                    raise AudioMixerError(
                        f"opaque source performance region {region_id} would require audio stretching or padding"
                    )
                opaque_inputs.append(media)
                row.update(
                    {
                        "opaque_media_sha256": _sha256_file(media),
                        "opaque_active_start_us": active_start_us,
                        "opaque_active_end_us": active_end_us,
                        "opaque_input_index": len(opaque_inputs) + 1,
                    }
                )
            else:
                raise AudioMixerError(
                    f"source performance region {region_id} has unsupported audio mode"
                )
            normalized.append(row)
        if set(placement_by_id) != seen_regions:
            raise AudioMixerError("source performance remux region coverage differs from rendered placements")
        normalized.sort(key=lambda item: int(item["output_start_us"]))
        boundary_by_left = {item["left_region_id"]: item for item in boundaries}
        boundary_by_right = {item["right_region_id"]: item for item in boundaries}

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_output = output_path.with_name(f".{output_path.stem}.source-audio-remux.mp4")
        if temporary_output.exists():
            temporary_output.unlink()
        command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source_media), "-i", str(rendered_video)]
        command.extend(item for media in opaque_inputs for item in ("-i", str(media)))
        filters: list[str] = []
        audio_inputs: list[str] = []
        for index, item in enumerate(normalized):
            local_end_us = int(item["output_duration_us"])
            fade_in_us = 0
            fade_out_us = 0
            if item["region_id"] in boundary_by_left:
                boundary = boundary_by_left[item["region_id"]]
                overlap_us = int(boundary["overlap_us"])
                fade_out_us = int(boundary["audio_fade_duration_us"])
                local_end_us = local_end_us - overlap_us + fade_out_us
            if item["region_id"] in boundary_by_right:
                fade_in_us = int(boundary_by_right[item["region_id"]]["audio_fade_duration_us"])
            if local_end_us <= 0:
                raise AudioMixerError("source performance transition leaves no audible carrier")
            item["audio_local_end_us"] = local_end_us
            item["audio_fade_in_us"] = fade_in_us
            item["audio_fade_out_us"] = fade_out_us
            if item["audio_mode"] == "source_master":
                filters.append(
                    f"[0:a]atrim=start={int(item['source_start_us']) / 1_000_000:.6f}:"
                    f"end={(int(item['source_start_us']) + local_end_us) / 1_000_000:.6f},asetpts=PTS-STARTPTS,"
                    f"aresample={_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
                )
            else:
                filters.append(
                    f"[{int(item['opaque_input_index'])}:a]atrim=start={int(item['opaque_active_start_us']) / 1_000_000:.6f}:"
                    f"end={(int(item['opaque_active_start_us']) + local_end_us) / 1_000_000:.6f},asetpts=PTS-STARTPTS,"
                    f"aresample={_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
                )
            current = f"a{index}"
            if fade_in_us:
                next_name = f"fadein{index}"
                filters.append(
                    f"[{current}]afade=t=in:st=0:d={fade_in_us / 1_000_000:.6f}[{next_name}]"
                )
                current = next_name
            if fade_out_us:
                next_name = f"fadeout{index}"
                filters.append(
                    f"[{current}]afade=t=out:st={(local_end_us - fade_out_us) / 1_000_000:.6f}:d={fade_out_us / 1_000_000:.6f}[{next_name}]"
                )
                current = next_name
            if boundaries:
                next_name = f"delay{index}"
                delay_ms = int(round(int(item["output_start_us"]) / 1_000))
                filters.append(f"[{current}]adelay={delay_ms}:all=1[{next_name}]")
                current = next_name
            audio_inputs.append(f"[{current}]")
        if boundaries:
            filters.append(
                f"{''.join(audio_inputs)}amix=inputs={len(normalized)}:normalize=0:dropout_transition=0[aout]"
            )
        else:
            filters.append(f"{''.join(audio_inputs)}concat=n={len(normalized)}:v=0:a=1[aout]")
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "1:v:0",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-ar",
                str(_SAMPLE_RATE),
                "-ac",
                str(_CHANNELS),
                "-movflags",
                "+faststart",
                "-shortest",
                str(temporary_output),
            ]
        )
        _run(command, label="source performance rendered-timeline audio remux")
        output_probe = _probe(temporary_output)
        if _stream_types(output_probe) != {"audio", "video"}:
            raise AudioMixerError("source performance remux output does not contain complete audio/video streams")
        output_duration_us = self._duration_us(output_probe, label="source performance remux output")
        if abs(output_duration_us - rendered_duration_us) > 50_000:
            raise AudioMixerError("source performance remux output duration drift exceeds 50ms")
        if declared_source_audio_sha:
            with tempfile.TemporaryDirectory(
                prefix="source-audio-contract-",
                dir=str(output_path.parent),
            ) as tmp:
                actual_source_audio_sha = self._asr_source_audio_sha256(
                    source_media,
                    work_dir=Path(tmp),
                )
            if actual_source_audio_sha != declared_source_audio_sha:
                raise AudioMixerError(
                    "source performance contract audio SHA-256 does not match the current source media"
                )
        os.replace(temporary_output, output_path)

        receipt_payload = {
            "schema_version": "source-audio-performance-remux/v1",
            "source_media_sha256": source_sha,
            "source_audio_sha256": declared_source_audio_sha,
            "rendered_visual_sha256": rendered_visual_sha256,
            "regions": normalized,
            "boundaries": boundaries,
            "forbidden_operations": list(self._FORBIDDEN_OPERATIONS),
        }
        return {
            **receipt_payload,
            "request_sha256": _canonical_sha256(receipt_payload),
            "final_output_sha256": _sha256_file(output_path),
            "output_duration_us": output_duration_us,
        }


__all__ = [
    "AudioMixerError",
    "EvidenceBoundAudioMixer",
    "SourceAudioPerformanceAssembler",
    "validate_evidence_bound_mix_receipt_media",
    "validate_evidence_bound_mix_receipts",
]
