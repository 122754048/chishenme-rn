from __future__ import annotations

from collections.abc import Mapping
import importlib
import os
from pathlib import Path
import sys
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..config import settings


_RUNTIME_FACTORY_ENV = "REPLICATION_RUNTIME_FACTORY"
_RUNTIME_KEYS = frozenset(
    {"job_store", "object_store", "stage_driver", "capability_secret", "commercial_batch_runtime"}
)


def _skill_root() -> Path:
    configured = os.getenv("UNIVERSAL_SOURCE_FIDELITY_SKILL_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "usfr-server"


def _production_runtime() -> bool:
    return settings.env.lower() in {"prod", "production"}


def _load_runtime_factory() -> dict[str, Any]:
    factory_path = (os.getenv(_RUNTIME_FACTORY_ENV) or "").strip()
    if not factory_path:
        return {}
    module_name, separator, attribute_name = factory_path.partition(":")
    if not separator or not module_name.strip() or not attribute_name.strip():
        raise RuntimeError(f"{_RUNTIME_FACTORY_ENV} must use the module:callable format")
    try:
        factory = getattr(importlib.import_module(module_name.strip()), attribute_name.strip())
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(f"cannot load {_RUNTIME_FACTORY_ENV} {factory_path!r}") from exc
    if not callable(factory):
        raise RuntimeError(f"{_RUNTIME_FACTORY_ENV} must resolve to a callable")
    runtime = factory()
    if not isinstance(runtime, Mapping):
        raise RuntimeError(f"{_RUNTIME_FACTORY_ENV} must return a mapping")
    unknown = set(runtime) - _RUNTIME_KEYS
    if unknown:
        raise RuntimeError(
            f"{_RUNTIME_FACTORY_ENV} returned unsupported keys: " + ", ".join(sorted(unknown))
        )
    return dict(runtime)


def load_runtime_dependencies() -> dict[str, Any]:
    """Load deployment-only dependencies without changing the USFR Skill API."""

    return _load_runtime_factory()


def _require_durable_runtime(
    *,
    job_store: Any,
    object_store: Any,
    stage_driver: Any,
    capability_secret: bytes | None,
) -> None:
    missing = [
        name
        for name, value in (
            ("job_store", job_store),
            ("object_store", object_store),
            ("stage_driver", stage_driver),
        )
        if value is None
    ]
    if missing:
        raise RuntimeError(
            "standard USFR runtime requires durable " + ", ".join(missing)
        )
    if not isinstance(capability_secret, bytes) or len(capability_secret) < 32:
        raise RuntimeError("standard USFR runtime requires a 32-byte capability_secret")


def _load_canonical_router():
    root = _skill_root()
    if not (root / "server" / "fastapi_router.py").is_file():
        raise RuntimeError(f"canonical universal source-fidelity server package is missing: {root}")
    root_string = str(root)
    if root_string not in sys.path:
        sys.path.insert(0, root_string)
    from server.fastapi_router import create_app

    return create_app


def _unavailable_replication_app() -> FastAPI:
    app = FastAPI(title="USFR Runtime Bridge")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def runtime_not_configured(_: Request, path: str) -> JSONResponse:
        del path
        return JSONResponse(
            status_code=503,
            content={
                "code": "USFR_RUNTIME_NOT_CONFIGURED",
                "message": "The standard USFR Redis/Object-Store runtime is not configured.",
            },
        )

    return app


def build_replication_app(
    *,
    job_store: Any = None,
    object_store: Any = None,
    stage_driver: Any = None,
    capability_secret: bytes | None = None,
    runtime_dependencies: Mapping[str, Any] | None = None,
) -> FastAPI:
    runtime = dict(runtime_dependencies) if runtime_dependencies is not None else _load_runtime_factory()
    job_store = job_store if job_store is not None else runtime.get("job_store")
    object_store = object_store if object_store is not None else runtime.get("object_store")
    stage_driver = stage_driver if stage_driver is not None else runtime.get("stage_driver")
    capability_secret = capability_secret if capability_secret is not None else runtime.get("capability_secret")

    if job_store is None and not _production_runtime():
        return _unavailable_replication_app()
    _require_durable_runtime(
        job_store=job_store,
        object_store=object_store,
        stage_driver=stage_driver,
        capability_secret=capability_secret,
    )
    create_app = _load_canonical_router()
    return create_app(
        job_store=job_store,
        object_store=object_store,
        stage_driver=stage_driver,
        capability_secret=capability_secret,
    )


def mount_replication_v2(
    app: FastAPI,
    *,
    job_store: Any = None,
    object_store: Any = None,
    stage_driver: Any = None,
    capability_secret: bytes | None = None,
    runtime_dependencies: Mapping[str, Any] | None = None,
) -> None:
    app.mount(
        "/api/v1/replication",
        build_replication_app(
            job_store=job_store,
            object_store=object_store,
            stage_driver=stage_driver,
            capability_secret=capability_secret,
            runtime_dependencies=runtime_dependencies,
        ),
        name="universal-source-fidelity-replication-bridge",
    )
