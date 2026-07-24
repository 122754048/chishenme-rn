from app.replication_runtime import CommercialBatchRuntime, CommercialBatchRuntimeError
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


class _Queue:
    def __init__(self):
        self.messages = []

    def enqueue(self, message):
        self.messages.append(message)


class _LimitedQueue(_Queue):
    def __init__(self):
        super().__init__()
        self.limit = None

    def set_concurrency_limit(self, limit):
        self.limit = limit


class _StateStore:
    def __init__(self):
        self.batches = {}

    def create_batch(self, rows):
        batch_id = f"batch-{len(self.batches) + 1}"
        self.batches[batch_id] = {"batch_id": batch_id, "rows": rows}
        return batch_id

    def replace_rows(self, batch_id, rows):
        self.batches[batch_id]["rows"] = rows

    def get_batch(self, batch_id):
        return self.batches[batch_id]


class _Snapshot:
    def __init__(self, *, state, final_ref=None, version=3, review_route=None):
        self.state = state
        self.final_ref = final_ref
        self.version = version
        self.review_route = review_route


class _BackgroundMusicExecutionAdapter:
    def __init__(self):
        self.startup_calls = 0

    def validate_startup(self):
        self.startup_calls += 1

    def validate_manifest(self, *, background_music):
        del background_music


def _row(row_id: str) -> dict[str, object]:
    return {
        "row_id": row_id,
        "slots": {"source_video": f"uploads/{row_id}/source.mp4"},
        "extensions": {"background_music": None},
        "output_language": "de",
        "opaque_audio_policy": {},
    }


def test_commercial_batch_runtime_requires_injected_durable_components_and_isolates_rows():
    queues = {name: _Queue() for name in CommercialBatchRuntime.CAPABILITY_QUEUES}
    state_store = _StateStore()
    resumed = []
    runtime = CommercialBatchRuntime(
        create_standard_job=lambda row: f"job-{row.row_id}",
        resume_known_job=resumed.append,
        capability_queues=queues,
        batch_state_store=state_store,
    )

    preflight = runtime.preflight([_row("one"), _row("two")])
    submitted = runtime.submit([_row("one"), _row("two")])
    retried = runtime.retry_row(submitted["batch_id"], "one")

    assert [row["row_id"] for row in preflight] == ["one", "two"]
    assert [row["job_id"] for row in submitted["rows"]] == ["job-one", "job-two"]
    assert retried == {"batch_id": submitted["batch_id"], "row_id": "one", "status": "resumed", "job_id": "job-one"}
    assert resumed == ["job-one"]


def test_commercial_batch_runtime_rejects_missing_capability_queue():
    queues = {name: _Queue() for name in CommercialBatchRuntime.CAPABILITY_QUEUES if name != "assembly_qc"}

    try:
        CommercialBatchRuntime(
            create_standard_job=lambda row: f"job-{row.row_id}",
            resume_known_job=lambda _: None,
            capability_queues=queues,
            batch_state_store=_StateStore(),
        )
    except CommercialBatchRuntimeError as error:
        assert str(error) == "COMMERCIAL_BATCH_CAPABILITY_QUEUE_MISSING"
    else:
        raise AssertionError("expected durable runtime rejection")


def test_commercial_batch_runtime_rejects_background_music_during_preflight_without_creating_a_job():
    queues = {name: _Queue() for name in CommercialBatchRuntime.CAPABILITY_QUEUES}
    created = []
    runtime = CommercialBatchRuntime(
        create_standard_job=lambda row: created.append(row.row_id) or f"job-{row.row_id}",
        resume_known_job=lambda _: None,
        capability_queues=queues,
        batch_state_store=_StateStore(),
    )
    row = _row("music-row")
    row["output_language"] = None
    row["extensions"] = {"background_music": {"object_key": "uploads/music-row/song.mp3"}}

    preflight = runtime.preflight([row])
    submitted = runtime.submit([row])

    assert preflight == [
        {
            "row_id": "music-row",
            "status": "rejected",
            "error": "BACKGROUND_MUSIC_EXECUTION_ADAPTER_REQUIRED",
            "route": "background_music_replace_sing",
            "required_qa": [
                "source_fidelity_contract",
                "timeline_placement",
                "final_technical",
                "music_timeline_contract",
                "uploaded_music_exact_fragment",
                "singing_alignment_or_explicit_no_visible_singer",
                "singing_lip_sync_qa_or_explicit_no_visible_singer",
                "final_mix_receipt",
            ],
        }
    ]
    assert submitted["rows"] == [
        {
            "row_id": "music-row",
            "status": "rejected",
            "route": "background_music_replace_sing",
            "required_qa": preflight[0]["required_qa"],
            "error": "BACKGROUND_MUSIC_EXECUTION_ADAPTER_REQUIRED",
        }
    ]
    assert created == []


def test_commercial_batch_runtime_admits_background_music_only_with_a_validated_execution_adapter():
    queues = {name: _Queue() for name in CommercialBatchRuntime.CAPABILITY_QUEUES}
    created = []
    adapter = _BackgroundMusicExecutionAdapter()
    runtime = CommercialBatchRuntime(
        create_standard_job=lambda row: created.append(row.row_id) or f"job-{row.row_id}",
        resume_known_job=lambda _: None,
        capability_queues=queues,
        batch_state_store=_StateStore(),
        background_music_execution_adapter=adapter,
    )
    row = _row("music-row")
    row["output_language"] = None
    row["extensions"] = {"background_music": {"object_key": "uploads/music-row/song.mp3"}}

    preflight = runtime.preflight([row])
    submitted = runtime.submit([row])

    assert preflight[0]["status"] == "ready"
    assert preflight[0]["route"] == "background_music_replace_sing"
    assert submitted["rows"][0]["status"] == "queued"
    assert submitted["rows"][0]["job_id"] == "job-music-row"
    assert created == ["music-row"]
    assert adapter.startup_calls == 1


def test_commercial_batch_api_is_separate_and_fails_closed_without_injected_runtime():
    from app.replication_runtime import mount_commercial_batch_api

    app = FastAPI()
    mount_commercial_batch_api(app, runtime=None)

    response = TestClient(app).post("/api/v1/commercial-batches", json={"rows": [_row("one")]})

    assert response.status_code == 503
    assert response.json()["code"] == "COMMERCIAL_BATCH_RUNTIME_NOT_CONFIGURED"


def test_commercial_batch_api_rejects_an_untyped_runtime_object_at_startup():
    from app.replication_runtime import mount_commercial_batch_api

    with pytest.raises(CommercialBatchRuntimeError, match="COMMERCIAL_BATCH_RUNTIME_INVALID"):
        mount_commercial_batch_api(FastAPI(), runtime=object())


def test_commercial_batch_runtime_applies_per_capability_environment_concurrency_limits():
    queues = {name: _LimitedQueue() for name in CommercialBatchRuntime.CAPABILITY_QUEUES}
    environment = {
        "USFR_BATCH_CONCURRENCY_PROBE_DYNAMICS": "2",
        "USFR_BATCH_CONCURRENCY_ASR_LOCALIZATION": "3",
        "USFR_BATCH_CONCURRENCY_STORYBOARD_GENERATION": "4",
        "USFR_BATCH_CONCURRENCY_PROVIDER_POLL": "5",
        "USFR_BATCH_CONCURRENCY_ASSEMBLY_QC": "6",
    }

    CommercialBatchRuntime.from_environment(
        create_standard_job=lambda row: f"job-{row.row_id}",
        resume_known_job=lambda _: None,
        capability_queues=queues,
        batch_state_store=_StateStore(),
        environment=environment,
    )

    assert {name: queue.limit for name, queue in queues.items()} == {
        "probe_dynamics": 2,
        "asr_localization": 3,
        "storyboard_generation": 4,
        "provider_poll": 5,
        "assembly_qc": 6,
    }


def test_commercial_batch_reads_current_standard_job_snapshot_and_persists_delivery_projection():
    queues = {name: _Queue() for name in CommercialBatchRuntime.CAPABILITY_QUEUES}
    state_store = _StateStore()
    snapshot = _Snapshot(
        state="SUCCEEDED",
        final_ref={
            "object_key": "final/job-one/result.mp4",
            "sha256": "a" * 64,
            "content_type": "video/mp4",
            "size_bytes": 128,
        },
    )
    runtime = CommercialBatchRuntime(
        create_standard_job=lambda row: f"job-{row.row_id}",
        resume_known_job=lambda _: None,
        capability_queues=queues,
        batch_state_store=state_store,
        snapshot_for_job=lambda job_id: snapshot if job_id == "job-one" else None,
    )

    submitted = runtime.submit([_row("one")])
    observed = runtime.get_batch(submitted["batch_id"])
    index = runtime.result_index(submitted["batch_id"])

    expected_result = {
        "object_key": "final/job-one/result.mp4",
        "sha256": "a" * 64,
        "content_type": "video/mp4",
        "size_bytes": 128,
    }
    assert observed["rows"][0]["status"] == "succeeded"
    assert observed["rows"][0]["result"] == expected_result
    assert observed["rows"][0]["job_version"] == 3
    assert index["items"] == [
        {"row_id": "one", "job_id": "job-one", "status": "succeeded", "result": expected_result}
    ]
    assert state_store.get_batch(submitted["batch_id"])["rows"][0]["status"] == "succeeded"


def test_commercial_batch_persists_the_durable_standard_job_timing_receipt():
    queues = {name: _Queue() for name in CommercialBatchRuntime.CAPABILITY_QUEUES}
    timing_receipt = {
        "queue_wait_ms": 1200,
        "active_ms": 3400,
        "provider_wait_ms": 5600,
        "approval_wait_ms": 7800,
        "retry_count": 1,
        "cache_hit": False,
        "stages": [],
    }
    runtime = CommercialBatchRuntime(
        create_standard_job=lambda row: f"job-{row.row_id}",
        resume_known_job=lambda _: None,
        capability_queues=queues,
        batch_state_store=_StateStore(),
        snapshot_for_job=lambda job_id: _Snapshot(state="ANALYZING") if job_id == "job-one" else None,
        timing_for_job=lambda job_id: timing_receipt if job_id == "job-one" else None,
    )

    submitted = runtime.submit([_row("one")])
    observed = runtime.get_batch(submitted["batch_id"])

    assert observed["rows"][0]["timing_ledger"] == timing_receipt
