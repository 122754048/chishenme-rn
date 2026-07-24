from __future__ import annotations

from dataclasses import dataclass, replace
import sys
import types
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from server.capabilities import REQUIRED_CAPABILITIES
from server.job_models import JobSnapshot, StageCheckpoint, WorkMessage
from server.redis_streams import WorkDelivery


READINESS_NAMES = {
    "redis",
    "object_store",
    "bundle",
    "models",
    "capabilities",
    "provider",
}


class _ImmutableBundle:
    immutable = True


class _JobStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.snapshot = JobSnapshot.new(
            job_id="job-1",
            capability_token_hash="a" * 64,
            slots_manifest={"admission": {"can_proceed": True}},
            expires_at_ms=9_999_999_999_999,
        )
        self.fail_complete = False

    def get_job(self, job_id: str) -> JobSnapshot | None:
        self.events.append("get_job")
        return self.snapshot if job_id == self.snapshot.job_id else None

    def claim_stage(
        self,
        *,
        job_id: str,
        stage: str,
        dedupe_key: str,
        owner: str,
        ttl_seconds: int,
    ) -> StageCheckpoint:
        del job_id, ttl_seconds
        self.events.append("claim_stage")
        return StageCheckpoint(stage, dedupe_key, "CLAIMED", 1, owner=owner)

    def complete_stage(
        self,
        *,
        job_id: str,
        stage: str,
        dedupe_key: str,
        owner: str,
        output_artifact_ids: tuple[str, ...],
        ttl_seconds: int,
    ) -> StageCheckpoint:
        del job_id, ttl_seconds
        self.events.append("complete_stage")
        if self.fail_complete:
            raise RuntimeError("checkpoint commit failed")
        return StageCheckpoint(
            stage,
            dedupe_key,
            "SUCCEEDED",
            1,
            output_artifact_ids=output_artifact_ids,
            owner=owner,
        )


class _WorkQueue:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.delivery = WorkDelivery(
            message_id="1-0",
            message=WorkMessage(
                job_id="job-1",
                stage="probe_source",
                expected_version=1,
                dedupe_key="d" * 64,
            ),
        )
        self.reclaimed: WorkDelivery | None = None
        self.acked: list[str] = []

    def reclaim(
        self,
        *,
        consumer: str,
        min_idle_ms: int,
        count: int,
    ) -> tuple[WorkDelivery, ...]:
        del consumer, min_idle_ms, count
        self.events.append("reclaim")
        delivery, self.reclaimed = self.reclaimed, None
        return (delivery,) if delivery is not None else ()

    def read(self, *, consumer: str, count: int, block_ms: int) -> tuple[WorkDelivery, ...]:
        del consumer, count, block_ms
        self.events.append("read")
        delivery, self.delivery = self.delivery, None
        return (delivery,) if delivery is not None else ()

    def ack(self, message_id: str) -> bool:
        self.events.append("ack")
        self.acked.append(message_id)
        return True


class _ObjectStore:
    def put_stream(self, **_kwargs: Any) -> object:
        return object()

    def head(self, _object_key: str) -> object:
        return object()

    def download_to(self, **_kwargs: Any) -> object:
        return object()

    def copy(self, **_kwargs: Any) -> object:
        return object()

    def delete_prefix(self, _prefix: str) -> int:
        return 0

    def signed_get(self, **_kwargs: Any) -> str:
        return "https://objects.example/result.mp4"


class _CleanupSweeper:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[int, int]] = []

    def sweep_once(self, now_ms: int, *, limit: int) -> tuple[str, ...]:
        self.events.append("sweep_once")
        self.calls.append((now_ms, limit))
        return ("job-1",)


class _WorkerManager:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.allow_local_paths = False
        self.profile_bundle_resolver: Any = _ImmutableBundle()
        self.capability_ports = {name: object() for name in REQUIRED_CAPABILITIES}

    def validate_startup_capabilities(self) -> None:
        self.events.append("startup")

    def process_work_message(
        self,
        *,
        message: WorkMessage,
        checkpoint: StageCheckpoint,
        owner: str,
    ) -> dict[str, tuple[str, ...]]:
        assert checkpoint.owner == owner
        assert checkpoint.stage == message.stage
        self.events.append("process_work_message")
        return {"output_artifact_ids": ("artifact-1",)}


@dataclass
class _RuntimeParts:
    events: list[str]
    job_store: _JobStore
    work_queue: _WorkQueue
    object_store: _ObjectStore
    cleanup_sweeper: _CleanupSweeper
    service: FastAPI
    worker_manager: _WorkerManager
    readiness_checks: dict[str, Any]

    def mapping(self) -> dict[str, Any]:
        return {
            "job_store": self.job_store,
            "work_queue": self.work_queue,
            "object_store": self.object_store,
            "cleanup_sweeper": self.cleanup_sweeper,
            "service": self.service,
            "worker_manager": self.worker_manager,
            "readiness_checks": dict(self.readiness_checks),
        }


@pytest.fixture
def runtime_parts(monkeypatch: pytest.MonkeyPatch) -> _RuntimeParts:
    events: list[str] = []
    parts = _RuntimeParts(
        events=events,
        job_store=_JobStore(events),
        work_queue=_WorkQueue(events),
        object_store=_ObjectStore(),
        cleanup_sweeper=_CleanupSweeper(events),
        service=FastAPI(),
        worker_manager=_WorkerManager(events),
        readiness_checks={name: (lambda: True) for name in READINESS_NAMES},
    )
    module = types.ModuleType("deployment_bootstrap_test_factory")
    module.factory = parts.mapping
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("USFR_DEPLOYMENT_FACTORY", f"{module.__name__}:factory")
    monkeypatch.setenv("USFR_PROFILE_MODE", "shadow")
    return parts


def _set_factory(monkeypatch: pytest.MonkeyPatch, value: dict[str, Any]) -> None:
    module = sys.modules["deployment_bootstrap_test_factory"]
    monkeypatch.setattr(module, "factory", lambda: value)


def test_environment_factory_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    monkeypatch.delenv("USFR_DEPLOYMENT_FACTORY", raising=False)
    with pytest.raises(DeploymentBootstrapError, match="USFR_DEPLOYMENT_FACTORY"):
        load_deployment_runtime()


@pytest.mark.parametrize(
    "dependency",
    ("job_store", "work_queue", "object_store", "cleanup_sweeper", "service", "worker_manager"),
)
def test_runtime_requires_every_ephemeral_dependency(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    value = runtime_parts.mapping()
    value[dependency] = None
    _set_factory(monkeypatch, value)
    with pytest.raises(DeploymentBootstrapError, match=dependency):
        load_deployment_runtime()


@pytest.mark.parametrize("dependency", sorted(READINESS_NAMES))
def test_runtime_requires_each_exact_readiness_dependency(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    value = runtime_parts.mapping()
    value["readiness_checks"].pop(dependency)
    _set_factory(monkeypatch, value)
    with pytest.raises(DeploymentBootstrapError, match=dependency):
        load_deployment_runtime()


def test_runtime_rejects_readiness_names_outside_the_six_dependencies(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    value = runtime_parts.mapping()
    value["readiness_checks"]["database"] = lambda: True
    _set_factory(monkeypatch, value)
    with pytest.raises(DeploymentBootstrapError, match="database"):
        load_deployment_runtime()


@pytest.mark.parametrize(
    "dependency",
    (
        "database",
        "repository",
        "auth",
        "tenant_resolver",
        "actor_resolver",
        "billing",
        "history",
        "outbox",
        "service_kwargs",
        "worker_main",
    ),
)
def test_runtime_rejects_legacy_control_plane_dependencies(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    value = runtime_parts.mapping()
    value[dependency] = object()
    _set_factory(monkeypatch, value)
    with pytest.raises(DeploymentBootstrapError, match=dependency):
        load_deployment_runtime()


@pytest.mark.parametrize("resolver", (None, "C:/Users/test/.codex/skills/seedance-20/SKILL.md"))
def test_runtime_requires_an_immutable_packaged_skill_bundle(
    runtime_parts: _RuntimeParts,
    resolver: object,
) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    runtime_parts.worker_manager.profile_bundle_resolver = resolver
    with pytest.raises(DeploymentBootstrapError, match="immutable.*bundle"):
        load_deployment_runtime()


def test_runtime_rejects_worker_local_path_mode(runtime_parts: _RuntimeParts) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    runtime_parts.worker_manager.allow_local_paths = True
    with pytest.raises(DeploymentBootstrapError, match="allow_local_paths"):
        load_deployment_runtime()


def test_runtime_rejects_the_legacy_execute_stage_only_worker_contract(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    class _LegacyWorkerManager:
        allow_local_paths = False
        profile_bundle_resolver = _ImmutableBundle()
        capability_ports = {name: object() for name in REQUIRED_CAPABILITIES}

        def validate_startup_capabilities(self) -> None:
            return None

        def execute_stage(self, **_kwargs: Any) -> dict[str, Any]:
            return {}

    value = runtime_parts.mapping()
    value["worker_manager"] = _LegacyWorkerManager()
    _set_factory(monkeypatch, value)
    with pytest.raises(DeploymentBootstrapError, match="process_work_message"):
        load_deployment_runtime()


@pytest.mark.parametrize("capability", ("dynamics_analyzer", "provider_adapter"))
def test_runtime_requires_model_and_provider_capability_ports(
    runtime_parts: _RuntimeParts,
    capability: str,
) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, load_deployment_runtime

    runtime_parts.worker_manager.capability_ports.pop(capability)
    with pytest.raises(DeploymentBootstrapError, match=capability):
        load_deployment_runtime()


def test_runtime_accepts_only_the_ephemeral_startup_contract(runtime_parts: _RuntimeParts) -> None:
    from server.deployment_bootstrap import load_deployment_runtime

    runtime = load_deployment_runtime()
    assert runtime.job_store is runtime_parts.job_store
    assert runtime.work_queue is runtime_parts.work_queue
    assert runtime.object_store is runtime_parts.object_store
    assert runtime.cleanup_sweeper is runtime_parts.cleanup_sweeper
    assert runtime.service is runtime_parts.service
    assert runtime.worker_manager is runtime_parts.worker_manager
    assert set(runtime.readiness_checks) == READINESS_NAMES
    assert not hasattr(runtime, "service_kwargs")
    assert not hasattr(runtime, "worker_main")


def test_http_health_and_readiness_are_deployment_owned(runtime_parts: _RuntimeParts) -> None:
    from server.deployment_bootstrap import build_http_app

    client = TestClient(build_http_app())
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert set(ready.json()["checks"]) == READINESS_NAMES
    assert runtime_parts.events == ["startup"]


def test_readiness_fails_closed_when_a_dependency_check_is_false(runtime_parts: _RuntimeParts) -> None:
    from server.deployment_bootstrap import build_http_app

    runtime_parts.readiness_checks["object_store"] = lambda: False
    response = TestClient(build_http_app()).get("/readyz")
    assert response.status_code == 503
    assert response.json()["failed_checks"] == ["object_store"]


def test_worker_acks_only_after_stage_checkpoint_commit(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.deployment_bootstrap import run_worker

    monkeypatch.setenv("USFR_WORKER_RUN_ONCE", "1")
    monkeypatch.setenv("USFR_WORKER_CONSUMER", "worker-1")
    assert run_worker() == 0
    assert runtime_parts.events == [
        "startup",
        "reclaim",
        "read",
        "get_job",
        "claim_stage",
        "process_work_message",
        "complete_stage",
        "ack",
    ]
    assert runtime_parts.work_queue.acked == ["1-0"]


def test_default_worker_consumer_has_a_unique_process_boot_nonce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.deployment_bootstrap import _worker_consumer

    monkeypatch.delenv("USFR_WORKER_CONSUMER", raising=False)
    assert _worker_consumer() != _worker_consumer()


def test_worker_reclaims_a_pending_delivery_after_an_expired_previous_claim(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.deployment_bootstrap import run_worker

    runtime_parts.work_queue.reclaimed = runtime_parts.work_queue.delivery
    runtime_parts.work_queue.delivery = None
    runtime_parts.job_store.snapshot = replace(runtime_parts.job_store.snapshot, version=2)
    monkeypatch.setenv("USFR_WORKER_RUN_ONCE", "1")
    monkeypatch.setenv("USFR_WORKER_CONSUMER", "worker-2")
    assert run_worker() == 0
    assert runtime_parts.events == [
        "startup",
        "reclaim",
        "get_job",
        "claim_stage",
        "process_work_message",
        "complete_stage",
        "ack",
    ]
    assert runtime_parts.work_queue.acked == ["1-0"]


def test_worker_leaves_delivery_pending_when_checkpoint_commit_fails(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.deployment_bootstrap import DeploymentBootstrapError, run_worker

    runtime_parts.job_store.fail_complete = True
    monkeypatch.setenv("USFR_WORKER_RUN_ONCE", "1")
    monkeypatch.setenv("USFR_WORKER_CONSUMER", "worker-1")
    with pytest.raises(DeploymentBootstrapError, match="checkpoint"):
        run_worker()
    assert runtime_parts.work_queue.acked == []
    assert runtime_parts.events[-2:] == ["process_work_message", "complete_stage"]


def test_sweeper_runs_scheduled_cleanup_once(
    runtime_parts: _RuntimeParts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.deployment_bootstrap import run_sweeper

    monkeypatch.setenv("USFR_SWEEPER_RUN_ONCE", "1")
    monkeypatch.setenv("USFR_SWEEPER_LIMIT", "17")
    assert run_sweeper() == 0
    assert runtime_parts.events == ["sweep_once"]
    now_ms, limit = runtime_parts.cleanup_sweeper.calls[0]
    assert now_ms > 0
    assert limit == 17


@pytest.mark.parametrize(
    ("role", "environment_name"),
    (("worker", "USFR_WORKER_BOOTSTRAP"), ("sweeper", "USFR_SWEEPER_BOOTSTRAP")),
)
def test_process_entrypoint_loads_the_role_specific_packaged_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    environment_name: str,
) -> None:
    from server import worker_entrypoint

    module = types.ModuleType("deployment_process_test_target")
    module.run = lambda: 7
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("USFR_PROCESS_ROLE", role)
    monkeypatch.setenv(environment_name, f"{module.__name__}:run")
    assert worker_entrypoint.main() == 7
