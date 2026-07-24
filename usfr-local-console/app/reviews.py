from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .jobs import FileJobStore, VersionConflict
from .models import JobSnapshot


class ReviewError(ValueError):
    pass


def canonical_digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReviewRevision:
    kind: str
    number: int
    sha256: str
    job_version: int
    content: str | dict[str, Any]


def create_script_revision(
    store: FileJobStore, job_id: str, expected_version: int, script_text: str
) -> ReviewRevision:
    if not script_text.strip():
        raise ReviewError("SCRIPT_EMPTY")
    return _create_revision(store, job_id, expected_version, "script", script_text)


def create_storyboard_revision(
    store: FileJobStore, job_id: str, expected_version: int, storyboard: dict[str, Any]
) -> ReviewRevision:
    if not storyboard:
        raise ReviewError("STORYBOARD_EMPTY")
    return _create_revision(store, job_id, expected_version, "storyboard", storyboard)


def approve_script_revision(
    store: FileJobStore,
    job_id: str,
    number: int,
    sha256: str,
    *,
    expected_version: int,
) -> JobSnapshot:
    return _approve_revision(store, job_id, "script", number, sha256, expected_version)


def approve_storyboard_revision(
    store: FileJobStore,
    job_id: str,
    number: int,
    sha256: str,
    *,
    expected_version: int,
) -> JobSnapshot:
    return _approve_revision(store, job_id, "storyboard", number, sha256, expected_version)


def _create_revision(
    store: FileJobStore,
    job_id: str,
    expected_version: int,
    kind: str,
    content: str | dict[str, Any],
) -> ReviewRevision:
    snapshot = store.get(job_id)
    if snapshot.version != expected_version:
        raise VersionConflict("JOB_VERSION_CONFLICT")
    revisions = (snapshot.reviews or {}).get(kind, [])
    number = len(revisions) + 1
    digest = canonical_digest(content)
    entry = {"number": number, "sha256": digest, "content": content, "approved": False}

    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        current.setdefault("reviews", {}).setdefault(kind, []).append(entry)
        current["stage"] = "SCRIPT_REVIEW" if kind == "script" else "STORYBOARD_REVIEW"
        return current

    updated = store.update(
        job_id, expected_version=expected_version, mutate=mutate, event=f"{kind.upper()}_REVISION_CREATED"
    )
    store.write_job_json(
        job_id,
        f"codex/revisions/{kind}-{number}.json",
        {"kind": kind, "number": number, "sha256": digest, "content": content},
    )
    return ReviewRevision(kind=kind, number=number, sha256=digest, job_version=updated.version, content=content)


def _approve_revision(
    store: FileJobStore,
    job_id: str,
    kind: str,
    number: int,
    sha256: str,
    expected_version: int,
) -> JobSnapshot:
    snapshot = store.get(job_id)
    if snapshot.version != expected_version:
        raise VersionConflict("JOB_VERSION_CONFLICT")
    revisions = (snapshot.reviews or {}).get(kind, [])
    matching = next((item for item in revisions if item["number"] == number), None)
    if not matching or matching["sha256"] != sha256:
        raise ReviewError("REVIEW_REVISION_MISMATCH")
    if matching["approved"]:
        raise ReviewError("REVIEW_ALREADY_APPROVED")

    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        for item in current["reviews"][kind]:
            if item["number"] == number:
                item["approved"] = True
        current["stage"] = "CODEX_REQUIRED"
        return current

    return store.update(
        job_id,
        expected_version=expected_version,
        mutate=mutate,
        event=f"{kind.upper()}_REVISION_APPROVED",
    )
