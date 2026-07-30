"""Provider-neutral S3-compatible object storage and job-scoped media wrappers.

The module intentionally receives a boto3-compatible client from its caller.  No
client, credentials, workstation path, or network connection is created at
import time.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
from typing import Any, BinaryIO, Protocol
from urllib.parse import unquote

from .errors import ReplicationError
from .job_models import ArtifactRef


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_KEY_BYTES = 1024
_MAX_STREAM_BYTES = 512 * 1024 * 1024


class ObjectStore(Protocol):
    def put_stream(
        self,
        *,
        object_key: str,
        stream: BinaryIO,
        content_type: str,
        expected_sha256: str | None = None,
    ) -> ArtifactRef: ...

    def head(self, object_key: str) -> ArtifactRef: ...

    def download_to(self, *, object_key: str, destination: Path, expected_sha256: str) -> Path: ...

    def copy(self, *, source_key: str, destination_key: str, expected_sha256: str) -> ArtifactRef: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def signed_get(self, *, object_key: str, expires_seconds: int) -> str: ...


def _error(code: str, message: str, *, status: int = 422, retryable: bool = False, **details: Any) -> ReplicationError:
    return ReplicationError(code, message, category="storage", retryable=retryable, details=details, http_status=status)


def _require_sha(value: str, *, field: str = "sha256") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value.lower()) is None or value != value.lower():
        raise _error("ARTIFACT_HASH_MISMATCH", f"{field} must be a lowercase SHA-256 digest")
    return value


def _validate_object_key(value: str, *, allow_prefix: bool = False) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise _error("OBJECT_KEY_INVALID", "object key is not a safe relative key")
    if len(value.encode("utf-8", "surrogatepass")) > _MAX_KEY_BYTES:
        raise _error("OBJECT_KEY_INVALID", "object key is too long")
    if any(ord(ch) < 32 or ord(ch) == 127 or 0xD800 <= ord(ch) <= 0xDFFF or ch in "?#" for ch in value):
        raise _error("OBJECT_KEY_INVALID", "object key contains unsafe characters")
    # Encoded traversal must be rejected before any provider normalization.
    try:
        decoded = unquote(value)
    except Exception as exc:  # pragma: no cover - urllib currently never raises here
        raise _error("OBJECT_KEY_INVALID", "object key encoding is invalid") from exc
    if decoded != value and any(part in {"", ".", ".."} for part in decoded.split("/")):
        raise _error("OBJECT_KEY_INVALID", "object key contains encoded traversal")
    if allow_prefix:
        if not value.endswith("/"):
            raise _error("OBJECT_KEY_INVALID", "object prefix must end with a slash")
        parts = value[:-1].split("/")
    else:
        parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _error("OBJECT_KEY_INVALID", "object key is not normalized")
    return value


def _validate_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or _SAFE_SEGMENT.fullmatch(job_id) is None:
        raise _error("OBJECT_KEY_INVALID", "job_id must be one safe path segment")
    return job_id


def _validate_logical_path(logical_path: str) -> str:
    if not isinstance(logical_path, str) or not logical_path or logical_path.startswith("/") or "\\" in logical_path:
        raise _error("OBJECT_KEY_INVALID", "logical path is not a safe relative path")
    # Re-use object-key validation; a logical path has the same normalization rules.
    return _validate_object_key(logical_path)


def _is_not_found(exc: BaseException) -> bool:
    if isinstance(exc, (KeyError, FileNotFoundError)):
        return True
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "nosuchkey" in name or "notfound" in name or "nosuchkey" in message or "not found" in message or "404" in message:
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
        error_code = str(response.get("Error", {}).get("Code", ""))
        return code == "404" or error_code in {"404", "NoSuchKey", "NotFound"}
    return False


def _is_precondition_failed(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        status = str(response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
        code = str(response.get("Error", {}).get("Code", ""))
        if status == "412" or code in {"412", "PreconditionFailed", "ConditionalRequestConflict"}:
            return True
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return "precondition" in name or "precondition" in message or "412" in message


def _is_conditional_unsupported(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", "")).lower()
        if code in {"invalidrequest", "notimplemented", "unsupported", "invalidparameter"}:
            return True
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return (
        isinstance(exc, (TypeError, AssertionError))
        or "unsupported" in name
        or "not implemented" in message
        or "invalidrequest" in message
        or "unknown parameter" in message
        or "invalid parameter" in message
    )


class S3ObjectStore:
    """S3-compatible implementation with an injected client and private bucket."""

    def __init__(self, client: Any, *, bucket: str, max_bytes: int = _MAX_STREAM_BYTES) -> None:
        if client is None:
            raise ValueError("client is required")
        if not isinstance(bucket, str) or not bucket.strip() or any(ch.isspace() for ch in bucket):
            raise ValueError("bucket is required")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self.client = client
        self.bucket = bucket
        self.max_bytes = max_bytes

    def _head_response(self, object_key: str) -> dict[str, Any]:
        _validate_object_key(object_key)
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=object_key)
        except Exception as exc:
            if _is_not_found(exc):
                raise _error("ARTIFACT_NOT_FOUND", "object does not exist", status=404, object_key=object_key) from exc
            raise _error("OBJECT_STORE_UNAVAILABLE", "object metadata could not be read", retryable=True, object_key=object_key) from exc
        if not isinstance(response, dict):
            raise _error("ARTIFACT_METADATA_MISMATCH", "object metadata is invalid", object_key=object_key)
        response_key = response.get("Key") or response.get("key")
        if response_key is not None and str(response_key) != object_key:
            raise _error("ARTIFACT_METADATA_MISMATCH", "object metadata key does not match requested key", object_key=object_key)
        metadata = response.get("Metadata") or response.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise _error("ARTIFACT_METADATA_MISMATCH", "object metadata is invalid", object_key=object_key)
        sha = metadata.get("sha256") or metadata.get("SHA256")
        if isinstance(sha, bytes):
            sha = sha.decode("ascii", "ignore")
        sha = str(sha or "").lower()
        if _SHA256.fullmatch(sha) is None:
            raise _error("ARTIFACT_METADATA_MISMATCH", "object SHA-256 metadata is missing or invalid", object_key=object_key)
        try:
            size = int(response.get("ContentLength", response.get("content_length")))
        except (TypeError, ValueError) as exc:
            raise _error("ARTIFACT_METADATA_MISMATCH", "object size metadata is missing or invalid", object_key=object_key) from exc
        if size < 0:
            raise _error("ARTIFACT_METADATA_MISMATCH", "object size metadata is invalid", object_key=object_key)
        content_type = str(response.get("ContentType", response.get("content_type")) or "").strip().lower()
        if not content_type:
            raise _error("ARTIFACT_METADATA_MISMATCH", "object content type metadata is missing", object_key=object_key)
        return {"sha256": sha, "size_bytes": size, "content_type": content_type}

    def _head_optional(self, object_key: str) -> ArtifactRef | None:
        try:
            return self.head(object_key)
        except ReplicationError as exc:
            if exc.code == "ARTIFACT_NOT_FOUND":
                return None
            raise

    def head(self, object_key: str) -> ArtifactRef:
        _validate_object_key(object_key)
        metadata = self._head_response(object_key)
        return ArtifactRef(
            artifact_id=object_key,
            kind="object",
            object_key=object_key,
            sha256=metadata["sha256"],
            content_type=metadata["content_type"],
            size_bytes=metadata["size_bytes"],
        )

    def put_stream(
        self,
        *,
        object_key: str,
        stream: BinaryIO,
        content_type: str,
        expected_sha256: str | None = None,
    ) -> ArtifactRef:
        _validate_object_key(object_key)
        if not isinstance(content_type, str) or not content_type.strip() or any(ord(ch) < 32 for ch in content_type):
            raise _error("OBJECT_METADATA_INVALID", "content_type is required")
        if expected_sha256 is not None:
            expected_sha256 = _require_sha(expected_sha256, field="expected_sha256")
        if not hasattr(stream, "read"):
            raise _error("OBJECT_STORE_UNAVAILABLE", "upload stream is invalid")
        digest = hashlib.sha256()
        size = 0
        # SpooledTemporaryFile bounds memory while retaining a seekable upload body.
        try:
            with tempfile.SpooledTemporaryFile(max_size=min(self.max_bytes, 8 * 1024 * 1024), mode="w+b") as staged:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if chunk == b"":
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise _error("OBJECT_STORE_UNAVAILABLE", "upload stream returned a non-byte chunk")
                    chunk = bytes(chunk)
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise _error("OBJECT_TOO_LARGE", "object exceeds configured size limit", status=413)
                    digest.update(chunk)
                    staged.write(chunk)
                sha = digest.hexdigest()
                if expected_sha256 is not None and sha != expected_sha256:
                    raise _error("ARTIFACT_HASH_MISMATCH", "uploaded bytes do not match expected SHA-256", expected=expected_sha256, actual=sha)
                existing = self._head_optional(object_key)
                if existing is not None:
                    if (
                        existing.sha256 != sha
                        or existing.size_bytes != size
                        or existing.content_type != content_type.strip().lower()
                    ):
                        raise _error("ARTIFACT_CONFLICT", "object key already contains different bytes", status=409, object_key=object_key)
                    return existing
                staged.seek(0)
                try:
                    # Use the low-level boto3-compatible operation directly:
                    # upload_fileobj's ExtraArgs are transfer-layer validated
                    # and do not portably support IfNoneMatch.
                    self.client.put_object(
                        Bucket=self.bucket,
                        Key=object_key,
                        Body=staged,
                        ContentType=content_type,
                        Metadata={"sha256": sha},
                        IfNoneMatch="*",
                    )
                except Exception as exc:
                    if _is_precondition_failed(exc):
                        existing = self.head(object_key)
                        if (
                            existing.sha256 == sha
                            and existing.size_bytes == size
                            and existing.content_type == content_type.strip().lower()
                        ):
                            return existing
                        raise _error("ARTIFACT_CONFLICT", "object key already contains different bytes", status=409, object_key=object_key) from exc
                    raise _error("OBJECT_STORE_UNAVAILABLE", "object could not be published", retryable=True, object_key=object_key) from exc
        except ReplicationError:
            raise
        except Exception as exc:
            raise _error("OBJECT_STORE_UNAVAILABLE", "object upload failed", retryable=True, object_key=object_key) from exc
        # Provider-side metadata is authoritative after publication.
        published = self.head(object_key)
        if published.sha256 != sha or published.size_bytes != size or published.content_type != content_type.strip().lower():
            raise _error("ARTIFACT_CONFLICT", "object key contains different bytes or metadata", status=409, object_key=object_key)
        return published

    def download_to(self, *, object_key: str, destination: Path, expected_sha256: str) -> Path:
        _validate_object_key(object_key)
        expected_sha256 = _require_sha(expected_sha256, field="expected_sha256")
        ref = self.head(object_key)
        if ref.sha256 != expected_sha256:
            raise _error("ARTIFACT_HASH_MISMATCH", "object metadata does not match expected SHA-256", expected=expected_sha256, actual=ref.sha256)
        destination = Path(destination)
        self._validate_destination(destination)
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f".{destination.name}.{os.getpid()}.partial"
        digest = hashlib.sha256()
        size = 0
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key)
            body = response.get("Body") if isinstance(response, dict) else None
            if body is None or not hasattr(body, "read"):
                raise _error("OBJECT_STORE_UNAVAILABLE", "object stream is invalid", retryable=True, object_key=object_key)
            with temporary.open("wb") as output:
                while True:
                    chunk = body.read(1024 * 1024)
                    if chunk == b"":
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise _error("OBJECT_STORE_UNAVAILABLE", "object stream returned a non-byte chunk", object_key=object_key)
                    chunk = bytes(chunk)
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise _error("OBJECT_TOO_LARGE", "object exceeds configured size limit", status=413)
                    digest.update(chunk)
                    output.write(chunk)
            actual = digest.hexdigest()
            if actual != expected_sha256 or size != ref.size_bytes:
                raise _error("ARTIFACT_HASH_MISMATCH", "downloaded bytes do not match object metadata", expected=expected_sha256, actual=actual)
            if destination.exists() and destination.is_symlink():
                raise _error("DESTINATION_UNSAFE", "destination must not be a symlink")
            os.replace(temporary, destination)
            return destination
        except ReplicationError:
            raise
        except Exception as exc:
            raise _error("OBJECT_STORE_UNAVAILABLE", "object could not be downloaded", retryable=True, object_key=object_key) from exc
        finally:
            try:
                close = getattr(locals().get("body"), "close", None)
                if callable(close):
                    close()
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _validate_destination(destination: Path) -> None:
        if not isinstance(destination, Path):
            destination = Path(destination)
        if destination.name in {"", ".", ".."} or any(part in {".", ".."} for part in destination.parts if part not in {destination.anchor, ""}):
            raise _error("DESTINATION_UNSAFE", "destination path is not normalized")
        current = destination
        if current.exists() and current.is_symlink():
            raise _error("DESTINATION_UNSAFE", "destination must not be a symlink")
        # Existing parent components must not be symlinks; otherwise resolve can escape
        # an operator-provided work directory between validation and publication.
        for parent in [*destination.parents]:
            if parent.exists() and parent.is_symlink():
                raise _error("DESTINATION_UNSAFE", "destination parent must not be a symlink")

    def copy(self, *, source_key: str, destination_key: str, expected_sha256: str) -> ArtifactRef:
        _validate_object_key(source_key)
        _validate_object_key(destination_key)
        expected_sha256 = _require_sha(expected_sha256, field="expected_sha256")
        source = self.head(source_key)
        if source.sha256 != expected_sha256:
            raise _error("ARTIFACT_HASH_MISMATCH", "source object does not match expected SHA-256", expected=expected_sha256, actual=source.sha256)
        existing = self._head_optional(destination_key)
        if existing is not None:
            if (
                existing.sha256 != expected_sha256
                or existing.size_bytes != source.size_bytes
                or existing.content_type.lower() != source.content_type.lower()
            ):
                raise _error("ARTIFACT_CONFLICT", "destination key already contains different bytes", status=409, object_key=destination_key)
            return existing
        copied_via_provider = False
        try:
            copy_object = getattr(self.client, "copy_object", None)
            if callable(copy_object):
                try:
                    copy_object(
                        Bucket=self.bucket,
                        Key=destination_key,
                        CopySource={"Bucket": self.bucket, "Key": source_key},
                        IfNoneMatch="*",
                    )
                    copied_via_provider = True
                except Exception as exc:
                    if _is_precondition_failed(exc):
                        existing = self.head(destination_key)
                        if (
                            existing.sha256 == expected_sha256
                            and existing.size_bytes == source.size_bytes
                            and existing.content_type.lower() == source.content_type.lower()
                        ):
                            return existing
                        raise _error("ARTIFACT_CONFLICT", "destination key already contains different bytes", status=409, object_key=destination_key) from exc
                    if not _is_conditional_unsupported(exc):
                        raise
            if not copied_via_provider:
                # CopyObject has no portable destination create-if-absent
                # contract across S3-compatible providers.  Stream the verified
                # source through put_stream(), which does.
                response = self.client.get_object(Bucket=self.bucket, Key=source_key)
                body = response.get("Body") if isinstance(response, dict) else None
                if body is None or not hasattr(body, "read"):
                    raise RuntimeError("source stream unavailable")
                try:
                    return self.put_stream(
                        object_key=destination_key,
                        stream=body,
                        content_type=source.content_type,
                        expected_sha256=expected_sha256,
                    )
                finally:
                    close = getattr(body, "close", None)
                    if callable(close):
                        close()
        except Exception as exc:
            if isinstance(exc, ReplicationError):
                raise
            raise _error("OBJECT_STORE_UNAVAILABLE", "object copy failed", retryable=True, object_key=destination_key) from exc
        destination = self.head(destination_key)
        if (
            destination.sha256 != expected_sha256
            or destination.size_bytes != source.size_bytes
            or destination.content_type.lower() != source.content_type.lower()
        ):
            raise _error("ARTIFACT_CONFLICT", "destination key contains different bytes or metadata", status=409, object_key=destination_key)
        return destination

    def delete_object(self, object_key: str) -> bool:
        _validate_object_key(object_key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=object_key)
            return True
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise _error("OBJECT_STORE_UNAVAILABLE", "object could not be deleted", retryable=True, object_key=object_key) from exc

    def list_keys(self, prefix: str) -> tuple[str, ...]:
        _validate_object_key(prefix, allow_prefix=True)
        keys: list[str] = []
        paginator_factory = getattr(self.client, "get_paginator", None)
        try:
            if callable(paginator_factory):
                paginator = paginator_factory("list_objects_v2")
                pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            else:
                def _pages():
                    token = None
                    while True:
                        kwargs = {"Bucket": self.bucket, "Prefix": prefix}
                        if token:
                            kwargs["ContinuationToken"] = token
                        page = self.client.list_objects_v2(**kwargs)
                        yield page
                        if not (page or {}).get("IsTruncated"):
                            break
                        token = (page or {}).get("NextContinuationToken")
                        if not token:
                            raise _error("OBJECT_STORE_UNAVAILABLE", "object listing pagination is malformed")

                pages = _pages()
            for page in pages:
                for item in ((page or {}).get("Contents") or ()):
                    key = item.get("Key") if isinstance(item, dict) else None
                    if not isinstance(key, str) or not key.startswith(prefix):
                        raise _error("OBJECT_STORE_UNAVAILABLE", "provider returned an unsafe object key")
                    _validate_object_key(key)
                    keys.append(key)
        except ReplicationError:
            raise
        except Exception as exc:
            raise _error("OBJECT_STORE_UNAVAILABLE", "object listing failed", retryable=True) from exc
        return tuple(sorted(set(keys)))

    def delete_prefix(self, prefix: str) -> int:
        _validate_object_key(prefix, allow_prefix=True)
        # Broad roots are never accepted, even if syntactically valid.
        allowed_roots = {"temporary", "final", "uploads"}
        root = prefix.split("/", 1)[0]
        if prefix in {"temporary/", "final/", "uploads/"} or root not in allowed_roots:
            raise _error("OBJECT_KEY_INVALID", "deletion prefix must be scoped to one job or upload scope")
        parts = prefix.rstrip("/").split("/")
        if len(parts) != 2 or not _SAFE_SEGMENT.fullmatch(parts[1]):
            raise _error("OBJECT_KEY_INVALID", "deletion prefix must be scoped to one job or upload scope")
        keys = self.list_keys(prefix)
        count = 0
        for key in keys:
            if not key.startswith(prefix):
                raise _error("OBJECT_KEY_INVALID", "provider returned key outside deletion prefix")
            self.delete_object(key)
            count += 1
        return count

    def signed_get(self, *, object_key: str, expires_seconds: int) -> str:
        _validate_object_key(object_key)
        if isinstance(expires_seconds, bool) or not isinstance(expires_seconds, int) or expires_seconds <= 0:
            raise _error("INVALID_INPUT", "expires_seconds must be a positive integer")
        try:
            return str(self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": object_key}, ExpiresIn=expires_seconds))
        except Exception as exc:
            raise _error("OBJECT_STORE_UNAVAILABLE", "signed object URL could not be generated", retryable=True) from exc


class TemporaryMediaStore:
    def __init__(self, object_store: ObjectStore) -> None:
        self.object_store = object_store

    @staticmethod
    def _key(job_id: str, logical_path: str) -> str:
        return f"temporary/{_validate_job_id(job_id)}/{_validate_logical_path(logical_path)}"

    @staticmethod
    def _job_prefix(job_id: str) -> str:
        return f"temporary/{_validate_job_id(job_id)}/"

    def put_bytes(self, *, job_id: str, logical_path: str, data: bytes, content_type: str) -> ArtifactRef:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise _error("OBJECT_STORE_UNAVAILABLE", "data must be bytes")
        return self.put_stream(job_id=job_id, logical_path=logical_path, stream=io.BytesIO(bytes(data)), content_type=content_type)

    def put_stream(
        self,
        *,
        job_id: str,
        logical_path: str,
        stream: BinaryIO,
        content_type: str,
        expected_sha256: str | None = None,
    ) -> ArtifactRef:
        key = self._key(job_id, logical_path)
        ref = self.object_store.put_stream(object_key=key, stream=stream, content_type=content_type, expected_sha256=expected_sha256)
        return replace(ref, artifact_id=logical_path, kind="temporary")

    def head(self, ref: ArtifactRef) -> ArtifactRef:
        if not isinstance(ref, ArtifactRef):
            raise _error("ARTIFACT_METADATA_MISMATCH", "artifact reference is invalid")
        self._job_from_key(ref.object_key)
        observed = self.object_store.head(ref.object_key)
        if observed.sha256 != ref.sha256 or observed.size_bytes != ref.size_bytes:
            raise _error("ARTIFACT_METADATA_MISMATCH", "artifact reference does not match object metadata", object_key=ref.object_key)
        return replace(observed, artifact_id=ref.artifact_id, kind=ref.kind or "temporary")

    def download_to(self, *, ref: ArtifactRef, destination: Path) -> Path:
        self.head(ref)
        return self.object_store.download_to(object_key=ref.object_key, destination=destination, expected_sha256=ref.sha256)

    def list_job_keys(self, job_id: str) -> tuple[str, ...]:
        prefix = self._job_prefix(job_id)
        lister = getattr(self.object_store, "list_keys", None)
        if callable(lister):
            return tuple(lister(prefix))
        lister = getattr(self.object_store, "list_job_keys", None)
        if callable(lister):
            return tuple(lister(job_id))
        raise _error("OBJECT_STORE_UNAVAILABLE", "object store cannot list job objects")

    def delete_job(self, job_id: str) -> int:
        prefix = self._job_prefix(job_id)
        return int(self.object_store.delete_prefix(prefix))

    @classmethod
    def _job_from_key(cls, object_key: str) -> str:
        _validate_object_key(object_key)
        parts = object_key.split("/")
        if len(parts) < 3 or parts[0] != "temporary" or not _SAFE_SEGMENT.fullmatch(parts[1]):
            raise _error("OBJECT_KEY_INVALID", "reference is outside temporary job namespace")
        return parts[1]


class UploadMediaStore:
    """Exact-scope lifecycle wrapper for pre-job upload completions."""

    def __init__(self, object_store: ObjectStore) -> None:
        self.object_store = object_store

    @staticmethod
    def _prefix(scope: str) -> str:
        return f"uploads/{_validate_job_id(scope)}/"

    def list_scope(self, scope: str) -> tuple[str, ...]:
        prefix = self._prefix(scope)
        lister = getattr(self.object_store, "list_keys", None)
        if not callable(lister):
            raise _error("OBJECT_STORE_UNAVAILABLE", "object store cannot list upload scope")
        return tuple(lister(prefix))

    def delete_scope(self, scope: str) -> int:
        return int(self.object_store.delete_prefix(self._prefix(scope)))


class FinalVideoStore:
    def __init__(self, object_store: ObjectStore) -> None:
        self.object_store = object_store

    @staticmethod
    def _key(job_id: str) -> str:
        return f"final/{_validate_job_id(job_id)}/result.mp4"

    @staticmethod
    def _source_job(source: ArtifactRef) -> str:
        if not isinstance(source, ArtifactRef):
            raise _error("ARTIFACT_METADATA_MISMATCH", "source artifact reference is invalid")
        parts = source.object_key.split("/")
        if len(parts) < 3 or parts[0] != "temporary" or not _SAFE_SEGMENT.fullmatch(parts[1]):
            raise _error("OBJECT_KEY_INVALID", "promotion source must be in temporary job namespace")
        return parts[1]

    @classmethod
    def _ref_job(cls, ref: ArtifactRef) -> str:
        if not isinstance(ref, ArtifactRef):
            raise _error("ARTIFACT_METADATA_MISMATCH", "artifact reference is invalid")
        parts = ref.object_key.split("/")
        if len(parts) != 3 or parts[0] != "final" or parts[2] != "result.mp4" or not _SAFE_SEGMENT.fullmatch(parts[1]):
            raise _error("ARTIFACT_METADATA_MISMATCH", "reference is not the exact final result key")
        return parts[1]

    def promote(self, *, job_id: str, source: ArtifactRef) -> ArtifactRef:
        job_id = _validate_job_id(job_id)
        source_job = self._source_job(source)
        if source_job != job_id or source.content_type.lower() != "video/mp4":
            raise _error("ARTIFACT_METADATA_MISMATCH", "promotion source does not belong to job or is not video/mp4")
        destination_key = self._key(job_id)
        existing: ArtifactRef | None
        try:
            existing = self.object_store.head(destination_key)
        except ReplicationError as exc:
            if exc.code == "ARTIFACT_NOT_FOUND":
                existing = None
            else:
                raise
        if existing is not None:
            if (
                existing.sha256 != source.sha256
                or existing.size_bytes != source.size_bytes
                or existing.content_type.lower() != "video/mp4"
                or existing.object_key != destination_key
            ):
                raise _error("ARTIFACT_CONFLICT", "final video already contains different bytes", status=409, object_key=destination_key)
            # A replay after source cleanup is valid.  If the source still
            # exists, re-HEAD it before deleting the exact object.
            try:
                observed_source = self.object_store.head(source.object_key)
            except ReplicationError as exc:
                if exc.code != "ARTIFACT_NOT_FOUND":
                    raise
            else:
                if (
                    observed_source.sha256 != source.sha256
                    or observed_source.size_bytes != source.size_bytes
                    or observed_source.content_type.lower() != "video/mp4"
                    or observed_source.object_key != source.object_key
                ):
                    raise _error("ARTIFACT_METADATA_MISMATCH", "promotion source metadata failed verification", object_key=source.object_key)
                self._delete_exact(source.object_key)
            return replace(existing, artifact_id=destination_key, kind="final", content_type="video/mp4")
        observed = self.object_store.head(source.object_key)
        if (
            observed.sha256 != source.sha256
            or observed.size_bytes != source.size_bytes
            or observed.content_type.lower() != "video/mp4"
            or observed.object_key != source.object_key
        ):
            raise _error("ARTIFACT_METADATA_MISMATCH", "promotion source metadata failed verification", object_key=source.object_key)
        copied = self.object_store.copy(source_key=source.object_key, destination_key=destination_key, expected_sha256=source.sha256)
        verified = self.object_store.head(destination_key)
        if (
            verified.sha256 != source.sha256
            or verified.size_bytes != source.size_bytes
            or verified.content_type.lower() != "video/mp4"
            or verified.object_key != destination_key
        ):
            raise _error("ARTIFACT_METADATA_MISMATCH", "promoted final video failed verification", object_key=destination_key)
        self._delete_exact(source.object_key)
        return replace(copied, artifact_id=destination_key, kind="final", content_type="video/mp4")

    def _delete_exact(self, object_key: str) -> None:
        deleter = getattr(self.object_store, "delete_object", None) or getattr(self.object_store, "_delete_object", None)
        if not callable(deleter):
            # A generic provider without exact delete cannot safely promote.
            raise _error("OBJECT_STORE_UNAVAILABLE", "object store lacks exact-object deletion", retryable=True)
        try:
            deleter(object_key)
        except ReplicationError as exc:
            if exc.code == "ARTIFACT_NOT_FOUND":
                return
            raise
        except Exception as exc:
            raise _error("OBJECT_STORE_UNAVAILABLE", "temporary source could not be deleted", retryable=True) from exc

    def exists(self, ref: ArtifactRef) -> bool:
        if not isinstance(ref, ArtifactRef):
            return False
        try:
            self._ref_job(ref)
        except ReplicationError:
            return False
        if ref.content_type.lower() != "video/mp4":
            return False
        try:
            observed = self.object_store.head(ref.object_key)
        except ReplicationError as exc:
            if exc.code == "ARTIFACT_NOT_FOUND":
                return False
            raise
        return (
            observed.sha256 == ref.sha256
            and observed.size_bytes == ref.size_bytes
            and observed.object_key == ref.object_key
            and observed.content_type == "video/mp4"
        )

    def signed_get(self, ref: ArtifactRef, *, expires_seconds: int = 300) -> str:
        if not isinstance(ref, ArtifactRef):
            raise _error("ARTIFACT_METADATA_MISMATCH", "artifact reference is invalid")
        if not self.exists(ref):
            raise _error("ARTIFACT_METADATA_MISMATCH", "final video reference failed verification", object_key=ref.object_key)
        return self.object_store.signed_get(object_key=ref.object_key, expires_seconds=expires_seconds)

    def delete_job(self, job_id: str, *, preserve_result: bool = False) -> int:
        """Delete final objects for a job, optionally retaining only result.mp4."""
        prefix = f"final/{_validate_job_id(job_id)}/"
        if not preserve_result:
            return int(self.object_store.delete_prefix(prefix))
        lister = getattr(self.object_store, "list_keys", None)
        deleter = getattr(self.object_store, "delete_object", None) or getattr(self.object_store, "_delete_object", None)
        if not callable(lister) or not callable(deleter):
            raise _error("OBJECT_STORE_UNAVAILABLE", "object store cannot safely preserve final result", retryable=True)
        result_key = self._key(job_id)
        count = 0
        for key in lister(prefix):
            if not isinstance(key, str) or not key.startswith(prefix):
                raise _error("OBJECT_KEY_INVALID", "provider returned key outside final job prefix")
            if key == result_key:
                continue
            deleter(key)
            count += 1
        return count


__all__ = [
    "ArtifactRef",
    "ObjectStore",
    "S3ObjectStore",
    "TemporaryMediaStore",
    "UploadMediaStore",
    "FinalVideoStore",
]
