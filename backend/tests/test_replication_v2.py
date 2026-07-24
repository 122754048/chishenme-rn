import os
from pathlib import Path
import sys
import types
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.replication_v2 as replication_v2
from app.replication_v2 import build_replication_app, load_runtime_dependencies


SKILL_ROOT = Path(__file__).resolve().parents[2] / "usfr-server"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))


def test_default_skill_root_is_the_repository_owned_usfr_server():
    assert replication_v2._skill_root() == Path(__file__).resolve().parents[2] / "usfr-server"


class _DurableJobStore:
    def get_job(self, _job_id):
        return None


class _DurableObjectStore:
    pass


class _StageDriver:
    def enqueue_next(self, _job_id):
        return None


def test_standard_usfr_adapter_passes_only_current_ephemeral_runtime_dependencies():
    job_store = _DurableJobStore()
    object_store = _DurableObjectStore()
    stage_driver = _StageDriver()
    mounted = FastAPI()

    with patch("server.fastapi_router.create_app", return_value=mounted) as create_app:
        result = build_replication_app(
            job_store=job_store,
            object_store=object_store,
            stage_driver=stage_driver,
            capability_secret=b"x" * 32,
        )

    assert result is mounted
    assert create_app.call_args.kwargs["job_store"] is job_store
    assert create_app.call_args.kwargs["object_store"] is object_store
    assert create_app.call_args.kwargs["stage_driver"] is stage_driver


def test_production_adapter_requires_standard_durable_runtime():
    with patch("app.replication_v2.settings.env", "production"):
        with pytest.raises(RuntimeError, match="job_store"):
            build_replication_app()


def test_runtime_factory_can_supply_standard_ephemeral_dependencies():
    job_store = _DurableJobStore()
    object_store = _DurableObjectStore()
    stage_driver = _StageDriver()
    runtime_module = types.ModuleType("test_usfr_runtime")
    runtime_module.build_runtime = lambda: {
        "job_store": job_store,
        "object_store": object_store,
        "stage_driver": stage_driver,
        "capability_secret": b"x" * 32,
    }
    mounted = FastAPI()

    with (
        patch("app.replication_v2.settings.env", "production"),
        patch.dict(os.environ, {"REPLICATION_RUNTIME_FACTORY": "test_usfr_runtime:build_runtime"}),
        patch.dict(sys.modules, {"test_usfr_runtime": runtime_module}),
        patch("server.fastapi_router.create_app", return_value=mounted) as create_app,
    ):
        assert build_replication_app() is mounted

    assert create_app.call_args.kwargs["job_store"] is job_store


def test_development_without_durable_runtime_fails_closed_without_a_local_queue():
    app = build_replication_app()

    response = TestClient(app).post("/api/v1/jobs", json={"slots": {"source_video": "source.mp4"}})

    assert response.status_code == 503
    assert response.json()["code"] == "USFR_RUNTIME_NOT_CONFIGURED"


def test_runtime_factory_keeps_commercial_batch_adapter_outside_skill_create_app_contract():
    job_store = _DurableJobStore()
    object_store = _DurableObjectStore()
    stage_driver = _StageDriver()
    commercial_batch_runtime = object()
    runtime_module = types.ModuleType("test_usfr_commercial_batch_runtime")
    runtime_module.build_runtime = lambda: {
        "job_store": job_store,
        "object_store": object_store,
        "stage_driver": stage_driver,
        "capability_secret": b"x" * 32,
        "commercial_batch_runtime": commercial_batch_runtime,
    }
    mounted = FastAPI()

    with (
        patch.dict(os.environ, {"REPLICATION_RUNTIME_FACTORY": "test_usfr_commercial_batch_runtime:build_runtime"}),
        patch.dict(sys.modules, {"test_usfr_commercial_batch_runtime": runtime_module}),
        patch("server.fastapi_router.create_app", return_value=mounted) as create_app,
    ):
        dependencies = load_runtime_dependencies()
        assert dependencies["commercial_batch_runtime"] is commercial_batch_runtime
        assert build_replication_app() is mounted

    assert "commercial_batch_runtime" not in create_app.call_args.kwargs
