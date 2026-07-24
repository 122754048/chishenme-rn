from pathlib import Path
import sys

import pytest

from app.batch_manifest import BatchRow
from app.replication_runtime import (
    build_standard_commercial_batch_runtime,
    CommercialBatchRuntimeError,
    RedisBatchStateStore,
    StandardUsfrBatchJobCreator,
)


SKILL_ROOT = Path(__file__).resolve().parents[2] / "usfr-server"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from server.intake import bind_uploaded_slots  # noqa: E402


class _ObjectStore:
    def __init__(self, objects):
        self.objects = objects

    def head(self, object_key):
        return self.objects[object_key]


class _Snapshot:
    def __init__(self, job_id, version=1, state="ANALYZING"):
        self.job_id = job_id
        self.version = version
        self.state = state
        self.final_ref = None
        self.review_route = None


class _JobStore:
    def __init__(self):
        self.created = []
        self.transitions = []

    def create_job(self, **kwargs):
        self.created.append(kwargs)
        return _Snapshot("standard-job")

    def cas_transition(self, **kwargs):
        self.transitions.append(kwargs)
        return _Snapshot(kwargs["job_id"], version=2)

    def get_job(self, job_id):
        return _Snapshot(job_id, version=2)


class _StageDriver:
    def __init__(self):
        self.started = []

    def enqueue_next(self, job_id):
        self.started.append(job_id)


class _MusicStageDriver(_StageDriver):
    background_music_execution_contract = "background_music_execution/v1"


class _BackgroundMusicExecutionAdapter:
    def __init__(self):
        self.startup_validated = False
        self.validated_music = []

    def validate_startup(self):
        self.startup_validated = True

    def validate_manifest(self, *, background_music):
        self.validated_music.append(dict(background_music))


class _Redis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.expirations[key] = ex

    def get(self, key):
        return self.values.get(key)


class _CapabilityQueue:
    def __init__(self):
        self.messages = []
        self.limit = None

    def enqueue(self, message):
        self.messages.append(message)

    def set_concurrency_limit(self, limit):
        self.limit = limit


def _completion(object_key, sha256, content_type, duration):
    return {
        "object_key": object_key,
        "sha256": sha256,
        "size_bytes": 128,
        "content_type": content_type,
        "duration_seconds": duration,
        "status": "completed",
    }


def test_standard_creator_binds_completed_uploads_and_starts_the_canonical_job():
    source = _completion("uploads/batch-scope/source.mp4", "a" * 64, "video/mp4", 12.0)
    product = _completion("uploads/batch-scope/product.png", "b" * 64, "image/png", 0.0)
    store = _ObjectStore({source["object_key"]: source, product["object_key"]: product})
    job_store = _JobStore()
    stage_driver = _StageDriver()
    creator = StandardUsfrBatchJobCreator(
        job_store=job_store,
        object_store=store,
        stage_driver=stage_driver,
        capability_secret=b"x" * 32,
        upload_scope="batch-scope",
        ttl_seconds=3600,
        bind_slots=bind_uploaded_slots,
        issue_capability=lambda _: ("token", "c" * 64),
    )

    job_id = creator(
        BatchRow(
            row_id="product-row",
            slots={"source_video": source, "new_product_image": product},
            extensions={"background_music": None},
            output_language=None,
            opaque_audio_policy={},
        )
    )

    assert job_id == "standard-job"
    manifest = job_store.created[0]["slots_manifest"]
    assert manifest["admission"]["language_only"] is False
    assert manifest["review_route"] is None
    assert "background_music" not in manifest.get("extensions", {})
    assert job_store.transitions == [
        {
            "job_id": "standard-job",
            "expected_version": 1,
            "command": "start",
            "updates": {"state": "ANALYZING"},
            "ttl_seconds": 3600,
        }
    ]
    assert stage_driver.started == ["standard-job"]


def test_standard_creator_rejects_a_music_adapter_when_the_stage_driver_cannot_execute_the_music_contract():
    with pytest.raises(CommercialBatchRuntimeError, match="BACKGROUND_MUSIC_EXECUTION_ADAPTER_INVALID"):
        StandardUsfrBatchJobCreator(
            job_store=_JobStore(),
            object_store=_ObjectStore({}),
            stage_driver=_StageDriver(),
            capability_secret=b"x" * 32,
            upload_scope="batch-scope",
            ttl_seconds=3600,
            bind_slots=bind_uploaded_slots,
            issue_capability=lambda _: ("token", "c" * 64),
            background_music_execution_adapter=_BackgroundMusicExecutionAdapter(),
        )


def test_standard_creator_fails_closed_for_background_music_until_the_stage_driver_can_execute_the_music_contract():
    source = _completion("uploads/batch-scope/source.mp4", "a" * 64, "video/mp4", 12.0)
    music = _completion("uploads/batch-scope/song.mp3", "b" * 64, "audio/mpeg", 30.0)
    job_store = _JobStore()
    stage_driver = _MusicStageDriver()
    creator = StandardUsfrBatchJobCreator(
        job_store=job_store,
        object_store=_ObjectStore({source["object_key"]: source, music["object_key"]: music}),
        stage_driver=stage_driver,
        capability_secret=b"x" * 32,
        upload_scope="batch-scope",
        ttl_seconds=3600,
        bind_slots=bind_uploaded_slots,
        issue_capability=lambda _: ("token", "c" * 64),
    )

    with pytest.raises(CommercialBatchRuntimeError, match="BACKGROUND_MUSIC_EXECUTION_ADAPTER_REQUIRED"):
        creator(
            BatchRow(
                row_id="music-row",
                slots={"source_video": source},
                extensions={"background_music": music},
                output_language=None,
                opaque_audio_policy={},
            )
        )

    assert job_store.created == []
    assert job_store.transitions == []
    assert stage_driver.started == []


def test_standard_creator_admits_background_music_only_after_the_deployment_adapter_validates_startup_and_manifest():
    source = _completion("uploads/batch-scope/source.mp4", "a" * 64, "video/mp4", 12.0)
    music = _completion("uploads/batch-scope/song.mp3", "b" * 64, "audio/mpeg", 30.0)
    job_store = _JobStore()
    stage_driver = _MusicStageDriver()
    adapter = _BackgroundMusicExecutionAdapter()
    creator = StandardUsfrBatchJobCreator(
        job_store=job_store,
        object_store=_ObjectStore({source["object_key"]: source, music["object_key"]: music}),
        stage_driver=stage_driver,
        capability_secret=b"x" * 32,
        upload_scope="batch-scope",
        ttl_seconds=3600,
        bind_slots=bind_uploaded_slots,
        issue_capability=lambda _: ("token", "c" * 64),
        background_music_execution_adapter=adapter,
    )

    job_id = creator(
        BatchRow(
            row_id="music-row",
            slots={"source_video": source},
            extensions={"background_music": music},
            output_language=None,
            opaque_audio_policy={},
        )
    )

    assert job_id == "standard-job"
    assert adapter.startup_validated is True
    assert adapter.validated_music == [
        {
            **music,
            "provider_route": "seedance_audio_reference",
            "provider_asset_type": "Audio",
            "provider_content_item_type": "audio_url",
            "prompt_reference_tag": "@Audio1",
            "forbidden_provider_field": "reference_audios",
            "final_audio_source": "uploaded_exact_audio",
            "allow_loop_or_time_stretch": False,
        }
    ]
    manifest = job_store.created[0]["slots_manifest"]
    assert manifest["admission"]["language_only"] is False
    assert manifest["extensions"]["background_music"] == adapter.validated_music[0]
    assert stage_driver.started == ["standard-job"]


def test_standard_creator_rejects_unverified_batch_references_before_creating_a_job():
    creator = StandardUsfrBatchJobCreator(
        job_store=_JobStore(),
        object_store=_ObjectStore({}),
        stage_driver=_StageDriver(),
        capability_secret=b"x" * 32,
        upload_scope="batch-scope",
        ttl_seconds=3600,
        bind_slots=bind_uploaded_slots,
        issue_capability=lambda _: ("token", "c" * 64),
    )

    with pytest.raises(CommercialBatchRuntimeError, match="BATCH_UPLOAD_COMPLETION_REQUIRED"):
        creator(
            BatchRow(
                row_id="bare-reference",
                slots={"source_video": "uploads/batch-scope/source.mp4"},
                extensions={"background_music": None},
                output_language="de",
                opaque_audio_policy={},
            )
        )


def test_redis_batch_state_store_persists_row_recovery_metadata_without_a_file_store():
    store = RedisBatchStateStore(_Redis(), prefix="commercial-test")
    batch_id = store.create_batch(
        [
            {
                "row_id": "row-1",
                "job_id": "standard-job",
                "status": "provider_running",
                "provider_task_id": "provider-known-task",
                "result": {"final_ref": None},
                "timing_ledger": {"provider_wait_ms": 1200},
            }
        ]
    )

    store.replace_rows(
        batch_id,
        [
            {
                "row_id": "row-1",
                "job_id": "standard-job",
                "status": "resumed",
                "provider_task_id": "provider-known-task",
                "result": {"final_ref": "final/standard-job/video.mp4"},
                "timing_ledger": {"provider_wait_ms": 1200},
            }
        ],
    )
    recovered = store.get_batch(batch_id)

    assert recovered["batch_id"] == batch_id
    assert recovered["rows"] == [
        {
            "row_id": "row-1",
            "job_id": "standard-job",
            "status": "resumed",
            "provider_task_id": "provider-known-task",
            "result": {"final_ref": "final/standard-job/video.mp4"},
            "timing_ledger": {"provider_wait_ms": 1200},
        }
    ]


def test_redis_batch_state_uses_the_same_24_hour_temporary_retention_window():
    redis = _Redis()
    store = RedisBatchStateStore(redis, prefix="commercial-test", ttl_seconds=86_400)

    batch_id = store.create_batch([{"row_id": "row-1", "status": "queued"}])

    assert redis.expirations[f"commercial-test:commercial-batches:{batch_id}"] == 86_400


def test_standard_runtime_builder_uses_the_durable_creator_state_store_and_capability_limits():
    source = _completion("uploads/batch-scope/source.mp4", "a" * 64, "video/mp4", 12.0)
    store = _ObjectStore({source["object_key"]: source})
    job_store = _JobStore()
    stage_driver = _StageDriver()
    queues = {
        name: _CapabilityQueue()
        for name in (
            "probe_dynamics",
            "asr_localization",
            "storyboard_generation",
            "provider_poll",
            "assembly_qc",
        )
    }
    runtime = build_standard_commercial_batch_runtime(
        job_store=job_store,
        object_store=store,
        stage_driver=stage_driver,
        capability_secret=b"x" * 32,
        upload_scope="batch-scope",
        ttl_seconds=3600,
        redis_client=_Redis(),
        capability_queues=queues,
        environment={
            "USFR_BATCH_CONCURRENCY_PROBE_DYNAMICS": "2",
            "USFR_BATCH_CONCURRENCY_ASR_LOCALIZATION": "3",
            "USFR_BATCH_CONCURRENCY_STORYBOARD_GENERATION": "4",
            "USFR_BATCH_CONCURRENCY_PROVIDER_POLL": "5",
            "USFR_BATCH_CONCURRENCY_ASSEMBLY_QC": "6",
        },
        bind_slots=bind_uploaded_slots,
        issue_capability=lambda _: ("token", "c" * 64),
    )

    submitted = runtime.submit(
        [
            {
                "row_id": "standard-row",
                "slots": {"source_video": source},
                "extensions": {"background_music": None},
                "output_language": "de",
                "opaque_audio_policy": {},
            }
        ]
    )

    assert submitted["rows"] == [
        {
            "row_id": "standard-row",
            "status": "queued",
            "job_id": "standard-job",
            "route": "language_only",
            "required_qa": [
                "source_fidelity_contract",
                "timeline_placement",
                "final_technical",
                "localized_audio",
            ],
        }
    ]
    assert stage_driver.started == ["standard-job"]
    assert {name: queue.limit for name, queue in queues.items()} == {
        "probe_dynamics": 2,
        "asr_localization": 3,
        "storyboard_generation": 4,
        "provider_poll": 5,
        "assembly_qc": 6,
    }


def test_standard_runtime_builder_registers_a_durable_timing_receipt_for_each_created_job():
    source = _completion("uploads/batch-scope/source.mp4", "a" * 64, "video/mp4", 12.0)
    redis = _Redis()
    queues = {
        name: _CapabilityQueue()
        for name in (
            "probe_dynamics",
            "asr_localization",
            "storyboard_generation",
            "provider_poll",
            "assembly_qc",
        )
    }
    runtime = build_standard_commercial_batch_runtime(
        job_store=_JobStore(),
        object_store=_ObjectStore({source["object_key"]: source}),
        stage_driver=_StageDriver(),
        capability_secret=b"x" * 32,
        upload_scope="batch-scope",
        ttl_seconds=3600,
        redis_client=redis,
        capability_queues=queues,
        environment={
            "USFR_BATCH_CONCURRENCY_PROBE_DYNAMICS": "2",
            "USFR_BATCH_CONCURRENCY_ASR_LOCALIZATION": "3",
            "USFR_BATCH_CONCURRENCY_STORYBOARD_GENERATION": "4",
            "USFR_BATCH_CONCURRENCY_PROVIDER_POLL": "5",
            "USFR_BATCH_CONCURRENCY_ASSEMBLY_QC": "6",
        },
        bind_slots=bind_uploaded_slots,
        issue_capability=lambda _: ("token", "c" * 64),
    )

    submitted = runtime.submit(
        [
            {
                "row_id": "timed-row",
                "slots": {"source_video": source},
                "extensions": {"background_music": None},
                "output_language": "de",
                "opaque_audio_policy": {},
            }
        ]
    )
    observed = runtime.get_batch(submitted["batch_id"])

    receipt = observed["rows"][0]["timing_ledger"]
    assert receipt["stages"] == []
    assert receipt["queue_wait_ms"] >= 0
    assert receipt["active_ms"] == 0
