"""Immutable, package-relative dependency resolution for deployed workers.

The public replication API never receives Skill paths.  Production workers
inject an :class:`ImmutableBundleResolver` built from verified bundle bytes and
package-relative metadata. Production code exposes no resolver for client or
workstation paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_~-]{0,127}$")
_PRIVATE_OBJECT_SCHEMES = ("s3://", "gs://", "az://", "azure://", "artifact://")


class BundleResolverError(ValueError):
    """Raised when an immutable bundle cannot be trusted or resolved."""


def _safe_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BundleResolverError("bundle dependency name must be a non-empty string")
    return value.strip()


def _safe_package_path(value: Any) -> str:
    if not isinstance(value, str):
        raise BundleResolverError("bundle dependency package_path must be a relative string")
    raw = value.replace("\\", "/")
    parts = raw.split("/")
    if (
        not raw
        or raw.startswith(("/", "./", "../"))
        or any(part in {"", ".", ".."} for part in parts)
        or ":" in parts[0]
        or _PACKAGE_PATH.fullmatch(raw) is None
    ):
        raise BundleResolverError("bundle dependency package_path must be safe and relative")
    return raw


def _frontmatter_version(name: str, payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleResolverError(f"bundle dependency {name} is not UTF-8 text") from exc
    match = re.search(r"(?m)^\s*version:\s*[\"']?([^\"'#\s]+)", text[:12000])
    version = match.group(1).strip() if match else "unknown"
    if version != "unknown" and _VERSION.fullmatch(version) is None:
        raise BundleResolverError(f"bundle dependency {name} version is invalid")
    return version


def _packaged_skill_bytes(path: Path, payload: bytes) -> bytes:
    """Return the canonical bytes for a text Skill in a source checkout.

    Runtime Skill manifests are generated from LF package bytes.  Windows Git
    checkouts may materialize the same UTF-8 Markdown with CRLF, so package
    loading normalizes only newline pairs for ``.md`` Skill files before the
    immutable resolver verifies and snapshots them.  Object-store bundles stay
    byte-exact through :meth:`from_object_resolver`.
    """

    return payload.replace(b"\r\n", b"\n") if path.suffix.lower() == ".md" else payload


@dataclass(frozen=True)
class BundleEntry:
    """Read-only virtual file backed by immutable bytes, never a host path."""

    name: str
    version: str
    package_path: str
    _payload: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self._payload).hexdigest()

    @property
    def immutable(self) -> bool:
        return True

    def read_bytes(self) -> bytes:
        return self._payload

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._payload.decode(encoding)

    def is_file(self) -> bool:
        return True


class ImmutableBundleResolver:
    """Resolve package dependencies from a verified immutable byte bundle.

    ``entries`` accepts ``name -> {bytes, version, package_path}`` records or
    ``name -> bytes`` values.  Path-like values are intentionally rejected so a
    production process cannot accidentally depend on ``~/.codex`` or a client
    workstation.  The resulting mapping and byte payloads are immutable.
    """

    immutable = True
    source = "immutable_bundle"

    @classmethod
    def from_object_resolver(cls, object_resolver: Any, manifest: Mapping[str, Any]) -> "ImmutableBundleResolver":
        """Build a resolver from a server-side immutable object reader.

        ``object_resolver`` must expose ``read_bytes(object_key)`` (or be a
        callable accepting the object key).  The manifest contains only logical
        dependency names and private object keys; no client path is accepted.
        Bytes are copied and hash-checked before the resolver is returned.
        """

        if not isinstance(manifest, Mapping) or not manifest:
            raise BundleResolverError("immutable bundle manifest must be a non-empty mapping")
        entries: dict[str, dict[str, Any]] = {}
        reader = getattr(object_resolver, "read_bytes", None)
        if not callable(reader) and not callable(object_resolver):
            raise BundleResolverError("object resolver must expose read_bytes(object_key)")
        for raw_name, record in manifest.items():
            name = _safe_name(raw_name)
            if not isinstance(record, Mapping):
                raise BundleResolverError(f"bundle manifest entry {name} must be an object")
            object_key = record.get("object_key", record.get("uri"))
            if (
                not isinstance(object_key, str)
                or not object_key.strip()
                or object_key.startswith(("file://", "http://", "~", "/", "\\"))
                or re.match(r"^[A-Za-z]:[\\/]", object_key)
                or ("://" in object_key and not object_key.startswith(_PRIVATE_OBJECT_SCHEMES))
            ):
                raise BundleResolverError(f"bundle manifest entry {name} has an invalid object reference")
            payload = reader(object_key) if callable(reader) else object_resolver(object_key)
            if not isinstance(payload, bytes):
                raise BundleResolverError(f"object resolver returned non-bytes for {name}")
            entries[name] = {
                "bytes": payload,
                "version": record.get("version"),
                "package_path": record.get("package_path"),
                "sha256": record.get("sha256"),
            }
        return cls(entries)

    @classmethod
    def from_package_manifest(
        cls,
        manifest_path: str | Path,
        *,
        package_root: str | Path | None = None,
    ) -> "ImmutableBundleResolver":
        """Load and verify immutable Skill bytes from the deployed package.

        The manifest path is deployment configuration, not request data. Every
        dependency path must remain below the package root and every payload
        must match the manifest SHA before the resolver becomes usable.
        """

        manifest_file = Path(manifest_path).resolve()
        root = Path(package_root).resolve() if package_root is not None else manifest_file.parents[1]
        try:
            manifest_file.relative_to(root)
        except ValueError as exc:
            raise BundleResolverError("runtime Skill manifest must be inside the package root") from exc
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BundleResolverError("runtime Skill manifest cannot be read") from exc
        if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1:
            raise BundleResolverError("runtime Skill manifest schema_version must be 1")
        records = manifest.get("dependencies")
        if (
            not isinstance(records, list)
            or not records
            or any(not isinstance(record, Mapping) for record in records)
        ):
            raise BundleResolverError("runtime Skill manifest dependencies must be a non-empty list")
        entries: dict[str, dict[str, Any]] = {}
        for record in records:
            name = _safe_name(record.get("name"))
            if name in entries:
                raise BundleResolverError(f"runtime Skill manifest repeats dependency: {name}")
            package_path = _safe_package_path(record.get("package_path"))
            payload_path = (root / package_path).resolve()
            try:
                payload_path.relative_to(root)
            except ValueError as exc:
                raise BundleResolverError(f"runtime Skill dependency escapes package root: {name}") from exc
            try:
                payload = payload_path.read_bytes()
            except OSError as exc:
                raise BundleResolverError(f"runtime Skill dependency cannot be read: {name}") from exc
            payload = _packaged_skill_bytes(payload_path, payload)
            entries[name] = {
                "bytes": payload,
                "version": record.get("version"),
                "package_path": package_path,
                "sha256": record.get("sha256"),
            }
        return cls(entries)

    def __init__(self, entries: Mapping[str, Any]) -> None:
        if not isinstance(entries, Mapping) or not entries:
            raise BundleResolverError("immutable bundle entries must be a non-empty mapping")
        normalised: dict[str, BundleEntry] = {}
        for raw_name, raw_value in entries.items():
            name = _safe_name(raw_name)
            if isinstance(raw_value, Path) or isinstance(raw_value, str):
                raise BundleResolverError(f"bundle dependency {name} cannot be a client/local path")
            supplied_version: Any = None
            supplied_package_path: Any = None
            supplied_sha: Any = None
            value = raw_value
            if isinstance(raw_value, Mapping):
                if any(key in raw_value for key in ("path", "file", "source")):
                    raise BundleResolverError(f"bundle dependency {name} cannot be a client/local path")
                value = raw_value.get("bytes", raw_value.get("data", raw_value.get("content")))
                supplied_version = raw_value.get("version")
                supplied_package_path = raw_value.get("package_path", raw_value.get("path_in_package"))
                supplied_sha = raw_value.get("sha256")
            if isinstance(value, (bytearray, memoryview)):
                raise BundleResolverError(f"bundle dependency {name} must use immutable bytes")
            if not isinstance(value, bytes):
                raise BundleResolverError(f"bundle dependency {name} must provide bytes")
            payload = bytes(value)
            if not payload:
                raise BundleResolverError(f"bundle dependency {name} cannot be empty")
            digest = hashlib.sha256(payload).hexdigest()
            if supplied_sha is not None and (not isinstance(supplied_sha, str) or not _SHA256.fullmatch(supplied_sha) or supplied_sha != digest):
                raise BundleResolverError(f"bundle dependency {name} SHA-256 does not match bytes")
            version = str(supplied_version or _frontmatter_version(name, payload)).strip()
            if not version or _VERSION.fullmatch(version) is None:
                raise BundleResolverError(f"bundle dependency {name} version is invalid")
            package_path = supplied_package_path or f"dependencies/{name}/SKILL.md"
            package_path = _safe_package_path(package_path)
            normalised[name] = BundleEntry(name, version, package_path, payload)
        self.entries = MappingProxyType(normalised)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.entries))

    def get(self, name: str) -> BundleEntry:
        try:
            return self.entries[_safe_name(name)]
        except KeyError as exc:
            raise BundleResolverError(f"bundle dependency is missing: {name}") from exc

    # ``resolve`` is the deployment-facing spelling; ``get`` remains a small
    # convenience for adapters and tests.
    resolve = get

    def get_bytes(self, name: str) -> bytes:
        return self.get(name).read_bytes()

    read_bytes = get_bytes

    def get_text(self, name: str, encoding: str = "utf-8") -> str:
        return self.get(name).read_text(encoding)

    def metadata(self, name: str) -> dict[str, str]:
        entry = self.get(name)
        return {
            "name": entry.name,
            "version": entry.version,
            "package_path": entry.package_path,
            "sha256": entry.sha256,
        }

    def skill_files(self, names: Any = None) -> Mapping[str, BundleEntry]:
        requested = self.names() if names is None else tuple(_safe_name(item) for item in names)
        return MappingProxyType({name: self.get(name) for name in requested})

    def dependency_records(self) -> Mapping[str, Mapping[str, Any]]:
        return MappingProxyType({
            name: MappingProxyType({
                "bytes": entry.read_bytes(),
                "version": entry.version,
                "package_path": entry.package_path,
                "sha256": entry.sha256,
            })
            for name, entry in self.entries.items()
        })


__all__ = [
    "BundleEntry",
    "BundleResolverError",
    "ImmutableBundleResolver",
]
