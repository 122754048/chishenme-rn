"""Packaged Redis/S3 deployment factory for API, Worker, and Sweeper."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Mapping

from .bundle_resolver import ImmutableBundleResolver
from .capabilities import REQUIRED_CAPABILITIES
from .cleanup import CleanupSweeper
from .deployment_bootstrap import DeploymentRuntime
from .ephemeral_driver import EXECUTABLE_STAGES, EphemeralStageDriver
from .ephemeral_worker import EphemeralWorkerManager
from .fastapi_router import create_app
from .media_materializer import MediaMaterializer
from .object_store import FinalVideoStore, S3ObjectStore, TemporaryMediaStore, UploadMediaStore
from .redis_job_store import RedisEphemeralJobStore
from .redis_streams import RedisWorkQueue


PORT_FACTORY_ENV = "USFR_PORT_FACTORY"
READINESS_ONLY_ENV = "USFR_READINESS_ONLY"


class PackagedFactoryError(RuntimeError):
    pass


class _ReadinessOnlyPort:
    def __init__(self, name: str) -> None:
        self.name = name

    def capability_identity(self) -> dict[str, str]:
        return {
            "implementation": f"server.packaged_factory:readiness-only:{self.name}",
            "version": "1",
            "sha256": (self.name.encode("utf-8").hex() + "0" * 64)[:64],
        }

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise PackagedFactoryError("readiness-only capability cannot execute video work")

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return self(*args, **kwargs)


class _S3MediaReader:
    def __init__(self, object_store: S3ObjectStore, client: Any, bucket: str) -> None:
        self.object_store = object_store
        self.client = client
        self.bucket = bucket

    def head(self, object_key: str) -> dict[str, Any]:
        ref = self.object_store.head(object_key)
        return {
            "object_key": ref.object_key,
            "sha256": ref.sha256,
            "size_bytes": ref.size_bytes,
            "content_type": ref.content_type,
        }

    def open_stream(self, object_key: str):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key)
            return response["Body"]
        except Exception as exc:
            raise PackagedFactoryError("S3 object stream could not be opened") from exc


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def _load_port_factory(spec: str) -> Mapping[str, Any]:
    module_name, separator, function_name = spec.partition(":")
    if (
        not separator
        or not module_name
        or not function_name
        or "/" in module_name
        or "\\" in module_name
        or ".codex" in module_name.casefold()
    ):
        raise PackagedFactoryError(f"{PORT_FACTORY_ENV} must be a packaged module:function")
    try:
        factory = getattr(importlib.import_module(module_name), function_name)
        result = factory()
    except Exception as exc:
        raise PackagedFactoryError("deployment port factory could not be loaded") from exc
    if not isinstance(result, Mapping):
        raise PackagedFactoryError("deployment port factory must return an object")
    return result


def _configure_optional_remotion_ui_adapter(
    factory_result: Mapping[str, Any],
    capability_ports: Mapping[str, Any],
) -> None:
    """Install the conditional UI lane only when a deployment opts in.

    ``USFR_PORT_FACTORY`` remains the deployment authority for both renderer
    implementations and the immutable activation receipt.  This package does
    not install Remotion or create a renderer itself.  A factory can return a
    ``remotion_react_ui`` object with its candidate ``renderer`` and its
    verified ``capabilities`` record; the existing UI renderer is then wrapped
    before worker capability validation.  Without that explicit object the
    deterministic renderer remains untouched.
    """

    configuration = factory_result.get("remotion_react_ui")
    if configuration is None:
        return
    if not isinstance(configuration, Mapping):
        raise PackagedFactoryError("remotion_react_ui factory configuration must be an object")
    renderer = configuration.get("renderer")
    capabilities = configuration.get("capabilities")
    if not callable(renderer) or not isinstance(capabilities, Mapping):
        raise PackagedFactoryError(
            "remotion_react_ui configuration requires a callable renderer and capability records"
        )
    ui_capability = capability_ports.get("ocr_ui_renderer")
    concrete_ui_renderer = getattr(ui_capability, "adapter", ui_capability)
    replace = getattr(concrete_ui_renderer, "replace_render_backend", None)
    fallback = getattr(concrete_ui_renderer, "render_backend", None)
    if not callable(replace) or not callable(fallback):
        raise PackagedFactoryError(
            "remotion_react_ui requires an ocr_ui_renderer with a replaceable deterministic video backend"
        )
    from .remotion_react_ui import ConditionalUiRenderBackend

    replace(
        ConditionalUiRenderBackend(
            fallback_renderer=fallback,
            remotion_renderer=renderer,
            capabilities=capabilities,
        )
    )


def _ports(*, readiness_only: bool) -> tuple[dict[str, Any], dict[str, Any], Any, Any]:
    spec = (os.getenv(PORT_FACTORY_ENV, "") or "").strip()
    if spec:
        result = _load_port_factory(spec)
        stage_ports = dict(result.get("stage_ports") or {})
        capability_ports = dict(result.get("capability_ports") or {})
        invocation_adapter = result.get("invocation_adapter")
        recovery_bridge = result.get("recovery_bridge")
        _configure_optional_remotion_ui_adapter(result, capability_ports)
    elif readiness_only:
        stage_ports = {stage: _ReadinessOnlyPort(stage) for stage in EXECUTABLE_STAGES}
        capability_ports = {name: _ReadinessOnlyPort(name) for name in REQUIRED_CAPABILITIES}
        invocation_adapter = None
        recovery_bridge = None
    else:
        raise PackagedFactoryError(
            f"{PORT_FACTORY_ENV} port factory is required outside explicit readiness-only mode"
        )
    missing_stages = sorted(set(EXECUTABLE_STAGES) - set(stage_ports))
    missing_capabilities = sorted(set(REQUIRED_CAPABILITIES) - set(capability_ports))
    if missing_stages or missing_capabilities:
        raise PackagedFactoryError(
            "deployment port factory is incomplete: "
            f"stages={missing_stages}, capabilities={missing_capabilities}"
        )
    return stage_ports, capability_ports, invocation_adapter, recovery_bridge


def _capability_secret(value: bytes | None) -> bytes:
    if value is not None:
        secret = value
    else:
        raw = (os.getenv("USFR_CAPABILITY_SECRET", "") or "").encode("utf-8")
        secret = raw
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise PackagedFactoryError("USFR_CAPABILITY_SECRET must contain at least 32 UTF-8 bytes")
    return secret


def build_runtime(
    *,
    redis_client: Any | None = None,
    s3_client: Any | None = None,
    bucket: str | None = None,
    capability_secret: bytes | None = None,
    readiness_only: bool | None = None,
) -> DeploymentRuntime:
    """Build the shared runtime from environment or injected integration fakes."""

    if redis_client is None:
        try:
            import redis

            redis_client = redis.Redis.from_url(
                os.getenv("USFR_REDIS_URL", "redis://redis:6379/0"),
                decode_responses=False,
            )
        except Exception as exc:
            raise PackagedFactoryError("Redis client could not be constructed") from exc
    if s3_client is None:
        try:
            import boto3

            endpoint = (os.getenv("USFR_S3_ENDPOINT", "") or "").strip() or None
            s3_client = boto3.client("s3", endpoint_url=endpoint)
        except Exception as exc:
            raise PackagedFactoryError("S3 client could not be constructed") from exc
    bucket = (bucket or os.getenv("USFR_S3_BUCKET", "usfr-media")).strip()
    readiness_only = _truthy(os.getenv(READINESS_ONLY_ENV)) if readiness_only is None else readiness_only
    if not isinstance(readiness_only, bool):
        raise PackagedFactoryError("readiness_only must be boolean")

    package_root = Path(__file__).resolve().parents[1]
    resolver = ImmutableBundleResolver.from_package_manifest(
        package_root / "references" / "runtime_skill_manifest.json",
        package_root=package_root,
    )
    stage_ports, capability_ports, invocation_adapter, recovery_bridge = _ports(
        readiness_only=readiness_only
    )
    job_store = RedisEphemeralJobStore(redis_client)
    work_queue = RedisWorkQueue(redis_client)
    stage_driver = EphemeralStageDriver(job_store, work_queue)
    object_store = S3ObjectStore(s3_client, bucket=bucket)
    temporary_store = TemporaryMediaStore(object_store)
    upload_store = UploadMediaStore(object_store)
    final_store = FinalVideoStore(object_store)
    materializer = MediaMaterializer(_S3MediaReader(object_store, s3_client, bucket))
    worker_manager = EphemeralWorkerManager(
        job_store=job_store,
        temporary_store=temporary_store,
        stage_ports=stage_ports,
        profile_bundle_resolver=resolver,
        capability_ports=capability_ports,
        materializer=materializer,
        invocation_adapter=invocation_adapter,
        recovery_bridge=recovery_bridge,
        stage_driver=stage_driver,
        final_store=final_store,
    )
    secret = _capability_secret(capability_secret)
    service = create_app(
        job_store=job_store,
        capability_secret=secret,
        object_store=object_store,
        stage_driver=stage_driver,
    )
    cleanup_sweeper = CleanupSweeper(
        redis_client,
        temporary_store,
        final_store,
        upload_store=upload_store,
    )

    def redis_ready() -> bool:
        return redis_client.ping() is True

    def object_store_ready() -> bool:
        try:
            s3_client.head_bucket(Bucket=bucket)
            return True
        except Exception:
            return False

    def bundle_ready() -> bool:
        return resolver.immutable is True

    def ports_ready() -> bool:
        try:
            worker_manager.validate_startup_capabilities()
            return True
        except Exception:
            return False

    return DeploymentRuntime(
        job_store=job_store,
        work_queue=work_queue,
        object_store=object_store,
        cleanup_sweeper=cleanup_sweeper,
        service=service,
        worker_manager=worker_manager,
        readiness_checks={
            "redis": redis_ready,
            "object_store": object_store_ready,
            "bundle": bundle_ready,
            "models": ports_ready,
            "capabilities": ports_ready,
            "provider": ports_ready,
        },
        profile_mode=(os.getenv("USFR_PROFILE_MODE", "shadow") or "shadow").strip().casefold(),
    )


__all__ = ["PackagedFactoryError", "build_runtime"]
