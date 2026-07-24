"""Layer-level hybrid compositor contract and backend policy.

The default production adapter remains FFmpeg.  This module validates the
immutable region manifest before the existing timeline splice consumes it;
actual rendering can be supplied by a server adapter without making a local
skill path or workstation file authoritative.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ROUTES = {"KEEP", "REPLACE", "COMPOSITE", "REMOVE", "REINTERPRET", "OPAQUE_SPLICE"}
_REMOTION_UI_MOTION_WHITELIST = frozenset(
    {"perspective", "parallax", "translate", "scale"}
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    copy = deepcopy(dict(value))
    copy.pop("manifest_sha256", None)
    return hashlib.sha256(_canonical(copy)).hexdigest()


def choose_backend(requirements: Mapping[str, Any], capabilities: Mapping[str, Any]) -> str:
    """Choose the fastest deterministic backend that passed local benchmarks."""
    def activated(name: str, domain: str) -> bool:
        record = capabilities.get(name)
        return (
            isinstance(record, Mapping)
            and record.get("status") == "enabled"
            and record.get("domain") == domain
            and isinstance(record.get("activation_report_sha256"), str)
            and _HEX64.fullmatch(record["activation_report_sha256"]) is not None
        )

    if _remotion_ui_eligible(requirements, capabilities):
        return "remotion_react_ui"
    if requirements.get("complex_ui") and activated(
        "hyperframes_html_ui", "complex_html_ui"
    ):
        return "hyperframes_html_ui"
    return "ffmpeg"


def _remotion_ui_eligible(
    requirements: Mapping[str, Any], capabilities: Mapping[str, Any]
) -> bool:
    """Return whether this exact UI interval may use the Remotion adapter.

    ``remotion_react_ui`` is not a general video backend.  A stage must bind
    its target evidence and every frozen source/UI contract before this
    selector can choose it.  The immutable activation receipt prevents a
    merely installed adapter from being treated as production-ready.
    """

    record = capabilities.get("remotion_react_ui")
    if not (
        isinstance(record, Mapping)
        and record.get("status") == "enabled"
        and record.get("domain") == "programmable_overlays"
    ):
        return False
    activation_sha = record.get("activation_report_sha256")
    if not isinstance(activation_sha, str) or _HEX64.fullmatch(activation_sha) is None:
        return False
    if (
        requirements.get("route") != "generated_ui_demo"
        or requirements.get("deterministic_ui_rebuild_allowed") is not True
        or requirements.get("existing_renderer_equivalent") is not False
        or requirements.get("benchmark_activation_report_sha256") != activation_sha
    ):
        return False
    for field in (
        "target_ui_evidence_sha256",
        "ui_truth_card_sha256",
        "ui_render_contract_sha256",
        "source_interval_contract_sha256",
    ):
        value = requirements.get(field)
        if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
            return False
    motions = requirements.get("motion_actions")
    return (
        isinstance(motions, Sequence)
        and not isinstance(motions, (str, bytes, bytearray))
        and bool(motions)
        and all(isinstance(action, str) and action in _REMOTION_UI_MOTION_WHITELIST for action in motions)
    )


def _require_object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def build_composite_manifest(
    *,
    region_id: str,
    base_plate: Mapping[str, Any],
    layers: Sequence[Mapping[str, Any]],
    audio_layers: Sequence[Mapping[str, Any]],
    output_artifact: Mapping[str, Any],
    backend: str = "ffmpeg",
) -> dict[str, Any]:
    manifest = {
        "schema_version": "hybrid-compositor/v1",
        "region_id": region_id,
        "backend": backend,
        "base_plate": deepcopy(dict(base_plate)),
        "layers": [deepcopy(dict(layer)) for layer in layers],
        "audio_layers": [deepcopy(dict(layer)) for layer in audio_layers],
        "output_artifact": deepcopy(dict(output_artifact)),
    }
    validate_composite_manifest(manifest, verify_digest=False)
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def validate_composite_manifest(manifest: Mapping[str, Any], *, verify_digest: bool = True) -> None:
    if not isinstance(manifest, Mapping):
        raise ValueError("composite manifest must be an object")
    if manifest.get("schema_version") != "hybrid-compositor/v1":
        raise ValueError("unsupported compositor schema")
    if not isinstance(manifest.get("region_id"), str) or not manifest["region_id"]:
        raise ValueError("region_id is required")
    if manifest.get("backend") not in {"ffmpeg", "hyperframes_html_ui", "remotion_react_ui"}:
        raise ValueError("unsupported compositor backend")
    base = _require_object(manifest.get("base_plate"), "base_plate")
    if base.get("origin") not in {"source", "generated", "opaque"} or not base.get("object_key"):
        raise ValueError("base_plate requires an origin and private object_key")
    layers = manifest.get("layers")
    if not isinstance(layers, list):
        raise ValueError("layers must be an array")
    z_orders: set[int] = set()
    for index, layer in enumerate(layers):
        layer = _require_object(layer, f"layers[{index}]")
        if not layer.get("layer_id") or layer.get("route") not in _ROUTES:
            raise ValueError(f"layers[{index}] has an invalid id or route")
        z_order = layer.get("z_order")
        if isinstance(z_order, bool) or not isinstance(z_order, int) or z_order in z_orders:
            raise ValueError("layer z_order values must be unique integers")
        z_orders.add(z_order)
        route = layer["route"]
        if route == "COMPOSITE":
            asset = _require_object(layer.get("asset"), f"layers[{index}].asset")
            if not asset.get("object_key") or not isinstance(asset.get("sha256"), str) or not _HEX64.fullmatch(asset["sha256"]):
                raise ValueError("composite layer asset must have object_key and SHA-256")
            for field in ("matte", "tracking", "occlusion"):
                value = _require_object(layer.get(field), f"layers[{index}].{field}")
                if field == "tracking":
                    invalid = not value.get("space") or not value.get("method")
                else:
                    invalid = value.get("kind") in {None, "none"}
                if invalid:
                    raise ValueError(f"composite layer requires {field} evidence")
        if route == "OPAQUE_SPLICE":
            policy = str(layer.get("opaque_policy") or "preserve_pixels")
            if policy != "preserve_pixels":
                raise ValueError("opaque media can only use preserve_pixels policy")
            if any(term in policy.lower() for term in ("ocr", "redraw", "retime", "rewrite")):
                raise ValueError("opaque media cannot be semantically rewritten")
    audio = manifest.get("audio_layers")
    if not isinstance(audio, list):
        raise ValueError("audio_layers must be an array")
    for index, event in enumerate(audio):
        event = _require_object(event, f"audio_layers[{index}]")
        if not event.get("event_id") or event.get("route") not in {"KEEP", "COMPOSITE", "REPLACE"}:
            raise ValueError("audio layer requires event_id and route")
        start = event.get("start_ms")
        end = event.get("end_ms")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError("audio layer window is invalid")
        if not event.get("object_key") and not event.get("source_ref"):
            raise ValueError("audio layer requires an authorized object/source reference")
    output = _require_object(manifest.get("output_artifact"), "output_artifact")
    if not output.get("object_key") or not isinstance(output.get("sha256"), str) or not _HEX64.fullmatch(output["sha256"]):
        raise ValueError("output_artifact requires private object_key and SHA-256")
    if verify_digest:
        recorded = manifest.get("manifest_sha256")
        if not isinstance(recorded, str) or not _HEX64.fullmatch(recorded) or recorded != _digest(manifest):
            raise ValueError("compositor manifest digest mismatch")
