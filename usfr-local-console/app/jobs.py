from __future__ import annotations

import copy
import json
import mimetypes
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .execution_map import build_execution_map, build_route_preview
from .models import JobSnapshot
from .settings import sha256_file
from .slots import ValidatedIntake
from .target_truth import AppEvidenceCache, app_evidence_required, build_target_truth


class JobNotFound(FileNotFoundError):
    pass


class VersionConflict(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class FileJobStore:
    def __init__(
        self,
        data_root: Path,
        *,
        app_evidence_resolver: Callable[..., Mapping[str, object]] | None = None,
        app_evidence_cache: AppEvidenceCache | None = None,
        app_evidence_locale: str = "und",
        app_evidence_parser_version: str = "official-store-v1",
    ):
        self.data_root = Path(data_root)
        self.jobs_root = self.data_root / "jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        if app_evidence_resolver is not None and not callable(app_evidence_resolver):
            raise ValueError("APP_EVIDENCE_RESOLVER_INVALID")
        self._app_evidence_resolver = app_evidence_resolver
        self._app_evidence_cache = app_evidence_cache or AppEvidenceCache(self.data_root / "app_evidence_cache")
        self._app_evidence_locale = app_evidence_locale
        self._app_evidence_parser_version = app_evidence_parser_version

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def create(self, validated: ValidatedIntake) -> JobSnapshot:
        job_id = uuid.uuid4().hex
        job_dir = self.job_dir(job_id)
        input_dir = job_dir / "inputs"
        input_dir.mkdir(parents=True)
        inputs = {
            "source_video": self._copy_input(input_dir, "source_video", validated.source_video),
        }
        for slot_id, path in validated.optional_files.items():
            inputs[slot_id] = self._copy_input(input_dir, slot_id, path)
        for extension_id, path in validated.extension_files.items():
            inputs[extension_id] = self._copy_input(input_dir, extension_id, path)
        if validated.app_store_url:
            inputs["app_store_url"] = {
                "kind": "url",
                "value": validated.app_store_url,
                "sha256": self._sha256_text(validated.app_store_url),
            }

        source_contract = {
            "schema_version": 1,
            "analysis_status": "pending",
            "provisional": True,
            "regions": [
                {
                    "region_id": "source_full",
                    "start_ms": 0,
                    "end_ms": round(validated.duration_seconds * 1000),
                    "kind": "body",
                }
            ],
        }
        target_truth = build_target_truth(slots=inputs, app_evidence=None)
        target_truth["status"] = "pending"
        execution_map = build_execution_map(
            intake=validated,
            source_contract=source_contract,
            target_truth=target_truth,
        )
        execution_map["input_slots_sha256"] = self._sha256_text(_canonical_json(inputs))
        execution_map["provisional"] = True
        route_preview = build_route_preview(execution_map)
        state: dict[str, Any] = {
            "job_id": job_id,
            "version": 1,
            "stage": "CODEX_REQUIRED",
            "route": execution_map["run_mode"],
            "output_language": validated.output_language,
            "inputs": inputs,
            "admission": validated.admission,
            "routes": validated.routes,
            "execution_map": execution_map,
            "route_preview": route_preview,
            "provider": None,
            "reviews": {"script": [], "storyboard": []},
            "artifacts": [],
            "qa_receipt": None,
            "timing_ledger": None,
            "created_at": _utc_now(),
        }
        self._write_json(job_dir / "analysis" / "input_slots.json", inputs)
        self._write_json(job_dir / "analysis" / "source_contract.pending.json", source_contract)
        self._write_json(job_dir / "analysis" / "target_truth.json", target_truth)
        self._write_json(job_dir / "analysis" / "execution_map.json", execution_map)
        self._write_json(job_dir / "job.json", state)
        self._append_event(job_dir, {"event": "JOB_CREATED", "version": 1, "at": _utc_now()})
        return JobSnapshot.from_dict(state)

    def get(self, job_id: str) -> JobSnapshot:
        path = self.job_dir(job_id) / "job.json"
        if not path.is_file():
            raise JobNotFound(job_id)
        return JobSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def update(
        self,
        job_id: str,
        *,
        expected_version: int,
        mutate: Callable[[dict[str, Any]], dict[str, Any]],
        event: str = "JOB_UPDATED",
    ) -> JobSnapshot:
        current = self.get(job_id).as_dict()
        if current["version"] != expected_version:
            raise VersionConflict("JOB_VERSION_CONFLICT")
        changed = mutate(copy.deepcopy(current))
        if changed.get("job_id") != job_id:
            raise ValueError("JOB_ID_IMMUTABLE")
        changed["version"] = current["version"] + 1
        self._write_json(self.job_dir(job_id) / "job.json", changed)
        self._append_event(
            self.job_dir(job_id),
            {"event": event, "version": changed["version"], "at": _utc_now()},
        )
        return JobSnapshot.from_dict(changed)

    def write_job_json(self, job_id: str, relative_path: str, value: dict[str, Any]) -> Path:
        job_dir = self.job_dir(job_id).resolve()
        if not job_dir.is_dir():
            raise JobNotFound(job_id)
        destination = (job_dir / relative_path).resolve()
        if not destination.is_relative_to(job_dir):
            raise ValueError("JOB_PATH_OUTSIDE_ROOT")
        self._write_json(destination, value)
        return destination

    def freeze_source_contract(
        self,
        job_id: str,
        *,
        expected_version: int,
        source_contract: dict[str, Any],
    ) -> JobSnapshot:
        job = self.get(job_id)
        if job.version != expected_version:
            raise VersionConflict("JOB_VERSION_CONFLICT")
        music_contract = source_contract.get("music_timeline_contract")
        if "background_music" in job.inputs and (
            not isinstance(music_contract, dict) or not isinstance(music_contract.get("windows"), list) or not music_contract["windows"]
        ):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
        target_truth = self._read_json(self.job_dir(job_id) / "analysis" / "target_truth.json")
        intake = self._rehydrate_intake(job, source_contract)
        execution_map = build_execution_map(
            intake=intake,
            source_contract=source_contract,
            target_truth=target_truth,
        )
        target_truth = self._resolve_target_truth(
            job=job,
            execution_map=execution_map,
        )
        execution_map = build_execution_map(
            intake=intake,
            source_contract=source_contract,
            target_truth=target_truth,
        )
        execution_map["input_slots_sha256"] = self._sha256_text(_canonical_json(job.inputs))
        execution_map["provisional"] = False
        if "background_music" in job.inputs and isinstance(music_contract, dict):
            execution_map["background_music"]["timeline_contract_sha256"] = self._sha256_text(
                _canonical_json(music_contract)
            )
            execution_map["background_music"]["timeline_contract"] = music_contract
            execution_map["background_music"]["timeline_status"] = "frozen"
            self._write_json(self.job_dir(job_id) / "analysis" / "music_timeline_contract.json", music_contract)
        self._write_json(self.job_dir(job_id) / "analysis" / "target_truth.json", target_truth)
        self._write_json(self.job_dir(job_id) / "analysis" / "source_fidelity_contract.json", source_contract)
        self._write_json(self.job_dir(job_id) / "analysis" / "execution_map.json", execution_map)
        route_preview = build_route_preview(execution_map)

        def mutate(current: dict[str, Any]) -> dict[str, Any]:
            current["execution_map"] = execution_map
            current["route_preview"] = route_preview
            return current

        return self.update(
            job_id,
            expected_version=expected_version,
            mutate=mutate,
            event="SOURCE_CONTRACT_FROZEN",
        )

    def _resolve_target_truth(
        self,
        *,
        job: JobSnapshot,
        execution_map: Mapping[str, object],
    ) -> dict[str, object]:
        if not app_evidence_required(execution_map):
            target_truth = build_target_truth(slots=job.inputs, app_evidence=None)
            target_truth["status"] = "skipped"
            return target_truth
        url_record = job.inputs.get("app_store_url")
        url = url_record.get("value") if isinstance(url_record, Mapping) else None
        app_evidence = execution_map.get("app_evidence")
        purpose = app_evidence.get("purpose") if isinstance(app_evidence, Mapping) else None
        if not isinstance(url, str) or not url or not isinstance(purpose, list) or not purpose:
            raise ValueError("APP_EVIDENCE_INPUT_REQUIRED")
        if self._app_evidence_resolver is None:
            raise ValueError("APP_EVIDENCE_RESOLVER_REQUIRED")
        bundle = self._app_evidence_cache.get_or_resolve(
            url=url,
            purpose=tuple(str(item) for item in purpose),
            store_locale=self._app_evidence_locale,
            parser_version=self._app_evidence_parser_version,
            resolver=lambda: self._app_evidence_resolver(url=url, purpose=tuple(str(item) for item in purpose)),
        )
        self._write_json(self.job_dir(job.job_id) / "analysis" / "app_evidence_bundle.json", bundle)
        target_truth = build_target_truth(slots=job.inputs, app_evidence=bundle)
        target_truth["status"] = "resolved"
        return target_truth

    def _copy_input(self, input_dir: Path, slot_id: str, source: Path) -> dict[str, Any]:
        destination = input_dir / f"{slot_id}{source.suffix.lower()}"
        shutil.copyfile(source, destination)
        return {
            "kind": "file",
            "relative_path": str(destination.relative_to(input_dir.parent)).replace("\\", "/"),
            "original_name": source.name,
            "mime_type": mimetypes.guess_type(destination.name)[0] or "application/octet-stream",
            "sha256": sha256_file(destination),
            "byte_count": destination.stat().st_size,
        }

    @staticmethod
    def _sha256_text(value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JOB_ARTIFACT_INVALID")
        return value

    @staticmethod
    def _rehydrate_intake(job: JobSnapshot, source_contract: dict[str, Any]) -> ValidatedIntake:
        input_ids = set(job.inputs)
        optional_files = {slot_id: Path(slot_id) for slot_id in input_ids if slot_id in {
            "new_product_image", "new_model_image", "ui_screenshot", "ui_operation_video", "tail_video"
        }}
        extension_files = {"background_music": Path("background_music")} if "background_music" in input_ids else {}
        app_record = job.inputs.get("app_store_url") or {}
        regions = source_contract.get("regions") or source_contract.get("cuts") or []
        end_ms = max(
            (int(region.get("end_ms") or 0) for region in regions if isinstance(region, dict)),
            default=0,
        )
        audio_policy = (job.execution_map or {}).get("audio_policy") or {}
        opaque_policies = {
            region_kind: policy
            for region_kind, policy in audio_policy.items()
            if region_kind in {"ui", "tail"} and isinstance(policy, str) and policy.startswith("opaque_audio_")
        }
        return ValidatedIntake(
            source_video=Path("source_video"),
            optional_files=optional_files,
            extension_files=extension_files,
            app_store_url=app_record.get("value") if isinstance(app_record, dict) else None,
            output_language=job.output_language,
            duration_seconds=end_ms / 1000,
            admission=job.admission,
            routes=job.routes,
            opaque_audio_policies=opaque_policies,
        )

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(_canonical_json(value))
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)

    @staticmethod
    def _append_event(job_dir: Path, event: dict[str, Any]) -> None:
        with (job_dir / "events.ndjson").open("a", encoding="utf-8") as output:
            output.write(_canonical_json(event) + "\n")
