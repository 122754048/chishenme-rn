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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .audio_lane_router import (
    ROUTE_VOICEOVER_TTS,
    route_audio_line,
)
from .singing_audio_router import subtract_protected_windows
from .approved_edit_contract import canonicalize_approved_edit_script
from .errors import ReplicationError
from .frame_quality import sharpness_ratio as _sharpness_ratio
from .seedance_request_audit_contract import (
    SeedanceRequestAuditValidationError,
    validate_v2_seedance_request_audit,
)
from .split_edit_runtime import (
    build_split_provider_retry_audit,
    canonical_sha,
    is_confirmed_provider_retry_row,
)
from .ffmpeg_encoding import video_encoder_args
from .image_media import UnsupportedImageFormat, detect_image_content_type
from .audio_provider_authorization import mint_audio_provider_authorization
from .job_models import ProviderAttempt
from .media_probe import probe_source
from .marketing_analysis_contract import MarketingAnalysisContractError, normalize_per_asset_analysis_row
from .production_ports import (
    EvidenceBoundGptPlanner,
    ProductionPortsError,
    RunningHubCreateAmbiguousError,
    RunningHubTaskFailed,
    _StoryboardRevisionStage,
)
from .recovery_workflow import plan_confirmed_edit_retry, provider_failure_evidence_sha256
from .review_models import RevisionManifest, StoryboardCutRef
from .public_content_policy import assert_public_content_safe
from .video_edit_qc_runtime import (
    QcRetryEvidenceError,
    QcRetryDecision,
    build_qc_retry_audit,
    current_qc_retry_decision_for_submit,
    is_qc_retry_row,
    read_immutable_artifact,
)
from .voiceover_tts_fallback import (
    VoiceoverTtsFallbackError,
    build_voiceover_tts_fallback_receipt,
)
from .runninghub_standard_contract import (
    RunningHubStandardPayloadError,
    build_provider_audit_proof,
    image_reference_binding_sha256,
    validate_audio_reference_artifact_receipt,
    validate_audio_reference_binding,
    validate_final_reference_lineage,
    validate_image_reference_binding,
    validate_public_https_url,
    validate_runninghub_standard_payload_contract,
    validate_video_reference_binding,
    validate_v2_image_reference_binding,
    validate_v2_video_reference_binding,
)
from .h3_edit_contract import H3EditContractError, build_h3_request, compile_h3_prompt
from .ui_interaction_contract import UiInteractionContractError, build_source_ui_interaction_contract
from .visible_text_contract import (
    VisibleTextContractError,
    canonicalize_visible_text_locks,
    split_visible_text_locks_by_render_route,
    visible_text_locks_sha256,
)


def _run_ordered_parallel(
    items: Sequence[Any],
    operation: Any,
    *,
    max_workers: int = 2,
) -> list[Any]:
    values = list(items)
    if len(values) <= 1 or max_workers <= 1:
        return [operation(value) for value in values]
    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(values)),
        thread_name_prefix="usfr-provider-io",
    ) as executor:
        return list(executor.map(operation, values))


def _provider_poll_delay(poll_index: int) -> float:
    schedule = (3.0, 5.0, 8.0, 12.0, 15.0)
    return schedule[min(max(int(poll_index), 0), len(schedule) - 1)]


def _asset_board_template_version(asset_type: object) -> str:
    normalized = str(asset_type or "").casefold()
    return "model-identity-v3" if normalized == "model" else f"{normalized}-v2"


def _persist_provider_attempt(context: Any, attempt: ProviderAttempt) -> None:
    snapshot = context.job_store.get_job(context.job_id)
    if snapshot is None:
        raise _replication_error("JOB_GONE", "job expired during provider attempt reconciliation", category="worker")
    context.job_store.update_provider_attempt(
        job_id=context.job_id,
        expected_version=snapshot.version,
        attempt=attempt,
        ttl_seconds=max(1, (snapshot.expires_at_ms - time.time_ns() // 1_000_000) // 1000),
    )


def _validate_confirmed_provider_retry(
    *,
    retry: Mapping[str, Any] | None,
    failed_attempts: Sequence[ProviderAttempt],
    target_request_sha256: str,
) -> tuple[Mapping[str, Any], ProviderAttempt]:
    required = {
        "parent_attempt_id",
        "parent_request_sha256",
        "failure_type",
        "confirmed",
        "adjustment",
        "evidence_sha256",
        "retry_index",
    }
    allowed = required | {"request_revision", "review_required"}
    if not isinstance(retry, Mapping) or not required.issubset(retry) or not set(retry).issubset(allowed):
        raise _replication_error(
            "PROVIDER_RETRY_INVALID",
            "confirmed provider retry audit contract is missing or non-canonical",
            category="provider",
        )
    parent_id = str(retry.get("parent_attempt_id") or "")
    parent_sha = str(retry.get("parent_request_sha256") or "").lower()
    failure_type = str(retry.get("failure_type") or "").strip().casefold()
    evidence_sha = str(retry.get("evidence_sha256") or "").lower()
    if (
        retry.get("confirmed") is not True
        or retry.get("retry_index") != 2
        or ("request_revision" in retry and retry.get("request_revision") != 2)
        or ("review_required" in retry and retry.get("review_required") is not True)
        or not parent_id
        or _SHA256.fullmatch(parent_sha) is None
        or not failure_type
        or _SHA256.fullmatch(evidence_sha) is None
    ):
        raise _replication_error(
            "PROVIDER_RETRY_INVALID",
            "confirmed provider retry audit fields are invalid",
            category="provider",
        )
    matching = [item for item in failed_attempts if item.attempt_id == parent_id]
    if len(matching) != 1 or matching[0].request_sha256 != parent_sha:
        raise _replication_error(
            "PROVIDER_RETRY_INVALID",
            "confirmed provider retry does not bind the immediately prior failed attempt",
            category="provider",
        )
    parent = matching[0]
    if parent.status != "FAILED" or parent.failure_kind != "provider":
        raise _replication_error(
            "PROVIDER_RETRY_INVALID",
            "confirmed provider retry requires an immutable provider failure",
            category="provider",
        )
    if evidence_sha != provider_failure_evidence_sha256(parent):
        raise _replication_error(
            "PROVIDER_RETRY_INVALID",
            "provider retry evidence does not match the immutable failed attempt",
            category="provider",
        )
    if parent.target_request_sha256 is None or parent.target_request_sha256 == target_request_sha256:
        raise _replication_error(
            "PROVIDER_RETRY_INVALID",
            "confirmed provider retry does not change the audited target request",
            category="provider",
        )
    planned = plan_confirmed_edit_retry(
        failure={"status": "FAILED", "confirmed": True, "failure_type": failure_type},
        request={"attempt": 1},
    )
    expected_adjustment = (
        planned.get("request", {}).get("adjustment")
        if planned.get("action") == "retry_once"
        else None
    )
    if retry.get("adjustment") != expected_adjustment:
        raise _replication_error(
            "PROVIDER_RETRY_INVALID",
            "provider retry adjustment does not match the recovery workflow mapping",
            category="provider",
        )
    return retry, parent


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/avif"})
_PERSON_PRESENCE = frozenset({"identifiable", "partial_or_hands"})
_MAX_CUTS_PER_PAGE = 6
_MAX_BOARD_PAGES = 2
_SLOT_ORDER = (
    "source_video",
    "new_product_image",
    "new_model_image",
    "ui_screenshot",
    "app_store_url",
    "ui_operation_video",
    "tail_video",
)


def _image_content_type(data: bytes, path: Path | None = None) -> str:
    del path
    try:
        return detect_image_content_type(data)
    except UnsupportedImageFormat as exc:
        raise _replication_error(
            "TARGET_EVIDENCE_IMAGE_INVALID",
            "target screenshot has an unsupported image format",
            category="artifact",
        ) from exc


def _sheet_aspect_ratio(sheet_path: Path) -> str:
    """Map an assembled contact/control sheet to the nearest provider ratio."""

    try:
        from PIL import Image

        with Image.open(sheet_path) as image:
            ratio = image.width / max(1, image.height)
    except Exception as exc:
        raise _replication_error(
            "ARTIFACT_INVALID",
            "contact sheet geometry could not be inspected",
            category="artifact",
        ) from exc
    candidates = {"16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "3:4": 3 / 4, "9:16": 9 / 16}
    return min(candidates, key=lambda key: abs(candidates[key] - ratio))


def _person_region_box(frame_paths: Sequence[Path]) -> tuple[int, int] | None:
    """Return the changing side of a source-frame set, if a static panel is clear.

    A persistent promo/UI panel is visually near-static across source Cuts,
    while the live-action region changes.  This is deliberately a small,
    deterministic pre-Image2 check: uncertainty keeps the complete frame.
    """

    if len(frame_paths) < 3:
        return None
    try:
        from PIL import Image
        import statistics

        columns_per_frame: list[list[float]] = []
        width: int | None = None
        height = 160
        for path in frame_paths:
            with Image.open(path) as image:
                if width is None:
                    width = image.width
                elif image.width != width:
                    return None
                small = image.convert("L").resize((image.width, height))
                pixels = small.load()
                columns_per_frame.append(
                    [
                        sum(pixels[x, y] for y in range(height)) / height
                        for x in range(image.width)
                    ]
                )
        if not width:
            return None
        variance = [
            statistics.pvariance([frame[x] for frame in columns_per_frame])
            for x in range(width)
        ]
    except Exception:
        return None
    peak = max(variance) if variance else 0.0
    if peak <= 0.0:
        return None
    dynamic = [x for x, value in enumerate(variance) if value / peak > 0.05]
    if not dynamic:
        return None
    left, right = min(dynamic), max(dynamic) + 1
    # Do not crop a source frame unless the static portion is decisive.
    if (right - left) / width > 0.85:
        return None
    return left, right


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


def _current_materialized_artifact_sha(context: Any, *, kind: str) -> str:
    descriptors = [
        item
        for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping) and item.get("kind") == kind
    ]
    if len(descriptors) != 1:
        raise _replication_error(
            "ARTIFACT_NOT_FOUND",
            f"exactly one current {kind} artifact is required",
            category="artifact",
        )
    descriptor = descriptors[0]
    artifact_id = str(descriptor.get("artifact_id") or "")
    digest = str(descriptor.get("sha256") or "").lower()
    if not artifact_id or _SHA256.fullmatch(digest) is None:
        raise _replication_error(
            "CONTRACT_INVALID",
            f"current {kind} artifact descriptor is invalid",
            category="artifact",
        )
    try:
        with context.materialize_artifact(kind, artifact_id=artifact_id, sha256=digest) as media:
            payload = Path(media.path).read_bytes()
    except ReplicationError:
        raise
    except Exception as exc:
        raise _replication_error(
            "ARTIFACT_NOT_FOUND",
            f"current {kind} artifact cannot be materialized",
            category="artifact",
        ) from exc
    if hashlib.sha256(payload).hexdigest() != digest:
        raise _replication_error(
            "ARTIFACT_HASH_MISMATCH",
            f"current {kind} artifact bytes differ from descriptor SHA",
            category="artifact",
        )
    return digest


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
    v2 = isinstance(extensions, Mapping) and extensions.get("edit_contract") == "video-edit-v2"
    try:
        from .uploaded_audio_contract import UploadedAudioContractError, validate_uploaded_audio_contract

        value = _read_json_artifact(context, kind="uploaded_audio_classification")
        return validate_uploaded_audio_contract(value, audio_sha256=str(hashes[0]).lower(), v2=v2)
    except ReplicationError:
        raise
    except UploadedAudioContractError as exc:
        raise _replication_error(
            "UPLOADED_AUDIO_CLASSIFICATION_REQUIRED",
            "uploaded audio must have a confirmed song or non-song classification before script approval",
        ) from exc


def _v2_audio_route(context: Any) -> tuple[str | None, dict[str, Any] | None]:
    snapshot = getattr(context, "snapshot", None)
    manifest = getattr(snapshot, "slots_manifest", {})
    extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
    music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
    if not isinstance(music, Mapping):
        return None, None
    classification = _uploaded_audio_classification(context)
    kind = str(classification.get("kind") or "").strip().casefold()
    if kind not in {"song", "background_music", "voiceover"}:
        raise _replication_error("UPLOADED_AUDIO_CLASSIFICATION_REQUIRED", "v2 uploaded audio kind is ambiguous", category="audio")
    revision = getattr(snapshot, "current_script_revision", None)
    getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
    script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
    sidecar = getter(context.job_id, revision) if callable(getter) else None
    audio_plan = sidecar.get("audio_plan") if isinstance(sidecar, Mapping) else None
    declared_sha = str(sidecar.get("audio_plan_sha256") or "").lower() if isinstance(sidecar, Mapping) else ""
    if (
        not isinstance(sidecar, Mapping)
        or sidecar.get("contract") != "approved-script-lines/v2"
        or sidecar.get("revision") != revision
        or str(sidecar.get("script_sha256") or "").lower() != script_sha
        or not isinstance(audio_plan, Mapping)
        or declared_sha != _sha(audio_plan)
    ):
        raise _replication_error("APPROVAL_STALE", "approved v2 audio plan is missing or stale", category="contract")
    if isinstance(manifest.get("audio_plan"), Mapping) and dict(manifest["audio_plan"]) != dict(audio_plan):
        raise _replication_error("APPROVAL_STALE", "v2 manifest audio plan differs from approved sidecar", category="contract")
    strategy = str(audio_plan.get("background_music_strategy") or "").strip().casefold()
    route = str(audio_plan.get("mv_lip_sync_route") or "").strip().casefold()
    voiceover_route = str(audio_plan.get("voiceover_route") or "").strip().casefold()
    valid_route = (
        (kind == "song" and strategy == "replace_uploaded_song" and route == "song_lipsync")
        or (
            kind == "background_music"
            and strategy == "replace_uploaded_background_music"
            and route
            and route != "song_lipsync"
        )
        or (
            kind == "voiceover"
            and strategy == "replace_uploaded_voiceover"
            and voiceover_route == "seedance_audio_reference"
            and route
            and route != "song_lipsync"
        )
    )
    if not valid_route:
        raise _replication_error(
            "CONTRACT_INVALID",
            f"approved audio plan does not match uploaded audio kind {kind}",
            category="audio",
        )
    return kind, dict(audio_plan)


def _v2_audio_directive(
    audio_kind: str | None,
    *,
    dialogue_changes: Sequence[Mapping[str, Any]],
) -> str:
    if audio_kind == "background_music":
        return "@Audio1 only replace music; preserve source speech; preserve source ambience."
    if audio_kind == "voiceover":
        if not dialogue_changes:
            return ""
        bindings: list[str] = []
        for change in dialogue_changes:
            speaker = str(change.get("speaker") or "").strip()
            text = str(change.get("text") or "").strip()
            window = str(change.get("window") or "").strip()
            if not speaker or not text or not window:
                raise _replication_error("CONTRACT_INVALID", "voiceover dialogue binding is incomplete", category="audio")
            bindings.append(f"{window} {speaker} speaks exactly {json.dumps(text, ensure_ascii=False)} using @Audio1")
        return "@Audio1 is the approved voiceover reference; " + "; ".join(bindings) + ". Seedance performs the approved voice binding; do not call TTS, final lip-sync, or replace_voiceover_audio."
    return ""


def merge_v2_binding_authority(
    runtime_entry: Mapping[str, Any], approved_binding: Mapping[str, Any]
) -> dict[str, Any]:
    """Restore prompt-only source-object authority after board verification."""

    merged = dict(runtime_entry)
    for field in (
        "replaces_tag",
        "source_object_descriptor",
        "target_identity_descriptor",
        "replacement_scope",
        "preserve_scope",
        "binding_confidence",
        "identity_scope",
        "wardrobe_policy",
        "target_wardrobe_evidence",
        "source_wardrobe_descriptor",
        "person_asset_profile",
        "asset_mime_type",
        "asset_width",
        "asset_height",
        "identity_subject_count",
        "asset_layout",
        "asset_composition",
    ):
        if field in approved_binding:
            merged[field] = approved_binding[field]
    return merged


def _resolve_v2_asset_board_manifest(context: Any) -> Mapping[str, Any]:
    """Resolve the one immutable target-asset manifest for a v2 edit."""

    descriptors = [
        item for item in (getattr(context, "artifacts", ()) or ())
        if isinstance(item, Mapping) and item.get("kind") == "asset_board_manifest"
    ]
    if not descriptors:
        raise _replication_error("ARTIFACT_NOT_FOUND", "v2 visual assets require a canonical asset board manifest", category="artifact")
    snapshot = getattr(context, "snapshot", None)
    revision = getattr(snapshot, "current_script_revision", None)
    approved_script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
    getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1 or _SHA256.fullmatch(approved_script_sha) is None or not callable(getter):
        raise _replication_error("APPROVAL_REQUIRED", "v2 asset board manifest requires the current approved script", category="artifact")
    approval = getter(context.job_id, revision)
    if not isinstance(approval, Mapping) or approval.get("contract") != "approved-script-lines/v2" or str(approval.get("script_sha256") or "").lower() != approved_script_sha:
        raise _replication_error("APPROVAL_REQUIRED", "v2 asset board manifest is not bound to the current approved script", category="artifact")
    try:
        approved_edit_script = canonicalize_approved_edit_script(approval.get("approved_edit_script"))
        _read_json_artifact(context, kind="script_revision", sha256=approved_script_sha)
    except ReplicationError as exc:
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest cannot verify the approved script mapping", category="artifact") from exc
    approved_bindings_sha = _sha(approved_edit_script["asset_bindings"])
    candidates = [
        item for item in descriptors
        if isinstance(item.get("metadata"), Mapping)
        and str(item["metadata"].get("approved_asset_bindings_sha256") or "").lower() == approved_bindings_sha
        and str(item["metadata"].get("approved_script_sha256") or "").lower() == approved_script_sha
    ]
    if len(candidates) != 1:
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest is missing or ambiguous for the current approved mapping", category="artifact")
    descriptor = candidates[0]
    artifact_id = str(descriptor.get("artifact_id") or "")
    digest = str(descriptor.get("sha256") or "").lower()
    if not artifact_id or _SHA256.fullmatch(digest) is None:
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest descriptor is invalid", category="artifact")
    try:
        with context.materialize_artifact("asset_board_manifest", artifact_id=artifact_id, sha256=digest) as media:
            data = Path(media.path).read_bytes()
    except ReplicationError:
        raise
    except Exception as exc:
        raise _replication_error("ARTIFACT_NOT_FOUND", "v2 asset board manifest cannot be materialized", category="artifact") from exc
    if hashlib.sha256(data).hexdigest() != digest:
        raise _replication_error("ARTIFACT_HASH_MISMATCH", "v2 asset board manifest bytes differ from its descriptor SHA", category="artifact")
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest is not canonical JSON", category="artifact") from exc
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != "asset-board-manifest/v1":
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest schema is invalid", category="artifact")
    metadata = descriptor.get("metadata")
    if (
        not isinstance(metadata, Mapping)
        or str(manifest.get("approved_script_sha256") or "").lower() != approved_script_sha
        or str(metadata.get("approved_script_sha256") or "").lower() != approved_script_sha
        or str(manifest.get("approved_asset_bindings_sha256") or "").lower() != approved_bindings_sha
        or str(metadata.get("approved_asset_bindings_sha256") or "").lower() != str(manifest.get("approved_asset_bindings_sha256") or "").lower()
        or str(metadata.get("asset_board_mapping_sha256") or "").lower() != str(manifest.get("asset_board_mapping_sha256") or "").lower()
        or str(metadata.get("provider_asset_board_contracts_sha256") or "").lower() != str(manifest.get("provider_asset_board_contracts_sha256") or "").lower()
    ):
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest metadata digests are stale", category="artifact")
    entries = manifest.get("entries")
    tags = manifest.get("uploaded_tags")
    if not isinstance(entries, list) or not isinstance(tags, list) or tags != manifest.get("binding_tags") or tags != manifest.get("prompt_tags"):
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest tag parity is invalid", category="artifact")
    approved_bindings = approved_edit_script["asset_bindings"]
    expected_tags = [str(binding["asset_tag"]) for binding in approved_bindings]
    if tags != expected_tags:
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest order differs from its tag contract", category="artifact")
    if len(entries) != len(approved_bindings):
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest does not cover the approved asset mapping", category="artifact")
    artifacts = {str(item.get("artifact_id") or ""): item for item in (getattr(context, "artifacts", ()) or ()) if isinstance(item, Mapping)}
    checked: list[dict[str, Any]] = []
    for expected_binding, entry in zip(approved_bindings, entries, strict=True):
        if not isinstance(entry, Mapping):
            raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest entry is invalid", category="artifact")
        for field in (
            "source_slot", "source_index", "source_asset_sha256", "asset_type",
            "asset_tag", "replaces_tag", "image_reference",
        ):
            if entry.get(field) != expected_binding.get(field):
                raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest differs from the approved asset mapping", category="artifact")
        board_id = str(entry.get("board_artifact_id") or "")
        board_sha = str(entry.get("board_sha256") or "").lower()
        board_descriptor = artifacts.get(board_id)
        if not board_id or _SHA256.fullmatch(board_sha) is None or not isinstance(board_descriptor, Mapping) or board_descriptor.get("kind") != "asset_board":
            raise _replication_error("ARTIFACT_NOT_FOUND", "v2 asset board manifest entry is not an immutable board artifact", category="artifact")
        metadata = board_descriptor.get("metadata")
        receipt = entry.get("receipt")
        expected_template = _asset_board_template_version(entry.get("asset_type"))
        if not isinstance(receipt, Mapping):
            raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest entry has no provider receipt", category="artifact")
        provider_request_sha = str(receipt.get("request_sha256") or "").lower()
        provider_response_sha = str(receipt.get("response_sha256") or "").lower()
        receipt_task_id = str(receipt.get("task_id") or "").strip()
        provider_receipt = receipt.get("provider_receipt")
        expected_provider_contract = _sha({
            "asset_type": entry.get("asset_type"),
            "template_version": expected_template,
            "source_asset_sha256": entry.get("source_asset_sha256"),
            "provider_request_sha256": provider_request_sha,
        })
        if (
            receipt.get("schema_version") != "runninghub-asset-board/v2"
            or receipt.get("asset_type") != entry.get("asset_type")
            or receipt.get("template_version") != expected_template
            or str(receipt.get("source_asset_sha256") or "").lower() != str(entry.get("source_asset_sha256") or "").lower()
            or _SHA256.fullmatch(provider_request_sha) is None
            or _SHA256.fullmatch(provider_response_sha) is None
            or not receipt_task_id
            or str(receipt.get("board_sha256") or "").lower() != board_sha
            or str(receipt.get("provider_asset_board_contract_sha256") or "").lower() != expected_provider_contract
            or not isinstance(provider_receipt, Mapping)
            or str(provider_receipt.get("request_sha256") or "").lower() != provider_request_sha
            or str(provider_receipt.get("response_sha256") or "").lower() != provider_response_sha
            or str(provider_receipt.get("task_id") or "").strip() != receipt_task_id
        ):
            raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest provider receipt lineage is invalid", category="artifact")
        if (
            str(board_descriptor.get("sha256") or "").lower() != board_sha
            or not isinstance(metadata, Mapping)
            or metadata.get("asset_type") != entry.get("asset_type")
            or metadata.get("template_version") != expected_template
            or metadata.get("source_slot") != entry.get("source_slot")
            or metadata.get("source_index") != entry.get("source_index")
            or metadata.get("asset_tag") != entry.get("asset_tag")
            or metadata.get("replaces_tag") != entry.get("replaces_tag")
            or metadata.get("image_reference") != entry.get("image_reference")
            or str(metadata.get("source_asset_sha256") or "").lower() != str(entry.get("source_asset_sha256") or "").lower()
            or str(metadata.get("provider_asset_board_contract_sha256") or "").lower() != str(receipt.get("provider_asset_board_contract_sha256") or "").lower()
            or str(metadata.get("provider_request_sha256") or "").lower() != provider_request_sha
            or str(metadata.get("provider_response_sha256") or "").lower() != provider_response_sha
            or str(metadata.get("provider_task_id") or "").strip() != receipt_task_id
        ):
            raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest differs from board artifact metadata", category="artifact")
        try:
            board_url = validate_public_https_url(entry.get("board_url"))
            metadata_url = validate_public_https_url(metadata.get("board_url"))
        except Exception as exc:
            raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest contains an invalid board URL", category="artifact") from exc
        if board_url != metadata_url:
            raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest URL differs from board metadata", category="artifact")
        try:
            with context.materialize_artifact("asset_board", artifact_id=board_id, sha256=board_sha) as media:
                board_bytes = Path(media.path).read_bytes()
            if hashlib.sha256(board_bytes).hexdigest() != board_sha:
                raise ValueError("board bytes SHA mismatch")
            StoryboardStage._png_dimensions(board_bytes)
        except ReplicationError:
            raise
        except Exception as exc:
            raise _replication_error("ARTIFACT_HASH_MISMATCH", "v2 asset board bytes cannot be verified", category="artifact") from exc
        checked.append(
            merge_v2_binding_authority(
                {**dict(entry), "board_url": board_url},
                expected_binding,
            )
        )
    mapping_basis = {
        "approved_asset_bindings_sha256": manifest.get("approved_asset_bindings_sha256"),
        "entries": [
            {key: entry[key] for key in ("source_slot", "source_index", "source_asset_sha256", "asset_type", "asset_tag", "replaces_tag", "image_reference", "board_artifact_id", "board_sha256", "board_url", "receipt")}
            for entry in checked
        ],
        "uploaded_tags": tags,
        "binding_tags": tags,
        "prompt_tags": tags,
    }
    if _sha(mapping_basis) != str(manifest.get("asset_board_mapping_sha256") or "").lower():
        raise _replication_error("CONTRACT_INVALID", "v2 asset board manifest mapping SHA is stale", category="artifact")
    provider_contracts_sha = _sha([entry.get("receipt", {}).get("provider_asset_board_contract_sha256") for entry in checked])
    if provider_contracts_sha != str(manifest.get("provider_asset_board_contracts_sha256") or "").lower():
        raise _replication_error("CONTRACT_INVALID", "v2 asset board provider contract aggregate is stale", category="artifact")
    return {
        "artifact_id": artifact_id,
        "sha256": digest,
        "approved_asset_bindings_sha256": approved_bindings_sha,
        "asset_board_mapping_sha256": str(manifest.get("asset_board_mapping_sha256") or "").lower(),
        "provider_asset_board_contracts_sha256": provider_contracts_sha,
        "entries": checked,
    }


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
        # non-song and emit exact ordered lyrics before the script review can
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

            is_v2 = isinstance(extensions, Mapping) and extensions.get("edit_contract") == "video-edit-v2"
            contract = validate_uploaded_audio_contract(candidate, audio_sha256=audio_sha256, v2=is_v2)
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

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        dynamics = _stage_output(context, "analyze_dynamics").get("source_dynamics_analysis")
        analysis = _mapping(dynamics, "source dynamics analysis")
        cuts = analysis.get("source_cuts")
        if not isinstance(cuts, Sequence) or isinstance(cuts, (str, bytes, bytearray)) or not cuts:
            raise _replication_error("CONTRACT_INVALID", "source dynamics has no ordered Cuts")
        snapshot = getattr(context, "snapshot", None)
        manifest = getattr(snapshot, "slots_manifest", None)
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
        published = _publish_json(context, kind="timeline_regions", value=envelope)
        return {"status": "ready", "timeline_regions": envelope, "published_artifacts": [published]}


def extract_voice_reference_audio(
    *,
    source_path: Path,
    start_ms: int,
    end_ms: int,
    destination: Path,
) -> Path:
    """Extract one bounded source voice sample for reference-conditioned TTS."""

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise _replication_error("CAPABILITY_UNAVAILABLE", "ffmpeg is required for voice reference extraction", category="capability")
    if start_ms < 0 or end_ms <= start_ms:
        raise _replication_error("CONTRACT_INVALID", "voice reference timing is invalid", category="audio")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-to",
        f"{end_ms / 1000:.3f}",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, timeout=120)
    if completed.returncode != 0 or not destination.is_file() or destination.stat().st_size <= 44:
        raise _replication_error("VOICE_REFERENCE_UNAVAILABLE", "source voiceover reference could not be extracted", category="audio")
    return destination


def assemble_language_audio_windows(
    *,
    source_path: Path,
    lip_sync_windows: Sequence[Mapping[str, Any]],
    voiceover_windows: Sequence[Mapping[str, Any]],
    destination: Path,
) -> None:
    """Assemble visible speech replacements, then overlay voiceover audio only."""

    base = destination.with_name(f"{destination.stem}-visible{destination.suffix}")
    if lip_sync_windows:
        raise _replication_error(
            "AUDIO_ROUTE_INVALID",
            "visible-speech lip-sync windows are no longer supported",
            category="audio",
        )
    shutil.copyfile(source_path, base)
    if not voiceover_windows:
        base.replace(destination)
        return

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise _replication_error("CAPABILITY_UNAVAILABLE", "ffmpeg is required for voiceover assembly", category="capability")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(base)]
    mute_filters: list[str] = []
    voice_filters: list[str] = []
    mix_inputs = ["[basea]"]
    for index, item in enumerate(voiceover_windows, start=1):
        timing = _mapping(item.get("timing"), f"voiceover window {index} timing")
        start_ms, end_ms = int(timing["start_ms"]), int(timing["end_ms"])
        if start_ms < 0 or end_ms <= start_ms:
            raise _replication_error("CONTRACT_INVALID", "voiceover window timing is invalid", category="audio")
        path = Path(item["path"])
        command.extend(["-i", str(path)])
        mute_filters.append(f"volume=0:enable='between(t,{start_ms / 1000:.3f},{end_ms / 1000:.3f})'")
        duration = (end_ms - start_ms) / 1000
        label = f"vo{index}"
        voice_filters.append(
            f"[{index}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,adelay={start_ms}|{start_ms}[{label}]"
        )
        mix_inputs.append(f"[{label}]")
    base_filter = ",".join(mute_filters) if mute_filters else "anull"
    filters = [f"[0:a]{base_filter}[basea]", *voice_filters]
    filters.append(
        f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0[aout]"
    )
    command.extend([
        "-filter_complex",
        ";".join(filters),
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(destination),
    ])
    completed = subprocess.run(command, check=False, capture_output=True, timeout=300)
    base.unlink(missing_ok=True)
    if completed.returncode != 0 or not destination.is_file() or destination.stat().st_size <= 0:
        raise _replication_error("AUDIO_ASSEMBLY_FAILED", "voiceover audio could not be assembled", category="audio")


class VoiceoverTtsFallbackEvaluationStage:
    """Authorize TTS only from a dialogue-only QC failure after assembly."""

    def __init__(self, *, qc_engine: Any, speech_transcriber: Any | None = None) -> None:
        if not callable(getattr(qc_engine, "run", None)):
            raise ValueError("VoiceoverTtsFallbackEvaluationStage requires a QC engine")
        if speech_transcriber is not None and not callable(speech_transcriber):
            raise ValueError("speech_transcriber must be callable")
        self.qc_engine = qc_engine
        self.speech_transcriber = speech_transcriber

    @staticmethod
    def _language_only(context: Any) -> bool:
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        admission = manifest.get("admission") if isinstance(manifest, Mapping) else None
        return isinstance(admission, Mapping) and admission.get("language_only") is True

    @staticmethod
    def _approved_lines(context: Any) -> dict[str, Mapping[str, Any]]:
        revision = getattr(getattr(context, "snapshot", None), "current_script_revision", None)
        getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
        if not isinstance(revision, int) or not callable(getter):
            return {}
        sidecar = getter(context.job_id, revision)
        rows = sidecar.get("line_contracts") if isinstance(sidecar, Mapping) else None
        result = {
            str(row.get("line_id") or ""): row
            for row in (rows or ())
            if isinstance(row, Mapping) and str(row.get("line_id") or "")
        }
        edit_script = sidecar.get("approved_edit_script") if isinstance(sidecar, Mapping) else None
        if isinstance(edit_script, Mapping):
            canonical = canonicalize_approved_edit_script(edit_script)
            dialogue_rows = [
                row for row in canonical["change_rows"]
                if str(row.get("kind") or "").casefold() == "dialogue"
            ]
            result = {
                line_id: line
                for line_id, line in result.items()
                if isinstance(line.get("time"), Mapping)
                and any(
                    int(change["start_ms"]) < int(line["time"]["end_ms"])
                    and int(change["end_ms"]) > int(line["time"]["start_ms"])
                    for change in dialogue_rows
                )
            }
        return result

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        if self._language_only(context):
            return {"status": "skipped", "reason": "language_only_never_uses_tts"}
        approved_by_id = self._approved_lines(context)
        if not approved_by_id:
            return {"status": "skipped", "reason": "no_approved_voiceover"}

        qc_result = self.qc_engine.run(context=context, input_artifacts=list(input_artifacts))
        report = qc_result.get("qc_report") if isinstance(qc_result, Mapping) else None
        hard_failures = report.get("hard_failures") if isinstance(report, Mapping) else None
        descriptor = VoiceoverTtsStage._assembled_descriptor(context)
        failed_rows: list[Mapping[str, Any]] = []
        if hard_failures == ["DIALOGUE_MISMATCH"]:
            evaluator = qc_result.get("qc_evaluator_response") if isinstance(qc_result, Mapping) else None
            edit_checks = evaluator.get("edit_checks") if isinstance(evaluator, Mapping) else None
            dialogue_checks = edit_checks.get("dialogue_checks") if isinstance(edit_checks, Mapping) else None
            failed_rows = [row for row in (dialogue_checks or ()) if isinstance(row, Mapping) and row.get("verdict") == "fail"]
        elif hard_failures == [] and callable(self.speech_transcriber):
            with context.materialize_artifact(
                "assembled_video",
                artifact_id=str(descriptor["artifact_id"]),
                sha256=str(descriptor["sha256"]),
            ) as media:
                segments = self.speech_transcriber(Path(media.path))

            def comparable(value: Any) -> str:
                return "".join(char.casefold() for char in str(value or "") if char.isalnum())

            for line_id, line in approved_by_id.items():
                speaker = line.get("speaker") if isinstance(line, Mapping) else None
                assignment = line.get("speaker_assignment") if isinstance(line, Mapping) else None
                speaker = speaker if isinstance(speaker, Mapping) else {}
                assignment = assignment if isinstance(assignment, Mapping) else {}
                visibility = str(speaker.get("visibility") or assignment.get("visibility") or "").casefold()
                timing = line.get("time") if isinstance(line, Mapping) else None
                text = line.get("text") if isinstance(line, Mapping) else None
                if str(line.get("content_type") or "").casefold() != "spoken" or visibility not in {"voiceover", "off_camera", "off_screen"} or not isinstance(timing, Mapping) or not isinstance(text, Mapping):
                    continue
                start_s, end_s = int(timing.get("start_ms", -1)) / 1000.0, int(timing.get("end_ms", -1)) / 1000.0
                actual = " ".join(
                    str(segment.get("text") or "").strip()
                    for segment in (segments or ())
                    if isinstance(segment, Mapping)
                    and float(segment.get("start", -1)) < end_s
                    and float(segment.get("end", -1)) > start_s
                ).strip()
                expected = str(text.get("exact") or "").strip()
                if comparable(actual) == comparable(expected):
                    continue
                failed_rows.append({
                    "change_id": line_id,
                    "verdict": "fail",
                    "expected_text": expected,
                    "asr_text": actual,
                    "output_language": str((line.get("language") or {}).get("bcp47") or ""),
                    "failure_type": "missing_line" if not actual else "wrong_words",
                })
        else:
            return {"status": "skipped", "reason": "voiceover_fallback_ineligible_qc_failure"}
        if not failed_rows:
            return {"status": "skipped", "reason": "voiceover_qc_failure_not_proven"}

        approved_lines: list[dict[str, Any]] = []
        failure_types: set[str] = set()
        line_ids: list[str] = []
        for check in failed_rows:
            check_id = str(check.get("change_id") or "")
            line_id = check_id
            line = approved_by_id.get(line_id)
            if line is None:
                check_start, check_end = check.get("start_ms"), check.get("end_ms")
                check_speaker = str(check.get("speaker") or "")
                matches = []
                for candidate_id, candidate in approved_by_id.items():
                    timing = candidate.get("time") if isinstance(candidate, Mapping) else None
                    speaker_data = candidate.get("speaker") if isinstance(candidate, Mapping) else None
                    speaker_data = speaker_data if isinstance(speaker_data, Mapping) else {}
                    if (
                        isinstance(timing, Mapping)
                        and isinstance(check_start, int)
                        and isinstance(check_end, int)
                        and check_start < int(timing.get("end_ms", -1))
                        and check_end > int(timing.get("start_ms", -1))
                        and (not check_speaker or check_speaker == str(speaker_data.get("id") or ""))
                    ):
                        matches.append((candidate_id, candidate))
                if len(matches) == 1:
                    line_id, line = matches[0]
            speaker = line.get("speaker") if isinstance(line, Mapping) else None
            assignment = line.get("speaker_assignment") if isinstance(line, Mapping) else None
            speaker = speaker if isinstance(speaker, Mapping) else {}
            assignment = assignment if isinstance(assignment, Mapping) else {}
            visibility = str(speaker.get("visibility") or assignment.get("visibility") or "").casefold()
            if not isinstance(line, Mapping) or str(line.get("content_type") or "").casefold() != "spoken" or visibility not in {"voiceover", "off_camera", "off_screen"}:
                return {"status": "skipped", "reason": "dialogue_failure_is_not_off_camera_voiceover"}
            timing = line.get("time")
            language = line.get("language")
            text = line.get("text")
            if not isinstance(timing, Mapping) or not isinstance(language, Mapping) or not isinstance(text, Mapping):
                raise _replication_error("CONTRACT_INVALID", "approved voiceover line is incomplete", category="audio")
            explicit_failure = str(check.get("failure_type") or "").strip().casefold()
            if explicit_failure in {"missing_line", "omitted_words", "wrong_words", "wrong_language", "absent_voiceover", "severe_timbre_drift"}:
                failure_type = explicit_failure
            elif not str(check.get("asr_text") or "").strip():
                failure_type = "missing_line"
            elif str(check.get("detected_language") or check.get("actual_language") or "").strip() not in {"", str(check.get("output_language") or "").strip()}:
                failure_type = "wrong_language"
            else:
                failure_type = "wrong_words"
            failure_types.add(failure_type)
            line_ids.append(line_id)
            approved_lines.append({
                "line_id": line_id,
                "changed": True,
                "content_type": "spoken",
                "visibility": "voiceover",
                "speaker": str(speaker.get("id") or assignment.get("speaker_id") or ""),
                "locale": str(language.get("bcp47") or ""),
                "text": str(text.get("exact") or ""),
                "start_ms": int(timing.get("start_ms", -1)),
                "end_ms": int(timing.get("end_ms", -1)),
                "reference_start_ms": int(timing.get("start_ms", -1)),
                "reference_end_ms": int(timing.get("end_ms", -1)),
            })

        script_sha = str(getattr(getattr(context, "snapshot", None), "approved_script_sha256", "") or "").lower()
        targeted_qc = {
            "contract": "voiceover-targeted-qc/v1",
            "picture_passed": True,
            "failure_scope": "voiceover_only",
            "failure_types": sorted(failure_types),
            "line_ids": line_ids,
            "assembled_video_sha256": str(descriptor.get("sha256") or "").lower(),
            "approved_script_sha256": script_sha,
        }
        attempted = {
            str(item.get("block_id") or "")
            for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping) and item.get("kind") == "voiceover_tts_attempt_receipt"
        }
        try:
            fallback = build_voiceover_tts_fallback_receipt(
                qc_receipt=targeted_qc,
                approved_lines=approved_lines,
                attempted_block_ids=attempted,
            )
        except VoiceoverTtsFallbackError as exc:
            raise _replication_error("CONTRACT_INVALID", str(exc), category="audio") from exc
        data = _canonical(fallback)
        published = context.publish_bytes(
            kind="voiceover_tts_fallback_receipt",
            data=data,
            content_type="application/json",
            expected_sha256=hashlib.sha256(data).hexdigest(),
            metadata={"contract": fallback["contract"], "receipt": fallback},
        )
        artifact = {**dict(published), "kind": "voiceover_tts_fallback_receipt", "receipt": fallback}
        return {"status": "ready", "fallback_receipt": fallback, "published_artifacts": [artifact]}


class VoiceoverTtsStage:
    """Replace approved normal-replication voiceovers without face lip-sync."""

    def __init__(self, *, workflow_client: Any) -> None:
        required = ("upload_media", "run_tts")
        if any(not callable(getattr(workflow_client, name, None)) for name in required):
            raise ValueError("VoiceoverTtsStage requires upload and TTS methods")
        self.workflow_client = workflow_client

    @staticmethod
    def _approved_voiceover_lines(context: Any) -> list[dict[str, Any]]:
        revision = getattr(getattr(context, "snapshot", None), "current_script_revision", None)
        getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
        if not isinstance(revision, int) or not callable(getter):
            return []
        sidecar = getter(context.job_id, revision)
        rows = sidecar.get("line_contracts") if isinstance(sidecar, Mapping) else None
        if not isinstance(rows, list):
            return []
        result: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, Mapping) or str(raw.get("content_type") or "").casefold() != "spoken":
                continue
            speaker = raw.get("speaker")
            assignment = raw.get("speaker_assignment")
            speaker = speaker if isinstance(speaker, Mapping) else {}
            assignment = assignment if isinstance(assignment, Mapping) else {}
            visibility = str(speaker.get("visibility") or assignment.get("visibility") or "").casefold()
            if visibility not in {"voiceover", "off_camera", "off_screen"}:
                continue
            text = raw.get("text")
            language = raw.get("language")
            timing = raw.get("time")
            if not isinstance(text, Mapping) or not isinstance(language, Mapping) or not isinstance(timing, Mapping):
                raise _replication_error("CONTRACT_INVALID", "approved voiceover line is incomplete", category="audio")
            exact = str(text.get("exact") or "").strip()
            locale = str(language.get("bcp47") or "").strip()
            speaker_id = str(speaker.get("id") or assignment.get("speaker_id") or "").strip()
            try:
                start_ms, end_ms = int(timing["start_ms"]), int(timing["end_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("CONTRACT_INVALID", "approved voiceover timing is invalid", category="audio") from exc
            if not exact or not locale or not speaker_id or start_ms < 0 or end_ms <= start_ms:
                raise _replication_error("CONTRACT_INVALID", "approved voiceover line is invalid", category="audio")
            assert_public_content_safe(exact)
            result.append({
                "line_id": str(raw.get("line_id") or ""),
                "text": exact,
                "locale": locale,
                "speaker": speaker_id,
                "timing": {"start_ms": start_ms, "end_ms": end_ms},
            })
        result.sort(key=lambda item: (item["timing"]["start_ms"], item["timing"]["end_ms"], item["line_id"]))
        return result

    @staticmethod
    def _assembled_descriptor(context: Any) -> Mapping[str, Any]:
        for item in reversed(tuple(getattr(context, "artifacts", ()) or ())):
            if isinstance(item, Mapping) and item.get("kind") == "assembled_video":
                if item.get("artifact_id") and item.get("sha256"):
                    return item
        raise _replication_error("ARTIFACT_NOT_FOUND", "assembled video is unavailable for voiceover replacement", category="artifact")

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        receipt = None
        for item in [*input_artifacts, *(getattr(context, "artifacts", ()) or ())]:
            if not isinstance(item, Mapping) or item.get("kind") != "voiceover_tts_fallback_receipt":
                continue
            candidate = item.get("receipt")
            metadata = item.get("metadata")
            if not isinstance(candidate, Mapping) and isinstance(metadata, Mapping):
                candidate = metadata.get("receipt")
            if isinstance(candidate, Mapping):
                receipt = candidate
                break
        if not isinstance(receipt, Mapping):
            return {"status": "skipped", "reason": "voiceover_tts_fallback_not_required"}
        if receipt.get("contract") != "voiceover-tts-fallback-receipt/v1":
            raise _replication_error("CONTRACT_INVALID", "voiceover TTS fallback receipt contract is invalid", category="audio")
        signed = dict(receipt)
        receipt_sha = str(signed.pop("receipt_sha256", "")).lower()
        if len(receipt_sha) != 64 or _sha(signed) != receipt_sha:
            raise _replication_error("CONTRACT_INVALID", "voiceover TTS fallback receipt SHA is invalid", category="audio")
        approved_script_sha = str(getattr(getattr(context, "snapshot", None), "approved_script_sha256", "") or "").lower()
        if approved_script_sha and str(receipt.get("approved_script_sha256") or "").lower() != approved_script_sha:
            raise _replication_error("CONTRACT_INVALID", "voiceover TTS fallback receipt is stale", category="audio")
        blocks = receipt.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise _replication_error("CONTRACT_INVALID", "voiceover TTS fallback receipt has no blocks", category="audio")
        descriptor = self._assembled_descriptor(context)
        if str(receipt.get("assembled_video_sha256") or "").lower() != str(descriptor.get("sha256") or "").lower():
            raise _replication_error("CONTRACT_INVALID", "voiceover TTS fallback receipt targets another assembly", category="audio")
        attempted_block_ids: set[str] = set()
        for item in [*input_artifacts, *(getattr(context, "artifacts", ()) or ())]:
            if not isinstance(item, Mapping) or item.get("kind") != "voiceover_tts_attempt_receipt":
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            attempted_block_ids.add(str(item.get("block_id") or metadata.get("block_id") or ""))
        if any(str(block.get("block_id") or "") in attempted_block_ids for block in blocks if isinstance(block, Mapping)):
            raise _replication_error("PROVIDER_RECONCILE_REQUIRED", "voiceover TTS block already has an attempt receipt", category="provider")
        voice_references: dict[str, str] = {}
        voiceover_windows: list[dict[str, Any]] = []
        attempt_artifacts: list[Mapping[str, Any]] = []
        with context.materialize_slot("source_video") as source:
            source_path = Path(source.path)
            for index, block in enumerate(blocks, start=1):
                if not isinstance(block, Mapping) or block.get("attempt_count") != 0:
                    raise _replication_error("CONTRACT_INVALID", "voiceover TTS fallback block is invalid or already attempted", category="audio")
                speaker = str(block.get("speaker") or "").strip()
                locale = str(block.get("locale") or "").strip()
                text = str(block.get("plain_text") or "").strip()
                timing = {"start_ms": int(block.get("start_ms", -1)), "end_ms": int(block.get("end_ms", -1))}
                reference_key = f"{speaker}:{block.get('reference_start_ms')}:{block.get('reference_end_ms')}"
                reference_url = voice_references.get(reference_key)
                if reference_url is None:
                    reference = extract_voice_reference_audio(
                        source_path=source_path,
                        start_ms=int(block.get("reference_start_ms", -1)),
                        end_ms=int(block.get("reference_end_ms", -1)),
                        destination=Path(context.work_dir) / f"normal-voice-reference-{len(voice_references) + 1:02d}.wav",
                    )
                    reference_url = str(self.workflow_client.upload_media(reference) or "").strip()
                    if not reference_url:
                        raise _replication_error("VOICE_REFERENCE_UNAVAILABLE", "voiceover reference upload returned no URL", category="provider")
                    voice_references[reference_key] = reference_url
                attempt = {
                    "contract": "voiceover-tts-attempt-receipt/v1",
                    "block_id": str(block.get("block_id") or ""),
                    "fallback_receipt_sha256": receipt_sha,
                    "attempt_count": 1,
                }
                attempt_data = _canonical(attempt)
                attempt_published = context.publish_bytes(
                    kind="voiceover_tts_attempt_receipt",
                    data=attempt_data,
                    content_type="application/json",
                    expected_sha256=hashlib.sha256(attempt_data).hexdigest(),
                    metadata={"block_id": attempt["block_id"], "contract": attempt["contract"]},
                )
                attempt_artifacts.append({
                    **dict(attempt_published),
                    "kind": "voiceover_tts_attempt_receipt",
                    "block_id": attempt["block_id"],
                })
                response = self.workflow_client.run_tts(
                    text,
                    locale,
                    timing,
                    speaker=speaker,
                    voice_reference_url=reference_url,
                )
                audio = response.get("audio_bytes") if isinstance(response, Mapping) else None
                receipt = response.get("receipt") if isinstance(response, Mapping) else None
                if not isinstance(audio, bytes) or not audio or not isinstance(receipt, Mapping):
                    raise _replication_error("PROVIDER_RESULT_INVALID", "voiceover TTS returned incomplete media", category="provider")
                digest = hashlib.sha256(audio).hexdigest()
                if str(receipt.get("output_sha256") or "").lower() != digest:
                    raise _replication_error("PROVIDER_RESULT_INVALID", "voiceover TTS receipt does not match output", category="provider")
                audio_path = Path(context.work_dir) / f"normal-voiceover-{index:02d}.wav"
                audio_path.write_bytes(audio)
                voiceover_windows.append({"path": audio_path, "timing": timing})
        with context.materialize_artifact(
            "assembled_video",
            artifact_id=str(descriptor["artifact_id"]),
            sha256=str(descriptor["sha256"]),
        ) as assembled:
            destination = Path(context.work_dir) / "result-with-voiceover.mp4"
            assemble_language_audio_windows(
                source_path=Path(assembled.path),
                lip_sync_windows=[],
                voiceover_windows=voiceover_windows,
                destination=destination,
            )
        data = destination.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        artifact = context.publish_bytes(
            kind="assembled_video",
            data=data,
            content_type="video/mp4",
            expected_sha256=digest,
            metadata={
                "producer_stage": "replace_voiceover_audio",
                "voiceover_window_count": len(voiceover_windows),
                "voiceover_tts_fallback_receipt_sha256": receipt_sha,
                "voiceover_tts_block_ids": [str(block.get("block_id") or "") for block in blocks],
            },
        )
        return {"status": "ready", "output_artifact": artifact, "published_artifacts": [*attempt_artifacts, artifact]}


def _ffmpeg_source_segment(*, source_path: Path, start_ms: int, end_ms: int, destination: Path) -> Path:
    duration_ms = end_ms - start_ms
    command = [
        "ffmpeg", "-v", "error", "-y", "-ss", f"{start_ms / 1000:.3f}", "-i", str(source_path),
        "-t", f"{duration_ms / 1000:.3f}", "-map", "0:v:0", "-map", "0:a?",
        *video_encoder_args(), "-c:a", "aac",
        "-movflags", "+faststart", "-map_metadata", "-1", str(destination),
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise _replication_error(
            "CAPABILITY_UNAVAILABLE",
            "ffmpeg could not create the bounded source video reference",
            retryable=True,
            category="capability",
        ) from exc
    return destination


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
    def _is_v2(context: Any) -> bool:
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
        return isinstance(extensions, Mapping) and extensions.get("edit_contract") == "video-edit-v2"

    @staticmethod
    def _v2_source_cuts(context: Any) -> list[dict[str, Any]]:
        source_dynamics = _mapping(
            _stage_output(context, "analyze_dynamics").get("source_dynamics_analysis"),
            "source dynamics analysis",
        )
        raw_cuts = source_dynamics.get("source_cuts")
        if not isinstance(raw_cuts, list) or not raw_cuts:
            raise _replication_error("CONTRACT_INVALID", "v2 storyboard requires source Cut evidence")
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        previous_end = -1
        for index, raw in enumerate(raw_cuts, start=1):
            cut = _mapping(raw, f"source Cut {index}")
            cut_id = str(cut.get("cut_id") or f"C{index:02d}")
            start_ms = int(cut.get("start_ms") if cut.get("start_ms") is not None else int(cut["start_us"]) // 1000)
            end_ms = int(cut.get("end_ms") if cut.get("end_ms") is not None else (int(cut["end_us"]) + 999) // 1000)
            if cut_id in seen or start_ms < previous_end or end_ms <= start_ms:
                raise _replication_error("CONTRACT_INVALID", "v2 source Cut timing or identity is invalid")
            result.append({**dict(cut), "cut_id": cut_id, "start_ms": start_ms, "end_ms": end_ms})
            seen.add(cut_id)
            previous_end = end_ms
        return result

    @staticmethod
    def _v2_script_cut_projection(context: Any, source_cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        script_sha = str(getattr(getattr(context, "snapshot", None), "approved_script_sha256", "") or "").lower()
        if _SHA256.fullmatch(script_sha) is None:
            raise _replication_error("APPROVAL_REQUIRED", "v2 storyboard requires an approved script")
        script = _read_json_artifact(context, kind="script_revision", sha256=script_sha)
        raw_cuts = script.get("cuts")
        if not isinstance(raw_cuts, list):
            raw_cuts = script.get("source_cuts")
        source_by_id = {str(item["cut_id"]): dict(item) for item in source_cuts}
        if not isinstance(raw_cuts, list) or not raw_cuts:
            raw_cuts = list(source_cuts)
        projected: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_cuts, start=1):
            cut = _mapping(raw, f"approved script Cut {index}")
            cut_id = str(cut.get("cut_id") or "")
            if cut_id not in source_by_id:
                raise _replication_error("CONTRACT_INVALID", f"approved script Cut {cut_id} is not in source evidence")
            source = source_by_id[cut_id]
            projected.append({
                **dict(source),
                **dict(cut),
                "cut_id": cut_id,
                "start_ms": int(cut.get("start_ms", source["start_ms"])),
                "end_ms": int(cut.get("end_ms", source["end_ms"])),
            })
        return projected

    @staticmethod
    def _v2_source_cut_frames(context: Any, source_cuts: Sequence[Mapping[str, Any]]) -> dict[str, Path]:
        work_dir = Path(context.work_dir) / "reference_frames"
        work_dir.mkdir(parents=True, exist_ok=True)
        frames: dict[str, Path] = {}
        with context.materialize_slot("source_video") as media:
            source_path = Path(media.path)
            source_sha = str(getattr(media, "sha256", "") or "").lower()
            if _SHA256.fullmatch(source_sha) is None or not source_path.is_file():
                raise _replication_error("ARTIFACT_HASH_MISMATCH", "v2 storyboard source video lineage is invalid", category="artifact")
            for index, raw in enumerate(source_cuts, start=1):
                cut = _mapping(raw, f"source Cut {index}")
                cut_id = str(cut["cut_id"])
                start_us = int(cut.get("start_us", int(cut["start_ms"]) * 1000))
                end_us = int(cut.get("end_us", int(cut["end_ms"]) * 1000))
                timestamp_us = start_us + max(0, min(100_000, (end_us - start_us - 1) // 2))
                frame_index = max(0, int(round(timestamp_us * 30 / 1_000_000)))
                output = work_dir / f"v2-source-{cut_id}.png"
                command = [
                    "ffmpeg", "-y", "-i", str(source_path), "-vf",
                    f"select='eq(n,{frame_index})'", "-vsync", "vfr", str(output),
                ]
                completed = subprocess.run(command, check=False, capture_output=True)
                if int(getattr(completed, "returncode", 1)) != 0 or not output.is_file():
                    raise _replication_error("CAPABILITY_UNAVAILABLE", f"source Cut {cut_id} frame extraction failed", retryable=True, category="artifact")
                data = output.read_bytes()
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise _replication_error("ARTIFACT_INVALID", f"source Cut {cut_id} frame is not PNG", category="artifact")
                frames[cut_id] = output
        return frames

    @staticmethod
    def _v2_sketch_prompt(page: Sequence[Mapping[str, Any]], *, page_index: int, page_count: int) -> str:
        cards = "\n".join(
            f"Cut {cut['cut_id']} {int(cut['start_ms'])}-{int(cut['end_ms'])}ms: "
            f"purpose={str(cut.get('action_purpose') or cut.get('action') or 'preserve source action')}; "
            f"motion={str(cut.get('motion') or 'preserve source movement')}"
            for cut in page
        )
        prompt = (
            "Create a hand-drawn source-video edit logic board. Use only the supplied source Cut frames. "
            f"Page {page_index} of {page_count}; keep strict chronological order and show the action handoff "
            "and camera continuity between cards. Do not add visual asset presentation, comparison panels, "
            "labels, captions, or other written marks.\n" + cards
        )
        try:
            assert_public_content_safe(prompt)
        except Exception as exc:
            raise _replication_error("CONTENT_SAFETY_BLOCKER", "v2 sketch storyboard prompt is not neutral", category="safety") from exc
        return prompt

    def _run_v2(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        source_cuts = self._v2_source_cuts(context)
        script_cuts = self._v2_script_cut_projection(context, source_cuts)
        snapshot = getattr(context, "snapshot", None)
        script_revision = getattr(snapshot, "current_script_revision", None)
        script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
        getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
        if not callable(getter) or isinstance(script_revision, bool) or not isinstance(script_revision, int) or script_revision < 1:
            raise _replication_error("APPROVAL_REQUIRED", "v2 storyboard requires the approved script sidecar")
        sidecar = getter(context.job_id, script_revision)
        if (
            not isinstance(sidecar, Mapping)
            or sidecar.get("contract") != "approved-script-lines/v2"
            or sidecar.get("revision") != script_revision
            or str(sidecar.get("script_sha256") or "").lower() != script_sha
        ):
            raise _replication_error("APPROVAL_STALE", "approved script sidecar is stale for v2 storyboard")
        draft = self._revision._planner.draft_storyboard(context, input_artifacts)
        candidate = draft.get("value") if isinstance(draft, Mapping) else None
        if not isinstance(candidate, Mapping):
            raise _replication_error("SKETCH_STORYBOARD_INVALID", "sketch storyboard candidate is missing")
        raw_candidate_cuts = candidate.get("cuts")
        if not isinstance(raw_candidate_cuts, list):
            raise _replication_error("SKETCH_STORYBOARD_INVALID", "sketch storyboard candidate has no Cuts")
        source_by_id = {str(cut["cut_id"]): cut for cut in script_cuts}
        normalized: list[dict[str, Any]] = []
        for raw in raw_candidate_cuts:
            cut = _mapping(raw, "sketch storyboard Cut")
            cut_id = str(cut.get("cut_id") or "")
            source = source_by_id.get(cut_id)
            if source is None:
                raise _replication_error("SKETCH_STORYBOARD_INVALID", "sketch storyboard Cut coverage is not source-bound")
            normalized.append({
                **dict(cut),
                "cut_id": cut_id,
                "start_ms": int(cut.get("start_ms", source["start_ms"])),
                "end_ms": int(cut.get("end_ms", source["end_ms"])),
                "action_purpose": str(cut.get("action_purpose") or source.get("action") or "preserve source action"),
                "motion": str(cut.get("motion") or source.get("motion") or "preserve source movement"),
            })
        validator = _load_module("scripts/validate_user_director_storyboard.py", "usfr_v2_sketch_validator")
        try:
            validated = validator.validate_sketch_cut_board(normalized)
        except Exception as exc:
            raise _replication_error("SKETCH_STORYBOARD_INVALID", f"sketch storyboard: {exc}", category="contract") from exc
        pages = validated["pages"]
        frame_paths = self._v2_source_cut_frames(context, source_cuts)
        image_results: list[dict[str, Any]] = []
        page_refs: list[dict[str, Any]] = []
        for page_index, page in enumerate(pages, start=1):
            page_cut_ids = [str(cut["cut_id"]) for cut in page]
            references = [frame_paths[cut_id] for cut_id in page_cut_ids]
            generated = self._image_client.run_image2(
                prompt=self._v2_sketch_prompt(page, page_index=page_index, page_count=len(pages)),
                reference_images=references,
                aspect_ratio="9:16",
                resolution="2k",
                quality="medium",
            )
            image_bytes = generated.get("image_bytes") if isinstance(generated, Mapping) else None
            width, height = self._png_dimensions(image_bytes if isinstance(image_bytes, bytes) else b"")
            digest = hashlib.sha256(image_bytes).hexdigest()
            published = context.publish_bytes(
                kind="storyboard_sketch_image",
                data=image_bytes,
                content_type="image/png",
                expected_sha256=digest,
                metadata={
                    "approved_script_sha256": str(getattr(context.snapshot, "approved_script_sha256", "")),
                    "page_index": page_index,
                    "page_cut_ids": page_cut_ids,
                    "source_cut_frame_sha256s": [hashlib.sha256(path.read_bytes()).hexdigest() for path in references],
                },
            )
            image_results.append(dict(published))
            page_refs.append({"page_index": page_index, "cut_ids": page_cut_ids, "artifact": dict(published), "width": width, "height": height})
        revision = int(getattr(snapshot, "current_storyboard_revision", 0) or 0) + 1
        sketch = {
            "schema_version": "sketch-cut-storyboard/v2",
            "revision": revision,
            "approved_script_sha256": script_sha,
            "pages": pages,
            "page_artifacts": page_refs,
        }
        revision_sha = _sha(sketch)
        sketch["revision_sha256"] = revision_sha
        raw = _canonical(sketch)
        artifact_sha = hashlib.sha256(raw).hexdigest()
        published_revision = context.publish_bytes(
            kind="storyboard_revision",
            data=raw,
            content_type="application/json",
            expected_sha256=artifact_sha,
            metadata={"approved_script_sha256": script_sha, "storyboard_revision": revision},
        )
        manifest = RevisionManifest(
            kind="storyboard",
            revision=revision,
            object_key=str(published_revision.get("object_key") or ""),
            sha256=artifact_sha,
            inputs_sha256=str(draft.get("inputs_sha256") or _sha({"source_cuts": source_cuts, "script_sha256": script_sha})),
            validation_sha256=_sha({"revision_sha256": revision_sha, "page_artifacts": [item["artifact"]["sha256"] for item in page_refs]}),
            parent_script_sha256=script_sha,
            output_language=str((getattr(snapshot, "slots_manifest", {}) or {}).get("output_language") or ""),
        )
        return {
            "storyboard_revision": manifest,
            "sketch_storyboard": sketch,
            "storyboard_images": image_results,
            "published_artifacts": [dict(published_revision), *image_results],
        }

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
            raw_paths_by_slot: dict[str, list[Path]] = {}
            # The role is fixed by the manifest. UI/opaque/tail slots never
            # enter a semantic storyboard request.
            for slot_id, limit in (("new_model_image", MAX_MODEL_REFERENCES), ("new_product_image", 2)):
                if not _present(context, slot_id):
                    continue
                hashes = _slot_sha256s(context, slot_id)
                slot_paths: list[Path] = []
                for index in range(min(limit, len(hashes))):
                    media = stack.enter_context(context.materialize_slot(slot_id, index=index))
                    path = Path(media.path)
                    if not path.is_file() or path.stat().st_size <= 0:
                        raise _replication_error("ARTIFACT_NOT_FOUND", f"{slot_id}[{index}] could not be materialized", category="artifact")
                    slot_paths.append(path)
                if slot_paths:
                    raw_paths_by_slot[slot_id] = slot_paths
            yield self._normalize_target_assets(context, raw_paths_by_slot)

    def _normalize_target_assets(
        self,
        context: Any,
        raw_paths_by_slot: Mapping[str, Sequence[Path]],
    ) -> list[Path]:
        """Create one clean multi-view reference sheet per uploaded target asset.

        The uploaded file remains the immutable authorization truth.  The
        generated sheet is only a normalized visual carrier for downstream
        Image2 calls, so its digest is published separately and never replaces
        the original slot SHA in the contract.
        """

        prompts = {
            "new_model_image": (
                "Create one clean character reference sheet for the single person in reference image 1. "
                "Layout: one row of three full-body views — front, three-quarter, and side — plus one "
                "close-up row containing a large frontal face close-up, a profile face close-up, and a "
                "hands close-up. Preserve this exact person's identity, facial structure, skin tone, hair, "
                "body proportion and wardrobe. Neutral studio background, even lighting, sharp focus, high "
                "detail on facial features and hands. One person only. No text, no logo, no watermark, "
                "no extra people, no stylization, no beautification, no body reshaping."
            ),
            "new_product_image": (
                "Create one clean product reference sheet for the single product in reference image 1. "
                "Layout: one row of three views — front, three-quarter, and side — plus one close-up row "
                "containing a material/texture macro, a label/interface detail macro, and a hand-held "
                "operation view showing how the product is held and used. Preserve exact shape, "
                "proportion, color, material and every printed marking. Neutral background, even lighting, "
                "sharp focus. No text beyond what exists on the product, no logo invention, no watermark."
            ),
        }
        normalized: list[Path] = []
        for slot_id in ("new_model_image", "new_product_image"):
            prompt = prompts.get(slot_id)
            for index, path in enumerate(raw_paths_by_slot.get(slot_id, ())):
                if prompt is None:
                    normalized.append(Path(path))
                    continue
                try:
                    generated = self._image_client.run_image2(
                        prompt=prompt,
                        reference_images=[Path(path)],
                        aspect_ratio="1:1",
                        resolution="2k",
                        quality="high",
                    )
                except Exception as exc:
                    raise _replication_error(
                        "CAPABILITY_UNAVAILABLE",
                        f"target asset normalization failed for {slot_id}[{index}]",
                        retryable=True,
                        category="provider",
                    ) from exc
                image_bytes = generated.get("image_bytes") if isinstance(generated, Mapping) else None
                self._png_dimensions(image_bytes if isinstance(image_bytes, bytes) else b"")
                digest = hashlib.sha256(image_bytes).hexdigest()
                destination = Path(context.work_dir) / "reference_assets" / f"{slot_id}-{index:02d}-sheet.png"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(image_bytes)
                context.publish_bytes(
                    kind="normalized_target_asset_sheet",
                    data=image_bytes,
                    content_type="image/png",
                    expected_sha256=digest,
                    metadata={
                        "slot_id": slot_id,
                        "slot_index": index,
                        "source_asset_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                        "sheet_kind": "character_views" if slot_id == "new_model_image" else "product_views",
                    },
                )
                normalized.append(destination)
        return normalized

    @staticmethod
    def _visual_target_sha256s(context: Any) -> list[str]:
        """Return every final visual target in fixed Image-slot order."""

        targets: list[str] = []
        for slot_id, limit in (("new_model_image", MAX_MODEL_REFERENCES), ("new_product_image", 2)):
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
        person_region_crop: list[int] | None = None
        try:
            with context.materialize_slot("source_video") as media:
                source_path = Path(media.path)
                source_sha256 = str(media.sha256 or "").lower()
                if _SHA256.fullmatch(source_sha256) is None:
                    raise _replication_error("ARTIFACT_HASH_MISMATCH", "source video has no immutable SHA-256", category="artifact")
                fps_num = int(source_dynamics.get("fps_num") or 30)
                fps_den = int(source_dynamics.get("fps_den") or 1)
                if fps_num <= 0 or fps_den <= 0:
                    fps_num, fps_den = 30, 1
                person_cuts = [
                    raw_cut
                    for raw_cut in cuts
                    if str(_mapping(raw_cut, "source Cut").get("subject_presence") or "uncertain") in _PERSON_PRESENCE
                ]
                # If the dynamics adapter did not provide usable person
                # labels, keep the complete source list rather than creating
                # an empty control sheet for a pure-UI/unknown input.
                selected_cuts = person_cuts or cuts
                person_filter_applied = bool(person_cuts)
                frame_specs: list[dict[str, Any]] = []
                for index, raw_cut in enumerate(selected_cuts, start=1):
                    cut = _mapping(raw_cut, f"source Cut {index}")
                    cut_id = str(cut.get("cut_id") or f"C{index:02d}")
                    start_us, end_us = int(cut["start_us"]), int(cut["end_us"])
                    if start_us < 0 or end_us <= start_us:
                        raise _replication_error("CONTRACT_INVALID", f"source Cut {cut_id} timing is invalid")
                    # A point inside the Cut avoids cross-cut decode ambiguity while
                    # keeping the frame maximally close to the recorded transition.
                    timestamp_us = start_us + min(100_000, max(0, (end_us - start_us - 1) // 2))
                    frame_index = max(
                        0,
                        int(round(timestamp_us * fps_num / (1_000_000 * fps_den))),
                    )
                    frame_specs.append(
                        {
                            "cut_id": cut_id,
                            "timestamp_us": timestamp_us,
                            "frame_index": frame_index,
                        }
                    )
                unique_indices = list(dict.fromkeys(item["frame_index"] for item in frame_specs))
                select_expression = "+".join(
                    f"eq(n\\,{frame_index})" for frame_index in unique_indices
                )
                batch_pattern = work_dir / "source-batch-%03d.png"
                command = [
                    "ffmpeg", "-v", "error", "-y", "-i", str(source_path),
                    "-vf", f"select='{select_expression}'", "-vsync", "0",
                    "-map_metadata", "-1", "-f", "image2", str(batch_pattern),
                ]
                subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                extracted = sorted(work_dir.glob("source-batch-*.png"))
                if len(extracted) != len(unique_indices):
                    raise _replication_error(
                        "PROVIDER_RESULT_INVALID",
                        "source keyframe batch extraction returned an unexpected frame count",
                        category="artifact",
                    )
                by_frame_index = dict(zip(unique_indices, extracted))
                for spec in frame_specs:
                    frame_path = work_dir / f"source-{spec['cut_id']}.png"
                    shutil.copyfile(by_frame_index[spec["frame_index"]], frame_path)
                    if not frame_path.is_file() or frame_path.stat().st_size <= 0:
                        raise _replication_error("PROVIDER_RESULT_INVALID", f"source keyframe extraction failed for {spec['cut_id']}", category="artifact")
                    frame_bytes = frame_path.read_bytes()
                    StoryboardStage._png_dimensions(frame_bytes)
                    frames.append((frame_path, {"cut_id": spec["cut_id"], "timestamp_us": spec["timestamp_us"], "sha256": hashlib.sha256(frame_bytes).hexdigest()}))
        except ReplicationError:
            raise
        except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "ffmpeg could not extract source Cut keyframes", retryable=True, category="capability") from exc

        # First discard whole-frame UI Cuts, then remove a clearly static
        # side panel from the remaining raw source frames.  This must happen
        # before contact-sheet assembly so the panel never reaches Image2.
        box = _person_region_box([path for path, _record in frames])
        if box is not None:
            left, right = box
            try:
                for frame_path, record in frames:
                    with Image.open(frame_path) as image:
                        image.crop((left, 0, right, image.height)).save(frame_path, format="PNG")
                    frame_bytes = frame_path.read_bytes()
                    StoryboardStage._png_dimensions(frame_bytes)
                    record["sha256"] = hashlib.sha256(frame_bytes).hexdigest()
                    record["person_region_crop"] = [left, right]
                person_region_crop = [left, right]
            except Exception as exc:
                raise _replication_error("ARTIFACT_INVALID", "source person-region crop failed", category="artifact") from exc

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
            metadata={
                "source_video_sha256": source_sha256,
                "cut_ids": [item[1]["cut_id"] for item in frames],
                "source_cut_count": len(cuts),
                "selected_cut_count": len(frames),
                "person_filter_applied": person_filter_applied,
                "person_region_crop": person_region_crop,
            },
        )
        return {
            "path": sheet_path,
            "source_video_sha256": source_sha256,
            "source_keyframes": [record for _path, record in frames],
            "source_keyframe_sheet_sha256": sheet_sha256,
            "person_filter_applied": person_filter_applied,
            "person_region_crop": person_region_crop,
            "published_artifacts": [published],
        }

    def _replacement_control_sheet(
        self,
        *,
        context: Any,
        source_dynamics: Mapping[str, Any],
        source_sheet: Mapping[str, Any],
        target_references: Sequence[Path],
        visible_text_locks: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Generate the internal, source-anchored replacement control sheet."""

        source_path = Path(source_sheet["path"])
        cut_ids = [
            str(item.get("cut_id") or f"C{index:02d}")
            for index, item in enumerate(source_sheet.get("source_keyframes") or (), start=1)
        ]
        if not cut_ids:
            raise _replication_error("CONTRACT_INVALID", "source keyframe sheet has no selected Cuts")
        target_roles: list[str] = []
        reference_index = 2
        if _present(context, "new_model_image"):
            model_count = min(MAX_MODEL_REFERENCES, len(_slot_sha256s(context, "new_model_image")))
            for model_index in range(model_count):
                target_roles.append(
                    f"Reference image {reference_index} is new_model_image[{model_index}] target truth: replace only the authorized "
                    f"model identity layer of source person {model_index + 1} "
                    "(identity-bearing face, hair, skin and body appearance). Preserve the source person's exact pose, action, gesture, "
                    "facial expression, gaze, mouth state, head angle, body orientation, wardrobe, hand state and interaction. "
                    "Leave every other person in the frame unchanged."
                )
                reference_index += 1
        if _present(context, "new_product_image"):
            for product_index in range(min(2, len(_slot_sha256s(context, "new_product_image")))):
                target_roles.append(
                    f"Reference image {reference_index} is new_product_image[{product_index}] target truth: replace only the authorized "
                    "product/App-product layer at the matching source location. Preserve exact source scale, orientation, open/closed state, "
                    "hand contact, occlusion, action state and screen position."
                )
                reference_index += 1
        if not target_roles:
            target_roles.append("No target visual layer is populated; preserve every source layer unchanged.")
        try:
            surface_locks = split_visible_text_locks_by_render_route(visible_text_locks)["generation_surface"]
        except VisibleTextContractError as exc:
            raise _replication_error("CONTRACT_INVALID", "visible text carrier routing is invalid") from exc
        surface_text = " ".join(
            (
                f"In Cuts {', '.join(lock['cut_ids'])}, remove the source text from physical carrier "
                f"{json.dumps(lock['placement']['carrier_id'], ensure_ascii=False)} and reconstruct the carrier surface, "
                f"{lock['placement']['surface_relation']}; it {lock['placement']['motion_behavior']}."
                if lock["disposition"] == "remove"
                else f"In Cuts {', '.join(lock['cut_ids'])}, render the exact approved text {json.dumps(lock['approved_text'], ensure_ascii=False)} "
                f"on physical carrier {json.dumps(lock['placement']['carrier_id'], ensure_ascii=False)}, "
                f"{lock['placement']['surface_relation']}; it {lock['placement']['motion_behavior']}. "
                "The glyphs are part of the carrier surface, with the same perspective, occlusion, lighting, texture and deformation."
            )
            for lock in surface_locks
        )
        prompt = (
            "Create exactly one ordered-panel replacement control keyframe sheet. "
            f"It contains exactly {len(cut_ids)} panels in this order: {', '.join(cut_ids)}. "
            "Reference image 1 is the complete source Cut contact sheet and is the sole authority for panel layout and all non-replacement pixels. "
            "Transform that one complete source sheet into one complete replacement-control sheet in this single image-to-image operation. "
            "Do not split the sheet, generate separate Cut images, redesign panels, restage the performance, or reinterpret the scene. "
            + " ".join(target_roles)
            + (" " + surface_text if surface_text else "")
            + " Every non-authorized source property must remain unchanged: panel count and order, background, environment topology, image quality, "
            "lighting, color treatment, composition, camera angle, camera distance, crop, subject position and scale, pose, action, gesture, "
            "facial expression, gaze, mouth state, head angle, body orientation, hands, product interaction, props, occlusion and continuity. "
            "Do not invent scenery, change framing, or add people. Authorized product or App-product replacement includes its exact target markings and interface details: "
            "replace the source product's old markings only at that authorized target location. Every approved scene-surface text instruction above is the sole authority for its physical text. "
            "All existing physical text, printed graphics, garment prints, logos, signs and shop boards not inside an authorized replacement layer or an approved scene-surface text lock "
            "are source detail: reproduce them exactly in place, with the same glyphs, position, perspective, texture, lighting and occlusion. "
            "Do not recreate screen-space subtitle, caption, CTA, lower-third, sticker or wordmark glyphs; preserve their underlying scene sharp and leave approved overlay text to its deterministic render layer. "
            "Never blur, pixelate, mosaic, smudge, gray out, black out, censor, redact, soften or otherwise obscure any region, and never leave any area blank. "
            "This is an internal control sheet; no brand-safety, moderation or anonymization treatment applies. Full sharp detail is required across the entire sheet."
        )
        try:
            generated = self._image_client.run_image2(
                prompt=prompt,
                reference_images=[source_path, *target_references],
                aspect_ratio=_sheet_aspect_ratio(source_path),
                resolution="2k",
                quality="medium",
            )
        except Exception as exc:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "RunningHub Image2 replacement control generation failed", retryable=True, category="provider") from exc
        image_bytes = generated.get("image_bytes") if isinstance(generated, Mapping) else None
        self._png_dimensions(image_bytes if isinstance(image_bytes, bytes) else b"")
        digest = hashlib.sha256(image_bytes).hexdigest()
        source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        target_digests = {
            hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in target_references
        }
        if digest == source_digest or digest in target_digests:
            raise _replication_error(
                "CONTROL_SHEET_QC_FAILED",
                "replacement control output is not a distinct source-anchored replacement sheet",
                category="quality",
            )
        try:
            from PIL import Image, ImageChops, ImageStat

            with Image.open(source_path) as source_image, Image.open(io.BytesIO(image_bytes)) as control_image:
                source_ratio = source_image.width / max(1, source_image.height)
                control_ratio = control_image.width / max(1, control_image.height)
                if abs(source_ratio - control_ratio) / max(source_ratio, 1e-6) > 0.03:
                    raise _replication_error(
                        "CONTROL_SHEET_QC_FAILED",
                        "replacement control output changed the complete-sheet geometry",
                        category="quality",
                    )
                source_small = source_image.convert("RGB").resize((64, 64))
                control_small = control_image.convert("RGB").resize((64, 64))
                mean_difference = sum(ImageStat.Stat(ImageChops.difference(source_small, control_small)).mean) / (3 * 255)
                if target_references and mean_difference < 0.002:
                    raise _replication_error(
                        "CONTROL_SHEET_QC_FAILED",
                        "replacement control output did not visibly apply the authorized replacement",
                        category="quality",
                    )
                if mean_difference > 0.70:
                    raise _replication_error(
                        "CONTROL_SHEET_QC_FAILED",
                        "replacement control output changed too much of the source composition",
                        category="quality",
                    )
                if _sharpness_ratio(source_image, control_image) < 0.60:
                    raise _replication_error(
                        "CONTROL_SHEET_QC_FAILED",
                        "replacement control output blurred or censored source scene detail",
                        category="quality",
                    )
        except ReplicationError:
            raise
        except Exception as exc:
            raise _replication_error(
                "CONTROL_SHEET_QC_FAILED",
                "replacement control output could not pass complete-sheet visual validation",
                category="quality",
            ) from exc
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
            control_generation={
                "provider": "runninghub_image2",
                "mode": "single_sheet_image_to_image",
                "source_sheet_count": 1,
                "output_sheet_count": 1,
                "image2_call_count": 1,
            },
        )
        receipt = contract.validate_control_keyframe_manifest(source_dynamics, manifest)
        published = context.publish_bytes(
            kind="replacement_control_keyframe_sheet", data=image_bytes, content_type="image/png", expected_sha256=digest,
            metadata={
                "source_keyframe_sheet_sha256": str(source_sheet["source_keyframe_sheet_sha256"]),
                "control_receipt_sha256": _sha(receipt),
                "generator_kind": "runninghub_image2",
                "generation_mode": "single_sheet_image_to_image",
                "image2_call_count": 1,
            },
        )
        published_receipt = _publish_json(context, kind="replacement_control_keyframe_receipt", value=receipt)
        return {"path": destination, "sha256": digest, "receipt": receipt, "published_artifacts": [published, published_receipt]}

    @staticmethod
    def _partition_storyboard_cuts(cut_ids: Sequence[str]) -> tuple[tuple[str, ...], ...]:
        ordered = tuple(str(value) for value in cut_ids if str(value))
        limit = _MAX_CUTS_PER_PAGE * _MAX_BOARD_PAGES
        if not ordered or len(ordered) > limit or len(set(ordered)) != len(ordered):
            raise _replication_error("SEGMENT_PLAN_INVALID", f"storyboard supports one to {limit} unique Cuts")
        if len(ordered) <= _MAX_CUTS_PER_PAGE:
            return (ordered,)
        first_size = math.ceil(len(ordered) / 2)
        pages = (ordered[:first_size], ordered[first_size:])
        if any(not page or len(page) > _MAX_CUTS_PER_PAGE for page in pages):
            raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard pagination exceeds six Cuts per page")
        return pages

    @staticmethod
    def _segment_prompt(
        *,
        segment: Mapping[str, Any],
        cuts: Mapping[str, Mapping[str, Any]],
        visible_text_locks: Sequence[Mapping[str, Any]],
        page_cut_ids: Sequence[str] | None = None,
        board_page_index: int = 1,
        board_page_count: int = 1,
    ) -> str:
        cut_ids = segment.get("cut_ids")
        page_cut_ids = tuple(page_cut_ids or (cut_ids if isinstance(cut_ids, list) else ()))
        selected = [cuts[str(cut_id)] for cut_id in page_cut_ids if str(cut_id) in cuts]
        if not selected:
            raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard segment has no approved script Cuts")
        if len(selected) > _MAX_CUTS_PER_PAGE or board_page_count not in {1, 2} or not 1 <= board_page_index <= board_page_count:
            raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard page contract is invalid")
        beats = []
        shot_cards: list[str] = []
        exact_labels: list[str] = []
        for cut in selected:
            cut_id = str(cut.get("cut_id") or "CXX")
            start_ms = int(cut.get("start_ms") or 0)
            end_ms = int(cut.get("end_ms") or 0)
            scene = str(cut.get("scene") or "approved source scene")
            action = str(cut.get("action") or "approved action")
            camera = str(cut.get("camera") or "approved source camera")
            beats.append(
                "scene=" + scene + "; action=" + action + "; camera=" + camera
            )
            shot_cards.append(
                f"Cut {cut_id}\n"
                f"画面：{scene}; {action}; {camera}\n"
                f"叙事：{str(cut.get('transition') or '')} → {str(cut.get('end_state') or '')}\n"
                f"标签：{cut_id}  {start_ms}-{end_ms}  KEEP SOURCE PERFORMANCE"
            )
            exact_labels.append(f"{cut_id}; {start_ms}-{end_ms}; KEEP PERFORMANCE")
        try:
            routed_text = split_visible_text_locks_by_render_route(visible_text_locks)
        except VisibleTextContractError as exc:
            raise _replication_error("CONTRACT_INVALID", "visible text carrier routing is invalid") from exc
        for lock in routed_text["generation_surface"]:
            exact_labels.append(
                f"SCENE-SURFACE TEXT: exact {json.dumps(lock['approved_text'], ensure_ascii=False)} on "
                f"{lock['placement']['carrier_id']}, {lock['placement']['surface_relation']}; "
                f"{lock['placement']['motion_behavior']}"
            )
        for lock in routed_text["deterministic_overlay"]:
            exact_labels.append(f"POST OVERLAY TEXT: {lock['approved_text']}")
        assert_public_content_safe(exact_labels)
        template_path = (
            Path(__file__).resolve().parents[1]
            / "bundled-skills/seedance-storyboard-replication/references/daohuo_storyboard_prompt.md"
        )
        try:
            template = template_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _replication_error(
                "CAPABILITY_UNAVAILABLE",
                "packaged director-storyboard prompt template is unavailable",
                retryable=True,
                category="capability",
            ) from exc
        prompt_start = template.find("Use case: infographic-diagram")
        prompt_end = template.find("```", prompt_start)
        if prompt_start < 0 or prompt_end < 0:
            raise _replication_error(
                "CONTRACT_INVALID",
                "packaged director-storyboard template is missing its Image2 prompt block",
            )
        # The Markdown file contains operating guidance plus exactly one
        # provider-ready fenced prompt. Only that fixed skeleton is admissible
        # to Image2; documentation prose must never influence board layout.
        template = template[prompt_start:prompt_end].strip()
        values = {
            "CONTENT_TYPE": "source-fidelity social video replication",
            "PRODUCT_OR_SERVICE_TYPE": "none",
            "VIDEO_TITLE": "Source Fidelity Director Board",
            "DURATION": f"{int(segment.get('duration_ms') or 0)}ms",
            "SEGMENT_INDEX": str(segment.get("segment_id") or "S01"),
            "SEGMENT_DURATION": f"{int(segment.get('duration_ms') or 0)}ms",
            "GLOBAL_CUT_RANGE": ", ".join(str(cut.get("cut_id") or "") for cut in selected),
            "SHOT_COUNT": str(len(selected)),
            "BOARD_PAGE_COUNT": str(board_page_count),
            "BOARD_PAGE_INDEX": str(board_page_index),
            "PAGE_CUT_RANGE": ", ".join(str(cut.get("cut_id") or "") for cut in selected),
            "TARGET_VIDEO_RATIO": "9:16",
            "CHARACTER_REFERENCE_ROLE": "none; authorized character identity is already resolved inside Reference image 1.",
            "PRODUCT_REFERENCE_ROLE": "none",
            "REFERENCE_VIDEO_ROLE": "Reference image 1 is the replacement-control sheet and is the non-negotiable visual base for every Cut card.",
            "VISUAL_STYLE": "source-faithful realistic live-action photography; preserve source camera, lighting, composition and color treatment",
            "COLOR_PALETTE": "derive only from the replacement-control sheet",
            "ENVIRONMENT_PLAN": "derive only from the replacement-control sheet; do not redesign the source environment",
            "CONTINUITY_MANIFEST": "Preserve every approved Cut's identity/product layer, source environment, camera, lighting, direction, props and action handoff.",
            "INCOMING_CONTINUITY": "first frame matches the replacement-control sheet",
            "OUTGOING_CONTINUITY": "last frame preserves the approved source action endpoint",
            "ADJACENT_BOARD_ROLE": "none",
            "SHOT_CARDS": "\n\n".join(shot_cards),
            "BOARD_GRID": (
                f"Arrange exactly {len(selected)} Cut cards in a "
                f"{math.ceil(len(selected) / (3 if len(selected) > 4 else len(selected)))}-row by "
                f"{3 if len(selected) > 4 else len(selected)}-column grid, in strict left-to-right, "
                "top-to-bottom global Cut order. Every card uses identical size. Each Cut scene image "
                "uses proportional fit-contain scaling and preserves its portrait source aspect ratio. "
                "Empty margins are acceptable; cropping to fill, horizontal compression, vertical stretching "
                "and body-proportion change are forbidden."
            ),
            "BOARD_FOCUS": (
                "This board communicates the source story flow: scene progression, plot order, character "
                "movement path and edit rhythm across Cuts. Draw connecting flow arrows between adjacent "
                "cards indicating action handoff and camera continuity. Do not display any asset showcase, "
                "reference gallery or identity comparison."
            ),
            "EXACT_LABELS": " | ".join(exact_labels) if exact_labels else "NO APPROVED VISIBLE TEXT",
            "AUDIO_NOTE": "Follow approved source audio and action/ambient sound contract; do not invent music.",
            "TRADEMARK_SAFETY_NOTE": "Do not copy source branding or invent brand marks; use only authorized target evidence.",
            "TASK_NEGATIVES": "changed pose, changed expression, changed camera, changed composition, changed background, changed lighting, extra Cut cards, extra people, invented props, asset showcase panel, character sheet, product sheet, reference gallery, split-screen comparison, any model name, provider name, workflow name, node ID, implementation note or internal production terminology rendered as visible text",
            "CUT_NUMBER": str(selected[0].get("cut_id") or "C01"),
            "COMPLETE_VISUAL_DESCRIPTION_FOR_IMAGE_GENERATION": "Use the corresponding approved Storyboard cards entry.",
            "NN": str(selected[0].get("cut_id") or "C01"),
            "START": str(selected[0].get("start_ms") or 0),
            "END": str(selected[0].get("end_ms") or 0),
            "KEY_ACTION_TAG": "KEEP ACTION",
            "IDENTITY_OR_PRODUCT_LOCK_TAG": "KEEP TARGET IDENTITY",
        }
        prompt = re.sub(
            r"\{\{([A-Z_]+)\}\}",
            lambda match: values.get(match.group(1), match.group(0)),
            template,
        )
        # The packaged template documents its placeholder convention with a
        # literal ``{{...}}`` example. It is not a dynamic field and must not
        # leak as braces into the provider request.
        prompt = prompt.replace("{{...}}", "placeholders")
        if re.search(r"\{\{[A-Z_]+\}\}", prompt):
            raise _replication_error(
                "CONTRACT_INVALID",
                "director-storyboard prompt template contains unresolved placeholders",
            )
        return prompt

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        if self._is_v2(context):
            return self._run_v2(context=context, input_artifacts=input_artifacts)
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
        ordered_cut_ids: list[str] = []
        segment_by_cut: dict[str, str] = {}
        for raw_segment in segments:
            segment = _mapping(raw_segment, "storyboard segment")
            segment_id = str(segment.get("segment_id") or "").strip()
            cut_ids = segment.get("cut_ids")
            if not segment_id or not isinstance(cut_ids, list) or not cut_ids:
                raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard segment is invalid")
            for raw_cut_id in cut_ids:
                cut_id = str(raw_cut_id)
                if cut_id not in ordered_cut_ids:
                    ordered_cut_ids.append(cut_id)
                segment_by_cut[cut_id] = segment_id
        storyboard_pages = self._partition_storyboard_cuts(ordered_cut_ids)
        published_images: list[dict[str, Any]] = []
        cut_images: list[StoryboardCutRef] = []
        upstream_artifacts: list[dict[str, Any]] = []
        with self._target_reference_images(context) as target_references:
            # Every storyboard-backed generated region uses the same visual
            # provenance chain:
            # source Cut frames -> replacement-control sheet -> director board.
            # An empty target list means "preserve source layers", not "skip
            # the control evidence".
            source_sheet = self._source_keyframe_sheet(context, source_dynamics)
            control_sheet = self._replacement_control_sheet(
                context=context,
                source_dynamics=source_dynamics,
                source_sheet=source_sheet,
                target_references=target_references,
                visible_text_locks=approved_visible_text_locks,
            )
            # The control sheet already contains the authorized target
            # replacement. Sending the raw/normalized target gallery again
            # causes Image2 to render an asset showcase and weakens the
            # source-story focus of the director board.
            references = [Path(control_sheet["path"])]
            upstream_artifacts.extend(list(source_sheet.get("published_artifacts") or []))
            upstream_artifacts.extend(list(control_sheet.get("published_artifacts") or []))

            def generate_board(spec: tuple[int, tuple[str, ...]]) -> tuple[int, dict[str, Any], list[Any], Mapping[str, Any]]:
                page_index, page_cut_ids = spec
                selected_cuts = [script_by_id[cut_id] for cut_id in page_cut_ids]
                page_segment = {
                    "segment_id": f"BOARD-{page_index:02d}",
                    "cut_ids": list(page_cut_ids),
                    "start_ms": min(int(cut.get("start_ms") or 0) for cut in selected_cuts),
                    "end_ms": max(int(cut.get("end_ms") or 0) for cut in selected_cuts),
                }
                page_segment["duration_ms"] = page_segment["end_ms"] - page_segment["start_ms"]
                try:
                    segment_text_locks = self._segment_visible_text_locks(
                        approved_visible_text_locks, segment=page_segment
                    )
                    generated = self._image_client.run_image2(
                        prompt=self._segment_prompt(
                            segment=page_segment,
                            cuts=script_by_id,
                            visible_text_locks=segment_text_locks,
                            page_cut_ids=page_cut_ids,
                            board_page_index=page_index,
                            board_page_count=len(storyboard_pages),
                        ),
                        reference_images=references,
                        aspect_ratio=_sheet_aspect_ratio(Path(control_sheet["path"])),
                        resolution="2k",
                        quality="medium",
                    )
                except ReplicationError:
                    raise
                except Exception as exc:
                    raise _replication_error("CAPABILITY_UNAVAILABLE", "director storyboard generation failed", retryable=True, category="provider") from exc
                return page_index, page_segment, list(segment_text_locks), generated

            generated_boards = _run_ordered_parallel(
                list(enumerate(storyboard_pages, start=1)),
                generate_board,
                max_workers=2,
            )
            for page_index, segment, segment_text_locks, generated in generated_boards:
                cut_ids = list(segment["cut_ids"])
                segment_ids = list(dict.fromkeys(segment_by_cut[cut_id] for cut_id in cut_ids))
                image_bytes = generated.get("image_bytes") if isinstance(generated, Mapping) else None
                routed_segment_text = split_visible_text_locks_by_render_route(segment_text_locks)
                image_bytes = self._render_visible_text_layer(
                    image_bytes if isinstance(image_bytes, bytes) else b"",
                    routed_segment_text["deterministic_overlay"],
                )
                width, height = self._png_dimensions(image_bytes)
                digest = hashlib.sha256(image_bytes).hexdigest()
                logical_name = (
                    f"storyboards/segment_01_v{manifest.revision}.png"
                    if len(storyboard_pages) == 1
                    else f"storyboards/segment_01_v{manifest.revision}_page_{page_index:02d}.png"
                )
                metadata = {
                    "segment_id": segment_ids[0],
                    "segment_ids": segment_ids,
                    "storyboard_revision": manifest.revision,
                    "logical_name": logical_name,
                    "storyboard_page": page_index,
                    "storyboard_page_count": len(storyboard_pages),
                    "page_cut_ids": cut_ids,
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
    """Freeze the approved script and formal source-Cut execution plan."""

    @staticmethod
    def _frame_midpoint_boundary_ms(active_end_ms: int) -> dict[str, int | str]:
        """Return the nearest legal midpoint on the fixed 24 fps split grid."""

        if (
            isinstance(active_end_ms, bool)
            or not isinstance(active_end_ms, int)
            or not 15_000 < active_end_ms <= 30_000
        ):
            raise _replication_error(
                "SEGMENT_PLAN_INVALID",
                "frame-midpoint fallback requires an editable duration above 15 and at most 30 seconds",
            )
        midpoint_us = active_end_ms * 1000 // 2
        lower_frame = midpoint_us * 24 // 1_000_000
        candidate_frames = {lower_frame, lower_frame + 1}
        legal: list[tuple[int, int]] = []
        for frame_index in candidate_frames:
            boundary_us = frame_index * 1_000_000 // 24
            first_us = boundary_us
            second_us = active_end_ms * 1000 - boundary_us
            if 0 < first_us <= 15_000_000 and 0 < second_us <= 15_000_000:
                legal.append((frame_index, boundary_us))
        if not legal:
            raise _replication_error(
                "SEGMENT_PLAN_INVALID",
                "fixed 24 fps midpoint grid cannot form two legal Provider segments",
            )
        frame_index, boundary_us = min(
            legal,
            key=lambda item: (abs(item[1] - midpoint_us), item[1]),
        )
        return {
            "boundary_mode": "frame_midpoint_fallback",
            "grid_fps_num": 24,
            "grid_fps_den": 1,
            "boundary_frame_index": frame_index,
            "boundary_time_us": boundary_us,
            "boundary_ms": boundary_us // 1000,
        }

    @staticmethod
    def _is_v2(context: Any) -> bool:
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
        return isinstance(extensions, Mapping) and extensions.get("edit_contract") == "video-edit-v2"

    @staticmethod
    def _approved_v2_inputs(context: Any, script_sha: str) -> tuple[Mapping[str, Any], dict[str, Any]]:
        snapshot = getattr(context, "snapshot", None)
        store = getattr(context, "job_store", None)
        script_revision = getattr(snapshot, "current_script_revision", None)
        get_script = getattr(store, "get_script_approval", None)
        if (
            isinstance(script_revision, bool)
            or not isinstance(script_revision, int)
            or script_revision < 1
            or not callable(get_script)
        ):
            raise _replication_error("APPROVAL_REQUIRED", "v2 segment planning requires the current script approval checkpoint")
        approval = get_script(context.job_id, script_revision)
        if not isinstance(approval, Mapping) or approval.get("contract") != "approved-script-lines/v2":
            raise _replication_error("APPROVAL_REQUIRED", "v2 segment planning requires approved-script-lines/v2")
        if (
            approval.get("revision") != script_revision
            or str(approval.get("script_sha256") or "").lower() != script_sha
        ):
            raise _replication_error("APPROVAL_STALE", "approved script revision or SHA is stale")
        try:
            approved_edit_script = canonicalize_approved_edit_script(approval.get("approved_edit_script"))
        except ReplicationError as exc:
            raise _replication_error(
                "APPROVED_SCRIPT_FIELDS_REQUIRED",
                "v2 segment planning requires canonical approved_edit_script fields",
            ) from exc
        return approval, approved_edit_script

    @staticmethod
    def _source_cut_authority(context: Any, dynamics: Mapping[str, Any]) -> str:
        output = _stage_output(context, "analyze_dynamics")
        published = output.get("published_artifacts")
        if not isinstance(published, list):
            raise _replication_error(
                "SOURCE_CUT_AUTHORITY_REQUIRED",
                "v2 segment planning requires the formal analyze_source Cut artifact",
                category="artifact",
            )
        candidates = [
            item for item in published
            if isinstance(item, Mapping) and item.get("kind") == "source_dynamics_analysis"
        ]
        if len(candidates) != 1:
            raise _replication_error(
                "SOURCE_CUT_AUTHORITY_REQUIRED",
                "v2 segment planning requires exactly one formal source Cut artifact",
                category="artifact",
            )
        descriptor = candidates[0]
        artifact_id = str(descriptor.get("artifact_id") or "")
        digest = str(descriptor.get("sha256") or "").lower()
        if not artifact_id or _SHA256.fullmatch(digest) is None:
            raise _replication_error(
                "SOURCE_CUT_AUTHORITY_REQUIRED",
                "formal source Cut artifact descriptor is invalid",
                category="artifact",
            )
        exact = [
            item for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping)
            and item.get("kind") == "source_dynamics_analysis"
            and str(item.get("artifact_id") or "") == artifact_id
            and str(item.get("sha256") or "").lower() == digest
        ]
        if len(exact) != 1:
            raise _replication_error(
                "SOURCE_CUT_AUTHORITY_REQUIRED",
                "formal source Cut artifact is unavailable from the analyze_source stage",
                category="artifact",
            )
        artifact = _read_json_artifact(context, kind="source_dynamics_analysis", sha256=digest)
        artifact_dynamics = _mapping(artifact.get("source_dynamics_analysis"), "formal source dynamics analysis")
        raw_artifact_cuts = artifact_dynamics.get("source_cuts")
        raw_stage_cuts = dynamics.get("source_cuts")
        if not isinstance(raw_artifact_cuts, list) or not isinstance(raw_stage_cuts, list):
            raise _replication_error("SOURCE_CUT_AUTHORITY_REQUIRED", "formal source Cut artifact has no Cut evidence", category="artifact")

        def timing(rows: Sequence[Any]) -> list[tuple[str, int, int]]:
            result: list[tuple[str, int, int]] = []
            for raw in rows:
                if not isinstance(raw, Mapping):
                    raise _replication_error("SOURCE_CUT_AUTHORITY_REQUIRED", "formal source Cut record is invalid", category="artifact")
                cut_id = str(raw.get("cut_id") or "").strip()
                try:
                    start_us = int(raw["start_us"])
                    end_us = int(raw["end_us"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise _replication_error("SOURCE_CUT_AUTHORITY_REQUIRED", "formal source Cut timing is invalid", category="artifact") from exc
                if not cut_id or end_us <= start_us:
                    raise _replication_error("SOURCE_CUT_AUTHORITY_REQUIRED", "formal source Cut timing is invalid", category="artifact")
                result.append((cut_id, start_us, end_us))
            return result

        if timing(raw_artifact_cuts) != timing(raw_stage_cuts):
            raise _replication_error("SOURCE_CUT_AUTHORITY_REQUIRED", "formal source Cut artifact differs from analyze_source output", category="artifact")
        return digest

    @staticmethod
    def _asset_binding_authority(context: Any, approved_edit_script: Mapping[str, Any]) -> dict[str, Any]:
        bindings = approved_edit_script["asset_bindings"]
        authority = {
            "approved_asset_bindings_sha256": str(approved_edit_script["asset_bindings_sha256"]),
            "asset_board_manifest_sha256": None,
        }
        if not bindings:
            return authority
        manifest = _resolve_v2_asset_board_manifest(context)
        authority["asset_board_manifest_sha256"] = str(manifest["sha256"])
        return authority

    @staticmethod
    def _cut_string_list(raw: Mapping[str, Any], field: str) -> list[str]:
        value = raw.get(field)
        if value is None:
            return []
        if not isinstance(value, list):
            raise _replication_error("CONTRACT_INVALID", f"source Cut {field} is invalid")
        result = [str(item).strip() for item in value]
        if any(not item for item in result) or len(set(result)) != len(result):
            raise _replication_error("CONTRACT_INVALID", f"source Cut {field} is invalid")
        return result

    @classmethod
    def _cut_execution_record(
        cls,
        raw: Mapping[str, Any],
        *,
        cut_id: str,
        segment_id: str,
        order: int,
        start_ms: int,
        end_ms: int,
        change_rows: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        def source_text(*fields: str, fallback: str) -> str:
            for field in fields:
                value = raw.get(field)
                if value is None:
                    continue
                if not isinstance(value, str) or not value.strip():
                    raise _replication_error("CONTRACT_INVALID", f"source Cut {field} is invalid")
                return value.strip()
            return fallback

        def window_ids(kind: str) -> list[str]:
            return [
                str(row["change_id"])
                for row in change_rows
                if str(row.get("kind") or "").casefold() == kind
                and int(row["start_ms"]) < end_ms
                and int(row["end_ms"]) > start_ms
            ]

        replacement_windows = [
            {
                "change_id": str(row["change_id"]),
                "asset_tag": str(row["asset_tag"]),
                "instruction": str(row["instruction"]),
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
            }
            for row in change_rows
            if str(row.get("kind") or "").casefold() == "replacement"
            and int(row["start_ms"]) < end_ms
            and int(row["end_ms"]) > start_ms
        ]

        return {
            "cut_id": cut_id,
            "segment_id": segment_id,
            "order": order,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "tags": {
                "person": cls._cut_string_list(raw, "person_tags"),
                "product": cls._cut_string_list(raw, "product_tags"),
                "ui": cls._cut_string_list(raw, "ui_tags"),
                "scene": cls._cut_string_list(raw, "scene_tags"),
            },
            "action_purpose": source_text("action_purpose", "action", fallback="preserve source action"),
            "product_display_steps": cls._cut_string_list(raw, "product_display_steps"),
            "app_operation_steps": cls._cut_string_list(raw, "app_operation_steps"),
            "replacement_windows": replacement_windows,
            "dialogue_windows": [*window_ids("dialogue"), *window_ids("language")],
            "text_windows": window_ids("text"),
            "start_state": source_text("start_state", "action", fallback="preserve source start state"),
            "end_state": source_text("end_state", "action", fallback="preserve source end state"),
        }

    @staticmethod
    def _approved_windows(
        approval: Mapping[str, Any], change_rows: Sequence[Mapping[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        performance: list[dict[str, Any]] = []
        for row in change_rows:
            kind = str(row.get("kind") or "").casefold()
            if kind not in {"dialogue", "language"}:
                continue
            performance.append({
                "window_id": str(row["change_id"]),
                "kind": kind,
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
            })
        line_contracts = approval.get("line_contracts", [])
        if not isinstance(line_contracts, list):
            raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved script line_contracts are invalid")
        seen_performance = {str(item["window_id"]) for item in performance}
        for raw in line_contracts:
            if not isinstance(raw, Mapping):
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved script line contract is invalid")
            line_id = str(raw.get("line_id") or "").strip()
            kind = str(raw.get("kind") or "dialogue").strip().casefold()
            timing = raw.get("time")
            if not line_id or line_id in seen_performance or not isinstance(timing, Mapping):
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved script line contract is invalid")
            try:
                start_ms = int(timing["start_ms"])
                end_ms = int(timing["end_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved script line timing is invalid") from exc
            if kind not in {"dialogue", "monologue", "song", "lyric"} or start_ms < 0 or end_ms <= start_ms:
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved script line contract is invalid")
            performance.append({
                "window_id": line_id,
                "kind": kind,
                "start_ms": start_ms,
                "end_ms": end_ms,
            })
            seen_performance.add(line_id)

        text: list[dict[str, Any]] = []
        seen_text: set[str] = set()
        for row in change_rows:
            if str(row.get("kind") or "").casefold() != "text":
                continue
            window_id = str(row["change_id"])
            route = "generation_surface" if str(row.get("layer") or "").casefold() == "physical" else "deterministic_overlay"
            text.append({
                "window_id": window_id,
                "kind": str(row.get("text_target") or "approved_text"),
                "cut_ids": [],
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
                "render_route": route,
            })
            seen_text.add(window_id)
        visible_locks = approval.get("visible_text_locks", [])
        if not isinstance(visible_locks, list):
            raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved visible text locks are invalid")
        for raw in visible_locks:
            if not isinstance(raw, Mapping):
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved visible text lock is invalid")
            text_id = str(raw.get("text_id") or "").strip()
            cut_ids = raw.get("cut_ids")
            kind = str(raw.get("kind") or "").strip()
            if not text_id or text_id in seen_text or not kind or not isinstance(cut_ids, list):
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved visible text lock is invalid")
            normalized_cut_ids = [str(item).strip() for item in cut_ids]
            if any(not item for item in normalized_cut_ids) or len(set(normalized_cut_ids)) != len(normalized_cut_ids):
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved visible text lock Cut coverage is invalid")
            try:
                start_ms = int(raw["start_ms"])
                end_ms = int(raw["end_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved visible text timing is invalid") from exc
            if start_ms < 0 or end_ms <= start_ms:
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved visible text timing is invalid")
            explicit_route = raw.get("render_route")
            if explicit_route is None:
                route = "deterministic_ui" if kind == "ui_text" else (
                    "generation_surface" if kind == "scene_surface_text" else "deterministic_overlay"
                )
            else:
                route = str(explicit_route).strip()
            if route not in {"generation_surface", "deterministic_overlay", "deterministic_ui"}:
                raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved visible text route is invalid")
            text.append({
                "window_id": text_id,
                "kind": kind,
                "cut_ids": normalized_cut_ids,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "render_route": route,
            })
            seen_text.add(text_id)
        performance.sort(key=lambda item: (int(item["start_ms"]), int(item["end_ms"]), str(item["window_id"])))
        text.sort(key=lambda item: (int(item["start_ms"]), int(item["end_ms"]), str(item["window_id"])))
        return performance, text

    @staticmethod
    def _post_routes(
        context: Any,
        approval: Mapping[str, Any],
        text_windows: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        routes = manifest.get("routes") if isinstance(manifest, Mapping) else None
        routes = routes if isinstance(routes, Mapping) else {}
        audio_plan = approval.get("audio_plan")
        if audio_plan is not None and not isinstance(audio_plan, Mapping):
            raise _replication_error("APPROVED_SCRIPT_FIELDS_REQUIRED", "approved script audio_plan is invalid")
        return {
            "ui_route": str(routes.get("ui") or "preserve_source_ui"),
            "tail_route": str(routes.get("tail") or "remove_source_tail_card"),
            "text_routes": {
                route: [
                    str(item["window_id"])
                    for item in text_windows
                    if item.get("render_route") == route
                ]
                for route in ("generation_surface", "deterministic_overlay", "deterministic_ui")
            },
            "audio_plan": dict(audio_plan or {}),
        }

    @staticmethod
    def _run_v2(context: Any) -> Mapping[str, Any]:
        snapshot = getattr(context, "snapshot", None)
        script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
        if _SHA256.fullmatch(script_sha) is None:
            raise _replication_error("APPROVAL_REQUIRED", "v2 segment planning requires approved script SHA")
        _read_json_artifact(context, kind="script_revision", sha256=script_sha)
        approval, approved_edit_script = SegmentPlanStage._approved_v2_inputs(context, script_sha)
        change_rows = [dict(row) for row in approved_edit_script["change_rows"]]

        probe = _mapping(_stage_output(context, "probe_source").get("probe"), "probe evidence")
        duration_us = probe.get("duration_us")
        if isinstance(duration_us, bool) or not isinstance(duration_us, int) or duration_us <= 0:
            raise _replication_error("CONTRACT_INVALID", "probe evidence has no source duration")
        source_duration_ms = (duration_us + 999) // 1000
        dynamics = _mapping(_stage_output(context, "analyze_dynamics").get("source_dynamics_analysis"), "source dynamics analysis")
        raw_cuts = dynamics.get("source_cuts")
        if not isinstance(raw_cuts, list) or not raw_cuts:
            raise _replication_error("CONTRACT_INVALID", "v2 source dynamics has no Cut evidence")
        source_dynamics_sha = SegmentPlanStage._source_cut_authority(context, dynamics)
        normalized: list[dict[str, Any]] = []
        previous_end = 0
        for index, raw in enumerate(raw_cuts, start=1):
            if not isinstance(raw, Mapping):
                raise _replication_error("CONTRACT_INVALID", f"source Cut {index} is invalid")
            cut_id = str(raw.get("cut_id") or "").strip()
            start_us, end_us = raw.get("start_us"), raw.get("end_us")
            if (
                not cut_id
                or isinstance(start_us, bool)
                or not isinstance(start_us, int)
                or isinstance(end_us, bool)
                or not isinstance(end_us, int)
                or start_us < 0
                or end_us <= start_us
                or (index == 1 and start_us != 0)
                or (index > 1 and start_us != previous_end)
            ):
                raise _replication_error("CONTRACT_INVALID", "source Cut timing is not contiguous")
            start_ms = start_us // 1000
            end_ms = (end_us + 999) // 1000
            normalized.append({
                "raw": dict(raw),
                "cut_id": cut_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "route": str(raw.get("route") or "source").casefold(),
                "terminal_tail": bool(raw.get("terminal_tail")),
            })
            previous_end = end_us
        if previous_end > duration_us + 999:
            raise _replication_error("CONTRACT_INVALID", "source Cut evidence exceeds probed duration")
        tail_index = next(
            (index for index, cut in enumerate(normalized) if cut["terminal_tail"] or cut["route"] in {"tail", "source_tail", "end_card"}),
            None,
        )
        active_cuts = normalized[:tail_index] if tail_index is not None else normalized
        if not active_cuts:
            raise _replication_error("SEGMENT_PLAN_INVALID", "v2 source has no editable content before the detected tail Cut")
        active_end_ms = active_cuts[-1]["end_ms"]
        if active_end_ms > 30_000:
            raise _replication_error("SEGMENT_PLAN_INVALID", "v2 editable source exceeds 30 seconds after tail exclusion")
        dialogue_windows = [
            dict(row) for row in change_rows
            if str(row.get("kind") or "").casefold() in {"dialogue", "language", "monologue", "lyric"}
        ]
        performance_windows, text_windows = SegmentPlanStage._approved_windows(approval, change_rows)
        if any(
            isinstance(row.get("start_ms"), bool)
            or not isinstance(row.get("start_ms"), int)
            or isinstance(row.get("end_ms"), bool)
            or not isinstance(row.get("end_ms"), int)
            or row["start_ms"] < 0
            or row["end_ms"] <= row["start_ms"]
            or row["end_ms"] > active_end_ms
            for row in performance_windows
        ):
            raise _replication_error("CONTRACT_INVALID", "approved performance windows are invalid")
        boundary_receipt: dict[str, int | str] | None = None
        if active_end_ms <= 15_000:
            boundaries: list[int] = []
            boundary_mode = "single_segment"
        else:
            boundaries = [int(cut["end_ms"]) for cut in active_cuts[:-1]]
            minimum = active_end_ms - 15_000
            maximum = 15_000
            boundaries = [
                boundary for boundary in boundaries
                if minimum <= boundary <= maximum
                and all(not (int(row["start_ms"]) < boundary < int(row["end_ms"])) for row in performance_windows)
            ]
            boundary_mode = "natural_cut"
            if not boundaries:
                boundary_receipt = SegmentPlanStage._frame_midpoint_boundary_ms(active_end_ms)
                boundaries = [int(boundary_receipt["boundary_ms"])]
                boundary_mode = "frame_midpoint_fallback"
        selected_boundary = min(boundaries, key=lambda boundary: (abs(boundary - 15_000), boundary)) if boundaries else None
        ranges = [(0, active_end_ms)] if selected_boundary is None else [(0, selected_boundary), (selected_boundary, active_end_ms)]
        segments: list[dict[str, Any]] = []
        for index, (start_ms, end_ms) in enumerate(ranges, start=1):
            cut_ids = [
                cut["cut_id"]
                for cut in active_cuts
                if cut["start_ms"] < end_ms and cut["end_ms"] > start_ms
            ]
            if not cut_ids or end_ms - start_ms > 15_000 or end_ms <= start_ms:
                raise _replication_error("SEGMENT_PLAN_INVALID", "v2 natural Cut coverage cannot form legal segments")
            ui_cut_ids = [cut["cut_id"] for cut in active_cuts if cut["cut_id"] in cut_ids and cut["route"] in {"ui", "source_ui_keep", "ui_keep"}]
            segments.append({
                "segment_id": f"S{index:02d}",
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": end_ms - start_ms,
                "cut_ids": cut_ids,
                "ui_cut_ids": ui_cut_ids,
            })
        cut_execution: list[dict[str, Any]] = []
        execution_order = 0
        for segment in segments:
            for cut in active_cuts:
                local_start_ms = max(int(cut["start_ms"]), int(segment["start_ms"]))
                local_end_ms = min(int(cut["end_ms"]), int(segment["end_ms"]))
                if local_start_ms >= local_end_ms:
                    continue
                execution_order += 1
                cut_execution.append(SegmentPlanStage._cut_execution_record(
                    cut["raw"],
                    cut_id=str(cut["cut_id"]),
                    segment_id=str(segment["segment_id"]),
                    order=execution_order,
                    start_ms=local_start_ms,
                    end_ms=local_end_ms,
                    change_rows=change_rows,
                ))
        inter_segment_state: dict[str, dict[str, Any]] = {}
        for previous, current in zip(segments, segments[1:], strict=False):
            previous_cut = next(item for item in reversed(cut_execution) if item["segment_id"] == previous["segment_id"])
            current_cut = next(item for item in cut_execution if item["segment_id"] == current["segment_id"])
            endpoint = str(previous_cut["end_state"])
            start_state = str(current_cut["start_state"])
            inter_segment_state[f"{previous['segment_id']}->{current['segment_id']}"] = {
                "from_cut_id": previous_cut["cut_id"],
                "to_cut_id": current_cut["cut_id"],
                "end_state": endpoint,
                "start_state": start_state,
                "carry_forward": list(dict.fromkeys((endpoint, start_state))),
            }
        forced_continuity_boundary: dict[str, Any] | None = None
        seam_qc: dict[str, Any] | None = None
        if boundary_mode == "frame_midpoint_fallback" and boundary_receipt is not None:
            boundary_ms = int(boundary_receipt["boundary_ms"])
            spanning_cut = next(
                cut
                for cut in active_cuts
                if int(cut["start_ms"]) < boundary_ms < int(cut["end_ms"])
            )
            raw = spanning_cut["raw"]
            continues_across_boundary = [
                f"{kind}:{tag}"
                for kind, field in (
                    ("person", "person_tags"),
                    ("product", "product_tags"),
                    ("ui", "ui_tags"),
                    ("scene", "scene_tags"),
                )
                for tag in SegmentPlanStage._cut_string_list(raw, field)
            ]
            crossing_window_ids = [
                str(row["window_id"])
                for row in [*performance_windows, *text_windows]
                if int(row["start_ms"]) < boundary_ms < int(row["end_ms"])
            ]
            forced_continuity_boundary = {
                "contract": "forced-continuity-boundary/v1",
                **boundary_receipt,
                "from_cut_id": str(spanning_cut["cut_id"]),
                "to_cut_id": str(spanning_cut["cut_id"]),
                "continues_across_boundary": continues_across_boundary,
                "action_purpose": str(raw.get("action_purpose") or raw.get("action") or "preserve source action").strip(),
                "product_display_steps": SegmentPlanStage._cut_string_list(raw, "product_display_steps"),
                "app_operation_steps": SegmentPlanStage._cut_string_list(raw, "app_operation_steps"),
                "crossing_window_ids": list(dict.fromkeys(crossing_window_ids)),
                "carry_forward": list(inter_segment_state.get("S01->S02", {}).get("carry_forward", [])),
            }
            seam_qc = {
                "contract": "forced-boundary-seam-qc/v1",
                "required": True,
                "boundary_ms": boundary_ms,
                "grid_fps_num": int(boundary_receipt["grid_fps_num"]),
                "grid_fps_den": int(boundary_receipt["grid_fps_den"]),
                "checks": [
                    "identity_continuity",
                    "object_state_continuity",
                    "contact_continuity",
                    "action_direction_continuity",
                    "camera_continuity",
                    "audio_continuity",
                    "no_black_frames",
                    "no_duplicate_frames",
                    "no_missing_frames",
                ],
            }
        plan = {
            "schema_version": "video-edit-segments/v2",
            "source_duration_ms": source_duration_ms,
            "active_end_ms": active_end_ms,
            "tail_boundary": normalized[tail_index] if tail_index is not None else None,
            "boundary_mode": boundary_mode,
            "selected_split_boundary_ms": selected_boundary,
            "segments": segments,
            "dialogue_windows": dialogue_windows,
            "approved_script_sha256": script_sha,
            "source_dynamics_sha256": source_dynamics_sha,
            "asset_binding_authority": SegmentPlanStage._asset_binding_authority(context, approved_edit_script),
            "cut_execution": cut_execution,
            "inter_segment_state": inter_segment_state,
            "forced_continuity_boundary": forced_continuity_boundary,
            "seam_qc": seam_qc,
            "performance_windows": performance_windows,
            "text_windows": text_windows,
            "post_routes": SegmentPlanStage._post_routes(context, approval, text_windows),
        }
        published = _publish_json(
            context,
            kind="segment_plan",
            value=plan,
            metadata={"canonical_json": _canonical(plan).decode("utf-8")},
        )
        return {
            "status": "ready",
            "segment_plan": plan,
            "segment_plan_sha256": _sha(plan),
            "dialogue_windows": dialogue_windows,
            "published_artifacts": [published],
        }

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        if self._is_v2(context):
            return self._run_v2(context)
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


class TargetEvidenceStage:
    """Classify frozen target images and publish one durable v2 evidence set."""

    _IMAGE_SLOTS = ("new_model_image", "new_product_image")
    _ROSTER_KEYS = ("source_identity_roster", "source_product_roster", "source_scene_roster")
    _ASSET_TYPES = frozenset({"model", "garment", "scene", "product"})

    def __init__(self, *, classifier: Any, app_semantic_analyzer: Any | None = None) -> None:
        self.classifier = classifier
        self.app_semantic_analyzer = app_semantic_analyzer

    @staticmethod
    def _all_descriptors(context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in [*(getattr(context, "artifacts", ()) or ()), *input_artifacts]:
            if not isinstance(item, Mapping):
                continue
            key = (str(item.get("kind") or ""), str(item.get("artifact_id") or ""), str(item.get("sha256") or "").lower())
            if not all(key) or key in seen:
                continue
            seen.add(key)
            result.append(dict(item))
        return result

    @classmethod
    def _source_roster(cls, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        outputs = getattr(context, "stage_outputs", {})
        analyze_output = None
        if isinstance(outputs, Mapping):
            analyze_output = outputs.get("analyze_source") or outputs.get("analyze_dynamics")
        analyze_output = _mapping(analyze_output, "analyze_source stage output")
        descriptors = cls._all_descriptors(context, input_artifacts)
        expected_id = str(analyze_output.get("artifact_id") or "")
        expected_sha = str(analyze_output.get("sha256") or "").lower()
        candidates = [item for item in descriptors if item.get("kind") == "source_dynamics_analysis"]
        if expected_id:
            candidates = [item for item in candidates if str(item.get("artifact_id") or "") == expected_id]
        if expected_sha:
            candidates = [item for item in candidates if str(item.get("sha256") or "").lower() == expected_sha]
        if len(candidates) != 1:
            raise _replication_error(
                "TARGET_EVIDENCE_SOURCE_REQUIRED",
                "build_target_evidence requires one materialized analyze_source dynamics artifact",
                category="artifact",
            )
        descriptor = candidates[0]
        analysis = _read_json_artifact(context, kind="source_dynamics_analysis", sha256=str(descriptor["sha256"]).lower())
        analysis = _mapping(analysis.get("source_dynamics_analysis", analysis), "source dynamics analysis")
        nested = analysis.get("source_roster")
        nested = nested if isinstance(nested, Mapping) else {}
        description_fields = {
            "source_identity_roster": "identity_description",
            "source_product_roster": "product_description",
            "source_scene_roster": "scene_description",
        }
        roster: dict[str, list[dict[str, Any]]] = {}
        for key in cls._ROSTER_KEYS:
            raw = analysis.get(key, nested.get(key))
            if raw is None:
                raw = []
            if not isinstance(raw, list):
                raise _replication_error("TARGET_EVIDENCE_SOURCE_INVALID", f"{key} is invalid", category="artifact")
            normalized: list[dict[str, Any]] = []
            seen_tags: set[str] = set()
            for row in raw:
                if not isinstance(row, Mapping):
                    raise _replication_error("TARGET_EVIDENCE_SOURCE_INVALID", f"{key} contains an invalid roster row", category="artifact")
                tag = str(row.get("source_tag") or "").strip()
                first_seen = row.get("first_seen_ms")
                if not tag or isinstance(first_seen, bool) or not isinstance(first_seen, int) or first_seen < 0 or tag in seen_tags:
                    raise _replication_error("TARGET_EVIDENCE_SOURCE_INVALID", f"{key} is not a stable source roster", category="artifact")
                seen_tags.add(tag)
                item: dict[str, Any] = {"source_tag": tag, "first_seen_ms": first_seen}
                if "evidence_ids" in row:
                    evidence_ids = row.get("evidence_ids")
                    if (
                        not isinstance(evidence_ids, list)
                        or any(not isinstance(value, str) or not value.strip() for value in evidence_ids)
                        or len(set(evidence_ids)) != len(evidence_ids)
                    ):
                        raise _replication_error("TARGET_EVIDENCE_SOURCE_INVALID", f"{key} evidence IDs are invalid", category="artifact")
                    item["evidence_ids"] = list(evidence_ids)
                description_field = description_fields[key]
                if description_field in row:
                    description = row.get(description_field)
                    if not isinstance(description, str) or not description.strip():
                        raise _replication_error("TARGET_EVIDENCE_SOURCE_INVALID", f"{key} description is invalid", category="artifact")
                    item[description_field] = description.strip()
                normalized.append(item)
            normalized.sort(key=lambda item: (item["first_seen_ms"], item["source_tag"]))
            roster[key] = normalized
        return roster

    @staticmethod
    def _validate_published_artifact(artifact: Any, *, kind: str, sha256: str) -> dict[str, Any]:
        if not isinstance(artifact, Mapping) or not str(artifact.get("artifact_id") or "").strip() or str(artifact.get("sha256") or "").lower() != sha256:
            raise _replication_error("ARTIFACT_INVALID", f"published {kind} artifact is missing immutable identity", category="artifact")
        return dict(artifact)

    @classmethod
    def _app_evidence(
        cls,
        context: Any,
        input_artifacts: Sequence[Mapping[str, Any]],
        stack: ExitStack,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
        has_screenshot = _present(context, "ui_screenshot")
        has_url = _present(context, "app_store_url")
        if not has_screenshot and not has_url:
            return None, [], []
        descriptors = cls._all_descriptors(context, input_artifacts)
        published: list[dict[str, Any]] = []
        members: list[dict[str, Any]] = []
        frame_records: list[dict[str, Any]] = []
        seen_shas: set[str] = set()
        if has_screenshot:
            for source_index, expected_sha in enumerate(_slot_sha256s(context, "ui_screenshot")):
                with context.materialize_slot("ui_screenshot", index=source_index) as media:
                    path = Path(media.path)
                    data = path.read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                if actual != expected_sha:
                    raise _replication_error("ARTIFACT_HASH_MISMATCH", "ui_screenshot bytes differ from the frozen slot SHA", category="artifact")
                if actual in seen_shas:
                    continue
                content_type = _image_content_type(data, path)
                existing = [
                    item
                    for item in descriptors
                    if item.get("kind") == "ui_screenshot" and str(item.get("sha256") or "").lower() == actual
                ]
                artifact = existing[0] if existing else context.publish_bytes(
                    kind="ui_screenshot",
                    data=data,
                    content_type=content_type,
                    expected_sha256=actual,
                    metadata={"producer_stage": "build_target_evidence", "source_slot": "ui_screenshot", "source_index": source_index},
                )
                artifact = cls._validate_published_artifact(artifact, kind="ui_screenshot", sha256=actual)
                if not existing:
                    published.append(artifact)
                order = len(members) + 1
                members.append({"artifact_id": artifact["artifact_id"], "kind": "ui_screenshot", "order": order, "sha256": actual, "content_type": content_type})
                frame_records.append({"bytes": data, "content_type": content_type, "artifact_id": artifact["artifact_id"], "kind": "ui_screenshot", "order": order, "sha256": actual})
                seen_shas.add(actual)
        official_url_evidence: dict[str, Any] | None = None
        if has_url:
            evidence_rows = [item for item in descriptors if item.get("kind") == "app_store_evidence"]
            screenshot_rows = [item for item in descriptors if item.get("kind") == "app_store_screenshot"]
            if len(evidence_rows) != 1 or not screenshot_rows:
                raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store URL requires parser evidence and screenshots", category="artifact")
            evidence_descriptor = evidence_rows[0]
            media = stack.enter_context(
                context.materialize_artifact(
                    "app_store_evidence",
                    artifact_id=str(evidence_descriptor["artifact_id"]),
                    sha256=str(evidence_descriptor["sha256"]).lower(),
                )
            )
            try:
                evidence = json.loads(Path(media.path).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store evidence is not valid JSON", category="artifact") from exc
            if hashlib.sha256(Path(media.path).read_bytes()).hexdigest() != str(evidence_descriptor.get("sha256") or "").lower():
                raise _replication_error("ARTIFACT_HASH_MISMATCH", "App Store evidence bytes differ from the parser SHA", category="artifact")
            if not isinstance(evidence, Mapping) or evidence.get("contract") != "app-store-evidence" or evidence.get("contract_version") != 1:
                raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store evidence contract is invalid", category="artifact")
            url_values = _slot(context, "app_store_url").get("values") or []
            url = str(url_values[0] if url_values else "").strip()
            try:
                url = validate_public_https_url(url)
            except Exception as exc:
                raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store URL is not a public HTTPS URL", category="artifact") from exc
            screenshot_by_sha = {str(item.get("sha256") or "").lower(): item for item in screenshot_rows}
            parser_screenshots = evidence.get("screenshots")
            if not isinstance(parser_screenshots, list) or not parser_screenshots:
                raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store evidence has no screenshots", category="artifact")
            for item in sorted(parser_screenshots, key=lambda row: int(row.get("store_media_ordinal") or 0) if isinstance(row, Mapping) else 0):
                if not isinstance(item, Mapping):
                    raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store screenshot record is invalid", category="artifact")
                try:
                    source_url = validate_public_https_url(item.get("source_url"))
                except Exception as exc:
                    raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store screenshot source URL is invalid", category="artifact") from exc
                if source_url != url:
                    raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store screenshot source URL differs from the requested App URL", category="artifact")
                screenshot_sha = str(item.get("sha256") or "").lower()
                descriptor = screenshot_by_sha.get(screenshot_sha)
                if descriptor is None:
                    raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App Store screenshot is not immutably published", category="artifact")
                screenshot_media = stack.enter_context(
                    context.materialize_artifact(
                        "app_store_screenshot",
                        artifact_id=str(descriptor["artifact_id"]),
                        sha256=screenshot_sha,
                    )
                )
                screenshot_path = Path(screenshot_media.path)
                screenshot_bytes = screenshot_path.read_bytes()
                if hashlib.sha256(screenshot_bytes).hexdigest() != screenshot_sha:
                    raise _replication_error("ARTIFACT_HASH_MISMATCH", "App Store screenshot bytes differ from parser SHA", category="artifact")
                if screenshot_sha in seen_shas:
                    continue
                content_type = _image_content_type(screenshot_bytes, screenshot_path)
                order = len(members) + 1
                members.append({"artifact_id": descriptor["artifact_id"], "kind": "app_store_screenshot", "order": order, "sha256": screenshot_sha, "content_type": content_type})
                frame_records.append({"bytes": screenshot_bytes, "content_type": content_type, "artifact_id": descriptor["artifact_id"], "kind": "app_store_screenshot", "order": order, "sha256": screenshot_sha})
                seen_shas.add(screenshot_sha)
            official_url_evidence = {
                "artifact_id": evidence_descriptor["artifact_id"],
                "sha256": str(evidence_descriptor["sha256"]).lower(),
                "url": url,
                "verified": True,
            }
        if not members:
            raise _replication_error("TARGET_EVIDENCE_APP_INVALID", "App evidence has no ordered image members", category="artifact")
        bundle: dict[str, Any] = {"schema_version": "app-evidence-bundle/v1", "members": members}
        if official_url_evidence is not None:
            bundle["official_url_evidence"] = official_url_evidence
        bundle_artifact = _publish_json(
            context,
            kind="app_evidence_bundle",
            value=bundle,
            metadata={"producer_stage": "build_target_evidence", "member_sha256s": [item["sha256"] for item in members]},
        )
        bundle_artifact = cls._validate_published_artifact(bundle_artifact, kind="app_evidence_bundle", sha256=str(bundle_artifact.get("sha256") or "").lower())
        published.append(bundle_artifact)
        bundle_with_identity = {**bundle, "artifact_id": bundle_artifact["artifact_id"], "sha256": bundle_artifact["sha256"]}
        return bundle_with_identity, published, frame_records

    @classmethod
    def _asset_analysis_row(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        observations = row.get("observations")
        if not isinstance(observations, Mapping):
            raise _replication_error("TARGET_EVIDENCE_ANALYSIS_INVALID", "asset observations are required", category="artifact")
        asset_tag = str(row.get("asset_tag") or "").strip() or "asset"
        candidate = {
            "asset_tag": row.get("asset_tag"),
            "asset_type": row.get("asset_type"),
            "selling_points": observations.get("selling_points"),
            "pain_points": observations.get("pain_points"),
            "pain_point_mapping": observations.get("pain_point_mapping"),
            "display_method_library": observations.get("display_method_library"),
            "display_operation_adaptation": observations.get("display_operation_adaptation"),
            "operation_logic": observations.get("operation_logic"),
        }
        try:
            return normalize_per_asset_analysis_row(candidate, field=asset_tag, allowed_asset_types=cls._ASSET_TYPES)
        except MarketingAnalysisContractError as exc:
            code = exc.code if exc.code == "CONTENT_SAFETY_BLOCKER" else "TARGET_EVIDENCE_ANALYSIS_INVALID"
            category = "safety" if code == "CONTENT_SAFETY_BLOCKER" else "artifact"
            raise _replication_error(code, str(exc), category=category) from exc

    @classmethod
    def _app_analysis_row(
        cls,
        result: Any,
        *,
        frame_records: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if not isinstance(result, Mapping):
            raise _replication_error("TARGET_EVIDENCE_APP_ANALYSIS_FAILED", "App semantic analyzer returned no object", category="capability", retryable=True)
        candidate = {
            "asset_tag": "AppA",
            "asset_type": "app",
            "selling_points": result.get("selling_points"),
            "pain_points": result.get("pain_points"),
            "pain_point_mapping": result.get("pain_point_mapping"),
            "display_method_library": result.get("display_method_library"),
            "display_operation_adaptation": result.get("display_operation_adaptation"),
            "operation_logic": result.get("operation_logic"),
        }
        try:
            row = normalize_per_asset_analysis_row(candidate, field="AppA", allowed_asset_types={"app"})
        except MarketingAnalysisContractError as exc:
            code = exc.code if exc.code == "CONTENT_SAFETY_BLOCKER" else "TARGET_EVIDENCE_APP_ANALYSIS_FAILED"
            category = "safety" if code == "CONTENT_SAFETY_BLOCKER" else "capability"
            raise _replication_error(code, str(exc), category=category) from exc
        frame_shas = [str(frame.get("sha256") or "").lower() for frame in frame_records]
        reported_frame_shas = result.get("frame_sha256s")
        if reported_frame_shas is not None and list(reported_frame_shas) != frame_shas:
            raise _replication_error("TARGET_EVIDENCE_APP_ANALYSIS_FAILED", "App semantic analyzer frame evidence is out of order", category="artifact")
        normalized = {
            "selling_points": list(row["selling_points"]),
            "pain_points": list(row["pain_points"]),
            "pain_point_mapping": list(row["pain_point_mapping"]),
            "display_method_library": list(row["display_method_library"]),
            "display_operation_adaptation": row["display_operation_adaptation"],
            "operation_logic": row["operation_logic"],
        }
        evidence = {"frame_sha256s": frame_shas}
        receipt = result.get("receipt")
        if isinstance(receipt, Mapping):
            evidence["receipt"] = dict(receipt)
        return row, evidence, normalized

    @classmethod
    def _analysis(
        cls,
        classifications: Sequence[Mapping[str, Any]],
        app_bundle: Mapping[str, Any] | None,
        *,
        app_analysis: Mapping[str, Any] | None = None,
        app_frame_records: Sequence[Mapping[str, Any]] = (),
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        per_asset = [cls._asset_analysis_row(row) for row in classifications]
        app_evidence: dict[str, Any] | None = None
        if app_bundle is not None:
            if app_analysis is None:
                raise _replication_error("CAPABILITY_UNAVAILABLE", "App assets require a semantic analyzer", category="capability", retryable=True)
            app_row, app_evidence, _ = cls._app_analysis_row(app_analysis, frame_records=app_frame_records)
            per_asset.append(app_row)
        if len({row["asset_tag"] for row in per_asset}) != len(per_asset):
            raise _replication_error("TARGET_EVIDENCE_ANALYSIS_INVALID", "asset analysis contains duplicate asset tags", category="artifact")

        product_rows = [row for row in per_asset if row["asset_type"] == "product"]
        aggregate_rows = product_rows or per_asset

        def aggregate(field: str) -> list[str]:
            values: list[str] = []
            for row in aggregate_rows:
                for item in row[field]:
                    if item not in values:
                        values.append(item)
                    if len(values) == 5:
                        return values
            return values

        selling_points = aggregate("selling_points")
        pain_points = aggregate("pain_points")
        if not 3 <= len(selling_points) <= 5 or not 3 <= len(pain_points) <= 5:
            raise _replication_error("TARGET_EVIDENCE_ANALYSIS_INVALID", "aggregated target analysis is incomplete", category="artifact")
        pain_mapping: list[dict[str, str]] = []
        seen_mapping_pairs: set[tuple[str, str]] = set()
        for row in aggregate_rows:
            for item in row["pain_point_mapping"]:
                pair = (item["pain_point"], item["selling_point"])
                if pair in seen_mapping_pairs or pair[0] not in pain_points or pair[1] not in selling_points:
                    continue
                seen_mapping_pairs.add(pair)
                pain_mapping.append({"pain_point": pair[0], "selling_point": pair[1]})
        if {item["pain_point"] for item in pain_mapping} != set(pain_points):
            raise _replication_error("TARGET_EVIDENCE_ANALYSIS_INVALID", "aggregated target pain mapping is incomplete", category="artifact")
        display_methods = aggregate("display_method_library")
        scene_rows = [row for row in per_asset if row["asset_type"] == "scene"]
        primary = product_rows[0] if product_rows else (per_asset[0] if per_asset else None)
        if primary is None:
            raise _replication_error("TARGET_EVIDENCE_ANALYSIS_INVALID", "target analysis has no asset rows", category="artifact")
        analysis = {
            "selling_points": selling_points,
            "pain_points": pain_points,
            "pain_point_mapping": pain_mapping,
            "display_operation_adaptation": primary["display_operation_adaptation"],
            "category_specific_adaptation": primary["display_operation_adaptation"],
            "action_compatibility": primary["operation_logic"],
            "display_method_library": display_methods,
            "operation_logic": primary["operation_logic"],
            "scene_adaptation": scene_rows[0]["display_operation_adaptation"] if scene_rows else primary["operation_logic"],
            "per_asset_analysis": per_asset,
        }
        return analysis, app_evidence

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        roster = self._source_roster(context, input_artifacts)
        classify = getattr(self.classifier, "classify_image", None)
        if not callable(classify):
            raise _replication_error("CAPABILITY_UNAVAILABLE", "target evidence requires an image classifier", retryable=True, category="capability")
        classifications: list[dict[str, Any]] = []
        product_mapping: list[dict[str, Any]] = []
        seen_source_keys: set[tuple[str, int]] = set()
        seen_tags: set[str] = set()
        with ExitStack() as stack:
            for slot_id in self._IMAGE_SLOTS:
                if not _present(context, slot_id):
                    continue
                for source_index, source_sha in enumerate(_slot_sha256s(context, slot_id)):
                    source_key = (slot_id, source_index)
                    if source_key in seen_source_keys:
                        raise _replication_error("TARGET_EVIDENCE_INVALID", "target source asset is duplicated", category="artifact")
                    media = stack.enter_context(context.materialize_slot(slot_id, index=source_index))
                    path = Path(media.path)
                    image_bytes = path.read_bytes()
                    actual_sha = hashlib.sha256(image_bytes).hexdigest()
                    if actual_sha != source_sha:
                        raise _replication_error("ARTIFACT_HASH_MISMATCH", "target image bytes differ from frozen slot SHA", category="artifact")
                    try:
                        candidate = classify(
                            source_slot=slot_id,
                            source_index=source_index,
                            source_asset_sha256=source_sha,
                            image_path=path,
                            image_bytes=image_bytes,
                            source_roster=roster,
                        )
                    except ReplicationError:
                        raise
                    except Exception as exc:
                        raise _replication_error("TARGET_EVIDENCE_CLASSIFICATION_FAILED", "target image classification failed", retryable=True, category="capability") from exc
                    if not isinstance(candidate, Mapping):
                        raise _replication_error("TARGET_EVIDENCE_INVALID", "target classifier returned an invalid mapping", category="artifact")
                    asset_type = str(candidate.get("asset_type") or "").strip().casefold()
                    asset_tag = str(candidate.get("asset_tag") or "").strip()
                    replaces_tag = str(candidate.get("replaces_tag") or "").strip()
                    observations = candidate.get("observations")
                    if (
                        candidate.get("source_slot") != slot_id
                        or candidate.get("source_index") != source_index
                        or str(candidate.get("source_asset_sha256") or "").lower() != source_sha
                        or asset_type not in self._ASSET_TYPES
                        or not asset_tag
                        or not replaces_tag
                        or not isinstance(observations, Mapping)
                    ):
                        raise _replication_error("TARGET_EVIDENCE_INVALID", "target classifier output is not bound to the frozen image", category="artifact")
                    roster_key = {
                        "model": "source_identity_roster",
                        "garment": "source_identity_roster",
                        "scene": "source_scene_roster",
                        "product": "source_product_roster",
                    }[asset_type]
                    source_tags = {str(item["source_tag"]) for item in roster[roster_key]}
                    if replaces_tag not in source_tags or asset_tag in seen_tags:
                        raise _replication_error("TARGET_EVIDENCE_INVALID", "target classifier returned an unstable source mapping", category="artifact")
                    row = {
                        "source_slot": slot_id,
                        "source_index": source_index,
                        "source_asset_sha256": source_sha,
                        "asset_type": asset_type,
                        "asset_tag": asset_tag,
                        "replaces_tag": replaces_tag,
                        "image_reference": f"@Image{len(classifications) + len(product_mapping) + 1}",
                        "observations": dict(observations),
                    }
                    seen_source_keys.add(source_key)
                    seen_tags.add(asset_tag)
                    if asset_type == "product":
                        product_mapping.append(row)
                    else:
                        classifications.append(row)
            app_bundle, app_published, app_frame_records = self._app_evidence(context, input_artifacts, stack)
        ordered_rows = [*classifications, *product_mapping]
        app_analysis: Mapping[str, Any] | None = None
        if app_bundle is not None:
            analyzer = getattr(self, "app_semantic_analyzer", None)
            analyze_images = getattr(analyzer, "analyze_images", None)
            if not callable(analyze_images):
                raise _replication_error(
                    "CAPABILITY_UNAVAILABLE",
                    "App assets require the packaged semantic image analyzer",
                    category="capability",
                    retryable=True,
                )
            else:
                try:
                    app_analysis = analyze_images(
                        frames=[dict(frame) for frame in app_frame_records],
                        evidence={
                            "contract": "app-evidence-bundle/v1",
                            "app_evidence_bundle": dict(app_bundle),
                            "frame_sha256s": [str(frame["sha256"]).lower() for frame in app_frame_records],
                        },
                    )
                except ReplicationError:
                    raise
                except Exception as exc:
                    raise _replication_error(
                        "TARGET_EVIDENCE_APP_ANALYSIS_FAILED",
                        "App semantic image analysis failed",
                        category="capability",
                        retryable=True,
                    ) from exc
        analysis, app_analysis_evidence = self._analysis(
            ordered_rows,
            app_bundle,
            app_analysis=app_analysis,
            app_frame_records=app_frame_records,
        )
        source_asset_sha256s = [str(row["source_asset_sha256"]).lower() for row in ordered_rows]
        if _present(context, "ui_screenshot"):
            source_asset_sha256s.extend(_slot_sha256s(context, "ui_screenshot"))
        if app_bundle is not None:
            source_asset_sha256s.extend(str(item["sha256"]).lower() for item in app_bundle["members"])
            official = app_bundle.get("official_url_evidence")
            if isinstance(official, Mapping):
                source_asset_sha256s.append(str(official["sha256"]).lower())
            source_asset_sha256s.append(str(app_bundle["sha256"]).lower())
        value: dict[str, Any] = {
            "schema_version": "target-evidence/v1",
            "source_roster": roster,
            "asset_classifications": classifications,
            "product_index_mapping": product_mapping,
            "product_or_app_analysis": analysis,
            "source_asset_sha256s": list(dict.fromkeys(source_asset_sha256s)),
        }
        if app_bundle is not None:
            value["app_evidence_bundle"] = app_bundle
        if app_analysis_evidence is not None:
            value["app_analysis_evidence"] = {
                **app_analysis_evidence,
                "bundle_sha256": str(app_bundle["sha256"]).lower() if isinstance(app_bundle, Mapping) else "",
            }
        target_artifact = _publish_json(
            context,
            kind="target_evidence",
            value=value,
            metadata={"producer_stage": "build_target_evidence", "source_asset_sha256s": value["source_asset_sha256s"]},
        )
        target_artifact = self._validate_published_artifact(target_artifact, kind="target_evidence", sha256=str(target_artifact.get("sha256") or "").lower())
        published_artifacts = [*app_published, target_artifact]
        return {
            "status": "ready",
            "target_evidence": target_artifact,
            "target_evidence_sha256": target_artifact["sha256"],
            "app_evidence_bundle": app_bundle,
            "published_artifacts": published_artifacts,
        }


class AssetBoardStage:
    """Materialize the server-approved asset mapping and generate each board once."""

    _SLOT_ORDER = {
        "new_model_image": 0,
        "new_product_image": 1,
        "ui_screenshot": 2,
        "app_store_evidence": 3,
    }

    def __init__(self, *, workflow_client: Any) -> None:
        self.workflow_client = workflow_client

    @classmethod
    def _approved_bindings(cls, context: Any) -> list[dict[str, Any]]:
        snapshot = getattr(context, "snapshot", None)
        revision = getattr(snapshot, "current_script_revision", None)
        script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
        getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1 or _SHA256.fullmatch(script_sha) is None or not callable(getter):
            raise _replication_error("APPROVAL_REQUIRED", "asset boards require the current approved v2 script mapping")
        approval = getter(context.job_id, revision)
        if not isinstance(approval, Mapping) or approval.get("contract") != "approved-script-lines/v2":
            raise _replication_error("APPROVAL_REQUIRED", "asset boards require approved-script-lines/v2")
        approval_revision = approval.get("revision")
        approval_sha = str(approval.get("script_sha256") or "").lower()
        if approval_revision is not None and (
            isinstance(approval_revision, bool)
            or not isinstance(approval_revision, int)
            or approval_revision != revision
            or approval_sha != script_sha
        ):
            raise _replication_error("APPROVAL_STALE", "approved script revision or SHA is stale")
        try:
            edit_script = canonicalize_approved_edit_script(approval.get("approved_edit_script"))
        except ReplicationError as exc:
            raise _replication_error("CONTRACT_INVALID", "approved asset mapping is not canonical") from exc
        # New v2 approvals are also bound to the immutable published script
        # artifact.  Keep the older approval-sidecar-only path readable for
        # the legacy packaged tests, but never consume stale v2 marketing data.
        script_payload: Mapping[str, Any] | None = None
        if approval_revision is not None:
            script_payload = _read_json_artifact(context, kind="script_revision", sha256=script_sha)
            if (
                script_payload.get("schema_version") != "approved-edit-script/v2"
                or script_payload.get("revision") != revision
                or not isinstance(script_payload.get("approved_edit_script"), Mapping)
            ):
                raise _replication_error("APPROVAL_STALE", "published approved script artifact is stale")
            try:
                published_edit_script = canonicalize_approved_edit_script(script_payload["approved_edit_script"])
            except ReplicationError as exc:
                raise _replication_error("CONTRACT_INVALID", "published approved script mapping is not canonical") from exc
            if published_edit_script != edit_script:
                raise _replication_error("APPROVAL_STALE", "published approved script mapping differs from the approval")

        marketing = script_payload.get("marketing_analysis") if isinstance(script_payload, Mapping) else None
        product_analysis = script_payload.get("product_or_app_analysis") if isinstance(script_payload, Mapping) else None
        if script_payload is not None and (
            not isinstance(marketing, Mapping) or not isinstance(product_analysis, Mapping)
        ):
            raise _replication_error("CONTRACT_INVALID", "approved script marketing analysis is incomplete")
        per_asset_rows = product_analysis.get("per_asset_analysis") if isinstance(product_analysis, Mapping) else None
        per_asset_index: dict[tuple[str, str], Mapping[str, Any]] | None = None
        if isinstance(per_asset_rows, list):
            per_asset_index = {}
            for index, item in enumerate(per_asset_rows):
                if not isinstance(item, Mapping):
                    raise _replication_error("CONTRACT_INVALID", f"approved per-asset analysis row {index} is invalid")
                key = (str(item.get("asset_tag") or "").strip(), str(item.get("asset_type") or "").strip().casefold())
                if not key[0] or not key[1] or key in per_asset_index:
                    raise _replication_error("CONTRACT_INVALID", "approved per-asset analysis has duplicate identity")
                per_asset_index[key] = item
        elif isinstance(script_payload, Mapping) and script_payload.get("target_evidence_summaries"):
            raise _replication_error("CONTRACT_INVALID", "approved v2 script is missing per-asset analysis")
        rows: list[dict[str, Any]] = []
        for binding in edit_script["asset_bindings"]:
            row = dict(binding)
            if isinstance(script_payload, Mapping):
                asset_type = str(row.get("asset_type") or "").casefold()
                asset_key = (str(row.get("asset_tag") or "").strip(), asset_type)
                matched_analysis = per_asset_index.get(asset_key) if per_asset_index is not None else None
                if per_asset_index is not None and matched_analysis is None:
                    raise _replication_error("CONTRACT_INVALID", "approved per-asset analysis does not match the binding")
                if matched_analysis is not None:
                    if asset_type in {"model", "garment"}:
                        row["attraction_constraint"] = str(marketing.get("attraction_preservation") or "")
                    elif asset_type in {"scene", "product"}:
                        row["display_logic"] = str(matched_analysis.get("display_operation_adaptation") or "")
                        row["operation_logic"] = str(matched_analysis.get("operation_logic") or "")
                    elif asset_type == "app":
                        row["display_logic"] = str(matched_analysis.get("display_operation_adaptation") or "")
                        row["operation_logic"] = str(matched_analysis.get("operation_logic") or "")
                elif asset_type in {"model", "garment"}:
                    row["attraction_constraint"] = str(marketing.get("attraction_preservation") or "")
                elif asset_type in {"scene", "product"}:
                    row["display_logic"] = str(product_analysis.get("display_operation_adaptation") or "")
                elif asset_type == "app":
                    row["operation_logic"] = str(
                        product_analysis.get("operation_logic")
                        or product_analysis.get("display_operation_adaptation")
                        or ""
                    )
            rows.append(row)
        return rows

    @classmethod
    def _slot_sha(cls, context: Any, binding: Mapping[str, Any]) -> str:
        slot_id = str(binding.get("source_slot") or "")
        source_index = binding.get("source_index")
        source_sha = str(binding.get("source_asset_sha256") or "").lower()
        if slot_id == "app_evidence_bundle":
            descriptors = [
                item for item in (getattr(context, "artifacts", ()) or ())
                if isinstance(item, Mapping)
                and str(item.get("artifact_id") or "") == str(binding.get("source_artifact_id") or "")
                and str(item.get("kind") or "") == "app_evidence_bundle"
            ]
            if len(descriptors) != 1 or str(descriptors[0].get("sha256") or "").lower() != source_sha:
                raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence artifact SHA does not match the approved asset binding", category="artifact")
            return source_sha
        slots = _mapping(getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("slots"), "input slots")
        slot = _mapping(slots.get(slot_id), f"{slot_id} slot")
        hashes = slot.get("sha256")
        if not isinstance(source_index, int) or isinstance(source_index, bool) or not isinstance(hashes, list) or source_index < 0 or source_index >= len(hashes):
            raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "approved asset binding source index is outside the frozen slot", category="artifact")
        actual_sha = str(hashes[source_index] or "").lower()
        if actual_sha != source_sha:
            raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "source asset SHA differs from the frozen input slot", category="artifact")
        return actual_sha

    @classmethod
    def _materialize_binding(cls, context: Any, binding: Mapping[str, Any], stack: ExitStack) -> list[Path]:
        slot_id = str(binding["source_slot"])
        source_index = int(binding["source_index"])
        if slot_id == "app_evidence_bundle":
            descriptor = next(
                item for item in (getattr(context, "artifacts", ()) or ())
                if isinstance(item, Mapping)
                and str(item.get("artifact_id") or "") == str(binding["source_artifact_id"] or "")
                and str(item.get("kind") or "") == "app_evidence_bundle"
            )
            bundle_media = stack.enter_context(
                context.materialize_artifact(
                    str(descriptor["kind"]),
                    artifact_id=str(descriptor["artifact_id"]),
                    sha256=str(descriptor["sha256"]),
                )
            )
            bundle_path = Path(bundle_media.path)
            bundle_bytes = bundle_path.read_bytes()
            if hashlib.sha256(bundle_bytes).hexdigest() != str(binding["source_asset_sha256"]).lower():
                raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence bundle bytes differ from the approved bundle SHA", category="artifact")
            try:
                bundle = json.loads(bundle_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence bundle is not canonical JSON", category="artifact") from exc
            if not isinstance(bundle, Mapping) or bundle.get("schema_version") != "app-evidence-bundle/v1":
                raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence bundle schema is invalid", category="artifact")
            url_evidence = bundle.get("official_url_evidence")
            members = bundle.get("members")
            if url_evidence is not None and not isinstance(url_evidence, Mapping):
                raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence URL evidence is invalid", category="artifact")
            if not isinstance(members, list) or not members:
                raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence bundle must contain ordered screenshots", category="artifact")
            ordered = sorted(members, key=lambda item: item.get("order", -1) if isinstance(item, Mapping) else -1)
            if ordered != members or [item.get("order") for item in ordered if isinstance(item, Mapping)] != list(range(1, len(ordered) + 1)):
                raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence screenshots are not stably ordered", category="artifact")
            descriptors = {str(item.get("artifact_id") or ""): item for item in (getattr(context, "artifacts", ()) or ()) if isinstance(item, Mapping)}
            if url_evidence is not None:
                url_id = str(url_evidence.get("artifact_id") or "")
                url_descriptor = descriptors.get(url_id)
                if (
                    not isinstance(url_descriptor, Mapping)
                    or url_descriptor.get("kind") != "app_store_evidence"
                    or str(url_descriptor.get("sha256") or "").lower() != str(url_evidence.get("sha256") or "").lower()
                ):
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence URL artifact is not bound to the bundle", category="artifact")
                url_media = stack.enter_context(context.materialize_artifact("app_store_evidence", artifact_id=url_id, sha256=str(url_descriptor.get("sha256") or "")))
                try:
                    parser_bytes = Path(url_media.path).read_bytes()
                    if hashlib.sha256(parser_bytes).hexdigest() != str(url_descriptor.get("sha256") or "").lower():
                        raise ValueError("parser evidence bytes differ from its descriptor SHA")
                    parser_evidence = json.loads(parser_bytes.decode("utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence URL artifact is invalid", category="artifact") from exc
                if not isinstance(parser_evidence, Mapping) or parser_evidence.get("contract") != "app-store-evidence" or parser_evidence.get("contract_version") != 1:
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence URL artifact contract is invalid", category="artifact")
                parser_screenshot_shas: list[str] = []
                parser_urls: set[str] = set()
                parser_screenshots = parser_evidence.get("screenshots")
                if not isinstance(parser_screenshots, list) or not parser_screenshots:
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence URL artifact has no screenshots", category="artifact")
                for screenshot in sorted(
                    parser_screenshots,
                    key=lambda item: int(item.get("store_media_ordinal") or 0) if isinstance(item, Mapping) else 0,
                ):
                    if not isinstance(screenshot, Mapping):
                        raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence parser screenshot is invalid", category="artifact")
                    try:
                        screenshot_url = validate_public_https_url(screenshot.get("source_url"))
                    except Exception as exc:
                        raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence parser screenshot URL is invalid", category="artifact") from exc
                    screenshot_sha = str(screenshot.get("sha256") or "").lower()
                    if _SHA256.fullmatch(screenshot_sha) is None:
                        raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence parser screenshot SHA is invalid", category="artifact")
                    parser_urls.add(screenshot_url)
                    if screenshot_sha not in parser_screenshot_shas:
                        parser_screenshot_shas.append(screenshot_sha)
                if len(parser_urls) != 1:
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence parser screenshots do not identify one official URL", category="artifact")
                declared_url = url_evidence.get("url")
                if declared_url is not None:
                    try:
                        official_url = validate_public_https_url(declared_url)
                    except Exception as exc:
                        raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence bundle URL is invalid", category="artifact") from exc
                    if parser_urls != {official_url}:
                        raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence parser screenshots differ from the approved URL", category="artifact")
                else:
                    official_url = next(iter(parser_urls))
                bundle_official_shas = [
                    str(item.get("sha256") or "").lower()
                    for item in ordered
                    if isinstance(item, Mapping) and item.get("kind") == "app_store_screenshot"
                ]
                if bundle_official_shas != parser_screenshot_shas:
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence bundle screenshots differ from parser evidence", category="artifact")
            paths: list[Path] = []
            for member in ordered:
                if not isinstance(member, Mapping):
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence bundle member is invalid", category="artifact")
                member_id = str(member.get("artifact_id") or "")
                member_sha = str(member.get("sha256") or "").lower()
                member_descriptor = descriptors.get(member_id)
                if not isinstance(member_descriptor, Mapping) or str(member_descriptor.get("sha256") or "").lower() != member_sha:
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence screenshot is not bound to the bundle", category="artifact")
                media = stack.enter_context(context.materialize_artifact(str(member_descriptor.get("kind") or ""), artifact_id=member_id, sha256=member_sha))
                path = Path(media.path)
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != member_sha:
                    raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence screenshot bytes differ from the bundle SHA", category="artifact")
                paths.append(path)
            if not paths:
                raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "App evidence bundle has no image members", category="artifact")
            return paths
        else:
            media = stack.enter_context(context.materialize_slot(slot_id, index=source_index))
        path = Path(media.path)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != str(binding["source_asset_sha256"]).lower():
            raise _replication_error("ASSET_BINDING_SOURCE_MISMATCH", "materialized asset bytes differ from the approved source asset SHA", category="artifact")
        return [path]

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        bindings = self._approved_bindings(context)
        if not bindings:
            return {"status": "ready", "asset_bindings": [], "asset_board_receipts": [], "published_artifacts": []}
        prepared: list[dict[str, Any]] = []
        with ExitStack() as stack:
            for binding in bindings:
                self._slot_sha(context, binding)
                reference_images = self._materialize_binding(context, binding, stack)
                prepared.append({
                    **binding,
                    "tag": binding["asset_tag"],
                    "path": reference_images[0],
                    "reference_images": reference_images,
                })
            try:
                boards = self.workflow_client.run_asset_board_batch(prepared)
            except ReplicationError:
                raise
            except Exception as exc:
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "RunningHub Image2 asset board generation failed", retryable=False, category="provider", user_action_required=True) from exc
        if not isinstance(boards, list) or len(boards) != len(prepared):
            raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board provider returned an incomplete batch", category="provider", user_action_required=True)
        published_artifacts: list[dict[str, Any]] = []
        result_bindings: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        for binding, board in zip(prepared, boards, strict=True):
            if not isinstance(board, Mapping) or str(board.get("tag") or "") != str(binding["asset_tag"]):
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board tag order differs from the approved mapping", category="provider")
            receipt = board.get("receipt")
            board_bytes = board.get("board_bytes")
            board_url_raw = board.get("board_url")
            if not isinstance(receipt, Mapping) or not isinstance(board_bytes, (bytes, bytearray)):
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board result lacks a receipt or bytes", category="provider")
            try:
                board_url = validate_public_https_url(board_url_raw)
            except Exception as exc:
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board result URL is not a public HTTPS URL", category="provider") from exc
            provider_request_sha = str(receipt.get("request_sha256") or "").lower()
            response_sha = str(receipt.get("response_sha256") or "").lower()
            result_task_id = str(board.get("task_id") or "").strip()
            receipt_task_id = str(receipt.get("task_id") or "").strip()
            provider_receipt = receipt.get("provider_receipt")
            expected_template = _asset_board_template_version(binding["asset_type"])
            if (
                receipt.get("schema_version") != "runninghub-asset-board/v2"
                or receipt.get("asset_type") != binding["asset_type"]
                or receipt.get("template_version") != expected_template
                or str(receipt.get("source_asset_sha256") or "").lower() != str(binding["source_asset_sha256"]).lower()
                or not result_task_id
                or result_task_id != receipt_task_id
                or _SHA256.fullmatch(provider_request_sha) is None
                or _SHA256.fullmatch(response_sha) is None
                or _SHA256.fullmatch(str(receipt.get("provider_asset_board_contract_sha256") or "").lower()) is None
                or not isinstance(provider_receipt, Mapping)
                or str(provider_receipt.get("request_sha256") or "").lower() != provider_request_sha
                or str(provider_receipt.get("response_sha256") or "").lower() != response_sha
                or str(provider_receipt.get("task_id") or "").strip() != receipt_task_id
            ):
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board provider receipt is incomplete", category="provider")
            expected_provider_contract = _sha({
                "asset_type": binding["asset_type"],
                "template_version": expected_template,
                "source_asset_sha256": binding["source_asset_sha256"],
                "provider_request_sha256": provider_request_sha,
            })
            if str(receipt.get("provider_asset_board_contract_sha256") or "").lower() != expected_provider_contract:
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board provider receipt contract hash differs from the canonical request record", category="provider")
            board_sha = hashlib.sha256(bytes(board_bytes)).hexdigest()
            try:
                width, height = StoryboardStage._png_dimensions(bytes(board_bytes))
            except ReplicationError as exc:
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board result is not a valid PNG", category="provider") from exc
            if width > 16_384 or height > 16_384:
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board PNG dimensions are outside the allowed range", category="provider")
            if (
                str(board.get("asset_type") or "") != str(binding["asset_type"])
            ):
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board result asset_type differs from the approved binding", category="provider")
            if str(board.get("board_sha256") or "").lower() != board_sha:
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board result bytes do not match the provider board SHA", category="provider")
            if str(receipt.get("board_sha256") or "").lower() != board_sha:
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "asset board receipt board SHA differs from the result bytes", category="provider")
            published = context.publish_bytes(
                kind="asset_board",
                data=bytes(board_bytes),
                content_type="image/png",
                expected_sha256=board_sha,
            metadata={
                "asset_type": binding["asset_type"],
                    "asset_tag": binding["asset_tag"],
                    "replaces_tag": binding["replaces_tag"],
                    "image_reference": binding["image_reference"],
                    "board_url": board_url,
                    "source_slot": binding["source_slot"],
                    "source_index": binding["source_index"],
                    "source_asset_sha256": binding["source_asset_sha256"],
                "template_version": expected_template,
                "provider_asset_board_contract_sha256": str(receipt["provider_asset_board_contract_sha256"]),
                "provider_request_sha256": provider_request_sha,
                "provider_response_sha256": response_sha,
                "provider_task_id": receipt_task_id,
            },
            )
            if not isinstance(published, Mapping) or not str(published.get("artifact_id") or "").strip() or str(published.get("sha256") or "").lower() != board_sha:
                raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "published asset board lacks an immutable artifact_id or matching SHA", category="artifact")
            final_receipt = {
                **dict(receipt),
                "schema_version": "runninghub-asset-board/v2",
                "asset_type": binding["asset_type"],
                "template_version": expected_template,
                "source_slot": binding["source_slot"],
                "source_index": binding["source_index"],
                "source_asset_sha256": binding["source_asset_sha256"],
                "asset_tag": binding["asset_tag"],
                "replaces_tag": binding["replaces_tag"],
                "image_reference": binding["image_reference"],
                "board_sha256": board_sha,
                "artifact_id": published["artifact_id"],
            }
            receipts.append(final_receipt)
            published_artifacts.append(dict(published))
            result_bindings.append({
                **binding,
                "tag": binding["asset_tag"],
                "reference": binding["image_reference"],
                "board_url": board_url,
                "board_sha256": board_sha,
                "board_artifact_id": published["artifact_id"],
                "receipt": final_receipt,
            })
        tags = [str(binding["asset_tag"]) for binding in result_bindings]
        approved_asset_bindings_sha256 = _sha(bindings)
        approved_script_sha256 = str(
            getattr(getattr(context, "snapshot", None), "approved_script_sha256", "") or ""
        ).lower()
        if _SHA256.fullmatch(approved_script_sha256) is None:
            raise _replication_error("APPROVAL_REQUIRED", "asset board manifest requires the current approved script SHA", category="artifact")
        provider_hash = _sha([receipt.get("provider_asset_board_contract_sha256") for receipt in receipts])
        manifest_entries = [
            {
                key: entry[key]
                for key in (
                    "source_slot", "source_index", "source_asset_sha256", "asset_type",
                    "asset_tag", "replaces_tag", "image_reference", "board_artifact_id",
                    "board_sha256", "board_url", "receipt",
                )
            }
            for entry in result_bindings
        ]
        mapping_sha = _sha({
            "approved_asset_bindings_sha256": approved_asset_bindings_sha256,
            "entries": manifest_entries,
            "uploaded_tags": tags,
            "binding_tags": tags,
            "prompt_tags": tags,
        })
        manifest_value = {
            "schema_version": "asset-board-manifest/v1",
            "approved_script_sha256": approved_script_sha256,
            "approved_asset_bindings_sha256": approved_asset_bindings_sha256,
            "asset_board_mapping_sha256": mapping_sha,
            "provider_asset_board_contracts_sha256": provider_hash,
            "entries": manifest_entries,
            "uploaded_tags": tags,
            "binding_tags": list(tags),
            "prompt_tags": list(tags),
        }
        manifest_artifact = _publish_json(
            context,
            kind="asset_board_manifest",
            value=manifest_value,
            metadata={
                "approved_script_sha256": approved_script_sha256,
                "approved_asset_bindings_sha256": approved_asset_bindings_sha256,
                "asset_board_mapping_sha256": mapping_sha,
                "provider_asset_board_contracts_sha256": provider_hash,
            },
        )
        if not isinstance(manifest_artifact, Mapping) or not str(manifest_artifact.get("artifact_id") or "").strip() or _SHA256.fullmatch(str(manifest_artifact.get("sha256") or "").lower()) is None:
            raise _replication_error("ASSET_BOARD_GENERATION_FAILED", "published asset board manifest lacks an immutable artifact_id or SHA", category="artifact")
        published_artifacts.append(dict(manifest_artifact))
        return {
            "status": "ready",
            "asset_bindings": result_bindings,
            "asset_board_receipts": receipts,
            "asset_board_manifest": dict(manifest_artifact),
            "asset_board_manifest_sha256": str(manifest_artifact["sha256"]).lower(),
            "asset_board_mapping_sha256": mapping_sha,
            "uploaded_tags": tags,
            "binding_tags": list(tags),
            "prompt_tags": list(tags),
            "published_artifacts": published_artifacts,
        }


MAX_MODEL_REFERENCES = 9


def select_v2_binding_mode(bindings: Sequence[Mapping[str, Any]]) -> str:
    """Select the strict direct-reference prompt for fully bound edit objects.

    The rule is count- and type-independent: one through nine independently
    indexed people, products, Apps, garments, and scenes use the same
    source-object mapping contract while retaining type-specific scopes.
    """

    if isinstance(bindings, (str, bytes, bytearray)) or not isinstance(bindings, Sequence):
        return "standard_v2_binding"
    if not bindings:
        return "standard_v2_binding"
    if len(bindings) > MAX_MODEL_REFERENCES:
        return "image_reference_limit_exceeded"
    required = {
        "source_slot",
        "source_index",
        "source_asset_sha256",
        "asset_type",
        "asset_tag",
        "replaces_tag",
        "image_reference",
        "source_object_descriptor",
        "replacement_scope",
        "preserve_scope",
        "binding_confidence",
    }
    for index, raw in enumerate(bindings, start=1):
        if not isinstance(raw, Mapping) or not required.issubset(raw):
            return "binding_evidence_required"
        confidence = raw.get("binding_confidence")
        if (
            str(raw.get("asset_type") or "").casefold() not in {"model", "garment", "scene", "product", "app"}
            or str(raw.get("image_reference") or "") != f"@Image{index}"
            or not str(raw.get("replaces_tag") or "").strip()
            or not str(raw.get("source_object_descriptor") or "").strip()
            or not str(raw.get("replacement_scope") or "").strip()
            or not str(raw.get("preserve_scope") or "").strip()
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or float(confidence) < 0.85
        ):
            return "binding_evidence_required"
    return "provider_only_multi_object_binding"


def _validate_provider_only_binding_receipt(
    receipt: Mapping[str, Any] | None,
    *,
    prompt: str,
    image_tags: Sequence[str],
) -> dict[str, Any]:
    """Validate the compact binding authority against the exact paid prompt/order."""

    expected_tags = [f"@Image{index}" for index in range(1, len(image_tags) + 1)]
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("contract") != "provider-only-multi-object-binding/v1"
        or receipt.get("compiler_version") != "provider-only-multi-object-binding/v1"
        or receipt.get("binding_mode") != "provider_only_multi_object_binding"
        or list(receipt.get("image_tags") or []) != expected_tags
        or list(image_tags) != expected_tags
        or str(receipt.get("prompt_sha256") or "").lower() != prompt_sha256
        or _SHA256.fullmatch(str(receipt.get("binding_contract_sha256") or "").lower()) is None
        or not isinstance(receipt.get("source_object_ids"), list)
        or len(receipt["source_object_ids"]) != len(expected_tags)
    ):
        raise _replication_error(
            "SOURCE_OBJECT_BINDING_REQUIRED",
            "canonical provider-only binding receipt is missing or stale",
            category="artifact",
        )
    return dict(receipt)


class SeedancePromptStage:
    """Compile each approved segment with the packaged Seedance-20 compiler."""

    def __init__(self, *, invocation_adapter: Any, uploaded_song_transcriber: Any | None = None) -> None:
        self.invocation_adapter = invocation_adapter
        self.uploaded_song_transcriber = uploaded_song_transcriber

    def _approved_revision(self, context: Any, *, kind: str, digest: str) -> Mapping[str, Any]:
        return _read_json_artifact(context, kind=f"{kind}_revision", sha256=digest)


class H3PromptStage:
    """Compile the compact Chinese H3 request without Seedance reference syntax."""

    @staticmethod
    def _approved_script(context: Any) -> Mapping[str, Any]:
        digest = str(getattr(context.snapshot, "approved_script_sha256", "") or "").lower()
        if _SHA256.fullmatch(digest) is None:
            raise _replication_error("APPROVAL_REQUIRED", "H3 edit requires the approved script")
        artifact = _read_json_artifact(context, kind="script_revision", sha256=digest)
        try:
            return canonicalize_approved_edit_script(artifact.get("approved_edit_script"))
        except ReplicationError as exc:
            raise _replication_error("CONTRACT_INVALID", "approved H3 edit mapping is not canonical") from exc

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        approved = self._approved_script(context)
        plan_output = _stage_output(context, "segment_plan")
        plan = _mapping(plan_output.get("segment_plan"), "H3 segment plan")
        plan_sha = str(plan_output.get("segment_plan_sha256") or "").lower()
        if plan_sha != _sha(plan) or not isinstance(plan.get("segments"), list):
            raise _replication_error("SEGMENT_PLAN_INVALID", "H3 segment plan digest is stale")
        manifest = getattr(context.snapshot, "slots_manifest", {}) or {}
        extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else {}
        music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
        mv_song = isinstance(music, Mapping) and str(music.get("kind") or "").casefold() in {"song", "mv"}
        target_language = str(manifest.get("output_language") or "").casefold() or None
        bindings = approved["asset_bindings"]
        rows = approved["change_rows"]
        compiled_segments: list[dict[str, Any]] = []
        for raw_segment in plan["segments"]:
            segment = _mapping(raw_segment, "H3 segment")
            start_ms, end_ms = int(segment["start_ms"]), int(segment["end_ms"])
            instructions = {
                str(row.get("asset_tag") or ""): str(row.get("instruction") or "").strip()
                for row in rows
                if str(row.get("kind") or "").casefold() == "replacement"
                and int(row["start_ms"]) < end_ms and int(row["end_ms"]) > start_ms
            }
            h3_bindings = [
                {
                    "image_index": index,
                    "asset_type": str(binding["asset_type"]),
                    "instruction": instructions.get(str(binding["asset_tag"]), ""),
                }
                for index, binding in enumerate(bindings, start=1)
            ]
            dialogue = " ".join(
                str(row.get("text") or "").strip()
                for row in rows
                if str(row.get("kind") or "").casefold() in {"dialogue", "language"}
                and int(row["start_ms"]) < end_ms and int(row["end_ms"]) > start_ms
                and str(row.get("text") or "").strip()
            )
            try:
                prompt = compile_h3_prompt(
                    target_language=target_language,
                    dialogue=dialogue or None,
                    bindings=h3_bindings,
                    preserve="镜头、人物动作、手部接触、剪辑节奏、UI 操作片段和未修改内容",
                    mv_target_song=mv_song,
                    has_audio=mv_song,
                )
            except H3EditContractError as exc:
                raise _replication_error(str(exc), "H3 compact prompt contract failed") from exc
            compiled_segments.append({
                "segment_id": str(segment["segment_id"]),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": int(segment["duration_ms"]),
                "prompt": prompt,
                "segment_plan_sha256": plan_sha,
            })
        envelope = {
            "schema_version": "h3-edit-input/v1",
            "edit_contract": "video-edit-v2",
            "segment_plan_sha256": plan_sha,
            "image_count": len(bindings),
            "segments": compiled_segments,
        }
        published = _publish_json(context, kind="h3_edit_input", value=envelope)
        return {"status": "ready", "h3_edit_input": envelope, "published_artifacts": [published]}


class H3AuditStage:
    """Materialize current-run media and freeze exact H3 payloads before create."""

    def __init__(self, *, workflow_client: Any) -> None:
        if not callable(getattr(workflow_client, "upload_media", None)):
            raise _replication_error("CAPABILITY_UNAVAILABLE", "H3 media uploader is unavailable", category="capability")
        self.workflow_client = workflow_client

    @staticmethod
    def _source_slice(context: Any, *, segment: Mapping[str, Any]) -> Path:
        destination = Path(context.work_dir) / f"{segment['segment_id']}-h3-source.mp4"
        with context.materialize_slot("source_video") as source:
            return _ffmpeg_source_segment(
                source_path=Path(source.path), start_ms=int(segment["start_ms"]),
                end_ms=int(segment["end_ms"]), destination=destination,
            )

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        contract = _mapping(_stage_output(context, "compile_h3_edit").get("h3_edit_input"), "H3 edit input")
        image_count = contract.get("image_count")
        if isinstance(image_count, bool) or not isinstance(image_count, int) or image_count < 0:
            raise _replication_error("CONTRACT_INVALID", "H3 image count is invalid")
        visual_manifest = _resolve_v2_asset_board_manifest(context) if image_count else None
        image_urls = [str(row["board_url"]) for row in (visual_manifest["entries"] if visual_manifest else [])]
        if len(image_urls) != image_count:
            raise _replication_error("H3_IMAGE_REFERENCE_MISMATCH", "H3 image URLs differ from approved bindings")
        manifest = getattr(context.snapshot, "slots_manifest", {}) or {}
        music = (manifest.get("extensions") or {}).get("background_music") if isinstance(manifest, Mapping) else None
        audited: list[dict[str, Any]] = []
        published_artifacts: list[Mapping[str, Any]] = []
        for raw in contract.get("segments") or []:
            segment = _mapping(raw, "H3 compiled segment")
            source_path = self._source_slice(context, segment=segment)
            source_bytes = source_path.read_bytes()
            source_sha = hashlib.sha256(source_bytes).hexdigest()
            published_artifacts.append(context.publish_bytes(
                kind="source_video_reference", data=source_bytes, content_type="video/mp4",
                expected_sha256=source_sha, metadata={
                    "segment_id": str(segment["segment_id"]),
                    "segment_plan_sha256": str(segment["segment_plan_sha256"]),
                    "start_ms": int(segment["start_ms"]), "end_ms": int(segment["end_ms"]),
                    "source_video_sha256": _slot_sha256s(context, "source_video")[0],
                },
            ))
            video_url = self.workflow_client.upload_media(source_path)
            audio_urls: list[str] = []
            if isinstance(music, Mapping):
                with context.materialize_extension("background_music") as audio:
                    audio_urls = [self.workflow_client.upload_media(Path(audio.path))]
            try:
                payload = build_h3_request(
                    prompt=str(segment["prompt"]), image_urls=image_urls,
                    video_urls=[video_url], audio_urls=audio_urls,
                    duration=max(5, min(15, round(int(segment["duration_ms"]) / 1000))),
                )
            except H3EditContractError as exc:
                raise _replication_error(str(exc), "H3 provider request contract failed") from exc
            audited.append({
                "segment_id": str(segment["segment_id"]),
                "segment_plan_sha256": str(segment["segment_plan_sha256"]),
                "payload": payload,
                "request_sha256": _sha(payload),
            })
        envelope = {"schema_version": "h3-request-audit/v1", "segments": audited}
        published = _publish_json(context, kind="h3_request_audit", value=envelope)
        return {"status": "ready", "h3_request_audit": envelope, "published_artifacts": [*published_artifacts, published]}


class H3SubmitStage:
    """Create every audited H3 segment exactly once."""

    def __init__(self, *, workflow_client: Any) -> None:
        self.workflow_client = workflow_client

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        audit = _mapping(_stage_output(context, "audit_h3_request").get("h3_request_audit"), "H3 request audit")
        submitted: list[dict[str, Any]] = []
        endpoint = f"{self.workflow_client.base_url}/openapi/v2/minimax/hailuo-h3/multimodal-to-video"
        for row in audit.get("segments") or []:
            item = _mapping(row, "H3 audited segment")
            response = self.workflow_client._post(url=endpoint, payload=_mapping(item.get("payload"), "H3 payload"))
            task_id = str(response.get("taskId") or "").strip()
            if not task_id:
                raise _replication_error("H3_CREATE_AMBIGUOUS", "H3 create omitted taskId; reconcile before retry", category="provider")
            submitted.append({"segment_id": str(item["segment_id"]), "task_id": task_id,
                              "segment_plan_sha256": str(item["segment_plan_sha256"]),
                              "request_sha256": str(item["request_sha256"])})
        return {"status": "ready", "h3_tasks": submitted}


class H3WaitStage:
    """Poll submitted H3 task IDs and publish their verified MP4 results."""

    def __init__(self, *, workflow_client: Any) -> None:
        self.workflow_client = workflow_client

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        tasks = _stage_output(context, "submit_h3_edit").get("h3_tasks")
        if not isinstance(tasks, list) or not tasks:
            raise _replication_error("H3_TASKS_REQUIRED", "H3 wait requires submitted tasks")
        results: list[dict[str, Any]] = []
        for raw in tasks:
            task = _mapping(raw, "H3 task")
            deadline = time.monotonic() + 1800
            while True:
                response = self.workflow_client._post(
                    url=f"{self.workflow_client.base_url}/openapi/v2/query",
                    payload={"taskId": str(task["task_id"])},
                )
                status = str(response.get("status") or "").upper()
                if status == "SUCCESS":
                    break
                if status in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                    raise _replication_error("H3_PROVIDER_FAILED", "H3 provider task failed", category="provider")
                if time.monotonic() >= deadline:
                    raise _replication_error("H3_POLL_TIMEOUT", "H3 provider result is ambiguous", category="provider")
                time.sleep(3)
            videos = [row for row in response.get("results") or [] if isinstance(row, Mapping)
                      and str(row.get("outputType") or "").casefold() in {"mp4", "mov"}
                      and str(row.get("url") or "").startswith("https://")]
            if len(videos) != 1:
                raise _replication_error("H3_RESULT_COUNT_INVALID", "H3 returned an invalid video result count", category="provider")
            data = self.workflow_client._download_file(
                url=str(videos[0]["url"]), timeout_seconds=300, maximum_bytes=512 * 1024 * 1024
            )
            if not data or b"ftyp" not in data[:64]:
                raise _replication_error("H3_RESULT_INVALID", "H3 result is not an MP4", category="provider")
            artifact = context.publish_bytes(
                kind="provider_video", data=data, content_type="video/mp4",
                expected_sha256=hashlib.sha256(data).hexdigest(), metadata={
                    "segment_id": str(task["segment_id"]),
                    "segment_plan_sha256": str(task["segment_plan_sha256"]),
                    "provider_task_id": str(task["task_id"]), "provider_model": "hailuo-h3",
                },
            )
            results.append({"segment_id": str(task["segment_id"]), "artifact": artifact})
        return {"status": "ready", "provider_videos": results}

class SeedancePromptStage(SeedancePromptStage):
    """Continue the Seedance compiler implementation after the H3 stage definitions."""

    @staticmethod
    def _compiler_asset_bindings(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        fields = (
            "replaces_tag", "source_object_descriptor", "target_identity_descriptor", "replacement_scope",
            "preserve_scope", "binding_confidence", "identity_scope", "wardrobe_policy",
            "target_wardrobe_evidence", "source_wardrobe_descriptor",
            "person_asset_profile", "asset_mime_type", "asset_width", "asset_height",
            "identity_subject_count", "asset_layout", "asset_composition",
        )
        result: list[dict[str, Any]] = []
        for item in entries:
            row = {
                "tag": str(item["asset_tag"]),
                "reference": str(item["image_reference"]),
                "role": str(item.get("asset_type") or "visual asset"),
                "asset_type": str(item.get("asset_type") or "visual asset"),
            }
            row.update({field: item[field] for field in fields if field in item})
            result.append(row)
        return result

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
    def _source_person_descriptors(context: Any) -> list[str]:
        """Return stable source-person descriptors in first-appearance order.

        Read from the frozen source content timeline the analysis stage already
        publishes.  A prompt can only say *which* source person an uploaded
        identity replaces if it can name that person with a human-visible trait,
        so internal speaker IDs are only a last-resort fallback.
        """

        try:
            timeline = _read_json_artifact(context, kind="source_content_timeline")
        except ReplicationError:
            return []
        tracks = timeline.get("visible_person_tracks")
        if not isinstance(tracks, Sequence) or isinstance(tracks, (str, bytes, bytearray)):
            return []
        ordered = sorted(
            (track for track in tracks if isinstance(track, Mapping)),
            key=lambda track: (int(track.get("start_ms") or 0), str(track.get("speaker_id") or "")),
        )
        descriptors: list[str] = []
        seen: set[str] = set()
        for track in ordered:
            speaker_id = str(track.get("speaker_id") or "").strip()
            if not speaker_id or speaker_id in seen:
                continue
            seen.add(speaker_id)
            descriptors.append(str(track.get("role") or "").strip() or speaker_id)
        return descriptors

    @staticmethod
    def _reference_roles(context: Any, *, segment_id: str) -> list[dict[str, Any]]:
        """Mirror the immutable Fixed-B upload order in the compiled prompt."""

        roles: list[dict[str, Any]] = []
        model_hashes = (
            _slot_sha256s(context, "new_model_image")[:MAX_MODEL_REFERENCES] if _present(context, "new_model_image") else []
        )
        source_people = SeedancePromptStage._source_person_descriptors(context)
        for model_index in range(len(model_hashes)):
            slot = len(roles) + 1
            roles.append(
                {
                    "slot": slot,
                    "tag": f"@Image{slot}",
                    "kind": "new_model_identity",
                    "subject_label": f"Subject {model_index + 1}",
                    "replaces_source_person": (
                        source_people[model_index] if model_index < len(source_people) else ""
                    ),
                    "role": "fixed new_model_image target truth",
                }
            )
        product_hashes = _slot_sha256s(context, "new_product_image")[:2] if _present(context, "new_product_image") else []
        if product_hashes:
            slot = len(roles) + 1
            roles.append({"slot": slot, "tag": f"@Image{slot}", "role": "fixed new_product_image target truth"})
        storyboard_count = sum(
            1
            for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping)
            and item.get("kind") == "storyboard_image"
            and isinstance(item.get("metadata"), Mapping)
            and (
                item["metadata"].get("segment_id") == segment_id
                or segment_id in (item["metadata"].get("segment_ids") or [])
            )
        )
        if not 1 <= storyboard_count <= 2:
            raise _replication_error("ARTIFACT_NOT_FOUND", "approved storyboard page set is unavailable", category="artifact")
        for page_index in range(1, storyboard_count + 1):
            slot = len(roles) + 1
            roles.append({"slot": slot, "tag": f"@Image{slot}", "role": f"approved storyboard visual control page {page_index}/{storyboard_count}"})
        for _digest in product_hashes[1:]:
            slot = len(roles) + 1
            roles.append({"slot": slot, "tag": f"@Image{slot}", "role": "additional verified new_product_image detail"})
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
                else (
                    "This is an audio-driven song performance: the confirmed on-camera performer visibly sings in exact sync with @Audio1. "
                    "Do not transcribe, quote, invent, or display lyrics; the uploaded audio bytes are the only lyric authority. "
                    if uploaded_audio_kind == "song"
                    else ""
                )
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
    def _is_v2(context: Any) -> bool:
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
        return isinstance(extensions, Mapping) and extensions.get("edit_contract") == "video-edit-v2"

    @staticmethod
    def _format_v2_window(start_ms: int, end_ms: int) -> str:
        def format_ms(value: int) -> str:
            minutes, remainder = divmod(int(value), 60_000)
            seconds, millis = divmod(remainder, 1_000)
            return f"{minutes:02d}:{seconds:02d}.{millis:03d}"

        return f"{format_ms(start_ms)}-{format_ms(end_ms)}"

    @staticmethod
    def _v2_approved_sidecar(context: Any, *, script_sha: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        snapshot = getattr(context, "snapshot", None)
        revision = getattr(snapshot, "current_script_revision", None)
        getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1 or not callable(getter):
            raise _replication_error("APPROVAL_REQUIRED", "v2 prompt compilation requires the approved script sidecar")
        sidecar = getter(context.job_id, revision)
        if (
            not isinstance(sidecar, Mapping)
            or sidecar.get("contract") != "approved-script-lines/v2"
            or sidecar.get("revision") != revision
            or str(sidecar.get("script_sha256") or "").lower() != script_sha
        ):
            raise _replication_error("APPROVAL_STALE", "approved script sidecar is stale for v2 prompt compilation")
        line_contracts = sidecar.get("line_contracts")
        visible_text_locks = sidecar.get("visible_text_locks")
        if not isinstance(line_contracts, list) or not isinstance(visible_text_locks, list):
            raise _replication_error("CONTRACT_INVALID", "approved v2 script sidecar is incomplete")
        if str(sidecar.get("line_contracts_sha256") or "").lower() != _sha(line_contracts):
            raise _replication_error("APPROVAL_STALE", "approved script line contract digest is stale")
        if str(sidecar.get("visible_text_locks_sha256") or "").lower() != _sha(visible_text_locks):
            raise _replication_error("APPROVAL_STALE", "approved visible text lock digest is stale")
        try:
            split_visible_text_locks_by_render_route(visible_text_locks)
        except VisibleTextContractError as exc:
            raise _replication_error("CONTRACT_INVALID", "approved visible text carrier routing is invalid") from exc
        return dict(sidecar), [dict(item) for item in line_contracts if isinstance(item, Mapping)], [dict(item) for item in visible_text_locks if isinstance(item, Mapping)]

    @staticmethod
    def _v2_source_reference(
        context: Any,
        *,
        segment_id: str,
        plan_sha: str,
        start_ms: int,
        end_ms: int,
    ) -> Mapping[str, Any]:
        candidates = [
            item for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping)
            and item.get("kind") == "source_video_reference"
            and isinstance(item.get("metadata"), Mapping)
            and item["metadata"].get("segment_id") == segment_id
        ]
        if len(candidates) != 1:
            raise _replication_error("ARTIFACT_NOT_FOUND", f"v2 source slice for {segment_id} is unavailable", category="artifact")
        descriptor = candidates[0]
        metadata = descriptor["metadata"]
        if (
            str(metadata.get("segment_plan_sha256") or "").lower() != plan_sha
            or metadata.get("start_ms") != start_ms
            or metadata.get("end_ms") != end_ms
        ):
            raise _replication_error("CONTRACT_INVALID", f"v2 source slice lineage for {segment_id} is invalid", category="artifact")
        source_sha = _slot_sha256s(context, "source_video")
        declared_source_sha = str(metadata.get("source_video_sha256") or "").lower()
        if len(source_sha) != 1 or declared_source_sha != source_sha[0]:
            raise _replication_error("ARTIFACT_HASH_MISMATCH", f"v2 source slice for {segment_id} is not bound to source video", category="artifact")
        artifact_id = str(descriptor.get("artifact_id") or "")
        slice_sha = str(descriptor.get("sha256") or "").lower()
        if not artifact_id or _SHA256.fullmatch(slice_sha) is None:
            raise _replication_error("CONTRACT_INVALID", f"v2 source slice descriptor for {segment_id} is invalid", category="artifact")
        return {
            "artifact_id": artifact_id,
            "source_video_sha256": source_sha[0],
            "source_slice_sha256": slice_sha,
            "start_ms": start_ms,
            "end_ms": end_ms,
        }

    def _run_v2(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        snapshot = getattr(context, "snapshot", None)
        script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
        if _SHA256.fullmatch(script_sha) is None:
            raise _replication_error("APPROVAL_REQUIRED", "v2 prompt compilation requires the approved script revision")

        script = self._approved_revision(context, kind="script", digest=script_sha)
        try:
            approved_edit_script = canonicalize_approved_edit_script(script.get("approved_edit_script"))
        except ReplicationError as exc:
            raise _replication_error("CONTRACT_INVALID", "approved v2 script mapping is not canonical") from exc
        _sidecar, line_contracts, visible_text_locks = self._v2_approved_sidecar(context, script_sha=script_sha)
        try:
            generation_surface_text_locks = split_visible_text_locks_by_render_route(visible_text_locks)[
                "generation_surface"
            ]
        except VisibleTextContractError as exc:
            raise _replication_error(
                "CONTRACT_INVALID", "approved visible text carrier routing is invalid"
            ) from exc
        audio_kind, _audio_plan = _v2_audio_route(context)
        try:
            sidecar_script = canonicalize_approved_edit_script(_sidecar.get("approved_edit_script"))
        except ReplicationError as exc:
            raise _replication_error("CONTRACT_INVALID", "approved v2 sidecar mapping is not canonical") from exc
        if sidecar_script != approved_edit_script:
            raise _replication_error("APPROVAL_STALE", "approved v2 sidecar mapping differs from the script artifact")

        plan = _read_json_artifact(context, kind="segment_plan")
        plan_sha = _sha(plan)
        if (
            str(plan.get("approved_script_sha256") or "").lower() != script_sha
            or not isinstance(plan.get("segments"), list)
            or not isinstance(plan.get("source_dynamics_sha256"), str)
        ):
            raise _replication_error("SEGMENT_PLAN_INVALID", "v2 prompt inputs are not bound to the approved plan")
        dynamics_sha = str(plan["source_dynamics_sha256"]).lower()
        dynamics_artifact = _read_json_artifact(context, kind="source_dynamics_analysis", sha256=dynamics_sha)
        stage_dynamics = _mapping(_stage_output(context, "analyze_dynamics").get("source_dynamics_analysis"), "source dynamics analysis")
        if dynamics_artifact.get("source_dynamics_analysis") != stage_dynamics:
            raise _replication_error("CONTRACT_INVALID", "source dynamics artifact differs from the stage output")
        source_dynamics = _mapping(dynamics_artifact.get("source_dynamics_analysis"), "source dynamics analysis")
        raw_cuts = source_dynamics.get("source_cuts")
        if not isinstance(raw_cuts, list) or not raw_cuts:
            raise _replication_error("CONTRACT_INVALID", "v2 prompt inputs contain no source Cut evidence")
        source_cuts: dict[str, dict[str, Any]] = {}
        for raw in raw_cuts:
            cut = _mapping(raw, "source Cut")
            cut_id = str(cut.get("cut_id") or "")
            try:
                start_ms = int(cut["start_ms"]) if cut.get("start_ms") is not None else int(cut["start_us"]) // 1000
                end_ms = int(cut["end_ms"]) if cut.get("end_ms") is not None else (int(cut["end_us"]) + 999) // 1000
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("CONTRACT_INVALID", "source Cut timing is invalid") from exc
            if not cut_id or end_ms <= start_ms or cut_id in source_cuts:
                raise _replication_error("CONTRACT_INVALID", "source Cut identity or timing is invalid")
            source_cuts[cut_id] = {**dict(cut), "cut_id": cut_id, "start_ms": start_ms, "end_ms": end_ms}

        compiler = _load_module("scripts/seedance_prompt_compiler.py", "usfr_v2_seedance_prompt_compiler")
        skill_files = getattr(self.invocation_adapter, "prompt_skill_files", None)
        if not isinstance(skill_files, Mapping) or not skill_files:
            raise _replication_error("CAPABILITY_UNAVAILABLE", "immutable Seedance-20 compiler bytes are unavailable", retryable=True, category="capability")

        canonical_bindings = approved_edit_script["asset_bindings"]
        binding_by_tag = {str(item["asset_tag"]): item for item in canonical_bindings}
        asset_bindings: list[dict[str, Any]] = []
        if canonical_bindings:
            try:
                visual_manifest = _resolve_v2_asset_board_manifest(context)
            except ReplicationError:
                raise
            if len(visual_manifest["entries"]) != len(canonical_bindings):
                raise _replication_error("CONTRACT_INVALID", "asset board manifest does not cover the approved bindings", category="artifact")
            asset_bindings = [
                {
                    **dict(entry),
                    "tag": entry["asset_tag"],
                    "reference": entry["image_reference"],
                    "role": entry["asset_type"],
                }
                for entry in visual_manifest["entries"]
            ]
        compiler_bindings = self._compiler_asset_bindings(asset_bindings)
        binding_mode = select_v2_binding_mode(canonical_bindings)
        if binding_mode == "binding_evidence_required":
            raise _replication_error(
                "SOURCE_OBJECT_BINDING_REQUIRED",
                "every visual replacement requires an explicit source object descriptor, continuous @Image index, replacement scope, preserve scope, and confidence",
                category="artifact",
            )
        if binding_mode == "image_reference_limit_exceeded":
            raise _replication_error(
                "IMAGE_REFERENCE_LIMIT",
                "one Seedance edit supports at most nine independently indexed target images",
                category="input",
            )
        line_by_window: dict[tuple[int, int], Mapping[str, Any]] = {}
        for line in line_contracts:
            timing = _mapping(line.get("time"), "approved line timing")
            try:
                start_ms, end_ms = int(timing["start_ms"]), int(timing["end_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("CONTRACT_INVALID", "approved line timing is invalid") from exc
            exact = str(_mapping(line.get("text"), "approved line text").get("exact") or "").strip()
            if not exact or end_ms <= start_ms or (start_ms, end_ms) in line_by_window:
                raise _replication_error("CONTRACT_INVALID", "approved line contract is invalid")
            line_by_window[(start_ms, end_ms)] = {**dict(line), "start_ms": start_ms, "end_ms": end_ms, "exact_text": exact}

        script_rows = approved_edit_script["change_rows"]
        if audio_kind == "voiceover":
            has_voiceover_binding = False
            for row in script_rows:
                if str(row.get("kind") or "").casefold() != "dialogue":
                    continue
                try:
                    row_start, row_end = int(row["start_ms"]), int(row["end_ms"])
                except (KeyError, TypeError, ValueError):
                    continue
                if (
                    row_start >= 0
                    and row_end > row_start
                    and str(row.get("speaker") or "").strip()
                    and str(row.get("text") or "").strip()
                ):
                    has_voiceover_binding = True
                    break
            if not has_voiceover_binding:
                raise _replication_error(
                    "CONTRACT_INVALID",
                    "voiceover requires an approved speaker, text, and dialogue window",
                    category="audio",
                )
        output_language = (getattr(snapshot, "slots_manifest", {}) or {}).get("output_language")
        outputs: list[dict[str, Any]] = []
        for raw_segment in plan["segments"]:
            segment_row = _mapping(raw_segment, "segment plan row")
            segment_id = str(segment_row.get("segment_id") or "")
            cut_ids = segment_row.get("cut_ids")
            try:
                global_start = int(segment_row["start_ms"])
                global_end = int(segment_row["end_ms"])
                duration_ms = int(segment_row["duration_ms"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _replication_error("SEGMENT_PLAN_INVALID", "v2 segment timing is invalid") from exc
            if not segment_id or not isinstance(cut_ids, list) or not cut_ids or global_end <= global_start or duration_ms != global_end - global_start or duration_ms > 15_000:
                raise _replication_error("SEGMENT_PLAN_INVALID", "v2 segment plan row is invalid")
            for cut_id in cut_ids:
                cut = source_cuts.get(str(cut_id))
                if cut is None or int(cut["start_ms"]) < global_start or int(cut["end_ms"]) > global_end:
                    raise _replication_error("SEGMENT_PLAN_INVALID", f"{segment_id} Cut timing is not source-bound")

            replacements: list[dict[str, Any]] = []
            dialogue_changes: list[dict[str, Any]] = []
            segment_target_changes: list[dict[str, Any]] = []
            for row in script_rows:
                row_start, row_end = int(row["start_ms"]), int(row["end_ms"])
                if row_start < global_start or row_end > global_end:
                    continue
                segment_target_changes.append(dict(row))
                kind = str(row.get("kind") or "").casefold()
                window = self._format_v2_window(row_start, row_end)
                if kind == "replacement":
                    asset_tag = str(row.get("asset_tag") or "")
                    binding = binding_by_tag.get(asset_tag)
                    if binding is None:
                        raise _replication_error("CONTRACT_INVALID", "approved replacement references an unknown asset")
                    replacements.append({
                        "change_id": str(row.get("change_id") or ""),
                        "execution_mode": str(row.get("execution_mode") or "direct_binding"),
                        "window": window,
                        "target": asset_tag,
                        "instruction": str(row.get("instruction") or ""),
                        "asset_type": binding["asset_type"],
                    })
                elif kind == "language":
                    dialogue_changes.append({
                        "window": window,
                        "speaker": str(row.get("speaker") or "approved voice"),
                        "text": str(row.get("text") or ""),
                    })

            for (line_start, line_end), line in line_by_window.items():
                if line_start < global_start or line_end > global_end:
                    continue
                matching_rows = [
                    row for row in script_rows
                    if str(row.get("kind") or "").casefold() == "dialogue"
                    and int(row["start_ms"]) == line_start
                    and int(row["end_ms"]) == line_end
                ]
                if len(matching_rows) != 1 or str(matching_rows[0].get("text") or "") != str(line["exact_text"]):
                    raise _replication_error("APPROVAL_STALE", "approved line text differs from the approved edit script")
                row = matching_rows[0]
                dialogue_changes.append({
                    "window": self._format_v2_window(line_start, line_end),
                    "speaker": str(line.get("speaker") or row.get("speaker") or "approved voice"),
                    "text": str(line["exact_text"]),
                })

            for lock in generation_surface_text_locks:
                try:
                    lock_start, lock_end = int(lock["start_ms"]), int(lock["end_ms"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise _replication_error("CONTRACT_INVALID", "approved visible text timing is invalid") from exc
                if lock_start < global_start or lock_end > global_end:
                    continue
                approved_text = str(lock.get("approved_text") or "").strip()
                if not approved_text:
                    raise _replication_error("CONTRACT_INVALID", "approved visible text is empty")
                replacements.append({
                    "window": self._format_v2_window(lock_start, lock_end),
                    "target": str(lock.get("kind") or lock.get("text_target") or "approved text"),
                    "asset_type": "physical_text",
                    "instruction": f"use the exact approved text {approved_text}",
                })

            continuity_instruction = ""
            state_map = plan.get("inter_segment_state")
            if isinstance(state_map, Mapping):
                previous = None
                for candidate in plan["segments"]:
                    if isinstance(candidate, Mapping) and str(candidate.get("segment_id") or "") == segment_id:
                        break
                    if isinstance(candidate, Mapping):
                        previous = str(candidate.get("segment_id") or "")
                if previous:
                    carry = state_map.get(f"{previous}->{segment_id}")
                    if isinstance(carry, Mapping) and isinstance(carry.get("carry_forward"), list) and carry["carry_forward"]:
                        continuity_instruction = "Continuity: carry forward approved " + ", ".join(str(item) for item in carry["carry_forward"])

            try:
                compiled = compiler.compile_edit_prompt(
                    source_video="@Video1",
                    asset_bindings=compiler_bindings,
                    replacements=replacements,
                    dialogue_changes=dialogue_changes,
                    output_language=output_language,
                    segment_window_ms=(global_start, global_end),
                )
            except Exception as exc:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", f"Seedance-20 compiler rejected {segment_id}") from exc
            expected_operational_change_ids = [
                str(item.get("change_id") or "")
                for item in replacements
                if str(item.get("execution_mode") or "direct_binding").casefold() == "adapt_action"
            ]
            if compiled.get("operational_change_ids") != expected_operational_change_ids:
                raise _replication_error(
                    "PROMPT_INTEGRITY_FAILED",
                    f"Seedance-20 compiler dropped an approved operational action in {segment_id}",
                )
            if continuity_instruction:
                compiled = dict(compiled)
                compiled["prompt"] = f"{compiled['prompt']} {continuity_instruction}."
                compiled["continuity_instruction"] = continuity_instruction
            audio_directive = _v2_audio_directive(audio_kind, dialogue_changes=dialogue_changes)
            if audio_directive:
                compiled = dict(compiled)
                compiled["prompt"] = f"{compiled['prompt']} {audio_directive}"
                compiled["audio_directive"] = audio_directive
            if binding_mode == "provider_only_multi_object_binding":
                compiled = dict(compiled)
                receipt = dict(_mapping(
                    compiled.get("provider_only_binding_receipt"),
                    "provider-only binding receipt",
                ))
                receipt["prompt_sha256"] = hashlib.sha256(
                    str(compiled["prompt"]).encode("utf-8")
                ).hexdigest()
                compiled["provider_only_binding_receipt"] = _validate_provider_only_binding_receipt(
                    receipt,
                    prompt=str(compiled["prompt"]),
                    image_tags=[str(item["reference"]) for item in compiler_bindings],
                )
                compiled["prompt_binding_sha256"] = receipt["prompt_sha256"]
            source_reference = self._v2_source_reference(
                context,
                segment_id=segment_id,
                plan_sha=plan_sha,
                start_ms=global_start,
                end_ms=global_end,
            )
            outputs.append({
                "segment_id": segment_id,
                "start_ms": global_start,
                "end_ms": global_end,
                "duration_ms": duration_ms,
                "cut_ids": [str(cut_id) for cut_id in cut_ids],
                "compiled_prompt": compiled,
                "segment_plan_sha256": plan_sha,
                "source_video_sha256": source_reference["source_video_sha256"],
                "source_slice_sha256": source_reference["source_slice_sha256"],
                "source_video_reference_artifact_id": source_reference["artifact_id"],
                "asset_bindings": [dict(item) for item in asset_bindings],
                "target_changes": segment_target_changes,
                "audio_kind": audio_kind,
                "audio_urls": [],
                "binding_mode": binding_mode,
                "provider_only": binding_mode == "provider_only_multi_object_binding",
            })
        envelope = {
            "schema_version": "seedance-input-contract/v1",
            "edit_contract": "video-edit-v2",
            "segment_plan": plan,
            "segment_plan_sha256": plan_sha,
            "segments": outputs,
        }
        published = _publish_json(context, kind="seedance_input_contract", value=envelope)
        return {"status": "ready", "seedance_input_contract": envelope, "published_artifacts": [published]}

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
            if route.get("mode") == "audio_driven_uploaded_song_lip_sync":
                performance_contract = _read_json_artifact(context, kind="performance_line_contract")
                raw_performance = performance_contract.get("cuts")
                raw_segments = plan.get("segments")
                eligible = route.get("eligible_source_windows")
                if not isinstance(raw_performance, list) or not isinstance(raw_segments, list) or not isinstance(eligible, list):
                    return {}
                approved_by_id = {str(line.get("line_id") or ""): line for line in line_contracts}
                performance_by_id = {str(line.get("line_id") or ""): line for line in raw_performance if isinstance(line, Mapping)}
                eligible_by_id = {str(line.get("line_id") or ""): line for line in eligible if isinstance(line, Mapping)}
                result: dict[str, list[dict[str, Any]]] = {}
                for segment in raw_segments:
                    if not isinstance(segment, Mapping) or not isinstance(segment.get("cut_ids"), list):
                        return {}
                    segment_id = str(segment.get("segment_id") or "")
                    start_ms, end_ms = segment.get("start_ms"), segment.get("end_ms")
                    if not segment_id or not isinstance(start_ms, int) or not isinstance(end_ms, int):
                        return {}
                    validated: list[dict[str, Any]] = []
                    for line_id, window in eligible_by_id.items():
                        approved = approved_by_id.get(line_id)
                        performance = performance_by_id.get(line_id)
                        if not isinstance(approved, Mapping) or not isinstance(performance, Mapping):
                            continue
                        assignment = performance.get("speaker_assignment")
                        approved_assignment = approved.get("speaker_assignment")
                        source_time = performance.get("source_time")
                        if (
                            performance.get("content_type") != "sung"
                            or not isinstance(assignment, Mapping)
                            or assignment.get("status") != "CONFIRMED"
                            or assignment != approved_assignment
                            or assignment.get("speaker_id") != window.get("speaker_id")
                            or source_time != {"start_ms": window.get("start_ms"), "end_ms": window.get("end_ms")}
                            or performance.get("cut_id") not in segment["cut_ids"]
                            or int(window["start_ms"]) >= end_ms
                            or start_ms >= int(window["end_ms"])
                        ):
                            continue
                        validated.append({
                            "line_id": line_id,
                            "cut_id": performance.get("cut_id"),
                            "source_time": dict(source_time),
                            "speaker_assignment": dict(assignment),
                            "audio_reference": "@Audio1",
                        })
                    if validated:
                        result[segment_id] = validated
                return result
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
            untimed_text: list[str] = []
            lyric_mode: str | None = None
            for raw in raw_lyrics:
                if not isinstance(raw, Mapping):
                    return {}
                text = str(raw.get("text") or "").strip()
                if not text:
                    return {}
                current_mode = "timed" if {"start_ms", "end_ms"}.issubset(raw) else "untimed"
                if lyric_mode is not None and current_mode != lyric_mode:
                    return {}
                lyric_mode = current_mode
                if current_mode == "untimed":
                    untimed_text.append(text)
                    continue
                try:
                    observed.append((int(raw["start_ms"]), int(raw["end_ms"]), text))
                except (KeyError, TypeError, ValueError):
                    return {}
            expected = [
                (
                    line["source_time"]["start_ms"],
                    line["source_time"]["end_ms"],
                    line["exact_sung_text"],
                )
                for line in canonical_performance
            ]
            if lyric_mode == "timed":
                if observed != expected:
                    return {}
            elif lyric_mode == "untimed":
                approved_text = " ".join(
                    " ".join(str(line["exact_sung_text"]).split()) for line in canonical_performance
                )
                transcript_text = " ".join(" ".join(text.split()) for text in untimed_text)
                if transcript_text != approved_text:
                    return {}
            else:
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
        if self._is_v2(context):
            return self._run_v2(context=context, input_artifacts=input_artifacts)
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
        try:
            visible_text_routes = split_visible_text_locks_by_render_route(script.get("visible_text_locks") or [])
        except VisibleTextContractError as exc:
            raise _replication_error("CONTRACT_INVALID", "approved visible text carrier routing is invalid") from exc
        surface_text_locks = visible_text_routes["generation_surface"]
        board_cuts = {str(item.get("cut_id") or ""): dict(item) for item in storyboard.get("cuts") or [] if isinstance(item, Mapping)}
        if not script_cuts or set(script_cuts) != set(board_cuts):
            raise _replication_error("PROMPT_INTEGRITY_FAILED", "approved script and storyboard Cut coverage differs")
        lines = self._approval_lines(context)
        uploaded_audio = (
            _uploaded_audio_classification(context)
            if self._uploaded_music_present(context)
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
                cut_surface_text = [lock for lock in surface_text_locks if str(cut_id) in lock["cut_ids"]]
                surface_text_instruction = " ".join(
                    (
                        f"Exact scene-surface text {json.dumps(lock['approved_text'], ensure_ascii=False)} is centered/bound as specified on "
                        f"physical carrier {lock['placement']['carrier_id']} ({lock['placement']['surface_relation']}); "
                        f"it {lock['placement']['motion_behavior']}. The text is part of the material surface: it follows perspective, "
                        "hand motion, bending, folding, occlusion and tearing, and never floats or stays screen-fixed."
                    )
                    for lock in cut_surface_text
                )
                shots.append({
                    "shot_id": str(cut_id), "start_ms": start_ms, "end_ms": end_ms,
                    "shot_scale": str(board.get("composition") or "approved composition"),
                    "scene": str(cut.get("scene") or "approved source scene"),
                    "camera": str(cut.get("camera") or board.get("camera") or "approved camera"),
                    "lighting": "match the approved storyboard lighting and source evidence",
                    "performance": str(cut.get("delivery") or "natural source-equivalent delivery"),
                    "action": " ".join(filter(None, (str(cut.get("action") or "complete the approved action"), surface_text_instruction))),
                    "endpoint": str(board.get("continuity") or "reach the approved Cut endpoint"),
                    "product_or_ui_truth": " ".join(filter(None, (str(cut.get("visual") or "use only approved target evidence"), surface_text_instruction))),
                    "commercial_proof": str((cut.get("selling_point") or {}).get("proof", {}).get("evidence_id") or "approved target evidence"),
                    "transition": "match the source Cut transition", "continuity": str(board.get("continuity") or "preserve continuity"),
                    "audio": " ".join(filter(None, (str(cut.get("dialogue") or "no dialogue"), uploaded_music_instruction))),
                    "factor_ids": [f"{cut_id}.scene", f"{cut_id}.camera", f"{cut_id}.action", f"{cut_id}.audio"]
                    + ([f"{cut_id}.scene_surface_text"] if cut_surface_text else []),
                })
            local_lines = [line for line in lines if str(line.get("cut_id") or "") in set(cut_ids)]
            validated_uploaded_song = uploaded_song_performance.get(segment_id, [])
            local_performance = [] if uploaded_audio_kind == "song" else source_song_performance.get(segment_id, [])
            expected_sung_lines = [
                line for line in local_lines if line.get("content_type") == "sung"
            ] if uploaded_audio_kind != "non_song" else []
            validated_count = len(validated_uploaded_song) if uploaded_audio_kind == "song" else len(local_performance)
            if expected_sung_lines and validated_count != len(expected_sung_lines):
                raise _replication_error(
                    "PERFORMANCE_LINE_CONTRACT_REQUIRED",
                    f"{segment_id} has confirmed sung lines without a source-verified performer and timing contract",
                )
            segment = {
                "segment_id": segment_id,
                "duration_ms": duration_ms,
                "output_global_start_ms": global_start,
                "cut_ids": list(cut_ids),
                "opening_state": str(board_cuts[str(cut_ids[0])].get("composition") or "approved opening storyboard state"),
                "reference_roles": self._reference_roles(context, segment_id=segment_id),
                "shots": shots,
                "locks": [
                    "preserve approved Cut order",
                    "preserve approved character and product evidence",
                    "scene-surface text must be written explicitly into the Seedance Cut prompt and remain physically attached to its carrier",
                ],
                "negative_constraints": ["no unapproved text", "no UI or tail media generation", "no generic quality filler"],
                "no_speech_contracts": [] if local_lines and uploaded_audio_kind != "non_song" else self._no_speech([str(item) for item in cut_ids]),
            }
            try:
                artifact = compiler.compile_prompt(
                    segment=segment,
                    line_contracts=[] if uploaded_audio_kind == "non_song" else local_lines,
                    performance_lines=local_performance,
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
            outputs.append({"segment_id": segment_id, "compiled_prompt": artifact, "segment_plan_sha256": plan_sha})
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

    _ffmpeg_source_segment = staticmethod(_ffmpeg_source_segment)

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
    def _storyboard_descriptors(context: Any, *, segment_id: str) -> tuple[Mapping[str, Any], ...]:
        revision = getattr(getattr(context, "snapshot", None), "current_storyboard_revision", None)
        matches = []
        for artifact in (getattr(context, "artifacts", ()) or ()):
            if not isinstance(artifact, Mapping) or artifact.get("kind") != "storyboard_image":
                continue
            metadata = artifact.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            segment_ids = metadata.get("segment_ids")
            if metadata.get("segment_id") != segment_id and (
                not isinstance(segment_ids, list) or segment_id not in segment_ids
            ):
                continue
            if isinstance(revision, int) and metadata.get("storyboard_revision") != revision:
                continue
            matches.append(artifact)
        matches.sort(key=lambda item: int(((item.get("metadata") or {}).get("storyboard_page") or 1)))
        if not 1 <= len(matches) <= 2:
            raise _replication_error("ARTIFACT_NOT_FOUND", f"one or two approved storyboard pages are required for {segment_id}", category="artifact")
        for descriptor in matches:
            artifact_id = str(descriptor.get("artifact_id") or "")
            digest = str(descriptor.get("sha256") or "").lower()
            if not artifact_id or _SHA256.fullmatch(digest) is None:
                raise _replication_error("CONTRACT_INVALID", "storyboard artifact descriptor is invalid", category="artifact")
        return tuple(matches)

    def _upload_storyboards(self, context: Any, *, segment_id: str) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        for descriptor in self._storyboard_descriptors(context, segment_id=segment_id):
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
                raise _replication_error("CAPABILITY_UNAVAILABLE", "storyboard upload failed", retryable=True, category="provider") from exc
            if not isinstance(url, str) or not url.strip():
                raise _replication_error("CAPABILITY_UNAVAILABLE", "storyboard upload returned no URL", retryable=True, category="provider")
            uploaded.append({"descriptor": descriptor, "url": url.strip()})
        return uploaded

    @staticmethod
    def _storyboard_descriptor(context: Any, *, segment_id: str) -> Mapping[str, Any]:
        """Compatibility accessor for callers that prove a one-page board."""

        descriptors = SeedanceAuditStage._storyboard_descriptors(context, segment_id=segment_id)
        if len(descriptors) != 1:
            raise _replication_error("CONTRACT_INVALID", "single-page storyboard accessor cannot select a multi-page set")
        return descriptors[0]

    def _upload_storyboard(self, context: Any, *, segment_id: str) -> str:
        """Compatibility accessor for a one-page board; production uses the set."""

        uploaded = self._upload_storyboards(context, segment_id=segment_id)
        if len(uploaded) != 1:
            raise _replication_error("CONTRACT_INVALID", "single-page storyboard upload cannot select a multi-page set")
        return str(uploaded[0]["url"])

    def _target_reference_urls(self, context: Any, *, prompt: str) -> tuple[list[str], list[dict[str, str]]]:
        urls: list[str] = []
        target_changes: list[dict[str, str]] = []
        # Continuous present-role order: model, product/App, storyboard pages.
        for slot_id, maximum in (("new_model_image", MAX_MODEL_REFERENCES), ("new_product_image", 2)):
            if not _present(context, slot_id):
                continue
            hashes = _slot_sha256s(context, slot_id)
            for index in range(min(maximum, len(hashes))):
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
    def _image_reference_binding(
        *,
        payload: Mapping[str, Any],
        segment: Mapping[str, Any],
        storyboards: Sequence[Mapping[str, Any]],
        target_entries: Sequence[Mapping[str, str]],
    ) -> dict[str, Any]:
        cut_ids = [str(value) for value in segment.get("cut_ids") or [] if isinstance(value, str) and value]
        if not cut_ids:
            raise _replication_error("SEGMENT_PLAN_INVALID", "image reference binding requires segment Cut scope")
        if not 1 <= len(storyboards) <= 2:
            raise _replication_error("CONTRACT_INVALID", "image reference binding requires one or two storyboard pages")
        manifest_sha = str(storyboards[0].get("storyboard_manifest_sha256") or "").lower()
        if _SHA256.fullmatch(manifest_sha) is None or any(
            str(board.get("storyboard_manifest_sha256") or "").lower() != manifest_sha
            for board in storyboards
        ):
            raise _replication_error("CONTRACT_INVALID", "approved storyboard set digest is invalid")
        ordered_entries: list[dict[str, Any]] = []
        model = [dict(item) for item in target_entries if item.get("kind") == "new_model_image"]
        products = [dict(item) for item in target_entries if item.get("kind") == "new_product_image"]
        for item in model:
            item["role"] = "new_model_identity"
            item["purpose"] = "replace model identity only"
            ordered_entries.append(item)
        if products:
            primary = products.pop(0)
            primary["role"] = "product_or_app_truth"
            primary["purpose"] = "lock product or App truth"
            ordered_entries.append(primary)
        for page_index, storyboard in enumerate(storyboards, start=1):
            ordered_entries.append(
                {
                    "role": "director_storyboard",
                    "artifact_name": Path(str(storyboard.get("logical_name") or f"storyboard-page-{page_index}.png")).name,
                    "sha256": str(storyboard.get("sha256") or "").lower(),
                    "url": str(storyboard.get("url") or ""),
                    "page": page_index,
                    "cut_ids": list(storyboard.get("page_cut_ids") or cut_ids),
                    "approval_set_sha256": manifest_sha,
                    "purpose": f"approved director storyboard page {page_index}/{len(storyboards)}",
                }
            )
        for item in products:
            item["role"] = "additional_reference"
            item["purpose"] = "additional verified product detail reference"
            ordered_entries.append(item)
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(ordered_entries, start=1):
            rows.append(
                {
                    "image_index": index,
                    "tag": f"@Image{index}",
                    "role": item["role"],
                    "artifact_name": str(item.get("artifact_name") or f"{item.get('kind', 'reference')}-{index}.png"),
                    "sha256": str(item.get("sha256") or "").lower(),
                    "url": str(item.get("url") or ""),
                    "cut_ids": list(item.get("cut_ids") or cut_ids),
                    "page": item.get("page"),
                    "approval_set_sha256": item.get("approval_set_sha256"),
                    "purpose": str(item["purpose"]),
                }
            )
        binding = {
            "schema_version": "usfr-multimodal-reference-binding/v2",
            "ordered_image_urls": [row["url"] for row in rows],
            "approval_set_sha256": manifest_sha,
            "image_bindings": rows,
            "slot_policy": "continuous-present-role-order/v1",
            "forbidden_artifact_names": ["seedance_execution_carrier.png"],
        }
        if list(payload.get("imageUrls") or []) != binding["ordered_image_urls"]:
            raise _replication_error("PROMPT_INTEGRITY_FAILED", "payload image order differs from the compiled image binding")
        try:
            validate_image_reference_binding(payload, binding)
        except RunningHubStandardPayloadError as exc:
            raise _replication_error("PROMPT_INTEGRITY_FAILED", "multimodal image binding is invalid") from exc
        return binding

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
        segment_ids = metadata.get("segment_ids") if isinstance(metadata, Mapping) else None
        if (
            not artifact_id
            or not object_key
            or _SHA256.fullmatch(digest) is None
            or not isinstance(metadata, Mapping)
            or (
                metadata.get("segment_id") != segment_id
                and (not isinstance(segment_ids, list) or segment_id not in segment_ids)
            )
            or not isinstance(metadata.get("storyboard_revision"), int)
            or isinstance(metadata.get("storyboard_revision"), bool)
            or int(metadata["storyboard_revision"]) < 1
            or any(_SHA256.fullmatch(str(metadata.get(key) or "").lower()) is None for key in required_metadata)
        ):
            raise _replication_error("CONTRACT_INVALID", "approved storyboard lineage metadata is incomplete", category="artifact")
        targets = metadata.get("replacement_target_sha256s")
        lock_ids = metadata.get("visible_text_lock_ids")
        page_cut_ids = metadata.get("page_cut_ids")
        page_index = metadata.get("storyboard_page", 1)
        page_count = metadata.get("storyboard_page_count", 1)
        segment_cut_ids = [str(value) for value in segment.get("cut_ids") or []]
        scoped_page_cut_ids = [str(value) for value in page_cut_ids or [] if str(value) in set(segment_cut_ids)]
        if (
            not isinstance(targets, list)
            or any(_SHA256.fullmatch(str(value).lower()) is None for value in targets)
            or not isinstance(lock_ids, list)
            or any(not isinstance(value, str) or not value.strip() for value in lock_ids)
            or len(set(lock_ids)) != len(lock_ids)
            or not isinstance(page_cut_ids, list)
            or not page_cut_ids
            or not scoped_page_cut_ids
            or page_count not in {1, 2}
            or not isinstance(page_index, int)
            or not 1 <= page_index <= page_count
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
            if not segment_cut_ids:
                raise _replication_error("SEGMENT_PLAN_INVALID", "storyboard segment Cut coverage is invalid")
            for cut_id in scoped_page_cut_ids:
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
                for lock in StoryboardStage._segment_visible_text_locks(
                    locks,
                    segment={**dict(segment), "cut_ids": list(page_cut_ids)},
                )
            ]
            if list(lock_ids) != expected_lock_ids:
                raise _replication_error("CONTRACT_INVALID", "approved storyboard visible text placement is incomplete", category="artifact")

        return {
            "artifact_id": artifact_id,
            "object_key": object_key,
            "kind": "storyboard_image",
            "sha256": digest,
            "segment_id": segment_id,
            "logical_name": str(metadata.get("logical_name") or ""),
            "page": int(page_index),
            "page_count": int(page_count),
            "page_cut_ids": [str(value) for value in page_cut_ids],
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
        image_reference_binding: Mapping[str, Any],
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
            "image_reference_binding_sha256": image_reference_binding_sha256(image_reference_binding),
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
        image_reference_binding: Mapping[str, Any],
        source_artifact: Mapping[str, Any],
        source_url: str,
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
            "schema_version": "seedance-final-reference-lineage/v2",
            "segment_id": segment_id,
            "segment_plan_sha256": plan_sha256,
            "ordered_image_urls": list(payload.get("imageUrls") or []),
            "ordered_video_urls": list(payload.get("videoUrls") or []),
            "image_reference_binding": dict(image_reference_binding),
            "source_reference": source_reference,
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
        audio_kind: str = "background_music",
        v2: bool = False,
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        if audio_kind == "voiceover":
            return self._voiceover_reference(
                context,
                segment=segment,
                plan_sha256=plan_sha256,
                v2=v2,
            )
        if audio_kind != "background_music":
            return None
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
                "audio_kind": audio_kind,
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
            "schema_version": "usfr-background-music-reference/v2" if v2 else "usfr-background-music-reference/v1",
            "url": url.strip(),
            **({"audio_kind": "background_music"} if v2 else {}),
            "source_audio_sha256": str(hashes[0]).lower(),
            "source_slice_sha256": slice_sha256,
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "segment_plan_sha256": plan_sha256,
            "replacement_timing_policy": "source_music_cut_in_out_exact",
            "source_music_windows": source_music_windows,
        }
        receipt = self._audio_reference_artifact_receipt_v2(published, binding) if v2 else self._audio_reference_artifact_receipt(published, binding)
        return url.strip(), binding, published, receipt

    def _voiceover_reference(
        self,
        context: Any,
        *,
        segment: Mapping[str, Any],
        plan_sha256: str,
        v2: bool,
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        if not v2:
            raise _replication_error("CONTRACT_INVALID", "voiceover reference is v2-only", category="audio")
        extensions = getattr(getattr(context, "snapshot", None), "slots_manifest", {}).get("extensions", {})
        music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
        if not isinstance(music, Mapping):
            raise _replication_error("INPUT_SLOT_INVALID", "voiceover upload evidence is missing", category="input")
        values, hashes, metadata = music.get("values"), music.get("sha256"), music.get("metadata")
        if not isinstance(values, list) or len(values) != 1 or not isinstance(hashes, list) or len(hashes) != 1 or not isinstance(metadata, list) or len(metadata) != 1:
            raise _replication_error("INPUT_SLOT_INVALID", "voiceover immutable upload evidence is invalid", category="input")
        source_sha = str(hashes[0] or "").lower()
        if _SHA256.fullmatch(source_sha) is None:
            raise _replication_error("INPUT_SLOT_INVALID", "voiceover upload hash is invalid", category="input")
        segment_id = str(segment.get("segment_id") or "").strip()
        start_ms, end_ms = int(segment["start_ms"]), int(segment["end_ms"])
        with context.materialize_extension("background_music") as source:
            data = Path(source.path).read_bytes()
            if hashlib.sha256(data).hexdigest() != source_sha:
                raise _replication_error("ARTIFACT_HASH_MISMATCH", "voiceover upload bytes differ from immutable evidence", category="artifact")
            try:
                url = self.media_uploader.upload_media(Path(source.path))
            except Exception as exc:
                raise _replication_error("CAPABILITY_UNAVAILABLE", "voiceover reference upload failed", retryable=True, category="provider") from exc
            if not isinstance(url, str) or not url.strip():
                raise _replication_error("CAPABILITY_UNAVAILABLE", "voiceover reference upload returned no URL", retryable=True, category="provider")
            published = context.publish_bytes(
                kind="voiceover_reference",
                data=data,
                content_type=str(music.get("content_type") or "audio/wav"),
                expected_sha256=source_sha,
                metadata={
                    "audio_kind": "voiceover",
                    "source_audio_sha256": source_sha,
                    "segment_id": segment_id,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "segment_plan_sha256": plan_sha256,
                    "reference_scope": "approved_voiceover_full_asset",
                },
            )
        binding = {
            "schema_version": "usfr-voiceover-reference/v1",
            "audio_kind": "voiceover",
            "url": url.strip(),
            "source_audio_sha256": source_sha,
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "segment_plan_sha256": plan_sha256,
            "reference_scope": "approved_voiceover_full_asset",
        }
        receipt = {
            "schema_version": "usfr-voiceover-artifact-receipt/v1",
            "artifact_id": str(published["artifact_id"]),
            "object_key": str(published["object_key"]),
            "kind": "voiceover_reference",
            "sha256": source_sha,
            "audio_kind": "voiceover",
            "source_audio_sha256": source_sha,
            "segment_id": segment_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "segment_plan_sha256": plan_sha256,
            "reference_scope": "approved_voiceover_full_asset",
        }
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

    @staticmethod
    def _audio_reference_artifact_receipt_v2(
        published: Mapping[str, Any], binding: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Project the explicit v2 background-music route into a receipt."""

        if binding.get("schema_version") != "usfr-background-music-reference/v2" or binding.get("audio_kind") != "background_music":
            raise _replication_error(
                "ARTIFACT_INVALID",
                "v2 background-music receipt requires the explicit audio kind",
                category="artifact",
            )
        receipt = SeedanceAuditStage._audio_reference_artifact_receipt(published, binding)
        receipt["schema_version"] = "usfr-background-music-artifact-receipt/v2"
        receipt["audio_kind"] = "background_music"
        return receipt

    def _v2_published_source_reference(
        self, *, context: Any, item: Mapping[str, Any]
    ) -> tuple[str, str, str, bool]:
        artifact_id = str(item.get("source_video_reference_artifact_id") or "").strip()
        declared_slice_sha = str(item.get("source_slice_sha256") or "").lower()
        if not artifact_id or _SHA256.fullmatch(declared_slice_sha) is None:
            raise _replication_error(
                "CONTRACT_INVALID",
                "v2 source reference must name a published artifact and SHA",
                category="artifact",
            )
        matches = [
            artifact
            for artifact in (getattr(context, "artifacts", ()) or ())
            if isinstance(artifact, Mapping)
            and artifact.get("kind") == "source_video_reference"
            and str(artifact.get("artifact_id") or "") == artifact_id
        ]
        if len(matches) != 1:
            raise _replication_error(
                "ARTIFACT_NOT_FOUND",
                "v2 source reference is not a unique published artifact",
                category="artifact",
            )
        descriptor = matches[0]
        descriptor_sha = str(descriptor.get("sha256") or "").lower()
        metadata = descriptor.get("metadata")
        if (
            descriptor_sha != declared_slice_sha
            or not isinstance(metadata, Mapping)
            or str(metadata.get("source_video_sha256") or "").lower()
            != str(item.get("source_video_sha256") or "").lower()
            or str(metadata.get("segment_id") or "") != str(item.get("segment_id") or "")
            or str(metadata.get("segment_plan_sha256") or "").lower()
            != str(item.get("segment_plan_sha256") or "").lower()
            or metadata.get("start_ms") != item.get("start_ms")
            or metadata.get("end_ms") != item.get("end_ms")
        ):
            raise _replication_error(
                "CONTRACT_INVALID",
                "v2 source reference lineage differs from the submitted segment",
                category="artifact",
            )
        source_sha256s = _slot_sha256s(context, "source_video")
        if len(source_sha256s) != 1 or source_sha256s[0] != str(metadata["source_video_sha256"]).lower():
            raise _replication_error(
                "ARTIFACT_HASH_MISMATCH",
                "v2 source reference is not bound to the current source upload",
                category="artifact",
            )
        try:
            with context.materialize_artifact(
                "source_video_reference",
                artifact_id=artifact_id,
                sha256=declared_slice_sha,
            ) as media:
                path = Path(media.path)
                data = path.read_bytes()
        except ReplicationError:
            raise
        except Exception as exc:
            raise _replication_error(
                "ARTIFACT_NOT_FOUND",
                "v2 source reference could not be materialized",
                category="artifact",
            ) from exc
        if hashlib.sha256(data).hexdigest() != declared_slice_sha or b"ftyp" not in data[:64]:
            raise _replication_error(
                "ARTIFACT_HASH_MISMATCH",
                "v2 source reference bytes do not match the published artifact",
                category="artifact",
            )
        source_duration_ms = metadata.get("source_duration_ms")
        full_source_evidence = (
            declared_slice_sha == source_sha256s[0]
            and isinstance(source_duration_ms, int)
            and not isinstance(source_duration_ms, bool)
            and int(item.get("start_ms") or -1) == 0
            and int(item.get("end_ms") or -1) == source_duration_ms
            and 0 < source_duration_ms <= 15_000
        )
        if declared_slice_sha == source_sha256s[0] and not full_source_evidence:
            raise _replication_error(
                "SOURCE_SLICE_SHA_INVALID",
                "equal source and slice SHA requires published evidence for the complete source duration",
                category="artifact",
            )
        object_key = str(descriptor.get("object_key") or "").strip()
        if object_key:
            upload_path = Path(getattr(context, "work_dir", path)) / Path(object_key).name
            if upload_path != path:
                upload_path.write_bytes(data)
                path = upload_path
        try:
            url = self.media_uploader.upload_media(path)
        except Exception as exc:
            raise _replication_error(
                "CAPABILITY_UNAVAILABLE",
                "v2 source reference upload failed",
                retryable=True,
                category="provider",
            ) from exc
        try:
            actual_url = validate_public_https_url(url)
        except Exception as exc:
            raise _replication_error(
                "CONTRACT_INVALID",
                "v2 source reference upload returned an invalid URL",
                category="provider",
            ) from exc
        return actual_url, source_sha256s[0], declared_slice_sha, full_source_evidence

    @staticmethod
    def _v2_published_board_url(
        context: Any, *, binding: Mapping[str, Any]
    ) -> str:
        manifest = _resolve_v2_asset_board_manifest(context)
        if manifest:
            manifest_entries = manifest["entries"]
            matches = [
                entry for entry in manifest_entries
                if entry.get("asset_tag") == binding.get("asset_tag")
                and entry.get("image_reference") == binding.get("image_reference")
            ]
            if len(matches) != 1:
                raise _replication_error("CONTRACT_INVALID", "v2 segment asset binding is not a canonical manifest binding", category="artifact")
            return str(matches[0]["board_url"])
        raise _replication_error(
            "ARTIFACT_NOT_FOUND",
            "v2 visual asset binding cannot use a segment-supplied board receipt without the canonical manifest",
            category="artifact",
        )

    @staticmethod
    def _v2_approved_target_changes(
        context: Any,
        *,
        target_changes: Sequence[Mapping[str, Any]],
        segment_start_ms: int | None = None,
        segment_end_ms: int | None = None,
    ) -> tuple[list[dict[str, Any]], str | None, str | None]:
        snapshot = getattr(context, "snapshot", None)
        revision = getattr(snapshot, "current_script_revision", None)
        approved_script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
        store = getattr(context, "job_store", None)
        getter = getattr(store, "get_script_approval", None)
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or _SHA256.fullmatch(approved_script_sha) is None
            or not callable(getter)
        ):
            if not target_changes:
                return [], None, None
            raise _replication_error(
                "APPROVAL_REQUIRED",
                "v2 target changes require the current approved script sidecar",
            )
        approval = getter(context.job_id, revision)
        if not isinstance(approval, Mapping):
            raise _replication_error(
                "APPROVAL_REQUIRED",
                "v2 target changes have no approved script sidecar",
            )
        if approval.get("contract") != "approved-script-lines/v2":
            raise _replication_error(
                "APPROVAL_REQUIRED",
                "v2 target changes require approved-script-lines/v2",
            )
        try:
            approved_edit_script = canonicalize_approved_edit_script(approval.get("approved_edit_script"))
        except ReplicationError as exc:
            raise _replication_error(
                "CONTRACT_INVALID",
                "approved script change rows are not canonical",
            ) from exc
        _read_json_artifact(context, kind="script_revision", sha256=approved_script_sha)
        derived = [
            dict(row)
            for row in approved_edit_script["change_rows"]
            if (
                segment_start_ms is None
                or segment_end_ms is None
                or int(row["start_ms"]) >= segment_start_ms
                and int(row["end_ms"]) <= segment_end_ms
            )
        ]
        normalized = [dict(item) for item in target_changes]
        if normalized and normalized != derived:
            raise _replication_error(
                "PROMPT_INTEGRITY_FAILED",
                "v2 target changes must be derived from the approved script artifact",
            )
        if str(approval.get("script_sha256") or "").lower() != approved_script_sha:
            raise _replication_error(
                "CONTRACT_INVALID",
                "v2 target changes use a stale script approval",
            )
        return (derived, _sha(derived) if derived else None, approved_script_sha)

    def _run_v2_edit_contract(
        self, *, context: Any, contract: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Audit v2 through the existing Seedance audit boundary."""

        compiler = _load_module(
            "scripts/seedance_prompt_compiler.py",
            "usfr_v2_seedance_prompt_compiler",
        )
        rows = contract.get("segments")
        if not isinstance(rows, list) or not rows:
            raise _replication_error(
                "PROMPT_INTEGRITY_FAILED",
                "v2 edit contract contains no segments",
            )
        audio_kind, _audio_plan = _v2_audio_route(context)
        audited: list[dict[str, Any]] = []
        for raw in rows:
            item = _mapping(raw, "v2 edit segment")
            segment_id = str(item.get("segment_id") or "").strip()
            prompt_artifact = _mapping(item.get("compiled_prompt"), "v2 compiled prompt")
            prompt = prompt_artifact.get("prompt")
            if not segment_id or not isinstance(prompt, str) or not prompt.strip():
                raise _replication_error(
                    "PROMPT_INTEGRITY_FAILED",
                    "v2 edit segment prompt is incomplete",
                )
            raw_bindings = item.get("asset_bindings") or []
            if not isinstance(raw_bindings, list):
                raise _replication_error(
                    "PROMPT_INTEGRITY_FAILED",
                    "v2 asset bindings must be a list",
                )
            raw_visual_bindings = [
                value for value in raw_bindings
                if isinstance(value, Mapping)
                and str(value.get("asset_type") or "").casefold() in {"model", "garment", "scene", "product", "app"}
            ]
            visual_manifest: Mapping[str, Any] | None = None
            if raw_visual_bindings:
                visual_manifest = _resolve_v2_asset_board_manifest(context)
                if len(raw_visual_bindings) != len(visual_manifest["entries"]):
                    raise _replication_error("PROMPT_INTEGRITY_FAILED", "v2 prompt asset bindings do not cover the canonical manifest")
            board_inputs = [
                {
                    "tag": entry["asset_tag"],
                    "asset_type": entry["asset_type"],
                    "board_url": entry["board_url"],
                    "receipt": entry["receipt"],
                }
                for entry in (visual_manifest["entries"] if visual_manifest is not None else [])
            ]
            try:
                bindings = compiler.build_asset_reference_bindings(
                    board_inputs,
                    approved_asset_bindings=(visual_manifest["entries"] if visual_manifest is not None else None),
                )
            except Exception as exc:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "v2 image binding order or receipt is invalid") from exc
            if len(bindings) != len(board_inputs):
                raise _replication_error(
                    "PROMPT_INTEGRITY_FAILED",
                    "v2 image binding descriptor is invalid",
                )
            binding_receipt: dict[str, Any] | None = None
            if raw_visual_bindings:
                binding_receipt = _validate_provider_only_binding_receipt(
                    prompt_artifact.get("provider_only_binding_receipt"),
                    prompt=str(prompt),
                    image_tags=[str(binding.get("reference") or "") for binding in bindings],
                )
            submitted_target_changes = item.get("target_changes")
            if submitted_target_changes is None:
                submitted_target_changes = []
            if not isinstance(submitted_target_changes, list):
                raise _replication_error(
                    "PROMPT_INTEGRITY_FAILED",
                    "v2 target changes must be an explicit list",
                )
            target_changes, approved_target_changes_sha256, approved_script_sha256 = self._v2_approved_target_changes(
                context,
                target_changes=submitted_target_changes,
                segment_start_ms=int(item["start_ms"]),
                segment_end_ms=int(item["end_ms"]),
            )
            audio_reference = None
            if audio_kind == "background_music" or (
                audio_kind == "voiceover" and "@Audio1" in str(prompt).strip()
            ):
                audio_reference = self._background_music_reference(
                    context,
                    segment={
                        "segment_id": segment_id,
                        "start_ms": int(item["start_ms"]),
                        "end_ms": int(item["end_ms"]),
                        "duration_ms": int(item["end_ms"]) - int(item["start_ms"]),
                    },
                    plan_sha256=str(item.get("segment_plan_sha256") or "").lower(),
                    prompt=str(prompt).strip(),
                    audio_kind=audio_kind,
                    v2=True,
                )
            audio_urls = [audio_reference[0]] if audio_reference is not None else []
            actual_video_url, actual_source_sha, actual_slice_sha, full_source_evidence = self._v2_published_source_reference(
                context=context, item=item
            )
            try:
                built = compiler.build_edit_provider_payload(
                    video_url=actual_video_url,
                    prompt=prompt,
                    asset_bindings=bindings,
                    audio_urls=audio_urls,
                    source_video_sha256=actual_source_sha,
                    source_slice_sha256=actual_slice_sha,
                    segment_plan_sha256=str(item.get("segment_plan_sha256") or ""),
                    segment_id=segment_id,
                    start_ms=int(item.get("start_ms")),
                    end_ms=int(item.get("end_ms")),
                    source_video_reference_artifact_id=str(
                        item.get("source_video_reference_artifact_id") or ""
                    ),
                    target_changes=target_changes,
                    approved_target_changes_sha256=approved_target_changes_sha256,
                    source_is_full_segment=full_source_evidence,
                )
                provider_payload = _mapping(
                    built.get("provider_payload"), "v2 provider payload"
                )
                image_binding = built.get("image_reference_binding")
                if provider_payload.get("imageUrls"):
                    validate_v2_image_reference_binding(provider_payload, image_binding)
                video_binding = _mapping(
                    built.get("video_reference_binding"), "v2 video binding"
                )
                validate_v2_video_reference_binding(provider_payload, video_binding)
                validate_runninghub_standard_payload_contract(provider_payload)
                validate_audio_reference_binding(provider_payload, audio_reference[1] if audio_reference is not None else None)
                if audio_reference is not None:
                    validate_audio_reference_artifact_receipt(audio_reference[1], audio_reference[3])
            except Exception as exc:
                if isinstance(exc, ReplicationError):
                    raise
                raise _replication_error(
                    "PROMPT_INTEGRITY_FAILED",
                    f"v2 provider payload audit failed for {segment_id}",
                ) from exc
            row = {
                "segment_id": segment_id,
                "segment_plan_sha256": str(item["segment_plan_sha256"]).lower(),
                "payload_template": dict(provider_payload),
                "image_reference_binding": dict(image_binding or {}),
                "video_reference_binding": dict(video_binding),
                "asset_board_receipts": list(built.get("asset_board_receipts") or []),
                "target_changes": [dict(change) for change in target_changes],
                "approved_target_changes_sha256": approved_target_changes_sha256,
                "approved_script_sha256": approved_script_sha256,
                "source_video_sha256": str(item["source_video_sha256"]).lower(),
                "source_slice_sha256": str(item["source_slice_sha256"]).lower(),
                "time_receipt": dict(video_binding["time_receipt"]),
                "audio_kind": audio_kind,
                "audio_reference_binding": audio_reference[1] if audio_reference is not None else None,
                "audio_reference_artifact_receipt": audio_reference[3] if audio_reference is not None else None,
                "audio_preservation": {"source_speech": "preserve", "source_ambience": "preserve"},
            }
            if binding_receipt is not None:
                row["provider_only_binding_receipt"] = binding_receipt
            if visual_manifest is not None:
                row["asset_board_manifest_artifact_id"] = visual_manifest["artifact_id"]
                row["asset_board_manifest_sha256"] = visual_manifest["sha256"]
                row["asset_board_mapping_sha256"] = visual_manifest["asset_board_mapping_sha256"]
                row["provider_asset_board_contracts_sha256"] = visual_manifest["provider_asset_board_contracts_sha256"]
            audited.append(row)
        envelope = {
            "schema_version": "seedance-request-audit/v2",
            "edit_contract": "video-edit-v2",
            "segments": audited,
        }
        envelope["stage_fingerprint"] = _sha(envelope)
        published = _publish_json(
            context,
            kind="seedance_request_audit",
            value=envelope,
            metadata={
                "edit_contract": "video-edit-v2",
                "stage_fingerprint": envelope["stage_fingerprint"],
                "approved_script_sha256": next(
                    iter(
                        {
                            str(row.get("approved_script_sha256") or "")
                            for row in audited
                            if row.get("approved_script_sha256")
                        }
                    ),
                    "",
                ),
            },
        )
        return {
            "status": "ready",
            "seedance_request_audit": envelope,
            "published_artifacts": [published],
        }

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        contract = _read_json_artifact(context, kind="seedance_input_contract")
        if contract.get("edit_contract") == "video-edit-v2":
            return self._run_v2_edit_contract(context=context, contract=contract)
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
            target_urls, target_changes = self._target_reference_urls(context, prompt=prompt)
            if not target_changes:
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "source video reference requires an approved target change")
            # Upload only the storyboard page(s) whose Cut scope intersects
            # this Segment. A second page is absent unless the full board has
            # more than four Cuts.
            uploaded_storyboards = self._upload_storyboards(context, segment_id=segment_id)
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
            audio_reference = self._background_music_reference(
                context, segment=segment_plan, plan_sha256=plan_sha, prompt=prompt.strip()
            )
            audio_urls = [audio_reference[0]] if audio_reference is not None else []
            visual_changes = [
                dict(change)
                for change in target_changes
                if change.get("kind") in {"new_model_image", "new_product_image"}
            ]
            if len(visual_changes) != len(target_urls):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "visual target URLs differ from target authorization")
            target_entries = [
                {
                    **change,
                    "url": url,
                    "artifact_name": f"{change['kind']}-{index}.png",
                }
                for index, (url, change) in enumerate(zip(target_urls, visual_changes, strict=True), start=1)
            ]
            model_urls = [item["url"] for item in target_entries if item["kind"] == "new_model_image"]
            product_urls = [item["url"] for item in target_entries if item["kind"] == "new_product_image"]
            storyboard_urls = [str(item["url"]) for item in uploaded_storyboards]
            ordered_image_urls = [*model_urls, *product_urls[:1], *storyboard_urls, *product_urls[1:]]
            payload_template = {
                "prompt": prompt.strip(), "resolution": "720p", "duration": str(max(4, min(15, round(duration / 1000)))),
                "imageUrls": ordered_image_urls, "videoUrls": [], "audioUrls": audio_urls, "generateAudio": True,
                "ratio": "9:16", "realPersonMode": True, "conversionSlots": ["all"],
                "returnLastFrame": False, "seed": -1,
            }
            binding_storyboards: list[dict[str, Any]] = []
            for uploaded in uploaded_storyboards:
                raw_storyboard_descriptor = _mapping(uploaded.get("descriptor"), "storyboard descriptor")
                storyboard_descriptor = self._approved_board_descriptor(
                    context,
                    segment_id=segment_id,
                    segment=segment_plan,
                    descriptor=raw_storyboard_descriptor,
                    storyboard_url=str(uploaded.get("url") or ""),
                )
                self._validate_internal_board_lineage(context, approved_board=storyboard_descriptor)
                raw_metadata = raw_storyboard_descriptor.get("metadata")
                binding_storyboards.append(
                    {
                        **storyboard_descriptor,
                        "logical_name": str(raw_metadata.get("logical_name") or "") if isinstance(raw_metadata, Mapping) else "",
                        "page": int(raw_metadata.get("storyboard_page", 1)) if isinstance(raw_metadata, Mapping) else 1,
                        "page_cut_ids": [
                            str(cut_id)
                            for cut_id in (
                                raw_metadata.get("page_cut_ids")
                                if isinstance(raw_metadata, Mapping)
                                else segment_plan.get("cut_ids")
                            ) or []
                            if str(cut_id) in set(str(value) for value in segment_plan.get("cut_ids") or [])
                        ],
                    }
                )
            image_reference_binding = self._image_reference_binding(
                payload=payload_template,
                segment=segment_plan,
                storyboards=binding_storyboards,
                target_entries=target_entries,
            )
            video_url, video_binding, published_video_reference = self._source_reference(
                context,
                segment=segment_plan,
                image_reference_binding=image_reference_binding,
                target_changes=target_changes,
                plan_sha256=plan_sha,
                segment_plan=plan,
            )
            payload_template["videoUrls"] = [video_url]
            final_reference_lineage = self._final_reference_lineage(
                payload=payload_template,
                segment_id=segment_id,
                plan_sha256=plan_sha,
                image_reference_binding=image_reference_binding,
                source_artifact=published_video_reference,
                source_url=video_url,
            )
            try:
                validate_runninghub_standard_payload_contract(payload_template)
                validate_image_reference_binding(payload_template, image_reference_binding)
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
                "image_reference_binding": image_reference_binding,
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
        image_reference_binding: Mapping[str, Any] | None = None,
        final_reference_lineage: Mapping[str, Any] | None = None,
        audio_reference_binding: Mapping[str, Any] | None = None,
        audio_reference_artifact_receipt: Mapping[str, Any] | None = None,
        provider_audit_proof: Mapping[str, Any] | None = None,
        provider_only_binding_receipt: Mapping[str, Any] | None = None,
        audio_provider_authorization: Mapping[str, Any] | None = None,
        server_audio_authorization_verifier: Any | None = None,
    ) -> None:
        super().__init__(dict(payload))
        self.video_reference_binding = dict(video_reference_binding) if isinstance(video_reference_binding, Mapping) else None
        self.image_reference_binding = dict(image_reference_binding) if isinstance(image_reference_binding, Mapping) else None
        self.final_reference_lineage = dict(final_reference_lineage) if isinstance(final_reference_lineage, Mapping) else None
        self.audio_reference_binding = dict(audio_reference_binding) if isinstance(audio_reference_binding, Mapping) else None
        self.audio_reference_artifact_receipt = dict(audio_reference_artifact_receipt) if isinstance(audio_reference_artifact_receipt, Mapping) else None
        self.provider_audit_proof = dict(provider_audit_proof) if isinstance(provider_audit_proof, Mapping) else None
        self.provider_only_binding_receipt = dict(provider_only_binding_receipt) if isinstance(provider_only_binding_receipt, Mapping) else None
        self.audio_provider_authorization = dict(audio_provider_authorization) if isinstance(audio_provider_authorization, Mapping) else None
        self.server_audio_authorization_verifier = server_audio_authorization_verifier


class SubmitProviderVideoStage:
    """Submit the exact audited payload once per frozen segment, never retry."""

    def __init__(self, *, provider: Any, audit_secret: str | None = None) -> None:
        self.provider = provider
        self.audit_secret = audit_secret

    @staticmethod
    def _split_pass_index(context: Any) -> int | None:
        stage = str(getattr(context, "stage", ""))
        if stage == "submit_provider_video_pass1":
            return 1
        if stage == "submit_provider_video_pass2":
            return 2
        return None

    @classmethod
    def _split_manifest(cls, context: Any, pass_index: int) -> Mapping[str, Any]:
        compiled = _stage_output(context, "compile_seedance20_prompt")
        contract = _mapping(compiled.get("seedance_input_contract"), "split compile contract")
        split_plan = _mapping(contract.get("split_edit_plan"), "split edit plan")
        manifests = split_plan.get("pass_manifests")
        if not isinstance(manifests, list) or len(manifests) != 2:
            raise _replication_error("CONTRACT_INVALID", "split edit plan must contain exactly two pass manifests")
        manifest = manifests[pass_index - 1]
        if not isinstance(manifest, Mapping) or manifest.get("pass_index") != pass_index:
            raise _replication_error("CONTRACT_INVALID", "split pass manifest identity is invalid")
        return manifest

    @classmethod
    def _split_inputs(
        cls,
        context: Any,
        *,
        pass_index: int,
        payload: Mapping[str, Any],
        binding: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, Mapping[str, Any]]:
        manifest = cls._split_manifest(context, pass_index)
        if not isinstance(binding, Mapping):
            raise _replication_error("CONTRACT_INVALID", "split provider request requires a video binding")
        resolved_payload = dict(payload)
        resolved_payload["prompt"] = str(manifest.get("prompt") or "")
        resolved_binding = dict(binding)
        if pass_index == 2:
            upstream = _stage_output(context, "wait_provider_video_pass1")
            provider_videos = upstream.get("provider_videos")
            if not isinstance(provider_videos, list) or len(provider_videos) != 1:
                raise _replication_error("CONTRACT_INVALID", "pass2 requires exactly one pass1 provider output")
            descriptor = provider_videos[0].get("artifact") if isinstance(provider_videos[0], Mapping) else None
            if not isinstance(descriptor, Mapping):
                raise _replication_error("CONTRACT_INVALID", "pass1 provider output descriptor is missing")
            artifact_id = str(descriptor.get("artifact_id") or "")
            artifact_sha = str(descriptor.get("sha256") or "").lower()
            if not artifact_id or _SHA256.fullmatch(artifact_sha) is None:
                raise _replication_error("CONTRACT_INVALID", "pass1 provider output descriptor is invalid")
            resolved_binding["source_video_reference_artifact_id"] = artifact_id
            resolved_binding["source_slice_sha256"] = artifact_sha
        return resolved_payload, resolved_binding, manifest

    @staticmethod
    def _provider_request(
        payload: Mapping[str, Any],
        video_reference_binding: Mapping[str, Any] | None,
        *,
        image_reference_binding: Mapping[str, Any] | None = None,
        final_reference_lineage: Mapping[str, Any] | None = None,
        audio_reference_binding: Mapping[str, Any] | None,
        audio_reference_artifact_receipt: Mapping[str, Any] | None = None,
        provider_audit_proof: Mapping[str, Any] | None = None,
        provider_only_binding_receipt: Mapping[str, Any] | None = None,
    ) -> _BoundProviderPayload:
        is_v2 = (
            isinstance(video_reference_binding, Mapping)
            and video_reference_binding.get("edit_contract") == "video-edit-v2"
        )
        if is_v2 and payload.get("imageUrls"):
            provider_only_binding_receipt = _validate_provider_only_binding_receipt(
                provider_only_binding_receipt,
                prompt=str(payload.get("prompt") or ""),
                image_tags=[f"@Image{index}" for index in range(1, len(payload["imageUrls"]) + 1)],
            )
        try:
            validate_runninghub_standard_payload_contract(payload)
            if is_v2:
                if payload.get("imageUrls"):
                    validate_v2_image_reference_binding(payload, image_reference_binding)
                    if (
                        not isinstance(video_reference_binding, Mapping)
                        or image_reference_binding_sha256(image_reference_binding or {})
                        != str(video_reference_binding.get("image_reference_binding_sha256") or "").lower()
                    ):
                        raise RunningHubStandardPayloadError(
                            "v2 image reference binding SHA does not match the submitted image sidecar"
                        )
                validate_v2_video_reference_binding(payload, video_reference_binding)
                if final_reference_lineage is not None:
                    raise RunningHubStandardPayloadError("v2 edit requests do not use the legacy final reference lineage")
            else:
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
            image_reference_binding=image_reference_binding,
            final_reference_lineage=final_reference_lineage,
            audio_reference_binding=audio_reference_binding,
            audio_reference_artifact_receipt=audio_reference_artifact_receipt,
            provider_audit_proof=provider_audit_proof,
            provider_only_binding_receipt=provider_only_binding_receipt,
        )

    @staticmethod
    def _ttl(context: Any) -> int:
        snapshot = context.job_store.get_job(context.job_id)
        if snapshot is None:
            raise _replication_error("JOB_GONE", "job expired before provider submission", category="worker")
        return max(1, (snapshot.expires_at_ms - time.time_ns() // 1_000_000) // 1000)

    @classmethod
    def _load_audit(cls, context: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        descriptors = [
            item for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping) and item.get("kind") == "seedance_request_audit"
        ]
        if not descriptors:
            raise _replication_error("ARTIFACT_NOT_FOUND", "provider submission requires a published seedance request audit", category="artifact")
        snapshot = getattr(context, "snapshot", None)
        current_script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
        v2_candidates: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        legacy_candidates: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        v2_authority: tuple[str, str, str, str] | None = None
        for descriptor in descriptors:
            artifact_id = str(descriptor.get("artifact_id") or "")
            digest = str(descriptor.get("sha256") or "").lower()
            if not artifact_id or _SHA256.fullmatch(digest) is None:
                raise _replication_error("CONTRACT_INVALID", "seedance request audit descriptor is invalid", category="artifact")
            try:
                data = read_immutable_artifact(context, descriptor)
            except QcRetryEvidenceError as exc:
                materialize_code = exc.code
                if materialize_code not in {
                    "ARTIFACT_NOT_FOUND",
                    "ARTIFACT_MATERIALIZE_UNAVAILABLE",
                    "ARTIFACT_HASH_MISMATCH",
                }:
                    materialize_code = "ARTIFACT_MATERIALIZE_UNAVAILABLE"
                raise _replication_error(
                    materialize_code,
                    str(exc),
                    category="artifact",
                ) from exc
            try:
                value = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _replication_error("CONTRACT_INVALID", "seedance request audit is not canonical JSON", category="artifact") from exc
            if not isinstance(value, Mapping):
                raise _replication_error("CONTRACT_INVALID", "seedance request audit must be an object", category="artifact")
            schema_version = value.get("schema_version")
            is_v2_audit = (
                schema_version == "seedance-request-audit/v2"
                or value.get("edit_contract") == "video-edit-v2"
            )
            if not is_v2_audit:
                if schema_version != "seedance-request-audit/v1":
                    raise _replication_error(
                        "CONTRACT_INVALID",
                        "seedance request audit contract version is unsupported",
                        category="artifact",
                    )
                legacy_candidates.append((value, descriptor))
                continue
            if v2_authority is None:
                if not _SHA256.fullmatch(current_script_sha):
                    raise _replication_error(
                        "CONTRACT_INVALID",
                        "v2 seedance request audit requires the current approved script SHA",
                        category="artifact",
                    )
                v2_authority = (
                    current_script_sha,
                    _current_materialized_artifact_sha(context, kind="source_video"),
                    _current_materialized_artifact_sha(context, kind="segment_plan"),
                    _current_materialized_artifact_sha(context, kind="asset_board_manifest"),
                )
            try:
                validate_v2_seedance_request_audit(
                    value,
                    descriptor.get("metadata"),
                    expected_script_sha256=v2_authority[0],
                    expected_source_sha256=v2_authority[1],
                    expected_segment_plan_sha256=v2_authority[2],
                    expected_asset_manifest_sha256=v2_authority[3],
                )
            except SeedanceRequestAuditValidationError as exc:
                raise _replication_error("CONTRACT_INVALID", str(exc), category="artifact") from exc
            v2_candidates.append((value, descriptor))
        if v2_candidates:
            qc_retry_candidates = [
                item
                for item in v2_candidates
                if any(is_qc_retry_row(segment.get("retry")) for segment in item[0].get("segments", ()) if isinstance(segment, Mapping))
            ]
            if len(qc_retry_candidates) > 1:
                raise _replication_error(
                    "CONTRACT_INVALID",
                    "multiple current QC retry audits are ambiguous",
                    category="artifact",
                )
            if qc_retry_candidates:
                return qc_retry_candidates[0]
            if len(v2_candidates) != 1:
                raise _replication_error("CONTRACT_INVALID", "multiple current v2 seedance request audits are ambiguous", category="artifact")
            return v2_candidates[0]
        provider_retry_candidates = [
            item
            for item in legacy_candidates
            if any(
                is_confirmed_provider_retry_row(segment.get("retry"))
                for segment in item[0].get("segments", ())
                if isinstance(segment, Mapping)
            )
        ]
        if len(provider_retry_candidates) > 1:
            raise _replication_error(
                "CONTRACT_INVALID",
                "multiple current provider retry audits are ambiguous",
                category="artifact",
            )
        if provider_retry_candidates:
            return provider_retry_candidates[0]
        if len(legacy_candidates) != 1:
            raise _replication_error("ARTIFACT_NOT_FOUND", "exactly one current seedance request audit is required", category="artifact")
        return legacy_candidates[0]

    @staticmethod
    def _validate_v2_manifest_sidecar(
        context: Any,
        *,
        row: Mapping[str, Any],
        image_binding: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        manifest = _resolve_v2_asset_board_manifest(context)
        if (
            str(row.get("asset_board_manifest_artifact_id") or "") != str(manifest.get("artifact_id") or "")
            or str(row.get("asset_board_manifest_sha256") or "").lower() != str(manifest.get("sha256") or "").lower()
        ):
            raise _replication_error("ARTIFACT_HASH_MISMATCH", "v2 audit manifest sidecar does not match the current published manifest", category="artifact")
        entries = manifest.get("entries")
        rows = image_binding.get("image_bindings")
        if not isinstance(entries, list) or not isinstance(rows, list):
            raise _replication_error("CONTRACT_INVALID", "v2 manifest and image sidecar entries are invalid", category="artifact")
        visual_rows = [
            item for item in rows
            if isinstance(item, Mapping)
            and str(item.get("asset_type") or "").casefold() in {"model", "garment", "scene", "product", "app"}
        ]
        if len(visual_rows) != len(entries):
            raise _replication_error("CONTRACT_INVALID", "v2 image sidecar does not cover the canonical manifest", category="artifact")
        for sidecar, entry in zip(visual_rows, entries, strict=True):
            for field in (
                ("tag", "asset_tag"),
                ("reference", "image_reference"),
                ("asset_type", "asset_type"),
                ("source_slot", "source_slot"),
                ("source_index", "source_index"),
                ("source_asset_sha256", "source_asset_sha256"),
                ("replaces_tag", "replaces_tag"),
                ("board_artifact_id", "board_artifact_id"),
                ("board_sha256", "board_sha256"),
                ("board_url", "board_url"),
            ):
                if sidecar.get(field[0]) != entry.get(field[1]):
                    raise _replication_error("CONTRACT_INVALID", "v2 image sidecar differs from the canonical manifest", category="artifact")
            if sidecar.get("receipt") != entry.get("receipt"):
                raise _replication_error("CONTRACT_INVALID", "v2 image sidecar receipt differs from the canonical manifest", category="artifact")
        return manifest

    @staticmethod
    def _qc_retry_blocker(decision: QcRetryDecision) -> None:
        if decision.is_safety_blocker:
            raise _replication_error(
                "CONTENT_SAFETY_BLOCKER",
                "current QC safety evidence blocks provider retry",
                category="safety",
                **{
                    "failure_type": decision.failure_type,
                    **dict(decision.details),
                },
            )

    @classmethod
    def _prepare_qc_retry_audit(
        cls,
        context: Any,
        audit: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], QcRetryDecision | None]:
        if audit.get("schema_version") != "seedance-request-audit/v2":
            return audit, {}, None
        rows = audit.get("segments")
        if not isinstance(rows, list) or not rows:
            return audit, {}, None
        existing_qc_retry = any(
            is_qc_retry_row(segment.get("retry"))
            for segment in rows
            if isinstance(segment, Mapping)
        )
        evidence_descriptors = [
            item
            for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping) and item.get("kind") == "video_edit_qc_evidence"
        ]
        if not evidence_descriptors:
            getter = getattr(getattr(context, "job_store", None), "list_artifacts", None)
            if callable(getter):
                evidence_descriptors = [
                    item
                    for item in getter(getattr(context, "job_id", None))
                    if getattr(item, "kind", None) == "video_edit_qc_evidence"
                ]
        if not evidence_descriptors:
            return audit, {}, None
        attempts = [
            item
            for item in context.job_store.list_provider_attempts(context.job_id)
            if item.operation == "CreateVideo"
        ]
        succeeded_by_segment = {
            str(item.segment_id): item
            for item in attempts
            if item.status == "SUCCEEDED" and item.segment_id
        }
        if not existing_qc_retry and not any(
            str(segment.get("segment_id") or "") in succeeded_by_segment
            for segment in rows
            if isinstance(segment, Mapping)
        ):
            return audit, {}, None
        decision = current_qc_retry_decision_for_submit(context)
        cls._qc_retry_blocker(decision)
        if existing_qc_retry:
            for segment in rows:
                retry = segment.get("retry") if isinstance(segment, Mapping) else None
                if is_qc_retry_row(retry) and retry.get("failure_type") != decision.failure_type:
                    raise _replication_error(
                        "QC_EVIDENCE_INVALID",
                        "QC retry audit failure type differs from current server evidence",
                        category="quality",
                        lineage_field="failure_type",
                    )
            return audit, {}, decision
        parent_attempts: dict[str, Any] = {}
        for segment in rows:
            if not isinstance(segment, Mapping):
                raise _replication_error(
                    "QC_EVIDENCE_INVALID",
                    "QC retry audit segment is invalid",
                    category="quality",
                    lineage_field="segments",
                )
            segment_id = str(segment.get("segment_id") or "")
            parent = succeeded_by_segment.get(segment_id)
            if parent is None:
                raise _replication_error(
                    "QC_EVIDENCE_INVALID",
                    "current QC evidence has no successful provider parent",
                    category="quality",
                    lineage_field="parent_attempt_id",
                )
            parent_attempts[segment_id] = parent
        try:
            retry_audit = build_qc_retry_audit(
                audit,
                decision=decision,
                parent_attempts=parent_attempts,
            )
            encoded = json.dumps(
                retry_audit,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            published = context.publish_bytes(
                kind="seedance_request_audit",
                data=encoded,
                content_type="application/json",
                expected_sha256=hashlib.sha256(encoded).hexdigest(),
                metadata={
                    "stage_fingerprint": retry_audit["stage_fingerprint"],
                    "approved_script_sha256": decision.approved_script_sha256,
                },
            )
        except (OSError, TypeError, ValueError, ReplicationError) as exc:
            raise _replication_error(
                "QC_EVIDENCE_INVALID",
                "server could not publish the immutable QC retry audit",
                category="quality",
                lineage_field="seedance_request_audit",
            ) from exc
        return retry_audit, published, decision

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        audit, audit_descriptor = self._load_audit(context)
        split_pass_index = self._split_pass_index(context)
        prepared_qc_retry_decision: QcRetryDecision | None = None
        if audit.get("schema_version") == "seedance-request-audit/v2":
            audit, published_audit, prepared_qc_retry_decision = self._prepare_qc_retry_audit(
                context,
                audit,
            )
            if published_audit:
                audit, audit_descriptor = self._load_audit(context)
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
            is_v2_audit = (
                audit.get("schema_version") == "seedance-request-audit/v2"
                or audit.get("edit_contract") == "video-edit-v2"
            )
            is_v2 = is_v2_audit
            if not isinstance(image_urls, list) or (not image_urls and not is_v2_audit):
                raise _replication_error("CAPABILITY_UNAVAILABLE", "storyboard media upload adapter is required before Seedance submission", retryable=True, category="capability")
            binding = row.get("video_reference_binding")
            if binding is not None and not isinstance(binding, Mapping):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit video reference binding is invalid")
            is_v2 = is_v2 or (
                isinstance(binding, Mapping)
                and binding.get("edit_contract") == "video-edit-v2"
            )
            binding_receipt = row.get("provider_only_binding_receipt")
            if is_v2 and image_urls:
                binding_receipt = _validate_provider_only_binding_receipt(
                    binding_receipt if isinstance(binding_receipt, Mapping) else None,
                    prompt=str(payload.get("prompt") or ""),
                    image_tags=[f"@Image{index}" for index in range(1, len(image_urls) + 1)],
                )
            split_manifest: Mapping[str, Any] | None = None
            if split_pass_index is not None:
                payload, binding, split_manifest = self._split_inputs(
                    context,
                    pass_index=split_pass_index,
                    payload=payload,
                    binding=binding,
                )
                image_urls = payload.get("imageUrls")
            image_binding = row.get("image_reference_binding")
            if image_binding is not None and not isinstance(image_binding, Mapping):
                raise _replication_error("PROMPT_INTEGRITY_FAILED", "provider audit image reference binding is invalid")
            retry = row.get("retry")
            provider_retry = retry if is_confirmed_provider_retry_row(retry) else None
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
            if is_v2_audit and image_urls:
                self._validate_v2_manifest_sidecar(
                    context,
                    row=row,
                    image_binding=image_binding if isinstance(image_binding, Mapping) else {},
                )
            if split_pass_index is not None and provider_retry is not None:
                payload["prompt"] = (
                    f"{payload.get('prompt', '')} Provider retry: "
                    f"{provider_retry.get('adjustment')}."
                )
            if is_v2 and image_urls:
                binding_receipt = dict(binding_receipt or {})
                binding_receipt["prompt_sha256"] = hashlib.sha256(
                    str(payload.get("prompt") or "").encode("utf-8")
                ).hexdigest()
            provider_request = self._provider_request(
                payload,
                binding,
                image_reference_binding=image_binding,
                final_reference_lineage=final_reference_lineage,
                audio_reference_binding=audio_binding,
                audio_reference_artifact_receipt=audio_artifact_receipt,
                provider_audit_proof=audit_proof,
                provider_only_binding_receipt=binding_receipt,
            )
            if split_pass_index is not None:
                provider_request.pass_index = split_pass_index
                provider_request.pass_identity = f"pass{split_pass_index}"
            target_sha_basis = {
                "payload": dict(payload),
                "video_reference_binding": dict(binding) if isinstance(binding, Mapping) else None,
                "image_reference_binding": dict(image_binding) if isinstance(image_binding, Mapping) else None,
                "final_reference_lineage": dict(final_reference_lineage) if isinstance(final_reference_lineage, Mapping) else None,
                "audio_reference_binding": dict(audio_binding) if isinstance(audio_binding, Mapping) else None,
                "audio_reference_artifact_receipt": dict(audio_artifact_receipt) if isinstance(audio_artifact_receipt, Mapping) else None,
                "asset_board_manifest_artifact_id": row.get("asset_board_manifest_artifact_id"),
                "asset_board_manifest_sha256": row.get("asset_board_manifest_sha256"),
                "approved_script_sha256": row.get("approved_script_sha256"),
                "approved_target_changes_sha256": row.get("approved_target_changes_sha256"),
                "provider_only_binding_receipt": dict(binding_receipt) if isinstance(binding_receipt, Mapping) else None,
            }
            if split_pass_index is not None:
                target_sha_basis.update({
                    "pass_index": split_pass_index,
                    "pass_identity": f"pass{split_pass_index}",
                    "pass_manifest_sha256": canonical_sha(dict(split_manifest or {})),
                })
            if provider_retry is not None:
                target_sha_basis["provider_retry"] = dict(provider_retry)
            target_request_sha = _sha(target_sha_basis)
            qc_retry = retry if is_qc_retry_row(retry) else None
            intent_sha_basis = {
                **target_sha_basis,
                "retry": dict(retry) if isinstance(retry, Mapping) else None,
            }
            request_sha = _sha(intent_sha_basis)
            all_attempts = [
                item for item in context.job_store.list_provider_attempts(context.job_id)
                if item.operation == "CreateVideo" and item.segment_id == segment_id and item.segment_plan_sha256 == plan_sha
                and (split_pass_index is None or item.pass_index == split_pass_index)
            ]
            succeeded = [item for item in all_attempts if item.status == "SUCCEEDED"]
            if split_pass_index == 2 and len(succeeded) == 1:
                target_sha_basis["qc_retry_parent_attempt_id"] = succeeded[0].attempt_id
                target_sha_basis["qc_retry_parent_request_sha256"] = succeeded[0].request_sha256
                target_request_sha = _sha(target_sha_basis)
                intent_sha_basis = {
                    **target_sha_basis,
                    "retry": {"retry_index": 2, "parent_attempt_id": succeeded[0].attempt_id},
                }
                request_sha = _sha(intent_sha_basis)
            matching_succeeded = [item for item in succeeded if item.request_sha256 == request_sha]
            retry_parent: ProviderAttempt | None = None
            if qc_retry is not None:
                try:
                    decision = (
                        prepared_qc_retry_decision
                        or current_qc_retry_decision_for_submit(context)
                    )
                except ReplicationError:
                    raise
                self._qc_retry_blocker(decision)
                if str(qc_retry.get("failure_type") or "") != decision.failure_type:
                    raise _replication_error(
                        "QC_EVIDENCE_INVALID",
                        "QC retry audit failure type does not match current QC evidence",
                        category="quality",
                        lineage_field="failure_type",
                    )
                retry_parent_candidates = [
                    item
                    for item in all_attempts
                    if item.attempt_id == str(qc_retry.get("parent_attempt_id") or "")
                ]
                if len(retry_parent_candidates) != 1 or retry_parent_candidates[0].status != "SUCCEEDED":
                    raise _replication_error(
                        "QC_EVIDENCE_INVALID",
                        "QC retry parent attempt is not the successful current candidate",
                        category="quality",
                        lineage_field="parent_attempt_id",
                    )
                retry_parent = retry_parent_candidates[0]
                if retry_parent.request_sha256 != str(qc_retry.get("parent_request_sha256") or ""):
                    raise _replication_error(
                        "QC_EVIDENCE_INVALID",
                        "QC retry parent request is foreign",
                        category="quality",
                        lineage_field="parent_request_sha256",
                    )
                retry_attempts = [item for item in all_attempts if item.retry_index == 2]
                if len(retry_attempts) > 1:
                    raise _replication_error(
                        "QC_EVIDENCE_INVALID",
                        "multiple QC retry attempts are ambiguous",
                        category="quality",
                        lineage_field="retry_index",
                    )
                if retry_attempts:
                    attempt = retry_attempts[0]
                    if attempt.request_sha256 != request_sha:
                        raise _replication_error(
                            "QC_EVIDENCE_INVALID",
                            "QC retry attempt does not match the immutable retry audit",
                            category="quality",
                            lineage_field="request_sha256",
                        )
                    if attempt.status == "SUCCEEDED":
                        raise _replication_error(
                            "SEEDANCE_EDIT_QC_FAILED",
                            "video edit remains QC-failed after the single targeted retry",
                            category="quality",
                            retryable=False,
                            failure_type=decision.failure_type,
                            attempt_count=2,
                            evidence_artifact_id=decision.evidence_artifact_id,
                            evidence_sha256=decision.evidence_sha256,
                        )
                    if attempt.status == "AMBIGUOUS":
                        raise _replication_error(
                            "PROVIDER_AMBIGUOUS",
                            "ambiguous QC retry provider attempt must be reconciled",
                            category="provider",
                        )
                    submitted.append({"segment_id": segment_id, "attempt_id": attempt.attempt_id, "task_id": attempt.provider_task_id, "status": attempt.status})
                    continue
            elif matching_succeeded:
                if len(matching_succeeded) > 1:
                    raise _replication_error("PROVIDER_AMBIGUOUS", "multiple successful provider attempts match the audited request", category="provider")
                attempt = matching_succeeded[0]
                submitted.append({"segment_id": segment_id, "attempt_id": attempt.attempt_id, "task_id": attempt.provider_task_id, "status": "SUCCEEDED"})
                continue
            if succeeded and qc_retry is None:
                if split_pass_index == 2 and len(succeeded) == 1:
                    retry_parent = succeeded[0]
                else:
                    raise _replication_error("IDEMPOTENCY_CONFLICT", "a successful provider attempt exists for a different audited request")
            active = [item for item in all_attempts if item.status in {"SUBMITTING", "RUNNING", "AMBIGUOUS"}]
            if len(active) > 1:
                raise _replication_error("PROVIDER_AMBIGUOUS", "multiple active provider attempts exist for the same segment", category="provider")
            if active:
                attempt = active[0]
                if attempt.request_sha256 != request_sha:
                    raise _replication_error("IDEMPOTENCY_CONFLICT", "active provider attempt has a different audited request")
                if attempt.status == "AMBIGUOUS":
                    raise _replication_error("PROVIDER_AMBIGUOUS", "ambiguous provider attempt must be reconciled before submission", category="provider")
                submitted.append({"segment_id": segment_id, "attempt_id": attempt.attempt_id, "task_id": attempt.provider_task_id, "status": attempt.status})
                continue
            billable_attempts = [
                item for item in all_attempts
                if not (item.status == "FAILED" and item.failure_kind == "preflight")
            ]
            if len(billable_attempts) >= 2:
                raise _replication_error(
                    "SEEDANCE_EDIT_FAILED",
                    "provider edit failed after the allowed two billable attempts",
                    category="provider",
                    user_action_required=True,
                )
            failed_attempts = [
                item for item in all_attempts
                if item.status == "FAILED" and item.failure_kind == "provider"
            ]
            unconfirmed_failures = [
                item for item in all_attempts
                if item.status == "FAILED" and item.failure_kind not in {None, "preflight", "provider"}
            ]
            if any(item.status == "FAILED" and item.failure_kind is None for item in all_attempts):
                raise _replication_error(
                    "PROVIDER_AMBIGUOUS",
                    "provider failure outcome is unconfirmed; reconcile the recorded attempt before retrying",
                    category="provider",
                )
            if unconfirmed_failures:
                raise _replication_error(
                    "PROVIDER_RETRY_NOT_CONFIRMED",
                    "provider retry failure kind is not confirmed",
                    category="provider",
                )
            if qc_retry is not None:
                pass
            elif failed_attempts:
                _retry, retry_parent = _validate_confirmed_provider_retry(
                    retry=retry if isinstance(retry, Mapping) else None,
                    failed_attempts=failed_attempts,
                    target_request_sha256=target_request_sha,
                )
            elif retry is not None:
                raise _replication_error(
                    "PROVIDER_RETRY_INVALID",
                    "retry audit data is not valid before a confirmed provider failure",
                    category="provider",
                )
            if not isinstance(self.audit_secret, str) or not self.audit_secret:
                raise _replication_error("CAPABILITY_UNAVAILABLE", "provider submission requires the service-side authorization secret", category="capability")
            snapshot = context.job_store.get_job(context.job_id)
            if snapshot is None:
                raise _replication_error("JOB_GONE", "job expired before provider submission", category="worker")
            attempt = context.job_store.begin_provider_attempt(
                job_id=context.job_id, expected_version=snapshot.version, operation="CreateVideo",
                request_sha256=request_sha, segment_id=segment_id, segment_plan_sha256=plan_sha,
                pass_index=split_pass_index,
                pass_identity=f"pass{split_pass_index}" if split_pass_index is not None else None,
                target_request_sha256=target_request_sha,
                parent_attempt_id=retry_parent.attempt_id if retry_parent is not None else None,
                parent_request_sha256=retry_parent.request_sha256 if retry_parent is not None else None,
                retry_index=2 if retry_parent is not None else None,
            )

            def mark_preflight_failed() -> None:
                current = context.job_store.get_job(context.job_id)
                if current is not None:
                    context.job_store.update_provider_attempt(
                        job_id=context.job_id,
                        expected_version=current.version,
                        attempt=replace(attempt, status="FAILED", failure_kind="preflight"),
                        ttl_seconds=self._ttl(context),
                    )

            try:
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
                        intent_sha256=request_sha,
                    )
                except Exception as exc:
                    mark_preflight_failed()
                    raise _replication_error("PROMPT_INTEGRITY_FAILED", f"server provider authorization cannot be minted: {exc}") from exc
                try:
                    provider_request.audio_provider_authorization = authorization
                    provider_request.server_audio_authorization_verifier = verifier
                except Exception as exc:
                    mark_preflight_failed()
                    raise _replication_error("PROVIDER_PREFLIGHT_FAILED", "provider request assembly failed before provider call", category="provider") from exc
                try:
                    response = self.provider.create_video(provider_request)
                except RunningHubCreateAmbiguousError:
                    raise
                except ProductionPortsError as exc:
                    mark_preflight_failed()
                    raise _replication_error(
                        "PROVIDER_PREFLIGHT_FAILED",
                        "provider adapter preflight rejected the request before the paid transport",
                        category="provider",
                    ) from exc
                except Exception as exc:
                    current = context.job_store.get_job(context.job_id)
                    if current is not None:
                        context.job_store.update_provider_attempt(
                            job_id=context.job_id,
                            expected_version=current.version,
                            attempt=replace(attempt, status="AMBIGUOUS"),
                            ttl_seconds=self._ttl(context),
                        )
                    raise _replication_error(
                        "PROVIDER_AMBIGUOUS",
                        "provider connection outcome is unknown; reconcile the recorded intent before retrying",
                        retryable=False,
                        category="provider",
                    ) from exc
            except RunningHubCreateAmbiguousError as exc:
                current = context.job_store.get_job(context.job_id)
                if current is not None:
                    context.job_store.update_provider_attempt(
                        job_id=context.job_id, expected_version=current.version,
                        attempt=replace(attempt, status="AMBIGUOUS"), ttl_seconds=self._ttl(context),
                    )
                raise _replication_error("PROVIDER_AMBIGUOUS", "RunningHub create outcome is ambiguous; reconcile the recorded intent instead of retrying", retryable=False, category="provider") from exc
            task_id = str(response.get("task_id") or "") if isinstance(response, Mapping) else ""
            receipt = response.get("receipt") if isinstance(response, Mapping) else None
            provider_payload_sha = _sha(payload)
            receipt_request_sha = str(receipt.get("request_sha256") or "").lower() if isinstance(receipt, Mapping) else ""
            receipt_response_sha = str(receipt.get("response_sha256") or "").lower() if isinstance(receipt, Mapping) else ""
            receipt_task_id = str(receipt.get("task_id") or "").strip() if isinstance(receipt, Mapping) else ""
            if (
                not task_id
                or not isinstance(receipt, Mapping)
                or receipt_request_sha != provider_payload_sha
                or _SHA256.fullmatch(receipt_response_sha) is None
                or receipt_task_id != task_id
            ):
                current = context.job_store.get_job(context.job_id)
                if current is not None:
                    context.job_store.update_provider_attempt(
                        job_id=context.job_id,
                        expected_version=current.version,
                        attempt=replace(attempt, status="AMBIGUOUS", response_sha256=receipt_response_sha or None),
                        ttl_seconds=self._ttl(context),
                    )
                raise _replication_error(
                    "PROVIDER_AMBIGUOUS",
                    "provider create returned an unverifiable result; reconcile before retrying",
                    category="provider",
                )
            current = context.job_store.get_job(context.job_id)
            if current is None:
                raise _replication_error("JOB_GONE", "job expired during provider submission", category="worker")
            running = replace(attempt, status="RUNNING", provider_task_id=task_id, response_sha256=receipt_response_sha)
            context.job_store.update_provider_attempt(job_id=context.job_id, expected_version=current.version, attempt=running, ttl_seconds=self._ttl(context))
            submitted.append({
                "segment_id": segment_id,
                "attempt_id": attempt.attempt_id,
                "task_id": task_id,
                "status": "RUNNING",
                "request_sha256": running.request_sha256,
                "target_request_sha256": running.target_request_sha256,
                "parent_attempt_id": running.parent_attempt_id,
                "parent_request_sha256": running.parent_request_sha256,
                "retry_index": running.retry_index,
                "pass_index": running.pass_index,
                "pass_identity": running.pass_identity,
                **(
                    {
                        "runtime_resolved_manifest": {
                            "pass_index": split_pass_index,
                            "input_video_artifact_id": binding.get("source_video_reference_artifact_id") if isinstance(binding, Mapping) else None,
                            "input_video_sha256": binding.get("source_slice_sha256") if isinstance(binding, Mapping) else None,
                            "request_sha256": request_sha,
                            "target_request_sha256": target_request_sha,
                        }
                    }
                    if split_pass_index is not None
                    else {}
                ),
            })
        return {"status": "ready", "provider_attempts": submitted}


class ReconcileProviderAttemptStage:
    """Resolve one ambiguous paid attempt without reserving a new attempt."""

    def __init__(self, *, provider: Any) -> None:
        self.provider = provider

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        selector = input_artifacts[0] if input_artifacts else {}
        requested_id = str(selector.get("attempt_id") or "") if isinstance(selector, Mapping) else ""
        requested_segment = str(selector.get("segment_id") or "") if isinstance(selector, Mapping) else ""
        candidates = [
            attempt
            for attempt in context.job_store.list_provider_attempts(context.job_id)
            if attempt.operation == "CreateVideo" and attempt.status == "AMBIGUOUS"
            and (not requested_id or attempt.attempt_id == requested_id)
            and (not requested_segment or attempt.segment_id == requested_segment)
        ]
        if len(candidates) != 1:
            raise _replication_error(
                "PROVIDER_RECONCILIATION_REQUIRED",
                "reconciliation requires exactly one ambiguous provider attempt",
                category="provider",
            )
        attempt = candidates[0]
        if not attempt.provider_task_id:
            raise _replication_error(
                "PROVIDER_RECONCILIATION_REQUIRED",
                "ambiguous provider create has no task id and cannot be guessed or resubmitted",
                category="provider",
            )
        try:
            state = self.provider.lookup({"taskId": attempt.provider_task_id})
        except RunningHubTaskFailed as exc:
            _persist_provider_attempt(
                context,
                replace(attempt, status="FAILED", failure_kind="provider"),
            )
            return {
                "status": "FAILED",
                "attempt_id": attempt.attempt_id,
                "task_id": attempt.provider_task_id,
                "create_count_delta": 0,
            }
        except Exception as exc:
            _persist_provider_attempt(context, replace(attempt, status="AMBIGUOUS"))
            raise _replication_error(
                "PROVIDER_AMBIGUOUS",
                "provider reconciliation lookup is inconclusive; the attempt remains ambiguous",
                retryable=False,
                category="provider",
            ) from exc
        status = str(state.get("status") or "").upper() if isinstance(state, Mapping) else ""
        if status in {"QUEUED", "PENDING", "RUNNING", "SUCCESS"}:
            _persist_provider_attempt(context, replace(attempt, status="RUNNING"))
            return {
                "status": "RUNNING",
                "provider_status": status,
                "attempt_id": attempt.attempt_id,
                "task_id": attempt.provider_task_id,
                "create_count_delta": 0,
            }
        if status in {"FAILED", "CANCELLED", "CANCELED"}:
            _persist_provider_attempt(
                context,
                replace(attempt, status="FAILED", failure_kind="provider"),
            )
            return {
                "status": "FAILED",
                "attempt_id": attempt.attempt_id,
                "task_id": attempt.provider_task_id,
                "create_count_delta": 0,
            }
        _persist_provider_attempt(context, replace(attempt, status="AMBIGUOUS"))
        raise _replication_error(
            "PROVIDER_RECONCILIATION_REQUIRED",
            "provider reconciliation returned an unsupported task status",
            category="provider",
        )


class WaitProviderVideoStage:
    """Poll known RunningHub tasks and publish verified MP4 bytes immediately."""

    def __init__(self, *, provider: Any, poll_seconds: float = 3.0, timeout_seconds: float = 1800.0) -> None:
        self.provider = provider
        self.poll_seconds = float(poll_seconds)
        self.timeout_seconds = float(timeout_seconds)

    @staticmethod
    def _publish_split_provider_retry_audit(
        context: Any,
        *,
        failed_attempt: ProviderAttempt,
    ) -> Mapping[str, Any]:
        audit, _descriptor = SubmitProviderVideoStage._load_audit(context)
        retry_audit = build_split_provider_retry_audit(
            audit,
            failed_attempt=failed_attempt,
            failure_evidence_sha256=provider_failure_evidence_sha256(failed_attempt),
        )
        encoded = json.dumps(
            retry_audit,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return context.publish_bytes(
            kind="seedance_request_audit",
            data=encoded,
            content_type="application/json",
            expected_sha256=hashlib.sha256(encoded).hexdigest(),
            metadata={"stage_fingerprint": retry_audit["stage_fingerprint"]},
        )

    def run(self, *, context: Any, input_artifacts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        del input_artifacts
        expected_pass_index = {
            "wait_provider_video_pass1": 1,
            "wait_provider_video_pass2": 2,
        }.get(str(getattr(context, "stage", "")))
        started = time.monotonic()
        results: list[dict[str, Any]] = []
        attempts = [
            attempt
            for attempt in context.job_store.list_provider_attempts(context.job_id)
            if attempt.operation == "CreateVideo" and attempt.status == "RUNNING"
            and (expected_pass_index is None or attempt.pass_index == expected_pass_index)
        ]
        if any(
            attempt.operation == "CreateVideo" and attempt.status == "AMBIGUOUS"
            for attempt in context.job_store.list_provider_attempts(context.job_id)
        ):
            raise _replication_error("PROVIDER_AMBIGUOUS", "ambiguous provider attempt must be reconciled before waiting", category="provider")
        pending = {attempt.attempt_id: attempt for attempt in attempts}
        for attempt in pending.values():
            if attempt.status == "AMBIGUOUS" or not attempt.provider_task_id:
                raise _replication_error("PROVIDER_AMBIGUOUS", "provider attempt must be reconciled before waiting", category="provider")

        def lookup(attempt: ProviderAttempt) -> tuple[ProviderAttempt, Mapping[str, Any] | None, Exception | None]:
            try:
                return attempt, self.provider.lookup({"taskId": attempt.provider_task_id}), None
            except Exception as exc:
                return attempt, None, exc

        def download(attempt: ProviderAttempt) -> tuple[ProviderAttempt, Path, Mapping[str, Any]]:
            destination = Path(context.work_dir) / f"{attempt.segment_id or attempt.attempt_id}.mp4"
            downloaded = self.provider.download(attempt.provider_task_id, destination)
            return attempt, destination, _mapping(downloaded, "provider download receipt")

        def confirmed_failure(attempt: ProviderAttempt) -> Mapping[str, Any]:
            failed = replace(attempt, status="FAILED", failure_kind="provider")
            _persist_provider_attempt(context, failed)
            if expected_pass_index != 2:
                raise _replication_error("PROVIDER_FAILED", "RunningHub video task failed", category="provider")
            if attempt.retry_index == 2:
                raise _replication_error(
                    "SEEDANCE_EDIT_FAILED",
                    "provider edit failed after the allowed two billable attempts",
                    category="provider",
                    retryable=False,
                )
            retry_audit = self._publish_split_provider_retry_audit(
                context,
                failed_attempt=failed,
            )
            return {
                "status": "FAILED",
                "provider_status": "FAILED",
                "confirmed_failure": True,
                "failure_kind": "provider",
                "attempt_id": attempt.attempt_id,
                "task_id": attempt.provider_task_id,
                "retry_index": attempt.retry_index,
                "published_artifacts": [retry_audit],
                "create_count_delta": 0,
            }

        poll_index = 0
        while pending:
            lookup_results = _run_ordered_parallel(
                list(pending.values()),
                lookup,
                max_workers=len(pending),
            )
            ready: list[ProviderAttempt] = []
            for attempt, state, error in lookup_results:
                if isinstance(error, RunningHubTaskFailed):
                    try:
                        result = confirmed_failure(attempt)
                    except ReplicationError as exc:
                        raise exc from error
                    results.append(result)
                    pending.pop(attempt.attempt_id, None)
                    continue
                if error is not None:
                    _persist_provider_attempt(context, replace(attempt, status="AMBIGUOUS"))
                    raise _replication_error(
                        "PROVIDER_AMBIGUOUS",
                        "provider lookup outcome is unknown; reconcile the recorded attempt",
                        retryable=False,
                        category="provider",
                    ) from error
                if isinstance(state, Mapping):
                    response_request_sha = str(state.get("request_sha256") or "").lower()
                    response_task_id = str(state.get("task_id") or "").strip()
                    response_pass_index = state.get("pass_index")
                    if response_request_sha and response_request_sha != attempt.request_sha256:
                        raise _replication_error("PROVIDER_RESULT_INVALID", "provider wait returned a foreign request SHA", category="provider")
                    if response_task_id and response_task_id != attempt.provider_task_id:
                        raise _replication_error("PROVIDER_RESULT_INVALID", "provider wait returned a foreign task id", category="provider")
                    if response_pass_index is not None and response_pass_index != attempt.pass_index:
                        raise _replication_error("PROVIDER_RESULT_INVALID", "provider wait returned a foreign pass identity", category="provider")
                    if "retry_index" in state and state.get("retry_index") != attempt.retry_index:
                        raise _replication_error("PROVIDER_RESULT_INVALID", "provider wait returned a foreign retry identity", category="provider")
                provider_status = str(state.get("status") or "").upper() if isinstance(state, Mapping) else ""
                if provider_status in {"FAILED", "CANCELLED", "CANCELED"}:
                    results.append(confirmed_failure(attempt))
                    pending.pop(attempt.attempt_id, None)
                    continue
                if provider_status == "SUCCESS":
                    ready.append(attempt)

            downloaded_results = _run_ordered_parallel(
                ready,
                download,
                max_workers=len(ready),
            ) if ready else []
            for attempt, destination, downloaded in downloaded_results:
                data = destination.read_bytes()
                if not data or not data.startswith(b"\x00\x00\x00") and b"ftyp" not in data[:64]:
                    raise _replication_error("PROVIDER_RESULT_INVALID", "RunningHub result is not an MP4 byte stream", category="provider")
                published = context.publish_bytes(
                    kind="provider_video",
                    data=data,
                    content_type="video/mp4",
                    expected_sha256=hashlib.sha256(data).hexdigest(),
                    metadata={
                        "segment_id": str(attempt.segment_id or ""),
                        "segment_plan_sha256": str(attempt.segment_plan_sha256 or "").lower(),
                        "provider_task_id": str(attempt.provider_task_id or ""),
                        "pass_index": attempt.pass_index,
                        "pass_identity": attempt.pass_identity,
                    },
                )
                current = context.job_store.get_job(context.job_id)
                if current is None:
                    raise _replication_error("JOB_GONE", "job expired during provider download", category="worker")
                context.job_store.update_provider_attempt(job_id=context.job_id, expected_version=current.version, attempt=replace(attempt, status="SUCCEEDED"), ttl_seconds=max(1, (current.expires_at_ms - time.time_ns() // 1_000_000) // 1000))
                results.append({"segment_id": attempt.segment_id, "artifact": published, "download": dict(downloaded)})
                pending.pop(attempt.attempt_id, None)

            if not pending:
                break
            if time.monotonic() - started >= self.timeout_seconds:
                for attempt in pending.values():
                    _persist_provider_attempt(context, replace(attempt, status="AMBIGUOUS"))
                raise _replication_error(
                    "PROVIDER_AMBIGUOUS",
                    "provider wait timed out; reconcile the recorded attempts before retrying",
                    retryable=False,
                    category="provider",
                )
            time.sleep(_provider_poll_delay(poll_index))
            poll_index += 1
        if results and all(item.get("confirmed_failure") for item in results if isinstance(item, Mapping)):
            return {
                "status": "FAILED",
                "provider_status": "FAILED",
                "confirmed_failure": True,
                "failure_kind": "provider",
                "results": results,
                "published_artifacts": [
                    artifact
                    for item in results
                    if isinstance(item, Mapping)
                    for artifact in item.get("published_artifacts", ())
                ],
                "create_count_delta": 0,
            }
        if not results:
            raise _replication_error("PROVIDER_RESULT_INVALID", "no successful provider video was available for assembly", category="provider")
        return {"status": "ready", "provider_videos": results}


__all__ = [
    "BindInputsStage", "ProbeSourceStage", "RouteRegionsStage", "VoiceoverTtsFallbackEvaluationStage", "VoiceoverTtsStage",
    "StoryboardStage", "SegmentPlanStage", "AssetBoardStage",
    "H3PromptStage", "H3AuditStage", "H3SubmitStage", "H3WaitStage",
    "SeedancePromptStage", "SeedanceAuditStage", "SubmitProviderVideoStage", "ReconcileProviderAttemptStage", "WaitProviderVideoStage",
]
