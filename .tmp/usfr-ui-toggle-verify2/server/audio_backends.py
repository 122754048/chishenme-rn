"""Evidence-bound audio event classifier adapters.

The public workflow keeps audio extraction and ASR in the existing stage.  This
module supplies the production boundary for Foley, ambience, music, and
meaningful-silence classification without allowing a worker-local path or an
unverified callback to become source evidence.  The classifier receives the
exact extracted WAV bytes, a SHA-256 of those bytes, and a pinned model
identity; the response is accepted only when all three are echoed correctly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .errors import ReplicationError


class AudioBackendUnavailable(ReplicationError):
    """The configured audio evidence service is unavailable or untrustworthy."""

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            "AUDIO_BACKEND_UNAVAILABLE",
            message,
            category="capability",
            retryable=True,
            user_action_required=True,
            details=dict(details or {}),
            http_status=503,
        )


class OptionalInputExtension(Protocol):
    """A capability-gated public input-contract-v2 extension."""

    @property
    def extension_id(self) -> str: ...

    @property
    def enabled(self) -> bool: ...


class MusicTimelineAnalyzer(Protocol):
    """Evidence-bound analyzer for the uploaded music timeline."""

    def analyze_music_timeline(
        self,
        audio_bytes: bytes,
        *,
        request_sha256: str,
    ) -> Mapping[str, Any]: ...


class BackgroundMusicCompositor(Protocol):
    """Evidence-bound compositor for validated uploaded music windows."""

    def compose_background_music(
        self,
        source_wav: bytes,
        *,
        timeline: Mapping[str, Any],
        request_sha256: str,
    ) -> Mapping[str, Any]: ...


def input_contract_v2_extensions(
    *,
    music_execution_available: bool,
) -> Mapping[str, Mapping[str, Any]]:
    """Describe public optional extensions without claiming an unavailable port.

    Intake may accept a background-music file independently of deployment
    readiness.  The execution driver checks this capability before attempting
    any provider or compositor work, so an unavailable adapter is a truthful
    fail-closed state rather than a hidden global feature switch.
    """

    availability = "enabled" if music_execution_available else "capability_unavailable"
    return {
        "background_music": {
            "extension_id": "input_contract_v2.background_music",
            "enabled": music_execution_available,
            "public_input": True,
            "required_capability": "background_music_execution/v1",
            "availability": availability,
        }
    }


def _audio_windows(value: Any, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise AudioBackendUnavailable(f"{field} must be an array of window objects")
    return [dict(item) for item in value]


def validate_final_audio_qc(
    *,
    contract: Mapping[str, Any],
    evidence: Mapping[str, Any],
    final_output_sha256: str,
) -> dict[str, Any]:
    final_sha = _sha256_model(final_output_sha256, "final_output_sha256")
    if str(evidence.get("final_output_sha256") or "").lower() != final_sha:
        raise AudioBackendUnavailable("final audio QC is not bound to the current final output")
    expected_language = contract.get("output_language")
    if expected_language != evidence.get("output_language"):
        raise AudioBackendUnavailable("final audio QC output language does not match")
    expected_lines = _audio_windows(
        contract.get("exact_line_windows", contract.get("segments")),
        "exact_line_windows",
    )
    observed_lines = _audio_windows(
        evidence.get("exact_line_windows"),
        "evidence.exact_line_windows",
    )
    if len(expected_lines) != len(observed_lines):
        raise AudioBackendUnavailable("final audio QC exact-line window count differs")
    supported_delivery = {
        "normal",
        "whisper",
        "light_voice",
        "soft",
        "energetic",
        "urgent",
        "conversational",
    }
    lip_sync_scores: list[float] = []
    for expected, observed in zip(expected_lines, observed_lines):
        for field in ("start_us", "end_us", "text", "meaning", "delivery", "visible_speaker"):
            if expected.get(field) != observed.get(field):
                raise AudioBackendUnavailable(
                    f"final audio QC exact-line {field} differs from the contract"
                )
        delivery = str(expected.get("delivery") or "normal")
        if delivery not in supported_delivery:
            raise AudioBackendUnavailable("final audio QC delivery label is unsupported")
        if expected.get("visible_speaker") is True:
            try:
                lip_sync = float(observed.get("lip_sync_match_percent"))
            except (TypeError, ValueError) as exc:
                raise AudioBackendUnavailable(
                    "visible-speaker line requires lip-sync evidence"
                ) from exc
            if lip_sync != 100:
                raise AudioBackendUnavailable(
                    "visible-speaker lip-sync match must equal 100"
                )
            lip_sync_scores.append(lip_sync)
    for field in ("foley_windows", "ambience_windows", "silence_windows"):
        expected = _audio_windows(contract.get(field), field)
        observed = _audio_windows(evidence.get(field), f"evidence.{field}")
        if expected != observed:
            raise AudioBackendUnavailable(f"final audio QC {field} differs from the contract")
    unexpected_silence = _audio_windows(
        evidence.get("unexpected_silence_windows"),
        "unexpected_silence_windows",
    )
    if unexpected_silence:
        raise AudioBackendUnavailable("final audio QC detected unexpected silence")
    try:
        integrated_lufs = float(evidence.get("integrated_lufs"))
        true_peak_dbfs = float(evidence.get("true_peak_dbfs"))
        boundary_jump = float(evidence.get("max_boundary_sample_jump"))
        start_offset_us = abs(int(evidence.get("stream_start_offset_us")))
        terminal_drift_us = abs(int(evidence.get("terminal_drift_us")))
    except (TypeError, ValueError) as exc:
        raise AudioBackendUnavailable("final audio QC measurements are invalid") from exc
    if not -20.0 <= integrated_lufs <= -12.0:
        raise AudioBackendUnavailable("final audio QC integrated loudness is out of range")
    if true_peak_dbfs > -1.0:
        raise AudioBackendUnavailable("final audio QC true peak is unsafe")
    if boundary_jump > 0.6:
        raise AudioBackendUnavailable("final audio QC boundary sample jump is unsafe")
    tolerance_us = int(contract.get("av_tolerance_us") or 50_000)
    if start_offset_us > tolerance_us:
        raise AudioBackendUnavailable("final audio QC stream start offset is too large")
    if terminal_drift_us > tolerance_us:
        raise AudioBackendUnavailable("final audio QC terminal A/V drift is too large")
    return {
        "schema_version": "final-audio-qc/v1",
        "passed": True,
        "final_output_sha256": final_sha,
        "output_language": expected_language,
        "exact_line_match_percent": 100,
        "delivery_match_percent": 100,
        "lip_sync_match_percent": 100 if lip_sync_scores else None,
        "foley_match_percent": 100,
        "ambience_match_percent": 100,
        "silence_match_percent": 100,
        "integrated_lufs": integrated_lufs,
        "true_peak_dbfs": true_peak_dbfs,
        "max_boundary_sample_jump": boundary_jump,
        "stream_start_offset_us": start_offset_us,
        "terminal_drift_us": terminal_drift_us,
        "repair_policy": "evidence_only_no_padding_trim_or_rezero",
    }


def validate_source_audio_performance_qc(
    *,
    remux_receipt: Mapping[str, Any],
    evidence: Mapping[str, Any],
    final_output_sha256: str,
) -> dict[str, Any]:
    """Fail closed on source-audio global-position and performance evidence.

    Audio byte selection is proved by the deterministic remux receipt; lip and
    beat evidence remains an independent evaluator input.  Neither a provider
    self-report nor a generic "audio passed" boolean can satisfy this gate.
    """

    final_sha = _sha256_model(final_output_sha256, "final_output_sha256")
    if remux_receipt.get("schema_version") != "source-audio-performance-remux/v1":
        raise AudioBackendUnavailable("source audio performance remux receipt has an unsupported schema")
    if str(remux_receipt.get("final_output_sha256") or "").lower() != final_sha:
        raise AudioBackendUnavailable("source audio performance remux receipt is not bound to the final output")
    if evidence.get("schema_version") != "source-audio-performance-qc/v1":
        raise AudioBackendUnavailable("source audio performance QC evidence has an unsupported schema")
    for field in ("final_output_sha256", "source_media_sha256", "source_audio_sha256"):
        expected = str(remux_receipt.get(field) or "").lower() if field != "final_output_sha256" else final_sha
        if str(evidence.get(field) or "").lower() != expected:
            raise AudioBackendUnavailable(f"source audio performance QC {field} does not match the remux receipt")
    if str(evidence.get("remux_request_sha256") or "").lower() != str(remux_receipt.get("request_sha256") or "").lower():
        raise AudioBackendUnavailable("source audio performance QC is not bound to the remux request")
    _sha256_model(str(evidence.get("performance_line_contract_sha256") or ""), "performance_line_contract_sha256")
    expected_regions = remux_receipt.get("regions")
    observed_regions = evidence.get("regions")
    if not isinstance(expected_regions, list) or not isinstance(observed_regions, list) or len(expected_regions) != len(observed_regions):
        raise AudioBackendUnavailable("source audio performance QC region coverage differs")
    generated_ids: list[str] = []
    for expected, observed in zip(expected_regions, observed_regions):
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            raise AudioBackendUnavailable("source audio performance QC region is invalid")
        mode = str(expected.get("audio_mode") or "")
        fields = ("region_id", "audio_mode", "source_start_us", "source_end_us") if mode == "source_master" else ("region_id", "audio_mode", "opaque_media_sha256")
        if any(expected.get(field) != observed.get(field) for field in fields):
            raise AudioBackendUnavailable("source audio performance QC region differs from the remux receipt")
        if mode == "source_master":
            generated_ids.append(str(expected.get("region_id") or ""))
    def errors(field: str, *, limit: int) -> None:
        values = evidence.get(field)
        if not isinstance(values, list):
            raise AudioBackendUnavailable(f"source audio performance QC {field} is missing")
        indexed: dict[str, Mapping[str, Any]] = {}
        for item in values:
            if not isinstance(item, Mapping):
                raise AudioBackendUnavailable(f"source audio performance QC {field} is invalid")
            region_id = str(item.get("region_id") or "")
            if not region_id or region_id in indexed:
                raise AudioBackendUnavailable(f"source audio performance QC {field} has duplicate regions")
            indexed[region_id] = item
        if set(indexed) != set(generated_ids):
            raise AudioBackendUnavailable(f"source audio performance QC {field} coverage differs")
        for region_id in generated_ids:
            try:
                error_ms = float(indexed[region_id].get("error_ms"))
            except (TypeError, ValueError) as exc:
                raise AudioBackendUnavailable(f"source audio performance QC {field} error is invalid") from exc
            if error_ms < 0 or error_ms > limit:
                label = "lip-sync" if field == "lip_sync_windows" else "beat-action"
                raise AudioBackendUnavailable(f"source audio performance QC {label} drift exceeds {limit}ms")
    errors("lip_sync_windows", limit=120)
    errors("beat_action_windows", limit=160)
    if evidence.get("forbidden_operations_detected") not in ([], (), None):
        raise AudioBackendUnavailable("source audio performance QC detected a forbidden splice operation")
    try:
        start_offset = abs(int(evidence.get("stream_start_offset_us")))
        terminal_drift = abs(int(evidence.get("terminal_drift_us")))
    except (TypeError, ValueError) as exc:
        raise AudioBackendUnavailable("source audio performance QC A/V timing is invalid") from exc
    if start_offset > 50_000 or terminal_drift > 50_000:
        raise AudioBackendUnavailable("source audio performance QC A/V timing exceeds 50ms")
    return {
        "schema_version": "source-audio-performance-qc/v1",
        "passed": True,
        "final_output_sha256": final_sha,
        "source_audio_sha256": str(remux_receipt["source_audio_sha256"]),
        "source_media_sha256": str(remux_receipt["source_media_sha256"]),
        "remux_request_sha256": str(remux_receipt["request_sha256"]),
        "lip_sync_max_error_ms": 120,
        "beat_action_max_error_ms": 160,
        "forbidden_operations": list(remux_receipt.get("forbidden_operations") or []),
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_model(value: str, field: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return digest


def _project_segments(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    scalar_fields = ("segment_id", "start_ms", "end_ms", "text", "speaker", "confidence")
    word_fields = ("word", "text", "start_ms", "end_ms", "probability", "confidence")
    for item in values:
        if not isinstance(item, Mapping):
            continue
        record = {field: item[field] for field in scalar_fields if field in item}
        words = item.get("words")
        if isinstance(words, list):
            record["words"] = [
                {field: word[field] for field in word_fields if field in word}
                for word in words
                if isinstance(word, Mapping)
            ]
        projected.append(record)
    return projected


def _project_silence(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = ("start_ms", "end_ms", "kind", "semantic_meaning")
    return [
        {field: item[field] for field in fields if field in item}
        for item in values
        if isinstance(item, Mapping)
    ]


class EvidenceBoundHttpAudioEventBackend:
    """Call a deployment-owned audio classifier with immutable evidence checks.

    The object is intentionally callable so it can be injected into the
    existing ``WhisperAsrTranscriber`` port.  ``evidence_bound`` is a trust
    marker consumed by production capability validation; a bare lambda cannot
    satisfy that boundary.
    """

    evidence_bound = True
    capability_kind = "audio_event_classifier"

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        model_sha256: str,
        api_token: str | None = None,
        timeout_seconds: float = 120.0,
        production: bool = True,
        implementation: str = "server.audio_backends:EvidenceBoundHttpAudioEventBackend",
        version: str = "1.0.0",
    ) -> None:
        self.endpoint = str(endpoint or "").strip()
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("audio backend endpoint must be an HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("audio backend endpoint must not contain credentials")
        if production and parsed.scheme != "https":
            raise ValueError("production audio backend endpoint must use HTTPS")
        self.model_id = str(model_id or "").strip()
        if not self.model_id:
            raise ValueError("audio backend model_id is required")
        self.model_sha256 = _sha256_model(model_sha256, "audio backend model_sha256")
        self.api_token = str(api_token).strip() if api_token else None
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("audio backend timeout_seconds must be positive")
        self.production = bool(production)
        self.implementation = implementation
        self.version = version

    def capability_identity(self) -> Mapping[str, Any]:
        return {
            "capability": self.capability_kind,
            "implementation": self.implementation,
            "version": self.version,
            "evidence_binding": "usfr-audio-evidence/v1",
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
        }

    @classmethod
    def from_environment(cls, *, production: bool = True) -> "EvidenceBoundHttpAudioEventBackend":
        """Construct the backend from deployment-owned immutable settings."""

        import os

        return cls(
            endpoint=os.environ["USFR_AUDIO_EVENT_ENDPOINT"],
            model_id=os.environ["USFR_AUDIO_EVENT_MODEL_ID"],
            model_sha256=os.environ["USFR_AUDIO_EVENT_MODEL_SHA256"],
            api_token=os.getenv("USFR_AUDIO_EVENT_API_TOKEN"),
            production=production,
        )

    def classify(
        self,
        audio_path: str | Path,
        *,
        segments: Sequence[Mapping[str, Any]] | None = None,
        silence_windows: Sequence[Mapping[str, Any]] | None = None,
        duration_ms: int | None = None,
        **_kwargs: Any,
    ) -> Mapping[str, Any]:
        path = Path(audio_path)
        try:
            audio_bytes = path.read_bytes()
        except OSError as exc:
            raise AudioBackendUnavailable("could not read extracted audio bytes") from exc
        input_sha = _sha256(audio_bytes)
        payload: dict[str, Any] = {
            "schema_version": "usfr-audio-request/v1",
            "input_sha256": input_sha,
            "model": {"id": self.model_id, "sha256": self.model_sha256},
            "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
            "segments": _project_segments(segments or []),
            "silence_windows": _project_silence(silence_windows or []),
        }
        if duration_ms is not None:
            payload["duration_ms"] = int(duration_ms)
        request_sha = _sha256(_canonical(payload))
        payload["request_sha256"] = request_sha
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **({"Authorization": f"Bearer {self.api_token}"} if self.api_token else {}),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - endpoint is deployment-configured
                raw_response = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise AudioBackendUnavailable("audio event backend request failed") from exc
        try:
            result = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AudioBackendUnavailable("audio event backend returned malformed JSON") from exc
        if not isinstance(result, Mapping):
            raise AudioBackendUnavailable("audio event backend response must be an object")
        if result.get("schema_version") != "usfr-audio-evidence/v1":
            raise AudioBackendUnavailable("audio event backend schema version is unsupported")
        if result.get("request_sha256") != request_sha:
            raise AudioBackendUnavailable("audio event backend request SHA does not match")
        if result.get("input_sha256") != input_sha:
            raise AudioBackendUnavailable("audio event backend input SHA does not match")
        model = result.get("model")
        if not isinstance(model, Mapping) or model.get("id") != self.model_id or str(model.get("sha256", "")).lower() != self.model_sha256:
            raise AudioBackendUnavailable("audio event backend model identity does not match")
        events = result.get("events")
        if not isinstance(events, list):
            raise AudioBackendUnavailable("audio event backend events must be a list")
        limit = int(duration_ms) if duration_ms is not None else None
        normalized: list[dict[str, Any]] = []
        for index, raw_event in enumerate(events, start=1):
            if not isinstance(raw_event, Mapping):
                raise AudioBackendUnavailable("audio event backend returned a non-object event", details={"event": index})
            event = {
                field: raw_event[field]
                for field in (
                    "event_id",
                    "kind",
                    "label",
                    "start_ms",
                    "end_ms",
                    "meaningful",
                    "confidence",
                    "certainty",
                )
                if field in raw_event
            }
            event_id = str(event.get("event_id") or f"E{index}").strip()
            kind = str(event.get("kind") or "").strip().lower()
            try:
                start_ms = int(event.get("start_ms"))
                end_ms = int(event.get("end_ms"))
            except (TypeError, ValueError) as exc:
                raise AudioBackendUnavailable("audio event backend event timing is invalid", details={"event": index}) from exc
            if not event_id or not kind or start_ms < 0 or end_ms <= start_ms or (limit is not None and end_ms > limit):
                raise AudioBackendUnavailable("audio event backend event timing is out of range", details={"event": index})
            event["event_id"] = event_id
            event["kind"] = kind
            event["start_ms"] = start_ms
            event["end_ms"] = end_ms
            if "confidence" in event:
                try:
                    confidence = float(event["confidence"])
                except (TypeError, ValueError) as exc:
                    raise AudioBackendUnavailable(
                        "audio event backend confidence must be numeric",
                        details={"event": index},
                    ) from exc
                if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise AudioBackendUnavailable(
                        "audio event backend confidence must be in [0, 1]",
                        details={"event": index},
                    )
                event["confidence"] = confidence
            if "meaningful" in event:
                if not isinstance(event["meaningful"], bool):
                    raise AudioBackendUnavailable(
                        "audio event backend meaningful flag must be boolean",
                        details={"event": index},
                    )
            normalized.append(event)
        evidence = result.get("evidence") if isinstance(result.get("evidence"), Mapping) else {}
        bound_evidence = {
            **dict(evidence),
            "schema_version": "usfr-audio-evidence/v1",
            "evidence_binding": "usfr-audio-evidence/v1",
            "input_sha256": input_sha,
            "request_sha256": request_sha,
            "response_sha256": _sha256(raw_response),
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
            "event_count": len(normalized),
            "events_sha256": _sha256(
                json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ),
        }
        return {"events": normalized, "evidence": bound_evidence}

    def __call__(
        self,
        audio_path: str | Path,
        *,
        segments: Sequence[Mapping[str, Any]] | None = None,
        silence_windows: Sequence[Mapping[str, Any]] | None = None,
        duration_ms: int | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        result = self.classify(
            audio_path,
            segments=segments,
            silence_windows=silence_windows,
            duration_ms=duration_ms,
            **kwargs,
        )
        return [dict(item) for item in result.get("events", []) if isinstance(item, Mapping)]


__all__ = [
    "AudioBackendUnavailable",
    "BackgroundMusicCompositor",
    "EvidenceBoundHttpAudioEventBackend",
    "MusicTimelineAnalyzer",
    "OptionalInputExtension",
    "input_contract_v2_extensions",
    "validate_final_audio_qc",
]
