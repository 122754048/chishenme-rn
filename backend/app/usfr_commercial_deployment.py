"""Deployment-owned commercial queue wiring around the canonical USFR runtime."""

from __future__ import annotations

from dataclasses import replace
import importlib
from importlib.util import find_spec
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .capability_work_queue import (
    CAPABILITY_QUEUES,
    CapabilityRoutedWorkQueue,
    RedisCapabilityCapacityGate,
)
from .services.replication_timing import RedisTimingLedgerStore, TimedStageDriver, TimedStagePort
from .usfr_bundle import UsfrBundleError, verify_usfr_bundle


class CommercialDeploymentError(RuntimeError):
    pass


BACKGROUND_MUSIC_ADAPTER_FACTORY_ENV = "USFR_BACKGROUND_MUSIC_ADAPTER_FACTORY"
BUNDLE_SKILL_SHA_ENV = "USFR_DEPLOYMENT_BUNDLE_SKILL_SHA256"
BUNDLE_TREE_SHA_ENV = "USFR_DEPLOYMENT_BUNDLE_TREE_SHA256"


def build_commercial_deployment_runtime(
    runtime: Any,
    *,
    capability_secret: bytes,
    queue_factory: Callable[..., Any],
    stage_driver_factory: Callable[[Any, Any], Any],
    service_factory: Callable[..., Any],
    worker_capability: str | None = None,
    environment: Mapping[str, str] | None = None,
    background_music_execution_adapter: Any | None = None,
) -> Any:
    """Return a canonical deployment runtime with one shared routed queue."""

    job_store = getattr(runtime, "job_store", None)
    work_queue = getattr(runtime, "work_queue", None)
    object_store = getattr(runtime, "object_store", None)
    worker_manager = getattr(runtime, "worker_manager", None)
    redis_client = getattr(job_store, "redis", None)
    prefix = str(getattr(job_store, "prefix", "") or "").strip()
    group = str(getattr(work_queue, "group", "") or "").strip()
    if job_store is None or object_store is None or worker_manager is None or redis_client is None:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_STANDARD_RUNTIME_REQUIRED")
    if not prefix or not group:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_QUEUE_METADATA_REQUIRED")
    if not isinstance(capability_secret, bytes) or len(capability_secret) < 32:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_CAPABILITY_SECRET_REQUIRED")
    if not callable(queue_factory) or not callable(stage_driver_factory) or not callable(service_factory):
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_FACTORY_INVALID")
    timing_ledger_store = RedisTimingLedgerStore(
        redis_client,
        prefix=prefix,
        ttl_seconds=_positive_environment(environment or {}, "USFR_COMMERCIAL_BATCH_TTL_SECONDS", default=86_400),
        job_scoped_keys=True,
    )
    worker_manager.timing_ledger_store = timing_ledger_store
    queues = {
        capability: queue_factory(
            redis_client,
            prefix=f"{prefix}:commercial:{capability}",
            group=group,
        )
        for capability in CAPABILITY_QUEUES
    }
    capacity_gate = None
    if environment is not None:
        capacity_gate = RedisCapabilityCapacityGate(
            redis_client,
            prefix=f"{prefix}:commercial:capacity",
            lease_ms=_capacity_lease_ms(environment),
        )
    routed_queue = CapabilityRoutedWorkQueue(
        queues,
        worker_capability=worker_capability,
        capacity_gate=capacity_gate,
    )
    if environment is not None:
        for capability, limit in _capability_limits(environment).items():
            routed_queue.set_concurrency_limit(capability, limit)
    stage_driver = stage_driver_factory(job_store, routed_queue)
    if not callable(getattr(stage_driver, "enqueue_next", None)):
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_STAGE_DRIVER_INVALID")
    stage_driver = _install_background_music_execution_adapter(
        adapter=background_music_execution_adapter,
        job_store=job_store,
        work_queue=routed_queue,
        worker_manager=worker_manager,
        stage_driver=stage_driver,
    )
    _instrument_worker_stage_ports(worker_manager, timing_ledger_store=timing_ledger_store)
    stage_driver = TimedStageDriver(
        delegate=stage_driver,
        job_store=job_store,
        timing_ledger_store=timing_ledger_store,
    )
    # The packaged worker consults this mutable reference after every completed
    # stage, so API submission and worker advancement share the same queues.
    worker_manager.stage_driver = stage_driver
    worker_manager.background_music_execution_adapter = background_music_execution_adapter
    service = service_factory(
        job_store=job_store,
        object_store=object_store,
        stage_driver=stage_driver,
        capability_secret=capability_secret,
    )
    try:
        return replace(runtime, work_queue=routed_queue, service=service)
    except TypeError as error:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_RUNTIME_REPLACE_FAILED") from error


def build_deployment_runtime() -> Any:
    """Factory entrypoint for ``USFR_DEPLOYMENT_FACTORY`` deployments."""

    spec = find_spec("server")
    package_file = getattr(spec, "origin", None)
    if not isinstance(package_file, str) or not package_file:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_CANONICAL_PACKAGE_MISSING")
    verify_deployment_usfr_bundle_path(
        server_package_file=package_file,
        environment=os.environ,
    )
    try:
        from server.ephemeral_driver import EphemeralStageDriver
        from server.fastapi_router import create_app
        from server.packaged_factory import build_runtime as build_packaged_runtime
        from server.redis_streams import RedisWorkQueue
    except ImportError as error:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_CANONICAL_PACKAGE_MISSING") from error
    secret = (os.getenv("USFR_CAPABILITY_SECRET", "") or "").encode("utf-8")
    base_runtime = build_packaged_runtime(capability_secret=secret)
    worker_capability = (os.getenv("USFR_WORKER_CAPABILITY", "") or "").strip() or None
    background_music_execution_adapter = _load_background_music_execution_adapter(
        os.getenv(BACKGROUND_MUSIC_ADAPTER_FACTORY_ENV, ""),
        base_runtime,
    )
    return build_commercial_deployment_runtime(
        base_runtime,
        capability_secret=secret,
        queue_factory=RedisWorkQueue,
        stage_driver_factory=EphemeralStageDriver,
        service_factory=create_app,
        worker_capability=worker_capability,
        environment=dict(os.environ),
        background_music_execution_adapter=background_music_execution_adapter,
    )


def verify_deployment_usfr_bundle(*, server_module: Any, environment: Mapping[str, str]) -> Path:
    """Reject a server package unless it is an immutable image-owned USFR bundle."""

    module_file = getattr(server_module, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_BUNDLE_ROOT_INVALID")
    return verify_deployment_usfr_bundle_path(
        server_package_file=module_file,
        environment=environment,
    )


def verify_deployment_usfr_bundle_path(
    *, server_package_file: str | Path, environment: Mapping[str, str]
) -> Path:
    """Verify the bundle before the standard ``server`` package is imported."""

    package_file = Path(server_package_file).resolve()
    if package_file.name != "__init__.py" or package_file.parent.name != "server":
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_BUNDLE_ROOT_INVALID")
    root = package_file.parent.parent
    normalized = root.as_posix().casefold()
    if ".codex/skills" in normalized:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_BUNDLE_LOCATION_FORBIDDEN")
    skill_sha256 = str(environment.get(BUNDLE_SKILL_SHA_ENV) or "").strip()
    tree_sha256 = str(environment.get(BUNDLE_TREE_SHA_ENV) or "").strip()
    if not skill_sha256 or not tree_sha256:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_BUNDLE_DIGEST_REQUIRED")
    try:
        verify_usfr_bundle(
            root,
            expected_skill_sha256=skill_sha256,
            expected_tree_sha256=tree_sha256,
        )
    except UsfrBundleError as error:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_BUNDLE_INVALID") from error
    return root


def build_backend_runtime_from_deployment(
    deployment_runtime: Any,
    *,
    capability_secret: bytes,
    upload_scope: str,
    environment: Mapping[str, str],
    commercial_runtime_builder: Callable[..., Any],
) -> dict[str, Any]:
    """Project one commercial deployment into ``REPLICATION_RUNTIME_FACTORY`` ports."""

    job_store = getattr(deployment_runtime, "job_store", None)
    object_store = getattr(deployment_runtime, "object_store", None)
    worker_manager = getattr(deployment_runtime, "worker_manager", None)
    routed_queue = getattr(deployment_runtime, "work_queue", None)
    stage_driver = getattr(worker_manager, "stage_driver", None)
    redis_client = getattr(job_store, "redis", None)
    controls = getattr(routed_queue, "capability_controls", None)
    if (
        job_store is None
        or object_store is None
        or redis_client is None
        or not callable(getattr(stage_driver, "enqueue_next", None))
        or not isinstance(controls, Mapping)
    ):
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_STANDARD_RUNTIME_REQUIRED")
    if not isinstance(upload_scope, str) or not upload_scope.strip():
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_UPLOAD_SCOPE_REQUIRED")
    if not callable(commercial_runtime_builder):
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_FACTORY_INVALID")
    ttl_seconds = _positive_environment(environment, "USFR_COMMERCIAL_BATCH_TTL_SECONDS", default=86_400)
    commercial_runtime = commercial_runtime_builder(
        job_store=job_store,
        object_store=object_store,
        stage_driver=stage_driver,
        capability_secret=capability_secret,
        upload_scope=upload_scope.strip(),
        ttl_seconds=ttl_seconds,
        redis_client=redis_client,
        capability_queues=controls,
        environment=environment,
        redis_prefix=str(getattr(job_store, "prefix", "usfr") or "usfr"),
        timing_ledger_store=getattr(worker_manager, "timing_ledger_store", None),
        background_music_execution_adapter=getattr(
            worker_manager,
            "background_music_execution_adapter",
            None,
        ),
    )
    return {
        "job_store": job_store,
        "object_store": object_store,
        "stage_driver": stage_driver,
        "capability_secret": capability_secret,
        "commercial_batch_runtime": commercial_runtime,
    }


def build_replication_runtime() -> dict[str, Any]:
    """Factory entrypoint for the backend API's ``REPLICATION_RUNTIME_FACTORY``."""

    try:
        from server.capability_tokens import issue_capability
        from server.intake import bind_uploaded_slots
    except ImportError as error:
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_CANONICAL_PACKAGE_MISSING") from error
    from .replication_runtime import build_standard_commercial_batch_runtime

    environment = dict(os.environ)
    secret = (environment.get("USFR_CAPABILITY_SECRET") or "").encode("utf-8")
    upload_scope = environment.get("USFR_COMMERCIAL_BATCH_UPLOAD_SCOPE") or ""
    deployment_runtime = build_deployment_runtime()

    def build_commercial_runtime(**kwargs: Any) -> Any:
        return build_standard_commercial_batch_runtime(
            **kwargs,
            bind_slots=bind_uploaded_slots,
            issue_capability=issue_capability,
        )

    return build_backend_runtime_from_deployment(
        deployment_runtime,
        capability_secret=secret,
        upload_scope=upload_scope,
        environment=environment,
        commercial_runtime_builder=build_commercial_runtime,
    )


def _positive_environment(environment: Mapping[str, str], name: str, *, default: int) -> int:
    raw = str(environment.get(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise CommercialDeploymentError(f"{name}_INVALID") from error
    if value <= 0:
        raise CommercialDeploymentError(f"{name}_INVALID")
    return value


def _capability_limits(environment: Mapping[str, str]) -> dict[str, int]:
    limits: dict[str, int] = {}
    for capability in CAPABILITY_QUEUES:
        name = "USFR_BATCH_CONCURRENCY_" + capability.upper()
        raw = environment.get(name)
        if raw is None or not str(raw).strip():
            raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_CONCURRENCY_REQUIRED")
        limits[capability] = _positive_environment(environment, name, default=0)
    return limits


def _capacity_lease_ms(environment: Mapping[str, str]) -> int:
    return _positive_environment(environment, "USFR_BATCH_CAPACITY_LEASE_MS", default=3_600_000)


def _install_background_music_execution_adapter(
    *,
    adapter: Any | None,
    job_store: Any,
    work_queue: Any,
    worker_manager: Any,
    stage_driver: Any,
) -> Any:
    if adapter is None:
        return stage_driver
    install = getattr(adapter, "install", None)
    validate_startup = getattr(adapter, "validate_startup", None)
    validate_manifest = getattr(adapter, "validate_manifest", None)
    if not all(callable(method) for method in (install, validate_startup, validate_manifest)):
        raise CommercialDeploymentError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_INVALID")
    try:
        installed = install(
            job_store=job_store,
            work_queue=work_queue,
            worker_manager=worker_manager,
            stage_driver=stage_driver,
        )
        if not callable(getattr(installed, "enqueue_next", None)):
            raise CommercialDeploymentError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_INVALID")
        if getattr(installed, "background_music_execution_contract", None) != "background_music_execution/v1":
            raise CommercialDeploymentError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_INVALID")
        validate_startup()
    except CommercialDeploymentError:
        raise
    except Exception as error:
        raise CommercialDeploymentError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_UNAVAILABLE") from error
    return installed


def _instrument_worker_stage_ports(worker_manager: Any, *, timing_ledger_store: RedisTimingLedgerStore) -> None:
    stage_ports = getattr(worker_manager, "stage_ports", None)
    if not isinstance(stage_ports, Mapping):
        raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_STAGE_PORTS_REQUIRED")
    wrapped: dict[str, Any] = {}
    for stage, port in stage_ports.items():
        if not isinstance(stage, str) or not stage.strip():
            raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_STAGE_PORTS_REQUIRED")
        if getattr(port, "timing_stage_port", False) is True:
            wrapped[stage] = port
            continue
        try:
            wrapped[stage] = TimedStagePort(
                stage=stage,
                delegate=port,
                timing_ledger_store=timing_ledger_store,
            )
        except ValueError as error:
            raise CommercialDeploymentError("COMMERCIAL_DEPLOYMENT_STAGE_PORTS_REQUIRED") from error
    worker_manager.stage_ports = wrapped


def _load_background_music_execution_adapter(spec: str | None, runtime: Any) -> Any | None:
    value = str(spec or "").strip()
    if not value:
        return None
    module_name, separator, function_name = value.partition(":")
    if (
        not separator
        or not module_name
        or not function_name
        or "/" in module_name
        or "\\" in module_name
        or ".codex" in module_name.casefold()
    ):
        raise CommercialDeploymentError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_FACTORY_INVALID")
    try:
        factory = getattr(importlib.import_module(module_name), function_name)
        if not callable(factory):
            raise TypeError("adapter factory is not callable")
        return factory(runtime)
    except CommercialDeploymentError:
        raise
    except Exception as error:
        raise CommercialDeploymentError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_UNAVAILABLE") from error


__all__ = [
    "CommercialDeploymentError",
    "build_backend_runtime_from_deployment",
    "build_commercial_deployment_runtime",
    "build_deployment_runtime",
    "build_replication_runtime",
    "verify_deployment_usfr_bundle",
    "verify_deployment_usfr_bundle_path",
]
