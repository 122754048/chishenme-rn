from __future__ import annotations

import hashlib
import mimetypes
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .jobs import FileJobStore, VersionConflict


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class ArtifactReceipt:
    artifact_id: str
    relative_path: str
    sha256: str
    byte_count: int
    job_version: int


class ArtifactRegistry:
    def __init__(self, store: FileJobStore):
        self.store = store

    def register_bytes(
        self,
        job_id: str,
        expected_version: int,
        *,
        role: str,
        filename: str,
        mime_type: str | None,
        payload: bytes,
    ) -> ArtifactReceipt:
        job = self.store.get(job_id)
        if job.version != expected_version:
            raise VersionConflict("JOB_VERSION_CONFLICT")
        artifact_id = uuid.uuid4().hex
        safe_name = Path(filename).name or "artifact.bin"
        suffix = Path(safe_name).suffix
        path = self.store.job_dir(job_id) / "artifacts" / f"{artifact_id}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
        relative_path = str(path.relative_to(self.store.job_dir(job_id))).replace("\\", "/")
        digest = hashlib.sha256(payload).hexdigest()
        record = {
            "artifact_id": artifact_id,
            "role": role,
            "relative_path": relative_path,
            "filename": safe_name,
            "mime_type": mime_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
            "sha256": digest,
            "byte_count": len(payload),
        }

        def mutate(current):
            current.setdefault("artifacts", []).append(record)
            return current

        updated = self.store.update(
            job_id, expected_version=expected_version, mutate=mutate, event="ARTIFACT_REGISTERED"
        )
        return ArtifactReceipt(
            artifact_id=artifact_id,
            relative_path=relative_path,
            sha256=digest,
            byte_count=len(payload),
            job_version=updated.version,
        )


def open_registered_artifact(store: FileJobStore, job_id: str, artifact_id: str) -> Path:
    job = store.get(job_id)
    record = next((item for item in job.artifacts or [] if item["artifact_id"] == artifact_id), None)
    if record is None:
        raise ArtifactError("ARTIFACT_NOT_REGISTERED")
    job_root = store.job_dir(job_id).resolve()
    path = (job_root / record["relative_path"]).resolve()
    if not path.is_relative_to(job_root) or not path.is_file():
        raise ArtifactError("ARTIFACT_NOT_REGISTERED")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ArtifactError("ARTIFACT_HASH_MISMATCH")
    return path
