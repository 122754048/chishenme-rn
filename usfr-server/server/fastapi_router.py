from __future__ import annotations

import os
import uuid
from typing import Any, Literal

from fastapi import FastAPI, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .capability_tokens import issue_capability, verify_capability
from .errors import CapabilityInvalidError, ReplicationError
from .intake import bind_uploaded_slots
from .review_models import RevisionRequest
from .ephemeral_service import ReplicationService


SUPPORTED_OUTPUT_LANGUAGES = ("en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh")


class JobCreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slots: dict[str, Any]
    output_language: Literal["en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"] | None = None
    upload_scope: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class VersionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class RevisionRequestModel(VersionModel):
    expected_revision: int | None = Field(default=None, ge=1)
    mode: Literal["direct_edit", "instruction", "regenerate"] = "instruction"
    changed_cut_ids: tuple[str, ...] = ()
    direct_patch: dict[str, Any] | None = None
    instruction: str | None = None


class RevisionApprovalModel(VersionModel):
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReconcileModel(VersionModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["CreateVideo", "CreateAsset"] = "CreateVideo"
    intent_id: str | None = None
    segment_id: str | None = None


def _error(exc: ReplicationError, request: Request) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.envelope(correlation_id=getattr(request.state, "correlation_id", None), run_id=request.path_params.get("job_id")))


def create_app(*, job_store: Any | None = None, review_service: ReplicationService | None = None, capability_secret: bytes | None = None, ttl_seconds: int = 48 * 60 * 60, object_store: Any | None = None, stage_driver: Any | None = None) -> FastAPI:
    """Create the lightweight capability-protected job API.

    The HTTP adapter intentionally depends only on the ephemeral JobStore and
    review service.  No SQL repository, tenant/actor account, history, SSE, or
    generic artifact browsing is reachable from this surface.
    """
    if job_store is None and review_service is not None:
        job_store = getattr(review_service, "job_store", None)
    if job_store is None:
        raise ValueError("job_store is required")
    secret = capability_secret or os.urandom(32)
    service = review_service or ReplicationService(job_store=job_store, review_ttl_seconds=ttl_seconds)
    app = FastAPI(title="Universal Source-Fidelity Jobs API", version="2.0")

    @app.exception_handler(ReplicationError)
    async def replication_error_handler(request: Request, exc: ReplicationError) -> JSONResponse:
        return _error(exc, request)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(ReplicationError("INPUT_REQUEST_INVALID", "request does not match the jobs API contract", category="input", user_action_required=True, http_status=400, details={"errors": exc.errors()}), request)

    def auth(request: Request, job_id: str):
        header = (request.headers.get("Authorization") or "").strip()
        if not header.startswith("Bearer "):
            raise CapabilityInvalidError()
        token = header[7:].strip()
        snapshot = job_store.get_job(job_id)
        if snapshot is None:
            raise ReplicationError("JOB_GONE", "job is no longer available", category="lifecycle", http_status=410)
        try:
            verify_capability(token, snapshot.capability_token_hash, secret)
        except CapabilityInvalidError:
            raise
        return snapshot

    def touch(job_id: str):
        return service.touch_review_ttl(job_id)

    def dump(snapshot: Any) -> dict[str, Any]:
        return snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)

    def advance(job_id: str) -> None:
        if stage_driver is not None:
            stage_driver.enqueue_next(job_id)

    @app.post("/api/v1/jobs", status_code=202)
    async def create_job(payload: JobCreateModel, request: Request):
        language_only = payload.output_language is not None and not any(k != "source_video" and payload.slots.get(k) for k in payload.slots)
        manifest = bind_uploaded_slots(
            payload.slots,
            object_store=object_store,
            upload_scope=payload.upload_scope,
            allow_language_only=language_only,
        )
        manifest["output_language"] = payload.output_language
        token, token_hash = issue_capability(secret)
        snapshot = job_store.create_job(slots_manifest=manifest, capability_token_hash=token_hash, ttl_seconds=ttl_seconds, correlation_id=str(uuid.uuid4()))
        body = dump(snapshot)
        body["capability_token"] = token
        body["output_language"] = payload.output_language
        return body

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(request: Request, job_id: str = Path(min_length=1)):
        auth(request, job_id)
        return dump(touch(job_id))

    @app.post("/api/v1/jobs/{job_id}/start", status_code=202)
    async def start_job(payload: VersionModel, request: Request, job_id: str = Path(min_length=1)):
        auth(request, job_id)
        snapshot = job_store.cas_transition(job_id=job_id, expected_version=payload.expected_version, command="start", updates={"state": "ANALYZING"}, ttl_seconds=ttl_seconds)
        advance(job_id)
        return dump(snapshot)

    @app.get("/api/v1/jobs/{job_id}/scripts")
    async def list_scripts(request: Request, job_id: str = Path(min_length=1)):
        auth(request, job_id)
        revisions = service.list_script_revisions(job_id)
        return {"job_id": job_id, "revisions": [item.to_dict() for item in revisions]}

    @app.post("/api/v1/jobs/{job_id}/scripts/revise", status_code=202)
    async def revise_script(payload: RevisionRequestModel, request: Request, job_id: str = Path(min_length=1)):
        auth(request, job_id)
        revision = RevisionRequest(payload.mode, payload.expected_revision, payload.changed_cut_ids, payload.direct_patch, payload.instruction)
        return dump(service.request_script_revision(job_id, expected_version=payload.expected_version, request=revision))

    @app.post("/api/v1/jobs/{job_id}/scripts/{revision}/approve", status_code=202)
    async def approve_script(payload: RevisionApprovalModel, request: Request, job_id: str = Path(min_length=1), revision: int = Path(ge=1)):
        auth(request, job_id)
        snapshot = service.approve_script_revision(job_id, revision=revision, expected_version=payload.expected_version, expected_sha256=payload.expected_sha256)
        advance(job_id)
        return dump(snapshot)

    @app.get("/api/v1/jobs/{job_id}/storyboards")
    async def list_storyboards(request: Request, job_id: str = Path(min_length=1)):
        auth(request, job_id)
        revisions = service.list_storyboard_revisions(job_id)
        rows = []
        for item in revisions:
            row = item.to_dict()
            signer = getattr(object_store, "signed_preview", None) if object_store is not None else None
            if signer is None and object_store is not None:
                signer = getattr(object_store, "signed_preview_url", None)
            if callable(signer):
                row["preview_url"] = signer(job_id=job_id, object_key=item.object_key)
            rows.append(row)
        return {"job_id": job_id, "revisions": rows}

    @app.post("/api/v1/jobs/{job_id}/storyboards/revise", status_code=202)
    async def revise_storyboard(payload: RevisionRequestModel, request: Request, job_id: str = Path(min_length=1)):
        auth(request, job_id)
        revision = RevisionRequest(payload.mode, payload.expected_revision, payload.changed_cut_ids, payload.direct_patch, payload.instruction)
        return dump(service.request_storyboard_revision(job_id, expected_version=payload.expected_version, request=revision))

    @app.post("/api/v1/jobs/{job_id}/storyboards/{revision}/approve", status_code=202)
    async def approve_storyboard(payload: RevisionApprovalModel, request: Request, job_id: str = Path(min_length=1), revision: int = Path(ge=1)):
        auth(request, job_id)
        snapshot = service.approve_storyboard_revision(job_id, revision=revision, expected_version=payload.expected_version, expected_sha256=payload.expected_sha256)
        advance(job_id)
        return dump(snapshot)

    @app.post("/api/v1/jobs/{job_id}/provider/reconcile", status_code=202)
    async def reconcile_provider(payload: ReconcileModel, request: Request, job_id: str = Path(min_length=1)):
        auth(request, job_id)
        raise ReplicationError("PROVIDER_RECONCILIATION_UNAVAILABLE", "provider reconciliation is not configured on this lightweight surface", category="provider", retryable=True, http_status=503)

    @app.get("/api/v1/jobs/{job_id}/result")
    async def get_result(request: Request, job_id: str = Path(min_length=1)):
        snapshot = auth(request, job_id)
        return {"job_id": job_id, "result": snapshot.final_ref}

    return app


__all__ = ["create_app", "RevisionRequestModel", "RevisionApprovalModel"]
