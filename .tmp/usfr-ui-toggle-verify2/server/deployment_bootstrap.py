"""Stateless API, Redis Streams worker, and cleanup-sweeper bootstrap.

One packaged ``module:function`` factory supplies the already-constructed
ephemeral runtime.  This module validates that boundary, adds deployment-owned
health probes to the injected FastAPI service, consumes active Redis Streams
work, and runs short-TTL cleanup.  It never resolves a workstation Skill path
or constructs a SQL/auth/history control plane.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import importlib
import inspect
import os
import secrets
import socket
import time
from types import MappingProxyType
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .capabilities import REQUIRED_CAPABILITIES
from .errors import ReplicationError
from .public_errors import project_public_error


DEPLOYMENT_FACTORY_ENV = "USFR_DEPLOYMENT_FACTORY"
PROFILE_MODE_ENV = "USFR_PROFILE_MODE"
WORKER_RUN_ONCE_ENV = "USFR_WORKER_RUN_ONCE"
SWEEPER_RUN_ONCE_ENV = "USFR_SWEEPER_RUN_ONCE"
REQUIRED_READINESS_CHECKS = (
    "redis",
    "object_store",
    "bundle",
    "models",
    "capabilities",
    "provider",
)
_ALLOWED_PROFILE_MODES = frozenset({"shadow", "legacy", "disabled", "active", "production"})
_RUNTIME_FIELDS = frozenset(
    {
        "job_store",
        "work_queue",
        "object_store",
        "cleanup_sweeper",
        "service",
        "worker_manager",
        "readiness_checks",
        "profile_mode",
    }
)


class DeploymentBootstrapError(RuntimeError):
    """Raised before serving or consuming when deployment wiring is incomplete."""


@dataclass(frozen=True)
class DeploymentRuntime:
    """Immutable dependencies shared by the stateless deployment processes."""

    job_store: Any
    work_queue: Any
    object_store: Any
    cleanup_sweeper: Any
    service: Any
    worker_manager: Any
    readiness_checks: Mapping[str, Callable[[], Any]]
    profile_mode: str = "shadow"


def _load_factory(spec: str) -> Callable[[], Any]:
    module_name, separator, function_name = spec.partition(":")
    folded = module_name.casefold()
    if (
        not separator
        or not module_name
        or not function_name
        or "/" in module_name
        or "\\" in module_name
        or "~/.codex" in folded
        or ".codex/skills" in folded
    ):
        raise DeploymentBootstrapError(
            f"{DEPLOYMENT_FACTORY_ENV} must be a packaged module:function reference"
        )
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise DeploymentBootstrapError(
            f"could not import deployment factory module: {module_name}"
        ) from exc
    factory = getattr(module, function_name, None)
    if not callable(factory):
        raise DeploymentBootstrapError(f"deployment factory is not callable: {spec}")
    return factory


def _profile_mode() -> str:
    mode = (os.getenv(PROFILE_MODE_ENV, "shadow") or "shadow").strip().casefold()
    if mode not in _ALLOWED_PROFILE_MODES:
        raise DeploymentBootstrapError(
            f"{PROFILE_MODE_ENV} must be one of: {', '.join(sorted(_ALLOWED_PROFILE_MODES))}"
        )
    return mode


def _require_methods(value: Any, label: str, methods: Sequence[str]) -> None:
    if value is None:
        raise DeploymentBootstrapError(f"deployment {label} is required")
    missing = [name for name in methods if not callable(getattr(value, name, None))]
    if missing:
        raise DeploymentBootstrapError(
            f"deployment {label} missing callable methods: {', '.join(missing)}"
        )


def _validate_worker_manager(worker_manager: Any) -> None:
    if worker_manager is None:
        raise DeploymentBootstrapError("deployment worker_manager is required")
    if not hasattr(worker_manager, "allow_local_paths"):
        raise DeploymentBootstrapError(
            "deployment worker_manager must expose allow_local_paths=False"
        )
    if bool(getattr(worker_manager, "allow_local_paths")):
        raise DeploymentBootstrapError(
            "deployment worker_manager.allow_local_paths must remain false"
        )
    bundle_resolver = getattr(worker_manager, "profile_bundle_resolver", None)
    if bundle_resolver is None:
        bundle_resolver = getattr(worker_manager, "profile_dependency_paths", None)
    if not bool(getattr(bundle_resolver, "immutable", False)):
        raise DeploymentBootstrapError(
            "deployment worker_manager requires an immutable packaged bundle resolver"
        )
    ports = getattr(worker_manager, "capability_ports", None)
    if not isinstance(ports, Mapping):
        raise DeploymentBootstrapError(
            "deployment worker_manager.capability_ports must bind the video/model and Provider ports"
        )
    missing_ports = [name for name in REQUIRED_CAPABILITIES if name not in ports]
    if missing_ports:
        raise DeploymentBootstrapError(
            f"deployment worker_manager capability ports missing: {', '.join(missing_ports)}"
        )
    _require_methods(
        worker_manager,
        "worker_manager",
        ("validate_startup_capabilities", "process_work_message"),
    )


def _validate_readiness_checks(value: Any) -> Mapping[str, Callable[[], Any]]:
    if not isinstance(value, Mapping):
        raise DeploymentBootstrapError("deployment readiness_checks must be an object")
    checks = dict(value)
    names = set(checks)
    required = set(REQUIRED_READINESS_CHECKS)
    missing = sorted(required - names)
    unexpected = sorted(names - required)
    if missing:
        raise DeploymentBootstrapError(
            f"deployment readiness_checks missing: {', '.join(missing)}"
        )
    if unexpected:
        raise DeploymentBootstrapError(
            f"deployment readiness_checks contain unsupported dependencies: {', '.join(unexpected)}"
        )
    invalid = sorted(name for name, check in checks.items() if not callable(check))
    if invalid:
        raise DeploymentBootstrapError(
            f"deployment readiness checks are not callable: {', '.join(invalid)}"
        )
    return MappingProxyType(checks)


def _coerce_runtime(value: Any, *, profile_mode: str) -> DeploymentRuntime:
    if isinstance(value, DeploymentRuntime):
        runtime = value
    elif isinstance(value, Mapping):
        unsupported = sorted(str(name) for name in set(value) - _RUNTIME_FIELDS)
        if unsupported:
            raise DeploymentBootstrapError(
                f"deployment factory returned unsupported dependencies: {', '.join(unsupported)}"
            )
        runtime = DeploymentRuntime(
            job_store=value.get("job_store"),
            work_queue=value.get("work_queue"),
            object_store=value.get("object_store"),
            cleanup_sweeper=value.get("cleanup_sweeper"),
            service=value.get("service"),
            worker_manager=value.get("worker_manager"),
            readiness_checks=value.get("readiness_checks") or {},
            profile_mode=str(value.get("profile_mode") or profile_mode),
        )
    else:
        raise DeploymentBootstrapError(
            "deployment factory must return DeploymentRuntime or an equivalent object mapping"
        )

    runtime_mode = str(runtime.profile_mode or "").strip().casefold()
    if runtime_mode != profile_mode:
        raise DeploymentBootstrapError(
            "deployment runtime profile_mode does not match USFR_PROFILE_MODE"
        )
    _require_methods(runtime.job_store, "job_store", ("get_job", "claim_stage", "complete_stage"))
    _require_methods(runtime.work_queue, "work_queue", ("read", "ack", "reclaim"))
    _require_methods(
        runtime.object_store,
        "object_store",
        ("put_stream", "head", "download_to", "copy", "delete_prefix", "signed_get"),
    )
    _require_methods(runtime.cleanup_sweeper, "cleanup_sweeper", ("sweep_once",))
    if runtime.service is None:
        raise DeploymentBootstrapError("deployment service is required")
    if not isinstance(runtime.service, FastAPI) and not callable(runtime.service):
        raise DeploymentBootstrapError(
            "deployment service must be a FastAPI instance or a zero-argument app factory"
        )
    _validate_worker_manager(runtime.worker_manager)
    checks = _validate_readiness_checks(runtime.readiness_checks)
    return DeploymentRuntime(
        job_store=runtime.job_store,
        work_queue=runtime.work_queue,
        object_store=runtime.object_store,
        cleanup_sweeper=runtime.cleanup_sweeper,
        service=runtime.service,
        worker_manager=runtime.worker_manager,
        readiness_checks=checks,
        profile_mode=profile_mode,
    )


def load_deployment_runtime() -> DeploymentRuntime:
    """Load and validate one packaged deployment-owned dependency factory."""

    spec = (os.getenv(DEPLOYMENT_FACTORY_ENV, "") or "").strip()
    if not spec:
        raise DeploymentBootstrapError(
            f"{DEPLOYMENT_FACTORY_ENV} is required; inject a packaged server factory"
        )
    mode = _profile_mode()
    factory = _load_factory(spec)
    try:
        value = factory()
    except DeploymentBootstrapError:
        raise
    except Exception as exc:
        raise DeploymentBootstrapError("deployment factory failed during construction") from exc
    return _coerce_runtime(value, profile_mode=mode)


def _validate_startup(runtime: DeploymentRuntime) -> None:
    try:
        runtime.worker_manager.validate_startup_capabilities()
    except Exception as exc:
        raise DeploymentBootstrapError(
            "deployment startup capability validation failed"
        ) from exc


async def _readiness_result(check: Callable[[], Any]) -> bool:
    value = check()
    if inspect.isawaitable(value):
        value = await value
    if isinstance(value, Mapping):
        if "ok" in value:
            return value.get("ok") is True
        return str(value.get("status") or "").casefold() in {"ok", "ready", "healthy"}
    return value is True


def _attach_health_routes(app: FastAPI, runtime: DeploymentRuntime) -> None:
    @app.get("/health", include_in_schema=False)
    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "universal-source-fidelity-replication",
            "profile_mode": runtime.profile_mode,
        }

    @app.get("/ready", include_in_schema=False)
    @app.get("/readyz", include_in_schema=False)
    async def ready() -> Any:
        checks: dict[str, str] = {}
        failed: list[str] = []
        for name in REQUIRED_READINESS_CHECKS:
            try:
                passed = await _readiness_result(runtime.readiness_checks[name])
            except Exception:
                passed = False
            checks[name] = "ready" if passed else "not_ready"
            if not passed:
                failed.append(name)
        payload = {
            "status": "ready" if not failed else "not_ready",
            "profile_mode": runtime.profile_mode,
            "checks": checks,
            "failed_checks": failed,
        }
        if failed:
            return JSONResponse(status_code=503, content=payload)
        return payload


def _service_app(service: Any) -> FastAPI:
    if isinstance(service, FastAPI):
        return service
    try:
        app = service()
    except Exception as exc:
        raise DeploymentBootstrapError("deployment HTTP service construction failed") from exc
    if not isinstance(app, FastAPI):
        raise DeploymentBootstrapError("deployment service factory must return FastAPI")
    return app


def build_http_app() -> FastAPI:
    """Uvicorn ``--factory`` entrypoint for the stateless HTTP service."""

    runtime = load_deployment_runtime()
    _validate_startup(runtime)
    app = _service_app(runtime.service)
    app.state.deployment_runtime = runtime
    _attach_health_routes(app, runtime)
    return app


def _positive_int_environment(name: str, default: int) -> int:
    raw = (os.getenv(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise DeploymentBootstrapError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise DeploymentBootstrapError(f"{name} must be a positive integer")
    return value


def _boolean_environment(name: str) -> bool:
    raw = (os.getenv(name, "") or "").strip().casefold()
    if raw in {"", "0", "false", "no"}:
        return False
    if raw in {"1", "true", "yes"}:
        return True
    raise DeploymentBootstrapError(f"{name} must be a boolean")


def _worker_consumer() -> str:
    configured = (os.getenv("USFR_WORKER_CONSUMER", "") or "").strip()
    if configured:
        return configured
    host = "".join(character if character.isalnum() or character in "._-" else "-" for character in socket.gethostname())
    return f"{host or 'worker'}-{os.getpid()}-{secrets.token_hex(6)}"


def _output_artifact_ids(result: Any) -> tuple[str, ...]:
    if result is None:
        return ()
    raw = result.get("output_artifact_ids", ()) if isinstance(result, Mapping) else result
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise DeploymentBootstrapError(
            "deployment worker result output_artifact_ids must be a sequence"
        )
    values = tuple(raw)
    if any(not isinstance(value, str) or not value for value in values):
        raise DeploymentBootstrapError(
            "deployment worker result output_artifact_ids must contain non-empty strings"
        )
    return values


def _process_delivery(
    runtime: DeploymentRuntime,
    delivery: Any,
    *,
    consumer: str,
    ttl_seconds: int,
) -> None:
    message = delivery.message
    snapshot = runtime.job_store.get_job(message.job_id)
    if snapshot is None:
        raise DeploymentBootstrapError(
            f"deployment worker cannot process expired job: {message.job_id}"
        )
    if int(snapshot.version) < int(message.expected_version):
        raise DeploymentBootstrapError(
            "deployment work message expected_version is ahead of the job checkpoint"
        )
    checkpoint = None
    try:
        checkpoint = runtime.job_store.claim_stage(
            job_id=message.job_id,
            stage=message.stage,
            dedupe_key=message.dedupe_key,
            owner=consumer,
            ttl_seconds=ttl_seconds,
        )
        result = runtime.worker_manager.process_work_message(
            message=message,
            checkpoint=checkpoint,
            owner=consumer,
        )
        runtime.job_store.complete_stage(
            job_id=message.job_id,
            stage=message.stage,
            dedupe_key=message.dedupe_key,
            owner=consumer,
            output_artifact_ids=_output_artifact_ids(result),
            ttl_seconds=ttl_seconds,
        )
        if message.stage == "run_qc":
            completed_snapshot = runtime.job_store.get_job(message.job_id)
            cleanup_sweeper = getattr(runtime, "cleanup_sweeper", None)
            schedule_temporary_cleanup = getattr(
                cleanup_sweeper,
                "schedule_temporary_cleanup",
                None,
            )
            if (
                completed_snapshot is not None
                and str(completed_snapshot.state or "").upper() == "SUCCEEDED"
                and callable(schedule_temporary_cleanup)
            ):
                schedule_temporary_cleanup(message.job_id)
        stage_driver = getattr(runtime.worker_manager, "stage_driver", None)
        if stage_driver is not None:
            stage_driver.enqueue_next(message.job_id)
    except DeploymentBootstrapError:
        raise
    except ReplicationError as exc:
        if checkpoint is None:
            raise DeploymentBootstrapError(
                "deployment worker stage claim failed"
            ) from exc
        retryable = (
            bool(exc.retryable)
            and int(checkpoint.attempt) < 3
            and message.stage != "submit_provider_video"
            and str(exc.code).upper() not in {
                "PROVIDER_AMBIGUOUS",
                "VIDEO_CREATE_AMBIGUOUS",
            }
        )
        try:
            runtime.job_store.fail_stage(
                job_id=message.job_id,
                stage=message.stage,
                dedupe_key=message.dedupe_key,
                owner=consumer,
                terminal=not retryable,
                public_error=None if retryable else project_public_error(exc),
                ttl_seconds=ttl_seconds,
            )
            cleanup_sweeper = getattr(runtime, "cleanup_sweeper", None)
            schedule_temporary_cleanup = getattr(
                cleanup_sweeper,
                "schedule_temporary_cleanup",
                None,
            )
            if not retryable and callable(schedule_temporary_cleanup):
                schedule_temporary_cleanup(message.job_id)
            runtime.work_queue.ack(delivery.message_id)
            if retryable:
                stage_driver = getattr(runtime.worker_manager, "stage_driver", None)
                if stage_driver is not None:
                    stage_driver.enqueue_next(message.job_id)
        except Exception as failure_exc:
            raise DeploymentBootstrapError(
                "deployment worker stage failure could not be committed"
            ) from failure_exc
        return
    except Exception as exc:
        raise DeploymentBootstrapError(
            "deployment worker checkpoint processing failed"
        ) from exc
    runtime.work_queue.ack(delivery.message_id)


def run_worker() -> int:
    """Consume Redis Streams and ACK only after stage checkpoint commit."""

    runtime = load_deployment_runtime()
    _validate_startup(runtime)
    consumer = _worker_consumer()
    count = _positive_int_environment("USFR_WORKER_BATCH_SIZE", 1)
    block_ms = _positive_int_environment("USFR_WORKER_BLOCK_MS", 1_000)
    reclaim_idle_ms = _positive_int_environment("USFR_WORKER_RECLAIM_IDLE_MS", 60_000)
    ttl_seconds = _positive_int_environment("USFR_STAGE_TTL_SECONDS", 60)
    run_once = _boolean_environment(WORKER_RUN_ONCE_ENV)
    while True:
        try:
            deliveries = runtime.work_queue.reclaim(
                consumer=consumer,
                min_idle_ms=reclaim_idle_ms,
                count=count,
            )
            if not deliveries:
                deliveries = runtime.work_queue.read(
                    consumer=consumer,
                    count=count,
                    block_ms=block_ms,
                )
        except Exception as exc:
            raise DeploymentBootstrapError("deployment Redis Streams read failed") from exc
        for delivery in deliveries:
            _process_delivery(
                runtime,
                delivery,
                consumer=consumer,
                ttl_seconds=ttl_seconds,
            )
        if run_once:
            return 0


def run_sweeper() -> int:
    """Run scheduled job/object cleanup without creating durable history."""

    runtime = load_deployment_runtime()
    limit = _positive_int_environment("USFR_SWEEPER_LIMIT", 100)
    interval_seconds = _positive_int_environment("USFR_SWEEPER_INTERVAL_SECONDS", 30)
    run_once = _boolean_environment(SWEEPER_RUN_ONCE_ENV)
    while True:
        now_ms = time.time_ns() // 1_000_000
        try:
            temporary_sweep = getattr(
                runtime.cleanup_sweeper,
                "sweep_temporary_once",
                None,
            )
            if callable(temporary_sweep):
                temporary_sweep(now_ms, limit=limit)
            runtime.cleanup_sweeper.sweep_once(now_ms, limit=limit)
        except Exception as exc:
            raise DeploymentBootstrapError("deployment scheduled cleanup failed") from exc
        if run_once:
            return 0
        time.sleep(interval_seconds)


__all__ = [
    "DEPLOYMENT_FACTORY_ENV",
    "PROFILE_MODE_ENV",
    "REQUIRED_READINESS_CHECKS",
    "DeploymentBootstrapError",
    "DeploymentRuntime",
    "build_http_app",
    "load_deployment_runtime",
    "run_sweeper",
    "run_worker",
]
