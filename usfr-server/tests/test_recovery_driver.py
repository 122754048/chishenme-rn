from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import fakeredis

from server.ephemeral_worker import EphemeralWorkerManager
from server.errors import ReplicationError
from server.job_models import WorkMessage
from server.object_store import S3ObjectStore, TemporaryMediaStore
from server.redis_job_store import RedisEphemeralJobStore

from test_object_lifecycle import MemoryS3


class FailingStage:
    def run(self, *, context, input_artifacts):
        raise ReplicationError(
            "UNSUPPORTED_TRANSITION",
            "standard compositor cannot reproduce the transition",
            category="fidelity",
            details={"intervals": [{"start_ms": 100, "end_ms": 500}]},
        )


class Bridge:
    def __init__(self, ref):
        self.ref = ref
        self.calls = []

    def recover_stage_failure(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            artifact_ref=self.ref.to_dict(),
            job_version=kwargs["expected_version"] + 4,
            checkpoint_sha256="f" * 64,
        )


def test_recoverable_stage_failure_reinserts_same_stage_artifact_without_new_stage() -> None:
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = RedisEphemeralJobStore(redis, prefix="recovery-driver")
    object_store = S3ObjectStore(MemoryS3(), bucket="test")
    temporary = TemporaryMediaStore(object_store)
    job = store.create_job(
        slots_manifest={
            "output_language": "zh",
            "extensions": {
                "recovery_goal": {
                    "source_fidelity": {"sha256": "1" * 64},
                    "approved_script_sha256": "2" * 64,
                    "approved_storyboard_sha256": "3" * 64,
                    "character_lock": {"sha256": "4" * 64},
                    "product_lock": {"sha256": "5" * 64},
                    "routes": {"ui": "opaque", "tail": "omit"},
                    "timing": {"segment_plan_sha256": "6" * 64},
                    "audio": {"language": "zh"},
                    "hard_gates": ["timeline_100"],
                }
            },
        },
        capability_token_hash="a" * 64,
        ttl_seconds=3600,
    )
    raw = temporary.put_bytes(
        job_id=job.job_id,
        logical_path="recovery/recovered.mp4",
        data=b"video",
        content_type="video/mp4",
    )
    recovered = replace(raw, artifact_id="recovered", kind="assembled_video")
    bridge = Bridge(recovered)
    manager = EphemeralWorkerManager(
        job_store=store,
        temporary_store=temporary,
        stage_ports={"splice_timeline": FailingStage()},
        profile_bundle_resolver=SimpleNamespace(immutable=True),
        capability_ports={},
        recovery_bridge=bridge,
    )
    checkpoint = store.claim_stage(
        job_id=job.job_id,
        stage="splice_timeline",
        dedupe_key="d1",
        owner="worker-1",
        ttl_seconds=60,
    )
    result = manager.process_work_message(
        message=WorkMessage(job.job_id, "splice_timeline", job.version, "d1"),
        checkpoint=checkpoint,
        owner="worker-1",
    )
    assert result["output_artifact_ids"] == ("recovered",)
    assert bridge.calls[0]["stage"] == "splice_timeline"
    assert store.get_artifact(job.job_id, "recovered") == recovered
