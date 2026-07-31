"""Canonical request validation for the RunningHub Seedance standard API.

This boundary is intentionally shared by the service adapter and the bundled
submitter.  It validates only the documented provider request; routing,
approvals, segment ownership, and music provenance remain the responsibility
of their existing USFR contracts.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlparse


RUNNINGHUB_STANDARD_SEEDANCE_FIELDS = frozenset(
    {
        "prompt",
        "resolution",
        "duration",
        "imageUrls",
        "videoUrls",
        "audioUrls",
        "generateAudio",
        "ratio",
        "realPersonMode",
        "conversionSlots",
        "returnLastFrame",
        "seed",
    }
)
_ROUTE_LEAKAGE_MARKERS = (
    "source_video",
    "opaque_ui",
    "ui_demo",
    "opaque_ui_demo",
    "opaque_ui_video",
    "ui_demo_video",
    "generated_ui_demo",
    "generated_ui",
    "ui_render_contract",
    "ui_truth_card",
    "ui_qc_report",
    "ui_operation_video",
    "ui_media",
    "ui_rendered_media",
    "ui_media_sha256",
    "ui_ocr_evidence",
    "ui_layout_evidence",
    "animation_interval_evidence",
    "tail_video",
    "tail_card",
    "tail_card_video",
    "app_tail_card_video",
    "opaque_app_tail_card",
    "opaque_tail",
    "append_opaque_tail",
    "tail_truth_card",
    "tail_render_contract",
    "tail_qc_report",
    "tail_media",
    "tail_media_sha256",
    "rendered_media",
    "media_sha256",
    "qc_report",
    "transition_render_receipt",
    "transition_render_receipts",
    "source_ui_frames",
    "source_interval",
    "source_ui_keep",
    "transition_shell",
    "reference_videos",
    "reference_audios",
    "excluded_app_end_card",
    "omit_source_end_card",
    "excluded_region",
)
_ROUTE_LEAKAGE_EXACT_KEYS = {
    "ui_truth",
    "tail_truth",
    "ui_render",
    "tail_render",
    "ui_qc",
    "tail_qc",
}
_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]", re.DOTALL)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_TAG_RE = re.compile(r"@Image([1-9])(?!\d)")
_IMAGE_REFERENCE_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "ordered_image_urls",
        "approval_set_sha256",
        "image_bindings",
        "slot_policy",
        "forbidden_artifact_names",
    }
)
_IMAGE_BINDING_FIELDS = frozenset(
    {
        "image_index",
        "tag",
        "role",
        "artifact_name",
        "sha256",
        "url",
        "cut_ids",
        "page",
        "approval_set_sha256",
        "purpose",
    }
)
_IMAGE_ROLE_RANK = {
    "new_model_identity": 0,
    "product_or_app_truth": 1,
    "director_storyboard": 2,
    "additional_reference": 3,
}
_FORBIDDEN_IMAGE_ARTIFACT_NAMES = ("seedance_execution_carrier.png",)
_VIDEO_REFERENCE_FIELDS = frozenset(
    {
        "schema_version",
        "url",
        "source_video_sha256",
        "source_slice_sha256",
        "segment_id",
        "segment_plan_sha256",
        "source_video_reference_artifact_id",
        "start_ms",
        "end_ms",
        "image_reference_binding_sha256",
        "target_changes",
    }
)
_FINAL_REFERENCE_LINEAGE_FIELDS = frozenset(
    {
        "schema_version",
        "segment_id",
        "segment_plan_sha256",
        "ordered_image_urls",
        "ordered_video_urls",
        "approved_board",
        "source_reference",
        "allowed_target_changes",
        "forbidden_artifact_kinds",
    }
)
_FINAL_REFERENCE_BOARD_FIELDS = frozenset(
    {
        "artifact_id",
        "object_key",
        "kind",
        "sha256",
        "segment_id",
        "storyboard_revision",
        "storyboard_manifest_sha256",
        "url",
        "source_video_sha256",
        "source_keyframe_sheet_sha256",
        "replacement_control_keyframe_sheet_sha256",
        "replacement_control_keyframe_receipt_sha256",
        "replacement_target_sha256s",
        "approved_visible_text_locks_sha256",
    }
)
_FINAL_REFERENCE_SOURCE_FIELDS = frozenset(
    {
        "artifact_id",
        "object_key",
        "kind",
        "sha256",
        "source_video_sha256",
        "segment_id",
        "segment_plan_sha256",
        "start_ms",
        "end_ms",
        "url",
    }
)
_FINAL_REFERENCE_TARGET_FIELDS = frozenset({"kind", "sha256", "image_slot", "url"})
_FORBIDDEN_FINAL_ARTIFACT_KINDS = (
    "source_keyframe_sheet",
    "replacement_control_keyframe_sheet",
    "replacement_control_keyframe_receipt",
)
_AUDIO_REFERENCE_FIELDS = frozenset(
    {
        "schema_version",
        "url",
        "source_audio_sha256",
        "source_slice_sha256",
        "segment_id",
        "start_ms",
        "end_ms",
        "segment_plan_sha256",
        "replacement_timing_policy",
        "source_music_windows",
    }
)
_AUDIO_ARTIFACT_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "object_key",
        "kind",
        "sha256",
        "source_audio_sha256",
        "segment_id",
        "start_ms",
        "end_ms",
        "segment_plan_sha256",
        "replacement_timing_policy",
        "source_music_windows",
    }
)
_AUDIT_PROOF_FIELDS = frozenset({"schema_version", "hmac_sha256"})
_AUDIT_PROOF_SCHEMA_VERSION = "usfr-provider-audit-proof/v1"
SOURCE_VIDEO_PROMPT_CONTRACT = (
    "@Video1 is the source reference video only for shot structure, composition, camera path, blocking, "
    "action timing, pacing, transitions, and delivery rhythm. "
    "Do not copy or output any person or identity, product/App or merchandise, visible text, original voice, "
    "original narration, or original dialogue from @Video1. "
    "Generate only the approved characters, target product/App evidence, exact visible text, voices, narration, "
    "dialogue, actions, and audio explicitly specified by this prompt and its bound image and audio references."
)


class RunningHubStandardPayloadError(ValueError):
    """Raised when a request cannot safely reach the paid standard API."""


def image_reference_binding_sha256(binding: Mapping[str, object]) -> str:
    """Return the canonical digest for the ordered multimodal image sidecar."""

    return hashlib.sha256(
        json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _image_binding_error(message: str) -> None:
    raise RunningHubStandardPayloadError(f"image reference binding {message}")


def validate_image_reference_binding(
    payload: Mapping[str, object], binding: Mapping[str, object] | None
) -> None:
    """Validate exact @ImageN order, provenance, role, scope, and Prompt closure.

    ``@Video1`` and ``@Audio1`` are separate provider namespaces.  They are
    intentionally ignored by this image-only validator and never consume an
    image index.
    """

    if not isinstance(binding, Mapping) or set(binding) != _IMAGE_REFERENCE_BINDING_FIELDS:
        _image_binding_error("must use the complete usfr-multimodal-reference-binding/v2 schema")
    if binding.get("schema_version") != "usfr-multimodal-reference-binding/v2":
        _image_binding_error("has an unsupported schema version")
    if binding.get("slot_policy") != "continuous-present-role-order/v1":
        _image_binding_error("must declare the deterministic continuous present-role slot policy")
    if binding.get("forbidden_artifact_names") != list(_FORBIDDEN_IMAGE_ARTIFACT_NAMES):
        _image_binding_error("must forbid the Seedance execution carrier")

    image_urls = payload.get("imageUrls")
    ordered_urls = binding.get("ordered_image_urls")
    rows = binding.get("image_bindings")
    if (
        not isinstance(image_urls, list)
        or not 1 <= len(image_urls) <= 9
        or not all(isinstance(url, str) and url for url in image_urls)
    ):
        _image_binding_error("requires between one and nine uploaded image URLs")
    if not isinstance(ordered_urls, list) or ordered_urls != image_urls:
        _image_binding_error("URL order must exactly match imageUrls")
    if not isinstance(rows, list) or len(rows) != len(image_urls):
        _image_binding_error("must bind every uploaded image exactly once")

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        _image_binding_error("requires a non-empty prompt")
    prompt_tags = {f"@Image{match}" for match in _IMAGE_TAG_RE.findall(prompt)}
    expected_tags = {f"@Image{index}" for index in range(1, len(image_urls) + 1)}
    if prompt_tags != expected_tags:
        missing = sorted(expected_tags - prompt_tags)
        extra = sorted(prompt_tags - expected_tags)
        _image_binding_error(f"prompt tags must equal uploaded tags; missing={missing}, extra={extra}")

    roles: list[str] = []
    seen_urls: set[str] = set()
    seen_sha256s: set[str] = set()
    storyboards: list[Mapping[str, object]] = []
    model_count = 0
    product_count = 0
    for expected_index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping) or set(row) != _IMAGE_BINDING_FIELDS:
            _image_binding_error("contains an incomplete image descriptor")
        if row.get("image_index") != expected_index or row.get("tag") != f"@Image{expected_index}":
            _image_binding_error("index/tag order is not contiguous or differs from imageUrls")
        if row.get("url") != image_urls[expected_index - 1]:
            _image_binding_error("descriptor URL order differs from imageUrls")
        role = row.get("role")
        if role not in _IMAGE_ROLE_RANK:
            _image_binding_error("contains an unsupported image role")
        roles.append(str(role))
        if role == "new_model_identity":
            model_count += 1
        elif role == "product_or_app_truth":
            product_count += 1
        elif role == "director_storyboard":
            storyboards.append(row)

        artifact_name = row.get("artifact_name")
        if not isinstance(artifact_name, str) or not artifact_name.strip():
            _image_binding_error("requires an artifact name for every image")
        if artifact_name.casefold() in {name.casefold() for name in _FORBIDDEN_IMAGE_ARTIFACT_NAMES}:
            _image_binding_error("forbids seedance execution carrier images")
        sha256 = row.get("sha256")
        if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
            _image_binding_error("requires a SHA-256 for every image")
        if str(row["url"]) in seen_urls or sha256 in seen_sha256s:
            _image_binding_error("forbids duplicate image URLs or SHA-256 values")
        seen_urls.add(str(row["url"]))
        seen_sha256s.add(sha256)
        cut_ids = row.get("cut_ids")
        if (
            not isinstance(cut_ids, list)
            or not cut_ids
            or len(cut_ids) != len(set(cut_ids))
            or not all(isinstance(cut_id, str) and cut_id.strip() for cut_id in cut_ids)
        ):
            _image_binding_error("requires a non-empty unique Cut scope for every image")
        if not isinstance(row.get("purpose"), str) or not str(row["purpose"]).strip():
            _image_binding_error("requires an explicit purpose for every image")

    ranks = [_IMAGE_ROLE_RANK[role] for role in roles]
    if ranks != sorted(ranks) or model_count > 1 or product_count > 1:
        _image_binding_error("role order must be model, product/App, storyboard pages, then additional references")
    if model_count and roles[0] != "new_model_identity":
        _image_binding_error("role order must place the new model at @Image1")
    product_index = roles.index("product_or_app_truth") if product_count else None
    if product_index is not None and product_index != model_count:
        _image_binding_error("role order must place product/App truth immediately after the present model role")

    approval_set_sha256 = binding.get("approval_set_sha256")
    if not storyboards:
        if approval_set_sha256 is not None:
            _image_binding_error("storyboard approval set must be null when no storyboard image is uploaded")
        return
    if len(storyboards) > 2:
        _image_binding_error("storyboard upload supports at most two approved pages")
    if not isinstance(approval_set_sha256, str) or _SHA256_RE.fullmatch(approval_set_sha256) is None:
        _image_binding_error("storyboard pages require one SHA-bound approval set")
    pages = [row.get("page") for row in storyboards]
    if pages != list(range(1, len(storyboards) + 1)):
        _image_binding_error("storyboard pages must be complete, unique, and ordered")
    storyboard_cuts: set[str] = set()
    for row in storyboards:
        if row.get("approval_set_sha256") != approval_set_sha256:
            _image_binding_error("storyboard pages must bind the same approved set")
        cuts = set(str(cut_id) for cut_id in row["cut_ids"])
        if storyboard_cuts.intersection(cuts):
            _image_binding_error("storyboard page Cut scopes must not overlap")
        storyboard_cuts.update(cuts)


def _route_tokens(value: str) -> list[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    separated = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", separated)
    return re.findall(r"[a-z0-9]+", separated.casefold())


def _canonical_route_key(value: str) -> str:
    return "_".join(_route_tokens(value))


def _route_leakage_matches(value: str) -> list[str]:
    tokens = _route_tokens(value)
    if not tokens:
        return []
    token_set = set(tokens)
    matches: list[str] = []
    for marker in _ROUTE_LEAKAGE_MARKERS:
        marker_tokens = _route_tokens(marker)
        width = len(marker_tokens)
        compact = "".join(marker_tokens)
        if compact in token_set or any(
            tokens[index : index + width] == marker_tokens
            for index in range(len(tokens) - width + 1)
        ):
            matches.append(marker)
    return matches


def _route_leakage_in_value(value: object) -> list[str]:
    matches: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                canonical_key = _canonical_route_key(key)
                if canonical_key in _ROUTE_LEAKAGE_EXACT_KEYS:
                    matches.append(key)
                matches.extend(_route_leakage_matches(key))
            matches.extend(_route_leakage_in_value(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            matches.extend(_route_leakage_in_value(child))
    elif isinstance(value, str):
        matches.extend(_route_leakage_matches(value))
    return list(dict.fromkeys(matches))


def _contains_unresolved_placeholder(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_unresolved_placeholder(key) or _contains_unresolved_placeholder(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unresolved_placeholder(child) for child in value)
    return isinstance(value, str) and _PLACEHOLDER_RE.search(value) is not None


def validate_public_https_url(value: object) -> str:
    """Return one public HTTPS URL or reject loopback, private, and link-local hosts."""

    if not isinstance(value, str):
        raise RunningHubStandardPayloadError("media URLs must be public HTTPS URLs")
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
    except ValueError as error:
        raise RunningHubStandardPayloadError("media URLs must be public HTTPS URLs") from error
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise RunningHubStandardPayloadError("media URLs must be public HTTPS URLs")
    normalized_host = hostname.rstrip(".").casefold()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost") or normalized_host.endswith(".local"):
        raise RunningHubStandardPayloadError("media URLs must be public HTTPS URLs")
    try:
        address = ipaddress.ip_address(unquote(hostname).split("%", 1)[0])
    except ValueError:
        return value
    if not address.is_global:
        raise RunningHubStandardPayloadError("media URLs must be public HTTPS URLs")
    return value


def validate_video_reference_binding(
    payload: Mapping[str, object], binding: Mapping[str, object] | None
) -> None:
    """Validate the auditable binding for the one permitted source-video reference."""

    video_urls = payload.get("videoUrls")
    if not isinstance(video_urls, list) or not all(isinstance(url, str) for url in video_urls):
        raise RunningHubStandardPayloadError("videoUrls must be a list of public HTTPS URLs")
    if not video_urls:
        if binding is not None:
            raise RunningHubStandardPayloadError("an empty videoUrls payload cannot carry a video reference binding")
        return
    if len(video_urls) != 1:
        raise RunningHubStandardPayloadError("USFR accepts exactly one source segment video reference")
    if not isinstance(binding, Mapping) or set(binding) != _VIDEO_REFERENCE_FIELDS:
        raise RunningHubStandardPayloadError("a source video reference requires a complete usfr-video-reference/v1 binding")
    if binding.get("schema_version") != "usfr-video-reference/v1":
        raise RunningHubStandardPayloadError("source video reference binding has an unsupported schema version")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or SOURCE_VIDEO_PROMPT_CONTRACT not in prompt:
        raise RunningHubStandardPayloadError(
            "source reference video prompt contract must name @Video1 as reference-only, forbid transfer of source "
            "people, products/Apps, visible text, voice, narration, and dialogue, and bind output to approved prompt content"
        )
    if binding.get("url") != video_urls[0]:
        raise RunningHubStandardPayloadError("source video reference binding URL differs from videoUrls[0]")
    if not all(
        isinstance(binding.get(key), str) and _SHA256_RE.fullmatch(str(binding[key]))
        for key in ("source_video_sha256", "source_slice_sha256", "segment_plan_sha256")
    ):
        raise RunningHubStandardPayloadError("source video reference binding requires SHA-256 source, slice, and plan evidence")
    if binding["source_video_sha256"] == binding["source_slice_sha256"]:
        raise RunningHubStandardPayloadError(
            "source video reference binding requires a distinct bounded slice, never the complete source upload"
        )
    artifact_id = binding.get("source_video_reference_artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise RunningHubStandardPayloadError("source video reference binding requires the immutable source slice artifact identity")
    segment_id = binding.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id.strip():
        raise RunningHubStandardPayloadError("source video reference binding requires a segment ID")
    start_ms, end_ms = binding.get("start_ms"), binding.get("end_ms")
    if (
        isinstance(start_ms, bool)
        or isinstance(end_ms, bool)
        or not isinstance(start_ms, int)
        or not isinstance(end_ms, int)
        or start_ms < 0
        or end_ms - start_ms not in range(2_000, 15_001)
    ):
        raise RunningHubStandardPayloadError("source video reference binding requires a 2-15 second frozen segment window")
    if (
        not isinstance(binding.get("image_reference_binding_sha256"), str)
        or _SHA256_RE.fullmatch(str(binding["image_reference_binding_sha256"])) is None
    ):
        raise RunningHubStandardPayloadError(
            "a source video reference requires the complete multimodal image binding digest"
        )
    target_changes = binding.get("target_changes")
    if not isinstance(target_changes, list) or not target_changes:
        raise RunningHubStandardPayloadError("a source video reference requires an authorized target change")
    for change in target_changes:
        if not isinstance(change, Mapping):
            raise RunningHubStandardPayloadError("source video reference target changes are invalid")
        kind = change.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise RunningHubStandardPayloadError("source video reference target changes are invalid")
        if kind == "output_language":
            if set(change) != {"kind", "value"} or not isinstance(change.get("value"), str) or not change["value"].strip():
                raise RunningHubStandardPayloadError("output_language target change is invalid")
        elif set(change) != {"kind", "sha256"} or not isinstance(change.get("sha256"), str) or not _SHA256_RE.fullmatch(str(change["sha256"])):
            raise RunningHubStandardPayloadError("source video reference target change requires SHA-256 evidence")
    if payload.get("realPersonMode") is not True:
        raise RunningHubStandardPayloadError("a source video reference requires realPersonMode=true")


def _final_reference_lineage_error(message: str) -> None:
    raise RunningHubStandardPayloadError(f"final reference lineage {message}")


def _final_reference_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _final_reference_lineage_error(f"requires a SHA-256 {label}")
    return value


def _final_reference_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _final_reference_lineage_error(f"requires {label}")
    return value


def validate_final_reference_lineage(
    payload: Mapping[str, object], lineage: Mapping[str, object] | None
) -> None:
    """Validate the private binding for every source-fidelity Seedance request.

    The public RunningHub payload deliberately remains unchanged.  This sidecar
    proves its fixed media order: approved director board at ``@Image1``, only
    fixed user model/product targets after it, and the matching source slice at
    ``videoUrls[0]``.  Internal source/control sheets are never admissible.
    """

    if isinstance(lineage, Mapping) and lineage.get("schema_version") == "seedance-final-reference-lineage/v2":
        expected = {
            "schema_version",
            "segment_id",
            "segment_plan_sha256",
            "ordered_image_urls",
            "ordered_video_urls",
            "image_reference_binding",
            "source_reference",
            "forbidden_artifact_kinds",
        }
        if set(lineage) != expected:
            _final_reference_lineage_error("must use the complete seedance-final-reference-lineage/v2 schema")
        segment_id = _final_reference_text(lineage.get("segment_id"), "a segment ID")
        plan_sha256 = _final_reference_sha256(lineage.get("segment_plan_sha256"), "segment plan")
        if lineage.get("ordered_image_urls") != payload.get("imageUrls") or lineage.get("ordered_video_urls") != payload.get("videoUrls"):
            _final_reference_lineage_error("ordered provider URLs do not exactly match the payload")
        image_binding = lineage.get("image_reference_binding")
        validate_image_reference_binding(payload, image_binding if isinstance(image_binding, Mapping) else None)
        source = lineage.get("source_reference")
        if not isinstance(source, Mapping) or set(source) != _FINAL_REFERENCE_SOURCE_FIELDS:
            _final_reference_lineage_error("source reference descriptor is incomplete")
        if source.get("kind") != "source_video_reference":
            _final_reference_lineage_error("source reference must be a source_video_reference artifact")
        _final_reference_text(source.get("artifact_id"), "source slice artifact identity")
        _final_reference_text(source.get("object_key"), "source slice object identity")
        source_slice_sha256 = _final_reference_sha256(source.get("sha256"), "source slice")
        source_video_sha256 = _final_reference_sha256(source.get("source_video_sha256"), "source video")
        if source_slice_sha256 == source_video_sha256:
            _final_reference_lineage_error("source slice must be a distinct bounded artifact, never the complete source")
        video_urls = payload.get("videoUrls")
        if (
            not isinstance(video_urls, list)
            or len(video_urls) != 1
            or source.get("url") != video_urls[0]
            or source.get("segment_id") != segment_id
            or source.get("segment_plan_sha256") != plan_sha256
        ):
            _final_reference_lineage_error("source slice does not match the frozen segment plan or videoUrls[0]")
        start_ms, end_ms = source.get("start_ms"), source.get("end_ms")
        if (
            isinstance(start_ms, bool)
            or isinstance(end_ms, bool)
            or not isinstance(start_ms, int)
            or not isinstance(end_ms, int)
            or start_ms < 0
            or end_ms - start_ms not in range(2_000, 15_001)
        ):
            _final_reference_lineage_error("source slice requires a frozen 2-15 second window")
        if lineage.get("forbidden_artifact_kinds") != list(_FORBIDDEN_FINAL_ARTIFACT_KINDS):
            _final_reference_lineage_error("must forbid every internal keyframe/control artifact kind")
        return

    if not isinstance(lineage, Mapping) or set(lineage) != _FINAL_REFERENCE_LINEAGE_FIELDS:
        _final_reference_lineage_error("must use the complete seedance-final-reference-lineage/v1 schema")
    if lineage.get("schema_version") != "seedance-final-reference-lineage/v1":
        _final_reference_lineage_error("has an unsupported schema version")
    segment_id = _final_reference_text(lineage.get("segment_id"), "a segment ID")
    plan_sha256 = _final_reference_sha256(lineage.get("segment_plan_sha256"), "segment plan")

    image_urls = payload.get("imageUrls")
    video_urls = payload.get("videoUrls")
    ordered_images = lineage.get("ordered_image_urls")
    ordered_videos = lineage.get("ordered_video_urls")
    if (
        not isinstance(image_urls, list)
        or not isinstance(video_urls, list)
        or not isinstance(ordered_images, list)
        or not isinstance(ordered_videos, list)
        or image_urls != ordered_images
        or video_urls != ordered_videos
    ):
        _final_reference_lineage_error("ordered provider URLs do not exactly match the payload")
    if not image_urls or not all(isinstance(url, str) and url for url in image_urls):
        _final_reference_lineage_error("requires the approved director board at imageUrls[0]")
    if len(video_urls) != 1 or not isinstance(video_urls[0], str) or not video_urls[0]:
        _final_reference_lineage_error("requires exactly one matching source segment at videoUrls[0]")
    if lineage.get("forbidden_artifact_kinds") != list(_FORBIDDEN_FINAL_ARTIFACT_KINDS):
        _final_reference_lineage_error("must forbid every internal keyframe/control artifact kind")

    board = lineage.get("approved_board")
    if not isinstance(board, Mapping) or set(board) != _FINAL_REFERENCE_BOARD_FIELDS:
        _final_reference_lineage_error("approved board descriptor is incomplete")
    if board.get("kind") != "storyboard_image":
        _final_reference_lineage_error("approved board must be a storyboard_image artifact")
    _final_reference_text(board.get("artifact_id"), "approved board artifact identity")
    _final_reference_text(board.get("object_key"), "approved board object identity")
    board_sha256 = _final_reference_sha256(board.get("sha256"), "approved board")
    if board.get("segment_id") != segment_id or board.get("url") != image_urls[0]:
        _final_reference_lineage_error("approved board does not occupy imageUrls[0] for this segment")
    revision = board.get("storyboard_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        _final_reference_lineage_error("approved board requires a positive storyboard revision")
    for field in (
        "storyboard_manifest_sha256",
        "source_video_sha256",
        "source_keyframe_sheet_sha256",
        "replacement_control_keyframe_sheet_sha256",
        "replacement_control_keyframe_receipt_sha256",
        "approved_visible_text_locks_sha256",
    ):
        _final_reference_sha256(board.get(field), f"approved board {field}")
    board_targets = board.get("replacement_target_sha256s")
    if not isinstance(board_targets, list) or any(
        not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None for value in board_targets
    ):
        _final_reference_lineage_error("approved board replacement target SHA list is invalid")
    internal_board_hashes = {
        board_sha256,
        str(board["source_keyframe_sheet_sha256"]),
        str(board["replacement_control_keyframe_sheet_sha256"]),
        str(board["replacement_control_keyframe_receipt_sha256"]),
    }

    source = lineage.get("source_reference")
    if not isinstance(source, Mapping) or set(source) != _FINAL_REFERENCE_SOURCE_FIELDS:
        _final_reference_lineage_error("source reference descriptor is incomplete")
    if source.get("kind") != "source_video_reference":
        _final_reference_lineage_error("source reference must be a source_video_reference artifact")
    _final_reference_text(source.get("artifact_id"), "source slice artifact identity")
    _final_reference_text(source.get("object_key"), "source slice object identity")
    source_slice_sha256 = _final_reference_sha256(source.get("sha256"), "source slice")
    source_video_sha256 = _final_reference_sha256(source.get("source_video_sha256"), "source video")
    if source_slice_sha256 == source_video_sha256:
        _final_reference_lineage_error("source slice must be a distinct bounded artifact, never the complete source")
    if source_video_sha256 != board.get("source_video_sha256"):
        _final_reference_lineage_error("source slice and approved board use different source videos")
    if (
        source.get("segment_id") != segment_id
        or source.get("segment_plan_sha256") != plan_sha256
        or source.get("url") != video_urls[0]
    ):
        _final_reference_lineage_error("source slice does not match the frozen segment plan or videoUrls[0]")
    start_ms, end_ms = source.get("start_ms"), source.get("end_ms")
    if (
        isinstance(start_ms, bool)
        or isinstance(end_ms, bool)
        or not isinstance(start_ms, int)
        or not isinstance(end_ms, int)
        or start_ms < 0
        or end_ms - start_ms not in range(2_000, 15_001)
    ):
        _final_reference_lineage_error("source slice requires a frozen 2-15 second window")
    if source_slice_sha256 in internal_board_hashes:
        _final_reference_lineage_error("source slice cannot be an internal keyframe/control artifact")

    targets = lineage.get("allowed_target_changes")
    if not isinstance(targets, list) or len(targets) != len(image_urls) - 1:
        _final_reference_lineage_error("target slots must cover every image after the approved board exactly once")
    actual_target_sha256s: list[str] = []
    for index, target in enumerate(targets, start=2):
        if not isinstance(target, Mapping) or set(target) != _FINAL_REFERENCE_TARGET_FIELDS:
            _final_reference_lineage_error("target descriptor is invalid")
        if target.get("kind") not in {"new_model_image", "new_product_image"}:
            _final_reference_lineage_error("forbids internal or non-fixed target artifacts")
        if target.get("image_slot") != index or target.get("url") != image_urls[index - 1]:
            _final_reference_lineage_error("target provider URL order is not fixed-slot order")
        target_sha256 = _final_reference_sha256(target.get("sha256"), "target")
        if target_sha256 in internal_board_hashes:
            _final_reference_lineage_error("forbids internal keyframe/control artifacts in target slots")
        actual_target_sha256s.append(target_sha256)
    if actual_target_sha256s != list(board_targets):
        _final_reference_lineage_error("approved board target lineage differs from final target slots")


def validate_audio_reference_binding(
    payload: Mapping[str, object], binding: Mapping[str, object] | None
) -> None:
    """Validate the immutable sidecar for the one permitted music slice."""

    audio_urls = payload.get("audioUrls")
    if not isinstance(audio_urls, list) or not all(isinstance(url, str) for url in audio_urls):
        raise RunningHubStandardPayloadError("audioUrls must be a list of public HTTPS URLs")
    if not audio_urls:
        if binding is not None:
            raise RunningHubStandardPayloadError("an empty audioUrls payload cannot carry an audio reference binding")
        return
    if len(audio_urls) != 1:
        raise RunningHubStandardPayloadError("USFR accepts exactly one background-music reference")
    if not isinstance(binding, Mapping) or set(binding) != _AUDIO_REFERENCE_FIELDS:
        raise RunningHubStandardPayloadError("an audio reference requires a complete usfr-background-music-reference/v1 binding")
    if binding.get("schema_version") != "usfr-background-music-reference/v1":
        raise RunningHubStandardPayloadError("audio reference binding has an unsupported schema version")
    if binding.get("url") != audio_urls[0]:
        raise RunningHubStandardPayloadError("audio reference binding URL differs from audioUrls[0]")
    if not all(
        isinstance(binding.get(key), str) and _SHA256_RE.fullmatch(str(binding[key]))
        for key in ("source_audio_sha256", "source_slice_sha256", "segment_plan_sha256")
    ):
        raise RunningHubStandardPayloadError("audio reference binding requires SHA-256 source, slice, and plan evidence")
    if binding["source_audio_sha256"] == binding["source_slice_sha256"]:
        raise RunningHubStandardPayloadError("audio reference binding must identify a sliced upload, not the complete song")
    segment_id = binding.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id.strip():
        raise RunningHubStandardPayloadError("audio reference binding requires a segment ID")
    start_ms, end_ms = binding.get("start_ms"), binding.get("end_ms")
    if (
        isinstance(start_ms, bool)
        or isinstance(end_ms, bool)
        or not isinstance(start_ms, int)
        or not isinstance(end_ms, int)
        or start_ms < 0
        or end_ms - start_ms not in range(2_000, 15_001)
    ):
        raise RunningHubStandardPayloadError("audio reference binding requires a 2-15 second frozen segment window")
    if binding.get("replacement_timing_policy") != "source_music_cut_in_out_exact":
        raise RunningHubStandardPayloadError("audio reference binding must preserve exact source music cut-in/cut-out timing")
    windows = binding.get("source_music_windows")
    if not isinstance(windows, list) or not windows:
        raise RunningHubStandardPayloadError("audio reference binding requires exact source music windows")
    previous_segment_end = 0
    seen_event_ids: set[str] = set()
    for raw_window in windows:
        if not isinstance(raw_window, Mapping) or set(raw_window) != {
            "event_id",
            "source_start_ms",
            "source_end_ms",
            "segment_start_ms",
            "segment_end_ms",
            "uploaded_start_ms",
            "uploaded_end_ms",
        }:
            raise RunningHubStandardPayloadError("audio reference binding source music window is invalid")
        event_id = raw_window.get("event_id")
        values = {
            key: raw_window.get(key)
            for key in (
                "source_start_ms",
                "source_end_ms",
                "segment_start_ms",
                "segment_end_ms",
                "uploaded_start_ms",
                "uploaded_end_ms",
            )
        }
        if (
            not isinstance(event_id, str)
            or not event_id.strip()
            or event_id in seen_event_ids
            or any(isinstance(value, bool) or not isinstance(value, int) for value in values.values())
            or values["source_start_ms"] < 0
            or values["source_end_ms"] <= values["source_start_ms"]
            or values["segment_start_ms"] < previous_segment_end
            or values["segment_end_ms"] <= values["segment_start_ms"]
            or values["segment_end_ms"] > end_ms - start_ms
            or values["uploaded_start_ms"] < 0
            or values["uploaded_end_ms"] <= values["uploaded_start_ms"]
            or values["source_end_ms"] - values["source_start_ms"] < values["segment_end_ms"] - values["segment_start_ms"]
            or values["uploaded_end_ms"] - values["uploaded_start_ms"] != values["segment_end_ms"] - values["segment_start_ms"]
        ):
            raise RunningHubStandardPayloadError("audio reference binding source music window is invalid")
        previous_segment_end = values["segment_end_ms"]
        seen_event_ids.add(event_id)


def validate_audio_reference_artifact_receipt(
    binding: Mapping[str, object], receipt: Mapping[str, object] | None
) -> None:
    """Require a server-published immutable artifact behind a music sidecar.

    A URL and hashes in ``audio_reference_binding`` remain caller-controllable
    data until they are paired with this receipt.  The receipt is projected only
    from the immutable ``background_music_reference`` artifact the audit stage
    just published, and its complete contents are covered by the service-held
    provider-audit HMAC.
    """

    if not isinstance(receipt, Mapping) or set(receipt) != _AUDIO_ARTIFACT_RECEIPT_FIELDS:
        raise RunningHubStandardPayloadError("audio reference requires a server-issued audio artifact receipt")
    if receipt.get("schema_version") != "usfr-background-music-artifact-receipt/v1":
        raise RunningHubStandardPayloadError("audio artifact receipt has an unsupported schema version")
    if receipt.get("kind") != "background_music_reference":
        raise RunningHubStandardPayloadError("audio artifact receipt must name a background_music_reference artifact")
    for field in ("artifact_id", "object_key", "segment_id"):
        if not isinstance(receipt.get(field), str) or not str(receipt[field]).strip():
            raise RunningHubStandardPayloadError("audio artifact receipt requires immutable artifact identity")
    for field in ("sha256", "source_audio_sha256", "segment_plan_sha256"):
        if not isinstance(receipt.get(field), str) or _SHA256_RE.fullmatch(str(receipt[field])) is None:
            raise RunningHubStandardPayloadError("audio artifact receipt requires SHA-256 evidence")
    for field in (
        "sha256",
        "source_audio_sha256",
        "segment_id",
        "start_ms",
        "end_ms",
        "segment_plan_sha256",
        "replacement_timing_policy",
        "source_music_windows",
    ):
        if receipt.get(field) != binding.get(
            "source_slice_sha256" if field == "sha256" else field
        ):
            raise RunningHubStandardPayloadError("audio artifact receipt does not match the duration-bounded audio binding")


def _provider_audit_proof_bytes(
    payload: Mapping[str, object],
    video_reference_binding: Mapping[str, object] | None,
    audio_reference_binding: Mapping[str, object] | None,
    audio_reference_artifact_receipt: Mapping[str, object] | None,
) -> bytes:
    return json.dumps(
        {
            "schema_version": _AUDIT_PROOF_SCHEMA_VERSION,
            "payload": dict(payload),
            "video_reference_binding": dict(video_reference_binding) if isinstance(video_reference_binding, Mapping) else None,
            "audio_reference_binding": dict(audio_reference_binding) if isinstance(audio_reference_binding, Mapping) else None,
            "audio_reference_artifact_receipt": dict(audio_reference_artifact_receipt) if isinstance(audio_reference_artifact_receipt, Mapping) else None,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_provider_audit_proof(
    payload: Mapping[str, object],
    video_reference_binding: Mapping[str, object] | None,
    audio_reference_binding: Mapping[str, object] | None,
    *,
    secret: str,
    audio_reference_artifact_receipt: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Sign a server-audited provider request without extending its HTTP body."""

    if not isinstance(secret, str) or not secret:
        raise RunningHubStandardPayloadError("provider audit proof requires a server capability secret")
    digest = hmac.new(
        secret.encode("utf-8"),
        _provider_audit_proof_bytes(
            payload,
            video_reference_binding,
            audio_reference_binding,
            audio_reference_artifact_receipt,
        ),
        hashlib.sha256,
    ).hexdigest()
    return {"schema_version": _AUDIT_PROOF_SCHEMA_VERSION, "hmac_sha256": digest}


def validate_provider_audit_proof(
    payload: Mapping[str, object],
    video_reference_binding: Mapping[str, object] | None,
    audio_reference_binding: Mapping[str, object] | None,
    proof: Mapping[str, object] | None,
    *,
    secret: str,
    audio_reference_artifact_receipt: Mapping[str, object] | None = None,
) -> None:
    """Require a current service-side HMAC whenever a music URL is supplied."""

    audio_urls = payload.get("audioUrls")
    if not isinstance(audio_urls, list):
        raise RunningHubStandardPayloadError("audioUrls must be a list of public HTTPS URLs")
    if not audio_urls:
        return
    validate_audio_reference_artifact_receipt(audio_reference_binding or {}, audio_reference_artifact_receipt)
    if not isinstance(proof, Mapping) or set(proof) != _AUDIT_PROOF_FIELDS:
        raise RunningHubStandardPayloadError("audio reference requires a service-side provider audit proof")
    if proof.get("schema_version") != _AUDIT_PROOF_SCHEMA_VERSION:
        raise RunningHubStandardPayloadError("provider audit proof has an unsupported schema version")
    actual = proof.get("hmac_sha256")
    if not isinstance(actual, str) or _SHA256_RE.fullmatch(actual) is None:
        raise RunningHubStandardPayloadError("provider audit proof is invalid")
    expected = build_provider_audit_proof(
        payload,
        video_reference_binding,
        audio_reference_binding,
        secret=secret,
        audio_reference_artifact_receipt=audio_reference_artifact_receipt,
    )["hmac_sha256"]
    if not hmac.compare_digest(actual, expected):
        raise RunningHubStandardPayloadError("provider audit proof does not match the audited request")


def validate_runninghub_standard_payload_contract(payload: Mapping[str, object]) -> None:
    """Validate the exact documented fixed-B request before any paid call."""

    if not isinstance(payload, Mapping) or set(payload) != RUNNINGHUB_STANDARD_SEEDANCE_FIELDS:
        raise RunningHubStandardPayloadError(
            "standard Seedance payload contains unknown or missing provider fields"
        )
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or prompt != prompt.strip() or not 1 <= len(prompt) <= 20_480:
        raise RunningHubStandardPayloadError("prompt must contain 1-20480 trimmed characters")
    leaked = _route_leakage_in_value(payload)
    if leaked:
        raise RunningHubStandardPayloadError(
            "route leakage detected in Seedance prompt or provider payload: " + ", ".join(leaked)
        )
    if _contains_unresolved_placeholder(payload):
        raise RunningHubStandardPayloadError("compiled prompt contains unresolved placeholders")
    if payload.get("resolution") not in {"480p", "720p", "1080p", "2k", "4k"}:
        raise RunningHubStandardPayloadError("resolution is not supported by RunningHub Seedance")
    if payload.get("ratio") not in {"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}:
        raise RunningHubStandardPayloadError("ratio is not supported by RunningHub Seedance")
    if payload.get("duration") not in {str(value) for value in range(4, 16)}:
        raise RunningHubStandardPayloadError("duration must be a string between 4 and 15 seconds")
    image_urls = payload.get("imageUrls")
    audio_urls = payload.get("audioUrls")
    video_urls = payload.get("videoUrls")
    if not isinstance(image_urls, list) or not all(isinstance(url, str) for url in image_urls):
        raise RunningHubStandardPayloadError("imageUrls must be a list of public HTTPS URLs")
    if not isinstance(video_urls, list) or not all(isinstance(url, str) for url in video_urls):
        raise RunningHubStandardPayloadError("videoUrls must be a list of public HTTPS URLs")
    if not isinstance(audio_urls, list) or not all(isinstance(url, str) for url in audio_urls):
        raise RunningHubStandardPayloadError("audioUrls must be a list of public HTTPS URLs")
    if len(image_urls) > 9:
        raise RunningHubStandardPayloadError("RunningHub Seedance accepts at most 9 images")
    if len(video_urls) > 1:
        raise RunningHubStandardPayloadError("USFR accepts exactly zero or one segment video reference")
    if len(audio_urls) > 1:
        raise RunningHubStandardPayloadError("USFR accepts at most one segment audio reference")
    for url in [*image_urls, *video_urls, *audio_urls]:
        validate_public_https_url(url)
    if audio_urls:
        if not image_urls:
            raise RunningHubStandardPayloadError(
                "an audio reference requires an approved image reference in the fixed-B route"
            )
        if "@Audio1" not in prompt:
            raise RunningHubStandardPayloadError("uploaded-song audio requires @Audio1 in the prompt")
    if payload.get("generateAudio") is not True:
        raise RunningHubStandardPayloadError("generateAudio must be enabled")
    real_person_mode = payload.get("realPersonMode")
    if not isinstance(real_person_mode, bool):
        raise RunningHubStandardPayloadError("realPersonMode must be a boolean")
    if payload.get("conversionSlots") != (["all"] if real_person_mode else []):
        raise RunningHubStandardPayloadError("conversionSlots must match realPersonMode")
    if payload.get("returnLastFrame") is not False or payload.get("seed") != -1:
        raise RunningHubStandardPayloadError("returnLastFrame and seed must use the fixed USFR values")


__all__ = [
    "RUNNINGHUB_STANDARD_SEEDANCE_FIELDS",
    "SOURCE_VIDEO_PROMPT_CONTRACT",
    "RunningHubStandardPayloadError",
    "build_provider_audit_proof",
    "image_reference_binding_sha256",
    "validate_public_https_url",
    "validate_audio_reference_binding",
    "validate_audio_reference_artifact_receipt",
    "validate_final_reference_lineage",
    "validate_image_reference_binding",
    "validate_provider_audit_proof",
    "validate_runninghub_standard_payload_contract",
    "validate_video_reference_binding",
]
