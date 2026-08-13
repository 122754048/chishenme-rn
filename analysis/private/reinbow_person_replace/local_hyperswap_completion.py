from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import cv2
import numpy as np

from local_multi_face_completion import assign_unique_tracks


TRACK_ORDER = ("SRC_BLONDE", "SRC_MAN", "SRC_DARK")
SWAP_TRACKS = ("SRC_BLONDE", "SRC_DARK")


def build_ffmpeg_command(
    *,
    width: int,
    height: int,
    fps: float,
    input_path: Path,
    output_path: Path,
) -> list[str]:
    return [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s:v",
        f"{width}x{height}",
        "-r",
        f"{fps:.8f}",
        "-i",
        "pipe:0",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "17",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


class HyperSwapCompletion:
    """Deterministic multi-track completion using FaceFusion HyperSwap 256."""

    def __init__(
        self,
        *,
        facefusion_root: Path,
        identity_root: Path,
        pixel_boost: str = "512x512",
        face_swapper_weight: float = 0.65,
    ) -> None:
        self.facefusion_root = facefusion_root.resolve()
        self.identity_root = identity_root.resolve()
        if not (self.facefusion_root / "facefusion.py").is_file():
            raise RuntimeError(f"FaceFusion checkout is missing: {self.facefusion_root}")
        if str(self.facefusion_root) not in sys.path:
            sys.path.insert(0, str(self.facefusion_root))

        previous_cwd = Path.cwd()
        os.chdir(self.facefusion_root)
        try:
            from facefusion.program import create_program
            from facefusion.args import apply_args
            from facefusion import state_manager

            calibration_path = self.identity_root / "02_TARGET_BLONDE.png"
            args = vars(
                create_program().parse_args(
                    [
                        "headless-run",
                        "-s",
                        str(calibration_path),
                        "-t",
                        str(calibration_path),
                        "-o",
                        str(self.identity_root / "_unused_hyperswap_output.png"),
                        "--processors",
                        "face_swapper",
                        "--face-swapper-model",
                        "hyperswap_1a_256",
                        "--face-swapper-pixel-boost",
                        pixel_boost,
                        "--face-swapper-weight",
                        str(face_swapper_weight),
                        "--face-mask-types",
                        "box",
                        "occlusion",
                        "--face-mask-blur",
                        "0.30",
                        "--face-mask-padding",
                        "0",
                        "0",
                        "0",
                        "0",
                        "--execution-providers",
                        "cpu",
                        "--execution-thread-count",
                        "1",
                        "--download-providers",
                        "github",
                        "huggingface",
                    ]
                )
            )
            apply_args(args, state_manager.init_item)
        finally:
            os.chdir(previous_cwd)

        from facefusion import face_store
        from facefusion.face_creator import get_static_faces
        from facefusion.processors.modules.face_swapper import core as face_swapper_core
        from facefusion.vision import read_static_image

        self._face_store = face_store
        self._get_static_faces = get_static_faces
        self._swap_face = face_swapper_core.swap_face
        self._read_static_image = read_static_image
        self._source_frames = {
            "SRC_BLONDE": self._read_static_image(str(self.identity_root / "02_TARGET_BLONDE.png")),
            "SRC_DARK": self._read_static_image(str(self.identity_root / "03_TARGET_DARK.png")),
        }
        self._source_faces = {
            track: self._largest_face(self._detect(frame), track)
            for track, frame in self._source_frames.items()
        }
        self._face_store.clear_faces()
        self.pixel_boost = pixel_boost
        self.face_swapper_weight = face_swapper_weight

    @staticmethod
    def _largest_face(faces: list[Any], label: str) -> Any:
        if not faces:
            raise RuntimeError(f"No face detected in {label}")
        return max(
            faces,
            key=lambda face: float(
                (face.bounding_box[2] - face.bounding_box[0])
                * (face.bounding_box[3] - face.bounding_box[1])
            ),
        )

    def _detect(self, frame: np.ndarray) -> list[Any]:
        return list(self._get_static_faces([frame]))

    @staticmethod
    def _candidate(face: Any, width: int, height: int) -> dict[str, Any]:
        x1, y1, x2, y2 = (float(value) for value in face.bounding_box)
        return {
            "face": face,
            "embedding": np.asarray(face.embedding_norm, dtype=np.float32),
            "center": (((x1 + x2) / 2) / width, ((y1 + y2) / 2) / height),
            "bbox": [x1, y1, x2, y2],
        }

    def _initialize_tracks(
        self, frame: np.ndarray
    ) -> tuple[dict[str, np.ndarray], dict[str, tuple[float, float]]]:
        height, width = frame.shape[:2]
        faces = sorted(self._detect(frame), key=lambda face: float(face.bounding_box[0]))[:3]
        if len(faces) < 3:
            raise RuntimeError(f"Calibration frame must expose three human faces; found {len(faces)}")
        templates = {
            track: np.asarray(face.embedding_norm, dtype=np.float32)
            for track, face in zip(TRACK_ORDER, faces, strict=True)
        }
        previous_centers = {
            track: self._candidate(face, width, height)["center"]
            for track, face in zip(TRACK_ORDER, faces, strict=True)
        }
        return templates, previous_centers

    def _process_frame(
        self,
        frame: np.ndarray,
        *,
        templates: dict[str, np.ndarray],
        previous_centers: dict[str, tuple[float, float]],
    ) -> tuple[np.ndarray, dict[str, Any]]:
        height, width = frame.shape[:2]
        candidates = [self._candidate(face, width, height) for face in self._detect(frame)]
        assignment = assign_unique_tracks(
            templates,
            candidates,
            previous_centers=previous_centers,
            minimum_score=0.20,
        )
        output = frame.copy()
        swapped_tracks: list[str] = []
        for track in TRACK_ORDER:
            candidate_index = assignment.get(track)
            if candidate_index is None:
                continue
            candidate = candidates[candidate_index]
            previous_centers[track] = candidate["center"]
            if track in SWAP_TRACKS:
                output = self._swap_face(
                    self._source_faces[track],
                    candidate["face"],
                    self._source_frames[track],
                    output,
                )
                swapped_tracks.append(track)
        self._face_store.clear_faces()
        return output, {
            "assignment": assignment,
            "swapped_tracks": swapped_tracks,
            "candidate_count": len(candidates),
        }

    def process_calibration_frame(self, frame: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        templates, previous_centers = self._initialize_tracks(frame)
        output, receipt = self._process_frame(
            frame,
            templates=templates,
            previous_centers=previous_centers,
        )
        return output, receipt

    def complete_video(self, input_path: Path, output_path: Path) -> dict[str, Any]:
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
        templates, previous_centers = self._initialize_tracks(first_frame)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_ffmpeg_command(
            width=width,
            height=height,
            fps=fps,
            input_path=input_path,
            output_path=output_path,
        )
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        if encoder.stdin is None:
            raise RuntimeError("Cannot open FFmpeg input pipe")

        swap_counts = {track: 0 for track in SWAP_TRACKS}
        unassigned = {track: 0 for track in TRACK_ORDER}
        frames_processed = 0

        def write_frame(frame: np.ndarray) -> None:
            nonlocal frames_processed
            output, receipt = self._process_frame(
                frame,
                templates=templates,
                previous_centers=previous_centers,
            )
            assignment = receipt["assignment"]
            for track in TRACK_ORDER:
                if track not in assignment:
                    unassigned[track] += 1
            for track in receipt["swapped_tracks"]:
                swap_counts[track] += 1
            encoder.stdin.write(output.tobytes())
            frames_processed += 1

        try:
            write_frame(first_frame)
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                write_frame(frame)
        finally:
            capture.release()
            encoder.stdin.close()
        stderr = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
        return_code = encoder.wait()
        if return_code != 0:
            raise RuntimeError(f"FFmpeg failed ({return_code}): {stderr}")
        if frames_processed != expected_frames:
            raise RuntimeError(
                f"Frame count mismatch: processed {frames_processed}, expected {expected_frames}"
            )

        manifest = {
            "schema_version": "usfr-local-multi-track-completion/v1",
            "backend": "facefusion-hyperswap-1a-256",
            "provider_result": str(input_path),
            "output_video": str(output_path),
            "fps": fps,
            "width": width,
            "height": height,
            "frames_processed": frames_processed,
            "swap_counts": swap_counts,
            "unassigned_frames": unassigned,
            "protected_tracks": ["SRC_MAN", "SRC_ALIEN"],
            "pixel_boost": self.pixel_boost,
            "face_swapper_weight": self.face_swapper_weight,
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
    parser.add_argument("--facefusion-root", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--pixel-boost", default="512x512")
    args = parser.parse_args()
    completion = HyperSwapCompletion(
        facefusion_root=args.facefusion_root,
        identity_root=args.identity_root,
        pixel_boost=args.pixel_boost,
    )
    print(json.dumps(completion.complete_video(args.input, args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
