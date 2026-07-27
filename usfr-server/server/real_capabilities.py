"""Reference-media capability adapters used by deployed workers.

The canonical Skill intentionally keeps the capability ports provider-neutral.
This module supplies executable server adapters for the media ports that cannot
be satisfied by a metadata sidecar alone:

* :class:`FfmpegDynamicsAnalyzer` probes the complete source and derives
  frame-zero-to-end cuts from decoder evidence.  A deployment may inject a
  VLM/vision callback to enrich the generic motion facts; the callback is
  never allowed to change timing coverage.
* :class:`WhisperAsrTranscriber` extracts a worker-local WAV and uses a pinned
  Whisper model or an evidence-bound ASR adapter. It emits word/segment timing,
  explicit silence windows, and per-invocation evidence receipts.
* The injected audio-event classifier contributes evidence-bound Foley,
  ambience, music, and meaningful-silence events without shared mutable state.
* :class:`DeterministicUiRenderer` renders target-owned UI bytes and verifies
  OCR/layout through an injected OCR backend (or a configured Tesseract
  executable).  It fails closed when strict evidence is unavailable.

All media paths are lease-local.  Callers must provide a
``WorkerStageContext``; workstation paths and client URLs are not accepted as
authority.  The adapters are deliberately small and deterministic so a
service deployment can replace the model backends without changing RunState,
the seven slots, or the public stage plan.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from array import array
import hashlib
import importlib.util
import io
import inspect
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

from .audio_backends import (
    AudioBackendUnavailable,
    validate_final_audio_qc,
    validate_source_audio_performance_qc,
)
from .audio_mixer import (
    AudioMixerError,
    EvidenceBoundAudioMixer,
    validate_evidence_bound_mix_receipt_media,
    validate_evidence_bound_mix_receipts,
)
from .audio_route_guard import validate_audio_route_contract
from .errors import ReplicationError
from .overlay_renderer import DeterministicOverlayRenderer, OverlayRenderError


class CapabilityUnavailable(ReplicationError):
    """A real production capability is missing or cannot produce evidence."""

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            "CAPABILITY_UNAVAILABLE",
            message,
            category="capability",
            retryable=True,
            user_action_required=True,
            details=dict(details or {}),
            http_status=503,
        )


def _active_high_fidelity(context: Any) -> bool:
    profile = getattr(context, "profile_snapshot", None)
    if not isinstance(profile, Mapping) or profile.get("profile") != "high_fidelity_hybrid_v1":
        return False
    return str(profile.get("activation_mode") or "active").lower() in {
        "active",
        "production",
        "default",
    }


def _has_generated_ui_region(context: Any) -> bool:
    return any(
        str(item.get("region_type") or item.get("kind") or "").lower()
        in {"generated_ui_demo", "generated_ui"}
        for item in (getattr(context, "timeline_regions", ()) or ())
        if isinstance(item, Mapping)
    )


def _load_high_fidelity_dynamics_validator() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "bundled-skills"
        / "analyze-reference-video-dynamics"
        / "scripts"
        / "validate_high_fidelity_extension.py"
    )
    spec = importlib.util.spec_from_file_location("usfr_validate_high_fidelity_dynamics", path)
    if spec is None or spec.loader is None:
        raise CapabilityUnavailable("packaged high-fidelity dynamics validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_adaptive_evidence_plan_module() -> Any:
    """Load the packaged single-pass evidence-plan contract by bundle path."""

    path = (
        Path(__file__).resolve().parents[1]
        / "bundled-skills"
        / "analyze-reference-video-dynamics"
        / "scripts"
        / "adaptive_evidence_plan.py"
    )
    spec = importlib.util.spec_from_file_location("usfr_adaptive_evidence_plan", path)
    if spec is None or spec.loader is None:
        raise CapabilityUnavailable("packaged adaptive evidence-plan module is unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise CapabilityUnavailable(
            "packaged adaptive evidence-plan module failed to load",
            details={"reason": str(exc)},
        ) from exc
    return module


def _build_adaptive_evidence_plan(
    probe: Mapping[str, Any],
    *,
    source_sha256: str,
    scene_cut_candidates_us: Sequence[int],
) -> dict[str, Any]:
    """Bridge the server probe shape into the packaged plan contract.

    The returned value contains only source hashes, media metadata, timing, and
    evidence instructions.  It never persists the lease-local media path.
    """

    probe_contract = {
        "contract": "reference-video-probe",
        "contract_version": 1,
        "duration_us": int(probe.get("duration_us") or 0),
        "source_width": int(probe.get("width") or probe.get("source_width") or 0),
        "source_height": int(probe.get("height") or probe.get("source_height") or 0),
        "fps_num": int(probe.get("fps_num") or 0),
        "fps_den": int(probe.get("fps_den") or 0),
        "scene_cut_candidates_us": [int(value) for value in scene_cut_candidates_us],
        "audio_streams": list(probe.get("audio_streams") or []),
    }
    module = _load_adaptive_evidence_plan_module()
    try:
        plan = module.build_evidence_plan(
            probe_contract,
            source_sha256=source_sha256,
            audio_required=bool(probe.get("has_audio")),
        )
        module.validate_evidence_plan(plan)
    except Exception as exc:
        raise CapabilityUnavailable(
            "adaptive evidence plan could not be built from the verified source probe",
            details={"reason": str(exc)},
        ) from exc
    return dict(plan)


def _accepts_keyword(callback: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return False
    return keyword in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _load_high_fidelity_qc_module() -> Any:
    """Load the packaged weighted high-fidelity QC implementation.

    The QC helper lives under ``scripts/`` so it can also be executed as a
    standalone validator.  Loading it from the bundle keeps the server
    adapter independent from the worker's current working directory and
    makes the exact implementation bytes part of the deployed Skill bundle.
    """

    path = Path(__file__).resolve().parents[1] / "scripts" / "high_fidelity_qc.py"
    spec = importlib.util.spec_from_file_location("usfr_high_fidelity_qc", path)
    if spec is None or spec.loader is None:
        raise CapabilityUnavailable("packaged high-fidelity QC module is unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise CapabilityUnavailable(
            "packaged high-fidelity QC module failed to load",
            details={"reason": str(exc)},
        ) from exc
    return module


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _embedded_timeline_overlay_contract(
    regions: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None, str | None]:
    """Recover immutable overlay evidence carried by Stage-4 region rows."""

    contracts: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    for region in regions:
        metadata = region.get("metadata") if isinstance(region.get("metadata"), Mapping) else region
        contract = metadata.get("source_overlay_contract") if isinstance(metadata, Mapping) else None
        if isinstance(contract, Mapping):
            contract_copy = dict(contract)
            contract_sha = _sha256_bytes(
                json.dumps(contract_copy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            declared_sha = str(metadata.get("source_overlay_contract_sha256") or "").lower() if isinstance(metadata, Mapping) else ""
            if declared_sha and declared_sha != contract_sha:
                raise ReplicationError(
                    "OVERLAY_CONTRACT_INVALID",
                    "embedded source_overlay_contract SHA does not match its bytes",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            contracts.append(contract_copy)
        mapping = metadata.get("overlay_render_mapping") if isinstance(metadata, Mapping) else None
        if isinstance(mapping, Mapping):
            mapping_copy = dict(mapping)
            mapping_sha = _sha256_bytes(
                json.dumps(mapping_copy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            declared_mapping_sha = str(metadata.get("overlay_render_mapping_sha256") or "").lower() if isinstance(metadata, Mapping) else ""
            if declared_mapping_sha and declared_mapping_sha != mapping_sha:
                raise ReplicationError(
                    "OVERLAY_RENDER_MAPPING_INVALID",
                    "embedded overlay_render_mapping SHA does not match its bytes",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            mappings.append(mapping_copy)

    def unique(values: list[dict[str, Any]], label: str) -> tuple[dict[str, Any] | None, str | None]:
        if not values:
            return None, None
        digests = [
            _sha256_bytes(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            for value in values
        ]
        if any(digest != digests[0] for digest in digests[1:]):
            raise ReplicationError(
                "OVERLAY_CONTRACT_MISMATCH" if label == "source_overlay_contract" else "OVERLAY_RENDER_MAPPING_INVALID",
                f"{label} differs across timeline region carriers",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )
        return values[0], digests[0]

    contract, contract_sha = unique(contracts, "source_overlay_contract")
    mapping, mapping_sha = unique(mappings, "overlay_render_mapping")
    return contract, contract_sha, mapping, mapping_sha


def _required_overlay_payloads(
    regions: Sequence[Mapping[str, Any]],
    source_overlay_contract: Mapping[str, Any] | None,
    overlay_render_mapping: Mapping[str, Any] | None,
    *,
    source_overlay_contract_sha256: str | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Validate the canonical mapping and return required payload digests."""

    if not isinstance(source_overlay_contract, Mapping):
        return {}
    required: dict[str, set[str]] = {}
    for cut in source_overlay_contract.get("cuts", []):
        if not isinstance(cut, Mapping):
            continue
        try:
            cut_start = int(cut.get("start_us"))
            cut_end = int(cut.get("end_us"))
        except (TypeError, ValueError):
            continue
        for overlay in cut.get("source_overlays", []):
            if not isinstance(overlay, Mapping):
                continue
            overlay_id = str(overlay.get("overlay_id") or "").strip()
            if not overlay_id:
                continue
            for region in regions:
                kind = str(region.get("region_type") or region.get("kind") or "").lower()
                if kind not in {"generated", "generated_ui", "generated_ui_demo"}:
                    continue
                try:
                    start = int(region.get("source_start_us", region.get("start_us")))
                    end = int(region.get("source_end_us", region.get("end_us")))
                except (TypeError, ValueError):
                    continue
                if end > cut_start and start < cut_end:
                    region_id = str(region.get("region_id") or "").strip()
                    if region_id:
                        required.setdefault(region_id, set()).add(overlay_id)
    if not required:
        return {}
    if not isinstance(overlay_render_mapping, Mapping):
        raise ReplicationError(
            "OVERLAY_RENDER_MAPPING_REQUIRED",
            "OVERLAY_RENDER_MAPPING_REQUIRED: generated semantic overlays require an overlay_render_mapping",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    if overlay_render_mapping.get("contract") != "target-overlay-render-mapping" or overlay_render_mapping.get("contract_version") != 1:
        raise ReplicationError(
            "OVERLAY_RENDER_MAPPING_INVALID",
            "OVERLAY_RENDER_MAPPING_INVALID: unsupported overlay_render_mapping contract",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    if str(overlay_render_mapping.get("source_overlay_contract_sha256") or "").lower() != str(source_overlay_contract_sha256 or "").lower():
        raise ReplicationError(
            "OVERLAY_RENDER_MAPPING_INVALID",
            "OVERLAY_RENDER_MAPPING_INVALID: source_overlay_contract_sha256 does not match",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    rows = overlay_render_mapping.get("regions")
    if not isinstance(rows, list):
        raise ReplicationError(
            "OVERLAY_RENDER_MAPPING_INVALID",
            "OVERLAY_RENDER_MAPPING_INVALID: regions must be an array",
            category="timeline",
            user_action_required=True,
            http_status=422,
        )
    rows_by_region = {
        str(row.get("region_id") or "").strip(): row
        for row in rows
        if isinstance(row, Mapping) and str(row.get("region_id") or "").strip()
    }
    payloads: dict[tuple[str, str], dict[str, Any]] = {}
    for region_id, overlay_ids in required.items():
        row = rows_by_region.get(region_id)
        if not isinstance(row, Mapping):
            raise ReplicationError(
                "OVERLAY_RENDER_MAPPING_REQUIRED",
                f"OVERLAY_RENDER_MAPPING_REQUIRED: region {region_id} has no mapping row",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )
        entries = row.get("overlays")
        if not isinstance(entries, list):
            raise ReplicationError(
                "OVERLAY_RENDER_MAPPING_INVALID",
                f"OVERLAY_RENDER_MAPPING_INVALID: region {region_id} overlays must be an array",
                category="timeline",
                user_action_required=True,
                http_status=422,
            )
        entries_by_id = {
            str(entry.get("overlay_id") or "").strip(): entry
            for entry in entries
            if isinstance(entry, Mapping) and str(entry.get("overlay_id") or "").strip()
        }
        for overlay_id in overlay_ids:
            entry = entries_by_id.get(overlay_id)
            if not isinstance(entry, Mapping) or entry.get("validated") is not True:
                raise ReplicationError(
                    "OVERLAY_RENDER_MAPPING_INVALID",
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} is not validated",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            mode = str(entry.get("render_mode") or "").lower()
            if mode not in {"deterministic_text", "deterministic_asset"}:
                raise ReplicationError(
                    "OVERLAY_RENDER_MAPPING_INVALID",
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} has no deterministic render mode",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            payload_sha = str(entry.get("payload_sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", payload_sha):
                raise ReplicationError(
                    "OVERLAY_RENDER_MAPPING_INVALID",
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} payload SHA is invalid",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            if isinstance(entry.get("payload"), Mapping) and _canonical_sha256(entry["payload"]) != payload_sha:
                raise ReplicationError(
                    "OVERLAY_RENDER_MAPPING_INVALID",
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} payload SHA does not match payload bytes",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            text_payload = entry.get("text")
            if not str(text_payload or "").strip() and isinstance(entry.get("payload"), Mapping):
                text_payload = entry["payload"].get("text")
            if mode == "deterministic_text" and not str(text_payload or "").strip():
                raise ReplicationError(
                    "OVERLAY_RENDER_MAPPING_INVALID",
                    f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} text payload is empty",
                    category="timeline",
                    user_action_required=True,
                    http_status=422,
                )
            if mode == "deterministic_asset":
                asset_sha = str(entry.get("asset_sha256") or "").lower()
                if not asset_sha and isinstance(entry.get("payload"), Mapping):
                    asset_sha = str(entry["payload"].get("asset_sha256") or "").lower()
                if not re.fullmatch(r"[0-9a-f]{64}", asset_sha):
                    raise ReplicationError(
                        "OVERLAY_RENDER_MAPPING_INVALID",
                        f"OVERLAY_RENDER_MAPPING_INVALID: {region_id}/{overlay_id} asset SHA is invalid",
                        category="timeline",
                        user_action_required=True,
                        http_status=422,
                    )
            payload = (
                entry.get("payload")
                if isinstance(entry.get("payload"), Mapping)
                else {}
            )
            payloads[(region_id, overlay_id)] = {
                "payload_sha256": payload_sha,
                "render_mode": mode,
                "verification_required": payload.get("verification_required") is True,
            }
    return payloads


def _validate_overlay_render_receipts(
    receipts: Any,
    required_payloads: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    source_overlay_contract_sha256: str,
    overlay_render_mapping_sha256: str | None,
    output_sha256: str,
) -> list[dict[str, Any]]:
    if not isinstance(receipts, list):
        raise ReplicationError(
            "OVERLAY_RENDER_RECEIPT_REQUIRED",
            "OVERLAY_RENDER_RECEIPT_REQUIRED: active semantic overlays require renderer receipts",
            category="quality",
            user_action_required=True,
            http_status=422,
        )
    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        key = (str(receipt.get("region_id") or "").strip(), str(receipt.get("overlay_id") or "").strip())
        if key not in required_payloads or key in seen:
            continue
        if str(receipt.get("source_overlay_contract_sha256") or "").lower() != source_overlay_contract_sha256.lower():
            continue
        if overlay_render_mapping_sha256 and str(receipt.get("overlay_render_mapping_sha256") or "").lower() != overlay_render_mapping_sha256.lower():
            continue
        requirement = required_payloads[key]
        if str(receipt.get("payload_sha256") or "").lower() != str(
            requirement.get("payload_sha256") or ""
        ).lower():
            continue
        if str(receipt.get("output_sha256") or "").lower() != output_sha256.lower():
            continue
        if not isinstance(receipt.get("frame_windows"), list) or not receipt.get("frame_windows"):
            continue
        if requirement.get("verification_required") is True:
            if str(receipt.get("final_output_sha256") or "").lower() != output_sha256.lower():
                continue
            if receipt.get("ocr_match_percent") != 100 or receipt.get("layout_match_percent") != 100:
                continue
            frame_digests = receipt.get("frame_digests")
            if (
                not isinstance(frame_digests, list)
                or not frame_digests
                or any(
                    not re.fullmatch(r"[0-9a-f]{64}", str(item or ""))
                    for item in frame_digests
                )
            ):
                continue
        seen.add(key)
        normalized.append(dict(receipt))
    if seen != set(required_payloads):
        missing = sorted(set(required_payloads) - seen)
        raise ReplicationError(
            "OVERLAY_RENDER_RECEIPT_REQUIRED",
            f"OVERLAY_RENDER_RECEIPT_REQUIRED: renderer did not prove all semantic overlays were rendered ({missing})",
            category="quality",
            user_action_required=True,
            http_status=422,
        )
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CapabilityUnavailable("could not read pinned model artifact", details={"path": str(path)}) from exc
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    """Hash JSON evidence without allowing caller ordering to change it."""

    return _sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _context_parent_digests(context: Any) -> dict[str, str]:
    """Bind a stage publication to immutable upstream evidence.

    The worker repository requires every high-fidelity artifact to carry at
    least one parent contract digest.  Prefer explicit/profile and prior
    artifact digests, then fall back to the sanitized input-artifact manifest;
    never hash or persist a worker-local media path.
    """

    result: dict[str, str] = {}
    profile = getattr(context, "profile_snapshot", None)
    if isinstance(profile, Mapping):
        parents = profile.get("parent_digests")
        if isinstance(parents, Mapping):
            for name, value in parents.items():
                digest = str(value or "").lower()
                if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
                    result[str(name)] = digest
    for artifact in getattr(context, "artifacts", ()) or ():
        if not isinstance(artifact, Mapping):
            continue
        kind = str(artifact.get("kind") or "").strip()
        digest = str(artifact.get("sha256") or "").lower()
        if kind and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
            result.setdefault(f"{kind}_sha256", digest)
    if not result:
        try:
            inputs = list(getattr(context, "input_artifacts"))
        except Exception:
            inputs = []
        result["input_manifest_sha256"] = _sha256_bytes(
            json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
    return result


def _identity(
    capability: str,
    implementation: str,
    version: str,
    sha256: str | None,
    *,
    require_explicit_digest: bool = False,
) -> dict[str, str]:
    if require_explicit_digest and not sha256:
        raise ValueError(f"{capability} requires an explicit deployment byte SHA-256")
    digest = (sha256 or hashlib.sha256(f"{implementation}@{version}".encode("utf-8")).hexdigest()).lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{capability} sha256 must be a lowercase SHA-256")
    return {
        "capability": capability,
        "implementation": implementation,
        "version": version,
        "sha256": digest,
    }


def _evidence_backend_identity(backend: Any, *, method: str, label: str) -> dict[str, Any]:
    """Validate a production model backend without coupling to one provider."""

    operation = getattr(backend, method, None)
    identity_method = getattr(backend, "capability_identity", None)
    if not callable(operation) or not callable(identity_method):
        raise ValueError(f"production requires an evidence-bound {label} backend with {method}() and capability_identity()")
    identity = identity_method()
    if not isinstance(identity, Mapping):
        raise ValueError(f"production {label} backend capability_identity() must return an object")
    model_id = str(identity.get("model_id") or "").strip()
    model_sha256 = str(identity.get("model_sha256") or "")
    binding = str(identity.get("evidence_binding") or "")
    implementation = str(identity.get("implementation") or "").strip()
    if not model_id or not implementation:
        raise ValueError(f"production {label} backend must identify its implementation and model")
    if len(model_sha256) != 64 or any(char not in "0123456789abcdef" for char in model_sha256):
        raise ValueError(f"production {label} backend model_sha256 must be lowercase SHA-256")
    if not binding.startswith("usfr-") or not binding.endswith("/v1"):
        raise ValueError(f"production {label} backend must declare a versioned USFR evidence binding")
    return {
        "implementation": implementation,
        "version": str(identity.get("version") or ""),
        "model_id": model_id,
        "model_sha256": model_sha256,
        "evidence_binding": binding,
        "transport": str(identity.get("transport") or ""),
    }


def _component_identity(backend: Any, *, label: str) -> dict[str, Any]:
    """Read an immutable identity for a nested renderer/compositor component."""

    identity_method = getattr(backend, "capability_identity", None)
    if not callable(identity_method):
        raise ValueError(f"production {label} requires capability_identity()")
    identity = identity_method()
    if not isinstance(identity, Mapping):
        raise ValueError(f"production {label} capability_identity() must return an object")
    implementation = str(identity.get("implementation") or "").strip()
    version = str(identity.get("version") or "").strip()
    sha256 = str(identity.get("sha256") or "")
    if not implementation or not version:
        raise ValueError(f"production {label} identity must include implementation and version")
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise ValueError(f"production {label} identity sha256 must be lowercase SHA-256")
    return {"implementation": implementation, "version": version, "sha256": sha256}


def _evidence_bound_mixer_identity(renderer: Any) -> dict[str, Any] | None:
    from .timeline_renderer import BundledTimelineRenderer

    if type(renderer) is not BundledTimelineRenderer:
        return None
    mixer = getattr(renderer, "audio_mixer", None)
    if type(mixer) is not EvidenceBoundAudioMixer or not bool(
        getattr(mixer, "supports_evidence_bound_mix", False)
    ):
        return None
    identity_method = getattr(mixer, "capability_identity", None)
    if not callable(identity_method):
        return None
    identity = identity_method()
    if not isinstance(identity, Mapping):
        return None
    normalized = dict(identity)
    if (
        normalized.get("capability_kind") != "audio_mixer"
        or normalized.get("audio_policy") != "evidence_bound_mix"
        or normalized.get("implementation")
        != "server.audio_mixer:EvidenceBoundAudioMixer"
        or normalized.get("version") != "1.0.0"
        or not _is_sha256(normalized.get("sha256"))
    ):
        return None
    return normalized


def _composite_identity(identity: Mapping[str, Any], dependencies: Mapping[str, Any]) -> dict[str, Any]:
    """Bind nested model/renderer identities into the manifest-visible SHA."""

    base = dict(identity)
    dependencies_payload = json.loads(
        json.dumps(dict(dependencies), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    binding = {
        "base_adapter_sha256": str(base.get("sha256") or ""),
        "dependencies": dependencies_payload,
    }
    base["sha256"] = _sha256_bytes(
        json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return base


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _validate_bound_model_receipt(
    evidence: Any,
    *,
    identity: Mapping[str, Any],
    input_sha256: str,
    payload: Sequence[Mapping[str, Any]],
    payload_digest_field: str,
    label: str,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise CapabilityUnavailable(f"production {label} backend returned no evidence receipt")
    binding = str(identity.get("evidence_binding") or "")
    if str(evidence.get("evidence_binding") or evidence.get("schema_version") or "") != binding:
        raise CapabilityUnavailable(f"production {label} evidence binding does not match the backend identity")
    if str(evidence.get("input_sha256") or "") != input_sha256:
        raise CapabilityUnavailable(f"production {label} evidence is not bound to the extracted WAV SHA")
    if str(evidence.get("model_id") or "") != str(identity.get("model_id") or "") or str(evidence.get("model_sha256") or "") != str(identity.get("model_sha256") or ""):
        raise CapabilityUnavailable(f"production {label} evidence model identity does not match the bound backend")
    for field in ("request_sha256", "response_sha256", payload_digest_field):
        if not _is_sha256(evidence.get(field)):
            raise CapabilityUnavailable(f"production {label} evidence requires {field}")
    expected_payload_sha = _sha256_bytes(
        json.dumps(list(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if expected_payload_sha != str(evidence.get(payload_digest_field) or ""):
        raise CapabilityUnavailable(f"production {label} payload does not match {payload_digest_field}")
    return dict(evidence)


def _executable(name: str, configured: str | None = None) -> str:
    candidate = configured or os.getenv(f"{name.upper()}_EXE")
    if candidate and Path(candidate).is_file():
        return str(Path(candidate))
    found = shutil.which(name)
    if found:
        return found
    raise CapabilityUnavailable(f"{name} executable is not installed", details={"executable": name})


def _run(command: Sequence[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CapabilityUnavailable("media capability command timed out", details={"command": list(command)[:2]}) from exc


def _stream_duration_seconds(stream: Mapping[str, Any]) -> float:
    """Return a stream-owned duration without borrowing the container clock."""

    try:
        duration = float(stream.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration > 0:
        return duration
    try:
        duration_ts = float(stream.get("duration_ts") or 0.0)
    except (TypeError, ValueError):
        duration_ts = 0.0
    time_base = str(stream.get("time_base") or "")
    if duration_ts > 0 and "/" in time_base:
        numerator, denominator = time_base.split("/", 1)
        try:
            seconds = duration_ts * float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            seconds = 0.0
        if seconds > 0:
            return seconds
    try:
        frame_count = float(stream.get("nb_frames") or 0.0)
    except (TypeError, ValueError):
        frame_count = 0.0
    frame_rate_raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    try:
        if "/" in str(frame_rate_raw or ""):
            rate_num, rate_den = str(frame_rate_raw).split("/", 1)
            frame_rate = float(rate_num) / float(rate_den)
        else:
            frame_rate = float(frame_rate_raw or 0.0)
    except (TypeError, ValueError, ZeroDivisionError):
        frame_rate = 0.0
    if frame_count > 0 and frame_rate > 0:
        return frame_count / frame_rate
    return 0.0


def _stream_start_seconds(stream: Mapping[str, Any]) -> float:
    """Return the stream timeline origin without borrowing container time."""

    try:
        value = float(stream.get("start_time") or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    if math.isfinite(value):
        return value
    return 0.0


def _probe(path: Path, *, ffprobe_bin: str | None = None) -> dict[str, Any]:
    ffprobe = _executable("ffprobe", ffprobe_bin)
    result = _run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if result.returncode != 0:
        raise CapabilityUnavailable("ffprobe could not inspect source media", details={"stderr": result.stderr[-1000:]})
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CapabilityUnavailable("ffprobe returned malformed JSON") from exc
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not isinstance(video, Mapping):
        raise CapabilityUnavailable("source media has no video stream")
    video_duration = _stream_duration_seconds(video)
    duration_us = int(round(video_duration * 1_000_000))
    if duration_us <= 0:
        raise CapabilityUnavailable("source video stream duration is unavailable")
    fps_raw = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    try:
        if "/" in str(fps_raw):
            n, d = str(fps_raw).split("/", 1)
            fps = float(n) / float(d)
        else:
            fps = float(fps_raw)
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 0.0
    if fps <= 0:
        fps = 30.0
    audio_durations = [
        _stream_duration_seconds(item)
        for item in streams
        if item.get("codec_type") == "audio"
    ]
    return {
        "duration_us": duration_us,
        "video_duration_us": duration_us,
        "video_start_time_us": int(round(_stream_start_seconds(video) * 1_000_000)),
        "audio_duration_us": max(
            [
                int(round(value * 1_000_000))
                for value in audio_durations
                if value > 0
            ]
            or [0]
        ),
        "audio_start_time_us": int(
            round(
                _stream_start_seconds(
                    next(
                        (item for item in streams if item.get("codec_type") == "audio"),
                        {},
                    )
                )
                * 1_000_000
            )
        ),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "fps_num": int(str(fps_raw).split("/", 1)[0]) if str(fps_raw).split("/", 1)[0].isdigit() else round(fps),
        "fps_den": int(str(fps_raw).split("/", 1)[1]) if "/" in str(fps_raw) and str(fps_raw).split("/", 1)[1].isdigit() else 1,
        "video_codec": str(video.get("codec_name") or ""),
        "has_audio": any(item.get("codec_type") == "audio" for item in streams),
        "audio_streams": [dict(item) for item in streams if item.get("codec_type") == "audio"],
    }


_BLACK_DETECT_RE = re.compile(
    r"black_start:(?P<start>-?\d+(?:\.\d+)?)\s+"
    r"black_end:(?P<end>-?\d+(?:\.\d+)?)"
)

_FREEZE_START_RE = re.compile(
    r"freeze_start\s*:\s*(?P<start>-?\d+(?:\.\d+)?)"
)
_FREEZE_END_RE = re.compile(
    r"freeze_end\s*:\s*(?P<end>-?\d+(?:\.\d+)?)"
)
_EBUR128_INTEGRATED_RE = re.compile(
    r"Integrated loudness:\s*\n\s*I:\s*(?P<value>-?(?:\d+(?:\.\d+)?|inf))\s+LUFS",
    re.IGNORECASE,
)
_EBUR128_TRUE_PEAK_RE = re.compile(
    r"True peak:\s*\n\s*Peak:\s*(?P<value>-?(?:\d+(?:\.\d+)?|inf))\s+dBFS",
    re.IGNORECASE,
)


def _parse_black_detect_intervals(stderr: str) -> tuple[tuple[float, float], ...]:
    """Parse FFmpeg blackdetect intervals without treating them as semantic shots."""

    intervals: list[tuple[float, float]] = []
    for match in _BLACK_DETECT_RE.finditer(stderr or ""):
        try:
            start = max(0.0, float(match.group("start")))
            end = max(start, float(match.group("end")))
        except (TypeError, ValueError):
            continue
        intervals.append((start, end))
    return tuple(intervals)


def _parse_freeze_detect_intervals(
    stderr: str,
    *,
    duration: float | None = None,
) -> tuple[tuple[float, float], ...]:
    """Parse paired FFmpeg freezedetect start/end records."""

    intervals: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in (stderr or "").splitlines():
        start_match = _FREEZE_START_RE.search(line)
        if start_match is not None:
            try:
                pending_start = max(0.0, float(start_match.group("start")))
            except (TypeError, ValueError):
                pending_start = None
            continue
        end_match = _FREEZE_END_RE.search(line)
        if end_match is None or pending_start is None:
            continue
        try:
            end = max(pending_start, float(end_match.group("end")))
        except (TypeError, ValueError):
            pending_start = None
            continue
        intervals.append((pending_start, end))
        pending_start = None
    if pending_start is not None and duration is not None and duration > pending_start:
        intervals.append((pending_start, float(duration)))
    return tuple(intervals)


def _parse_audio_db(value: str) -> float:
    normalized = str(value or "").strip().lower()
    if normalized in {"inf", "+inf"}:
        return float("inf")
    if normalized == "-inf":
        return float("-inf")
    return float(normalized)


def _audio_db_report_value(value: float) -> tuple[float | None, str]:
    """Return a strict-JSON value plus an explicit measurement state."""

    if math.isnan(value):
        return None, "not_a_number"
    if value == float("inf"):
        return None, "positive_infinity"
    if value == float("-inf"):
        return None, "negative_infinity"
    return float(value), "finite"


def _line_contract_requires_audio(value: Any) -> bool:
    if isinstance(value, Mapping):
        if str(value.get("speech_mode") or "").strip().lower() == "none":
            return False
        for key in ("lines", "line_contracts", "contracts"):
            nested = value.get(key)
            if nested is not None and _line_contract_requires_audio(nested):
                return True
        if value.get("line_id"):
            return True
        text = value.get("text")
        if isinstance(text, Mapping):
            text = text.get("exact") or text.get("normalized")
        return bool(str(text or "").strip() and value.get("speaker"))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_line_contract_requires_audio(item) for item in value)
    return False


def _audio_plan_requires_stream(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("audio_required") is True:
        return True
    if _line_contract_requires_audio(value):
        return True
    for key in ("layers", "buses", "tracks"):
        items = value.get(key)
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            mode = str(item.get("mode") or item.get("policy") or "").strip().lower()
            if mode not in {"", "none", "remove", "omit", "silence"}:
                return True
    return False


def _audio_contract_requires_stream(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    nested = value.get("audio_contract")
    if isinstance(nested, Mapping):
        value = nested
    segments = value.get("segments")
    if isinstance(segments, Sequence) and not isinstance(
        segments, (str, bytes, bytearray)
    ):
        if any(isinstance(item, Mapping) for item in segments):
            return True
    for key in ("events", "audio_events", "source_events"):
        events = value.get(key)
        if not isinstance(events, Sequence) or isinstance(
            events, (str, bytes, bytearray)
        ):
            continue
        for item in events:
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("kind") or "").strip().lower().replace("-", "_")
            if kind not in {"", "silence", "meaningful_silence"}:
                return True
    return value.get("has_audio") is True


def _timeline_manifest_requires_audio(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("audio_required") is True:
        return True
    for key in ("exact_line_contract", "line_contracts"):
        if _line_contract_requires_audio(value.get(key)):
            return True
    return _audio_plan_requires_stream(value.get("audio_layer_plan"))


def _final_audio_stream_required(
    context: Any,
    timeline_manifest: Mapping[str, Any] | None,
) -> bool:
    policy = getattr(context, "audio_qc_policy", None)
    if isinstance(policy, Mapping) and policy.get("require_audio") is True:
        return True
    if getattr(context, "audio_required", False) is True:
        return True
    if getattr(context, "expect_audio", False) is True:
        return True
    for attr in ("exact_line_contract", "line_contracts"):
        if _line_contract_requires_audio(getattr(context, attr, None)):
            return True
    if _audio_plan_requires_stream(getattr(context, "audio_layer_plan", None)):
        return True
    if _audio_contract_requires_stream(getattr(context, "audio_contract", None)):
        return True
    stage_outputs = getattr(context, "stage_outputs", None)
    if isinstance(stage_outputs, Mapping):
        for output in stage_outputs.values():
            if not isinstance(output, Mapping):
                continue
            for key in ("exact_line_contract", "line_contracts"):
                if _line_contract_requires_audio(output.get(key)):
                    return True
            if _audio_plan_requires_stream(output.get("audio_layer_plan")):
                return True
            if _audio_contract_requires_stream(output.get("audio_contract")):
                return True
            if _timeline_manifest_requires_audio(output.get("timeline_manifest")):
                return True
    return _timeline_manifest_requires_audio(timeline_manifest)


def _audio_boundary_times(
    timeline_manifest: Mapping[str, Any] | None,
) -> tuple[float, ...]:
    if not isinstance(timeline_manifest, Mapping):
        return ()
    receipts = timeline_manifest.get("transition_renders")
    if not isinstance(receipts, list):
        return ()
    result: list[float] = []
    for item in receipts:
        if not isinstance(item, Mapping):
            continue
        try:
            offset = float(item.get("offset"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(offset) and offset > 0:
            result.append(offset)
    return tuple(result)


def _decode_audio_window(
    path: Path,
    *,
    center_seconds: float,
    window_seconds: float,
    ffmpeg_bin: str | None = None,
    sample_rate: int = 48_000,
) -> tuple[float, ...]:
    """Decode a small PCM window for deterministic splice-pop inspection."""

    ffmpeg = _executable("ffmpeg", ffmpeg_bin)
    start = max(0.0, center_seconds - window_seconds)
    duration = max(0.02, window_seconds * 2.0)
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-ss",
                f"{start:.6f}",
                "-t",
                f"{duration:.6f}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "f32le",
                "pipe:1",
            ],
            check=False,
            capture_output=True,
            timeout=120.0,
        )
    except subprocess.TimeoutExpired as exc:
        raise CapabilityUnavailable(
            "audio boundary PCM decode timed out",
            details={"center_seconds": center_seconds},
        ) from exc
    if result.returncode != 0:
        raise CapabilityUnavailable(
            "audio boundary PCM decode failed",
            details={"stderr": result.stderr.decode("utf-8", errors="replace")[-500:]},
        )
    raw = bytes(result.stdout or b"")
    usable = len(raw) - (len(raw) % 4)
    if usable <= 0:
        return ()
    samples = array("f")
    samples.frombytes(raw[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    return tuple(float(value) for value in samples)


def _measure_audio_quality(
    path: Path,
    *,
    timeline_manifest: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
    ffmpeg_bin: str | None = None,
) -> dict[str, Any]:
    """Measure delivery loudness, true peak, and declared splice boundaries."""

    ffmpeg = _executable("ffmpeg", ffmpeg_bin)
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            "ebur128=peak=true:framelog=quiet",
            "-f",
            "null",
            "-",
        ]
    )
    if result.returncode != 0:
        raise CapabilityUnavailable(
            "audio loudness measurement failed",
            details={"stderr": result.stderr[-500:]},
        )
    integrated_match = _EBUR128_INTEGRATED_RE.search(result.stderr or "")
    true_peak_match = _EBUR128_TRUE_PEAK_RE.search(result.stderr or "")
    if integrated_match is None or true_peak_match is None:
        raise CapabilityUnavailable("audio loudness measurement returned no ebur128 summary")
    integrated_lufs = _parse_audio_db(integrated_match.group("value"))
    true_peak_dbfs = _parse_audio_db(true_peak_match.group("value"))
    integrated_lufs_report, integrated_lufs_state = _audio_db_report_value(integrated_lufs)
    true_peak_report, true_peak_state = _audio_db_report_value(true_peak_dbfs)
    try:
        lufs_min = float(policy.get("integrated_lufs_min", -20.0))
        lufs_max = float(policy.get("integrated_lufs_max", -12.0))
        true_peak_max = float(policy.get("true_peak_max_dbfs", -1.0))
        max_jump = float(policy.get("max_boundary_sample_jump", 0.6))
    except (TypeError, ValueError) as exc:
        raise CapabilityUnavailable("audio quality policy contains non-numeric thresholds") from exc
    if not math.isfinite(lufs_min) or not math.isfinite(lufs_max) or lufs_min >= lufs_max:
        raise CapabilityUnavailable("audio quality policy loudness range is invalid")
    if not math.isfinite(true_peak_max) or not math.isfinite(max_jump) or max_jump <= 0:
        raise CapabilityUnavailable("audio quality policy peak/jump thresholds are invalid")

    boundaries: list[dict[str, Any]] = []
    click_detected = False
    if bool(policy.get("check_boundary_clicks", True)):
        for index, offset in enumerate(_audio_boundary_times(timeline_manifest)):
            samples = _decode_audio_window(
                path,
                center_seconds=offset,
                window_seconds=float(policy.get("boundary_window_seconds", 0.05)),
                ffmpeg_bin=ffmpeg_bin,
            )
            center = len(samples) // 2
            search = max(1, int(round(float(policy.get("boundary_search_seconds", 0.01)) * 48_000)))
            start = max(1, center - search)
            end = min(len(samples), center + search)
            jump = max(
                (abs(samples[pos] - samples[pos - 1]) for pos in range(start, end)),
                default=0.0,
            )
            failed = jump > max_jump
            click_detected = click_detected or failed
            boundaries.append(
                {
                    "boundary_index": index,
                    "offset_seconds": round(offset, 6),
                    "max_sample_jump": round(jump, 6),
                    "threshold": max_jump,
                    "passed": not failed,
                }
            )

    loudness_ok = math.isfinite(integrated_lufs) and lufs_min <= integrated_lufs <= lufs_max
    true_peak_ok = (
        math.isfinite(true_peak_dbfs) and true_peak_dbfs <= true_peak_max
    ) or true_peak_dbfs == float("-inf")
    return {
        "status": "measured",
        "integrated_lufs": integrated_lufs_report,
        "integrated_lufs_state": integrated_lufs_state,
        "true_peak_dbfs": true_peak_report,
        "true_peak_state": true_peak_state,
        "integrated_lufs_range": [lufs_min, lufs_max],
        "true_peak_max_dbfs": true_peak_max,
        "boundary_count": len(boundaries),
        "boundary_checks": boundaries,
        "loudness_in_range": loudness_ok,
        "true_peak_safe": true_peak_ok,
        "boundary_clicks_absent": not click_detected,
        "hard_failures": list(
            dict.fromkeys(
                [
                    *(["AUDIO_LOUDNESS_OUT_OF_RANGE"] if not loudness_ok else []),
                    *(["AUDIO_TRUE_PEAK_EXCEEDED"] if not true_peak_ok else []),
                    *(["AUDIO_BOUNDARY_CLICK_DETECTED"] if click_detected else []),
                ]
            )
        ),
    }


def _timeline_black_boundary_windows(
    manifest: Mapping[str, Any],
    *,
    duration: float,
    fps: float,
) -> tuple[tuple[float, float], ...] | None:
    """Return output-clock windows where black pixels indicate a splice fault.

    The compositor manifest is the only source of output-clock boundaries when
    elastic UI/tail media changes duration.  Transition receipts are preferred;
    adjacent placement ranges are a compatibility fallback.
    """

    half_frame = max(0.5 / max(fps, 1.0), 0.001)
    windows: list[tuple[float, float]] = []
    receipts = manifest.get("transition_renders")
    if isinstance(receipts, list):
        for item in receipts:
            if not isinstance(item, Mapping):
                continue
            try:
                offset = float(item.get("offset"))
                transition_duration = max(0.0, float(item.get("duration") or 0.0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(offset) or not math.isfinite(transition_duration):
                continue
            if offset < 0.0 or offset > duration:
                continue
            windows.append(
                (
                    max(0.0, offset - half_frame),
                    min(duration, offset + transition_duration + half_frame),
                )
            )
    if windows:
        return tuple(windows)

    placements = manifest.get("placements")
    if not isinstance(placements, list):
        regions = manifest.get("regions")
        # A multi-region manifest without output-clock placement evidence
        # cannot safely distinguish an internal black shot from a splice
        # boundary after elastic UI/tail duration changes. Fail closed rather
        # than guessing source time equals output time.
        if isinstance(regions, list) and len(regions) > 1:
            return None
        return ()
    ordered: list[tuple[float, float]] = []
    for item in placements:
        if not isinstance(item, Mapping):
            continue
        try:
            start = float(item.get("output_start"))
            end = float(item.get("output_end"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(start) and math.isfinite(end) and end >= start:
            ordered.append((start, end))
    for left, right in zip(ordered, ordered[1:]):
        start = min(left[1], right[0])
        end = max(left[1], right[0])
        windows.append(
            (
                max(0.0, start - half_frame),
                min(duration, end + half_frame),
            )
        )
    return tuple(windows)


def _black_interval_is_boundary_failure(
    intervals: Sequence[tuple[float, float]],
    *,
    duration: float,
    fps: float,
    timeline_manifest: Mapping[str, Any] | None,
) -> bool:
    """Apply legacy-all-black behavior or manifest-boundary-aware QC."""

    if not intervals:
        return False
    if timeline_manifest is None:
        # Legacy/local runs have no output-clock evidence. Preserve the
        # historical conservative gate rather than guessing splice locations.
        return True
    edge_tolerance = max(0.5 / max(fps, 1.0), 0.001)
    boundary_windows = _timeline_black_boundary_windows(
        timeline_manifest,
        duration=duration,
        fps=fps,
    )
    if boundary_windows is None:
        return True
    for start, end in intervals:
        if start <= edge_tolerance or end >= duration - edge_tolerance:
            return True
        if any(
            end >= window_start - edge_tolerance
            and start <= window_end + edge_tolerance
            for window_start, window_end in boundary_windows
        ):
            return True
    return False


def _freeze_interval_is_boundary_failure(
    intervals: Sequence[tuple[float, float]],
    *,
    duration: float,
    fps: float,
    timeline_manifest: Mapping[str, Any] | None,
    minimum_duration: float,
) -> bool:
    """Reject repeated frames at an edge/splice, not intentional static shots."""

    candidates = [
        (start, end)
        for start, end in intervals
        if end - start >= minimum_duration
    ]
    if not candidates:
        return False
    if timeline_manifest is None:
        return True
    edge_tolerance = max(0.5 / max(fps, 1.0), 0.001)
    boundary_windows = _timeline_black_boundary_windows(
        timeline_manifest,
        duration=duration,
        fps=fps,
    )
    if boundary_windows is None:
        return True
    for start, end in candidates:
        if start <= edge_tolerance or end >= duration - edge_tolerance:
            return True
        if any(
            end >= window_start - edge_tolerance
            and start <= window_end + edge_tolerance
            for window_start, window_end in boundary_windows
        ):
            return True
    return False


def _freeze_interval_failure_code(
    intervals: Sequence[tuple[float, float]],
    *,
    duration: float,
    fps: float,
    timeline_manifest: Mapping[str, Any] | None,
    minimum_duration: float,
) -> str | None:
    """Return a stable diagnostic code for the first actionable freeze."""

    if not _manifest_has_replacement_route(timeline_manifest):
        return None

    candidates = [
        (start, end)
        for start, end in intervals
        if end - start >= minimum_duration
    ]
    allowed_windows = _manifest_allowed_freeze_windows(timeline_manifest)
    candidates = [
        (start, end)
        for start, end in candidates
        if not any(
            start >= allowed_start - 1e-6 and end <= allowed_end + 1e-6
            for allowed_start, allowed_end in allowed_windows
        )
    ]
    if not candidates:
        return None
    edge_tolerance = max(0.5 / max(fps, 1.0), 0.001)
    if timeline_manifest is None:
        if any(end >= duration - edge_tolerance for _, end in candidates):
            return "TRAILING_FREEZE_DETECTED"
        if any(start <= edge_tolerance for start, _ in candidates):
            return "LEADING_FREEZE_DETECTED"
        return "FREEZE_FRAME_DETECTED"
    boundary_windows = _timeline_black_boundary_windows(
        timeline_manifest,
        duration=duration,
        fps=fps,
    )
    if boundary_windows is None:
        return "FREEZE_FRAME_DETECTED"
    for start, end in candidates:
        if end >= duration - edge_tolerance:
            return "TRAILING_FREEZE_DETECTED"
        if start <= edge_tolerance:
            return "LEADING_FREEZE_DETECTED"
        if any(
            end >= window_start - edge_tolerance
            and start <= window_end + edge_tolerance
            for window_start, window_end in boundary_windows
        ):
            return "SPLICE_BOUNDARY_FREEZE_DETECTED"
    return None


def _manifest_allowed_freeze_windows(
    timeline_manifest: Mapping[str, Any] | None,
) -> tuple[tuple[float, float], ...]:
    """Return output windows whose static frames are proven input content."""

    if not isinstance(timeline_manifest, Mapping):
        return ()
    windows: list[tuple[float, float]] = []
    explicit = timeline_manifest.get("allowed_freeze_intervals")
    if isinstance(explicit, list):
        for item in explicit:
            if not isinstance(item, Mapping):
                continue
            try:
                start = float(item.get("start"))
                end = float(item.get("end"))
            except (TypeError, ValueError):
                continue
            if 0 <= start < end:
                windows.append((start, end))
    placements = timeline_manifest.get("placements")
    if not isinstance(placements, list):
        return tuple(windows)
    for item in placements:
        if not isinstance(item, Mapping):
            continue
        origin = str(item.get("media_origin") or "").strip().lower()
        if origin not in {"source_interval", "source_video", "user_upload"}:
            continue
        try:
            start = float(item.get("output_start"))
            end = float(item.get("output_end"))
        except (TypeError, ValueError):
            continue
        if not (0 <= start < end):
            continue
        if origin in {"source_interval", "source_video"}:
            windows.append((start, end))
            continue
        try:
            actual = float(item.get("actual_video_duration"))
            effective = float(item.get("effective_media_duration"))
        except (TypeError, ValueError):
            actual = effective = 0.0
        if actual > 0 and effective > 0 and actual + 0.05 >= effective:
            windows.append((start, end))
    return tuple(windows)


def _manifest_has_replacement_route(
    timeline_manifest: Mapping[str, Any] | None,
) -> bool:
    """Return whether the manifest contains a carrier that can add freezes.

    A static source shot is valid content. Freeze QC becomes a hard gate only
    when the compositor manifest proves that generated/opaque/omitted media or
    a transition carrier was assembled into the output.
    """

    if not isinstance(timeline_manifest, Mapping):
        return False
    if isinstance(timeline_manifest.get("omitted_intervals"), list) and timeline_manifest.get("omitted_intervals"):
        return True
    if isinstance(timeline_manifest.get("transition_renders"), list) and timeline_manifest.get("transition_renders"):
        return True
    placements = timeline_manifest.get("placements")
    if not isinstance(placements, list):
        placements = timeline_manifest.get("regions")
    if not isinstance(placements, list):
        return False
    replacement_kinds = {
        "generated",
        "generated_ui_demo",
        "opaque_ui_demo",
        "excluded_app_end_card",
        "ui_demo",
        "tail_card",
    }
    for item in placements:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("region_type") or item.get("kind") or "").strip().lower()
        origin = str(item.get("media_origin") or "").strip().lower()
        if origin in {"source_interval", "source_video"}:
            continue
        if kind in replacement_kinds:
            return True
        if origin:
            return True
    return False


def _cached_probe_output(context: Any) -> Mapping[str, Any] | None:
    """Return the latest durable ``probe_source`` payload, when present.

    The stage output is deliberately preferred over re-reading an intermediate
    artifact: it is already decoded from the repository transaction that
    completed ``probe_source``.  A few deployment adapters publish the probe
    under a named key, so the small set of accepted carriers is explicit and
    cannot accidentally treat arbitrary stage output as media metadata.
    """

    stage_outputs = getattr(context, "stage_outputs", None)
    if isinstance(stage_outputs, Mapping):
        output = stage_outputs.get("probe_source")
        if isinstance(output, Mapping):
            for key in ("probe", "video_probe", "media_probe", "source_probe"):
                candidate = output.get(key)
                if isinstance(candidate, Mapping):
                    return candidate
            # A direct probe payload is accepted only when it carries at least
            # one canonical timing field; arbitrary stage output is ignored.
            if any(key in output for key in ("duration_us", "duration_seconds", "fps", "fps_num")):
                return output

    # A verified probe artifact may carry the same payload in its immutable
    # metadata.  Do not materialize an object-store JSON file just to recover
    # a cache hit; if the deployment did not persist the metadata, the caller
    # safely falls back to one fresh probe.
    for artifact in getattr(context, "artifacts", ()) or ():
        if not isinstance(artifact, Mapping):
            continue
        if str(artifact.get("kind") or "").lower() not in {
            "probe_source",
            "source_probe",
            "video_probe",
            "media_probe",
        }:
            continue
        metadata = artifact.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        for key in ("probe", "video_probe", "media_probe", "source_probe"):
            candidate = metadata.get(key)
            if isinstance(candidate, Mapping):
                return candidate
    return None


def _cached_probe_for_media(context: Any, media: Any) -> dict[str, Any] | None:
    """Validate and normalize a durable probe payload for one media object.

    A present-but-stale payload is an integrity error, not a cache miss.  This
    prevents a changed source object from silently reusing old duration/fps
    evidence.  Only an absent payload takes the normal one-probe fallback.
    """

    raw = _cached_probe_output(context)
    if raw is None:
        return None
    source_sha = str(
        raw.get("source_sha256")
        or raw.get("input_sha256")
        or raw.get("sha256")
        or ""
    ).lower()
    expected_sha = str(getattr(media, "sha256", "") or "").lower()
    if len(source_sha) != 64 or any(char not in "0123456789abcdef" for char in source_sha):
        raise CapabilityUnavailable("probe_source output is missing a valid source SHA-256")
    if expected_sha and source_sha != expected_sha:
        raise CapabilityUnavailable(
            "probe_source output SHA-256 does not match the materialized source",
            details={"expected_source_sha256": expected_sha, "probe_source_sha256": source_sha},
        )

    duration_value = raw.get("duration_us")
    if duration_value is None:
        duration_value = raw.get("video_duration_us")
    if duration_value is None and raw.get("duration_seconds") is not None:
        try:
            duration_value = float(raw["duration_seconds"]) * 1_000_000
        except (TypeError, ValueError):
            duration_value = None
    try:
        duration_us = int(round(float(duration_value)))
    except (TypeError, ValueError) as exc:
        raise CapabilityUnavailable("probe_source output has no valid duration") from exc
    if duration_us <= 0 or duration_us > 30_000_000:
        raise CapabilityUnavailable("probe_source output duration is outside the source limit")

    fps_num = raw.get("fps_num")
    fps_den = raw.get("fps_den")
    fps_raw = raw.get("fps")
    if (fps_num is None or fps_den is None) and isinstance(fps_raw, str) and "/" in fps_raw:
        numerator, denominator = fps_raw.split("/", 1)
        try:
            fps_num = int(numerator)
            fps_den = int(denominator)
        except (TypeError, ValueError):
            fps_num = fps_den = None
    try:
        fps_num = int(fps_num)
        fps_den = int(fps_den)
    except (TypeError, ValueError):
        fps_num = fps_den = 0
    if fps_num <= 0 or fps_den <= 0:
        try:
            fps = float(fps_raw)
        except (TypeError, ValueError):
            fps = 0.0
        if not math.isfinite(fps) or fps <= 0:
            raise CapabilityUnavailable("probe_source output has no valid frame rate")
        fps_num = max(1, int(round(fps * 1000)))
        fps_den = 1000
    fps = float(fps_num) / float(fps_den)
    if not math.isfinite(fps) or fps <= 0:
        raise CapabilityUnavailable("probe_source output has no valid frame rate")

    try:
        width = int(raw.get("width") or raw.get("source_width") or 0)
        height = int(raw.get("height") or raw.get("source_height") or 0)
    except (TypeError, ValueError) as exc:
        raise CapabilityUnavailable("probe_source output dimensions are invalid") from exc
    if width <= 0 or height <= 0:
        raise CapabilityUnavailable("probe_source output dimensions are missing")

    # Upload-completion metadata is an independent duration claim.  Allow one
    # decoded frame of quantization in addition to the normal 1 ms metadata
    # tolerance, but never accept an unrelated source timeline.
    for slot in getattr(context, "input_slots", ()) or ():
        if not isinstance(slot, Mapping) or str(slot.get("slot_id")) != "source_video":
            continue
        metadata = slot.get("metadata") or []
        if not isinstance(metadata, Sequence) or not metadata or not isinstance(metadata[0], Mapping):
            break
        declared = metadata[0].get("duration_seconds")
        if declared is None:
            break
        try:
            declared_seconds = float(declared)
        except (TypeError, ValueError) as exc:
            raise CapabilityUnavailable("source slot duration metadata is invalid") from exc
        if abs(float(duration_us) / 1_000_000.0 - declared_seconds) > max(0.001, 1.0 / fps):
            raise CapabilityUnavailable("probe_source output duration does not match source metadata")
        break

    try:
        video_duration_us = int(
            raw.get("video_duration_us")
            if raw.get("video_duration_us") is not None
            else duration_us
        )
        audio_duration_us = int(
            raw.get("audio_duration_us")
            if raw.get("audio_duration_us") is not None
            else 0
        )
    except (TypeError, ValueError) as exc:
        raise CapabilityUnavailable("probe_source output stream durations are invalid") from exc
    if video_duration_us <= 0 or audio_duration_us < 0:
        raise CapabilityUnavailable("probe_source output stream durations are invalid")
    if abs(video_duration_us - duration_us) > max(1_000, int(round(1_000_000.0 / fps))):
        raise CapabilityUnavailable("probe_source output video duration is inconsistent")

    normalized = {
        key: value
        for key, value in raw.items()
        if key not in {"path", "file", "source"}
    }
    normalized.update(
        {
            "source_sha256": source_sha,
            "duration_us": duration_us,
            "video_duration_us": video_duration_us,
            "audio_duration_us": audio_duration_us,
            "width": width,
            "height": height,
            "fps": fps,
            "fps_num": fps_num,
            "fps_den": fps_den,
            "has_audio": bool(raw.get("has_audio")),
            "audio_streams": list(raw.get("audio_streams") or []),
            "video_codec": str(raw.get("video_codec") or ""),
        }
    )
    return normalized


def _materialize(context: Any, slot_id: str):
    materialize = getattr(context, "materialize_slot", None)
    if not callable(materialize):
        raise CapabilityUnavailable("worker context does not expose materialize_slot", details={"slot_id": slot_id})
    try:
        return materialize(slot_id)
    except TypeError:
        return materialize(slot_id=slot_id)


def _frame_boundaries(path: Path, *, duration_us: int, fps: float, max_samples: int = 180) -> list[int]:
    """Derive edit/motion candidates without pretending fixed sampling is truth."""

    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return []
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return []
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 1:
        capture.release()
        return []
    stride = max(1, math.ceil(total / max_samples))
    previous = None
    previous_hist = None
    candidates: list[int] = []
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % stride:
            index += 1
            continue
        small = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
        cv2.normalize(hist, hist)
        if previous is not None and previous_hist is not None:
            pixel_delta = float(np.mean(cv2.absdiff(gray, previous))) / 255.0
            hist_delta = float(cv2.compareHist(previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
            # A cut candidate must be a material visual change, not a single
            # noisy frame.  The threshold is intentionally conservative; the
            # complete interval is still covered even when no candidate fires.
            if pixel_delta >= 0.30 or hist_delta >= 0.55:
                timestamp = int(round(index / fps * 1_000_000))
                if 0 < timestamp < duration_us and (not candidates or timestamp - candidates[-1] > int(0.12 * 1_000_000)):
                    candidates.append(timestamp)
        previous = gray
        previous_hist = hist
        index += 1
    capture.release()
    return candidates


def _cut_record(number: int, start_us: int, end_us: int, *, boundary: bool, motion: str = "unknown") -> dict[str, Any]:
    return {
        "cut": number,
        "start_us": int(start_us),
        "end_us": int(end_us),
        "subject_presence": "uncertain",
        "content_roles": ["scene_progression", "source_motion", "audio_relationship"],
        "scene": "source scene preserved; target identity is resolved downstream",
        "action": "visible action phase retained; semantic enrichment is evidence-bounded",
        "camera": f"decoder-derived motion={motion}",
        "transition": "edit_boundary" if boundary else "continuous",
        "end_state": "state at source cut end",
        "certainty": "uncertain" if motion == "unknown" else "certain",
        "evidence_refs": [
            {"kind": "frame", "start_us": int(start_us), "end_us": int(end_us), "method": "ffmpeg/opencv decoder evidence"}
        ],
    }


class FfmpegDynamicsAnalyzer:
    """Concrete frame/timing analyzer with an optional semantic backend."""

    def __init__(
        self,
        *,
        semantic_analyzer: Any | None = None,
        allow_heuristic: bool = False,
        ffprobe_bin: str | None = None,
        implementation: str = "server.real_capabilities:FfmpegDynamicsAnalyzer",
        version: str = "1.0.0",
        sha256: str | None = None,
        production: bool = False,
        require_explicit_digest: bool | None = None,
    ) -> None:
        self.semantic_analyzer = semantic_analyzer
        self.allow_heuristic = allow_heuristic
        self.ffprobe_bin = ffprobe_bin
        self.production = bool(production)
        if self.production and self.allow_heuristic:
            raise ValueError("production dynamics analyzer cannot enable heuristic mode")
        self._identity = _identity("dynamics_analyzer", implementation, version, sha256, require_explicit_digest=self.production if require_explicit_digest is None else require_explicit_digest)
        self._semantic_backend_identity = (
            _evidence_backend_identity(semantic_analyzer, method="analyze", label="VLM")
            if self.production and semantic_analyzer is not None
            else None
        )
        self._capability_identity = _composite_identity(
            self._identity,
            {"semantic_backend": self._semantic_backend_identity or {"mode": "heuristic"}},
        )

    def capability_identity(self) -> Mapping[str, Any]:
        return dict(self._capability_identity)

    def analyze(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        with _materialize(context, "source_video") as media:
            source = Path(media.path)
            analysis_scope = getattr(context, "analysis_scope", None)
            if analysis_scope is not None and not isinstance(analysis_scope, Mapping):
                raise CapabilityUnavailable("analysis scope must be an immutable object")
            semantic_pass = analysis_scope.get("semantic_pass") if isinstance(analysis_scope, Mapping) else None
            semantic_required = not (
                isinstance(semantic_pass, Mapping)
                and semantic_pass.get("status") == "skipped"
            )
            probe = _cached_probe_for_media(context, media)
            if probe is None:
                probe = _probe(source, ffprobe_bin=self.ffprobe_bin)
            # MaterializedMedia already verified the bytes.  Keep the source
            # digest in the evidence envelope even when the canonical probe
            # came from a legacy adapter that did not include it.
            probe.setdefault("source_sha256", str(getattr(media, "sha256", "") or "").lower())
            if semantic_required and self.semantic_analyzer is None and not self.allow_heuristic:
                raise CapabilityUnavailable(
                    "dynamics analyzer requires an injected VLM/semantic backend in strict mode",
                    details={"implementation": self._identity["implementation"]},
                )
            boundaries = _frame_boundaries(source, duration_us=probe["duration_us"], fps=probe["fps"])
            source_sha256 = str(getattr(media, "sha256", "") or probe.get("source_sha256") or "").lower()
            if len(source_sha256) != 64 or any(char not in "0123456789abcdef" for char in source_sha256):
                source_sha256 = _sha256_file(source)
            evidence_plan = _build_adaptive_evidence_plan(
                probe,
                source_sha256=source_sha256,
                scene_cut_candidates_us=boundaries,
            )
            points = [0, *boundaries, probe["duration_us"]]
            cuts = []
            for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
                cuts.append(_cut_record(index, start, end, boundary=index > 1))
            enriched_events: list[dict[str, Any]] | None = None
            semantic_extensions: dict[str, Any] | None = None
            semantic_overlay_contract: dict[str, Any] | None = None
            semantic_evidence: dict[str, Any] | None = None
            if semantic_required and self.semantic_analyzer is not None:
                analyzer = getattr(self.semantic_analyzer, "analyze", None)
                if not callable(analyzer):
                    analyzer = self.semantic_analyzer
                semantic_kwargs = {
                    "path": source,
                    "probe": dict(probe),
                    "cuts": [dict(item) for item in cuts],
                    "context": context,
                }
                accepts_evidence_plan = _accepts_keyword(analyzer, "evidence_plan")
                if self.production and not accepts_evidence_plan:
                    raise CapabilityUnavailable(
                        "production VLM backend must accept the packaged adaptive evidence_plan"
                    )
                if accepts_evidence_plan:
                    semantic_kwargs["evidence_plan"] = evidence_plan
                accepts_analysis_scope = _accepts_keyword(analyzer, "analysis_scope")
                if analysis_scope is not None and self.production and not accepts_analysis_scope:
                    raise CapabilityUnavailable(
                        "production VLM backend must accept the immutable pre-route analysis_scope"
                    )
                if analysis_scope is not None and accepts_analysis_scope:
                    semantic_kwargs["analysis_scope"] = dict(analysis_scope)
                if self.production:
                    enriched = analyzer(**semantic_kwargs)
                else:
                    try:
                        enriched = analyzer(**semantic_kwargs)
                    except TypeError:
                        enriched = analyzer(source, dict(probe), [dict(item) for item in cuts])
                if self.production:
                    if not isinstance(enriched, Mapping):
                        raise CapabilityUnavailable("production VLM backend returned no evidence-bound semantic object")
                    evidence = enriched.get("backend_evidence")
                    if not isinstance(evidence, Mapping):
                        raise CapabilityUnavailable("production VLM backend returned semantic facts without backend_evidence")
                    expected_source_sha = str(getattr(media, "sha256", "") or _sha256_file(source))
                    frame_sha256s = evidence.get("frame_sha256s")
                    identity = self._semantic_backend_identity or {}
                    if str(evidence.get("source_sha256") or "") != expected_source_sha:
                        raise CapabilityUnavailable("production VLM evidence is not bound to the materialized source SHA")
                    if str(evidence.get("model_id") or "") != str(identity.get("model_id") or "") or str(evidence.get("model_sha256") or "") != str(identity.get("model_sha256") or ""):
                        raise CapabilityUnavailable("production VLM evidence model identity does not match the bound backend")
                    if any(
                        len(str(evidence.get(field) or "")) != 64
                        or any(char not in "0123456789abcdef" for char in str(evidence.get(field) or ""))
                        for field in ("request_sha256", "response_sha256")
                    ):
                        raise CapabilityUnavailable("production VLM evidence requires request and response SHA-256 values")
                    if not isinstance(frame_sha256s, list) or not frame_sha256s or any(
                        not isinstance(value, str)
                        or len(value) != 64
                        or any(char not in "0123456789abcdef" for char in value)
                        for value in frame_sha256s
                    ):
                        raise CapabilityUnavailable("production VLM evidence requires exact sampled-frame SHA-256 values")
                    semantic_evidence = dict(evidence)
                if isinstance(enriched, Mapping):
                    semantic_payload = enriched.get("source_dynamics_analysis") if isinstance(enriched.get("source_dynamics_analysis"), Mapping) else enriched
                    if isinstance(semantic_payload, Mapping) and isinstance(semantic_payload.get("extensions"), Mapping):
                        semantic_extensions = deepcopy(dict(semantic_payload["extensions"]))
                    if isinstance(semantic_payload, Mapping) and isinstance(semantic_payload.get("source_overlay_contract"), Mapping):
                        semantic_overlay_contract = deepcopy(dict(semantic_payload["source_overlay_contract"]))
                    candidate_cuts = semantic_payload.get("source_cuts") if isinstance(semantic_payload, Mapping) else None
                    if isinstance(candidate_cuts, list) and candidate_cuts:
                        candidate_points: list[tuple[int, int]] = []
                        valid_timing = True
                        for source_cut in candidate_cuts:
                            if not isinstance(source_cut, Mapping):
                                valid_timing = False
                                break
                            try:
                                start = int(source_cut.get("start_us"))
                                end = int(source_cut.get("end_us"))
                            except (TypeError, ValueError):
                                valid_timing = False
                                break
                            candidate_points.append((start, end))
                        if valid_timing and candidate_points and candidate_points[0][0] == 0 and candidate_points[-1][1] == probe["duration_us"] and all(end > start for start, end in candidate_points) and all(candidate_points[index][1] == candidate_points[index + 1][0] for index in range(len(candidate_points) - 1)):
                            cuts = []
                            for index, ((start, end), source_cut) in enumerate(zip(candidate_points, candidate_cuts), start=1):
                                record = _cut_record(index, start, end, boundary=index > 1)
                                for key in ("subject_presence", "content_roles", "scene", "action", "camera", "transition", "end_state", "certainty", "evidence_refs"):
                                    if key in source_cut:
                                        record[key] = source_cut[key]
                                cuts.append(record)
                        elif self.production:
                            raise CapabilityUnavailable("semantic dynamics backend returned Cuts that do not cover frame zero through the exact decoded end")
                    candidate_events = semantic_payload.get("source_events") if isinstance(semantic_payload, Mapping) else None
                    if isinstance(candidate_events, list) and candidate_events:
                        enriched_events = [dict(item) for item in candidate_events if isinstance(item, Mapping)]
            events = enriched_events or [
                {
                    "event": 1,
                    "kind": "ambience" if probe["has_audio"] else "silence",
                    "start_us": 0,
                    "end_us": probe["duration_us"],
                    "source_cut_start": 1,
                    "source_cut_end": len(cuts),
                    "text": "",
                    "certainty": "uncertain" if probe["has_audio"] else "not_applicable",
                    "evidence_refs": [{"kind": "audio_stream", "method": "ffprobe stream presence only"}],
                }
            ]
            if self.production:
                for index, event in enumerate(events, start=1):
                    try:
                        start = int(event.get("start_us"))
                        end = int(event.get("end_us"))
                    except (TypeError, ValueError):
                        raise CapabilityUnavailable("semantic dynamics backend returned an invalid source audio event", details={"event": index})
                    if not (0 <= start < end <= probe["duration_us"]):
                        raise CapabilityUnavailable("semantic dynamics backend returned an out-of-range source audio event", details={"event": index})
                    event["event"] = index
            analysis = {
                "contract": "reference-video-dynamics",
                "contract_version": 1,
                "reference_duration_us": probe["duration_us"],
                "source_width": probe["width"],
                "source_height": probe["height"],
                "fps_num": probe["fps_num"],
                "fps_den": probe["fps_den"],
                "source_cut_count": len(cuts),
                "source_cuts": cuts,
                "source_events": events,
                "notes": [
                    "timing and frame coverage are decoder-derived",
                    "opaque UI/tail intervals are classified downstream from the authoritative timeline route",
                ],
            }
            if semantic_extensions is not None:
                analysis["extensions"] = semantic_extensions
            if semantic_overlay_contract is not None:
                analysis["source_overlay_contract"] = semantic_overlay_contract
            if _active_high_fidelity(context):
                extension = (analysis.get("extensions") or {}).get("high_fidelity_hybrid_v1")
                if not isinstance(extension, Mapping):
                    raise CapabilityUnavailable(
                        "active high-fidelity dynamics requires extensions.high_fidelity_hybrid_v1 from the single semantic pass"
                    )
                try:
                    validator = _load_high_fidelity_dynamics_validator()
                    validator.validate_high_fidelity_extension(analysis)
                except CapabilityUnavailable:
                    raise
                except Exception as exc:
                    raise CapabilityUnavailable(
                        "active high-fidelity dynamics extension is invalid",
                        details={"reason": str(exc)},
                    ) from exc
            return {
                "status": "ready",
                "source_dynamics_analysis": analysis,
                "evidence_plan": evidence_plan,
                "evidence": {
                    "probe": probe,
                    "boundary_count": len(boundaries),
                    "evidence_plan_sha256": evidence_plan["plan_sha256"],
                    "analysis_scope_sha256": (
                        str(analysis_scope.get("scope_sha256") or "")
                        if isinstance(analysis_scope, Mapping)
                        else None
                    ),
                    "semantic_backend": bool(self.semantic_analyzer) and semantic_required,
                    "semantic_backend_identity": dict(self._semantic_backend_identity or {}),
                    "semantic_backend_evidence": semantic_evidence,
                },
            }


def _silence_windows(duration_ms: int, segments: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    spans: list[tuple[int, int]] = []
    for item in segments:
        try:
            start = max(0, int(round(float(item.get("start", item.get("start_ms", 0))) * (1000 if "start_ms" not in item else 1))))
            end = min(duration_ms, int(round(float(item.get("end", item.get("end_ms", 0))) * (1000 if "end_ms" not in item else 1))))
        except (TypeError, ValueError):
            continue
        if end > start:
            spans.append((start, end))
    spans.sort()
    windows: list[dict[str, int]] = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            windows.append({"start_ms": cursor, "end_ms": start, "kind": "meaningful_silence"})
        cursor = max(cursor, end)
    if cursor < duration_ms:
        windows.append({"start_ms": cursor, "end_ms": duration_ms, "kind": "meaningful_silence"})
    if not windows and duration_ms > 0:
        windows.append({"start_ms": 0, "end_ms": duration_ms, "kind": "meaningful_silence"})
    return windows


def _default_silence_detector(path: Path, *, ffmpeg_bin: str | None = None) -> list[dict[str, int]]:
    """Detect acoustic silence only; semantic meaning is assigned elsewhere."""

    ffmpeg = _executable("ffmpeg", ffmpeg_bin)
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-35dB:d=0.25",
            "-f",
            "null",
            "-",
        ]
    )
    if result.returncode != 0:
        return []
    import re

    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)", result.stderr)]
    windows: list[dict[str, int]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else start
        if end > start:
            windows.append({"start_ms": int(round(start * 1000)), "end_ms": int(round(end * 1000))})
    return windows


def _normalise_silence_windows(raw: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, Mapping):
            continue
        try:
            start = int(round(float(item.get("start_ms", item.get("start", 0)))))
            end = int(round(float(item.get("end_ms", item.get("end", 0)))))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        result.append(
            {
                "start_ms": max(0, start),
                "end_ms": max(0, end),
                "kind": "acoustic_silence",
                "semantic_meaning": "unclassified",
            }
        )
    return result


class WhisperAsrTranscriber:
    """Whisper/faster-whisper compatible ASR port with explicit silence."""

    _model_cache: dict[tuple[str, str, str], Any] = {}

    def __init__(
        self,
        *,
        transcriber: Callable[[Path], Sequence[Mapping[str, Any]]] | None = None,
        model_name: str = "tiny",
        language: str | None = None,
        ffmpeg_bin: str | None = None,
        implementation: str = "server.real_capabilities:WhisperAsrTranscriber",
        version: str = "1.0.0",
        sha256: str | None = None,
        production: bool = False,
        require_explicit_digest: bool | None = None,
        download_root: str | Path | None = None,
        device: str | None = None,
        model_artifact_sha256: str | None = None,
        allow_model_download: bool = False,
        model_path: str | Path | None = None,
        model_sha256: str | None = None,
        silence_detector: Callable[[Path], Sequence[Mapping[str, Any]]] | None = None,
        audio_event_classifier: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.transcriber = transcriber
        self.production = bool(production)
        self.model_name = model_name
        self.language = language
        self.ffmpeg_bin = ffmpeg_bin
        self.download_root = Path(download_root).resolve() if download_root else None
        self.model_path = Path(model_path).resolve() if model_path else None
        self.device = device
        self.model_artifact_sha256 = model_artifact_sha256 or model_sha256
        self.model_sha256 = model_sha256 or model_artifact_sha256
        self.silence_detector = silence_detector
        self.audio_event_classifier = audio_event_classifier
        self.allow_model_download = allow_model_download and not self.production
        self._asr_backend_identity = (
            _evidence_backend_identity(transcriber, method="transcribe", label="ASR")
            if self.production and transcriber is not None
            else None
        )
        self._audio_event_backend_identity = (
            _evidence_backend_identity(
                audio_event_classifier,
                method="classify",
                label="audio event classifier",
            )
            if self.production and audio_event_classifier is not None
            else None
        )
        if self.production and self.transcriber is None:
            if self.model_path is None:
                raise ValueError("production Whisper requires model_path")
            if not self.model_sha256:
                raise ValueError("production Whisper requires model_sha256")
            if not self.device:
                raise ValueError("production Whisper requires device")
        self._identity = _identity("asr_transcriber", implementation, version, sha256, require_explicit_digest=self.production if require_explicit_digest is None else require_explicit_digest)
        asr_dependency = self._asr_backend_identity or {
            "implementation": "openai-whisper",
            "version": str(self.model_name),
            "model_id": str(self.model_name),
            "model_sha256": str(self.model_sha256 or ""),
            "device": str(self.device or ""),
            "evidence_binding": "local-whisper-pinned/v1",
        }
        self._capability_identity = _composite_identity(
            self._identity,
            {
                "asr_backend": asr_dependency,
                "audio_event_backend": self._audio_event_backend_identity or {"mode": "none"},
            },
        )

    def capability_identity(self) -> Mapping[str, Any]:
        return dict(self._capability_identity)

    def _load_model(self) -> Any:
        cache_key = (str(self.model_path) if self.model_path else self.model_name, self.model_sha256 or "", self.device or "")
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]
        try:
            import whisper  # type: ignore
        except ImportError as exc:
            raise CapabilityUnavailable("openai-whisper is not installed") from exc
        try:
            if self.model_path is not None:
                if not self.model_path.is_file():
                    raise CapabilityUnavailable("pinned Whisper model_path is missing", details={"path": str(self.model_path)})
                actual = _sha256_file(self.model_path)
                if self.model_sha256 and actual != self.model_sha256.lower():
                    raise CapabilityUnavailable("pinned Whisper model SHA-256 does not match", details={"expected": self.model_sha256, "actual": actual})
            elif not self.allow_model_download and self.download_root is None:
                raise CapabilityUnavailable("Whisper requires a pinned local model path/download_root when network download is disabled")
            kwargs: dict[str, Any] = {}
            if self.download_root is not None:
                kwargs["download_root"] = str(self.download_root)
            if self.device:
                kwargs["device"] = self.device
            if not self.allow_model_download and self.model_path is None:
                # openai-whisper has no strict offline flag; the pinned model
                # directory must already contain the requested checkpoint.
                expected = self.download_root / f"{self.model_name}.pt" if self.download_root else None
                if expected is not None and not expected.is_file():
                    raise CapabilityUnavailable("pinned Whisper checkpoint is missing", details={"path": str(expected)})
            model = whisper.load_model(str(self.model_path) if self.model_path is not None else self.model_name, **kwargs)
        except CapabilityUnavailable:
            raise
        except Exception as exc:
            raise CapabilityUnavailable("Whisper model could not be loaded", details={"model": self.model_name}) from exc
        self._model_cache[cache_key] = model
        return model

    def transcribe(self, *, context: Any, input_artifacts: list[Mapping[str, Any]], **kwargs: Any) -> Mapping[str, Any]:
        with _materialize(context, "source_video") as media:
            source = Path(media.path)
            probe = _probe(source)
            work_dir = Path(getattr(context, "work_dir", tempfile.gettempdir())).resolve()
            work_dir.mkdir(parents=True, exist_ok=True)
            wav = work_dir / "source-asr.wav"
            raw: Sequence[Mapping[str, Any]] = []
            if probe["has_audio"]:
                ffmpeg = _executable("ffmpeg", self.ffmpeg_bin)
                converted = _run([ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
                if converted.returncode != 0:
                    raise CapabilityUnavailable("audio extraction for ASR failed", details={"stderr": converted.stderr[-1000:]})
            wav_sha256 = _sha256_file(wav) if probe["has_audio"] else ""
            if self.production and probe["has_audio"] and self.audio_event_classifier is None:
                raise CapabilityUnavailable("production ASR requires an audio event classifier for Foley/ambience/silence evidence")
            asr_backend_evidence: Mapping[str, Any] | None = None
            if self.transcriber is not None and probe["has_audio"]:
                operation = getattr(self.transcriber, "transcribe", None)
                if not callable(operation):
                    operation = self.transcriber
                language = kwargs.get("language", self.language)
                try:
                    backend_result = operation(wav, language=language)
                except TypeError:
                    backend_result = operation(wav)
                if isinstance(backend_result, Mapping):
                    raw_value = backend_result.get("segments")
                    raw = [dict(item) for item in raw_value if isinstance(item, Mapping)] if isinstance(raw_value, list) else []
                    detected_language = backend_result.get("language") or language
                    if self.production:
                        asr_backend_evidence = _validate_bound_model_receipt(
                            backend_result.get("evidence"),
                            identity=self._asr_backend_identity or {},
                            input_sha256=wav_sha256,
                            payload=raw,
                            payload_digest_field="segments_sha256",
                            label="ASR",
                        )
                else:
                    if self.production:
                        raise CapabilityUnavailable("production ASR backend must return segments plus evidence")
                    raw = backend_result if isinstance(backend_result, Sequence) else []
                    detected_language = language
            elif probe["has_audio"]:
                model = self._load_model()
                options: dict[str, Any] = {"word_timestamps": True, "verbose": False}
                language = kwargs.get("language", self.language)
                if language:
                    options["language"] = language
                try:
                    result = model.transcribe(str(wav), **options)
                except Exception as exc:
                    raise CapabilityUnavailable("Whisper transcription failed") from exc
                raw = result.get("segments", []) if isinstance(result, Mapping) else []
                detected_language = result.get("language") if isinstance(result, Mapping) else None
                if self.production:
                    asr_backend_evidence = {
                        "evidence_binding": "local-whisper-pinned/v1",
                        "input_sha256": wav_sha256,
                        "model_id": self.model_name,
                        "model_sha256": str(self.model_sha256 or ""),
                        "device": str(self.device or ""),
                    }
            else:
                detected_language = None
            segments: list[dict[str, Any]] = []
            for index, item in enumerate(raw or [], start=1):
                if not isinstance(item, Mapping):
                    continue
                try:
                    start = float(item.get("start", item.get("start_seconds", 0.0)))
                    end = float(item.get("end", item.get("end_seconds", 0.0)))
                except (TypeError, ValueError):
                    continue
                if end <= start:
                    continue
                text = str(item.get("text") or "").strip()
                words = item.get("words") if isinstance(item.get("words"), list) else []
                normalized_words: list[dict[str, Any]] = []
                for word in words:
                    if not isinstance(word, Mapping):
                        continue
                    normalized = dict(word)
                    try:
                        if "start_ms" not in normalized and normalized.get("start") is not None:
                            normalized["start_ms"] = int(round(float(normalized["start"]) * 1000))
                        if "end_ms" not in normalized and normalized.get("end") is not None:
                            normalized["end_ms"] = int(round(float(normalized["end"]) * 1000))
                    except (TypeError, ValueError):
                        pass
                    normalized_words.append(normalized)
                segments.append(
                    {
                        "segment_id": f"A{index:03d}",
                        "start_ms": max(0, int(round(start * 1000))),
                        "end_ms": min(probe["duration_us"] // 1000, int(round(end * 1000))),
                        "text": text,
                        "speaker": str(item.get("speaker") or "source_speaker"),
                        "confidence": float(item.get("confidence")) if item.get("confidence") is not None else None,
                        "words": normalized_words,
                    }
                )
            duration_ms = max(1, probe["duration_us"] // 1000)
            if probe["has_audio"]:
                raw_silence = self.silence_detector(wav) if self.silence_detector is not None else _default_silence_detector(wav, ffmpeg_bin=self.ffmpeg_bin)
                silence = _normalise_silence_windows(raw_silence)
                for item in silence:
                    item["end_ms"] = min(duration_ms, int(item["end_ms"]))
                    item["start_ms"] = min(item["start_ms"], item["end_ms"])
            else:
                silence = [{"start_ms": 0, "end_ms": duration_ms, "kind": "acoustic_silence", "semantic_meaning": "no_audio_stream"}]
            audio_events: list[dict[str, Any]] = []
            meaningful_silence: list[dict[str, Any]] = []
            audio_event_backend_evidence: Mapping[str, Any] | None = None
            if self.audio_event_classifier is not None and probe["has_audio"]:
                classifier = getattr(self.audio_event_classifier, "classify", None)
                if not callable(classifier):
                    classifier = self.audio_event_classifier
                try:
                    classifier_result = classifier(
                        wav,
                        segments=segments,
                        silence_windows=silence,
                        duration_ms=duration_ms,
                    )
                except TypeError:
                    classifier_result = classifier(wav)
                if isinstance(classifier_result, Mapping):
                    raw_events = classifier_result.get("events")
                    classified = [dict(item) for item in raw_events if isinstance(item, Mapping)] if isinstance(raw_events, list) else []
                    if self.production:
                        audio_event_backend_evidence = _validate_bound_model_receipt(
                            classifier_result.get("evidence"),
                            identity=self._audio_event_backend_identity or {},
                            input_sha256=wav_sha256,
                            payload=classified,
                            payload_digest_field="events_sha256",
                            label="audio event",
                        )
                else:
                    if self.production:
                        raise CapabilityUnavailable("production audio event backend must return events plus evidence")
                    classified = classifier_result if isinstance(classifier_result, Sequence) else []
                for item in classified or []:
                    if not isinstance(item, Mapping):
                        continue
                    event = dict(item)
                    try:
                        event["start_ms"] = int(round(float(event.get("start_ms", event.get("start", 0)))))
                        event["end_ms"] = int(round(float(event.get("end_ms", event.get("end", 0)))))
                    except (TypeError, ValueError):
                        continue
                    if event["end_ms"] <= event["start_ms"]:
                        continue
                    if self.production and not (0 <= event["start_ms"] < event["end_ms"] <= duration_ms):
                        raise CapabilityUnavailable(
                            "production audio event classifier returned out-of-range timing",
                            details={"event": event.get("event_id")},
                        )
                    if self.production and not str(event.get("kind") or "").strip():
                        raise CapabilityUnavailable(
                            "production audio event classifier returned an event without kind",
                            details={"event": event.get("event_id")},
                        )
                    audio_events.append(event)
                    if str(event.get("kind") or "").lower() == "silence" and event.get("meaningful") is True:
                        meaningful_silence.append(event)
            return {
                "status": "ready",
                "audio_contract": {
                    "schema_version": "audio-contract/v1",
                    "source_duration_ms": duration_ms,
                    "source_audio_sha256": wav_sha256,
                    "segments": segments,
                    "silence_windows": silence,
                    "meaningful_silence": meaningful_silence,
                    "audio_events": audio_events,
                    "asr_backend_evidence": dict(asr_backend_evidence or {}),
                    "audio_event_backend_evidence": dict(audio_event_backend_evidence or {}),
                    "language": detected_language,
                    "speaker_policy": "source_speaker_role_only",
                    "provenance": {"engine": "injected" if self.transcriber is not None else ("openai-whisper" if probe["has_audio"] else "none"), "model": self.model_name if self.transcriber is None and probe["has_audio"] else None},
                },
            }


class BundledAppStoreEvidenceParser:
    """Execute the bundled official App Store/Google Play parser stage.

    ``parse_app_store_evidence`` remains an existing evidence stage rather than
    a new capability or approval.  This adapter gives deployed workers a
    package-relative implementation: it consumes the fixed ``app_store_url``
    slot, runs the bundled parser once, verifies every downloaded screenshot
    against the emitted bundle, and publishes immutable artifacts for the
    following ``resolve_ui_evidence`` stage.
    """

    def __init__(
        self,
        *,
        python_bin: str | None = None,
        timeout_seconds: float = 180.0,
        parser_script: Path | None = None,
    ) -> None:
        try:
            timeout_seconds = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("App Store parser timeout_seconds must be positive") from exc
        if timeout_seconds <= 0:
            raise ValueError("App Store parser timeout_seconds must be positive")
        self.python_bin = python_bin or sys.executable
        self.timeout_seconds = timeout_seconds
        self.parser_script = (
            Path(parser_script).resolve()
            if parser_script is not None
            else Path(__file__).resolve().parents[1]
            / "bundled-skills"
            / "parse-app-store-evidence"
            / "scripts"
            / "parse_app_store.py"
        )

    @staticmethod
    def _url_from_context(context: Any) -> str:
        for slot in getattr(context, "input_slots", ()) or ():
            if not isinstance(slot, Mapping) or str(slot.get("slot_id") or "") != "app_store_url":
                continue
            if not slot.get("present"):
                break
            values = slot.get("values") or []
            if isinstance(values, str):
                values = [values]
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)) and values:
                url = str(values[0] or "").strip()
                if url:
                    return url
        raise CapabilityUnavailable(
            "parse_app_store_evidence requires a populated app_store_url slot"
        )

    @staticmethod
    def _safe_media_path(root: Path, relative: Any) -> Path:
        value = str(relative or "").strip()
        if not value:
            raise CapabilityUnavailable("App Store evidence media record has no file_path")
        candidate = (root / value).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise CapabilityUnavailable(
                "App Store evidence media path escapes the parser output directory"
            ) from exc
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            raise CapabilityUnavailable(
                "App Store evidence media file is missing or empty",
                details={"file_path": value},
            )
        return candidate

    def run(
        self,
        *,
        context: Any,
        input_artifacts: list[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        del input_artifacts
        if hasattr(context, "timeline_regions") and not _has_generated_ui_region(context):
            return {
                "status": "skipped",
                "skipped_reason": "no_generated_ui_region",
            }
        url = self._url_from_context(context)
        work_dir = Path(getattr(context, "work_dir", tempfile.gettempdir())).resolve()
        output_dir = work_dir / "app_store"
        output_dir.mkdir(parents=True, exist_ok=True)
        if not self.parser_script.is_file():
            raise CapabilityUnavailable(
                "bundled App Store evidence parser is unavailable",
                details={"parser_script": str(self.parser_script)},
            )
        command = [
            str(self.python_bin),
            str(self.parser_script),
            url,
            "--output-dir",
            str(output_dir),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CapabilityUnavailable(
                "App Store evidence parser execution failed"
            ) from exc
        if result.returncode != 0:
            raise CapabilityUnavailable(
                "App Store evidence parser rejected the official URL or page",
                details={"stderr": str(result.stderr or "")[-2000:]},
            )
        bundle_path = output_dir / "app_store_evidence_bundle.json"
        if not bundle_path.is_file():
            raise CapabilityUnavailable("App Store parser produced no evidence bundle")
        try:
            bundle_bytes = bundle_path.read_bytes()
            bundle = json.loads(bundle_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CapabilityUnavailable("App Store parser bundle is not valid UTF-8 JSON") from exc
        if not isinstance(bundle, Mapping) or bundle.get("contract") != "app-store-evidence" or bundle.get("contract_version") != 1:
            raise CapabilityUnavailable("App Store parser returned an unsupported evidence bundle")
        bundle_sha256 = _sha256_bytes(bundle_bytes)
        publisher = getattr(context, "publish_artifact", None)
        if not callable(publisher):
            raise CapabilityUnavailable(
                "App Store evidence parser requires immutable artifact publication"
            )
        published: list[Mapping[str, Any]] = []
        published.append(
            publisher(
                kind="app_store_evidence",
                stream=io.BytesIO(bundle_bytes),
                content_type="application/json",
                expected_sha256=bundle_sha256,
                metadata={
                    "producer_stage": "parse_app_store_evidence",
                    "bundle_sha256": bundle_sha256,
                    "store_app_id": str(bundle.get("store_app_id") or ""),
                    "pixel_truth_mode": str(bundle.get("pixel_truth_mode") or ""),
                },
            )
        )

        screenshots = bundle.get("screenshots") or []
        if not isinstance(screenshots, list):
            raise CapabilityUnavailable("App Store evidence screenshots must be an array")
        for item in screenshots:
            if not isinstance(item, Mapping):
                raise CapabilityUnavailable("App Store screenshot evidence record is invalid")
            path = self._safe_media_path(output_dir, item.get("file_path"))
            actual_sha256 = _sha256_file(path)
            declared_sha256 = str(item.get("sha256") or "").lower()
            if declared_sha256 != actual_sha256:
                raise CapabilityUnavailable(
                    "App Store screenshot SHA-256 does not match the parser bundle",
                    details={"file_path": str(item.get("file_path") or "")},
                )
            published.append(
                publisher(
                    kind="app_store_screenshot",
                    stream=io.BytesIO(path.read_bytes()),
                    content_type=str(item.get("content_type") or "image/png"),
                    expected_sha256=actual_sha256,
                    metadata={
                        "producer_stage": "parse_app_store_evidence",
                        "bundle_sha256": bundle_sha256,
                        "truth_basis": "parsed-app-store-evidence",
                        "store_app_id": str(bundle.get("store_app_id") or ""),
                        "store_media_ordinal": item.get("store_media_ordinal"),
                        "source_url": str(item.get("source_url") or ""),
                        "width": item.get("width"),
                        "height": item.get("height"),
                    },
                )
            )
        return {
            "status": "ready",
            "evidence_bundle": dict(bundle),
            "evidence_bundle_sha256": bundle_sha256,
            "published_artifacts": [dict(item) for item in published],
        }


def _normalise_text(value: str) -> str:
    return " ".join(str(value or "").replace("\u200b", "").split()).casefold()


class DeterministicUiRenderer:
    """Render and verify target-owned UI without sending UI pixels to Seedance."""

    def __init__(
        self,
        *,
        ocr_backend: Any | None = None,
        render_backend: Callable[[Path, Path, Any], Any] | None = None,
        expected_text: Sequence[str] | None = None,
        expected_layout: Sequence[Mapping[str, Any]] | None = None,
        allow_self_consistency: bool = False,
        tesseract_bin: str | None = None,
        case_sensitive: bool | None = None,
        implementation: str = "server.real_capabilities:DeterministicUiRenderer",
        version: str = "1.0.0",
        sha256: str | None = None,
        production: bool = False,
        require_explicit_digest: bool | None = None,
        app_evidence_artifact_kind: str = "app_store_screenshot",
    ) -> None:
        self.ocr_backend = ocr_backend
        self.render_backend = render_backend
        self.expected_text = list(expected_text or [])
        self.expected_layout = [dict(item) for item in (expected_layout or [])]
        self.allow_self_consistency = allow_self_consistency
        self.tesseract_bin = tesseract_bin
        self.production = bool(production)
        self.case_sensitive = self.production if case_sensitive is None else bool(case_sensitive)
        self.app_evidence_artifact_kind = app_evidence_artifact_kind
        if self.production and allow_self_consistency:
            raise ValueError("production UI renderer cannot enable self consistency")
        self._identity = _identity("ocr_ui_renderer", implementation, version, sha256, require_explicit_digest=self.production if require_explicit_digest is None else require_explicit_digest)
        if self.production and ocr_backend is None:
            raise ValueError("production requires an evidence-bound OCR backend; implicit Tesseract fallback is not model-pinned")
        self._ocr_backend_identity = (
            _evidence_backend_identity(ocr_backend, method="recognize", label="OCR")
            if self.production and ocr_backend is not None
            else None
        )
        if self.production and render_backend is not None:
            self._render_backend_identity = _component_identity(render_backend, label="UI render backend")
        elif render_backend is None:
            self._render_backend_identity = {
                "implementation": "server.real_capabilities:png-normalizer",
                "version": "1.0.0",
                "sha256": _sha256_bytes(b"server.real_capabilities:png-normalizer@1.0.0"),
            }
        else:
            self._render_backend_identity = None
        self._capability_identity = _composite_identity(
            self._identity,
            {
                "ocr_backend": self._ocr_backend_identity or {"mode": "development"},
                "render_backend": self._render_backend_identity or {"mode": "development"},
            },
        )

    def replace_render_backend(self, render_backend: Callable[[Path, Path, Any], Any]) -> None:
        """Replace the injected video backend before worker startup.

        Deployment composition may wrap the existing deterministic renderer in
        a strictly conditional candidate (for example the restricted Remotion
        UI adapter).  Recompute the public capability identity at that boundary
        so the startup manifest and every later receipt bind the backend that
        will actually receive rendered UI work.
        """

        if not callable(render_backend):
            raise ValueError("UI render backend must be callable")
        render_identity = (
            _component_identity(render_backend, label="UI render backend")
            if self.production
            else None
        )
        self.render_backend = render_backend
        self._render_backend_identity = render_identity
        self._capability_identity = _composite_identity(
            self._identity,
            {
                "ocr_backend": self._ocr_backend_identity or {"mode": "development"},
                "render_backend": self._render_backend_identity or {"mode": "development"},
            },
        )

    def validate_production_readiness(self) -> None:
        """Fail closed before a production worker can claim a generated-UI run.

        A static screenshot normalizer is retained for legacy/local compatibility,
        but it is not a production implementation of the generated UI route.
        The deployment capability gate calls this method for the concrete
        renderer so a missing video renderer is discovered at startup rather
        than after a paid or irreversible stage begins.
        """

        if not self.production:
            return None
        if self.render_backend is None:
            raise ValueError(
                "production generated UI requires a real video render backend"
            )
        if not callable(self.render_backend):
            raise ValueError("production generated UI render backend must be callable")
        if not callable(getattr(self.render_backend, "capability_identity", None)):
            raise ValueError(
                "production generated UI render backend requires capability_identity()"
            )
        return None

    def capability_identity(self) -> Mapping[str, Any]:
        return dict(self._capability_identity)

    @contextmanager
    def _ui_source(self, context: Any):
        slots = getattr(context, "input_slots", ())
        present = {str(item.get("slot_id")): item for item in slots if isinstance(item, Mapping) and item.get("present")}
        artifacts = getattr(context, "artifacts", ())
        evidence = next(
            (item for item in artifacts if isinstance(item, Mapping) and str(item.get("kind") or "") == self.app_evidence_artifact_kind),
            None,
        )
        if "app_store_url" in present and evidence is not None:
            materialize = getattr(context, "materialize_artifact", None)
            if not callable(materialize):
                raise CapabilityUnavailable("parsed App evidence artifact cannot be materialized")
            with materialize(self.app_evidence_artifact_kind) as media:
                yield Path(media.path), "app_store_evidence", dict(evidence.get("metadata") or {})
            return
        if "ui_screenshot" in present:
            with _materialize(context, "ui_screenshot") as media:
                metadata = present["ui_screenshot"].get("metadata") or []
                record = metadata[0] if metadata and isinstance(metadata[0], Mapping) else {}
                yield Path(media.path), "ui_screenshot", dict(record)
            return
        if "app_store_url" in present:
            raise CapabilityUnavailable("UI renderer requires parsed App evidence artifact, not a raw URL")
        raise CapabilityUnavailable("generated UI route has no ui_screenshot input")

    def _ocr(self, path: Path) -> Any:
        if self.ocr_backend is not None:
            recognize = getattr(self.ocr_backend, "recognize", None)
            return recognize(path) if callable(recognize) else self.ocr_backend(path)
        tesseract = self.tesseract_bin or shutil.which("tesseract")
        if not tesseract:
            raise CapabilityUnavailable("no OCR backend is configured", details={"required": "ocr_backend or tesseract"})
        result = _run([tesseract, str(path), "stdout", "--psm", "6", "tsv"])
        if result.returncode != 0:
            raise CapabilityUnavailable("OCR backend failed", details={"stderr": result.stderr[-1000:]})
        rows: list[dict[str, Any]] = []
        lines = result.stdout.splitlines()
        for line in lines[1:]:
            fields = line.split("\t")
            if len(fields) < 12 or not fields[11].strip():
                continue
            try:
                left, top, width, height, confidence = (int(fields[6]), int(fields[7]), int(fields[8]), int(fields[9]), float(fields[10]))
            except (TypeError, ValueError):
                continue
            rows.append({"text": fields[11].strip(), "bbox": [left, top, left + width, top + height], "confidence": confidence / 100.0})
        return rows

    @staticmethod
    def _records(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, str):
            return [{"text": value}]
        if isinstance(value, Mapping):
            if "text" in value:
                return [dict(value)]
            return []
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
            result: list[dict[str, Any]] = []
            for item in value:
                result.extend(DeterministicUiRenderer._records(item))
            return result
        return []

    @staticmethod
    def _bbox_iou(left: Sequence[Any], right: Sequence[Any]) -> float:
        try:
            lx1, ly1, lx2, ly2 = [float(value) for value in left[:4]]
            rx1, ry1, rx2, ry2 = [float(value) for value in right[:4]]
        except (TypeError, ValueError, IndexError):
            return 0.0
        ix1, iy1, ix2, iy2 = max(lx1, rx1), max(ly1, ry1), min(lx2, rx2), min(ly2, ry2)
        intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1) + max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1) - intersection
        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _truth_from_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        """Return target-owned UI truth, never renderer-produced truth.

        The source slot metadata is the authority for generated UI.  A
        renderer may echo this object so that a remote service can consume it,
        but it cannot create or revise the object.  App evidence parsers and
        upload intake currently use either ``ui_truth_card`` or the compact
        ``expected_text``/``expected_layout`` form; both are accepted here.
        """

        if not isinstance(metadata, Mapping):
            return None
        direct = metadata.get("ui_truth_card") or metadata.get("truth_card")
        if isinstance(direct, Mapping):
            return deepcopy(dict(direct))
        if isinstance(metadata.get("states"), list):
            value: dict[str, Any] = {"states": deepcopy(list(metadata["states"]))}
            if isinstance(metadata.get("approved_copy"), list):
                value["approved_copy"] = deepcopy(list(metadata["approved_copy"]))
            return value
        expected_text = metadata.get("expected_text") or metadata.get("ui_text")
        expected_layout = metadata.get("expected_layout")
        if isinstance(expected_text, str):
            expected_text = [expected_text]
        if isinstance(expected_text, list) and isinstance(expected_layout, Sequence) and not isinstance(
            expected_layout, (str, bytes, bytearray)
        ):
            return {
                "expected_text": [str(item) for item in expected_text],
                "expected_layout": [dict(item) for item in expected_layout if isinstance(item, Mapping)],
            }
        return None

    @staticmethod
    def _contract_from_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        if not isinstance(metadata, Mapping):
            return None
        direct = metadata.get("ui_render_contract") or metadata.get("render_contract")
        return deepcopy(dict(direct)) if isinstance(direct, Mapping) else None

    def _derive_truth_from_source(
        self,
        *,
        source: Path,
        slot: str,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], str]:
        """Freeze target UI truth from the uploaded/parsed screenshot itself.

        Fixed input slots intentionally carry only media bytes, not caller-authored
        truth metadata.  In an active generated-UI route the first evidence
        boundary therefore derives a one-state truth card with the independent
        OCR backend.  The renderer receives this frozen card, but cannot create
        or revise it.  Multi-state cards may still be supplied by a deployment
        evidence builder; this fallback makes the public screenshot/App URL
        routes executable without adding a slot or approval.
        """

        try:
            source_sha256 = _sha256_file(source)
            from PIL import Image

            with Image.open(source) as image:
                viewport = [int(image.width), int(image.height)]
        except (OSError, ValueError) as exc:
            raise CapabilityUnavailable(
                "target UI evidence cannot be decoded as an image"
            ) from exc

        raw_ocr = self._ocr(source)
        records_value = raw_ocr
        backend_evidence: Mapping[str, Any] | None = None
        if isinstance(raw_ocr, Mapping) and "records" in raw_ocr:
            records_value = raw_ocr.get("records")
            evidence = raw_ocr.get("evidence")
            if isinstance(evidence, Mapping):
                backend_evidence = dict(evidence)
        records = self._records(records_value)
        if self.production:
            self._validate_generated_ui_ocr_evidence(
                backend_evidence,
                input_sha256=source_sha256,
                records=records,
            )

        expected_text: list[str] = []
        expected_layout: list[dict[str, Any]] = []
        width, height = viewport
        for index, item in enumerate(records, start=1):
            text = str(item.get("text") or "").strip()
            if not text or self._contains_garbled_text(text):
                raise ReplicationError(
                    "UI_OCR_MISMATCH",
                    "target UI evidence contains empty or garbled text",
                    category="quality",
                    user_action_required=True,
                    details={"source_sha256": source_sha256, "text": text},
                    http_status=422,
                )
            bbox = item.get("bbox")
            if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes, bytearray)) or len(bbox) < 4:
                raise CapabilityUnavailable(
                    "target UI OCR evidence requires a four-coordinate bounding box"
                )
            try:
                x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
            except (TypeError, ValueError) as exc:
                raise CapabilityUnavailable(
                    "target UI OCR evidence bounding boxes must be numeric"
                ) from exc
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise CapabilityUnavailable(
                    "target UI OCR evidence bounding box lies outside the source image"
                )
            expected_text.append(text)
            expected_layout.append(
                {
                    "element_id": f"text-{index:03d}",
                    "role": "text",
                    "text": text,
                    "bbox": [x1, y1, x2, y2],
                }
            )

        basis = "parsed-app-store-evidence" if slot == "app_store_evidence" else "target-owned-upload"
        truth = {
            "schema_version": "ui-truth-card/v1",
            "truth_basis": basis,
            "source_sha256": source_sha256,
            "approved_copy": list(expected_text),
            "states": [
                {
                    "state_id": "state-001",
                    "frame_ms": 0,
                    "expected_text": list(expected_text),
                    "expected_layout": expected_layout,
                }
            ],
            "derivation": {
                "method": "independent_ocr",
                "evidence": dict(backend_evidence or {}),
            },
        }
        contract = {
            "schema_version": "ui-render-contract/v1",
            "route": "generated_ui_demo",
            "viewport": list(viewport),
            "rendered_viewport": list(viewport),
            "state_sequence": ["state-001"],
            "navigation": [],
            "animation_qc": {"samples_per_interval": 1},
            "truth_source_sha256": source_sha256,
        }
        return truth, contract, basis

    def _resolve_target_truth(
        self,
        *,
        context: Any,
        source_metadata: Mapping[str, Any],
        source: Path,
        slot: str,
    ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None, str]:
        """Resolve immutable truth from the uploaded screenshot/App evidence.

        In an active route, an absent target truth is a contract error.  The
        renderer response is deliberately not considered a fallback.  This
        prevents a renderer from silently inventing copy/layout and then
        self-verifying the invented result.
        """

        candidates: list[Mapping[str, Any]] = [source_metadata]
        # Only the immutable slot descriptor may be a secondary source.  Do
        # not search timeline/generated-media metadata: those records can be
        # produced after rendering and therefore cannot become UI truth.
        for item in getattr(context, "input_slots", ()) or ():
            if not isinstance(item, Mapping) or str(item.get("slot_id") or "") != slot:
                continue
            metadata = item.get("metadata")
            if isinstance(metadata, Sequence) and not isinstance(metadata, (str, bytes, bytearray)):
                for record in metadata:
                    if isinstance(record, Mapping):
                        candidates.append(record)
            elif isinstance(metadata, Mapping):
                candidates.append(metadata)

        truth: Mapping[str, Any] | None = None
        contract: Mapping[str, Any] | None = None
        basis = ""
        declared_digest = ""
        truth_metadata: Mapping[str, Any] = source_metadata
        for metadata in candidates:
            candidate_truth = self._truth_from_metadata(metadata)
            if candidate_truth is not None:
                truth = candidate_truth
                truth_metadata = metadata
                contract = self._contract_from_metadata(metadata) or contract
                basis = str(
                    metadata.get("truth_basis")
                    or metadata.get("ui_truth_basis")
                    or candidate_truth.get("truth_basis")
                    or ""
                ).strip().lower()
                declared_digest = str(
                    metadata.get("ui_truth_card_sha256")
                    or metadata.get("truth_sha256")
                    or ""
                ).strip().lower()
                break

        if truth is None:
            if self.production and _active_high_fidelity(context):
                # The fixed public slots contain bytes/URLs only.  Derive the
                # immutable one-state truth card at this evidence boundary so
                # screenshot-only and parsed-App routes can execute without
                # trusting renderer-authored copy or layout.
                return self._derive_truth_from_source(source=source, slot=slot)
            return None, contract, basis

        allowed_basis = {
            "target-owned-upload",
            "user-ui-screenshot",
            "parsed-app-store-evidence",
            "official-app-evidence",
        }
        if self.production and basis and basis not in allowed_basis:
            raise CapabilityUnavailable(
                "generated UI truth provenance must be the uploaded screenshot or official App evidence"
            )
        if self.production and not basis:
            # Older intake manifests did not persist a basis label.  The fixed
            # slot itself still identifies the authority; renderer-authored
            # labels are never accepted as a fallback.
            basis = "parsed-app-store-evidence" if slot == "app_store_evidence" else "target-owned-upload"
        if self.production and declared_digest:
            if declared_digest != _canonical_sha256(truth):
                raise CapabilityUnavailable("target UI truth SHA-256 does not match the frozen evidence")
        source_sha = _sha256_file(source)
        declared_source_sha = str(
            truth_metadata.get("source_sha256")
            or truth_metadata.get("ui_source_sha256")
            or truth_metadata.get("evidence_sha256")
            or ""
        ).strip().lower()
        if self.production and declared_source_sha and declared_source_sha != source_sha:
            raise CapabilityUnavailable("target UI truth source SHA-256 does not match uploaded evidence")
        return truth, contract, basis or ("parsed-app-store-evidence" if slot == "app_store_evidence" else "target-owned-upload")

    @staticmethod
    def _invoke_video_renderer(
        renderer: Callable[..., Any],
        source: Path,
        output: Path,
        context: Any,
        *,
        truth: Mapping[str, Any] | None,
        render_contract: Mapping[str, Any] | None,
    ) -> Any:
        """Call old and new renderer adapters without weakening the contract."""

        try:
            signature = inspect.signature(renderer)
            parameters = signature.parameters
        except (TypeError, ValueError):
            parameters = {}
        kwargs: dict[str, Any] = {}
        if "truth" in parameters:
            kwargs["truth"] = truth
        if "render_contract" in parameters:
            kwargs["render_contract"] = render_contract
        return renderer(source, output, context, **kwargs)

    @staticmethod
    def _animation_sample_times(
        states: Sequence[Mapping[str, Any]],
        duration_ms: int,
        render_contract: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        policy = render_contract.get("animation_qc")
        policy = policy if isinstance(policy, Mapping) else {}
        raw_count = policy.get("samples_per_interval", 2)
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 2
        count = max(1, min(count, 8))
        pair_count = max(0, len(states) - 1)
        if pair_count > 64:
            raise CapabilityUnavailable(
                "generated UI state sequence exceeds the 64-interval animation QC limit"
            )
        if pair_count:
            # Keep independent OCR deployable at scale while retaining at
            # least one sample in every transition interval.
            count = min(count, max(1, 64 // pair_count))
        intervals: list[dict[str, Any]] = []
        for left, right in zip(states, states[1:]):
            start_ms = int(left.get("frame_ms"))
            end_ms = int(right.get("frame_ms"))
            gap = end_ms - start_ms
            if gap <= 1:
                continue
            samples = [
                start_ms + int(round(gap * position / float(count + 1)))
                for position in range(1, count + 1)
            ]
            samples = sorted({value for value in samples if 0 <= value < duration_ms})
            if samples:
                intervals.append(
                    {
                        "from_state_id": str(left.get("state_id") or ""),
                        "to_state_id": str(right.get("state_id") or ""),
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "sample_times_ms": samples,
                    }
                )
        return intervals

    @staticmethod
    def _contains_garbled_text(value: str) -> bool:
        # U+FFFD is the Unicode replacement glyph.  White boxes, control
        # characters, and common OCR mojibake markers are equally unsafe in a
        # final UI animation even when the state-frame OCR happened to pass.
        if any(char in value for char in ("\ufffd", "\u25a1")):
            return True
        return any(ord(char) < 32 and char not in "\t\n\r" for char in value)

    def _validate_animation_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        states: Sequence[Mapping[str, Any]],
        video_width: int,
        video_height: int,
        scale_x: float,
        scale_y: float,
        frame_ms: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        expected_text: list[str] = []
        expected_by_text: dict[str, list[Sequence[Any]]] = {}
        state_layouts: list[tuple[int, dict[str, Sequence[Any]]]] = []

        def normalize(value: Any) -> str:
            return " ".join(str(value or "").replace("\u200b", "").split()).casefold()

        for state in states:
            for value in state.get("expected_text", []) if isinstance(state.get("expected_text"), list) else []:
                normalized = normalize(value)
                if normalized and normalized not in expected_text:
                    expected_text.append(normalized)
            layout = state.get("expected_layout")
            state_frame_ms = int(state.get("frame_ms") or 0)
            state_boxes: dict[str, Sequence[Any]] = {}
            if not isinstance(layout, list):
                state_layouts.append((state_frame_ms, state_boxes))
                continue
            for item in layout:
                if not isinstance(item, Mapping):
                    continue
                label = normalize(item.get("text"))
                bbox = item.get("bbox")
                if label and isinstance(bbox, Sequence) and not isinstance(bbox, (str, bytes, bytearray)):
                    expected_by_text.setdefault(label, []).append(bbox)
                    state_boxes.setdefault(label, bbox)
            state_layouts.append((state_frame_ms, state_boxes))
        state_layouts.sort(key=lambda item: item[0])

        if not records:
            raise ReplicationError(
                "UI_ANIMATION_TEXT_UNREADABLE",
                "generated UI animation interval contains no independently readable text",
                category="quality",
                user_action_required=True,
                details={"frame_ms": frame_ms},
                http_status=422,
            )
        observed: list[dict[str, Any]] = []
        layout_records: list[dict[str, Any]] = []
        for item in records:
            if not isinstance(item, Mapping):
                raise ReplicationError(
                    "UI_ANIMATION_TEXT_UNREADABLE",
                    "generated UI animation OCR returned a malformed record",
                    category="quality",
                    user_action_required=True,
                    details={"frame_ms": frame_ms},
                    http_status=422,
                )
            text = str(item.get("text") or "").strip()
            normalized = normalize(text)
            if not normalized or self._contains_garbled_text(text):
                raise ReplicationError(
                    "UI_ANIMATION_TEXT_UNREADABLE",
                    "generated UI animation contains garbled or replacement text",
                    category="quality",
                    user_action_required=True,
                    details={"frame_ms": frame_ms, "text": text},
                    http_status=422,
                )
            if expected_text and normalized not in expected_text:
                raise ReplicationError(
                    "UI_ANIMATION_TEXT_UNREADABLE",
                    "generated UI animation contains text outside target truth",
                    category="quality",
                    user_action_required=True,
                    details={"frame_ms": frame_ms, "text": text, "expected": expected_text},
                    http_status=422,
                )
            confidence = item.get("confidence")
            if self.production and confidence is not None:
                try:
                    if float(confidence) < 0.5:
                        raise ValueError
                except (TypeError, ValueError):
                    raise ReplicationError(
                        "UI_ANIMATION_TEXT_UNREADABLE",
                        "generated UI animation OCR confidence is below the readability threshold",
                        category="quality",
                        user_action_required=True,
                        details={"frame_ms": frame_ms, "text": text, "confidence": confidence},
                        http_status=422,
                    )
            bbox = item.get("bbox")
            if not isinstance(bbox, Sequence) or isinstance(bbox, (str, bytes, bytearray)) or len(bbox) < 4:
                raise ReplicationError(
                    "UI_ANIMATION_LAYOUT_MISMATCH",
                    "generated UI animation OCR record has no valid layout bounds",
                    category="quality",
                    user_action_required=True,
                    details={"frame_ms": frame_ms, "text": text},
                    http_status=422,
                )
            try:
                x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
            except (TypeError, ValueError):
                raise ReplicationError(
                    "UI_ANIMATION_LAYOUT_MISMATCH",
                    "generated UI animation layout bounds are not numeric",
                    category="quality",
                    user_action_required=True,
                    details={"frame_ms": frame_ms, "text": text, "bbox": list(bbox[:4])},
                    http_status=422,
                )
            if not (0 <= x1 < x2 <= video_width and 0 <= y1 < y2 <= video_height):
                raise ReplicationError(
                    "UI_ANIMATION_LAYOUT_MISMATCH",
                    "generated UI animation layout leaves the rendered viewport",
                    category="quality",
                    user_action_required=True,
                    details={"frame_ms": frame_ms, "text": text, "bbox": [x1, y1, x2, y2]},
                    http_status=422,
                )
            expected_boxes = expected_by_text.get(normalized, [])
            if expected_boxes:
                # During a transition the element may move/fade, so use a
                # tolerant size bound rather than requiring state-frame IoU.
                observed_area = max(1.0, (x2 - x1) * (y2 - y1))
                candidate_areas = []
                for expected_bbox in expected_boxes:
                    try:
                        ex1, ey1, ex2, ey2 = [float(value) * factor for value, factor in zip(expected_bbox[:4], (scale_x, scale_y, scale_x, scale_y))]
                    except (TypeError, ValueError, IndexError):
                        continue
                    candidate_areas.append(max(1.0, (ex2 - ex1) * (ey2 - ey1)))
                if candidate_areas and not any(0.25 <= observed_area / area <= 4.0 for area in candidate_areas):
                    raise ReplicationError(
                        "UI_ANIMATION_LAYOUT_MISMATCH",
                        "generated UI animation text geometry changes beyond target layout bounds",
                        category="quality",
                        user_action_required=True,
                        details={"frame_ms": frame_ms, "text": text, "bbox": [x1, y1, x2, y2]},
                        http_status=422,
                    )
                # Compare position against the linearly interpolated target
                # geometry between the surrounding truth states.  This catches
                # a text layer that remains technically inside the viewport
                # but jumps to an unrelated location during the transition.
                before = None
                after = None
                for state_frame_ms, state_boxes in state_layouts:
                    if state_frame_ms <= frame_ms and normalized in state_boxes:
                        before = (state_frame_ms, state_boxes[normalized])
                    if state_frame_ms >= frame_ms and normalized in state_boxes:
                        after = (state_frame_ms, state_boxes[normalized])
                        break
                if before is None and after is not None:
                    before = after
                if after is None and before is not None:
                    after = before
                if before is not None and after is not None:
                    try:
                        before_ms, before_bbox = before
                        after_ms, after_bbox = after
                        before_scaled = [
                            float(value) * factor
                            for value, factor in zip(before_bbox[:4], (scale_x, scale_y, scale_x, scale_y))
                        ]
                        after_scaled = [
                            float(value) * factor
                            for value, factor in zip(after_bbox[:4], (scale_x, scale_y, scale_x, scale_y))
                        ]
                        alpha = (
                            0.0
                            if after_ms <= before_ms
                            else max(0.0, min(1.0, (frame_ms - before_ms) / float(after_ms - before_ms)))
                        )
                        expected_center_x = (
                            before_scaled[0] + (after_scaled[0] - before_scaled[0]) * alpha
                            + before_scaled[2] + (after_scaled[2] - before_scaled[2]) * alpha
                        ) / 2.0
                        expected_center_y = (
                            before_scaled[1] + (after_scaled[1] - before_scaled[1]) * alpha
                            + before_scaled[3] + (after_scaled[3] - before_scaled[3]) * alpha
                        ) / 2.0
                        observed_center_x = (x1 + x2) / 2.0
                        observed_center_y = (y1 + y2) / 2.0
                        if (
                            abs(observed_center_x - expected_center_x) > video_width * 0.25
                            or abs(observed_center_y - expected_center_y) > video_height * 0.25
                        ):
                            raise ReplicationError(
                                "UI_ANIMATION_LAYOUT_MISMATCH",
                                "generated UI animation text jumps outside interpolated target layout",
                                category="quality",
                                user_action_required=True,
                                details={"frame_ms": frame_ms, "text": text, "bbox": [x1, y1, x2, y2]},
                                http_status=422,
                            )
                    except (TypeError, ValueError, IndexError):
                        raise ReplicationError(
                            "UI_ANIMATION_LAYOUT_MISMATCH",
                            "generated UI animation truth layout cannot be interpolated",
                            category="quality",
                            user_action_required=True,
                            details={"frame_ms": frame_ms, "text": text},
                            http_status=422,
                        )
            observed_item = dict(item)
            observed_item["text"] = text
            observed.append(observed_item)
            layout_records.append(observed_item)
        return observed, layout_records

    def _render_active_generated_ui_video(
        self,
        *,
        context: Any,
        source: Path,
        source_metadata: Mapping[str, Any],
        slot: str,
    ) -> Mapping[str, Any]:
        """Accept only a real multi-state video plus frame-bound evidence.

        The render backend owns deterministic UI animation.  This boundary
        rejects the historical single-PNG/summary-score route.  The downstream
        timeline validator independently decodes every declared state frame;
        consequently the OCR input hash may describe encoded OCR bytes while
        ``decoded_frame_sha256`` remains bound to the raw decoded frame.
        """

        if self.render_backend is None:
            raise CapabilityUnavailable(
                "active generated UI requires a real video render backend and state_evidence; single PNG normalization is forbidden"
            )
        output = Path(getattr(context, "work_dir", tempfile.gettempdir())) / "generated-ui.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        target_truth, target_contract, truth_basis = self._resolve_target_truth(
            context=context,
            source_metadata=source_metadata,
            source=source,
            slot=slot,
        )
        rendered = self._invoke_video_renderer(
            self.render_backend,
            source,
            output,
            context,
            # The renderer receives a disposable copy.  Even an in-process
            # adapter that mutates its arguments cannot change the authority
            # retained by this stage.
            truth=deepcopy(dict(target_truth)) if isinstance(target_truth, Mapping) else None,
            render_contract=deepcopy(dict(target_contract)) if isinstance(target_contract, Mapping) else None,
        )
        if not isinstance(rendered, Mapping):
            raise CapabilityUnavailable(
                "active generated UI render backend must return video and state_evidence"
            )
        raw_renderer_decision = rendered.get("ui_renderer_decision")
        if isinstance(raw_renderer_decision, Mapping):
            renderer_decision = deepcopy(dict(raw_renderer_decision))
            backend = str(renderer_decision.get("backend") or "")
            enabled = renderer_decision.get("enabled")
            reason = renderer_decision.get("reason")
            renderer_identity = renderer_decision.get("renderer_identity")
            if (
                backend not in {"ffmpeg", "remotion_react_ui"}
                or not isinstance(enabled, bool)
                or not isinstance(reason, str)
                or not reason
                or not isinstance(renderer_identity, Mapping)
                or not all(str(renderer_identity.get(field) or "") for field in ("implementation", "version", "sha256"))
            ):
                raise CapabilityUnavailable("generated UI renderer decision is incomplete")
        else:
            renderer_decision = {
                "backend": "ffmpeg",
                "enabled": False,
                "reason": "existing_deterministic_renderer",
                "renderer_identity": dict(self._render_backend_identity or self._identity),
            }
        candidate = rendered.get("video_path") or rendered.get("output_path") or output
        video_path = Path(candidate)
        if not video_path.is_file() or video_path.stat().st_size <= 0:
            raise CapabilityUnavailable("active generated UI renderer produced no video bytes")
        try:
            _probe(video_path)
        except CapabilityUnavailable as exc:
            raise CapabilityUnavailable("active generated UI output is not a valid video") from exc

        returned_truth = rendered.get("ui_truth_card")
        returned_contract = rendered.get("ui_render_contract")
        if target_truth is not None and returned_truth is not None and _canonical_sha256(returned_truth) != _canonical_sha256(target_truth):
            raise CapabilityUnavailable(
                "UI renderer cannot modify target-owned truth from the screenshot/App evidence"
            )
        if target_contract is not None and returned_contract is not None and _canonical_sha256(returned_contract) != _canonical_sha256(target_contract):
            raise CapabilityUnavailable(
                "UI renderer cannot modify the frozen target UI render contract"
            )
        truth = target_truth or returned_truth
        render_contract = target_contract or returned_contract
        report = rendered.get("ui_qc_report")
        if not isinstance(truth, Mapping) or not isinstance(render_contract, Mapping):
            raise CapabilityUnavailable(
                "active generated UI requires ui_truth_card and ui_render_contract"
            )
        # In an active production run, renderer-supplied OCR/QC is never
        # authoritative.  Rebuild it from decoded state frames with the
        # independently bound OCR backend; a renderer may still include a
        # report as non-authoritative debug metadata.
        if report is None or _active_high_fidelity(context):
            report = self._build_generated_ui_report_from_video(
                video_path=video_path,
                truth=truth,
                render_contract=render_contract,
                context=context,
            )
        elif not isinstance(report, Mapping):
            raise CapabilityUnavailable(
                "active generated UI ui_qc_report must be an object when supplied"
            )
        states = truth.get("states")
        if not isinstance(states, list) or not states:
            raise CapabilityUnavailable("active generated UI requires a non-empty target state sequence")
        state_ids: list[str] = []
        for index, state in enumerate(states, start=1):
            if not isinstance(state, Mapping):
                raise CapabilityUnavailable(f"generated UI truth state {index} must be an object")
            state_id = str(state.get("state_id") or "")
            if not state_id or state_id in state_ids:
                raise CapabilityUnavailable("generated UI truth states require unique state_id values")
            if isinstance(state.get("frame_ms"), bool) or not isinstance(state.get("frame_ms"), int):
                raise CapabilityUnavailable(f"generated UI truth state {state_id} requires integer frame_ms")
            if not isinstance(state.get("expected_text"), list) or not isinstance(state.get("expected_layout"), list):
                raise CapabilityUnavailable(f"generated UI truth state {state_id} requires expected text and layout")
            state_ids.append(state_id)
        if render_contract.get("state_sequence") != state_ids:
            raise CapabilityUnavailable("generated UI render state_sequence does not match target truth")
        evidence = report.get("state_evidence")
        if not isinstance(evidence, list) or [str(row.get("state_id") or "") for row in evidence if isinstance(row, Mapping)] != state_ids:
            raise CapabilityUnavailable("active generated UI requires one ordered state_evidence row per target state")
        for row in evidence:
            if not isinstance(row, Mapping):
                raise CapabilityUnavailable("generated UI state_evidence rows must be objects")
            raw_frame_sha = str(row.get("decoded_frame_sha256") or row.get("frame_sha256") or "")
            if len(raw_frame_sha) != 64 or any(char not in "0123456789abcdef" for char in raw_frame_sha):
                raise CapabilityUnavailable("generated UI state_evidence requires decoded frame SHA-256")
            for kind in ("ocr_evidence", "layout_evidence"):
                receipt = row.get(kind)
                if not isinstance(receipt, Mapping):
                    raise CapabilityUnavailable(f"generated UI state_evidence requires {kind}")
                input_sha = str(receipt.get("input_sha256") or "")
                decoded_sha = str(receipt.get("decoded_frame_sha256") or raw_frame_sha)
                if any(
                    len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
                    for value in (input_sha, decoded_sha)
                ):
                    raise CapabilityUnavailable(
                        f"generated UI {kind} must bind both decoded frame and actual OCR/layout input bytes"
                    )
            if row.get("ocr_match_percent") != 100 or row.get("layout_match_percent") != 100:
                raise CapabilityUnavailable("generated UI state OCR and layout matches must both be 100")
        if report.get("ocr_match_percent") != 100 or report.get("layout_match_percent") != 100:
            raise CapabilityUnavailable("generated UI aggregate OCR and layout matches must both be 100")
        if str(report.get("ui_truth_card_sha256") or "").lower() != _canonical_sha256(truth):
            raise CapabilityUnavailable("generated UI QC truth SHA-256 does not match immutable target truth")
        if _active_high_fidelity(context):
            animation_evidence = report.get("animation_interval_evidence")
            if not isinstance(animation_evidence, list):
                raise CapabilityUnavailable(
                    "active generated UI requires independent animation interval evidence"
                )
            if report.get("animation_ocr_match_percent") != 100 or report.get("animation_layout_match_percent") != 100:
                raise CapabilityUnavailable(
                    "active generated UI animation OCR and layout matches must both be 100"
                )

        data = video_path.read_bytes()
        digest = _sha256_bytes(data)
        publisher = getattr(context, "publish_artifact", None)
        if not callable(publisher):
            raise CapabilityUnavailable("active generated UI requires immutable video publication")
        rendered_media = publisher(
            kind="generated_ui_video",
            stream=io.BytesIO(data),
            content_type="video/mp4",
            expected_sha256=digest,
            metadata={
                "producer": str((self._render_backend_identity or {}).get("implementation") or self._identity["implementation"]),
                "producer_stage": "resolve_ui_evidence",
                "parent_digests": _context_parent_digests(context),
                "state_count": len(states),
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
                "ui_renderer_decision_sha256": _canonical_sha256(renderer_decision),
            },
        )
        decision_payload = {
            "schema_version": "ui-renderer-decision/v1",
            "decision": renderer_decision,
            "target_ui_evidence_sha256": _sha256_file(source),
            "ui_truth_card_sha256": _canonical_sha256(truth),
            "ui_render_contract_sha256": _canonical_sha256(render_contract),
        }
        encoded_decision = json.dumps(
            decision_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        decision_sha256 = _sha256_bytes(encoded_decision)
        decision_artifact = publisher(
            kind="ui_renderer_decision",
            stream=io.BytesIO(encoded_decision),
            content_type="application/json",
            expected_sha256=decision_sha256,
            metadata={
                "producer_stage": "resolve_ui_evidence",
                "decision": renderer_decision,
                "decision_sha256": decision_sha256,
                "target_ui_evidence_sha256": _sha256_file(source),
                "ui_truth_card_sha256": _canonical_sha256(truth),
                "ui_render_contract_sha256": _canonical_sha256(render_contract),
            },
        )
        report = deepcopy(dict(report))
        report["media_sha256"] = digest
        report["truth_basis"] = truth_basis or (
            "parsed-app-store-evidence" if slot == "app_store_evidence" else "target-owned-upload"
        )
        report["truth_source_sha256"] = _sha256_file(source)
        return {
            "status": "ready",
            "ui_truth_card": deepcopy(dict(truth)),
            "ui_render_contract": deepcopy(dict(render_contract)),
            "rendered_media": rendered_media,
            "published_artifacts": [dict(rendered_media), dict(decision_artifact)],
            "ocr_match_percent": 100,
            "layout_match_percent": 100,
            "state_evidence": deepcopy(list(evidence)),
            "ui_qc_report": report,
            "truth_basis": truth_basis or ("parsed-app-store-evidence" if slot == "app_store_evidence" else "target-owned-upload"),
            "ui_truth_card_sha256": _canonical_sha256(truth),
            "truth_source_sha256": _sha256_file(source),
            "ui_renderer_decision": renderer_decision,
            "ui_renderer_decision_artifact": decision_artifact,
        }

    def _build_generated_ui_report_from_video(
        self,
        *,
        video_path: Path,
        truth: Mapping[str, Any],
        render_contract: Mapping[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        """Independently verify renderer pixels with the bound OCR backend.

        A production renderer owns only deterministic media construction.  It
        must not self-attest OCR/layout scores.  This method samples each
        declared state, sends the exact encoded PNG bytes to the configured OCR
        backend, and creates the frame-bound receipts consumed by timeline QC.
        """

        states = truth.get("states")
        if not isinstance(states, list) or not states:
            raise CapabilityUnavailable("active generated UI requires a non-empty target state sequence")
        state_ids: list[str] = []
        previous_frame_ms: int | None = None
        for index, state in enumerate(states, start=1):
            if not isinstance(state, Mapping):
                raise CapabilityUnavailable(f"generated UI truth state {index} must be an object")
            state_id = str(state.get("state_id") or "")
            frame_ms = state.get("frame_ms")
            if not state_id or state_id in state_ids:
                raise CapabilityUnavailable("generated UI truth states require unique state_id values")
            if isinstance(frame_ms, bool) or not isinstance(frame_ms, int) or frame_ms < 0:
                raise CapabilityUnavailable(f"generated UI truth state {state_id} requires non-negative integer frame_ms")
            if previous_frame_ms is not None and frame_ms <= previous_frame_ms:
                raise CapabilityUnavailable("generated UI truth state frame_ms values must be strictly increasing")
            state_ids.append(state_id)
            previous_frame_ms = frame_ms

        if render_contract.get("state_sequence") != state_ids:
            raise CapabilityUnavailable("generated UI render state_sequence does not match target truth")
        viewport = render_contract.get("viewport")
        if not isinstance(viewport, Sequence) or isinstance(viewport, (str, bytes, bytearray)) or len(viewport) != 2:
            raise CapabilityUnavailable("generated UI render contract requires a two-value viewport")
        try:
            viewport_width = float(viewport[0])
            viewport_height = float(viewport[1])
        except (TypeError, ValueError) as exc:
            raise CapabilityUnavailable("generated UI viewport must be numeric") from exc
        if viewport_width <= 0 or viewport_height <= 0:
            raise CapabilityUnavailable("generated UI viewport must be positive")

        probe = _probe(video_path)
        video_width = int(probe.get("width") or 0)
        video_height = int(probe.get("height") or 0)
        duration_ms = int(probe.get("video_duration_us") or probe.get("duration_us") or 0) // 1000
        if video_width <= 0 or video_height <= 0 or duration_ms <= 0:
            raise CapabilityUnavailable("generated UI video has no usable dimensions or duration")
        if abs((video_width / video_height) - (viewport_width / viewport_height)) / (video_width / video_height) > 0.01:
            raise CapabilityUnavailable("generated UI viewport aspect does not match rendered video")
        scale_x = video_width / viewport_width
        scale_y = video_height / viewport_height

        work_dir = Path(getattr(context, "work_dir", tempfile.gettempdir()))
        work_dir.mkdir(parents=True, exist_ok=True)
        state_evidence: list[dict[str, Any]] = []
        for state in states:
            state_id = str(state["state_id"])
            frame_ms = int(state["frame_ms"])
            if frame_ms >= duration_ms:
                raise CapabilityUnavailable(f"generated UI state {state_id} frame_ms is outside rendered video")
            expected_text = state.get("expected_text")
            expected_layout = state.get("expected_layout")
            if not isinstance(expected_text, list) or not all(isinstance(item, str) and item.strip() for item in expected_text):
                raise CapabilityUnavailable(f"generated UI state {state_id} requires exact expected_text")
            if not isinstance(expected_layout, list) or len(expected_layout) != len(expected_text):
                raise CapabilityUnavailable(f"generated UI state {state_id} requires one layout item per text item")

            png_path, decoded_frame_sha256 = self._extract_ui_frame(
                video_path,
                frame_ms=frame_ms,
                work_dir=work_dir,
                state_id=state_id,
            )
            input_sha256 = _sha256_file(png_path)
            raw_ocr = self._ocr(png_path)
            records_value = raw_ocr
            backend_evidence: dict[str, Any] | None = None
            if isinstance(raw_ocr, Mapping) and "records" in raw_ocr:
                records_value = raw_ocr.get("records")
                evidence = raw_ocr.get("evidence")
                if isinstance(evidence, Mapping):
                    backend_evidence = dict(evidence)
            recognized_records = self._records(records_value)
            if self.production:
                self._validate_generated_ui_ocr_evidence(
                    backend_evidence,
                    input_sha256=input_sha256,
                    records=recognized_records,
                )
            recognized = [str(item.get("text") or "").strip() for item in recognized_records if str(item.get("text") or "").strip()]
            def normalize(value: Any) -> str:
                return " ".join(str(value or "").replace("\u200b", "").split()).casefold()
            expected_norm = [normalize(item) for item in expected_text]
            observed_norm = [normalize(item) for item in recognized]
            if expected_norm != observed_norm:
                raise ReplicationError(
                    "UI_OCR_MISMATCH",
                    "rendered UI state text does not exactly match target truth",
                    category="quality",
                    user_action_required=True,
                    details={"state_id": state_id, "expected": expected_text, "observed": recognized},
                    http_status=422,
                )
            layout_records: list[dict[str, Any]] = []
            for expected_item, observed_item in zip(expected_layout, recognized_records):
                if not isinstance(expected_item, Mapping) or not isinstance(expected_item.get("bbox"), Sequence):
                    raise CapabilityUnavailable(f"generated UI state {state_id} expected layout is invalid")
                bbox = expected_item.get("bbox")
                try:
                    target_bbox = [float(bbox[0]) * scale_x, float(bbox[1]) * scale_y, float(bbox[2]) * scale_x, float(bbox[3]) * scale_y]
                except (TypeError, ValueError, IndexError) as exc:
                    raise CapabilityUnavailable(f"generated UI state {state_id} expected layout is invalid") from exc
                observed_bbox = observed_item.get("bbox")
                if not isinstance(observed_bbox, Sequence) or self._bbox_iou(target_bbox, observed_bbox) < 0.98:
                    raise ReplicationError(
                        "UI_LAYOUT_MISMATCH",
                        "rendered UI state layout does not match target truth",
                        category="quality",
                        user_action_required=True,
                        details={"state_id": state_id, "expected_layout": expected_layout, "observed_layout": recognized_records},
                        http_status=422,
                    )
                layout_record = dict(observed_item)
                layout_record["element_id"] = str(expected_item.get("element_id") or "")
                if expected_item.get("role") is not None:
                    layout_record["role"] = str(expected_item.get("role"))
                layout_records.append(layout_record)

            records_digest = _sha256_bytes(
                json.dumps(recognized_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            layout_digest = _sha256_bytes(
                json.dumps(layout_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            base_receipt = dict(backend_evidence or {})
            base_receipt.update({"input_sha256": input_sha256, "decoded_frame_sha256": decoded_frame_sha256})
            ocr_receipt = dict(base_receipt)
            ocr_receipt.update({"records": recognized_records, "records_sha256": records_digest})
            layout_receipt = dict(base_receipt)
            layout_receipt.update({"records": layout_records, "records_sha256": layout_digest})
            state_evidence.append(
                {
                    "state_id": state_id,
                    "frame_ms": frame_ms,
                    "frame_sha256": decoded_frame_sha256,
                    "decoded_frame_sha256": decoded_frame_sha256,
                    "truth_state_sha256": _sha256_bytes(
                        json.dumps(dict(state), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ),
                    "ocr_match_percent": 100,
                    "layout_match_percent": 100,
                    "ocr_evidence": ocr_receipt,
                    "layout_evidence": layout_receipt,
                }
            )

        # State snapshots do not cover interpolation frames.  Sample every
        # declared state-to-state interval and run the same independently
        # bound OCR on those decoded pixels.  This catches replacement glyphs,
        # mojibake, unreadable fades, and geometry excursions that disappear
        # at the exact state timestamps.
        animation_interval_evidence: list[dict[str, Any]] = []
        animation_intervals = self._animation_sample_times(states, duration_ms, render_contract)
        for interval_index, interval in enumerate(animation_intervals, start=1):
            samples: list[dict[str, Any]] = []
            for sample_index, frame_ms in enumerate(interval["sample_times_ms"], start=1):
                sample_id = f"animation-{interval_index}-{sample_index}-{frame_ms}"
                png_path, decoded_frame_sha256 = self._extract_ui_frame(
                    video_path,
                    frame_ms=int(frame_ms),
                    work_dir=work_dir,
                    state_id=sample_id,
                )
                input_sha256 = _sha256_file(png_path)
                raw_ocr = self._ocr(png_path)
                records_value = raw_ocr
                backend_evidence: dict[str, Any] | None = None
                if isinstance(raw_ocr, Mapping) and "records" in raw_ocr:
                    records_value = raw_ocr.get("records")
                    evidence = raw_ocr.get("evidence")
                    if isinstance(evidence, Mapping):
                        backend_evidence = dict(evidence)
                recognized_records = self._records(records_value)
                if self.production:
                    self._validate_generated_ui_ocr_evidence(
                        backend_evidence,
                        input_sha256=input_sha256,
                        records=recognized_records,
                    )
                observed_records, layout_records = self._validate_animation_records(
                    recognized_records,
                    states=states,
                    video_width=video_width,
                    video_height=video_height,
                    scale_x=scale_x,
                    scale_y=scale_y,
                    frame_ms=int(frame_ms),
                )
                records_digest = _canonical_sha256(observed_records)
                layout_digest = _canonical_sha256(layout_records)
                base_receipt = dict(backend_evidence or {})
                base_receipt.update(
                    {
                        "input_sha256": input_sha256,
                        "decoded_frame_sha256": decoded_frame_sha256,
                    }
                )
                ocr_receipt = dict(base_receipt)
                ocr_receipt.update({"records": observed_records, "records_sha256": records_digest})
                layout_receipt = dict(base_receipt)
                layout_receipt.update({"records": layout_records, "records_sha256": layout_digest})
                samples.append(
                    {
                        "frame_ms": int(frame_ms),
                        "frame_sha256": decoded_frame_sha256,
                        "decoded_frame_sha256": decoded_frame_sha256,
                        "ocr_match_percent": 100,
                        "layout_match_percent": 100,
                        "ocr_evidence": ocr_receipt,
                        "layout_evidence": layout_receipt,
                    }
                )
            animation_interval_evidence.append(
                {
                    "from_state_id": interval["from_state_id"],
                    "to_state_id": interval["to_state_id"],
                    "start_ms": interval["start_ms"],
                    "end_ms": interval["end_ms"],
                    "samples": samples,
                }
            )

        truth_sha256 = _sha256_bytes(
            json.dumps(dict(truth), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        render_contract_sha256 = _sha256_bytes(
            json.dumps(dict(render_contract), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        animation_count = max(
            (len(interval.get("sample_times_ms", [])) for interval in animation_intervals),
            default=0,
        )
        report = {
            "passed": True,
            "status": "passed",
            "ocr_passed": True,
            "approved_copy_passed": True,
            "page_state_passed": True,
            "layout_passed": True,
            "ocr_match_percent": 100,
            "layout_match_percent": 100,
            "approved_copy_observed": list(truth.get("approved_copy") or []),
            "frame_sha256_algorithm": "ffmpeg-rawvideo-rgb24-v1",
            "state_evidence": state_evidence,
            "ocr_evidence": [
                {"frame_ms": row["frame_ms"], "sha256": row["frame_sha256"]}
                for row in state_evidence
            ],
            "layout_evidence": [
                {"frame_ms": row["frame_ms"], "sha256": row["frame_sha256"]}
                for row in state_evidence
            ],
            "animation_interval_evidence": animation_interval_evidence,
            "animation_qc_required": True,
            "animation_intervals_checked": len(animation_interval_evidence),
            "animation_ocr_match_percent": 100,
            "animation_layout_match_percent": 100,
            "animation_sampling_policy": {
                "samples_per_interval": animation_count,
                "frame_sha256_algorithm": "ffmpeg-rawvideo-rgb24-v1",
            },
        }
        report["ui_truth_card_sha256"] = truth_sha256
        report["ui_render_contract_sha256"] = render_contract_sha256
        return report

    @staticmethod
    def _extract_ui_frame(
        video_path: Path,
        *,
        frame_ms: int,
        work_dir: Path,
        state_id: str,
    ) -> tuple[Path, str]:
        ffmpeg = _executable("ffmpeg", None)
        png_path = work_dir / f"generated-ui-{state_id}-{frame_ms}.png"
        png_result = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(video_path),
                "-ss",
                f"{frame_ms / 1000.0:.6f}",
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if png_result.returncode != 0 or not png_result.stdout:
            raise CapabilityUnavailable(
                f"generated UI frame extraction failed for state {state_id}",
                details={"stderr": png_result.stderr.decode("utf-8", errors="replace")[-500:]},
            )
        png_path.write_bytes(png_result.stdout)
        raw_result = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(video_path),
                "-ss",
                f"{frame_ms / 1000.0:.6f}",
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if raw_result.returncode != 0 or not raw_result.stdout:
            raise CapabilityUnavailable(
                f"generated UI decoded frame evidence failed for state {state_id}",
                details={"stderr": raw_result.stderr.decode("utf-8", errors="replace")[-500:]},
            )
        return png_path, _sha256_bytes(raw_result.stdout)

    def _validate_generated_ui_ocr_evidence(
        self,
        evidence: Mapping[str, Any] | None,
        *,
        input_sha256: str,
        records: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        if not isinstance(evidence, Mapping):
            raise CapabilityUnavailable("production OCR backend returned records without evidence binding")
        identity = self._ocr_backend_identity or {}
        if str(evidence.get("input_sha256") or "") != input_sha256:
            raise CapabilityUnavailable("production OCR evidence is not bound to the encoded frame bytes")
        if str(evidence.get("model_id") or "") != str(identity.get("model_id") or "") or str(evidence.get("model_sha256") or "") != str(identity.get("model_sha256") or ""):
            raise CapabilityUnavailable("production OCR evidence model identity does not match the bound backend")
        for field in ("request_sha256", "response_sha256", "records_sha256"):
            value = str(evidence.get(field) or "")
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise CapabilityUnavailable(f"production OCR evidence requires {field}")
        if records is not None:
            records_digest = _sha256_bytes(
                json.dumps(list(records), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            if records_digest != str(evidence.get("records_sha256") or ""):
                raise CapabilityUnavailable("production OCR evidence records SHA does not match returned records")

    def render_and_verify(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        with self._ui_source(context) as (source, slot, source_metadata):
            if _active_high_fidelity(context) and _has_generated_ui_region(context):
                return self._render_active_generated_ui_video(
                    context=context,
                    source=source,
                    source_metadata=source_metadata,
                    slot=slot,
                )
            output = Path(getattr(context, "work_dir", tempfile.gettempdir())) / "ui-render.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            if self.render_backend is None:
                try:
                    from PIL import Image
                    with Image.open(source) as image:
                        image.convert("RGBA").save(output, format="PNG")
                except Exception as exc:
                    raise CapabilityUnavailable("UI source cannot be decoded as an image") from exc
            else:
                rendered = self.render_backend(source, output, context)
                if rendered is not None:
                    candidate = Path(rendered) if isinstance(rendered, (str, Path)) else None
                    if candidate is not None and candidate != output:
                        output.write_bytes(candidate.read_bytes())
                try:
                    from PIL import Image
                    with Image.open(output) as image:
                        image.convert("RGBA").save(output, format="PNG")
                except Exception as exc:
                    raise CapabilityUnavailable("UI renderer output is not a decodable image") from exc
            if not output.is_file() or output.stat().st_size == 0:
                raise CapabilityUnavailable("UI renderer produced no bytes")
            data = output.read_bytes()
            digest = _sha256_bytes(data)
            raw_ocr = self._ocr(output)
            backend_evidence: dict[str, Any] | None = None
            records_value = raw_ocr
            if isinstance(raw_ocr, Mapping) and "records" in raw_ocr:
                records_value = raw_ocr.get("records")
                evidence = raw_ocr.get("evidence")
                if isinstance(evidence, Mapping):
                    backend_evidence = dict(evidence)
            if self.production:
                if backend_evidence is None:
                    raise CapabilityUnavailable("production OCR backend returned records without evidence binding")
                identity = self._ocr_backend_identity or {}
                if str(backend_evidence.get("input_sha256") or "") != digest:
                    raise CapabilityUnavailable("production OCR evidence is not bound to the rendered image SHA")
                if str(backend_evidence.get("model_id") or "") != str(identity.get("model_id") or "") or str(backend_evidence.get("model_sha256") or "") != str(identity.get("model_sha256") or ""):
                    raise CapabilityUnavailable("production OCR evidence model identity does not match the bound backend")
                for field in ("request_sha256", "response_sha256", "records_sha256"):
                    value = str(backend_evidence.get(field) or "")
                    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                        raise CapabilityUnavailable(f"production OCR evidence requires {field}")
            recognized_records = self._records(records_value)
            if self.production:
                records_digest = _sha256_bytes(
                    json.dumps(recognized_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                )
                if records_digest != str((backend_evidence or {}).get("records_sha256") or ""):
                    raise CapabilityUnavailable("production OCR records do not match the evidence records SHA")
            recognized = [str(item.get("text") or "").strip() for item in recognized_records if str(item.get("text") or "").strip()]
            expected = list(self.expected_text)
            expected_layout = list(self.expected_layout)
            if source_metadata:
                if not expected:
                    raw = source_metadata.get("expected_text") or source_metadata.get("ui_text")
                    expected = [str(value) for value in raw] if isinstance(raw, list) else ([str(raw)] if raw else [])
                if not expected_layout and isinstance(source_metadata.get("expected_layout"), Sequence):
                    expected_layout = [dict(item) for item in source_metadata["expected_layout"] if isinstance(item, Mapping)]
            if not expected:
                metadata = getattr(context, "input_slots", ())
                for item in metadata:
                    if isinstance(item, Mapping) and item.get("slot_id") == slot:
                        records = item.get("metadata") or []
                        if records and isinstance(records[0], Mapping):
                            raw = records[0].get("expected_text") or records[0].get("ui_text")
                            expected = [str(value) for value in raw] if isinstance(raw, list) else ([str(raw)] if raw else [])
                            if not expected_layout and isinstance(records[0].get("expected_layout"), Sequence):
                                expected_layout = [dict(item) for item in records[0]["expected_layout"] if isinstance(item, Mapping)]
                        break
            if not expected and not self.allow_self_consistency:
                raise CapabilityUnavailable("UI truth has no expected text evidence")
            if not expected:
                expected = list(recognized)
            def normalize(value: str) -> str:
                text = " ".join(str(value or "").replace("\u200b", "").split())
                return text if self.case_sensitive else text.casefold()

            expected_norm = [normalize(item) for item in expected if normalize(item)]
            observed_norm = [normalize(item) for item in recognized if normalize(item)]
            if expected_norm != observed_norm:
                raise ReplicationError(
                    "UI_OCR_MISMATCH",
                    "rendered UI text does not exactly match target truth",
                    category="quality",
                    user_action_required=True,
                    details={"expected": expected, "observed": recognized},
                    http_status=422,
                )
            if not expected_layout:
                if self.production:
                    raise CapabilityUnavailable("production UI verification requires expected_layout evidence")
                if not self.allow_self_consistency:
                    raise CapabilityUnavailable("UI truth has no expected layout evidence")
                expected_layout = list(recognized_records)
            if any(not isinstance(item.get("bbox"), Sequence) for item in recognized_records):
                raise CapabilityUnavailable("OCR backend did not return bounding boxes for every text item")
            expected_layout_labels = [normalize(str(item.get("text") or "")) for item in expected_layout]
            if expected_layout_labels != expected_norm:
                raise ReplicationError(
                    "UI_LAYOUT_MISMATCH",
                    "expected UI layout does not cover the exact OCR text set",
                    category="quality",
                    user_action_required=True,
                    details={"expected_text": expected_norm, "expected_layout_text": expected_layout_labels},
                    http_status=422,
                )
            for expected_item in expected_layout:
                label = normalize(str(expected_item.get("text") or ""))
                observed_item = next((item for item in recognized_records if normalize(str(item.get("text") or "")) == label), None)
                if observed_item is None or self._bbox_iou(expected_item.get("bbox") or [], observed_item.get("bbox") or []) < 0.98:
                    raise ReplicationError(
                        "UI_LAYOUT_MISMATCH",
                        "rendered UI layout does not match target truth",
                        category="quality",
                        user_action_required=True,
                        details={"expected_layout": expected_layout, "observed_layout": recognized_records},
                        http_status=422,
                    )
            publisher = getattr(context, "publish_artifact", None)
            if callable(publisher):
                rendered_media = publisher(
                    kind="rendered_ui",
                    stream=io.BytesIO(data),
                    content_type="image/png",
                    expected_sha256=digest,
                    metadata={
                        "ocr_engine": str((self._ocr_backend_identity or {}).get("implementation") or self._identity["implementation"]),
                        "ocr_model_sha256": str((self._ocr_backend_identity or {}).get("model_sha256") or ""),
                        "ocr_match_percent": 100,
                        "layout_match_percent": 100,
                    },
                )
            elif self.allow_self_consistency:
                rendered_media = {"kind": "rendered_ui", "sha256": digest, "uri": f"memory://rendered-ui/{digest}", "object_key": f"memory://rendered-ui/{digest}"}
            else:
                raise CapabilityUnavailable("UI renderer requires context.publish_artifact in strict mode")
            return {
                "status": "ready",
                "ui_truth_card": {
                    "expected_text": expected,
                    "source_slot": slot,
                    "truth_basis": "parsed-app-store-evidence" if slot == "app_store_evidence" else "target-owned-upload",
                },
                "ui_render_contract": {"renderer": self._identity["implementation"], "text_policy": "deterministic_exact", "layout_policy": "target_geometry_preserved"},
                "rendered_media": rendered_media,
                "ocr_match_percent": 100,
                "layout_match_percent": 100,
                "ocr_evidence": {
                    "backend": dict(backend_evidence or {}),
                    "recognized_text": recognized,
                    "expected_text": expected,
                    "recognized_layout": recognized_records,
                    "expected_layout": expected_layout,
                },
            }


_OMITTED_TIMELINE_POLICIES = {
    "omit",
    "omit_source_end_card",
    "omit_source_tail",
}


def _flatten_timeline_region(region: Mapping[str, Any]) -> dict[str, Any]:
    metadata = region.get("metadata")
    if isinstance(metadata, Mapping):
        return {**dict(metadata), **dict(region)}
    return dict(region)


def _timeline_region_key(region: Mapping[str, Any], *, index: int) -> tuple[str, int, int]:
    region_id = str(region.get("region_id") or "").strip()
    if not region_id:
        raise CapabilityUnavailable(
            "renderer timeline manifest region coverage requires region_id",
            details={"region_index": index},
        )
    try:
        start_us = int(region.get("source_start_us", region.get("start_us")))
        end_us = int(region.get("source_end_us", region.get("end_us")))
    except (TypeError, ValueError) as exc:
        raise CapabilityUnavailable(
            "renderer timeline manifest region coverage has invalid source bounds",
            details={"region_id": region_id},
        ) from exc
    if start_us < 0 or end_us <= start_us:
        raise CapabilityUnavailable(
            "renderer timeline manifest region coverage has invalid source bounds",
            details={"region_id": region_id},
        )
    return region_id, start_us, end_us


def _timeline_region_is_omitted(region: Mapping[str, Any]) -> bool:
    kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
    policy = str(region.get("assembly_policy") or "").strip().lower()
    return kind == "omit_source_end_card" or policy in _OMITTED_TIMELINE_POLICIES


def _normalised_timeline_route(region: Mapping[str, Any]) -> tuple[str, str, str]:
    """Project a persisted region onto the renderer's canonical route tuple."""

    raw_kind = str(region.get("region_type") or region.get("kind") or "").strip().lower()
    media_origin = str(region.get("media_origin") or "generated_media").strip().lower()
    assembly_policy = str(region.get("assembly_policy") or "").strip().lower()
    if raw_kind in {"source_ui_keep", "source_interval", "source_keep", "source_preserve"}:
        return "generated", "source_interval", "splice_source_interval"
    if raw_kind in {"opaque_ui_demo", "ui_demo", "opaque_ui_video"}:
        return "opaque_ui_demo", media_origin, assembly_policy or "splice_opaque_media"
    if raw_kind in {"generated_ui_demo", "generated_ui"}:
        return "generated_ui_demo", "generated_media", assembly_policy or "generate_ui"
    if raw_kind in {"excluded_app_end_card", "opaque_app_tail_card", "opaque_tail", "tail_card"}:
        return "excluded_app_end_card", media_origin, assembly_policy or "splice_opaque_media"
    if raw_kind == "omit_source_end_card":
        return "excluded_app_end_card", "source_interval", "omit_source_end_card"
    if raw_kind == "generated":
        return "generated", media_origin, assembly_policy or (
            "splice_source_interval" if media_origin == "source_interval" else "generate_region"
        )
    return raw_kind, media_origin, assembly_policy


def _transition_shell_digest(region: Mapping[str, Any], phase: str) -> str | None:
    shell = region.get("transition_shell")
    if not isinstance(shell, Mapping):
        return None
    value = shell.get(phase)
    if value is None:
        return None
    if isinstance(value, str):
        visual = {"type": value}
    elif isinstance(value, Mapping):
        visual = dict(value)
        if visual.get("type") is None and visual.get("kind") is not None:
            visual["type"] = visual.pop("kind")
    else:
        return None
    source_shell = {
        "visual": visual,
        "audio": shell.get("audio"),
        "z_order": shell.get("z_order"),
    }
    return _canonical_sha256(source_shell)


def _transition_shell_type(region: Mapping[str, Any], phase: str) -> str | None:
    shell = region.get("transition_shell")
    if not isinstance(shell, Mapping):
        return None
    value = shell.get(phase)
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, Mapping):
        return str(value.get("type") or value.get("kind") or "").strip().lower() or None
    return None


def _validate_timeline_transition_receipts(
    manifest: Mapping[str, Any],
    *,
    regions: Sequence[Mapping[str, Any]],
    output_sha256: str,
) -> None:
    included = [
        region
        for region in regions
        if not _timeline_region_is_omitted(region)
    ]
    raw_receipts = manifest.get("transition_renders")
    receipts = raw_receipts if isinstance(raw_receipts, list) else []
    by_boundary: dict[int, Mapping[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise CapabilityUnavailable("renderer transition receipt is invalid")
        try:
            boundary_index = int(receipt.get("boundary_index"))
        except (TypeError, ValueError) as exc:
            raise CapabilityUnavailable("renderer transition receipt boundary is invalid") from exc
        if boundary_index in by_boundary:
            raise CapabilityUnavailable("renderer transition receipts contain duplicate boundaries")
        if boundary_index < 0 or boundary_index + 1 >= len(included):
            raise CapabilityUnavailable("renderer transition receipt boundary is out of range")
        by_boundary[boundary_index] = receipt
        final_sha = str(receipt.get("final_output_sha256") or "").lower()
        if re.fullmatch(r"[0-9a-f]{64}", final_sha) is None or final_sha != output_sha256.lower():
            raise CapabilityUnavailable(
                "renderer transition receipt does not bind the current output bytes"
            )

    for boundary_index, (left, right) in enumerate(zip(included, included[1:])):
        left_type = _transition_shell_type(left, "exit")
        right_type = _transition_shell_type(right, "entry")
        left_sha = _transition_shell_digest(left, "exit")
        right_sha = _transition_shell_digest(right, "entry")
        if left_type and right_type and left_type != right_type:
            raise CapabilityUnavailable("conflicting transition shells at a timeline boundary")
        if left_sha and right_sha and left_sha != right_sha:
            raise CapabilityUnavailable("conflicting transition shell digests at a timeline boundary")
        expected_type = right_type or left_type
        expected_sha = right_sha or left_sha
        receipt = by_boundary.get(boundary_index)
        if expected_type is None:
            if receipt is not None and str(receipt.get("source_shell_sha256") or ""):
                raise CapabilityUnavailable(
                    "ordinary hard cut receipt unexpectedly binds a source shell"
                )
            continue
        if receipt is None:
            raise CapabilityUnavailable(
                "declared source transition shell has no transition receipt"
            )
        actual_sha = str(receipt.get("source_shell_sha256") or "").lower()
        if not expected_sha or actual_sha != expected_sha.lower():
            raise CapabilityUnavailable(
                "renderer transition receipt does not bind the declared source shell"
            )
        if expected_type != "hard_cut" and receipt.get("rendered") is not True:
            raise CapabilityUnavailable("non-hard transition receipt is not rendered")


def _validate_renderer_timeline_manifest(
    manifest: Mapping[str, Any] | None,
    *,
    regions: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
    output_sha256: str,
) -> dict[str, Any]:
    if not isinstance(manifest, Mapping) or not manifest:
        raise CapabilityUnavailable(
            "active non-source compositor requires a non-empty renderer timeline manifest"
        )
    placements = manifest.get("placements")
    omitted = manifest.get("omitted_intervals")
    if not isinstance(placements, list) or not isinstance(omitted, list):
        raise CapabilityUnavailable(
            "renderer timeline manifest region coverage requires placements and omitted_intervals"
        )
    declared_output_sha = str(manifest.get("final_output_sha256") or "").lower()
    if declared_output_sha != output_sha256.lower():
        raise CapabilityUnavailable(
            "renderer timeline manifest does not bind the current output bytes"
        )
    if manifest.get("duration_us") is None and manifest.get("actual_output_duration") is None:
        raise CapabilityUnavailable(
            "renderer timeline manifest must declare output duration"
        )

    expected: dict[tuple[str, int, int], tuple[dict[str, Any], bool]] = {}
    for index, raw_region in enumerate(regions, start=1):
        region = _flatten_timeline_region(raw_region)
        key = _timeline_region_key(region, index=index)
        if key in expected:
            raise CapabilityUnavailable(
                "renderer timeline manifest region coverage contains duplicate source regions",
                details={"region_id": key[0]},
            )
        expected[key] = (region, _timeline_region_is_omitted(region))

    placement_by_key: dict[tuple[str, int, int], Mapping[str, Any]] = {}
    for index, raw_placement in enumerate(placements, start=1):
        if not isinstance(raw_placement, Mapping):
            raise CapabilityUnavailable(
                "renderer timeline manifest region coverage contains an invalid placement",
                details={"placement_index": index},
            )
        key = _timeline_region_key(raw_placement, index=index)
        if key in placement_by_key:
            raise CapabilityUnavailable(
                "renderer timeline manifest region coverage contains duplicate placements",
                details={"region_id": key[0]},
            )
        placement_by_key[key] = raw_placement

    omitted_by_key: dict[tuple[str, int, int], Mapping[str, Any]] = {}
    for index, raw_omitted in enumerate(omitted, start=1):
        if not isinstance(raw_omitted, Mapping):
            raise CapabilityUnavailable(
                "renderer timeline manifest region coverage contains an invalid omission",
                details={"omission_index": index},
            )
        key = _timeline_region_key(raw_omitted, index=index)
        if key in omitted_by_key or key in placement_by_key:
            raise CapabilityUnavailable(
                "renderer timeline manifest region coverage contains duplicate regions",
                details={"region_id": key[0]},
            )
        omitted_by_key[key] = raw_omitted

    if set(placement_by_key) | set(omitted_by_key) != set(expected):
        raise CapabilityUnavailable(
            "renderer timeline manifest region coverage does not match frozen timeline regions"
        )
    for key, (_region, is_omitted) in expected.items():
        if is_omitted != (key in omitted_by_key):
            raise CapabilityUnavailable(
                "renderer timeline manifest region coverage does not match omitted routes",
                details={"region_id": key[0]},
            )
        if not is_omitted and key not in placement_by_key:
            raise CapabilityUnavailable(
                "renderer timeline manifest region coverage is missing a placement",
                details={"region_id": key[0]},
            )

        observed = omitted_by_key.get(key) if is_omitted else placement_by_key.get(key)
        if observed is None:
            continue
        expected_route = _normalised_timeline_route(_region)
        observed_route = _normalised_timeline_route(observed)
        if observed_route != expected_route:
            raise CapabilityUnavailable(
                "renderer timeline manifest placement route does not match frozen timeline region",
                details={
                    "region_id": key[0],
                    "expected_route": expected_route,
                    "observed_route": observed_route,
                },
            )

    artifact_rows = [item for item in artifacts if isinstance(item, Mapping)]
    for key, (region, is_omitted) in expected.items():
        raw_bindings = region.get("media_artifact_bindings")
        placement = placement_by_key.get(key)
        raw_receipts = (
            placement.get("provider_carrier_receipts")
            if isinstance(placement, Mapping)
            else None
        )
        _route_kind, route_origin, _route_policy = _normalised_timeline_route(region)
        if is_omitted or route_origin == "source_interval":
            if raw_bindings is not None or raw_receipts or (
                isinstance(placement, Mapping) and placement.get("carrier_receipts")
            ):
                raise CapabilityUnavailable(
                    "source/omitted timeline placement contains media bindings or carrier receipts",
                    details={"region_id": key[0]},
                )
            continue
        if raw_bindings is None:
            if raw_receipts:
                raise CapabilityUnavailable(
                    "provider carrier receipt does not match a frozen provider binding",
                    details={"region_id": key[0]},
                )
            generic_receipts = (
                placement.get("carrier_receipts")
                if isinstance(placement, Mapping)
                else None
            )
            if not isinstance(generic_receipts, list) or len(generic_receipts) != 1:
                raise CapabilityUnavailable(
                    "non-source placement requires exactly one output-bound carrier receipt",
                    details={"region_id": key[0]},
                )
            receipt = generic_receipts[0]
            if not isinstance(receipt, Mapping):
                raise CapabilityUnavailable(
                    "non-source carrier receipt is invalid",
                    details={"region_id": key[0]},
                )
            media_sha = str(receipt.get("media_sha256") or "").lower()
            carrier_sha = str(receipt.get("carrier_sha256") or "").lower()
            if re.fullmatch(r"[0-9a-f]{64}", media_sha) is None or media_sha != carrier_sha:
                raise CapabilityUnavailable(
                    "non-source carrier receipt does not bind media bytes",
                    details={"region_id": key[0]},
                )
            if str(receipt.get("region_id") or "") != key[0]:
                raise CapabilityUnavailable(
                    "non-source carrier receipt does not match its region",
                    details={"region_id": key[0]},
                )
            receipt_output_sha = str(receipt.get("final_output_sha256") or "").lower()
            if receipt_output_sha != output_sha256.lower():
                raise CapabilityUnavailable(
                    "non-source carrier receipt does not bind the current output bytes",
                    details={"region_id": key[0]},
                )
            declared_media_sha = str(
                region.get("media_sha256")
                or region.get("media_artifact_sha256")
                or region.get("artifact_sha256")
                or ""
            ).lower()
            if declared_media_sha and declared_media_sha != media_sha:
                mixer_receipts = manifest.get("audio_mixer_receipts")
                mixer_receipt = next(
                    (
                        item
                        for item in mixer_receipts
                        if isinstance(item, Mapping)
                        and str(item.get("region_id") or "") == key[0]
                    ),
                    None,
                ) if isinstance(mixer_receipts, list) else None
                if not (
                    str(region.get("audio_policy") or "").strip().lower()
                    == "evidence_bound_mix"
                    and isinstance(mixer_receipt, Mapping)
                    and str(mixer_receipt.get("opaque_media_sha256") or "").lower()
                    == declared_media_sha
                    and str(mixer_receipt.get("mixed_region_sha256") or "").lower()
                    == media_sha
                ):
                    raise CapabilityUnavailable(
                        "non-source carrier receipt does not match frozen media identity",
                        details={"region_id": key[0]},
                    )
            continue
        if is_omitted or not isinstance(raw_bindings, list) or not raw_bindings:
            raise CapabilityUnavailable(
                "provider carrier consumption is invalid for the timeline route",
                details={"region_id": key[0]},
            )
        if not isinstance(raw_receipts, list) or len(raw_receipts) != len(raw_bindings):
            raise CapabilityUnavailable(
                "provider carrier consumption receipts are incomplete",
                details={"region_id": key[0]},
            )
        for binding, receipt in zip(raw_bindings, raw_receipts):
            if not isinstance(binding, Mapping) or not isinstance(receipt, Mapping):
                raise CapabilityUnavailable(
                    "provider carrier consumption receipt is invalid",
                    details={"region_id": key[0]},
                )
            expected_values = {
                "kind": "provider_video",
                "segment_id": str(binding.get("segment_id") or ""),
                "artifact_id": str(binding.get("artifact_id") or ""),
                "artifact_sha256": str(binding.get("sha256") or "").lower(),
                "segment_plan_sha256": str(
                    binding.get("segment_plan_sha256") or ""
                ).lower(),
            }
            for field, expected_value in expected_values.items():
                if str(receipt.get(field) or "").lower() != str(expected_value).lower():
                    raise CapabilityUnavailable(
                        "provider carrier receipt does not match the frozen provider binding",
                        details={"region_id": key[0], "field": field},
                    )
            carrier_sha = str(receipt.get("carrier_sha256") or "").lower()
            if re.fullmatch(r"[0-9a-f]{64}", carrier_sha) is None:
                raise CapabilityUnavailable(
                    "provider carrier consumption receipt has an invalid carrier SHA-256",
                    details={"region_id": key[0]},
                )
            segment_sha = str(receipt.get("segment_sha256") or "").lower()
            if segment_sha != expected_values["artifact_sha256"]:
                raise CapabilityUnavailable(
                    "provider carrier receipt segment SHA does not match the frozen artifact",
                    details={"region_id": key[0]},
                )
            combined_sha = str(receipt.get("combined_carrier_sha256") or carrier_sha).lower()
            if combined_sha != carrier_sha:
                raise CapabilityUnavailable(
                    "provider carrier receipt combined SHA is inconsistent",
                    details={"region_id": key[0]},
                )
            if len(raw_bindings) == 1 and carrier_sha != expected_values["artifact_sha256"]:
                raise CapabilityUnavailable(
                    "single provider carrier SHA does not match the artifact SHA",
                    details={"region_id": key[0]},
                )
            receipt_output_sha = str(
                receipt.get("final_output_sha256") or ""
            ).lower()
            if receipt_output_sha != output_sha256.lower():
                raise CapabilityUnavailable(
                    "provider carrier receipt does not bind the current output bytes",
                    details={"region_id": key[0]},
                )
            matches = [
                artifact
                for artifact in artifact_rows
                if artifact.get("kind") == "provider_video"
                and str(artifact.get("artifact_id") or "")
                == expected_values["artifact_id"]
                and str(artifact.get("sha256") or "").lower()
                == expected_values["artifact_sha256"]
                and str(artifact.get("segment_id") or "")
                == expected_values["segment_id"]
                and str(artifact.get("segment_plan_sha256") or "").lower()
                == expected_values["segment_plan_sha256"]
            ]
            if len(matches) != 1:
                raise CapabilityUnavailable(
                    "provider carrier receipt does not match a current provider artifact",
                    details={"region_id": key[0], "artifact_id": expected_values["artifact_id"]},
                )
    _validate_timeline_transition_receipts(
        manifest,
        regions=regions,
        output_sha256=output_sha256,
    )
    return dict(manifest)


def _merge_audio_mixer_receipts(
    *,
    audio_regions: Sequence[Mapping[str, Any]],
    regions: Sequence[Mapping[str, Any]],
    renderer_receipts: Any,
) -> list[dict[str, Any]]:
    """Merge deferred renderer receipts with frozen pre-bound receipts by region."""

    pending_ids = {
        str(item.get("region_id") or "")
        for item in audio_regions
        if item.get("mixer_receipt_status") == "pending_renderer_receipt"
    }
    prebound_ids = {
        str(item.get("region_id") or "")
        for item in audio_regions
        if item.get("mixer_receipt_status") == "verified_prebound_receipt"
    }
    expected_ids = {
        str(item.get("region_id") or "") for item in audio_regions
    }
    if not expected_ids or pending_ids | prebound_ids != expected_ids:
        raise AudioMixerError("audio mixer receipt states are incomplete")
    raw_renderer_receipts = [] if renderer_receipts is None else renderer_receipts
    if not isinstance(raw_renderer_receipts, list):
        raise AudioMixerError("renderer audio mixer receipts are invalid")
    typed_renderer_receipts = [
        dict(item) for item in raw_renderer_receipts if isinstance(item, Mapping)
    ]
    if len(typed_renderer_receipts) != len(raw_renderer_receipts):
        raise AudioMixerError("renderer audio mixer receipt is invalid")
    renderer_by_id = {
        str(item.get("region_id") or ""): item for item in typed_renderer_receipts
    }
    if set(renderer_by_id) != pending_ids or len(renderer_by_id) != len(
        typed_renderer_receipts
    ):
        raise AudioMixerError(
            "renderer audio mixer receipt coverage does not match pending regions"
        )
    region_by_id = {
        str(item.get("region_id") or ""): item for item in regions
    }
    prebound_by_id: dict[str, dict[str, Any]] = {}
    for region_id in prebound_ids:
        receipt = region_by_id.get(region_id, {}).get("mixer_receipt")
        if not isinstance(receipt, Mapping):
            raise AudioMixerError("pre-bound audio mixer receipt is missing")
        prebound_by_id[region_id] = dict(receipt)
    return [
        dict(renderer_by_id.get(region_id) or prebound_by_id[region_id])
        for region_id in (
            str(item.get("region_id") or "") for item in audio_regions
        )
    ]


_PUBLIC_MANIFEST_OMITTED_PATH_KEYS = frozenset(
    {
        "media_path",
        "timeline_manifest_path",
    }
)
_PUBLIC_MANIFEST_PATH_FIELDS = frozenset(
    {
        "path",
        "paths",
        "worker_path",
        "worker_paths",
        "local_path",
        "local_paths",
        "file_path",
        "file_paths",
    }
)
_NONLOCAL_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_KNOWN_POSIX_WORKER_ROOTS = (
    PurePosixPath("/tmp"),
    PurePosixPath("/var/tmp"),
    PurePosixPath("/private/tmp"),
)


def _is_manifest_path_field(field_name: str | None) -> bool:
    normalized = str(field_name or "").strip().lower()
    return (
        normalized in _PUBLIC_MANIFEST_PATH_FIELDS
        or normalized.endswith("_path")
        or normalized.endswith("_paths")
    )


def _path_parts_start_with(
    parts: tuple[str, ...],
    root_parts: tuple[str, ...],
    *,
    case_sensitive: bool,
) -> bool:
    if len(parts) < len(root_parts):
        return False
    if not case_sensitive:
        parts = tuple(item.casefold() for item in parts)
        root_parts = tuple(item.casefold() for item in root_parts)
    return parts[: len(root_parts)] == root_parts


def _is_worker_local_manifest_path(
    value: str,
    *,
    field_name: str | None,
    worker_roots: Sequence[str | Path],
) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if candidate.lower().startswith("file:"):
        return True
    if _NONLOCAL_URI.match(candidate):
        return False
    windows_path = PureWindowsPath(candidate)
    if windows_path.is_absolute():
        return True
    posix_path = PurePosixPath(candidate)
    if not posix_path.is_absolute():
        return False
    if _is_manifest_path_field(field_name):
        return True
    if any(
        _path_parts_start_with(
            posix_path.parts,
            root.parts,
            case_sensitive=True,
        )
        for root in _KNOWN_POSIX_WORKER_ROOTS
    ):
        return True
    for raw_root in worker_roots:
        root_value = str(raw_root).strip()
        if not root_value:
            continue
        windows_root = PureWindowsPath(root_value)
        if windows_root.is_absolute() and _path_parts_start_with(
            windows_path.parts,
            windows_root.parts,
            case_sensitive=False,
        ):
            return True
        posix_root = PurePosixPath(root_value)
        if posix_root.is_absolute() and _path_parts_start_with(
            posix_path.parts,
            posix_root.parts,
            case_sensitive=True,
        ):
            return True
    return False


def _sanitize_public_timeline_manifest(
    value: Any,
    *,
    field_name: str | None = None,
    worker_roots: Sequence[str | Path] = (),
) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _sanitize_public_timeline_manifest(
                item,
                field_name=str(key),
                worker_roots=worker_roots,
            )
            for key, item in value.items()
            if str(key) not in _PUBLIC_MANIFEST_OMITTED_PATH_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_public_timeline_manifest(
                item,
                field_name=field_name,
                worker_roots=worker_roots,
            )
            for item in value
        ]
    if isinstance(value, str) and _is_worker_local_manifest_path(
        value,
        field_name=field_name,
        worker_roots=worker_roots,
    ):
        raise CapabilityUnavailable(
            "final timeline manifest contains a worker-local absolute path"
        )
    return deepcopy(value)


def _public_manifest_artifact_descriptor(
    artifact: Any,
    *,
    default_kind: str,
    expected_sha256: str,
) -> dict[str, Any]:
    source = artifact if isinstance(artifact, Mapping) else {}
    result = {
        "kind": str(source.get("kind") or default_kind),
        "sha256": (
            str(source.get("sha256") or "").lower()
            if _is_sha256(str(source.get("sha256") or "").lower())
            else expected_sha256
        ),
    }
    artifact_id = str(source.get("artifact_id") or "").strip()
    if artifact_id:
        result["artifact_id"] = artifact_id
    uri = str(source.get("uri") or "").strip()
    if (
        uri
        and not uri.lower().startswith("file:")
        and (
            _NONLOCAL_URI.match(uri)
            or not (
                PureWindowsPath(uri).is_absolute()
                or PurePosixPath(uri).is_absolute()
            )
        )
    ):
        result["uri"] = uri
    return result


class FfmpegCompositor:
    """Deterministic FFmpeg compositor boundary for complete region media.

    The actual layer/timeline renderer is injected because deployments may
    use the bundled FFmpeg splice implementation or a service-native wrapper.
    In production a missing renderer fails closed; a local pass-through is
    available only when explicitly requested for contract tests.
    """

    def __init__(
        self,
        *,
        renderer: Callable[[Path, Path, Any], Any] | None = None,
        production: bool = False,
        allow_passthrough: bool = False,
        implementation: str = "server.real_capabilities:FfmpegCompositor",
        version: str = "1.0.0",
        sha256: str | None = None,
    ) -> None:
        self.renderer = renderer
        self.production = bool(production)
        self.allow_passthrough = bool(allow_passthrough)
        self._builtin_overlay_renderer = (
            DeterministicOverlayRenderer(production=self.production) if self.renderer is None else None
        )
        self._identity = _identity("compositor", implementation, version, sha256, require_explicit_digest=self.production)
        if self.production:
            if self.renderer is not None:
                self._renderer_identity = _component_identity(self.renderer, label="compositor renderer")
            else:
                self._renderer_identity = _component_identity(
                    self._builtin_overlay_renderer,
                    label="bundled overlay renderer",
                )
        else:
            self._renderer_identity = {
                "mode": "bundled_overlay" if self.renderer is None else "injected"
            }
        self._capability_identity = _composite_identity(
            self._identity,
            {"renderer": self._renderer_identity},
        )

    def capability_identity(self) -> Mapping[str, Any]:
        return dict(self._capability_identity)

    def compose(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        with _materialize(context, "source_video") as media, tempfile.TemporaryDirectory(
            prefix="usfr-audio-mix-verify-"
        ) as audio_mix_verification_dir:
            source = Path(media.path)
            source_media_sha256 = str(getattr(media, "sha256", "") or "").lower()
            if not _is_sha256(source_media_sha256):
                if self.production:
                    raise CapabilityUnavailable(
                        "production compositor requires the immutable source media SHA-256 declaration"
                    )
                source_media_sha256 = _sha256_file(source)
            try:
                setattr(context, "source_media_sha256", source_media_sha256)
                setattr(
                    context,
                    "audio_mix_verification_dir",
                    Path(audio_mix_verification_dir).resolve(),
                )
            except Exception as exc:
                raise CapabilityUnavailable(
                    "compositor context cannot carry the verified source media SHA-256"
                ) from exc
            work_dir = Path(getattr(context, "work_dir", tempfile.gettempdir())).resolve()
            output = work_dir / "composited.mp4"
            output.parent.mkdir(parents=True, exist_ok=True)
            regions = [dict(item) for item in (getattr(context, "timeline_regions", ()) or ()) if isinstance(item, Mapping)]
            audio_required = _final_audio_stream_required(context, None)
            if audio_required:
                try:
                    setattr(context, "expect_audio", True)
                except Exception as exc:
                    raise CapabilityUnavailable(
                        "compositor context cannot carry the approved audio requirement"
                    ) from exc
            evidence_bound_mixer_identity = _evidence_bound_mixer_identity(
                self.renderer
            )
            audio_route_guard = validate_audio_route_contract(
                context=context,
                regions=regions,
                active_high_fidelity=_active_high_fidelity(context),
                defer_evidence_bound_mix_receipts=bool(
                    getattr(self.renderer, "supports_evidence_bound_mix", False)
                    and evidence_bound_mixer_identity is not None
                ),
            )
            if isinstance(audio_route_guard, Mapping):
                try:
                    setattr(context, "audio_route_guard", deepcopy(dict(audio_route_guard)))
                except Exception as exc:
                    raise CapabilityUnavailable(
                        "compositor context cannot carry the audio route guard"
                    ) from exc
            (
                source_overlay_contract,
                source_overlay_contract_sha256,
                overlay_render_mapping,
                overlay_render_mapping_sha256,
            ) = _embedded_timeline_overlay_contract(regions)
            required_overlay_payloads: dict[
                tuple[str, str], dict[str, Any]
            ] = {}
            if _active_high_fidelity(context):
                required_overlay_payloads = _required_overlay_payloads(
                    regions,
                    source_overlay_contract,
                    overlay_render_mapping,
                    source_overlay_contract_sha256=source_overlay_contract_sha256,
                )
                if required_overlay_payloads:
                    try:
                        setattr(
                            context,
                            "overlay_render_plan",
                            {
                                "source_overlay_contract_sha256": source_overlay_contract_sha256,
                                "overlay_render_mapping_sha256": overlay_render_mapping_sha256,
                                "required_payloads": dict(required_overlay_payloads),
                            },
                        )
                    except Exception:
                        pass
            overlay_render_receipts: list[dict[str, Any]] = []
            audio_mixer_verification_media: list[dict[str, Any]] = []
            renderer_timeline_manifest: dict[str, Any] | None = None
            # A semantic overlay renderer is a layer pass, not a timeline
            # renderer.  In production it must never become an accidental
            # source-video passthrough when the timeline contains generated
            # or user-supplied replacement media.  Source-origin-only runs
            # may still use the deterministic overlay renderer because their
            # pixels intentionally remain the verified source plate.
            has_non_source_carrier = any(
                str(region.get("media_origin") or "generated_media").strip().lower()
                != "source_interval"
                or str(region.get("assembly_policy") or "").strip().lower()
                in _OMITTED_TIMELINE_POLICIES
                for region in regions
            )
            renderer_kind = str(getattr(self.renderer, "capability_kind", "") or "").strip().lower()
            if self.production and has_non_source_carrier and (
                self.renderer is None or renderer_kind == "overlay_renderer"
            ):
                raise CapabilityUnavailable(
                    "compositor timeline renderer is not configured for non-source regions"
                )
            effective_renderer = self.renderer
            if effective_renderer is None and required_overlay_payloads:
                effective_renderer = self._builtin_overlay_renderer
            if effective_renderer is not None and required_overlay_payloads:
                try:
                    rendered = effective_renderer.render(source, output, context) if hasattr(effective_renderer, "render") else effective_renderer(source, output, context)
                except OverlayRenderError as exc:
                    raise CapabilityUnavailable(str(exc)) from exc
                if isinstance(rendered, Mapping):
                    raw_timeline_manifest = rendered.get("timeline_manifest")
                    if isinstance(raw_timeline_manifest, Mapping):
                        renderer_timeline_manifest = deepcopy(dict(raw_timeline_manifest))
                    raw_receipts = rendered.get("overlay_render_receipts")
                    if isinstance(raw_receipts, list):
                        overlay_render_receipts = [dict(item) for item in raw_receipts if isinstance(item, Mapping)]
                    raw_audio_media = rendered.get("audio_mixer_verification_media")
                    if isinstance(raw_audio_media, list):
                        audio_mixer_verification_media = [
                            dict(item)
                            for item in raw_audio_media
                            if isinstance(item, Mapping)
                        ]
                    rendered_path = rendered.get("output_path") or rendered.get("path") or rendered.get("media_path")
                    if rendered_path and Path(rendered_path) != output:
                        output.write_bytes(Path(rendered_path).read_bytes())
                elif isinstance(rendered, (str, Path)) and Path(rendered) != output:
                    output.write_bytes(Path(rendered).read_bytes())
            elif self.renderer is not None:
                rendered = self.renderer(source, output, context)
                if isinstance(rendered, Mapping):
                    raw_timeline_manifest = rendered.get("timeline_manifest")
                    if isinstance(raw_timeline_manifest, Mapping):
                        renderer_timeline_manifest = deepcopy(dict(raw_timeline_manifest))
                    raw_receipts = rendered.get("overlay_render_receipts")
                    if isinstance(raw_receipts, list):
                        overlay_render_receipts = [dict(item) for item in raw_receipts if isinstance(item, Mapping)]
                    raw_audio_media = rendered.get("audio_mixer_verification_media")
                    if isinstance(raw_audio_media, list):
                        audio_mixer_verification_media = [
                            dict(item)
                            for item in raw_audio_media
                            if isinstance(item, Mapping)
                        ]
                    rendered_path = rendered.get("output_path") or rendered.get("path") or rendered.get("media_path")
                    if rendered_path and Path(rendered_path) != output:
                        output.write_bytes(Path(rendered_path).read_bytes())
                elif isinstance(rendered, (str, Path)) and Path(rendered) != output:
                    output.write_bytes(Path(rendered).read_bytes())
            elif self.allow_passthrough:
                output.write_bytes(source.read_bytes())
            else:
                raise CapabilityUnavailable("compositor renderer is not configured")
            if not output.is_file() or output.stat().st_size == 0:
                raise CapabilityUnavailable("compositor produced no media bytes")
            data = output.read_bytes()
            digest = _sha256_bytes(data)
            if isinstance(audio_route_guard, Mapping):
                audio_regions = [
                    item
                    for item in audio_route_guard.get("regions", [])
                    if isinstance(item, Mapping)
                    and item.get("audio_policy") == "evidence_bound_mix"
                ]
                if audio_regions:
                    has_pending_receipts = any(
                        item.get("mixer_receipt_status")
                        == "pending_renderer_receipt"
                        for item in audio_regions
                    )
                    if has_pending_receipts and evidence_bound_mixer_identity is None:
                        raise ReplicationError(
                            "AUDIO_LAYER_POLICY_REQUIRED",
                            "AUDIO_LAYER_POLICY_REQUIRED: deferred mixing requires the immutable bundled mixer identity",
                            category="quality",
                            user_action_required=True,
                            http_status=422,
                        )
                    try:
                        candidate_receipts = _merge_audio_mixer_receipts(
                            audio_regions=audio_regions,
                            regions=regions,
                            renderer_receipts=(
                                renderer_timeline_manifest.get(
                                    "audio_mixer_receipts"
                                )
                                if isinstance(renderer_timeline_manifest, Mapping)
                                else None
                            ),
                        )
                        verification_by_id = {
                            str(item.get("region_id") or ""): item
                            for item in audio_mixer_verification_media
                        }
                        expected_audio_ids = {
                            str(item.get("region_id") or "")
                            for item in audio_regions
                        }
                        if (
                            set(verification_by_id) != expected_audio_ids
                            or len(verification_by_id)
                            != len(audio_mixer_verification_media)
                        ):
                            raise AudioMixerError(
                                "current audio mixer media coverage is incomplete"
                            )
                        from .timeline_renderer import _timeline_module

                        timeline_module = _timeline_module()
                        guard_by_id = {
                            str(item.get("region_id") or ""): item
                            for item in audio_regions
                        }
                        region_by_id = {
                            str(item.get("region_id") or ""): item
                            for item in regions
                        }
                        for receipt in candidate_receipts:
                            region_id = str(receipt.get("region_id") or "")
                            verification = verification_by_id[region_id]
                            opaque_media_path = Path(
                                verification.get("opaque_media_path") or ""
                            ).resolve()
                            mixed_region_path = Path(
                                verification.get("mixed_region_path") or ""
                            ).resolve()
                            opaque_info = timeline_module.probe_media(
                                opaque_media_path
                            )
                            active_window = timeline_module.detect_active_window(
                                opaque_media_path,
                                duration=timeline_module._video_duration(opaque_info),
                                fps=timeline_module._replacement_fps(
                                    opaque_info,
                                    fallback=float(
                                        getattr(context, "target_fps", 30) or 30
                                    ),
                                ),
                            )
                            region = region_by_id[region_id]
                            guard_region = guard_by_id[region_id]
                            speech_windows = guard_region.get("speech_windows")
                            if not isinstance(speech_windows, list):
                                raise AudioMixerError(
                                    "current audio mixer verification lacks frozen speech windows"
                                )
                            validate_evidence_bound_mix_receipt_media(
                                receipt=receipt,
                                source_media=source,
                                opaque_media=opaque_media_path,
                                mixed_media=mixed_region_path,
                                active_window=active_window,
                                region_id=region_id,
                                source_start_us=int(region.get("source_start_us")),
                                source_end_us=int(region.get("source_end_us")),
                                frozen_speech_windows=speech_windows,
                                mix_policy=(
                                    region.get("audio_mix_policy")
                                    if isinstance(
                                        region.get("audio_mix_policy"), Mapping
                                    )
                                    else None
                                ),
                            )
                        validated_receipts = validate_evidence_bound_mix_receipts(
                            receipts=candidate_receipts,
                            regions=regions,
                            audio_route_guard=audio_route_guard,
                            placements=(
                                renderer_timeline_manifest.get("placements")
                                if isinstance(renderer_timeline_manifest, Mapping)
                                else None
                            ),
                            source_media_sha256=source_media_sha256,
                            final_output_sha256=digest,
                            expected_mixer_identity_by_region={
                                str(item.get("region_id") or ""):
                                evidence_bound_mixer_identity
                                for item in audio_regions
                                if item.get("mixer_receipt_status")
                                == "pending_renderer_receipt"
                            },
                        )
                    except AudioMixerError as exc:
                        raise ReplicationError(
                            "AUDIO_LAYER_POLICY_REQUIRED",
                            f"AUDIO_LAYER_POLICY_REQUIRED: {exc}",
                            category="quality",
                            user_action_required=True,
                            http_status=422,
                        ) from exc
                    receipt_by_region = {
                        item["region_id"]: item for item in validated_receipts
                    }
                    for audio_region in audio_regions:
                        receipt = receipt_by_region[str(audio_region["region_id"])]
                        audio_region["mixer_receipt_status"] = str(
                            "verified_renderer_final_bound_receipt"
                            if audio_region.get("mixer_receipt_status")
                            == "pending_renderer_receipt"
                            else "verified_prebound_final_bound_receipt"
                        )
                        audio_region["mixer_receipt_sha256"] = _canonical_sha256(
                            receipt
                        )
                        audio_region["mixer_final_output_sha256"] = digest
                    audio_route_guard["status"] = (
                        "passed_final_bound_evidence_bound_mix"
                    )
                    if isinstance(renderer_timeline_manifest, dict):
                        renderer_timeline_manifest["audio_mixer_receipts"] = deepcopy(
                            validated_receipts
                        )
            if self.production and has_non_source_carrier:
                renderer_timeline_manifest = _validate_renderer_timeline_manifest(
                    renderer_timeline_manifest,
                    regions=regions,
                    artifacts=(getattr(context, "artifacts", ()) or ()),
                    output_sha256=digest,
                )
            if required_overlay_payloads:
                overlay_render_receipts = _validate_overlay_render_receipts(
                    overlay_render_receipts,
                    required_overlay_payloads,
                    source_overlay_contract_sha256=str(source_overlay_contract_sha256 or ""),
                    overlay_render_mapping_sha256=overlay_render_mapping_sha256,
                    output_sha256=digest,
                )
            probe = _probe(output)
            renderer_manifest_sha256: str | None = None
            if renderer_timeline_manifest is not None:
                declared_output_sha = str(
                    renderer_timeline_manifest.get("final_output_sha256") or ""
                ).strip().lower()
                if declared_output_sha and declared_output_sha != digest:
                    raise CapabilityUnavailable(
                        "renderer timeline manifest does not bind the current output bytes"
                    )
                declared_duration_us: int | None = None
                if renderer_timeline_manifest.get("duration_us") is not None:
                    try:
                        declared_duration_us = int(renderer_timeline_manifest["duration_us"])
                    except (TypeError, ValueError) as exc:
                        raise CapabilityUnavailable(
                            "renderer timeline manifest duration_us is invalid"
                        ) from exc
                elif renderer_timeline_manifest.get("actual_output_duration") is not None:
                    try:
                        declared_duration_us = round(
                            float(renderer_timeline_manifest["actual_output_duration"])
                            * 1_000_000
                        )
                    except (TypeError, ValueError) as exc:
                        raise CapabilityUnavailable(
                            "renderer timeline manifest actual_output_duration is invalid"
                        ) from exc
                if declared_duration_us is not None:
                    tolerance_us = max(
                        int(round(2_000_000 / float(probe.get("fps") or 30.0))),
                        50_000,
                    )
                    if abs(declared_duration_us - int(probe["duration_us"])) > tolerance_us:
                        raise CapabilityUnavailable(
                            "renderer timeline manifest duration does not match the current output"
                        )
                transition_renders = renderer_timeline_manifest.get("transition_renders")
                if isinstance(transition_renders, list):
                    for receipt in transition_renders:
                        if not isinstance(receipt, Mapping):
                            continue
                        receipt_sha = str(
                            receipt.get("final_output_sha256") or ""
                        ).strip().lower()
                        if receipt_sha and receipt_sha != digest:
                            raise CapabilityUnavailable(
                                "renderer transition receipt does not bind the current output bytes"
                            )
                        if not self.production:
                            receipt["final_output_sha256"] = digest
                try:
                    renderer_manifest_sha256 = _sha256_bytes(
                        json.dumps(
                            renderer_timeline_manifest,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8")
                    )
                except (TypeError, ValueError) as exc:
                    raise CapabilityUnavailable(
                        "renderer timeline manifest is not canonical JSON"
                    ) from exc
            if regions:
                cursor = 0
                for region in sorted(regions, key=lambda item: int(item.get("source_start_us", item.get("start_us", 0)) or 0)):
                    start = int(region.get("source_start_us", region.get("start_us", 0)) or 0)
                    end = int(region.get("source_end_us", region.get("end_us", 0)) or 0)
                    if start != cursor or end <= start:
                        raise ReplicationError(
                            "TIMELINE_COVERAGE_MISMATCH",
                            "compositor timeline regions contain a gap or overlap",
                            category="quality",
                            user_action_required=True,
                            http_status=422,
                        )
                    cursor = end
                if cursor <= 0:
                    raise ReplicationError("TIMELINE_COVERAGE_MISMATCH", "compositor timeline has no positive coverage", category="quality", http_status=422)
            timeline_parent_digest = _sha256_bytes(
                json.dumps(regions, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            profile = getattr(context, "profile_snapshot", None)
            profile_digest = ""
            if isinstance(profile, Mapping):
                profile_digest = str(profile.get("snapshot_sha256") or profile.get("config_digest") or "")
            if len(profile_digest) != 64:
                profile_digest = _sha256_bytes(
                    json.dumps(dict(profile or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                )
            publisher = getattr(context, "publish_artifact", None)
            if self.production and not callable(publisher):
                raise CapabilityUnavailable("compositor requires context.publish_artifact in production")
            timeline_manifest = (
                deepcopy(renderer_timeline_manifest)
                if renderer_timeline_manifest is not None
                else {}
            )
            timeline_manifest.update({
                "schema_version": "timeline-splice-manifest/v1",
                "duration_us": probe["duration_us"],
                "regions": regions,
                "source_duration_authority": "actual_composited_media",
                "output_duration_authority": "actual_composited_media",
                "transition_policy": "source_transition_shell_preserved",
                "audio_required": audio_required,
                "output_artifact": {
                    "kind": "assembled_video",
                    "sha256": digest,
                },
                "final_output_sha256": digest,
                "output_path": "assembled_video",
            })
            if renderer_manifest_sha256 is not None:
                timeline_manifest["renderer_manifest_sha256"] = renderer_manifest_sha256
            if source_overlay_contract is not None:
                timeline_manifest["source_overlay_contract"] = source_overlay_contract
                timeline_manifest["source_overlay_contract_sha256"] = source_overlay_contract_sha256
            if overlay_render_mapping is not None:
                timeline_manifest["overlay_render_mapping"] = overlay_render_mapping
                timeline_manifest["overlay_render_mapping_sha256"] = overlay_render_mapping_sha256
            if required_overlay_payloads:
                timeline_manifest["overlay_render_receipts_required"] = True
            if overlay_render_receipts:
                timeline_manifest["overlay_render_receipts"] = overlay_render_receipts
            if audio_route_guard is not None:
                timeline_manifest["audio_route_guard"] = audio_route_guard
            manifest_worker_roots = (
                source.parent,
                work_dir,
                output.parent,
                Path(audio_mix_verification_dir),
                Path(tempfile.gettempdir()),
            )
            timeline_manifest = _sanitize_public_timeline_manifest(
                timeline_manifest,
                worker_roots=manifest_worker_roots,
            )
            try:
                json.dumps(
                    timeline_manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise CapabilityUnavailable(
                    "final timeline manifest is not canonical JSON"
                ) from exc
            published_artifacts: list[Mapping[str, Any]] = []
            if callable(publisher):
                output_artifact = publisher(
                    kind="assembled_video",
                    stream=io.BytesIO(data),
                    content_type="video/mp4",
                    expected_sha256=digest,
                    metadata={
                        "producer": self._identity["implementation"],
                        "producer_stage": "splice_timeline",
                        "parent_digests": {"timeline_regions": timeline_parent_digest},
                        "profile_digest": profile_digest,
                        "media_origin": "composited",
                    },
                )
                published_artifacts.append(output_artifact)
            else:
                output_artifact = {
                    "kind": "assembled_video",
                    "sha256": digest,
                    "uri": f"memory://assembled/{digest}",
                    "object_key": f"memory://assembled/{digest}",
                }
            timeline_manifest["output_artifact"] = _public_manifest_artifact_descriptor(
                output_artifact,
                default_kind="assembled_video",
                expected_sha256=digest,
            )
            manifest_artifact = None
            if callable(publisher):
                encoded_manifest = json.dumps(
                    timeline_manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                manifest_sha = _sha256_bytes(encoded_manifest)
                manifest_artifact = publisher(
                    kind="hybrid_composite_manifest",
                    stream=io.BytesIO(encoded_manifest),
                    content_type="application/json",
                    expected_sha256=manifest_sha,
                    metadata={
                        "producer_stage": "splice_timeline",
                        "parent_digests": {"timeline_regions": timeline_parent_digest},
                        "profile_digest": profile_digest,
                    },
                )
                published_artifacts.append(manifest_artifact)
            return {
                "status": "ready",
                "output_artifact": output_artifact,
                "timeline_manifest": timeline_manifest,
                "manifest_artifact": manifest_artifact,
                "overlay_render_receipts": overlay_render_receipts,
                # Local compatibility descriptors use memory:// URIs and are
                # intentionally not persisted as stage artifacts.  Only the
                # worker-owned publisher receipts are eligible for durable
                # publication and downstream materialization.
                "published_artifacts": list(published_artifacts),
                "capability_identity": dict(self._identity),
            }


class FfmpegQcEngine:
    """Technical final-media QC that blocks A/V drift and black splice frames."""

    def __init__(
        self,
        *,
        production: bool = False,
        evaluator: Any | None = None,
        ffmpeg_bin: str | None = None,
        implementation: str = "server.real_capabilities:FfmpegQcEngine",
        version: str = "1.0.0",
        sha256: str | None = None,
    ) -> None:
        self.production = bool(production)
        self.evaluator = evaluator
        self.ffmpeg_bin = ffmpeg_bin
        self._identity = _identity("qc_engine", implementation, version, sha256, require_explicit_digest=self.production)

    def capability_identity(self) -> Mapping[str, Any]:
        return dict(self._identity)

    def _evaluator_identity(self, context: Any) -> Mapping[str, Any] | None:
        if self.evaluator is not None:
            identity_method = getattr(self.evaluator, "capability_identity", None)
            if not callable(identity_method):
                if self.production and self._active_profile(context):
                    raise CapabilityUnavailable(
                        "active production QC evaluator must expose capability_identity()"
                    )
            else:
                identity = identity_method()
                if not isinstance(identity, Mapping):
                    raise CapabilityUnavailable("QC evaluator capability_identity() must return an object")
                normalized = dict(identity)
                for field in ("implementation", "version", "model_id"):
                    if not str(normalized.get(field) or "").strip():
                        raise CapabilityUnavailable(
                            f"active production QC evaluator identity requires {field}"
                        )
                if not _is_sha256(normalized.get("model_sha256")):
                    raise CapabilityUnavailable(
                        "active production QC evaluator identity requires model_sha256"
                    )
                binding = str(normalized.get("evidence_binding") or "")
                if binding and (not binding.startswith("usfr-") or not binding.endswith("/v1")):
                    raise CapabilityUnavailable(
                        "active production QC evaluator evidence_binding must be versioned"
                    )
                return normalized
        configured = getattr(context, "high_fidelity_qc_evaluator_identity", None)
        return dict(configured) if isinstance(configured, Mapping) else None

    def _run_evaluator(
        self,
        *,
        context: Any,
        input_artifacts: list[Mapping[str, Any]],
        media_path: Path,
        final_output_sha256: str,
        current_run_source_sha256s: set[str],
        source_audio_performance: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        """Invoke the deployment-owned semantic evaluator in production.

        The evaluator only supplies score/evidence input plus a provenance
        receipt.  This adapter does not interpret semantic scores itself.
        """

        if self.evaluator is None:
            return None
        operation = getattr(self.evaluator, "evaluate", None)
        if not callable(operation):
            operation = getattr(self.evaluator, "run", None)
        if not callable(operation) and callable(self.evaluator):
            operation = self.evaluator
        if not callable(operation):
            raise CapabilityUnavailable("QC evaluator must expose evaluate(), run(), or __call__()")
        request_payload = {
            "schema_version": "high-fidelity-qc-evaluator-request/v1",
            "final_output_sha256": final_output_sha256,
            "current_run_source_sha256s": sorted(current_run_source_sha256s),
            "input_artifact_sha256s": sorted(
                str(item.get("sha256") or "").lower()
                for item in input_artifacts
                if isinstance(item, Mapping)
                and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256") or "").lower())
            ),
        }
        if source_audio_performance is not None:
            request_payload["source_audio_performance"] = dict(source_audio_performance)
        request_sha256 = _canonical_sha256(request_payload)
        kwargs = {
            "path": media_path,
            "context": context,
            "input_artifacts": input_artifacts,
            "final_output_sha256": final_output_sha256,
            "current_run_source_sha256s": sorted(current_run_source_sha256s),
            "source_audio_performance": source_audio_performance,
            "request_payload": request_payload,
            "request_sha256": request_sha256,
        }
        try:
            result = operation(**kwargs)
        except TypeError:
            result = operation(media_path)
        if not isinstance(result, Mapping):
            raise CapabilityUnavailable("QC evaluator returned no evidence-bearing object")
        payload = result.get("qc_input")
        if isinstance(payload, Mapping):
            qc_input = dict(payload)
        else:
            qc_input = dict(result)
        receipt = qc_input.get("evaluator_receipt")
        if not isinstance(receipt, Mapping):
            raise CapabilityUnavailable("QC evaluator returned no evaluator receipt")
        response_payload = {
            key: value for key, value in qc_input.items() if key != "evaluator_receipt"
        }
        expected_response_sha256 = _canonical_sha256(response_payload)
        if str(receipt.get("request_sha256") or "") != request_sha256:
            raise CapabilityUnavailable("QC evaluator receipt request SHA does not match the call payload")
        if str(receipt.get("response_sha256") or "") != expected_response_sha256:
            raise CapabilityUnavailable("QC evaluator receipt response SHA does not match the returned result")
        return qc_input

    @staticmethod
    def _source_audio_performance_request(
        context: Any,
        *,
        timeline_manifest: Mapping[str, Any] | None,
        final_output_sha256: str,
    ) -> Mapping[str, Any] | None:
        """Project source-performance evidence for an independent QC worker.

        The evaluator needs source/global timing and the performance-line
        contract digest to assess lips and beat actions.  It must never receive
        source audio/video bytes, opaque UI/tail bytes, or worker-local paths.
        """

        if not isinstance(timeline_manifest, Mapping):
            return None
        receipt = timeline_manifest.get("source_audio_performance_receipt")
        if receipt is None:
            return None
        if not isinstance(receipt, Mapping):
            raise CapabilityUnavailable("source audio performance remux receipt must be an object")
        if receipt.get("schema_version") != "source-audio-performance-remux/v1":
            raise CapabilityUnavailable("source audio performance remux receipt schema is unsupported")
        expected_final_sha = str(final_output_sha256 or "").lower()
        if not _is_sha256(expected_final_sha):
            raise CapabilityUnavailable("source audio performance final output SHA-256 is invalid")
        if str(receipt.get("final_output_sha256") or "").lower() != expected_final_sha:
            raise CapabilityUnavailable("source audio performance remux receipt is not bound to the final output")
        normalized_receipt: dict[str, str] = {}
        for field in ("source_media_sha256", "source_audio_sha256", "request_sha256"):
            digest = str(receipt.get(field) or "").lower()
            if not _is_sha256(digest):
                raise CapabilityUnavailable(f"source audio performance remux receipt requires {field}")
            normalized_receipt[field] = digest

        descriptors = [
            item
            for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping)
            and str(item.get("kind") or "") == "performance_line_contract"
        ]
        if len(descriptors) != 1:
            raise CapabilityUnavailable(
                "source audio performance evaluator request requires exactly one performance_line_contract artifact"
            )
        performance_line_sha = str(descriptors[0].get("sha256") or "").lower()
        if not _is_sha256(performance_line_sha):
            raise CapabilityUnavailable(
                "source audio performance evaluator request performance_line_contract SHA-256 is invalid"
            )

        raw_regions = receipt.get("regions")
        if not isinstance(raw_regions, list):
            raise CapabilityUnavailable("source audio performance remux receipt regions must be an array")
        regions: list[dict[str, Any]] = []
        region_ids: set[str] = set()
        for index, raw_region in enumerate(raw_regions):
            if not isinstance(raw_region, Mapping):
                raise CapabilityUnavailable(f"source audio performance remux region {index} must be an object")
            region_id = str(raw_region.get("region_id") or "").strip()
            mode = str(raw_region.get("audio_mode") or "").strip()
            if not region_id or region_id in region_ids:
                raise CapabilityUnavailable("source audio performance remux regions require unique IDs")
            region_ids.add(region_id)

            def bound(field: str) -> int:
                value = raw_region.get(field)
                if isinstance(value, bool):
                    raise CapabilityUnavailable(f"source audio performance remux region {region_id} {field} is invalid")
                try:
                    result = int(value)
                except (TypeError, ValueError) as exc:
                    raise CapabilityUnavailable(
                        f"source audio performance remux region {region_id} requires {field}"
                    ) from exc
                if result < 0:
                    raise CapabilityUnavailable(
                        f"source audio performance remux region {region_id} {field} must be non-negative"
                    )
                return result

            output_start_us = bound("output_start_us")
            output_end_us = bound("output_end_us")
            if output_end_us <= output_start_us:
                raise CapabilityUnavailable(
                    f"source audio performance remux region {region_id} output window is invalid"
                )
            projected: dict[str, Any] = {
                "region_id": region_id,
                "audio_mode": mode,
                "output_start_us": output_start_us,
                "output_end_us": output_end_us,
            }
            if mode == "source_master":
                source_start_us = bound("source_start_us")
                source_end_us = bound("source_end_us")
                if source_end_us <= source_start_us or (
                    source_end_us - source_start_us != output_end_us - output_start_us
                ):
                    raise CapabilityUnavailable(
                        f"source audio performance remux region {region_id} source window is invalid"
                    )
                projected.update(
                    {
                        "source_start_us": source_start_us,
                        "source_end_us": source_end_us,
                    }
                )
            elif mode == "opaque_audio_keep":
                opaque_sha = str(raw_region.get("opaque_media_sha256") or "").lower()
                if not _is_sha256(opaque_sha):
                    raise CapabilityUnavailable(
                        f"source audio performance remux opaque region {region_id} requires opaque_media_sha256"
                    )
                projected["opaque_media_sha256"] = opaque_sha
            else:
                raise CapabilityUnavailable(
                    f"source audio performance remux region {region_id} has unsupported audio mode"
                )
            regions.append(projected)

        return {
            "performance_line_contract_sha256": performance_line_sha,
            "final_output_sha256": expected_final_sha,
            "source_media_sha256": normalized_receipt["source_media_sha256"],
            "source_audio_sha256": normalized_receipt["source_audio_sha256"],
            "remux_request_sha256": normalized_receipt["request_sha256"],
            "regions": regions,
        }

    def _load_timeline_manifest(self, context: Any) -> tuple[Mapping[str, Any] | None, str | None]:
        """Read immutable output-clock evidence from the compositor.

        Source-region timestamps describe the input contract.  They are not
        the output clock when an opaque UI/tail interval is elastic.  The
        compositor's manifest records the actual output duration and is the
        only authority QC may use for that comparison.
        """

        inline = getattr(context, "timeline_manifest", None)
        if isinstance(inline, Mapping):
            return dict(inline), "context"
        materialize = getattr(context, "materialize_artifact", None)
        if not callable(materialize):
            return None, None
        available = {
            str(item.get("kind") or "")
            for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping)
        }
        if "hybrid_composite_manifest" not in available:
            return None, None
        try:
            with materialize("hybrid_composite_manifest") as manifest_media:
                raw = Path(manifest_media.path).read_bytes()
            descriptor = next(
                (
                    item
                    for item in (getattr(context, "artifacts", ()) or ())
                    if isinstance(item, Mapping)
                    and str(item.get("kind") or "") == "hybrid_composite_manifest"
                ),
                None,
            )
            declared_sha = str((descriptor or {}).get("sha256") or "").lower()
            if declared_sha and declared_sha != _sha256_bytes(raw):
                raise CapabilityUnavailable(
                    "timeline manifest SHA-256 does not match its published artifact"
                )
            parsed = json.loads(raw.decode("utf-8"))
        except CapabilityUnavailable:
            raise
        except Exception as exc:
            if self.production:
                raise CapabilityUnavailable(
                    "published timeline manifest cannot be materialized or parsed"
                ) from exc
            return None, None
        if not isinstance(parsed, Mapping):
            if self.production:
                raise CapabilityUnavailable("published timeline manifest must be an object")
            return None, None
        return dict(parsed), "artifact"

    def _find_media(self, context: Any) -> Any:
        available = {
            str(item.get("kind") or "")
            for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping)
        }
        for kind in ("assembled_video", "provider_video"):
            materialize = getattr(context, "materialize_artifact", None)
            if callable(materialize) and kind in available:
                return kind, materialize(kind)
        if not self.production:
            return "source_video", _materialize(context, "source_video")
        raise CapabilityUnavailable("QC requires a published assembled/provider video artifact")

    @staticmethod
    def _active_profile(context: Any) -> bool:
        """Return whether the run requires the weighted HF QC extension."""

        return _active_high_fidelity(context)

    @staticmethod
    def _weighted_input(context: Any) -> Mapping[str, Any] | None:
        """Resolve deployment-owned weighted QC evidence for the current run.

        A worker may expose the evidence directly on its lease context or
        attach it to an immutable upstream artifact/manifest.  We accept a
        small set of names for compatibility with deployment adapters, but do
        not derive a score from a summary flag.  The packaged weighted helper
        below is the sole authority for score calculation and gate evaluation.
        """

        for name in (
            "high_fidelity_qc_input",
            "high_fidelity_qc_evidence",
            "qc_extension_input",
        ):
            value = getattr(context, name, None)
            if isinstance(value, Mapping):
                return dict(value)

        for container_name in ("timeline_manifest", "compositor_manifest"):
            container = getattr(context, container_name, None)
            if isinstance(container, Mapping):
                for key in (
                    "high_fidelity_qc_input",
                    "high_fidelity_qc_evidence",
                    "qc_extension_input",
                ):
                    value = container.get(key)
                    if isinstance(value, Mapping):
                        return dict(value)

        for artifact in getattr(context, "artifacts", ()) or ():
            if not isinstance(artifact, Mapping):
                continue
            metadata = artifact.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            for key in (
                "high_fidelity_qc_input",
                "high_fidelity_qc_evidence",
                "qc_extension_input",
            ):
                value = metadata.get(key)
                if isinstance(value, Mapping):
                    return dict(value)
        return None

    @staticmethod
    def _final_audio_records(
        context: Any,
        *,
        timeline_manifest: Mapping[str, Any] | None,
        evaluator_response: Mapping[str, Any] | None,
    ) -> tuple[
        Mapping[str, Any] | None,
        Mapping[str, Any] | None,
        Mapping[str, str],
    ]:
        """Resolve canonical final-audio records from immutable execution data.

        Direct lease-context values remain first for compatibility. Production
        adapters may instead package the same records in compositor manifests,
        stage outputs, artifact metadata, or the independent evaluator response.
        Summary booleans and self-reported scores are deliberately ignored.
        """

        contract = getattr(context, "final_audio_contract", None)
        evidence = getattr(context, "final_audio_qc_evidence", None)
        resolved_contract = dict(contract) if isinstance(contract, Mapping) else None
        resolved_evidence = dict(evidence) if isinstance(evidence, Mapping) else None
        sources: dict[str, str] = {}
        if resolved_contract is not None:
            sources["contract"] = "context.final_audio_contract"
        if resolved_evidence is not None:
            sources["evidence"] = "context.final_audio_qc_evidence"

        def consider(container: Any, label: str) -> None:
            nonlocal resolved_contract, resolved_evidence
            if not isinstance(container, Mapping):
                return
            candidates: list[tuple[Mapping[str, Any], str]] = [(container, label)]
            for envelope_key in ("final_audio_qc", "final_audio_delivery"):
                envelope = container.get(envelope_key)
                if isinstance(envelope, Mapping):
                    candidates.append((envelope, f"{label}.{envelope_key}"))
            for candidate, candidate_label in candidates:
                if resolved_contract is None:
                    value = candidate.get("final_audio_contract")
                    if not isinstance(value, Mapping) and candidate is not container:
                        value = candidate.get("contract")
                    if isinstance(value, Mapping):
                        resolved_contract = dict(value)
                        sources["contract"] = candidate_label
                if resolved_evidence is None:
                    value = candidate.get("final_audio_qc_evidence")
                    if not isinstance(value, Mapping) and candidate is not container:
                        value = candidate.get("evidence")
                    if isinstance(value, Mapping):
                        resolved_evidence = dict(value)
                        sources["evidence"] = candidate_label

        consider(timeline_manifest, "timeline_manifest")
        consider(getattr(context, "compositor_manifest", None), "compositor_manifest")

        stage_outputs = getattr(context, "stage_outputs", None)
        if isinstance(stage_outputs, Mapping):
            for stage_name, output in stage_outputs.items():
                label = f"stage_outputs.{stage_name}"
                consider(output, label)
                if isinstance(output, Mapping):
                    consider(output.get("timeline_manifest"), f"{label}.timeline_manifest")
                    consider(output.get("compositor_manifest"), f"{label}.compositor_manifest")

        for index, artifact in enumerate(getattr(context, "artifacts", ()) or ()):
            if not isinstance(artifact, Mapping):
                continue
            metadata = artifact.get("metadata")
            kind = str(artifact.get("kind") or index)
            consider(metadata, f"artifacts.{kind}.metadata")

        consider(evaluator_response, "independent_evaluator_response")
        return resolved_contract, resolved_evidence, sources

    @staticmethod
    def _source_audio_performance_evidence(
        context: Any,
        *,
        timeline_manifest: Mapping[str, Any] | None,
        evaluator_response: Mapping[str, Any] | None,
    ) -> Mapping[str, Any] | None:
        direct = getattr(context, "source_audio_performance_qc_evidence", None)
        if isinstance(direct, Mapping):
            return dict(direct)
        candidates: list[Any] = [timeline_manifest, evaluator_response]
        stage_outputs = getattr(context, "stage_outputs", None)
        if isinstance(stage_outputs, Mapping):
            candidates.extend(stage_outputs.values())
        for container in candidates:
            if not isinstance(container, Mapping):
                continue
            for key in ("source_audio_performance_qc_evidence", "source_audio_performance_qc"):
                value = container.get(key)
                if isinstance(value, Mapping):
                    return dict(value)
        return None

    @staticmethod
    def _build_weighted_extension(
        context: Any,
        *,
        route_ok: bool,
        ui_ok: bool,
        technical_failures: list[str],
        final_output_sha256: str,
        current_run_source_sha256s: set[str],
        weighted_input: Mapping[str, Any] | None = None,
        expected_evaluator_identity: Mapping[str, Any] | None = None,
        require_evaluator_receipt: bool = False,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Build and validate the weighted report from real evidence.

        ``high_fidelity_qc.py`` rejects missing dimensions/evidence and
        recomputes the weighted total and acceptance gates.  We additionally
        bind route/UI gates to deterministic technical QC so a caller cannot
        claim 100% while the media scan failed.
        """

        value = dict(weighted_input) if isinstance(weighted_input, Mapping) else FfmpegQcEngine._weighted_input(context)
        if value is None:
            return None, "HIGH_FIDELITY_QC_EVIDENCE_MISSING"
        try:
            module = _load_high_fidelity_qc_module()
            dimensions = value.get("dimensions")
            factor_scores = value.get("factor_scores")
            if not isinstance(factor_scores, Mapping) or not factor_scores:
                raise ValueError("factor_scores must contain real evidence records")
            if not isinstance(value.get("hard_failures", []), list):
                raise ValueError("hard_failures must be an array")
            evaluator_receipt = value.get("evaluator_receipt")
            if require_evaluator_receipt and not isinstance(evaluator_receipt, Mapping):
                raise ValueError("active high-fidelity QC requires an evaluator receipt")
            supplied_failures = [
                str(item)
                for item in value.get("hard_failures", [])
                if isinstance(item, str) and item.strip()
            ]
            # Route/UI are deterministic technical gates; never trust a
            # caller-supplied 100 when the assembled media failed those
            # checks.
            route_coverage = value.get("route_coverage")
            if not route_ok:
                route_coverage = 0
            ui_ocr = value.get("ui_ocr")
            if not ui_ok:
                ui_ocr = 0
            hard_failures = list(dict.fromkeys([*supplied_failures, *technical_failures]))
            extension = module.build_qc_extension(
                dimensions=dimensions,
                route_coverage=route_coverage,
                ui_ocr=ui_ocr,
                hard_failures=hard_failures,
                factor_scores=factor_scores,
                media_bindings={
                    "final_output_sha256": final_output_sha256,
                    "current_run_source_sha256s": sorted(current_run_source_sha256s),
                },
                evaluator_receipt=evaluator_receipt,
                expected_evaluator_identity=expected_evaluator_identity,
            )
            # Re-validate accepted reports through the strict helper.  The
            # helper intentionally raises for a rejected report; rejected
            # reports are still retained as diagnostic evidence so the
            # caller can see which hard gate blocked delivery.
            if extension.get("accepted") is True:
                module.validate_qc_extension(
                    extension,
                    require_evaluator_receipt=require_evaluator_receipt,
                    expected_evaluator_identity=expected_evaluator_identity,
                )
            return dict(extension), None
        except Exception as exc:
            return None, f"HIGH_FIDELITY_QC_EVIDENCE_INVALID: {exc}"

    @staticmethod
    def _current_run_source_sha256s(
        context: Any,
        input_artifacts: list[Mapping[str, Any]],
    ) -> set[str]:
        """Return immutable source/evidence digests owned by the current run."""

        digests: set[str] = set()

        def add(value: Any) -> None:
            digest = str(value or "").lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                digests.add(digest)

        for slot in getattr(context, "input_slots", ()) or ():
            if not isinstance(slot, Mapping) or not slot.get("present"):
                continue
            slot_hashes = slot.get("sha256")
            if isinstance(slot_hashes, str):
                add(slot_hashes)
            elif isinstance(slot_hashes, Sequence):
                for digest in slot_hashes:
                    add(digest)
        for item in input_artifacts or []:
            if isinstance(item, Mapping):
                add(item.get("sha256"))
        for item in getattr(context, "artifacts", ()) or ():
            if not isinstance(item, Mapping):
                continue
            if str(item.get("kind") or "") in {
                "assembled_video",
                "provider_video",
                "high_fidelity_qc_extension",
            }:
                continue
            add(item.get("sha256"))

        # Local/legacy test contexts may expose only materialize_slot().  The
        # active server path above is authoritative, but this fallback still
        # binds evidence to the exact current source bytes rather than a label.
        if not digests:
            try:
                with _materialize(context, "source_video") as source_media:
                    add(getattr(source_media, "sha256", None))
                    if not digests:
                        add(_sha256_file(Path(source_media.path)))
            except Exception:
                pass
        return digests

    def run(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        kind, manager = self._find_media(context)
        with manager as media:
            path = Path(media.path)
            final_output_sha256 = _sha256_file(path)
            current_run_source_sha256s = self._current_run_source_sha256s(
                context, input_artifacts
            )
            probe = _probe(path)
            hard_failures: list[str] = []
            streams = probe.get("audio_streams") or []
            if probe.get("has_audio") and probe.get("audio_duration_us"):
                tolerance_us = max(int(round(2_000_000 / float(probe.get("fps") or 30.0))), 50_000)
                if abs(int(probe.get("video_duration_us") or probe["duration_us"]) - int(probe.get("audio_duration_us") or 0)) > tolerance_us:
                    hard_failures.append("AUDIO_VIDEO_DURATION_DRIFT")
                start_delta_us = abs(
                    int(probe.get("audio_start_time_us") or 0)
                    - int(probe.get("video_start_time_us") or 0)
                )
                if start_delta_us > tolerance_us:
                    hard_failures.append("AUDIO_VIDEO_START_OFFSET")
            else:
                start_delta_us = 0
            active_profile = self._active_profile(context)
            regions = [dict(item) for item in (getattr(context, "timeline_regions", ()) or ()) if isinstance(item, Mapping)]
            generated_ui_regions = [
                item for item in regions
                if str(item.get("kind") or item.get("region_type") or "").lower() in {"generated_ui_demo", "generated_ui"}
            ]
            ui_ok = True
            if generated_ui_regions:
                def ui_metrics(item: Mapping[str, Any]) -> Mapping[str, Any]:
                    for key in ("ui_qc", "ui_qc_report"):
                        nested = item.get(key)
                        if isinstance(nested, Mapping):
                            return nested
                    return item

                ui_ok = all(
                    ui_metrics(item).get("ocr_match_percent") == 100
                    and ui_metrics(item).get("layout_match_percent") == 100
                    and (
                        not active_profile
                        or (
                            ui_metrics(item).get("animation_qc_required") is True
                            and ui_metrics(item).get("animation_ocr_match_percent") == 100
                            and ui_metrics(item).get("animation_layout_match_percent") == 100
                        )
                    )
                    for item in generated_ui_regions
                )
                if not ui_ok:
                    hard_failures.append("UI_EVIDENCE_MISSING")
            timeline_manifest, timeline_manifest_source = self._load_timeline_manifest(context)
            audio_required = _final_audio_stream_required(context, timeline_manifest)
            if audio_required and (not probe.get("has_audio") or not streams):
                hard_failures.append("FINAL_AUDIO_STREAM_REQUIRED")
            overlay_receipts_ok = True
            if isinstance(timeline_manifest, Mapping) and timeline_manifest.get("overlay_render_receipts_required") is True:
                receipts = timeline_manifest.get("overlay_render_receipts")
                overlay_receipts_ok = isinstance(receipts, list) and bool(receipts)
                if not overlay_receipts_ok:
                    hard_failures.append("OVERLAY_RENDER_RECEIPT_REQUIRED")
            route_ok = True
            if regions:
                covered = 0
                for item in sorted(regions, key=lambda row: int(row.get("source_start_us", row.get("start_us", 0)) or 0)):
                    start = int(item.get("source_start_us", item.get("start_us", 0)) or 0)
                    end = int(item.get("source_end_us", item.get("end_us", 0)) or 0)
                    if start != covered or end <= start:
                        route_ok = False
                        break
                    covered = end
                if timeline_manifest is not None:
                    try:
                        manifest_duration_us = int(timeline_manifest.get("duration_us") or 0)
                    except (TypeError, ValueError):
                        manifest_duration_us = 0
                    tolerance_us = max(
                        int(round(2_000_000 / float(probe.get("fps") or 30.0))),
                        50_000,
                    )
                    route_ok = route_ok and manifest_duration_us > 0 and abs(
                        manifest_duration_us - int(probe["duration_us"])
                    ) <= tolerance_us
                elif self.production:
                    route_ok = False
                else:
                    # Legacy/local contexts may not have a compositor
                    # manifest.  Preserve their historical source-duration
                    # check while active production fails closed above.
                    route_ok = route_ok and covered == int(probe["duration_us"])
                if not route_ok:
                    hard_failures.append("TIMELINE_COVERAGE_MISMATCH")
            if self.production and timeline_manifest is None:
                hard_failures.append("TIMELINE_MANIFEST_MISSING")
            ffmpeg = _executable("ffmpeg", self.ffmpeg_bin)
            scan_fps = float(probe.get("fps") or 30.0)
            minimum_black = max(0.5 / scan_fps, 0.001)
            black_scan = _run([
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-vf",
                # A 99% picture threshold misclassifies a sparse, legitimate
                # Logo/download mark on a black App card as a full black
                # frame.  This gate must reject only genuinely full-black
                # frames; preserve any decoded non-black pixel.
                f"scale=160:-2,blackdetect=d={minimum_black:.6f}:pix_th=0.1:pic_th=1.0",
                "-an",
                "-f",
                "null",
                "-",
            ])
            black_intervals = _parse_black_detect_intervals(black_scan.stderr)
            if _black_interval_is_boundary_failure(
                black_intervals,
                duration=float(probe["duration_us"]) / 1_000_000.0,
                fps=scan_fps,
                timeline_manifest=timeline_manifest,
            ):
                hard_failures.append("BLACK_FRAME_DETECTED")
            minimum_freeze = max(0.5, 2.0 / max(scan_fps, 1.0))
            freeze_scan = _run([
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-vf",
                (
                    "scale=160:-2,setpts=PTS-STARTPTS,"
                    f"freezedetect=n=-60dB:d={minimum_freeze:.6f}"
                ),
                "-an",
                "-f",
                "null",
                "-",
            ])
            freeze_intervals = _parse_freeze_detect_intervals(
                freeze_scan.stderr,
                duration=float(probe["duration_us"]) / 1_000_000.0,
            )
            freeze_failure = _freeze_interval_failure_code(
                freeze_intervals,
                duration=float(probe["duration_us"]) / 1_000_000.0,
                fps=scan_fps,
                timeline_manifest=timeline_manifest,
                minimum_duration=minimum_freeze,
            )
            if freeze_failure:
                hard_failures.append(freeze_failure)

            raw_audio_policy = getattr(context, "audio_qc_policy", None)
            audio_policy = dict(raw_audio_policy) if isinstance(raw_audio_policy, Mapping) else {}
            measure_audio_quality = bool(
                audio_policy.get("measure", audio_policy.get("enforce", active_profile))
            )
            audio_quality: dict[str, Any] = {
                "status": "not_requested" if not measure_audio_quality else "pending",
                "boundary_count": 0,
                "boundary_checks": [],
            }
            if probe.get("has_audio") and measure_audio_quality:
                try:
                    audio_quality = _measure_audio_quality(
                        path,
                        timeline_manifest=timeline_manifest,
                        policy=audio_policy,
                        ffmpeg_bin=self.ffmpeg_bin,
                    )
                    hard_failures.extend(audio_quality.get("hard_failures") or [])
                except CapabilityUnavailable as exc:
                    audio_quality = {
                        "status": "unavailable",
                        "error": str(exc),
                        "boundary_count": len(_audio_boundary_times(timeline_manifest)),
                        "boundary_checks": [],
                    }
                    hard_failures.append("AUDIO_QUALITY_MEASUREMENT_UNAVAILABLE")

            weighted_extension: dict[str, Any] | None = None
            weighted_input: Mapping[str, Any] | None = None
            weighted_error: str | None = None
            evaluator_identity: Mapping[str, Any] | None = None
            require_receipt = False
            source_audio_performance: Mapping[str, Any] | None = None
            source_audio_evaluator_error: str | None = None
            source_audio_receipt = (
                timeline_manifest.get("source_audio_performance_receipt")
                if isinstance(timeline_manifest, Mapping)
                else None
            )
            source_audio_route_declared = source_audio_receipt is not None
            source_audio_route_active = isinstance(source_audio_receipt, Mapping)
            if active_profile or (self.production and source_audio_route_declared):
                evaluator_identity = self._evaluator_identity(context)
                require_receipt = self.production or getattr(
                    context, "allow_local_paths", True
                ) is False
                if self.production:
                    if source_audio_route_declared and not source_audio_route_active:
                        weighted_error = "SOURCE_AUDIO_PERFORMANCE_REMUX_RECEIPT_INVALID"
                        source_audio_evaluator_error = weighted_error
                    elif self.evaluator is None:
                        weighted_error = "HIGH_FIDELITY_QC_EVALUATOR_MISSING"
                        if source_audio_route_active:
                            source_audio_evaluator_error = weighted_error
                    else:
                        try:
                            if source_audio_route_active:
                                source_audio_performance = self._source_audio_performance_request(
                                    context,
                                    timeline_manifest=timeline_manifest,
                                    final_output_sha256=final_output_sha256,
                                )
                            weighted_input = self._run_evaluator(
                                context=context,
                                input_artifacts=input_artifacts,
                                media_path=path,
                                final_output_sha256=final_output_sha256,
                                current_run_source_sha256s=current_run_source_sha256s,
                                source_audio_performance=source_audio_performance,
                            )
                        except CapabilityUnavailable as exc:
                            weighted_error = str(exc)
                            if source_audio_route_active:
                                source_audio_evaluator_error = str(exc)
                        if weighted_error is None and weighted_input is None:
                            weighted_error = "HIGH_FIDELITY_QC_EVALUATOR_EMPTY"
                            if source_audio_route_active:
                                source_audio_evaluator_error = weighted_error

            final_audio_qc: dict[str, Any] = {"status": "not_requested"}
            (
                final_audio_contract,
                final_audio_evidence,
                final_audio_sources,
            ) = self._final_audio_records(
                context,
                timeline_manifest=timeline_manifest,
                evaluator_response=weighted_input,
            )
            final_audio_required = bool(
                getattr(context, "final_audio_qc_required", False)
            ) or (self.production and active_profile and audio_required)
            if (
                isinstance(final_audio_contract, Mapping)
                or isinstance(final_audio_evidence, Mapping)
                or final_audio_required
            ):
                if not isinstance(final_audio_contract, Mapping) or not isinstance(
                    final_audio_evidence, Mapping
                ):
                    final_audio_qc = {
                        "status": "missing",
                        "required": final_audio_required,
                        "missing": [
                            name
                            for name, value in (
                                ("final_audio_contract", final_audio_contract),
                                ("final_audio_qc_evidence", final_audio_evidence),
                            )
                            if not isinstance(value, Mapping)
                        ],
                        "record_sources": dict(final_audio_sources),
                        "final_output_sha256": final_output_sha256,
                    }
                    hard_failures.append("FINAL_AUDIO_QC_EVIDENCE_MISSING")
                else:
                    try:
                        final_audio_qc = validate_final_audio_qc(
                            contract=final_audio_contract,
                            evidence=final_audio_evidence,
                            final_output_sha256=final_output_sha256,
                        )
                        final_audio_qc["status"] = "passed"
                        final_audio_qc["record_sources"] = dict(final_audio_sources)
                    except (AudioBackendUnavailable, TypeError, ValueError) as exc:
                        final_audio_qc = {
                            "status": "failed",
                            "error": str(exc),
                            "record_sources": dict(final_audio_sources),
                            "final_output_sha256": final_output_sha256,
                            "evidence_final_output_sha256": str(
                                final_audio_evidence.get("final_output_sha256") or ""
                            ),
                        }
                        hard_failures.append("FINAL_AUDIO_QC_FAILED")

            source_audio_performance_qc: dict[str, Any] = {"status": "not_requested"}
            remux_receipt = (
                timeline_manifest.get("source_audio_performance_receipt")
                if isinstance(timeline_manifest, Mapping)
                else None
            )
            if source_audio_route_declared and not isinstance(remux_receipt, Mapping):
                source_audio_performance_qc = {
                    "status": "failed",
                    "error": source_audio_evaluator_error
                    or "source audio performance remux receipt must be an object",
                    "final_output_sha256": final_output_sha256,
                }
                hard_failures.append("SOURCE_AUDIO_PERFORMANCE_EVALUATOR_REQUEST_INVALID")
            elif isinstance(remux_receipt, Mapping):
                if source_audio_evaluator_error is not None:
                    source_audio_performance_qc = {
                        "status": "failed",
                        "error": source_audio_evaluator_error,
                        "final_output_sha256": final_output_sha256,
                    }
                    hard_failures.append("SOURCE_AUDIO_PERFORMANCE_EVALUATOR_REQUEST_INVALID")
                else:
                    source_audio_evidence = self._source_audio_performance_evidence(
                        context,
                        timeline_manifest=timeline_manifest,
                        evaluator_response=weighted_input,
                    )
                    if not isinstance(source_audio_evidence, Mapping):
                        source_audio_performance_qc = {
                            "status": "missing",
                            "final_output_sha256": final_output_sha256,
                        }
                        hard_failures.append("SOURCE_AUDIO_PERFORMANCE_QC_EVIDENCE_MISSING")
                    else:
                        try:
                            if source_audio_performance is not None and str(
                                source_audio_evidence.get("performance_line_contract_sha256") or ""
                            ).lower() != str(
                                source_audio_performance["performance_line_contract_sha256"]
                            ):
                                raise AudioBackendUnavailable(
                                    "source audio performance QC is not bound to the approved performance line contract"
                                )
                            source_audio_performance_qc = validate_source_audio_performance_qc(
                                remux_receipt=remux_receipt,
                                evidence=source_audio_evidence,
                                final_output_sha256=final_output_sha256,
                            )
                            source_audio_performance_qc["status"] = "passed"
                        except (AudioBackendUnavailable, TypeError, ValueError) as exc:
                            source_audio_performance_qc = {
                                "status": "failed",
                                "error": str(exc),
                                "final_output_sha256": final_output_sha256,
                            }
                            hard_failures.append("SOURCE_AUDIO_PERFORMANCE_QC_FAILED")

            if active_profile:
                weighted_extension, weighted_error = self._build_weighted_extension(
                    context,
                    route_ok=route_ok,
                    ui_ok=ui_ok,
                    technical_failures=list(hard_failures),
                    final_output_sha256=final_output_sha256,
                    current_run_source_sha256s=current_run_source_sha256s,
                    weighted_input=weighted_input,
                    expected_evaluator_identity=evaluator_identity,
                    require_evaluator_receipt=require_receipt,
                ) if weighted_error is None else (None, weighted_error)
                if weighted_error:
                    hard_failures.append(weighted_error)
                elif weighted_extension is not None and not weighted_extension.get("accepted"):
                    hard_failures.append("HIGH_FIDELITY_QC_EXTENSION_REJECTED")
            report = {
                "schema_version": "high-fidelity-qc/v1",
                "source_kind": kind,
                "passed": not hard_failures,
                "hard_failures": hard_failures,
                "metrics": {
                    "duration_us": probe["duration_us"],
                    "width": probe["width"],
                    "height": probe["height"],
                    "fps": probe["fps"],
                    "has_audio": bool(probe["has_audio"]),
                    "audio_required": audio_required,
                    "audio_video_duration_delta_us": abs(int(probe.get("video_duration_us") or probe["duration_us"]) - int(probe.get("audio_duration_us") or 0)) if probe.get("has_audio") else 0,
                    "audio_video_start_delta_us": start_delta_us,
                    "audio_quality": audio_quality,
                    "final_audio_qc": final_audio_qc,
                    "source_audio_performance_qc": source_audio_performance_qc,
                    "black_scan": (
                        "ffmpeg-blackdetect-one-frame-boundary-aware"
                        if timeline_manifest is not None
                        else "ffmpeg-blackdetect-one-frame"
                    ),
                    "black_intervals": [
                        {"start": round(start, 6), "end": round(end, 6)}
                        for start, end in black_intervals
                    ],
                    "freeze_scan": "ffmpeg-freezedetect-boundary-aware" if timeline_manifest is not None else "ffmpeg-freezedetect",
                    "freeze_intervals": [
                        {"start": round(start, 6), "end": round(end, 6)}
                        for start, end in freeze_intervals
                    ],
                },
                "checks": {
                    "route_timeline_coverage": route_ok,
                    "ui_ocr": ui_ok,
                    "overlay_render_receipts": overlay_receipts_ok,
                    "no_black_splice_frames": "BLACK_FRAME_DETECTED" not in hard_failures,
                    "no_freeze_splice_frames": not any(
                        str(item).endswith("FREEZE_DETECTED")
                        or str(item) == "FREEZE_FRAME_DETECTED"
                        for item in hard_failures
                    ),
                    "a_v_sync": "AUDIO_VIDEO_DURATION_DRIFT" not in hard_failures,
                    "a_v_start_alignment": "AUDIO_VIDEO_START_OFFSET" not in hard_failures,
                    "audio_stream_present": not audio_required or bool(probe.get("has_audio")),
                    "audio_loudness_in_range": audio_quality.get("loudness_in_range") is True
                    if audio_quality.get("status") == "measured"
                    else audio_quality.get("status") == "not_requested"
                    or (not probe.get("has_audio") and not audio_required),
                    "audio_true_peak_safe": audio_quality.get("true_peak_safe") is True
                    if audio_quality.get("status") == "measured"
                    else audio_quality.get("status") == "not_requested"
                    or (not probe.get("has_audio") and not audio_required),
                    "audio_boundary_clicks_absent": audio_quality.get("boundary_clicks_absent") is True
                    if audio_quality.get("status") == "measured"
                    else audio_quality.get("status") == "not_requested"
                    or (not probe.get("has_audio") and not audio_required),
                    "final_audio_delivery": final_audio_qc.get("status")
                    in {"not_requested", "passed"},
                    "source_audio_performance": source_audio_performance_qc.get("status")
                    in {"not_requested", "passed"},
                },
                "timeline_manifest_source": timeline_manifest_source,
            }
            if weighted_extension is not None:
                report["high_fidelity_qc_extension"] = weighted_extension
            report_sha = _sha256_bytes(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            qc_artifact = None
            weighted_artifact = None
            published_artifacts: list[Mapping[str, Any]] = []
            publisher = getattr(context, "publish_artifact", None)
            # The full technical/evidence-bearing report is always the
            # canonical ``qc_report`` delivery artifact. Active profiles also
            # publish the weighted extension under its own immutable kind;
            # never substitute one kind for the other at the final transition.
            publish_weighted = active_profile and weighted_extension is not None
            if callable(publisher):
                profile = getattr(context, "profile_snapshot", None)
                profile_digest = str(profile.get("snapshot_sha256") or profile.get("config_digest") or "") if isinstance(profile, Mapping) else ""
                if len(profile_digest) != 64:
                    profile_digest = _sha256_bytes(json.dumps(dict(profile or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                qc_artifact = publisher(
                    kind="qc_report",
                    stream=io.BytesIO(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
                    content_type="application/json",
                    expected_sha256=report_sha,
                    metadata={
                        "producer_stage": "run_qc",
                        "parent_digests": {"assembled_video": _sha256_bytes(path.read_bytes())},
                        "profile_digest": profile_digest,
                        "passed": bool(report["passed"]),
                        "weighted_report_sha256": (
                            _sha256_bytes(
                                json.dumps(weighted_extension, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                            )
                            if publish_weighted
                            else None
                        ),
                    },
                )
                published_artifacts.append(qc_artifact)
                if publish_weighted:
                    encoded_extension = json.dumps(weighted_extension, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    extension_sha = _sha256_bytes(encoded_extension)
                    weighted_artifact = publisher(
                        kind="high_fidelity_qc_extension",
                        stream=io.BytesIO(encoded_extension),
                        content_type="application/json",
                        expected_sha256=extension_sha,
                        metadata={
                            "producer_stage": "run_qc",
                            "parent_digests": {"assembled_video": _sha256_bytes(path.read_bytes())},
                            "profile_digest": profile_digest,
                            "weighted_report_sha256": extension_sha,
                        },
                    )
                    published_artifacts.append(weighted_artifact)
            elif self.production:
                raise CapabilityUnavailable("QC requires context.publish_artifact for its immutable report")
            result = {
                "status": "ready" if report["passed"] else "blocked",
                "passed": report["passed"],
                "qc_report": report,
                "qc_report_sha256": report_sha,
                "qc_artifact": qc_artifact,
                "weighted_qc_artifact": weighted_artifact,
                "published_artifacts": list(published_artifacts),
            }
            if weighted_extension is not None:
                result["high_fidelity_qc_extension"] = weighted_extension
                result["high_fidelity_qc_extension_sha256"] = _sha256_bytes(
                    json.dumps(weighted_extension, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                )
            if self.production and isinstance(weighted_input, Mapping):
                # Preserve the exact independent evaluator response so the
                # outer CapabilityStagePort can recompute the receipt digest
                # instead of trusting a custom QC adapter's status envelope.
                result["qc_evaluator_response"] = dict(weighted_input)
            return result


__all__ = [
    "CapabilityUnavailable",
    "FfmpegDynamicsAnalyzer",
    "WhisperAsrTranscriber",
    "BundledAppStoreEvidenceParser",
    "DeterministicUiRenderer",
    "FfmpegCompositor",
    "FfmpegQcEngine",
]
