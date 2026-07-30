from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .errors import ReplicationError


def _read_revision_json(*, object_store: Any, job_id: str, manifest: Any) -> Mapping[str, Any]:
    if object_store is None or not callable(getattr(object_store, "download_to", None)):
        raise ReplicationError(
            "REVIEW_CONTENT_UNAVAILABLE",
            "review content storage is unavailable",
            category="storage",
            retryable=True,
            http_status=503,
        )
    prefix = f"temporary/{job_id}/"
    object_key = str(manifest.object_key or "")
    if not object_key.startswith(prefix):
        raise ReplicationError("REVIEW_CONTENT_INVALID", "review content is outside the job namespace", http_status=409)
    with tempfile.TemporaryDirectory(prefix="usfr-review-") as directory:
        destination = Path(directory) / "revision.json"
        object_store.download_to(
            object_key=object_key,
            destination=destination,
            expected_sha256=str(manifest.sha256),
        )
        raw = destination.read_bytes()
    if len(raw) > 2 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != str(manifest.sha256):
        raise ReplicationError("REVIEW_CONTENT_INVALID", "review content failed validation", http_status=409)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplicationError("REVIEW_CONTENT_INVALID", "review content is not valid UTF-8 JSON", http_status=409) from exc
    if not isinstance(value, Mapping):
        raise ReplicationError("REVIEW_CONTENT_INVALID", "review content is not an object", http_status=409)
    return value


def _script_review(*, job_store: Any, object_store: Any, job_id: str, manifest: Any) -> dict[str, Any]:
    value = _read_revision_json(object_store=object_store, job_id=job_id, manifest=manifest)
    del job_store
    from .user_script_document import UserScriptDocumentError, render_user_script_markdown

    locks = value.get("visible_text_locks")
    if not isinstance(locks, list):
        raise ReplicationError("REVIEW_CONTENT_INVALID", "script review has no visible-text approval locks", http_status=409)
    try:
        content = render_user_script_markdown(value, locks)
    except UserScriptDocumentError as exc:
        raise ReplicationError("REVIEW_CONTENT_INVALID", "script review document is invalid", http_status=409) from exc
    return {
        "type": "script",
        "content": content,
    }


def _storyboard_review(*, object_store: Any, job_id: str, manifest: Any) -> dict[str, Any]:
    if object_store is None:
        raise ReplicationError("REVIEW_CONTENT_UNAVAILABLE", "storyboard storage is unavailable", http_status=503)
    signer = getattr(object_store, "signed_get", None) or getattr(object_store, "signed_preview", None)
    if not callable(signer):
        raise ReplicationError("REVIEW_CONTENT_UNAVAILABLE", "storyboard preview is unavailable", http_status=503)
    keys = []
    for cut in getattr(manifest, "cut_images", ()):
        key = str(getattr(cut, "object_key", "") or "")
        if key and key not in keys:
            keys.append(key)
    grid_key = str(getattr(manifest, "grid_object_key", "") or "")
    if not keys and grid_key:
        keys.append(grid_key)
    prefix = f"temporary/{job_id}/"
    if not keys or any(not key.startswith(prefix) for key in keys):
        raise ReplicationError("REVIEW_CONTENT_INVALID", "storyboard preview binding is invalid", http_status=409)
    urls = []
    for key in keys:
        try:
            urls.append(str(signer(object_key=key, expires_seconds=900)))
        except TypeError:
            urls.append(str(signer(job_id=job_id, object_key=key)))
    return {"type": "storyboard", "image_urls": urls}


def project_public_job(snapshot: Any, *, job_store: Any | None = None, object_store: Any | None = None) -> dict[str, Any]:
    """Return the deliberately small public representation of a job."""

    job_id = str(snapshot.job_id)
    state = str(snapshot.state or "").upper()
    if state == "SUCCEEDED":
        final_ref = snapshot.final_ref
        metadata = final_ref.get("metadata") if isinstance(final_ref, Mapping) else None
        result_url = metadata.get("public_url") if isinstance(metadata, Mapping) else None
        if not isinstance(result_url, str) or not result_url.strip():
            raise ReplicationError(
                "FINAL_URL_UNAVAILABLE",
                "final video URL is unavailable",
                category="delivery",
                retryable=True,
                http_status=503,
            )
        return {
            "job_id": job_id,
            "status": "completed",
            "result_url": result_url.strip(),
        }
    pending = getattr(snapshot, "pending_review_request", None)
    if isinstance(pending, Mapping):
        stage = "script_generation" if pending.get("kind") == "script" else "storyboard_generation"
        return {"job_id": job_id, "status": "processing", "stage": stage}
    if job_store is not None:
        script = job_store.get_current_revision(job_id, "script")
        if script is not None and snapshot.approved_script_sha256 != script.sha256:
            return {
                "job_id": job_id,
                "status": "waiting_review",
                "stage": "script",
                "review": _script_review(job_store=job_store, object_store=object_store, job_id=job_id, manifest=script),
            }
        storyboard = job_store.get_current_revision(job_id, "storyboard")
        if storyboard is not None and snapshot.approved_storyboard_sha256 != storyboard.sha256:
            return {
                "job_id": job_id,
                "status": "waiting_review",
                "stage": "storyboard",
                "review": _storyboard_review(object_store=object_store, job_id=job_id, manifest=storyboard),
            }
    if state == "IMPORTING":
        return {"job_id": job_id, "status": "importing"}
    if state == "FAILED":
        public_error = getattr(snapshot, "public_error", None)
        if isinstance(public_error, Mapping):
            return {"job_id": job_id, "status": "failed", "error": dict(public_error)}
        return {
            "job_id": job_id,
            "status": "failed",
            "error": {
                "code": "PROCESSING_FAILED",
                "message": "video generation failed",
                "retryable": False,
            },
        }
    return {"job_id": job_id, "status": "processing"}


__all__ = ["project_public_job"]
