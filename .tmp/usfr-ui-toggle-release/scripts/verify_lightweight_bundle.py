"""Fail closed when non-video product or workstation state enters the bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


FORBIDDEN_PATHS = (
    "server/repository.py",
    "server/service.py",
    "server/driver.py",
    "server/worker.py",
    "server/runtime.py",
    "server/models.py",
    "server/state_machine.py",
    "server/migrations",
    "replication-v1.db",
    "schemas/run.schema.json",
    "schemas/event.schema.json",
    "references/event-contract.md",
    "references/persistence-contract.md",
    "BASELINE.md",
)

FORBIDDEN_DIRECTORY_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "validation_runs",
}

FORBIDDEN_RUNTIME_PATTERNS = {
    "tenant resolver": re.compile(r"\btenant_resolver\b"),
    "actor resolver": re.compile(r"\bactor_resolver\b"),
    "SQLite repository": re.compile(r"\bSQLiteRepository\b"),
    "Outbox events": re.compile(r"\boutbox_events\b", re.IGNORECASE),
    "workstation path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]", re.IGNORECASE),
    "home Skill resolver": re.compile(r"(?:Path\.home|expanduser)\s*\([^)]*\)[^\n]*\.codex", re.IGNORECASE),
    "legacy events route": re.compile(r"[\"']/events(?:[/?\"']|$)", re.IGNORECASE),
}

SCANNED_RUNTIME_SUFFIXES = {".py", ".json", ".toml", ".yaml", ".yml"}


def _runtime_paths(root: Path, manifest: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for item in manifest.get("runtime_files", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        relative = item["path"].replace("\\", "/")
        if relative.startswith("/") or ".." in relative.split("/"):
            continue
        path = root / relative
        if path.is_file():
            paths.append(path)
    return paths


def verify_lightweight_bundle(root: Path) -> list[str]:
    root = root.resolve()
    failures: list[str] = []

    manifest_path = root / "references" / "bundle_manifest.json"
    if not manifest_path.is_file():
        return [f"missing bundle manifest: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid bundle manifest: {exc}"]
    if not isinstance(manifest, dict):
        return ["invalid bundle manifest: root must be an object"]

    for relative in FORBIDDEN_PATHS:
        if (root / relative).exists():
            failures.append(f"forbidden lightweight path: {relative}")

    for path in root.rglob("*"):
        if path.is_dir() and path.name in FORBIDDEN_DIRECTORY_NAMES:
            failures.append(
                f"forbidden generated directory: {path.relative_to(root).as_posix()}"
            )

    for path in _runtime_paths(root, manifest):
        if path.suffix.casefold() not in SCANNED_RUNTIME_SUFFIXES and path.name != "Dockerfile":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for label, pattern in FORBIDDEN_RUNTIME_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"forbidden {label} in runtime file: {relative}")

    return sorted(set(failures))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that the deployable bundle contains video-only runtime capability."
    )
    parser.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    failures = verify_lightweight_bundle(args.root)
    if failures:
        raise SystemExit("\n".join(failures))
    print("lightweight bundle is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
