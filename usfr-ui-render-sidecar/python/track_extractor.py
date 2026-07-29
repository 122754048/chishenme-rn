from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class ExtractorError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ExtractorError(f"{label} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ExtractorError(f"{label} must be a positive integer") from exc
    if result <= 0:
        raise ExtractorError(f"{label} must be a positive integer")
    return result


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ExtractorError(f"{label} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ExtractorError(f"{label} must be a non-negative integer") from exc
    if result < 0:
        raise ExtractorError(f"{label} must be a non-negative integer")
    return result


def _validated_contract(contract: dict[str, Any]) -> dict[str, int]:
    if contract.get("schema_version") != "source-ui-interaction/v1":
        raise ExtractorError("unsupported source UI interaction contract")
    try:
        frame_start = _non_negative_int(contract["frame_window"]["start"], "frame window start")
        frame_end = _positive_int(contract["frame_window"]["end_exclusive"], "frame window end")
        fps_num = _positive_int(contract["source_fps"]["num"], "source FPS numerator")
        fps_den = _positive_int(contract["source_fps"]["den"], "source FPS denominator")
        viewport_width = _positive_int(contract["display_viewport"][0], "viewport width")
        viewport_height = _positive_int(contract["display_viewport"][1], "viewport height")
        roi = contract["ui_roi"]
        roi_x = _non_negative_int(roi["x"], "UI ROI x")
        roi_y = _non_negative_int(roi["y"], "UI ROI y")
        roi_width = _positive_int(roi["width"], "UI ROI width")
        roi_height = _positive_int(roi["height"], "UI ROI height")
    except (KeyError, IndexError, TypeError) as exc:
        raise ExtractorError("source UI interaction contract is incomplete") from exc
    if frame_end <= frame_start:
        raise ExtractorError("frame window is empty")
    if roi_x + roi_width > viewport_width or roi_y + roi_height > viewport_height:
        raise ExtractorError("UI ROI lies outside the display viewport")
    if roi.get("coordinate_space") != "display_pixels":
        raise ExtractorError("UI ROI coordinate space is unsupported")
    return {
        "frame_start": frame_start,
        "frame_end": frame_end,
        "expected_frames": frame_end - frame_start,
        "fps_num": fps_num,
        "fps_den": fps_den,
        "viewport_width": viewport_width,
        "viewport_height": viewport_height,
        "roi_x": roi_x,
        "roi_y": roi_y,
        "roi_width": roi_width,
        "roi_height": roi_height,
    }


def _read_frames(path: Path) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ExtractorError("motion reference video cannot be decoded")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames or not math.isfinite(fps) or fps <= 0:
        raise ExtractorError("motion reference video has no usable frames")
    return frames, fps


def _incremental_affine(
    previous_gray: np.ndarray,
    current_gray: np.ndarray,
    flow: np.ndarray,
) -> tuple[float, float, float, float, float]:
    magnitude = np.linalg.norm(flow, axis=2)
    active = magnitude >= 0.35
    if int(np.count_nonzero(active)) >= 8:
        dx = float(np.median(flow[..., 0][active]))
        dy = float(np.median(flow[..., 1][active]))
    else:
        dx = 0.0
        dy = 0.0

    scale = 1.0
    rotation = 0.0
    confidence = min(1.0, float(np.count_nonzero(active)) / max(1.0, active.size * 0.08))
    points = cv2.goodFeaturesToTrack(previous_gray, maxCorners=240, qualityLevel=0.01, minDistance=4)
    if points is not None and len(points) >= 4:
        tracked, status, _ = cv2.calcOpticalFlowPyrLK(previous_gray, current_gray, points, None)
        if tracked is not None and status is not None:
            valid = status.reshape(-1) == 1
            source_points = points.reshape(-1, 2)[valid]
            target_points = tracked.reshape(-1, 2)[valid]
            if len(source_points) >= 4:
                matrix, inliers = cv2.estimateAffinePartial2D(
                    source_points,
                    target_points,
                    method=cv2.RANSAC,
                    ransacReprojThreshold=2.5,
                )
                if matrix is not None and np.isfinite(matrix).all():
                    a = float(matrix[0, 0])
                    b = float(matrix[0, 1])
                    candidate_scale = math.sqrt(a * a + b * b)
                    if 0.75 <= candidate_scale <= 1.25:
                        scale = candidate_scale
                        rotation = math.degrees(math.atan2(float(matrix[1, 0]), a))
                    if abs(dx) < 0.35 and abs(dy) < 0.35:
                        dx = float(matrix[0, 2])
                        dy = float(matrix[1, 2])
                    if inliers is not None:
                        confidence = max(confidence, float(np.mean(inliers)))
    return dx, dy, scale, rotation, confidence


def _warp_roi(image: np.ndarray, flow: np.ndarray) -> np.ndarray:
    height, width = flow.shape[:2]
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    return cv2.remap(
        image,
        grid_x - flow[..., 0],
        grid_y - flow[..., 1],
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def _encode_frames(frame_dir: Path, output: Path, fps_num: int, fps_den: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExtractorError("FFmpeg is required to encode motion transfer frames")
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            f"{fps_num}/{fps_den}",
            "-i",
            str(frame_dir / "frame-%06d.png"),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output),
        ],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if result.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        raise ExtractorError(f"FFmpeg could not encode motion transfer: {result.stderr[-500:]}")


def extract_tracks(
    source_video: Path,
    target_image: Path,
    contract: dict[str, Any],
    output_dir: Path,
) -> dict[str, Path]:
    source_video = Path(source_video)
    target_image = Path(target_image)
    output_dir = Path(output_dir)
    if not source_video.is_file() or source_video.stat().st_size <= 0:
        raise ExtractorError("motion reference video is missing")
    if not target_image.is_file() or target_image.stat().st_size <= 0:
        raise ExtractorError("target UI image is missing")
    facts = _validated_contract(contract)
    frames, decoded_fps = _read_frames(source_video)
    if len(frames) != facts["expected_frames"]:
        raise ExtractorError(
            f"frame window expects {facts['expected_frames']} frames but motion reference contains {len(frames)}"
        )
    expected_fps = facts["fps_num"] / facts["fps_den"]
    if abs(decoded_fps - expected_fps) / expected_fps > 0.02:
        raise ExtractorError("motion reference FPS does not match the frame window contract")
    for frame in frames:
        if frame.shape[1] != facts["viewport_width"] or frame.shape[0] != facts["viewport_height"]:
            raise ExtractorError("motion reference viewport does not match the UI contract")

    target = cv2.imread(str(target_image), cv2.IMREAD_COLOR)
    if target is None:
        raise ExtractorError("target UI image cannot be decoded")
    target = cv2.resize(
        target,
        (facts["viewport_width"], facts["viewport_height"]),
        interpolation=cv2.INTER_AREA,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = output_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)

    x = facts["roi_x"]
    y = facts["roi_y"]
    width = facts["roi_width"]
    height = facts["roi_height"]
    previous_gray = cv2.cvtColor(frames[0][y : y + height, x : x + width], cv2.COLOR_BGR2GRAY)
    reference_mean = max(1.0, float(np.mean(previous_gray)))
    warped_target = target.copy()
    cumulative_x = 0.0
    cumulative_y = 0.0
    cumulative_scale = 1.0
    cumulative_rotation = 0.0
    rows: list[dict[str, Any]] = []

    for index, source_frame in enumerate(frames):
        current_gray = cv2.cvtColor(
            source_frame[y : y + height, x : x + width],
            cv2.COLOR_BGR2GRAY,
        )
        tap = False
        confidence = 1.0 if index == 0 else 0.0
        if index > 0:
            flow = cv2.calcOpticalFlowFarneback(
                previous_gray,
                current_gray,
                None,
                pyr_scale=0.5,
                levels=4,
                winsize=21,
                iterations=5,
                poly_n=7,
                poly_sigma=1.5,
                flags=0,
            )
            dx, dy, step_scale, step_rotation, confidence = _incremental_affine(
                previous_gray,
                current_gray,
                flow,
            )
            cumulative_x += dx
            cumulative_y += dy
            cumulative_scale *= step_scale
            cumulative_rotation += step_rotation
            difference = cv2.absdiff(previous_gray, current_gray)
            changed_ratio = float(np.mean(difference >= 35))
            tap = abs(dx) < 1.0 and abs(dy) < 1.0 and 0.001 <= changed_ratio <= 0.12
            warped_roi = _warp_roi(warped_target[y : y + height, x : x + width], flow)
            warped_target[y : y + height, x : x + width] = warped_roi

        opacity = max(0.0, min(1.0, float(np.mean(current_gray)) / reference_mean))
        numeric_values = (
            cumulative_x,
            cumulative_y,
            cumulative_scale,
            cumulative_rotation,
            opacity,
            confidence,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise ExtractorError("motion extraction produced a non-finite track value")
        rows.append(
            {
                "frame": index,
                "translation_x": round(cumulative_x, 4),
                "translation_y": round(cumulative_y, 4),
                "scale_x": round(cumulative_scale, 6),
                "scale_y": round(cumulative_scale, 6),
                "rotation_deg": round(cumulative_rotation, 4),
                "opacity": round(opacity, 6),
                "tap": bool(tap),
                "confidence": round(max(0.0, min(1.0, confidence)), 6),
            }
        )
        frame_path = frame_dir / f"frame-{index + 1:06d}.png"
        if not cv2.imwrite(str(frame_path), warped_target):
            raise ExtractorError("motion transfer frame could not be written")
        previous_gray = current_gray

    video_path = output_dir / "motion.mp4"
    _encode_frames(frame_dir, video_path, facts["fps_num"], facts["fps_den"])
    track = {
        "schema_version": "usfr-ui-motion-track/v1",
        "source_video_sha256": _sha256(source_video),
        "target_image_sha256": _sha256(target_image),
        "fps": {"num": facts["fps_num"], "den": facts["fps_den"]},
        "viewport": [facts["viewport_width"], facts["viewport_height"]],
        "roi": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "coordinate_space": "display_pixels",
        },
        "frames": rows,
    }
    track_path = output_dir / "motion-track.json"
    track_path.write_text(
        json.dumps(track, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return {"video_path": video_path, "track_path": track_path}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        contract = json.loads(arguments.contract.read_text(encoding="utf-8"))
        result = extract_tracks(arguments.source, arguments.target, contract, arguments.output_dir)
    except (ExtractorError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "video_path": str(result["video_path"]),
                "track_path": str(result["track_path"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
