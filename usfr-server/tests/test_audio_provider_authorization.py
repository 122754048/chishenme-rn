from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import fakeredis


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _sha(char: str) -> str:
    return char * 64


def _payload_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import server.production_ports as production_ports

    monkeypatch.setattr(production_ports, "_resolve_hostname", lambda _host: ("8.8.8.8",))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_MODEL_CONFIG_SHA256", _sha("a"))
    monkeypatch.setenv("RUNNINGHUB_BASE_URL", "https://runninghub.example")
    monkeypatch.setenv("RUNNINGHUB_API_KEY", "test-key")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_API_KEY", "test-seedance-key")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_CREATE_URL", "https://runninghub.example/seedance/create")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_QUERY_URL", "https://runninghub.example/seedance/query")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_UPLOAD_URL", "https://runninghub.example/seedance/upload")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_WORKFLOW_ID", "workflow-test")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_MODEL_ID", "seedance-test")
    monkeypatch.setenv("RUNNINGHUB_SEEDANCE_CONFIG_SHA256", _sha("e"))
    monkeypatch.setenv("USFR_CAPABILITY_SECRET", "test-capability-secret")


def _payload() -> dict[str, object]:
    return {
        "prompt": "@Image1 keep the approved action. Use @Audio1 only for this song window.",
        "resolution": "720p", "duration": "4",
        "imageUrls": ["https://media.example/board.png"], "videoUrls": [],
        "audioUrls": ["https://media.example/song-slice.wav"], "generateAudio": True,
        "ratio": "9:16", "realPersonMode": False, "conversionSlots": [],
        "returnLastFrame": False, "seed": -1,
    }


def _binding() -> dict[str, object]:
    return {
        "schema_version": "usfr-background-music-reference/v1",
        "url": "https://media.example/song-slice.wav",
        "source_audio_sha256": _sha("a"), "source_slice_sha256": _sha("b"),
        "segment_id": "S01", "start_ms": 0, "end_ms": 4000,
        "segment_plan_sha256": _sha("c"),
        "replacement_timing_policy": "source_music_cut_in_out_exact",
        "source_music_windows": [{
            "event_id": "M01", "source_start_ms": 0, "source_end_ms": 4000,
            "segment_start_ms": 0, "segment_end_ms": 4000,
            "uploaded_start_ms": 0, "uploaded_end_ms": 4000,
        }],
    }


def _receipt(binding: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "usfr-background-music-artifact-receipt/v1",
        "artifact_id": "music-current", "object_key": "jobs/current/music.wav",
        "kind": "background_music_reference", "sha256": binding["source_slice_sha256"],
        "source_audio_sha256": binding["source_audio_sha256"], "segment_id": "S01",
        "start_ms": 0, "end_ms": 4000, "segment_plan_sha256": binding["segment_plan_sha256"],
        "replacement_timing_policy": binding["replacement_timing_policy"],
        "source_music_windows": binding["source_music_windows"],
    }


class _Store:
    def __init__(self, *, job_id: str, audit_id: str, music_id: str, attempt_id: str) -> None:
        from server.job_models import ArtifactRef, ProviderAttempt

        self.job_id = job_id
        self.snapshot = SimpleNamespace(job_id=job_id, expires_at_ms=4_102_444_800_000)
        self.audit = ArtifactRef(audit_id, "seedance_request_audit", f"jobs/{job_id}/audit.json", _sha("d"), "application/json", 10)
        self.music = ArtifactRef(
            music_id, "background_music_reference", f"jobs/{job_id}/music.wav", _sha("b"), "audio/wav", 10,
            metadata={"segment_id": "S01", "segment_plan_sha256": _sha("c"), "source_audio_sha256": _sha("a"), "start_ms": 0, "end_ms": 4000,
                "replacement_timing_policy": "source_music_cut_in_out_exact", "source_music_windows": _binding()["source_music_windows"]},
        )
        self.attempt = ProviderAttempt.new(
            attempt_id=attempt_id, operation="CreateVideo", request_sha256="", segment_id="S01", segment_plan_sha256=_sha("c")
        )
        self.attempt = replace(self.attempt, status="SUBMITTING")
        self.extra_artifacts = []
        self.consumed_authorizations: set[str] = set()

    def get_job(self, job_id: str):
        return self.snapshot if job_id == self.job_id else None

    def get_artifact(self, job_id: str, artifact_id: str):
        if job_id != self.job_id:
            return None
        return {item.artifact_id: item for item in (self.audit, self.music, *self.extra_artifacts)}.get(artifact_id)

    def list_artifacts(self, job_id: str):
        return (self.audit, self.music, *self.extra_artifacts) if job_id == self.job_id else ()

    def list_provider_attempts(self, job_id: str):
        return (self.attempt,) if job_id == self.job_id else ()

    def consume_provider_authorization_nonce(self, *, job_id: str, nonce: str, **_kwargs):
        if job_id != self.job_id or nonce in self.consumed_authorizations:
            return False
        self.consumed_authorizations.add(nonce)
        return True


def _visual_payload_and_lineage(job_id: str):
    from server.job_models import ArtifactRef

    payload = _payload()
    payload.update({
        "imageUrls": ["https://media.example/seedance-visual-carrier.png", "https://media.example/model.png"],
        "videoUrls": ["https://media.example/source.mp4"], "audioUrls": [],
        "realPersonMode": True, "conversionSlots": ["all"],
    })
    source_video, source_slice, plan, target = _sha("a"), _sha("b"), _sha("c"), _sha("d")
    board_sha, source_sheet, control_sheet, control_receipt = _sha("e"), _sha("f"), _sha("0"), _sha("1")
    carrier_sha, layout_receipt_sha = _sha("4"), _sha("5")
    binding = {
        "schema_version": "usfr-video-reference/v1", "url": payload["videoUrls"][0],
        "source_video_sha256": source_video, "source_slice_sha256": source_slice,
        "segment_id": "S01", "segment_plan_sha256": plan,
        "source_video_reference_artifact_id": f"source-{job_id}", "start_ms": 0, "end_ms": 4000,
        "storyboard_url": payload["imageUrls"][0], "target_changes": [{"kind": "new_model_image", "sha256": target}],
    }
    lineage = {
        "schema_version": "seedance-final-reference-lineage/v1", "segment_id": "S01", "segment_plan_sha256": plan,
        "ordered_image_urls": list(payload["imageUrls"]), "ordered_video_urls": list(payload["videoUrls"]),
        "approved_board": {
            "artifact_id": f"board-{job_id}", "object_key": f"jobs/{job_id}/board.png", "kind": "storyboard_image", "sha256": board_sha,
            "segment_id": "S01", "storyboard_revision": 1, "storyboard_manifest_sha256": _sha("2"), "url": payload["imageUrls"][0],
            "source_video_sha256": source_video, "source_keyframe_sheet_sha256": source_sheet,
            "replacement_control_keyframe_sheet_sha256": control_sheet, "replacement_control_keyframe_receipt_sha256": control_receipt,
            "replacement_target_sha256s": [target], "approved_visible_text_locks_sha256": _sha("3"),
            "execution_carrier_artifact_id": f"carrier-{job_id}",
            "execution_carrier_object_key": f"jobs/{job_id}/seedance-visual-carrier.png",
            "execution_carrier_sha256": carrier_sha,
            "storyboard_layout_receipt_sha256": layout_receipt_sha,
            "execution_carrier_source_roi_sha256": carrier_sha,
        },
        "source_reference": {
            "artifact_id": f"source-{job_id}", "object_key": f"jobs/{job_id}/source.mp4", "kind": "source_video_reference", "sha256": source_slice,
            "source_video_sha256": source_video, "segment_id": "S01", "segment_plan_sha256": plan, "start_ms": 0, "end_ms": 4000, "url": payload["videoUrls"][0],
        },
        "allowed_target_changes": [{"kind": "new_model_image", "sha256": target, "image_slot": 2, "url": payload["imageUrls"][1]}],
        "forbidden_artifact_kinds": [
            "source_keyframe_sheet", "replacement_control_keyframe_sheet",
            "replacement_control_keyframe_receipt", "storyboard_image",
            "storyboard_layout_receipt",
        ],
    }
    artifacts = [
        ArtifactRef(f"board-{job_id}", "storyboard_image", f"jobs/{job_id}/board.png", board_sha, "image/png", 1),
        ArtifactRef(f"source-{job_id}", "source_video_reference", f"jobs/{job_id}/source.mp4", source_slice, "video/mp4", 1),
        ArtifactRef(f"source-sheet-{job_id}", "source_keyframe_sheet", f"jobs/{job_id}/source-sheet.png", source_sheet, "image/png", 1),
        ArtifactRef(f"control-sheet-{job_id}", "replacement_control_keyframe_sheet", f"jobs/{job_id}/control-sheet.png", control_sheet, "image/png", 1),
        ArtifactRef(f"control-receipt-{job_id}", "replacement_control_keyframe_receipt", f"jobs/{job_id}/control.json", control_receipt, "application/json", 1),
        ArtifactRef(f"carrier-{job_id}", "seedance_visual_carrier", f"jobs/{job_id}/seedance-visual-carrier.png", carrier_sha, "image/png", 1),
        ArtifactRef(f"layout-{job_id}", "storyboard_layout_receipt", f"jobs/{job_id}/storyboard-layout.json", layout_receipt_sha, "application/json", 1),
    ]
    return payload, binding, lineage, artifacts


def test_provider_authorization_rejects_complete_previous_job_hmac_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """A legitimate authorization from another job/audit/artifact cannot replay."""

    from server.audio_provider_authorization import mint_audio_provider_authorization
    from server.packaged_stages import _BoundProviderPayload
    from server.production_ports import ProductionEnvironment, ProductionPortsError, RunningHubSeedanceProvider
    from server.runninghub_standard_contract import build_provider_audit_proof

    _environment(monkeypatch)
    current = _Store(job_id="job-current", audit_id="audit-current", music_id="music-current", attempt_id="attempt-current")
    previous = _Store(job_id="job-previous", audit_id="audit-previous", music_id="music-previous", attempt_id="attempt-previous")
    binding, receipt, payload = _binding(), _receipt(_binding()), _payload()
    receipt["object_key"] = "jobs/job-current/music.wav"
    previous.attempt = replace(previous.attempt, request_sha256=_payload_sha(payload))
    current.attempt = replace(current.attempt, request_sha256=_payload_sha(payload))
    previous_receipt = dict(receipt)
    previous_receipt.update({"artifact_id": "music-previous", "object_key": "jobs/job-previous/music.wav"})
    authorization, _ = mint_audio_provider_authorization(
        job_store=previous, job_id="job-previous", audit_artifact=previous.audit,
        payload=payload, video_reference_binding=None, audio_reference_binding=binding,
        audio_reference_artifact_receipt=previous_receipt, attempt=previous.attempt,
        secret="test-capability-secret",
    )
    _, verifier = mint_audio_provider_authorization(
        job_store=current, job_id="job-current", audit_artifact=current.audit,
        payload=payload, video_reference_binding=None, audio_reference_binding=binding,
        audio_reference_artifact_receipt=receipt, attempt=current.attempt,
        secret="test-capability-secret",
    )
    calls: list[dict[str, object]] = []
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(), request_json=lambda **kwargs: calls.append(kwargs) or {"taskId": "unexpected"}
    )
    request = _BoundProviderPayload(
        payload, video_reference_binding=None, audio_reference_binding=binding,
        audio_reference_artifact_receipt=previous_receipt,
        provider_audit_proof=build_provider_audit_proof(payload, None, binding, secret="test-capability-secret", audio_reference_artifact_receipt=previous_receipt),
        audio_provider_authorization=authorization,
        server_audio_authorization_verifier=verifier,
    )

    with pytest.raises(ProductionPortsError, match="audio provider authorization"):
        provider.create_video(request)

    assert calls == []


def test_provider_authorization_admits_current_song_slice_once_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    from server.audio_provider_authorization import mint_audio_provider_authorization
    from server.packaged_stages import _BoundProviderPayload
    from server.production_ports import ProductionEnvironment, RunningHubSeedanceProvider
    from server.runninghub_standard_contract import build_provider_audit_proof

    _environment(monkeypatch)
    store = _Store(job_id="job-current", audit_id="audit-current", music_id="music-current", attempt_id="attempt-current")
    binding, receipt, payload = _binding(), _receipt(_binding()), _payload()
    receipt["object_key"] = "jobs/job-current/music.wav"
    store.attempt = replace(store.attempt, request_sha256=_payload_sha(payload))
    authorization, verifier = mint_audio_provider_authorization(
        job_store=store, job_id="job-current", audit_artifact=store.audit,
        payload=payload, video_reference_binding=None, audio_reference_binding=binding,
        audio_reference_artifact_receipt=receipt, attempt=store.attempt,
        secret="test-capability-secret",
    )
    calls: list[dict[str, object]] = []
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(), request_json=lambda **kwargs: calls.append(kwargs) or {"taskId": "created"}
    )
    request = _BoundProviderPayload(
        payload, video_reference_binding=None, audio_reference_binding=binding,
        audio_reference_artifact_receipt=receipt,
        provider_audit_proof=build_provider_audit_proof(payload, None, binding, secret="test-capability-secret", audio_reference_artifact_receipt=receipt),
        audio_provider_authorization=authorization,
        server_audio_authorization_verifier=verifier,
    )

    assert provider.create_video(request)["task_id"] == "created"
    assert len(calls) == 1


def test_provider_rejects_complete_previous_visual_lineage_authorization_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """A self-consistent old board/source/control lineage is not current-job authority."""

    from server.audio_provider_authorization import mint_audio_provider_authorization
    from server.packaged_stages import _BoundProviderPayload
    from server.production_ports import ProductionEnvironment, ProductionPortsError, RunningHubSeedanceProvider

    _environment(monkeypatch)
    current = _Store(job_id="job-current", audit_id="audit-current", music_id="music-current", attempt_id="attempt-current")
    previous = _Store(job_id="job-previous", audit_id="audit-previous", music_id="music-previous", attempt_id="attempt-previous")
    current_payload, current_binding, current_lineage, current_artifacts = _visual_payload_and_lineage("job-current")
    previous_payload, previous_binding, previous_lineage, previous_artifacts = _visual_payload_and_lineage("job-previous")
    current.extra_artifacts, previous.extra_artifacts = current_artifacts, previous_artifacts
    current.attempt = replace(current.attempt, request_sha256=_payload_sha(current_payload))
    previous.attempt = replace(previous.attempt, request_sha256=_payload_sha(previous_payload))
    old_authorization, _ = mint_audio_provider_authorization(
        job_store=previous, job_id="job-previous", audit_artifact=previous.audit,
        payload=previous_payload, video_reference_binding=previous_binding, final_reference_lineage=previous_lineage,
        audio_reference_binding=None, audio_reference_artifact_receipt=None, attempt=previous.attempt,
        secret="test-capability-secret",
    )
    _, current_verifier = mint_audio_provider_authorization(
        job_store=current, job_id="job-current", audit_artifact=current.audit,
        payload=current_payload, video_reference_binding=current_binding, final_reference_lineage=current_lineage,
        audio_reference_binding=None, audio_reference_artifact_receipt=None, attempt=current.attempt,
        secret="test-capability-secret",
    )
    calls: list[dict[str, object]] = []
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(), request_json=lambda **kwargs: calls.append(kwargs) or {"taskId": "unexpected"}
    )
    forged = _BoundProviderPayload(
        previous_payload, video_reference_binding=previous_binding, final_reference_lineage=previous_lineage,
        audio_reference_binding=None, audio_provider_authorization=old_authorization,
        server_audio_authorization_verifier=current_verifier,
    )

    with pytest.raises(ProductionPortsError, match="audio provider authorization"):
        provider.create_video(forged)

    assert calls == []


def test_real_redis_authorization_admits_current_visual_and_audio_request_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The durable SUBMITTING attempt authorizes one exact visual+audio HTTP request."""

    from server.audio_provider_authorization import (
        ServerAudioAuthorizationVerifier,
        mint_audio_provider_authorization,
    )
    from server.job_models import ArtifactRef
    from server.packaged_stages import _BoundProviderPayload
    from server.production_ports import ProductionEnvironment, ProductionPortsError, RunningHubSeedanceProvider
    from server.redis_job_store import RedisEphemeralJobStore
    from server.runninghub_standard_contract import build_provider_audit_proof

    _environment(monkeypatch)
    job_id = "job-real-current"
    store = RedisEphemeralJobStore(fakeredis.FakeRedis(decode_responses=False), prefix="provider-auth-real-current")
    job = store.create_job(
        slots_manifest={"admission": {"can_proceed": True}}, capability_token_hash=_sha("a"), ttl_seconds=3600,
    )
    payload, video_binding, lineage, visual_artifacts = _visual_payload_and_lineage(job.job_id)
    binding, receipt = _binding(), _receipt(_binding())
    receipt.update({"artifact_id": "music-real", "object_key": f"jobs/{job.job_id}/music.wav"})
    payload["audioUrls"] = [str(binding["url"])]
    for artifact in visual_artifacts:
        store.put_artifact(job_id=job.job_id, artifact=artifact)
    audit = ArtifactRef("audit-real", "seedance_request_audit", f"jobs/{job.job_id}/audit.json", _sha("9"), "application/json", 1)
    music = ArtifactRef(
        "music-real", "background_music_reference", f"jobs/{job.job_id}/music.wav", _sha("b"), "audio/wav", 1,
        metadata={key: receipt[key] for key in ("source_audio_sha256", "segment_id", "start_ms", "end_ms", "segment_plan_sha256", "replacement_timing_policy", "source_music_windows")},
    )
    store.put_artifact(job_id=job.job_id, artifact=audit)
    store.put_artifact(job_id=job.job_id, artifact=music)
    attempt = store.begin_provider_attempt(
        job_id=job.job_id, expected_version=job.version, operation="CreateVideo", request_sha256=_payload_sha(payload),
        segment_id="S01", segment_plan_sha256=_sha("c"),
    )
    authorization, verifier = mint_audio_provider_authorization(
        job_store=store, job_id=job.job_id, audit_artifact=audit, payload=payload,
        video_reference_binding=video_binding, final_reference_lineage=lineage,
        audio_reference_binding=binding, audio_reference_artifact_receipt=receipt,
        attempt=attempt, secret="test-capability-secret",
    )
    calls: list[dict[str, object]] = []
    provider = RunningHubSeedanceProvider(
        ProductionEnvironment.from_environ(), request_json=lambda **kwargs: calls.append(kwargs) or {"taskId": "created"}
    )
    request = _BoundProviderPayload(
        payload, video_reference_binding=video_binding, final_reference_lineage=lineage,
        audio_reference_binding=binding, audio_reference_artifact_receipt=receipt,
        provider_audit_proof=build_provider_audit_proof(payload, video_binding, binding, secret="test-capability-secret", audio_reference_artifact_receipt=receipt),
        audio_provider_authorization=authorization, server_audio_authorization_verifier=verifier,
    )

    forged_payload = {**payload, "prompt": payload["prompt"] + " Keep the original closing pose."}
    forged = _BoundProviderPayload(
        forged_payload, video_reference_binding=video_binding, final_reference_lineage=lineage,
        audio_reference_binding=binding, audio_reference_artifact_receipt=receipt,
        provider_audit_proof=request.provider_audit_proof,
        audio_provider_authorization=authorization, server_audio_authorization_verifier=verifier,
    )
    with pytest.raises(ProductionPortsError):
        provider.create_video(forged)
    assert calls == []

    foreign_job = store.create_job(
        slots_manifest={"admission": {"can_proceed": True}}, capability_token_hash=_sha("a"), ttl_seconds=3600,
    )
    foreign_payload, foreign_video_binding, foreign_lineage, foreign_visual_artifacts = _visual_payload_and_lineage(foreign_job.job_id)
    foreign_binding, foreign_receipt = _binding(), _receipt(_binding())
    foreign_receipt.update({"artifact_id": "music-foreign", "object_key": f"jobs/{foreign_job.job_id}/music.wav"})
    foreign_payload["audioUrls"] = [str(foreign_binding["url"])]
    for artifact in foreign_visual_artifacts:
        store.put_artifact(job_id=foreign_job.job_id, artifact=artifact)
    foreign_audit = ArtifactRef("audit-foreign", "seedance_request_audit", f"jobs/{foreign_job.job_id}/audit.json", _sha("8"), "application/json", 1)
    foreign_music = ArtifactRef(
        "music-foreign", "background_music_reference", f"jobs/{foreign_job.job_id}/music.wav", _sha("b"), "audio/wav", 1,
        metadata={key: foreign_receipt[key] for key in ("source_audio_sha256", "segment_id", "start_ms", "end_ms", "segment_plan_sha256", "replacement_timing_policy", "source_music_windows")},
    )
    store.put_artifact(job_id=foreign_job.job_id, artifact=foreign_audit)
    store.put_artifact(job_id=foreign_job.job_id, artifact=foreign_music)
    foreign_attempt = store.begin_provider_attempt(
        job_id=foreign_job.job_id, expected_version=foreign_job.version, operation="CreateVideo",
        request_sha256=_payload_sha(foreign_payload), segment_id="S01", segment_plan_sha256=_sha("c"),
    )
    foreign_authorization, _ = mint_audio_provider_authorization(
        job_store=store, job_id=foreign_job.job_id, audit_artifact=foreign_audit, payload=foreign_payload,
        video_reference_binding=foreign_video_binding, final_reference_lineage=foreign_lineage,
        audio_reference_binding=foreign_binding, audio_reference_artifact_receipt=foreign_receipt,
        attempt=foreign_attempt, secret="test-capability-secret",
    )
    cross_job = _BoundProviderPayload(
        foreign_payload, video_reference_binding=foreign_video_binding, final_reference_lineage=foreign_lineage,
        audio_reference_binding=foreign_binding, audio_reference_artifact_receipt=foreign_receipt,
        provider_audit_proof=build_provider_audit_proof(foreign_payload, foreign_video_binding, foreign_binding, secret="test-capability-secret", audio_reference_artifact_receipt=foreign_receipt),
        audio_provider_authorization=foreign_authorization, server_audio_authorization_verifier=verifier,
    )
    with pytest.raises(ProductionPortsError, match="audio provider authorization"):
        provider.create_video(cross_job)
    assert calls == []

    assert provider.create_video(request)["task_id"] == "created"
    assert len(calls) == 1
    assert "audio_provider_authorization" not in calls[0]["payload"]
    fresh_verifier = ServerAudioAuthorizationVerifier(
        job_store=store, job_id=job.job_id, authorization=authorization, secret="test-capability-secret"
    )
    replay = _BoundProviderPayload(
        payload, video_reference_binding=video_binding, final_reference_lineage=lineage,
        audio_reference_binding=binding, audio_reference_artifact_receipt=receipt,
        provider_audit_proof=request.provider_audit_proof,
        audio_provider_authorization=authorization, server_audio_authorization_verifier=fresh_verifier,
    )
    with pytest.raises(ProductionPortsError, match="audio provider authorization"):
        provider.create_video(replay)
    assert len(calls) == 1

    stale_payload = {**payload, "prompt": payload["prompt"] + " Keep the original eye line."}
    stale_attempt = store.begin_provider_attempt(
        job_id=job.job_id, expected_version=store.get_job(job.job_id).version, operation="CreateVideo",
        request_sha256=_payload_sha(stale_payload), segment_id="S01", segment_plan_sha256=_sha("c"),
    )
    stale_authorization, stale_verifier = mint_audio_provider_authorization(
        job_store=store, job_id=job.job_id, audit_artifact=audit, payload=stale_payload,
        video_reference_binding=video_binding, final_reference_lineage=lineage,
        audio_reference_binding=binding, audio_reference_artifact_receipt=receipt,
        attempt=stale_attempt, secret="test-capability-secret",
    )
    store.update_provider_attempt(
        job_id=job.job_id, expected_version=store.get_job(job.job_id).version,
        attempt=replace(stale_attempt, status="RUNNING"), ttl_seconds=3600,
    )
    stale = _BoundProviderPayload(
        stale_payload, video_reference_binding=video_binding, final_reference_lineage=lineage,
        audio_reference_binding=binding, audio_reference_artifact_receipt=receipt,
        provider_audit_proof=build_provider_audit_proof(stale_payload, video_binding, binding, secret="test-capability-secret", audio_reference_artifact_receipt=receipt),
        audio_provider_authorization=stale_authorization, server_audio_authorization_verifier=stale_verifier,
    )
    with pytest.raises(ProductionPortsError, match="audio provider authorization"):
        provider.create_video(stale)
    assert len(calls) == 1
