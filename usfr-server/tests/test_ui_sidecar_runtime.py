from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

from server.ui_sidecar_runtime import OnDemandUiSidecarRenderer


class _Process:
    def poll(self):
        return None


class _Delegate:
    def __init__(self) -> None:
        self.ready = False
        self.calls = 0
        self._lock = threading.Lock()

    def check_ready(self) -> bool:
        return self.ready

    def capability_identity(self) -> dict[str, str]:
        return {
            "implementation": "tests:_Delegate",
            "version": "1",
            "sha256": "d" * 64,
        }

    def __call__(self, source, output, context, **kwargs):
        del source, context, kwargs
        with self._lock:
            self.calls += 1
        Path(output).write_bytes(b"video")
        return {"video_path": str(output)}


def _wrapper(tmp_path: Path):
    delegate = _Delegate()
    starts: list[tuple] = []

    def process_factory(command, **kwargs):
        starts.append((tuple(command), kwargs))
        delegate.ready = True
        return _Process()

    wrapper = OnDemandUiSidecarRenderer(
        renderer=delegate,
        command=["node", "server.js"],
        project_dir=tmp_path,
        startup_timeout_seconds=2,
        startup_lock_path=tmp_path / "startup.lock",
        process_factory=process_factory,
        poll_interval_seconds=0.01,
    )
    return wrapper, delegate, starts


def test_constructing_and_checking_wrapper_do_not_start_process(tmp_path: Path) -> None:
    wrapper, _delegate, starts = _wrapper(tmp_path)

    assert starts == []
    assert wrapper.check_ready() is False
    assert starts == []


def test_first_ui_call_starts_once_and_concurrent_calls_share_process(tmp_path: Path) -> None:
    wrapper, delegate, starts = _wrapper(tmp_path)

    def render(index: int):
        return wrapper(
            tmp_path / "target.png",
            tmp_path / f"output-{index}.mp4",
            object(),
            truth={"states": []},
            render_contract={"state_sequence": []},
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(render, range(4)))

    assert len(starts) == 1
    assert delegate.calls == 4
    assert all(result["ui_renderer_decision"]["backend"] == "remotion_react_ui" for result in results)
    assert sum(result["ui_renderer_decision"]["started_process"] is True for result in results) == 1


def test_ready_sidecar_is_used_without_launching_another_process(tmp_path: Path) -> None:
    wrapper, delegate, starts = _wrapper(tmp_path)
    delegate.ready = True

    result = wrapper(tmp_path / "target.png", tmp_path / "output.mp4", object())

    assert starts == []
    assert result["ui_renderer_decision"]["started_process"] is False
