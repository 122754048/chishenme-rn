#!/usr/bin/env python3
"""Swap one detected presenter face per decoded source frame with pixel-lock QC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from insightface import model_zoo


PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"]
INSIGHT_ROOT = Path(r"E:\AI\Comfyui_mi\ComfyUI\models\insightface")
SWAPPER_PATH = INSIGHT_ROOT / "inswapper_128.fp16.onnx"


def largest_face(faces: list[Any], label: str) -> Any:
    if not faces:
        raise RuntimeError(f"No face detected in {label}")
    return max(faces, key=lambda face: float((face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])))


def face_mask(shape: tuple[int, int], face: Any) -> np.ndarray:
    height, width = shape
    x1, y1, x2, y2 = (float(value) for value in face.bbox)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    # Include the complete feathered edge produced by the swapper while keeping
    # the authorised region limited to the face and immediate hairline.
    axes = (max(1, round((x2 - x1) * 1.08)), max(1, round((y2 - y1) * 1.08)))
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(mask, (round(cx), round(cy)), axes, 0, 0, 360, 255, -1)
    return cv2.GaussianBlur(mask, (0, 0), 2.0)


def process(app: FaceAnalysis, swapper: Any, source_face: Any, input_path: Path, output_dir: Path) -> dict[str, Any]:
    source = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError(f"Cannot decode {input_path}")
    target_face = largest_face(app.get(source), input_path.name)
    output = swapper.get(source, target_face, source_face, paste_back=True)
    if output is None:
        raise RuntimeError(f"Face swap returned no image for {input_path.name}")
    mask = face_mask(source.shape[:2], target_face)
    changed = np.max(np.abs(output.astype(np.int16) - source.astype(np.int16)), axis=2) > 2
    permitted = mask > 2
    outside_changed = int(np.count_nonzero(changed & ~permitted))
    changed_count = int(np.count_nonzero(changed))
    if outside_changed:
        raise RuntimeError(f"Pixel-lock failure in {input_path.name}: {outside_changed} changed pixels outside authorised mask")
    stem = input_path.stem
    image_path = output_dir / f"{stem}.png"
    mask_path = output_dir / f"{stem}.mask.png"
    if not cv2.imwrite(str(image_path), output):
        raise RuntimeError(f"Cannot write {image_path}")
    if not cv2.imwrite(str(mask_path), mask):
        raise RuntimeError(f"Cannot write {mask_path}")
    return {
        "source_frame": str(input_path),
        "replacement_frame": str(image_path),
        "mask": str(mask_path),
        "target_bbox": [round(float(value), 2) for value in target_face.bbox],
        "changed_pixels": changed_count,
        "outside_mask_changed_pixels": outside_changed,
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    if not SWAPPER_PATH.is_file():
        raise RuntimeError(f"Missing swapper model: {SWAPPER_PATH}")
    reference = cv2.imread(str(args.reference), cv2.IMREAD_COLOR)
    if reference is None:
        raise RuntimeError(f"Cannot decode reference image: {args.reference}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    app = FaceAnalysis(name="buffalo_l", root=str(INSIGHT_ROOT), providers=PROVIDERS)
    app.prepare(ctx_id=0, det_size=(640, 640))
    source_face = largest_face(app.get(reference), args.reference.name)
    swapper = model_zoo.get_model(str(SWAPPER_PATH), providers=PROVIDERS)
    records = [process(app, swapper, source_face, input_path, args.output_dir) for input_path in args.inputs]
    manifest = {"contract": "frame-locked-character-swap/v1", "reference": str(args.reference), "records": records}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
