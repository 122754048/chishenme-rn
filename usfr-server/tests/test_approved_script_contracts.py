from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import server.performance_audio_contracts as performance_audio_contracts
from server.errors import ReplicationError
from server.high_fidelity_ports import HighFidelityStageAdapter

from test_performance_audio_contracts import _approved_lines, _audio_contract, _lines


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _approval(*, revision, script_sha, timeline_sha, lines):
    canonical_lines = _canonical(lines)
    return {
        "contract": "approved-script-lines/v1",
        "revision": revision,
        "script_sha256": script_sha,
        "source_content_timeline_sha256": timeline_sha,
        "line_contracts": lines,
        "line_contracts_sha256": hashlib.sha256(canonical_lines).hexdigest(),
    }


class _Context:
    def __init__(self, *, approval, script_payload, timeline_payload):
        script_raw = _canonical(script_payload)
        timeline_raw = _canonical(timeline_payload)
        source_audio_payload = {
            "contract": "performance-audio-source/v1",
            "mode": "source_audio_replicate_v1",
            "source_audio_sha256": "4" * 64,
        }
        lyrics_payload = {
            "contract": "audio-lyrics-beat/v1",
            "source_audio_sha256": "4" * 64,
            "segments": _audio_contract()["audio_contract"]["segments"],
        }
        source_audio_raw = _canonical(source_audio_payload)
        lyrics_raw = _canonical(lyrics_payload)
        self.job_id = "recovery-job"
        self.snapshot = SimpleNamespace(
            current_script_revision=approval["revision"],
            approved_script_sha256=hashlib.sha256(script_raw).hexdigest(),
        )
        assert approval["script_sha256"] == self.snapshot.approved_script_sha256
        self.job_store = SimpleNamespace(
            get_script_approval=lambda job_id, revision: approval
        )
        self._payloads = {
            ("script_revision", self.snapshot.approved_script_sha256): script_raw,
            ("source_content_timeline", approval["source_content_timeline_sha256"]): timeline_raw,
            ("performance_audio_source_contract", hashlib.sha256(source_audio_raw).hexdigest()): source_audio_raw,
            ("audio_lyrics_beat_contract", hashlib.sha256(lyrics_raw).hexdigest()): lyrics_raw,
        }
        self.artifacts = (
            {"kind": "script_revision", "sha256": self.snapshot.approved_script_sha256},
            {"kind": "source_content_timeline", "sha256": approval["source_content_timeline_sha256"]},
            {"kind": "performance_audio_source_contract", "sha256": hashlib.sha256(source_audio_raw).hexdigest()},
            {"kind": "audio_lyrics_beat_contract", "sha256": hashlib.sha256(lyrics_raw).hexdigest()},
        )
        self.published = []

    @contextmanager
    def materialize_artifact(self, kind, *, sha256, **_kwargs):
        raw = self._payloads[(kind, sha256)]
        path = Path("C:/Temp") / f"{kind}-{sha256}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        try:
            yield SimpleNamespace(path=path)
        finally:
            path.unlink(missing_ok=True)

    def publish_bytes(self, *, kind, data, content_type, expected_sha256):
        assert content_type == "application/json"
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        value = {"kind": kind, "sha256": expected_sha256}
        self.published.append((value, data))
        return value


def _recovery_fixture():
    timeline_payload = {"contract": "source-content-timeline/v1", "contract_sha256": "3" * 64}
    timeline_sha = hashlib.sha256(_canonical(timeline_payload)).hexdigest()
    lines = [
        {**line, "source_content_timeline_sha256": timeline_sha}
        for line in _approved_lines()
    ]
    candidate_cuts = []
    for line in _lines():
        candidate = {
            key: deepcopy(value)
            for key, value in line.items()
            if key not in {"line_id", "source_content_timeline_sha256", "content_type", "speaker_assignment"}
        }
        candidate_cuts.append(candidate)
    script_payload = {
        "performance_line_candidates": {
            "contract": "performance-line-candidate/v1",
            "status": "PENDING_CONFIRMATION",
            "source_audio_sha256": "4" * 64,
            "source_duration_ms": 16_033,
            "cuts": candidate_cuts,
        }
    }
    script_sha = hashlib.sha256(_canonical(script_payload)).hexdigest()
    approval = _approval(
        revision=1,
        script_sha=script_sha,
        timeline_sha=timeline_sha,
        lines=lines,
    )
    return approval, script_payload, timeline_payload


def test_recovery_publishes_final_line_and_performance_contracts_only_after_confirmed_approval():
    approval, script_payload, timeline_payload = _recovery_fixture()
    context = _Context(
        approval=approval,
        script_payload=script_payload,
        timeline_payload=timeline_payload,
    )

    result = performance_audio_contracts.recover_confirmed_script_contracts(context)

    assert [artifact["kind"] for artifact, _raw in context.published] == [
        "exact_line_contract",
        "performance_line_contract",
    ]
    assert result["performance_line_contract"]["source_content_timeline_sha256"] == approval["source_content_timeline_sha256"]
    assert result["performance_line_contract"]["cuts"][0]["speaker_assignment"]["status"] == "CONFIRMED"
    assert result["performance_line_contract"]["cuts"][0]["exact_sung_text"] == approval["line_contracts"][0]["text"]["exact"]


def test_existing_script_stage_recovers_confirmed_contracts_without_rerunning_gpt_or_invocation_a():
    approval, script_payload, timeline_payload = _recovery_fixture()
    context = _Context(
        approval=approval,
        script_payload=script_payload,
        timeline_payload=timeline_payload,
    )
    context.stage = "build_script"
    context.profile_snapshot = {"profile": "high_fidelity_hybrid_v1"}

    class Invocation:
        def invoke_a(self, **_kwargs):
            raise AssertionError("confirmation recovery must not call Invocation A again")

    output = HighFidelityStageAdapter(Invocation()).run_stage(
        context=context,
        handler=lambda **_: (_ for _ in ()).throw(AssertionError("confirmation recovery must not rerun GPT")),
    )

    assert output["performance_line_contract_sha256"] == context.published[-1][0]["sha256"]
    assert [artifact["kind"] for artifact, _raw in context.published] == [
        "exact_line_contract",
        "performance_line_contract",
    ]


def test_recovery_rejects_pending_or_changed_timeline_before_publishing():
    approval, script_payload, timeline_payload = _recovery_fixture()
    pending = deepcopy(approval)
    pending["line_contracts"][0]["speaker_assignment"] = {"status": "PENDING_ASSIGNMENT"}
    pending["line_contracts_sha256"] = hashlib.sha256(_canonical(pending["line_contracts"])).hexdigest()
    pending_context = _Context(
        approval=pending,
        script_payload=script_payload,
        timeline_payload=timeline_payload,
    )
    with pytest.raises(ReplicationError, match="PENDING_ASSIGNMENT"):
        performance_audio_contracts.recover_confirmed_script_contracts(pending_context)
    assert pending_context.published == []

    changed = deepcopy(approval)
    changed["source_content_timeline_sha256"] = "f" * 64
    changed["line_contracts"] = [
        {**line, "source_content_timeline_sha256": "f" * 64}
        for line in changed["line_contracts"]
    ]
    changed["line_contracts_sha256"] = hashlib.sha256(_canonical(changed["line_contracts"])).hexdigest()
    changed_context = _Context(
        approval=changed,
        script_payload=script_payload,
        timeline_payload=timeline_payload,
    )
    changed_context.artifacts = tuple(
        {
            **artifact,
            "sha256": approval["source_content_timeline_sha256"],
        }
        if artifact["kind"] == "source_content_timeline"
        else artifact
        for artifact in changed_context.artifacts
    )
    with pytest.raises(ReplicationError, match="timeline SHA"):
        performance_audio_contracts.recover_confirmed_script_contracts(changed_context)
    assert changed_context.published == []


def test_recovery_rejects_a_pending_lyric_candidate_before_publishing():
    approval, script_payload, timeline_payload = _recovery_fixture()
    script_payload["performance_line_candidates"]["cuts"][0]["lyric_status"] = "PENDING_CONFIRMATION"
    approval["script_sha256"] = hashlib.sha256(_canonical(script_payload)).hexdigest()
    context = _Context(
        approval=approval,
        script_payload=script_payload,
        timeline_payload=timeline_payload,
    )

    with pytest.raises(ReplicationError, match="lyric_status"):
        performance_audio_contracts.recover_confirmed_script_contracts(context)

    assert context.published == []


def test_recovery_rejects_a_cross_segment_local_time_candidate_before_publishing():
    approval, script_payload, timeline_payload = _recovery_fixture()
    script_payload["performance_line_candidates"]["cuts"][0]["segment_time"] = {
        "start_ms": 0,
        "end_ms": 4_001,
    }
    approval["script_sha256"] = hashlib.sha256(_canonical(script_payload)).hexdigest()
    context = _Context(
        approval=approval,
        script_payload=script_payload,
        timeline_payload=timeline_payload,
    )

    with pytest.raises(ReplicationError, match="segment-time"):
        performance_audio_contracts.recover_confirmed_script_contracts(context)

    assert context.published == []


def test_recovery_rejects_a_performance_mode_that_differs_from_confirmed_content_type():
    approval, script_payload, timeline_payload = _recovery_fixture()
    script_payload["performance_line_candidates"]["cuts"][0]["performance_mode"] = "spoken"
    approval["script_sha256"] = hashlib.sha256(_canonical(script_payload)).hexdigest()
    context = _Context(
        approval=approval,
        script_payload=script_payload,
        timeline_payload=timeline_payload,
    )

    with pytest.raises(ReplicationError, match="performance_mode must match content_type"):
        performance_audio_contracts.recover_confirmed_script_contracts(context)

    assert context.published == []
