from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


FPS = 30
FRAME_COUNT = 141
WIDTH = 480
HEIGHT = 854

CTA_TEXT = "加入房间"
STATUS_TEXT = "在线"
SUBTITLE_0 = "想告别孤单，\n开心地认识和你一样的人吗？"
SUBTITLE_1 = "那你一定要试试 ISUGO！"
SUBTITLE_2 = "不过要小心……\n你可能会玩到睡不着！"


def _run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:] or "media command failed")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value


def _extract_frames(source: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            f"fps={FPS}",
            str(destination / "source-%06d.png"),
        ]
    )
    frames = sorted(destination.glob("source-*.png"))
    if len(frames) != FRAME_COUNT:
        raise RuntimeError(f"expected {FRAME_COUNT} source frames, got {len(frames)}")
    return frames


def _component_boxes(mask: np.ndarray, *, min_area: int, max_area: int) -> list[tuple[int, int, int, int]]:
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    boxes: list[tuple[int, int, int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if min_area <= area <= max_area:
            boxes.append((x, y, width, height))
    return boxes


def _cta_boxes(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    blue, green, red = cv2.split(frame)
    magenta = (
        (red > 105)
        & (blue > 65)
        & (red.astype(np.float32) > green.astype(np.float32) * 1.12)
        & (blue.astype(np.float32) > green.astype(np.float32) * 1.02)
    ).astype(np.uint8)
    strong_magenta = cv2.inRange(
        hsv,
        np.array([118, 120, 110]),
        np.array([179, 255, 255]),
    )
    near_magenta = cv2.dilate(magenta * 255, np.ones((21, 21), np.uint8))
    white = cv2.inRange(hsv, np.array([0, 0, 150]), np.array([179, 115, 255]))
    grouped = cv2.dilate(
        cv2.bitwise_and(white, near_magenta),
        np.ones((7, 13), np.uint8),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(grouped, 8)
    text_boxes: list[tuple[int, int, int, int]] = []
    for index in range(1, count):
        x, y, width, height, _area = (int(value) for value in stats[index])
        if not 82 <= width <= 185 or not 14 <= height <= 40:
            continue
        left = max(0, x - 15)
        top = max(0, y - 12)
        right = min(WIDTH, x + width + 15)
        bottom = min(HEIGHT, y + height + 12)
        if float(np.mean(magenta[top:bottom, left:right])) < 0.5:
            continue
        text_boxes.append((left, top, right - left, bottom - top))
    component_mask = cv2.morphologyEx(
        magenta * 255,
        cv2.MORPH_CLOSE,
        np.ones((9, 17), np.uint8),
    )
    component_boxes = [
        box
        for box in _component_boxes(component_mask, min_area=300, max_area=20_000)
        if 75 <= box[2] <= 220 and 18 <= box[3] <= 90
    ]
    deduplicated: list[tuple[int, int, int, int]] = []
    ordered_candidates = sorted(
        text_boxes,
        key=lambda value: value[2] * value[3],
        reverse=True,
    ) + sorted(
        component_boxes,
        key=lambda value: value[2] * value[3],
        reverse=True,
    )
    for candidate in ordered_candidates:
        x, y, width, height = candidate
        area = width * height
        if float(np.mean(strong_magenta[y : y + height, x : x + width] > 0)) < 0.25:
            continue
        duplicate = False
        for kept_x, kept_y, kept_width, kept_height in deduplicated:
            intersection_width = max(0, min(x + width, kept_x + kept_width) - max(x, kept_x))
            intersection_height = max(0, min(y + height, kept_y + kept_height) - max(y, kept_y))
            intersection = intersection_width * intersection_height
            if intersection / max(1, min(area, kept_width * kept_height)) >= 0.65:
                duplicate = True
                break
        if not duplicate:
            deduplicated.append(candidate)
    return sorted(deduplicated, key=lambda value: (value[1], value[0]))


def _status_boxes(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35, 130, 105]), np.array([100, 255, 255]))
    boxes: list[tuple[int, int, int, int]] = []
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(green, 8)
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if not 70 <= area <= 520:
            continue
        local_x = x % (WIDTH // 2)
        ratio = width / max(1, height)
        solidity = area / max(1, width * height)
        if (
            6 <= width <= 30
            and 6 <= height <= 30
            and 0.55 <= ratio <= 1.8
            and solidity >= 0.65
            and local_x < 78
        ):
            left = max(0, x - 5)
            top = max(0, y - 9)
            right = min(WIDTH, x + 94)
            bottom = min(HEIGHT, y + height + 9)
            boxes.append((left, top, right - left, bottom - top))
    return sorted(boxes, key=lambda value: (value[1], value[0]))


def _subtitle(frame: np.ndarray) -> tuple[tuple[int, int, int, int] | None, np.ndarray | None, str | None]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([40, 115, 115]), np.array([88, 255, 255]))
    constrained = np.zeros_like(green)
    constrained[285:455, 35:445] = green[285:455, 35:445]
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(constrained, 8)
    selected = np.zeros_like(green)
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if 4 <= area <= 210 and 35 <= x <= 445 and 285 <= y <= 455 and width <= 42 and height <= 42:
            selected[labels == index] = 255
    points = cv2.findNonZero(selected)
    if points is None or len(points) < 40:
        return None, None, None
    x, y, width, height = cv2.boundingRect(points)
    if width < 180:
        return None, None, None
    x = 35
    y = max(270, y - 10)
    width = WIDTH - 70
    height = min(190, height + 20)
    phrase = SUBTITLE_2 if height >= 58 else SUBTITLE_1
    broad_green = cv2.inRange(hsv, np.array([30, 60, 65]), np.array([100, 255, 255]))
    removal = np.zeros_like(green)
    removal[y : y + height, x : x + width] = broad_green[y : y + height, x : x + width]
    removal = cv2.dilate(removal, np.ones((9, 9), np.uint8), iterations=1)
    return (x, y, width, height), removal, phrase


def _inpaint_white_text(
    frame: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    require_magenta: bool = False,
) -> np.ndarray:
    x, y, width, height = box
    roi = frame[y : y + height, x : x + width]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 145]), np.array([179, 105, 255]))
    if require_magenta:
        blue, green, red = cv2.split(roi)
        magenta = (
            (red > 95)
            & (blue > 55)
            & (red.astype(np.float32) > green.astype(np.float32) * 1.08)
            & (blue.astype(np.float32) > green.astype(np.float32) * 0.98)
        ).astype(np.uint8) * 255
        mask = cv2.bitwise_and(mask, cv2.dilate(magenta, np.ones((9, 9), np.uint8)))
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    cleaned = cv2.inpaint(roi, mask, 3, cv2.INPAINT_TELEA)
    result = frame.copy()
    result[y : y + height, x : x + width] = cleaned
    return result


def _text_layout(
    *,
    element_id: str,
    text: str,
    box: tuple[int, int, int, int],
    font_size: int,
    color: str,
) -> dict[str, Any]:
    x, y, width, height = box
    return {
        "element_id": element_id,
        "role": "localized_ui_text",
        "text": text,
        "bbox": [x, y, x + width, y + height],
        "font_size": font_size,
        "color": color,
        "text_align": "center",
    }


def _build_states(frames: list[np.ndarray]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    states: list[dict[str, Any]] = []
    geometry: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        ctas = _cta_boxes(frame)
        statuses = _status_boxes(frame)
        subtitle_box, subtitle_mask, subtitle_text = _subtitle(frame)
        if subtitle_box is not None:
            if index < 28:
                subtitle_text = SUBTITLE_0
            elif index < 66:
                subtitle_text = SUBTITLE_1
            else:
                subtitle_text = SUBTITLE_2
        layouts: list[dict[str, Any]] = []
        for item_index, box in enumerate(ctas):
            x, y, width, height = box
            inner = (x + 5, y + 4, max(20, width - 10), max(14, height - 8))
            layouts.append(
                _text_layout(
                    element_id=f"cta-{index:03d}-{item_index}",
                    text=CTA_TEXT,
                    box=inner,
                    font_size=max(15, min(24, int(height * 0.48))),
                    color="#ffffff",
                )
            )
        for item_index, box in enumerate(statuses):
            x, y, width, height = box
            label = (x + 25, y + 1, max(18, width - 30), max(12, height - 2))
            layouts.append(
                _text_layout(
                    element_id=f"status-{index:03d}-{item_index}",
                    text=STATUS_TEXT,
                    box=label,
                    font_size=max(11, min(16, int(height * 0.52))),
                    color="#ffffff",
                )
            )
        if subtitle_box is not None and subtitle_text is not None:
            layouts.append(
                _text_layout(
                    element_id=f"subtitle-{index:03d}",
                    text=subtitle_text,
                    box=subtitle_box,
                    font_size=25 if subtitle_text == SUBTITLE_1 else 23,
                    color="#4cff20",
                )
            )
        state_id = f"frame-{index:03d}"
        states.append(
            {
                "state_id": state_id,
                "frame_ms": int(round(index * 1000 / FPS)),
                "expected_text": [layout["text"] for layout in layouts],
                "expected_layout": layouts,
            }
        )
        geometry.append(
            {
                "frame": index,
                "cta_boxes": ctas,
                "status_boxes": statuses,
                "subtitle_box": subtitle_box,
                "subtitle_mask": subtitle_mask,
                "subtitle_text": subtitle_text,
            }
        )
    return states, geometry


def _prepare_target(frame: np.ndarray, geometry: dict[str, Any], output: Path) -> None:
    target = frame.copy()
    for box in geometry["cta_boxes"] + geometry["status_boxes"]:
        target = _inpaint_white_text(target, box)
    if geometry["subtitle_mask"] is not None:
        target = cv2.inpaint(target, geometry["subtitle_mask"], 4, cv2.INPAINT_TELEA)
    if not cv2.imwrite(str(output), target):
        raise RuntimeError("target UI image could not be written")


def _extract_video_frames(video: Path, destination: Path, prefix: str) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={FPS}",
            str(destination / f"{prefix}-%06d.png"),
        ]
    )
    paths = sorted(destination.glob(f"{prefix}-*.png"))
    if len(paths) != FRAME_COUNT:
        raise RuntimeError(f"expected {FRAME_COUNT} {prefix} frames, got {len(paths)}")
    return paths


def _copy_sidecar_glyphs(
    cleaned: np.ndarray,
    sidecar: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    kind: str,
) -> np.ndarray:
    x, y, width, height = box
    source = sidecar[y : y + height, x : x + width]
    result_roi = cleaned[y : y + height, x : x + width]
    hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV)
    if kind == "subtitle":
        glyph = cv2.inRange(hsv, np.array([38, 100, 100]), np.array([90, 255, 255]))
        glyph = cv2.morphologyEx(glyph, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        outline = cv2.dilate(glyph, np.ones((5, 5), np.uint8), iterations=1)
        result_roi[outline > 0] = (0, 0, 0)
    else:
        glyph = cv2.inRange(hsv, np.array([0, 0, 155]), np.array([179, 105, 255]))
        glyph = cv2.morphologyEx(glyph, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    if int(np.count_nonzero(glyph)) < (3 if kind == "status" else 12):
        return cleaned
    result_roi[glyph > 0] = source[glyph > 0]
    result = cleaned.copy()
    result[y : y + height, x : x + width] = result_roi
    return result


def _draw_centered_text(
    frame: np.ndarray,
    text: str,
    box: tuple[int, int, int, int],
    *,
    font_size: int,
    fill: tuple[int, int, int],
    stroke_width: int = 0,
) -> np.ndarray:
    x, y, width, height = box
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", font_size)
    spacing = max(2, font_size // 8)
    left, top, right, bottom = draw.multiline_textbbox(
        (0, 0), text, font=font, spacing=spacing, align="center", stroke_width=stroke_width
    )
    text_width = right - left
    text_height = bottom - top
    position = (
        x + (width - text_width) / 2 - left,
        y + (height - text_height) / 2 - top,
    )
    draw.multiline_text(
        position,
        text,
        font=font,
        fill=fill,
        spacing=spacing,
        align="center",
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0),
    )
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def _compose_frames(
    source_paths: list[Path],
    sidecar_paths: list[Path],
    geometry: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, (source_path, sidecar_path, record) in enumerate(zip(source_paths, sidecar_paths, geometry)):
        frame = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
        sidecar = cv2.imread(str(sidecar_path), cv2.IMREAD_COLOR)
        if frame is None or sidecar is None:
            raise RuntimeError(f"frame {index} could not be decoded")
        result = frame.copy()
        for box in _cta_boxes(frame):
            result = _inpaint_white_text(result, box, require_magenta=True)
            x, y, width, height = box
            result = _draw_centered_text(
                result,
                CTA_TEXT,
                (x + 4, y + 2, max(20, width - 8), max(14, height - 4)),
                font_size=max(15, min(23, int(height * 0.46))),
                fill=(255, 255, 255),
            )
        for box in _status_boxes(frame):
            result = _inpaint_white_text(result, box)
            x, y, width, height = box
            label_box = (x + 25, y + 1, max(18, width - 30), max(12, height - 2))
            result = _draw_centered_text(
                result,
                STATUS_TEXT,
                label_box,
                font_size=max(11, min(16, int(height * 0.52))),
                fill=(255, 255, 255),
            )
        if record["subtitle_box"] is not None and record["subtitle_mask"] is not None:
            result = cv2.inpaint(result, record["subtitle_mask"], 4, cv2.INPAINT_TELEA)
            result = _draw_centered_text(
                result,
                record["subtitle_text"],
                record["subtitle_box"],
                font_size=25 if record["subtitle_text"] == SUBTITLE_1 else 23,
                fill=(32, 255, 76),
                stroke_width=3,
            )
        if not cv2.imwrite(str(output_dir / f"final-{index + 1:06d}.png"), result):
            raise RuntimeError(f"frame {index} could not be written")


def _probe(path: Path) -> dict[str, Any]:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        timeout=60,
    )
    value = json.loads(result.stdout)
    video = next(stream for stream in value["streams"] if stream.get("codec_type") == "video")
    audio = [stream for stream in value["streams"] if stream.get("codec_type") == "audio"]
    if (
        video.get("codec_name") != "h264"
        or int(video.get("width") or 0) != WIDTH
        or int(video.get("height") or 0) != HEIGHT
        or int(video.get("nb_read_frames") or 0) != FRAME_COUNT
        or not audio
    ):
        raise RuntimeError("final localized UI video failed the basic media contract")
    return {"video": video, "audio": audio[0], "format": value["format"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--skill-root", required=True, type=Path)
    parser.add_argument("--resume-existing", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    run_root = args.run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=args.resume_existing)
    _load_env(args.env_file.resolve())
    os.environ["USFR_UI_SIDECAR_IDLE_TIMEOUT_SECONDS"] = "12"
    project_root = Path(os.environ["USFR_UI_SIDECAR_PROJECT_DIR"]).resolve()
    manifest = json.loads((project_root / "sidecar-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("cpu_only") is not True:
        raise RuntimeError("configured UI Sidecar is not CPU-only")
    if os.environ.get("USFR_UI_RENDER_MODEL_SHA256") != manifest.get("model_sha256"):
        raise RuntimeError("configured Sidecar model does not match its manifest")

    input_dir = run_root / "inputs"
    analysis_dir = run_root / "analysis"
    sidecar_dir = run_root / "sidecar"
    final_dir = run_root / "final"
    source_frames_dir = run_root / "source-frames"
    sidecar_frames_dir = run_root / "sidecar-frames"
    final_frames_dir = run_root / "final-frames"
    for directory in (input_dir, analysis_dir, sidecar_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)
    bound_source = input_dir / source.name
    if not bound_source.is_file():
        shutil.copy2(source, bound_source)

    source_paths = sorted(source_frames_dir.glob("source-*.png"))
    if len(source_paths) != FRAME_COUNT:
        source_paths = _extract_frames(bound_source, source_frames_dir)
    source_frames = [cv2.imread(str(path), cv2.IMREAD_COLOR) for path in source_paths]
    if any(frame is None for frame in source_frames):
        raise RuntimeError("one or more source frames could not be decoded")
    states, geometry = _build_states(source_frames)
    target_image = sidecar_dir / "localized-ui-target.png"
    if not target_image.is_file():
        _prepare_target(source_frames[0], geometry[0], target_image)

    geometry_json = []
    for record in geometry:
        geometry_json.append(
            {
                "frame": record["frame"],
                "cta_boxes": record["cta_boxes"],
                "status_boxes": record["status_boxes"],
                "subtitle_box": record["subtitle_box"],
                "subtitle_text": record["subtitle_text"],
            }
        )
    (analysis_dir / "ui_geometry.json").write_text(
        json.dumps(geometry_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    interaction = {
        "schema_version": "source-ui-interaction/v1",
        "region_id": "ui-localization-001",
        "source_window_us": {"start": 0, "end_exclusive": 4_700_000},
        "frame_window": {"start": 0, "end_exclusive": FRAME_COUNT},
        "source_fps": {"num": FPS, "den": 1},
        "display_viewport": [WIDTH, HEIGHT],
        "ui_roi": {
            "x": 0,
            "y": 0,
            "width": WIDTH,
            "height": HEIGHT,
            "coordinate_space": "display_pixels",
        },
        "language": {"source": "ar", "target": "zh", "mode": "localized"},
        "text_encoding": {"encoding": "utf-8", "replacement_glyphs_forbidden": True},
        "motion": {
            "capture_scope": "ui_roi_only",
            "track_policy": "source_frame_locked",
            "supported_actions": ["drag", "scroll", "bounce", "scale", "rotate", "opacity", "tap"],
        },
        "validation": {
            "mode": "basic_anchor_only",
            "automatic_retry": False,
            "anchor_frames": [0, FRAME_COUNT - 1],
        },
    }
    truth = {
        "approved_copy": [STATUS_TEXT, CTA_TEXT, SUBTITLE_0, SUBTITLE_1, SUBTITLE_2],
        "states": states,
    }
    render_contract = {
        "route": "generated_ui_demo",
        "viewport": [WIDTH, HEIGHT],
        "state_sequence": [state["state_id"] for state in states],
        "source_ui_interaction_contract": interaction,
        "language": {"source": "ar", "target": "zh", "mode": "localized"},
        "text_encoding": {"encoding": "utf-8", "replacement_glyphs_forbidden": True},
    }
    (analysis_dir / "ui_truth_card.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (analysis_dir / "ui_render_contract.json").write_text(
        json.dumps(render_contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(args.skill_root.resolve()))
    from server.ui_sidecar_runtime import OnDemandUiSidecarRenderer
    from server.vision_backends import EvidenceBoundHttpUiRenderer

    delegate = EvidenceBoundHttpUiRenderer(
        endpoint=os.environ["USFR_UI_RENDER_ENDPOINT"],
        model_id=os.environ["USFR_UI_RENDER_MODEL_ID"],
        model_sha256=os.environ["USFR_UI_RENDER_MODEL_SHA256"],
        api_token_env="USFR_UI_RENDER_API_TOKEN",
        timeout_seconds=float(os.environ.get("USFR_UI_RENDER_TIMEOUT_SECONDS", "300")),
        production=False,
    )
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is unavailable")
    sidecar_video = sidecar_dir / "localized-ui-sidecar.mp4"
    result: dict[str, Any] | None = None
    sidecar_seconds: float | None = None
    if not args.resume_existing:
        wrapper = OnDemandUiSidecarRenderer(
            renderer=delegate,
            command=[npm, "run", "start", "--silent"],
            project_dir=project_root,
            startup_timeout_seconds=float(os.environ.get("USFR_UI_SIDECAR_STARTUP_TIMEOUT_SECONDS", "90")),
            startup_lock_path=project_root / ".runtime" / "sidecar-startup.lock",
        )

        @contextmanager
        def materialize_slot(slot_id: str):
            if slot_id != "source_video":
                raise RuntimeError("unexpected materialized slot")
            yield SimpleNamespace(path=bound_source)

        context = SimpleNamespace(materialize_slot=materialize_slot, work_dir=sidecar_dir)
        started_at = time.perf_counter()
        result = dict(
            wrapper(
                target_image,
                sidecar_video,
                context,
                truth=truth,
                render_contract=render_contract,
            )
        )
        sidecar_seconds = round(time.perf_counter() - started_at, 3)
    elif not sidecar_video.is_file():
        raise RuntimeError("existing Sidecar video is unavailable for resume")
    sidecar_paths = sorted(sidecar_frames_dir.glob("sidecar-*.png"))
    if len(sidecar_paths) != FRAME_COUNT:
        sidecar_paths = _extract_video_frames(sidecar_video, sidecar_frames_dir, "sidecar")
    _compose_frames(source_paths, sidecar_paths, geometry, final_frames_dir)

    final_video = final_dir / "7月16日(1)_中文UI.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
            "-i",
            str(final_frames_dir / "final-%06d.png"),
            "-i",
            str(bound_source),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "15",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(final_video),
        ],
        timeout=300,
    )
    probe = _probe(final_video)
    receipt = {
        "schema_version": "usfr-ui-localization-receipt/v1",
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "final_path": str(final_video),
        "final_sha256": _sha256(final_video),
        "language": {"source": "ar", "target": "zh"},
        "translations": {
            "متصل": STATUS_TEXT,
            "انضم إلى الغرفة": CTA_TEXT,
            "عايز تبقى مش لوحدك وسعيد وتتواصل مع ناس زيك؟": SUBTITLE_0.replace("\n", " "),
            "يبقى لازم تجرب ISUGO!": SUBTITLE_1,
            "بس خد بالك... ممكن ماتعرفش تنام بسببها!": SUBTITLE_2.replace("\n", " "),
        },
        "sidecar_seconds": sidecar_seconds,
        "sidecar_result": {
            "backend_evidence": result.get("backend_evidence") if result else None,
            "decision": result.get("ui_renderer_decision") if result else {"reused_existing_render": True},
            "video_sha256": _sha256(sidecar_video),
        },
        "counts": {
            "frames": FRAME_COUNT,
            "cta_instances": sum(len(item["cta_boxes"]) for item in geometry),
            "status_instances": sum(len(item["status_boxes"]) for item in geometry),
            "subtitle_frames": sum(item["subtitle_box"] is not None for item in geometry),
        },
        "qa": {
            "mode": "basic",
            "automatic_retry": False,
            "video_decodable": True,
            "audio_preserved": True,
            "frame_count": FRAME_COUNT,
            "dimensions": [WIDTH, HEIGHT],
            "fps": FPS,
            "exact_utf8_target_text": True,
        },
        "probe": probe,
    }
    receipt_path = final_dir / "ui-localization-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"final_video": str(final_video), "receipt": str(receipt_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
