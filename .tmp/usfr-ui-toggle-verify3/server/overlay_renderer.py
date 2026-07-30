"""Deterministic semantic-overlay renderer for the source-fidelity compositor.

The source-overlay skill freezes geometry; this module is the executable bridge
that paints approved target text/assets into the same screen-space intervals.
It intentionally accepts only an immutable ``overlay_render_mapping`` payload
and returns output-bound receipts.  It does not inspect opaque UI or tail-card
media and it never asks a video model to draw readable text.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OverlayRenderError(RuntimeError):
    """The deterministic overlay payload cannot be rendered safely."""


_MOJIBAKE_MARKERS = ("\ufffd", "Ã", "Â", "â€", "绔嬪嵆", "涓嬭浇")


def _normalized_text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFC", str(value or "")).split())


def validate_readable_overlay_evidence(
    receipt: Mapping[str, Any],
    *,
    frame_bytes: bytes,
    evidence: Mapping[str, Any],
    final_output_sha256: str,
) -> dict[str, Any]:
    final_sha = _require_sha(final_output_sha256, "final_output_sha256")
    declared_final = str(receipt.get("final_output_sha256") or "").lower()
    if declared_final and declared_final != final_sha:
        raise OverlayRenderError("readable overlay receipt binds a stale final output")
    frame_sha = hashlib.sha256(frame_bytes).hexdigest()
    if str(evidence.get("input_sha256") or "").lower() != frame_sha:
        raise OverlayRenderError("OCR evidence is not bound to the decoded final frame")
    expected_text = _normalized_text(receipt.get("expected_text"))
    if not expected_text or any(marker in expected_text for marker in _MOJIBAKE_MARKERS):
        raise OverlayRenderError("expected readable overlay text is invalid")
    records = evidence.get("records")
    if not isinstance(records, list):
        raise OverlayRenderError("OCR evidence records must be an array")
    matched: Mapping[str, Any] | None = None
    for item in records:
        if not isinstance(item, Mapping):
            continue
        observed = _normalized_text(item.get("text"))
        if any(marker in observed for marker in _MOJIBAKE_MARKERS):
            continue
        if observed == expected_text:
            matched = item
            break
    if matched is None:
        raise OverlayRenderError("readable overlay OCR text does not match target text")
    expected_language = receipt.get("output_language")
    if expected_language is not None and matched.get("language") != expected_language:
        raise OverlayRenderError("readable overlay OCR language does not match output_language")
    expected_bbox = _rect(receipt.get("expected_bbox"), "expected_bbox")
    observed_bbox = _rect(matched.get("bbox"), "OCR bbox")
    if any(abs(left - right) > 1e-6 for left, right in zip(expected_bbox, observed_bbox)):
        raise OverlayRenderError("readable overlay OCR bounding box does not match layout")
    try:
        expected_z = int(receipt.get("z_index"))
        observed_z = int(matched.get("z_index"))
    except (TypeError, ValueError) as exc:
        raise OverlayRenderError("readable overlay z-order evidence is invalid") from exc
    if expected_z != observed_z:
        raise OverlayRenderError("readable overlay z-order does not match source layout")
    result = dict(receipt)
    result.update(
        {
            "final_output_sha256": final_sha,
            "ocr_match_percent": 100,
            "layout_match_percent": 100,
            "frame_digests": [frame_sha],
            "ocr_evidence_sha256": _sha256(evidence),
        }
    )
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha(value: Any, field: str) -> str:
    digest = str(value or "").lower()
    if _SHA256.fullmatch(digest) is None:
        raise OverlayRenderError(f"{field} must be a lowercase SHA-256")
    return digest


def _rect(value: Any, field: str) -> tuple[float, float, float, float]:
    if isinstance(value, Mapping):
        value = [value.get("x"), value.get("y"), value.get("width"), value.get("height")]
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise OverlayRenderError(f"{field} must contain x,y,width,height")
    try:
        x, y, width, height = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise OverlayRenderError(f"{field} must be numeric") from exc
    if not all(math.isfinite(item) for item in (x, y, width, height)):
        raise OverlayRenderError(f"{field} contains non-finite values")
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise OverlayRenderError(f"{field} must remain inside normalized frame bounds")
    return x, y, width, height


def _overlay_trajectory(
    source_overlay: Mapping[str, Any],
    *,
    start_us: int,
    end_us: int,
) -> list[tuple[int, float, float, float, float, float, float]]:
    """Return ordered normalized keyframes clipped to the region window."""

    raw = source_overlay.get("keyframes")
    points: list[tuple[int, float, float, float, float, float, float]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            try:
                time_us = int(item.get("time_us"))
                rect = _rect(item.get("bbox"), "source_overlay.keyframes.bbox")
                rotation = float(item.get("rotation_deg", 0) or 0)
                opacity = float(item.get("opacity", 1) if item.get("opacity") is not None else 1)
            except (TypeError, ValueError) as exc:
                raise OverlayRenderError("source overlay keyframe values are invalid") from exc
            if not start_us <= time_us <= end_us:
                continue
            points.append((time_us, *rect, rotation, opacity))
    if not points:
        start = _rect(source_overlay.get("start_rect"), "source_overlay.start_rect")
        finish = _rect(source_overlay.get("end_rect") or start, "source_overlay.end_rect")
        points = [
            (start_us, *start, float(source_overlay.get("start_rotation_deg", 0) or 0), float(source_overlay.get("start_opacity", 1) or 1)),
            (end_us, *finish, float(source_overlay.get("end_rotation_deg", 0) or 0), float(source_overlay.get("end_opacity", 1) or 1)),
        ]
    points.sort(key=lambda item: item[0])
    if points[0][0] > start_us:
        points.insert(0, (start_us, *points[0][1:]))
    if points[-1][0] < end_us:
        points.append((end_us, *points[-1][1:]))
    deduped: list[tuple[int, float, float, float, float, float, float]] = []
    for point in points:
        if deduped and point[0] == deduped[-1][0]:
            deduped[-1] = point
        else:
            deduped.append(point)
    return deduped


def _piecewise_expr(points: list[tuple[int, float, float, float, float, float, float]], component: int) -> str:
    """Build a FFmpeg linear piecewise expression for one keyframe component."""

    if not points:
        raise OverlayRenderError("overlay trajectory requires at least one keyframe")
    expression = f"{points[-1][component + 1]:.9f}"
    for index in range(len(points) - 2, -1, -1):
        t0, v0 = points[index][0], points[index][component + 1]
        t1, v1 = points[index + 1][0], points[index + 1][component + 1]
        if t1 <= t0:
            continue
        seconds0 = t0 / 1_000_000
        seconds1 = t1 / 1_000_000
        interpolation = f"({v0:.9f}+({v1 - v0:.9f})*(t-{seconds0:.9f})/{seconds1 - seconds0:.9f})"
        expression = f"if(lt(t,{seconds1:.9f}),{interpolation},{expression})"
    return expression


def _escape_filter_path(path: Path) -> str:
    # FFmpeg filter syntax treats ':' and '\\' as separators.  Forward slashes
    # plus an escaped drive-colon work on Windows and POSIX workers alike.
    value = path.resolve().as_posix().replace("'", "\\'")
    if len(value) >= 2 and value[1] == ":":
        value = value[0] + r"\:" + value[2:]
    return value


def _escape_drawtext_value(value: Any) -> str:
    text = str(value or "")
    if "\ufffd" in text or any(ord(char) < 32 and char not in {"\n", "\t"} for char in text):
        raise OverlayRenderError("overlay text contains replacement/control characters")
    # textfile is used for the actual payload; this fallback is only for color
    # and other scalar filter options.
    return text.replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_overlay_index(contract: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    cuts = contract.get("cuts")
    if not isinstance(cuts, list):
        raise OverlayRenderError("source_overlay_contract.cuts must be an array")
    for cut in cuts:
        if not isinstance(cut, Mapping):
            raise OverlayRenderError("source overlay Cut must be an object")
        overlays = cut.get("source_overlays")
        if not isinstance(overlays, list):
            raise OverlayRenderError("source overlay Cut source_overlays must be an array")
        for overlay in overlays:
            if not isinstance(overlay, Mapping):
                raise OverlayRenderError("source overlay entry must be an object")
            overlay_id = str(overlay.get("overlay_id") or "").strip()
            if not overlay_id:
                raise OverlayRenderError("source overlay IDs must be non-empty")
            if overlay_id not in result:
                result[overlay_id] = dict(overlay)
            else:
                merged = result[overlay_id]
                merged["start_us"] = min(int(merged.get("start_us") or 0), int(overlay.get("start_us") or 0))
                merged["end_us"] = max(int(merged.get("end_us") or 0), int(overlay.get("end_us") or 0))
                merged["end_rect"] = overlay.get("end_rect") or merged.get("end_rect")
                merged["end_rotation_deg"] = overlay.get("end_rotation_deg", merged.get("end_rotation_deg"))
                merged["end_opacity"] = overlay.get("end_opacity", merged.get("end_opacity"))
                old_keyframes = merged.get("keyframes") if isinstance(merged.get("keyframes"), list) else []
                new_keyframes = overlay.get("keyframes") if isinstance(overlay.get("keyframes"), list) else []
                merged["keyframes"] = sorted(
                    [*old_keyframes, *new_keyframes],
                    key=lambda item: int(item.get("time_us", 0)) if isinstance(item, Mapping) else 0,
                )
    return result


def _mapping_rows(mapping: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    rows = mapping.get("regions")
    if not isinstance(rows, list):
        raise OverlayRenderError("overlay_render_mapping.regions must be an array")
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise OverlayRenderError("overlay mapping region must be an object")
        region_id = str(row.get("region_id") or "").strip()
        overlays = row.get("overlays")
        if not region_id or not isinstance(overlays, list):
            raise OverlayRenderError("overlay mapping region requires region_id and overlays")
        for item in overlays:
            if not isinstance(item, Mapping):
                raise OverlayRenderError("overlay mapping entry must be an object")
            overlay_id = str(item.get("overlay_id") or "").strip()
            key = (region_id, overlay_id)
            if not overlay_id or key in result:
                raise OverlayRenderError("overlay mapping IDs must be unique and non-empty")
            result[key] = item
    return result


def _region_overlay_geometry(
    source_overlay: Mapping[str, Any],
    *,
    start_us: int,
    end_us: int,
) -> tuple[float, float, float, float]:
    start = source_overlay.get("start_rect")
    end = source_overlay.get("end_rect") or start
    if start is None:
        keyframes = source_overlay.get("keyframes")
        if isinstance(keyframes, list) and keyframes and isinstance(keyframes[0], Mapping):
            start = keyframes[0].get("bbox")
            end = keyframes[-1].get("bbox") or start
    # The deterministic FFmpeg backend supports a static box and records the
    # full source window in the receipt.  A moving overlay must be supplied to
    # a renderer with trajectory support instead of silently freezing it.
    start_rect = _rect(start, "source_overlay.start_rect")
    end_rect = _rect(end, "source_overlay.end_rect")
    if start_rect != end_rect:
        raise OverlayRenderError(
            "OVERLAY_RENDER_TRAJECTORY_CAPABILITY_REQUIRED: moving semantic overlays require a trajectory renderer"
        )
    source_start = int(source_overlay.get("start_us") or start_us)
    source_end = int(source_overlay.get("end_us") or end_us)
    if source_start < start_us or source_end > end_us or source_end <= source_start:
        raise OverlayRenderError("source overlay window is outside its timeline region")
    return start_rect


class DeterministicOverlayRenderer:
    """Render approved deterministic text/asset overlays with FFmpeg.

    The class is deployment-safe when the worker supplies an immutable bundle
    and an FFmpeg binary.  It has no dependency on client paths or a workstation
    skill installation; payload files are staged only in a lease-owned temp
    directory and receipts contain hashes, never those paths.
    """

    evidence_bound = True
    capability_kind = "overlay_renderer"

    def __init__(
        self,
        *,
        ffmpeg_bin: str = "ffmpeg",
        version: str = "1.0.0",
        sha256: str | None = None,
        production: bool = False,
        ocr_backend: Any | None = None,
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.version = version
        self.production = bool(production)
        self.ocr_backend = ocr_backend
        self.sha256 = sha256 or hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        _require_sha(self.sha256, "overlay renderer sha256")

    def capability_identity(self) -> Mapping[str, Any]:
        return {
            "implementation": "server.overlay_renderer:DeterministicOverlayRenderer",
            "version": self.version,
            "sha256": self.sha256,
            "evidence_binding": "usfr-overlay-render/v1",
        }

    def _materialize_asset(
        self,
        *,
        payload: Mapping[str, Any],
        context: Any,
        temp_dir: Path,
        index: int,
    ) -> Path:
        """Resolve one immutable asset into the lease-local render directory."""

        asset_sha = _require_sha(payload.get("asset_sha256"), "asset_sha256")
        asset_path = payload.get("asset_path")
        if asset_path is not None:
            if self.production:
                raise OverlayRenderError("production deterministic assets cannot use local asset_path")
            source = Path(str(asset_path)).resolve()
            if not source.is_file() or source.stat().st_size <= 0:
                raise OverlayRenderError("deterministic asset_path is missing or empty")
            if _sha256_file(source) != asset_sha:
                raise OverlayRenderError("deterministic asset_path bytes do not match asset_sha256")
            destination = temp_dir / f"overlay_asset_{index:04d}{source.suffix or '.bin'}"
            shutil.copyfile(source, destination)
            return destination

        kind = str(payload.get("artifact_kind") or "").strip()
        materialize = getattr(context, "materialize_artifact", None)
        if not kind or not callable(materialize):
            raise OverlayRenderError(
                "deterministic_asset requires an immutable artifact_kind and materialize_artifact context"
            )
        kwargs: dict[str, Any] = {"sha256": asset_sha}
        if payload.get("artifact_id") is not None:
            kwargs["artifact_id"] = str(payload["artifact_id"])
        try:
            with materialize(kind, **kwargs) as media:
                source = Path(media.path)
                if not source.is_file() or source.stat().st_size <= 0:
                    raise OverlayRenderError("materialized deterministic asset is missing or empty")
                if _sha256_file(source) != asset_sha:
                    raise OverlayRenderError("materialized deterministic asset bytes do not match asset_sha256")
                destination = temp_dir / f"overlay_asset_{index:04d}{source.suffix or '.bin'}"
                shutil.copyfile(source, destination)
                return destination
        except OverlayRenderError:
            raise
        except Exception as exc:
            raise OverlayRenderError("immutable deterministic asset materialization failed") from exc

    def _materialize_font(
        self,
        *,
        payload: Mapping[str, Any],
        context: Any,
        temp_dir: Path,
        index: int,
    ) -> Path:
        font_sha = _require_sha(payload.get("font_sha256"), "font_sha256")
        font_path = payload.get("font_path")
        if font_path is not None:
            if self.production:
                raise OverlayRenderError(
                    "production deterministic fonts cannot use local font_path"
                )
            source = Path(str(font_path)).resolve()
            if not source.is_file() or _sha256_file(source) != font_sha:
                raise OverlayRenderError(
                    "deterministic font_path bytes do not match font_sha256"
                )
            destination = temp_dir / f"overlay_font_{index:04d}{source.suffix or '.ttf'}"
            shutil.copyfile(source, destination)
            return destination
        kind = str(payload.get("font_artifact_kind") or "").strip()
        materialize = getattr(context, "materialize_artifact", None)
        if not kind or not callable(materialize):
            raise OverlayRenderError(
                "deterministic readable text requires an immutable font artifact"
            )
        kwargs: dict[str, Any] = {"sha256": font_sha}
        if payload.get("font_artifact_id") is not None:
            kwargs["artifact_id"] = str(payload["font_artifact_id"])
        try:
            with materialize(kind, **kwargs) as media:
                source = Path(media.path)
                if not source.is_file() or _sha256_file(source) != font_sha:
                    raise OverlayRenderError(
                        "materialized font bytes do not match font_sha256"
                    )
                destination = temp_dir / f"overlay_font_{index:04d}{source.suffix or '.ttf'}"
                shutil.copyfile(source, destination)
                return destination
        except OverlayRenderError:
            raise
        except Exception as exc:
            raise OverlayRenderError(
                "immutable deterministic font materialization failed"
            ) from exc

    def _build_filters(
        self,
        *,
        source_contract: Mapping[str, Any],
        mapping: Mapping[str, Any],
        regions: list[Mapping[str, Any]],
        temp_dir: Path,
        context: Any | None = None,
    ) -> tuple[str, list[dict[str, Any]], list[Path]]:
        source_index = _source_overlay_index(source_contract)
        rows = _mapping_rows(mapping)
        filters: list[str] = []
        receipts: list[dict[str, Any]] = []
        asset_paths: list[Path] = []
        seen: set[tuple[str, str]] = set()
        current_label = "[0:v]"
        filter_index = 0
        for region in regions:
            region_id = str(region.get("region_id") or "").strip()
            if not region_id:
                continue
            try:
                start_us = int(region.get("source_start_us") or 0)
                end_us = int(region.get("source_end_us") or 0)
            except (TypeError, ValueError) as exc:
                raise OverlayRenderError("timeline region time bounds must be integers") from exc
            region_rows = sorted(
                (
                    (key, entry)
                    for key, entry in rows.items()
                    if key[0] == region_id
                ),
                key=lambda item: int(
                    source_index.get(item[0][1], {}).get("z_index") or 0
                ),
            )
            for (mapped_region_id, overlay_id), entry in region_rows:
                source_overlay = source_index.get(overlay_id)
                if source_overlay is None:
                    raise OverlayRenderError(f"overlay mapping references unknown overlay {overlay_id}")
                key = (region_id, overlay_id)
                seen.add(key)
                if entry.get("validated") is not True:
                    raise OverlayRenderError(f"overlay mapping {region_id}/{overlay_id} is not validated")
                mode = str(entry.get("render_mode") or "").strip().lower()
                payload = entry.get("payload")
                if not isinstance(payload, Mapping):
                    raise OverlayRenderError(f"overlay mapping {region_id}/{overlay_id} requires payload")
                payload_sha = _require_sha(entry.get("payload_sha256"), f"{region_id}/{overlay_id}.payload_sha256")
                if _sha256(payload) != payload_sha:
                    raise OverlayRenderError(f"overlay mapping {region_id}/{overlay_id} payload SHA does not match payload bytes")
                trajectory = _overlay_trajectory(
                    source_overlay,
                    start_us=start_us,
                    end_us=end_us,
                )
                x, y, width, height = trajectory[0][1:5]
                x_trajectory = _piecewise_expr(trajectory, 0)
                y_trajectory = _piecewise_expr(trajectory, 1)
                width_trajectory = _piecewise_expr(trajectory, 2)
                height_trajectory = _piecewise_expr(trajectory, 3)
                rotation_trajectory = _piecewise_expr(trajectory, 4)
                opacity_trajectory = _piecewise_expr(trajectory, 5)
                enable = f"between(t,{start_us / 1_000_000:.6f},{end_us / 1_000_000:.6f})"
                if mode == "deterministic_text":
                    if any(abs(point[5] - trajectory[0][5]) > 1e-9 for point in trajectory):
                        raise OverlayRenderError(
                            "OVERLAY_RENDER_TRAJECTORY_CAPABILITY_REQUIRED: rotating text overlays require a dedicated text-rotation renderer"
                        )
                    text = payload.get("text")
                    if not isinstance(text, str) or not text.strip():
                        raise OverlayRenderError(f"overlay mapping {region_id}/{overlay_id} text payload is empty")
                    text_path = temp_dir / f"overlay_{len(receipts):04d}.txt"
                    text_path.write_text(text, encoding="utf-8", newline="")
                    font_option = ""
                    if payload.get("verification_required") is True and (
                        self.production
                        or payload.get("font_path") is not None
                        or payload.get("font_artifact_kind") is not None
                    ):
                        if context is None:
                            raise OverlayRenderError(
                                "deterministic readable text requires a worker context"
                            )
                        font_path = self._materialize_font(
                            payload=payload,
                            context=context,
                            temp_dir=temp_dir,
                            index=len(receipts),
                        )
                        font_option = f"fontfile='{_escape_filter_path(font_path)}':"
                    color = _escape_drawtext_value(payload.get("color") or "white")
                    try:
                        font_size = int(payload.get("font_size") or max(8, round(height * 720)))
                    except (TypeError, ValueError) as exc:
                        raise OverlayRenderError(f"overlay mapping {region_id}/{overlay_id} font_size is invalid") from exc
                    if font_size <= 0 or font_size > 4096:
                        raise OverlayRenderError(f"overlay mapping {region_id}/{overlay_id} font_size is invalid")
                    x_expr = f"(w*(({x_trajectory})+({width_trajectory})/2)-text_w/2)"
                    y_expr = f"(h*(({y_trajectory})+({height_trajectory})/2)-text_h/2)"
                    filters.append(
                        f"{current_label}drawtext="
                        f"textfile='{_escape_filter_path(text_path)}':"
                        f"{font_option}"
                        f"fontcolor={color}:fontsize={font_size}:x='{x_expr}':y='{y_expr}':"
                        f"alpha='{opacity_trajectory}':"
                        f"enable='{enable}'[ovr{filter_index}]"
                    )
                elif mode == "deterministic_asset":
                    if context is None:
                        raise OverlayRenderError("deterministic_asset requires a worker context")
                    asset_path = self._materialize_asset(
                        payload=payload,
                        context=context,
                        temp_dir=temp_dir,
                        index=len(asset_paths),
                    )
                    asset_paths.append(asset_path)
                    target_width = max(1, round(float(source_contract.get("source_width") or 0) * width))
                    target_height = max(1, round(float(source_contract.get("source_height") or 0) * height))
                    if target_width <= 1 or target_height <= 1:
                        raise OverlayRenderError("deterministic asset geometry requires source dimensions")
                    input_index = len(asset_paths)
                    fit = str(payload.get("fit") or "contain").strip().lower()
                    source_width = float(source_contract.get("source_width") or 0)
                    source_height = float(source_contract.get("source_height") or 0)
                    if fit == "fill":
                        scale = f"scale=w='{source_width:.9f}*({width_trajectory})':h='{source_height:.9f}*({height_trajectory})':eval=frame"
                    elif fit == "contain":
                        # Contain is deterministic for a static box.  A
                        # changing box uses fill so that scale remains
                        # frame-evaluable instead of freezing the motion.
                        if len(trajectory) == 2 and trajectory[0][1:5] == trajectory[-1][1:5]:
                            scale = (
                                f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black@0"
                            )
                        else:
                            scale = f"scale=w='{source_width:.9f}*({width_trajectory})':h='{source_height:.9f}*({height_trajectory})':eval=frame"
                    else:
                        raise OverlayRenderError(f"unsupported deterministic asset fit: {fit}")
                    asset_label = f"asset{filter_index}"
                    filters.append(f"[{input_index}:v]format=rgba,{scale}[{asset_label}]")
                    opacity = payload.get("opacity", 1)
                    try:
                        opacity = float(opacity)
                    except (TypeError, ValueError) as exc:
                        raise OverlayRenderError("deterministic asset opacity must be numeric") from exc
                    if not 0 <= opacity <= 1:
                        raise OverlayRenderError("deterministic asset opacity must be between 0 and 1")
                    overlay_label = f"ovr{filter_index}"
                    x_expr = f"W*({x_trajectory})"
                    y_expr = f"H*({y_trajectory})"
                    if any(abs(point[5] - trajectory[0][5]) > 1e-9 for point in trajectory):
                        filters.append(
                            f"[{asset_label}]rotate=(({rotation_trajectory})*PI/180):fillcolor=none:eval=frame[{asset_label}r]"
                        )
                        asset_label = f"{asset_label}r"
                    if opacity < 1:
                        filters.append(f"[{asset_label}]colorchannelmixer=aa={opacity:.9f}[{asset_label}a]")
                        asset_label = f"{asset_label}a"
                    filters.append(
                        f"{current_label}[{asset_label}]overlay=x='{x_expr}':y='{y_expr}':"
                        f"eof_action=pass:enable='{enable}':format=auto[{overlay_label}]"
                    )
                else:
                    raise OverlayRenderError(
                        "OVERLAY_RENDER_BACKEND_CAPABILITY_REQUIRED: supported modes are deterministic_text and deterministic_asset"
                    )
                current_label = f"[ovr{filter_index}]"
                filter_index += 1
                receipt = {
                    "region_id": region_id,
                    "overlay_id": overlay_id,
                    "source_overlay_contract_sha256": _sha256(source_contract),
                    "overlay_render_mapping_sha256": _sha256(mapping),
                    "payload_sha256": payload_sha,
                    "frame_windows": [{"start_us": start_us, "end_us": end_us}],
                    "render_mode": mode,
                }
                if mode == "deterministic_text" and payload.get("verification_required") is True:
                    receipt.update(
                        {
                            "verification_required": True,
                            "expected_text": str(payload.get("text") or ""),
                            "expected_bbox": [x, y, width, height],
                            "output_language": payload.get("output_language"),
                            "font_sha256": _require_sha(
                                payload.get("font_sha256"),
                                f"{region_id}/{overlay_id}.font_sha256",
                            ),
                            "glyph_coverage_sha256": _require_sha(
                                payload.get("glyph_coverage_sha256"),
                                f"{region_id}/{overlay_id}.glyph_coverage_sha256",
                            ),
                            "z_index": int(source_overlay.get("z_index") or 0),
                        }
                    )
                if mode == "deterministic_asset":
                    receipt["asset_sha256"] = _require_sha(payload.get("asset_sha256"), f"{region_id}/{overlay_id}.asset_sha256")
                receipts.append(receipt)
        if not receipts:
            raise OverlayRenderError("overlay mapping contains no renderable overlays")
        if set(rows) != seen:
            missing = sorted(set(rows) - seen)
            raise OverlayRenderError(f"overlay mapping regions are not present in timeline: {missing}")
        filter_graph = ";".join(filters)
        if not filter_graph:
            raise OverlayRenderError("overlay mapping produced no filter graph")
        filter_graph += f";{current_label}copy[vout]"
        return filter_graph, receipts, asset_paths

    def render(self, source_path: Path, output_path: Path, context: Any) -> Mapping[str, Any]:
        source_path = Path(source_path)
        output_path = Path(output_path)
        regions = [
            dict(item)
            for item in (getattr(context, "timeline_regions", ()) or ())
            if isinstance(item, Mapping)
        ]
        contracts = [item.get("source_overlay_contract") for item in regions if isinstance(item.get("source_overlay_contract"), Mapping)]
        mappings = [item.get("overlay_render_mapping") for item in regions if isinstance(item.get("overlay_render_mapping"), Mapping)]
        if not contracts or not mappings:
            raise OverlayRenderError("source overlay contract and render mapping are required")
        contract = dict(contracts[0])
        mapping = dict(mappings[0])
        if any(_sha256(item) != _sha256(contract) for item in contracts):
            raise OverlayRenderError("timeline carries conflicting source overlay contracts")
        if any(_sha256(item) != _sha256(mapping) for item in mappings):
            raise OverlayRenderError("timeline carries conflicting overlay render mappings")
        work_dir = Path(getattr(context, "work_dir", output_path.parent)).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="usfr-overlay-", dir=str(work_dir)) as tmp:
            temp_dir = Path(tmp)
            filter_graph, receipts, asset_paths = self._build_filters(
                source_contract=contract,
                mapping=mapping,
                regions=regions,
                temp_dir=temp_dir,
                context=context,
            )
            command = [
                self.ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source_path),
            ]
            for asset_path in asset_paths:
                command.extend(["-loop", "1", "-i", str(asset_path)])
            command.extend([
                "-filter_complex",
                filter_graph,
                "-map", "[vout]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ])
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if result.returncode != 0:
                raise OverlayRenderError(f"ffmpeg overlay render failed: {result.stderr.strip()[-800:]}")
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise OverlayRenderError("overlay renderer did not produce output bytes")
        output_sha = _file_sha256(output_path)
        for receipt in receipts:
            receipt["output_sha256"] = output_sha
            receipt["renderer"] = self.capability_identity()["implementation"]
        verification_backend = self.ocr_backend or getattr(
            context, "overlay_ocr_backend", None
        )
        for index, receipt in enumerate(list(receipts)):
            if receipt.get("verification_required") is not True:
                continue
            if verification_backend is None:
                raise OverlayRenderError(
                    "readable overlays require an independent OCR backend"
                )
            window = receipt["frame_windows"][0]
            midpoint = (
                int(window["start_us"]) + int(window["end_us"])
            ) / 2_000_000
            with tempfile.TemporaryDirectory(
                prefix="usfr-overlay-ocr-", dir=str(work_dir)
            ) as verify_tmp:
                frame_path = Path(verify_tmp) / "frame.png"
                decoded = subprocess.run(
                    [
                        self.ffmpeg_bin,
                        "-y",
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{midpoint:.6f}",
                        "-i",
                        str(output_path),
                        "-frames:v",
                        "1",
                        str(frame_path),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if decoded.returncode != 0 or not frame_path.is_file():
                    raise OverlayRenderError(
                        "could not decode readable overlay verification frame"
                    )
                frame_bytes = frame_path.read_bytes()
            recognize = getattr(verification_backend, "recognize", None)
            if callable(recognize):
                evidence = recognize(frame_bytes)
            elif callable(verification_backend):
                evidence = verification_backend(frame_bytes)
            else:
                raise OverlayRenderError("independent OCR backend is invalid")
            if not isinstance(evidence, Mapping):
                raise OverlayRenderError(
                    "independent OCR backend returned invalid evidence"
                )
            receipts[index] = validate_readable_overlay_evidence(
                receipt,
                frame_bytes=frame_bytes,
                evidence=evidence,
                final_output_sha256=output_sha,
            )
        return {"output_path": output_path, "overlay_render_receipts": receipts}
