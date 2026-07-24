from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_runtime_has_no_workstation_skill_resolver_or_path() -> None:
    production_files = [
        *(ROOT / "server").rglob("*.py"),
        ROOT / "deployment" / "Dockerfile",
        ROOT / "deployment" / "docker-compose.yml",
        ROOT / "references" / "runtime_skill_manifest.json",
    ]
    forbidden = (
        "PathBundleResolver",
        "SEEDANCE20_SKILL_FILE",
        "C:\\Users",
        "Path.home() / \".codex\"",
        "expanduser() / \".codex\"",
    )
    violations: list[str] = []
    for path in production_files:
        if not path.is_file():
            violations.append(f"missing:{path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        violations.extend(
            f"{path.relative_to(ROOT)}:{token}"
            for token in forbidden
            if token in text
        )
    assert violations == []
