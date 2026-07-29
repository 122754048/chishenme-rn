from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_lightweight_bundle import verify_lightweight_bundle
from scripts import verify_bundle as bundle_verifier


ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path: Path, relative: str, content: str = "") -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    manifest = tmp_path / "references" / "bundle_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"runtime_files": [{"path": relative}]}), encoding="utf-8"
    )
    return tmp_path


@pytest.mark.parametrize(
    "relative",
    (
        "server/repository.py",
        "server/migrations/001_initial.sql",
        "replication-v1.db",
        "schemas/event.schema.json",
        "references/event-contract.md",
    ),
)
def test_verifier_rejects_legacy_control_plane_files(
    tmp_path: Path, relative: str
) -> None:
    failures = verify_lightweight_bundle(_fixture(tmp_path, relative))
    expected = "server/migrations" if relative.startswith("server/migrations/") else relative
    assert any(expected in failure.replace("\\", "/") for failure in failures)


@pytest.mark.parametrize(
    "token",
    (
        "tenant_resolver",
        "actor_resolver",
        "SQLiteRepository",
        "outbox_events",
        'Path("C:\\\\Users\\\\client\\\\video.mp4")',
        'Path.home() / ".codex" / "skills"',
        '@app.get("/events")',
    ),
)
def test_verifier_rejects_product_state_and_workstation_dependencies(
    tmp_path: Path, token: str
) -> None:
    failures = verify_lightweight_bundle(
        _fixture(tmp_path, "server/runtime_adapter.py", token)
    )
    assert failures


def test_verifier_rejects_generated_cache_directories(tmp_path: Path) -> None:
    root = _fixture(tmp_path, "server/runtime_adapter.py", "video only")
    cache = root / "server" / "__pycache__"
    cache.mkdir()
    (cache / "runtime_adapter.pyc").write_bytes(b"cache")
    assert any("__pycache__" in failure for failure in verify_lightweight_bundle(root))


def test_paid_provider_wording_is_not_a_payment_system_violation(
    tmp_path: Path,
) -> None:
    root = _fixture(
        tmp_path,
        "server/provider_adapter.py",
        "paid request idempotency prevents duplicate video generation tasks",
    )
    assert verify_lightweight_bundle(root) == []


def test_current_deployable_bundle_is_lightweight() -> None:
    assert verify_lightweight_bundle(ROOT) == []


def test_primary_bundle_verifier_composes_lightweight_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        bundle_verifier,
        "verify_lightweight_bundle",
        lambda _root: ["synthetic lightweight violation"],
        raising=False,
    )
    assert "synthetic lightweight violation" in bundle_verifier.verify_bundle(ROOT)


def test_lightweight_verifier_is_declared_as_runtime_release_tool() -> None:
    manifest = json.loads(
        (ROOT / "references" / "bundle_manifest.json").read_text(encoding="utf-8")
    )
    declared = {item["path"] for item in manifest["runtime_files"]}
    assert "scripts/verify_lightweight_bundle.py" in declared
