from __future__ import annotations

import argparse
import itertools
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from insightface import model_zoo


ROOT = Path(__file__).resolve().parent
INSIGHT_ROOT = Path(r"E:\AI\Comfyui_mi\ComfyUI\models\insightface")
SWAPPER_PATH = INSIGHT_ROOT / "inswapper_128.fp16.onnx"
PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"]
TRACK_ORDER = ("SRC_BLONDE", "SRC_MAN", "SRC_DARK")
SWAP_TRACKS = ("SRC_BLONDE", "SRC_DARK")


def _unit(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(value))
    if norm <= 1e-8:
        raise ValueError("zero embedding")
    return value / norm


def assign_unique_tracks(
    templates: Mapping[str, np.ndarray],
    candidates: Sequence[Mapping[str, Any]],
    *,
    previous_centers: Mapping[str, tuple[float, float]],
    minimum_score: float = 0.25,
) -> dict[str, int]:
    """Assign detections uniquely by identity similarity plus mild motion continuity."""

    tracks = list(templates)
    if not tracks or not candidates:
        return {}
    normalized_templates = {track: _unit(templates[track]) for track in tracks}
    scores: dict[tuple[str, int], float] = {}
    for track in tracks:
        previous = previous_centers.get(track)
        for index, candidate in enumerate(candidates):
            similarity = float(np.dot(normalized_templates[track], _unit(np.asarray(candidate["embedding"]))))
            center = candidate.get("center")
            motion_penalty = 0.0
            if previous is not None and isinstance(center, tuple) and len(center) == 2:
                motion_penalty = 0.15 * float(np.hypot(center[0] - previous[0], center[1] - previous[1]))
            scores[(track, index)] = similarity - motion_penalty

    best_score = float("-inf")
    best: dict[str, int] = {}
    pair_count = min(len(tracks), len(candidates))
    for selected_tracks in itertools.combinations(tracks, pair_count):
        for candidate_indices in itertools.permutations(range(len(candidates)), pair_count):
            assignment = dict(zip(selected_tracks, candidate_indices, strict=True))
            total = sum(scores[(track, index)] for track, index in assignment.items())
            if total > best_score:
                best_score = total
                best = assignment
    return {
        track: index
        for track, index in best.items()
        if scores[(track, index)] >= minimum_score
    }


def _largest_face(faces: Sequence[Any], label: str) -> Any:
    if not faces:
        raise RuntimeError(f"No face detected in {label}")
    return max(faces, key=lambda face: float((face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])))


def _candidate(face: Any, width: int, height: int) -> dict[str, Any]:
    x1, y1, x2, y2 = (float(value) for value in face.bbox)
    return {
        "face": face,
        "embedding": np.asarray(face.embedding, dtype=np.float32),
        "center": (((x1 + x2) / 2) / width, ((y1 + y2) / 2) / height),
        "bbox": [x1, y1, x2, y2],
    }


def _source_face(app: FaceAnalysis, path: Path) -> Any:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Cannot decode identity reference: {path}")
    square = cv2.resize(image, (512, 512), interpolation=cv2.INTER_AREA)
    padded = np.full((1024, 1024, 3), 230, dtype=np.uint8)
    padded[256:768, 256:768] = square
    return _largest_face(app.get(padded), path.name)


def complete_video(input_path: Path, output_path: Path) -> dict[str, Any]:
    if not SWAPPER_PATH.is_file():
        raise RuntimeError(f"Missing swapper model: {SWAPPER_PATH}")
    app = FaceAnalysis(name="buffalo_l", root=str(INSIGHT_ROOT), providers=PROVIDERS)
    app.prepare(ctx_id=0, det_size=(640, 640), det_thresh=0.20)
    swapper = model_zoo.get_model(str(SWAPPER_PATH), providers=PROVIDERS)
    replacement_faces = {
        "SRC_BLONDE": _source_face(app, ROOT / "identity_v3" / "02_TARGET_BLONDE.png"),
        "SRC_DARK": _source_face(app, ROOT / "identity_v3" / "03_TARGET_DARK.png"),
    }

    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, first_frame = capture.read()
    if not ok:
        raise RuntimeError("Cannot decode first video frame")
    initial_faces = sorted(
        app.get(first_frame),
        key=lambda face: float(face.bbox[0] + face.bbox[2]),
    )
    if len(initial_faces) < 3:
        raise RuntimeError(f"First frame must expose three human faces; found {len(initial_faces)}")
    initial_faces = initial_faces[:3]
    templates = {
        track: _unit(np.asarray(face.embedding, dtype=np.float32))
        for track, face in zip(TRACK_ORDER, initial_faces, strict=True)
    }
    previous_centers = {
        track: _candidate(face, width, height)["center"]
        for track, face in zip(TRACK_ORDER, initial_faces, strict=True)
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s:v", f"{width}x{height}", "-r", f"{fps:.8f}", "-i", "pipe:0",
        "-i", str(input_path),
        "-map", "0:v:0", "-map", "1:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-c:a", "copy", "-shortest", "-movflags", "+faststart",
        str(output_path),
    ]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    if encoder.stdin is None:
        raise RuntimeError("Cannot open FFmpeg input pipe")

    counts = {track: 0 for track in SWAP_TRACKS}
    unassigned = {track: 0 for track in TRACK_ORDER}
    frames_processed = 0

    def process_frame(frame: np.ndarray) -> np.ndarray:
        nonlocal frames_processed
        faces = app.get(frame)
        candidates = [_candidate(face, width, height) for face in faces]
        assignment = assign_unique_tracks(templates, candidates, previous_centers=previous_centers)
        output = frame
        for track in TRACK_ORDER:
            candidate_index = assignment.get(track)
            if candidate_index is None:
                unassigned[track] += 1
                continue
            candidate = candidates[candidate_index]
            previous_centers[track] = candidate["center"]
            if track in replacement_faces:
                swapped = swapper.get(output, candidate["face"], replacement_faces[track], paste_back=True)
                if swapped is None:
                    raise RuntimeError(f"Face swap failed for {track} at frame {frames_processed}")
                output = swapped
                counts[track] += 1
        frames_processed += 1
        return output

    try:
        encoder.stdin.write(process_frame(first_frame).tobytes())
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            encoder.stdin.write(process_frame(frame).tobytes())
    finally:
        capture.release()
        encoder.stdin.close()
    stderr = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr is not None else ""
    return_code = encoder.wait()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg failed ({return_code}): {stderr}")
    if frames_processed != expected_frames:
        raise RuntimeError(f"Frame count mismatch: processed {frames_processed}, expected {expected_frames}")

    manifest = {
        "schema_version": "reinbow-local-multi-face-completion/v1",
        "input_video": str(input_path),
        "output_video": str(output_path),
        "fps": fps,
        "width": width,
        "height": height,
        "frames_processed": frames_processed,
        "swap_counts": counts,
        "unassigned_frames": unassigned,
        "protected_tracks": ["SRC_MAN", "SRC_ALIEN"],
    }
    output_path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(complete_video(args.input, args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
