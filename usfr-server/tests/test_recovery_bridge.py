from __future__ import annotations

from server.recovery_bridge import AdaptiveRecoveryBridge
from server.recovery_models import RecoveryCandidate
from server.redis_job_store import RedisEphemeralJobStore

import fakeredis


class Broker:
    def discover(self, *, goal, failure):
        return [{"strategy_id": "s1", "tool_id": "dynamic-tool", "method": "hybrid"}]


class Executor:
    def __init__(self, job_id):
        self.job_id = job_id

    def execute(self, *, strategy, context):
        return RecoveryCandidate(
            candidate_id="candidate-1",
            artifact_ref={
                "artifact_id": "artifact-recovered",
                "kind": "assembled_video",
                "object_key": f"temporary/{self.job_id}/recovery/candidate-1.mp4",
                "sha256": "c" * 64,
            },
            artifact_sha256="c" * 64,
            receipts=(
                {"kind": "request"},
                {"kind": "response"},
                {"kind": "artifact"},
            ),
        )


class Qc:
    def evaluate(self, *, candidate, goal, intervals):
        return {"passed": True, "hard_gates_passed": True, "score": 100}


def _goal():
    return {
        "source_fidelity": {"sha256": "1" * 64},
        "approved_script_sha256": "2" * 64,
        "approved_storyboard_sha256": "3" * 64,
        "character_lock": {"sha256": "4" * 64},
        "product_lock": {"sha256": "5" * 64},
        "routes": {"ui": "opaque", "tail": "omit"},
        "timing": {"segment_plan_sha256": "6" * 64},
        "audio": {"language": "zh"},
        "hard_gates": ["timeline_100", "ocr_100"],
    }


def test_bridge_reinserts_passing_candidate_through_original_artifact_kind() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="bridge-test")
    job = store.create_job(slots_manifest={}, capability_token_hash="a" * 64, ttl_seconds=3600)
    bridge = AdaptiveRecoveryBridge(
        job_store=store,
        broker=Broker(),
        executor=Executor(job.job_id),
        focused_qc=Qc(),
        ttl_seconds=3600,
    )
    result = bridge.recover_stage_failure(
        job_id=job.job_id,
        stage="assembly",
        failure={
            "stage": "assembly",
            "code": "UNSUPPORTED_TRANSITION",
            "intervals": [{"start_ms": 100, "end_ms": 500}],
        },
        expected_version=job.version,
        goal=_goal(),
        artifact_kind="assembled_video",
        unsupported=True,
        hard_failure_signatures=(),
        transient=False,
    )
    assert result is not None
    assert result.artifact_ref["kind"] == "assembled_video"
    assert result.artifact_ref["sha256"] == "c" * 64
    assert result.job_version > job.version
    checkpoint = store.get_recovery_checkpoint(job.job_id)
    assert checkpoint is not None
    assert checkpoint.status.value == "ACHIEVED"


def test_bridge_does_not_enter_for_transient_or_single_hard_failure() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="bridge-skip")
    job = store.create_job(slots_manifest={}, capability_token_hash="a" * 64, ttl_seconds=3600)
    bridge = AdaptiveRecoveryBridge(store, Broker(), Executor(job.job_id), Qc())
    result = bridge.recover_stage_failure(
        job_id=job.job_id,
        stage="assembly",
        failure={"stage": "assembly", "code": "TIMEOUT"},
        expected_version=job.version,
        goal=_goal(),
        artifact_kind="assembled_video",
        unsupported=False,
        hard_failure_signatures=("b" * 64,),
        transient=True,
    )
    assert result is None
    assert store.get_recovery_checkpoint(job.job_id) is None
