from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ui_sidecar_lifecycle_module_is_declared_as_runtime_without_dependencies() -> None:
    manifest = json.loads((ROOT / "references" / "bundle_manifest.json").read_text(encoding="utf-8"))
    declared = {
        item.get("path")
        for item in manifest.get("runtime_files", [])
        if isinstance(item, dict)
    }

    assert "server/ui_sidecar_runtime.py" in declared
    assert all("node_modules" not in str(path) and ".venv" not in str(path) for path in declared)


def test_bundle_verifier_requires_the_ui_sidecar_lifecycle_module() -> None:
    path = ROOT / "scripts" / "verify_bundle.py"
    spec = importlib.util.spec_from_file_location("test_verify_bundle", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "server/ui_sidecar_runtime.py" in module.REQUIRED_SERVER_FILES
