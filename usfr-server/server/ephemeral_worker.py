"""Job-scoped StagePort execution with temporary object-store artifacts."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterator, Mapping, Sequence

from .analysis_scope import build_analysis_scope
from .errors import ReplicationError
from .job_models import ArtifactRef, JobSnapshot, StageCheckpoint, WorkMessage
from .media_materializer import MaterializedMedia, MediaMaterializer
from .review_models import RevisionManifest


_STAGE_OUTPUT_SCHEMA = "ephemeral-stage-output/v1"
_UNSAFE_STAGE_OUTPUT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "file_path",
        "local_path",
        "output_path",
        "path",
        "secret",
        "token",
        "video_path",
        "work_dir",
    }
)


def _artifact_id(stage: str, kind: str, sha256: str) -> str:
    return hashlib.sha256(f"{stage}\0{kind}\0{sha256}".encode()).hexdigest()[:32]


def _stage_output_value(value: Any) -> Any:
    """Return a JSON-safe stage-output projection without worker-local data."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "stage output cannot contain a non-finite number",
                category="artifact",
                http_status=422,
            )
        return value
    if isinstance(value, Path):
        raise ReplicationError(
            "CONTRACT_INVALID",
            "stage output cannot persist a local path",
            category="artifact",
            http_status=422,
        )
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "stage output keys must be non-empty strings",
                    category="artifact",
                    http_status=422,
                )
            if key.casefold() in _UNSAFE_STAGE_OUTPUT_KEYS:
                continue
            result[key] = _stage_output_value(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_stage_output_value(item) for item in value]
    raise ReplicationError(
        "CONTRACT_INVALID",
        "stage output contains an unsupported value",
        category="artifact",
        http_status=422,
    )


@dataclass
class EphemeralStageContext:
    job_id: str
    stage: str
    snapshot: JobSnapshot
    job_store: Any
    temporary_store: Any
    work_dir: Path
    materializer: MediaMaterializer | None = None
    profile_snapshot: Mapping[str, Any] | None = None
    invocation_adapter: Any | None = None
    allow_local_paths: bool = False
    analysis_scope: Mapping[str, Any] = field(default_factory=dict)
    stage_outputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    timeline_regions: tuple[Mapping[str, Any], ...] = ()
    _published: dict[str, ArtifactRef] = field(default_factory=dict, init=False, repr=False)

    @property
    def run_id(self) -> str:
        return self.job_id

    @property
    def input_slots(self) -> tuple[Mapping[str, Any], ...]:
        raw = self.snapshot.slots_manifest.get("slots", ())
        if isinstance(raw, Mapping):
            return tuple(
                {"slot_id": str(name), **(dict(value) if isinstance(value, Mapping) else {"values": [value], "present": value is not None})}
                for name, value in raw.items()
            )
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            return tuple(dict(item) for item in raw if isinstance(item, Mapping))
        return ()

    @property
    def artifacts(self) -> tuple[Mapping[str, Any], ...]:
        rows: list[Mapping[str, Any]] = []
        for item in self.job_store.list_artifacts(self.job_id):
            row = item.to_dict()
            metadata = row.get("metadata")
            if isinstance(metadata, Mapping):
                # Segment identity is immutable provider-carrier authority.
                # Surface it to the complete timeline renderer without letting
                # arbitrary metadata override an ArtifactRef identity.
                for field in ("segment_id", "segment_plan_sha256"):
                    if field in metadata:
                        row[field] = metadata[field]
            rows.append(row)
        return tuple(rows)

    @property
    def input_artifacts(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for slot in self.input_slots:
            if slot.get("present") is False:
                continue
            metadata = slot.get("metadata") or []
            values = slot.get("values") or []
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
                values = [values]
            for index, value in enumerate(values):
                record = metadata[index] if isinstance(metadata, Sequence) and index < len(metadata) and isinstance(metadata[index], Mapping) else {}
                item = {"slot_id": slot.get("slot_id"), "index": index}
                if record.get("object_key"):
                    item["object_key"] = record["object_key"]
                if record.get("sha256"):
                    item["sha256"] = record["sha256"]
                if isinstance(value, str) and value.startswith(("https://", "http://")):
                    item["url"] = value
                result.append(item)
        return result

    def _slot(self, slot_id: str) -> Mapping[str, Any]:
        for slot in self.input_slots:
            if slot.get("slot_id") == slot_id:
                return slot
        raise ReplicationError("INPUT_SLOT_INVALID", f"unknown input slot: {slot_id}", category="input", http_status=422)

    @contextmanager
    def materialize_slot(self, slot_id: str, *, index: int = 0) -> Iterator[MaterializedMedia]:
        if self.materializer is None:
            raise ReplicationError("OBJECT_STORE_REQUIRED", "slot materialization requires object storage", category="storage", http_status=503)
        slot = self._slot(slot_id)
        metadata = slot.get("metadata") or []
        if not isinstance(metadata, Sequence) or index < 0 or index >= len(metadata) or not isinstance(metadata[index], Mapping):
            raise ReplicationError("INPUT_SLOT_INVALID", f"{slot_id}[{index}] is unavailable", category="input", http_status=422)
        record = metadata[index]
        with self.materializer.materialize(
            job_id=self.job_id,
            object_key=str(record.get("object_key") or ""),
            expected_sha256=str(record.get("sha256") or ""),
            expected_size_bytes=record.get("size_bytes"),
            work_dir=self.work_dir,
        ) as media:
            yield media

    @contextmanager
    def materialize_extension(self, extension_id: str, *, index: int = 0) -> Iterator[MaterializedMedia]:
        """Lease-materialize one verified public input-contract extension."""

        if self.materializer is None:
            raise ReplicationError("OBJECT_STORE_REQUIRED", "extension materialization requires object storage", category="storage", http_status=503)
        extensions = self.snapshot.slots_manifest.get("extensions", {})
        extension = extensions.get(extension_id) if isinstance(extensions, Mapping) else None
        if not isinstance(extension, Mapping):
            raise ReplicationError("INPUT_SLOT_INVALID", f"unknown input extension: {extension_id}", category="input", http_status=422)
        values = extension.get("values") or []
        hashes = extension.get("sha256") or []
        metadata = extension.get("metadata") or []
        if (
            not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray))
            or not isinstance(hashes, Sequence) or isinstance(hashes, (str, bytes, bytearray))
            or not isinstance(metadata, Sequence) or isinstance(metadata, (str, bytes, bytearray))
            or index < 0 or index >= len(values) or len(values) != len(hashes) or len(values) != len(metadata)
            or not isinstance(metadata[index], Mapping)
        ):
            raise ReplicationError("INPUT_SLOT_INVALID", f"{extension_id}[{index}] immutable upload evidence is invalid", category="input", http_status=422)
        record = metadata[index]
        object_key = str(record.get("object_key") or "")
        expected_sha256 = str(record.get("sha256") or "").lower()
        if not object_key or expected_sha256 != str(hashes[index]).lower():
            raise ReplicationError("INPUT_SLOT_INVALID", f"{extension_id}[{index}] upload digest is invalid", category="input", http_status=422)
        with self.materializer.materialize(
            job_id=self.job_id,
            object_key=object_key,
            expected_sha256=expected_sha256,
            expected_size_bytes=record.get("size_bytes"),
            work_dir=self.work_dir,
        ) as media:
            yield media

    @contextmanager
    def materialize_artifact(
        self,
        kind: str,
        *,
        index: int = 0,
        sha256: str | None = None,
        artifact_id: str | None = None,
    ) -> Iterator[MaterializedMedia]:
        if self.materializer is None:
            raise ReplicationError("OBJECT_STORE_REQUIRED", "artifact materialization requires object storage", category="storage", http_status=503)
        matches = [item for item in self.job_store.list_artifacts(self.job_id) if item.kind == kind]
        if sha256 is not None:
            matches = [item for item in matches if item.sha256 == sha256]
        if artifact_id is not None:
            matches = [item for item in matches if item.artifact_id == artifact_id]
        if index < 0 or index >= len(matches):
            raise ReplicationError("ARTIFACT_NOT_FOUND", f"artifact {kind}[{index}] is unavailable", category="artifact", http_status=404)
        ref = matches[index]
        with self.materializer.materialize(
            job_id=self.job_id,
            object_key=ref.object_key,
            expected_sha256=ref.sha256,
            expected_size_bytes=ref.size_bytes,
            work_dir=self.work_dir,
        ) as media:
            yield media

    def publish_artifact(
        self,
        *,
        kind: str,
        stream: Any,
        content_type: str,
        expected_sha256: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if metadata is None:
            artifact_metadata: dict[str, Any] = {}
        elif not isinstance(metadata, Mapping):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "artifact metadata must be an object",
                category="artifact",
                http_status=422,
            )
        else:
            try:
                artifact_metadata = json.loads(
                    json.dumps(dict(metadata), ensure_ascii=False, sort_keys=True)
                )
            except (TypeError, ValueError) as exc:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "artifact metadata must be JSON-serializable",
                    category="artifact",
                    http_status=422,
                ) from exc
        artifact_id = _artifact_id(self.stage, kind, expected_sha256)
        stored = self.temporary_store.put_stream(
            job_id=self.job_id,
            logical_path=f"stages/{self.stage}/{artifact_id}",
            stream=stream,
            content_type=content_type,
            expected_sha256=expected_sha256,
        )
        ref = replace(
            stored,
            artifact_id=artifact_id,
            kind=kind,
            metadata=artifact_metadata,
        )
        self.job_store.put_artifact(job_id=self.job_id, artifact=ref)
        self._published[artifact_id] = ref
        return ref.to_dict()

    def publish_bytes(
        self,
        *,
        kind: str,
        data: bytes,
        content_type: str,
        expected_sha256: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        import io

        return self.publish_artifact(
            kind=kind,
            stream=io.BytesIO(data),
            content_type=content_type,
            expected_sha256=expected_sha256,
            metadata=metadata,
        )

    def publish_stage_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(output, Mapping):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "stage output must be an object",
                category="artifact",
                http_status=422,
            )
        safe_output = _stage_output_value(output)
        if not isinstance(safe_output, Mapping):  # defensive: the helper preserves mappings
            raise ReplicationError("CONTRACT_INVALID", "stage output projection is invalid", category="artifact", http_status=422)
        output_sha256 = hashlib.sha256(
            json.dumps(safe_output, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        payload = {
            "schema_version": _STAGE_OUTPUT_SCHEMA,
            "stage": self.stage,
            "output": dict(safe_output),
            "output_sha256": output_sha256,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.publish_artifact(
            kind="stage_output",
            stream=__import__("io").BytesIO(encoded),
            content_type="application/json",
            expected_sha256=hashlib.sha256(encoded).hexdigest(),
            metadata={
                "stage": self.stage,
                "schema_version": _STAGE_OUTPUT_SCHEMA,
                "output_sha256": output_sha256,
            },
        )

    @property
    def published_artifact_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._published))


class EphemeralWorkerManager:
    ephemeral_job_control = True

    def __init__(
        self,
        *,
        job_store: Any,
        temporary_store: Any,
        stage_ports: Mapping[str, Any],
        profile_bundle_resolver: Any,
        capability_ports: Mapping[str, Any],
        materializer: MediaMaterializer | None = None,
        invocation_adapter: Any | None = None,
        recovery_bridge: Any | None = None,
        stage_driver: Any | None = None,
        final_store: Any | None = None,
    ) -> None:
        self.job_store = job_store
        self.temporary_store = temporary_store
        self.stage_ports = dict(stage_ports)
        self.profile_bundle_resolver = profile_bundle_resolver
        self.capability_ports = dict(capability_ports)
        self.materializer = materializer
        self.invocation_adapter = invocation_adapter
        self.recovery_bridge = recovery_bridge
        self.stage_driver = stage_driver
        self.final_store = final_store
        self.allow_local_paths = False

    def validate_startup_capabilities(self) -> None:
        if not bool(getattr(self.profile_bundle_resolver, "immutable", False)):
            raise ReplicationError("CONTRACT_INVALID", "worker requires an immutable runtime Skill bundle")
        if any(not callable(port) and not callable(getattr(port, "run", None)) for port in self.stage_ports.values()):
            raise ReplicationError("CONTRACT_INVALID", "worker StagePort binding is invalid")

    @staticmethod
    def _invoke(handler: Any, context: EphemeralStageContext) -> Mapping[str, Any]:
        target = getattr(handler, "run", handler)
        if not callable(target):
            raise ReplicationError("CONTRACT_INVALID", "stage handler is not callable")
        try:
            signature = inspect.signature(target)
            if "input_artifacts" in signature.parameters:
                result = target(context=context, input_artifacts=context.input_artifacts)
            else:
                result = target(context=context)
        except (TypeError, ValueError):
            result = target(context=context, input_artifacts=context.input_artifacts)
        if not isinstance(result, Mapping):
            raise ReplicationError("CONTRACT_INVALID", "StagePort must return an object")
        return result

    @staticmethod
    def _remaining_ttl_seconds(snapshot: JobSnapshot) -> int:
        return max(1, (snapshot.expires_at_ms - time.time_ns() // 1_000_000) // 1000)

    @staticmethod
    def _known_stages() -> tuple[str, ...]:
        from .ephemeral_driver import EXECUTABLE_STAGES

        return tuple(EXECUTABLE_STAGES)

    def _hydrate_stage_outputs(self, context: EphemeralStageContext) -> None:
        """Restore only checkpoint-bound, JSON-safe outputs from prior stages."""

        if context.materializer is None:
            return
        artifacts = {item.get("artifact_id"): item for item in context.artifacts if isinstance(item, Mapping)}
        hydrated: dict[str, Mapping[str, Any]] = {}
        for stage in self._known_stages():
            if stage == context.stage:
                continue
            checkpoint = self.job_store.get_stage_checkpoint(context.job_id, stage)
            if checkpoint is None or checkpoint.status != "SUCCEEDED":
                continue
            artifact_id = next(
                (
                    candidate
                    for candidate in checkpoint.output_artifact_ids
                    if isinstance(artifacts.get(candidate), Mapping)
                    and artifacts[candidate].get("kind") == "stage_output"
                    and isinstance(artifacts[candidate].get("metadata"), Mapping)
                    and artifacts[candidate]["metadata"].get("stage") == stage
                ),
                None,
            )
            if artifact_id is None:
                continue
            descriptor = artifacts[artifact_id]
            metadata = descriptor["metadata"]
            try:
                with context.materialize_artifact("stage_output", artifact_id=artifact_id) as media:
                    payload = json.loads(Path(media.path).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "prior stage output artifact is not valid JSON",
                    category="artifact",
                    http_status=422,
                ) from exc
            if (
                not isinstance(payload, Mapping)
                or payload.get("schema_version") != _STAGE_OUTPUT_SCHEMA
                or payload.get("stage") != stage
                or not isinstance(payload.get("output"), Mapping)
            ):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "prior stage output artifact has an invalid schema",
                    category="artifact",
                    http_status=422,
                )
            output = _stage_output_value(payload["output"])
            output_sha256 = hashlib.sha256(
                json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if (
                payload.get("output_sha256") != output_sha256
                or metadata.get("output_sha256") != output_sha256
                or metadata.get("schema_version") != _STAGE_OUTPUT_SCHEMA
            ):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "prior stage output artifact digest does not match its checkpoint metadata",
                    category="artifact",
                    http_status=422,
                )
            hydrated[stage] = dict(output)
        context.stage_outputs = hydrated
        route_output = hydrated.get("route_regions")
        if not isinstance(route_output, Mapping):
            return
        timeline_output = route_output.get("timeline_regions")
        if timeline_output is None:
            return
        if isinstance(timeline_output, Mapping):
            regions = timeline_output.get("regions")
        else:
            regions = timeline_output
        if not isinstance(regions, Sequence) or isinstance(regions, (str, bytes, bytearray)):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "route_regions stage output must expose a region sequence",
                category="artifact",
                http_status=422,
            )
        if any(not isinstance(region, Mapping) for region in regions):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "route_regions stage output contains an invalid region",
                category="artifact",
                http_status=422,
            )
        context.timeline_regions = tuple(dict(region) for region in regions)

    def _apply_result_authority(
        self,
        *,
        context: EphemeralStageContext,
        result: Mapping[str, Any],
    ) -> None:
        revision_fields = {
            "build_script": ("script_revision", "script"),
            "generate_storyboards": ("storyboard_revision", "storyboard"),
        }
        revision_spec = revision_fields.get(context.stage)
        if revision_spec is not None and result.get(revision_spec[0]) is not None:
            manifest = result[revision_spec[0]]
            if not isinstance(manifest, RevisionManifest) or manifest.kind != revision_spec[1]:
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    f"{revision_spec[0]} must be a {revision_spec[1]} RevisionManifest",
                )
            current = self.job_store.get_job(context.job_id)
            if current is None:
                raise ReplicationError("JOB_GONE", "job is no longer available", http_status=410)
            self.job_store.append_revision(
                job_id=context.job_id,
                kind=manifest.kind,
                expected_version=current.version,
                manifest=manifest,
                invalidate_downstream=True,
                ttl_seconds=self._remaining_ttl_seconds(current),
            )

        final_artifact_id = result.get("final_artifact_id")
        if final_artifact_id is None:
            return
        if context.stage != "run_qc" or result.get("qc_passed") is not True:
            raise ReplicationError("CONTRACT_INVALID", "final promotion requires a passing run_qc result")
        if self.final_store is None:
            raise ReplicationError("OBJECT_STORE_REQUIRED", "final video store is not configured", category="storage", http_status=503)
        if not isinstance(final_artifact_id, str) or not final_artifact_id:
            raise ReplicationError("CONTRACT_INVALID", "final_artifact_id must be a non-empty string")
        source = self.job_store.get_artifact(context.job_id, final_artifact_id)
        if source is None or source.content_type.casefold() != "video/mp4":
            raise ReplicationError("ARTIFACT_NOT_FOUND", "passing QC did not identify a temporary MP4", category="artifact", http_status=404)
        promoted = self.final_store.promote(job_id=context.job_id, source=source)
        sidecar_request_sha256s = tuple(
            str((item.get("metadata") or {}).get("ui_sidecar_request_sha256") or "").lower()
            for item in context.artifacts
            if isinstance(item, Mapping)
            and isinstance(item.get("metadata"), Mapping)
            and str((item.get("metadata") or {}).get("ui_sidecar_request_sha256") or "")
        )
        if sidecar_request_sha256s:
            from .ui_sidecar_retention import finalize_ui_sidecar_requests

            finalize_ui_sidecar_requests(
                render_endpoint=os.environ.get("USFR_UI_RENDER_ENDPOINT", ""),
                api_token=os.environ.get("USFR_UI_RENDER_API_TOKEN", ""),
                request_sha256s=sidecar_request_sha256s,
                final_video_sha256=str(promoted.sha256),
            )
        current = self.job_store.get_job(context.job_id)
        if current is None:
            raise ReplicationError("JOB_GONE", "job is no longer available", http_status=410)
        self.job_store.cas_transition(
            job_id=context.job_id,
            expected_version=current.version,
            command="publish_final_result",
            updates={"state": "SUCCEEDED", "final_ref": promoted.to_dict()},
            ttl_seconds=self._remaining_ttl_seconds(current),
        )

    def process_work_message(
        self,
        *,
        message: WorkMessage,
        checkpoint: StageCheckpoint,
        owner: str,
    ) -> Mapping[str, Any]:
        if checkpoint.stage != message.stage or checkpoint.dedupe_key != message.dedupe_key or checkpoint.owner != owner:
            raise ReplicationError("WORKER_LEASE_LOST", "work message differs from claimed checkpoint", category="worker", retryable=True, http_status=409)
        snapshot = self.job_store.get_job(message.job_id)
        if snapshot is None:
            raise ReplicationError("JOB_GONE", "job is no longer available", http_status=410)
        handler = self.stage_ports.get(message.stage)
        if handler is None:
            raise ReplicationError("CONTRACT_INVALID", f"no StagePort for {message.stage}")
        with tempfile.TemporaryDirectory(prefix=f"usfr-{message.job_id[:8]}-") as temporary:
            context = EphemeralStageContext(
                job_id=message.job_id,
                stage=message.stage,
                snapshot=snapshot,
                job_store=self.job_store,
                temporary_store=self.temporary_store,
                work_dir=Path(temporary),
                materializer=self.materializer,
                profile_snapshot=snapshot.slots_manifest.get("extensions", {}).get("high_fidelity_profile"),
                invocation_adapter=self.invocation_adapter,
                analysis_scope=build_analysis_scope(snapshot.slots_manifest),
            )
            try:
                self._hydrate_stage_outputs(context)
                output = self._invoke(handler, context)
                self._apply_result_authority(context=context, result=output)
                context.publish_stage_output(output)
            except ReplicationError as exc:
                if self.recovery_bridge is None or exc.retryable:
                    raise
                goal = snapshot.slots_manifest.get("extensions", {}).get("recovery_goal")
                if not isinstance(goal, Mapping):
                    raise
                artifact_kind = {
                    "splice_timeline": "assembled_video",
                    "run_qc": "qc_report",
                }.get(message.stage, f"{message.stage}_output")
                bridge_result = self.recovery_bridge.recover_stage_failure(
                    job_id=message.job_id,
                    stage=message.stage,
                    failure={
                        "stage": message.stage,
                        "code": exc.code,
                        "details": dict(exc.details),
                        "intervals": exc.details.get("intervals", ()),
                    },
                    expected_version=snapshot.version,
                    goal=goal,
                    artifact_kind=artifact_kind,
                    unsupported=exc.code.startswith(("UNSUPPORTED_", "CAPABILITY_")),
                    hard_failure_signatures=tuple(exc.details.get("hard_failure_signatures") or ()),
                    transient=exc.retryable,
                )
                if bridge_result is None:
                    raise
                artifact = ArtifactRef(**dict(bridge_result.artifact_ref))
                self.job_store.put_artifact(job_id=message.job_id, artifact=artifact)
                return {
                    "output_artifact_ids": (artifact.artifact_id,),
                    "output": {
                        "recovered": True,
                        "checkpoint_sha256": bridge_result.checkpoint_sha256,
                        "artifact": artifact.to_dict(),
                    },
                }
            return {
                "output_artifact_ids": context.published_artifact_ids,
                "output": dict(output),
            }


__all__ = ["EphemeralStageContext", "EphemeralWorkerManager"]
