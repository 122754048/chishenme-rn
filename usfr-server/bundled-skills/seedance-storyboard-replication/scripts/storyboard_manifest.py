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


_PAIR_CONTINUITY_FIELDS = (
    "character_identity_lock",
    "wardrobe_lock",
    "product_interaction_lock",
    "segment_01_final_state",
    "segment_02_opening_state",
)
_PAIR_QA_FIELDS = {
    "character_identity_lock",
    "wardrobe_lock",
    "product_interaction_lock",
    "screen_direction",
}


def _non_empty_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field} must be a non-empty object")
    return dict(value)


def _normalise_segment_board(item: Mapping[str, Any], *, expected_segment_id: str | None = None) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise ValueError("segment board must be an object")
    segment_id = item.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id:
        raise ValueError("segment_id is required")
    if expected_segment_id is not None and segment_id != expected_segment_id:
        raise ValueError("segment boards are reordered")
    object_key = item.get("object_key")
    if not isinstance(object_key, str) or not object_key:
        raise ValueError(f"segment {segment_id} object_key is required")
    width = item.get("width")
    height = item.get("height")
    if not isinstance(width, int) or width < 1 or not isinstance(height, int) or height < 1:
        raise ValueError(f"segment {segment_id} dimensions are invalid")
    result = {
        "segment_id": segment_id,
        "object_key": object_key,
        "sha256": _sha(item.get("sha256"), f"segment {segment_id} sha256"),
        "width": width,
        "height": height,
    }
    if "previous_board_sha256" in item:
        result["previous_board_sha256"] = _sha(
            item.get("previous_board_sha256"),
            f"segment {segment_id} previous_board_sha256",
        )
    return result


def _normalise_pair_continuity(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema_version") != "storyboard-continuity/v1":
        raise ValueError("continuity_manifest schema is invalid")
    result = {"schema_version": "storyboard-continuity/v1"}
    for field in _PAIR_CONTINUITY_FIELDS:
        result[field] = _non_empty_mapping(value.get(field), f"continuity_manifest.{field}")
    return result


def _normalise_pair_qa(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("status") != "passed":
        raise ValueError("continuity_qa must have status=passed")
    fields = value.get("checked_fields")
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes, bytearray)):
        raise ValueError("continuity_qa.checked_fields must be an array")
    checked = [str(item) for item in fields if isinstance(item, str) and item]
    if len(checked) != len(fields) or not _PAIR_QA_FIELDS.issubset(set(checked)):
        raise ValueError("continuity_qa.checked_fields is incomplete")
    return {"status": "passed", "checked_fields": checked}


def _pair_core(manifest: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    result.pop("manifest_sha256", None)
    return result


def build_paired_storyboard_manifest(
    *,
    revision_number: int,
    approved_script_sha256: str,
    segment_boards: Sequence[Mapping[str, Any]],
    continuity_manifest: Mapping[str, Any],
    continuity_qa: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze two dependent segment boards behind one storyboard review.

    Segment two is not allowed to be an independently generated board.  Its
    immutable board descriptor must prove that the exact segment-one board was
    supplied as its continuity reference before the pair can reach the single
    existing storyboard approval gate.
    """

    if not isinstance(revision_number, int) or revision_number < 1:
        raise ValueError("revision_number must be >= 1")
    if not isinstance(segment_boards, Sequence) or isinstance(segment_boards, (str, bytes, bytearray)):
        raise ValueError("segment_boards must be an array")
    if len(segment_boards) != 2:
        raise ValueError("paired storyboard manifests require exactly two segment boards")
    first = _normalise_segment_board(segment_boards[0])
    second = _normalise_segment_board(segment_boards[1])
    if first["segment_id"] == second["segment_id"]:
        raise ValueError("paired storyboard segments must be unique")
    if second.get("previous_board_sha256") != first["sha256"]:
        raise ValueError("second segment previous_board_sha256 must bind the first board")
    manifest: dict[str, Any] = {
        "kind": "storyboard",
        "schema_version": "storyboard-pair-manifest/v1",
        "revision": revision_number,
        "approved_script_sha256": _sha(approved_script_sha256, "approved_script_sha256"),
        "segments": [first, second],
        "continuity_manifest": _normalise_pair_continuity(continuity_manifest),
        "continuity_qa": _normalise_pair_qa(continuity_qa),
        "review": {
            "approval_scope": "all_segments_together",
            "generation_policy": "pair_generate_before_review",
            "user_approval_count": 1,
        },
    }
    manifest["manifest_sha256"] = _digest(_pair_core(manifest))
    return manifest


def validate_paired_storyboard_manifest(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping) or manifest.get("kind") != "storyboard":
        raise ValueError("invalid paired storyboard manifest")
    if manifest.get("schema_version") != "storyboard-pair-manifest/v1":
        raise ValueError("paired storyboard manifest schema is stale")
    revision = manifest.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ValueError("paired storyboard revision is invalid")
    _sha(manifest.get("approved_script_sha256"), "approved_script_sha256")
    segments = manifest.get("segments")
    if not isinstance(segments, list) or len(segments) != 2:
        raise ValueError("paired storyboard manifest requires two segments")
    first = _normalise_segment_board(segments[0])
    second = _normalise_segment_board(segments[1])
    if first["segment_id"] == second["segment_id"]:
        raise ValueError("paired storyboard segments must be unique")
    if second.get("previous_board_sha256") != first["sha256"]:
        raise ValueError("second segment previous_board_sha256 must bind the first board")
    _normalise_pair_continuity(manifest.get("continuity_manifest"))
    _normalise_pair_qa(manifest.get("continuity_qa"))
    review = manifest.get("review")
    expected_review = {
        "approval_scope": "all_segments_together",
        "generation_policy": "pair_generate_before_review",
        "user_approval_count": 1,
    }
    if review != expected_review:
        raise ValueError("paired storyboard review policy is invalid")
    if manifest.get("manifest_sha256") != _digest(_pair_core(manifest)):
        raise ValueError("paired storyboard manifest digest mismatch")


def select_paired_storyboard_regeneration(
    *,
    ordered_segment_ids: Sequence[str],
    failed_segment_ids: Sequence[str],
) -> list[str]:
    """Return failed boards plus only dependent downstream boards.

    A correction to segment one invalidates segment two's incoming-state
    reference.  A correction confined to segment two does not regenerate the
    already-accepted first board.
    """

    ordered = list(ordered_segment_ids)
    failed = list(failed_segment_ids)
    if len(ordered) != 2 or any(not isinstance(item, str) or not item for item in ordered):
        raise ValueError("paired storyboard regeneration requires two ordered segment IDs")
    if len(set(ordered)) != len(ordered) or any(item not in ordered for item in failed):
        raise ValueError("failed_segment_ids are invalid")
    if not failed:
        return []
    earliest = min(ordered.index(item) for item in failed)
    return ordered[earliest:]


def render_overview_grid(manifest: Mapping[str, Any], output_path: Path) -> Path:
    """Render a review-only overview; per-Cut refs remain authoritative."""
    validate_storyboard_manifest(manifest)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # A deterministic valid PNG placeholder keeps rendering dependency-free.
    png_1x1 = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc000000301010018dd8db40000000049454e44ae426082")
    output_path.write_bytes(png_1x1)
    return output_path


__all__ = [
    "build_paired_storyboard_manifest",
    "build_storyboard_manifest",
    "render_overview_grid",
    "select_paired_storyboard_regeneration",
    "validate_paired_storyboard_manifest",
    "validate_storyboard_manifest",
]
