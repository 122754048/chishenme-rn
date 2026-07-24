from __future__ import annotations

from collections.abc import Callable, Mapping
import copy
import json
import math
from typing import Any, Protocol
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .batch_manifest import BatchManifestError, BatchRow, parse_batch_manifest
from .batch_scheduler import BatchScheduler
from .services.replication_timing import RedisTimingLedgerStore


class CommercialBatchRuntimeError(RuntimeError):
    pass


class CommercialBatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict[str, object]]


class BatchStateStore(Protocol):
    def create_batch(self, rows: list[dict[str, object]]) -> str: ...

    def replace_rows(self, batch_id: str, rows: list[dict[str, object]]) -> None: ...

    def get_batch(self, batch_id: str) -> Mapping[str, object]: ...


class RedisBatchStateStore:
    """Durable commercial batch ledger backed by the deployment Redis authority."""

    def __init__(self, redis_client: Any, *, prefix: str = "usfr") -> None:
        if not callable(getattr(redis_client, "get", None)) or not callable(getattr(redis_client, "set", None)):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_REDIS_STATE_REQUIRED")
        if not isinstance(prefix, str) or not prefix.strip():
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_REDIS_PREFIX_INVALID")
        self._redis = redis_client
        self._prefix = prefix.strip()

    def create_batch(self, rows: list[dict[str, object]]) -> str:
        batch_id = uuid.uuid4().hex
        payload = {"batch_id": batch_id, "rows": _state_rows(rows)}
        self._write(batch_id, payload)
        return batch_id

    def replace_rows(self, batch_id: str, rows: list[dict[str, object]]) -> None:
        payload = self._read(batch_id)
        payload["rows"] = _state_rows(rows)
        self._write(batch_id, payload)

    def get_batch(self, batch_id: str) -> Mapping[str, object]:
        return copy.deepcopy(self._read(batch_id))

    def _key(self, batch_id: str) -> str:
        if not isinstance(batch_id, str) or not batch_id:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID")
        return f"{self._prefix}:commercial-batches:{batch_id}"

    def _write(self, batch_id: str, payload: Mapping[str, object]) -> None:
        try:
            self._redis.set(
                self._key(batch_id),
                json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
            )
        except CommercialBatchRuntimeError:
            raise
        except Exception as error:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_UNAVAILABLE") from error

    def _read(self, batch_id: str) -> dict[str, object]:
        try:
            raw = self._redis.get(self._key(batch_id))
        except CommercialBatchRuntimeError:
            raise
        except Exception as error:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_UNAVAILABLE") from error
        if raw is None:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_UNKNOWN")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID") from error
        if (
            not isinstance(payload, dict)
            or payload.get("batch_id") != batch_id
            or not isinstance(payload.get("rows"), list)
        ):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID")
        _state_rows(payload["rows"])
        return payload


class StandardUsfrBatchJobCreator:
    """Create commercial rows through the standard USFR durable lifecycle."""

    def __init__(
        self,
        *,
        job_store: Any,
        object_store: Any,
        stage_driver: Any,
        capability_secret: bytes,
        upload_scope: str,
        ttl_seconds: int,
        bind_slots: Callable[..., dict[str, Any]],
        issue_capability: Callable[[bytes], tuple[str, str]],
        timing_ledger_store: Any | None = None,
        background_music_execution_adapter: Any | None = None,
    ) -> None:
        if not all(callable(getattr(job_store, name, None)) for name in ("create_job", "cas_transition", "get_job")):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_JOB_STORE_REQUIRED")
        if not callable(getattr(object_store, "head", None)):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_OBJECT_STORE_REQUIRED")
        if not callable(getattr(stage_driver, "enqueue_next", None)):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STAGE_DRIVER_REQUIRED")
        if not isinstance(capability_secret, bytes) or len(capability_secret) < 32:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_CAPABILITY_SECRET_REQUIRED")
        if not isinstance(upload_scope, str) or not upload_scope.strip():
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_UPLOAD_SCOPE_REQUIRED")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_TTL_INVALID")
        if not callable(bind_slots) or not callable(issue_capability):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_BINDING_REQUIRED")
        if timing_ledger_store is not None and not callable(getattr(timing_ledger_store, "create", None)):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_TIMING_STORE_REQUIRED")
        self._job_store = job_store
        self._object_store = object_store
        self._stage_driver = stage_driver
        self._capability_secret = capability_secret
        self._upload_scope = upload_scope.strip()
        self._ttl_seconds = ttl_seconds
        self._bind_slots = bind_slots
        self._issue_capability = issue_capability
        self._timing_ledger_store = timing_ledger_store
        self._background_music_execution_adapter = _validate_background_music_execution_adapter(
            background_music_execution_adapter,
            stage_driver=stage_driver,
        )

    def __call__(self, row: BatchRow) -> str:
        slots = self._completed_slot_objects(row)
        background_music = self._background_music_extension(row)
        if background_music is not None and self._background_music_execution_adapter is None:
            raise CommercialBatchRuntimeError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_REQUIRED")
        fixed_optional = any(
            value
            for slot_id, value in slots.items()
            if slot_id != "source_video"
        )
        allow_language_only = bool(row.output_language and not fixed_optional) or bool(background_music and not fixed_optional)
        manifest = self._bind_slots(
            slots,
            object_store=self._object_store,
            upload_scope=self._upload_scope,
            allow_language_only=allow_language_only,
        )
        if not isinstance(manifest, dict):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_MANIFEST_INVALID")
        manifest["output_language"] = row.output_language
        manifest["opaque_audio_policy"] = dict(row.opaque_audio_policy)
        if background_music is not None:
            self._background_music_execution_adapter.validate_manifest(
                background_music=copy.deepcopy(background_music)
            )
            admission = dict(manifest.get("admission") or {})
            admission["language_only"] = False
            admission["minimum_optional_slots"] = 0
            admission["can_proceed"] = True
            admission["blocker_code"] = None
            manifest["admission"] = admission
            manifest["review_route"] = None
            extensions = dict(manifest.get("extensions") or {})
            extensions["background_music"] = background_music
            manifest["extensions"] = extensions
        _, token_hash = self._issue_capability(self._capability_secret)
        snapshot = self._job_store.create_job(
            slots_manifest=manifest,
            capability_token_hash=token_hash,
            ttl_seconds=self._ttl_seconds,
            correlation_id=row.row_id,
        )
        job_id = str(getattr(snapshot, "job_id", "") or "")
        version = getattr(snapshot, "version", None)
        if not job_id or isinstance(version, bool) or not isinstance(version, int):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_JOB_INVALID")
        if self._timing_ledger_store is not None:
            try:
                self._timing_ledger_store.create(job_id)
            except CommercialBatchRuntimeError:
                raise
            except Exception as error:
                raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_TIMING_UNAVAILABLE") from error
        self._job_store.cas_transition(
            job_id=job_id,
            expected_version=version,
            command="start",
            updates={"state": "ANALYZING"},
            ttl_seconds=self._ttl_seconds,
        )
        self._stage_driver.enqueue_next(job_id)
        return job_id

    def resume_known_job(self, job_id: str) -> None:
        snapshot = self._job_store.get_job(job_id)
        if snapshot is None:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_JOB_UNKNOWN")
        self._stage_driver.enqueue_next(job_id)

    def _completed_slot_objects(self, row: BatchRow) -> dict[str, object]:
        objects: dict[str, object] = {}
        for slot_id, reference in row.slots.items():
            if reference is None:
                continue
            if slot_id == "app_store_url":
                if isinstance(reference, str):
                    objects[slot_id] = reference
                    continue
                if isinstance(reference, Mapping) and isinstance(reference.get("url"), str):
                    objects[slot_id] = dict(reference)
                    continue
            objects[slot_id] = self._verified_completion(reference, slot_id=slot_id, audio=False)
        return objects

    def _background_music_extension(self, row: BatchRow) -> dict[str, object] | None:
        reference = row.extensions.get("background_music")
        if reference is None:
            return None
        completion = self._verified_completion(reference, slot_id="background_music", audio=True)
        return {
            **completion,
            "provider_route": "seedance_audio_reference",
            "provider_asset_type": "Audio",
            "provider_content_item_type": "audio_url",
            "prompt_reference_tag": "@Audio1",
            "forbidden_provider_field": "reference_audios",
            "final_audio_source": "uploaded_exact_audio",
            "allow_loop_or_time_stretch": False,
        }

    def _verified_completion(self, reference: object, *, slot_id: str, audio: bool) -> dict[str, object]:
        if not isinstance(reference, Mapping):
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_COMPLETION_REQUIRED")
        completion = copy.deepcopy(dict(reference))
        allowed = {
            "object_key",
            "object_uri",
            "uri",
            "sha256",
            "size_bytes",
            "content_type",
            "duration_seconds",
            "etag",
            "status",
        }
        if set(completion) - allowed:
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_COMPLETION_INVALID")
        object_key = str(
            completion.get("object_key") or completion.get("object_uri") or completion.get("uri") or ""
        ).strip()
        if not object_key.startswith(f"uploads/{self._upload_scope}/"):
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_SCOPE_INVALID")
        digest = str(completion.get("sha256") or "").lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_COMPLETION_INVALID")
        try:
            size_bytes = int(completion.get("size_bytes"))
            duration = float(completion.get("duration_seconds"))
        except (TypeError, ValueError) as error:
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_COMPLETION_INVALID") from error
        content_type = str(completion.get("content_type") or "").strip().lower()
        if size_bytes < 0 or not math.isfinite(duration) or duration < 0:
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_COMPLETION_INVALID")
        if str(completion.get("status") or "").lower() != "completed":
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_COMPLETION_INVALID")
        if audio:
            if not content_type.startswith("audio/"):
                raise CommercialBatchRuntimeError("BATCH_BACKGROUND_MUSIC_INVALID")
        elif not (content_type.startswith("video/") or content_type.startswith("image/")):
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_COMPLETION_INVALID")
        observed = self._object_store.head(object_key)
        observed_values = _object_metadata(observed)
        if (
            observed_values["object_key"] != object_key
            or observed_values["sha256"] != digest
            or observed_values["size_bytes"] != size_bytes
            or observed_values["content_type"] != content_type
        ):
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_OBJECT_MISMATCH")
        if observed_values["duration_seconds"] is not None and abs(observed_values["duration_seconds"] - duration) > 0.001:
            raise CommercialBatchRuntimeError("BATCH_UPLOAD_OBJECT_MISMATCH")
        completion["object_key"] = object_key
        completion.pop("object_uri", None)
        completion.pop("uri", None)
        completion["sha256"] = digest
        completion["size_bytes"] = size_bytes
        completion["content_type"] = content_type
        completion["duration_seconds"] = duration
        completion["status"] = "completed"
        return completion


def _validate_background_music_execution_adapter(
    adapter: Any | None,
    *,
    stage_driver: Any | None = None,
) -> Any | None:
    if adapter is None:
        return None
    validate_startup = getattr(adapter, "validate_startup", None)
    validate_manifest = getattr(adapter, "validate_manifest", None)
    if not callable(validate_startup) or not callable(validate_manifest):
        raise CommercialBatchRuntimeError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_INVALID")
    if (
        stage_driver is not None
        and getattr(stage_driver, "background_music_execution_contract", None)
        != "background_music_execution/v1"
    ):
        raise CommercialBatchRuntimeError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_INVALID")
    try:
        validate_startup()
    except CommercialBatchRuntimeError:
        raise
    except Exception as error:
        raise CommercialBatchRuntimeError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_UNAVAILABLE") from error
    return adapter


def _object_metadata(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        payload = value
        object_key = payload.get("object_key") or payload.get("object_uri") or payload.get("uri")
        sha256 = payload.get("sha256")
        size_bytes = payload.get("size_bytes")
        content_type = payload.get("content_type")
        duration = payload.get("duration_seconds")
    else:
        object_key = getattr(value, "object_key", None)
        sha256 = getattr(value, "sha256", None)
        size_bytes = getattr(value, "size_bytes", None)
        content_type = getattr(value, "content_type", None)
        duration = getattr(value, "duration_seconds", None)
    try:
        normalized_size = int(size_bytes)
        normalized_duration = None if duration is None else float(duration)
    except (TypeError, ValueError) as error:
        raise CommercialBatchRuntimeError("BATCH_UPLOAD_OBJECT_MISMATCH") from error
    return {
        "object_key": str(object_key or ""),
        "sha256": str(sha256 or "").lower(),
        "size_bytes": normalized_size,
        "content_type": str(content_type or "").lower(),
        "duration_seconds": normalized_duration,
    }


def _state_rows(rows: object) -> list[dict[str, object]]:
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID")
    return [copy.deepcopy(dict(row)) for row in rows]


def build_standard_commercial_batch_runtime(
    *,
    job_store: Any,
    object_store: Any,
    stage_driver: Any,
    capability_secret: bytes,
    upload_scope: str,
    ttl_seconds: int,
    redis_client: Any,
    capability_queues: Mapping[str, Any],
    environment: Mapping[str, str],
    bind_slots: Callable[..., dict[str, Any]],
    issue_capability: Callable[[bytes], tuple[str, str]],
    timing_ledger_store: Any | None = None,
    background_music_execution_adapter: Any | None = None,
    redis_prefix: str = "usfr",
) -> "CommercialBatchRuntime":
    """Assemble commercial batch ports from the same durable USFR deployment."""

    timing_store = timing_ledger_store or RedisTimingLedgerStore(
        redis_client,
        prefix=f"{redis_prefix}:commercial:timing",
    )
    if not callable(getattr(timing_store, "snapshot", None)):
        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_TIMING_STORE_REQUIRED")
    creator = StandardUsfrBatchJobCreator(
        job_store=job_store,
        object_store=object_store,
        stage_driver=stage_driver,
        capability_secret=capability_secret,
        upload_scope=upload_scope,
        ttl_seconds=ttl_seconds,
        bind_slots=bind_slots,
        issue_capability=issue_capability,
        timing_ledger_store=timing_store,
        background_music_execution_adapter=background_music_execution_adapter,
    )
    return CommercialBatchRuntime.from_environment(
        create_standard_job=creator,
        resume_known_job=creator.resume_known_job,
        capability_queues=capability_queues,
        batch_state_store=RedisBatchStateStore(redis_client, prefix=redis_prefix),
        snapshot_for_job=job_store.get_job,
        timing_for_job=timing_store.snapshot,
        environment=environment,
        background_music_execution_adapter=background_music_execution_adapter,
    )


class CommercialBatchRuntime:
    """Commercial batch adapter over injected durable USFR runtime ports."""

    CAPABILITY_QUEUES = BatchScheduler.CAPABILITY_QUEUES

    def __init__(
        self,
        *,
        create_standard_job: Callable[[BatchRow], str],
        resume_known_job: Callable[[str], None],
        capability_queues: Mapping[str, Any],
        batch_state_store: BatchStateStore,
        snapshot_for_job: Callable[[str], Any | None] | None = None,
        timing_for_job: Callable[[str], Mapping[str, object] | None] | None = None,
        background_music_execution_adapter: Any | None = None,
    ) -> None:
        if not callable(create_standard_job) or not callable(resume_known_job):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_RUNTIME_REQUIRED")
        if set(self.CAPABILITY_QUEUES) - set(capability_queues):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_CAPABILITY_QUEUE_MISSING")
        if not all(callable(getattr(batch_state_store, name, None)) for name in ("create_batch", "replace_rows", "get_batch")):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_STORE_REQUIRED")
        self._state_store = batch_state_store
        self._snapshot_for_job = snapshot_for_job
        if timing_for_job is not None and not callable(timing_for_job):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_TIMING_READER_REQUIRED")
        self._timing_for_job = timing_for_job
        self._background_music_execution_adapter = _validate_background_music_execution_adapter(
            background_music_execution_adapter
        )
        self._scheduler = BatchScheduler(
            create_job=create_standard_job,
            resume_known_job=resume_known_job,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        create_standard_job: Callable[[BatchRow], str],
        resume_known_job: Callable[[str], None],
        capability_queues: Mapping[str, Any],
        batch_state_store: BatchStateStore,
        snapshot_for_job: Callable[[str], Any | None] | None = None,
        timing_for_job: Callable[[str], Mapping[str, object] | None] | None = None,
        environment: Mapping[str, str] | None = None,
        background_music_execution_adapter: Any | None = None,
    ) -> "CommercialBatchRuntime":
        runtime = cls(
            create_standard_job=create_standard_job,
            resume_known_job=resume_known_job,
            capability_queues=capability_queues,
            batch_state_store=batch_state_store,
            snapshot_for_job=snapshot_for_job,
            timing_for_job=timing_for_job,
            background_music_execution_adapter=background_music_execution_adapter,
        )
        limits = _capability_concurrency_limits(environment or {})
        setters: dict[str, Callable[[int], Any]] = {}
        for name in cls.CAPABILITY_QUEUES:
            setter = getattr(capability_queues[name], "set_concurrency_limit", None)
            if not callable(setter):
                raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_QUEUE_LIMIT_UNSUPPORTED")
            setters[name] = setter
        for name, limit in limits.items():
            setters[name](limit)
        return runtime

    def preflight(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [self._preflight_row(raw) for raw in rows]

    def submit(self, rows: list[dict[str, object]]) -> dict[str, object]:
        preflight = self.preflight(rows)
        batch_rows = [
            {"input": dict(raw), "row_id": item["row_id"], "status": item["status"], "route": item.get("route")}
            for raw, item in zip(rows, preflight)
        ]
        batch_id = self._state_store.create_batch(batch_rows)
        results = []
        for raw, preview in zip(rows, preflight):
            if preview["status"] != "ready":
                results.append(
                    {
                        "row_id": preview["row_id"],
                        "status": "rejected",
                        "error": preview.get("error", "COMMERCIAL_BATCH_PREFLIGHT_REJECTED"),
                    }
                )
                continue
            results.extend(self._scheduler.submit_rows([raw]))
        by_id = {str(item.get("row_id") or ""): item for item in preflight}
        stored_rows: list[dict[str, object]] = []
        for source, result in zip(batch_rows, results):
            merged = dict(source)
            merged.update(result)
            preview = by_id.get(str(result.get("row_id") or ""))
            if preview:
                merged["route"] = preview.get("route")
                merged["required_qa"] = preview.get("required_qa")
            stored_rows.append(merged)
        self._state_store.replace_rows(batch_id, stored_rows)
        return {"batch_id": batch_id, "rows": [_public_row(row) for row in stored_rows]}

    def get_batch(self, batch_id: str) -> dict[str, object]:
        batch = self._synchronize_batch(batch_id)
        rows = batch.get("rows")
        if not isinstance(rows, list):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID")
        return {"batch_id": batch_id, "rows": [_public_row(row) for row in rows if isinstance(row, Mapping)]}

    def retry_row(self, batch_id: str, row_id: str) -> dict[str, object]:
        batch = self._state_store.get_batch(batch_id)
        rows = batch.get("rows")
        if not isinstance(rows, list):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID")
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping) or raw.get("row_id") != row_id:
                continue
            job_id = raw.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_JOB_UNKNOWN")
            self._scheduler.resume_row(job_id)
            updated = dict(raw)
            updated["status"] = "resumed"
            mutable_rows = [dict(item) for item in rows if isinstance(item, Mapping)]
            mutable_rows[index] = updated
            self._state_store.replace_rows(batch_id, mutable_rows)
            return {"batch_id": batch_id, "row_id": row_id, "status": "resumed", "job_id": job_id}
        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_ROW_UNKNOWN")

    def result_index(self, batch_id: str) -> dict[str, object]:
        batch = self._synchronize_batch(batch_id)
        rows = batch.get("rows")
        if not isinstance(rows, list):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID")
        return {
            "batch_id": batch_id,
            "items": [
                {
                    "row_id": row.get("row_id"),
                    "job_id": row.get("job_id"),
                    "status": row.get("status"),
                    "result": row.get("result"),
                }
                for row in rows
                if isinstance(row, Mapping)
            ],
        }

    def _preflight_row(self, raw: dict[str, object]) -> dict[str, object]:
        row_id = str(raw.get("row_id") or "") if isinstance(raw, dict) else ""
        try:
            row = parse_batch_manifest([raw])[0]
        except (BatchManifestError, ValueError) as error:
            return {"row_id": row_id, "status": "rejected", "error": str(error)}
        if (
            row.extensions.get("background_music") is not None
            and self._background_music_execution_adapter is None
        ):
            return {
                "row_id": row.row_id,
                "status": "rejected",
                "error": "BACKGROUND_MUSIC_EXECUTION_ADAPTER_REQUIRED",
                "route": _route_preview(row),
                "required_qa": _required_qa(row),
            }
        return {
            "row_id": row.row_id,
            "status": "ready",
            "route": _route_preview(row),
            "required_qa": _required_qa(row),
        }

    def _synchronize_batch(self, batch_id: str) -> Mapping[str, object]:
        batch = self._state_store.get_batch(batch_id)
        rows = batch.get("rows")
        if not isinstance(rows, list):
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID")
        if self._snapshot_for_job is None:
            return batch
        synchronized: list[dict[str, object]] = []
        changed = False
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STATE_INVALID")
            row = dict(raw)
            job_id = row.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                synchronized.append(row)
                continue
            try:
                snapshot = self._snapshot_for_job(job_id)
            except CommercialBatchRuntimeError:
                raise
            except Exception as error:
                raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_STATE_UNAVAILABLE") from error
            if snapshot is None:
                synchronized.append(row)
                continue
            projection = _snapshot_projection(snapshot)
            if self._timing_for_job is not None:
                try:
                    timing = self._timing_for_job(job_id)
                except CommercialBatchRuntimeError:
                    raise
                except Exception as error:
                    raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_TIMING_UNAVAILABLE") from error
                if timing is not None:
                    if not isinstance(timing, Mapping):
                        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_TIMING_INVALID")
                    projection["timing_ledger"] = copy.deepcopy(dict(timing))
            updated = {**row, **projection}
            changed = changed or updated != row
            synchronized.append(updated)
        if changed:
            self._state_store.replace_rows(batch_id, synchronized)
            return self._state_store.get_batch(batch_id)
        return batch


def _route_preview(row: BatchRow) -> str:
    optional_slots = {name for name, value in row.slots.items() if name != "source_video" and value}
    has_music = bool(row.extensions.get("background_music"))
    if row.output_language and not optional_slots and not has_music:
        return "language_only"
    if has_music and not optional_slots and not row.output_language:
        return "background_music_replace_sing"
    return "composite_replication"


def _required_qa(row: BatchRow) -> list[str]:
    checks = ["source_fidelity_contract", "timeline_placement", "final_technical"]
    if row.extensions.get("background_music"):
        checks.extend(
            (
                "music_timeline_contract",
                "uploaded_music_exact_fragment",
                "singing_alignment_or_explicit_no_visible_singer",
                "singing_lip_sync_qa_or_explicit_no_visible_singer",
                "final_mix_receipt",
            )
        )
    if row.output_language:
        checks.append("localized_audio")
    if row.slots.get("ui_operation_video") or row.slots.get("tail_video"):
        checks.append("opaque_media_technical")
    return checks


def _public_row(row: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if key != "input"}


def _snapshot_projection(snapshot: object) -> dict[str, object]:
    state = str(getattr(snapshot, "state", "") or "").strip()
    if not state:
        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_STATE_INVALID")
    normalized_state = state.lower()
    status = {
        "succeeded": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(normalized_state, normalized_state)
    result = getattr(snapshot, "final_ref", None)
    if result is not None and not isinstance(result, Mapping):
        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_STATE_INVALID")
    version = getattr(snapshot, "version", None)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_STATE_INVALID")
    review_route = getattr(snapshot, "review_route", None)
    if review_route is not None and not isinstance(review_route, str):
        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_STANDARD_STATE_INVALID")
    return {
        "status": status,
        "standard_state": state,
        "job_version": version,
        "review_route": review_route,
        "result": copy.deepcopy(dict(result)) if isinstance(result, Mapping) else None,
    }


def _capability_concurrency_limits(environment: Mapping[str, str]) -> dict[str, int]:
    limits: dict[str, int] = {}
    for name in CommercialBatchRuntime.CAPABILITY_QUEUES:
        environment_key = "USFR_BATCH_CONCURRENCY_" + name.upper()
        value = environment.get(environment_key)
        if value is None or not str(value).strip():
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_CONCURRENCY_LIMIT_REQUIRED")
        try:
            limit = int(str(value))
        except ValueError as error:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_CONCURRENCY_LIMIT_INVALID") from error
        if limit <= 0:
            raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_CONCURRENCY_LIMIT_INVALID")
        limits[name] = limit
    return limits


def mount_commercial_batch_api(app: FastAPI, *, runtime: CommercialBatchRuntime | None) -> None:
    """Mount the commercial API without altering the canonical USFR job API."""

    if runtime is not None and not isinstance(runtime, CommercialBatchRuntime):
        raise CommercialBatchRuntimeError("COMMERCIAL_BATCH_RUNTIME_INVALID")
    if runtime is None:
        @app.api_route(
            "/api/v1/commercial-batches/{path:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )
        async def batch_runtime_unavailable(path: str) -> JSONResponse:
            del path
            return _runtime_error("COMMERCIAL_BATCH_RUNTIME_NOT_CONFIGURED", status_code=503)

        return

    @app.post("/api/v1/commercial-batches/preflight", response_model=None)
    def preflight(command: CommercialBatchCommand) -> Any:
        try:
            return {"rows": runtime.preflight(command.rows)}
        except CommercialBatchRuntimeError as error:
            return _runtime_error(str(error), status_code=422)

    @app.post("/api/v1/commercial-batches", status_code=202, response_model=None)
    def submit(command: CommercialBatchCommand) -> Any:
        try:
            return runtime.submit(command.rows)
        except CommercialBatchRuntimeError as error:
            return _runtime_error(str(error), status_code=422)

    @app.get("/api/v1/commercial-batches/{batch_id}", response_model=None)
    def get_batch(batch_id: str) -> Any:
        try:
            return runtime.get_batch(batch_id)
        except CommercialBatchRuntimeError as error:
            return _runtime_error(str(error), status_code=404)

    @app.post("/api/v1/commercial-batches/{batch_id}/rows/{row_id}/retry", response_model=None)
    def retry_row(batch_id: str, row_id: str) -> Any:
        try:
            return runtime.retry_row(batch_id, row_id)
        except CommercialBatchRuntimeError as error:
            return _runtime_error(str(error), status_code=422)

    @app.get("/api/v1/commercial-batches/{batch_id}/results-index", response_model=None)
    def result_index(batch_id: str) -> Any:
        try:
            return runtime.result_index(batch_id)
        except CommercialBatchRuntimeError as error:
            return _runtime_error(str(error), status_code=404)


def _runtime_error(code: str, *, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": "The commercial batch runtime is unavailable or rejected the request.",
        },
    )
