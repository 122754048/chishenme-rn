from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server.production_ports as production_ports
from server.runninghub_standard_contract import SOURCE_VIDEO_PROMPT_CONTRACT
from server.production_ports import (
    EvidenceBoundGptPlanner,
    ProductionEnvironment,
    ProductionPortsError,
    RunningHubCreateAmbiguousError,
    RunningHubSeedanceProvider,
    RunningHubTaskFailed,
    _DurableDynamicsEvidenceStage,
    _ScriptRevisionStage,
    _StoryboardRevisionStage,
)
from server.review_models import RevisionManifest
from server.source_content_timeline import build_source_content_timeline
from server.visible_text_contract import visible_text_locks_sha256


def _set_complete_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(production_ports, "_resolve_hostname", lambda _host: ("8.8.8.8",), raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("USFR_CAPABILITY_SECRET", "test-capability-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-2026-07-22")
    monkeypatch.setenv("OPENAI_MODEL_CONFIG_SHA256", "a" * 64)
    monkeypatch.setenv("RUNNINGHUB_API_KEY", "runninghub-secret")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_API_KEY", "runninghub-standard-secret")
    monkeypatch.setenv("RUNNINGHUB_BASE_URL", "https://runninghub.example")
    monkeypatch.setenv(
        "RUNNINGHUB_SEEDANCE_CREATE_URL",
        "https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
    )
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_QUERY_URL", "https://www.runninghub.cn/openapi/v2/query")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_UPLOAD_URL", "https://www.runninghub.cn/openapi/v2/media/upload/binary")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_WORKFLOW_ID", "workflow-123")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_MODEL_ID", "seedance-2.0")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_CONFIG_SHA256", "b" * 64)


def _standard_video_payload(prompt: str) -> dict[str, object]:
    return {
        "prompt": prompt,
        "resolution": "720p",
        "duration": "5",
        "imageUrls": ["https://media.example/board.png"],
        "videoUrls": [],
        "audioUrls": [],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": False,
        "conversionSlots": [],
        "returnLastFrame": False,
        "seed": -1,
    }


@pytest.mark.parametrize(
    "url",
    (
        "https://localhost/board.png",
        "https://127.0.0.1/board.png",
        "https://10.0.0.2/board.png",
        "https://[::1]/board.png",
    ),
)
def test_runninghub_seedance_provider_rejects_non_public_or_route_leaking_media_before_paid_create(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    _set_complete_environment(monkeypatch)
    payload = _standard_video_payload("Keep the approved performance.")
    payload["imageUrls"] = [url]
    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ())

    with pytest.raises(ProductionPortsError, match="public HTTPS"):
        provider.create_video(payload)


def test_runninghub_seedance_provider_rejects_source_route_leakage_before_paid_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    payload = _standard_video_payload("Use the source video as a visual reference.")
    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ())

    with pytest.raises(ProductionPortsError, match="route leakage"):
        provider.create_video(payload)


def _strict_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cuts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "required": [],
                },
            }
        },
        "required": ["cuts"],
    }


class _CreativeContext:
    """Minimal StageContext double with only artifact publication authority."""

    def __init__(self, *, approved_script_sha256: str | None = None) -> None:
        self.job_id = "creative-job-123"
        self.work_dir = Path("C:/worker/secret-job")
        self.secret = "must-not-serialize"
        self.hidden_reasoning = "must-not-persist"
        self.snapshot = SimpleNamespace(
            slots_manifest={
                "output_language": "en",
                "slots": {
                    "source_video": {"sha256": ["1" * 64]},
                    "new_product_image": {"sha256": ["2" * 64]},
                },
            },
            current_script_revision=0,
            current_storyboard_revision=0,
            approved_script_sha256=approved_script_sha256,
        )
        self.input_artifacts = [
            {"slot_id": "source_video", "index": 0, "sha256": "1" * 64},
            {"slot_id": "new_product_image", "index": 0, "sha256": "2" * 64},
        ]
        dynamics = json.dumps(
            {
                "source_dynamics_analysis": {
                    "source_cuts": [
                        {
                            "cut": 1,
                            "start_us": 0,
                            "end_us": 1_000_000,
                            "scene": "bathroom",
                            "action": "product pickup",
                            "camera": "close-up",
                        },
                        {
                            "cut": 2,
                            "start_us": 1_000_000,
                            "end_us": 2_000_000,
                            "scene": "counter",
                            "action": "product demonstration",
                            "camera": "medium shot",
                        },
                    ],
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        target_evidence = json.dumps({"evidence_ids": ["target-1"]}, sort_keys=True).encode("utf-8")
        self._artifact_payloads = {
            ("source_dynamics_analysis", hashlib.sha256(dynamics).hexdigest()): dynamics,
            ("target_evidence", hashlib.sha256(target_evidence).hexdigest()): target_evidence,
        }
        self.artifacts = [
            {
                "artifact_id": "dynamics-1",
                "kind": "source_dynamics_analysis",
                "object_key": f"temporary/{self.job_id}/dynamics.json",
                "sha256": hashlib.sha256(dynamics).hexdigest(),
                "content_type": "application/json",
                "size_bytes": len(dynamics),
            },
            {
                "artifact_id": "target-1",
                "kind": "target_evidence",
                "object_key": f"temporary/{self.job_id}/target-evidence.json",
                "sha256": hashlib.sha256(target_evidence).hexdigest(),
                "content_type": "application/json",
                "size_bytes": len(target_evidence),
            },
        ]
        self.published: list[dict[str, Any]] = []
        self.published_bytes: dict[str, bytes] = {}

    def replace_dynamics(self, analysis: Mapping[str, Any]) -> None:
        payload = json.dumps({"source_dynamics_analysis": dict(analysis)}, sort_keys=True).encode("utf-8")
        sha256 = hashlib.sha256(payload).hexdigest()
        self._artifact_payloads = {
            key: value for key, value in self._artifact_payloads.items() if key[0] != "source_dynamics_analysis"
        }
        self._artifact_payloads[("source_dynamics_analysis", sha256)] = payload
        for artifact in self.artifacts:
            if artifact["kind"] == "source_dynamics_analysis":
                artifact["sha256"] = sha256
                artifact["size_bytes"] = len(payload)

    @contextmanager
    def materialize_artifact(self, kind: str, *, sha256: str, **_kwargs: Any):
        payload = self._artifact_payloads[(kind, sha256)]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.json"
            path.write_bytes(payload)
            yield SimpleNamespace(path=path, sha256=sha256)

    def publish_bytes(
        self,
        *,
        kind: str,
        data: bytes,
        content_type: str,
        expected_sha256: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert expected_sha256 == hashlib.sha256(data).hexdigest()
        artifact = {
            "artifact_id": f"artifact-{len(self.published) + 1}",
            "kind": kind,
            "object_key": f"temporary/{self.job_id}/{kind}.json",
            "sha256": expected_sha256,
            "content_type": content_type,
            "size_bytes": len(data),
            "metadata": dict(metadata or {}),
        }
        self.published.append(artifact)
        self.published_bytes[expected_sha256] = data
        return artifact


def _script_cut(cut_id: str, *, index: int, evidence_id: str) -> dict[str, Any]:
    return {
        "cut_id": cut_id,
        "start_ms": index * 1000,
        "end_ms": (index + 1) * 1000,
        "scene": "bathroom",
        "action": "demonstrates product",
        "camera": "close-up",
        "dialogue": "Watch this.",
        "delivery": "natural",
        "audio_events": ["room tone"],
        "selling_point": {
            "feature": "portable",
            "mechanism": "folds flat",
            "benefit": "saves space",
            "proof": {"evidence_id": evidence_id},
            "cta": "try it",
        },
        "proof": {"evidence_id": evidence_id},
        "visual": "product in hand",
        "evidence_ids": [evidence_id],
        "route": "route_2",
        "output_language": "en",
        "performance": _performance_cut(index=index),
    }


def _creative_response(**request: Any) -> dict[str, Any]:
    evidence = None
    input_messages = request["payload"]["input"]
    for message in input_messages:
        for item in message.get("content", []):
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                candidate = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "kind" in candidate and "job_id" in candidate:
                evidence = candidate
                break
        if evidence is not None:
            break
    assert evidence is not None
    assert "C:/worker/secret-job" not in json.dumps(evidence, sort_keys=True)
    assert "must-not-serialize" not in json.dumps(evidence, sort_keys=True)
    assert "must-not-persist" not in json.dumps(evidence, sort_keys=True)
    common = {
        "kind": evidence["kind"],
        "job_id": evidence["job_id"],
        "source_sha256": evidence["source_sha256"],
        "source_dynamics_sha256": evidence["source_dynamics_sha256"],
        "target_sha256": evidence["target_sha256"],
        "output_language": evidence["output_language"],
        "parent_revision_sha256": evidence["parent_revision_sha256"],
        "cut_coverage_sha256": evidence["cut_coverage_sha256"],
        "request_evidence_sha256": evidence["request_evidence_sha256"],
        "visible_text_locks_sha256": evidence["visible_text_locks_sha256"],
    }
    if evidence["kind"] == "script":
        common["cuts"] = [
            _script_cut(cut_id, index=index, evidence_id=evidence["target_evidence_ids"][0])
            for index, cut_id in enumerate(evidence["cut_ids"])
        ]
    else:
        common["cuts"] = [
            {
                "cut_id": cut_id,
                "prompt": f"storyboard {cut_id}",
                "negative_prompt": "no text artifacts",
                "reference_evidence_ids": [evidence["target_evidence_ids"][0]],
                "composition": "product centered",
                "camera": "close-up",
                "continuity": "same product",
                "output_language": evidence["output_language"],
            }
            for cut_id in evidence["cut_ids"]
        ]
    return {"model": "gpt-test-2026-07-22", "output_text": json.dumps(common, sort_keys=True)}


def test_language_only_request_includes_explicit_localization_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    context.snapshot.slots_manifest["admission"] = {"language_only": True}
    captured: dict[str, Any] = {}

    def request_json(**request: Any) -> dict[str, Any]:
        captured.update(request)
        return _creative_response(**request)

    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=request_json)
    planner._request_structured(kind="script", evidence=planner._revision_evidence(context, kind="script"), schema=planner._revision_schema("script"))
    messages = captured["payload"]["input"]
    assert len(messages) == 2
    assert "language-only localization task" in messages[0]["content"][0]["text"].lower()
    assert "translate only the spoken dialogue and visible text" in messages[0]["content"][0]["text"].lower()
    evidence = json.loads(messages[1]["content"][0]["text"])
    assert evidence["language_only"] is True


def _add_source_audio_evidence(context: _CreativeContext) -> None:
    source = {
        "contract": "performance-audio-source/v1",
        "mode": "source_audio_replicate_v1",
        "authorization": {"status": "user_default_authorized", "scope": "current_run_only"},
        "source_audio_sha256": "4" * 64,
        "audio_language": "en",
        "provider_reference_audio": "forbidden",
        "final_audio_carrier": "deterministic_postproduction",
    }
    lyrics = {
        "contract": "audio-lyrics-beat/v1",
        "source_audio_sha256": "4" * 64,
        "audio_language": "en",
        "segments": [
            {"segment_id": "A01", "start_ms": 0, "end_ms": 1000, "text": "first exact lyric", "confidence": 0.99, "kind": "singing", "beat_anchors_ms": [200], "emotion": "hopeful"},
            {"segment_id": "A02", "start_ms": 1000, "end_ms": 2000, "text": "second exact lyric", "confidence": 0.99, "kind": "singing", "beat_anchors_ms": [1200], "emotion": "release"},
        ],
    }
    for kind, value in (("performance_audio_source_contract", source), ("audio_lyrics_beat_contract", lyrics)):
        payload = json.dumps(value, sort_keys=True).encode("utf-8")
        sha256 = hashlib.sha256(payload).hexdigest()
        context._artifact_payloads[(kind, sha256)] = payload
        context.artifacts.append(
            {"artifact_id": f"{kind}-1", "kind": kind, "object_key": f"temporary/{context.job_id}/{kind}.json", "sha256": sha256, "content_type": "application/json", "size_bytes": len(payload)}
        )


def _add_source_content_timeline(context: _CreativeContext) -> str:
    analysis = {
        "source_cuts": [
            {"cut_id": "C01", "start_us": 0, "end_us": 1_000_000, "scene": "bathroom", "action": "product pickup", "camera": "close-up"},
            {"cut_id": "C02", "start_us": 1_000_000, "end_us": 2_000_000, "scene": "counter", "action": "product demonstration", "camera": "medium shot"},
        ],
        "ocr_intervals": [],
        "visible_person_tracks": [],
    }
    audio = {
        "source_duration_ms": 2_000,
        "source_audio_sha256": "4" * 64,
        "language": "en",
        "segments": [{"segment_id": "A01", "start_ms": 0, "end_ms": 900, "text": "Use it daily.", "kind": "speech", "confidence": 0.92}],
        "audio_events": [],
        "meaningful_silence": [],
    }
    timeline = build_source_content_timeline(
        source_video_sha256="1" * 64,
        source_dynamics_analysis=analysis,
        audio_contract=audio,
    )
    payload = json.dumps(timeline, sort_keys=True).encode("utf-8")
    sha256 = hashlib.sha256(payload).hexdigest()
    context._artifact_payloads[("source_content_timeline", sha256)] = payload
    context.artifacts.append(
        {"artifact_id": "source-content-timeline-1", "kind": "source_content_timeline", "object_key": f"temporary/{context.job_id}/source-content-timeline.json", "sha256": sha256, "content_type": "application/json", "size_bytes": len(payload)}
    )
    return sha256


def test_creative_planner_carries_the_frozen_source_content_timeline_into_script_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    timeline_sha256 = _add_source_content_timeline(context)
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)

    evidence = planner._revision_evidence(context, kind="script")

    assert evidence["source_content_timeline"]["artifact_sha256"] == timeline_sha256
    assert evidence["source_content_timeline"]["audio_lines"][0]["speaker_assignment"]["status"] == "PENDING_ASSIGNMENT"


def _add_visible_text_source_content_timeline(context: _CreativeContext) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = {
        "source_cuts": [
            {"cut_id": "C01", "start_us": 0, "end_us": 1_000_000, "scene": "bathroom", "action": "product pickup", "camera": "close-up"},
            {"cut_id": "C02", "start_us": 1_000_000, "end_us": 2_000_000, "scene": "counter", "action": "product demonstration", "camera": "medium shot"},
        ],
        "ocr_intervals": [{"text_id": "T01", "kind": "subtitle", "text": "Before breakfast", "start_ms": 100, "end_ms": 750, "confidence": 0.98, "evidence_sha256": "f" * 64}],
        "visible_person_tracks": [],
    }
    audio = {
        "source_duration_ms": 2_000,
        "source_audio_sha256": "4" * 64,
        "language": "en",
        "segments": [],
        "audio_events": [],
        "meaningful_silence": [],
    }
    timeline = build_source_content_timeline(source_video_sha256="1" * 64, source_dynamics_analysis=analysis, audio_contract=audio)
    payload = json.dumps(timeline, sort_keys=True).encode("utf-8")
    sha256 = hashlib.sha256(payload).hexdigest()
    context._artifact_payloads[("source_content_timeline", sha256)] = payload
    context.artifacts.append(
        {"artifact_id": "visible-source-content-timeline-1", "kind": "source_content_timeline", "object_key": f"temporary/{context.job_id}/visible-source-content-timeline.json", "sha256": sha256, "content_type": "application/json", "size_bytes": len(payload)}
    )
    source = timeline["visible_text"][0]
    lock = {
        "text_id": source["text_id"],
        "cut_ids": source["cut_ids"],
        "start_ms": source["start_ms"],
        "end_ms": source["end_ms"],
        "kind": source["kind"],
        "source_evidence_sha256": source["evidence_sha256"],
        "approved_text": source["text"],
        "disposition": "keep",
        "placement": source["placement"],
    }
    return timeline, lock


def test_storyboard_evidence_requires_and_projects_the_approved_visible_text_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    approved_script_sha256 = "3" * 64
    context = _CreativeContext(approved_script_sha256=approved_script_sha256)
    context.snapshot.current_script_revision = 1
    _timeline, lock = _add_visible_text_source_content_timeline(context)
    timeline_artifact_sha256 = next(
        artifact["sha256"] for artifact in context.artifacts if artifact["kind"] == "source_content_timeline"
    )
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)

    with pytest.raises(ProductionPortsError, match="approved visible text"):
        planner._revision_evidence(context, kind="storyboard")

    approval = {
        "revision": 1,
        "script_sha256": approved_script_sha256,
        "source_content_timeline_sha256": timeline_artifact_sha256,
        "visible_text_locks": [lock],
        "visible_text_locks_sha256": visible_text_locks_sha256([lock]),
    }
    context.job_store = SimpleNamespace(
        get_current_revision=lambda _job_id, _kind: RevisionManifest.script(
            revision=1,
            object_key="temporary/creative-job-123/scripts/r1.json",
            sha256=approved_script_sha256,
            inputs_sha256="d" * 64,
        ),
        get_script_approval=lambda _job_id, _revision: approval,
    )

    evidence = planner._revision_evidence(context, kind="storyboard")

    assert evidence["approved_visible_text_locks"] == [lock]
    assert evidence["approved_visible_text_locks_sha256"] == approval["visible_text_locks_sha256"]
    storyboard_result = _StoryboardRevisionStage(planner).run(context=context, input_artifacts=[])
    storyboard_payload = json.loads(context.published_bytes[storyboard_result["storyboard_revision"].sha256])
    assert storyboard_payload["visible_text_locks"] == [lock]
    assert storyboard_payload["approved_visible_text_locks_sha256"] == approval["visible_text_locks_sha256"]
    assert storyboard_payload["cuts"][0]["visible_text_locks"] == [lock]
    assert storyboard_payload["cuts"][1]["visible_text_locks"] == []

    forged = {**approval, "source_content_timeline_sha256": "0" * 64}
    context.job_store = SimpleNamespace(
        get_current_revision=lambda _job_id, _kind: RevisionManifest.script(
            revision=1,
            object_key="temporary/creative-job-123/scripts/r1.json",
            sha256=approved_script_sha256,
            inputs_sha256="d" * 64,
        ),
        get_script_approval=lambda _job_id, _revision: forged,
    )
    with pytest.raises(ProductionPortsError, match="source content timeline"):
        planner._revision_evidence(context, kind="storyboard")


def test_creative_revisions_publish_exact_visible_text_locks_per_cut_and_user_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    _timeline, lock = _add_visible_text_source_content_timeline(context)
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)

    script_result = _ScriptRevisionStage(planner).run(context=context, input_artifacts=[])

    script_payload = json.loads(context.published_bytes[script_result["script_revision"].sha256])
    assert script_payload["visible_text_locks"] == [lock]
    assert script_payload["visible_text_locks_sha256"] == visible_text_locks_sha256([lock])
    assert script_payload["cuts"][0]["visible_text_locks"] == [lock]
    assert script_payload["cuts"][1]["visible_text_locks"] == []
    user_script = next(artifact for artifact in context.published if artifact["kind"] == "user_script_markdown")
    assert context.published_bytes[user_script["sha256"]].decode("utf-8").count("## ") == 2


def _performance_cut(*, index: int) -> dict[str, Any]:
    text = "first exact lyric" if index == 0 else "second exact lyric"
    start_ms = index * 1000
    return {
        "source_time": {"start_ms": start_ms, "end_ms": start_ms + 1000},
        "segment_time": {"start_ms": 0, "end_ms": 1000},
        "performance_mode": "singing",
        "exact_sung_text": text,
        "lyric_status": "verified",
        "beat_anchors_ms": [200],
        "no_beat_reason": "",
        "lip_sync": {"face_visibility": "front visible", "articulation": "clear lyric mouth shapes", "end_state": "mouth closes"},
        "action": {"start": "hands down", "beat_action": "raise palm", "end": "hands down"},
        "expression": {"start": "calm", "peak": "bright", "end": "steady"},
        "emotion": "hopeful" if index == 0 else "release",
        "end_pose": "front-facing pose",
        "criticality": "H",
    }


def test_creative_planner_keeps_source_audio_performance_as_pending_script_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    _add_source_audio_evidence(context)

    def response(**request: Any) -> dict[str, Any]:
        value = json.loads(_creative_response(**request)["output_text"])
        for index, cut in enumerate(value["cuts"]):
            cut["performance"] = _performance_cut(index=index)
        return {"model": "gpt-test-2026-07-22", "output_text": json.dumps(value, sort_keys=True)}

    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=response)
    draft = planner.draft_script(context, [])

    assert draft["performance_line_candidates"]["status"] == "PENDING_CONFIRMATION"
    assert draft["performance_line_candidates"]["cuts"][1]["exact_sung_text"] == "second exact lyric"
    result = _ScriptRevisionStage(planner).run(context=context, input_artifacts=[])
    assert [artifact["kind"] for artifact in result["published_artifacts"]] == ["script_revision", "user_script_markdown"]

    def missing_response(**request: Any) -> dict[str, Any]:
        value = json.loads(_creative_response(**request)["output_text"])
        for cut in value["cuts"]:
            cut.pop("performance")
        return {"model": "gpt-test-2026-07-22", "output_text": json.dumps(value, sort_keys=True)}

    planner_missing = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=missing_response)
    with pytest.raises(ProductionPortsError, match="declared object properties"):
        planner_missing.draft_script(context, [])


def test_creative_planner_rejects_unbound_script_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    planner = EvidenceBoundGptPlanner.from_environment()

    with pytest.raises(ProductionPortsError, match="source SHA"):
        planner._validate_response({"source_sha256": "0" * 64}, context=context, kind="script")


@pytest.mark.parametrize("receipt_field", ("request_sha256", "response_sha256"))
def test_creative_planner_rejects_tampered_transport_receipt(
    monkeypatch: pytest.MonkeyPatch,
    receipt_field: str,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)
    evidence = planner._revision_evidence(context, kind="script")
    response = planner._request_structured(
        kind="script",
        evidence=evidence,
        schema=planner._revision_schema("script"),
    )
    receipt = dict(response["receipt"])
    receipt[receipt_field] = "0" * 64
    tampered = {**response, "receipt": receipt}

    with pytest.raises(ProductionPortsError, match=receipt_field.replace("_", " ")):
        planner._validate_response(tampered, context=context, kind="script")


@pytest.mark.parametrize(
    ("kind", "field", "replacement", "message"),
    (
        ("script", "target_sha256", "0" * 64, "target SHA"),
        ("script", "output_language", "ja", "output_language"),
        ("script", "cuts", [_script_cut("C01", index=0, evidence_id="target-1")], "Cut coverage"),
        ("storyboard", "parent_revision_sha256", "0" * 64, "parent revision SHA"),
    ),
)
def test_creative_planner_rejects_stale_current_job_bindings(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    field: str,
    replacement: Any,
    message: str,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext(approved_script_sha256="3" * 64 if kind == "storyboard" else None)
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)
    evidence = planner._revision_evidence(context, kind=kind)
    response = planner._request_structured(kind=kind, evidence=evidence, schema=planner._revision_schema(kind))
    value = dict(response["value"])
    value[field] = replacement

    with pytest.raises(ProductionPortsError, match=message):
        planner._validate_response({**response, "value": value}, context=context, kind=kind)


@pytest.mark.parametrize(
    ("remove", "message"),
    (
        ("source", "source_video SHA"),
        ("target", "target evidence"),
        ("cuts", "source dynamics artifact"),
    ),
)
def test_creative_planner_fails_closed_before_gpt_without_required_evidence(
    monkeypatch: pytest.MonkeyPatch,
    remove: str,
    message: str,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _creative_response(**kwargs)

    if remove == "source":
        context.snapshot.slots_manifest["slots"]["source_video"]["sha256"] = []
    elif remove == "target":
        del context.snapshot.slots_manifest["slots"]["new_product_image"]
        context.artifacts = [item for item in context.artifacts if item["kind"] != "target_evidence"]
    else:
        context.artifacts = [item for item in context.artifacts if item["kind"] != "source_dynamics_analysis"]
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(ProductionPortsError, match=message):
        planner.draft_script(context, [])
    assert calls == []


def test_creative_planner_ignores_absent_replacement_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    for slot_id in (
        "new_model_image",
        "ui_screenshot",
        "app_store_url",
        "ui_operation_video",
        "tail_video",
    ):
        context.snapshot.slots_manifest["slots"][slot_id] = {"present": False, "sha256": []}
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)

    draft = planner.draft_script(context, [])

    assert draft["value"]["source_sha256"] == "1" * 64


def test_creative_planner_admits_uploaded_music_as_the_only_target_change(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    del context.snapshot.slots_manifest["slots"]["new_product_image"]
    context.snapshot.slots_manifest["extensions"] = {
        "background_music": {
            "extension_id": "input_contract_v2.background_music",
            "sha256": ["4" * 64],
        }
    }
    context.artifacts = [item for item in context.artifacts if item["kind"] != "target_evidence"]
    classification = {
        "contract": "uploaded-audio-classification/v1",
        "audio_sha256": "4" * 64,
        "kind": "non_song",
        "confidence": 0.97,
        "classification_evidence_sha256": "5" * 64,
        "lyrics": [],
    }
    raw = json.dumps(classification, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    context._artifact_payloads[("uploaded_audio_classification", digest)] = raw
    context.artifacts.append({
        "artifact_id": "uploaded-audio-1", "kind": "uploaded_audio_classification",
        "object_key": f"temporary/{context.job_id}/uploaded-audio.json", "sha256": digest,
        "content_type": "application/json", "size_bytes": len(raw),
    })
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ())

    evidence = planner._revision_evidence(context, kind="script")

    assert evidence["target_evidence_ids"] == ["slot:background_music:" + "4" * 64]


def test_creative_planner_exposes_uploaded_song_lyrics_for_script_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    upload_sha = "4" * 64
    classification = {
        "contract": "uploaded-audio-classification/v1",
        "audio_sha256": upload_sha,
        "kind": "song",
        "confidence": 0.97,
        "classification_evidence_sha256": "5" * 64,
        "lyrics": [{"start_ms": 0, "end_ms": 1000, "text": "Meet me where the morning starts"}],
    }
    raw = json.dumps(classification, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    context.snapshot.slots_manifest["extensions"] = {
        "background_music": {"extension_id": "input_contract_v2.background_music", "sha256": [upload_sha]}
    }
    context._artifact_payloads[("uploaded_audio_classification", digest)] = raw
    context.artifacts.append({
        "artifact_id": "uploaded-audio-1", "kind": "uploaded_audio_classification",
        "object_key": f"temporary/{context.job_id}/uploaded-audio.json", "sha256": digest,
        "content_type": "application/json", "size_bytes": len(raw),
    })
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ())

    evidence = planner._revision_evidence(context, kind="script")

    assert evidence["uploaded_audio"] == {
        "artifact_sha256": digest,
        "kind": "song",
        "lyrics": [{"start_ms": 0, "end_ms": 1000, "text": "Meet me where the morning starts"}],
        "instruction": "Show these exact uploaded-song lyrics in the editable script for user confirmation; assign each sung line to an explicitly confirmed on-camera performer.",
    }


@pytest.mark.parametrize(("kind", "field"), (("script", "output_language"), ("script", "evidence_ids"), ("storyboard", "reference_evidence_ids")))
def test_creative_planner_rejects_unbound_per_cut_language_or_target_evidence(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    field: str,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext(approved_script_sha256="3" * 64 if kind == "storyboard" else None)
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)
    evidence = planner._revision_evidence(context, kind=kind)
    response = planner._request_structured(kind=kind, evidence=evidence, schema=planner._revision_schema(kind))
    value = dict(response["value"])
    cuts = [dict(item) for item in value["cuts"]]
    cuts[0][field] = "ja" if field == "output_language" else ["forged-evidence-id"]
    value["cuts"] = cuts

    with pytest.raises(ProductionPortsError, match="Cut (output_language|target evidence)"):
        planner._validate_response({**response, "value": value}, context=context, kind=kind)


def test_durable_dynamics_stage_publishes_canonical_source_cut_evidence() -> None:
    context = _CreativeContext()

    class DynamicsStage:
        def run(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
            del context, input_artifacts
            return {
                "source_dynamics_analysis": {
                    "source_cuts": [
                        {
                            "cut": 1,
                            "start_us": 0,
                            "end_us": 1_000_000,
                            "scene": "bathroom",
                            "action": "product pickup",
                            "camera": "close-up",
                        },
                    ]
                }
            }

    result = _DurableDynamicsEvidenceStage(DynamicsStage()).run(context=context, input_artifacts=[])

    assert result["source_dynamics_analysis"]["source_cuts"][0]["cut"] == 1
    assert [artifact["kind"] for artifact in result["published_artifacts"]] == ["source_dynamics_analysis"]
    assert [artifact["kind"] for artifact in context.published] == ["source_dynamics_analysis"]


def test_creative_planner_rejects_a_script_cut_with_source_timing_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)
    evidence = planner._revision_evidence(context, kind="script")
    response = planner._request_structured(kind="script", evidence=evidence, schema=planner._revision_schema("script"))
    value = dict(response["value"])
    cuts = [dict(item) for item in value["cuts"]]
    cuts[0]["start_ms"] = 1
    value["cuts"] = cuts

    with pytest.raises(ProductionPortsError, match="Cut timing"):
        planner._validate_response({**response, "value": value}, context=context, kind="script")


@pytest.mark.parametrize(
    "analysis",
    (
        {
            "source_cuts": [
                {"cut": 1, "start_us": 1, "end_us": 1_000_000, "scene": "a", "action": "b", "camera": "c"}
            ]
        },
        {
            "source_cuts": [
                {"cut": 1, "start_us": 0, "end_us": 1_000_000, "scene": "a", "action": "b"}
            ]
        },
    ),
)
def test_creative_planner_rejects_incomplete_or_nonzero_source_cut_contract(
    monkeypatch: pytest.MonkeyPatch,
    analysis: Mapping[str, Any],
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    context.replace_dynamics(analysis)
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)

    with pytest.raises(ProductionPortsError, match="source Cut .*?(timing|camera)"):
        planner.draft_script(context, [])


def test_durable_dynamics_stage_rejects_hidden_reasoning_before_publication() -> None:
    context = _CreativeContext()

    class UnsafeDynamicsStage:
        def run(self, *, context: Any, input_artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
            del context, input_artifacts
            return {
                "source_dynamics_analysis": {
                    "hidden_reasoning": "private chain",
                    "source_cuts": [
                        {"cut": 1, "start_us": 0, "end_us": 1_000_000, "scene": "a", "action": "b", "camera": "c"}
                    ],
                }
            }

    with pytest.raises(ProductionPortsError, match="unsafe field"):
        _DurableDynamicsEvidenceStage(UnsafeDynamicsStage()).run(context=context, input_artifacts=[])
    assert context.published == []


def test_creative_planner_rejects_storyboard_cut_without_current_output_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext(approved_script_sha256="3" * 64)
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)
    evidence = planner._revision_evidence(context, kind="storyboard")
    response = planner._request_structured(kind="storyboard", evidence=evidence, schema=planner._revision_schema("storyboard"))
    value = dict(response["value"])
    cuts = [dict(item) for item in value["cuts"]]
    del cuts[0]["output_language"]
    value["cuts"] = cuts

    with pytest.raises(ProductionPortsError, match="Cut output_language"):
        planner._validate_response({**response, "value": value}, context=context, kind="storyboard")


def test_creative_planner_publishes_current_script_revision_without_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    context = _CreativeContext()
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)

    result = _ScriptRevisionStage(planner).run(context=context, input_artifacts=[])

    manifest = result["script_revision"]
    assert isinstance(manifest, RevisionManifest)
    assert manifest.kind == "script"
    assert manifest.status == "CURRENT"
    assert manifest.parent_script_sha256 is None
    assert result.get("final_artifact_id") is None
    assert [artifact["kind"] for artifact in context.published] == ["script_revision", "user_script_markdown"]
    assert result["user_script_markdown"]["metadata"] == {
        "logical_name": "analysis/reverse_storyboard_script.md",
        "presentation": "file",
        "inline_chat_substitute_forbidden": True,
    }


def test_creative_planner_binds_storyboard_to_approved_script_without_media_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    approved_script_sha256 = "3" * 64
    context = _CreativeContext(approved_script_sha256=approved_script_sha256)
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=_creative_response)

    result = _StoryboardRevisionStage(planner).run(context=context, input_artifacts=[])

    manifest = result["storyboard_revision"]
    assert isinstance(manifest, RevisionManifest)
    assert manifest.kind == "storyboard"
    assert manifest.status == "CURRENT"
    assert manifest.parent_script_sha256 == approved_script_sha256
    assert result.get("final_artifact_id") is None
    assert [artifact["kind"] for artifact in context.published] == ["storyboard_revision"]


def test_environment_rejects_missing_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProductionPortsError, match="OPENAI_API_KEY"):
        ProductionEnvironment.from_environ()


def test_environment_rejects_missing_runninghub_video_route(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    monkeypatch.delenv("RUNNINGHUB_SEEDANCE_CREATE_URL", raising=False)
    with pytest.raises(ProductionPortsError, match="RUNNINGHUB_SEEDANCE_CREATE_URL"):
        ProductionEnvironment.from_environ()


def test_environment_rejects_non_https_production_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_QUERY_URL", "http://runninghub.example/seedance/query")
    with pytest.raises(ProductionPortsError, match="RUNNINGHUB_SEEDANCE_QUERY_URL"):
        ProductionEnvironment.from_environ()


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://localhost/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://169.254.169.254/v1",
    ),
)
def test_environment_rejects_local_private_or_link_local_production_hosts(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    _set_complete_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)

    with pytest.raises(ProductionPortsError, match="OPENAI_BASE_URL"):
        ProductionEnvironment.from_environ()


def test_environment_rejects_hostname_that_resolves_to_a_private_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    monkeypatch.setattr(production_ports, "_resolve_hostname", lambda _host: ("10.0.0.8",))

    with pytest.raises(ProductionPortsError, match="OPENAI_BASE_URL"):
        ProductionEnvironment.from_environ()


def test_environment_rejects_malformed_https_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example:invalid/v1")
    with pytest.raises(ProductionPortsError, match="OPENAI_BASE_URL"):
        ProductionEnvironment.from_environ()


def test_environment_rejects_malformed_https_ipv6_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://[broken-host/v1")
    with pytest.raises(ProductionPortsError, match="OPENAI_BASE_URL"):
        ProductionEnvironment.from_environ()


def test_environment_rejects_uppercase_configuration_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_MODEL_CONFIG_SHA256", "A" * 64)
    with pytest.raises(ProductionPortsError, match="OPENAI_MODEL_CONFIG_SHA256"):
        ProductionEnvironment.from_environ()


def test_environment_is_frozen_and_contains_only_redacted_credential_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    config = ProductionEnvironment.from_environ()

    assert config.openai_api_key_env == "OPENAI_API_KEY"
    assert config.runninghub_api_key_env == "RUNNINGHUB_API_KEY"
    assert "openai-secret" not in repr(config)
    assert "runninghub-secret" not in repr(config)
    assert {field.name for field in fields(config)} == {
        "openai_api_key_env",
        "capability_secret_env",
        "openai_base_url",
        "openai_model",
        "openai_model_config_sha256",
        "runninghub_api_key_env",
        "runninghub_base_url",
        "runninghub_seedance_api_key_env",
        "runninghub_seedance_create_url",
        "runninghub_seedance_query_url",
        "runninghub_seedance_upload_url",
        "runninghub_seedance_model_id",
        "runninghub_seedance_config_sha256",
    }
    with pytest.raises(AttributeError):
        config.openai_model = "other"  # type: ignore[misc]


def test_gpt_planner_posts_strict_json_schema_and_redacts_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"model": "gpt-test-2026-07-22", "output_text": '{"cuts": []}'}

    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=request_json)
    result = planner.request_script(evidence={"source_sha256": "c" * 64}, schema=_strict_schema())

    assert result["value"] == {"cuts": []}
    assert result["receipt"]["provider"] == "openai"
    assert result["receipt"]["model_id"] == "gpt-test-2026-07-22"
    assert result["receipt"]["configuration_sha256"] == "a" * 64
    assert len(calls) == 1
    assert calls[0]["url"] == "https://openai.example/v1/responses"
    assert calls[0]["headers"]["Authorization"] == "Bearer openai-secret"
    assert calls[0]["payload"]["text"]["format"] == {
        "type": "json_schema",
        "name": "usfr_script",
        "strict": True,
        "schema": _strict_schema(),
    }
    assert "openai-secret" not in json.dumps(result, sort_keys=True)


def test_gpt_planner_exposes_storyboard_and_prompt_structured_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {"model": "gpt-test-2026-07-22", "output_text": '{"cuts": []}'}

    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=request_json)

    assert planner.request_storyboard(evidence={"cut_id": "C01"}, schema=_strict_schema())["kind"] == "storyboard"
    assert planner.request_prompt(evidence={"cut_id": "C01"}, schema=_strict_schema())["kind"] == "prompt"


def test_gpt_planner_rejects_non_strict_schema_before_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {}

    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(ProductionPortsError, match="additionalProperties"):
        planner.request_script(evidence={}, schema={"type": "object"})
    assert calls == []


def test_gpt_planner_rejects_permissive_nested_schema_before_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {}

    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=request_json)
    schema = _strict_schema()
    schema["properties"]["cuts"]["items"] = {"type": "object"}

    with pytest.raises(ProductionPortsError, match="additionalProperties"):
        planner.request_script(evidence={}, schema=schema)
    assert calls == []


def test_gpt_planner_rejects_a_pattern_constraint_that_it_cannot_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"model": "gpt-test-2026-07-22", "output_text": '{"cuts": [], "code": "invalid"}'}

    schema = _strict_schema()
    schema["properties"]["code"] = {"type": "string", "pattern": "^[0-9]+$"}
    schema["required"].append("code")
    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(ProductionPortsError, match="unsupported keyword"):
        planner.request_script(evidence={}, schema=schema)
    assert calls == []


def test_gpt_planner_rejects_structured_output_that_violates_the_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {"model": "gpt-test-2026-07-22", "output_text": '{"cuts": "not-an-array"}'}

    planner = EvidenceBoundGptPlanner(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(ProductionPortsError, match="does not match"):
        planner.request_script(evidence={}, schema=_strict_schema())


def test_https_transport_rejects_redirects_before_following_their_target() -> None:
    handler = production_ports._RejectRedirect()

    with pytest.raises(ProductionPortsError, match="redirect"):
        handler.redirect_request(None, None, 302, "Found", None, "http://redirected.example")


def test_post_json_rejects_redirect_through_the_actual_no_redirect_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    class RedirectResponse:
        status = 302

        def close(self) -> None:
            return

    class RedirectConnection:
        requests: list[dict[str, Any]] = []

        def __init__(self, **_kwargs: Any) -> None:
            return

        def request(self, method: str, target: str, body: bytes, headers: dict[str, str]) -> None:
            type(self).requests.append({"method": method, "target": target, "body": body, "headers": headers})

        def getresponse(self) -> RedirectResponse:
            return RedirectResponse()

        def close(self) -> None:
            return

    monkeypatch.setattr(production_ports, "_resolve_hostname", lambda _host: ("8.8.8.8",))
    monkeypatch.setattr(
        production_ports,
        "_NO_REDIRECT_OPENER",
        production_ports._PinnedHttpsOpener(connection_factory=RedirectConnection),
    )

    with pytest.raises(ProductionPortsError, match="redirect"):
        production_ports._post_json(url="https://api.example/redirect", headers={}, payload={"probe": True}, timeout_seconds=1)
    assert len(RedirectConnection.requests) == 1


def test_post_json_pins_the_verified_address_when_dns_would_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    class SuccessResponse:
        status = 200

        def read(self, _limit: int) -> bytes:
            return b'{"ok":true}'

        def close(self) -> None:
            return

    class SuccessConnection:
        resolved_addresses: list[str] = []

        def __init__(self, *, resolved_address: str, **_kwargs: Any) -> None:
            type(self).resolved_addresses.append(resolved_address)

        def request(self, _method: str, _target: str, body: bytes, headers: dict[str, str]) -> None:
            assert body == b'{"probe":true}'
            assert headers == {}

        def getresponse(self) -> SuccessResponse:
            return SuccessResponse()

        def close(self) -> None:
            return

    resolver_calls: list[str] = []

    def resolve(host: str) -> tuple[str, ...]:
        resolver_calls.append(host)
        return ("8.8.8.8",) if len(resolver_calls) == 1 else ("10.0.0.8",)

    monkeypatch.setattr(production_ports, "_resolve_hostname", resolve)
    monkeypatch.setattr(
        production_ports,
        "_NO_REDIRECT_OPENER",
        production_ports._PinnedHttpsOpener(connection_factory=SuccessConnection),
    )

    assert production_ports._post_json(
        url="https://api.example/v1/responses",
        headers={},
        payload={"probe": True},
        timeout_seconds=1,
    ) == {"ok": True}
    assert resolver_calls == ["api.example"]
    assert SuccessConnection.resolved_addresses == ["8.8.8.8"]


def test_pinned_https_connection_uses_the_verified_address_and_original_sni(monkeypatch: pytest.MonkeyPatch) -> None:
    connection_calls: list[tuple[tuple[str, int], float, Any]] = []
    tls_calls: list[tuple[Any, str]] = []
    raw_socket = object()
    tls_socket = object()

    class TlsContext:
        def wrap_socket(self, sock: Any, *, server_hostname: str) -> Any:
            tls_calls.append((sock, server_hostname))
            return tls_socket

    def create_connection(address: tuple[str, int], timeout: float, source_address: Any) -> Any:
        connection_calls.append((address, timeout, source_address))
        return raw_socket

    monkeypatch.setattr(production_ports.socket, "create_connection", create_connection)
    connection = production_ports._PinnedHttpsConnection(
        hostname="api.example",
        port=443,
        resolved_address="8.8.8.8",
        timeout_seconds=3.0,
        ssl_context=TlsContext(),
    )

    connection.connect()

    assert connection_calls == [(("8.8.8.8", 443), 3.0, None)]
    assert tls_calls == [(raw_socket, "api.example")]
    assert connection.sock is tls_socket


def test_runninghub_video_create_uses_standard_model_payload_and_dedicated_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"taskId": "task-123"}

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)
    payload = _standard_video_payload("preserve the approved storyboard")
    result = provider.create_video(payload)

    assert result["task_id"] == "task-123"
    assert calls == [
        {
            "url": "https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer runninghub-standard-secret",
                "Content-Type": "application/json; charset=utf-8",
            },
            "payload": payload,
            "timeout_seconds": 120.0,
        }
    ]
    identity = provider.capability_identity()
    assert identity["provider"] == "runninghub"
    assert identity["model_id"] == "seedance-2.0-fast-token"
    assert identity["sha256"] == hashlib.sha256(
        json.dumps(
            {key: value for key, value in identity.items() if key != "sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    serialized = json.dumps({"identity": identity, "receipt": result}, sort_keys=True)
    assert "runninghub-secret" not in serialized
    assert "runninghub-standard-secret" not in serialized


def test_runninghub_video_create_rejects_source_or_opaque_video_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        request_json=lambda **_kwargs: {"taskId": "unexpected"},
    )

    with pytest.raises(ProductionPortsError, match="video reference binding"):
        provider.create_video(
            {
                "prompt": "Preserve @Image1 identity while the presenter completes one gesture.",
                "resolution": "720p",
                "duration": "5",
                "imageUrls": [],
                "videoUrls": ["https://media.example/source.mp4"],
                "audioUrls": [],
                "generateAudio": True,
                "ratio": "9:16",
                "realPersonMode": False,
                "conversionSlots": [],
                "returnLastFrame": False,
                "seed": -1,
            }
        )


def test_runninghub_video_create_rejects_a_bound_source_slice_without_final_board_lineage_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public source-slice receipt cannot stand in for approved-board proof."""

    from server.packaged_stages import _BoundProviderPayload

    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        request_json=lambda **kwargs: calls.append(kwargs) or {"taskId": "unexpected"},
    )
    payload = _standard_video_payload(
        f"@Image1 preserves the approved director board. {SOURCE_VIDEO_PROMPT_CONTRACT}"
    )
    payload.update(
        {
            "videoUrls": ["https://media.example/source-s01.mp4"],
            "realPersonMode": True,
            "conversionSlots": ["all"],
        }
    )
    binding = {
        "schema_version": "usfr-video-reference/v1",
        "url": payload["videoUrls"][0],
        "source_video_sha256": "a" * 64,
        "source_slice_sha256": "b" * 64,
        "segment_id": "S01",
        "segment_plan_sha256": "c" * 64,
        "source_video_reference_artifact_id": "source-s01-artifact",
        "start_ms": 0,
        "end_ms": 5000,
        "image_reference_binding_sha256": "e" * 64,
        "target_changes": [{"kind": "new_model_image", "sha256": "d" * 64}],
    }
    request = _BoundProviderPayload(
        payload, video_reference_binding=binding, audio_reference_binding=None
    )

    with pytest.raises(ProductionPortsError, match="final reference lineage"):
        provider.create_video(request)

    assert calls == []


def test_runninghub_video_create_rejects_an_unbound_or_full_song_audio_url_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        request_json=lambda **kwargs: calls.append(kwargs) or {"taskId": "unexpected"},
    )
    payload = _standard_video_payload("@Image1 keep the approved action. Use @Audio1 only for this song window.")
    payload["audioUrls"] = ["https://media.example/full-song.wav"]

    with pytest.raises(ProductionPortsError, match="audio reference binding"):
        provider.create_video(payload)

    assert calls == []


def test_runninghub_video_create_rejects_a_complete_forged_full_song_audio_sidecar_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.packaged_stages import _BoundProviderPayload

    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        request_json=lambda **kwargs: calls.append(kwargs) or {"taskId": "unexpected"},
    )
    payload = _standard_video_payload("@Image1 keep the approved action. Use @Audio1 only for this song window.")
    payload["audioUrls"] = ["https://media.example/full-song.wav"]
    forged = {
        "schema_version": "usfr-background-music-reference/v1",
        "url": payload["audioUrls"][0],
        "source_audio_sha256": "a" * 64,
        "source_slice_sha256": "b" * 64,
        "segment_id": "S01",
        "start_ms": 0,
        "end_ms": 5000,
        "segment_plan_sha256": "c" * 64,
        "replacement_timing_policy": "source_music_cut_in_out_exact",
        "source_music_windows": [{
            "event_id": "M01",
            "source_start_ms": 0,
            "source_end_ms": 5000,
            "segment_start_ms": 0,
            "segment_end_ms": 5000,
            "uploaded_start_ms": 0,
            "uploaded_end_ms": 5000,
        }],
    }
    request = _BoundProviderPayload(
        payload, video_reference_binding=None, audio_reference_binding=forged
    )

    with pytest.raises(ProductionPortsError, match="server-issued audio artifact receipt"):
        provider.create_video(request)

    assert calls == []


def test_runninghub_video_create_rejects_a_hmac_signed_audio_sidecar_without_server_artifact_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A field-valid sidecar is not trusted until it names a server artifact.

    This models an untrusted caller that can present a complete binding and a
    syntactically valid HMAC.  The paid HTTP transport must still be unreachable
    because no immutable ``background_music_reference`` receipt was issued for
    the claimed slice.
    """

    from server.packaged_stages import _BoundProviderPayload
    from server.runninghub_standard_contract import build_provider_audit_proof

    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        request_json=lambda **kwargs: calls.append(kwargs) or {"taskId": "unexpected"},
    )
    payload = _standard_video_payload("@Image1 keep the approved action. Use @Audio1 only for this song window.")
    payload["audioUrls"] = ["https://media.example/forged-slice.wav"]
    forged = {
        "schema_version": "usfr-background-music-reference/v1",
        "url": payload["audioUrls"][0],
        "source_audio_sha256": "a" * 64,
        "source_slice_sha256": "b" * 64,
        "segment_id": "S01",
        "start_ms": 0,
        "end_ms": 5000,
        "segment_plan_sha256": "c" * 64,
        "replacement_timing_policy": "source_music_cut_in_out_exact",
        "source_music_windows": [{
            "event_id": "M01",
            "source_start_ms": 0,
            "source_end_ms": 5000,
            "segment_start_ms": 0,
            "segment_end_ms": 5000,
            "uploaded_start_ms": 0,
            "uploaded_end_ms": 5000,
        }],
    }
    request = _BoundProviderPayload(
        payload,
        video_reference_binding=None,
        audio_reference_binding=forged,
        provider_audit_proof=build_provider_audit_proof(
            payload, None, forged, secret="test-capability-secret"
        ),
    )

    with pytest.raises(ProductionPortsError, match="server-issued audio artifact receipt"):
        provider.create_video(request)

    assert calls == []


def test_runninghub_video_create_does_not_retry_an_ambiguous_paid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        raise OSError("connection closed after submit")

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(RunningHubCreateAmbiguousError, match="ambiguous") as error:
        provider.create_video(_standard_video_payload("no automatic retry"))
    assert error.value.retryable is False
    assert error.value.reconciliation_required is True
    assert len(calls) == 1


def test_runninghub_paid_create_turns_http_failure_into_non_retryable_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        raise ProductionPortsError("production HTTPS request failed")

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(RunningHubCreateAmbiguousError, match="ambiguous") as error:
        provider.create_video(_standard_video_payload("provider may have accepted this"))
    assert error.value.retryable is False
    assert error.value.reconciliation_required is True


def test_runninghub_paid_create_turns_malformed_response_into_non_retryable_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> Any:
        return ["not-a-response-object"]

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(RunningHubCreateAmbiguousError, match="ambiguous"):
        provider.create_video(_standard_video_payload("malformed response"))


def test_runninghub_paid_create_turns_missing_task_id_into_non_retryable_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "SUCCESS"}

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(RunningHubCreateAmbiguousError, match="taskId") as error:
        provider.create_video(_standard_video_payload("response omitted task id"))
    assert error.value.retryable is False
    assert error.value.reconciliation_required is True


def test_runninghub_video_create_reports_a_missing_runtime_key_as_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_complete_environment(monkeypatch)
    config = ProductionEnvironment.from_environ()
    monkeypatch.delenv("RUNNINGHUB_SEEDANCE_API_KEY")
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"taskId": "should-not-be-called"}

    provider = RunningHubSeedanceProvider(config, request_json=request_json)

    with pytest.raises(ProductionPortsError, match="RUNNINGHUB_SEEDANCE_API_KEY is required") as error:
        provider.create_video(_standard_video_payload("missing key"))
    assert "ambiguous" not in str(error.value)
    assert calls == []


def test_runninghub_asset_create_uses_packaged_image_route(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"taskId": "image-task"}

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)
    result = provider.create_asset({"prompt": "storyboard frame"})

    assert result["task_id"] == "image-task"
    assert calls[0]["url"] == "https://runninghub.example/openapi/v2/rhart-image-g-2-official/image-to-image"
    assert calls[0]["payload"] == {"prompt": "storyboard frame"}


def test_runninghub_lookup_accepts_success_only_with_an_https_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)
    calls: list[dict[str, Any]] = []

    def request_json(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"status": "SUCCESS", "results": [{"url": "https://media.example/task-123.mp4"}]}

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)
    result = provider.lookup({"taskId": "task-123"})

    assert result["status"] == "SUCCESS"
    assert "result_url" not in result
    assert calls[0]["payload"] == {"taskId": "task-123"}


def test_runninghub_lookup_keeps_a_signed_result_url_private_until_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_complete_environment(monkeypatch)
    downloads: list[dict[str, Any]] = []

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "SUCCESS",
            "results": [{"url": "https://media.example/task-123.mp4?signature=temporary"}],
        }

    def download_bytes(**kwargs: Any) -> bytes:
        downloads.append(kwargs)
        return b"generated-media"

    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        request_json=request_json,
        download_bytes=download_bytes,
    )
    result = provider.lookup({"taskId": "task-123"})
    receipt = provider.download("task-123", tmp_path / "provider.mp4")

    assert "result_url" not in result
    assert "temporary" not in json.dumps(result, sort_keys=True)
    assert downloads == [{"url": "https://media.example/task-123.mp4?signature=temporary", "timeout_seconds": 180.0}]
    assert "temporary" not in json.dumps(receipt, sort_keys=True)


def test_runninghub_lookup_rejects_non_https_success_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "SUCCESS", "results": [{"url": "http://media.example/task-123.mp4"}]}

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(ProductionPortsError, match="HTTPS"):
        provider.lookup({"taskId": "task-123"})


def test_runninghub_lookup_rejects_success_url_with_an_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "SUCCESS", "results": [{"url": "https://media.example:invalid/task-123.mp4"}]}

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(ProductionPortsError, match="HTTPS"):
        provider.lookup({"taskId": "task-123"})


def test_runninghub_lookup_rejects_lowercase_provider_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "success", "results": [{"url": "https://media.example/task-123.mp4"}]}

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(ProductionPortsError, match="unsupported task status"):
        provider.lookup({"taskId": "task-123"})


def test_runninghub_lookup_raises_for_terminal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "FAILED", "message": "model rejected request"}

    provider = RunningHubSeedanceProvider(ProductionEnvironment.from_environ(), request_json=request_json)

    with pytest.raises(RunningHubTaskFailed, match="FAILED"):
        provider.lookup({"taskId": "task-123"})


def test_runninghub_download_writes_verified_https_result_without_a_network_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_complete_environment(monkeypatch)
    downloads: list[dict[str, Any]] = []

    def download_bytes(**kwargs: Any) -> bytes:
        downloads.append(kwargs)
        return b"generated-media"

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "SUCCESS", "results": [{"url": "https://media.example/task-123.mp4"}]}

    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        request_json=request_json,
        download_bytes=download_bytes,
    )
    destination = tmp_path / "provider.mp4"
    provider.lookup({"taskId": "task-123"})
    receipt = provider.download("task-123", destination)

    assert destination.read_bytes() == b"generated-media"
    assert receipt == {
        "provider": "runninghub",
        "result_url": "https://media.example/task-123.mp4",
        "sha256": hashlib.sha256(b"generated-media").hexdigest(),
        "size_bytes": len(b"generated-media"),
    }
    assert downloads == [{"url": "https://media.example/task-123.mp4", "timeout_seconds": 180.0}]


def test_runninghub_download_rejects_a_url_or_unknown_task_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_complete_environment(monkeypatch)
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        download_bytes=lambda **_kwargs: b"generated-media",
    )

    with pytest.raises(ProductionPortsError, match="private task result"):
        provider.download("https://media.example/task-123.mp4?signature=temporary", tmp_path / "provider.mp4")


def test_runninghub_download_redacts_a_signed_query_from_its_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_complete_environment(monkeypatch)

    def request_json(**_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "SUCCESS",
            "results": [{"url": "https://media.example/task-123.mp4?signature=temporary-secret"}],
        }

    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(),
        request_json=request_json,
        download_bytes=lambda **_kwargs: b"generated-media",
    )
    provider.lookup({"taskId": "task-123"})

    receipt = provider.download(
        "task-123",
        tmp_path / "provider.mp4",
    )

    assert receipt["result_url"] == "https://media.example/task-123.mp4"
    assert "temporary-secret" not in json.dumps(receipt, sort_keys=True)
