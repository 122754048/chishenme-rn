"""Canonical request validation for the RunningHub Seedance standard API.

This boundary is intentionally shared by the service adapter and the bundled
submitter.  It validates only the documented provider request; routing,
approvals, segment ownership, and music provenance remain the responsibility
of their existing USFR contracts.
"""

from __future__ import annotations

import ipaddress
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
_VIDEO_REFERENCE_FIELDS = frozenset(
    {
        "schema_version",
        "url",
        "source_video_sha256",
        "source_slice_sha256",
        "segment_id",
        "start_ms",
        "end_ms",
        "storyboard_url",
        "target_changes",
    }
)
_VIDEO_REFERENCE_TARGET_CHANGE_KINDS = frozenset(
    {
        "new_model_image",
        "new_product_image",
        "ui_screenshot",
        "app_store_evidence",
        "ui_operation_video",
        "tail_video",
        "approved_script",
        "background_music",
        "output_language",
    }
)
_OUTPUT_LANGUAGE_CODES = frozenset({"en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"})


class RunningHubStandardPayloadError(ValueError):
    """Raised when a request cannot safely reach the paid standard API."""


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
    video_urls = payload.get("videoUrls")
    audio_urls = payload.get("audioUrls")
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
    if video_urls and (not image_urls or not real_person_mode):
        raise RunningHubStandardPayloadError(
            "a video reference requires an approved storyboard image and realPersonMode=true"
        )
    if payload.get("returnLastFrame") is not False or payload.get("seed") != -1:
        raise RunningHubStandardPayloadError("returnLastFrame and seed must use the fixed USFR values")


def validate_video_reference_binding(
    payload: Mapping[str, object],
    binding: Mapping[str, object] | None,
    *,
    expected_segment: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    """Validate the non-provider receipt that authorizes one source-video reference."""

    video_urls = payload.get("videoUrls")
    if not isinstance(video_urls, list):
        raise RunningHubStandardPayloadError("videoUrls must be a list before binding a video reference")
    if not video_urls:
        if binding is not None:
            raise RunningHubStandardPayloadError("a video reference binding requires videoUrls[0]")
        return None
    if len(video_urls) != 1:
        raise RunningHubStandardPayloadError("a video reference binding requires exactly one videoUrls item")
    if not isinstance(binding, Mapping) or set(binding) != _VIDEO_REFERENCE_FIELDS:
        raise RunningHubStandardPayloadError("video reference binding has unknown or missing fields")
    normalized = dict(binding)
    if normalized.get("schema_version") != "usfr-video-reference/v1":
        raise RunningHubStandardPayloadError("video reference binding schema is invalid")
    if normalized.get("url") != video_urls[0]:
        raise RunningHubStandardPayloadError("video reference URL differs from videoUrls[0]")
    validate_public_https_url(normalized["url"])
    image_urls = payload.get("imageUrls")
    if (
        not isinstance(image_urls, list)
        or not image_urls
        or normalized.get("storyboard_url") != image_urls[0]
        or "@Image1" not in str(payload.get("prompt") or "")
    ):
        raise RunningHubStandardPayloadError("video reference requires the approved storyboard at @Image1")
    for field in ("source_video_sha256", "source_slice_sha256"):
        if not isinstance(normalized.get(field), str) or _SHA256_RE.fullmatch(normalized[field]) is None:
            raise RunningHubStandardPayloadError(f"video reference {field} must be a lowercase SHA-256")
    if not isinstance(normalized.get("segment_id"), str) or not normalized["segment_id"].strip():
        raise RunningHubStandardPayloadError("video reference segment_id is required")
    start_ms = normalized.get("start_ms")
    end_ms = normalized.get("end_ms")
    if (
        isinstance(start_ms, bool)
        or isinstance(end_ms, bool)
        or not isinstance(start_ms, int)
        or not isinstance(end_ms, int)
        or not 0 <= start_ms < end_ms
        or not 2_000 <= end_ms - start_ms <= 15_000
    ):
        raise RunningHubStandardPayloadError("video reference must bind one 2-15 second source segment")
    if expected_segment is not None:
        if (
            normalized["segment_id"] != expected_segment.get("segment_id")
            or start_ms != expected_segment.get("start_ms")
            or end_ms != expected_segment.get("end_ms")
        ):
            raise RunningHubStandardPayloadError("video reference does not match the frozen generation segment")
    target_changes = normalized.get("target_changes")
    if not isinstance(target_changes, list) or not target_changes:
        raise RunningHubStandardPayloadError("video reference requires at least one target change")
    for change in target_changes:
        if not isinstance(change, Mapping):
            raise RunningHubStandardPayloadError("video reference target changes must be objects")
        kind = change.get("kind")
        if kind not in _VIDEO_REFERENCE_TARGET_CHANGE_KINDS:
            raise RunningHubStandardPayloadError("video reference target change kind is not supported")
        if kind == "output_language":
            if set(change) != {"kind", "value"} or change.get("value") not in _OUTPUT_LANGUAGE_CODES:
                raise RunningHubStandardPayloadError("output_language target change is invalid")
        elif (
            set(change) != {"kind", "sha256"}
            or not isinstance(change.get("sha256"), str)
            or _SHA256_RE.fullmatch(change["sha256"]) is None
        ):
            raise RunningHubStandardPayloadError("video reference target change SHA-256 is invalid")
    return normalized


__all__ = [
    "RUNNINGHUB_STANDARD_SEEDANCE_FIELDS",
    "RunningHubStandardPayloadError",
    "validate_public_https_url",
    "validate_runninghub_standard_payload_contract",
    "validate_video_reference_binding",
]
