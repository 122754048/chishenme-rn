from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import DEFAULT_ENV_FILE, load_settings


YOUDAO_CREATE_PATH = "/api/v1/video/tasks"
YOUDAO_QUERY_PATH = "/api/v1/video/tasks/{task_id}?model={model}"
YOUDAO_ASSET_PATH = "/api/v1/assets?Action={action}"
# The production worker must inject the immutable, packaged Seedance-20
# snapshot.  Do not derive a dependency from the operator's home directory:
# that makes a local Codex checkout accidentally authoritative and is not
# deployable in a server/container worker.  ``None`` deliberately fails closed
# on audited submissions until the worker supplies an explicit path or the
# ``SEEDANCE20_SKILL_FILE`` environment variable.
DEFAULT_SEEDANCE20_SKILL_FILE: Path | None = None
PROFILE_SCHEMA_FILE = Path(__file__).resolve().parents[3] / "schemas" / "high_fidelity_profile.schema.json"
_MANIFEST_LOCKS: dict[str, threading.RLock] = {}
_MANIFEST_LOCKS_GUARD = threading.Lock()


def resolve_seedance20_skill_file(value: str | Path | None = None) -> Path | None:
    """Resolve the worker-provided Seedance-20 snapshot without local fallback.

    A CLI value wins over the deployment environment.  The returned path is a
    staging/worker path only; the immutable run profile stores its package-
    relative name and byte digest, never this path.
    """

    if value is not None and str(value).strip():
        return Path(value).expanduser()
    configured = os.environ.get("SEEDANCE20_SKILL_FILE")
    if configured and configured.strip():
        return Path(configured).expanduser()
    return None


class PayloadError(ValueError):
    pass


class SeedanceApiError(RuntimeError):
    pass


class TaskFailedError(SeedanceApiError):
    pass


class PollTimeoutError(SeedanceApiError):
    pass


@dataclass(frozen=True)
class FailureDiagnosis:
    code: str
    title: str
    user_message: str
    next_action: str
    retry_allowed: bool
    requires_user_confirmation: bool
    prompt_or_image_change_required: bool


def _require_public_https_urls(urls: list[str]) -> None:
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise PayloadError("media URLs must be public HTTPS URLs")


def _require_asset_urls(urls: list[str], provider_name: str) -> None:
    for url in urls:
        if not url.startswith("asset://asset-"):
            raise PayloadError(
                f"{provider_name} image references must use asset://asset-* URLs"
            )


def build_payload(
    prompt: str,
    duration: int,
    ratio: str,
    image_urls: list[str],
    reference_video_urls: list[str],
    *,
    provider: str = "youdao",
    model: str = "seedance-2.0-fast",
    resolution: str = "720p",
    review_bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_prompt = prompt.strip()
    if not normalized_prompt or len(normalized_prompt) > 5000:
        raise PayloadError("prompt must contain 1-5000 characters")
    if not 4 <= int(duration) <= 15:
        raise PayloadError("duration must be between 4 and 15 seconds")
    if ratio not in {"16:9", "9:16", "1:1"}:
        raise PayloadError("ratio must be one of 16:9, 9:16, 1:1")
    if len(image_urls) > 4:
        raise PayloadError("seedance2.0-fast-md accepts at most 4 images")
    if reference_video_urls:
        raise PayloadError("reference_videos is disabled by the fixed B route")
    if provider != "youdao":
        raise PayloadError("provider must be youdao")
    _require_asset_urls(image_urls, "Youdao")
    content: list[dict[str, Any]] = [{"type": "text", "text": normalized_prompt}]
    content.extend(
        {
            "type": "image_url",
            "role": "reference_image",
            "image_url": {"url": url},
        }
        for url in image_urls
    )
    payload = {
        "model": model,
        "content": content,
        "generate_audio": True,
        "ratio": ratio,
        "duration": int(duration),
        "watermark": False,
    }
    if resolution not in {"480p", "720p", "1080p", "4k"}:
        raise PayloadError(
            "Youdao resolution must be one of: 480p, 720p, 1080p, 4k"
        )
    if model == "seedance-2.0-fast" and resolution in {"1080p", "4k"}:
        raise PayloadError(
            "seedance-2.0-fast supports only 480p or 720p through Youdao"
        )
    payload["resolution"] = resolution
    if review_bindings is not None:
        _validate_review_bindings(review_bindings)
        payload["review_bindings"] = json.loads(json.dumps(review_bindings, ensure_ascii=False))
    _validate_route_integrity(payload, normalized_prompt)
    return payload


_REVIEW_LANGUAGES = {"en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"}
_REVIEW_FIELDS = {
    "output_language",
    "approved_script_sha256",
    "approved_storyboard_manifest_sha256",
    "approved_storyboard_cut_sha256s",
    "segment_plan_sha256",
}


def _validate_review_bindings(bindings: dict[str, Any]) -> None:
    if not isinstance(bindings, dict) or not _REVIEW_FIELDS.issubset(bindings):
        raise PayloadError("provider payload review binding set is incomplete")
    language = bindings.get("output_language")
    if language is not None and language not in _REVIEW_LANGUAGES:
        raise PayloadError("provider payload output_language is invalid")
    for field in ("approved_script_sha256", "approved_storyboard_manifest_sha256", "segment_plan_sha256"):
        if not _is_lower_sha256(bindings.get(field)):
            raise PayloadError(f"provider payload review binding {field} is invalid")
    cuts = bindings.get("approved_storyboard_cut_sha256s")
    if not isinstance(cuts, list) or any(not _is_lower_sha256(item) for item in cuts):
        raise PayloadError("provider payload ordered Cut SHA bindings are invalid")


def request_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


REQUIRED_AUDIT_CHECKS = (
    "approved_cut_order",
    "character_lock",
    "product_lock",
    "duration_and_timing",
    "voiceover_and_audio",
    "camera_action_continuity",
    "selling_point_evidence",
    "timeline_region_routing",
    "reference_role_mapping",
    "provider_parameters",
    "forbidden_fields",
    "zero_ambiguity",
    "no_unresolved_placeholders",
)

REQUIRED_CONTRACT_DIGESTS = (
    "approved_storyboard_sha256",
    "source_fidelity_contract_sha256",
    "timeline_regions_sha256",
    "character_lock_sha256",
    "product_truth_sha256",
    "selling_point_mapping_sha256",
    "audio_contract_sha256",
    "continuity_manifest_sha256",
)

_COMPILER_CHECKS = (
    "professional_gate",
    "capability_check",
    "allocation_check",
    "reference_role_check",
    "directing_coherence_check",
    "anti_slop_check",
)

_FACTOR_CARRIERS = {
    "prompt_carried",
    "reference_carried",
    "payload_carried",
    "postproduction_carried",
    "route_excluded",
}

_ROUTE_LEAKAGE_MARKERS = (
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

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]", re.DOTALL)


def _payload_prompt(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        raise PayloadError("payload content must be a list")
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                return text
    raise PayloadError("payload does not include prompt text")


def _is_lower_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _route_excludes_factor(audit: dict[str, Any], factor_id: str) -> bool:
    route_contract = audit.get("route_contract")
    if not isinstance(route_contract, dict):
        return False
    if route_contract.get(factor_id) is True:
        return True
    for key in ("excluded_factor_ids", "excluded_factors", "excluded", "excludes"):
        excluded = route_contract.get(key)
        if isinstance(excluded, str):
            if excluded == factor_id:
                return True
        elif isinstance(excluded, list):
            if factor_id in excluded:
                return True
        elif isinstance(excluded, dict):
            if excluded.get(factor_id) is True:
                return True
    return False


_MISSING_PAYLOAD_VALUE = object()


def _resolve_payload_path(payload: dict[str, Any], payload_path: str) -> Any:
    """Resolve the small JSONPath subset used by factor coverage references."""
    if not _non_empty_string(payload_path) or not payload_path.startswith("$"):
        return _MISSING_PAYLOAD_VALUE
    if payload_path == "$":
        return payload
    current: Any = payload
    index = 1
    while index < len(payload_path):
        if payload_path[index] == ".":
            match = re.match(r"\.([A-Za-z_][A-Za-z0-9_-]*)", payload_path[index:])
            if match is None:
                return _MISSING_PAYLOAD_VALUE
            key = match.group(1)
            index += len(match.group(0))
            if not isinstance(current, dict) or key not in current:
                return _MISSING_PAYLOAD_VALUE
            current = current[key]
            continue
        if payload_path[index] == "[":
            close = payload_path.find("]", index + 1)
            if close < 0:
                return _MISSING_PAYLOAD_VALUE
            token = payload_path[index + 1 : close]
            if token.isdigit():
                key: int | str = int(token)
            elif len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
                key = token[1:-1]
            else:
                return _MISSING_PAYLOAD_VALUE
            index = close + 1
            if isinstance(current, list) and isinstance(key, int):
                if key >= len(current):
                    return _MISSING_PAYLOAD_VALUE
                current = current[key]
            elif isinstance(current, dict) and isinstance(key, str) and key in current:
                current = current[key]
            else:
                return _MISSING_PAYLOAD_VALUE
            continue
        return _MISSING_PAYLOAD_VALUE
    return current


def _validate_factor_coverage(
    audit: dict[str, Any],
    prompt: str,
    payload: dict[str, Any],
    expected_factor_ids: set[str] | None = None,
    *,
    strict_factory: bool = False,
) -> None:
    ledger = audit.get("factor_coverage_ledger")
    if not isinstance(ledger, list) or not ledger:
        raise PayloadError("factor coverage ledger must be non-empty")
    seen_factor_ids: set[str] = set()
    for row in ledger:
        if not isinstance(row, dict):
            raise PayloadError("factor coverage rows must be objects")
        factor_id = row.get("factor_id")
        source_pointer = row.get("source_pointer")
        carrier = row.get("carrier")
        status = row.get("status")
        if not _non_empty_string(factor_id) or factor_id in seen_factor_ids:
            raise PayloadError("factor coverage requires stable unique factor ids")
        seen_factor_ids.add(factor_id)
        if not _non_empty_string(source_pointer):
            raise PayloadError("factor coverage requires a source pointer")
        if carrier not in _FACTOR_CARRIERS:
            raise PayloadError("factor coverage has an invalid or unassigned carrier")
        if status != "passed":
            raise PayloadError("factor coverage rows must have passed status")
        if carrier == "route_excluded":
            route_contract = audit.get("route_contract")
            if strict_factory:
                if (
                    not isinstance(route_contract, dict)
                    or route_contract.get(factor_id) is not True
                ):
                    raise PayloadError(
                        "strict Factory route_excluded requires canonical {factor_id: true} mapping"
                    )
            elif not _route_excludes_factor(audit, factor_id):
                raise PayloadError(
                    "factor coverage route_excluded requires an explicit route contract exclusion"
                )

        contract_pointer = row.get("contract_pointer")
        contract_index = audit.get("contract_index")
        if not _non_empty_string(contract_pointer):
            raise PayloadError("factor coverage requires a contract pointer")
        if not isinstance(contract_index, dict) or contract_pointer not in contract_index:
            raise PayloadError("factor coverage contract pointer is not indexed")
        mapped_digest = contract_index.get(contract_pointer)
        if mapped_digest not in REQUIRED_CONTRACT_DIGESTS:
            raise PayloadError(
                "factor coverage contract pointer maps to an unknown contract digest"
            )

        payload_carriers = {"prompt_carried", "reference_carried", "payload_carried"}
        payload_path = row.get("payload_path")
        if carrier in payload_carriers:
            if not _non_empty_string(payload_path):
                raise PayloadError("factor coverage requires a payload path")
            if _resolve_payload_path(payload, payload_path) is _MISSING_PAYLOAD_VALUE:
                raise PayloadError("factor coverage payload path does not resolve")
        elif _non_empty_string(payload_path) and _resolve_payload_path(
            payload, payload_path
        ) is _MISSING_PAYLOAD_VALUE:
            raise PayloadError("factor coverage payload path does not resolve")

        span = row.get("prompt_span")
        if carrier == "prompt_carried" and not isinstance(span, dict):
            raise PayloadError("factor coverage prompt span is required")
        if span is not None:
            if not isinstance(span, dict):
                raise PayloadError("factor coverage prompt span is invalid")
            start = span.get("start")
            end = span.get("end")
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or end > len(prompt)
            ):
                raise PayloadError("factor coverage prompt span is invalid")
    if expected_factor_ids is not None and seen_factor_ids != expected_factor_ids:
        raise PayloadError(
            "factor coverage does not exactly match frozen input contract factor ids"
        )


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


def _route_leakage_in_value(value: Any) -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
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


def _validate_route_integrity(payload: dict[str, Any], prompt: str) -> None:
    leaked = _route_leakage_in_value(payload)
    if leaked:
        raise PayloadError(
            "route leakage detected in Seedance prompt or provider payload: "
            + ", ".join(leaked)
        )
    if _PLACEHOLDER_RE.search(prompt):
        raise PayloadError("compiled prompt contains unresolved placeholders")


def _validate_compiler_provenance(
    audit: dict[str, Any],
    skill_file: Path | None = None,
) -> None:
    compiler = audit.get("compiler")
    if not isinstance(compiler, dict):
        raise PayloadError("seedance-20 compiler provenance is required")
    if compiler.get("skill") != "seedance-20":
        raise PayloadError("seedance-20 compiler provenance has an invalid skill")
    if not _non_empty_string(compiler.get("version")):
        raise PayloadError("seedance-20 compiler provenance requires a version")
    if not _is_lower_sha256(compiler.get("skill_sha256")):
        raise PayloadError(
            "seedance-20 compiler provenance skill_sha256 must be lowercase SHA-256"
        )
    if any(compiler.get(name) is not True for name in _COMPILER_CHECKS):
        raise PayloadError("seedance-20 compiler provenance checks must all pass")
    if (
        compiler.get("contract") == "seedance20-prompt-compiler/v1"
        or compiler.get("profile") == "high_fidelity_hybrid_v1"
    ):
        modules = compiler.get("loaded_modules")
        required = ["seedance-20", "seedance-prompt", "seedance-antislop"]
        if (
            not isinstance(modules, list)
            or modules[:3] != required
            or len(modules) != len(set(modules))
        ):
            raise PayloadError(
                "high-fidelity compiler must load seedance-prompt and "
                "seedance-antislop after seedance-20"
            )
        specialists = compiler.get("required_specialists", [])
        if (
            not isinstance(specialists, list)
            or any(not _non_empty_string(item) for item in specialists)
            or not set(specialists).issubset(set(modules))
        ):
            raise PayloadError(
                "high-fidelity compiler is missing a required Seedance specialist"
            )
    if skill_file is not None:
        _, skill_digest, skill_version = _load_seedance20_snapshot(skill_file)
        if not hmac.compare_digest(skill_digest, compiler["skill_sha256"]):
            raise PayloadError("seedance-20 skill snapshot hash does not match compiler")
        if skill_version != compiler["version"]:
            raise PayloadError("seedance-20 skill snapshot version does not match compiler")


def _validate_contract_digests(audit: dict[str, Any]) -> None:
    digests = audit.get("contract_digests")
    if not isinstance(digests, dict):
        raise PayloadError("audit artifact contract digests are required")
    for name in REQUIRED_CONTRACT_DIGESTS:
        if not _is_lower_sha256(digests.get(name)):
            raise PayloadError(
                f"audit artifact contract digest {name} must be lowercase SHA-256"
            )


def _read_json_file(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PayloadError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PayloadError(f"{label} must be a JSON object")
    return raw, value


def _validate_input_contract_schema(
    contract: dict[str, Any],
    expected_script_sha256: str,
) -> set[str]:
    expected_script = expected_script_sha256.strip()
    if not _is_lower_sha256(expected_script):
        raise PayloadError("--approved-script-sha256 must be lowercase SHA-256")
    contract_script = contract.get("approved_script_sha256")
    if not _is_lower_sha256(contract_script) or not hmac.compare_digest(
        contract_script, expected_script
    ):
        raise PayloadError("frozen input contract approved script digest does not match")
    digests = contract.get("contract_digests")
    if not isinstance(digests, dict):
        raise PayloadError("frozen input contract contract digests are required")
    for name in REQUIRED_CONTRACT_DIGESTS:
        if not _is_lower_sha256(digests.get(name)):
            raise PayloadError(
                f"frozen input contract contract digest {name} is invalid"
            )
    required_checks = contract.get("required_audit_checks")
    if (
        not isinstance(required_checks, list)
        or required_checks != list(REQUIRED_AUDIT_CHECKS)
    ):
        raise PayloadError("frozen input contract required audit checks must match exactly")
    required_factor_ids = contract.get("required_factor_ids")
    if (
        not isinstance(required_factor_ids, list)
        or not required_factor_ids
        or any(not _non_empty_string(item) for item in required_factor_ids)
        or len(required_factor_ids) != len({item for item in required_factor_ids if isinstance(item, str)})
    ):
        raise PayloadError(
            "frozen input contract required factor ids must be non-empty and unique"
        )
    return set(required_factor_ids)


def _validate_frozen_input_contract(
    audit: dict[str, Any],
    contract_path: Path,
    expected_script_sha256: str,
) -> set[str]:
    raw, contract = _read_json_file(contract_path, "seedance input contract")
    contract_digest = hashlib.sha256(raw).hexdigest()
    artifact_digest = audit.get("seedance_input_contract_sha256")
    if not _is_lower_sha256(artifact_digest) or not hmac.compare_digest(
        contract_digest, artifact_digest
    ):
        raise PayloadError("seedance input contract digest does not match")
    required_factor_ids = _validate_input_contract_schema(
        contract, expected_script_sha256
    )
    audit_digests = audit.get("contract_digests")
    if not isinstance(audit_digests, dict):
        raise PayloadError("audit artifact contract digests are required")
    for name in REQUIRED_CONTRACT_DIGESTS:
        if not hmac.compare_digest(str(contract["contract_digests"][name]), str(audit_digests.get(name))):
            raise PayloadError(
                f"frozen input contract contract digest {name} does not match audit"
            )
    return required_factor_ids


def _load_seedance20_snapshot(skill_file: Path) -> tuple[bytes, str, str]:
    try:
        if not skill_file.is_file():
            raise OSError("file does not exist")
        raw = skill_file.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise PayloadError(f"seedance-20 skill snapshot is unreadable: {exc}") from exc
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise PayloadError("seedance-20 skill snapshot frontmatter is missing")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise PayloadError("seedance-20 skill snapshot frontmatter is unterminated")
    frontmatter = "".join(lines[1:closing_index])
    if not re.search(r"(?m)^name:\s*seedance-20\s*$", frontmatter):
        raise PayloadError("seedance-20 skill snapshot frontmatter name is invalid")
    version_match = re.search(
        r"(?ms)^metadata:\s*\r?\n(?:[ \t]+[^\r\n]*\r?\n)*?[ \t]+version:\s*[\"']?([^\"'\r\n ]+)",
        frontmatter,
    )
    if version_match is None or not _non_empty_string(version_match.group(1)):
        raise PayloadError("seedance-20 skill snapshot metadata version is missing")
    return raw, hashlib.sha256(raw).hexdigest(), version_match.group(1).strip()


def _load_profile_schema_digest() -> str:
    try:
        raw = PROFILE_SCHEMA_FILE.read_bytes()
    except OSError as exc:
        raise PayloadError(f"high-fidelity profile schema is unavailable: {exc}") from exc
    return hashlib.sha256(raw).hexdigest()


def _validate_audited_fixed_b_payload(payload: dict[str, Any]) -> None:
    expected_top_level = {
        "model",
        "content",
        "generate_audio",
        "ratio",
        "duration",
        "watermark",
        "resolution",
    }
    if set(payload) != expected_top_level:
        raise PayloadError("audited fixed-B payload contains unknown or missing provider fields")
    if payload.get("model") != "seedance-2.0-fast":
        raise PayloadError("audited fixed-B payload requires model seedance-2.0-fast")
    if payload.get("resolution") != "720p" or payload.get("ratio") != "9:16":
        raise PayloadError("audited fixed-B payload parameters are not fixed-B")
    duration = payload.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 4 <= duration <= 15:
        raise PayloadError("audited fixed-B payload duration is invalid")
    if payload.get("generate_audio") is not True or payload.get("watermark") is not False:
        raise PayloadError("audited fixed-B payload audio or watermark is not fixed-B")
    content = payload.get("content")
    if not isinstance(content, list) or not 1 <= len(content) <= 5:
        raise PayloadError("audited fixed-B payload content is invalid")
    text_item = content[0]
    if (
        not isinstance(text_item, dict)
        or set(text_item) != {"type", "text"}
        or text_item.get("type") != "text"
        or not isinstance(text_item.get("text"), str)
    ):
        raise PayloadError("audited fixed-B payload first content item must be exact text")
    for item in content[1:]:
        if (
            not isinstance(item, dict)
            or set(item) != {"type", "role", "image_url"}
            or item.get("type") != "image_url"
            or item.get("role") != "reference_image"
            or not isinstance(item.get("image_url"), dict)
            or set(item["image_url"]) != {"url"}
            or not isinstance(item["image_url"].get("url"), str)
            or not item["image_url"]["url"].startswith("asset://asset-")
        ):
            raise PayloadError("audited fixed-B payload reference image item is invalid")


def _validate_audit_check_set(checks: Any) -> None:
    if (
        not isinstance(checks, dict)
        or set(checks) != set(REQUIRED_AUDIT_CHECKS)
        or any(checks.get(name) is not True for name in REQUIRED_AUDIT_CHECKS)
    ):
        raise PayloadError("audit checks must contain exactly 13 literal true keys")


def _validate_audited_factory_parameters(
    *,
    prompt: str,
    provider: str,
    model: str,
    resolution: str,
    ratio: str,
    duration: int,
    input_contract_path: Path,
    approved_script_sha256: str,
    skill_file: Path | None,
) -> None:
    if provider != "youdao":
        raise PayloadError("audited fixed-B Factory path requires Youdao")
    if model != "seedance-2.0-fast" or resolution != "720p" or ratio != "9:16":
        raise PayloadError("audited fixed-B Factory parameters are not fixed-B")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 4 <= duration <= 15:
        raise PayloadError("audited fixed-B Factory duration is invalid")
    if skill_file is None:
        raise PayloadError(
            "audited fixed-B Factory path requires a packaged Seedance-20 snapshot; "
            "set --seedance20-skill-file or SEEDANCE20_SKILL_FILE"
        )
    _raw_contract, contract = _read_json_file(
        input_contract_path, "seedance input contract"
    )
    _validate_input_contract_schema(contract, approved_script_sha256)
    _load_seedance20_snapshot(skill_file)
    prompt_payload = {"content": [{"type": "text", "text": prompt}]}
    _validate_route_integrity(prompt_payload, prompt)


def validate_profile_snapshot_file(snapshot_path: Path, skill_file: Path) -> None:
    """Validate the immutable high-fidelity profile/Seedance dependency pin.

    Kept local to the bundled submitter so a deployed worker does not import a
    workstation's ``~/.codex`` package.  The canonical snapshot builder lives
    in the top-level bundle; this check verifies the same byte-level boundary
    immediately before Invocation B/paid submission.
    """
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PayloadError(f"invalid high-fidelity profile snapshot: {exc}") from exc
    if not isinstance(snapshot, dict) or snapshot.get("profile") != "high_fidelity_hybrid_v1":
        raise PayloadError("high-fidelity profile snapshot is missing or unsupported")
    allowed_snapshot_fields = {
        "profile", "schema_version", "revision", "profile_sha256", "schema_sha256",
        "config_digest", "config_sha256", "activation_mode", "created_at",
        "dependencies", "parent_digests", "artifact", "snapshot_sha256",
    }
    if set(snapshot) != allowed_snapshot_fields:
        raise PayloadError("high-fidelity profile snapshot contains unknown fields")
    if snapshot.get("schema_version") != "high-fidelity-profile/v1":
        raise PayloadError("high-fidelity profile snapshot schema is stale")
    if snapshot.get("revision") != 1:
        raise PayloadError("high-fidelity profile snapshot revision is unsupported")
    profile_digest = hashlib.sha256(
        json.dumps(
            {"profile": "high_fidelity_hybrid_v1", "revision": 1},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if snapshot.get("profile_sha256") != profile_digest:
        raise PayloadError("high-fidelity profile digest is invalid")
    schema_digest = snapshot.get("schema_sha256")
    if not _is_lower_sha256(schema_digest) or schema_digest != _load_profile_schema_digest():
        raise PayloadError("high-fidelity profile schema digest is stale")
    if not _is_lower_sha256(snapshot.get("config_digest")) or snapshot.get("config_digest") != snapshot.get("config_sha256"):
        raise PayloadError("high-fidelity profile config digest is invalid")
    parent_digests = snapshot.get("parent_digests")
    if not isinstance(parent_digests, dict) or any(
        not isinstance(name, str) or not name or not _is_lower_sha256(value)
        for name, value in parent_digests.items()
    ):
        raise PayloadError("high-fidelity profile parent digests are invalid")
    dependencies = snapshot.get("dependencies")
    if not isinstance(dependencies, list):
        raise PayloadError("high-fidelity profile snapshot dependencies are invalid")
    dependency = next((item for item in dependencies if isinstance(item, dict) and item.get("name") == "seedance-20"), None)
    if dependency is None:
        raise PayloadError("high-fidelity profile snapshot does not pin seedance-20")
    if any(
        not isinstance(item, dict)
        or set(item) != {"name", "version", "sha256", "package_path"}
        for item in dependencies
    ):
        raise PayloadError("high-fidelity profile dependency records contain unknown fields")
    _raw_skill, actual, actual_version = _load_seedance20_snapshot(skill_file)
    if dependency.get("sha256") != actual:
        raise PayloadError("high-fidelity profile/Seedance-20 dependency hash mismatch")
    if dependency.get("version") != actual_version:
        raise PayloadError("high-fidelity profile/Seedance-20 dependency version mismatch")
    package_path = dependency.get("package_path")
    if (
        not isinstance(package_path, str)
        or not package_path
        or package_path.startswith(("/", "\\", ".", "~"))
        or any(part in {"", ".", ".."} for part in package_path.replace("\\", "/").split("/"))
        or ":" in package_path.split("/")[0]
    ):
        raise PayloadError("high-fidelity profile dependency package path is invalid")
    if not _is_lower_sha256(snapshot.get("snapshot_sha256")):
        raise PayloadError("high-fidelity profile snapshot digest is invalid")
    payload = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload.pop("snapshot_sha256", None)
    if isinstance(payload.get("artifact"), dict):
        payload["artifact"].pop("sha256", None)
    expected = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if expected != snapshot.get("snapshot_sha256"):
        raise PayloadError("high-fidelity profile snapshot digest mismatch")
    artifact = snapshot.get("artifact")
    if not isinstance(artifact, dict) or artifact.get("sha256") != snapshot.get("snapshot_sha256"):
        raise PayloadError("high-fidelity profile snapshot artifact hash mismatch")
    allowed_artifact_fields = {
        "kind", "schema_version", "content_type", "uri", "private", "sha256",
        "tenant_id", "run_id", "producer_stage", "correlation_id",
    }
    if set(artifact) - allowed_artifact_fields:
        raise PayloadError("high-fidelity profile artifact metadata contains unknown fields")
    artifact_uri = artifact.get("uri")
    if artifact.get("private") is not True or (
        artifact_uri is not None
        and (
            not isinstance(artifact_uri, str)
            or not artifact_uri.startswith(("s3://", "gs://", "az://", "azure://", "artifact://", "https://"))
        )
    ):
        raise PayloadError("high-fidelity profile artifact must use private object-store metadata")


def _validate_prescript_execution_candidate(candidate: dict[str, Any], index: int) -> None:
    """Repeat Invocation-A execution checks at the paid-boundary bridge.

    The top-level builder performs the same validation during A.  Repeating the
    small structural contract here prevents a hand-edited sidecar with a
    recomputed digest from bypassing the B/paid boundary.
    """
    prefix = f"candidate_regions[{index}]"
    cut_ids = candidate.get("cut_ids")
    if (
        not isinstance(cut_ids, list)
        or not cut_ids
        or len(cut_ids) != len(set(cut_ids))
        or any(not isinstance(item, str) or not item for item in cut_ids)
    ):
        raise PayloadError(f"{prefix}.cut_ids is invalid")
    duration = candidate.get("duration_ms")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 4000 <= duration <= 15000:
        raise PayloadError(f"{prefix}.duration_ms is invalid")
    if candidate.get("primary_fidelity_spend") not in {"identity", "motion", "scene"}:
        raise PayloadError(f"{prefix}.primary_fidelity_spend is invalid")
    if candidate.get("mode") != "fixed_b_image_reference":
        raise PayloadError(f"{prefix}.mode must remain fixed_b_image_reference")
    if candidate.get("single_take_or_multishot") not in {"single_take", "multishot"}:
        raise PayloadError(f"{prefix}.single_take_or_multishot is invalid")
    for field in ("allowed_split_cut_ids", "forbidden_split_cut_ids", "economized_factors"):
        values = candidate.get(field)
        if not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values):
            raise PayloadError(f"{prefix}.{field} is invalid")
    if not set(candidate["allowed_split_cut_ids"]) <= set(cut_ids) or not set(candidate["forbidden_split_cut_ids"]) <= set(cut_ids):
        raise PayloadError(f"{prefix} split Cut IDs are outside candidate region")
    if set(candidate["allowed_split_cut_ids"]) & set(candidate["forbidden_split_cut_ids"]):
        raise PayloadError(f"{prefix} split Cut IDs overlap")

    shots = candidate.get("shot_budget")
    if not isinstance(shots, list) or not shots:
        raise PayloadError(f"{prefix}.shot_budget is required")
    shot_ids: set[str] = set()
    total_shot_duration = 0
    for shot_index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            raise PayloadError(f"{prefix}.shot_budget[{shot_index}] is invalid")
        shot_id = shot.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id or shot_id in shot_ids:
            raise PayloadError(f"{prefix}.shot_budget[{shot_index}].shot_id is invalid")
        shot_ids.add(shot_id)
        shot_duration = shot.get("duration_ms")
        if isinstance(shot_duration, bool) or not isinstance(shot_duration, int) or shot_duration <= 0:
            raise PayloadError(f"{prefix}.shot_budget[{shot_index}].duration_ms is invalid")
        total_shot_duration += shot_duration
        for field in ("primary_action", "endpoint"):
            if not isinstance(shot.get(field), str) or not shot[field].strip():
                raise PayloadError(f"{prefix}.shot_budget[{shot_index}].{field} is required")
    if total_shot_duration != duration:
        raise PayloadError(f"{prefix}.shot_budget does not cover duration")

    roles = candidate.get("reference_role_plan", [])
    if not isinstance(roles, list) or len(roles) > 4:
        raise PayloadError(f"{prefix}.reference_role_plan is invalid")
    seen_slots: set[int] = set()
    for role in roles:
        if not isinstance(role, dict) or role.get("slot") not in {1, 2, 3, 4}:
            raise PayloadError(f"{prefix}.reference_role_plan entry is invalid")
        if role["slot"] in seen_slots:
            raise PayloadError(f"{prefix}.reference_role_plan repeats a slot")
        seen_slots.add(role["slot"])
        if not isinstance(role.get("role"), str) or not role["role"].strip():
            raise PayloadError(f"{prefix}.reference_role_plan role is required")

    if candidate.get("background_strategy") not in {"KEEP", "COMPOSITE", "REPLACE"}:
        raise PayloadError(f"{prefix}.background_strategy is invalid")
    if not isinstance(candidate.get("performance_strategy"), dict) or not candidate["performance_strategy"]:
        raise PayloadError(f"{prefix}.performance_strategy is required")
    states = candidate.get("action_state_requirements")
    if not isinstance(states, list) or not states:
        raise PayloadError(f"{prefix}.action_state_requirements is required")
    completed = False
    for state_index, state in enumerate(states, start=1):
        if not isinstance(state, dict):
            raise PayloadError(f"{prefix}.action_state_requirements[{state_index}] is invalid")
        if not isinstance(state.get("phase"), str) or not state["phase"].strip() or not isinstance(state.get("state"), str) or not state["state"].strip():
            raise PayloadError(f"{prefix}.action_state_requirements[{state_index}] needs phase/state")
        if not isinstance(state.get("required"), bool):
            raise PayloadError(f"{prefix}.action_state_requirements[{state_index}].required is invalid")
        completed = completed or state["phase"] == "completed" and state["required"] is True
    if not completed:
        raise PayloadError(f"{prefix}.action_state_requirements needs a completed endpoint")

    audio = candidate.get("audio_strategy")
    if not isinstance(audio, dict) or audio.get("music_policy") not in {"none", "preserve_source", "approved"}:
        raise PayloadError(f"{prefix}.audio_strategy.music_policy is invalid")
    if not isinstance(audio.get("ambience"), str) or not audio["ambience"].strip():
        raise PayloadError(f"{prefix}.audio_strategy.ambience is required")
    for field in ("foley_event_ids", "silence_window_ids"):
        values = audio.get(field)
        if not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values):
            raise PayloadError(f"{prefix}.audio_strategy.{field} is invalid")

    voice_plan = candidate.get("voiceover_timing_plan")
    if not isinstance(voice_plan, list):
        raise PayloadError(f"{prefix}.voiceover_timing_plan is invalid")
    seen_lines: set[str] = set()
    for line_index, line in enumerate(voice_plan, start=1):
        if not isinstance(line, dict) or not isinstance(line.get("line_id"), str) or not line["line_id"].strip() or line["line_id"] in seen_lines:
            raise PayloadError(f"{prefix}.voiceover_timing_plan[{line_index}].line_id is invalid")
        seen_lines.add(line["line_id"])
        if line.get("carrier") not in {"prompt", "postproduction"}:
            raise PayloadError(f"{prefix}.voiceover_timing_plan[{line_index}].carrier is invalid")
    for field in ("prompt_carrier_plan", "postproduction_carrier_plan", "hard_blockers", "warnings"):
        if not isinstance(candidate.get(field), list):
            raise PayloadError(f"{prefix}.{field} is invalid")


def _validate_prescript_line_carriers(candidates: list[dict[str, Any]], lines: list[dict[str, Any]]) -> None:
    candidate_ids = {candidate["candidate_region_id"] for candidate in candidates}
    plans: dict[str, tuple[str, str]] = {}
    for candidate in candidates:
        region_id = candidate["candidate_region_id"]
        for item in candidate["voiceover_timing_plan"]:
            line_id = item["line_id"]
            if line_id in plans:
                raise PayloadError(f"line carrier is duplicated: {line_id}")
            plans[line_id] = (region_id, item["carrier"])
    for line in lines:
        if not isinstance(line, dict):
            raise PayloadError("line contract must be an object")
        line_id = line.get("line_id")
        region_id = line.get("candidate_region_id")
        if line_id not in plans:
            raise PayloadError(f"line carrier is required: {line_id}")
        if region_id not in candidate_ids or plans[line_id][0] != region_id:
            raise PayloadError(f"line candidate region is invalid: {line_id}")
        candidate = next(candidate for candidate in candidates if candidate["candidate_region_id"] == region_id)
        if line.get("cut_id") not in candidate["cut_ids"]:
            raise PayloadError(f"line Cut is outside candidate region: {line_id}")
    line_ids = {line.get("line_id") for line in lines}
    unknown = set(plans) - line_ids
    if unknown:
        raise PayloadError(f"line carrier references unknown line: {sorted(unknown)[0]}")


def _validate_prescript_exact_lines(lines: list[dict[str, Any]]) -> None:
    """Load the packaged exact-line validator without relying on `~/.codex`."""
    line_contract_path = Path(__file__).resolve().parents[3] / "scripts" / "line_contract.py"
    if not line_contract_path.is_file():
        raise PayloadError("packaged exact-line validator is unavailable")
    spec = importlib.util.spec_from_file_location("replication_line_contract", line_contract_path)
    if spec is None or spec.loader is None:
        raise PayloadError("packaged exact-line validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.validate_line_contracts(lines)
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        raise PayloadError(f"invalid exact line contract: {exc}") from exc


def validate_prescript_snapshot_file(prescript_path: Path, skill_file: Path) -> None:
    """Ensure Invocation A and B use the same exact, untampered sidecar."""
    try:
        artifact = json.loads(prescript_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PayloadError(f"invalid Seedance-20 prescript artifact: {exc}") from exc
    if not isinstance(artifact, dict) or artifact.get("profile") != "seedance20_prescript_v1":
        raise PayloadError("Seedance-20 prescript artifact is unsupported")
    allowed_fields = {
        "schema_version", "profile", "route", "revision", "compiler",
        "candidate_regions", "line_contracts", "factor_coverage",
        "hard_blockers", "warnings", "created_at", "route_1_mutations",
    }
    if set(artifact) - allowed_fields:
        raise PayloadError("Seedance-20 prescript artifact contains unknown fields")
    if artifact.get("schema_version") != "seedance20-prescript/v1":
        raise PayloadError("Seedance-20 prescript schema is stale")
    if artifact.get("route") not in {"route_1", "route_2"}:
        raise PayloadError("Seedance-20 prescript route is invalid")
    if artifact.get("revision") != 1:
        raise PayloadError("Seedance-20 prescript revision is unsupported")
    compiler = artifact.get("compiler")
    if not isinstance(compiler, dict) or not _is_lower_sha256(compiler.get("skill_sha256")):
        raise PayloadError("Seedance-20 prescript compiler provenance is invalid")
    _raw, actual, version = _load_seedance20_snapshot(skill_file)
    if compiler.get("skill") != "seedance-20" or compiler.get("skill_sha256") != actual or str(compiler.get("version")) != version:
        raise PayloadError("Invocation A/B Seedance-20 skill snapshot mismatch")
    input_digests = compiler.get("input_digests")
    if not isinstance(input_digests, dict) or any(
        not isinstance(key, str) or not key or not _is_lower_sha256(value)
        for key, value in input_digests.items()
    ):
        raise PayloadError("Seedance-20 prescript input digests are invalid")
    candidates = artifact.get("candidate_regions")
    if not isinstance(candidates, list) or len(candidates) > 2:
        raise PayloadError("Seedance-20 prescript candidate regions are invalid")
    seen_regions: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise PayloadError("Seedance-20 prescript candidate region is invalid")
        region_id = candidate.get("candidate_region_id")
        if not isinstance(region_id, str) or not region_id or region_id in seen_regions:
            raise PayloadError("Seedance-20 prescript candidate region ID is invalid")
        seen_regions.add(region_id)
        cut_ids = candidate.get("cut_ids")
        duration = candidate.get("duration_ms")
        if (
            not isinstance(cut_ids, list) or not cut_ids
            or any(not isinstance(item, str) or not item for item in cut_ids)
            or isinstance(duration, bool) or not isinstance(duration, int)
            or not 4000 <= duration <= 15000
            or candidate.get("primary_fidelity_spend") not in {"identity", "motion", "scene"}
        ):
            raise PayloadError("Seedance-20 prescript candidate region contract is invalid")
        roles = candidate.get("reference_role_plan", [])
        if not isinstance(roles, list) or len(roles) > 4:
            raise PayloadError("Seedance-20 prescript reference role plan is invalid")
        _validate_prescript_execution_candidate(candidate, len(seen_regions))
    for field in ("line_contracts", "factor_coverage", "hard_blockers", "warnings"):
        if not isinstance(artifact.get(field), list):
            raise PayloadError(f"Seedance-20 prescript {field} must be an array")
    lines = artifact["line_contracts"]
    _validate_prescript_exact_lines(lines)
    _validate_prescript_line_carriers(candidates, lines)
    if artifact.get("route") == "route_1" and artifact.get("route_1_mutations"):
        raise PayloadError("Route 1 Invocation A cannot mutate the approved script")
    if not _is_lower_sha256(compiler.get("output_sha256")):
        raise PayloadError("Seedance-20 prescript output digest is invalid")
    canonical = json.loads(json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    canonical["compiler"].pop("output_sha256", None)
    expected_output = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if expected_output != compiler.get("output_sha256"):
        raise PayloadError("Seedance-20 prescript output digest mismatch")


def validate_audit_artifact(
    payload: dict[str, Any],
    artifact_path: Path,
    expected_request_sha256: str,
    expected_script_sha256: str,
    *,
    seedance_input_contract_path: Path | None = None,
    seedance20_skill_file: Path | None = None,
    strict_factory: bool = False,
) -> str:
    strict_factory = strict_factory or seedance_input_contract_path is not None
    try:
        raw = artifact_path.read_bytes()
        audit = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PayloadError(f"invalid audit artifact: {exc}") from exc
    if not isinstance(audit, dict):
        raise PayloadError("audit artifact must be a JSON object")
    if audit.get("auditor") != "seedance-20":
        raise PayloadError("audit artifact auditor must be seedance-20")
    if audit.get("status") != "passed":
        raise PayloadError("audit artifact status must be passed")
    current = request_sha256(payload)
    if not hmac.compare_digest(current, expected_request_sha256.strip().lower()):
        raise PayloadError("the Seedance request changed since integrity audit")
    artifact_request = audit.get("request_sha256")
    if not isinstance(artifact_request, str) or not hmac.compare_digest(
        current, artifact_request.strip().lower()
    ):
        raise PayloadError("audit artifact request digest does not match payload")
    script_digest = audit.get("approved_script_sha256")
    expected_script = expected_script_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_script):
        raise PayloadError("--approved-script-sha256 must be lowercase SHA-256")
    if not isinstance(script_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", script_digest
    ):
        raise PayloadError("audit artifact approved_script_sha256 must be lowercase SHA-256")
    if not hmac.compare_digest(script_digest, expected_script):
        raise PayloadError("audit artifact approved script digest does not match")
    prompt_digest = audit.get("compiled_prompt_sha256")
    current_prompt_digest = hashlib.sha256(
        _payload_prompt(payload).encode("utf-8")
    ).hexdigest()
    if not isinstance(prompt_digest, str) or not hmac.compare_digest(
        current_prompt_digest, prompt_digest
    ):
        raise PayloadError("audit artifact compiled prompt digest does not match payload")
    ambiguities = audit.get("ambiguities")
    if ambiguities != []:
        raise PayloadError("audit artifact must satisfy zero ambiguity: ambiguities must be []")
    unresolved_placeholders = audit.get("unresolved_placeholders")
    if unresolved_placeholders != []:
        raise PayloadError(
            "audit artifact unresolved placeholders must be []"
        )
    prompt = _payload_prompt(payload)
    _validate_route_integrity(payload, prompt)
    compiler_review = (audit.get("compiler") or {}).get("review_bindings")
    payload_review = payload.get("review_bindings")
    if compiler_review is not None or payload_review is not None:
        if not isinstance(compiler_review, dict) or not isinstance(payload_review, dict):
            raise PayloadError("provider payload and compiler audit review bindings are incomplete")
        _validate_review_bindings(compiler_review)
        _validate_review_bindings(payload_review)
        if compiler_review != payload_review:
            raise PayloadError("provider payload review binding does not match compiler audit")
    if strict_factory:
        if seedance_input_contract_path is None:
            raise PayloadError("--seedance-input-contract is required for audited Factory submission")
        if seedance20_skill_file is None:
            raise PayloadError("--seedance20-skill-file is required for audited Factory submission")
        _validate_audited_fixed_b_payload(payload)
    expected_factor_ids = None
    if seedance_input_contract_path is not None:
        expected_factor_ids = _validate_frozen_input_contract(
            audit, seedance_input_contract_path, expected_script_sha256
        )
    _validate_compiler_provenance(audit, seedance20_skill_file)
    _validate_contract_digests(audit)
    _validate_factor_coverage(
        audit,
        prompt,
        payload,
        expected_factor_ids,
        strict_factory=strict_factory,
    )
    checks = audit.get("checks")
    if strict_factory or seedance_input_contract_path is not None:
        _validate_audit_check_set(checks)
    elif not isinstance(checks, dict) or any(
        checks.get(name) is not True for name in REQUIRED_AUDIT_CHECKS
    ):
        raise PayloadError("audit artifact is missing a required passed check")
    return hashlib.sha256(raw).hexdigest()


def require_request_authorization(
    payload: dict[str, Any],
    *,
    approved_sha256: str | None = None,
    audited_sha256: str | None = None,
) -> str:
    supplied = [value for value in (approved_sha256, audited_sha256) if value]
    if len(supplied) != 1:
        raise PayloadError("provide exactly one approved or audited request digest")
    current = request_sha256(payload)
    if not hmac.compare_digest(current, supplied[0].strip().lower()):
        if audited_sha256:
            raise PayloadError("the Seedance request changed since integrity audit")
        raise PayloadError("the Seedance request changed since user approval")
    return current


def require_approved_request(
    payload: dict[str, Any],
    approved_sha256: str | None,
) -> str:
    return require_request_authorization(payload, approved_sha256=approved_sha256)


def classify_failure(message: str) -> FailureDiagnosis:
    normalized = message.lower()
    if "provider_moderation_error" in normalized and "trademark" in normalized:
        return FailureDiagnosis(
            code="trademark_moderation",
            title="商标审核未通过",
            user_message="Seedance 输出触发了商标审核，当前请求不能原样重试。",
            next_action=(
                "返回故事板生图提示词和图片素材，检查额外品牌文字、来源视频品牌、"
                "Logo 特写及产品图商标；经用户同意修改或更换合规素材后，重新确认故事板"
                "和 Seedance 提示词。"
            ),
            retry_allowed=False,
            requires_user_confirmation=True,
            prompt_or_image_change_required=True,
        )
    if "provider_moderation_error" in normalized:
        return FailureDiagnosis(
            code="provider_moderation_unspecified",
            title="内容审核未通过",
            user_message="Seedance 返回了通用内容审核错误，但没有提供具体审核子类型。",
            next_action=(
                "不要推断为商标或其他具体原因。向用户展示原始错误，返回故事板提示词和"
                "图片素材检查；获得更完整原因或完成合规调整后，重新确认故事板及 Seedance 提示词。"
            ),
            retry_allowed=False,
            requires_user_confirmation=True,
            prompt_or_image_change_required=True,
        )
    if any(
        marker in normalized
        for marker in ("read timed out", "s3 upload failed", "connection reset by peer")
    ):
        return FailureDiagnosis(
            code="transient_media_fetch",
            title="上游媒体读取超时",
            user_message="服务商拉取已上传图片时发生临时网络失败，提示词和素材本身无需修改。",
            next_action="保留原请求和审批摘要，等待用户明确确认后再原样发起一次新请求。",
            retry_allowed=True,
            requires_user_confirmation=True,
            prompt_or_image_change_required=False,
        )
    if "duration_too_long" in normalized and any(
        marker in normalized for marker in ("video_reference", "reference_video")
    ):
        return FailureDiagnosis(
            code="stale_reference_video",
            title="旧方案参考视频超长",
            user_message="请求仍携带参考视频，且服务商判定其时长超过限制。",
            next_action=(
                "当前固定 B 方案必须删除 `reference_videos` 并重新生成请求；"
                "若未来其他方案明确需要参考视频，则先将其控制在 15 秒以内。"
            ),
            retry_allowed=False,
            requires_user_confirmation=True,
            prompt_or_image_change_required=False,
        )
    return FailureDiagnosis(
        code="unknown_provider_failure",
        title="未识别的服务商错误",
        user_message="服务商返回了尚未分类的错误，系统不会自动创建新的付费任务。",
        next_action="保留原始错误和请求参数，先向用户说明，再决定是否修改或重新发起。",
        retry_allowed=False,
        requires_user_confirmation=True,
        prompt_or_image_change_required=False,
    )


def build_failure_report(message: str) -> dict[str, Any]:
    return {"raw_error": message, **asdict(classify_failure(message))}


def _error_message(response: dict[str, Any], fallback: str) -> str:
    direct = response.get("message") or response.get("msg")
    if direct:
        return str(direct)
    nested = response.get("error")
    if isinstance(nested, dict):
        nested_message = nested.get("message") or nested.get("msg")
        if nested_message:
            return str(nested_message)
    if nested:
        return str(nested)
    return fallback


def _split_response(raw_response: Any) -> tuple[int, dict[str, Any]]:
    if isinstance(raw_response, tuple) and len(raw_response) == 2:
        status_code, payload = raw_response
        return int(status_code), dict(payload)
    return 200, dict(raw_response)


def _read_json_bytes(payload: bytes) -> dict[str, Any]:
    if not payload:
        return {}
    return json.loads(payload.decode("utf-8"))


def _urllib_request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    body = None
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, _read_json_bytes(response.read())
    except HTTPError as exc:
        return exc.code, _read_json_bytes(exc.read())


def _download_file(url: str, output_path: Path) -> None:
    request = Request(url, method="GET")
    with urlopen(request, timeout=120) as response:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.read())


class SeedanceHttpClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str,
        request_json: Callable[..., Any] | None = None,
        download: Callable[[str, Path], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        request_timeout: float = 60,
        max_attempts: int = 3,
        service_name: str = "Seedance provider",
        api_key_name: str = "SEEDANCE_API_KEY",
        auth_header_name: str = "Authorization",
        auth_header_prefix: str = "Bearer ",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.request_json = request_json or _urllib_request_json
        self.download = download or _download_file
        self.sleep = sleep
        self.clock = clock
        self.request_timeout = request_timeout
        self.max_attempts = max_attempts
        self.service_name = service_name
        self.api_key_name = api_key_name
        self.auth_header_name = auth_header_name
        self.auth_header_prefix = auth_header_prefix
        self.last_response: dict[str, Any] = {}
        self.last_status_response: dict[str, Any] = {}

    def create_video(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError

    def get_status(self, task_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def download_video(self, video_url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.download(video_url, output_path)

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None,
        *,
        retry_transient: bool = True,
        retry_block_reason: str = "duplicate side effect",
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            self.auth_header_name: f"{self.auth_header_prefix}{self.api_key}",
            "Content-Type": "application/json",
        }
        delay = 1.0
        for attempt in range(1, self.max_attempts + 1):
            status_code, payload = _split_response(
                self.request_json(
                    method=method,
                    url=url,
                    headers=headers,
                    json_body=json_body,
                    timeout=self.request_timeout,
                )
            )
            if status_code == 429 or 500 <= status_code < 600:
                if not retry_transient:
                    message = _error_message(payload, "ambiguous create response")
                    raise SeedanceApiError(
                        f"{self.service_name} non-idempotent create request returned "
                        f"HTTP {status_code}: {message}; not retried to avoid a "
                        f"{retry_block_reason}"
                    )
                if attempt == self.max_attempts:
                    raise SeedanceApiError(
                        f"{self.service_name} request failed with HTTP {status_code}"
                    )
                self.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if status_code in {401, 403}:
                raise SeedanceApiError(
                    f"{self.service_name} request rejected with HTTP {status_code}; "
                    f"check {self.api_key_name}"
                )
            if status_code >= 400:
                message = _error_message(payload, "request failed")
                raise SeedanceApiError(
                    f"{self.service_name} request failed with HTTP {status_code}: {message}"
                )
            return payload
        raise SeedanceApiError(f"{self.service_name} request failed")


def _find_response_value(value: Any, names: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in names and item not in (None, ""):
                return item
        for item in value.values():
            found = _find_response_value(item, names)
            if found not in (None, ""):
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_response_value(item, names)
            if found not in (None, ""):
                return found
    return None


class YoudaoSeedanceClient(SeedanceHttpClient):
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://openapi.youdao.com/llmgateway",
        model: str = "seedance-2.0-fast",
        project_name: str = "default",
        request_json: Callable[..., Any] | None = None,
        download: Callable[[str, Path], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        request_timeout: float = 90,
        max_attempts: int = 3,
    ) -> None:
        super().__init__(
            api_key,
            base_url=base_url,
            request_json=request_json,
            download=download,
            sleep=sleep,
            clock=clock,
            request_timeout=request_timeout,
            max_attempts=max_attempts,
            service_name="Youdao Seedance gateway",
            api_key_name="YOUDAO_API_KEY",
            auth_header_name="x-api-key",
            auth_header_prefix="",
        )
        self.model = model
        self.project_name = project_name

    def register_asset(self, source_url: str, name: str) -> str:
        _require_public_https_urls([source_url])
        response = self._request(
            "POST",
            YOUDAO_ASSET_PATH.format(action="CreateAsset"),
            {
                "URL": source_url,
                "Name": name,
                "AssetType": "Image",
                "ProjectName": self.project_name,
            },
            retry_transient=False,
            retry_block_reason="duplicate asset registration",
        )
        result = response.get("Result") or response.get("result") or {}
        asset_id = result.get("Id") or result.get("id") if isinstance(result, dict) else None
        if not asset_id:
            raise SeedanceApiError(
                "Youdao CreateAsset response did not include Result.id"
            )
        return str(asset_id)

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            YOUDAO_ASSET_PATH.format(action="GetAsset"),
            {"Id": asset_id, "ProjectName": self.project_name},
        )

    def create_video(self, payload: dict[str, Any]) -> str:
        prompt = _payload_prompt(payload) if isinstance(payload.get("content"), list) else ""
        _validate_route_integrity(payload, prompt)
        response = self._request(
            "POST",
            YOUDAO_CREATE_PATH,
            payload,
            retry_transient=False,
            retry_block_reason="duplicate paid task",
        )
        self.last_response = response
        task_id = _find_response_value(response, {"id", "task_id", "taskid"})
        if not task_id:
            raise SeedanceApiError("Youdao response did not include task id")
        return str(task_id)

    def get_status(self, task_id: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            YOUDAO_QUERY_PATH.format(task_id=task_id, model=self.model),
            None,
        )
        self.last_status_response = response
        return response


def prepare_youdao_assets(
    client: YoudaoSeedanceClient,
    source_urls: list[str],
    manifest_path: Path,
    *,
    timeout: float = 900,
    poll_interval: float = 5,
    max_workers: int = 4,
    cache_only: bool = False,
) -> list[str]:
    _require_public_https_urls(source_urls)
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    with _manifest_lock(manifest_path):
        existing: list[dict[str, str]] = []
        if manifest_path.is_file():
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [item for item in loaded if isinstance(item, dict)]
        by_source = {item.get("source_url"): item for item in existing}
        unique_urls = list(dict.fromkeys(source_urls))
        if cache_only:
            cached_uris: dict[str, str] = {}
            for source_url in unique_urls:
                item = by_source.get(source_url)
                asset_uri = item.get("asset_uri") if isinstance(item, dict) else None
                asset_id = item.get("asset_id") if isinstance(item, dict) else None
                if (
                    not isinstance(item, dict)
                    or str(item.get("status", "")).lower() != "active"
                    or not _non_empty_string(asset_id)
                    or asset_uri != f"asset://{asset_id}"
                    or item.get("project_name") != client.project_name
                ):
                    raise PayloadError(
                        f"audited cache-only asset mapping missing for {source_url}"
                    )
                cached_uris[source_url] = asset_uri
            return [cached_uris[source_url] for source_url in source_urls]
        results: dict[str, dict[str, str]] = {}
        worker_count = min(max_workers, len(unique_urls)) if unique_urls else 0
        if worker_count:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(
                        _prepare_youdao_asset,
                        client,
                        source_url,
                        f"seedance-reference-{index:02d}",
                        by_source.get(source_url),
                        timeout=timeout,
                        poll_interval=poll_interval,
                    ): source_url
                    for index, source_url in enumerate(unique_urls, start=1)
                }
                for future, source_url in ((future, futures[future]) for future in futures):
                    results[source_url] = future.result()
        # Preserve mappings not requested by this invocation so concurrent or
        # sequential callers never erase another invocation's cached assets.
        manifest = [dict(item) for item in existing if item.get("source_url") not in results]
        for index, source_url in enumerate(unique_urls, start=1):
            item = dict(results[source_url])
            item["index"] = str(index)
            manifest.append(item)
        _write_json(manifest_path, manifest)
        return [results[source_url]["asset_uri"] for source_url in source_urls]


@contextmanager
def _manifest_lock(manifest_path: Path):
    resolved = manifest_path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    key = str(resolved).casefold()
    with _MANIFEST_LOCKS_GUARD:
        process_lock = _MANIFEST_LOCKS.setdefault(key, threading.RLock())
    # Serialize same-process callers before opening/locking the Windows lock
    # file.  This avoids a sharing violation from two simultaneous ``a+b``
    # opens while preserving the OS-level lock for separate worker processes.
    process_lock.acquire()
    lock_path = resolved.with_name(f".{resolved.name}.lock")
    handle = None
    try:
        handle = lock_path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        try:
            if handle is not None:
                handle.close()
        finally:
            process_lock.release()


def _prepare_youdao_asset(
    client: YoudaoSeedanceClient,
    source_url: str,
    name: str,
    cached: dict[str, str] | None,
    *,
    timeout: float,
    poll_interval: float,
) -> dict[str, str]:
    if cached and cached.get("status", "").lower() == "active":
        return cached
    asset_id = str((cached or {}).get("asset_id") or "")
    if not asset_id:
        asset_id = client.register_asset(source_url, name)
    deadline = client.clock() + timeout
    while True:
        response = client.get_asset(asset_id)
        status = str(_find_response_value(response, {"status"}) or "").lower()
        if status == "active":
            return {
                "source_url": source_url,
                "asset_id": asset_id,
                "asset_uri": f"asset://{asset_id}",
                "status": "Active",
                "project_name": client.project_name,
            }
        if status == "failed":
            reason = _find_response_value(response, {"message", "error", "reason"})
            raise SeedanceApiError(
                f"Youdao asset {asset_id} processing failed: {reason or 'unknown error'}"
            )
        if status not in {"processing", "submitting", "queued"}:
            raise SeedanceApiError(f"unknown Youdao asset status: {status or '<empty>'}")
        if client.clock() >= deadline:
            raise PollTimeoutError(
                f"Youdao asset {asset_id} did not become Active before timeout"
            )
        client.sleep(poll_interval)


def poll_delay_for_status(status: str, attempt: int, maximum: float) -> float:
    normalized = status.lower()
    base = {
        "submitting": 2.0,
        "queued": 5.0,
        "running": 15.0,
        "processing": 15.0,
    }.get(normalized, 10.0)
    return min(maximum, base * (1.0 + min(max(attempt, 0), 6) * 0.25))


def poll_youdao_task(
    client: YoudaoSeedanceClient,
    task_id: str,
    *,
    timeout: float | None = None,
    poll_interval: float = 20,
) -> str:
    deadline = None if timeout is None else client.clock() + timeout
    attempt = 0
    while True:
        response = client.get_status(task_id)
        status = str(_find_response_value(response, {"status"}) or "").lower()
        if status == "succeeded":
            video_url = _find_response_value(
                response, {"video_url", "videourl"}
            )
            if not video_url:
                raise SeedanceApiError(
                    "succeeded Youdao task did not include video_url"
                )
            return str(video_url)
        if status in {"failed", "expired"}:
            message = _find_response_value(
                response, {"message", "error_message", "error", "reason"}
            )
            raise TaskFailedError(str(message or f"Youdao task {status}"))
        if status not in {"submitting", "queued", "running", "processing"}:
            raise SeedanceApiError(
                f"unknown Youdao task status: {status or '<empty>'}"
            )
        if deadline is not None and client.clock() >= deadline:
            raise PollTimeoutError(f"Youdao task {task_id} timed out")
        client.sleep(poll_delay_for_status(status, attempt, poll_interval))
        attempt += 1


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False,
        prefix=f".{path.name}.", suffix=".tmp",
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    try:
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare, submit, or resume Seedance 2.0 video tasks."
    )
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--image-url", action="append", default=[])
    parser.add_argument("--duration", type=int)
    parser.add_argument("--ratio", default="9:16")
    parser.add_argument("--resolution", choices=("480p", "720p", "1080p", "4k"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--resume-task-id")
    parser.add_argument("--approved-request-sha256")
    parser.add_argument("--audited-request-sha256")
    parser.add_argument("--audit-artifact", type=Path)
    parser.add_argument("--approved-script-sha256")
    parser.add_argument("--seedance-input-contract", type=Path)
    parser.add_argument(
        "--seedance20-skill-file",
        type=Path,
        default=DEFAULT_SEEDANCE20_SKILL_FILE,
    )
    parser.add_argument(
        "--profile-snapshot",
        type=Path,
        help="internal high_fidelity_hybrid_v1 snapshot used to pin Invocation A/B bytes",
    )
    parser.add_argument(
        "--prescript-artifact",
        type=Path,
        help="internal seedance20_prescript_v1 artifact to reconcile before B",
    )
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--poll-interval", type=float, default=20)
    parser.add_argument("--asset-timeout", type=float, default=900)
    parser.add_argument("--asset-poll-interval", type=float, default=5)
    args = parser.parse_args()
    # Resolve only from an explicit worker argument or deployment environment;
    # never silently use ~/.codex from the machine running the process.
    args.seedance20_skill_file = resolve_seedance20_skill_file(
        args.seedance20_skill_file
    )

    authorization_flags = (
        args.audited_request_sha256,
        args.approved_request_sha256,
        args.audit_artifact,
        args.approved_script_sha256,
        args.seedance_input_contract,
    )
    has_authorization_flags = any(value is not None for value in authorization_flags)
    has_internal_snapshot_flags = args.profile_snapshot is not None or args.prescript_artifact is not None
    if (args.profile_snapshot is None) != (args.prescript_artifact is None):
        raise PayloadError(
            "--profile-snapshot and --prescript-artifact must be supplied together"
        )
    if args.resume_task_id and args.dry_run:
        raise PayloadError("resume-task-id cannot be combined with dry-run")
    if args.resume_task_id and (has_authorization_flags or has_internal_snapshot_flags):
        raise PayloadError(
            "resume-task-id cannot be combined with audited, legacy, or new-request profile flags"
        )
    if args.profile_snapshot is not None:
        if args.seedance20_skill_file is None:
            raise PayloadError("--profile-snapshot requires a packaged --seedance20-skill-file or SEEDANCE20_SKILL_FILE")
        validate_profile_snapshot_file(args.profile_snapshot, args.seedance20_skill_file)
    if args.prescript_artifact is not None:
        if args.seedance20_skill_file is None:
            raise PayloadError("--prescript-artifact requires a packaged --seedance20-skill-file or SEEDANCE20_SKILL_FILE")
        validate_prescript_snapshot_file(args.prescript_artifact, args.seedance20_skill_file)
    if args.dry_run and has_authorization_flags:
        raise PayloadError("dry-run cannot be combined with authorization flags")

    audited_request = bool(args.audited_request_sha256)
    legacy_request = bool(args.approved_request_sha256)
    if audited_request and legacy_request:
        raise PayloadError("provide exactly one approved or audited request digest")
    if audited_request:
        if args.audit_artifact is None:
            raise PayloadError("--audit-artifact is required with --audited-request-sha256")
        if args.approved_script_sha256 is None:
            raise PayloadError("--approved-script-sha256 is required with --audited-request-sha256")
        if args.seedance_input_contract is None:
            raise PayloadError(
                "--seedance-input-contract is required with --audited-request-sha256"
            )
    elif (
        args.audit_artifact is not None
        or args.approved_script_sha256 is not None
        or args.seedance_input_contract is not None
    ):
        raise PayloadError("audited flags require --audited-request-sha256")

    if not args.resume_task_id:
        if args.prompt_file is None:
            raise PayloadError("--prompt-file is required for a new Seedance request")
        if args.duration is None:
            raise PayloadError("--duration is required for a new Seedance request")

    settings = load_settings(args.env_file)
    settings.require_seedance()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prompt = (
        args.prompt_file.read_text(encoding="utf-8-sig")
        if args.prompt_file is not None and not args.resume_task_id
        else ""
    )

    client: SeedanceHttpClient = YoudaoSeedanceClient(
        settings.youdao_api_key,
        base_url=settings.youdao_base_url,
        model=settings.youdao_model,
        project_name=settings.youdao_project_name,
    )
    image_references = []
    model = settings.youdao_model
    resolution = args.resolution or settings.youdao_resolution

    if not args.resume_task_id:
        if audited_request:
            _validate_audited_factory_parameters(
                prompt=prompt,
                provider=settings.seedance_api_provider,
                model=model,
                resolution=resolution,
                ratio=args.ratio,
                duration=args.duration,
                input_contract_path=args.seedance_input_contract,
                approved_script_sha256=args.approved_script_sha256,
                skill_file=args.seedance20_skill_file,
            )

        image_references = prepare_youdao_assets(
            client,
            args.image_url,
            args.output_dir / "youdao_assets.json",
            timeout=args.asset_timeout,
            poll_interval=args.asset_poll_interval,
            cache_only=audited_request and not args.dry_run,
        )

        payload = build_payload(
            prompt,
            args.duration,
            args.ratio,
            image_references,
            [],
            provider=settings.seedance_api_provider,
            model=model,
            resolution=resolution,
        )
        _write_json(args.output_dir / "request.redacted.json", payload)
        payload_sha256 = request_sha256(payload)
        _write_json(
            args.output_dir / "approval_preview.json",
            {
                "status": (
                    "internal_integrity_preview"
                    if args.dry_run
                    else "internal_integrity_check"
                    if args.audited_request_sha256
                    else "approval_check"
                ),
                "request_sha256": payload_sha256,
            },
        )
        if args.dry_run:
            _write_json(args.output_dir / "create_response.json", {"status": "dry_run"})
            _write_json(args.output_dir / "status.json", {"status": "dry_run"})
            return 0

    try:
        if args.resume_task_id:
            task_id = args.resume_task_id
            _write_json(args.output_dir / "create_response.json", {"resume_task_id": task_id})
        else:
            require_request_authorization(
                payload,
                approved_sha256=args.approved_request_sha256,
                audited_sha256=args.audited_request_sha256,
            )
            audit_artifact_sha256 = None
            if args.audited_request_sha256:
                if args.audit_artifact is None:
                    raise PayloadError("--audit-artifact is required with --audited-request-sha256")
                if args.approved_script_sha256 is None:
                    raise PayloadError("--approved-script-sha256 is required with --audited-request-sha256")
                audit_artifact_sha256 = validate_audit_artifact(
                    payload,
                    args.audit_artifact,
                    args.audited_request_sha256,
                    args.approved_script_sha256,
                    seedance_input_contract_path=args.seedance_input_contract,
                    seedance20_skill_file=args.seedance20_skill_file,
                    strict_factory=True,
                )
            _write_json(
                args.output_dir / "request_integrity.json",
                {
                    "status": (
                        "internally_audited"
                        if args.audited_request_sha256
                        else "user_approved"
                    ),
                    "request_sha256": payload_sha256,
                    "authorization": (
                        "seedance_20_audit_artifact"
                        if args.audited_request_sha256
                        else "explicit_user_approval"
                    ),
                    "audit_artifact_sha256": audit_artifact_sha256,
                },
            )
            task_id = client.create_video(payload)
            _write_json(args.output_dir / "create_response.json", client.last_response)
        (args.output_dir / "task_id.txt").write_text(task_id, encoding="utf-8")

        if args.poll:
            video_url = poll_youdao_task(
                client,
                task_id,
                timeout=args.timeout,
                poll_interval=args.poll_interval,
            )
            _write_json(args.output_dir / "status.json", client.last_status_response)
            client.download_video(video_url, args.output_dir / "result.mp4")
        else:
            _write_json(
                args.output_dir / "status.json",
                {
                    "task_id": task_id,
                    "status": "known_task" if args.resume_task_id else "created",
                },
            )
    except SeedanceApiError as exc:
        if client.last_status_response:
            _write_json(args.output_dir / "status.json", client.last_status_response)
        report = build_failure_report(str(exc))
        _write_json(args.output_dir / "failure.json", report)
        raise SystemExit(f"{report['user_message']}\n下一步：{report['next_action']}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
