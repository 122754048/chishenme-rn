"""Internal high-fidelity stage adapter ports.

The adapter embeds Invocation A and B inside the existing ``build_script`` and
``compile_seedance20_prompt`` stage handlers.  It is deliberately not a new
RunState stage and never calls a provider.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import inspect
import json
from pathlib import Path
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from typing import Any, Callable

from .errors import ReplicationError


_RUNNINGHUB_SUBMIT_MODULE: Any | None = None
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _load_runninghub_submit_module() -> Any:
    """Load the bundled RunningHub fixed-B payload authority from deployed bytes."""

    global _RUNNINGHUB_SUBMIT_MODULE
    if _RUNNINGHUB_SUBMIT_MODULE is not None:
        return _RUNNINGHUB_SUBMIT_MODULE
    script = (
        Path(__file__).resolve().parents[1]
        / "bundled-skills"
        / "seedance-storyboard-replication"
        / "scripts"
        / "runninghub_seedance_submit.py"
    )
    module_name = "usfr_high_fidelity_runninghub_submit"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError("bundled Seedance payload validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(script.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    _RUNNINGHUB_SUBMIT_MODULE = module
    return module


class HighFidelityStageAdapter:
    INVOCATION_A_TIMEOUT_SECONDS = 120.0

    def __init__(self, invocation_adapter: Any, *, invocation_a_timeout_seconds: float = INVOCATION_A_TIMEOUT_SECONDS) -> None:
        if invocation_adapter is None:
            raise ValueError("invocation_adapter is required")
        try:
            invocation_a_timeout_seconds = float(invocation_a_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("invocation_a_timeout_seconds must be positive") from exc
        if invocation_a_timeout_seconds <= 0:
            raise ValueError("invocation_a_timeout_seconds must be positive")
        self.invocation_adapter = invocation_adapter
        self.invocation_a_timeout_seconds = invocation_a_timeout_seconds

    @staticmethod
    def _record_metric(context: Any, *, duration_seconds: float, status: str) -> None:
        recorder = getattr(context, "record_profile_metric", None)
        if not callable(recorder):
            return
        try:
            recorder(
                "seedance_invocation_a",
                duration_seconds=max(0.0, float(duration_seconds)),
                status=status,
            )
        except TypeError:
            # Narrow compatibility for a deployment-owned sink that exposes
            # positional arguments while preserving the canonical keyword
            # contract for WorkerStageContext.
            recorder("seedance_invocation_a", max(0.0, float(duration_seconds)), status)

    def _invoke_a_with_deadline(self, *, context: Any, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        timeout = self.invocation_a_timeout_seconds
        try:
            context_timeout = getattr(context, "invocation_a_timeout_seconds", None)
            if context_timeout is not None:
                timeout = float(context_timeout)
        except (TypeError, ValueError):
            timeout = self.invocation_a_timeout_seconds
        if timeout <= 0:
            timeout = self.invocation_a_timeout_seconds

        started = time.monotonic()
        done = threading.Event()
        result_box: dict[str, Any] = {}

        def invoke() -> None:
            try:
                result_box["value"] = self.invocation_adapter.invoke_a(context=context, **dict(payload))
            except BaseException as exc:  # propagate the original failure below
                result_box["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=invoke, name="seedance-invocation-a", daemon=True)
        thread.start()
        if not done.wait(timeout):
            duration = min(max(0.0, time.monotonic() - started), timeout)
            self._record_metric(context, duration_seconds=duration, status="timeout")
            raise ReplicationError(
                "INVOCATION_A_TIMEOUT",
                "Seedance Invocation A exceeded the 120-second deadline",
                category="contract",
                retryable=True,
                user_action_required=True,
                details={"timeout_seconds": 120},
                http_status=503,
            )
        duration = max(0.0, time.monotonic() - started)
        error = result_box.get("error")
        if error is not None:
            self._record_metric(context, duration_seconds=min(duration, timeout), status="failed")
            raise error
        self._record_metric(context, duration_seconds=min(duration, timeout), status="succeeded")
        value = result_box.get("value")
        if not isinstance(value, Mapping):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "Invocation A adapter must return an object",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        return value

    @staticmethod
    def _call_handler(handler: Callable[..., Mapping[str, Any]] | Any, context: Any) -> Mapping[str, Any]:
        stage_port = getattr(handler, "run", None)
        if stage_port is not None and callable(stage_port) and not callable(handler):
            input_artifacts = getattr(context, "input_artifacts", [])
            try:
                signature = inspect.signature(stage_port)
            except (TypeError, ValueError):
                value = stage_port(context=context, input_artifacts=input_artifacts)
            else:
                try:
                    signature.bind(context=context, input_artifacts=input_artifacts)
                except TypeError:
                    try:
                        signature.bind(context, input_artifacts)
                    except TypeError as exc:
                        raise ReplicationError(
                            "CONTRACT_INVALID",
                            "StagePort.run signature must accept context and input_artifacts",
                            category="contract",
                            user_action_required=True,
                            http_status=422,
                        ) from exc
                    value = stage_port(context, input_artifacts)
                else:
                    value = stage_port(context=context, input_artifacts=input_artifacts)
            if not isinstance(value, Mapping):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "StagePort.run must return an object",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            return value
        try:
            signature = inspect.signature(handler)
        except (TypeError, ValueError):
            return handler()
        for kwargs in ({"context": context}, {"stage_context": context}, {}):
            try:
                signature.bind(**kwargs)
            except TypeError:
                continue
            value = handler(**kwargs)
            if not isinstance(value, Mapping):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "high-fidelity stage handler must return an object",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            return value
        try:
            signature.bind(context)
        except TypeError as exc:
            raise ReplicationError(
                "CONTRACT_INVALID",
                "high-fidelity stage handler signature is unsupported",
                category="contract",
                user_action_required=True,
                http_status=422,
            ) from exc
        value = handler(context)
        if not isinstance(value, Mapping):
            raise ReplicationError(
                "CONTRACT_INVALID",
                "high-fidelity stage handler must return an object",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        return value

    @staticmethod
    def _frozen_segment_plan(
        context: Any,
    ) -> tuple[Mapping[str, Any], str] | None:
        artifacts = getattr(context, "artifacts", ()) or ()
        matches = [
            item
            for item in artifacts
            if isinstance(item, Mapping) and str(item.get("kind") or "") == "segment_plan"
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B requires exactly one frozen Stage 7 segment plan artifact",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        descriptor = matches[0]
        declared_sha = str(descriptor.get("sha256") or "").lower()
        if len(declared_sha) != 64:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "frozen segment plan artifact is missing its SHA-256",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        materialize = getattr(context, "materialize_artifact", None)
        if not callable(materialize):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B cannot materialize the frozen segment plan artifact",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        try:
            with materialize("segment_plan", sha256=declared_sha) as media:
                raw = Path(media.path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != declared_sha:
                raise ValueError("materialized bytes do not match the published SHA-256")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError("segment plan artifact must be a JSON object")
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if canonical != raw:
                raise ValueError("segment plan artifact bytes are not canonical JSON")
            return dict(value), declared_sha
        except ReplicationError:
            raise
        except Exception as exc:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "frozen Stage 7 segment plan artifact is invalid",
                category="contract",
                user_action_required=True,
                details={"reason": str(exc)},
                http_status=422,
            ) from exc

    @staticmethod
    def _source_audio_contracts_required(context: Any) -> bool:
        kinds = {
            str(item.get("kind") or "")
            for item in (getattr(context, "artifacts", ()) or ())
            if isinstance(item, Mapping)
        }
        required = {
            "performance_audio_source_contract",
            "audio_lyrics_beat_contract",
        }
        present = kinds & required
        if present and present != required:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "source-audio evidence artifacts are incomplete",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        return present == required

    @staticmethod
    def _frozen_performance_line_contract(
        context: Any,
    ) -> tuple[Mapping[str, Any], str] | None:
        """Load approved source-audio performance text, never audio media."""

        artifacts = getattr(context, "artifacts", ()) or ()
        matches = [
            item for item in artifacts
            if isinstance(item, Mapping)
            and str(item.get("kind") or "") == "performance_line_contract"
        ]
        source_audio_required = HighFidelityStageAdapter._source_audio_contracts_required(context)
        if not matches:
            if source_audio_required:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B requires the approved performance line contract",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            return None
        if len(matches) != 1:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B requires exactly one approved performance line contract",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        descriptor = matches[0]
        declared_sha = str(descriptor.get("sha256") or "").lower()
        if len(declared_sha) != 64:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "approved performance line contract is missing its SHA-256",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        materialize = getattr(context, "materialize_artifact", None)
        if not callable(materialize):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B cannot materialize the approved performance line contract",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        try:
            with materialize("performance_line_contract", sha256=declared_sha) as media:
                raw = Path(media.path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != declared_sha:
                raise ValueError("materialized bytes do not match the published SHA-256")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, Mapping) or value.get("contract") != "performance-line/v1":
                raise ValueError("artifact must be a performance-line/v1 object")
            cuts = value.get("cuts")
            if not isinstance(cuts, list) or not cuts:
                raise ValueError("artifact must contain performance Cut contracts")
            canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if canonical != raw:
                raise ValueError("artifact bytes are not canonical JSON")
            contract = dict(value)
            if source_audio_required:
                HighFidelityStageAdapter._validate_confirmed_source_audio_performance(
                    context=context,
                    contract=contract,
                )
            return contract, declared_sha
        except ReplicationError:
            raise
        except Exception as exc:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "approved performance line contract is invalid",
                category="contract",
                user_action_required=True,
                details={"reason": str(exc)},
                http_status=422,
            ) from exc

    @staticmethod
    def _validate_confirmed_source_audio_performance(
        *,
        context: Any,
        contract: Mapping[str, Any],
    ) -> None:
        """Bind B's published performance artifact to the approved CAS sidecar."""

        snapshot = getattr(context, "snapshot", None)
        revision = getattr(snapshot, "current_script_revision", None)
        script_sha = str(getattr(snapshot, "approved_script_sha256", "") or "").lower()
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or _SHA256.fullmatch(script_sha) is None
        ):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B requires the exact approved script revision",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
        if not callable(getter):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B requires the approved script-line sidecar",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        sidecar = getter(getattr(context, "job_id", ""), revision)
        if not isinstance(sidecar, Mapping):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B requires user-confirmed script lines",
                category="contract",
                user_action_required=True,
                http_status=422,
            )

        try:
            from scripts.line_contract import validate_line_contracts
            from .performance_audio_contracts import canonical_json_sha256

            approved_lines = validate_line_contracts(sidecar.get("line_contracts"))
        except Exception as exc:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B requires canonical confirmed script lines",
                category="contract",
                user_action_required=True,
                details={"reason": str(exc)},
                http_status=422,
            ) from exc

        timeline_sha = str(sidecar.get("source_content_timeline_sha256") or "").lower()
        approved_lines_sha = canonical_json_sha256(approved_lines)
        if (
            sidecar.get("contract") != "approved-script-lines/v1"
            or sidecar.get("revision") != revision
            or sidecar.get("script_sha256") != script_sha
            or _SHA256.fullmatch(timeline_sha) is None
            or sidecar.get("line_contracts_sha256") != approved_lines_sha
            or any(line.get("source_content_timeline_sha256") != timeline_sha for line in approved_lines)
        ):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "approved script sidecar is not bound to the frozen timeline SHA",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        if (
            contract.get("script_revision") != revision
            or contract.get("script_sha256") != script_sha
            or contract.get("source_content_timeline_sha256") != timeline_sha
            or contract.get("line_contracts_sha256") != approved_lines_sha
        ):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "approved performance line contract differs from the confirmed timeline SHA",
                category="contract",
                user_action_required=True,
                http_status=422,
            )

        cuts = contract.get("cuts")
        if not isinstance(cuts, list):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "approved performance line contract Cut rows are invalid",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        approved_by_line_id = {line["line_id"]: line for line in approved_lines}
        cuts_by_line_id = {
            item.get("line_id"): item
            for item in cuts
            if isinstance(item, Mapping) and isinstance(item.get("line_id"), str)
        }
        if len(cuts_by_line_id) != len(cuts) or set(cuts_by_line_id) != set(approved_by_line_id):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "approved performance line contract coverage differs from confirmed script lines",
                category="contract",
                user_action_required=True,
                http_status=422,
            )
        for line_id, approved in approved_by_line_id.items():
            performance = cuts_by_line_id[line_id]
            lyric_status = str(performance.get("lyric_status") or "").lower()
            expected_content_type = {
                "spoken": "spoken",
                "sung": "sung",
                "singing": "sung",
                "instrumental": "instrumental",
                "inaudible": "inaudible",
            }.get(str(performance.get("performance_mode") or "").lower())
            expected_text = (
                approved["text"]["exact"]
                if approved["content_type"] in {"spoken", "sung"}
                else lyric_status
            )
            if (
                performance.get("cut_id") != approved["cut_id"]
                or performance.get("source_content_timeline_sha256") != timeline_sha
                or performance.get("content_type") != approved["content_type"]
                or performance.get("speaker_assignment") != approved["speaker_assignment"]
                or performance.get("source_time") != {
                    "start_ms": approved["time"]["start_ms"],
                    "end_ms": approved["time"]["end_ms"],
                }
                or performance.get("segment_time") != {
                    "start_ms": 0,
                    "end_ms": approved["time"]["end_ms"] - approved["time"]["start_ms"],
                }
                or lyric_status not in {"verified", "instrumental", "inaudible"}
                or expected_content_type != approved["content_type"]
                or performance.get("exact_sung_text") != expected_text
            ):
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "approved performance line fails final source-audio validation",
                    category="contract",
                    user_action_required=True,
                    details={"line_id": line_id},
                    http_status=422,
                )

    @staticmethod
    def _request_segment_id(payload: Mapping[str, Any]) -> str | None:
        segment_id = payload.get("segment_id")
        if isinstance(segment_id, str) and segment_id.strip():
            return segment_id.strip()
        prompt_request = payload.get("prompt_request")
        prompt_segment = (
            prompt_request.get("segment")
            if isinstance(prompt_request, Mapping)
            else None
        )
        if isinstance(prompt_segment, Mapping):
            value = prompt_segment.get("segment_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _provider_binding(
        *,
        segment_id: str,
        segment_plan_sha256: str,
        request: Mapping[str, Any],
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = result or {}
        performance_line_contract_sha256 = request.get("performance_line_contract_sha256")
        source_content_timeline_sha256 = request.get("source_content_timeline_sha256")
        if (performance_line_contract_sha256 is None) != (source_content_timeline_sha256 is None):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B source-audio binding requires both performance and timeline digests",
                category="contract",
                user_action_required=True,
                details={"segment_id": segment_id},
                http_status=422,
            )
        if performance_line_contract_sha256 is not None:
            if (
                not isinstance(performance_line_contract_sha256, str)
                or _SHA256.fullmatch(performance_line_contract_sha256) is None
            ):
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B performance line contract digest must be a lowercase SHA-256",
                    category="contract",
                    user_action_required=True,
                    details={"segment_id": segment_id},
                    http_status=422,
                )
            if (
                not isinstance(source_content_timeline_sha256, str)
                or _SHA256.fullmatch(source_content_timeline_sha256) is None
            ):
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B source-content timeline digest must be a lowercase SHA-256",
                    category="contract",
                    user_action_required=True,
                    details={"segment_id": segment_id},
                    http_status=422,
                )
            observed_digest = result.get("performance_line_contract_sha256")
            if observed_digest != performance_line_contract_sha256:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "Provider result performance line contract digest is missing or differs from Invocation B",
                    category="contract",
                    user_action_required=True,
                    details={"segment_id": segment_id},
                    http_status=422,
                )
            observed_timeline = result.get("source_content_timeline_sha256")
            if observed_timeline != source_content_timeline_sha256:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "Provider result source-content timeline digest is missing or differs from Invocation B",
                    category="contract",
                    user_action_required=True,
                    details={"segment_id": segment_id},
                    http_status=422,
                )
        raw_payload = result.get("provider_payload")
        if raw_payload is None:
            raw_payload = request.get("provider_payload")
        template = request.get("provider_payload_template")
        if raw_payload is not None and template is not None:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B accepts provider_payload or provider_payload_template, not both",
                category="contract",
                user_action_required=True,
                details={"segment_id": segment_id},
                http_status=422,
            )
        if raw_payload is None and isinstance(template, Mapping):
            compiled_prompt = result.get("compiled_prompt")
            if not isinstance(compiled_prompt, str) or not compiled_prompt:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "provider_payload_template requires the exact Invocation B prompt",
                    category="contract",
                    user_action_required=True,
                    details={"segment_id": segment_id},
                    http_status=422,
                )
            raw_payload = json.loads(
                json.dumps(template, ensure_ascii=False)
            )
            if not isinstance(raw_payload.get("prompt"), str):
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "provider_payload_template is missing its direct prompt",
                    category="contract",
                    user_action_required=True,
                    details={"segment_id": segment_id},
                    http_status=422,
                )
            raw_payload["prompt"] = compiled_prompt
        if not isinstance(raw_payload, Mapping):
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                "Invocation B requires the exact canonical provider_payload",
                category="contract",
                user_action_required=True,
                details={"segment_id": segment_id},
                http_status=422,
            )
        payload = dict(raw_payload)
        validator = _load_runninghub_submit_module()
        try:
            prompt = validator.validate_runninghub_standard_payload(payload, fixed_b=True)
            video_urls = payload.get("videoUrls")
            raw_video_reference = request.get("video_reference")
            video_reference = None
            if video_urls or raw_video_reference is not None:
                expected_segment = None
                if video_urls:
                    plan = request.get("segment_plan")
                    plan_segments = plan.get("segments") if isinstance(plan, Mapping) else None
                    if not isinstance(plan_segments, list):
                        raise ValueError("video reference requires the frozen segment plan")
                    expected_segment = next(
                        (
                            item
                            for item in plan_segments
                            if isinstance(item, Mapping) and item.get("segment_id") == segment_id
                        ),
                        None,
                    )
                    if not isinstance(expected_segment, Mapping):
                        raise ValueError("video reference segment is absent from the frozen segment plan")
                video_reference = validator.validate_video_reference_binding(
                    payload,
                    raw_video_reference if isinstance(raw_video_reference, Mapping) else None,
                    expected_segment=expected_segment,
                )
            compiled_prompt = result.get("compiled_prompt")
            if compiled_prompt is not None and prompt != compiled_prompt:
                raise ValueError("provider payload prompt differs from Invocation B output")
            request_sha256 = validator.runninghub_standard_request_sha256(payload, fixed_b=True)
            for source_name, source in (("request", request), ("result", result)):
                declared = source.get("request_sha256")
                if declared is not None and declared != request_sha256:
                    raise ValueError(
                        f"{source_name} request_sha256 differs from canonical provider payload"
                    )
        except ReplicationError:
            raise
        except Exception as exc:
            raise ReplicationError(
                "PROMPT_INTEGRITY_FAILED",
                f"Invocation B provider payload is not the canonical fixed-B request: {exc}",
                category="contract",
                user_action_required=True,
                details={"segment_id": segment_id, "reason": str(exc)},
                http_status=422,
            ) from exc
        binding = {
            "segment_id": segment_id,
            "segment_plan_sha256": segment_plan_sha256,
            "provider_payload": payload,
            "request_sha256": request_sha256,
        }
        if performance_line_contract_sha256 is not None:
            binding["performance_line_contract_sha256"] = performance_line_contract_sha256
            binding["source_content_timeline_sha256"] = source_content_timeline_sha256
        if video_reference is not None:
            binding["video_reference"] = video_reference
        return binding

    @staticmethod
    def _segment_aggregate(
        *,
        schema_version: str,
        bindings: list[Mapping[str, Any]],
        source_rows: list[Mapping[str, Any]],
        source_key: str,
        nested_key: str,
    ) -> dict[str, Any]:
        segments: list[dict[str, Any]] = []
        for binding, source in zip(bindings, source_rows):
            nested = source.get(source_key)
            if not isinstance(nested, Mapping):
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    f"Stage 9 requires a per-segment {nested_key}",
                    category="contract",
                    user_action_required=True,
                    details={"segment_id": binding.get("segment_id")},
                    http_status=422,
                )
            segments.append({**dict(binding), nested_key: dict(nested)})
        aggregate: dict[str, Any] = {
            "schema_version": schema_version,
            "segments": segments,
        }
        if len(segments) == 1:
            # Preserve the old single-segment object fields as root aliases
            # while retaining the canonical segmented envelope.
            aggregate = {
                **dict(segments[0][nested_key]),
                **dict(bindings[0]),
                "schema_version": schema_version,
                "segments": segments,
            }
        return aggregate

    @staticmethod
    def _publish_stage9_aggregate(
        *,
        context: Any,
        request: Mapping[str, Any],
        kind: str,
        aggregate: Mapping[str, Any],
    ) -> list[dict[str, Any]] | None:
        """Publish the one canonical Stage-9 artifact in production.

        Local compatibility handlers may still return their historical
        descriptor.  A deployed WorkerStageContext must publish the bytes
        after B has produced the exact prompt/payload, otherwise the stage
        would persist a pre-B placeholder instead of the aggregate contract.
        """

        existing = request.get("published_artifacts")
        descriptors = [dict(item) for item in existing or [] if isinstance(item, Mapping)]
        if getattr(context, "allow_local_paths", True):
            return descriptors if existing is not None else None
        publisher = getattr(context, "publish_artifact", None)
        if not callable(publisher):
            raise ReplicationError(
                "OBJECT_STORE_UNAVAILABLE",
                f"{kind} aggregate requires the lease-owned artifact publisher",
                category="storage",
                user_action_required=True,
                http_status=503,
            )
        raw = json.dumps(
            aggregate,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        prior = next((item for item in descriptors if item.get("kind") == kind), {})
        metadata = dict(prior.get("metadata") or {})
        metadata.setdefault("producer_stage", str(getattr(context, "stage", "")))
        metadata.setdefault(
            "logical_path",
            "seedance/seedance_input_contract.json"
            if kind == "seedance_input_contract"
            else "seedance/seedance_request_audit.json",
        )
        metadata.setdefault("parent_digests", {})
        identity = getattr(context, "execution_identity", {})
        if isinstance(identity, Mapping) and identity.get("profile_digest"):
            metadata.setdefault("profile_digest", identity["profile_digest"])
        metadata.setdefault("schema_version", aggregate.get("schema_version", "v1"))
        published = publisher(
            kind=kind,
            stream=io.BytesIO(raw),
            content_type="application/json",
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            metadata=metadata,
        )
        return [item for item in descriptors if item.get("kind") != kind] + [dict(published)]

    @staticmethod
    def _active(context: Any) -> bool:
        profile = getattr(context, "profile_snapshot", None)
        if not isinstance(profile, Mapping) or profile.get("profile") != "high_fidelity_hybrid_v1":
            return False
        mode = str(profile.get("activation_mode") or "active").strip().lower()
        return mode not in {"shadow", "legacy", "disabled"}

    def run_stage(self, *, context: Any, handler: Callable[..., Mapping[str, Any]] | Any) -> dict[str, Any]:
        stage = str(getattr(context, "stage", ""))
        if not self._active(context):
            # The profile adapter is additive.  A legacy/profile-disabled run
            # must still execute the canonical stage handler and preserve its
            # output; only the internal A/B sidecar is marked skipped.  The
            # previous implementation returned the skip marker before calling
            # ``build_script``/``compile_seedance20_prompt``, silently
            # disconnecting those existing stages whenever a wrapper was
            # installed globally.
            request = self._call_handler(handler, context)
            if stage == "build_script":
                self._record_metric(context, duration_seconds=0.0, status="skipped")
                return {**dict(request), "invocation_a": {"status": "skipped", "reason": "legacy_profile"}}
            if stage == "compile_seedance20_prompt":
                return {**dict(request), "invocation_b": {"status": "skipped", "reason": "legacy_profile"}}
            return dict(request)
        if stage == "build_script":
            snapshot = getattr(context, "snapshot", None)
            revision = getattr(snapshot, "current_script_revision", None)
            approved_sha = getattr(snapshot, "approved_script_sha256", None)
            getter = getattr(getattr(context, "job_store", None), "get_script_approval", None)
            approval = (
                getter(getattr(context, "job_id", ""), revision)
                if isinstance(revision, int) and not isinstance(revision, bool)
                and isinstance(approved_sha, str) and approved_sha
                and callable(getter)
                else None
            )
            if approval is not None:
                # The original script lease owns the unconfirmed GPT draft.
                # Re-entry after the user CAS approval consumes only immutable
                # artifacts + the JobStore sidecar; never invoke GPT, source
                # analysis, or Invocation A a second time.
                from .performance_audio_contracts import recover_confirmed_script_contracts

                recovered = recover_confirmed_script_contracts(context)
                return {
                    **recovered,
                    "invocation_a": {
                        "status": "recovered",
                        "performance_line_contract_sha256": recovered.get(
                            "performance_line_contract_sha256"
                        ),
                        "source_content_timeline_sha256": approval.get(
                            "source_content_timeline_sha256"
                        ),
                    },
                }
        request = self._call_handler(handler, context)
        if stage == "build_script":
            # The canonical build_script handler may return only the frozen
            # analysis/route artifacts.  Project those artifacts into the
            # existing Invocation-A request shape here, inside the same
            # stage, so deployments do not need a second ad-hoc analysis
            # pass or a custom provider-facing stage.
            payload = request.get("invocation_a_request")
            if not isinstance(payload, Mapping):
                from .high_fidelity_projection import build_invocation_a_request

                payload = build_invocation_a_request(context, request)
                request = {**dict(request), "invocation_a_request": payload}
            if not isinstance(payload, Mapping):
                raise ReplicationError(
                    "CONTRACT_INVALID",
                    "build_script requires invocation_a_request",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            result = self._invoke_a_with_deadline(context=context, payload=payload)
            return {**dict(request), "invocation_a": result}
        if stage == "compile_seedance20_prompt":
            singular = request.get("invocation_b_request")
            plural = request.get("invocation_b_requests")
            if singular is not None and plural is not None:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "compile_seedance20_prompt accepts either invocation_b_request or invocation_b_requests, not both",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            if plural is not None:
                if (
                    not isinstance(plural, list)
                    or not 1 <= len(plural) <= 2
                    or any(not isinstance(item, Mapping) for item in plural)
                ):
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "invocation_b_requests must contain one or two request objects",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                payloads = [dict(item) for item in plural]
            elif isinstance(singular, Mapping):
                payloads = [dict(singular)]
            else:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "compile_seedance20_prompt requires invocation_b_request or invocation_b_requests",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )

            frozen = self._frozen_segment_plan(context)
            if frozen is None:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B requires the frozen Stage 7 segment plan artifact",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            segment_plan, segment_plan_sha256 = frozen
            frozen_performance = self._frozen_performance_line_contract(context)
            source_audio_required = self._source_audio_contracts_required(context)

            raw_segments = segment_plan.get("segments")
            if not isinstance(raw_segments, list) or not 1 <= len(raw_segments) <= 2:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "final segment plan must contain one or two segments",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            expected_segment_ids = [
                str(item.get("segment_id") or "")
                for item in raw_segments
                if isinstance(item, Mapping)
            ]
            if (
                len(expected_segment_ids) != len(raw_segments)
                or any(not item for item in expected_segment_ids)
                or len(expected_segment_ids) != len(set(expected_segment_ids))
            ):
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "final segment plan has invalid segment IDs",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            if len(payloads) != len(expected_segment_ids):
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B request count must equal the frozen segment count",
                    category="contract",
                    user_action_required=True,
                    details={
                        "expected_segment_ids": expected_segment_ids,
                        "request_count": len(payloads),
                    },
                    http_status=422,
                )
            normalized_payloads: list[dict[str, Any]] = []
            observed_segment_ids: list[str] = []
            for payload in payloads:
                supplied_plan = payload.get("segment_plan")
                if isinstance(supplied_plan, Mapping) and dict(supplied_plan) != dict(segment_plan):
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "Invocation B segment plan differs from the frozen Stage 7 artifact",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                normalized = dict(payload)
                normalized["segment_plan"] = segment_plan
                segment_id = self._request_segment_id(normalized)
                if segment_id is None and len(expected_segment_ids) == 1:
                    segment_id = expected_segment_ids[0]
                    normalized["segment_id"] = segment_id
                if segment_id is None:
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "each Invocation B request requires a segment_id",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                if frozen_performance is not None:
                    contract, contract_sha256 = frozen_performance
                    raw_lines = contract.get("cuts")
                    assert isinstance(raw_lines, list)
                    planned = next(
                        (item for item in raw_segments if isinstance(item, Mapping) and str(item.get("segment_id") or "") == segment_id),
                        None,
                    )
                    if not isinstance(planned, Mapping):
                        raise ReplicationError(
                            "PROMPT_INTEGRITY_FAILED",
                            "performance contract cannot be bound to the final segment",
                            category="contract",
                            user_action_required=True,
                            http_status=422,
                        )
                    cut_ids = [str(item) for item in planned.get("cut_ids") or []]
                    lines_by_cut = {
                        str(item.get("cut_id") or ""): dict(item)
                        for item in raw_lines
                        if isinstance(item, Mapping)
                    }
                    if set(cut_ids) - set(lines_by_cut):
                        raise ReplicationError(
                            "PROMPT_INTEGRITY_FAILED",
                            "performance contract Cut coverage differs from the final segment",
                            category="contract",
                            user_action_required=True,
                            details={"segment_id": segment_id},
                            http_status=422,
                        )
                    prompt_request = normalized.get("prompt_request")
                    if not isinstance(prompt_request, Mapping):
                        raise ReplicationError(
                            "PROMPT_INTEGRITY_FAILED",
                            "source-audio performance requires a structured Seedance prompt request",
                            category="contract",
                            user_action_required=True,
                            details={"segment_id": segment_id},
                            http_status=422,
                        )
                    prompt_request = dict(prompt_request)
                    lines = [lines_by_cut[cut_id] for cut_id in cut_ids]
                    supplied = prompt_request.get("performance_lines")
                    if supplied is not None and supplied != lines:
                        raise ReplicationError(
                            "PROMPT_INTEGRITY_FAILED",
                            "prompt performance lines differ from the approved source-audio contract",
                            category="contract",
                            user_action_required=True,
                            details={"segment_id": segment_id},
                            http_status=422,
                        )
                    prompt_request["performance_lines"] = lines
                    normalized["prompt_request"] = prompt_request
                    if source_audio_required:
                        timeline_sha = contract.get("source_content_timeline_sha256")
                        if not isinstance(timeline_sha, str) or _SHA256.fullmatch(timeline_sha) is None:
                            raise ReplicationError(
                                "PROMPT_INTEGRITY_FAILED",
                                "approved performance line contract is missing the frozen timeline digest",
                                category="contract",
                                user_action_required=True,
                                details={"segment_id": segment_id},
                                http_status=422,
                            )
                        normalized["performance_line_contract_sha256"] = contract_sha256
                        normalized["source_content_timeline_sha256"] = timeline_sha
                observed_segment_ids.append(segment_id)
                normalized_payloads.append(normalized)
            if observed_segment_ids != expected_segment_ids:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "Invocation B request segment IDs must exactly match the frozen segment plan order",
                    category="contract",
                    user_action_required=True,
                    details={
                        "expected_segment_ids": expected_segment_ids,
                        "observed_segment_ids": observed_segment_ids,
                    },
                    http_status=422,
                )

            def invoke(payload: Mapping[str, Any]) -> Mapping[str, Any]:
                invocation_payload = dict(payload)
                for stage9_key in (
                    "provider_payload",
                    "provider_payload_template",
                    "request_sha256",
                    "seedance_input_contract",
                ):
                    invocation_payload.pop(stage9_key, None)
                value = self.invocation_adapter.invoke_b(
                    context=context,
                    **invocation_payload,
                )
                if not isinstance(value, Mapping):
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "Invocation B adapter must return an object",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                return value

            if len(normalized_payloads) == 1:
                results = [invoke(normalized_payloads[0])]
            else:
                with ThreadPoolExecutor(
                    max_workers=len(normalized_payloads),
                    thread_name_prefix="seedance-invocation-b",
                ) as executor:
                    results = list(executor.map(invoke, normalized_payloads))
            normalized_results: list[dict[str, Any]] = []
            provider_bindings: list[dict[str, Any]] = []
            for expected_segment_id, value in zip(expected_segment_ids, results):
                result = dict(value)
                if result.get("status") != "ready":
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "Invocation B segment did not return ready status",
                        category="contract",
                        user_action_required=True,
                        details={"segment_id": expected_segment_id},
                        http_status=422,
                    )
                if result.get("segment_id") != expected_segment_id:
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "Invocation B result segment_id differs from the frozen plan",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                if result.get("segment_plan_sha256") != segment_plan_sha256:
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "Invocation B result is not bound to the frozen segment plan SHA-256",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                binding = self._provider_binding(
                    segment_id=expected_segment_id,
                    segment_plan_sha256=segment_plan_sha256,
                    request=normalized_payloads[len(normalized_results)],
                    result=result,
                )
                result.update(
                    provider_payload=binding["provider_payload"],
                    request_sha256=binding["request_sha256"],
                )
                if "performance_line_contract_sha256" in binding:
                    result["performance_line_contract_sha256"] = binding["performance_line_contract_sha256"]
                    result["source_content_timeline_sha256"] = binding["source_content_timeline_sha256"]
                normalized_results.append(result)
                provider_bindings.append(binding)

            input_contract = self._segment_aggregate(
                schema_version="seedance-input-contract-segments/v1",
                bindings=provider_bindings,
                source_rows=normalized_payloads,
                source_key="seedance_input_contract",
                nested_key="input_contract",
            )

            output = {
                **dict(request),
                "invocation_b_requests": normalized_payloads,
                "invocation_b_segments": normalized_results,
                "provider_requests": provider_bindings,
                "seedance_input_contract": input_contract,
            }
            published = self._publish_stage9_aggregate(
                context=context,
                request=request,
                kind="seedance_input_contract",
                aggregate=input_contract,
            )
            if published is not None:
                output["published_artifacts"] = published
            if len(normalized_results) == 1:
                output["invocation_b_request"] = normalized_payloads[0]
                output["invocation_b"] = normalized_results[0]
                output["provider_request"] = output["provider_requests"][0]
            else:
                output.pop("invocation_b_request", None)
            return output
        if stage == "audit_seedance_request":
            frozen = self._frozen_segment_plan(context)
            if frozen is None:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "request audit requires the frozen Stage 7 segment plan artifact",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            segment_plan, segment_plan_sha256 = frozen
            raw_segments = segment_plan.get("segments")
            expected_segment_ids = [
                str(item.get("segment_id") or "")
                for item in raw_segments or []
                if isinstance(item, Mapping)
            ]
            plural = request.get("seedance_request_audits")
            singular = request.get("seedance_request_audit")
            if plural is not None and singular is not None:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "audit_seedance_request accepts singular or plural audit input, not both",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            if plural is not None:
                if not isinstance(plural, list) or any(not isinstance(item, Mapping) for item in plural):
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "seedance_request_audits must be an array of segment audit objects",
                        category="contract",
                        user_action_required=True,
                        http_status=422,
                    )
                rows = [dict(item) for item in plural]
            elif isinstance(singular, Mapping):
                rows = [dict(singular)]
            else:
                return dict(request)
            if len(rows) != len(expected_segment_ids):
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "request audit count must equal the frozen segment count",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            bindings: list[dict[str, Any]] = []
            observed_ids: list[str] = []
            for expected_segment_id, row in zip(expected_segment_ids, rows):
                segment_id = str(row.get("segment_id") or expected_segment_id)
                observed_ids.append(segment_id)
                if row.get("segment_plan_sha256") not in {None, segment_plan_sha256}:
                    raise ReplicationError(
                        "PROMPT_INTEGRITY_FAILED",
                        "request audit is not bound to the frozen segment plan SHA-256",
                        category="contract",
                        user_action_required=True,
                        details={"segment_id": segment_id},
                        http_status=422,
                    )
                bindings.append(
                    self._provider_binding(
                        segment_id=segment_id,
                        segment_plan_sha256=segment_plan_sha256,
                        request=row,
                    )
                )
            if observed_ids != expected_segment_ids:
                raise ReplicationError(
                    "PROMPT_INTEGRITY_FAILED",
                    "request audit segment IDs must match the frozen plan order",
                    category="contract",
                    user_action_required=True,
                    http_status=422,
                )
            aggregate = self._segment_aggregate(
                schema_version="seedance-request-audit-segments/v1",
                bindings=bindings,
                source_rows=rows,
                source_key="audit",
                nested_key="audit",
            )
            output = {
                **dict(request),
                "seedance_request_audits": rows,
                "seedance_request_audit": aggregate,
                "provider_requests": bindings,
            }
            published = self._publish_stage9_aggregate(
                context=context,
                request=request,
                kind="seedance_request_audit",
                aggregate=aggregate,
            )
            if published is not None:
                output["published_artifacts"] = published
            if len(bindings) == 1:
                output["provider_request"] = bindings[0]
            return output
        # Other existing stages do not gain hidden Invocation work.
        return dict(request)


__all__ = ["HighFidelityStageAdapter"]
