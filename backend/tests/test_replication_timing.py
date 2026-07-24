from app.services.replication_timing import (
    RedisTimingLedgerStore,
    TimedStageDriver,
    TimedStagePort,
    TimingLedger,
)


class _Clock:
    def __init__(self, *values: float):
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class _Redis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.expirations[key] = ex


def test_timing_ledger_separates_queue_active_provider_and_skipped_work():
    ledger = TimingLedger(now=_Clock(0.0, 2.0, 3.0, 4.0, 8.0, 10.0, 16.0))

    ledger.start_stage("app_evidence")
    ledger.end_stage("app_evidence", status="skipped", skipped_reason="opaque_ui_only")
    ledger.start_stage("dynamics")
    ledger.end_stage("dynamics", status="succeeded")
    ledger.start_stage("seedance_provider", provider=True)
    ledger.end_stage("seedance_provider", status="succeeded")

    snapshot = ledger.snapshot()

    assert snapshot["queue_wait_ms"] == 5000
    assert snapshot["active_ms"] == 11000
    assert snapshot["provider_wait_ms"] == 6000
    assert snapshot["retry_count"] == 0
    assert snapshot["cache_hit"] is False
    assert snapshot["stages"][0]["skipped_reason"] == "opaque_ui_only"
    assert snapshot["stages"][0]["started_at"] == 2.0
    assert snapshot["stages"][0]["ended_at"] == 3.0


def test_timing_ledger_keeps_approval_wait_out_of_active_time_and_counts_retries():
    ledger = TimingLedger(now=_Clock(0.0, 1.0, 4.0, 6.0, 7.0, 10.0, 12.0))

    ledger.start_stage("analyze_dynamics")
    ledger.end_stage("analyze_dynamics", status="failed")
    ledger.start_stage("analyze_dynamics")
    ledger.end_stage("analyze_dynamics", status="succeeded")
    ledger.start_stage("script_approval", approval=True)
    ledger.end_stage("script_approval", status="succeeded")

    snapshot = ledger.snapshot()

    assert snapshot["active_ms"] == 4000
    assert snapshot["approval_wait_ms"] == 2000
    assert snapshot["retry_count"] == 1
    assert snapshot["stages"][2]["approval"] is True


def test_redis_timing_ledger_store_keeps_one_job_ledger_durable_between_processes():
    redis = _Redis()
    writer = RedisTimingLedgerStore(redis, prefix="usfr:test:timing", now=_Clock(0.0, 2.0, 5.0))

    writer.create("music-job")
    writer.start_stage("music-job", "analyze_dynamics")
    writer.end_stage("music-job", "analyze_dynamics", status="succeeded")

    reader = RedisTimingLedgerStore(redis, prefix="usfr:test:timing")

    assert reader.snapshot("music-job") == {
        "created_at": 0.0,
        "queue_wait_ms": 2000,
        "active_ms": 3000,
        "provider_wait_ms": 0,
        "approval_wait_ms": 0,
        "retry_count": 0,
        "cache_hit": False,
        "stages": [
            {
                "name": "analyze_dynamics",
                "provider": False,
                "approval": False,
                "started_at": 2.0,
                "ended_at": 5.0,
                "status": "succeeded",
                "skipped_reason": None,
                "retry_count": 0,
                "cache_hit": False,
            }
        ],
    }


def test_redis_timing_ledger_uses_a_job_scoped_24_hour_temporary_key():
    redis = _Redis()
    store = RedisTimingLedgerStore(
        redis,
        prefix="usfr:test",
        ttl_seconds=86_400,
        job_scoped_keys=True,
    )

    store.create("music-job")

    assert "usfr:test:music-job:timing" in redis.values
    assert redis.expirations["usfr:test:music-job:timing"] == 86_400


def test_timed_stage_port_records_a_real_provider_wait_against_the_registered_job_ledger():
    class _Port:
        def run(self, *, context, input_artifacts):
            assert context.job_id == "music-job"
            assert input_artifacts == []
            return {"provider_task_id": "known-task"}

    context = type("Context", (), {"job_id": "music-job"})()
    store = RedisTimingLedgerStore(_Redis(), prefix="usfr:test:timing", now=_Clock(0.0, 2.0, 5.0))
    store.create("music-job")
    port = TimedStagePort(stage="wait_provider_video", delegate=_Port(), timing_ledger_store=store)

    assert port.run(context=context, input_artifacts=[]) == {"provider_task_id": "known-task"}

    receipt = store.snapshot("music-job")
    assert receipt["active_ms"] == 3000
    assert receipt["provider_wait_ms"] == 3000
    assert receipt["stages"][0]["name"] == "wait_provider_video"
    assert receipt["stages"][0]["provider"] is True


def test_timed_stage_driver_records_only_the_existing_script_approval_wait():
    class _Snapshot:
        review_route = None
        current_script_revision = 1
        approved_script_sha256 = None
        current_storyboard_revision = None
        approved_storyboard_sha256 = None

    class _JobStore:
        def __init__(self):
            self.snapshot = _Snapshot()

        def get_job(self, job_id):
            assert job_id == "music-job"
            return self.snapshot

    class _Driver:
        def __init__(self):
            self.calls = []

        def enqueue_next(self, job_id):
            self.calls.append(job_id)
            return None

    store = RedisTimingLedgerStore(_Redis(), prefix="usfr:test:timing", now=_Clock(0.0, 2.0, 5.0))
    store.create("music-job")
    job_store = _JobStore()
    delegate = _Driver()
    driver = TimedStageDriver(delegate=delegate, job_store=job_store, timing_ledger_store=store)

    driver.enqueue_next("music-job")
    job_store.snapshot.approved_script_sha256 = "a" * 64
    driver.enqueue_next("music-job")

    receipt = store.snapshot("music-job")
    assert receipt["active_ms"] == 0
    assert receipt["approval_wait_ms"] == 3000
    assert receipt["stages"][0]["name"] == "script_approval"
    assert receipt["stages"][0]["approval"] is True
    assert delegate.calls == ["music-job", "music-job"]
