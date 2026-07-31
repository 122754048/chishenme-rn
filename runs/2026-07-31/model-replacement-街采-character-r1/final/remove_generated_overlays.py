from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np


RUN = Path(__file__).resolve().parents[1]
SOURCE = RUN / "seedance" / "provider" / "result.mp4"
OUTPUT = RUN / "final" / "cleaned_provider_video.mp4"
W, H, FPS = 720, 1280, 24


def overlay_mask(frame: np.ndarray) -> np.ndarray:
    mask = np.zeros((H, W), dtype=np.uint8)
    y0, y1, x0, x1 = 500, 780, 18, 702
    roi = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([78, 90, 120]), np.array([132, 255, 255]))
    pink = cv2.inRange(hsv, np.array([135, 75, 120]), np.array([179, 255, 255]))
    purple = cv2.inRange(hsv, np.array([125, 90, 90]), np.array([165, 255, 255]))
    yellow = cv2.inRange(hsv, np.array([10, 155, 145]), np.array([38, 255, 255]))
    colored = cv2.bitwise_or(cv2.bitwise_or(blue, pink), cv2.bitwise_or(purple, yellow))
    # Retain only compact bright graphic components, then expand across their white glyph interiors/outlines.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(colored, 8)
    kept = np.zeros_like(colored)
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area >= 8 and w <= 620 and h <= 150:
            kept[labels == i] = 255
    kept = cv2.morphologyEx(kept, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    kept = cv2.dilate(kept, np.ones((19, 19), np.uint8), iterations=1)
    # A final horizontal close joins colored outlines around white Japanese glyph centers.
    kept = cv2.morphologyEx(kept, cv2.MORPH_CLOSE, np.ones((35, 11), np.uint8), iterations=1)
    boxed = np.zeros_like(kept)
    contours, _ = cv2.findContours(kept, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < 80:
            continue
        pad_x, pad_y = 8, 7
        cv2.rectangle(boxed, (max(0, x - pad_x), max(0, y - pad_y)),
                      (min(boxed.shape[1] - 1, x + w + pad_x), min(boxed.shape[0] - 1, y + h + pad_y)), 255, -1)
    kept = cv2.bitwise_or(kept, boxed)
    mask[y0:y1, x0:x1] = kept
    return mask


def read_anchor(frame_number: int) -> np.ndarray:
    capture = cv2.VideoCapture(str(SOURCE))
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"cannot read clean anchor frame {frame_number}")
    return frame


def repair_from_anchor(frame: np.ndarray, anchor: np.ndarray, mask: np.ndarray) -> np.ndarray:
    # Estimate target-to-anchor motion from heavily blurred luminance so colored glyphs
    # do not dominate the flow, then sample clean pixels from the nearby no-caption frame.
    target_gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (0, 0), 10)
    anchor_gray = cv2.GaussianBlur(cv2.cvtColor(anchor, cv2.COLOR_BGR2GRAY), (0, 0), 10)
    scale = 0.25
    small_size = (round(W * scale), round(H * scale))
    target_small = cv2.resize(target_gray, small_size, interpolation=cv2.INTER_AREA)
    anchor_small = cv2.resize(anchor_gray, small_size, interpolation=cv2.INTER_AREA)
    flow_small = cv2.calcOpticalFlowFarneback(target_small, anchor_small, None, 0.5, 4, 31, 5, 7, 1.7, 0)
    flow = cv2.resize(flow_small, (W, H), interpolation=cv2.INTER_CUBIC) / scale
    flow = cv2.GaussianBlur(flow, (0, 0), 5)
    grid_x, grid_y = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    warped = cv2.remap(anchor, grid_x + flow[..., 0], grid_y + flow[..., 1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    feather = cv2.GaussianBlur(mask, (0, 0), 4.0).astype(np.float32) / 255.0
    feather = feather[..., None]
    repaired = frame.astype(np.float32) * (1.0 - feather) + warped.astype(np.float32) * feather
    return np.clip(repaired, 0, 255).astype(np.uint8)


def main() -> None:
    anchors = {
        "early": read_anchor(41),    # 1.708s gap after the first caption/logo
        "middle": read_anchor(104),  # 4.333s gap between answer and follow-up
        "late1": read_anchor(143),   # 5.958s gap before the large pink line
        "late2": read_anchor(252),   # 10.500s after the final caption
    }
    decode = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(SOURCE), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE,
    )
    encode = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p", str(OUTPUT)],
        stdin=subprocess.PIPE,
    )
    assert decode.stdout is not None and encode.stdin is not None
    frame_bytes = W * H * 3
    frame_index = 0
    while True:
        raw = decode.stdout.read(frame_bytes)
        if len(raw) != frame_bytes:
            break
        frame = np.frombuffer(raw, dtype=np.uint8).reshape((H, W, 3)).copy()
        t = frame_index / FPS
        anchor = None
        if t <= 1.65:
            anchor = anchors["early"]
        elif 1.75 <= t <= 3.05:
            anchor = anchors["early"]
        elif 3.05 < t <= 4.30:
            anchor = anchors["middle"]
        elif 4.42 <= t <= 5.68:
            anchor = anchors["middle"]
        elif 6.18 <= t <= 8.72:
            anchor = anchors["late1"]
        elif 8.55 <= t <= 10.48:
            anchor = anchors["late2"]
        mask = overlay_mask(frame)
        if 0.62 <= t <= 1.68:
            cv2.rectangle(mask, (255, 535), (480, 705), 255, -1)
        if anchor is not None and cv2.countNonZero(mask):
            frame = repair_from_anchor(frame, anchor, mask)
        encode.stdin.write(frame.tobytes())
        frame_index += 1
    encode.stdin.close()
    decode.stdout.close()
    decode.wait()
    encode.wait()
    if decode.returncode != 0 or encode.returncode != 0 or frame_index == 0:
        raise RuntimeError(f"overlay cleanup failed: decode={decode.returncode}, encode={encode.returncode}, frames={frame_index}")
    print(f"cleaned_frames={frame_index}")


if __name__ == "__main__":
    main()
