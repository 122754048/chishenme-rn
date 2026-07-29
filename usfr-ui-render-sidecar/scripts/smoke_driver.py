from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
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


FRAME_COUNT = 24
FPS = 30
WIDTH = 180
HEIGHT = 320
COPY = ["立即购买", "اشتر الآن", "Comprar agora", "Buy now"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_exact_text(values: list[str]) -> None:
    for value in values:
        if not value or "\ufffd" in value or "??" in value:
            raise RuntimeError("multilingual truth contains replacement or placeholder glyphs")


def _write_source_motion(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        FPS,
        (WIDTH, HEIGHT),
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not create the UI motion fixture")
    try:
        for index in range(FRAME_COUNT):
            progress = index / (FRAME_COUNT - 1)
            frame = np.full((HEIGHT, WIDTH, 3), (36, 30, 24), dtype=np.uint8)
            cv2.rectangle(frame, (10, 16), (170, 304), (58, 50, 42), -1)
            center_x = int(48 + 76 * progress)
            center_y = int(145 - 18 * math.sin(progress * math.pi * 2))
            scale = 1.0 + 0.18 * math.sin(progress * math.pi)
            angle = -12 + 24 * progress
            rect = ((center_x, center_y), (70 * scale, 104 * scale), angle)
            points = cv2.boxPoints(rect).astype(np.int32)
            alpha = 0.55 + 0.45 * progress
            overlay = frame.copy()
            cv2.fillConvexPoly(overlay, points, (70, 210, 145))
            cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
            cv2.circle(frame, (center_x, center_y - 20), 16, (205, 225, 245), -1)
            cv2.putText(
                frame,
                "SOURCE UI",
                (32, 286),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (245, 245, 245),
                1,
                cv2.LINE_AA,
            )
            if 15 <= index <= 18:
                radius = 7 + (index - 15) * 5
                cv2.circle(frame, (142, 265), radius, (255, 255, 255), 2)
            writer.write(frame)
    finally:
        writer.release()
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("UI motion fixture was not written")


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,nb_read_frames,duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("FFprobe rejected the smoke output")
    stream = json.loads(result.stdout)["streams"][0]
    if (
        stream.get("codec_name") != "h264"
        or int(stream.get("width") or 0) != WIDTH
        or int(stream.get("height") or 0) != HEIGHT
        or int(stream.get("nb_read_frames") or 0) != FRAME_COUNT
    ):
        raise RuntimeError("smoke output does not match the frozen media contract")
    return stream


def _sample_nonblank(path: Path) -> list[float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError("smoke output cannot be decoded by OpenCV")
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if len(frames) != FRAME_COUNT:
        raise RuntimeError("OpenCV frame count does not match the smoke contract")
    means = [float(np.mean(frames[index])) for index in (0, FRAME_COUNT // 2, FRAME_COUNT - 1)]
    if any(value <= 5.0 for value in means):
        raise RuntimeError("a smoke anchor frame is blank")
    return means


class _FallbackRenderer:
    def __init__(self) -> None:
        self.calls = 0

    def capability_identity(self) -> dict[str, str]:
        return {
            "implementation": "scripts.smoke_driver:_FallbackRenderer",
            "version": "1.0.0",
            "sha256": "f" * 64,
        }

    def __call__(self, source: Path, output: Path, context: Any, **kwargs: Any) -> dict[str, Any]:
        del source, context, kwargs
        self.calls += 1
        return {"video_path": str(output), "fallback": True}


def _interaction_contract() -> dict[str, Any]:
    return {
        "schema_version": "source-ui-interaction/v1",
        "region_id": "ui-smoke-001",
        "source_window_us": {"start": 0, "end_exclusive": 800_000},
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
        "language": {"source": "en", "target": "multilingual", "mode": "localized"},
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


def _truth_and_render_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    truth = {
        "approved_copy": COPY,
        "states": [
            {
                "state_id": "state-001",
                "frame_ms": 0,
                "expected_text": COPY,
                "expected_layout": [
                    {
                        "element_id": f"copy-{index + 1}",
                        "role": "button",
                        "text": text,
                        "bbox": [12, 20 + index * 66, 168, 70 + index * 66],
                        "font_size": 15,
                        "color": "#ffffff",
                        "background_color": "#111827",
                        "text_align": "center",
                    }
                    for index, text in enumerate(COPY)
                ],
            }
        ],
    }
    render_contract = {
        "route": "generated_ui_demo",
        "viewport": [WIDTH, HEIGHT],
        "state_sequence": ["state-001"],
        "source_ui_interaction_contract": _interaction_contract(),
        "language": {"source": "en", "target": "multilingual", "mode": "localized"},
        "text_encoding": {"encoding": "utf-8", "replacement_glyphs_forbidden": True},
    }
    return truth, render_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--skill-root", required=True, type=Path)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    skill_root = args.skill_root.resolve()
    if not (project_root / "sidecar-manifest.json").is_file():
        raise RuntimeError("Sidecar manifest is unavailable")
    manifest = json.loads((project_root / "sidecar-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("cpu_only") is not True:
        raise RuntimeError("Sidecar manifest is not CPU-only")
    if os.environ.get("USFR_UI_RENDER_MODEL_SHA256") != manifest.get("model_sha256"):
        raise RuntimeError("private configuration does not match the Sidecar manifest")

    sys.path.insert(0, str(skill_root))
    from server.remotion_react_ui import ConditionalUiRenderBackend
    from server.ui_sidecar_runtime import OnDemandUiSidecarRenderer
    from server.vision_backends import EvidenceBoundHttpUiRenderer

    runtime_root = project_root / ".runtime"
    smoke_dir = runtime_root / "smoke"
    prior_receipt_path = smoke_dir / "receipt.json"
    if prior_receipt_path.is_file():
        prior = json.loads(prior_receipt_path.read_text(encoding="utf-8"))
        prior_request_sha = str(prior.get("request_sha256") or "")
        if len(prior_request_sha) == 64 and all(char in "0123456789abcdef" for char in prior_request_sha):
            prior_job = (runtime_root / "jobs" / prior_request_sha).resolve()
            if prior_job.parent == (runtime_root / "jobs").resolve() and prior_job.is_dir():
                shutil.rmtree(prior_job)
    if smoke_dir.is_dir():
        shutil.rmtree(smoke_dir)
    smoke_dir.mkdir(parents=True, exist_ok=True)

    source_video = smoke_dir / "source-ui.mp4"
    target_image = project_root / "fixtures" / "target-ui.png"
    output_video = smoke_dir / "output-ui.mp4"
    _write_source_motion(source_video)
    if not target_image.is_file():
        raise RuntimeError("target UI fixture is unavailable")
    _validate_exact_text(COPY)

    endpoint = os.environ["USFR_UI_RENDER_ENDPOINT"]
    delegate = EvidenceBoundHttpUiRenderer(
        endpoint=endpoint,
        model_id=os.environ["USFR_UI_RENDER_MODEL_ID"],
        model_sha256=os.environ["USFR_UI_RENDER_MODEL_SHA256"],
        api_token_env="USFR_UI_RENDER_API_TOKEN",
        timeout_seconds=float(os.environ.get("USFR_UI_RENDER_TIMEOUT_SECONDS", "300")),
        production=False,
    )
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is unavailable")
    wrapper = OnDemandUiSidecarRenderer(
        renderer=delegate,
        command=[npm, "run", "start", "--silent"],
        project_dir=project_root,
        startup_timeout_seconds=float(os.environ.get("USFR_UI_SIDECAR_STARTUP_TIMEOUT_SECONDS", "90")),
        startup_lock_path=runtime_root / "sidecar-startup.lock",
    )
    if wrapper.process is not None or wrapper.check_ready():
        raise RuntimeError("Sidecar must not be running before an eligible UI call")

    truth, render_contract = _truth_and_render_contract()
    fallback = _FallbackRenderer()
    conditional = ConditionalUiRenderBackend(
        fallback_renderer=fallback,
        remotion_renderer=wrapper,
        capabilities={},
    )
    for route in ([], [{"region_type": "opaque_ui_demo", "region_id": "opaque-001"}]):
        context = SimpleNamespace(timeline_regions=route)
        conditional(target_image, smoke_dir / "bypass.mp4", context, truth=truth, render_contract=render_contract)
        if wrapper.process is not None or wrapper.check_ready():
            raise RuntimeError("a bypass route started the UI Sidecar")
    if fallback.calls != 2:
        raise RuntimeError("bypass routes did not remain on the existing renderer")

    @contextmanager
    def materialize_slot(slot_id: str):
        if slot_id != "source_video":
            raise RuntimeError("smoke materializer received an unexpected slot")
        yield SimpleNamespace(path=source_video)

    context = SimpleNamespace(materialize_slot=materialize_slot, work_dir=smoke_dir)
    result = wrapper(
        target_image,
        output_video,
        context,
        truth=truth,
        render_contract=render_contract,
    )
    decision = result.get("ui_renderer_decision") or {}
    if decision.get("started_process") is not True or wrapper.process is None:
        raise RuntimeError("eligible generated UI did not start exactly one Sidecar process")
    if result.get("state_sequence") != ["state-001"]:
        raise RuntimeError("returned UI state order is incorrect")
    if result.get("ui_truth_card") != truth:
        raise RuntimeError("returned multilingual truth does not match the exact input")

    probe = _probe(output_video)
    sample_means = _sample_nonblank(output_video)
    evidence = result["backend_evidence"]
    request_sha = evidence["request_sha256"]
    server_response_path = runtime_root / "jobs" / request_sha / "response.json"
    server_response = json.loads(server_response_path.read_text(encoding="utf-8"))
    if server_response.get("video_sha256") != _sha256(output_video):
        raise RuntimeError("Sidecar receipt is not bound to the final smoke output")
    if server_response.get("receipt", {}).get("cpu_only") is not True:
        raise RuntimeError("Sidecar receipt does not prove CPU-only execution")
    if server_response.get("receipt", {}).get("cache_hit") is not False:
        raise RuntimeError("smoke must execute one fresh render")

    idle_deadline = time.monotonic() + 20
    while time.monotonic() < idle_deadline:
        poll = getattr(wrapper.process, "poll", None)
        if callable(poll) and poll() is not None and not wrapper.check_ready():
            break
        time.sleep(0.5)
    else:
        raise RuntimeError("Sidecar did not exit after the smoke idle timeout")

    receipt = {
        "schema_version": "usfr-ui-sidecar-smoke/v1",
        "request_sha256": request_sha,
        "response_sha256": evidence["response_sha256"],
        "source_ui_sha256": evidence["source_sha256"],
        "source_motion_sha256": _sha256(source_video),
        "output_path": str(output_video),
        "output_sha256": _sha256(output_video),
        "motion_track_sha256": server_response["motion_track_sha256"],
        "model_id": manifest["model_id"],
        "model_sha256": manifest["model_sha256"],
        "probe": probe,
        "anchor_frame_means": sample_means,
        "timing": server_response["receipt"],
        "cpu_only": True,
        "automatic_retry": False,
        "process_started_on_generated_ui": True,
        "bypass_routes_started_process": False,
        "idle_exit_verified": True,
        "multilingual_truth": COPY,
    }
    prior_receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output_path": str(output_video), "receipt_path": str(prior_receipt_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
