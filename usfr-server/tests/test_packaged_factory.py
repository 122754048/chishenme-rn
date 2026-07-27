from __future__ import annotations

import fakeredis
from fastapi import FastAPI
import importlib.util
from pathlib import Path
import pytest

from server.remotion_react_ui import ConditionalUiRenderBackend

from server.deployment_bootstrap import DeploymentRuntime

from test_object_lifecycle import MemoryS3


ROOT = Path(__file__).resolve().parents[1]


def _factory_api():
    path = ROOT / "server" / "packaged_factory.py"
    assert path.is_file(), "packaged deployment factory is missing"
    spec = importlib.util.spec_from_file_location("server.packaged_factory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PackagedFactoryError, module.build_runtime


class HealthyMemoryS3(MemoryS3):
    def head_bucket(self, *, Bucket: str):
        return {"Bucket": Bucket}


def test_packaged_factory_builds_complete_readiness_only_runtime(monkeypatch) -> None:
    _error, build_runtime = _factory_api()
    monkeypatch.setenv("USFR_PROFILE_MODE", "shadow")
    runtime = build_runtime(
        redis_client=fakeredis.FakeRedis(decode_responses=False),
        s3_client=HealthyMemoryS3(),
        bucket="usfr-test",
        capability_secret=b"s" * 32,
        readiness_only=True,
    )
    assert isinstance(runtime, DeploymentRuntime)
    assert isinstance(runtime.service, FastAPI)
    assert runtime.worker_manager.allow_local_paths is False
    assert runtime.worker_manager.profile_bundle_resolver.immutable is True
    assert set(runtime.readiness_checks) == {
        "redis", "object_store", "bundle", "models", "capabilities", "provider"
    }
    assert all(check() is True for check in runtime.readiness_checks.values())


def test_packaged_factory_rejects_missing_real_ports_by_default(monkeypatch) -> None:
    PackagedFactoryError, build_runtime = _factory_api()
    monkeypatch.setenv("USFR_PROFILE_MODE", "shadow")
    with pytest.raises(PackagedFactoryError, match="port factory"):
        build_runtime(
            redis_client=fakeredis.FakeRedis(decode_responses=False),
            s3_client=HealthyMemoryS3(),
            bucket="usfr-test",
            capability_secret=b"s" * 32,
            readiness_only=False,
        )


def test_readiness_only_stage_ports_fail_if_work_is_accidentally_dispatched(monkeypatch) -> None:
    PackagedFactoryError, build_runtime = _factory_api()
    monkeypatch.setenv("USFR_PROFILE_MODE", "shadow")
    runtime = build_runtime(
        redis_client=fakeredis.FakeRedis(decode_responses=False),
        s3_client=HealthyMemoryS3(),
        bucket="usfr-test",
        capability_secret=b"s" * 32,
        readiness_only=True,
    )
    port = runtime.worker_manager.stage_ports["run_qc"]
    with pytest.raises(PackagedFactoryError, match="readiness-only"):
        port.run(context=None)


def test_port_factory_wires_only_an_explicit_remotion_candidate_into_the_ui_renderer() -> None:
    path = ROOT / "server" / "packaged_factory.py"
    spec = importlib.util.spec_from_file_location("server.packaged_factory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Renderer:
        def __init__(self, name: str, digest: str) -> None:
            self.name = name
            self.digest = digest

        def capability_identity(self) -> dict[str, str]:
            return {"implementation": f"tests:{self.name}", "version": "1", "sha256": self.digest}

        def __call__(self, *_args, **_kwargs):
            return {"video_path": "unused.mp4"}

    class UiAdapter:
        def __init__(self, backend):
            self.render_backend = backend

        def replace_render_backend(self, backend) -> None:
            self.render_backend = backend

    fallback = Renderer("ffmpeg", "f" * 64)
    remotion = Renderer("remotion", "d" * 64)
    adapter = UiAdapter(fallback)
    module._configure_optional_remotion_ui_adapter(
        {
            "remotion_react_ui": {
                "renderer": remotion,
                "capabilities": {
                    "remotion_react_ui": {
                        "status": "enabled",
                        "domain": "programmable_overlays",
                        "activation_report_sha256": "a" * 64,
                        **remotion.capability_identity(),
                    }
                },
            }
        },
        {"ocr_ui_renderer": adapter},
    )

    assert isinstance(adapter.render_backend, ConditionalUiRenderBackend)
    assert adapter.render_backend.fallback_renderer is fallback
    assert adapter.render_backend.remotion_renderer is remotion
