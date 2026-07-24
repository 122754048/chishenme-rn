"""Verified job-scoped materialization of private object-store media."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, BinaryIO, ContextManager, Mapping, Protocol
from urllib.parse import unquote

from .errors import ReplicationError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_MAX_BYTES = 512 * 1024 * 1024


class ObjectStoreMediaReader(Protocol):
    def head(self, object_key: str) -> Mapping[str, Any]: ...

    def open_stream(self, object_key: str) -> BinaryIO: ...


@dataclass(frozen=True)
class MaterializedMedia:
    path: Path
    job_id: str
    object_key: str
    sha256: str
    size_bytes: int
    content_type: str
    metadata: Mapping[str, Any]


def _fail(code: str, message: str, *, status: int = 422, retryable: bool = False, **details: Any) -> ReplicationError:
    return ReplicationError(code, message, category="artifact", retryable=retryable, details=details, http_status=status)


class MediaMaterializer:
    def __init__(self, reader: ObjectStoreMediaReader, *, max_bytes: int = _MAX_BYTES) -> None:
        self.reader = reader
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self.max_bytes = max_bytes

    @staticmethod
    def _validate_ref(*, job_id: str, object_key: str) -> None:
        if not isinstance(job_id, str) or _SAFE_SEGMENT.fullmatch(job_id) is None:
            raise _fail("OBJECT_KEY_INVALID", "job_id must be one safe path segment")
        if not isinstance(object_key, str) or object_key.startswith("/") or "\\" in object_key or any(ch in object_key for ch in "?#"):
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object key is unsafe")
        if len(object_key.encode("utf-8", "surrogatepass")) > 1024 or any(ord(ch) < 32 or ord(ch) == 127 or 0xD800 <= ord(ch) <= 0xDFFF for ch in object_key):
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object key is unsafe")
        decoded = unquote(object_key)
        if any(part in {"", ".", ".."} for part in decoded.split("/")) or any(ch in decoded for ch in "?#\\"):
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object key contains encoded traversal")
        parts = object_key.split("/")
        if any(not part or part in {".", ".."} for part in parts):
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object key is not normalized")
        temporary = len(parts) >= 3 and parts[0] == "temporary" and parts[1] == job_id
        final = parts == ["final", job_id, "result.mp4"]
        if not (temporary or final):
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object key is outside the job namespace")

    def _head(self, *, job_id: str, object_key: str, expected_sha256: str, expected_size_bytes: int | None) -> dict[str, Any]:
        try:
            observed = self.reader.head(object_key)
        except Exception as exc:
            raise _fail("OBJECT_STORE_UNAVAILABLE", "object metadata could not be read", retryable=True, object_key=object_key) from exc
        if not isinstance(observed, Mapping):
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object metadata is invalid")
        observed_key = str(observed.get("object_key") or observed.get("key") or observed.get("uri") or "").strip()
        observed_sha = str(observed.get("sha256") or "").lower()
        if observed_key != object_key or _SHA256.fullmatch(observed_sha) is None or observed_sha != expected_sha256:
            raise _fail(
                "ARTIFACT_METADATA_MISMATCH",
                "object metadata does not match the immutable reference",
                object_key=object_key,
                observed_object_key=observed_key,
                expected_sha256=expected_sha256,
                observed_sha256=observed_sha,
            )
        try:
            size = int(observed.get("size_bytes"))
        except (TypeError, ValueError) as exc:
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object size metadata is invalid", object_key=object_key) from exc
        if size < 0 or (expected_size_bytes is not None and size != expected_size_bytes):
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object size does not match the immutable reference", object_key=object_key)
        content_type = str(observed.get("content_type") or "").strip().lower()
        if not content_type:
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object content type is missing", object_key=object_key)
        status = str(observed.get("status") or "completed").lower()
        if status != "completed":
            raise _fail("ARTIFACT_METADATA_MISMATCH", "object is not complete", object_key=object_key)
        result = dict(observed)
        result.update({"object_key": object_key, "sha256": observed_sha, "size_bytes": size, "content_type": content_type})
        return result

    @staticmethod
    def _safe_work_dir(work_dir: Path | None) -> Path | None:
        if work_dir is None:
            return None
        parent = Path(work_dir)
        absolute = Path(os.path.abspath(parent))
        for ancestor in (absolute, *absolute.parents):
            if ancestor.is_symlink():
                raise _fail("DESTINATION_UNSAFE", "work directory must not contain symlink ancestors")
        parent.mkdir(parents=True, exist_ok=True)
        resolved = parent.resolve()
        if not resolved.is_dir():
            raise _fail("DESTINATION_UNSAFE", "work directory is not a directory")
        return resolved

    @staticmethod
    def _safe_filename(filename: str | None, object_key: str) -> str:
        value = filename or Path(object_key).name or "media.bin"
        if not isinstance(value, str) or "/" in value or "\\" in value or value in {".", ".."} or _SAFE_FILENAME.fullmatch(value) is None:
            raise _fail("DESTINATION_UNSAFE", "filename must be one safe path segment")
        return value

    @contextmanager
    def materialize(
        self,
        *,
        job_id: str,
        object_key: str,
        expected_sha256: str,
        expected_size_bytes: int | None = None,
        work_dir: Path | None = None,
        filename: str | None = None,
    ) -> ContextManager[MaterializedMedia]:
        expected_sha256 = str(expected_sha256 or "").lower()
        if _SHA256.fullmatch(expected_sha256) is None:
            raise _fail("ARTIFACT_HASH_MISMATCH", "expected_sha256 must be lowercase SHA-256")
        if expected_size_bytes is not None and (isinstance(expected_size_bytes, bool) or not isinstance(expected_size_bytes, int) or expected_size_bytes < 0):
            raise _fail("ARTIFACT_METADATA_MISMATCH", "expected_size_bytes must be a non-negative integer")
        self._validate_ref(job_id=job_id, object_key=object_key)
        observed = self._head(job_id=job_id, object_key=object_key, expected_sha256=expected_sha256, expected_size_bytes=expected_size_bytes)
        parent = self._safe_work_dir(work_dir)
        safe_name = self._safe_filename(filename, object_key)
        stream: Any = None
        ephemeral: Path | None = None
        try:
            try:
                stream = self.reader.open_stream(object_key)
            except Exception as exc:
                raise _fail("OBJECT_STORE_UNAVAILABLE", "object stream could not be opened", retryable=True, object_key=object_key) from exc
            if not hasattr(stream, "read"):
                raise _fail("OBJECT_STORE_UNAVAILABLE", "object stream is invalid", object_key=object_key)
            ephemeral = Path(tempfile.mkdtemp(prefix="media-", dir=str(parent) if parent else None))
            destination = ephemeral / safe_name
            digest = hashlib.sha256()
            size = 0
            with destination.open("xb") as output:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if chunk == b"":
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise _fail("OBJECT_STORE_UNAVAILABLE", "object stream returned a non-byte chunk", object_key=object_key)
                    chunk = bytes(chunk)
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise _fail("OBJECT_TOO_LARGE", "materialized media exceeds configured size limit", status=413)
                    digest.update(chunk)
                    output.write(chunk)
            actual = digest.hexdigest()
            if actual != expected_sha256 or (expected_size_bytes is not None and size != expected_size_bytes) or size != observed["size_bytes"]:
                raise _fail(
                    "ARTIFACT_HASH_MISMATCH",
                    "materialized bytes do not match the immutable object reference",
                    object_key=object_key,
                    expected_sha256=expected_sha256,
                    actual_sha256=actual,
                    expected_size_bytes=expected_size_bytes,
                    actual_size_bytes=size,
                )
            yield MaterializedMedia(
                path=destination,
                job_id=job_id,
                object_key=object_key,
                sha256=actual,
                size_bytes=size,
                content_type=observed["content_type"],
                metadata=observed,
            )
        finally:
            try:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            finally:
                if ephemeral is not None:
                    shutil.rmtree(ephemeral, ignore_errors=True)


__all__ = ["MediaMaterializer", "MaterializedMedia", "ObjectStoreMediaReader"]
