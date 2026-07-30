"""Packaged Redis/S3 deployment factory for API, Worker, and Sweeper."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import shutil
from typing import Any, Mapping

from .bundle_resolver import ImmutableBundleResolver
from .aliyun_oss_final_store import AliyunOssFinalStore
from .capabilities import REQUIRED_CAPABILITIES
from .cleanup import CleanupSweeper
from .deployment_bootstrap import DeploymentRuntime
from .ephemeral_driver import EXECUTABLE_STAGES, EphemeralStageDriver
from .ephemeral_worker import EphemeralWorkerManager
from .public_fastapi_router import create_public_app
from .media_materializer import MediaMaterializer
from .object_store import FinalVideoStore, S3ObjectStore, TemporaryMediaStore, UploadMediaStore
from .redis_job_store import RedisEphemeralJobStore
from .redis_streams import RedisWorkQueue


PORT_FACTORY_ENV = "USFR_PORT_FACTORY"
READINESS_ONLY_ENV = "USFR_READINESS_ONLY"
UI_SIDECAR_ENABLED_ENV = "USFR_UI_SIDECAR_ENABLED"
UI_REBUILD_ENABLED_ENV = "USFR_UI_REBUILD_ENABLED"


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


def _validate_ui_rebuild_switch() -> bool:
    """Validate the deployment-wide automatic UI rebuild switch.

    A bad value must stop startup instead of silently turning on an expensive
    renderer. Explicit UI screenshots and official store URLs remain enabled
    per-run by the intake route even when this switch is false.
    """

    raw = (os.getenv(UI_REBUILD_ENABLED_ENV, "") or "").strip().casefold()
    if not raw:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise PackagedFactoryError(
        f"{UI_REBUILD_ENABLED_ENV} must be true/false; received {raw!r}"
    )


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


def _configure_optional_local_ui_sidecar(capability_ports: Mapping[str, Any]) -> None:
    """Register the independent local Sidecar without starting its process."""

    if not _truthy(os.getenv(UI_SIDECAR_ENABLED_ENV)):
        return
    project_dir = Path(os.environ["USFR_UI_SIDECAR_PROJECT_DIR"]).resolve()
    if not project_dir.is_dir():
        raise PackagedFactoryError("USFR_UI_SIDECAR_PROJECT_DIR is unavailable")
    try:
        startup_timeout = float(os.getenv("USFR_UI_SIDECAR_STARTUP_TIMEOUT_SECONDS", "90"))
    except ValueError as exc:
        raise PackagedFactoryError("USFR_UI_SIDECAR_STARTUP_TIMEOUT_SECONDS is invalid") from exc
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise PackagedFactoryError("npm is required to start the local UI Sidecar")
    try:
        from .ui_sidecar_runtime import OnDemandUiSidecarRenderer
        from .vision_backends import EvidenceBoundHttpUiRenderer

        renderer = EvidenceBoundHttpUiRenderer(
            endpoint=os.environ["USFR_UI_RENDER_ENDPOINT"],
            model_id=os.environ["USFR_UI_RENDER_MODEL_ID"],
            model_sha256=os.environ["USFR_UI_RENDER_MODEL_SHA256"],
            api_token_env="USFR_UI_RENDER_API_TOKEN",
            timeout_seconds=float(os.getenv("USFR_UI_RENDER_TIMEOUT_SECONDS", "300")),
            max_response_bytes=int(os.getenv("USFR_UI_RENDER_MAX_RESPONSE_BYTES", str(128 * 1024 * 1024))),
            production=False,
        )
        wrapper = OnDemandUiSidecarRenderer(
            renderer=renderer,
            command=[npm, "run", "start", "--silent"],
            project_dir=project_dir,
            startup_timeout_seconds=startup_timeout,
            startup_lock_path=project_dir / ".runtime" / "sidecar-startup.lock",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PackagedFactoryError("local UI Sidecar configuration is incomplete") from exc
    ui_capability = capability_ports.get("ocr_ui_renderer")
    concrete_ui_renderer = getattr(ui_capability, "adapter", ui_capability)
    replace = getattr(concrete_ui_renderer, "replace_render_backend", None)
    if not callable(replace):
        raise PackagedFactoryError(
            "local UI Sidecar requires an ocr_ui_renderer with a replaceable video backend"
        )
    replace(wrapper)


def _ports(*, readiness_only: bool) -> tuple[dict[str, Any], dict[str, Any], Any, Any]:
    spec = (os.getenv(PORT_FACTORY_ENV, "") or "").strip()
    final_store_factory = None
    if spec:
        result = _load_port_factory(spec)
        stage_ports = dict(result.get("stage_ports") or {})
        capability_ports = dict(result.get("capability_ports") or {})
        invocation_adapter = result.get("invocation_adapter")
        recovery_bridge = result.get("recovery_bridge")
        final_store_factory = result.get("final_store_factory")
        if final_store_factory is not None and not callable(final_store_factory):
            raise PackagedFactoryError("final_store_factory must be callable")
        _configure_optional_remotion_ui_adapter(result, capability_ports)
    elif readiness_only:
        stage_ports = {stage: _ReadinessOnlyPort(stage) for stage in EXECUTABLE_STAGES}
        capability_ports = {name: _ReadinessOnlyPort(name) for name in REQUIRED_CAPABILITIES}
        invocation_adapter = None
        recovery_bridge = None
    else:
        # The distribution is self-contained: a normal deployment must never
        # import a user workstation module just to obtain its video ports.
        # Advanced operators can still supply an explicit packaged override.
        try:
            from .packaged_ports import build_ports

            result = build_ports()
        except Exception as exc:
            raise PackagedFactoryError("packaged production port factory could not be loaded") from exc
        stage_ports = dict(result.get("stage_ports") or {})
        capability_ports = dict(result.get("capability_ports") or {})
        invocation_adapter = result.get("invocation_adapter")
        recovery_bridge = result.get("recovery_bridge")
    if not readiness_only:
        _configure_optional_local_ui_sidecar(capability_ports)
    missing_stages = sorted(set(EXECUTABLE_STAGES) - set(stage_ports))
    missing_capabilities = sorted(set(REQUIRED_CAPABILITIES) - set(capability_ports))
    if missing_stages or missing_capabilities:
        raise PackagedFactoryError(
            "deployment port factory is incomplete: "
            f"stages={missing_stages}, capabilities={missing_capabilities}"
        )
    return stage_ports, capability_ports, invocation_adapter, recovery_bridge, final_store_factory


def _capability_secret(value: bytes | None) -> bytes:
    if value is not None:
        secret = value
    else:
        raw = (os.getenv("USFR_CAPABILITY_SECRET", "") or "").encode("utf-8")
        secret = raw
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise PackagedFactoryError("USFR_CAPABILITY_SECRET must contain at least 32 UTF-8 bytes")
    return secret


def _integer_environment(name: str, default: int, *, minimum: int) -> int:
    raw = (os.getenv(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise PackagedFactoryError(f"{name} must be an integer") from exc
    if value < minimum:
        raise PackagedFactoryError(f"{name} must be at least {minimum}")
    return value


def build_runtime(
    *,
    redis_client: Any | None = None,
    s3_client: Any | None = None,
    bucket: str | None = None,
    oss_bucket: Any | None = None,
    oss_public_base_url: str | None = None,
    capability_secret: bytes | None = None,
    readiness_only: bool | None = None,
) -> DeploymentRuntime:
    """Build the shared runtime from environment or injected integration fakes."""

    _validate_ui_rebuild_switch()

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
    stage_ports, capability_ports, invocation_adapter, recovery_bridge, final_store_factory = _ports(
        readiness_only=readiness_only
    )
    job_store = RedisEphemeralJobStore(redis_client)
    work_queue = RedisWorkQueue(redis_client)
    stage_driver = EphemeralStageDriver(job_store, work_queue)
    object_store = S3ObjectStore(s3_client, bucket=bucket)
    temporary_store = TemporaryMediaStore(object_store)
    upload_store = UploadMediaStore(object_store)
    if final_store_factory is not None:
        try:
            final_store = final_store_factory(
                internal_store=object_store,
                s3_client=s3_client,
                bucket=bucket,
            )
        except Exception as exc:
            raise PackagedFactoryError("deployment final-store factory could not be constructed") from exc
        required_final_methods = ("promote", "delete_job", "has_final", "validate_final_ref")
        if any(not callable(getattr(final_store, method, None)) for method in required_final_methods):
            raise PackagedFactoryError("deployment final-store factory returned an incomplete store")
    elif readiness_only:
        final_store = FinalVideoStore(object_store)
    else:
        public_base_url = (
            oss_public_base_url
            or os.getenv("USFR_OSS_PUBLIC_BASE_URL", "")
            or ""
        ).strip()
        if oss_bucket is None:
            try:
                import oss2

                auth = oss2.Auth(
                    os.environ["USFR_OSS_ACCESS_KEY_ID"],
                    os.environ["USFR_OSS_ACCESS_KEY_SECRET"],
                )
                oss_bucket = oss2.Bucket(
                    auth,
                    os.environ["USFR_OSS_ENDPOINT"],
                    os.environ["USFR_OSS_BUCKET"],
                )
            except Exception as exc:
                raise PackagedFactoryError("Alibaba OSS final store could not be constructed") from exc
        try:
            final_store = AliyunOssFinalStore(
                internal_store=object_store,
                bucket=oss_bucket,
                public_base_url=public_base_url,
                final_prefix=os.getenv("USFR_OSS_FINAL_PREFIX", "usfr"),
            )
        except (TypeError, ValueError) as exc:
            raise PackagedFactoryError("Alibaba OSS final store configuration is invalid") from exc
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
    job_ttl_seconds = _integer_environment(
        "USFR_JOB_TERMINAL_TTL_SECONDS",
        7 * 24 * 60 * 60,
        minimum=1,
    )
    temporary_retention_seconds = _integer_environment(
        "USFR_TEMPORARY_RETENTION_SECONDS",
        0,
        minimum=0,
    )
    service = create_public_app(
        job_store=job_store,
        capability_secret=secret,
        object_store=object_store,
        stage_driver=stage_driver,
        ttl_seconds=job_ttl_seconds,
    )
    cleanup_sweeper = CleanupSweeper(
        redis_client,
        temporary_store,
        final_store,
        upload_store=upload_store,
        temporary_retention_seconds=temporary_retention_seconds,
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
