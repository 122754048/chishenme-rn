from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .artifacts import ArtifactReceipt, ArtifactRegistry
from .jobs import FileJobStore, VersionConflict
from .models import JobSnapshot
from .reviews import canonical_digest


class ProviderError(RuntimeError):
    pass


class ProviderAmbiguousError(ProviderError):
    pass


class RunningHubTransport(Protocol):
    def create(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def query(self, task_id: str) -> dict[str, Any]: ...

    def download(self, url: str) -> bytes: ...


class HttpRunningHubTransport:
    """Small adapter for the documented RunningHub AI-app run/query endpoints."""

    base_url = "https://www.runninghub.ai"

    def __init__(
        self,
        api_key: str,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: int = 90,
    ) -> None:
        if not api_key.strip():
            raise ValueError("RUNNINGHUB_API_KEY_REQUIRED")
        self._api_key = api_key
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(request.get("workflow_id") or "")
        if not workflow_id.isdecimal():
            raise ProviderError("RUNNINGHUB_WORKFLOW_ID_INVALID")
        payload = request.get("payload")
        if payload is None:
            payload = {key: value for key, value in request.items() if key not in {"workflow_id", "payload"}}
        if not isinstance(payload, dict):
            raise ProviderError("RUNNINGHUB_CREATE_PAYLOAD_INVALID")
        response = self._post_json(
            f"{self.base_url}/openapi/v2/run/ai-app/{workflow_id}", payload
        )
        task_id = response.get("taskId") or response.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError("RUNNINGHUB_TASK_ID_MISSING")
        return {"task_id": task_id, "status": str(response.get("status") or "SUBMITTED").upper()}

    def query(self, task_id: str) -> dict[str, Any]:
        response = self._post_json(f"{self.base_url}/openapi/v2/query", {"taskId": task_id})
        results = response.get("results")
        output_url = None
        if isinstance(results, list) and results and isinstance(results[0], dict):
            candidate = results[0].get("url")
            if isinstance(candidate, str) and candidate.startswith(("https://", "http://")):
                output_url = candidate
        return {
            "task_id": str(response.get("taskId") or task_id),
            "status": str(response.get("status") or "RUNNING").upper(),
            "output_url": output_url,
        }

    def download(self, url: str) -> bytes:
        if not url.startswith(("https://", "http://")):
            raise ProviderError("RUNNINGHUB_OUTPUT_URL_INVALID")
        try:
            with self._opener(Request(url, method="GET"), self._timeout_seconds) as response:
                payload = response.read(1024 * 1024 * 512 + 1)
        except (HTTPError, URLError, TimeoutError) as error:
            raise ProviderError("RUNNINGHUB_DOWNLOAD_FAILED") from error
        if not payload or len(payload) > 1024 * 1024 * 512:
            raise ProviderError("RUNNINGHUB_OUTPUT_INVALID")
        return payload

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            with self._opener(Request(url, data=data, headers=headers, method="POST"), self._timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024)
        except (HTTPError, URLError, TimeoutError) as error:
            raise ProviderError("RUNNINGHUB_REQUEST_FAILED") from error
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderError("RUNNINGHUB_RESPONSE_INVALID") from error
        if not isinstance(decoded, dict):
            raise ProviderError("RUNNINGHUB_RESPONSE_INVALID")
        return decoded


@dataclass(frozen=True)
class ProviderAttempt:
    request_sha256: str
    task_id: str | None
    status: str
    job_version: int


class RunningHubGateway:
    def __init__(self, store: FileJobStore, transport: RunningHubTransport):
        self.store = store
        self.transport = transport
        self.artifacts = ArtifactRegistry(store)

    def submit_once(
        self, job_id: str, expected_version: int, request: dict[str, Any]
    ) -> ProviderAttempt:
        job = self.store.get(job_id)
        if job.version != expected_version:
            raise VersionConflict("JOB_VERSION_CONFLICT")
        digest = canonical_digest(request)
        provider = job.provider or {}
        if provider:
            if provider.get("state") == "REQUEST_READY":
                if provider.get("request") != request:
                    raise ProviderError("PROVIDER_REQUEST_MISMATCH")
            else:
                if provider.get("request_sha256") != digest:
                    raise ProviderError("PROVIDER_REQUEST_MISMATCH")
                if provider.get("task_id"):
                    return ProviderAttempt(
                        request_sha256=digest,
                        task_id=provider["task_id"],
                        status=provider.get("status", "SUBMITTED"),
                        job_version=job.version,
                    )
                if provider.get("status") == "PENDING_CREATE":
                    raise ProviderAmbiguousError("PROVIDER_CREATE_AMBIGUOUS")

        self.store.write_job_json(
            job_id,
            "provider/request.json",
            {
                "request_sha256": digest,
                "request": request,
                "input_manifest_sha256": canonical_digest(job.inputs),
                "workflow_id": request.get("workflow_id"),
                "status": "PENDING_CREATE",
            },
        )

        def pending(current: dict[str, Any]) -> dict[str, Any]:
            current["provider"] = {
                "request_sha256": digest,
                "request": request,
                "task_id": None,
                "status": "PENDING_CREATE",
            }
            current["stage"] = "PROVIDER"
            return current

        prepared = self.store.update(
            job_id, expected_version=job.version, mutate=pending, event="PROVIDER_CREATE_PREPARED"
        )
        try:
            response = self.transport.create(request)
        except Exception as error:
            raise ProviderAmbiguousError("PROVIDER_CREATE_AMBIGUOUS") from error
        task_id = response.get("task_id") or response.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderAmbiguousError("PROVIDER_CREATE_AMBIGUOUS")
        status = str(response.get("status", "SUBMITTED")).upper()

        def submitted(current: dict[str, Any]) -> dict[str, Any]:
            current["provider"] = {
                "request_sha256": digest,
                "request": request,
                "task_id": task_id,
                "status": status,
            }
            return current

        saved = self.store.update(
            job_id,
            expected_version=prepared.version,
            mutate=submitted,
            event="PROVIDER_SUBMITTED",
        )
        return ProviderAttempt(digest, task_id, status, saved.version)

    def record_known_attempt(
        self,
        job_id: str,
        expected_version: int,
        *,
        request_sha256: str,
        task_id: str,
        status: str,
    ) -> JobSnapshot:
        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            current["provider"] = {
                "request_sha256": request_sha256,
                "task_id": task_id,
                "status": status.upper(),
            }
            current["stage"] = "PROVIDER"
            return current

        return self.store.update(
            job_id, expected_version=expected_version, mutate=mutate, event="PROVIDER_ATTEMPT_RECOVERED"
        )

    def poll_existing(self, job_id: str, expected_version: int) -> ProviderAttempt:
        job = self.store.get(job_id)
        if job.version != expected_version:
            raise VersionConflict("JOB_VERSION_CONFLICT")
        provider = job.provider or {}
        task_id = provider.get("task_id")
        if not task_id:
            raise ProviderError("PROVIDER_TASK_UNKNOWN")
        response = self.transport.query(task_id)
        status = str(response.get("status", provider.get("status", "RUNNING"))).upper()

        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            current["provider"] = {**(current.get("provider") or {}), "status": status, "last_response": response}
            if status == "SUCCESS":
                current["stage"] = "QA"
            return current

        updated = self.store.update(
            job_id, expected_version=job.version, mutate=mutate, event="PROVIDER_POLLED"
        )
        return ProviderAttempt(provider["request_sha256"], task_id, status, updated.version)

    def download_registered_artifact(
        self, job_id: str, expected_version: int, *, role: str = "final_video"
    ) -> ArtifactReceipt:
        job = self.store.get(job_id)
        if job.version != expected_version:
            raise VersionConflict("JOB_VERSION_CONFLICT")
        provider = job.provider or {}
        if provider.get("status") != "SUCCESS":
            raise ProviderError("PROVIDER_RESULT_NOT_READY")
        response = provider.get("last_response") or {}
        output_url = response.get("output_url") or response.get("outputUrl")
        if not isinstance(output_url, str) or not output_url.startswith(("https://", "http://")):
            raise ProviderError("PROVIDER_OUTPUT_URL_MISSING")
        payload = self.transport.download(output_url)
        return self.artifacts.register_bytes(
            job_id,
            expected_version,
            role=role,
            filename="result.mp4",
            mime_type="video/mp4",
            payload=payload,
        )
