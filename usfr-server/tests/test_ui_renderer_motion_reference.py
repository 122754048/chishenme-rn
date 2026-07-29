from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace

from PIL import Image

from server.vision_backends import EvidenceBoundHttpUiRenderer


@contextmanager
def _json_server(response_factory):
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(payload)
            encoded = json.dumps(response_factory(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1/render", requests
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _video(path: Path, *, frames: int, fps: int, color: str) -> Path:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            f"color=c={color}:s=64x64:r={fps}:d={frames / fps}",
            "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return path


def _frame_count(path: Path) -> int:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames", "-of", "default=nk=1:nw=1", str(path),
        ],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return int(result.stdout.strip())


def test_http_ui_renderer_materializes_only_the_frozen_ui_interval() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "target.png"
        Image.new("RGB", (64, 64), "green").save(target)
        source_video = _video(root / "source.mp4", frames=10, fps=10, color="blue")
        sidecar_video = _video(root / "sidecar.mp4", frames=4, fps=10, color="red")
        sidecar_bytes = sidecar_video.read_bytes()
        interaction = {
            "schema_version": "source-ui-interaction/v1",
            "region_id": "ui-1",
            "source_window_us": {"start": 200_000, "end_exclusive": 600_000},
            "frame_window": {"start": 2, "end_exclusive": 6},
            "source_fps": {"num": 10, "den": 1},
            "display_viewport": [64, 64],
            "ui_roi": {"x": 4, "y": 4, "width": 56, "height": 56, "coordinate_space": "display_pixels"},
            "language": {"source": "en", "target": "pt", "mode": "localized"},
            "text_encoding": {"encoding": "utf-8", "replacement_glyphs_forbidden": True},
            "motion": {
                "capture_scope": "ui_roi_only",
                "track_policy": "source_frame_locked",
                "supported_actions": ["drag", "scroll", "bounce", "scale", "rotate", "opacity", "tap"],
            },
            "validation": {"mode": "basic_anchor_only", "automatic_retry": False, "anchor_frames": [2, 5]},
        }
        truth = {
            "approved_copy": ["Comprar"],
            "states": [{"state_id": "state-001", "frame_ms": 0, "expected_text": ["Comprar"], "expected_layout": []}],
        }
        render_contract = {
            "viewport": [64, 64],
            "state_sequence": ["state-001"],
            "source_ui_interaction_contract": interaction,
        }

        @contextmanager
        def materialize_slot(slot_id: str):
            assert slot_id == "source_video"
            yield SimpleNamespace(path=source_video)

        context = SimpleNamespace(materialize_slot=materialize_slot, work_dir=root)

        def response(payload: dict) -> dict:
            return {
                "schema_version": "usfr-ui-render-evidence/v1",
                "request_sha256": payload["request_sha256"],
                "source_sha256": payload["source_sha256"],
                "ui_truth_card": payload["ui_truth_card"],
                "ui_render_contract": payload["ui_render_contract"],
                "video_base64": base64.b64encode(sidecar_bytes).decode("ascii"),
                "video_sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
                "state_sequence": ["state-001"],
                "motion_track_sha256": "4" * 64,
                "model": {"id": "ui-model", "sha256": "3" * 64},
            }

        with _json_server(response) as (endpoint, requests):
            renderer = EvidenceBoundHttpUiRenderer(
                endpoint=endpoint,
                model_id="ui-model",
                model_sha256="3" * 64,
                production=False,
            )
            output = root / "output.mp4"
            renderer(target, output, context, truth=truth, render_contract=render_contract)

        assert output.read_bytes() == sidecar_bytes
        assert len(requests) == 1
        motion = requests[0]["motion_reference"]
        motion_bytes = base64.b64decode(motion["video_base64"], validate=True)
        assert hashlib.sha256(motion_bytes).hexdigest() == motion["sha256"]
        assert motion["source_ui_interaction_contract"] == interaction
        motion_path = root / "captured-motion.mp4"
        motion_path.write_bytes(motion_bytes)
        assert _frame_count(motion_path) == 4
