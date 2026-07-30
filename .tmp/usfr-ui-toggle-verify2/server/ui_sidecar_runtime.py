"""On-demand lifecycle wrapper for the independent UI render Sidecar."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Sequence


class UiSidecarStartupError(RuntimeError):
    pass


def _sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OnDemandUiSidecarRenderer:
    """Start one local Sidecar process only when generated UI actually renders."""

    implementation = "server.ui_sidecar_runtime:OnDemandUiSidecarRenderer"
    version = "1.0.0"

    def __init__(
        self,
        *,
        renderer: Any,
        command: Sequence[str],
        project_dir: Path,
        startup_timeout_seconds: float = 90.0,
        startup_lock_path: Path | None = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        poll_interval_seconds: float = 0.2,
    ) -> None:
        if not callable(renderer) or not callable(getattr(renderer, "check_ready", None)):
            raise ValueError("UI Sidecar renderer must be callable and expose check_ready()")
        if not callable(getattr(renderer, "capability_identity", None)):
            raise ValueError("UI Sidecar renderer must expose capability_identity()")
        normalized_command = tuple(str(item) for item in command if str(item))
        if not normalized_command:
            raise ValueError("UI Sidecar start command is required")
        if not 0 < float(startup_timeout_seconds) <= 600:
            raise ValueError("UI Sidecar startup timeout must be in (0, 600]")
        if not 0 < float(poll_interval_seconds) <= 5:
            raise ValueError("UI Sidecar poll interval must be in (0, 5]")
        self.renderer = renderer
        self.command = normalized_command
        self.project_dir = Path(project_dir).resolve()
        self.startup_timeout_seconds = float(startup_timeout_seconds)
        self.startup_lock_path = Path(
            startup_lock_path or self.project_dir / ".runtime" / "sidecar-startup.lock"
        ).resolve()
        self.process_factory = process_factory
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._thread_lock = threading.Lock()
        self._process: Any | None = None
        self._delegate_identity = dict(renderer.capability_identity())
        identity = {
            "implementation": self.implementation,
            "version": self.version,
            "delegate": self._delegate_identity,
            "command": list(self.command),
        }
        self._identity = {**identity, "sha256": _sha256(identity)}

    @property
    def process(self) -> Any | None:
        return self._process

    def capability_identity(self) -> Mapping[str, Any]:
        return dict(self._identity)

    def check_ready(self) -> bool:
        return bool(self.renderer.check_ready())

    def _create_startup_lock(self) -> int:
        self.startup_lock_path.parent.mkdir(parents=True, exist_ok=True)
        return os.open(
            self.startup_lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )

    def _release_startup_lock(self, descriptor: int | None) -> None:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            self.startup_lock_path.unlink()
        except FileNotFoundError:
            pass

    def _launch(self) -> Any:
        runtime_dir = self.project_dir / ".runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        stdout = (runtime_dir / "sidecar.out.log").open("ab")
        stderr = (runtime_dir / "sidecar.err.log").open("ab")
        kwargs: dict[str, Any] = {
            "cwd": str(self.project_dir),
            "env": os.environ.copy(),
            "stdin": subprocess.DEVNULL,
            "stdout": stdout,
            "stderr": stderr,
            "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            return self.process_factory(list(self.command), **kwargs)
        except Exception:
            stdout.close()
            stderr.close()
            raise

    def _ensure_ready(self) -> bool:
        if self.check_ready():
            return False
        with self._thread_lock:
            if self.check_ready():
                return False
            deadline = time.monotonic() + self.startup_timeout_seconds
            descriptor: int | None = None
            while descriptor is None:
                try:
                    descriptor = self._create_startup_lock()
                    os.write(descriptor, str(os.getpid()).encode("ascii"))
                except FileExistsError:
                    if self.check_ready():
                        return False
                    if time.monotonic() >= deadline:
                        try:
                            age = time.time() - self.startup_lock_path.stat().st_mtime
                        except FileNotFoundError:
                            continue
                        if age >= self.startup_timeout_seconds:
                            try:
                                self.startup_lock_path.unlink()
                            except FileNotFoundError:
                                pass
                            continue
                        raise UiSidecarStartupError("UI Sidecar startup lock did not become ready")
                    time.sleep(self.poll_interval_seconds)
            try:
                if self.check_ready():
                    return False
                try:
                    self._process = self._launch()
                except Exception as exc:
                    raise UiSidecarStartupError("UI Sidecar process could not start") from exc
                while time.monotonic() < deadline:
                    if self.check_ready():
                        return True
                    poll = getattr(self._process, "poll", None)
                    if callable(poll) and poll() is not None:
                        raise UiSidecarStartupError("UI Sidecar process exited before readiness")
                    time.sleep(self.poll_interval_seconds)
                raise UiSidecarStartupError("UI Sidecar did not become ready before timeout")
            finally:
                self._release_startup_lock(descriptor)

    def __call__(self, source: Path, output: Path, context: Any, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
        started = self._ensure_ready()
        result = self.renderer(source, output, context, *args, **kwargs)
        if not isinstance(result, Mapping):
            raise ValueError("UI Sidecar renderer must return an object")
        response = dict(result)
        response["ui_renderer_decision"] = {
            "backend": "remotion_react_ui",
            "enabled": True,
            "reason": "eligible_generated_ui_started_on_demand",
            "renderer_identity": self.capability_identity(),
            "started_process": started,
        }
        return response


__all__ = ["OnDemandUiSidecarRenderer", "UiSidecarStartupError"]
