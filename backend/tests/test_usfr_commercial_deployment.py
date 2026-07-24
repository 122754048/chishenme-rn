from dataclasses import dataclass
import sys
from types import ModuleType

import pytest

from app.capability_work_queue import CapabilityRoutedWorkQueue
from app.services.replication_timing import TimedStageDriver, TimedStagePort
from app.usfr_commercial_deployment import (
    CommercialDeploymentError,
    _load_background_music_execution_adapter,
    build_backend_runtime_from_deployment,
    build_commercial_deployment_runtime,
)


class _Redis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, *, nx=False, px=None):
        del px
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def eval(self, _script, _numkeys, key, token):
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1


class _JobStore:
    def __init__(self):
        self.redis = _Redis()
        self.prefix = "usfr"

    def get_job(self, job_id):
        del job_id
        return None


class _Queue:
    def __init__(self, prefix, group):
        self.prefix = prefix
        self.group = group

    def enqueue(self, **_):
        return "entry-1"

    def read(self, **_):
        return ()

    def reclaim(self, **_):
        return ()

    def ack(self, _):
        return True


class _WorkerManager:
    def __init__(self, stage_ports=None):
        self.stage_driver = "old-driver"
        self.stage_ports = dict(stage_ports or {})


class _StageDriver:
    def __init__(self, job_store, work_queue):
        self.job_store = job_store
        self.work_queue = work_queue

    def enqueue_next(self, job_id):
        del job_id
        return None


class _StagePort:
    def run(self, *, context, input_artifacts):
        del context, input_artifacts
        return {"stage": "completed"}


class _MusicStageDriver(_StageDriver):
    background_music_execution_contract = "background_music_execution/v1"


class _BackgroundMusicDeploymentAdapter:
    def __init__(self):
        self.install_calls = []
        self.startup_calls = 0

    def install(self, *, job_store, work_queue, worker_manager, stage_driver):
        self.install_calls.append((job_store, work_queue, worker_manager, stage_driver))
        return _MusicStageDriver(job_store, work_queue)

    def validate_startup(self):
        self.startup_calls += 1

    def validate_manifest(self, *, background_music):
        del background_music


@dataclass(frozen=True)
class _Runtime:
    job_store: object
    work_queue: object
    object_store: object
    worker_manager: object
    service: object


def test_commercial_deployment_runtime_gives_api_and_worker_manager_the_same_capability_routed_stage_driver():
    base = _Runtime(
        job_store=_JobStore(),
        work_queue=_Queue("usfr:work", "workers"),
        object_store=object(),
        worker_manager=_WorkerManager(),
        service="old-service",
    )
    queue_calls = []
    service_calls = []

    def queue_factory(redis, *, prefix, group):
        assert redis is base.job_store.redis
        queue_calls.append((prefix, group))
        return _Queue(prefix, group)

    def stage_driver_factory(job_store, work_queue):
        assert job_store is base.job_store
        assert isinstance(work_queue, CapabilityRoutedWorkQueue)
        return _StageDriver(job_store, work_queue)

    def service_factory(*, job_store, object_store, stage_driver, capability_secret):
        service_calls.append((job_store, object_store, stage_driver, capability_secret))
        return {"stage_driver": stage_driver}

    result = build_commercial_deployment_runtime(
        base,
        capability_secret=b"x" * 32,
        queue_factory=queue_factory,
        stage_driver_factory=stage_driver_factory,
        service_factory=service_factory,
        worker_capability="provider_poll",
    )

    assert result is not base
    assert isinstance(result.work_queue, CapabilityRoutedWorkQueue)
    assert result.worker_manager is base.worker_manager
    assert isinstance(result.worker_manager.stage_driver, TimedStageDriver)
    assert result.worker_manager.stage_driver == result.service["stage_driver"]
    assert result.work_queue._worker_capability == "provider_poll"
    assert queue_calls == [
        ("usfr:commercial:probe_dynamics", "workers"),
        ("usfr:commercial:asr_localization", "workers"),
        ("usfr:commercial:storyboard_generation", "workers"),
        ("usfr:commercial:provider_poll", "workers"),
        ("usfr:commercial:assembly_qc", "workers"),
    ]
    assert service_calls == [(base.job_store, base.object_store, result.worker_manager.stage_driver, b"x" * 32)]


def test_commercial_deployment_runtime_applies_every_capability_limit_before_workers_consume_messages():
    base = _Runtime(
        job_store=_JobStore(),
        work_queue=_Queue("usfr:work", "workers"),
        object_store=object(),
        worker_manager=_WorkerManager(),
        service="old-service",
    )

    result = build_commercial_deployment_runtime(
        base,
        capability_secret=b"x" * 32,
        queue_factory=lambda *_, **kwargs: _Queue(kwargs["prefix"], kwargs["group"]),
        stage_driver_factory=_StageDriver,
        service_factory=lambda **_: object(),
        environment={
            "USFR_BATCH_CONCURRENCY_PROBE_DYNAMICS": "2",
            "USFR_BATCH_CONCURRENCY_ASR_LOCALIZATION": "3",
            "USFR_BATCH_CONCURRENCY_STORYBOARD_GENERATION": "4",
            "USFR_BATCH_CONCURRENCY_PROVIDER_POLL": "5",
            "USFR_BATCH_CONCURRENCY_ASSEMBLY_QC": "6",
        },
    )

    assert result.work_queue.concurrency_limits == {
        "probe_dynamics": 2,
        "asr_localization": 3,
        "storyboard_generation": 4,
        "provider_poll": 5,
        "assembly_qc": 6,
    }


def test_commercial_deployment_wraps_existing_stage_ports_with_the_durable_timing_sink():
    worker_manager = _WorkerManager(stage_ports={"analyze_dynamics": _StagePort()})
    base = _Runtime(
        job_store=_JobStore(),
        work_queue=_Queue("usfr:work", "workers"),
        object_store=object(),
        worker_manager=worker_manager,
        service="old-service",
    )

    build_commercial_deployment_runtime(
        base,
        capability_secret=b"x" * 32,
        queue_factory=lambda *_, **kwargs: _Queue(kwargs["prefix"], kwargs["group"]),
        stage_driver_factory=_StageDriver,
        service_factory=lambda **_: object(),
    )

    assert isinstance(worker_manager.stage_ports["analyze_dynamics"], TimedStagePort)
    worker_manager.timing_ledger_store.create("commercial-job")
    context = type("Context", (), {"job_id": "commercial-job"})()
    worker_manager.stage_ports["analyze_dynamics"].run(context=context, input_artifacts=[])
    assert worker_manager.timing_ledger_store.snapshot("commercial-job")["stages"][0]["name"] == "analyze_dynamics"


def test_commercial_deployment_runtime_rejects_a_stage_driver_without_standard_enqueue_next():
    base = _Runtime(
        job_store=_JobStore(),
        work_queue=_Queue("usfr:work", "workers"),
        object_store=object(),
        worker_manager=_WorkerManager(),
        service="old-service",
    )

    with pytest.raises(CommercialDeploymentError, match="COMMERCIAL_DEPLOYMENT_STAGE_DRIVER_INVALID"):
        build_commercial_deployment_runtime(
            base,
            capability_secret=b"x" * 32,
            queue_factory=lambda *_, **kwargs: _Queue(kwargs["prefix"], kwargs["group"]),
            stage_driver_factory=lambda *_: {"not": "a driver"},
            service_factory=lambda **_: object(),
        )


def test_commercial_deployment_installs_a_validated_background_music_adapter_on_the_same_worker_stage_driver():
    base = _Runtime(
        job_store=_JobStore(),
        work_queue=_Queue("usfr:work", "workers"),
        object_store=object(),
        worker_manager=_WorkerManager(),
        service="old-service",
    )
    adapter = _BackgroundMusicDeploymentAdapter()

    result = build_commercial_deployment_runtime(
        base,
        capability_secret=b"x" * 32,
        queue_factory=lambda *_, **kwargs: _Queue(kwargs["prefix"], kwargs["group"]),
        stage_driver_factory=_StageDriver,
        service_factory=lambda **kwargs: {"stage_driver": kwargs["stage_driver"]},
        background_music_execution_adapter=adapter,
    )

    assert len(adapter.install_calls) == 1
    assert adapter.install_calls[0][0] is base.job_store
    assert adapter.install_calls[0][2] is base.worker_manager
    assert adapter.install_calls[0][3] is not result.worker_manager.stage_driver
    assert adapter.startup_calls == 1
    assert result.worker_manager.background_music_execution_adapter is adapter
    assert result.service["stage_driver"] is result.worker_manager.stage_driver


def test_commercial_deployment_rejects_a_background_music_adapter_that_does_not_install_a_music_aware_stage_driver():
    base = _Runtime(
        job_store=_JobStore(),
        work_queue=_Queue("usfr:work", "workers"),
        object_store=object(),
        worker_manager=_WorkerManager(),
        service="old-service",
    )

    with pytest.raises(CommercialDeploymentError, match="BACKGROUND_MUSIC_EXECUTION_ADAPTER_INVALID"):
        build_commercial_deployment_runtime(
            base,
            capability_secret=b"x" * 32,
            queue_factory=lambda *_, **kwargs: _Queue(kwargs["prefix"], kwargs["group"]),
            stage_driver_factory=_StageDriver,
            service_factory=lambda **_: object(),
            background_music_execution_adapter=type(
                "InvalidBackgroundMusicAdapter",
                (),
                {
                    "install": lambda self, **kwargs: _StageDriver(kwargs["job_store"], kwargs["work_queue"]),
                    "validate_startup": lambda self: None,
                    "validate_manifest": lambda self, **kwargs: None,
                },
            )(),
        )


def test_background_music_adapter_factory_receives_the_built_deployment_runtime_and_returns_its_adapter():
    module_name = "test_background_music_adapter_factory"
    module = ModuleType(module_name)
    adapter = _BackgroundMusicDeploymentAdapter()
    observed = []
    module.build_adapter = lambda runtime: observed.append(runtime) or adapter
    sys.modules[module_name] = module
    runtime = _Runtime(
        job_store=_JobStore(),
        work_queue=_Queue("usfr:work", "workers"),
        object_store=object(),
        worker_manager=_WorkerManager(),
        service="old-service",
    )
    try:
        result = _load_background_music_execution_adapter(f"{module_name}:build_adapter", runtime)
    finally:
        del sys.modules[module_name]

    assert result is adapter
    assert observed == [runtime]


def test_backend_runtime_factory_projection_builds_the_typed_commercial_runtime_from_the_deployment_ports():
    stage_driver = _StageDriver(_JobStore(), _Queue("usfr:commercial", "workers"))
    worker_manager = _WorkerManager()
    worker_manager.stage_driver = stage_driver
    deployment = _Runtime(
        job_store=stage_driver.job_store,
        work_queue=CapabilityRoutedWorkQueue(
            {
                name: _Queue(f"usfr:commercial:{name}", "workers")
                for name in (
                    "probe_dynamics",
                    "asr_localization",
                    "storyboard_generation",
                    "provider_poll",
                    "assembly_qc",
                )
            }
        ),
        object_store=object(),
        worker_manager=worker_manager,
        service=object(),
    )
    calls = []

    result = build_backend_runtime_from_deployment(
        deployment,
        capability_secret=b"x" * 32,
        upload_scope="batch-scope",
        environment={"USFR_BATCH_CONCURRENCY_PROBE_DYNAMICS": "2"},
        commercial_runtime_builder=lambda **kwargs: calls.append(kwargs) or "typed-runtime",
    )

    assert result == {
        "job_store": deployment.job_store,
        "object_store": deployment.object_store,
        "stage_driver": stage_driver,
        "capability_secret": b"x" * 32,
        "commercial_batch_runtime": "typed-runtime",
    }
    assert calls[0]["capability_queues"] is deployment.work_queue.capability_controls
    assert calls[0]["redis_client"] is deployment.job_store.redis
    assert calls[0]["upload_scope"] == "batch-scope"
