from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from local_hyperswap_completion import HyperSwapCompletion, build_ffmpeg_command


ROOT = Path(__file__).resolve().parent
FRAME = ROOT / "four_person_once" / "diagnostics_v1" / "provider_0.5s.png"
FACEFUSION_ROOT = ROOT.parent / "facefusion_research"
INSIGHT_ROOT = Path(r"E:\AI\Comfyui_mi\ComfyUI\models\insightface")


def _sorted_faces(app: FaceAnalysis, image: np.ndarray):
    return sorted(app.get(image), key=lambda face: float(face.bbox[0]))


def test_hyperswap_replaces_two_bound_tracks_and_preserves_protected_man() -> None:
    frame = cv2.imread(str(FRAME), cv2.IMREAD_COLOR)
    assert frame is not None

    completion = HyperSwapCompletion(
        facefusion_root=FACEFUSION_ROOT,
        identity_root=ROOT / "identity_v3",
        pixel_boost="512x512",
    )
    output, receipt = completion.process_calibration_frame(frame)

    evaluator = FaceAnalysis(
        name="buffalo_l",
        root=str(INSIGHT_ROOT),
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    evaluator.prepare(ctx_id=0, det_size=(640, 640), det_thresh=0.20)
    before = _sorted_faces(evaluator, frame)
    after = _sorted_faces(evaluator, output)
    blonde_ref = _sorted_faces(
        evaluator,
        cv2.imread(str(ROOT / "identity_v3" / "02_TARGET_BLONDE.png"), cv2.IMREAD_COLOR),
    )[0]
    dark_ref = _sorted_faces(
        evaluator,
        cv2.imread(str(ROOT / "identity_v3" / "03_TARGET_DARK.png"), cv2.IMREAD_COLOR),
    )[0]

    assert receipt["assignment"] == {"SRC_BLONDE": 0, "SRC_MAN": 1, "SRC_DARK": 2}
    assert float(np.dot(after[0].normed_embedding, blonde_ref.normed_embedding)) >= 0.70
    assert float(np.dot(after[2].normed_embedding, dark_ref.normed_embedding)) >= 0.70
    assert float(np.dot(before[1].normed_embedding, after[1].normed_embedding)) >= 0.99


def test_ffmpeg_command_preserves_full_source_audio() -> None:
    command = build_ffmpeg_command(
        width=720,
        height=1280,
        fps=24.0,
        input_path=Path("provider.mp4"),
        output_path=Path("completed.mp4"),
    )

    assert "-c:a" in command
    assert command[command.index("-c:a") + 1] == "copy"
    assert "-shortest" not in command
