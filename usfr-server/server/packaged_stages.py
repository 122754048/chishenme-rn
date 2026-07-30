"""Executable, package-owned stages for the deployable USFR worker.

The service deliberately keeps operational stages separate from the twelve
semantic stages.  This module provides the missing operational glue without
inventing media or analysis: every media input is materialized through the
lease context, every bytes result is published through the context, and every
paid request is frozen before it reaches RunningHub.

The stage implementations are intentionally small.  Source understanding,
script/storyboard reasoning, Seedance prompt rules, composition, and QC stay
in their existing authoritative modules.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .analysis_scope import build_analysis_scope, build_execution_scope, promote_deferred_tool
from .errors import ReplicationError
from .audio_provider_authorization import (
    AudioProviderAuthorizationError,
    mint_audio_provider_authorization,
)
from .job_models import ProviderAttempt
from .media_probe import probe_source
from .production_ports import (
    EvidenceBoundGptPlanner,
    ProductionPortsError,
    RunningHubCreateAmbiguousError,
    RunningHubTaskFailed,
    _StoryboardRevisionStage,
)
from .review_models import RevisionManifest, StoryboardCutRef
from .source_evidence_bundle import build_source_evidence_bundle
from .runninghub_standard_contract import (
    RunningHubStandardPayloadError,
    build_provider_audit_proof,
    validate_audio_reference_artifact_receipt,
    validate_audio_reference_binding,
    validate_final_reference_lineage,
    validate_runninghub_standard_payload_contract,
    validate_video_reference_binding,
)
from .ui_interaction_contract import UiInteractionContractError, build_source_ui_interaction_contract
from .visible_text_contract import (
    VisibleTextContractError,
    canonicalize_visible_text_locks,
    visible_text_locks_sha256,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/avif"})
_SLOT_ORDER = (
    "source_video",
    "new_product_image",
    "new_model_image",
    "ui_screenshot",
    "app_store_url",
    "ui_operation_video",
    "tail_video",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _replication_error(code: str, message: str, *, retryable: bool = False, category: str = "contract", **details: Any) -> ReplicationError:
    return ReplicationError(
        code,
        message,
        category=category,
        retryable=retryable,
        user_action_required=not retryable,
        details=details or None,
        http_status=503 if retryable else 422,
    )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _replication_error("CONTRACT_INVALID", f"{label} must be an object")
    return value


def _stage_output(context: Any, name: str) -> Mapping[str, Any]:
    outputs = getattr(context, "stage_outputs", {})
    value = outputs.get(name) if isinstance(outputs, Mapping) else None
    return _mapping(value, f"{name} stage output")


def _slots(context: Any) -> Mapping[str, Any]:
    snapshot = getattr(context, "snapshot", None)
    manifest = getattr(snapshot, "slots_manifest", None)
    slots = manifest.get("slots") if isinstance(manifest, Mapping) else None
    return _mapping(slots, "fixed input slots")


def _slot(context: Any, slot_id: str) -> Mapping[str, Any]:
    value = _slots(context).get(slot_id)
    return _mapping(value, f"{slot_id} slot")


def _present(context: Any, slot_id: str) -> bool:
    return bool(_slot(context, slot_id).get("present"))


def _slot_sha256s(context: Any, slot_id: str) -> list[str]:
    values = _slot(context, slot_id).get("sha256") or []
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise _replication_error("CONTRACT_INVALID", f"{slot_id} SHA evidence must be an array")
    result = [str(value or "").lower() for value in values]
    if any(_SHA256.fullmatch(value) is None for value in result):
        raise _replication_error("CONTRACT_INVALID", f"{slot_id} SHA evidence is invalid")
    return result


def _read_json_artifact(context: Any, *, kind: str, sha256: str | None = None) -> Mapping[str, Any]:
    artifacts = [
        item for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping)
        and item.get("kind") == kind
        and (sha256 is None or item.get("sha256") == sha256)
    ]
    if len(artifacts) != 1:
        raise _replication_error("ARTIFACT_NOT_FOUND", f"exactly one {kind} artifact is required", category="artifact")
    descriptor = artifacts[0]
    artifact_id = str(descriptor.get("artifact_id") or "")
    digest = str(descriptor.get("sha256") or "").lower()
    if not artifact_id or _SHA256.fullmatch(digest) is None:
        raise _replication_error("CONTRACT_INVALID", f"{kind} artifact descriptor is invalid", category="artifact")
    try:
        with context.materialize_artifact(kind, artifact_id=artifact_id, sha256=digest) as media:
            payload = Path(media.path).read_bytes()
    except ReplicationError:
        raise
    except Exception as exc:
        raise _replication_error("ARTIFACT_NOT_FOUND", f"{kind} artifact cannot be materialized", category="artifact") from exc
    if hashlib.sha256(payload).hexdigest() != digest:
        raise _replication_error("ARTIFACT_HASH_MISMATCH", f"{kind} artifact bytes do not match SHA-256", category="artifact")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _replication_error("CONTRACT_INVALID", f"{kind} artifact is not UTF-8 JSON", category="artifact") from exc
    return _mapping(value, f"{kind} artifact")


def _uploaded_audio_source_music_windows(context: Any) -> list[dict[str, int | str]]:
    """Read the one frozen source music timeline for an uploaded-audio run."""

    try:
        from .singing_audio_router import route_uploaded_audio

        route = route_uploaded_audio(_read_json_artifact(context, kind="source_content_timeline"))
    except ReplicationError:
        raise
    except ValueError as exc:
        raise _replication_error(
            "SOURCE_MUSIC_WINDOW_INVALID",
            "frozen source music cut-in/cut-out windows are invalid",
        ) from exc
    raw_windows = route.get("source_music_windows")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise _replication_error(
            "SOURCE_MUSIC_WINDOW_REQUIRED",
            "uploaded audio can replace only an observed source music window",
        )
    windows = [dict(item) for item in raw_windows if isinstance(item, Mapping)]
    if len(windows) != len(raw_windows):
        raise _replication_error("SOURCE_MUSIC_WINDOW_INVALID", "frozen source music windows are invalid")
    return windows


def _uploaded_audio_classification(context: Any) -> dict[str, object]:
    """Load the one immutable classification before script/prompt decisions.

    Classification is intentionally an upstream artifact, not a late prompt
    heuristic.  This keeps song lyrics visible in the script approval and
    prevents an unknown track from being treated as harmless background music.
    """

    extensions = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("extensions", {})
    music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
    if not isinstance(music, Mapping):
        raise _replication_error("UPLOADED_AUDIO_CLASSIFICATION_REQUIRED", "uploaded audio extension is missing")
    hashes = music.get("sha256")
    if (
        not isinstance(hashes, Sequence)
        or isinstance(hashes, (str, bytes, bytearray))
        or len(hashes) != 1
        or _SHA256.fullmatch(str(hashes[0]).lower()) is None
    ):
        raise _replication_error("INPUT_SLOT_INVALID", "uploaded audio immutable hash is invalid", category="input")
    try:
        from .uploaded_audio_contract import UploadedAudioContractError, validate_uploaded_audio_contract

        value = _read_json_artifact(context, kind="uploaded_audio_classification")
        return validate_uploaded_audio_contract(value, audio_sha256=str(hashes[0]).lower())
    except ReplicationError:
        raise
    except UploadedAudioContractError as exc:
        raise _replication_error(
            "UPLOADED_AUDIO_CLASSIFICATION_REQUIRED",
            "uploaded audio must have a confirmed song or non-song classification before script approval",
        ) from exc


def _segment_music_window_bindings(
    source_music_windows: Sequence[Mapping[str, Any]],
    *,
    segment_start_ms: int,
    segment_end_ms: int,
) -> list[dict[str, int | str]]:
    """Project global source music windows to a silence-padded segment track.

    Uploaded audio advances only while a source music window is active.  It is
    never stretched, looped, or allowed to fill an observed non-music gap.
    """

    if (
        isinstance(segment_start_ms, bool)
        or isinstance(segment_end_ms, bool)
        or not isinstance(segment_start_ms, int)
        or not isinstance(segment_end_ms, int)
        or segment_start_ms < 0
        or segment_end_ms <= segment_start_ms
    ):
        raise _replication_error("SEGMENT_PLAN_INVALID", "uploaded-audio segment timing is invalid")
    result: list[dict[str, int | str]] = []
    upload_cursor_ms = 0
    previous_end_ms = -1
    seen_event_ids: set[str] = set()
    for raw in source_music_windows:
        if not isinstance(raw, Mapping):
            raise _replication_error("SOURCE_MUSIC_WINDOW_INVALID", "frozen source music window is invalid")
        event_id = str(raw.get("event_id") or "").strip()
        source_start_ms, source_end_ms = raw.get("start_ms"), raw.get("end_ms")
        if (
            not event_id
            or event_id in seen_event_ids
            or isinstance(source_start_ms, bool)
            or isinstance(source_end_ms, bool)
            or not isinstance(source_start_ms, int)
            or not isinstance(source_end_ms, int)
            or source_start_ms < 0
            or source_end_ms <= source_start_ms
            or source_start_ms < previous_end_ms
        ):
            raise _replication_error("SOURCE_MUSIC_WINDOW_INVALID", "frozen source music windows are invalid")
        overlap_start_ms = max(segment_start_ms, source_start_ms)
        overlap_end_ms = min(segment_end_ms, source_end_ms)
        if overlap_start_ms < overlap_end_ms:
            uploaded_start_ms = upload_cursor_ms + overlap_start_ms - source_start_ms
            uploaded_end_ms = uploaded_start_ms + overlap_end_ms - overlap_start_ms
            result.append(
                {
                    "event_id": event_id,
                    "source_start_ms": source_start_ms,
                    "source_end_ms": source_end_ms,
                    "segment_start_ms": overlap_start_ms - segment_start_ms,
                    "segment_end_ms": overlap_end_ms - segment_start_ms,
                    "uploaded_start_ms": uploaded_start_ms,
                    "uploaded_end_ms": uploaded_end_ms,
                }
            )
        upload_cursor_ms += source_end_ms - source_start_ms
        previous_end_ms = source_end_ms
        seen_event_ids.add(event_id)
    return result


def _publish_json(
    context: Any,
    *,
    kind: str,
    value: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    raw = _canonical(dict(value))
    return context.publish_bytes(
        kind=kind,
        data=raw,
        content_type="application/json",
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        metadata=metadata,
    )


def _load_module(relative: str, name: str) -> Any:
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise _replication_error("CAPABILITY_UNAVAILABLE", f"packaged dependency {relative} is unavailable", retryable=True, category="capability")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise _replication_error("CAPABILITY_UNAVAILABLE", f"packaged dependency {relative} could not load", retryable=True, category="capability") from exc
    return module


class BindInputsStage:
    """Revalidate intake and publish uploaded-audio classification before script work."""

    def __init__(self, *, uploaded_audio_classifier: Any | None = None) -> None:
        # The classifier is deployment-owned.  It must determine song versus
        # non-song and emit timestamped lyrics before the script review can
        # expose or approve them; prompt compilation is intentionally too late.
        self.uploaded_audio_classifier = uploaded_audio_classifier

    def _classify_uploaded_audio(self, context: Any) -> tuple[dict[str, object], dict[str, Any]] | None:
        snapshot = getattr(context, "snapshot", None)
        manifest = getattr(snapshot, "slots_manifest", None)
        extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
        music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
        if music is None:
            return None
        if not isinstance(music, Mapping):
            raise _replication_error("INPUT_SLOT_INVALID", "background_music extension is invalid", category="input")
        values, hashes, metadata = music.get("values"), music.get("sha256"), music.get("metadata")
        if (
            music.get("extension_id") != "input_contract_v2.background_music"
            or not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)) or len(values) != 1
            or not isinstance(hashes, Sequence) or isinstance(hashes, (str, bytes, bytearray)) or len(hashes) != 1
            or not isinstance(metadata, Sequence) or isinstance(metadata, (str, bytes, bytearray)) or len(metadata) != 1
            or not isinstance(metadata[0], Mapping)
        ):
            raise _replication_error("INPUT_SLOT_INVALID", "background_music immutable upload evidence is invalid", category="input")
        audio_sha256 = str(hashes[0] or "").lower()
        if _SHA256.fullmatch(audio_sha256) is None:
            raise _replication_error("INPUT_SLOT_INVALID", "background_music immutable upload hash is invalid", category="input")
        if (
            not str(metadata[0].get("object_key") or "")
            or str(metadata[0].get("sha256") or "").lower() != audio_sha256
        ):
            raise _replication_error("INPUT_SLOT_INVALID", "background_music completion evidence does not match", category="input")
        classifier = self.uploaded_audio_classifier
        classify = getattr(classifier, "classify_uploaded_audio", None)
        if not callable(classify):
            raise _replication_error(
                "CAPABILITY_UNAVAILABLE",
                "background_music requires the deployment-bound uploaded-audio classifier",
                retryable=True,
                category="capability",
            )
        try:
            with context.materialize_extension("background_music") as audio:
                if str(getattr(audio, "sha256", "") or "").lower() != audio_sha256:
                    raise _replication_error(
                        "ARTIFACT_HASH_MISMATCH",
                        "materialized background_music bytes differ from the immutable upload",
                        category="artifact",
                    )
                candidate = classify(Path(audio.path), audio_sha256=audio_sha256)
            from .uploaded_audio_contract import UploadedAudioContractError, validate_uploaded_audio_contract

            contract = validate_uploaded_audio_contract(candidate, audio_sha256=audio_sha256)
        except ReplicationError:
            raise
        except (UploadedAudioContractError, TypeError, ValueError) as exc:
            raise _replication_error(
                "UPLOADED_AUDIO_CLASSIFICATION_REQUIRED",
                "uploaded audio classifier returned an invalid or ambiguous song/non-song result",
            ) from exc
        except Exception as exc:
            raise _replication_error(
                "CAPABILITY_UNAVAILABLE",
                "uploaded-audio classification service failed before script drafting",
                retryable=True,
                category="capability",
            ) from exc
        published = _publish_json(
            context,
            kind="uploaded_audio_classification",
            value=contract,
            metadata={
                "audio_sha256": audio_sha256,
                "classification_evidence_sha256": contract["classification_evidence_sha256"],
            },
        )
        return contract, published

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        slots = _slots(context)
        if set(slots) != set(_SLOT_ORDER):
            raise _replication_error("INPUT_SLOT_INVALID", "fixed input manifest must contain exactly seven slots", category="input")
        normalized: dict[str, Any] = {}
        for slot_id in _SLOT_ORDER:
            slot = _slot(context, slot_id)
            present = bool(slot.get("present"))
            values = slot.get("values") or []
            metadata = slot.get("metadata") or []
            hashes = slot.get("sha256") or []
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
                raise _replication_error("INPUT_SLOT_INVALID", f"{slot_id} values must be an array", category="input")
            if not present:
                if values or hashes or metadata:
                    raise _replication_error("INPUT_SLOT_INVALID", f"absent {slot_id} cannot retain media evidence", category="input")
                normalized[slot_id] = {"present": False, "sha256": []}
                continue
            if not values or len(values) != len(hashes):
                raise _replication_error("INPUT_SLOT_INVALID", f"{slot_id} input evidence is incomplete", category="input")
            _slot_sha256s(context, slot_id)
            if slot_id != "app_store_url":
                if not isinstance(metadata, Sequence) or len(metadata) != len(values):
                    raise _replication_error("INPUT_SLOT_INVALID", f"{slot_id} upload completion is incomplete", category="input")
                for index, record in enumerate(metadata):
                    if not isinstance(record, Mapping) or not str(record.get("object_key") or ""):
                        raise _replication_error("INPUT_SLOT_INVALID", f"{slot_id}[{index}] has no immutable object key", category="input")
                    if str(record.get("sha256") or "").lower() != str(hashes[index]).lower():
                        raise _replication_error("INPUT_SLOT_INVALID", f"{slot_id}[{index}] completion SHA does not match slot evidence", category="input")
            normalized[slot_id] = {"present": True, "sha256": list(_slot_sha256s(context, slot_id))}
        if not normalized["source_video"]["present"]:
            raise _replication_error("INPUT_SOURCE_REQUIRED", "source_video is required", category="input")
        snapshot = getattr(context, "snapshot", None)
        manifest = getattr(snapshot, "slots_manifest", None)
        admission = manifest.get("admission") if isinstance(manifest, Mapping) else None
        if not isinstance(admission, Mapping) or admission.get("can_proceed") is not True:
            raise _replication_error("MIN_ONE_OPTIONAL_INPUT_REQUIRED", "the frozen intake manifest is not admitted", category="input")
        result: dict[str, Any] = {
            "status": "ready",
            "input_manifest": normalized,
            "input_manifest_sha256": _sha(normalized),
        }
        uploaded_audio = self._classify_uploaded_audio(context)
        if uploaded_audio is not None:
            contract, published = uploaded_audio
            result["uploaded_audio_classification"] = contract
            result["uploaded_audio_classification_sha256"] = published["sha256"]
            result["published_artifacts"] = [published]
        return result


class ProbeSourceStage:
    """Run the single deterministic ffprobe cache boundary on source bytes."""

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        try:
            with context.materialize_slot("source_video") as media:
                result = probe_source(media.path, max_duration_seconds=30.0)
        except ReplicationError:
            raise
        except Exception as exc:
            raise _replication_error("INPUT_SOURCE_INVALID", "source video probe failed", category="input") from exc
        digest = str(getattr(media, "sha256", "") or "").lower()
        if _SHA256.fullmatch(digest) is None or result.get("sha256") != digest:
            raise _replication_error("ARTIFACT_HASH_MISMATCH", "probed source bytes do not match immutable source evidence", category="artifact")
        duration_seconds = float(result.get("duration_seconds") or 0)
        if not 0 < duration_seconds <= 30:
            raise _replication_error("INPUT_SOURCE_TOO_LONG", "source_video must be between zero and 30 seconds", category="input")
        width, height = int(result.get("width") or 0), int(result.get("height") or 0)
        if width <= 0 or height <= 0:
            raise _replication_error("INPUT_SOURCE_INVALID", "source video has invalid dimensions", category="input")
        fps_text = str(result.get("fps") or "")
        try:
            fps_num, fps_den = (int(item) for item in fps_text.split("/", 1))
        except (TypeError, ValueError):
            fps_num, fps_den = 0, 0
        if fps_num <= 0 or fps_den <= 0:
            raise _replication_error("INPUT_SOURCE_INVALID", "source video frame rate is invalid", category="input")
        probe = {
            "source_sha256": digest,
            "sha256": digest,
            "duration_us": int(round(duration_seconds * 1_000_000)),
            "video_duration_us": int(round(duration_seconds * 1_000_000)),
            "width": width,
            "height": height,
            "source_width": width,
            "source_height": height,
            "fps": fps_text,
            "fps_num": fps_num,
            "fps_den": fps_den,
            "has_audio": bool(result.get("has_audio")),
            "format": str(result.get("format") or ""),
        }
        return {"status": "ready", "probe": probe, "probe_sha256": _sha(probe)}


class RouteRegionsStage:
    """Bind fixed slots to the one frozen source Cut timeline.

    This stage does not reclassify file roles.  It only converts source Cut
    evidence and deterministic slot routes into ordinary generated, source,
    opaque, or generated-UI carriers.  A supplied UI/tail file never enters a
    semantic media request.
    """

    _UI_WORDS = (" ui", "screen", "app", "interface", "phone display", "phone screen", "web page")
    _TAIL_WORDS = ("end card", "endcard", "download", "install now", "app store")

    @classmethod
    def _text(cls, cut: Mapping[str, Any]) -> str:
        return " ".join(str(cut.get(key) or "") for key in ("scene", "action", "transition")).casefold()

    @classmethod
    def _is_ui_cut(cls, cut: Mapping[str, Any]) -> bool:
        if any(cut.get(field) is True for field in ("contains_ui", "ui_interaction", "ui_operation")):
            return True
        return any(word in cls._text(cut) for word in cls._UI_WORDS)

    @staticmethod
    def _transition_shell(cut: Mapping[str, Any]) -> dict[str, Any]:
        shell = cut.get("transition_shell")
        if isinstance(shell, Mapping) and shell:
            return json.loads(json.dumps(shell, ensure_ascii=False, sort_keys=True))
        return {"kind": str(cut.get("transition") or "cut"), "source_fidelity": "exact"}

    @staticmethod
    def _source_language(analysis: Mapping[str, Any]) -> str:
        for key in ("source_language", "language"):
            candidate = analysis.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return "und"

    @staticmethod
    def _cut_has_vocal_content(cut: Mapping[str, Any]) -> bool:
        if any(
            cut.get(field) is True
            for field in (
                "contains_speech",
                "contains_dialogue",
                "visible_singing",
                "contains_singing",
                "speaking",
                "singing",
            )
        ):
            return True
        return any(
            isinstance(cut.get(field), str) and bool(str(cut.get(field)).strip())
            for field in ("dialogue", "speech", "lyrics", "transcript", "spoken_text", "sung_text")
        )

    @classmethod
    def _promotion_receipts(
        cls,
        *,
        context: Any,
        manifest: Mapping[str, Any],
        cuts: Sequence[Mapping[str, Any]],
        regions: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        analysis_scope = getattr(context, "analysis_scope", None)
        if not isinstance(analysis_scope, Mapping) or not analysis_scope:
            analysis_scope = build_analysis_scope(manifest)
        tools = analysis_scope.get("tools")
        tools = tools if isinstance(tools, Mapping) else {}
        receipts: list[dict[str, Any]] = []

        def promote(tool_name: str, region_ids: Sequence[str], reason: str) -> None:
            decision = tools.get(tool_name)
            if not isinstance(decision, Mapping) or decision.get("status") != "deferred" or not region_ids:
                return
            receipts.append(
                promote_deferred_tool(
                    scope=analysis_scope,
                    tool_name=tool_name,
                    region_ids=region_ids,
                    reason=reason,
                )
            )

        generated_ui_ids = [
            str(item.get("region_id"))
            for item in regions
            if item.get("media_origin") == "generated_ui"
        ]
        generated_video_ids = [
            str(item.get("region_id"))
            for item in regions
            if item.get("media_origin") == "generated"
        ]
        generated_ids = [*generated_ui_ids, *generated_video_ids]
        if generated_ui_ids:
            for tool_name, reason in (
                ("source_ocr", "generated UI regions require source ROI text evidence"),
                ("target_ui_ocr", "generated UI regions require target UI text evidence"),
                ("ui_rebuild", "generated UI regions require deterministic reconstruction"),
                ("app_store_evidence", "generated UI regions consume official App Store evidence"),
            ):
                promote(tool_name, generated_ui_ids, reason)
        promote("storyboard", generated_ids, "generated regions require the approved director board set")
        promote("seedance_video", generated_video_ids, "non-UI generated regions require Seedance video")

        cuts_by_id = {
            str(cut.get("cut_id") or f"C{index:02d}"): cut
            for index, cut in enumerate(cuts, start=1)
            if isinstance(cut, Mapping)
        }
        vocal_region_ids: list[str] = []
        for region in regions:
            if region.get("media_origin") not in {"generated", "generated_ui"}:
                continue
            cut_ids = region.get("cut_ids") or ()
            if any(cls._cut_has_vocal_content(cuts_by_id.get(str(cut_id), {})) for cut_id in cut_ids):
                vocal_region_ids.append(str(region.get("region_id")))
        promote("source_asr", vocal_region_ids, "generated vocal regions require one timestamped source transcription")
        return receipts

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        dynamics = _stage_output(context, "analyze_dynamics").get("source_dynamics_analysis")
        analysis = _mapping(dynamics, "source dynamics analysis")
        cuts = analysis.get("source_cuts")
        if not isinstance(cuts, Sequence) or isinstance(cuts, (str, bytes, bytearray)) or not cuts:
            raise _replication_error("CONTRACT_INVALID", "source dynamics has no ordered Cuts")
        snapshot = getattr(context, "snapshot", None)
        manifest = getattr(snapshot, "slots_manifest", None)
        analysis_scope = getattr(context, "analysis_scope", None)
        if not isinstance(analysis_scope, Mapping) or not analysis_scope:
            analysis_scope = build_analysis_scope(manifest if isinstance(manifest, Mapping) else {})
        routes = manifest.get("routes") if isinstance(manifest, Mapping) else None
        routes = dict(routes) if isinstance(routes, Mapping) else {}
        model_change = _present(context, "new_model_image")
        product_change = _present(context, "new_product_image")
        language_change = isinstance(manifest, Mapping) and isinstance(manifest.get("output_language"), str)
        ui_route = str(routes.get("ui") or "source_ui_keep")
        extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
        extensions = dict(extensions) if isinstance(extensions, Mapping) else {}
        explicit_ui_target = _present(context, "ui_screenshot") or _present(context, "app_store_url")
        automatic_ui_rebuild = extensions.get("ui_rebuild_enabled") is True
        tail_replacement = _present(context, "tail_video")
        regions: list[dict[str, Any]] = []
        previous_end = 0
        tail_index: int | None = None
        if tail_replacement:
            candidates = [index for index, cut in enumerate(cuts) if isinstance(cut, Mapping) and any(word in self._text(cut) for word in self._TAIL_WORDS)]
            if not candidates:
                raise _replication_error("TIMELINE_ROUTE_REQUIRED", "tail_video requires an evidence-backed terminal source end-card Cut")
            tail_index = candidates[-1]
            if tail_index != len(cuts) - 1:
                raise _replication_error("TIMELINE_ROUTE_REQUIRED", "tail_video may replace only a contiguous terminal source end-card interval")
        for index, raw_cut in enumerate(cuts, start=1):
            cut = _mapping(raw_cut, f"source Cut {index}")
            try:
                start_us, end_us = int(cut.get("start_us")), int(cut.get("end_us"))
            except (TypeError, ValueError) as exc:
                raise _replication_error("CONTRACT_INVALID", f"source Cut {index} timing is invalid") from exc
            if start_us != previous_end or end_us <= start_us:
                raise _replication_error("CONTRACT_INVALID", "source Cut timing must be contiguous")
            previous_end = end_us
            cut_id = str(cut.get("cut_id") or f"C{index:02d}")
            source_text = self._text(cut)
            is_ui = self._is_ui_cut(cut)
            region: dict[str, Any] = {
                "region_id": f"R{index:02d}",
                "cut_ids": [cut_id],
                "source_start_us": start_us,
                "source_end_us": end_us,
                "source_start_ms": start_us // 1000,
                "source_end_ms": (end_us + 999) // 1000,
                "display_viewport": [int(analysis.get("source_width") or 0), int(analysis.get("source_height") or 0)],
                "rotation_degrees": 0,
                "safe_cover_crop_percent": 0,
            }
            if tail_index is not None and index - 1 == tail_index:
                region.update({"region_type": "opaque_app_tail_card", "media_origin": "opaque_tail", "assembly_policy": "splice_opaque_tail"})
            elif is_ui and ui_route == "opaque_ui_demo":
                region.update({
                    "region_type": "opaque_ui_demo",
                    "media_origin": "opaque_ui",
                    "assembly_policy": "splice_opaque_ui",
                    "transition_shell": self._transition_shell(cut),
                })
            elif is_ui and ui_route == "generated_ui_demo" and (
                explicit_ui_target or automatic_ui_rebuild
            ):
                region.update({
                    "region_type": "generated_ui_demo",
                    "media_origin": "generated_ui",
                    "assembly_policy": "render_generated_ui",
                    "transition_shell": self._transition_shell(cut),
                })
                try:
                    interaction_contract = build_source_ui_interaction_contract(
                        region,
                        fps_num=int(analysis.get("fps_num") or 0),
                        fps_den=int(analysis.get("fps_den") or 0),
                        source_language=self._source_language(analysis),
                        output_language=manifest.get("output_language") if isinstance(manifest, Mapping) else None,
                    )
                except UiInteractionContractError as exc:
                    raise _replication_error("CONTRACT_INVALID", f"source UI interaction contract is invalid: {exc}") from exc
                region["source_ui_interaction_contract"] = interaction_contract
                region["source_ui_interaction_contract_sha256"] = _sha(interaction_contract)
            elif is_ui:
                region.update({"region_type": "source_interval", "media_origin": "source_interval", "assembly_policy": "splice_source_interval"})
            elif model_change or product_change or language_change:
                region.update({"region_type": "generated", "media_origin": "generated", "assembly_policy": "generate_region"})
            else:
                region.update({"region_type": "source_interval", "media_origin": "source_interval", "assembly_policy": "splice_source_interval"})
            regions.append(region)
        envelope = {
            "schema_version": "usfr-timeline-regions/v1",
            "regions": regions,
            "generation_required": any(item["media_origin"] in {"generated", "generated_ui"} for item in regions),
            "seedance_generation_required": any(item["media_origin"] == "generated" for item in regions),
        }
        envelope["timeline_regions_sha256"] = _sha(envelope)
        promotion_receipts = self._promotion_receipts(
            context=context,
            manifest=dict(manifest) if isinstance(manifest, Mapping) else {},
            cuts=[dict(item) for item in cuts if isinstance(item, Mapping)],
            regions=regions,
        )
        final_execution_scope = build_execution_scope(
            analysis_scope,
            promotion_receipts=promotion_receipts,
            finalized=True,
        )
        generated_ui_ids = [
            str(item.get("region_id"))
            for item in regions
            if item.get("media_origin") == "generated_ui"
        ]
        prior_outputs = getattr(context, "stage_outputs", {})
        prior_outputs = prior_outputs if isinstance(prior_outputs, Mapping) else {}
        probe_output = prior_outputs.get("probe_source")
        probe = probe_output.get("probe", probe_output) if isinstance(probe_output, Mapping) else {}
        analysis_output = prior_outputs.get("analyze_dynamics")
        analysis_output = analysis_output if isinstance(analysis_output, Mapping) else {}
        dynamics_evidence = analysis_output.get("source_dynamics_analysis")
        dynamics_evidence = dynamics_evidence if isinstance(dynamics_evidence, Mapping) else {}
        bundle = build_source_evidence_bundle(
            probe=probe if isinstance(probe, Mapping) else {},
            timeline=envelope,
            execution_scope=final_execution_scope,
            semantic_evidence=dynamics_evidence,
            audio_evidence=analysis_output.get("audio_contract") if isinstance(analysis_output.get("audio_contract"), Mapping) else {},
            ui_evidence={
                "generated_region_ids": generated_ui_ids,
                "source_ui_cut_ids": [str(item.get("region_id")) for item in regions if item.get("media_origin") == "source_interval" and item.get("region_type") == "source_interval"],
            },
        )
        published = _publish_json(context, kind="timeline_regions", value=envelope)
        published_bundle = _publish_json(context, kind="source_evidence_bundle", value=bundle)
        return {
            "status": "ready",
            "timeline_regions": envelope,
            "tool_promotion_receipts": promotion_receipts,
            "source_evidence_bundle": bundle,
            "published_artifacts": [published, published_bundle],
        }


class StoryboardStage:
    """Create editable text plus real, reviewable Image2 storyboard boards.

    The GPT revision remains the text authority.  Each generated segment gets
    one actual RunningHub Image2 PNG; the revision manifest binds every Cut to
    the relevant board so one storyboard approval covers the complete set.
    """

    def __init__(self, planner: EvidenceBoundGptPlanner, *, image_client: Any) -> None:
        self._revision = _StoryboardRevisionStage(planner)
        if not callable(getattr(image_client, "run_image2", None)):
            raise _replication_error("CAPABILITY_UNAVAILABLE", "RunningHub Image2 storyboard adapter is required", retryable=True, category="capability")
        self._image_client = image_client

    @staticmethod
    def _script_cuts(context: Any) -> list[dict[str, Any]]:
        revision = getattr(context.snapshot, "approved_script_sha256", None)
        if not isinstance(revision, str) or _SHA256.fullmatch(revision) is None:
            raise _replication_error("APPROVAL_REQUIRED", "storyboard generation requires the approved script")
        payload = _read_json_artifact(context, kind="script_revision", sha256=revision)
        cuts = payload.get("cuts")
        if not isinstance(cuts, list) or not cuts:
            raise _replication_error("CONTRACT_INVALID", "approved script has no Cuts")
        return [dict(item) for item in cuts if isinstance(item, Mapping)]

    @staticmethod
    def _png_dimensions(data: bytes) -> tuple[int, int]:
        if not isinstance(data, bytes) or len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
            raise _replication_error("PROVIDER_RESULT_INVALID", "RunningHub Image2 did not return a decodable PNG storyboard", category="provider")
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if width <= 0 or height <= 0:
            raise _replication_error("PROVIDER_RESULT_INVALID", "RunningHub Image2 PNG has invalid dimensions", category="provider")
        return width, height

    @contextmanager
    def _target_reference_images(self, context: Any):
        """Materialize only user-authorized target assets for Image2."""

        with ExitStack() as stack:
            paths: list[Path] = []
            # The role is fixed by the manifest. UI/opaque/tail slots never
            # enter a semantic storyboard request.
            for slot_id, limit in (("new_model_image", 1), ("new_product_image", 2)):
                if not _present(context, slot_id):
                    continue
                hashes = _slot_sha256s(context, slot_id)
                for index in range(min(limit, len(hashes))):
                    media = stack.enter_context(context.materialize_slot(slot_id, index=index))
                    path = Path(media.path)
                    if not path.is_file() or path.stat().st_size <= 0:
                        raise _replication_error("ARTIFACT_NOT_FOUND", f"{slot_id}[{index}] could not be materialized", category="artifact")
                    paths.append(path)
            yield paths

    @staticmethod
    def _visual_target_sha256s(context: Any) -> list[str]:
        """Return every final visual target in fixed Image-slot order."""

        targets: list[str] = []
        for slot_id, limit in (("new_model_image", 1), ("new_product_image", 2)):
            if not _present(context, slot_id):
                continue
            targets.extend(_slot_sha256s(context, slot_id)[:limit])
        return targets

    @staticmethod
    def _approved_visible_text_locks(context: Any) -> tuple[list[dict[str, Any]], str]:
        """Read the script-approved text sidecar before drawing a board.

        The board cannot use GPT/Image2 output as a text authority.  It gets
        only the immutable, user-approved source lock contract and renders
        those glyphs after Image2 has produced the visual board.
        """

        script_sha256 = str(getattr(getattr(context, "snapshot", None), "approved_script_sha256", "") or "").lower()
        if _SHA256.fullmatch(script_sha256) is None:
            raise _replication_error("APPROVAL_REQUIRED", "storyboard generation requires an approved script text lock")
        script = _read_json_artifact(context, kind="script_revision", sha256=script_sha256)
        raw_locks = script.get("visible_text_locks")
        digest = str(script.get("visible_text_locks_sha256") or "").lower()
        if not isinstance(raw_locks, list) or _SHA256.fullmatch(digest) is None:
            raise _replication_error("CONTRACT_INVALID", "approved script visible text locks are missing")
        try:
            locks = canonicalize_visible_text_locks(raw_locks)
        except VisibleTextContractError as exc:
            raise _replication_error("CONTRACT_INVALID", "approved script visible text locks are invalid") from exc
        if visible_text_locks_sha256(locks) != digest:
            raise _replication_error("CONTRACT_INVALID", "approved script visible text lock digest is invalid")

        # A durable worker has a job-store sidecar.  Lightweight unit contexts
        # do not, but production must prove that the same approval froze these
        # exact words before a director board can be shown to the user.
        store = getattr(context, "job_store", None)
        revision = getattr(getattr(context, "snapshot", None), "current_script_revision", None)
        getter = getattr(store, "get_script_approval", None)
        if callable(getter):
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise _replication_error("APPROVAL_REQUIRED", "approved script revision is missing for visible text")
            sidecar = getter(context.job_id, revision)
            if not isinstance(sidecar, Mapping):
                raise _replication_error("APPROVAL_REQUIRED", "approved script visible text sidecar is missing")
            if (
                str(sidecar.get("script_sha256") or "").lower() != script_sha256
                or str(sidecar.get("visible_text_locks_sha256") or "").lower() != digest
                or sidecar.get("visible_text_locks") != locks
            ):
                raise _replication_error("CONTRACT_INVALID", "approved script visible text sidecar does not match the revision")
        return locks, digest

    @staticmethod
    def _segment_visible_text_locks(
        locks: Sequence[Mapping[str, Any]], *, segment: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        try:
            start_ms, end_ms = int(segment["start_ms"]), int(segment["end_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard text segment timing is invalid") from exc
        selected = [
            dict(lock)
            for lock in locks
            if lock.get("disposition") in {"keep", "replace"}
            and max(start_ms, int(lock["start_ms"])) < min(end_ms, int(lock["end_ms"]))
        ]
        return sorted(selected, key=lambda item: (int(item["start_ms"]), int(item["end_ms"]), str(item["text_id"])))

    @staticmethod
    def _text_font(*, size: int) -> Any:
        """Load a deployment-provided multilingual font or fail closed."""

        try:
            from PIL import ImageFont
        except ImportError as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "Pillow is required for director-board text rendering", retryable=True, category="capability") from exc
        candidates = (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/Noto Sans SC Bold (TrueType).otf",
            "C:/Windows/Fonts/NotoSansSC-VF.ttf",
        )
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
        raise _replication_error(
            "CAPABILITY_UNAVAILABLE",
            "a deterministic multilingual director-board font is required",
            retryable=True,
            category="capability",
        )

    @classmethod
    def _render_visible_text_layer(cls, image_bytes: bytes, locks: Sequence[Mapping[str, Any]]) -> bytes:
        """Paint exact approved text after Image2, never trusting generated glyphs."""

        if not locks:
            return image_bytes
        try:
            from PIL import Image, ImageDraw
            with Image.open(io.BytesIO(image_bytes)) as opened:
                image = opened.convert("RGBA")
        except Exception as exc:
            raise _replication_error("PROVIDER_RESULT_INVALID", "director board cannot accept deterministic text", category="artifact") from exc

        draw = ImageDraw.Draw(image, "RGBA")
        font = cls._text_font(size=max(20, image.height // 30))
        margin = max(12, image.width // 100)
        fallback_y = image.height - margin
        for lock in reversed(list(locks)):
            text = str(lock["approved_text"])
            cut_ids = "/".join(str(value) for value in lock["cut_ids"])
            label = f"{cut_ids} {int(lock['start_ms'])}-{int(lock['end_ms'])}ms | {text}"
            bbox = lock.get("placement", {}).get("bbox") if isinstance(lock.get("placement"), Mapping) else None
            x = margin
            y: int | None = None
            if isinstance(bbox, Mapping):
                try:
                    normalized_x = float(bbox["x"])
                    normalized_y = float(bbox["y"])
                    if 0.0 <= normalized_x <= 1.0 and 0.0 <= normalized_y <= 1.0:
                        x = max(margin, min(image.width - margin, round(normalized_x * image.width)))
                        y = max(margin, min(image.height - margin, round(normalized_y * image.height)))
                except (KeyError, TypeError, ValueError):
                    y = None
            text_box = draw.multiline_textbbox((x, 0), label, font=font, spacing=4)
            strip_width = min(image.width - x - margin, max(1, text_box[2] - text_box[0] + margin * 2))
            strip_height = text_box[3] - text_box[1] + margin * 2
            if y is None:
                y = max(margin, fallback_y - strip_height)
                fallback_y = y - margin
            else:
                y = min(max(margin, y), max(margin, image.height - strip_height - margin))
            # The filled strip is deliberately larger than the text so the
            # exact user-approved wording stays legible in the review board.
            draw.rounded_rectangle((x, y, x + strip_width, y + strip_height), radius=margin // 2, fill=(0, 0, 0, 230))
            draw.multiline_text((x + margin, y + margin), label, font=font, fill=(255, 255, 255, 255), spacing=4)

        output = io.BytesIO()
        image.convert("RGB").save(output, format="PNG", optimize=True)
        return output.getvalue()

    @staticmethod
    def _source_keyframe_sheet(context: Any, source_dynamics: Mapping[str, Any]) -> dict[str, Any]:
        """Extract one ordered source frame per Cut and publish a single sheet."""

        cuts = source_dynamics.get("source_cuts")
        if not isinstance(cuts, list) or not cuts:
            raise _replication_error("CONTRACT_INVALID", "source dynamics has no Cuts for keyframe control")
        try:
            from PIL import Image
        except ImportError as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "Pillow is required for source keyframe sheet assembly", retryable=True, category="capability") from exc

        work_dir = Path(context.work_dir) / "reference_frames"
        work_dir.mkdir(parents=True, exist_ok=True)
        frames: list[tuple[Path, dict[str, Any]]] = []
        try:
            with context.materialize_slot("source_video") as media:
                source_path = Path(media.path)
                source_sha256 = str(media.sha256 or "").lower()
                if _SHA256.fullmatch(source_sha256) is None:
                    raise _replication_error("ARTIFACT_HASH_MISMATCH", "source video has no immutable SHA-256", category="artifact")
                for index, raw_cut in enumerate(cuts, start=1):
                    cut = _mapping(raw_cut, f"source Cut {index}")
                    cut_id = str(cut.get("cut_id") or f"C{index:02d}")
                    start_us, end_us = int(cut["start_us"]), int(cut["end_us"])
                    if start_us < 0 or end_us <= start_us:
                        raise _replication_error("CONTRACT_INVALID", f"source Cut {cut_id} timing is invalid")
                    # A point inside the Cut avoids cross-cut decode ambiguity while
                    # keeping the frame maximally close to the recorded transition.
                    timestamp_us = start_us + min(100_000, max(0, (end_us - start_us - 1) // 2))
                    frame_path = work_dir / f"source-{cut_id}.png"
                    command = [
                        "ffmpeg", "-v", "error", "-y", "-i", str(source_path),
                        "-ss", f"{timestamp_us / 1_000_000:.6f}", "-frames:v", "1",
                        "-map_metadata", "-1", "-f", "image2", str(frame_path),
                    ]
                    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                    if not frame_path.is_file() or frame_path.stat().st_size <= 0:
                        raise _replication_error("PROVIDER_RESULT_INVALID", f"source keyframe extraction failed for {cut_id}", category="artifact")
                    frame_bytes = frame_path.read_bytes()
                    StoryboardStage._png_dimensions(frame_bytes)
                    frames.append((frame_path, {"cut_id": cut_id, "timestamp_us": timestamp_us, "sha256": hashlib.sha256(frame_bytes).hexdigest()}))
        except ReplicationError:
            raise
        except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "ffmpeg could not extract source Cut keyframes", retryable=True, category="capability") from exc

        columns = max(1, math.ceil(math.sqrt(len(frames))))
        rendered: list[Any] = []
        try:
            for frame_path, _record in frames:
                with Image.open(frame_path) as image:
                    rendered.append(image.convert("RGB"))
            cell_width = min(480, max(image.width for image in rendered))
            scaled = [
                image.resize((cell_width, max(1, round(image.height * cell_width / image.width))), Image.Resampling.LANCZOS)
                for image in rendered
            ]
            cell_height = max(image.height for image in scaled)
            rows = math.ceil(len(scaled) / columns)
            sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "black")
            for index, image in enumerate(scaled):
                x, y = (index % columns) * cell_width, (index // columns) * cell_height
                sheet.paste(image, (x, y))
            sheet_path = work_dir / "source-keyframes.png"
            sheet.save(sheet_path, format="PNG", optimize=True)
        except Exception as exc:
            raise _replication_error("ARTIFACT_INVALID", "source keyframe sheet assembly failed", category="artifact") from exc
        sheet_bytes = sheet_path.read_bytes()
        sheet_sha256 = hashlib.sha256(sheet_bytes).hexdigest()
        published = context.publish_bytes(
            kind="source_keyframe_sheet", data=sheet_bytes, content_type="image/png", expected_sha256=sheet_sha256,
            metadata={"source_video_sha256": source_sha256, "cut_ids": [item[1]["cut_id"] for item in frames]},
        )
        return {
            "path": sheet_path,
            "source_video_sha256": source_sha256,
            "source_keyframes": [record for _path, record in frames],
            "source_keyframe_sheet_sha256": sheet_sha256,
            "published_artifacts": [published],
        }

    def _replacement_control_sheet(
        self,
        *,
        context: Any,
        source_dynamics: Mapping[str, Any],
        source_sheet: Mapping[str, Any],
        target_references: Sequence[Path],
    ) -> dict[str, Any]:
        """Generate the internal, source-anchored replacement control sheet."""

        source_path = Path(source_sheet["path"])
        cut_ids = [str(item.get("cut_id") or f"C{index:02d}") for index, item in enumerate(source_dynamics["source_cuts"], start=1)]
        prompt = (
            "Create exactly one ordered-panel replacement control keyframe sheet. "
            f"It contains exactly {len(cut_ids)} panels in this order: {', '.join(cut_ids)}. "
            "Use the source keyframe sheet as the non-negotiable visual base for every matching panel. "
            "Preserve source background, environment topology, image quality, lighting, color treatment, composition, "
            "camera angle, camera distance, pose, gesture, facial expression, gaze, timing state, and continuity. "
            "Replace only the identities/products explicitly supplied in the target reference images. "
            "Do not invent scenery, change framing, add text, UI, logos, props, or people. This is an internal control sheet, not a director storyboard."
        )
        try:
            generated = self._image_client.run_image2(
                prompt=prompt, reference_images=[source_path, *target_references], aspect_ratio="16:9", resolution="2k", quality="medium"
            )
        except Exception as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "RunningHub Image2 replacement control generation failed", retryable=True, category="provider") from exc
        image_bytes = generated.get("image_bytes") if isinstance(generated, Mapping) else None
        self._png_dimensions(image_bytes if isinstance(image_bytes, bytes) else b"")
        digest = hashlib.sha256(image_bytes).hexdigest()
        destination = Path(context.work_dir) / "reference_frames" / "replacement-control-keyframes.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(image_bytes)
        contract = _load_module("scripts/control_keyframe_contract.py", "usfr_control_keyframe_contract")
        manifest = contract.build_control_keyframe_manifest(
            source_dynamics,
            source_video_sha256=str(source_sheet["source_video_sha256"]),
            source_keyframes=list(source_sheet["source_keyframes"]),
            source_keyframe_sheet_sha256=str(source_sheet["source_keyframe_sheet_sha256"]),
            replacement_control_sheet_sha256=digest,
            replacement_target_sha256s=self._visual_target_sha256s(context),
        )
        receipt = contract.validate_control_keyframe_manifest(source_dynamics, manifest)
        published = context.publish_bytes(
            kind="replacement_control_keyframe_sheet", data=image_bytes, content_type="image/png", expected_sha256=digest,
            metadata={"source_keyframe_sheet_sha256": str(source_sheet["source_keyframe_sheet_sha256"]), "control_receipt_sha256": _sha(receipt)},
        )
        published_receipt = _publish_json(context, kind="replacement_control_keyframe_receipt", value=receipt)
        return {"path": destination, "sha256": digest, "receipt": receipt, "published_artifacts": [published, published_receipt]}

    @staticmethod
    def _segment_prompt(
        *,
        segment: Mapping[str, Any],
        cuts: Mapping[str, Mapping[str, Any]],
        visible_text_locks: Sequence[Mapping[str, Any]],
    ) -> str:
        cut_ids = segment.get("cut_ids")
        selected = [cuts[str(cut_id)] for cut_id in cut_ids if str(cut_id) in cuts] if isinstance(cut_ids, list) else []
        if not selected:
            raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard segment has no approved script Cuts")
        beats = []
        for cut in selected:
            beats.append(
                "scene=" + str(cut.get("scene") or "approved source scene")
                + "; action=" + str(cut.get("action") or "approved action")
                + "; camera=" + str(cut.get("camera") or "approved source camera")
            )
        text_instruction = (
            "Reserve clean high-contrast caption strips at the approved source placements for these exact labels; "
            "the deterministic post-Image2 layer will render the final glyphs: "
            + " | ".join(
                f"{','.join(str(value) for value in lock['cut_ids'])} {lock['start_ms']}-{lock['end_ms']}ms: {lock['approved_text']}"
                for lock in visible_text_locks
            )
            if visible_text_locks
            else "Reserve no caption strip; this segment has no approved visible text."
        )
        return (
            "Create one polished landscape 16:9 director production board using the packaged director-storyboard layout: "
            "shared direction, character/target evidence, ordered Cut cards, environment/camera plan, and concise bottom notes. "
            "Use the replacement-control sheet as the non-negotiable visual base. Preserve source background, composition, "
            "image quality, camera language, lighting, action order, and continuity; replace only fixed target identity/product layers. "
            "Do not invent scenery, UI, logos, end cards, props, people, or claims. "
            + text_instruction
            + " Approved segment beats: " + " | ".join(beats)
        )

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        script_cuts = self._script_cuts(context)
        approved_visible_text_locks, approved_visible_text_locks_sha256 = self._approved_visible_text_locks(context)
        source_dynamics = _mapping(
            _stage_output(context, "analyze_dynamics").get("source_dynamics_analysis"),
            "source dynamics analysis",
        )
        route = _stage_output(context, "route_regions").get("timeline_regions")
        regions = _mapping(route, "timeline regions").get("regions")
        if not isinstance(regions, list):
            raise _replication_error("CONTRACT_INVALID", "timeline regions are invalid")
        planner_module = _load_module(
            "bundled-skills/seedance-storyboard-replication/scripts/segment_plan.py",
            "usfr_packaged_segment_plan",
        )
        try:
            segment_plan = planner_module.plan_structured_segments(regions, script_cuts)
        except Exception as exc:
            raise _replication_error("SEGMENT_PLAN_INVALID", "approved script and timeline cannot form one or two 4-15 second generated segments") from exc
        plan_digest = _sha(segment_plan)
        published_plan = _publish_json(
            context,
            kind="segment_plan",
            value=segment_plan,
            metadata={"canonical_json": _canonical(segment_plan).decode("utf-8")},
        )
        result = self._revision.run(context=context, input_artifacts=input_artifacts)
        manifest = result.get("storyboard_revision")
        if not isinstance(manifest, RevisionManifest) or manifest.kind != "storyboard":
            raise _replication_error("CONTRACT_INVALID", "storyboard revision did not return a storyboard manifest")
        segments = segment_plan.get("segments")
        if not isinstance(segments, list) or not 1 <= len(segments) <= 2:
            raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard plan must contain one or two segments")
        script_by_id = {str(item.get("cut_id") or ""): item for item in script_cuts if str(item.get("cut_id") or "")}
        published_images: list[dict[str, Any]] = []
        cut_images: list[StoryboardCutRef] = []
        upstream_artifacts: list[dict[str, Any]] = []
        with self._target_reference_images(context) as target_references:
            # Every semantic generated region uses the exact same visual
            # provenance chain, including source-preserve/language-only work:
            # source Cut frames -> replacement-control sheet -> director board.
            # An empty target list means "preserve source layers", not "skip
            # the control evidence".
            source_sheet = self._source_keyframe_sheet(context, source_dynamics)
            control_sheet = self._replacement_control_sheet(
                context=context,
                source_dynamics=source_dynamics,
                source_sheet=source_sheet,
                target_references=target_references,
            )
            references = [Path(control_sheet["path"]), *target_references]
            upstream_artifacts.extend(list(source_sheet.get("published_artifacts") or []))
            upstream_artifacts.extend(list(control_sheet.get("published_artifacts") or []))
            for segment_index, raw_segment in enumerate(segments):
                segment = _mapping(raw_segment, "storyboard segment")
                segment_id = str(segment.get("segment_id") or "").strip()
                cut_ids = segment.get("cut_ids")
                if not segment_id or not isinstance(cut_ids, list) or not cut_ids:
                    raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard segment is invalid")
                try:
                    segment_text_locks = self._segment_visible_text_locks(
                        approved_visible_text_locks, segment=segment
                    )
                    generated = self._image_client.run_image2(
                        prompt=self._segment_prompt(
                            segment=segment,
                            cuts=script_by_id,
                            visible_text_locks=segment_text_locks,
                        ),
                        reference_images=references,
                        aspect_ratio="16:9",
                        resolution="2k",
                        quality="medium",
                    )
                except ReplicationError:
                    raise
                except Exception as exc:
                    raise _replication_error("CAPABILITY_UNAVAILABLE", f"RunningHub Image2 storyboard generation failed for {segment_id}", retryable=True, category="provider") from exc
                image_bytes = generated.get("image_bytes") if isinstance(generated, Mapping) else None
                image_bytes = self._render_visible_text_layer(
                    image_bytes if isinstance(image_bytes, bytes) else b"", segment_text_locks
                )
                width, height = self._png_dimensions(image_bytes)
                digest = hashlib.sha256(image_bytes).hexdigest()
                segment_number = segment_index + 1
                metadata = {
                    "segment_id": segment_id,
                    "storyboard_revision": manifest.revision,
                    "logical_name": f"storyboards/segment_{segment_number:02d}_v{manifest.revision}.png",
                    "presentation": "image_set",
                    "approval_scope": "all_segments_together",
                    "text_only_substitute_forbidden": True,
                    "storyboard_manifest_sha256": manifest.sha256,
                    "source_video_sha256": str(source_sheet["source_video_sha256"]),
                    "source_keyframe_sheet_sha256": str(source_sheet["source_keyframe_sheet_sha256"]),
                    "replacement_control_keyframe_sheet_sha256": str(control_sheet["sha256"]),
                    "replacement_control_keyframe_receipt_sha256": _sha(_mapping(control_sheet["receipt"], "replacement control receipt")),
                    "replacement_target_sha256s": self._visual_target_sha256s(context),
                    "approved_visible_text_locks_sha256": approved_visible_text_locks_sha256,
                    "visible_text_lock_ids": [str(lock["text_id"]) for lock in segment_text_locks],
                }
                published = context.publish_bytes(
                    kind="storyboard_image",
                    data=image_bytes,
                    content_type="image/png",
                    expected_sha256=digest,
                    metadata=metadata,
                )
                if not isinstance(published, Mapping) or str(published.get("sha256") or "").lower() != digest:
                    raise _replication_error("ARTIFACT_HASH_MISMATCH", "published storyboard image digest differs from Image2 bytes", category="artifact")
                published_images.append(dict(published))
                for cut_id in cut_ids:
                    cut_images.append(
                        StoryboardCutRef(
                            cut_id=str(cut_id), object_key=str(published.get("object_key") or ""), sha256=digest,
                            width=width, height=height,
                        )
                    )
        if not published_images:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "no actual storyboard image was generated", retryable=True, category="capability")
        primary = published_images[0]
        bound_manifest = replace(
            manifest,
            grid_object_key=str(primary.get("object_key") or ""),
            grid_sha256=str(primary.get("sha256") or "").lower(),
            cut_images=tuple(cut_images),
        )
        if not bound_manifest.grid_object_key or _SHA256.fullmatch(str(bound_manifest.grid_sha256 or "")) is None:
            raise _replication_error("CONTRACT_INVALID", "storyboard manifest has no immutable board binding")
        return {
            **dict(result),
            "storyboard_revision": bound_manifest,
            "storyboard_images": published_images,
            "segment_plan": segment_plan,
            "segment_plan_sha256": plan_digest,
            "published_artifacts": [*list(result.get("published_artifacts") or []), published_plan, *upstream_artifacts, *published_images],
        }


class SegmentPlanStage:
    """Freeze the Stage-7 plan again after storyboard approval.

    The preliminary plan shown with the storyboard is review material.  This
    stage is the authoritative post-approval publication point, so prompt and
    provider stages never consume an unapproved or stale duration plan.
    """

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        script_sha = str(getattr(context.snapshot, "approved_script_sha256", "") or "").lower()
        board_sha = str(getattr(context.snapshot, "approved_storyboard_sha256", "") or "").lower()
        if _SHA256.fullmatch(script_sha) is None or _SHA256.fullmatch(board_sha) is None:
            raise _replication_error("APPROVAL_REQUIRED", "Stage-7 segment planning requires both approved revisions")
        script = _read_json_artifact(context, kind="script_revision", sha256=script_sha)
        cuts = script.get("cuts")
        if not isinstance(cuts, list) or not cuts:
            raise _replication_error("CONTRACT_INVALID", "approved script has no Cut timing")
        route = _stage_output(context, "route_regions").get("timeline_regions")
        regions = _mapping(route, "timeline regions").get("regions")
        if not isinstance(regions, list):
            raise _replication_error("CONTRACT_INVALID", "timeline regions are invalid")
        planner_module = _load_module(
            "bundled-skills/seedance-storyboard-replication/scripts/segment_plan.py",
            "usfr_packaged_approved_segment_plan",
        )
        try:
            plan = planner_module.plan_structured_segments(regions, [dict(item) for item in cuts if isinstance(item, Mapping)])
        except Exception as exc:
            raise _replication_error("SEGMENT_PLAN_INVALID", "approved storyboard cannot be mapped to one or two legal generated segments") from exc
        published = _publish_json(
            context,
            kind="segment_plan",
            value=plan,
            metadata={"canonical_json": _canonical(plan).decode("utf-8")},
        )
        return {"status": "ready", "segment_plan": plan, "segment_plan_sha256": _sha(plan), "published_artifacts": [published]}


class SeedancePromptStage:
    """Compile each approved segment with the packaged Seedance-20 compiler."""

    def __init__(self, *, invocation_adapter: Any, uploaded_song_transcriber: Any | None = None) -> None:
        self.invocation_adapter = invocation_adapter
        self.uploaded_song_transcriber = uploaded_song_transcriber

    def _approved_revision(self, context: Any, *, kind: str, digest: str) -> Mapping[str, Any]:
        return _read_json_artifact(context, kind=f"{kind}_revision", sha256=digest)

    @staticmethod
    def _approval_lines(context: Any) -> list[dict[str, Any]]:
        revision = getattr(context.snapshot, "current_script_revision", None)
        getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
        if not isinstance(revision, int) or not callable(getter):
            return []
        sidecar = getter(context.job_id, revision)
        if not isinstance(sidecar, Mapping):
            return []
        rows = sidecar.get("line_contracts")
        if not isinstance(rows, list):
            return []
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    @staticmethod
    def _factor_flags(context: Any) -> dict[str, bool]:
        return {
            "camera": True,
            "motion": True,
            "lighting": True,
            "performance": _present(context, "new_model_image"),
            "characters": _present(context, "new_model_image"),
            "audio": True,
            "sequence": True,
        }

    @staticmethod
    def _reference_roles(context: Any) -> list[dict[str, Any]]:
        """Mirror the immutable Fixed-B upload order in the compiled prompt."""

        roles: list[dict[str, Any]] = [
            {"slot": 1, "tag": "@Image1", "role": "approved storyboard visual control"}
        ]
        for slot_id, limit in (("new_model_image", 1), ("new_product_image", 2)):
            if not _present(context, slot_id):
                continue
            for _index, _digest in enumerate(_slot_sha256s(context, slot_id)[:limit], start=1):
                slot = len(roles) + 1
                roles.append({"slot": slot, "tag": f"@Image{slot}", "role": f"fixed {slot_id} target truth"})
        return roles

    @staticmethod
    def _audio_instruction(
        context: Any,
        *,
        source_music_windows: Sequence[Mapping[str, Any]] | None = None,
        uploaded_audio_kind: str | None = None,
    ) -> str:
        extensions = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("extensions", {})
        music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
        if not isinstance(music, Mapping):
            return ""
        # Songs are applied only by the dedicated RunningHub song-lip-sync
        # post-process.  Seedance must receive neither @Audio1 nor lyrics.
        if uploaded_audio_kind == "song":
            return ""
        if source_music_windows is not None:
            if not source_music_windows:
                return ""
            windows = "; ".join(
                f"{int(window['segment_start_ms'])}-{int(window['segment_end_ms'])}ms"
                for window in source_music_windows
            )
            behavior = (
                "This is a confirmed non-song replacement: no lyrics, singing, or lip-sync performance. "
                if uploaded_audio_kind == "non_song"
                else ""
            )
            return behavior + (
                "Use @Audio1 as the only uploaded audio reference. It is audible only in these exact segment-local "
                f"source music windows: {windows}; keep @Audio1 silent outside them. Do not stretch, loop, advance, "
                "delay, substitute, or add unrelated music or lyrics."
            )
        return (
            "Use @Audio1 as the only uploaded audio reference. Match this segment's approved music cut-in/cut-out exactly; "
            "do not substitute a full-song track, new lyrics, or unrelated music."
        )

    @staticmethod
    def _uploaded_music_present(context: Any) -> bool:
        extensions = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("extensions", {})
        return isinstance(extensions, Mapping) and isinstance(extensions.get("background_music"), Mapping)

    @staticmethod
    def _song_language_hint(lines: Sequence[Mapping[str, Any]]) -> str | None:
        values = {
            str((line.get("language") or {}).get("bcp47") or "").strip()
            for line in lines if isinstance(line.get("language"), Mapping)
        }
        values.discard("")
        return next(iter(values)) if len(values) == 1 else None

    @staticmethod
    def _whisper_window(value: Mapping[str, Any]) -> tuple[int, int, str] | None:
        try:
            start, end = float(value.get("start")), float(value.get("end"))
        except (TypeError, ValueError):
            return None
        if not (start >= 0 and end > start):
            return None
        text = str(value.get("text") or "").strip()
        if not text:
            return None
        return round(start * 1000), round(end * 1000), text

    def _uploaded_song_performance_lines(
        self,
        *,
        context: Any,
        plan: Mapping[str, Any],
        line_contracts: Sequence[Mapping[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Bind pre-script-confirmed uploaded-song lyrics to source performers.

        The transcript is an immutable upstream classification artifact.  It
        must never be created here after the user has approved the script.
        """

        if not self._uploaded_music_present(context) or not line_contracts:
            return {}
        try:
            uploaded_audio = _uploaded_audio_classification(context)
        except Exception:
            return {}
        if uploaded_audio.get("kind") != "song":
            return {}
        timeline_shas = {
            str(line.get("source_content_timeline_sha256") or "").lower()
            for line in line_contracts
        }
        if len(timeline_shas) != 1:
            return {}
        timeline_sha = next(iter(timeline_shas))
        if _SHA256.fullmatch(timeline_sha) is None:
            return {}
        try:
            from .performance_audio_contracts import build_background_music_performance_contract_from_route
            from .singing_audio_router import route_uploaded_audio

            source_timeline = _read_json_artifact(
                context, kind="source_content_timeline", sha256=timeline_sha
            )
            route = route_uploaded_audio(
                source_timeline,
                uploaded_audio_contract=uploaded_audio,
                uploaded_audio_sha256=str(uploaded_audio["audio_sha256"]),
            )
            if route.get("mode") != "pending_uploaded_song_lyrics_confirmation":
                return {}
            windows = route.get("eligible_source_windows")
            raw_segments = plan.get("segments")
            if not isinstance(windows, Sequence) or isinstance(windows, (str, bytes, bytearray)) or not isinstance(raw_segments, list):
                return {}
            generated_segments = [dict(item) for item in raw_segments if isinstance(item, Mapping)]
            if not any(
                int(segment.get("start_ms")) < int(window.get("end_ms"))
                and int(window.get("start_ms")) < int(segment.get("end_ms"))
                for segment in generated_segments for window in windows if isinstance(window, Mapping)
            ):
                return {}
            if not callable(self.uploaded_song_transcriber):
                return {}
            performance_contract = _read_json_artifact(context, kind="performance_line_contract")
            if performance_contract.get("source_content_timeline_sha256") != timeline_sha:
                return {}
            verified = build_background_music_performance_contract_from_route(
                uploaded_audio_route=route,
                performance_line_contract=performance_contract,
            )
            if verified.get("mode") != "verified_singing":
                return {}
            raw_performance = performance_contract.get("cuts")
            singing_lines = verified.get("singing_lines")
            if not isinstance(raw_performance, list) or not isinstance(singing_lines, list) or len(raw_performance) != len(singing_lines):
                return {}
            approved_by_id = {str(line.get("line_id") or ""): line for line in line_contracts}
            canonical_performance: list[dict[str, Any]] = []
            for raw, verified_line in zip(raw_performance, singing_lines):
                if not isinstance(raw, Mapping) or not isinstance(verified_line, Mapping):
                    return {}
                approved = approved_by_id.get(str(raw.get("line_id") or ""))
                if (
                    approved is None
                    or raw.get("cut_id") != approved.get("cut_id")
                    or raw.get("source_content_timeline_sha256") != timeline_sha
                    or raw.get("content_type") != "sung"
                    or raw.get("source_time") != {"start_ms": approved.get("time", {}).get("start_ms"), "end_ms": approved.get("time", {}).get("end_ms")}
                    or raw.get("line_id") != verified_line.get("line_id")
                    or raw.get("source_time") != verified_line.get("source_time")
                    or approved.get("content_type") != "sung"
                    or raw.get("speaker_assignment") != approved.get("speaker_assignment")
                ):
                    return {}
                # The source contract locks the visible singer, performance,
                # and source window.  The approved script supplies the new
                # song lyric; it must still match the bounded uploaded-song
                # transcript exactly before it reaches the compiler.
                candidate = dict(raw)
                candidate["exact_sung_text"] = str((approved.get("text") or {}).get("exact") or "").strip()
                candidate["speaker_assignment"] = dict(approved["speaker_assignment"])
                if not candidate["exact_sung_text"]:
                    return {}
                canonical_performance.append(candidate)
            raw_lyrics = uploaded_audio.get("lyrics")
            if not isinstance(raw_lyrics, Sequence) or isinstance(raw_lyrics, (str, bytes, bytearray)):
                return {}
            observed = []
            for raw in raw_lyrics:
                if not isinstance(raw, Mapping):
                    return {}
                try:
                    observed.append((int(raw["start_ms"]), int(raw["end_ms"]), str(raw["text"]).strip()))
                except (KeyError, TypeError, ValueError):
                    return {}
            for line in canonical_performance:
                expected_text = " ".join(str(line["exact_sung_text"]).split()).casefold()
                matches = [
                    (start_ms, end_ms)
                    for start_ms, end_ms, text in observed
                    if " ".join(text.split()).casefold() == expected_text
                ]
                if len(matches) != 1:
                    return {}
                start_ms, end_ms = matches[0]
                if start_ms < 0 or end_ms <= start_ms:
                    return {}
                line["uploaded_song_time"] = {"start_ms": start_ms, "end_ms": end_ms}
            by_cut = {str(line.get("cut_id") or ""): line for line in canonical_performance}
            result: dict[str, list[dict[str, Any]]] = {}
            for segment in generated_segments:
                segment_id = str(segment.get("segment_id") or "")
                cut_ids = segment.get("cut_ids")
                if not segment_id or not isinstance(cut_ids, list):
                    return {}
                segment_lines = [by_cut.get(str(cut_id)) for cut_id in cut_ids]
                if all(isinstance(line, Mapping) for line in segment_lines):
                    result[segment_id] = [dict(line) for line in segment_lines if isinstance(line, Mapping)]
            return result
        except Exception:
            return {}

    def _source_song_performance_lines(
        self,
        *,
        context: Any,
        plan: Mapping[str, Any],
        line_contracts: Sequence[Mapping[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Bind confirmed source-song lyrics to their visible source singers.

        This is the default path when no replacement song was uploaded.  It
        consumes the source-audio transcript already frozen by dynamics and the
        user-confirmed script lines; it must never silently turn an eligible
        singer into generic background music.
        """

        if self._uploaded_music_present(context) or not line_contracts:
            return {}
        timeline_shas = {
            str(line.get("source_content_timeline_sha256") or "").lower()
            for line in line_contracts
        }
        if len(timeline_shas) != 1:
            return {}
        timeline_sha = next(iter(timeline_shas))
        if _SHA256.fullmatch(timeline_sha) is None:
            return {}
        try:
            from .singing_audio_router import route_uploaded_audio

            source_timeline = _read_json_artifact(
                context, kind="source_content_timeline", sha256=timeline_sha
            )
            route = route_uploaded_audio(source_timeline)
            if route.get("mode") != "pending_source_lyrics_confirmation":
                return {}
            windows = route.get("eligible_source_windows")
            raw_segments = plan.get("segments")
            if not isinstance(windows, Sequence) or isinstance(windows, (str, bytes, bytearray)) or not isinstance(raw_segments, list):
                return {}
            generated_segments = [dict(item) for item in raw_segments if isinstance(item, Mapping)]
            performance_contract = _read_json_artifact(context, kind="performance_line_contract")
            if performance_contract.get("source_content_timeline_sha256") != timeline_sha:
                return {}
            raw_performance = performance_contract.get("cuts")
            if not isinstance(raw_performance, list):
                return {}
            approved_by_id = {str(line.get("line_id") or ""): line for line in line_contracts}
            eligible_by_line = {
                str(window.get("line_id") or ""): window
                for window in windows
                if isinstance(window, Mapping)
            }
            canonical_performance: list[dict[str, Any]] = []
            for raw in raw_performance:
                if not isinstance(raw, Mapping):
                    return {}
                approved = approved_by_id.get(str(raw.get("line_id") or ""))
                window = eligible_by_line.get(str(raw.get("line_id") or ""))
                if not isinstance(approved, Mapping) or not isinstance(window, Mapping):
                    return {}
                expected_source = {
                    "start_ms": approved.get("time", {}).get("start_ms"),
                    "end_ms": approved.get("time", {}).get("end_ms"),
                }
                assignment = approved.get("speaker_assignment")
                if (
                    raw.get("cut_id") != approved.get("cut_id")
                    or raw.get("source_content_timeline_sha256") != timeline_sha
                    or raw.get("content_type") != "sung"
                    or approved.get("content_type") != "sung"
                    or raw.get("source_time") != expected_source
                    or raw.get("speaker_assignment") != assignment
                    or not isinstance(assignment, Mapping)
                    or assignment.get("speaker_id") != window.get("speaker_id")
                ):
                    return {}
                candidate = dict(raw)
                candidate["exact_sung_text"] = str((approved.get("text") or {}).get("exact") or "").strip()
                candidate["speaker_assignment"] = dict(assignment)
                if not candidate["exact_sung_text"]:
                    return {}
                canonical_performance.append(candidate)
            if not canonical_performance:
                return {}
            by_cut = {str(line.get("cut_id") or ""): line for line in canonical_performance}
            result: dict[str, list[dict[str, Any]]] = {}
            for segment in generated_segments:
                segment_id = str(segment.get("segment_id") or "")
                cut_ids = segment.get("cut_ids")
                if not segment_id or not isinstance(cut_ids, list):
                    return {}
                segment_lines = [by_cut.get(str(cut_id)) for cut_id in cut_ids]
                if all(isinstance(line, Mapping) for line in segment_lines):
                    result[segment_id] = [dict(line) for line in segment_lines if isinstance(line, Mapping)]
            return result
        except Exception:
            return {}

    @staticmethod
    def _no_speech(cut_ids: Sequence[str]) -> list[dict[str, Any]]:
        return [
            {"cut_id": cut_id, "speech_mode": "none", "allowed_audio": ["approved music, ambience, and foley"], "forbidden_audio": ["unapproved dialogue"]}
            for cut_id in cut_ids
        ]

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        script_sha = str(getattr(context.snapshot, "approved_script_sha256", "") or "").lower()
        storyboard_sha = str(getattr(context.snapshot, "approved_storyboard_sha256", "") or "").lower()
        if _SHA256.fullmatch(script_sha) is None or _SHA256.fullmatch(storyboard_sha) is None:
            raise _replication_error("APPROVAL_REQUIRED", "Seedance compilation requires both approved revisions")
        script = self._approved_revision(context, kind="script", digest=script_sha)
        storyboard = self._approved_revision(context, kind="storyboard", digest=storyboard_sha)
        plan = _read_json_artifact(context, kind="segment_plan")
        segments = plan.get("segments")
        if not isinstance(segments, list) or not 1 <= len(segments) <= 2:
            raise _replication_error("SEGMENT_PLAN_INVALID", "frozen segment plan must contain one or two segments")
        script_cuts = {str(item.get("cut_id") or ""): dict(item) for item in script.get("cuts") or [] if isinstance(item, Mapping)}
        board_cuts = {str(item.get("cut_id") or ""): dict(item) for item in storyboard.get("cuts") or [] if isinstance(item, Mapping)}
        if not script_cuts or set(script_cuts) != set(board_cuts):
            raise _replication_error("PROMPT_INTEGRITY_FAILED", "approved script and storyboard Cut coverage differs")
        lines = self._approval_lines(context)
        extensions = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("extensions", {})
        uploaded_audio = (
            _uploaded_audio_classification(context)
            if isinstance(extensions, Mapping) and isinstance(extensions.get("background_music"), Mapping)
            else None
        )
        uploaded_audio_kind = str(uploaded_audio.get("kind") or "") if uploaded_audio else None
        source_audio_present = any(
            item.get("kind") in {"performance_audio_source_contract", "audio_lyrics_beat_contract"}
            for item in (getattr(context, "artifacts", ()) or ()) if isinstance(item, Mapping)
        )
        if source_audio_present and not lines and uploaded_audio_kind != "non_song":
            raise _replication_error("APPROVAL_REQUIRED", "source audio requires user-confirmed speaker and line contracts before compilation")
        compiler = _load_module("scripts/seedance_prompt_compiler.py", "usfr_packaged_seedance_prompt_compiler")
        skill_files = getattr(self.invocation_adapter, "prompt_skill_files", None)
        if not isinstance(skill_files, Mapping) or not skill_files:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "immutable Seedance-20 compiler bytes are unavailable", retryable=True, category="capability")
        plan_sha = _sha(plan)
        source_music_windows = (
            _uploaded_audio_source_music_windows(context)
            if self._uploaded_music_present(context)
            else []
        )
        source_song_performance = self._source_song_performance_lines(
            context=context, plan=plan, line_contracts=lines
        )
        uploaded_song_performance = self._uploaded_song_performance_lines(
            context=context, plan=plan, line_contracts=lines
        )
        if uploaded_audio_kind == "song" and not uploaded_song_performance:
            raise _replication_error(
                "PERFORMANCE_LINE_CONTRACT_REQUIRED",
                "uploaded lyric song is missing the source-verified lyric and performer contract required for lip-sync compilation",
            )
        outputs: list[dict[str, Any]] = []
        for raw_segment in segments:
            segment_row = _mapping(raw_segment, "segment plan row")
            segment_id = str(segment_row.get("segment_id") or "")
            cut_ids = segment_row.get("cut_ids")
            if not segment_id or not isinstance(cut_ids, list) or not cut_ids:
                raise _replication_error("SEGMENT_PLAN_INVALID", "segment plan row is invalid")
            try:
                duration_ms = int(segment_row["duration_ms"])
                global_start = int(segment_row["start_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("SEGMENT_PLAN_INVALID", "segment plan timing is invalid") from exc
            segment_music_windows = _segment_music_window_bindings(
                source_music_windows,
                segment_start_ms=global_start,
                segment_end_ms=global_start + duration_ms,
            )
            uploaded_music_instruction = self._audio_instruction(
                context,
                source_music_windows=segment_music_windows,
                uploaded_audio_kind=uploaded_audio_kind,
            )
            shots: list[dict[str, Any]] = []
            for index, cut_id in enumerate(cut_ids, start=1):
                cut = script_cuts.get(str(cut_id))
                board = board_cuts.get(str(cut_id))
                if cut is None or board is None:
                    raise _replication_error("PROMPT_INTEGRITY_FAILED", "segment references an unapproved Cut")
                start_ms = int(cut.get("start_ms")) - global_start
                end_ms = int(cut.get("end_ms")) - global_start
                shots.append({
                    "shot_id": str(cut_id), "start_ms": start_ms, "end_ms": end_ms,
                    "shot_scale": str(board.get("composition") or "approved composition"),
                    "scene": str(cut.get("scene") or "approved source scene"),
                    "camera": str(cut.get("camera") or board.get("camera") or "approved camera"),
                    "lighting": "match the approved storyboard lighting and source evidence",
                    "performance": str(cut.get("delivery") or "natural source-equivalent delivery"),
                    "action": str(cut.get("action") or "complete the approved action"),
                    "endpoint": str(board.get("continuity") or "reach the approved Cut endpoint"),
                    "product_or_ui_truth": str(cut.get("visual") or "use only approved target evidence"),
                    "commercial_proof": str((cut.get("selling_point") or {}).get("proof", {}).get("evidence_id") or "approved target evidence"),
                    "transition": "match the source Cut transition", "continuity": str(board.get("continuity") or "preserve continuity"),
                    "audio": "no dialogue" if uploaded_audio_kind == "song" else " ".join(filter(None, (str(cut.get("dialogue") or "no dialogue"), uploaded_music_instruction))),
                    "factor_ids": [f"{cut_id}.scene", f"{cut_id}.camera", f"{cut_id}.action", f"{cut_id}.audio"],
                })
            local_lines = [line for line in lines if str(line.get("cut_id") or "") in set(cut_ids)]
            local_performance = source_song_performance.get(
                segment_id, uploaded_song_performance.get(segment_id, [])
            )
            if uploaded_audio_kind == "song" and not local_performance:
                raise _replication_error(
                    "PERFORMANCE_LINE_CONTRACT_REQUIRED",
                    f"{segment_id} has an uploaded lyric song without a verified lyric lip-sync contract",
                )
            expected_sung_lines = [
                line for line in local_lines if line.get("content_type") == "sung"
            ] if uploaded_audio_kind != "non_song" else []
            if expected_sung_lines and len(local_performance) != len(expected_sung_lines):
                raise _replication_error(
                    "PERFORMANCE_LINE_CONTRACT_REQUIRED",
                    f"{segment_id} has confirmed sung lines without a source-verified lyric and performer contract",
                )
            segment = {
                "segment_id": segment_id,
                "duration_ms": duration_ms,
                "output_global_start_ms": global_start,
                "cut_ids": list(cut_ids),
                "opening_state": str(board_cuts[str(cut_ids[0])].get("composition") or "approved opening storyboard state"),
                "reference_roles": self._reference_roles(context),
                "shots": shots,
                "locks": ["preserve approved Cut order", "preserve approved character and product evidence"],
                "negative_constraints": ["no unapproved text", "no UI or tail media generation", "no generic quality filler"],
                "no_speech_contracts": [] if local_lines and uploaded_audio_kind not in {"non_song", "song"} else self._no_speech([str(item) for item in cut_ids]),
            }
            try:
                artifact = compiler.compile_prompt(
                    segment=segment,
                    # Uploaded lyric songs are lip-synced only after the
                    # generated-person video exists.  Keep their verified
                    # contract outside Seedance rather than asking Seedance
                    # to render audio, lyrics, or mouth timing.
                    line_contracts=[] if uploaded_audio_kind in {"non_song", "song"} else local_lines,
                    performance_lines=[] if uploaded_audio_kind == "song" else local_performance,
                    factors=self._factor_flags(context),
                    skill_files=skill_files,
                    compiler_checks={
                        "professional_gate": True, "capability_check": True, "allocation_check": True,
                        "reference_role_check": True, "directing_coherence_check": True, "anti_slop_check": True,
                        "route_exclusion_check": True, "line_parity_check": True,
                    },
                    review_bindings={
                        "output_language": getattr(context.snapshot, "slots_manifest", {}).get("output_language"),
                        "approved_script_sha256": script_sha,
                        "approved_storyboard_manifest_sha256": storyboard_sha,
                        "approved_storyboard_cut_sha256s": [storyboard_sha for _ in cut_ids],
                        "segment_plan_sha256": plan_sha,
                    },
                )
            except Exception as exc:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", f"Seedance-20 compiler rejected {segment_id}") from exc
            row = {"segment_id": segment_id, "compiled_prompt": artifact, "segment_plan_sha256": plan_sha}
            if uploaded_audio_kind == "song":
                song_starts = [
                    int(line["uploaded_song_time"]["start_ms"])
                    for line in local_performance
                    if isinstance(line.get("uploaded_song_time"), Mapping)
                ]
                if not song_starts:
                    raise _replication_error(
                        "PERFORMANCE_LINE_CONTRACT_REQUIRED",
                        f"{segment_id} has no unambiguous uploaded-song time binding",
                    )
                song_start_seconds = min(song_starts) // 1000
                song_end_seconds = (min(song_starts) + duration_ms + 999) // 1000
                if song_end_seconds <= song_start_seconds:
                    raise _replication_error(
                        "PERFORMANCE_LINE_CONTRACT_REQUIRED",
                        f"{segment_id} has an invalid uploaded-song lip-sync window",
                    )
                song_start = f"{song_start_seconds // 60}:{song_start_seconds % 60:02d}"
                song_end = f"{song_end_seconds // 60}:{song_end_seconds % 60:02d}"
                row["song_lip_sync_contract"] = {
                    "schema_version": "uploaded-song-lip-sync-contract/v1",
                    "segment_id": segment_id,
                    "segment_plan_sha256": plan_sha,
                    "performance_lines": local_performance,
                    "song_start": song_start,
                    "song_end": song_end,
                }
            outputs.append(row)
        envelope = {"schema_version": "seedance-input-contract/v1", "segment_plan": plan, "segment_plan_sha256": plan_sha, "segments": outputs}
        published = _publish_json(context, kind="seedance_input_contract", value=envelope)
        return {"status": "ready", "seedance_input_contract": envelope, "published_artifacts": [published]}


class SeedanceAuditStage:
    """Validate and freeze canonical provider-ready payloads without paying."""

    def __init__(
        self,
        *,
        provider: Any,
        media_uploader: Any,
        video_segmenter: Any | None = None,
        audio_segmenter: Any | None = None,
        audit_secret: str | None = None,
    ) -> None:
        self.provider = provider
        if not callable(getattr(media_uploader, "upload_media", None)):
            raise _replication_error("CAPABILITY_UNAVAILABLE", "RunningHub media upload adapter is required", retryable=True, category="capability")
        self.media_uploader = media_uploader
        # Production uses the bundled source-video reference materializer.  An
        # injected segmenter is intentionally retained only as a test seam.
        self.video_segmenter = video_segmenter
        if self.video_segmenter is not None and not callable(self.video_segmenter):
            raise _replication_error("CAPABILITY_UNAVAILABLE", "source video segment adapter is required", retryable=True, category="capability")
        self.audio_segmenter = audio_segmenter or self._ffmpeg_audio_segment
        if not callable(self.audio_segmenter):
            raise _replication_error("CAPABILITY_UNAVAILABLE", "uploaded-song segment adapter is required", retryable=True, category="capability")
        self.audit_secret = audit_secret

    @staticmethod
    def _ffmpeg_source_segment(*, source_path: Path, start_ms: int, end_ms: int, destination: Path) -> Path:
        duration_ms = end_ms - start_ms
        command = [
            "ffmpeg", "-v", "error", "-y", "-ss", f"{start_ms / 1000:.3f}", "-i", str(source_path),
            "-t", f"{duration_ms / 1000:.3f}", "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac",
            "-movflags", "+faststart", "-map_metadata", "-1", str(destination),
        ]
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "ffmpeg could not create the bounded source video reference", retryable=True, category="capability") from exc
        return destination

    @staticmethod
    def _ffmpeg_audio_segment(
        *,
        source_path: Path,
        start_ms: int,
        end_ms: int,
        source_music_windows: Sequence[Mapping[str, Any]],
        destination: Path,
    ) -> Path:
        """Render a segment-long uploaded-audio reference with exact silent gaps."""

        duration_ms = end_ms - start_ms
        if duration_ms <= 0 or not source_music_windows:
            raise _replication_error("SOURCE_MUSIC_WINDOW_REQUIRED", "uploaded audio requires an observed source music window")
        filters: list[str] = []
        labels: list[str] = []
        cursor_ms = 0
        for index, raw in enumerate(source_music_windows):
            if not isinstance(raw, Mapping):
                raise _replication_error("SOURCE_MUSIC_WINDOW_INVALID", "source music window is invalid")
            try:
                local_start = int(raw["segment_start_ms"])
                local_end = int(raw["segment_end_ms"])
                uploaded_start = int(raw["uploaded_start_ms"])
                uploaded_end = int(raw["uploaded_end_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("SOURCE_MUSIC_WINDOW_INVALID", "source music window is invalid") from exc
            if (
                local_start < cursor_ms
                or local_end <= local_start
                or local_end > duration_ms
                or uploaded_start < 0
                or uploaded_end - uploaded_start != local_end - local_start
            ):
                raise _replication_error("SOURCE_MUSIC_WINDOW_INVALID", "source music windows do not form an exact replacement timeline")
            if local_start > cursor_ms:
                label = f"silence_{index}"
                filters.append(f"anullsrc=r=44100:cl=stereo:d={(local_start - cursor_ms) / 1000:.3f}[{label}]")
                labels.append(f"[{label}]")
            label = f"music_{index}"
            filters.append(
                f"[0:a]atrim=start={uploaded_start / 1000:.3f}:end={uploaded_end / 1000:.3f},"
                f"asetpts=PTS-STARTPTS,aresample=44100[{label}]"
            )
            labels.append(f"[{label}]")
            cursor_ms = local_end
        if cursor_ms < duration_ms:
            label = "silence_tail"
            filters.append(f"anullsrc=r=44100:cl=stereo:d={(duration_ms - cursor_ms) / 1000:.3f}[{label}]")
            labels.append(f"[{label}]")
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1,aresample=44100[outa]")
        command = [
            "ffmpeg", "-v", "error", "-y", "-i", str(source_path),
            "-filter_complex", ";".join(filters), "-map", "[outa]", "-vn", "-ac", "2", "-ar", "44100",
            "-c:a", "pcm_s16le", "-map_metadata", "-1", str(destination),
        ]
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "ffmpeg could not create the bounded uploaded-song reference", retryable=True, category="capability") from exc
        return destination

    @staticmethod
    def _storyboard_descriptor(context: Any, *, segment_id: str) -> Mapping[str, Any]:
        revision = getattr(getattr(context, "snapshot", None), "current_storyboard_revision", None)
        matches = []
        for artifact in (getattr(context, "artifacts", ()) or ()):
            if not isinstance(artifact, Mapping) or artifact.get("kind") != "storyboard_image":
                continue
            metadata = artifact.get("metadata")
            if not isinstance(metadata, Mapping) or metadata.get("segment_id") != segment_id:
                continue
            if isinstance(revision, int) and metadata.get("storyboard_revision") != revision:
                continue
            matches.append(artifact)
        if len(matches) != 1:
            raise _replication_error("ARTIFACT_NOT_FOUND", f"exactly one approved Image2 storyboard is required for {segment_id}", category="artifact")
        descriptor = matches[0]
        artifact_id = str(descriptor.get("artifact_id") or "")
        digest = str(descriptor.get("sha256") or "").lower()
        if not artifact_id or _SHA256.fullmatch(digest) is None:
            raise _replication_error("CONTRACT_INVALID", "storyboard artifact descriptor is invalid", category="artifact")
        return descriptor

    def _upload_storyboard(self, context: Any, *, segment_id: str) -> str:
        descriptor = self._storyboard_descriptor(context, segment_id=segment_id)
        artifact_id = str(descriptor["artifact_id"])
        digest = str(descriptor["sha256"]).lower()
        try:
            with context.materialize_artifact("storyboard_image", artifact_id=artifact_id, sha256=digest) as media:
                path = Path(media.path)
                data = path.read_bytes()
                StoryboardStage._png_dimensions(data)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise _replication_error("ARTIFACT_HASH_MISMATCH", "storyboard bytes differ from the approved artifact", category="artifact")
                url = self.media_uploader.upload_media(path)
        except ReplicationError:
            raise
        except Exception as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", f"RunningHub storyboard media upload failed for {segment_id}", retryable=True, category="provider") from exc
        if not isinstance(url, str) or not url.strip():
            raise _replication_error("CAPABILITY_UNAVAILABLE", "RunningHub storyboard upload returned no URL", retryable=True, category="provider")
        return url.strip()

    def _target_reference_urls(self, context: Any, *, prompt: str) -> tuple[list[str], list[dict[str, str]]]:
        urls: list[str] = []
        target_changes: list[dict[str, str]] = []
        # Fixed slot order is also the RunningHub reference order: @Image1 is
        # storyboard, then one model board, then up to two product boards.
        for slot_id, maximum in (("new_model_image", 1), ("new_product_image", 2)):
            if not _present(context, slot_id):
                continue
            hashes = _slot_sha256s(context, slot_id)
            for index in range(min(maximum, len(hashes))):
                tag = f"@Image{len(urls) + 2}"
                if tag not in prompt:
                    raise _replication_error("PROMPT_INTEGRITY_FAILED", f"compiled Seedance prompt omits required {tag} {slot_id} reference")
                try:
                    with context.materialize_slot(slot_id, index=index) as media:
                        path = Path(media.path)
                        if not path.is_file() or path.stat().st_size <= 0:
                            raise _replication_error("ARTIFACT_NOT_FOUND", f"{slot_id}[{index}] is unavailable", category="artifact")
                        url = self.media_uploader.upload_media(path)
                except ReplicationError:
                    raise
                except Exception as exc:
                    raise _replication_error("CAPABILITY_UNAVAILABLE", f"RunningHub upload failed for {slot_id}[{index}]", retryable=True, category="provider") from exc
                if not isinstance(url, str) or not url.strip():
                    raise _replication_error("CAPABILITY_UNAVAILABLE", f"RunningHub upload returned no URL for {slot_id}[{index}]", retryable=True, category="provider")
                urls.append(url.strip())
                target_changes.append({"kind": slot_id, "sha256": hashes[index]})
        output_language = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("output_language")
        if isinstance(output_language, str) and output_language.strip():
            target_changes.append({"kind": "output_language", "value": output_language.strip()})
        extensions = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("extensions", {})
        music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
        if isinstance(music, Mapping):
            hashes = music.get("sha256")
            if (
                not isinstance(hashes, list)
                or len(hashes) != 1
                or _SHA256.fullmatch(str(hashes[0]).lower()) is None
            ):
                raise _replication_error("INPUT_SLOT_INVALID", "background_music immutable upload evidence is invalid", category="input")
            target_changes.append({"kind": "background_music", "sha256": str(hashes[0]).lower()})
        return urls, target_changes

    @staticmethod
    def _final_target_descriptors(
        *, target_urls: Sequence[str], target_changes: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Project only uploaded model/product pixels into final Image slots.

        ``target_changes`` also carries non-image authorizations (language and
        music), which are valid for the public source-video receipt but must
        never masquerade as a final image reference.
        """

        visual_changes = [
            item for item in target_changes
            if isinstance(item, Mapping) and item.get("kind") in {"new_model_image", "new_product_image"}
        ]
        if len(visual_changes) != len(target_urls):
            raise _replication_error(
                "PROMPT_INTEGRITY_FAILED",
                "final Seedance target image slots do not match the fixed-slot authorization",
            )
        descriptors: list[dict[str, Any]] = []
        for index, (url, change) in enumerate(zip(target_urls, visual_changes, strict=True), start=2):
            digest = str(change.get("sha256") or "").lower()
            kind = str(change.get("kind") or "")
            if not isinstance(url, str) or not url.strip() or _SHA256.fullmatch(digest) is None:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "final target image descriptor is invalid")
            descriptors.append({"kind": kind, "sha256": digest, "image_slot": index, "url": url})
        return descriptors

    @staticmethod
    def _approved_board_descriptor(
        context: Any,
        *,
        segment_id: str,
        segment: Mapping[str, Any],
        descriptor: Mapping[str, Any],
        storyboard_url: str,
    ) -> dict[str, Any]:
        """Bind the uploaded board to the current user-approved revision.

        The Image2 artifact is not sufficient by itself: it must be the board
        produced from the recorded source/control chain and the revision that
        the user actually approved.  Durable worker contexts expose a job-store
        revision; lightweight unit contexts retain only schema validation.
        """

        artifact_id = str(descriptor.get("artifact_id") or "").strip()
        object_key = str(descriptor.get("object_key") or "").strip()
        digest = str(descriptor.get("sha256") or "").lower()
        metadata = descriptor.get("metadata")
        required_metadata = (
            "storyboard_manifest_sha256",
            "source_video_sha256",
            "source_keyframe_sheet_sha256",
            "replacement_control_keyframe_sheet_sha256",
            "replacement_control_keyframe_receipt_sha256",
            "approved_visible_text_locks_sha256",
        )
        if (
            not artifact_id
            or not object_key
            or _SHA256.fullmatch(digest) is None
            or not isinstance(metadata, Mapping)
            or metadata.get("segment_id") != segment_id
            or not isinstance(metadata.get("storyboard_revision"), int)
            or isinstance(metadata.get("storyboard_revision"), bool)
            or int(metadata["storyboard_revision"]) < 1
            or any(_SHA256.fullmatch(str(metadata.get(key) or "").lower()) is None for key in required_metadata)
        ):
            raise _replication_error("CONTRACT_INVALID", "approved storyboard lineage metadata is incomplete", category="artifact")
        targets = metadata.get("replacement_target_sha256s")
        lock_ids = metadata.get("visible_text_lock_ids")
        if (
            not isinstance(targets, list)
            or any(_SHA256.fullmatch(str(value).lower()) is None for value in targets)
            or not isinstance(lock_ids, list)
            or any(not isinstance(value, str) or not value.strip() for value in lock_ids)
            or len(set(lock_ids)) != len(lock_ids)
        ):
            raise _replication_error("CONTRACT_INVALID", "approved storyboard target lineage is invalid", category="artifact")
        source_sha256s = _slot_sha256s(context, "source_video")
        current_targets = StoryboardStage._visual_target_sha256s(context)
        if (
            len(source_sha256s) != 1
            or str(metadata["source_video_sha256"]).lower() != source_sha256s[0]
            or [str(value).lower() for value in targets] != current_targets
        ):
            raise _replication_error("CONTRACT_INVALID", "approved storyboard source or target lineage differs from current fixed inputs", category="artifact")

        snapshot = getattr(context, "snapshot", None)
        approved_sha = str(getattr(snapshot, "approved_storyboard_sha256", "") or "").lower()
        current_revision = getattr(snapshot, "current_storyboard_revision", None)
        if approved_sha:
            if (
                _SHA256.fullmatch(approved_sha) is None
                or approved_sha != str(metadata["storyboard_manifest_sha256"]).lower()
                or current_revision != metadata["storyboard_revision"]
            ):
                raise _replication_error("APPROVAL_REQUIRED", "storyboard artifact is not bound to the current approved revision")

        store = getattr(context, "job_store", None)
        getter = getattr(store, "get_current_revision", None)
        if callable(getter):
            try:
                revision = getter(context.job_id, "storyboard")
            except Exception as exc:
                raise _replication_error("ARTIFACT_NOT_FOUND", "current storyboard approval cannot be loaded", category="artifact") from exc
            if (
                not isinstance(revision, RevisionManifest)
                or revision.kind != "storyboard"
                or revision.status != "APPROVED"
                or revision.revision != metadata["storyboard_revision"]
                or revision.sha256 != str(metadata["storyboard_manifest_sha256"]).lower()
                or revision.sha256 != approved_sha
            ):
                raise _replication_error("APPROVAL_REQUIRED", "storyboard artifact is not the current approved revision")
            bound_hashes = {str(item.sha256).lower() for item in revision.cut_images}
            if digest not in bound_hashes and str(revision.grid_sha256 or "").lower() != digest:
                raise _replication_error("CONTRACT_INVALID", "approved storyboard revision does not bind the uploaded board", category="artifact")
            segment_cut_ids = segment.get("cut_ids")
            if not isinstance(segment_cut_ids, list) or not segment_cut_ids:
                raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard segment Cut coverage is invalid")
            for cut_id in segment_cut_ids:
                matches = [item for item in revision.cut_images if item.cut_id == cut_id]
                if (
                    len(matches) != 1
                    or str(matches[0].sha256).lower() != digest
                    or matches[0].object_key != object_key
                ):
                    raise _replication_error("CONTRACT_INVALID", "approved storyboard revision has no exact board binding for every segment Cut", category="artifact")
            script_revision = getattr(snapshot, "current_script_revision", None)
            get_script_approval = getattr(store, "get_script_approval", None)
            if (
                isinstance(script_revision, bool)
                or not isinstance(script_revision, int)
                or script_revision < 1
                or not callable(get_script_approval)
            ):
                raise _replication_error("APPROVAL_REQUIRED", "approved script text lock authority is unavailable")
            sidecar = get_script_approval(context.job_id, script_revision)
            if not isinstance(sidecar, Mapping):
                raise _replication_error("APPROVAL_REQUIRED", "approved script text lock sidecar is unavailable")
            try:
                locks = canonicalize_visible_text_locks(sidecar.get("visible_text_locks") or [])
            except VisibleTextContractError as exc:
                raise _replication_error("CONTRACT_INVALID", "approved script visible text locks are invalid") from exc
            lock_sha = str(sidecar.get("visible_text_locks_sha256") or "").lower()
            if (
                str(sidecar.get("script_sha256") or "").lower()
                != str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
                or visible_text_locks_sha256(locks) != lock_sha
                or str(metadata["approved_visible_text_locks_sha256"]).lower() != lock_sha
            ):
                raise _replication_error("CONTRACT_INVALID", "approved storyboard visible text lock lineage is stale", category="artifact")
            expected_lock_ids = [
                str(lock["text_id"])
                for lock in StoryboardStage._segment_visible_text_locks(locks, segment=segment)
            ]
            if list(lock_ids) != expected_lock_ids:
                raise _replication_error("CONTRACT_INVALID", "approved storyboard visible text placement is incomplete", category="artifact")

        return {
            "artifact_id": artifact_id,
            "object_key": object_key,
            "kind": "storyboard_image",
            "sha256": digest,
            "segment_id": segment_id,
            "storyboard_revision": int(metadata["storyboard_revision"]),
            "storyboard_manifest_sha256": str(metadata["storyboard_manifest_sha256"]).lower(),
            "url": storyboard_url,
            "source_video_sha256": str(metadata["source_video_sha256"]).lower(),
            "source_keyframe_sheet_sha256": str(metadata["source_keyframe_sheet_sha256"]).lower(),
            "replacement_control_keyframe_sheet_sha256": str(metadata["replacement_control_keyframe_sheet_sha256"]).lower(),
            "replacement_control_keyframe_receipt_sha256": str(metadata["replacement_control_keyframe_receipt_sha256"]).lower(),
            "replacement_target_sha256s": [str(value).lower() for value in targets],
            "approved_visible_text_locks_sha256": str(metadata["approved_visible_text_locks_sha256"]).lower(),
        }

    @staticmethod
    def _validate_internal_board_lineage(context: Any, *, approved_board: Mapping[str, Any]) -> None:
        """Verify that board metadata names real, matching upstream artifacts.

        This is a durable-worker gate.  A local unit double without a JobStore
        is deliberately not treated as production authority, while a real
        worker must materialize the published receipt rather than trust JSON
        fields copied into the board metadata.
        """

        if not callable(getattr(getattr(context, "job_store", None), "get_current_revision", None)):
            return
        artifacts = getattr(context, "artifacts", ()) or ()

        def descriptor(kind: str, digest: str) -> Mapping[str, Any]:
            matches = [
                item
                for item in artifacts
                if isinstance(item, Mapping)
                and item.get("kind") == kind
                and str(item.get("sha256") or "").lower() == digest
            ]
            if len(matches) != 1:
                raise _replication_error("ARTIFACT_NOT_FOUND", f"approved storyboard requires exactly one {kind} artifact", category="artifact")
            item = matches[0]
            if not str(item.get("artifact_id") or "").strip() or not str(item.get("object_key") or "").strip():
                raise _replication_error("CONTRACT_INVALID", f"{kind} artifact has no immutable identity", category="artifact")
            return item

        source_sheet = descriptor("source_keyframe_sheet", str(approved_board["source_keyframe_sheet_sha256"]))
        control_sheet = descriptor(
            "replacement_control_keyframe_sheet",
            str(approved_board["replacement_control_keyframe_sheet_sha256"]),
        )
        descriptor(
            "replacement_control_keyframe_receipt",
            str(approved_board["replacement_control_keyframe_receipt_sha256"]),
        )
        source_metadata = source_sheet.get("metadata")
        control_metadata = control_sheet.get("metadata")
        if (
            not isinstance(source_metadata, Mapping)
            or not isinstance(control_metadata, Mapping)
            or str(source_metadata.get("source_video_sha256") or "").lower()
            != approved_board["source_video_sha256"]
            or str(control_metadata.get("source_keyframe_sheet_sha256") or "").lower()
            != approved_board["source_keyframe_sheet_sha256"]
            or str(control_metadata.get("control_receipt_sha256") or "").lower()
            != approved_board["replacement_control_keyframe_receipt_sha256"]
        ):
            raise _replication_error("CONTRACT_INVALID", "approved storyboard control artifact metadata is inconsistent", category="artifact")
        try:
            receipt = _read_json_artifact(
                context,
                kind="replacement_control_keyframe_receipt",
                sha256=str(approved_board["replacement_control_keyframe_receipt_sha256"]),
            )
            dynamics = _mapping(
                _stage_output(context, "analyze_dynamics").get("source_dynamics_analysis"),
                "source dynamics analysis",
            )
            control_contract = _load_module(
                "scripts/control_keyframe_contract.py", "usfr_audit_control_keyframe_contract"
            )
            expected_cut_ids = control_contract.source_cut_ids(dynamics)
        except ReplicationError:
            raise
        except Exception as exc:
            raise _replication_error("CONTRACT_INVALID", "approved storyboard control receipt cannot be validated", category="artifact") from exc
        if (
            receipt.get("schema_version") != "usfr-control-keyframes-validation/v1"
            or receipt.get("status") != "passed"
            or receipt.get("source_cut_ids") != expected_cut_ids
            or str(receipt.get("source_video_sha256") or "").lower() != approved_board["source_video_sha256"]
            or str(receipt.get("source_keyframe_sheet_sha256") or "").lower()
            != approved_board["source_keyframe_sheet_sha256"]
            or str(receipt.get("replacement_control_sheet_sha256") or "").lower()
            != approved_board["replacement_control_keyframe_sheet_sha256"]
            or list(receipt.get("replacement_target_sha256s") or [])
            != list(approved_board["replacement_target_sha256s"])
        ):
            raise _replication_error("CONTRACT_INVALID", "approved storyboard control receipt lineage is inconsistent", category="artifact")

    def _source_reference(
        self,
        context: Any,
        *,
        segment: Mapping[str, Any],
        storyboard_url: str,
        target_changes: list[dict[str, str]],
        plan_sha256: str,
        segment_plan: Mapping[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        segment_id = str(segment.get("segment_id") or "").strip()
        try:
            start_ms, end_ms = int(segment["start_ms"]), int(segment["end_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _replication_error("SEGMENT_PLAN_INVALID", "source reference segment timing is invalid") from exc
        if not segment_id or not 2_000 <= end_ms - start_ms <= 15_000:
            raise _replication_error("SEGMENT_PLAN_INVALID", "source reference segment must be 2-15 seconds")
        source_sha256s = _slot_sha256s(context, "source_video")
        if len(source_sha256s) != 1:
            raise _replication_error("CONTRACT_INVALID", "source_video needs exactly one immutable digest")
        destination = Path(context.work_dir) / f"{segment_id}-source-reference.mp4"
        try:
            with context.materialize_slot("source_video") as source:
                if self.video_segmenter is not None:
                    produced = self.video_segmenter(
                        source_path=Path(source.path), start_ms=start_ms, end_ms=end_ms, destination=destination
                    )
                else:
                    module = _load_module(
                        "bundled-skills/seedance-storyboard-replication/scripts/source_video_reference.py",
                        "usfr_source_video_reference",
                    )
                    reference = module.materialize_source_video_reference(
                        source_video=Path(source.path),
                        segment_plan=segment_plan,
                        segment_id=segment_id,
                        output_dir=Path(context.work_dir) / "source_video_references",
                    )
                    if (
                        str(reference.source_video_sha256).lower() != source_sha256s[0]
                        or reference.segment_id != segment_id
                        or reference.start_ms != start_ms
                        or reference.end_ms != end_ms
                    ):
                        raise _replication_error("ARTIFACT_HASH_MISMATCH", "bounded source reference does not match the frozen source segment", category="artifact")
                    produced = reference.path
        except ReplicationError:
            raise
        except Exception as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", f"source reference extraction failed for {segment_id}", retryable=True, category="capability") from exc
        output = Path(produced)
        data = output.read_bytes() if output.is_file() else b""
        if len(data) < 12 or b"ftyp" not in data[:64]:
            raise _replication_error("PROVIDER_RESULT_INVALID", "bounded source reference is not MP4 bytes", category="artifact")
        slice_sha256 = hashlib.sha256(data).hexdigest()
        if slice_sha256 == source_sha256s[0]:
            raise _replication_error(
                "ARTIFACT_INVALID",
                "source video reference must be a distinct bounded slice, never the complete source upload",
                category="artifact",
            )
        published = context.publish_bytes(
            kind="source_video_reference",
            data=data,
            content_type="video/mp4",
            expected_sha256=slice_sha256,
            metadata={
                "source_video_sha256": source_sha256s[0],
                "segment_id": segment_id,
                "segment_plan_sha256": plan_sha256,
                "start_ms": start_ms,
                "end_ms": end_ms,
            },
        )
        source_reference_artifact_id = str(published.get("artifact_id") or "").strip() if isinstance(published, Mapping) else ""
        if not source_reference_artifact_id:
            raise _replication_error(
                "CONTRACT_INVALID",
                "published source video reference has no immutable artifact identity",
                category="artifact",
            )
        try:
            url = self.media_uploader.upload_media(output)
        except Exception as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", f"RunningHub source-reference upload failed for {segment_id}", retryable=True, category="provider") from exc
        if not isinstance(url, str) or not url.strip():
            raise _replication_error("CAPABILITY_UNAVAILABLE", "RunningHub source-reference upload returned no URL", retryable=True, category="provider")
        binding = {
            "schema_version": "usfr-video-reference/v1",
            "url": url.strip(),
            "source_video_sha256": source_sha256s[0],
            "source_slice_sha256": slice_sha256,
            "segment_id": segment_id,
            "segment_plan_sha256": plan_sha256,
            "source_video_reference_artifact_id": source_reference_artifact_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "storyboard_url": storyboard_url,
            "target_changes": target_changes,
        }
        return url.strip(), binding, published

    @staticmethod
    def _frozen_segment_plan(contract: Mapping[str, Any]) -> tuple[Mapping[str, Any], str, dict[str, Mapping[str, Any]]]:
        """Return the one canonical Stage-7 plan and reject edited copies."""

        plan = _mapping(contract.get("segment_plan"), "Seedance segment plan")
        plan_sha256 = _sha(plan)
        declared_sha256 = str(contract.get("segment_plan_sha256") or "").lower()
        if _SHA256.fullmatch(declared_sha256) is None or declared_sha256 != plan_sha256:
            raise _replication_error("SEGMENT_PLAN_INVALID", "Seedance input contract segment plan digest is missing or stale")
        raw_segments = plan.get("segments")
        if not isinstance(raw_segments, list) or not 1 <= len(raw_segments) <= 2:
            raise _replication_error("SEGMENT_PLAN_INVALID", "frozen segment plan must contain one or two segments")
        planned: dict[str, Mapping[str, Any]] = {}
        seen_cut_ids: set[str] = set()
        previous_end = -1
        for raw in raw_segments:
            segment = _mapping(raw, "frozen segment plan row")
            segment_id = str(segment.get("segment_id") or "").strip()
            cut_ids = segment.get("cut_ids")
            start_ms, end_ms, duration_ms = (
                segment.get("start_ms"), segment.get("end_ms"), segment.get("duration_ms")
            )
            if (
                isinstance(start_ms, bool)
                or isinstance(end_ms, bool)
                or isinstance(duration_ms, bool)
                or not isinstance(start_ms, int)
                or not isinstance(end_ms, int)
                or not isinstance(duration_ms, int)
            ):
                raise _replication_error("SEGMENT_PLAN_INVALID", "frozen segment plan timing is invalid")
            if (
                not segment_id
                or segment_id in planned
                or not isinstance(cut_ids, list)
                or not cut_ids
                or any(not isinstance(cut_id, str) or not cut_id.strip() for cut_id in cut_ids)
                or len(set(cut_ids)) != len(cut_ids)
                or start_ms < 0
                or end_ms - start_ms != duration_ms
                or not 4_000 <= duration_ms <= 15_000
                or start_ms < previous_end
                or seen_cut_ids.intersection(cut_ids)
            ):
                raise _replication_error("SEGMENT_PLAN_INVALID", "frozen segment plan is not unique, ordered, and duration-consistent")
            planned[segment_id] = segment
            seen_cut_ids.update(cut_ids)
            previous_end = end_ms
        return plan, plan_sha256, planned

    @staticmethod
    def _validate_published_segment_plan(
        context: Any, *, plan: Mapping[str, Any], plan_sha256: str
    ) -> None:
        """Ensure the compiled contract did not replace the Stage-7 artifact."""

        if not callable(getattr(getattr(context, "job_store", None), "get_current_revision", None)):
            return
        published = _read_json_artifact(context, kind="segment_plan", sha256=plan_sha256)
        if published != plan:
            raise _replication_error("SEGMENT_PLAN_INVALID", "compiled segment plan differs from the published Stage-7 plan", category="artifact")
        script_sha = str(getattr(context.snapshot, "approved_script_sha256", "") or "").lower()
        script = _read_json_artifact(context, kind="script_revision", sha256=script_sha)
        script_cuts = {
            str(cut.get("cut_id") or "")
            for cut in script.get("cuts") or []
            if isinstance(cut, Mapping) and str(cut.get("cut_id") or "")
        }
        regions = _mapping(
            _stage_output(context, "route_regions").get("timeline_regions"), "timeline regions"
        ).get("regions")
        generated_cut_ids = {
            str(cut_id)
            for region in regions or []
            if isinstance(region, Mapping) and region.get("media_origin") == "generated"
            for cut_id in region.get("cut_ids") or []
            if isinstance(cut_id, str) and cut_id
        }
        plan_cut_ids = {
            str(cut_id)
            for segment in plan.get("segments") or []
            if isinstance(segment, Mapping)
            for cut_id in segment.get("cut_ids") or []
            if isinstance(cut_id, str) and cut_id
        }
        if not plan_cut_ids or plan_cut_ids != generated_cut_ids or not plan_cut_ids.issubset(script_cuts):
            raise _replication_error("SEGMENT_PLAN_INVALID", "frozen segment plan Cut coverage differs from the approved script or generated timeline")

    @staticmethod
    def _final_reference_lineage(
        *,
        payload: Mapping[str, Any],
        segment_id: str,
        plan_sha256: str,
        approved_board: Mapping[str, Any],
        source_artifact: Mapping[str, Any],
        source_url: str,
        target_descriptors: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Build the private proof of the only legal final media ordering."""

        artifact_id = str(source_artifact.get("artifact_id") or "").strip()
        object_key = str(source_artifact.get("object_key") or "").strip()
        digest = str(source_artifact.get("sha256") or "").lower()
        metadata = source_artifact.get("metadata")
        if (
            source_artifact.get("kind") != "source_video_reference"
            or not artifact_id
            or not object_key
            or _SHA256.fullmatch(digest) is None
            or not isinstance(metadata, Mapping)
        ):
            raise _replication_error("ARTIFACT_INVALID", "source video reference is not a server-published immutable artifact", category="artifact")
        source_reference = {
            "artifact_id": artifact_id,
            "object_key": object_key,
            "kind": "source_video_reference",
            "sha256": digest,
            "source_video_sha256": str(metadata.get("source_video_sha256") or "").lower(),
            "segment_id": str(metadata.get("segment_id") or ""),
            "segment_plan_sha256": str(metadata.get("segment_plan_sha256") or "").lower(),
            "start_ms": metadata.get("start_ms"),
            "end_ms": metadata.get("end_ms"),
            "url": source_url,
        }
        lineage = {
            "schema_version": "seedance-final-reference-lineage/v1",
            "segment_id": segment_id,
            "segment_plan_sha256": plan_sha256,
            "ordered_image_urls": list(payload.get("imageUrls") or []),
            "ordered_video_urls": list(payload.get("videoUrls") or []),
            "approved_board": dict(approved_board),
            "source_reference": source_reference,
            "allowed_target_changes": [dict(item) for item in target_descriptors],
            "forbidden_artifact_kinds": [
                "source_keyframe_sheet",
                "replacement_control_keyframe_sheet",
                "replacement_control_keyframe_receipt",
            ],
        }
        try:
            validate_final_reference_lineage(payload, lineage)
        except RunningHubStandardPayloadError as exc:
            raise _replication_error("PROMPT_INTEGRITY_FAILED", "final reference lineage is invalid") from exc
        return lineage

    def _background_music_reference(
        self,
        context: Any,
        *,
        segment: Mapping[str, Any],
        plan_sha256: str,
        prompt: str,
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        extensions = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("extensions", {})
        music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
        if not isinstance(music, Mapping):
            return None
        if "@Audio1" not in prompt:
            raise _replication_error("PROMPT_INTEGRITY_FAILED", "uploaded music requires an exact @Audio1 reference in the compiled Seedance prompt")
        values, hashes, metadata = music.get("values"), music.get("sha256"), music.get("metadata")
        if (
            not isinstance(values, list) or len(values) != 1
            or not isinstance(hashes, list) or len(hashes) != 1 or _SHA256.fullmatch(str(hashes[0]).lower()) is None
            or not isinstance(metadata, list) or len(metadata) != 1 or not isinstance(metadata[0], Mapping)
        ):
            raise _replication_error("INPUT_SLOT_INVALID", "background_music immutable upload evidence is invalid", category="input")
        segment_id = str(segment.get("segment_id") or "").strip()
        try:
            start_ms, end_ms = int(segment["start_ms"]), int(segment["end_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _replication_error("SEGMENT_PLAN_INVALID", "uploaded-song segment timing is invalid") from exc
        if not segment_id or not 2_000 <= end_ms - start_ms <= 15_000:
            raise _replication_error("SEGMENT_PLAN_INVALID", "uploaded-song segment must be 2-15 seconds")
        source_music_windows = _segment_music_window_bindings(
            _uploaded_audio_source_music_windows(context),
            segment_start_ms=start_ms,
            segment_end_ms=end_ms,
        )
        if not source_music_windows:
            if "@Audio1" in prompt:
                raise _replication_error(
                    "PROMPT_INTEGRITY_FAILED",
                    "compiled Seedance prompt references uploaded audio outside an observed source music window",
                )
            return None
        destination = Path(context.work_dir) / f"{segment_id}-audio-reference.wav"
        try:
            with context.materialize_extension("background_music") as source:
                produced = self.audio_segmenter(
                    source_path=Path(source.path),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source_music_windows=source_music_windows,
                    destination=destination,
                )
        except ReplicationError:
            raise
        except Exception as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", f"uploaded-song slicing failed for {segment_id}", retryable=True, category="capability") from exc
        output = Path(produced)
        data = output.read_bytes() if output.is_file() else b""
        if not data:
            raise _replication_error("PROVIDER_RESULT_INVALID", "uploaded-song slicing produced no audio bytes", category="artifact")
        slice_sha256 = hashlib.sha256(data).hexdigest()
        published = context.publish_bytes(
            kind="background_music_reference",
            data=data,
            content_type="audio/wav",
            expected_sha256=slice_sha256,
            metadata={
                "segment_id": segment_id,
                "segment_plan_sha256": plan_sha256,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "source_audio_sha256": str(hashes[0]).lower(),
                "replacement_timing_policy": "source_music_cut_in_out_exact",
                "source_music_windows": source_music_windows,
            },
        )
        try:
            url = self.media_uploader.upload_media(output)
        except Exception as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", f"RunningHub uploaded-song reference upload failed for {segment_id}", retryable=True, category="provider") from exc
        if not isinstance(url, str) or not url.strip():
            raise _replication_error("CAPABILITY_UNAVAILABLE", "RunningHub uploaded-song reference upload returned no URL", retryable=True, category="provider")
        binding = {
            "schema_version": "usfr-background-music-reference/v1",
            "url": url.strip(),
            "source_audio_sha256": str(hashes[0]).lower(),
            "source_slice_sha256": slice_sha256,
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "segment_plan_sha256": plan_sha256,
            "replacement_timing_policy": "source_music_cut_in_out_exact",
            "source_music_windows": source_music_windows,
        }
        receipt = self._audio_reference_artifact_receipt(published, binding)
        return url.strip(), binding, published, receipt

    @staticmethod
    def _audio_reference_artifact_receipt(
        published: Mapping[str, Any], binding: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Project a server-published audio artifact into HMAC-bound evidence."""

        artifact_id = str(published.get("artifact_id") or "").strip()
        object_key = str(published.get("object_key") or "").strip()
        digest = str(published.get("sha256") or "").lower()
        metadata = published.get("metadata")
        if (
            published.get("kind") != "background_music_reference"
            or not artifact_id
            or not object_key
            or _SHA256.fullmatch(digest) is None
            or not isinstance(metadata, Mapping)
            or digest != binding.get("source_slice_sha256")
        ):
            raise _replication_error(
                "ARTIFACT_INVALID",
                "background-music reference must be a server-published immutable artifact",
                category="artifact",
            )
        fields = (
            "source_audio_sha256",
            "segment_id",
            "start_ms",
            "end_ms",
            "segment_plan_sha256",
            "replacement_timing_policy",
            "source_music_windows",
        )
        if any(metadata.get(field) != binding.get(field) for field in fields):
            raise _replication_error(
                "ARTIFACT_INVALID",
                "background-music artifact metadata does not match its immutable audio binding",
                category="artifact",
            )
        return {
            "schema_version": "usfr-background-music-artifact-receipt/v1",
            "artifact_id": artifact_id,
            "object_key": object_key,
            "kind": "background_music_reference",
            "sha256": digest,
            **{field: binding[field] for field in fields},
        }

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        contract = _read_json_artifact(context, kind="seedance_input_contract")
        rows = contract.get("segments")
        if not isinstance(rows, list) or not rows:
            raise _replication_error("PROMPT_INTEGRITY_FAILED", "Seedance input contract contains no segments")
        audited: list[dict[str, Any]] = []
        plan, frozen_plan_sha, planned = self._frozen_segment_plan(contract)
        self._validate_published_segment_plan(
            context, plan=plan, plan_sha256=frozen_plan_sha
        )
        if len(rows) != len(planned):
            raise _replication_error("SEGMENT_PLAN_INVALID", "compiled segments do not cover the frozen plan exactly")
        seen_compiled_segments: set[str] = set()
        for row in rows:
            item = _mapping(row, "Seedance segment")
            artifact = _mapping(item.get("compiled_prompt"), "compiled Seedance prompt")
            prompt = artifact.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "compiled Seedance prompt is missing")
            duration = int((_mapping(item, "Seedance segment").get("compiled_prompt", {}).get("source_contract", {}).get("segment", {}) or {}).get("duration_ms") or 0)
            if not 4_000 <= duration <= 15_000:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "compiled Seedance segment duration is invalid")
            segment_id = str(item.get("segment_id") or "").strip()
            if not segment_id or segment_id in seen_compiled_segments:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "compiled Seedance segment is missing its ID")
            seen_compiled_segments.add(segment_id)
            # @Image1 is the exact Image2 PNG shown in the sole storyboard
            # confirmation. It is uploaded only from immutable current-job
            # bytes; neither client URLs nor a text-only board can reach paid
            # Seedance submission.
            storyboard_url = self._upload_storyboard(context, segment_id=segment_id)
            target_urls, target_changes = self._target_reference_urls(context, prompt=prompt)
            if not target_changes:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "source video reference requires an approved target change")
            segment_plan = planned.get(segment_id)
            if not isinstance(segment_plan, Mapping):
                raise _replication_error("SEGMENT_PLAN_INVALID", "compiled Seedance segment has no frozen plan row")
            plan_sha = str(item.get("segment_plan_sha256") or "").lower()
            if plan_sha != frozen_plan_sha:
                raise _replication_error("SEGMENT_PLAN_INVALID", "compiled Seedance segment does not use the frozen plan digest")
            try:
                planned_duration = int(segment_plan["duration_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("SEGMENT_PLAN_INVALID", "frozen segment plan duration is invalid") from exc
            if duration != planned_duration:
                raise _replication_error("SEGMENT_PLAN_INVALID", "compiled Seedance segment duration differs from the frozen plan")
            video_url, video_binding, published_video_reference = self._source_reference(
                context,
                segment=segment_plan,
                storyboard_url=storyboard_url,
                target_changes=target_changes,
                plan_sha256=plan_sha,
                segment_plan=plan,
            )
            # A classified song is intentionally not a Seedance audio input:
            # its original full audio and exact time window go to the
            # dedicated song-lip-sync workflow after this video is generated.
            uploaded_kind = None
            if SeedancePromptStage._uploaded_music_present(context):
                try:
                    uploaded_kind = str(_uploaded_audio_classification(context).get("kind") or "")
                except Exception:
                    uploaded_kind = None
            if uploaded_kind == "song" and "@Audio1" in prompt:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "song Seedance prompt must not reference @Audio1")
            audio_reference = None if uploaded_kind == "song" else self._background_music_reference(
                context, segment=segment_plan, plan_sha256=plan_sha, prompt=prompt.strip()
            )
            audio_urls = [audio_reference[0]] if audio_reference is not None else []
            payload_template = {
                "prompt": prompt.strip(), "resolution": "720p", "duration": str(max(4, min(15, round(duration / 1000)))),
                "imageUrls": [storyboard_url, *target_urls], "videoUrls": [video_url], "audioUrls": audio_urls, "generateAudio": True,
                "ratio": "9:16", "realPersonMode": True, "conversionSlots": ["all"],
                "returnLastFrame": False, "seed": -1,
            }
            storyboard_descriptor = self._approved_board_descriptor(
                context,
                segment_id=segment_id,
                segment=segment_plan,
                descriptor=self._storyboard_descriptor(context, segment_id=segment_id),
                storyboard_url=storyboard_url,
            )
            self._validate_internal_board_lineage(context, approved_board=storyboard_descriptor)
            target_descriptors = self._final_target_descriptors(
                target_urls=target_urls, target_changes=target_changes
            )
            final_reference_lineage = self._final_reference_lineage(
                payload=payload_template,
                segment_id=segment_id,
                plan_sha256=plan_sha,
                approved_board=storyboard_descriptor,
                source_artifact=published_video_reference,
                source_url=video_url,
                target_descriptors=target_descriptors,
            )
            try:
                validate_runninghub_standard_payload_contract(payload_template)
                validate_video_reference_binding(payload_template, video_binding)
                validate_final_reference_lineage(payload_template, final_reference_lineage)
                validate_audio_reference_binding(
                    payload_template, audio_reference[1] if audio_reference is not None else None
                )
                if audio_reference is not None and not isinstance(self.audit_secret, str):
                    raise RunningHubStandardPayloadError("audio reference requires a service-side provider audit proof")
                audit_proof = (
                    build_provider_audit_proof(
                        payload_template,
                        video_binding,
                        audio_reference[1] if audio_reference is not None else None,
                        secret=self.audit_secret,
                        audio_reference_artifact_receipt=audio_reference[3] if audio_reference is not None else None,
                    )
                    if audio_reference is not None
                    else None
                )
            except RunningHubStandardPayloadError as exc:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "audited RunningHub payload is invalid") from exc
            audited.append({
                "segment_id": segment_id,
                "segment_plan_sha256": plan_sha,
                "compiled_prompt_sha256": str(artifact.get("compiler", {}).get("output_sha256") or ""),
                "payload_template": payload_template,
                "video_reference_binding": video_binding,
                "source_video_reference_artifact": published_video_reference,
                "final_reference_lineage": final_reference_lineage,
                "audio_reference_binding": audio_reference[1] if audio_reference is not None else None,
                "background_music_reference_artifact": audio_reference[2] if audio_reference is not None else None,
                "audio_reference_artifact_receipt": audio_reference[3] if audio_reference is not None else None,
                "provider_audit_proof": audit_proof,
            })
        envelope = {"schema_version": "seedance-request-audit/v1", "segments": audited}
        published = _publish_json(context, kind="seedance_request_audit", value=envelope)
        return {"status": "ready", "seedance_request_audit": envelope, "published_artifacts": [published]}


class _BoundProviderPayload(dict[str, Any]):
    """Exact Standard payload with immutable sidecar evidence for the adapter."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        video_reference_binding: Mapping[str, Any] | None,
        final_reference_lineage: Mapping[str, Any] | None = None,
        audio_reference_binding: Mapping[str, Any] | None = None,
        audio_reference_artifact_receipt: Mapping[str, Any] | None = None,
        provider_audit_proof: Mapping[str, Any] | None = None,
        audio_provider_authorization: Mapping[str, Any] | None = None,
        server_audio_authorization_verifier: Any | None = None,
    ) -> None:
        super().__init__(dict(payload))
        self.video_reference_binding = dict(video_reference_binding) if isinstance(video_reference_binding, Mapping) else None
        self.final_reference_lineage = dict(final_reference_lineage) if isinstance(final_reference_lineage, Mapping) else None
        self.audio_reference_binding = dict(audio_reference_binding) if isinstance(audio_reference_binding, Mapping) else None
        self.audio_reference_artifact_receipt = dict(audio_reference_artifact_receipt) if isinstance(audio_reference_artifact_receipt, Mapping) else None
        self.provider_audit_proof = dict(provider_audit_proof) if isinstance(provider_audit_proof, Mapping) else None
        self.audio_provider_authorization = dict(audio_provider_authorization) if isinstance(audio_provider_authorization, Mapping) else None
        self.server_audio_authorization_verifier = server_audio_authorization_verifier


class SubmitProviderVideoStage:
    """Submit the exact audited payload once per frozen segment, never retry."""

    def __init__(self, *, provider: Any, audit_secret: str | None = None) -> None:
        self.provider = provider
        self.audit_secret = audit_secret

    @staticmethod
    def _provider_request(
        payload: Mapping[str, Any],
        video_reference_binding: Mapping[str, Any] | None,
        *,
        final_reference_lineage: Mapping[str, Any] | None = None,
        audio_reference_binding: Mapping[str, Any] | None,
        audio_reference_artifact_receipt: Mapping[str, Any] | None = None,
        provider_audit_proof: Mapping[str, Any] | None = None,
    ) -> _BoundProviderPayload:
        try:
            validate_runninghub_standard_payload_contract(payload)
            validate_video_reference_binding(payload, video_reference_binding)
            if payload.get("videoUrls"):
                validate_final_reference_lineage(payload, final_reference_lineage)
            elif final_reference_lineage is not None:
                raise RunningHubStandardPayloadError("final reference lineage is valid only with one source video reference")
            validate_audio_reference_binding(payload, audio_reference_binding)
            if audio_reference_binding is not None:
                validate_audio_reference_artifact_receipt(
                    audio_reference_binding, audio_reference_artifact_receipt
                )
        except RunningHubStandardPayloadError as exc:
            raise _replication_error(
                "PROMPT_INTEGRITY_FAILED", f"audited RunningHub provider request is invalid: {exc}"
            ) from exc
        return _BoundProviderPayload(
            payload,
            video_reference_binding=video_reference_binding,
            final_reference_lineage=final_reference_lineage,
            audio_reference_binding=audio_reference_binding,
            audio_reference_artifact_receipt=audio_reference_artifact_receipt,
            provider_audit_proof=provider_audit_proof,
        )

    @staticmethod
    def _ttl(context: Any) -> int:
        snapshot = context.job_store.get_job(context.job_id)
        if snapshot is None:
            raise _replication_error("JOB_GONE", "job expired before provider submission", category="worker")
        return max(1, (snapshot.expires_at_ms - time.time_ns() // 1_000_000) // 1000)

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        audit = _read_json_artifact(context, kind="seedance_request_audit")
        audit_descriptors = [
            item for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping) and item.get("kind") == "seedance_request_audit"
        ]
        if len(audit_descriptors) != 1:
            raise _replication_error("ARTIFACT_NOT_FOUND", "provider submission requires exactly one immutable seedance request audit artifact", category="artifact")
        audit_descriptor = audit_descriptors[0]
        rows = audit.get("segments")
        if not isinstance(rows, list) or not rows:
            raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit has no segments")
        submitted: list[dict[str, Any]] = []
        for raw in rows:
            row = _mapping(raw, "provider audit segment")
            segment_id = str(row.get("segment_id") or "")
            plan_sha = str(row.get("segment_plan_sha256") or "").lower()
            payload = _mapping(row.get("payload_template"), "provider payload template")
            if not segment_id or _SHA256.fullmatch(plan_sha) is None:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit segment binding is invalid")
            # A real storyboard URL is mandatory before a paid request.  The
            # deployment may only add it through a dedicated uploader adapter;
            # accepting a caller URL here would violate the object boundary.
            image_urls = payload.get("imageUrls")
            if not isinstance(image_urls, list) or not image_urls:
                raise _replication_error("CAPABILITY_UNAVAILABLE", "storyboard media upload adapter is required before Seedance submission", retryable=True, category="capability")
            binding = row.get("video_reference_binding")
            if binding is not None and not isinstance(binding, Mapping):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit video reference binding is invalid")
            final_reference_lineage = row.get("final_reference_lineage")
            if final_reference_lineage is not None and not isinstance(final_reference_lineage, Mapping):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit final reference lineage is invalid")
            audio_binding = row.get("audio_reference_binding")
            if audio_binding is not None and not isinstance(audio_binding, Mapping):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit audio reference binding is invalid")
            audio_artifact_receipt = row.get("audio_reference_artifact_receipt")
            if audio_artifact_receipt is not None and not isinstance(audio_artifact_receipt, Mapping):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit audio artifact receipt is invalid")
            audit_proof = row.get("provider_audit_proof")
            if audit_proof is not None and not isinstance(audit_proof, Mapping):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit proof is invalid")
            provider_request = self._provider_request(
                payload,
                binding,
                final_reference_lineage=final_reference_lineage,
                audio_reference_binding=audio_binding,
                audio_reference_artifact_receipt=audio_artifact_receipt,
                provider_audit_proof=audit_proof,
            )
            request_sha = _sha(payload)
            active = [
                item for item in context.job_store.list_provider_attempts(context.job_id)
                if item.operation == "CreateVideo" and item.segment_id == segment_id and item.segment_plan_sha256 == plan_sha
                and item.status in {"SUBMITTING", "RUNNING", "AMBIGUOUS"}
            ]
            if active:
                attempt = active[0]
                if attempt.request_sha256 != request_sha:
                    raise _replication_error("IDEMPOTENCY_CONFLICT", "active provider attempt has a different audited request")
                submitted.append({"segment_id": segment_id, "attempt_id": attempt.attempt_id, "task_id": attempt.provider_task_id, "status": attempt.status})
                continue
            snapshot = context.job_store.get_job(context.job_id)
            if snapshot is None:
                raise _replication_error("JOB_GONE", "job expired before provider submission", category="worker")
            attempt = context.job_store.begin_provider_attempt(
                job_id=context.job_id, expected_version=snapshot.version, operation="CreateVideo",
                request_sha256=request_sha, segment_id=segment_id, segment_plan_sha256=plan_sha,
            )
            try:
                if not isinstance(self.audit_secret, str) or not self.audit_secret:
                    raise _replication_error("CAPABILITY_UNAVAILABLE", "provider submission requires the service-side authorization secret", category="capability")
                try:
                    authorization, verifier = mint_audio_provider_authorization(
                        job_store=context.job_store,
                        job_id=context.job_id,
                        audit_artifact=audit_descriptor,
                        payload=payload,
                        video_reference_binding=binding,
                        final_reference_lineage=final_reference_lineage,
                        audio_reference_binding=audio_binding,
                        audio_reference_artifact_receipt=audio_artifact_receipt,
                        attempt=attempt,
                        secret=self.audit_secret,
                    )
                except AudioProviderAuthorizationError as exc:
                    raise _replication_error("PROMPT_INTEGRITY_FAILED", f"server provider authorization cannot be minted: {exc}") from exc
                provider_request.audio_provider_authorization = authorization
                provider_request.server_audio_authorization_verifier = verifier
                response = self.provider.create_video(provider_request)
            except RunningHubCreateAmbiguousError as exc:
                current = context.job_store.get_job(context.job_id)
                if current is not None:
                    context.job_store.update_provider_attempt(
                        job_id=context.job_id, expected_version=current.version,
                        attempt=replace(attempt, status="AMBIGUOUS"), ttl_seconds=self._ttl(context),
                    )
                raise _replication_error("PROVIDER_AMBIGUOUS", "RunningHub create outcome is ambiguous; reconcile the recorded intent instead of retrying", retryable=False, category="provider") from exc
            task_id = str(response.get("task_id") or "")
            receipt = _mapping(response.get("receipt"), "provider create receipt")
            current = context.job_store.get_job(context.job_id)
            if current is None:
                raise _replication_error("JOB_GONE", "job expired during provider submission", category="worker")
            running = replace(attempt, status="RUNNING", provider_task_id=task_id, response_sha256=str(receipt.get("response_sha256") or ""))
            context.job_store.update_provider_attempt(job_id=context.job_id, expected_version=current.version, attempt=running, ttl_seconds=self._ttl(context))
            submitted.append({"segment_id": segment_id, "attempt_id": attempt.attempt_id, "task_id": task_id, "status": "RUNNING"})
        return {"status": "ready", "provider_attempts": submitted}


class WaitProviderVideoStage:
    """Poll known RunningHub tasks and publish verified MP4 bytes immediately."""

    def __init__(
        self,
        *,
        provider: Any,
        song_lip_sync_client: Any | None = None,
        poll_seconds: float = 5.0,
        timeout_seconds: float = 1800.0,
    ) -> None:
        self.provider = provider
        self.song_lip_sync_client = song_lip_sync_client
        self.poll_seconds = float(poll_seconds)
        self.timeout_seconds = float(timeout_seconds)

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        started = time.monotonic()
        results: list[dict[str, Any]] = []
        downloaded_results: list[dict[str, Any]] = []
        for attempt in context.job_store.list_provider_attempts(context.job_id):
            if attempt.operation != "CreateVideo" or attempt.status == "SUCCEEDED":
                continue
            if attempt.status == "AMBIGUOUS" or not attempt.provider_task_id:
                raise _replication_error("PROVIDER_AMBIGUOUS", "provider attempt must be reconciled before waiting", category="provider")
            while True:
                try:
                    state = self.provider.lookup({"taskId": attempt.provider_task_id})
                except RunningHubTaskFailed as exc:
                    current = context.job_store.get_job(context.job_id)
                    if current is not None:
                        context.job_store.update_provider_attempt(job_id=context.job_id, expected_version=current.version, attempt=replace(attempt, status="FAILED"), ttl_seconds=max(1, (current.expires_at_ms - time.time_ns() // 1_000_000) // 1000))
                    raise _replication_error("PROVIDER_FAILED", "RunningHub video task failed", category="provider") from exc
                if state.get("status") == "SUCCESS":
                    destination = Path(context.work_dir) / f"{attempt.segment_id or attempt.attempt_id}.mp4"
                    downloaded = self.provider.download(attempt.provider_task_id, destination)
                    data = destination.read_bytes()
                    if not data or not data.startswith(b"\x00\x00\x00") and b"ftyp" not in data[:64]:
                        raise _replication_error("PROVIDER_RESULT_INVALID", "RunningHub result is not an MP4 byte stream", category="provider")
                    downloaded_results.append({
                        "attempt": attempt,
                        "destination": destination,
                        "data": data,
                        "download": dict(downloaded),
                    })
                    break
                if time.monotonic() - started >= self.timeout_seconds:
                    raise _replication_error("PROVIDER_TIMEOUT", "RunningHub video task did not finish before the configured provider wait limit", retryable=True, category="provider")
                time.sleep(self.poll_seconds)
        if not downloaded_results:
            raise _replication_error("PROVIDER_RESULT_INVALID", "no successful provider video was available for assembly", category="provider")

        extensions = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("extensions", {})
        uploaded_audio = (
            _uploaded_audio_classification(context)
            if isinstance(extensions, Mapping) and isinstance(extensions.get("background_music"), Mapping)
            else None
        )
        if uploaded_audio and uploaded_audio.get("kind") == "song":
            if not callable(getattr(self.song_lip_sync_client, "run_song_lip_sync_segments", None)):
                raise _replication_error(
                    "CAPABILITY_UNAVAILABLE",
                    "song lip-sync workflow client is unavailable",
                    retryable=True,
                    category="capability",
                )
            contract = _read_json_artifact(context, kind="seedance_input_contract")
            contract_rows = contract.get("segments") if isinstance(contract, Mapping) else None
            if not isinstance(contract_rows, list):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "song lip-sync contracts are unavailable")
            contracts = {
                str(row.get("segment_id") or ""): row.get("song_lip_sync_contract")
                for row in contract_rows if isinstance(row, Mapping)
            }
            segments: list[dict[str, Any]] = []
            for item in downloaded_results:
                attempt = item["attempt"]
                segment_id = str(attempt.segment_id or "")
                lip_contract = contracts.get(segment_id)
                if not isinstance(lip_contract, Mapping) or not lip_contract.get("song_start") or not lip_contract.get("song_end"):
                    raise _replication_error(
                        "PERFORMANCE_LINE_CONTRACT_REQUIRED",
                        f"{segment_id} is missing its uploaded-song lip-sync time window",
                    )
                segments.append({
                    "segment_id": segment_id,
                    "segment_type": "generated_person",
                    "video_path": item["destination"],
                    "song_start": lip_contract["song_start"],
                    "song_end": lip_contract["song_end"],
                })
            try:
                with context.materialize_extension("background_music") as materialized:
                    lip_result = self.song_lip_sync_client.run_song_lip_sync_segments(
                        uploaded_audio_kind="song",
                        audio_path=Path(materialized.path),
                        segments=segments,
                    )
            except Exception as exc:
                raise _replication_error(
                    "PROVIDER_FAILED",
                    "RunningHub song lip-sync workflow failed",
                    retryable=True,
                    category="provider",
                ) from exc
            lip_rows = lip_result.get("segments") if isinstance(lip_result, Mapping) else None
            if not isinstance(lip_rows, list):
                raise _replication_error("PROVIDER_RESULT_INVALID", "song lip-sync workflow returned no segments", category="provider")
            lip_by_segment = {
                str(row.get("segment_id") or ""): row
                for row in lip_rows if isinstance(row, Mapping)
            }
        else:
            lip_by_segment = {}

        for item in downloaded_results:
            attempt = item["attempt"]
            segment_id = str(attempt.segment_id or "")
            lip_row = lip_by_segment.get(segment_id)
            data = lip_row.get("video_bytes") if isinstance(lip_row, Mapping) else item["data"]
            if not isinstance(data, bytes) or not data or b"ftyp" not in data[:64]:
                raise _replication_error("PROVIDER_RESULT_INVALID", "final provider result is not an MP4 byte stream", category="provider")
            metadata = {
                "segment_id": segment_id,
                "segment_plan_sha256": str(attempt.segment_plan_sha256 or "").lower(),
                "provider_task_id": str(attempt.provider_task_id or ""),
            }
            if isinstance(lip_row, Mapping):
                metadata.update({
                    "song_lip_sync_task_id": str(lip_row.get("task_id") or ""),
                    "song_lip_sync_receipt": dict(lip_row.get("receipt") or {}),
                })
            published = context.publish_bytes(
                kind="provider_video",
                data=data,
                content_type="video/mp4",
                expected_sha256=hashlib.sha256(data).hexdigest(),
                metadata=metadata,
            )
            current = context.job_store.get_job(context.job_id)
            if current is None:
                raise _replication_error("JOB_GONE", "job expired during provider download", category="worker")
            context.job_store.update_provider_attempt(job_id=context.job_id, expected_version=current.version, attempt=replace(attempt, status="SUCCEEDED"), ttl_seconds=max(1, (current.expires_at_ms - time.time_ns() // 1_000_000) // 1000))
            results.append({"segment_id": attempt.segment_id, "artifact": published, "download": item["download"]})
        return {"status": "ready", "provider_videos": results}


__all__ = [
    "BindInputsStage", "ProbeSourceStage", "RouteRegionsStage", "StoryboardStage", "SegmentPlanStage",
    "SeedancePromptStage", "SeedanceAuditStage", "SubmitProviderVideoStage", "WaitProviderVideoStage",
]
