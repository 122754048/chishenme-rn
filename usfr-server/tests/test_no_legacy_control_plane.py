from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "server/ephemeral_service.py",
    "server/ephemeral_driver.py",
    "server/ephemeral_worker.py",
    "server/worker_entrypoint.py",
    "server/intake.py",
    "server/fastapi_router.py",
    "server/deployment_bootstrap.py",
)


def test_runtime_call_sites_use_only_ephemeral_job_control() -> None:
    forbidden = (
        "from .repository import",
        "SQLiteRepository",
        "tenant_id",
        "actor_resolver",
        "outbox",
        "server/migrations",
        "from .service import",
        "from .driver import",
        "from .worker import",
        "from .runtime import",
    )
    violations: list[str] = []
    for relative in RUNTIME_FILES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        violations.extend(f"{relative}:{token}" for token in forbidden if token in text)
    assert violations == []


def test_production_entrypoints_use_ephemeral_modules() -> None:
    router = (ROOT / "server" / "fastapi_router.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "server" / "deployment_bootstrap.py").read_text(encoding="utf-8")
    assert "from .ephemeral_service import ReplicationService" in router
    assert "process_work_message" in bootstrap
