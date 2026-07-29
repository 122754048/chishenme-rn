from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


WIDTH = 160
HEIGHT = 120
FPS = 12


def _writer(path: Path, *, frames: int, draw) -> Path:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        FPS,
        (WIDTH, HEIGHT),
    )
    if not writer.isOpened():
        raise RuntimeError("test video writer could not open")
    for index in range(frames):
        frame = np.full((HEIGHT, WIDTH, 3), (18, 20, 28), dtype=np.uint8)
        draw(frame, index)
        writer.write(frame)
    writer.release()
    return path


def make_drag_video(tmp_path: Path, *, frames: int = 12, dx: int = 48) -> Path:
    def draw(frame: np.ndarray, index: int) -> None:
        progress = index / max(1, frames - 1)
        x = 18 + round(dx * progress)
        cv2.rectangle(frame, (x, 36), (x + 44, 82), (238, 238, 244), -1)
        cv2.circle(frame, (x + 12, 50), 6, (40, 80, 230), -1)
        cv2.putText(frame, "UI", (x + 8, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1)

    return _writer(tmp_path / "drag.mp4", frames=frames, draw=draw)


def make_target_ui(tmp_path: Path) -> Path:
    image = np.full((HEIGHT, WIDTH, 3), (26, 28, 38), dtype=np.uint8)
    cv2.rectangle(image, (18, 36), (62, 82), (60, 210, 135), -1)
    cv2.circle(image, (30, 50), 6, (230, 120, 40), -1)
    cv2.putText(image, "NEW", (22, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (12, 20, 14), 1)
    path = tmp_path / "target.png"
    cv2.imwrite(str(path), image)
    return path


def full_frame_contract(frames: int = 12) -> dict:
    return {
        "schema_version": "source-ui-interaction/v1",
        "region_id": "ui-test",
        "source_window_us": {"start": 0, "end_exclusive": round(frames / FPS * 1_000_000)},
        "frame_window": {"start": 0, "end_exclusive": frames},
        "source_fps": {"num": FPS, "den": 1},
        "display_viewport": [WIDTH, HEIGHT],
        "ui_roi": {
            "x": 0,
            "y": 0,
            "width": WIDTH,
            "height": HEIGHT,
            "coordinate_space": "display_pixels",
        },
    }


def video_with_motion_outside_roi(tmp_path: Path, *, frames: int = 12) -> Path:
    def draw(frame: np.ndarray, index: int) -> None:
        x = 100 + index * 2
        cv2.rectangle(frame, (x, 35), (min(WIDTH - 1, x + 28), 70), (245, 245, 245), -1)
        cv2.rectangle(frame, (8, 8), (62, 108), (34, 36, 46), 1)

    return _writer(tmp_path / "outside-roi.mp4", frames=frames, draw=draw)


def roi_contract(frames: int = 12) -> dict:
    contract = full_frame_contract(frames)
    contract["ui_roi"] = {
        "x": 0,
        "y": 0,
        "width": 72,
        "height": HEIGHT,
        "coordinate_space": "display_pixels",
    }
    return contract


def probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)["streams"][0]
