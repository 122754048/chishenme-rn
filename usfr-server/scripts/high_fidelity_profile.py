"""Internal profile snapshot and dependency pinning helpers.

The high-fidelity profile is deliberately an additive execution profile.  This
module does not bind slots, choose routes, add run states, or call a provider;
it only creates and validates immutable run metadata that lets Invocation A
and Invocation B prove they used the same packaged bytes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


PROFILE_NAME = "high_fidelity_hybrid_v1"
SCHEMA_VERSION = "high-fidelity-profile/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_~-]{0,127}$")
_PRIVATE_URI_SCHEMES = ("s3://", "gs://", "az://", "azure://", "artifact://", "https://")
_PRODUCTION_ACTIVATION_MODES = {"active", "production", "default"}
_ACTIVATION_MODES = frozenset({"shadow", "legacy", "disabled", "active", "production", "default"})
_ACTIVATION_EVIDENCE_SCHEMA = "high-fidelity-activation-evidence/v1"
_ACTIVATION_RECEIPT_FIELDS = (
    "receipt_id",
    "artifact_id",
    "uri",
    "object_key",
    "sha256",
    "size_bytes",
    "content_type",
)
_COMPARISON_METRICS = (
    "fixed_slots",
    "existing_approvals",
    "fixed_b_provider",
    "duplicate_task_protection",
    "claim_evidence_coverage",
    "exact_voiceover_content",
    "action_chain_coverage",
    "ui_errors",
    "claim_regressions",
    "hard_failures",
    "route_timeline_coverage",
    "high_criticality_factor_min",
    "ui_ocr",
)
_COMPARISON_METRIC_ALIASES = {
    "claim_evidence_coverage": ("claim_evidence_coverage", "high_criticality_claim_evidence", "high_criticality_claim_evidence_percent"),
    "exact_voiceover_content": ("exact_voiceover_content", "exact_approved_voiceover_content", "voiceover_exact"),
    "action_chain_coverage": ("action_chain_coverage", "high_criticality_action_chain_coverage", "action_chain_coverage_percent"),
    "ui_errors": ("ui_errors", "ui_error_count"),
    "claim_regressions": ("claim_regressions", "false_claim_regressions"),
    "hard_failures": ("hard_failures", "hard_failure_count"),
    "route_timeline_coverage": ("route_timeline_coverage", "timeline_route_coverage"),
    "high_criticality_factor_min": ("high_criticality_factor_min", "high_criticality_min_score"),
    "ui_ocr": ("ui_ocr", "ui_ocr_percent"),
}


class ProfileSnapshotError(ValueError):
    """Raised when profile metadata cannot be trusted for a downstream stage."""


def _canonical(value: Any) -> bytes:
    """Return the service's stable UTF-8 JSON representation."""

    def default(item: Any) -> Any:
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, (datetime,)):
            return item.isoformat()
        raise TypeError(f"unsupported value in profile metadata: {type(item).__name__}")

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=default).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProfileSnapshotError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileSnapshotError(f"{field} must be a non-empty string")
    return value.strip()


def _version_from_skill(path: Path) -> str | None:
    """Read the lightweight frontmatter version without a YAML dependency."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    in_frontmatter = bool(lines and lines[0].strip() == "---")
    if not in_frontmatter:
        return None
    for line in lines[1:120]:
        if line.strip() == "---":
            break
        match = re.match(r"^\s*(?:version|metadata\.version)\s*:\s*[\"']?([^\"'#\s]+)", line)
        if match:
            return match.group(1).strip()
    # The common nested form is:
    # metadata:
    #   version: "6.6.0"
    for index, line in enumerate(lines[1:120]):
        if line.strip().lower() == "metadata:":
            for child in lines[index + 2 : index + 8]:
                match = re.match(r"^\s+version\s*:\s*[\"']?([^\"'#\s]+)", child)
                if match:
                    return match.group(1).strip()
    return None


def _version_from_bytes(payload: bytes) -> str | None:
    """Read a lightweight frontmatter version from immutable bundle bytes."""

    try:
        text = payload.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return None
    lines = text.splitlines()
    in_frontmatter = bool(lines and lines[0].strip() == "---")
    if not in_frontmatter:
        return None
    for line in lines[1:120]:
        if line.strip() == "---":
            break
        match = re.match(r"^\s*(?:version|metadata\.version)\s*:\s*[\"']?([^\"'#\s]+)", line)
        if match:
            return match.group(1).strip()
    for index, line in enumerate(lines[1:120]):
        if line.strip().lower() == "metadata:":
            for child in lines[index + 2 : index + 8]:
                match = re.match(r"^\s+version\s*:\s*[\"']?([^\"'#\s]+)", child)
                if match:
                    return match.group(1).strip()
    return None


def _relative_package_path(path: Path, name: str, supplied: Any = None) -> str:
    if supplied is not None:
        raw = str(supplied).replace("\\", "/")
        segments = raw.split("/")
        if (
            not raw
            or raw.startswith(("/", "./", "../"))
            or any(segment in {"", ".", ".."} for segment in segments)
            or ":" in segments[0]
            or not _PACKAGE_PATH.fullmatch(raw)
        ):
            raise ProfileSnapshotError("dependency package_path must be a safe relative path")
        return raw

    parts = [part for part in path.parts if part not in {".", ""}]
    # Preserve the deployable package-relative suffix when this is a normal
    # ~/.codex/skills checkout.  No workstation prefix enters the snapshot.
    lowered = [part.lower() for part in parts]
    for marker in ("bundled-skills", "skills"):
        if marker in lowered:
            index = lowered.index(marker)
            candidate = "/".join(parts[index + 1 :])
            if candidate and _PACKAGE_PATH.fullmatch(candidate) and not any(part in {"", ".", ".."} for part in candidate.split("/")):
                return candidate
    candidate = f"{name}/{path.name}" if path.parent.name != name else f"{name}/{path.name}"
    candidate = candidate.replace("\\", "/")
    if not _PACKAGE_PATH.fullmatch(candidate) or any(part in {"", ".", ".."} for part in candidate.split("/")):
        raise ProfileSnapshotError("dependency path cannot be represented as a package-relative path")
    return candidate


def _normalise_dependencies(dependency_paths: Any) -> list[tuple[str, Any]]:
    # Production injects an immutable resolver; keep this duck-typed so the
    # script remains independently packageable and the development Path
    # adapter remains backwards compatible.
    records = getattr(dependency_paths, "dependency_records", None)
    if callable(records):
        dependency_paths = records()
    if isinstance(dependency_paths, Mapping):
        values = list(dependency_paths.items())
    elif isinstance(dependency_paths, (str, Path)):
        path = Path(dependency_paths)
        values = [(path.parent.name or path.stem, path)]
    else:
        try:
            values = []
            for item in dependency_paths:
                path = item.get("path") if isinstance(item, Mapping) else item
                name = item.get("name") if isinstance(item, Mapping) else None
                values.append((name or Path(str(path)).parent.name or Path(str(path)).stem, item))
        except TypeError as exc:
            raise ProfileSnapshotError("dependency_paths must be a mapping or iterable") from exc
    if not values:
        raise ProfileSnapshotError("at least one profile dependency is required")
    normalised: list[tuple[str, Any]] = []
    for raw_name, value in values:
        name = _require_non_empty_string(raw_name, "dependency name")
        normalised.append((name, value))
    return sorted(normalised, key=lambda item: item[0])


def _dependency_record(name: str, value: Any, config: Mapping[str, Any], expected: Mapping[str, Any] | None = None) -> dict[str, str]:
    supplied_version: Any = None
    supplied_digest: Any = None
    supplied_package: Any = None
    raw_path: Any = value
    raw_bytes: bytes | None = None
    if isinstance(value, Mapping):
        raw_path = value.get("path") or value.get("file") or value.get("source")
        raw_bytes_value = value.get("bytes", value.get("data", value.get("content")))
        if raw_bytes_value is not None:
            raw_bytes = raw_bytes_value
        supplied_version = value.get("version")
        supplied_digest = value.get("sha256")
        supplied_package = value.get("package_path") or value.get("path_in_package")
    elif hasattr(value, "read_bytes") and not isinstance(value, Path):
        raw_bytes = value.read_bytes()
        supplied_version = getattr(value, "version", None)
        supplied_digest = getattr(value, "sha256", None)
        supplied_package = getattr(value, "package_path", None)
        raw_path = None
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raw_bytes = value
        raw_path = None
    if raw_bytes is not None:
        if isinstance(raw_bytes, (bytearray, memoryview)) or not isinstance(raw_bytes, bytes):
            raise ProfileSnapshotError(f"dependency {name!r} must provide immutable bytes")
        payload = bytes(raw_bytes)
        path = None
    else:
        if raw_path is None:
            raise ProfileSnapshotError(f"dependency {name!r} is missing a path or immutable bytes")
        path = Path(str(raw_path)).expanduser()
        if not path.is_file():
            raise ProfileSnapshotError(f"dependency {name!r} is missing: {path}")
        payload = path.read_bytes()
    digest = _sha256(payload)
    if supplied_digest is not None and str(supplied_digest).lower() != digest:
        raise ProfileSnapshotError(f"dependency {name!r} SHA-256 does not match its bytes")
    expected_version = (expected or {}).get("version")
    configured_versions = config.get("dependency_versions") or {}
    configured_version = configured_versions.get(name) if isinstance(configured_versions, Mapping) else None
    version = supplied_version or configured_version
    if version is None:
        version = _version_from_skill(path) if path is not None else _version_from_bytes(payload)
    version = version or expected_version
    version = _require_non_empty_string(version, f"dependency {name!r} version")
    if _VERSION.fullmatch(version) is None:
        raise ProfileSnapshotError(f"dependency {name!r} version is not a safe package version")
    # Derive the current package-relative location from the installed bytes;
    # never borrow the prior snapshot's path, otherwise a moved dependency
    # could appear fresh during the A/B consistency check.
    if supplied_package is not None:
        package_path = _relative_package_path(Path("bundle") / name / "SKILL.md", name, supplied_package)
    elif path is not None:
        package_path = _relative_package_path(path, name)
    else:
        package_path = f"dependencies/{name}/SKILL.md"
    return {"name": name, "version": version, "sha256": digest, "package_path": package_path}


def _schema_digest() -> str:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "high_fidelity_profile.schema.json"
    if schema_path.is_file():
        return _sha256(schema_path.read_bytes())
    # This fallback is only useful while packaging a worker; the manifest
    # verifier requires the schema to be present in a deployable bundle.
    return _sha256(b"https://codex.local/universal-source-fidelity/high_fidelity_profile.schema.json")


def _validate_artifact_metadata(artifact: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(artifact, Mapping):
        raise ProfileSnapshotError("artifact metadata must be an object")
    result: dict[str, Any] = {
        "kind": _require_non_empty_string(artifact.get("kind", "high_fidelity_profile"), "artifact.kind"),
        "schema_version": _require_non_empty_string(artifact.get("schema_version", SCHEMA_VERSION), "artifact.schema_version"),
        "content_type": _require_non_empty_string(artifact.get("content_type", "application/json"), "artifact.content_type"),
    }
    uri = artifact.get("uri")
    if uri is not None:
        uri = _require_non_empty_string(uri, "artifact.uri")
        if not uri.startswith(_PRIVATE_URI_SCHEMES) or uri.startswith(("file://", "http://")):
            raise ProfileSnapshotError("artifact.uri must be a private object-store reference")
        result["uri"] = uri
    else:
        result["uri"] = None
    for field in ("tenant_id", "run_id", "producer_stage", "correlation_id"):
        if field in artifact and artifact[field] is not None:
            result[field] = _require_non_empty_string(artifact[field], f"artifact.{field}")
    if artifact.get("private") is not None and artifact.get("private") is not True:
        raise ProfileSnapshotError("artifact.private must be true when supplied")
    result["private"] = True
    return result


def _parent_digests(config: Mapping[str, Any]) -> dict[str, str]:
    raw = config.get("parent_digests", config.get("immutable_parent_digests", {}))
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ProfileSnapshotError("parent_digests must be an object")
    result: dict[str, str] = {}
    for name, digest in sorted(raw.items(), key=lambda item: str(item[0])):
        key = _require_non_empty_string(name, "parent digest name")
        result[key] = _require_digest(digest, f"parent_digests.{key}")
    return result


def _evidence_section(evidence: Mapping[str, Any], *names: str) -> Mapping[str, Any]:
    section = next((evidence.get(name) for name in names if evidence.get(name) is not None), None)
    if not isinstance(section, Mapping):
        raise ProfileSnapshotError(f"activation evidence is missing {names[0]}")
    report = section.get("report")
    if report is not None:
        if not isinstance(report, Mapping):
            raise ProfileSnapshotError(f"activation evidence {names[0]}.report must be an object")
        return report
    return section


def _evidence_wrapper(evidence: Mapping[str, Any], *names: str) -> Mapping[str, Any]:
    """Select a report envelope without unwrapping its ``report`` payload."""

    section = next((evidence.get(name) for name in names if evidence.get(name) is not None), None)
    if not isinstance(section, Mapping):
        raise ProfileSnapshotError(f"activation evidence is missing {names[0]}")
    return section


def _evidence_count(report: Mapping[str, Any], label: str) -> int:
    value = report.get("case_count")
    if value is None:
        rows = report.get("cases", report.get("records"))
        value = len(rows) if isinstance(rows, list) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProfileSnapshotError(f"activation evidence {label}.case_count must be a non-negative integer")
    return value


def _zero_if_present(report: Mapping[str, Any], label: str, *fields: str) -> None:
    for field in fields:
        if field not in report:
            continue
        value = report[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 0:
            raise ProfileSnapshotError(f"activation evidence {label}.{field} must be zero")


def _shadow_compatibility_pass(report: Mapping[str, Any]) -> bool:
    explicit = report.get("compatibility_pass")
    if explicit is not None:
        return explicit is True
    records = report.get("records", report.get("cases"))
    if not isinstance(records, list) or not records:
        return False
    for record in records:
        if not isinstance(record, Mapping):
            return False
        invariants = record.get("compatibility_invariants")
        if not isinstance(invariants, Mapping) or not invariants:
            return False
        for key in ("fixed_slots", "existing_approvals", "fixed_b_provider", "max_generated_regions"):
            if key in invariants and invariants[key] is not True:
                return False
        metrics = record.get("compatibility_metrics")
        if not isinstance(metrics, Mapping):
            return False
        if metrics.get("fixed_slots") is not True or metrics.get("existing_approvals") is not True or metrics.get("fixed_b_provider") is not True:
            return False
        if metrics.get("hard_failures", 0) != 0 or metrics.get("ui_errors", 0) != 0 or metrics.get("claim_regressions", 0) != 0:
            return False
    return True


def _private_uri(value: Any, label: str) -> str:
    uri = _require_non_empty_string(value, label)
    if not uri.startswith(_PRIVATE_URI_SCHEMES) or uri.startswith(("file://", "http://")):
        raise ProfileSnapshotError(f"{label} must be a private object-store reference")
    return uri


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    payload = json.loads(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload.pop("receipt_sha256", None)
    return _sha256(_canonical(payload))


def _validate_activation_receipt(
    receipt: Any,
    report_sha256: str,
    report_size: int,
    label: str,
    receipt_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None,
) -> dict[str, Any]:
    """Validate a server-minted immutable artifact receipt.

    The JSON envelope is deliberately not treated as authority.  In a
    production worker ``receipt_verifier`` must resolve the receipt through the
    server's private object-store/evidence ledger and return the authoritative
    metadata.  This prevents a caller from changing a report and simply
    changing the claimed hash alongside it.
    """

    if not isinstance(receipt, Mapping):
        raise ProfileSnapshotError(f"activation evidence {label}.publication_receipt must be an object")
    normalized = dict(receipt)
    for field in ("receipt_id", "artifact_id", "object_key", "content_type"):
        _require_non_empty_string(normalized.get(field), f"{label}.publication_receipt.{field}")
    normalized["uri"] = _private_uri(normalized.get("uri"), f"{label}.publication_receipt.uri")
    normalized["sha256"] = _require_digest(normalized.get("sha256"), f"{label}.publication_receipt.sha256")
    if normalized["sha256"] != report_sha256:
        raise ProfileSnapshotError(f"activation evidence {label} receipt SHA-256 does not match report bytes")
    size = normalized.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size != report_size:
        raise ProfileSnapshotError(f"activation evidence {label} receipt size does not match report bytes")
    if normalized.get("content_type") != "application/json":
        raise ProfileSnapshotError(f"activation evidence {label} receipt content type must be application/json")
    if normalized.get("immutable") is not True or normalized.get("server_minted") is not True:
        raise ProfileSnapshotError(f"activation evidence {label} receipt is not an immutable server publication")
    normalized["receipt_sha256"] = _require_digest(
        normalized.get("receipt_sha256"), f"{label}.publication_receipt.receipt_sha256"
    )
    if _receipt_digest(normalized) != normalized["receipt_sha256"]:
        raise ProfileSnapshotError(f"activation evidence {label} receipt digest is stale or tampered")
    if receipt_verifier is None:
        raise ProfileSnapshotError(
            f"activation evidence {label} has no server receipt verifier; self-attested reports are not admissible"
        )
    try:
        authoritative = receipt_verifier(dict(normalized))
    except Exception as exc:  # pragma: no cover - adapter-specific failures
        raise ProfileSnapshotError(f"activation evidence {label} receipt verification failed: {exc}") from exc
    if not isinstance(authoritative, Mapping):
        raise ProfileSnapshotError(f"activation evidence {label} receipt verifier returned no authoritative receipt")
    authority = dict(authoritative)
    for field in _ACTIVATION_RECEIPT_FIELDS:
        if authority.get(field) != normalized.get(field):
            raise ProfileSnapshotError(f"activation evidence {label} receipt authority mismatch for {field}")
    if authority.get("immutable") is not True or authority.get("server_minted") is not True:
        raise ProfileSnapshotError(f"activation evidence {label} authoritative receipt is not immutable/server-minted")
    authority_receipt_sha = authority.get("receipt_sha256")
    if authority_receipt_sha is not None:
        _require_digest(authority_receipt_sha, f"{label}.authoritative_receipt.receipt_sha256")
        if str(authority_receipt_sha) != normalized["receipt_sha256"]:
            raise ProfileSnapshotError(f"activation evidence {label} authoritative receipt digest mismatch")
    return normalized


def _strict_report_envelope(
    evidence: Mapping[str, Any],
    names: tuple[str, ...],
    label: str,
    receipt_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    section = _evidence_wrapper(evidence, *names)
    report = section.get("report")
    if not isinstance(report, Mapping):
        raise ProfileSnapshotError(f"activation evidence {label} must carry a complete report artifact")
    report = json.loads(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    report_bytes = _canonical(report)
    report_sha = _require_digest(section.get("report_sha256"), f"activation evidence {label}.report_sha256")
    actual_sha = _sha256(report_bytes)
    if report_sha != actual_sha:
        raise ProfileSnapshotError(f"activation evidence {label} report SHA-256 does not match report bytes")
    receipt = _validate_activation_receipt(
        section.get("publication_receipt") or section.get("receipt") or section.get("artifact"),
        report_sha,
        len(report_bytes),
        label,
        receipt_verifier,
    )
    return report, report_sha, receipt


def _metric_failures(metrics: Any, label: str) -> list[str]:
    if not isinstance(metrics, Mapping):
        return [f"{label}:compatibility_metrics"]
    failures: list[str] = []
    for key in _COMPARISON_METRICS:
        actual_key = next((candidate for candidate in _COMPARISON_METRIC_ALIASES.get(key, (key,)) if candidate in metrics), None)
        if actual_key is None:
            failures.append(f"{label}:compatibility_metrics.{key}")
            continue
        value = metrics[actual_key]
        if key in {"fixed_slots", "existing_approvals", "fixed_b_provider", "duplicate_task_protection"}:
            if value is not True:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key in {"claim_evidence_coverage", "exact_voiceover_content"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 100:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key == "action_chain_coverage":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 90:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key == "high_criticality_factor_min":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 90:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key == "ui_ocr":
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 100):
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif key == "route_timeline_coverage":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 100:
                failures.append(f"{label}:compatibility_metrics.{key}")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 0:
            failures.append(f"{label}:compatibility_metrics.{key}")
    return failures


def _strict_shadow_report(report: Mapping[str, Any]) -> int:
    records = report.get("records", report.get("cases"))
    if not isinstance(records, list) or not records:
        raise ProfileSnapshotError("activation evidence shadow report must contain case records")
    count = _evidence_count(report, "shadow")
    if count != len(records):
        raise ProfileSnapshotError("activation evidence shadow case_count is not server-recomputed")
    if count < 18:
        raise ProfileSnapshotError("activation evidence shadow matrix requires at least 18 cases")
    if report.get("status") not in {"shadow", "shadow_validated", "passed", "complete"}:
        raise ProfileSnapshotError("activation evidence shadow status is not passing")
    totals = {
        field: 0
        for field in ("provider_calls", "invocation_a_calls", "invocation_b_calls", "user_approvals", "paid_tasks")
    }
    for index, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise ProfileSnapshotError(f"activation evidence shadow record {index} is invalid")
        for field in totals:
            value = record.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProfileSnapshotError(f"activation evidence shadow record {index}.{field} is required")
            totals[field] += value
        invariants = record.get("compatibility_invariants")
        metrics = record.get("compatibility_metrics")
        if not isinstance(invariants, Mapping) or not isinstance(metrics, Mapping):
            raise ProfileSnapshotError(f"activation evidence shadow record {index} lacks compatibility evidence")
        for key in ("fixed_slots", "existing_approvals", "fixed_b_provider", "max_generated_regions"):
            if key in invariants and invariants[key] is not True:
                raise ProfileSnapshotError(f"activation evidence shadow record {index} has a failed invariant")
        if _metric_failures(metrics, f"shadow:{index}"):
            raise ProfileSnapshotError(f"activation evidence shadow record {index} has failed compatibility metrics")
    for field, value in totals.items():
        if report.get(field) != value:
            raise ProfileSnapshotError(f"activation evidence shadow.{field} is not server-recomputed")
    if report.get("compatibility_pass") is not None and report.get("compatibility_pass") is not True:
        raise ProfileSnapshotError("activation evidence shadow compatibility must be 100% green")
    return count


def _strict_matched_report(report: Mapping[str, Any]) -> tuple[int, float, bool, bool]:
    rows = report.get("cases", report.get("records"))
    if not isinstance(rows, list) or not rows:
        raise ProfileSnapshotError("activation evidence matched A/B report must contain case records")
    count = _evidence_count(report, "matched_ab")
    if count != len(rows) or count < 12:
        raise ProfileSnapshotError("activation evidence requires at least 12 matched A/B cases")
    deltas: list[float] = []
    within_time = True
    failures: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ProfileSnapshotError(f"activation evidence matched A/B record {index} is invalid")
        case_id = str(row.get("case_id") or index)
        old_score, new_score = row.get("baseline_fidelity_score"), row.get("candidate_fidelity_score")
        old_time, new_time = row.get("baseline_active_seconds"), row.get("candidate_active_seconds")
        for value, name in ((old_score, "baseline_fidelity_score"), (new_score, "candidate_fidelity_score"), (old_time, "baseline_active_seconds"), (new_time, "candidate_active_seconds")):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ProfileSnapshotError(f"activation evidence matched A/B record {index}.{name} is required")
        if (
            not all(math.isfinite(float(value)) for value in (old_score, new_score, old_time, new_time))
            or not 0 <= float(old_score) <= 100
            or not 0 <= float(new_score) <= 100
            or float(old_time) <= 0
            or float(new_time) <= 0
        ):
            raise ProfileSnapshotError(f"activation evidence matched A/B record {index} has invalid score/time")
        delta = float(new_score) - float(old_score)
        overhead_seconds = float(new_time) - float(old_time)
        budget = min(120.0, float(old_time) * 0.10)
        expected_within = overhead_seconds <= budget
        row_delta = row.get("fidelity_delta")
        row_overhead = row.get("active_overhead_seconds")
        if isinstance(row_delta, bool) or not isinstance(row_delta, (int, float)):
            raise ProfileSnapshotError(f"activation evidence matched A/B record {index}.fidelity_delta is required")
        if isinstance(row_overhead, bool) or not isinstance(row_overhead, (int, float)):
            raise ProfileSnapshotError(f"activation evidence matched A/B record {index}.active_overhead_seconds is required")
        if not math.isfinite(float(row_delta)) or abs(float(row_delta) - delta) > 0.01:
            raise ProfileSnapshotError(f"activation evidence matched A/B record {index}.fidelity_delta is not recomputed")
        if not math.isfinite(float(row_overhead)) or abs(float(row_overhead) - overhead_seconds) > 0.01:
            raise ProfileSnapshotError(f"activation evidence matched A/B record {index} active overhead is not recomputed")
        if row.get("within_active_time_target") is not expected_within:
            raise ProfileSnapshotError(f"activation evidence matched A/B record {index} time target is not recomputed")
        old_failures = _metric_failures(row.get("baseline_compatibility_metrics"), f"baseline:{case_id}")
        new_failures = _metric_failures(row.get("candidate_compatibility_metrics"), f"candidate:{case_id}")
        failures.extend(old_failures + new_failures)
        deltas.append(delta)
        within_time = within_time and expected_within
    average_delta = sum(deltas) / len(deltas)
    expected_failures = sorted(set(failures))
    declared_failures = sorted(set(report.get("compatibility_failures") or []))
    if declared_failures != expected_failures:
        raise ProfileSnapshotError("activation evidence matched A/B compatibility failures are not recomputed")
    compatibility = not expected_failures
    report_average = report.get("average_fidelity_delta")
    if isinstance(report_average, bool) or not isinstance(report_average, (int, float)):
        raise ProfileSnapshotError("activation evidence matched A/B average fidelity gain is required")
    if not math.isfinite(float(report_average)) or abs(float(report_average) - average_delta) > 0.01:
        raise ProfileSnapshotError("activation evidence matched A/B average fidelity gain is not recomputed")
    if report.get("compatibility_pass") is not compatibility or report.get("within_active_time_target") is not within_time:
        raise ProfileSnapshotError("activation evidence matched A/B aggregate flags are not recomputed")
    meets = bool(compatibility and within_time and count >= 12 and average_delta >= 10.0)
    if report.get("meets_targets") is not meets:
        raise ProfileSnapshotError("activation evidence matched A/B target flag is not recomputed")
    if not meets:
        raise ProfileSnapshotError("activation evidence matched A/B report does not meet targets")
    return count, round(average_delta, 2), compatibility, within_time


def _strict_regression_report(report: Mapping[str, Any]) -> int:
    rows = report.get("cases", report.get("records"))
    if not isinstance(rows, list) or not rows:
        raise ProfileSnapshotError("activation evidence regression report must contain case records")
    count = _evidence_count(report, "regression")
    if count != len(rows) or count < 30 or count > 40:
        raise ProfileSnapshotError("activation evidence expanded regression requires 30-40 cases")
    hard_failures = ui_errors = claim_regressions = 0
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ProfileSnapshotError(f"activation evidence regression record {index} is invalid")
        passed = row.get("passed")
        if not isinstance(passed, bool):
            status = row.get("status")
            passed = status in {"passed", "pass", "complete", "regression_validated"}
        if passed is not True:
            raise ProfileSnapshotError(f"activation evidence regression record {index} did not pass")
        for field in ("hard_failures", "ui_errors", "claim_regressions"):
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProfileSnapshotError(f"activation evidence regression record {index}.{field} is required")
            if field == "hard_failures":
                hard_failures += value
            elif field == "ui_errors":
                ui_errors += value
            else:
                claim_regressions += value
    for field, value in (("hard_failures", hard_failures), ("ui_errors", ui_errors), ("claim_regressions", claim_regressions)):
        if report.get(field) != value:
            raise ProfileSnapshotError(f"activation evidence regression.{field} is not server-recomputed")
        if value != 0:
            raise ProfileSnapshotError(f"activation evidence regression.{field} must be zero")
    pass_flag = next((report.get(field) for field in ("passed", "regression_pass", "meets_targets", "compatibility_pass") if field in report), None)
    if pass_flag is not True:
        raise ProfileSnapshotError("activation evidence expanded regression must pass")
    return count


def validate_activation_evidence(
    evidence: Mapping[str, Any] | None,
    *,
    required: bool,
    receipt_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any] | None:
    """Validate deployment-quality gates with server-recomputed evidence.

    ``required=False`` retains the historical shadow/legacy compatibility path.
    Production/default activation is stricter: each complete report must be a
    byte-hashed immutable artifact whose receipt is resolved by the server, and
    all aggregate counts/flags are recomputed from the case records rather than
    trusted from caller-supplied booleans.
    """

    if evidence is None or evidence == {}:
        if required:
            raise ProfileSnapshotError("production high-fidelity activation evidence is required")
        return None
    if not isinstance(evidence, Mapping):
        raise ProfileSnapshotError("activation evidence must be an object")
    if not required:
        # Explicit shadow/legacy callers retain the old summary-only behavior.
        shadow = _evidence_section(evidence, "shadow", "shadow_report", "shadow_matrix")
        shadow_count = _evidence_count(shadow, "shadow")
        if shadow_count < 18 or shadow.get("status") not in {"shadow", "shadow_validated", "passed", "complete"}:
            raise ProfileSnapshotError("activation evidence shadow report is not passing")
        _zero_if_present(shadow, "shadow", "provider_calls", "user_approvals", "paid_tasks")
        if not _shadow_compatibility_pass(shadow):
            raise ProfileSnapshotError("activation evidence shadow compatibility must be 100% green")
        matched = _evidence_section(evidence, "matched_ab", "matched_ab_report", "ab_comparison")
        matched_count = _evidence_count(matched, "matched_ab")
        gain = matched.get("average_fidelity_delta")
        if matched_count < 12 or isinstance(gain, bool) or not isinstance(gain, (int, float)) or float(gain) < 10.0:
            raise ProfileSnapshotError("activation evidence matched A/B gate is not passing")
        if matched.get("compatibility_pass") is not True or matched.get("within_active_time_target") is not True or matched.get("meets_targets") is False:
            raise ProfileSnapshotError("activation evidence matched A/B compatibility/time gate is not passing")
        regression = _evidence_section(evidence, "regression", "regression_report", "expanded_regression")
        regression_count = _evidence_count(regression, "regression")
        if regression_count < 30 or regression_count > 40 or regression.get("passed") is not True:
            raise ProfileSnapshotError("activation evidence expanded regression gate is not passing")
        _zero_if_present(regression, "regression", "hard_failures", "ui_errors", "claim_regressions")
        return {
            "passed": True,
            "shadow_case_count": shadow_count,
            "matched_ab_case_count": matched_count,
            "average_fidelity_delta": round(float(gain), 2),
            "regression_case_count": regression_count,
        }

    if evidence.get("schema_version") != _ACTIVATION_EVIDENCE_SCHEMA:
        raise ProfileSnapshotError("production activation evidence schema version is missing or stale")
    shadow, shadow_sha, _shadow_receipt = _strict_report_envelope(
        evidence, ("shadow", "shadow_report", "shadow_matrix"), "shadow", receipt_verifier
    )
    matched, matched_sha, _matched_receipt = _strict_report_envelope(
        evidence, ("matched_ab", "matched_ab_report", "ab_comparison"), "matched_ab", receipt_verifier
    )
    regression, regression_sha, _regression_receipt = _strict_report_envelope(
        evidence, ("regression", "regression_report", "expanded_regression"), "regression", receipt_verifier
    )
    shadow_count = _strict_shadow_report(shadow)
    matched_count, average_delta, _compatibility, _within_time = _strict_matched_report(matched)
    regression_count = _strict_regression_report(regression)
    recomputed = {
        "shadow_case_count": shadow_count,
        "matched_ab_case_count": matched_count,
        "average_fidelity_delta": average_delta,
        "regression_case_count": regression_count,
        "report_sha256": {
            "shadow": shadow_sha,
            "matched_ab": matched_sha,
            "regression": regression_sha,
        },
    }
    if evidence.get("aggregate") != recomputed:
        raise ProfileSnapshotError("activation evidence aggregate is not server-recomputed")
    aggregate_sha = _require_digest(evidence.get("aggregate_sha256"), "activation evidence.aggregate_sha256")
    if aggregate_sha != _sha256(_canonical(recomputed)):
        raise ProfileSnapshotError("activation evidence aggregate digest is stale or tampered")
    return {
        "passed": True,
        "shadow_case_count": shadow_count,
        "matched_ab_case_count": matched_count,
        "average_fidelity_delta": average_delta,
        "regression_case_count": regression_count,
        "aggregate_sha256": aggregate_sha,
        "report_sha256": recomputed["report_sha256"],
    }


def _snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    payload = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload.pop("snapshot_sha256", None)
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        artifact.pop("sha256", None)
    return _sha256(_canonical(payload))


def build_profile_snapshot(
    profile_name: str,
    dependency_paths: Any,
    config: Mapping[str, Any] | None = None,
    *,
    activation_evidence_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Build immutable internal metadata for the selected profile.

    ``dependency_paths`` is accepted as a mapping of package name to a worker
    file path (or records containing ``path``, ``version`` and optional
    ``package_path``).  Only package-relative names and byte hashes are emitted;
    workstation paths never become deployment metadata.  Active/default builds
    must additionally provide the deployment-owned activation receipt verifier
    through ``activation_evidence_verifier``.
    """

    if profile_name != PROFILE_NAME:
        raise ProfileSnapshotError(f"unsupported profile: {profile_name!r}")
    if config is None:
        config = {}
    if not isinstance(config, Mapping):
        raise ProfileSnapshotError("profile config must be an object")
    activation_mode = config.get("activation_mode", config.get("mode", "shadow"))
    activation_mode = _require_non_empty_string(activation_mode, "activation_mode")
    if activation_mode not in _ACTIVATION_MODES:
        raise ProfileSnapshotError(
            "activation_mode must be one of: " + ", ".join(sorted(_ACTIVATION_MODES))
        )
    if activation_mode in _PRODUCTION_ACTIVATION_MODES and not bool(getattr(dependency_paths, "immutable", False)):
        raise ProfileSnapshotError(
            "active production profile requires an ImmutableBundleResolver; local/client dependency paths are rejected"
        )
    dependencies = [
        _dependency_record(name, value, config)
        for name, value in _normalise_dependencies(dependency_paths)
    ]
    activation_evidence = config.get("activation_evidence")
    validate_activation_evidence(
        activation_evidence,
        required=activation_mode in _PRODUCTION_ACTIVATION_MODES,
        receipt_verifier=activation_evidence_verifier,
    )
    created_at = config.get("created_at")
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        created_at = _require_non_empty_string(created_at, "created_at")
    artifact = _validate_artifact_metadata(config.get("artifact", {}))
    config_digest = _sha256(_canonical(dict(config)))
    profile_digest = _sha256(_canonical({"profile": PROFILE_NAME, "revision": 1}))
    schema_digest = _schema_digest()
    snapshot: dict[str, Any] = {
        "profile": PROFILE_NAME,
        "schema_version": SCHEMA_VERSION,
        "revision": 1,
        "profile_sha256": profile_digest,
        "schema_sha256": schema_digest,
        "config_digest": config_digest,
        "config_sha256": config_digest,
        "activation_mode": activation_mode,
        "created_at": created_at,
        "dependencies": dependencies,
        "parent_digests": _parent_digests(config),
        "artifact": artifact,
    }
    if activation_evidence is not None:
        snapshot["activation_evidence"] = json.loads(
            json.dumps(activation_evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    digest = _snapshot_digest(snapshot)
    snapshot["snapshot_sha256"] = digest
    artifact["sha256"] = digest
    return snapshot


def validate_profile_snapshot(
    snapshot: Mapping[str, Any] | None,
    current_dependency_paths: Any,
    *,
    activation_evidence_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
) -> None:
    """Fail closed for an active profile, while preserving legacy-run bypass.

    ``None`` and an empty mapping represent pre-profile runs and intentionally
    return without inspecting dependencies.  An active snapshot must match
    the installed dependency names, versions, package paths, and exact bytes;
    active/default snapshots also revalidate immutable activation report
    receipts through the injected server verifier.
    """

    if snapshot is None or snapshot == {}:
        return None
    if not isinstance(snapshot, Mapping):
        raise ProfileSnapshotError("profile snapshot must be an object")
    if snapshot.get("profile") != PROFILE_NAME:
        raise ProfileSnapshotError("profile snapshot name is not supported")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ProfileSnapshotError("profile snapshot schema version is stale")
    for field in ("profile_sha256", "schema_sha256", "config_digest", "config_sha256", "snapshot_sha256"):
        _require_digest(snapshot.get(field), field)
    if snapshot.get("config_digest") != snapshot.get("config_sha256"):
        raise ProfileSnapshotError("config digest aliases do not match")
    expected_profile_digest = _sha256(_canonical({"profile": PROFILE_NAME, "revision": 1}))
    if snapshot.get("profile_sha256") != expected_profile_digest:
        raise ProfileSnapshotError("profile digest does not match the selected profile")
    if snapshot.get("schema_sha256") != _schema_digest():
        raise ProfileSnapshotError("profile schema dependency is stale")
    _require_non_empty_string(snapshot.get("activation_mode"), "activation_mode")
    activation_mode = str(snapshot.get("activation_mode"))
    if activation_mode not in _ACTIVATION_MODES:
        raise ProfileSnapshotError(
            "activation_mode must be one of: " + ", ".join(sorted(_ACTIVATION_MODES))
        )
    validate_activation_evidence(
        snapshot.get("activation_evidence"),
        required=activation_mode in _PRODUCTION_ACTIVATION_MODES,
        receipt_verifier=activation_evidence_verifier,
    )
    _require_non_empty_string(snapshot.get("created_at"), "created_at")
    expected_dependencies = snapshot.get("dependencies")
    if not isinstance(expected_dependencies, list) or not expected_dependencies:
        raise ProfileSnapshotError("profile snapshot has no dependencies")
    expected_by_name: dict[str, Mapping[str, Any]] = {}
    for item in expected_dependencies:
        if not isinstance(item, Mapping):
            raise ProfileSnapshotError("profile dependency records must be objects")
        name = _require_non_empty_string(item.get("name"), "dependency.name")
        if name in expected_by_name:
            raise ProfileSnapshotError(f"duplicate dependency: {name}")
        _require_non_empty_string(item.get("version"), f"dependency {name} version")
        _require_digest(item.get("sha256"), f"dependency {name} sha256")
        package_path = item.get("package_path")
        if (
            not isinstance(package_path, str)
            or _PACKAGE_PATH.fullmatch(package_path) is None
            or any(part in {"", ".", ".."} for part in package_path.split("/"))
        ):
            raise ProfileSnapshotError(f"dependency {name} package_path is invalid")
        expected_by_name[name] = item
    artifact = snapshot.get("artifact") or {}
    _validate_artifact_metadata(artifact)
    if artifact.get("sha256") != snapshot.get("snapshot_sha256"):
        raise ProfileSnapshotError("artifact hash does not match the profile snapshot")
    parent_digests = snapshot.get("parent_digests")
    if not isinstance(parent_digests, Mapping):
        raise ProfileSnapshotError("parent_digests must be an object")
    for parent_name, parent_digest in parent_digests.items():
        _require_digest(parent_digest, f"parent_digests.{parent_name}")
    if _snapshot_digest(snapshot) != snapshot.get("snapshot_sha256"):
        raise ProfileSnapshotError("profile snapshot digest is stale or tampered")
    current = [
        _dependency_record(name, value, {}, expected=expected_by_name.get(name))
        for name, value in _normalise_dependencies(current_dependency_paths)
    ]
    current_by_name = {item["name"]: item for item in current}
    if set(current_by_name) != set(expected_by_name):
        raise ProfileSnapshotError("installed profile dependencies do not match the snapshot")
    for name, expected in expected_by_name.items():
        actual = current_by_name[name]
        for field in ("version", "sha256", "package_path"):
            if actual[field] != expected[field]:
                raise ProfileSnapshotError(f"dependency {name} {field} does not match the profile snapshot")
    return None


__all__ = [
    "PROFILE_NAME",
    "SCHEMA_VERSION",
    "ProfileSnapshotError",
    "build_profile_snapshot",
    "validate_activation_evidence",
    "validate_profile_snapshot",
]
