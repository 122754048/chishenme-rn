"""Deployment-side routing for the optional USFR background-music extension.

This module deliberately leaves the packaged USFR Skill unchanged.  It only
selects existing operational stages when a deployment has installed a real
music execution adapter; StagePorts remain responsible for the actual audio
asset, prompt, mix, and QA evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
import json
import shutil
import subprocess
from typing import Any

from server.ephemeral_driver import EXECUTABLE_STAGES, _dedupe
from server.errors import ReplicationError
from server.job_models import WorkMessage
from server.orchestrator import build_stage_plan
from server.performance_audio_contracts import build_background_music_performance_contract


MUSIC_EXECUTION_CONTRACT = "background_music_execution/v1"
MUSIC_STAGE_PORTS = (
    "analyze_dynamics",
    "build_script",
    "generate_storyboards",
    "compile_seedance20_prompt",
    "audit_seedance_request",
    "submit_provider_video",
    "wait_provider_video",
    "splice_timeline",
    "run_qc",
)
REQUIRED_MUSIC_CAPABILITIES = frozenset(
    {
        "source_music_timeline",
        "audio_asset_registration",
        "seedance_audio_reference",
        "exact_fragment_mix",
        "singing_qa",
        "frozen_provider_submit",
        "provider_task_lineage_lookup",
    }
)
MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND = "music_timeline_contract"
PERFORMANCE_LINE_CONTRACT_ARTIFACT_KIND = "performance_line_contract"
BACKGROUND_MUSIC_AUDIT_RECEIPT_ARTIFACT_KIND = "background_music_audit_receipt"
BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND = "background_music_execution_request"
BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND = "background_music_provider_submission"
BACKGROUND_MUSIC_PROVIDER_RAW_RESPONSE_ARTIFACT_KIND = "background_music_provider_raw_response"
BACKGROUND_MUSIC_PROVIDER_OUTPUT_ARTIFACT_KIND = "background_music_provider_output"
BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1 = "background_music_execution_receipt/v1"
BACKGROUND_MUSIC_AUDIT_RECEIPT_V1 = "background_music_audit_receipt/v1"
FORBIDDEN_MUSIC_OPERATIONS = ("loop", "atempo", "stretch", "pitch_shift", "silence_padding")
POST_AUDIT_MUSIC_STAGES = frozenset(
    {"submit_provider_video", "wait_provider_video", "splice_timeline", "run_qc"}
)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def is_background_music_manifest(manifest: object) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    extensions = manifest.get("extensions")
    return isinstance(extensions, Mapping) and extensions.get("background_music") is not None


def _background_music_error(error: Exception) -> ValueError:
    if isinstance(error, ReplicationError):
        return ValueError(f"{error.code}: {error.message}")
    return ValueError(str(error))


def _validated_uploaded_music(uploaded_audio: Mapping[str, object]) -> dict[str, object]:
    if (
        not isinstance(uploaded_audio, Mapping)
        or not _is_sha256(uploaded_audio.get("sha256"))
        or not isinstance(uploaded_audio.get("content_type"), str)
        or not uploaded_audio["content_type"].casefold().startswith("audio/")
    ):
        raise ValueError("BACKGROUND_MUSIC_MANIFEST_INVALID")
    return dict(uploaded_audio)


def _validated_audio_asset_receipt(
    receipt: Mapping[str, object],
    *,
    uploaded_audio_sha256: str,
) -> dict[str, object]:
    uri = receipt.get("asset_uri") if isinstance(receipt, Mapping) else None
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("asset_type") != "Audio"
        or receipt.get("status") != "active"
        or receipt.get("uploaded_audio_sha256") != uploaded_audio_sha256
        or not isinstance(uri, str)
        or not uri.startswith("asset://asset-")
    ):
        raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
    return dict(receipt)


def _validated_music_windows(
    music_timeline_contract: Mapping[str, object],
    *,
    uploaded_audio: Mapping[str, object],
) -> list[dict[str, object]]:
    """Validate exact uploaded-song ranges while retaining source event facts."""

    if not isinstance(music_timeline_contract, Mapping):
        raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    BackgroundMusicStagePort._validate_music_timeline(
        contract=music_timeline_contract,
        uploaded=uploaded_audio,
    )
    windows = music_timeline_contract.get("windows")
    if not isinstance(windows, list):  # protected by _validate_music_timeline; keeps the return typed.
        raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    return [dict(window) for window in windows if isinstance(window, Mapping)]


def _provider_payload(*, asset_uri: str, performance: Mapping[str, object]) -> dict[str, object]:
    mode = performance.get("mode")
    if mode == "verified_singing":
        lines = performance.get("singing_lines")
        if not isinstance(lines, list) or not lines:
            raise ValueError("VERIFIED_SINGING_EVIDENCE_REQUIRED")
        exact_lines = " | ".join(str(line["exact_sung_text"]) for line in lines)
        text = (
            "Use @Audio1 as the uploaded-song reference. Perform only these verified lyrics exactly: "
            f"{exact_lines}. Preserve the frozen source music windows, entries, exits, fades, silences, and transitions."
        )
    elif mode == "background_music_replacement":
        text = (
            "Use @Audio1 as the uploaded-song background-music reference. No lyric lip-sync. "
            "Preserve the frozen source music windows, entries, exits, fades, silences, and transitions."
        )
    else:
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID")
    return {
        "model": "seedance-2.0",
        "content": [
            {"type": "text", "text": text},
            {"type": "audio_url", "role": "reference_audio", "audio_url": {"url": asset_uri}},
        ],
    }


def _execution_binding(execution_contract: Mapping[str, object]) -> dict[str, str]:
    payload = execution_contract.get("provider_payload")
    if not isinstance(payload, Mapping):
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID")
    unsigned = {
        key: value
        for key, value in execution_contract.items()
        if key not in {"execution_contract_sha256", "seedance_payload_sha256"}
    }
    return {
        "execution_contract_sha256": hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest(),
        "seedance_payload_sha256": hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
    }


def _validate_verified_singing_windows(
    *,
    performance: Mapping[str, object],
    music_windows: list[dict[str, object]],
) -> None:
    if performance.get("mode") != "verified_singing":
        return
    lines = performance.get("singing_lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("VERIFIED_SINGING_EVIDENCE_REQUIRED")
    source_windows: list[tuple[int, int]] = []
    for window in music_windows:
        start = window.get("source_start_ms")
        end = window.get("source_end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError("VERIFIED_SINGING_WINDOW_REQUIRED")
        source_windows.append((start, end))
    for line in lines:
        source_time = line.get("source_time") if isinstance(line, Mapping) else None
        if not isinstance(source_time, Mapping):
            raise ValueError("VERIFIED_SINGING_WINDOW_REQUIRED")
        start = source_time.get("start_ms")
        end = source_time.get("end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("VERIFIED_SINGING_WINDOW_REQUIRED")
        if not any(window_start <= start and end <= window_end for window_start, window_end in source_windows):
            raise ValueError("VERIFIED_SINGING_WINDOW_REQUIRED")


def compile_background_music_execution_contract(
    *,
    uploaded_audio: Mapping[str, object],
    music_timeline_contract: Mapping[str, object],
    audio_asset_receipt: Mapping[str, object],
    user_confirmed_intent: str,
    performance_line_contract: Mapping[str, object] | None,
) -> dict[str, object]:
    """Compile a conditional Seedance ``@Audio1`` request without new stages.

    Singing is selected only by immutable confirmed performance evidence.  The
    fallback is an explicit BGM replacement, never a guessed lyric performance.
    """

    uploaded = _validated_uploaded_music(uploaded_audio)
    windows = _validated_music_windows(music_timeline_contract, uploaded_audio=uploaded)
    asset_receipt = _validated_audio_asset_receipt(
        audio_asset_receipt,
        uploaded_audio_sha256=str(uploaded["sha256"]),
    )
    try:
        performance = build_background_music_performance_contract(
            user_confirmed_intent=user_confirmed_intent,
            performance_line_contract=performance_line_contract,
        )
    except ReplicationError as error:
        raise _background_music_error(error) from error
    _validate_verified_singing_windows(performance=performance, music_windows=windows)
    payload = _provider_payload(asset_uri=str(asset_receipt["asset_uri"]), performance=performance)
    execution = {
        "contract": BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1,
        "mode": performance["mode"],
        "lyric_lip_sync_policy": performance["lyric_lip_sync_policy"],
        "performance_line_contract_sha256": performance["performance_line_contract_sha256"],
        "uploaded_audio_sha256": uploaded["sha256"],
        "uploaded_audio": uploaded,
        "music_timeline_contract": dict(music_timeline_contract),
        "user_confirmed_intent": user_confirmed_intent,
        "performance_line_contract": (
            None if performance_line_contract is None else dict(performance_line_contract)
        ),
        "source_music_windows": windows,
        "forbidden_operations": list(FORBIDDEN_MUSIC_OPERATIONS),
        "audio_asset_receipt": asset_receipt,
        "performance": performance,
        "provider_payload": payload,
    }
    execution.update(_execution_binding(execution))
    return execution


def _validate_frozen_execution_contract(execution_contract: Mapping[str, object]) -> None:
    try:
        expected = compile_background_music_execution_contract(
            uploaded_audio=execution_contract["uploaded_audio"],
            music_timeline_contract=execution_contract["music_timeline_contract"],
            audio_asset_receipt=execution_contract["audio_asset_receipt"],
            user_confirmed_intent=str(execution_contract["user_confirmed_intent"]),
            performance_line_contract=execution_contract.get("performance_line_contract"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID") from error
    if dict(execution_contract) != expected:
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID")


def execute_background_music(
    *,
    execution_contract: Mapping[str, object],
    final_mix_receipt: Mapping[str, object],
    materialize_bytes: Any | None = None,
    materialize_pcm: Any | None = None,
    materialize_video_timing: Any | None = None,
) -> dict[str, object]:
    """Accept only a final receipt that proves exact uploaded-song fragments.

    This is a verification boundary, not a media transformation: it binds the
    uploaded SHA, every source window and final MP4 SHA to the final mix.
    """

    if (
        not isinstance(execution_contract, Mapping)
        or execution_contract.get("contract") != BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1
        or execution_contract.get("mode") not in {"verified_singing", "background_music_replacement"}
        or execution_contract.get("forbidden_operations") != list(FORBIDDEN_MUSIC_OPERATIONS)
        or not _is_sha256(execution_contract.get("uploaded_audio_sha256"))
        or (
            execution_contract.get("mode") == "verified_singing"
            and not _is_sha256(execution_contract.get("performance_line_contract_sha256"))
        )
        or (
            execution_contract.get("mode") == "background_music_replacement"
            and execution_contract.get("performance_line_contract_sha256") is not None
        )
    ):
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID")
    _validate_frozen_execution_contract(execution_contract)
    expected_windows = execution_contract.get("source_music_windows")
    if not isinstance(expected_windows, list) or not expected_windows or any(
        not isinstance(window, Mapping) for window in expected_windows
    ):
        raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    if (
        not isinstance(final_mix_receipt, Mapping)
        or final_mix_receipt.get("passed") is not True
        or final_mix_receipt.get("mode") != execution_contract.get("mode")
        or final_mix_receipt.get("uploaded_audio_sha256") != execution_contract.get("uploaded_audio_sha256")
        or final_mix_receipt.get("forbidden_operations") != list(FORBIDDEN_MUSIC_OPERATIONS)
        or not _is_sha256(final_mix_receipt.get("final_audio_sha256"))
        or not _is_sha256(final_mix_receipt.get("final_video_sha256"))
    ):
        raise ValueError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
    observed_windows = final_mix_receipt.get("window_receipts")
    if not isinstance(observed_windows, list) or len(observed_windows) != len(expected_windows):
        raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
    required_flags = (
        "looped",
        "atempo_applied",
        "speed_changed",
        "time_stretched",
        "pitch_shifted",
        "silence_padded",
        "generated_substitute",
    )
    for expected, observed in zip(expected_windows, observed_windows):
        if (
            not isinstance(observed, Mapping)
            or any(observed.get(field) != value for field, value in expected.items())
            or not _is_sha256(observed.get("fragment_sha256"))
            or observed.get("uploaded_fragment_sha256") != observed.get("fragment_sha256")
            or observed.get("final_audio_fragment_sha256") != observed.get("fragment_sha256")
        ):
            raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        if any(observed.get(flag) is not False for flag in required_flags):
            raise ValueError("BACKGROUND_MUSIC_TRANSFORM_FORBIDDEN")
    if not callable(materialize_bytes) or not callable(materialize_pcm) or not callable(materialize_video_timing):
        raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED")
    _validate_materialized_mix_media(
        execution_contract=execution_contract,
        final_mix_receipt=final_mix_receipt,
        materialize_bytes=materialize_bytes,
        materialize_pcm=materialize_pcm,
        materialize_video_timing=materialize_video_timing,
    )
    return {
        **dict(final_mix_receipt),
        "source_music_windows": [dict(window) for window in expected_windows],
        "lyric_lip_sync_policy": execution_contract["lyric_lip_sync_policy"],
    }


def _validate_materialized_mix_media(
    *,
    execution_contract: Mapping[str, object],
    final_mix_receipt: Mapping[str, object],
    materialize_bytes: Any,
    materialize_pcm: Any | None,
    materialize_video_timing: Any | None,
) -> None:
    """Prove receipt digests from lease-local bytes, never delegate claims."""

    if not callable(materialize_bytes):
        raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED")
    for artifact_field, sha_field in (
        ("final_audio_artifact", "final_audio_sha256"),
        ("final_video_artifact", "final_video_sha256"),
    ):
        reference = final_mix_receipt.get(artifact_field)
        if (
            not isinstance(reference, Mapping)
            or not _is_sha256(reference.get("sha256"))
            or reference.get("sha256") != final_mix_receipt.get(sha_field)
        ):
            raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED")
    try:
        uploaded = materialize_bytes("uploaded_audio", execution_contract.get("uploaded_audio"))
        final_audio = materialize_bytes("final_audio", final_mix_receipt.get("final_audio_artifact"))
        final_video = materialize_bytes("final_video", final_mix_receipt.get("final_video_artifact"))
    except Exception as error:
        raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED") from error
    if not all(isinstance(value, bytes) for value in (uploaded, final_audio, final_video)):
        raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED")
    if (
        hashlib.sha256(uploaded).hexdigest() != execution_contract.get("uploaded_audio_sha256")
        or hashlib.sha256(final_audio).hexdigest() != final_mix_receipt.get("final_audio_sha256")
        or hashlib.sha256(final_video).hexdigest() != final_mix_receipt.get("final_video_sha256")
    ):
        raise ValueError("BACKGROUND_MUSIC_MEDIA_HASH_MISMATCH")
    windows = final_mix_receipt.get("window_receipts")
    if not isinstance(windows, list):
        raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
    for window in windows:
        if not isinstance(window, Mapping):
            raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        offsets = (
            window.get("uploaded_byte_offset"),
            window.get("uploaded_byte_length"),
            window.get("final_audio_byte_offset"),
            window.get("final_audio_byte_length"),
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in offsets):
            raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        uploaded_offset, uploaded_length, final_offset, final_length = offsets
        if uploaded_length <= 0 or final_length != uploaded_length:
            raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        source_fragment = uploaded[uploaded_offset : uploaded_offset + uploaded_length]
        final_fragment = final_audio[final_offset : final_offset + final_length]
        fragment_sha = hashlib.sha256(source_fragment).hexdigest()
        if (
            len(source_fragment) != uploaded_length
            or len(final_fragment) != final_length
            or source_fragment != final_fragment
            or fragment_sha != window.get("fragment_sha256")
            or fragment_sha != window.get("uploaded_fragment_sha256")
            or fragment_sha != window.get("final_audio_fragment_sha256")
        ):
            raise ValueError("BACKGROUND_MUSIC_MEDIA_HASH_MISMATCH")
    if materialize_pcm is not None:
        if not callable(materialize_pcm):
            raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED")
        try:
            uploaded_pcm = materialize_pcm("uploaded_audio", execution_contract.get("uploaded_audio"))
            final_audio_pcm = materialize_pcm("final_audio", final_mix_receipt.get("final_audio_artifact"))
            final_video_pcm = materialize_pcm("final_video", final_mix_receipt.get("final_video_artifact"))
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED") from error
        if (
            not isinstance(uploaded_pcm, bytes)
            or not isinstance(final_audio_pcm, bytes)
            or not isinstance(final_video_pcm, bytes)
            or not final_audio_pcm
            or final_audio_pcm != final_video_pcm
        ):
            raise ValueError("BACKGROUND_MUSIC_VIDEO_AUDIO_MISMATCH")
        _validate_pcm_timeline(
            execution_contract=execution_contract,
            final_mix_receipt=final_mix_receipt,
            uploaded_pcm=uploaded_pcm,
            final_audio_pcm=final_audio_pcm,
        )
        if not callable(materialize_video_timing):
            raise ValueError("BACKGROUND_MUSIC_VIDEO_TIMELINE_MISMATCH")
        try:
            video_timing = materialize_video_timing(final_mix_receipt.get("final_video_artifact"))
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_VIDEO_TIMELINE_MISMATCH") from error
        windows = execution_contract.get("source_music_windows")
        if not isinstance(video_timing, Mapping) or not isinstance(windows, list):
            raise ValueError("BACKGROUND_MUSIC_VIDEO_TIMELINE_MISMATCH")
        timeline = execution_contract.get("music_timeline_contract")
        output_duration_ms = timeline.get("output_duration_ms") if isinstance(timeline, Mapping) else None
        if (
            abs(video_timing.get("start_ms", -1)) > 1
            or not isinstance(output_duration_ms, int)
            or abs(video_timing.get("duration_ms", -1) - output_duration_ms) > 1
        ):
            raise ValueError("BACKGROUND_MUSIC_VIDEO_TIMELINE_MISMATCH")


def _validate_pcm_timeline(
    *,
    execution_contract: Mapping[str, object],
    final_mix_receipt: Mapping[str, object],
    uploaded_pcm: bytes,
    final_audio_pcm: bytes,
) -> None:
    """Derive every exact fragment from frozen milliseconds in canonical PCM."""

    bytes_per_ms = 48_000 * 2 * 2 // 1_000
    windows = execution_contract.get("source_music_windows")
    receipts = final_mix_receipt.get("window_receipts")
    if not isinstance(windows, list) or not isinstance(receipts, list) or len(windows) != len(receipts):
        raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
    timeline = execution_contract.get("music_timeline_contract")
    silence_intervals = timeline.get("meaningful_silence_output_intervals") if isinstance(timeline, Mapping) else None
    output_duration_ms = timeline.get("output_duration_ms") if isinstance(timeline, Mapping) else None
    if isinstance(output_duration_ms, bool) or not isinstance(output_duration_ms, int) or output_duration_ms <= 0 or not isinstance(silence_intervals, list):
        raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
    declared_silence: list[tuple[int, int]] = []
    for silence in silence_intervals:
        if not isinstance(silence, Mapping):
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        start, end = silence.get("output_start_ms"), silence.get("output_end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        if start < 0 or end > output_duration_ms:
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        declared_silence.append((start, end))
    covered: list[tuple[int, int, str]] = [(start, end, "silence") for start, end in declared_silence]
    for window, receipt in zip(windows, receipts):
        if not isinstance(window, Mapping) or not isinstance(receipt, Mapping):
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        values = (window.get("uploaded_start_ms"), window.get("uploaded_end_ms"), window.get("output_start_ms"), window.get("output_end_ms"))
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        uploaded_start, uploaded_end, output_start, output_end = values
        source = uploaded_pcm[uploaded_start * bytes_per_ms : uploaded_end * bytes_per_ms]
        observed = final_audio_pcm[output_start * bytes_per_ms : output_end * bytes_per_ms]
        digest = hashlib.sha256(source).hexdigest()
        if (
            uploaded_end <= uploaded_start
            or output_end - output_start != uploaded_end - uploaded_start
            or len(source) != (uploaded_end - uploaded_start) * bytes_per_ms
            or source != observed
            or receipt.get("pcm_fragment_sha256") != digest
        ):
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        if output_end > output_duration_ms:
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        covered.append((output_start, output_end, "music"))
    if len(final_audio_pcm) != output_duration_ms * bytes_per_ms:
        raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
    cursor = 0
    for start, end, kind in sorted(covered):
        if start != cursor or end <= start:
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        if kind == "silence" and any(final_audio_pcm[start * bytes_per_ms : end * bytes_per_ms]):
            raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")
        cursor = end
    if cursor != output_duration_ms:
        raise ValueError("BACKGROUND_MUSIC_TIME_FRAGMENT_MISMATCH")


def build_background_music_stage_plan(
    manifest: Mapping[str, Any],
    *,
    review_route: str | None,
) -> list[dict[str, Any]]:
    """Expand only music jobs onto the canonical generation-stage names."""

    plan = build_stage_plan(manifest, review_route=review_route)
    if not is_background_music_manifest(manifest):
        return plan
    if any(item.get("name") == "build_script" for item in plan):
        return plan

    extensions = manifest.get("extensions") if isinstance(manifest.get("extensions"), Mapping) else {}
    selected_route = review_route or extensions.get("review_route") or manifest.get("review_route")
    if selected_route == "local_only":
        raise ValueError("BACKGROUND_MUSIC_REVIEW_ROUTE_INVALID")
    # This is an in-memory planning projection only.  It preserves every
    # canonical stage field (including active high-fidelity internals) while
    # making the optional audio extension require the existing generation path.
    planning_manifest = dict(manifest)
    planning_routes = dict(manifest.get("routes") or {})
    planning_routes["character"] = "replace_from_slot"
    planning_manifest["routes"] = planning_routes
    planned = build_stage_plan(planning_manifest, review_route=review_route)
    if not any(item.get("name") == "build_script" for item in planned):
        raise ValueError("BACKGROUND_MUSIC_STAGE_PLAN_INVALID")
    return planned


def _background_music_context(context: Any) -> Any:
    snapshot = getattr(context, "snapshot", None)
    manifest = getattr(snapshot, "slots_manifest", None)
    if not isinstance(manifest, Mapping):
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID")
    extensions = manifest.get("extensions")
    background_music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
    if not isinstance(background_music, Mapping):
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID")
    required = ("object_key", "sha256", "size_bytes", "content_type", "duration_seconds", "status")
    if any(background_music.get(field) is None for field in required):
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID")
    slots = manifest.get("slots")
    if not isinstance(slots, Mapping) or "background_music" in slots:
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID")

    completion = dict(background_music)
    completion["store_verified"] = True
    descriptor = {
        "kind": "audio",
        "metadata": [completion],
        "present": True,
        "role": "background_music_extension",
        "sha256": [completion["sha256"]],
        "slot_id": "background_music",
        "source": "extension",
        "valid": True,
        "values": [completion["object_key"]],
    }
    transient_manifest = dict(manifest)
    transient_manifest["slots"] = {**slots, "background_music": descriptor}
    try:
        transient_snapshot = replace(snapshot, slots_manifest=transient_manifest)
        return replace(context, snapshot=transient_snapshot)
    except TypeError as error:
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID") from error


class _VerifiedBackgroundMusicProviderAdapter:
    """Hold the exact manifest-bound Provider methods selected at startup."""

    def __init__(self, adapter: Any) -> None:
        identity = getattr(adapter, "capability_identity", None)
        if not callable(identity):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID")
        declared = identity()
        if not isinstance(declared, Mapping) or not all(
            isinstance(declared.get(field), str) and declared[field]
            for field in ("implementation", "version", "sha256")
        ) or not _is_sha256(declared.get("sha256")):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID")
        self.adapter = adapter
        self.identity = dict(declared)
        self._identity_self, self._identity_func = self._bound_method("capability_identity")
        self._create_self, self._create_func = self._bound_method("create_video")
        self._lookup_self, self._lookup_func = self._bound_method("lookup")

    def _bound_method(self, name: str) -> tuple[Any, Any]:
        method = getattr(self.adapter, name, None)
        receiver = getattr(method, "__self__", None)
        function = getattr(method, "__func__", None)
        if not callable(method) or receiver is not self.adapter or function is None:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID")
        return receiver, function

    def _verified_method(self, name: str, expected_self: Any, expected_func: Any) -> Any:
        current_self, current_func = self._bound_method(name)
        if current_self is not expected_self or current_func is not expected_func:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID")
        return getattr(self.adapter, name)

    def create_video(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._verified_method("create_video", self._create_self, self._create_func)(request)

    def lookup(self, intent: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._verified_method("lookup", self._lookup_self, self._lookup_func)(intent)

    def validate_integrity(self) -> None:
        identity = self._verified_method(
            "capability_identity", self._identity_self, self._identity_func
        )()
        if not isinstance(identity, Mapping) or dict(identity) != self.identity:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID")
        self._verified_method("create_video", self._create_self, self._create_func)
        self._verified_method("lookup", self._lookup_self, self._lookup_func)


class BackgroundMusicStagePort:
    """Dispatch a music job through a dedicated existing-stage StagePort.

    The extension gains a materializable descriptor only in the copied worker
    context.  It is never persisted into the canonical seven-slot manifest.
    """

    def __init__(
        self,
        *,
        stage: str | None = None,
        delegate: Any,
        music_delegate: Any,
        provider_adapter: Any | None = None,
    ) -> None:
        if not callable(getattr(delegate, "run", delegate)) or not callable(
            getattr(music_delegate, "run", music_delegate)
        ):
            raise ValueError("BACKGROUND_MUSIC_STAGE_PORT_INVALID")
        self.delegate = delegate
        self.music_delegate = music_delegate
        self.stage = stage
        self._provider_adapter = _VerifiedBackgroundMusicProviderAdapter(provider_adapter) if provider_adapter is not None else None

    @staticmethod
    def _run(port: Any, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        operation = getattr(port, "run", port)
        result = operation(context=context, input_artifacts=input_artifacts)
        if not isinstance(result, Mapping):
            raise ValueError("BACKGROUND_MUSIC_STAGE_OUTPUT_INVALID")
        return result

    def run(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        if not is_background_music_manifest(manifest):
            return self._run(self.delegate, context=context, input_artifacts=input_artifacts)
        frozen_contract = (
            self._materialize_frozen_timeline_contract(context)
            if self.stage in {"compile_seedance20_prompt", "audit_seedance_request", "splice_timeline", "run_qc"}
            else None
        )
        frozen_audit_receipt = (
            self._materialize_frozen_audit_receipt(context)
            if self.stage in POST_AUDIT_MUSIC_STAGES
            else None
        )
        frozen_execution_request = (
            self._materialize_frozen_execution_request(context)
            if self.stage == "submit_provider_video"
            else None
        )
        frozen_provider_submission = (
            self._materialize_frozen_provider_submission(context)
            if self.stage == "wait_provider_video"
            else None
        )
        if self.stage == "compile_seedance20_prompt":
            try:
                artifacts = context.artifacts
            except AttributeError:
                artifacts = ()
            if any(isinstance(item, Mapping) and item.get("kind") == PERFORMANCE_LINE_CONTRACT_ARTIFACT_KIND for item in artifacts):
                self._materialize_frozen_performance_line_contract(context)
        augmented_artifacts = list(input_artifacts)
        if frozen_contract is not None:
            _, reference = frozen_contract
            augmented_artifacts.append(
                {
                    "artifact_id": reference["artifact_id"],
                    "kind": MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND,
                    "sha256": reference["sha256"],
                }
            )
        if frozen_audit_receipt is not None:
            _, reference = frozen_audit_receipt
            augmented_artifacts.append(
                {
                    "artifact_id": reference["artifact_id"],
                    "kind": BACKGROUND_MUSIC_AUDIT_RECEIPT_ARTIFACT_KIND,
                    "sha256": reference["sha256"],
                }
            )
        if frozen_execution_request is not None:
            frozen_execution, reference = frozen_execution_request
            augmented_artifacts.append(
                {
                    "artifact_id": reference["artifact_id"],
                    "kind": BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND,
                    "sha256": reference["sha256"],
                    "music_execution_contract": frozen_execution["music_execution_contract"],
                    "provider_payload": frozen_execution["provider_payload"],
                    "request_binding": frozen_execution["request_binding"],
                }
            )
        if frozen_provider_submission is not None:
            submission, reference = frozen_provider_submission
            augmented_artifacts.append({
                "artifact_id": reference["artifact_id"],
                "kind": BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND,
                "sha256": reference["sha256"],
                "provider_submission_receipt": submission,
            })
        music_context = _background_music_context(context)
        if self.stage == "submit_provider_video":
            result = self._submit_frozen_provider_request(frozen_execution_request)
        elif self.stage == "wait_provider_video":
            result = self._lookup_frozen_provider_task(
                context=context,
                frozen_provider_submission=frozen_provider_submission,
            )
        else:
            result = self._run(
                self.music_delegate,
                context=music_context,
                input_artifacts=augmented_artifacts,
            )
        return self._validate_stage_result(
            context=context,
            result=result,
            frozen_contract=frozen_contract,
            frozen_audit_receipt=frozen_audit_receipt,
            frozen_execution_request=frozen_execution_request,
            frozen_provider_submission=frozen_provider_submission,
        )

    def _provider(self) -> "_VerifiedBackgroundMusicProviderAdapter":
        if self._provider_adapter is None:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_ADAPTER_REQUIRED")
        return self._provider_adapter

    def _submit_frozen_provider_request(
        self,
        frozen_execution_request: tuple[Mapping[str, Any], dict[str, str]] | None,
    ) -> Mapping[str, Any]:
        if frozen_execution_request is None:
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED")
        request, request_reference = frozen_execution_request
        execution_contract = request["music_execution_contract"]
        provider_payload = request["provider_payload"]
        binding = _execution_binding(execution_contract)
        request_binding = request.get("request_binding")
        if (
            not isinstance(request_binding, Mapping)
            or request_binding.get("execution_contract_sha256") != binding["execution_contract_sha256"]
            or request_binding.get("seedance_payload_sha256") != binding["seedance_payload_sha256"]
            or request_binding.get("provider_payload") != provider_payload
        ):
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED")
        provider_response = self._provider().create_video(provider_payload)
        if not isinstance(provider_response, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        task_id = provider_response.get("task_id", provider_response.get("taskId"))
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        raw_response = _canonical_json_bytes(dict(provider_response))
        receipt = {
            "provider_task_id": task_id.strip(),
            **binding,
            "provider_payload": provider_payload,
            "provider_raw_response_sha256": hashlib.sha256(raw_response).hexdigest(),
        }
        return {
            "background_music_evidence": {
                "music_execution_contract": execution_contract,
                "provider_payload": provider_payload,
                "music_execution_audit_receipt_artifact": request["audit_receipt_artifact"],
                "music_execution_request_artifact": {
                    **request_reference,
                    "kind": BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND,
                },
                "music_execution_audit_binding": binding,
                "provider_submission_receipt": receipt,
                "provider_raw_response": raw_response,
            }
        }

    def _lookup_frozen_provider_task(
        self,
        *,
        context: Any,
        frozen_provider_submission: tuple[Mapping[str, Any], dict[str, str]] | None,
    ) -> Mapping[str, Any]:
        if frozen_provider_submission is None:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        submission, reference = frozen_provider_submission
        request_reference = submission.get("execution_request_artifact")
        if not isinstance(request_reference, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        request = self._materialize_execution_request_reference(
            context=context,
            reference=request_reference,
        )
        if (
            request.get("music_execution_contract") != submission.get("music_execution_contract")
            or request.get("provider_payload") != submission.get("provider_payload")
            or request.get("audit_receipt_artifact") != submission.get("audit_receipt_artifact")
            or request.get("request_binding")
            != {
                **_execution_binding(submission["music_execution_contract"]),
                "provider_payload": submission.get("provider_payload"),
            }
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        raw_reference = submission.get("provider_raw_response_artifact")
        if not isinstance(raw_reference, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        raw = self._materialize_provider_json_artifact(
            context=context,
            kind=BACKGROUND_MUSIC_PROVIDER_RAW_RESPONSE_ARTIFACT_KIND,
            reference=raw_reference,
        )
        task_id = submission.get("provider_task_id")
        if (
            not isinstance(task_id, str)
            or raw.get("task_id", raw.get("taskId")) != task_id
            or hashlib.sha256(_canonical_json_bytes(raw)).hexdigest() != submission.get("provider_raw_response_sha256")
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        lookup = self._provider().lookup({"taskId": task_id})
        if not isinstance(lookup, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED")
        lookup_task_id = lookup.get("task_id", lookup.get("taskId"))
        status = lookup.get("status")
        if (
            lookup_task_id != task_id
            or not isinstance(status, str)
            or status.casefold() not in {"completed", "complete", "succeeded", "success", "done"}
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED")
        raw_lookup = _canonical_json_bytes(dict(lookup))
        output_reference = self._publish_provider_output(
            context=context,
            raw_lookup=raw_lookup,
            task_id=task_id,
            submission=submission,
            submission_reference=reference,
        )
        output = self._materialize_provider_json_artifact(
            context=context,
            kind=BACKGROUND_MUSIC_PROVIDER_OUTPUT_ARTIFACT_KIND,
            reference=output_reference,
        )
        execution_contract = submission.get("music_execution_contract")
        provider_payload = submission.get("provider_payload")
        audit_reference = submission.get("audit_receipt_artifact")
        if not isinstance(execution_contract, Mapping) or not isinstance(provider_payload, Mapping) or not isinstance(audit_reference, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        if (
            output.get("provider_task_id") != task_id
            or output.get("provider_submission_artifact")
            != {**reference, "kind": BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND}
            or output.get("audit_receipt_artifact") != audit_reference
            or output.get("execution_contract_sha256") != submission.get("execution_contract_sha256")
            or output.get("seedance_payload_sha256") != submission.get("seedance_payload_sha256")
            or output.get("provider_payload") != provider_payload
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED")
        return {
            "background_music_evidence": {
                "music_execution_contract": execution_contract,
                "provider_payload": provider_payload,
                "music_execution_audit_receipt_artifact": audit_reference,
                "music_execution_audit_binding": _execution_binding(execution_contract),
                "provider_submission_receipt": submission,
                "provider_submission_artifact": {**reference, "kind": BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND},
                "provider_output_artifact": output_reference,
            }
        }

    def _validate_stage_result(
        self,
        *,
        context: Any,
        result: Mapping[str, Any],
        frozen_contract: tuple[Mapping[str, Any], dict[str, str]] | None,
        frozen_audit_receipt: tuple[Mapping[str, Any], dict[str, str]] | None,
        frozen_execution_request: tuple[Mapping[str, Any], dict[str, str]] | None,
        frozen_provider_submission: tuple[Mapping[str, Any], dict[str, str]] | None,
    ) -> Mapping[str, Any]:
        if self.stage in POST_AUDIT_MUSIC_STAGES:
            self._validate_post_audit_evidence(
                result=result,
                frozen_audit_receipt=frozen_audit_receipt,
            )
        if self.stage == "analyze_dynamics":
            evidence = result.get("background_music_evidence")
            contract = evidence.get("music_timeline_contract") if isinstance(evidence, Mapping) else None
            manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
            extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
            uploaded = extensions.get("background_music") if isinstance(extensions, Mapping) else None
            if not isinstance(contract, Mapping) or not isinstance(uploaded, Mapping):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
            self._validate_music_timeline(contract=contract, uploaded=uploaded)
            return self._publish_frozen_timeline_contract(
                context=context,
                result=result,
                contract=contract,
            )
        if self.stage == "splice_timeline":
            evidence = result.get("background_music_evidence")
            contract = evidence.get("music_timeline_contract") if isinstance(evidence, Mapping) else None
            receipt = evidence.get("mix_receipt") if isinstance(evidence, Mapping) else None
            execution_contract = evidence.get("music_execution_contract") if isinstance(evidence, Mapping) else None
            manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
            extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
            uploaded = extensions.get("background_music") if isinstance(extensions, Mapping) else None
            if not isinstance(contract, Mapping) or not isinstance(receipt, Mapping) or not isinstance(uploaded, Mapping):
                raise ValueError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
            if not isinstance(execution_contract, Mapping):
                raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_REQUIRED")
            self._validate_audit_binding(evidence=evidence, execution_contract=execution_contract)
            self._validate_frozen_verified_performance(context=context, execution_contract=execution_contract)
            self._validate_music_timeline(contract=contract, uploaded=uploaded)
            self._validate_mix_receipt(contract=contract, uploaded=uploaded, receipt=receipt)
            self._validate_frozen_timeline_reference(
                result=result,
                contract=contract,
                frozen_contract=frozen_contract,
            )
            execute_background_music(
                execution_contract=execution_contract,
                final_mix_receipt=receipt,
                materialize_bytes=self._materialized_mix_bytes(context),
                materialize_pcm=self._materialized_mix_pcm(context),
                materialize_video_timing=self._materialized_video_timing(context),
            )
            return result
        if self.stage == "run_qc":
            evidence = result.get("background_music_evidence")
            contract = evidence.get("music_timeline_contract") if isinstance(evidence, Mapping) else None
            receipt = evidence.get("mix_receipt") if isinstance(evidence, Mapping) else None
            singing_qa = evidence.get("singing_qa") if isinstance(evidence, Mapping) else None
            execution_contract = evidence.get("music_execution_contract") if isinstance(evidence, Mapping) else None
            manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
            extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
            uploaded = extensions.get("background_music") if isinstance(extensions, Mapping) else None
            if not isinstance(contract, Mapping) or not isinstance(receipt, Mapping) or not isinstance(uploaded, Mapping):
                raise ValueError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
            if not isinstance(execution_contract, Mapping):
                raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_REQUIRED")
            self._validate_audit_binding(evidence=evidence, execution_contract=execution_contract)
            self._validate_frozen_verified_performance(context=context, execution_contract=execution_contract)
            self._validate_music_timeline(contract=contract, uploaded=uploaded)
            self._validate_mix_receipt(contract=contract, uploaded=uploaded, receipt=receipt)
            self._validate_frozen_timeline_reference(
                result=result,
                contract=contract,
                frozen_contract=frozen_contract,
            )
            execute_background_music(
                execution_contract=execution_contract,
                final_mix_receipt=receipt,
                materialize_bytes=self._materialized_mix_bytes(context),
                materialize_pcm=self._materialized_mix_pcm(context),
                materialize_video_timing=self._materialized_video_timing(context),
            )
            if execution_contract.get("mode") == "background_music_replacement":
                self._validate_no_lyric_lip_sync(singing_qa=singing_qa)
            else:
                self._validate_singing_qa(contract=contract, singing_qa=singing_qa)
            return result
        if self.stage == "compile_seedance20_prompt":
            evidence = result.get("background_music_evidence")
            execution_contract = evidence.get("music_execution_contract") if isinstance(evidence, Mapping) else None
            payload = evidence.get("provider_payload") if isinstance(evidence, Mapping) else None
            if not isinstance(execution_contract, Mapping) or not isinstance(payload, Mapping):
                raise ValueError("BACKGROUND_MUSIC_SEEDANCE_COMPILE_INVALID")
            try:
                _validate_frozen_execution_contract(execution_contract)
            except ValueError as error:
                raise ValueError("BACKGROUND_MUSIC_SEEDANCE_COMPILE_INVALID") from error
            if execution_contract.get("provider_payload") != payload:
                raise ValueError("BACKGROUND_MUSIC_SEEDANCE_COMPILE_INVALID")
            if frozen_contract is None:
                raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
            frozen_timeline, _ = frozen_contract
            if _canonical_json_bytes(execution_contract.get("music_timeline_contract")) != _canonical_json_bytes(frozen_timeline):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH")
            self._validate_frozen_verified_performance(context=context, execution_contract=execution_contract)
            return result
        if self.stage == "submit_provider_video":
            evidence = result.get("background_music_evidence")
            execution_contract = evidence.get("music_execution_contract") if isinstance(evidence, Mapping) else None
            receipt = evidence.get("provider_submission_receipt") if isinstance(evidence, Mapping) else None
            raw_response = evidence.get("provider_raw_response") if isinstance(evidence, Mapping) else None
            if not isinstance(execution_contract, Mapping) or not isinstance(receipt, Mapping):
                raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
            if frozen_execution_request is None or execution_contract != frozen_execution_request[0]["music_execution_contract"]:
                raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
            binding = _execution_binding(execution_contract)
            if (
                receipt.get("execution_contract_sha256") != binding["execution_contract_sha256"]
                or receipt.get("seedance_payload_sha256") != binding["seedance_payload_sha256"]
                or receipt.get("provider_payload") != execution_contract.get("provider_payload")
                or not isinstance(receipt.get("provider_task_id"), str)
                or not receipt["provider_task_id"]
                or not _is_sha256(receipt.get("provider_raw_response_sha256"))
                or not isinstance(raw_response, bytes)
                or hashlib.sha256(raw_response).hexdigest() != receipt.get("provider_raw_response_sha256")
            ):
                raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
            return self._publish_provider_submission(
                context=context,
                result=result,
                receipt=receipt,
                raw_response=raw_response,
                audit_receipt=frozen_execution_request[0]["audit_receipt_artifact"],
            )
        if self.stage == "wait_provider_video":
            evidence = result.get("background_music_evidence")
            receipt = evidence.get("provider_submission_receipt") if isinstance(evidence, Mapping) else None
            reference = evidence.get("provider_submission_artifact") if isinstance(evidence, Mapping) else None
            output = evidence.get("provider_output_artifact") if isinstance(evidence, Mapping) else None
            if (
                frozen_provider_submission is None
                or not isinstance(receipt, Mapping)
                or receipt != frozen_provider_submission[0]
                or not isinstance(reference, Mapping)
                or self._contract_artifact_reference(reference) != frozen_provider_submission[1]
                or not isinstance(output, Mapping)
                or output.get("kind") != BACKGROUND_MUSIC_PROVIDER_OUTPUT_ARTIFACT_KIND
            ):
                raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
            return result
        if self.stage != "audit_seedance_request":
            return result
        evidence = result.get("background_music_evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        receipt = evidence.get("audio_asset_receipt")
        payload = evidence.get("provider_payload")
        execution_contract = evidence.get("music_execution_contract")
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
        uploaded = extensions.get("background_music") if isinstance(extensions, Mapping) else None
        if (
            not isinstance(receipt, Mapping)
            or not isinstance(payload, Mapping)
            or not isinstance(uploaded, Mapping)
            or not isinstance(execution_contract, Mapping)
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        if (
            execution_contract.get("contract") != BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1
            or execution_contract.get("uploaded_audio_sha256") != uploaded.get("sha256")
            or execution_contract.get("audio_asset_receipt") != receipt
            or execution_contract.get("provider_payload") != payload
            or execution_contract.get("mode") not in {"verified_singing", "background_music_replacement"}
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        try:
            _validate_frozen_execution_contract(execution_contract)
        except ValueError as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID") from error
        if frozen_contract is None:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        frozen_timeline, _ = frozen_contract
        execution_timeline = execution_contract.get("music_timeline_contract")
        if (
            not isinstance(execution_timeline, Mapping)
            or _canonical_json_bytes(execution_timeline) != _canonical_json_bytes(frozen_timeline)
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        if execution_contract.get("mode") == "verified_singing":
            frozen_performance = self._materialize_frozen_performance_line_contract(context)
            declared_performance_sha = execution_contract.get("performance_line_contract_sha256")
            execution_performance = execution_contract.get("performance_line_contract")
            if (
                not isinstance(execution_performance, Mapping)
                or not _is_sha256(declared_performance_sha)
                or declared_performance_sha != frozen_performance[1]["sha256"]
                or _canonical_json_bytes(execution_performance) != _canonical_json_bytes(frozen_performance[0])
            ):
                raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        asset_uri = receipt.get("asset_uri")
        if (
            receipt.get("asset_type") != "Audio"
            or receipt.get("uploaded_audio_sha256") != uploaded.get("sha256")
            or receipt.get("status") != "active"
            or not isinstance(asset_uri, str)
            or not asset_uri.startswith("asset://asset-")
            or "reference_audios" in payload
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        content = payload.get("content")
        if not isinstance(content, list):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        text_items = [item.get("text") for item in content if isinstance(item, Mapping) and item.get("type") == "text"]
        audio_items = [item for item in content if isinstance(item, Mapping) and item.get("type") == "audio_url"]
        if (
            not any(isinstance(text, str) and "@Audio1" in text for text in text_items)
            or len(audio_items) != 1
            or audio_items[0].get("role") != "reference_audio"
            or not isinstance(audio_items[0].get("audio_url"), Mapping)
            or audio_items[0]["audio_url"].get("url") != asset_uri
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        enriched = dict(result)
        enriched["background_music_evidence"] = {
            **dict(evidence),
            "music_execution_audit_binding": _execution_binding(execution_contract),
        }
        audited = self._publish_audit_receipt(
            context=context,
            result=enriched,
            execution_contract=execution_contract,
            frozen_timeline_reference=frozen_contract[1],
        )
        return self._publish_execution_request(
            context=context,
            result=audited,
            execution_contract=execution_contract,
        )

    @staticmethod
    def _validate_audit_binding(*, evidence: Mapping[str, Any], execution_contract: Mapping[str, object]) -> None:
        binding = evidence.get("music_execution_audit_binding")
        if not isinstance(binding, Mapping) or dict(binding) != _execution_binding(execution_contract):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_BINDING_REQUIRED")

    @staticmethod
    def _validate_frozen_verified_performance(*, context: Any, execution_contract: Mapping[str, object]) -> None:
        if execution_contract.get("mode") != "verified_singing":
            return
        frozen_performance, reference = BackgroundMusicStagePort._materialize_frozen_performance_line_contract(context)
        if (
            execution_contract.get("performance_line_contract_sha256") != reference["sha256"]
            or _canonical_json_bytes(execution_contract.get("performance_line_contract"))
            != _canonical_json_bytes(frozen_performance)
        ):
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_MISMATCH")

    @staticmethod
    def _audit_receipt_payload(
        *,
        execution_contract: Mapping[str, object],
        frozen_timeline_reference: Mapping[str, str],
    ) -> dict[str, object]:
        return {
            "contract": BACKGROUND_MUSIC_AUDIT_RECEIPT_V1,
            **_execution_binding(execution_contract),
            "music_timeline_contract_sha256": frozen_timeline_reference["sha256"],
            "performance_line_contract_sha256": execution_contract.get("performance_line_contract_sha256"),
        }

    @staticmethod
    def _publish_audit_receipt(
        *,
        context: Any,
        result: Mapping[str, Any],
        execution_contract: Mapping[str, object],
        frozen_timeline_reference: Mapping[str, str],
    ) -> Mapping[str, Any]:
        publish = getattr(context, "publish_bytes", None)
        if not callable(publish):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED")
        payload = BackgroundMusicStagePort._audit_receipt_payload(
            execution_contract=execution_contract,
            frozen_timeline_reference=frozen_timeline_reference,
        )
        encoded = _canonical_json_bytes(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        try:
            published = publish(
                kind=BACKGROUND_MUSIC_AUDIT_RECEIPT_ARTIFACT_KIND,
                data=encoded,
                content_type="application/json",
                expected_sha256=digest,
            )
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED") from error
        if not isinstance(published, Mapping):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(published)
        evidence = result.get("background_music_evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED")
        enriched = dict(result)
        enriched["background_music_evidence"] = {
            **dict(evidence),
            "music_execution_audit_receipt_artifact": {
                **reference,
                "kind": BACKGROUND_MUSIC_AUDIT_RECEIPT_ARTIFACT_KIND,
            },
        }
        return enriched

    @staticmethod
    def _publish_execution_request(
        *,
        context: Any,
        result: Mapping[str, Any],
        execution_contract: Mapping[str, object],
    ) -> Mapping[str, Any]:
        evidence = result.get("background_music_evidence")
        audit_reference = evidence.get("music_execution_audit_receipt_artifact") if isinstance(evidence, Mapping) else None
        if not isinstance(audit_reference, Mapping):
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED")
        binding = _execution_binding(execution_contract)
        payload = {
            "contract": "background_music_execution_request/v1",
            "music_execution_contract": dict(execution_contract),
            "provider_payload": execution_contract["provider_payload"],
            "audit_receipt_artifact": dict(audit_reference),
            "request_binding": binding,
        }
        encoded = _canonical_json_bytes(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        publish = getattr(context, "publish_bytes", None)
        if not callable(publish):
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED")
        try:
            published = publish(
                kind=BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND,
                data=encoded,
                content_type="application/json",
                expected_sha256=digest,
            )
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED") from error
        if not isinstance(published, Mapping):
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(published)
        enriched = dict(result)
        enriched["background_music_evidence"] = {
            **dict(evidence),
            "music_execution_request_artifact": {
                **reference,
                "kind": BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND,
            },
        }
        return enriched

    @staticmethod
    def _materialize_frozen_execution_request(
        context: Any,
    ) -> tuple[Mapping[str, Any], dict[str, str]]:
        try:
            artifacts = context.artifacts
        except AttributeError as error:
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED") from error
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, Mapping)
            and artifact.get("kind") == BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND
        ]
        if len(matches) != 1 or not callable(getattr(context, "materialize_artifact", None)):
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(matches[0])
        try:
            with context.materialize_artifact(
                BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND,
                artifact_id=reference["artifact_id"],
                sha256=reference["sha256"],
            ) as materialized:
                encoded = materialized.path.read_bytes()
            decoded = json.loads(encoded)
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED") from error
        if (
            hashlib.sha256(encoded).hexdigest() != reference["sha256"]
            or not isinstance(decoded, Mapping)
            or decoded.get("contract") != "background_music_execution_request/v1"
            or not isinstance(decoded.get("music_execution_contract"), Mapping)
            or decoded.get("provider_payload") != decoded["music_execution_contract"].get("provider_payload")
            or not isinstance(decoded.get("request_binding"), Mapping)
        ):
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED")
        return dict(decoded), reference

    @staticmethod
    def _publish_provider_submission(
        *,
        context: Any,
        result: Mapping[str, Any],
        receipt: Mapping[str, object],
        raw_response: bytes,
        audit_receipt: Mapping[str, object],
    ) -> Mapping[str, Any]:
        try:
            raw = json.loads(raw_response)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED") from error
        if not isinstance(raw, Mapping) or raw.get("task_id", raw.get("taskId")) != receipt.get("provider_task_id"):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        publish = getattr(context, "publish_bytes", None)
        if not callable(publish):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        raw_digest = hashlib.sha256(raw_response).hexdigest()
        try:
            raw_published = publish(
                kind=BACKGROUND_MUSIC_PROVIDER_RAW_RESPONSE_ARTIFACT_KIND,
                data=raw_response,
                content_type="application/json",
                expected_sha256=raw_digest,
            )
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED") from error
        if not isinstance(raw_published, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        raw_reference = BackgroundMusicStagePort._contract_artifact_reference(raw_published)
        evidence = result.get("background_music_evidence")
        request_artifact = evidence.get("music_execution_request_artifact") if isinstance(evidence, Mapping) else None
        if not isinstance(request_artifact, Mapping):
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_REQUEST_REQUIRED")
        payload = {
            **dict(receipt),
            "provider_raw_response_artifact": {**raw_reference, "kind": BACKGROUND_MUSIC_PROVIDER_RAW_RESPONSE_ARTIFACT_KIND},
            "audit_receipt_artifact": dict(audit_receipt),
            "execution_request_artifact": dict(request_artifact),
            "music_execution_contract": evidence.get("music_execution_contract"),
            "provider_payload": evidence.get("provider_payload"),
        }
        encoded = _canonical_json_bytes(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        try:
            published = publish(
                kind=BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND,
                data=encoded,
                content_type="application/json",
                expected_sha256=digest,
            )
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED") from error
        if not isinstance(published, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(published)
        evidence = result.get("background_music_evidence")
        enriched = dict(result)
        enriched["background_music_evidence"] = {
            **(dict(evidence) if isinstance(evidence, Mapping) else {}),
            "provider_submission_artifact": {**reference, "kind": BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND},
            "provider_submission_receipt": payload,
        }
        return enriched

    @staticmethod
    def _materialize_provider_json_artifact(
        *,
        context: Any,
        kind: str,
        reference: Mapping[str, object],
    ) -> Mapping[str, Any]:
        try:
            artifact = BackgroundMusicStagePort._contract_artifact_reference(reference)
            with context.materialize_artifact(
                kind,
                artifact_id=artifact["artifact_id"],
                sha256=artifact["sha256"],
            ) as media:
                encoded = media.path.read_bytes()
            decoded = json.loads(encoded)
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED") from error
        if hashlib.sha256(encoded).hexdigest() != artifact["sha256"] or not isinstance(decoded, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        return dict(decoded)

    @staticmethod
    def _materialize_execution_request_reference(
        *,
        context: Any,
        reference: Mapping[str, object],
    ) -> Mapping[str, Any]:
        try:
            artifact = BackgroundMusicStagePort._contract_artifact_reference(reference)
            artifacts = context.artifacts
            if not any(
                isinstance(item, Mapping)
                and item.get("kind") == BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND
                and BackgroundMusicStagePort._contract_artifact_reference(item) == artifact
                for item in artifacts
            ):
                raise ValueError("request artifact unavailable")
            with context.materialize_artifact(
                BACKGROUND_MUSIC_EXECUTION_REQUEST_ARTIFACT_KIND,
                artifact_id=artifact["artifact_id"],
                sha256=artifact["sha256"],
            ) as media:
                encoded = media.path.read_bytes()
            decoded = json.loads(encoded)
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED") from error
        if (
            hashlib.sha256(encoded).hexdigest() != artifact["sha256"]
            or not isinstance(decoded, Mapping)
            or decoded.get("contract") != "background_music_execution_request/v1"
            or not isinstance(decoded.get("music_execution_contract"), Mapping)
            or not isinstance(decoded.get("provider_payload"), Mapping)
            or not isinstance(decoded.get("audit_receipt_artifact"), Mapping)
            or not isinstance(decoded.get("request_binding"), Mapping)
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        return dict(decoded)

    @staticmethod
    def _publish_provider_output(
        *,
        context: Any,
        raw_lookup: bytes,
        task_id: str,
        submission: Mapping[str, Any],
        submission_reference: Mapping[str, str],
    ) -> dict[str, str]:
        try:
            decoded = json.loads(raw_lookup)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED") from error
        if not isinstance(decoded, Mapping) or decoded.get("task_id", decoded.get("taskId")) != task_id:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED")
        publish = getattr(context, "publish_bytes", None)
        if not callable(publish):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED")
        payload = {
            "provider_task_id": task_id,
            "provider_lookup_response": dict(decoded),
            "provider_lookup_response_sha256": hashlib.sha256(raw_lookup).hexdigest(),
            "provider_submission_sha256": hashlib.sha256(_canonical_json_bytes(submission)).hexdigest(),
            "provider_submission_artifact": {
                **dict(submission_reference),
                "kind": BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND,
            },
            "execution_request_artifact": submission.get("execution_request_artifact"),
            "execution_contract_sha256": submission.get("execution_contract_sha256"),
            "seedance_payload_sha256": submission.get("seedance_payload_sha256"),
            "provider_payload": submission.get("provider_payload"),
            "audit_receipt_artifact": submission.get("audit_receipt_artifact"),
        }
        encoded = _canonical_json_bytes(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        try:
            published = publish(
                kind=BACKGROUND_MUSIC_PROVIDER_OUTPUT_ARTIFACT_KIND,
                data=encoded,
                content_type="application/json",
                expected_sha256=digest,
            )
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED") from error
        if not isinstance(published, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_LOOKUP_REQUIRED")
        return {
            **BackgroundMusicStagePort._contract_artifact_reference(published),
            "kind": BACKGROUND_MUSIC_PROVIDER_OUTPUT_ARTIFACT_KIND,
        }

    @staticmethod
    def _materialize_frozen_provider_submission(context: Any) -> tuple[Mapping[str, Any], dict[str, str]]:
        try:
            artifacts = context.artifacts
        except AttributeError as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED") from error
        matches = [item for item in artifacts if isinstance(item, Mapping) and item.get("kind") == BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND]
        if len(matches) != 1 or not callable(getattr(context, "materialize_artifact", None)):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(matches[0])
        try:
            with context.materialize_artifact(BACKGROUND_MUSIC_PROVIDER_SUBMISSION_ARTIFACT_KIND, artifact_id=reference["artifact_id"], sha256=reference["sha256"]) as media:
                encoded = media.path.read_bytes()
            decoded = json.loads(encoded)
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED") from error
        if (
            hashlib.sha256(encoded).hexdigest() != reference["sha256"]
            or not isinstance(decoded, Mapping)
            or not isinstance(decoded.get("provider_task_id"), str)
            or not _is_sha256(decoded.get("provider_raw_response_sha256"))
            or not isinstance(decoded.get("provider_raw_response_artifact"), Mapping)
            or not isinstance(decoded.get("audit_receipt_artifact"), Mapping)
            or not isinstance(decoded.get("execution_request_artifact"), Mapping)
            or not isinstance(decoded.get("music_execution_contract"), Mapping)
            or not isinstance(decoded.get("provider_payload"), Mapping)
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_SUBMISSION_RECEIPT_REQUIRED")
        return dict(decoded), reference

    @staticmethod
    def _validate_post_audit_evidence(
        *,
        result: Mapping[str, Any],
        frozen_audit_receipt: tuple[Mapping[str, Any], dict[str, str]] | None,
    ) -> None:
        if frozen_audit_receipt is None:
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED")
        receipt, expected_reference = frozen_audit_receipt
        evidence = result.get("background_music_evidence")
        execution_contract = evidence.get("music_execution_contract") if isinstance(evidence, Mapping) else None
        provider_payload = evidence.get("provider_payload") if isinstance(evidence, Mapping) else None
        observed_reference = (
            evidence.get("music_execution_audit_receipt_artifact") if isinstance(evidence, Mapping) else None
        )
        if (
            not isinstance(execution_contract, Mapping)
            or not isinstance(provider_payload, Mapping)
            or not isinstance(observed_reference, Mapping)
        ):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_MISMATCH")
        try:
            _validate_frozen_execution_contract(execution_contract)
        except ValueError as error:
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_MISMATCH") from error
        if (
            BackgroundMusicStagePort._contract_artifact_reference(observed_reference) != expected_reference
            or execution_contract.get("provider_payload") != provider_payload
            or receipt
            != BackgroundMusicStagePort._audit_receipt_payload(
                execution_contract=execution_contract,
                frozen_timeline_reference={
                    "artifact_id": "not-used-for-binding",
                    "sha256": receipt.get("music_timeline_contract_sha256"),
                },
            )
        ):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_MISMATCH")
        BackgroundMusicStagePort._validate_audit_binding(
            evidence=evidence,
            execution_contract=execution_contract,
        )

    @staticmethod
    def _materialize_frozen_audit_receipt(
        context: Any,
    ) -> tuple[Mapping[str, Any], dict[str, str]]:
        try:
            artifacts = context.artifacts
        except AttributeError as error:
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED") from error
        if not isinstance(artifacts, (tuple, list)):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED")
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, Mapping)
            and artifact.get("kind") == BACKGROUND_MUSIC_AUDIT_RECEIPT_ARTIFACT_KIND
        ]
        if len(matches) != 1 or not callable(getattr(context, "materialize_artifact", None)):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(matches[0])
        try:
            with context.materialize_artifact(
                BACKGROUND_MUSIC_AUDIT_RECEIPT_ARTIFACT_KIND,
                artifact_id=reference["artifact_id"],
                sha256=reference["sha256"],
            ) as materialized:
                encoded = materialized.path.read_bytes()
        except Exception as error:
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_REQUIRED") from error
        if hashlib.sha256(encoded).hexdigest() != reference["sha256"]:
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_MISMATCH")
        try:
            decoded = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_MISMATCH") from error
        if (
            not isinstance(decoded, Mapping)
            or decoded.get("contract") != BACKGROUND_MUSIC_AUDIT_RECEIPT_V1
            or not _is_sha256(decoded.get("execution_contract_sha256"))
            or not _is_sha256(decoded.get("seedance_payload_sha256"))
            or not _is_sha256(decoded.get("music_timeline_contract_sha256"))
            or (
                decoded.get("performance_line_contract_sha256") is not None
                and not _is_sha256(decoded.get("performance_line_contract_sha256"))
            )
        ):
            raise ValueError("BACKGROUND_MUSIC_AUDIT_RECEIPT_MISMATCH")
        return dict(decoded), reference

    @staticmethod
    def _materialized_mix_bytes(context: Any) -> Any:
        music_context = _background_music_context(context)

        def materialize(kind: str, reference: object) -> bytes:
            try:
                if kind == "uploaded_audio":
                    with music_context.materialize_slot("background_music") as media:
                        return media.path.read_bytes()
                if (
                    not isinstance(reference, Mapping)
                    or not isinstance(reference.get("kind"), str)
                    or not reference["kind"]
                ):
                    raise ValueError("media reference required")
                artifact = BackgroundMusicStagePort._contract_artifact_reference(reference)
                with context.materialize_artifact(
                    str(reference.get("kind") or ""),
                    artifact_id=artifact["artifact_id"],
                    sha256=artifact["sha256"],
                ) as media:
                    return media.path.read_bytes()
            except Exception as error:
                raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED") from error

        return materialize

    @staticmethod
    def _materialized_mix_pcm(context: Any) -> Any:
        music_context = _background_music_context(context)

        def materialize(kind: str, reference: object) -> bytes:
            try:
                if kind == "uploaded_audio":
                    with music_context.materialize_slot("background_music") as media:
                        return BackgroundMusicStagePort._decode_audio_pcm(
                            media.path,
                            require_default_audio_stream=False,
                        )
                if kind not in {"final_audio", "final_video"} or not isinstance(reference, Mapping):
                    raise ValueError("media reference required")
                artifact = BackgroundMusicStagePort._contract_artifact_reference(reference)
                with context.materialize_artifact(
                    str(reference.get("kind") or ""),
                    artifact_id=artifact["artifact_id"],
                    sha256=artifact["sha256"],
                ) as media:
                    return BackgroundMusicStagePort._decode_audio_pcm(
                        media.path,
                        require_default_audio_stream=kind == "final_video",
                    )
            except Exception as error:
                raise ValueError("BACKGROUND_MUSIC_MEDIA_MATERIALIZATION_REQUIRED") from error

        return materialize

    @staticmethod
    def _materialized_video_timing(context: Any) -> Any:
        def materialize(reference: object) -> Mapping[str, int]:
            if not isinstance(reference, Mapping):
                raise ValueError("media reference required")
            artifact = BackgroundMusicStagePort._contract_artifact_reference(reference)
            with context.materialize_artifact(
                str(reference.get("kind") or ""),
                artifact_id=artifact["artifact_id"],
                sha256=artifact["sha256"],
            ) as media:
                ffprobe = shutil.which("ffprobe")
                if ffprobe is None:
                    raise ValueError("ffprobe required")
                completed = subprocess.run(
                    [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=start_time,duration", "-of", "json", str(media.path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                payload = json.loads(completed.stdout)
                streams = payload.get("streams") if isinstance(payload, Mapping) else None
                if completed.returncode != 0 or not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], Mapping):
                    raise ValueError("audio timing unavailable")
                return {
                    "start_ms": round(float(streams[0]["start_time"]) * 1000),
                    "duration_ms": round(float(streams[0]["duration"]) * 1000),
                }

        return materialize

    @staticmethod
    def _decode_audio_pcm(path: Any, *, require_default_audio_stream: bool) -> bytes:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if ffmpeg is None or ffprobe is None:
            raise ValueError("ffmpeg required")
        probed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        try:
            stream_payload = json.loads(probed.stdout)
            streams = stream_payload.get("streams") if isinstance(stream_payload, Mapping) else None
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("audio stream probe failed") from error
        if (
            probed.returncode != 0
            or not isinstance(streams, list)
            or len(streams) != 1
            or not isinstance(streams[0], Mapping)
            or (
                require_default_audio_stream
                and (
                    not isinstance(streams[0].get("disposition"), Mapping)
                    or streams[0]["disposition"].get("default") != 1
                )
            )
        ):
            raise ValueError("single default audio stream required")
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-c:a",
                "pcm_s16le",
                "-f",
                "s16le",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout:
            raise ValueError("audio decode failed")
        return completed.stdout

    @staticmethod
    def _materialize_frozen_timeline_contract(
        context: Any,
    ) -> tuple[Mapping[str, Any], dict[str, str]] | None:
        try:
            artifacts = context.artifacts
        except AttributeError:
            return None
        if not isinstance(artifacts, (tuple, list)):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, Mapping) and artifact.get("kind") == MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND
        ]
        if len(matches) != 1 or not callable(getattr(context, "materialize_artifact", None)):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(matches[0])
        try:
            with context.materialize_artifact(
                MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND,
                artifact_id=reference["artifact_id"],
                sha256=reference["sha256"],
            ) as materialized:
                encoded = materialized.path.read_bytes()
        except Exception as error:
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if hashlib.sha256(encoded).hexdigest() != reference["sha256"]:
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH")
        try:
            decoded = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH") from error
        if not isinstance(decoded, Mapping):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH")
        return dict(decoded), reference

    @staticmethod
    def _materialize_frozen_performance_line_contract(
        context: Any,
    ) -> tuple[Mapping[str, Any], dict[str, str]]:
        try:
            artifacts = context.artifacts
        except AttributeError as error:
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if not isinstance(artifacts, (tuple, list)):
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_REQUIRED")
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, Mapping) and artifact.get("kind") == PERFORMANCE_LINE_CONTRACT_ARTIFACT_KIND
        ]
        if len(matches) != 1 or not callable(getattr(context, "materialize_artifact", None)):
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(matches[0])
        try:
            with context.materialize_artifact(
                PERFORMANCE_LINE_CONTRACT_ARTIFACT_KIND,
                artifact_id=reference["artifact_id"],
                sha256=reference["sha256"],
            ) as materialized:
                encoded = materialized.path.read_bytes()
        except Exception as error:
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if hashlib.sha256(encoded).hexdigest() != reference["sha256"]:
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_MISMATCH")
        try:
            decoded = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_MISMATCH") from error
        if not isinstance(decoded, Mapping):
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_MISMATCH")
        return dict(decoded), reference

    @staticmethod
    def _contract_artifact_reference(value: Mapping[str, object]) -> dict[str, str]:
        artifact_id = value.get("artifact_id")
        sha256 = value.get("sha256")
        if not isinstance(artifact_id, str) or not artifact_id or not _is_sha256(sha256):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        return {"artifact_id": artifact_id, "sha256": sha256}

    @staticmethod
    def _publish_frozen_timeline_contract(
        *,
        context: Any,
        result: Mapping[str, Any],
        contract: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        publish = getattr(context, "publish_bytes", None)
        if not callable(publish):
            return result
        encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        try:
            published = publish(
                kind=MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND,
                data=encoded,
                content_type="application/json",
                expected_sha256=digest,
            )
        except Exception as error:
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if not isinstance(published, Mapping):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(published)
        evidence = result.get("background_music_evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
        enriched = dict(result)
        enriched["background_music_evidence"] = {
            **dict(evidence),
            "music_timeline_contract_artifact": {
                **reference,
                "kind": MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND,
            },
        }
        return enriched

    @staticmethod
    def _validate_frozen_timeline_reference(
        *,
        result: Mapping[str, Any],
        contract: Mapping[str, Any],
        frozen_contract: tuple[Mapping[str, Any], dict[str, str]] | None,
    ) -> None:
        if frozen_contract is None:
            return
        frozen, expected_reference = frozen_contract
        evidence = result.get("background_music_evidence")
        reference = evidence.get("music_timeline_contract_artifact") if isinstance(evidence, Mapping) else None
        if not isinstance(reference, Mapping):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        observed_reference = BackgroundMusicStagePort._contract_artifact_reference(reference)
        if observed_reference != expected_reference or _canonical_json_bytes(contract) != _canonical_json_bytes(frozen):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH")

    @staticmethod
    def _validate_music_timeline(*, contract: Mapping[str, Any], uploaded: Mapping[str, Any]) -> None:
        windows = contract.get("windows")
        singers = contract.get("visible_singer_regions")
        meaningful_silence = contract.get("meaningful_silence_output_intervals")
        output_duration_ms = contract.get("output_duration_ms")
        try:
            available_ms = round(float(uploaded.get("duration_seconds")) * 1000)
        except (TypeError, ValueError) as error:
            raise ValueError("BACKGROUND_MUSIC_DURATION_INSUFFICIENT") from error
        if (
            available_ms <= 0
            or not isinstance(windows, list)
            or not windows
            or not isinstance(singers, list)
            or not isinstance(meaningful_silence, list)
            or isinstance(output_duration_ms, bool)
            or not isinstance(output_duration_ms, int)
            or output_duration_ms <= 0
        ):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
        prior_source_end = -1
        prior_uploaded_end: int | None = None
        intervals: list[tuple[int, int, str]] = []
        for window in windows:
            if not isinstance(window, Mapping):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
            values = tuple(
                window.get(field)
                for field in (
                    "source_start_frame",
                    "source_end_frame",
                    "output_start_frame",
                    "output_end_frame",
                    "uploaded_start_ms",
                    "uploaded_end_ms",
                    "output_start_ms",
                    "output_end_ms",
                )
            )
            if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
            source_start, source_end, output_start, output_end, uploaded_start, uploaded_end, output_start_ms, output_end_ms = values
            for field in (
                "source_entry",
                "source_exit",
                "fade_in",
                "fade_out",
                "silence_before",
                "silence_after",
                "transition",
            ):
                event = window.get(field)
                bounds = (
                    event.get("source_start_ms") if isinstance(event, Mapping) else None,
                    event.get("source_end_ms") if isinstance(event, Mapping) else None,
                    event.get("output_start_ms") if isinstance(event, Mapping) else None,
                    event.get("output_end_ms") if isinstance(event, Mapping) else None,
                )
                if (
                    not isinstance(event, Mapping)
                    or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in bounds)
                    or bounds[1] < bounds[0]
                    or bounds[3] < bounds[2]
                    or bounds[0] < uploaded_start
                    or bounds[1] > uploaded_end
                    or bounds[2] < output_start_ms
                    or bounds[3] > output_end_ms
                ):
                    raise ValueError("MUSIC_TIMING_EVIDENCE_REQUIRED")
            if (
                source_start < 0
                or source_end <= source_start
                or source_start != output_start
                or source_end != output_end
                or source_start < prior_source_end
                or output_start_ms < 0
                or output_end_ms <= output_start_ms
                or output_end_ms > output_duration_ms
            ):
                raise ValueError("BACKGROUND_MUSIC_TIMELINE_MISMATCH")
            if (
                uploaded_start < 0
                or uploaded_end <= uploaded_start
                or uploaded_end > available_ms
                or (prior_uploaded_end is not None and uploaded_start != prior_uploaded_end)
            ):
                raise ValueError("BACKGROUND_MUSIC_DURATION_INSUFFICIENT")
            prior_source_end = source_end
            prior_uploaded_end = uploaded_end
            intervals.append((output_start_ms, output_end_ms, "music"))
        for silence in meaningful_silence:
            if not isinstance(silence, Mapping):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
            start, end = silence.get("output_start_ms"), silence.get("output_end_ms")
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or end > output_duration_ms
            ):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
            intervals.append((start, end, "silence"))
        cursor = 0
        for start, end, _ in sorted(intervals):
            if start != cursor:
                raise ValueError("BACKGROUND_MUSIC_TIMELINE_MISMATCH")
            cursor = end
        if cursor != output_duration_ms:
            raise ValueError("BACKGROUND_MUSIC_TIMELINE_MISMATCH")

    @staticmethod
    def _validate_mix_receipt(
        *,
        contract: Mapping[str, Any],
        uploaded: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        if (
            receipt.get("passed") is not True
            or receipt.get("uploaded_audio_sha256") != uploaded.get("sha256")
            or not _is_sha256(receipt.get("final_audio_sha256"))
        ):
            raise ValueError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
        expected_windows = contract.get("windows")
        observed_windows = receipt.get("window_receipts")
        if not isinstance(expected_windows, list) or not isinstance(observed_windows, list) or len(expected_windows) != len(observed_windows):
            raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        fields = (
            "source_start_frame",
            "source_end_frame",
            "output_start_frame",
            "output_end_frame",
            "uploaded_start_ms",
            "uploaded_end_ms",
        )
        for expected, observed in zip(expected_windows, observed_windows):
            if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
                raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
            if any(observed.get(field) != expected.get(field) for field in fields) or not _is_sha256(observed.get("fragment_sha256")):
                raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
            if any(observed.get(flag) is not False for flag in ("looped", "time_stretched", "pitch_shifted", "generated_substitute")):
                raise ValueError("BACKGROUND_MUSIC_TRANSFORM_FORBIDDEN")

    @staticmethod
    def _validate_singing_qa(*, contract: Mapping[str, Any], singing_qa: object) -> None:
        raw_regions = contract.get("visible_singer_regions")
        if not isinstance(raw_regions, list) or any(not isinstance(region, Mapping) for region in raw_regions):
            raise ValueError("SINGING_ALIGNMENT_REQUIRED")
        visible = [region for region in raw_regions if region.get("visible") is True]
        if not isinstance(singing_qa, Mapping):
            raise ValueError("SINGING_ALIGNMENT_REQUIRED")
        observed = singing_qa.get("regions")
        if not visible:
            if (
                singing_qa.get("status") != "skipped"
                or singing_qa.get("reason") != "no_visible_singing_person"
                or observed != []
            ):
                raise ValueError("SINGING_ALIGNMENT_REQUIRED")
            return
        if singing_qa.get("status") != "passed" or not isinstance(observed, list) or len(observed) != len(visible):
            raise ValueError("SINGING_ALIGNMENT_REQUIRED")
        for expected, receipt in zip(visible, observed):
            if not isinstance(receipt, Mapping) or receipt.get("region_id") != expected.get("region_id"):
                raise ValueError("SINGING_ALIGNMENT_REQUIRED")
            alignment = receipt.get("lyrics_phoneme_alignment")
            if (
                not isinstance(alignment, Mapping)
                or alignment.get("passed") is not True
                or not _is_sha256(alignment.get("receipt_sha256"))
            ):
                raise ValueError("SINGING_ALIGNMENT_REQUIRED")
            lip_sync = receipt.get("lip_sync_qa")
            if (
                not isinstance(lip_sync, Mapping)
                or lip_sync.get("passed") is not True
                or not _is_sha256(lip_sync.get("receipt_sha256"))
            ):
                raise ValueError("SINGING_LIP_SYNC_QA_REQUIRED")

    @staticmethod
    def _validate_no_lyric_lip_sync(*, singing_qa: object) -> None:
        if (
            not isinstance(singing_qa, Mapping)
            or singing_qa.get("status") != "skipped"
            or singing_qa.get("reason") != "no_lyric_lip_sync"
            or singing_qa.get("regions") != []
        ):
            raise ValueError("NO_LYRIC_LIP_SYNC_REQUIRED")


class DeploymentBackgroundMusicExecutionAdapter:
    """Install real deployment StagePorts for optional music jobs only."""

    def __init__(self, *, music_stage_ports: Mapping[str, Any], provider_adapter: Any) -> None:
        if set(music_stage_ports) != set(MUSIC_STAGE_PORTS):
            raise ValueError("BACKGROUND_MUSIC_STAGE_PORTS_INVALID")
        if any(not callable(getattr(port, "run", port)) for port in music_stage_ports.values()):
            raise ValueError("BACKGROUND_MUSIC_STAGE_PORTS_INVALID")
        self._music_stage_ports = dict(music_stage_ports)
        self._provider_adapter = _VerifiedBackgroundMusicProviderAdapter(provider_adapter)
        self._installed = False

    def install(
        self,
        *,
        job_store: Any,
        work_queue: Any,
        worker_manager: Any,
        stage_driver: Any,
    ) -> BackgroundMusicStageDriver:
        if not callable(getattr(stage_driver, "enqueue_next", None)):
            raise ValueError("BACKGROUND_MUSIC_STAGE_DRIVER_INVALID")
        canonical_ports = getattr(worker_manager, "stage_ports", None)
        if not isinstance(canonical_ports, Mapping) or set(MUSIC_STAGE_PORTS) - set(canonical_ports):
            raise ValueError("BACKGROUND_MUSIC_STAGE_PORTS_INVALID")
        capability_ports = getattr(worker_manager, "capability_ports", None)
        if (
            not isinstance(capability_ports, Mapping)
            or capability_ports.get("provider_adapter") is not self._provider_adapter.adapter
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_ADAPTER_INVALID")
        wrapped = dict(canonical_ports)
        for stage in MUSIC_STAGE_PORTS:
            wrapped[stage] = BackgroundMusicStagePort(
                stage=stage,
                delegate=canonical_ports[stage],
                music_delegate=self._music_stage_ports[stage],
                provider_adapter=self._provider_adapter.adapter,
            )
        worker_manager.stage_ports = wrapped
        self._installed = True
        return BackgroundMusicStageDriver(job_store, work_queue)

    def validate_startup(self) -> None:
        if not self._installed:
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_UNAVAILABLE")
        self._provider_adapter.validate_integrity()
        declared: set[str] = set()
        for port in self._music_stage_ports.values():
            capabilities = getattr(port, "background_music_capabilities", None)
            if not callable(capabilities):
                raise ValueError("BACKGROUND_MUSIC_CAPABILITY_DECLARATION_REQUIRED")
            values = capabilities()
            if not isinstance(values, (set, frozenset, tuple, list)) or any(
                not isinstance(value, str) for value in values
            ):
                raise ValueError("BACKGROUND_MUSIC_CAPABILITY_DECLARATION_REQUIRED")
            declared.update(values)
        if not REQUIRED_MUSIC_CAPABILITIES.issubset(declared):
            raise ValueError("BACKGROUND_MUSIC_CAPABILITY_DECLARATION_REQUIRED")

    def validate_manifest(self, *, background_music: Mapping[str, object]) -> None:
        if not isinstance(background_music, Mapping):
            raise ValueError("BACKGROUND_MUSIC_MANIFEST_INVALID")
        expected = {
            "provider_route": "seedance_audio_reference",
            "provider_asset_type": "Audio",
            "provider_content_item_type": "audio_url",
            "prompt_reference_tag": "@Audio1",
            "forbidden_provider_field": "reference_audios",
            "final_audio_source": "uploaded_exact_audio",
            "allow_loop_or_time_stretch": False,
        }
        if any(background_music.get(key) != value for key, value in expected.items()):
            raise ValueError("BACKGROUND_MUSIC_MANIFEST_INVALID")

        content_type = background_music.get("content_type")
        digest = background_music.get("sha256")
        if (
            not isinstance(content_type, str)
            or not content_type.casefold().startswith("audio/")
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("BACKGROUND_MUSIC_MANIFEST_INVALID")


class BackgroundMusicStageDriver:
    """Canonical queue bridge with music-aware plan selection.

    Non-music jobs use the unmodified plan returned by ``build_stage_plan``.
    Music jobs use the same existing stage names and approval checks as normal
    generated-media jobs, so checkpoint, dedupe, Provider, and ACK semantics
    remain owned by the packaged worker.
    """

    background_music_execution_contract = MUSIC_EXECUTION_CONTRACT

    def __init__(self, job_store: Any, work_queue: Any) -> None:
        self.job_store = job_store
        self.work_queue = work_queue

    def enqueue_next(self, job_id: str) -> WorkMessage | None:
        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            return None
        manifest = getattr(snapshot, "slots_manifest", None)
        if not isinstance(manifest, Mapping):
            return None
        plan = build_background_music_stage_plan(manifest, review_route=getattr(snapshot, "review_route", None))
        music_enabled = is_background_music_manifest(manifest)
        language_only = bool(
            isinstance(manifest.get("admission"), Mapping)
            and manifest["admission"].get("language_only")
        )
        if music_enabled and language_only:
            raise ValueError("BACKGROUND_MUSIC_LANGUAGE_ONLY_INVALID")

        for item in plan:
            stage = str(item.get("name") or "")
            if stage == "await_script_approval":
                if not getattr(snapshot, "approved_script_sha256", None):
                    return None
                continue
            if stage == "await_storyboard_approval":
                if not getattr(snapshot, "approved_storyboard_sha256", None):
                    return None
                continue
            if stage not in EXECUTABLE_STAGES:
                continue
            if stage == "build_script" and not language_only and getattr(snapshot, "review_route", None) == "route_1" and not getattr(snapshot, "approved_script_sha256", None):
                return None
            if stage == "generate_storyboards" and not language_only and getattr(snapshot, "review_route", None) == "route_2" and not getattr(snapshot, "approved_script_sha256", None):
                return None
            if stage in {"compile_seedance20_prompt", "audit_seedance_request", "submit_provider_video", "wait_provider_video", "splice_timeline", "run_qc"} and not language_only and not getattr(snapshot, "approved_storyboard_sha256", None):
                return None
            checkpoint = self.job_store.get_stage_checkpoint(job_id, stage)
            if checkpoint is not None and checkpoint.status == "SUCCEEDED":
                continue
            if checkpoint is not None and checkpoint.status == "CLAIMED":
                return None
            dedupe_key = _dedupe(job_id, stage, snapshot)
            message = WorkMessage(job_id, stage, snapshot.version, dedupe_key)
            self.work_queue.enqueue(
                job_id=message.job_id,
                stage=message.stage,
                expected_version=message.expected_version,
                dedupe_key=message.dedupe_key,
            )
            return message
        return None


__all__ = [
    "BackgroundMusicStageDriver",
    "BackgroundMusicStagePort",
    "DeploymentBackgroundMusicExecutionAdapter",
    "MUSIC_EXECUTION_CONTRACT",
    "MUSIC_STAGE_PORTS",
    "REQUIRED_MUSIC_CAPABILITIES",
    "build_background_music_stage_plan",
    "is_background_music_manifest",
]
