from __future__ import annotations

import csv
import io
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .artifacts import ArtifactError, open_registered_artifact
from .codex_bridge import BridgeError, export_codex_task, import_codex_result
from .jobs import FileJobStore, JobNotFound, VersionConflict
from .reviews import (
    ReviewError,
    approve_script_revision,
    approve_storyboard_revision,
    create_script_revision,
)
from .runninghub import HttpRunningHubTransport, ProviderAmbiguousError, ProviderError, RunningHubGateway
from .settings import Settings, sha256_file
from .slots import IntakeError, build_intake, probe_video_duration, validate_intake


class UnavailableRunningHubTransport:
    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        raise ProviderError("RUNNINGHUB_TRANSPORT_NOT_CONFIGURED")

    def query(self, task_id: str) -> dict[str, Any]:
        raise ProviderError("RUNNINGHUB_TRANSPORT_NOT_CONFIGURED")

    def download(self, url: str) -> bytes:
        raise ProviderError("RUNNINGHUB_TRANSPORT_NOT_CONFIGURED")


class CommercialBatchRuntimeUnavailable(RuntimeError):
    pass


class BatchManifestFormatError(ValueError):
    pass


class CommercialBatchDispatcher(Protocol):
    def preflight(self, rows: list[dict[str, object]]) -> list[dict[str, object]]: ...

    def submit(self, rows: list[dict[str, object]]) -> dict[str, object]: ...

    def get_batch(self, batch_id: str) -> dict[str, object]: ...

    def retry_row(self, batch_id: str, row_id: str) -> dict[str, object]: ...

    def result_index(self, batch_id: str) -> dict[str, object]: ...


class UnavailableCommercialBatchDispatcher:
    def preflight(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [{"row_id": str(row.get("row_id") or ""), "status": "runtime_required"} for row in rows]

    def submit(self, rows: list[dict[str, object]]) -> dict[str, object]:
        del rows
        raise CommercialBatchRuntimeUnavailable("COMMERCIAL_BATCH_RUNTIME_NOT_CONFIGURED")

    def get_batch(self, batch_id: str) -> dict[str, object]:
        del batch_id
        raise CommercialBatchRuntimeUnavailable("COMMERCIAL_BATCH_RUNTIME_NOT_CONFIGURED")

    def retry_row(self, batch_id: str, row_id: str) -> dict[str, object]:
        del batch_id, row_id
        raise CommercialBatchRuntimeUnavailable("COMMERCIAL_BATCH_RUNTIME_NOT_CONFIGURED")

    def result_index(self, batch_id: str) -> dict[str, object]:
        del batch_id
        raise CommercialBatchRuntimeUnavailable("COMMERCIAL_BATCH_RUNTIME_NOT_CONFIGURED")


class HttpCommercialBatchDispatcher:
    def __init__(
        self,
        base_url: str,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    def preflight(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        payload = self._request("POST", "/preflight", {"rows": rows})
        result = payload.get("rows")
        if not isinstance(result, list):
            raise CommercialBatchRuntimeUnavailable("COMMERCIAL_BATCH_RESPONSE_INVALID")
        return result

    def submit(self, rows: list[dict[str, object]]) -> dict[str, object]:
        return self._request("POST", "", {"rows": rows})

    def get_batch(self, batch_id: str) -> dict[str, object]:
        return self._request("GET", f"/{batch_id}", None)

    def retry_row(self, batch_id: str, row_id: str) -> dict[str, object]:
        return self._request("POST", f"/{batch_id}/rows/{row_id}/retry", None)

    def result_index(self, batch_id: str) -> dict[str, object]:
        return self._request("GET", f"/{batch_id}/results-index", None)

    def _request(self, method: str, path: str, payload: dict[str, object] | None) -> dict[str, object]:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = UrlRequest(self._base_url + path, data=data, headers=headers, method=method)
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024)
        except HTTPError as error:
            try:
                body = json.loads(error.read().decode("utf-8"))
                code = body.get("code") if isinstance(body, dict) else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                code = None
            raise CommercialBatchRuntimeUnavailable(str(code or "COMMERCIAL_BATCH_BACKEND_REJECTED")) from error
        except (URLError, TimeoutError) as error:
            raise CommercialBatchRuntimeUnavailable("COMMERCIAL_BATCH_BACKEND_UNAVAILABLE") from error
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CommercialBatchRuntimeUnavailable("COMMERCIAL_BATCH_RESPONSE_INVALID") from error
        if not isinstance(decoded, dict):
            raise CommercialBatchRuntimeUnavailable("COMMERCIAL_BATCH_RESPONSE_INVALID")
        return decoded


class RevisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    content: str


class ApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    sha256: str


class PollCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int


class BatchManifestCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict[str, object]]


def create_app(
    *,
    settings: Settings | None = None,
    store: FileJobStore | None = None,
    gateway: RunningHubGateway | None = None,
    batch_dispatcher: CommercialBatchDispatcher | None = None,
    probe_duration: Callable[[Path], float] = probe_video_duration,
) -> FastAPI:
    settings = settings or Settings.load()
    store = store or FileJobStore(settings.data_root)
    gateway = gateway or RunningHubGateway(
        store,
        HttpRunningHubTransport(settings.runninghub_api_key)
        if settings.runninghub_api_key
        else UnavailableRunningHubTransport(),
    )
    batch_dispatcher = batch_dispatcher or (
        HttpCommercialBatchDispatcher(settings.commercial_batch_api_url)
        if settings.commercial_batch_api_url
        else UnavailableCommercialBatchDispatcher()
    )
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.purge_expired_jobs(ttl_seconds=settings.temporary_job_ttl_seconds)
        yield

    app = FastAPI(title="USFR Local Console", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.gateway = gateway
    app.state.batch_dispatcher = batch_dispatcher
    app.state.probe_duration = probe_duration

    @app.exception_handler(IntakeError)
    @app.exception_handler(BridgeError)
    @app.exception_handler(ReviewError)
    async def validation_error_handler(_: Request, error: Exception) -> JSONResponse:
        return _error_response(str(error), status_code=422, stage="VALIDATION", retryable=False)

    @app.exception_handler(VersionConflict)
    async def conflict_handler(_: Request, error: VersionConflict) -> JSONResponse:
        return _error_response(str(error), status_code=409, stage="STATE", retryable=True)

    @app.exception_handler(JobNotFound)
    @app.exception_handler(ArtifactError)
    async def missing_handler(_: Request, error: Exception) -> JSONResponse:
        return _error_response(str(error), status_code=404, stage="ARTIFACT", retryable=False)

    @app.exception_handler(ProviderAmbiguousError)
    async def ambiguous_provider_handler(_: Request, error: ProviderAmbiguousError) -> JSONResponse:
        return _error_response(str(error), status_code=409, stage="PROVIDER", retryable=False)

    @app.exception_handler(ProviderError)
    async def provider_handler(_: Request, error: ProviderError) -> JSONResponse:
        return _error_response(str(error), status_code=409, stage="PROVIDER", retryable=False)

    @app.exception_handler(CommercialBatchRuntimeUnavailable)
    async def batch_runtime_handler(_: Request, error: CommercialBatchRuntimeUnavailable) -> JSONResponse:
        return _error_response(str(error), status_code=503, stage="BATCH", retryable=False)

    @app.exception_handler(BatchManifestFormatError)
    async def batch_manifest_handler(_: Request, error: BatchManifestFormatError) -> JSONResponse:
        return _error_response(str(error), status_code=422, stage="BATCH", retryable=False)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        settings.assert_skill_unchanged()
        return {"status": "ok", "host": settings.host, "skill_md_sha256": settings.skill_sha256}

    @app.post("/api/jobs", status_code=201)
    async def create_job(
        source_video: UploadFile = File(...),
        new_product_image: UploadFile | None = File(None),
        new_model_image: UploadFile | None = File(None),
        ui_screenshot: UploadFile | None = File(None),
        app_store_url: str | None = Form(None),
        ui_operation_video: UploadFile | None = File(None),
        tail_video: UploadFile | None = File(None),
        background_music: UploadFile | None = File(None),
        output_language: str | None = Form(None),
        opaque_audio_policy: str | None = Form(None),
    ) -> dict[str, Any]:
        store.purge_expired_jobs(ttl_seconds=settings.temporary_job_ttl_seconds)
        with tempfile.TemporaryDirectory(dir=settings.data_root) as temp_dir:
            temporary = Path(temp_dir)
            source_path = await _save_upload(source_video, temporary, "source_video")
            optional_files = {
                "new_product_image": new_product_image,
                "new_model_image": new_model_image,
                "ui_screenshot": ui_screenshot,
                "ui_operation_video": ui_operation_video,
                "tail_video": tail_video,
            }
            saved = {
                slot: await _save_upload(upload, temporary, slot)
                for slot, upload in optional_files.items()
                if upload and upload.filename
            }
            saved_extensions = {
                "background_music": await _save_upload(background_music, temporary, "background_music")
            } if background_music and background_music.filename else {}
            selected_policy = (opaque_audio_policy or "").strip()
            opaque_audio_policies = (
                {"ui": selected_policy, "tail": selected_policy}
                if selected_policy
                else {}
            )
            intake = build_intake(
                source_video=source_path,
                app_store_url=app_store_url,
                output_language=output_language,
                opaque_audio_policies=opaque_audio_policies,
                **saved_extensions,
                **saved,
            )
            validated = validate_intake(intake, probe_duration=probe_duration)
            return _job_payload(store.create(validated))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _job_payload(store.get(job_id))

    @app.get("/api/final-videos/{job_id}")
    def get_final_video(job_id: str) -> FileResponse:
        return FileResponse(store.open_final_video(job_id), media_type="video/mp4", filename="result.mp4")

    @app.post("/api/batches/preflight")
    def preflight_batch(command: BatchManifestCommand) -> dict[str, object]:
        return {"rows": batch_dispatcher.preflight(command.rows)}

    @app.post("/api/batches/manifest/preflight")
    async def preflight_uploaded_batch_manifest(manifest: UploadFile = File(...)) -> dict[str, object]:
        rows = _parse_batch_manifest(await manifest.read(), manifest.filename or "", manifest.content_type)
        return {"rows": batch_dispatcher.preflight(rows)}

    @app.post("/api/batches/manifest", status_code=202)
    async def submit_uploaded_batch_manifest(manifest: UploadFile = File(...)) -> dict[str, object]:
        rows = _parse_batch_manifest(await manifest.read(), manifest.filename or "", manifest.content_type)
        return batch_dispatcher.submit(rows)

    @app.post("/api/batches", status_code=202)
    def submit_batch(command: BatchManifestCommand) -> dict[str, object]:
        return batch_dispatcher.submit(command.rows)

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, object]:
        return batch_dispatcher.get_batch(batch_id)

    @app.post("/api/batches/{batch_id}/rows/{row_id}/retry")
    def retry_batch_row(batch_id: str, row_id: str) -> dict[str, object]:
        return batch_dispatcher.retry_row(batch_id, row_id)

    @app.get("/api/batches/{batch_id}/results-index")
    def get_batch_result_index(batch_id: str) -> dict[str, object]:
        return batch_dispatcher.result_index(batch_id)

    @app.get("/api/jobs/{job_id}/inputs/{slot_id}")
    def get_input(job_id: str, slot_id: str) -> FileResponse:
        job = store.get(job_id)
        record = job.inputs.get(slot_id)
        if not record or record.get("kind") != "file":
            raise ArtifactError("ARTIFACT_NOT_REGISTERED")
        job_root = store.job_dir(job_id).resolve()
        path = (job_root / record["relative_path"]).resolve()
        if not path.is_relative_to(job_root) or not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ArtifactError("ARTIFACT_NOT_REGISTERED")
        return FileResponse(path, media_type=record["mime_type"], filename=record["original_name"])

    @app.get("/api/jobs/{job_id}/codex-task")
    def get_codex_task(job_id: str, stage: str | None = None) -> dict[str, Any]:
        job = store.get(job_id)
        requested_stage = stage or _recommended_codex_stage(job)
        return export_codex_task(store, job, stage=requested_stage)

    @app.post("/api/jobs/{job_id}/codex-result")
    async def post_codex_result(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        imported = import_codex_result(store, job_id, payload.get("expected_job_version"), payload)
        if payload.get("stage") == "provider_request_ready":
            request = (imported.provider or {}).get("request")
            attempt = gateway.submit_once(imported.job_id, imported.version, request)
            imported = store.get(imported.job_id)
            return {**_job_payload(imported), "provider_attempt": attempt.__dict__}
        return _job_payload(imported)

    @app.post("/api/jobs/{job_id}/reviews/script")
    def save_script(job_id: str, command: RevisionCommand) -> dict[str, Any]:
        revision = create_script_revision(store, job_id, command.expected_version, command.content)
        return revision.__dict__

    @app.post("/api/jobs/{job_id}/reviews/script/{number}/approve")
    def approve_script(job_id: str, number: int, command: ApprovalCommand) -> dict[str, Any]:
        return _job_payload(
            approve_script_revision(store, job_id, number, command.sha256, expected_version=command.expected_version)
        )

    @app.post("/api/jobs/{job_id}/reviews/storyboard/{number}/approve")
    def approve_storyboard(job_id: str, number: int, command: ApprovalCommand) -> dict[str, Any]:
        return _job_payload(
            approve_storyboard_revision(store, job_id, number, command.sha256, expected_version=command.expected_version)
        )

    @app.post("/api/jobs/{job_id}/provider/poll")
    def poll_provider(job_id: str, command: PollCommand) -> dict[str, Any]:
        attempt = gateway.poll_existing(job_id, command.expected_version)
        job = store.get(job_id)
        if attempt.status == "SUCCESS":
            receipt = gateway.deliver_final_video(job_id, job.version)
            return {
                "job_id": receipt.job_id,
                "stage": "DELIVERED",
                "final_video_url": f"/api/final-videos/{receipt.job_id}",
                "filename": receipt.filename,
                "sha256": receipt.sha256,
                "byte_count": receipt.byte_count,
                "provider_attempt": attempt.__dict__,
            }
        return {**_job_payload(job), "provider_attempt": attempt.__dict__}

    @app.get("/api/jobs/{job_id}/artifacts")
    def list_artifacts(job_id: str) -> dict[str, Any]:
        job = store.get(job_id)
        return {"items": job.artifacts or []}

    @app.get("/api/jobs/{job_id}/artifacts/{artifact_id}")
    def get_artifact(job_id: str, artifact_id: str) -> FileResponse:
        path = open_registered_artifact(store, job_id, artifact_id)
        record = next(item for item in store.get(job_id).artifacts or [] if item["artifact_id"] == artifact_id)
        return FileResponse(path, media_type=record["mime_type"], filename=record["filename"])

    web_root = Path(__file__).resolve().parents[1] / "web"
    if web_root.is_dir():
        app.mount("/", StaticFiles(directory=web_root, html=True), name="web")
    else:
        @app.get("/")
        def placeholder() -> dict[str, str]:
            return {"status": "web console assets are not installed"}

    return app


async def _save_upload(upload: UploadFile, directory: Path, slot_id: str) -> Path:
    safe_name = Path(upload.filename or slot_id).name
    suffix = Path(safe_name).suffix
    path = directory / f"{slot_id}{suffix}"
    with path.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            output.write(chunk)
    return path


def _recommended_codex_stage(job) -> str:
    if job.route == "language_only":
        return "provider_request_ready"
    reviews = job.reviews or {}
    scripts = reviews.get("script", [])
    boards = reviews.get("storyboard", [])
    if not scripts:
        return "semantic_analysis_required"
    if scripts[-1].get("approved") and not boards:
        return "storyboard_review_required"
    if boards and boards[-1].get("approved"):
        return "provider_request_ready"
    return "semantic_analysis_required"


def _parse_batch_manifest(payload: bytes, filename: str, content_type: str | None) -> list[dict[str, object]]:
    suffix = Path(filename).suffix.lower()
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise BatchManifestFormatError("BATCH_MANIFEST_ENCODING_INVALID") from error
    if suffix == ".json" or normalized_content_type == "application/json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise BatchManifestFormatError("BATCH_MANIFEST_JSON_INVALID") from error
        rows = value.get("rows") if isinstance(value, dict) else value
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BatchManifestFormatError("BATCH_MANIFEST_ROWS_INVALID")
        return [dict(row) for row in rows]
    if suffix == ".csv" or normalized_content_type in {"text/csv", "application/csv"}:
        return _csv_batch_rows(text)
    raise BatchManifestFormatError("BATCH_MANIFEST_FORMAT_UNSUPPORTED")


def _csv_batch_rows(text: str) -> list[dict[str, object]]:
    reader = csv.DictReader(io.StringIO(text))
    required = {"row_id", "source_video"}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise BatchManifestFormatError("BATCH_MANIFEST_CSV_COLUMNS_INVALID")
    rows: list[dict[str, object]] = []
    slot_ids = (
        "source_video",
        "new_product_image",
        "new_model_image",
        "ui_screenshot",
        "app_store_url",
        "ui_operation_video",
        "tail_video",
    )
    for source in reader:
        row_id = (source.get("row_id") or "").strip()
        source_video = (source.get("source_video") or "").strip()
        if not row_id or not source_video:
            raise BatchManifestFormatError("BATCH_MANIFEST_CSV_ROW_INVALID")
        slots = {slot_id: (source.get(slot_id) or "").strip() or None for slot_id in slot_ids}
        background_music = (source.get("background_music") or "").strip() or None
        opaque_audio_policy = {
            kind: value
            for kind, value in {
                "ui": (source.get("opaque_audio_policy_ui") or "").strip(),
                "tail": (source.get("opaque_audio_policy_tail") or "").strip(),
            }.items()
            if value
        }
        rows.append(
            {
                "row_id": row_id,
                "slots": slots,
                "extensions": {"background_music": background_music},
                "output_language": (source.get("output_language") or "").strip() or None,
                "opaque_audio_policy": opaque_audio_policy,
            }
        )
    if not rows:
        raise BatchManifestFormatError("BATCH_MANIFEST_ROWS_INVALID")
    return rows


def _job_payload(job) -> dict[str, Any]:
    return job.as_dict()


def _error_response(code: str, *, status_code: int, stage: str, retryable: bool) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code or "REQUEST_REJECTED",
            "message": "The request could not be completed.",
            "stage": stage,
            "retryable": retryable,
            "next_action": "Refresh the job and follow the displayed stage.",
        },
    )
