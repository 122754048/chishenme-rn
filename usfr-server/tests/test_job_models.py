from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from server.job_models import (
    ArtifactRef,
    JobSnapshot,
    ProviderAttempt,
    StageCheckpoint,
    WorkMessage,
)
from server.job_store import EphemeralJobStore


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _json_value(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _representative_payloads() -> dict[str, dict[str, Any]]:
    snapshot = JobSnapshot.new(
        job_id="job-1",
        capability_token_hash="a" * 64,
        slots_manifest={"admission": {"can_proceed": True}},
        expires_at_ms=1_900_000_000_000,
    )
    attempt = ProviderAttempt.new(
        attempt_id="attempt-1",
        operation="CreateVideo",
        request_sha256="b" * 64,
        segment_id="segment-01",
        segment_plan_sha256="c" * 64,
    )
    message = WorkMessage(
        job_id="job-1",
        stage="analyze_dynamics",
        expected_version=3,
        dedupe_key="d" * 64,
    )
    return {
        "job.schema.json": _json_value(snapshot.to_dict()),
        "provider_attempt.schema.json": _json_value(attempt.to_dict()),
        "queue_message.schema.json": _json_value(message.to_dict()),
    }


def test_job_snapshot_has_no_product_identity_fields():
    snapshot = JobSnapshot.new(
        job_id="job-1",
        capability_token_hash="a" * 64,
        slots_manifest={"admission": {"can_proceed": True}},
        expires_at_ms=1_900_000_000_000,
    )
    payload = snapshot.to_dict()
    assert payload["version"] == 1
    assert "tenant_id" not in payload
    assert "actor" not in payload
    assert "user_id" not in payload


def test_job_snapshot_new_sets_initial_state_and_copies_slots_manifest():
    slots_manifest = {"admission": {"can_proceed": True}}

    snapshot = JobSnapshot.new(
        job_id="job-1",
        capability_token_hash="a" * 64,
        slots_manifest=slots_manifest,
        expires_at_ms=1_900_000_000_000,
    )
    slots_manifest["late_mutation"] = {"accepted": False}

    assert snapshot.state == "INTAKE_VALIDATED"
    assert snapshot.version == 1
    assert snapshot.capability_token_version == 1
    assert "late_mutation" not in snapshot.slots_manifest


def test_job_snapshot_round_trip_restores_invalidated_as_tuple():
    snapshot = JobSnapshot.new(
        job_id="job-1",
        capability_token_hash="a" * 64,
        slots_manifest={"admission": {"can_proceed": True}},
        expires_at_ms=1_900_000_000_000,
    )
    payload = snapshot.to_dict()
    payload["invalidated"] = ["storyboard", "prompt"]

    restored = JobSnapshot.from_dict(payload)

    assert restored.invalidated == ("storyboard", "prompt")
    assert restored.to_dict()["invalidated"] == ("storyboard", "prompt")


def test_artifact_ref_serializes_all_contract_fields():
    artifact = ArtifactRef(
        artifact_id="artifact-1",
        kind="segment_video",
        object_key="jobs/job-1/segment-01.mp4",
        sha256="a" * 64,
        content_type="video/mp4",
        size_bytes=1234,
        revision=2,
        segment_id="segment-01",
        segment_plan_sha256="b" * 64,
    )

    assert artifact.to_dict() == {
        "artifact_id": "artifact-1",
        "kind": "segment_video",
        "object_key": "jobs/job-1/segment-01.mp4",
        "sha256": "a" * 64,
        "content_type": "video/mp4",
        "size_bytes": 1234,
        "revision": 2,
        "segment_id": "segment-01",
        "segment_plan_sha256": "b" * 64,
    }


def test_provider_attempt_round_trip_keeps_segment_identity():
    attempt = ProviderAttempt.new(
        attempt_id="attempt-1",
        operation="CreateVideo",
        request_sha256="b" * 64,
        segment_id="segment-01",
        segment_plan_sha256="c" * 64,
    )

    assert attempt.status == "PREPARED"
    assert ProviderAttempt.from_dict(attempt.to_dict()) == attempt


def test_provider_attempt_round_trip_preserves_restart_sensitive_states():
    for status in ("SUBMITTING", "AMBIGUOUS"):
        attempt = ProviderAttempt(
            attempt_id="attempt-1",
            operation="CreateAsset",
            request_sha256="b" * 64,
            status=status,
            segment_id=None,
            segment_plan_sha256=None,
        )

        assert ProviderAttempt.from_dict(attempt.to_dict()) == attempt


def test_stage_checkpoint_defaults_to_no_outputs_or_owner():
    checkpoint = StageCheckpoint(
        stage="analyze_dynamics",
        dedupe_key="d" * 64,
        status="CLAIMED",
        attempt=1,
    )

    assert checkpoint.output_artifact_ids == ()
    assert checkpoint.owner is None


def test_work_message_is_job_and_stage_scoped():
    message = WorkMessage(
        job_id="job-1",
        stage="analyze_dynamics",
        expected_version=3,
        dedupe_key="d" * 64,
    )
    assert message.to_dict() == {
        "job_id": "job-1",
        "stage": "analyze_dynamics",
        "expected_version": 3,
        "dedupe_key": "d" * 64,
    }


def test_ephemeral_job_store_exposes_only_the_required_public_methods():
    public_methods = {
        name
        for name, value in EphemeralJobStore.__dict__.items()
        if callable(value) and not name.startswith("_")
    }

    assert public_methods == {
        "create_job",
        "get_job",
        "cas_transition",
        "append_revision",
        "approve_revision",
        "get_script_approval",
        "list_revisions",
        "get_current_revision",
        "touch_review_ttl",
        "get_recovery_checkpoint",
        "put_recovery_checkpoint",
        "clear_recovery_checkpoint",
        "put_artifact",
        "get_artifact",
        "list_artifacts",
        "get_stage_checkpoint",
        "begin_provider_attempt",
        "list_provider_attempts",
        "update_provider_attempt",
        "claim_stage",
        "complete_stage",
    }


def test_unimplemented_ephemeral_job_store_methods_fail_loudly():
    class BareJobStore(EphemeralJobStore):
        pass

    store = BareJobStore()
    attempt = ProviderAttempt.new(
        attempt_id="attempt-1",
        operation="CreateVideo",
        request_sha256="b" * 64,
    )
    operations = (
        lambda: store.create_job(
            slots_manifest={},
            capability_token_hash="a" * 64,
            ttl_seconds=60,
        ),
        lambda: store.get_job("job-1"),
        lambda: store.cas_transition(
            job_id="job-1",
            expected_version=1,
            command="start_analysis",
        ),
        lambda: store.append_revision(
            job_id="job-1",
            kind="script",
            expected_version=1,
            manifest={},
            invalidate_downstream=True,
            ttl_seconds=60,
        ),
        lambda: store.approve_revision(
            job_id="job-1",
            kind="script",
            revision=1,
            expected_version=1,
            expected_sha256="a" * 64,
            ttl_seconds=60,
        ),
        lambda: store.list_revisions("job-1", "script"),
        lambda: store.get_current_revision("job-1", "script"),
        lambda: store.touch_review_ttl("job-1", 60),
        lambda: store.begin_provider_attempt(
            job_id="job-1",
            expected_version=1,
            operation="CreateVideo",
            request_sha256="b" * 64,
        ),
        lambda: store.list_provider_attempts("job-1"),
        lambda: store.update_provider_attempt(
            job_id="job-1",
            expected_version=1,
            attempt=attempt,
            ttl_seconds=60,
        ),
        lambda: store.claim_stage(
            job_id="job-1",
            stage="analyze_dynamics",
            dedupe_key="d" * 64,
            owner="worker-1",
            ttl_seconds=60,
        ),
        lambda: store.complete_stage(
            job_id="job-1",
            stage="analyze_dynamics",
            dedupe_key="d" * 64,
            owner="worker-1",
            output_artifact_ids=(),
            ttl_seconds=60,
        ),
    )

    for operation in operations:
        with pytest.raises(NotImplementedError):
            operation()


@pytest.mark.parametrize(
    "schema_name",
    (
        "job.schema.json",
        "provider_attempt.schema.json",
        "queue_message.schema.json",
    ),
)
def test_job_contract_schemas_are_valid_draft_2020_12(schema_name: str):
    Draft202012Validator.check_schema(_load_schema(schema_name))


@pytest.mark.parametrize(
    ("schema_name", "payload"),
    tuple(_representative_payloads().items()),
)
def test_job_contract_schemas_accept_representative_payloads(
    schema_name: str,
    payload: dict[str, Any],
):
    Draft202012Validator(_load_schema(schema_name)).validate(payload)


@pytest.mark.parametrize(
    ("schema_name", "payload"),
    tuple(_representative_payloads().items()),
)
def test_job_contract_schemas_reject_additional_properties(
    schema_name: str,
    payload: dict[str, Any],
):
    payload["tenant_id"] = "tenant-1"

    with pytest.raises(ValidationError):
        Draft202012Validator(_load_schema(schema_name)).validate(payload)


@pytest.mark.parametrize(
    ("schema_name", "payload", "required_field"),
    (
        (
            "job.schema.json",
            _representative_payloads()["job.schema.json"],
            "capability_token_hash",
        ),
        (
            "provider_attempt.schema.json",
            _representative_payloads()["provider_attempt.schema.json"],
            "status",
        ),
        (
            "queue_message.schema.json",
            _representative_payloads()["queue_message.schema.json"],
            "expected_version",
        ),
    ),
)
def test_job_contract_schemas_require_contract_fields(
    schema_name: str,
    payload: dict[str, Any],
    required_field: str,
):
    payload.pop(required_field)

    with pytest.raises(ValidationError):
        Draft202012Validator(_load_schema(schema_name)).validate(payload)


@pytest.mark.parametrize(
    ("schema_name", "field", "invalid_value"),
    (
        ("job.schema.json", "capability_token_hash", "not-a-sha256"),
        ("provider_attempt.schema.json", "request_sha256", "A" * 64),
        ("provider_attempt.schema.json", "operation", "DeleteVideo"),
        ("provider_attempt.schema.json", "status", "SUBMITTED"),
        ("queue_message.schema.json", "dedupe_key", "short"),
    ),
)
def test_job_contract_schemas_enforce_hashes_and_enums(
    schema_name: str,
    field: str,
    invalid_value: str,
):
    payload = _representative_payloads()[schema_name]
    payload[field] = invalid_value

    with pytest.raises(ValidationError):
        Draft202012Validator(_load_schema(schema_name)).validate(payload)
