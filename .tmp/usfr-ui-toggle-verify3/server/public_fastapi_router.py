from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any

from fastapi import FastAPI, Header, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .capability_tokens import derive_capability, hash_capability, verify_capability
from .errors import CapabilityInvalidError, ReplicationError
from .public_api_models import PublicJobCreate, PublicReviewRequest
from .public_idempotency import IdempotencyConflict, RedisIdempotencyStore
from .public_job_projection import project_public_job
from .public_errors import project_public_error
from .ephemeral_service import ReplicationService
from .review_models import RevisionRequest


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _public_error(exc: ReplicationError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=project_public_error(exc),
    )


def create_public_app(
    *,
    job_store: Any,
    capability_secret: bytes | None = None,
    stage_driver: Any | None = None,
    review_service: Any | None = None,
    object_store: Any | None = None,
    idempotency_store: RedisIdempotencyStore | None = None,
    ttl_seconds: int = 48 * 60 * 60,
) -> FastAPI:
    if job_store is None:
        raise ValueError("job_store is required")
    secret = capability_secret or os.urandom(32)
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("capability_secret must contain at least 32 bytes")
    if idempotency_store is None:
        redis_client = getattr(job_store, "redis", None)
        prefix = getattr(job_store, "prefix", "usfr")
        idempotency_store = RedisIdempotencyStore(redis_client, prefix=prefix)
    service = review_service or ReplicationService(job_store=job_store, review_ttl_seconds=ttl_seconds)

    app = FastAPI(title="USFR Public Video API", version="1.0")

    @app.exception_handler(ReplicationError)
    async def replication_error_handler(request: Request, exc: ReplicationError) -> JSONResponse:
        del request
        return _public_error(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        del request, exc
        return _public_error(
            ReplicationError(
                "INVALID_REQUEST",
                "request does not match the public API contract",
                category="input",
                user_action_required=True,
                http_status=422,
            )
        )

    def authorize(request: Request, job_id: str) -> Any:
        header = (request.headers.get("Authorization") or "").strip()
        if not header.startswith("Bearer "):
            raise CapabilityInvalidError()
        snapshot = job_store.get_job(job_id)
        if snapshot is None:
            raise CapabilityInvalidError()
        verify_capability(header[7:].strip(), snapshot.capability_token_hash, secret)
        return snapshot

    @app.post("/api/v1/jobs", status_code=202)
    async def create_job(
        payload: PublicJobCreate,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> dict[str, str]:
        public_intake = payload.canonical_dict()
        request_sha256 = _canonical_sha256(public_intake)
        proposed_job_id = uuid.uuid4().hex
        try:
            claim = idempotency_store.claim(
                key=idempotency_key,
                request_sha256=request_sha256,
                proposed_job_id=proposed_job_id,
                ttl_seconds=ttl_seconds,
            )
        except (IdempotencyConflict, ValueError) as exc:
            raise ReplicationError(
                "INVALID_REQUEST",
                str(exc),
                category="input",
                user_action_required=True,
                http_status=409 if isinstance(exc, IdempotencyConflict) else 422,
            ) from exc

        token = derive_capability(secret, claim.job_id, idempotency_key)
        if claim.created:
            snapshot = job_store.create_job(
                job_id=claim.job_id,
                slots_manifest={"public_intake": public_intake},
                capability_token_hash=hash_capability(token, secret),
                ttl_seconds=ttl_seconds,
                correlation_id=str(uuid.uuid4()),
                initial_state="IMPORTING",
            )
            if stage_driver is not None:
                stage_driver.enqueue_next(snapshot.job_id)
        elif job_store.get_job(claim.job_id) is None:
            raise ReplicationError(
                "JOB_GONE",
                "job is no longer available",
                category="lifecycle",
                http_status=410,
            )
        return {"job_id": claim.job_id, "access_token": token, "status": "importing"}

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(request: Request, job_id: str = Path(min_length=1)) -> dict[str, Any]:
        return project_public_job(
            authorize(request, job_id),
            job_store=job_store,
            object_store=object_store,
        )

    @app.post("/api/v1/jobs/{job_id}/review", status_code=202)
    async def review_job(
        payload: PublicReviewRequest,
        request: Request,
        job_id: str = Path(min_length=1),
    ) -> dict[str, Any]:
        snapshot = authorize(request, job_id)
        if snapshot.pending_review_request is not None:
            raise ReplicationError(
                "REVIEW_NOT_ALLOWED",
                "a revised review is still being generated",
                category="review",
                user_action_required=True,
                http_status=409,
            )
        script = job_store.get_current_revision(job_id, "script")
        storyboard = job_store.get_current_revision(job_id, "storyboard")
        if script is not None and snapshot.approved_script_sha256 != script.sha256:
            kind, manifest = "script", script
        elif storyboard is not None and snapshot.approved_storyboard_sha256 != storyboard.sha256:
            kind, manifest = "storyboard", storyboard
        else:
            raise ReplicationError(
                "REVIEW_NOT_ALLOWED",
                "job is not waiting for review",
                category="review",
                user_action_required=True,
                http_status=409,
            )

        if payload.action == "approve":
            if kind == "script":
                from .public_script_approval import approved_script_contract

                approval = approved_script_contract(
                    job_store=job_store,
                    object_store=object_store,
                    job_id=job_id,
                    manifest=manifest,
                )
                updated = service.approve_script_revision(
                    job_id,
                    revision=manifest.revision,
                    expected_version=snapshot.version,
                    expected_sha256=manifest.sha256,
                    line_contracts=approval["line_contracts"],
                    source_content_timeline_sha256=approval["source_content_timeline_sha256"],
                    visible_text_locks=approval["visible_text_locks"],
                    visible_text_locks_sha256=approval["visible_text_locks_sha256"],
                )
            else:
                updated = service.approve_storyboard_revision(
                    job_id,
                    revision=manifest.revision,
                    expected_version=snapshot.version,
                    expected_sha256=manifest.sha256,
                )
        elif kind == "script":
            updated = service.request_script_revision(
                job_id,
                expected_version=snapshot.version,
                request=RevisionRequest("instruction", manifest.revision, (), None, str(payload.content)),
            )
        else:
            updated = service.request_storyboard_revision(
                job_id,
                expected_version=snapshot.version,
                request=RevisionRequest("instruction", manifest.revision, (), None, str(payload.content)),
            )
        if stage_driver is not None:
            stage_driver.enqueue_next(job_id)
        return project_public_job(updated, job_store=job_store, object_store=object_store)

    return app


__all__ = ["create_public_app"]
