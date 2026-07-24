"""Immutable, revision-scoped storyboard Cut manifests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


_HEX64 = set("0123456789abcdef")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in _HEX64 for c in value):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _normalise_cut(item: Mapping[str, Any], *, revision_number: int) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise ValueError("cut image must be an object")
    cut_id = item.get("cut_id")
    if not isinstance(cut_id, str) or not cut_id:
        raise ValueError("cut_id is required")
    sha = _sha(item.get("sha256"), f"cut {cut_id} sha256")
    object_key = item.get("object_key")
    if not isinstance(object_key, str) or not object_key:
        object_key = f"storyboards/r{revision_number}/cuts/{cut_id}.png"
    width = item.get("width", 1)
    height = item.get("height", 1)
    if not isinstance(width, int) or width < 1 or not isinstance(height, int) or height < 1:
        raise ValueError(f"cut {cut_id} dimensions are invalid")
    return {"cut_id": cut_id, "object_key": object_key, "sha256": sha, "width": width, "height": height}


def _core(manifest: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    result.pop("manifest_sha256", None)
    # The overview is a review convenience and deliberately non-authoritative.
    result.pop("overview", None)
    return result


def build_storyboard_manifest(
    *,
    revision_number: int,
    approved_script_sha256: str,
    ordered_cut_ids: Sequence[str],
    cut_images: Sequence[Mapping[str, Any]],
    previous_manifest: Mapping[str, Any] | None = None,
    requested_cut_ids: Sequence[str] | None = None,
    continuity: bool = False,
    output_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(revision_number, int) or revision_number < 1:
        raise ValueError("revision_number must be >= 1")
    script_sha = _sha(approved_script_sha256, "approved_script_sha256")
    ordered = list(ordered_cut_ids)
    if not ordered or any(not isinstance(c, str) or not c for c in ordered):
        raise ValueError("ordered_cut_ids must contain non-empty strings")
    if len(ordered) != len(set(ordered)):
        raise ValueError("duplicate Cut IDs in ordered_cut_ids")
    provided = [_normalise_cut(item, revision_number=revision_number) for item in cut_images]
    provided_ids = [item["cut_id"] for item in provided]
    if len(provided_ids) != len(set(provided_ids)):
        raise ValueError("duplicate Cut IDs in cut_images")
    unknown = set(provided_ids) - set(ordered)
    if unknown:
        raise ValueError("cut_images contains unknown Cut IDs")
    if requested_cut_ids is None and provided_ids != ordered:
        if set(provided_ids) == set(ordered):
            raise ValueError("cut_images are reordered")
        missing = [c for c in ordered if c not in provided_ids]
        raise ValueError(f"missing Cut images: {', '.join(missing)}")
    if requested_cut_ids is not None:
        requested = list(requested_cut_ids)
        if any(c not in ordered for c in requested) or len(requested) != len(set(requested)):
            raise ValueError("requested_cut_ids are invalid")
        if provided_ids != requested and provided_ids != [c for c in ordered if c in set(requested)]:
            raise ValueError("requested Cut images are reordered")
    previous_by_id: dict[str, Mapping[str, Any]] = {}
    if previous_manifest is not None:
        validate_storyboard_manifest(previous_manifest)
        previous_by_id = {item["cut_id"]: item for item in previous_manifest["cut_images"]}
    by_id = {item["cut_id"]: item for item in provided}
    regenerated = list(requested_cut_ids) if requested_cut_ids is not None else list(ordered)
    if requested_cut_ids is not None and continuity:
        expanded = set(regenerated)
        for cut_id in list(regenerated):
            index = ordered.index(cut_id)
            if index:
                expanded.add(ordered[index - 1])
            if index + 1 < len(ordered):
                expanded.add(ordered[index + 1])
        # Continuity neighbors may be reused from the previous approved manifest.
        regenerated = [c for c in ordered if c in set(requested_cut_ids)]
        for cut_id in ordered:
            if cut_id in expanded and cut_id not in by_id and cut_id in previous_by_id:
                by_id[cut_id] = dict(previous_by_id[cut_id])
    elif requested_cut_ids is not None:
        for cut_id in ordered:
            if cut_id not in by_id and cut_id in previous_by_id:
                by_id[cut_id] = dict(previous_by_id[cut_id])
    missing = [c for c in ordered if c not in by_id]
    if missing:
        raise ValueError(f"missing Cut images: {', '.join(missing)}")
    cuts = [dict(by_id[c]) for c in ordered]
    root = Path(output_root) if output_root is not None else None
    overview_key = f"storyboards/r{revision_number}/overview.png"
    if root is not None:
        overview_key = str(Path(f"storyboards/r{revision_number}/overview.png")).replace("\\", "/")
    manifest: dict[str, Any] = {
        "kind": "storyboard",
        "schema_version": "storyboard-manifest/v1",
        "revision": revision_number,
        "approved_script_sha256": script_sha,
        "cut_ids": ordered,
        "cut_images": cuts,
        "regenerated_cut_ids": regenerated,
        "overview": {"object_key": overview_key, "sha256": None, "authority": "review_only"},
    }
    manifest["manifest_sha256"] = _digest(_core(manifest))
    return manifest


def validate_storyboard_manifest(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping) or manifest.get("kind") != "storyboard":
        raise ValueError("invalid storyboard manifest")
    if manifest.get("schema_version") != "storyboard-manifest/v1":
        raise ValueError("storyboard manifest schema is stale")
    revision = manifest.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ValueError("storyboard revision is invalid")
    _sha(manifest.get("approved_script_sha256"), "approved_script_sha256")
    cut_ids = manifest.get("cut_ids")
    cuts = manifest.get("cut_images")
    if not isinstance(cut_ids, list) or len(cut_ids) != len(set(cut_ids)):
        raise ValueError("duplicate Cut IDs in manifest")
    if not isinstance(cuts, list) or [item.get("cut_id") for item in cuts] != cut_ids:
        raise ValueError("Cut order does not match approved script")
    for item in cuts:
        _normalise_cut(item, revision_number=revision)
    if manifest.get("manifest_sha256") != _digest(_core(manifest)):
        raise ValueError("storyboard manifest digest mismatch")
    overview = manifest.get("overview")
    if isinstance(overview, Mapping) and overview.get("authority") not in {None, "review_only"}:
        raise ValueError("overview is not authoritative")


def render_overview_grid(manifest: Mapping[str, Any], output_path: Path) -> Path:
    """Render a review-only overview; per-Cut refs remain authoritative."""
    validate_storyboard_manifest(manifest)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # A deterministic valid PNG placeholder keeps rendering dependency-free.
    png_1x1 = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc000000301010018dd8db40000000049454e44ae426082")
    output_path.write_bytes(png_1x1)
    return output_path


__all__ = ["build_storyboard_manifest", "validate_storyboard_manifest", "render_overview_grid"]
