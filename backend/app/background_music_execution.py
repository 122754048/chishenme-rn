"""Deployment-side routing for the optional USFR background-music extension.

This module deliberately leaves the packaged USFR Skill unchanged.  It only
selects existing operational stages when a deployment has installed a real
music execution adapter; StagePorts remain responsible for the actual audio
asset, prompt, mix, and QA evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
import json
from typing import Any

from server.ephemeral_driver import EXECUTABLE_STAGES, _dedupe
from server.errors import ReplicationError
from server.job_models import WorkMessage
from server.orchestrator import build_stage_plan
from server.performance_audio_contracts import build_background_music_performance_contract


MUSIC_EXECUTION_CONTRACT = "background_music_execution/v1"
MUSIC_STAGE_PORTS = (
    "analyze_dynamics",
    "build_script",
    "generate_storyboards",
    "compile_seedance20_prompt",
    "audit_seedance_request",
    "submit_provider_video",
    "wait_provider_video",
    "splice_timeline",
    "run_qc",
)
REQUIRED_MUSIC_CAPABILITIES = frozenset(
    {
        "source_music_timeline",
        "audio_asset_registration",
        "seedance_audio_reference",
        "exact_fragment_mix",
        "singing_qa",
    }
)
MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND = "music_timeline_contract"
PERFORMANCE_LINE_CONTRACT_ARTIFACT_KIND = "performance_line_contract"
BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1 = "background_music_execution_receipt/v1"
FORBIDDEN_MUSIC_OPERATIONS = ("loop", "atempo", "stretch", "pitch_shift", "silence_padding")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def is_background_music_manifest(manifest: object) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    extensions = manifest.get("extensions")
    return isinstance(extensions, Mapping) and extensions.get("background_music") is not None


def _background_music_error(error: Exception) -> ValueError:
    if isinstance(error, ReplicationError):
        return ValueError(f"{error.code}: {error.message}")
    return ValueError(str(error))


def _validated_uploaded_music(uploaded_audio: Mapping[str, object]) -> dict[str, object]:
    if (
        not isinstance(uploaded_audio, Mapping)
        or not _is_sha256(uploaded_audio.get("sha256"))
        or not isinstance(uploaded_audio.get("content_type"), str)
        or not uploaded_audio["content_type"].casefold().startswith("audio/")
    ):
        raise ValueError("BACKGROUND_MUSIC_MANIFEST_INVALID")
    return dict(uploaded_audio)


def _validated_audio_asset_receipt(
    receipt: Mapping[str, object],
    *,
    uploaded_audio_sha256: str,
) -> dict[str, object]:
    uri = receipt.get("asset_uri") if isinstance(receipt, Mapping) else None
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("asset_type") != "Audio"
        or receipt.get("status") != "active"
        or receipt.get("uploaded_audio_sha256") != uploaded_audio_sha256
        or not isinstance(uri, str)
        or not uri.startswith("asset://asset-")
    ):
        raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
    return dict(receipt)


def _validated_music_windows(
    music_timeline_contract: Mapping[str, object],
    *,
    uploaded_audio: Mapping[str, object],
) -> list[dict[str, object]]:
    """Validate exact uploaded-song ranges while retaining source event facts."""

    if not isinstance(music_timeline_contract, Mapping):
        raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    BackgroundMusicStagePort._validate_music_timeline(
        contract=music_timeline_contract,
        uploaded=uploaded_audio,
    )
    windows = music_timeline_contract.get("windows")
    if not isinstance(windows, list):  # protected by _validate_music_timeline; keeps the return typed.
        raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    return [dict(window) for window in windows if isinstance(window, Mapping)]


def _provider_payload(*, asset_uri: str, performance: Mapping[str, object]) -> dict[str, object]:
    mode = performance.get("mode")
    if mode == "verified_singing":
        lines = performance.get("singing_lines")
        if not isinstance(lines, list) or not lines:
            raise ValueError("VERIFIED_SINGING_EVIDENCE_REQUIRED")
        exact_lines = " | ".join(str(line["exact_sung_text"]) for line in lines)
        text = (
            "Use @Audio1 as the uploaded-song reference. Perform only these verified lyrics exactly: "
            f"{exact_lines}. Preserve the frozen source music windows, entries, exits, fades, silences, and transitions."
        )
    elif mode == "background_music_replacement":
        text = (
            "Use @Audio1 as the uploaded-song background-music reference. No lyric lip-sync. "
            "Preserve the frozen source music windows, entries, exits, fades, silences, and transitions."
        )
    else:
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID")
    return {
        "model": "seedance-2.0",
        "content": [
            {"type": "text", "text": text},
            {"type": "audio_url", "role": "reference_audio", "audio_url": {"url": asset_uri}},
        ],
    }


def _validate_verified_singing_windows(
    *,
    performance: Mapping[str, object],
    music_windows: list[dict[str, object]],
) -> None:
    if performance.get("mode") != "verified_singing":
        return
    lines = performance.get("singing_lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("VERIFIED_SINGING_EVIDENCE_REQUIRED")
    source_windows: list[tuple[int, int]] = []
    for window in music_windows:
        start = window.get("source_start_ms")
        end = window.get("source_end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError("VERIFIED_SINGING_WINDOW_REQUIRED")
        source_windows.append((start, end))
    for line in lines:
        source_time = line.get("source_time") if isinstance(line, Mapping) else None
        if not isinstance(source_time, Mapping):
            raise ValueError("VERIFIED_SINGING_WINDOW_REQUIRED")
        start = source_time.get("start_ms")
        end = source_time.get("end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("VERIFIED_SINGING_WINDOW_REQUIRED")
        if not any(window_start <= start and end <= window_end for window_start, window_end in source_windows):
            raise ValueError("VERIFIED_SINGING_WINDOW_REQUIRED")


def compile_background_music_execution_contract(
    *,
    uploaded_audio: Mapping[str, object],
    music_timeline_contract: Mapping[str, object],
    audio_asset_receipt: Mapping[str, object],
    user_confirmed_intent: str,
    performance_line_contract: Mapping[str, object] | None,
) -> dict[str, object]:
    """Compile a conditional Seedance ``@Audio1`` request without new stages.

    Singing is selected only by immutable confirmed performance evidence.  The
    fallback is an explicit BGM replacement, never a guessed lyric performance.
    """

    uploaded = _validated_uploaded_music(uploaded_audio)
    windows = _validated_music_windows(music_timeline_contract, uploaded_audio=uploaded)
    asset_receipt = _validated_audio_asset_receipt(
        audio_asset_receipt,
        uploaded_audio_sha256=str(uploaded["sha256"]),
    )
    try:
        performance = build_background_music_performance_contract(
            user_confirmed_intent=user_confirmed_intent,
            performance_line_contract=performance_line_contract,
        )
    except ReplicationError as error:
        raise _background_music_error(error) from error
    _validate_verified_singing_windows(performance=performance, music_windows=windows)
    payload = _provider_payload(asset_uri=str(asset_receipt["asset_uri"]), performance=performance)
    return {
        "contract": BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1,
        "mode": performance["mode"],
        "lyric_lip_sync_policy": performance["lyric_lip_sync_policy"],
        "performance_line_contract_sha256": performance["performance_line_contract_sha256"],
        "uploaded_audio_sha256": uploaded["sha256"],
        "uploaded_audio": uploaded,
        "music_timeline_contract": dict(music_timeline_contract),
        "user_confirmed_intent": user_confirmed_intent,
        "performance_line_contract": (
            None if performance_line_contract is None else dict(performance_line_contract)
        ),
        "source_music_windows": windows,
        "forbidden_operations": list(FORBIDDEN_MUSIC_OPERATIONS),
        "audio_asset_receipt": asset_receipt,
        "performance": performance,
        "provider_payload": payload,
    }


def _validate_frozen_execution_contract(execution_contract: Mapping[str, object]) -> None:
    try:
        expected = compile_background_music_execution_contract(
            uploaded_audio=execution_contract["uploaded_audio"],
            music_timeline_contract=execution_contract["music_timeline_contract"],
            audio_asset_receipt=execution_contract["audio_asset_receipt"],
            user_confirmed_intent=str(execution_contract["user_confirmed_intent"]),
            performance_line_contract=execution_contract.get("performance_line_contract"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID") from error
    if dict(execution_contract) != expected:
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID")


def execute_background_music(
    *,
    execution_contract: Mapping[str, object],
    final_mix_receipt: Mapping[str, object],
) -> dict[str, object]:
    """Accept only a final receipt that proves exact uploaded-song fragments.

    This is a verification boundary, not a media transformation: it binds the
    uploaded SHA, every source window and final MP4 SHA to the final mix.
    """

    if (
        not isinstance(execution_contract, Mapping)
        or execution_contract.get("contract") != BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1
        or execution_contract.get("mode") not in {"verified_singing", "background_music_replacement"}
        or execution_contract.get("forbidden_operations") != list(FORBIDDEN_MUSIC_OPERATIONS)
        or not _is_sha256(execution_contract.get("uploaded_audio_sha256"))
        or (
            execution_contract.get("mode") == "verified_singing"
            and not _is_sha256(execution_contract.get("performance_line_contract_sha256"))
        )
        or (
            execution_contract.get("mode") == "background_music_replacement"
            and execution_contract.get("performance_line_contract_sha256") is not None
        )
    ):
        raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_INVALID")
    _validate_frozen_execution_contract(execution_contract)
    expected_windows = execution_contract.get("source_music_windows")
    if not isinstance(expected_windows, list) or not expected_windows or any(
        not isinstance(window, Mapping) for window in expected_windows
    ):
        raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
    if (
        not isinstance(final_mix_receipt, Mapping)
        or final_mix_receipt.get("passed") is not True
        or final_mix_receipt.get("mode") != execution_contract.get("mode")
        or final_mix_receipt.get("uploaded_audio_sha256") != execution_contract.get("uploaded_audio_sha256")
        or final_mix_receipt.get("forbidden_operations") != list(FORBIDDEN_MUSIC_OPERATIONS)
        or not _is_sha256(final_mix_receipt.get("final_audio_sha256"))
        or not _is_sha256(final_mix_receipt.get("final_video_sha256"))
    ):
        raise ValueError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
    observed_windows = final_mix_receipt.get("window_receipts")
    if not isinstance(observed_windows, list) or len(observed_windows) != len(expected_windows):
        raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
    required_flags = (
        "looped",
        "atempo_applied",
        "speed_changed",
        "time_stretched",
        "pitch_shifted",
        "silence_padded",
        "generated_substitute",
    )
    for expected, observed in zip(expected_windows, observed_windows):
        if (
            not isinstance(observed, Mapping)
            or any(observed.get(field) != value for field, value in expected.items())
            or not _is_sha256(observed.get("fragment_sha256"))
            or observed.get("uploaded_fragment_sha256") != observed.get("fragment_sha256")
            or observed.get("final_audio_fragment_sha256") != observed.get("fragment_sha256")
        ):
            raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        if any(observed.get(flag) is not False for flag in required_flags):
            raise ValueError("BACKGROUND_MUSIC_TRANSFORM_FORBIDDEN")
    return {
        **dict(final_mix_receipt),
        "source_music_windows": [dict(window) for window in expected_windows],
        "lyric_lip_sync_policy": execution_contract["lyric_lip_sync_policy"],
    }


def build_background_music_stage_plan(
    manifest: Mapping[str, Any],
    *,
    review_route: str | None,
) -> list[dict[str, Any]]:
    """Expand only music jobs onto the canonical generation-stage names."""

    plan = build_stage_plan(manifest, review_route=review_route)
    if not is_background_music_manifest(manifest):
        return plan
    if any(item.get("name") == "build_script" for item in plan):
        return plan

    extensions = manifest.get("extensions") if isinstance(manifest.get("extensions"), Mapping) else {}
    selected_route = review_route or extensions.get("review_route") or manifest.get("review_route")
    if selected_route == "local_only":
        raise ValueError("BACKGROUND_MUSIC_REVIEW_ROUTE_INVALID")
    # This is an in-memory planning projection only.  It preserves every
    # canonical stage field (including active high-fidelity internals) while
    # making the optional audio extension require the existing generation path.
    planning_manifest = dict(manifest)
    planning_routes = dict(manifest.get("routes") or {})
    planning_routes["character"] = "replace_from_slot"
    planning_manifest["routes"] = planning_routes
    planned = build_stage_plan(planning_manifest, review_route=review_route)
    if not any(item.get("name") == "build_script" for item in planned):
        raise ValueError("BACKGROUND_MUSIC_STAGE_PLAN_INVALID")
    return planned


def _background_music_context(context: Any) -> Any:
    snapshot = getattr(context, "snapshot", None)
    manifest = getattr(snapshot, "slots_manifest", None)
    if not isinstance(manifest, Mapping):
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID")
    extensions = manifest.get("extensions")
    background_music = extensions.get("background_music") if isinstance(extensions, Mapping) else None
    if not isinstance(background_music, Mapping):
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID")
    required = ("object_key", "sha256", "size_bytes", "content_type", "duration_seconds", "status")
    if any(background_music.get(field) is None for field in required):
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID")
    slots = manifest.get("slots")
    if not isinstance(slots, Mapping) or "background_music" in slots:
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID")

    completion = dict(background_music)
    completion["store_verified"] = True
    descriptor = {
        "kind": "audio",
        "metadata": [completion],
        "present": True,
        "role": "background_music_extension",
        "sha256": [completion["sha256"]],
        "slot_id": "background_music",
        "source": "extension",
        "valid": True,
        "values": [completion["object_key"]],
    }
    transient_manifest = dict(manifest)
    transient_manifest["slots"] = {**slots, "background_music": descriptor}
    try:
        transient_snapshot = replace(snapshot, slots_manifest=transient_manifest)
        return replace(context, snapshot=transient_snapshot)
    except TypeError as error:
        raise ValueError("BACKGROUND_MUSIC_CONTEXT_INVALID") from error


class BackgroundMusicStagePort:
    """Dispatch a music job through a dedicated existing-stage StagePort.

    The extension gains a materializable descriptor only in the copied worker
    context.  It is never persisted into the canonical seven-slot manifest.
    """

    def __init__(self, *, stage: str | None = None, delegate: Any, music_delegate: Any) -> None:
        if not callable(getattr(delegate, "run", delegate)) or not callable(
            getattr(music_delegate, "run", music_delegate)
        ):
            raise ValueError("BACKGROUND_MUSIC_STAGE_PORT_INVALID")
        self.delegate = delegate
        self.music_delegate = music_delegate
        self.stage = stage

    @staticmethod
    def _run(port: Any, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        operation = getattr(port, "run", port)
        result = operation(context=context, input_artifacts=input_artifacts)
        if not isinstance(result, Mapping):
            raise ValueError("BACKGROUND_MUSIC_STAGE_OUTPUT_INVALID")
        return result

    def run(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        if not is_background_music_manifest(manifest):
            return self._run(self.delegate, context=context, input_artifacts=input_artifacts)
        frozen_contract = (
            self._materialize_frozen_timeline_contract(context)
            if self.stage in {"audit_seedance_request", "splice_timeline", "run_qc"}
            else None
        )
        augmented_artifacts = list(input_artifacts)
        if frozen_contract is not None:
            _, reference = frozen_contract
            augmented_artifacts.append(
                {
                    "artifact_id": reference["artifact_id"],
                    "kind": MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND,
                    "sha256": reference["sha256"],
                }
            )
        result = self._run(
            self.music_delegate,
            context=_background_music_context(context),
            input_artifacts=augmented_artifacts,
        )
        return self._validate_stage_result(
            context=context,
            result=result,
            frozen_contract=frozen_contract,
        )

    def _validate_stage_result(
        self,
        *,
        context: Any,
        result: Mapping[str, Any],
        frozen_contract: tuple[Mapping[str, Any], dict[str, str]] | None,
    ) -> Mapping[str, Any]:
        if self.stage == "analyze_dynamics":
            evidence = result.get("background_music_evidence")
            contract = evidence.get("music_timeline_contract") if isinstance(evidence, Mapping) else None
            manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
            extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
            uploaded = extensions.get("background_music") if isinstance(extensions, Mapping) else None
            if not isinstance(contract, Mapping) or not isinstance(uploaded, Mapping):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
            self._validate_music_timeline(contract=contract, uploaded=uploaded)
            return self._publish_frozen_timeline_contract(
                context=context,
                result=result,
                contract=contract,
            )
        if self.stage == "splice_timeline":
            evidence = result.get("background_music_evidence")
            contract = evidence.get("music_timeline_contract") if isinstance(evidence, Mapping) else None
            receipt = evidence.get("mix_receipt") if isinstance(evidence, Mapping) else None
            execution_contract = evidence.get("music_execution_contract") if isinstance(evidence, Mapping) else None
            manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
            extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
            uploaded = extensions.get("background_music") if isinstance(extensions, Mapping) else None
            if not isinstance(contract, Mapping) or not isinstance(receipt, Mapping) or not isinstance(uploaded, Mapping):
                raise ValueError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
            if not isinstance(execution_contract, Mapping):
                raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_REQUIRED")
            self._validate_music_timeline(contract=contract, uploaded=uploaded)
            self._validate_mix_receipt(contract=contract, uploaded=uploaded, receipt=receipt)
            execute_background_music(
                execution_contract=execution_contract,
                final_mix_receipt=receipt,
            )
            self._validate_frozen_timeline_reference(
                result=result,
                contract=contract,
                frozen_contract=frozen_contract,
            )
            return result
        if self.stage == "run_qc":
            evidence = result.get("background_music_evidence")
            contract = evidence.get("music_timeline_contract") if isinstance(evidence, Mapping) else None
            receipt = evidence.get("mix_receipt") if isinstance(evidence, Mapping) else None
            singing_qa = evidence.get("singing_qa") if isinstance(evidence, Mapping) else None
            execution_contract = evidence.get("music_execution_contract") if isinstance(evidence, Mapping) else None
            manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
            extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
            uploaded = extensions.get("background_music") if isinstance(extensions, Mapping) else None
            if not isinstance(contract, Mapping) or not isinstance(receipt, Mapping) or not isinstance(uploaded, Mapping):
                raise ValueError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
            if not isinstance(execution_contract, Mapping):
                raise ValueError("BACKGROUND_MUSIC_EXECUTION_CONTRACT_REQUIRED")
            self._validate_music_timeline(contract=contract, uploaded=uploaded)
            self._validate_mix_receipt(contract=contract, uploaded=uploaded, receipt=receipt)
            execute_background_music(
                execution_contract=execution_contract,
                final_mix_receipt=receipt,
            )
            if execution_contract.get("mode") == "background_music_replacement":
                self._validate_no_lyric_lip_sync(singing_qa=singing_qa)
            else:
                self._validate_singing_qa(contract=contract, singing_qa=singing_qa)
            self._validate_frozen_timeline_reference(
                result=result,
                contract=contract,
                frozen_contract=frozen_contract,
            )
            return result
        if self.stage != "audit_seedance_request":
            return result
        evidence = result.get("background_music_evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        receipt = evidence.get("audio_asset_receipt")
        payload = evidence.get("provider_payload")
        execution_contract = evidence.get("music_execution_contract")
        manifest = getattr(getattr(context, "snapshot", None), "slots_manifest", None)
        extensions = manifest.get("extensions") if isinstance(manifest, Mapping) else None
        uploaded = extensions.get("background_music") if isinstance(extensions, Mapping) else None
        if (
            not isinstance(receipt, Mapping)
            or not isinstance(payload, Mapping)
            or not isinstance(uploaded, Mapping)
            or not isinstance(execution_contract, Mapping)
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        if (
            execution_contract.get("contract") != BACKGROUND_MUSIC_EXECUTION_RECEIPT_V1
            or execution_contract.get("uploaded_audio_sha256") != uploaded.get("sha256")
            or execution_contract.get("audio_asset_receipt") != receipt
            or execution_contract.get("provider_payload") != payload
            or execution_contract.get("mode") not in {"verified_singing", "background_music_replacement"}
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        try:
            _validate_frozen_execution_contract(execution_contract)
        except ValueError as error:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID") from error
        if frozen_contract is None:
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        frozen_timeline, _ = frozen_contract
        execution_timeline = execution_contract.get("music_timeline_contract")
        if (
            not isinstance(execution_timeline, Mapping)
            or _canonical_json_bytes(execution_timeline) != _canonical_json_bytes(frozen_timeline)
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        if execution_contract.get("mode") == "verified_singing":
            frozen_performance = self._materialize_frozen_performance_line_contract(context)
            declared_performance_sha = execution_contract.get("performance_line_contract_sha256")
            execution_performance = execution_contract.get("performance_line_contract")
            if (
                not isinstance(execution_performance, Mapping)
                or not _is_sha256(declared_performance_sha)
                or declared_performance_sha != frozen_performance[1]["sha256"]
                or _canonical_json_bytes(execution_performance) != _canonical_json_bytes(frozen_performance[0])
            ):
                raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        asset_uri = receipt.get("asset_uri")
        if (
            receipt.get("asset_type") != "Audio"
            or receipt.get("uploaded_audio_sha256") != uploaded.get("sha256")
            or receipt.get("status") != "active"
            or not isinstance(asset_uri, str)
            or not asset_uri.startswith("asset://asset-")
            or "reference_audios" in payload
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        content = payload.get("content")
        if not isinstance(content, list):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        text_items = [item.get("text") for item in content if isinstance(item, Mapping) and item.get("type") == "text"]
        audio_items = [item for item in content if isinstance(item, Mapping) and item.get("type") == "audio_url"]
        if (
            not any(isinstance(text, str) and "@Audio1" in text for text in text_items)
            or len(audio_items) != 1
            or audio_items[0].get("role") != "reference_audio"
            or not isinstance(audio_items[0].get("audio_url"), Mapping)
            or audio_items[0]["audio_url"].get("url") != asset_uri
        ):
            raise ValueError("BACKGROUND_MUSIC_PROVIDER_REQUEST_INVALID")
        return result

    @staticmethod
    def _materialize_frozen_timeline_contract(
        context: Any,
    ) -> tuple[Mapping[str, Any], dict[str, str]] | None:
        try:
            artifacts = context.artifacts
        except AttributeError:
            return None
        if not isinstance(artifacts, (tuple, list)):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, Mapping) and artifact.get("kind") == MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND
        ]
        if len(matches) != 1 or not callable(getattr(context, "materialize_artifact", None)):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(matches[0])
        try:
            with context.materialize_artifact(
                MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND,
                artifact_id=reference["artifact_id"],
                sha256=reference["sha256"],
            ) as materialized:
                encoded = materialized.path.read_bytes()
        except Exception as error:
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if hashlib.sha256(encoded).hexdigest() != reference["sha256"]:
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH")
        try:
            decoded = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH") from error
        if not isinstance(decoded, Mapping):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH")
        return dict(decoded), reference

    @staticmethod
    def _materialize_frozen_performance_line_contract(
        context: Any,
    ) -> tuple[Mapping[str, Any], dict[str, str]]:
        try:
            artifacts = context.artifacts
        except AttributeError as error:
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if not isinstance(artifacts, (tuple, list)):
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_REQUIRED")
        matches = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, Mapping) and artifact.get("kind") == PERFORMANCE_LINE_CONTRACT_ARTIFACT_KIND
        ]
        if len(matches) != 1 or not callable(getattr(context, "materialize_artifact", None)):
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(matches[0])
        try:
            with context.materialize_artifact(
                PERFORMANCE_LINE_CONTRACT_ARTIFACT_KIND,
                artifact_id=reference["artifact_id"],
                sha256=reference["sha256"],
            ) as materialized:
                encoded = materialized.path.read_bytes()
        except Exception as error:
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if hashlib.sha256(encoded).hexdigest() != reference["sha256"]:
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_MISMATCH")
        try:
            decoded = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_MISMATCH") from error
        if not isinstance(decoded, Mapping):
            raise ValueError("PERFORMANCE_LINE_CONTRACT_ARTIFACT_MISMATCH")
        return dict(decoded), reference

    @staticmethod
    def _contract_artifact_reference(value: Mapping[str, object]) -> dict[str, str]:
        artifact_id = value.get("artifact_id")
        sha256 = value.get("sha256")
        if not isinstance(artifact_id, str) or not artifact_id or not _is_sha256(sha256):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        return {"artifact_id": artifact_id, "sha256": sha256}

    @staticmethod
    def _publish_frozen_timeline_contract(
        *,
        context: Any,
        result: Mapping[str, Any],
        contract: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        publish = getattr(context, "publish_bytes", None)
        if not callable(publish):
            return result
        encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        try:
            published = publish(
                kind=MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND,
                data=encoded,
                content_type="application/json",
                expected_sha256=digest,
            )
        except Exception as error:
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED") from error
        if not isinstance(published, Mapping):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        reference = BackgroundMusicStagePort._contract_artifact_reference(published)
        evidence = result.get("background_music_evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
        enriched = dict(result)
        enriched["background_music_evidence"] = {
            **dict(evidence),
            "music_timeline_contract_artifact": {
                **reference,
                "kind": MUSIC_TIMELINE_CONTRACT_ARTIFACT_KIND,
            },
        }
        return enriched

    @staticmethod
    def _validate_frozen_timeline_reference(
        *,
        result: Mapping[str, Any],
        contract: Mapping[str, Any],
        frozen_contract: tuple[Mapping[str, Any], dict[str, str]] | None,
    ) -> None:
        if frozen_contract is None:
            return
        frozen, expected_reference = frozen_contract
        evidence = result.get("background_music_evidence")
        reference = evidence.get("music_timeline_contract_artifact") if isinstance(evidence, Mapping) else None
        if not isinstance(reference, Mapping):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_REQUIRED")
        observed_reference = BackgroundMusicStagePort._contract_artifact_reference(reference)
        if observed_reference != expected_reference or _canonical_json_bytes(contract) != _canonical_json_bytes(frozen):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_ARTIFACT_MISMATCH")

    @staticmethod
    def _validate_music_timeline(*, contract: Mapping[str, Any], uploaded: Mapping[str, Any]) -> None:
        windows = contract.get("windows")
        singers = contract.get("visible_singer_regions")
        try:
            available_ms = round(float(uploaded.get("duration_seconds")) * 1000)
        except (TypeError, ValueError) as error:
            raise ValueError("BACKGROUND_MUSIC_DURATION_INSUFFICIENT") from error
        if available_ms <= 0 or not isinstance(windows, list) or not windows or not isinstance(singers, list):
            raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
        prior_source_end = -1
        prior_uploaded_end: int | None = None
        for window in windows:
            if not isinstance(window, Mapping):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
            values = tuple(
                window.get(field)
                for field in (
                    "source_start_frame",
                    "source_end_frame",
                    "output_start_frame",
                    "output_end_frame",
                    "uploaded_start_ms",
                    "uploaded_end_ms",
                )
            )
            if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
                raise ValueError("MUSIC_TIMELINE_CONTRACT_REQUIRED")
            source_start, source_end, output_start, output_end, uploaded_start, uploaded_end = values
            if (
                source_start < 0
                or source_end <= source_start
                or source_start != output_start
                or source_end != output_end
                or source_start < prior_source_end
            ):
                raise ValueError("BACKGROUND_MUSIC_TIMELINE_MISMATCH")
            if (
                uploaded_start < 0
                or uploaded_end <= uploaded_start
                or uploaded_end > available_ms
                or (prior_uploaded_end is not None and uploaded_start != prior_uploaded_end)
            ):
                raise ValueError("BACKGROUND_MUSIC_DURATION_INSUFFICIENT")
            prior_source_end = source_end
            prior_uploaded_end = uploaded_end

    @staticmethod
    def _validate_mix_receipt(
        *,
        contract: Mapping[str, Any],
        uploaded: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        if (
            receipt.get("passed") is not True
            or receipt.get("uploaded_audio_sha256") != uploaded.get("sha256")
            or not _is_sha256(receipt.get("final_audio_sha256"))
        ):
            raise ValueError("BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED")
        expected_windows = contract.get("windows")
        observed_windows = receipt.get("window_receipts")
        if not isinstance(expected_windows, list) or not isinstance(observed_windows, list) or len(expected_windows) != len(observed_windows):
            raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
        fields = (
            "source_start_frame",
            "source_end_frame",
            "output_start_frame",
            "output_end_frame",
            "uploaded_start_ms",
            "uploaded_end_ms",
        )
        for expected, observed in zip(expected_windows, observed_windows):
            if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
                raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
            if any(observed.get(field) != expected.get(field) for field in fields) or not _is_sha256(observed.get("fragment_sha256")):
                raise ValueError("BACKGROUND_MUSIC_FRAGMENT_RECEIPT_REQUIRED")
            if any(observed.get(flag) is not False for flag in ("looped", "time_stretched", "pitch_shifted", "generated_substitute")):
                raise ValueError("BACKGROUND_MUSIC_TRANSFORM_FORBIDDEN")

    @staticmethod
    def _validate_singing_qa(*, contract: Mapping[str, Any], singing_qa: object) -> None:
        raw_regions = contract.get("visible_singer_regions")
        if not isinstance(raw_regions, list) or any(not isinstance(region, Mapping) for region in raw_regions):
            raise ValueError("SINGING_ALIGNMENT_REQUIRED")
        visible = [region for region in raw_regions if region.get("visible") is True]
        if not isinstance(singing_qa, Mapping):
            raise ValueError("SINGING_ALIGNMENT_REQUIRED")
        observed = singing_qa.get("regions")
        if not visible:
            if (
                singing_qa.get("status") != "skipped"
                or singing_qa.get("reason") != "no_visible_singing_person"
                or observed != []
            ):
                raise ValueError("SINGING_ALIGNMENT_REQUIRED")
            return
        if singing_qa.get("status") != "passed" or not isinstance(observed, list) or len(observed) != len(visible):
            raise ValueError("SINGING_ALIGNMENT_REQUIRED")
        for expected, receipt in zip(visible, observed):
            if not isinstance(receipt, Mapping) or receipt.get("region_id") != expected.get("region_id"):
                raise ValueError("SINGING_ALIGNMENT_REQUIRED")
            alignment = receipt.get("lyrics_phoneme_alignment")
            if (
                not isinstance(alignment, Mapping)
                or alignment.get("passed") is not True
                or not _is_sha256(alignment.get("receipt_sha256"))
            ):
                raise ValueError("SINGING_ALIGNMENT_REQUIRED")
            lip_sync = receipt.get("lip_sync_qa")
            if (
                not isinstance(lip_sync, Mapping)
                or lip_sync.get("passed") is not True
                or not _is_sha256(lip_sync.get("receipt_sha256"))
            ):
                raise ValueError("SINGING_LIP_SYNC_QA_REQUIRED")

    @staticmethod
    def _validate_no_lyric_lip_sync(*, singing_qa: object) -> None:
        if (
            not isinstance(singing_qa, Mapping)
            or singing_qa.get("status") != "skipped"
            or singing_qa.get("reason") != "no_lyric_lip_sync"
            or singing_qa.get("regions") != []
        ):
            raise ValueError("NO_LYRIC_LIP_SYNC_REQUIRED")


class DeploymentBackgroundMusicExecutionAdapter:
    """Install real deployment StagePorts for optional music jobs only."""

    def __init__(self, *, music_stage_ports: Mapping[str, Any]) -> None:
        if set(music_stage_ports) != set(MUSIC_STAGE_PORTS):
            raise ValueError("BACKGROUND_MUSIC_STAGE_PORTS_INVALID")
        if any(not callable(getattr(port, "run", port)) for port in music_stage_ports.values()):
            raise ValueError("BACKGROUND_MUSIC_STAGE_PORTS_INVALID")
        self._music_stage_ports = dict(music_stage_ports)
        self._installed = False

    def install(
        self,
        *,
        job_store: Any,
        work_queue: Any,
        worker_manager: Any,
        stage_driver: Any,
    ) -> BackgroundMusicStageDriver:
        if not callable(getattr(stage_driver, "enqueue_next", None)):
            raise ValueError("BACKGROUND_MUSIC_STAGE_DRIVER_INVALID")
        canonical_ports = getattr(worker_manager, "stage_ports", None)
        if not isinstance(canonical_ports, Mapping) or set(MUSIC_STAGE_PORTS) - set(canonical_ports):
            raise ValueError("BACKGROUND_MUSIC_STAGE_PORTS_INVALID")
        wrapped = dict(canonical_ports)
        for stage in MUSIC_STAGE_PORTS:
            wrapped[stage] = BackgroundMusicStagePort(
                stage=stage,
                delegate=canonical_ports[stage],
                music_delegate=self._music_stage_ports[stage],
            )
        worker_manager.stage_ports = wrapped
        self._installed = True
        return BackgroundMusicStageDriver(job_store, work_queue)

    def validate_startup(self) -> None:
        if not self._installed:
            raise ValueError("BACKGROUND_MUSIC_EXECUTION_ADAPTER_UNAVAILABLE")
        declared: set[str] = set()
        for port in self._music_stage_ports.values():
            capabilities = getattr(port, "background_music_capabilities", None)
            if not callable(capabilities):
                raise ValueError("BACKGROUND_MUSIC_CAPABILITY_DECLARATION_REQUIRED")
            values = capabilities()
            if not isinstance(values, (set, frozenset, tuple, list)) or any(
                not isinstance(value, str) for value in values
            ):
                raise ValueError("BACKGROUND_MUSIC_CAPABILITY_DECLARATION_REQUIRED")
            declared.update(values)
        if not REQUIRED_MUSIC_CAPABILITIES.issubset(declared):
            raise ValueError("BACKGROUND_MUSIC_CAPABILITY_DECLARATION_REQUIRED")

    def validate_manifest(self, *, background_music: Mapping[str, object]) -> None:
        if not isinstance(background_music, Mapping):
            raise ValueError("BACKGROUND_MUSIC_MANIFEST_INVALID")
        expected = {
            "provider_route": "seedance_audio_reference",
            "provider_asset_type": "Audio",
            "provider_content_item_type": "audio_url",
            "prompt_reference_tag": "@Audio1",
            "forbidden_provider_field": "reference_audios",
            "final_audio_source": "uploaded_exact_audio",
            "allow_loop_or_time_stretch": False,
        }
        if any(background_music.get(key) != value for key, value in expected.items()):
            raise ValueError("BACKGROUND_MUSIC_MANIFEST_INVALID")

        content_type = background_music.get("content_type")
        digest = background_music.get("sha256")
        if (
            not isinstance(content_type, str)
            or not content_type.casefold().startswith("audio/")
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("BACKGROUND_MUSIC_MANIFEST_INVALID")


class BackgroundMusicStageDriver:
    """Canonical queue bridge with music-aware plan selection.

    Non-music jobs use the unmodified plan returned by ``build_stage_plan``.
    Music jobs use the same existing stage names and approval checks as normal
    generated-media jobs, so checkpoint, dedupe, Provider, and ACK semantics
    remain owned by the packaged worker.
    """

    background_music_execution_contract = MUSIC_EXECUTION_CONTRACT

    def __init__(self, job_store: Any, work_queue: Any) -> None:
        self.job_store = job_store
        self.work_queue = work_queue

    def enqueue_next(self, job_id: str) -> WorkMessage | None:
        snapshot = self.job_store.get_job(job_id)
        if snapshot is None:
            return None
        manifest = getattr(snapshot, "slots_manifest", None)
        if not isinstance(manifest, Mapping):
            return None
        plan = build_background_music_stage_plan(manifest, review_route=getattr(snapshot, "review_route", None))
        music_enabled = is_background_music_manifest(manifest)
        language_only = bool(
            isinstance(manifest.get("admission"), Mapping)
            and manifest["admission"].get("language_only")
        )
        if music_enabled and language_only:
            raise ValueError("BACKGROUND_MUSIC_LANGUAGE_ONLY_INVALID")

        for item in plan:
            stage = str(item.get("name") or "")
            if stage == "await_script_approval":
                if not getattr(snapshot, "approved_script_sha256", None):
                    return None
                continue
            if stage == "await_storyboard_approval":
                if not getattr(snapshot, "approved_storyboard_sha256", None):
                    return None
                continue
            if stage not in EXECUTABLE_STAGES:
                continue
            if stage == "build_script" and not language_only and getattr(snapshot, "review_route", None) == "route_1" and not getattr(snapshot, "approved_script_sha256", None):
                return None
            if stage == "generate_storyboards" and not language_only and getattr(snapshot, "review_route", None) == "route_2" and not getattr(snapshot, "approved_script_sha256", None):
                return None
            if stage in {"compile_seedance20_prompt", "audit_seedance_request", "submit_provider_video", "wait_provider_video", "splice_timeline", "run_qc"} and not language_only and not getattr(snapshot, "approved_storyboard_sha256", None):
                return None
            checkpoint = self.job_store.get_stage_checkpoint(job_id, stage)
            if checkpoint is not None and checkpoint.status == "SUCCEEDED":
                continue
            if checkpoint is not None and checkpoint.status == "CLAIMED":
                return None
            dedupe_key = _dedupe(job_id, stage, snapshot)
            message = WorkMessage(job_id, stage, snapshot.version, dedupe_key)
            self.work_queue.enqueue(
                job_id=message.job_id,
                stage=message.stage,
                expected_version=message.expected_version,
                dedupe_key=message.dedupe_key,
            )
            return message
        return None


__all__ = [
    "BackgroundMusicStageDriver",
    "BackgroundMusicStagePort",
    "DeploymentBackgroundMusicExecutionAdapter",
    "MUSIC_EXECUTION_CONTRACT",
    "MUSIC_STAGE_PORTS",
    "REQUIRED_MUSIC_CAPABILITIES",
    "build_background_music_stage_plan",
    "is_background_music_manifest",
]
