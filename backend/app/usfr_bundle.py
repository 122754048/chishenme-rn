"""Build and verify an immutable USFR deployment bundle outside runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path


class UsfrBundleError(ValueError):
    pass


MANIFEST_NAME = "usfr_bundle_manifest.json"
_REQUIRED_FILES = (
    "SKILL.md",
    "server/__init__.py",
    "references/runtime_skill_manifest.json",
    "runtime-skills/seedance-20/SKILL.md",
)
_REQUIRED_DIRECTORIES = ("bundled-skills", "scripts")


def build_usfr_bundle(
    *, source_root: Path, output_root: Path, expected_skill_sha256: str
) -> dict[str, object]:
    """Copy a complete, digest-bound USFR bundle for an image build context."""

    source = _source_root(source_root)
    expected = _sha256(expected_skill_sha256, "USFR_BUNDLE_SKILL_DIGEST_INVALID")
    skill_path = source / "SKILL.md"
    if _file_digest(skill_path) != expected:
        raise UsfrBundleError("USFR_BUNDLE_SKILL_DIGEST_MISMATCH")
    files = _source_files(source)
    receipt = _receipt(files, root=source, skill_sha256=expected)

    output = Path(output_root).resolve()
    if output == source or source in output.parents:
        raise UsfrBundleError("USFR_BUNDLE_OUTPUT_INSIDE_SOURCE")
    if output.exists():
        raise UsfrBundleError("USFR_BUNDLE_OUTPUT_EXISTS")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for entry in receipt["files"]:
            relative_path = entry["path"]
            destination = temporary / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative_path, destination)
        (temporary / MANIFEST_NAME).write_bytes(_canonical_json(receipt))
        verify_usfr_bundle(
            temporary,
            expected_skill_sha256=expected,
            expected_tree_sha256=receipt["source_tree_sha256"],
        )
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return receipt


def verify_usfr_bundle(
    bundle_root: Path,
    *,
    expected_skill_sha256: str,
    expected_tree_sha256: str,
) -> dict[str, object]:
    """Verify an image-ready USFR bundle against its immutable manifest."""

    root = Path(bundle_root).resolve()
    expected = _sha256(expected_skill_sha256, "USFR_BUNDLE_SKILL_DIGEST_INVALID")
    expected_tree = _sha256(expected_tree_sha256, "USFR_BUNDLE_TREE_DIGEST_INVALID")
    manifest_path = root / MANIFEST_NAME
    if not root.is_dir() or not manifest_path.is_file():
        raise UsfrBundleError("USFR_BUNDLE_MANIFEST_REQUIRED")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UsfrBundleError("USFR_BUNDLE_MANIFEST_INVALID") from error
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1:
        raise UsfrBundleError("USFR_BUNDLE_MANIFEST_INVALID")
    if manifest.get("skill_sha256") != expected:
        raise UsfrBundleError("USFR_BUNDLE_SKILL_DIGEST_MISMATCH")
    if manifest.get("source_tree_sha256") != expected_tree:
        raise UsfrBundleError("USFR_BUNDLE_TREE_DIGEST_MISMATCH")
    files = _manifest_files(manifest.get("files"))
    expected_receipt = _receipt(files, root=root, skill_sha256=expected)
    if manifest != expected_receipt:
        if manifest.get("files") != expected_receipt["files"]:
            raise UsfrBundleError("USFR_BUNDLE_FILE_DIGEST_MISMATCH")
        raise UsfrBundleError("USFR_BUNDLE_TREE_DIGEST_MISMATCH")
    actual_paths = _bundle_file_paths(root)
    manifest_paths = {entry["path"] for entry in files}
    if actual_paths != manifest_paths:
        raise UsfrBundleError("USFR_BUNDLE_FILE_SET_MISMATCH")
    _require_layout(root)
    return expected_receipt


def _source_root(value: Path) -> Path:
    root = Path(value).resolve()
    if not root.is_dir():
        raise UsfrBundleError("USFR_BUNDLE_SOURCE_ROOT_REQUIRED")
    _require_layout(root)
    return root


def _require_layout(root: Path) -> None:
    if any(not (root / relative_path).is_file() for relative_path in _REQUIRED_FILES):
        raise UsfrBundleError("USFR_BUNDLE_REQUIRED_FILE_MISSING")
    if any(not (root / relative_path).is_dir() for relative_path in _REQUIRED_DIRECTORIES):
        raise UsfrBundleError("USFR_BUNDLE_REQUIRED_DIRECTORY_MISSING")


def _source_files(root: Path) -> list[dict[str, object]]:
    paths = _bundle_file_paths(root)
    return [
        {
            "path": relative_path,
            "sha256": _file_digest(root / relative_path),
            "size_bytes": (root / relative_path).stat().st_size,
        }
        for relative_path in sorted(paths)
    ]


def _bundle_file_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for path in root.rglob("*"):
        if _is_ignored(path, root):
            continue
        if path.is_symlink():
            raise UsfrBundleError("USFR_BUNDLE_SYMLINK_FORBIDDEN")
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        if relative_path == MANIFEST_NAME:
            continue
        paths.add(relative_path)
    return paths


def _is_ignored(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}


def _manifest_files(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise UsfrBundleError("USFR_BUNDLE_MANIFEST_INVALID")
    files: list[dict[str, object]] = []
    paths: set[str] = set()
    for entry in value:
        if not isinstance(entry, Mapping):
            raise UsfrBundleError("USFR_BUNDLE_MANIFEST_INVALID")
        path = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("size_bytes")
        if (
            not isinstance(path, str)
            or not path
            or path in paths
            or path.startswith("/")
            or "\\" in path
            or ".." in Path(path).parts
            or _sha256(digest, "USFR_BUNDLE_MANIFEST_INVALID") != digest
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise UsfrBundleError("USFR_BUNDLE_MANIFEST_INVALID")
        paths.add(path)
        files.append({"path": path, "sha256": digest, "size_bytes": size})
    return files


def _receipt(
    files: Iterable[Mapping[str, object]], *, root: Path, skill_sha256: str
) -> dict[str, object]:
    normalized = [dict(entry) for entry in files]
    for entry in normalized:
        path = entry["path"]
        if not isinstance(path, str):
            raise UsfrBundleError("USFR_BUNDLE_MANIFEST_INVALID")
        candidate = root / path
        if not candidate.is_file() or candidate.is_symlink():
            raise UsfrBundleError("USFR_BUNDLE_FILE_DIGEST_MISMATCH")
        if entry.get("sha256") != _file_digest(candidate) or entry.get("size_bytes") != candidate.stat().st_size:
            raise UsfrBundleError("USFR_BUNDLE_FILE_DIGEST_MISMATCH")
    return {
        "schema_version": 1,
        "skill_sha256": skill_sha256,
        "source_tree_sha256": _tree_digest(normalized),
        "files": normalized,
    }


def _tree_digest(files: Iterable[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry in files:
        digest.update(str(entry["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry["sha256"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(entry["size_bytes"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256(value: object, error_code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise UsfrBundleError(error_code)
    return value


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an immutable USFR deployment bundle.")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--expected-skill-sha256", required=True)
    arguments = parser.parse_args(argv)
    try:
        receipt = build_usfr_bundle(
            source_root=Path(arguments.source_root),
            output_root=Path(arguments.output_root),
            expected_skill_sha256=arguments.expected_skill_sha256,
        )
    except UsfrBundleError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
