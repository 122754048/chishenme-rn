# USFR Provider-Aware Batch Throughput Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize completed, QC-passed USFR MP4s per wall-clock hour for concurrent batches without weakening source fidelity, approval gates, or paid-Provider idempotency.

**Architecture:** Keep the existing twelve-stage USFR workflow and five routed worker queues, but add a control plane around them. A temporary, receipt-backed ledger first reveals where time is spent; a Provider-aware capacity controller, weighted-fair ready dispatcher, and centralized due-time poll coordinator then decide *when* existing work may proceed. Exact-fingerprint reuse is deliberately limited to safe temporary artifacts and documented Provider asset mappings, never source semantic analysis or completed media.

**Tech Stack:** Python 3, pytest, Redis Streams/ZSET/Hash, existing `CapabilityRoutedWorkQueue`, `RedisWorkQueue`, `RedisTimingLedgerStore`, RunningHub, Youdao Seedance 2.0, FFmpeg.

## Global Constraints

- Do not change the USFR semantic contract: seven fixed slots, twelve semantic stages, exactly two user approvals, mandatory source analysis and final QC, and at most two Seedance-generated segments.
- `source_video` remains the sole source fact. Its deep semantic analysis remains job-scoped and is never shared between jobs, even for identical SHA-256 values.
- Opaque UI operation media and tail media must never enter Provider semantic analysis.
- `background_music` remains an optional extension, not an eighth slot: Youdao `AssetType=Audio`, `content.audio_url` plus `role=reference_audio`, prompt `@Audio1`, and no top-level `reference_audios`.
- Language-only localization keeps the selected lip-sync Provider MP4 as final media. Do not add an Audio1 remux/replacement path, a 125 ms source-window condition, or a 40% A/V duration-ratio blocker. Independent TTS stays capped at six concurrent items.
- No `CreateAsset` or `CreateVideo` may be automatically retried after 429, overload, 5xx, timeout, reset, or any ambiguous response. Reconcile a known task/intent only; otherwise stop with a receipt.
- Do not introduce accounts, billing, user history, media-library retention, or a product analytics system. Operational receipts, queue records, and caches use the current job/batch TTL; only `final/{job_id}/result.mp4` remains durable after success.
- The success metric is `finalized_qc_passed_mp4s_per_hour`; the existing 30-minute target remains measurement only and must never cancel a valid Provider wait.
- Every new control is feature-flagged and defaults to the current static behavior until its deterministic load suite and a controlled deployment prove it safe.

## Current Bottlenecks and Decisions

1. Static limits exist only for `probe_dynamics`, `asr_localization`, `storyboard_generation`, `provider_poll`, and `assembly_qc`. They cannot distinguish a RunningHub storyboard create from a Youdao video create, so raising a broad limit risks unnecessary 429s.
2. Existing timing receipts expose per-job active/provider time and queue wait, but do not expose Provider saturation, rate-limit events, p50/p95 by operation, fairness, cache effectiveness, or delivered MP4s/hour.
3. Each Provider wait can consume a worker loop. `RedisWorkQueue.schedule()` and `promote_due()` already provide a safe due-time primitive; the plan uses it for shared polling rather than adding a second queue product.
4. The current source-analysis claim test explicitly guarantees that analysis is not shared across jobs. Cache work therefore targets only byte-identical upload validation and documented, reusable Provider asset registrations with exact contracts.

## File Map

- Create: `backend/app/services/batch_throughput.py` - TTL-scoped operational event ledger and aggregate snapshot.
- Create: `backend/app/services/provider_capacity.py` - deterministic Provider capability classification and additive-increase/multiplicative-decrease capacity policy.
- Create: `backend/app/services/fair_dispatch.py` - weighted-fair ready-work ordering without changing `WorkMessage` fields.
- Create: `backend/app/services/temporary_artifact_reuse.py` - exact-fingerprint, TTL-scoped safe reuse store.
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/provider_polling.py` - known-task-only due-time polling coordinator.
- Create: `backend/tests/test_batch_throughput.py`, `backend/tests/test_provider_capacity.py`, `backend/tests/test_fair_dispatch.py`, `backend/tests/test_temporary_artifact_reuse.py`.
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_polling.py` and `tests/test_provider_aware_batch_load.py`.
- Modify: `backend/app/services/replication_timing.py`, `backend/app/capability_work_queue.py`, `backend/app/replication_runtime.py`, `backend/app/usfr_commercial_deployment.py`.
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/telemetry.py`, `server/production_ports.py`, `server/ephemeral_worker.py`, `server/redis_streams.py`, and the corresponding production/queue tests.
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md` only to document runtime controls and receipts. Do not alter routing, input, media, or approval semantics.

---

### Task 1: Establish a Backward-Compatible Throughput Ledger and Baseline

**Files:**
- Create: `backend/app/services/batch_throughput.py`
- Create: `backend/tests/test_batch_throughput.py`
- Modify: `backend/app/replication_runtime.py`
- Modify: `backend/tests/test_standard_usfr_batch_runtime.py`

**Interfaces:**
- Consumes: `job_id`, optional `batch_id`, stage/capability names, timestamps, non-sensitive Provider outcome class, cache decision, and final QC result.
- Produces: `RedisBatchThroughputStore.record(event: BatchThroughputEvent) -> None` and `snapshot(batch_id: str) -> dict[str, object]`.
- Invariant: the existing `TimingLedger` JSON shape stays readable. The new ledger is a separate TTL key and can be absent from legacy batch receipts.

- [ ] **Step 1: Write failing aggregation and legacy-isolation tests**

```python
def test_throughput_snapshot_counts_only_qc_passed_final_mp4s_and_excludes_open_jobs():
    store = BatchThroughputStore(now=_Clock(0, 60, 120))
    store.record(BatchThroughputEvent("batch-1", "job-ok", "run_qc", "assembly_qc", 0, 60,
                                     outcome="succeeded", final_mp4_sha256="a" * 64))
    store.record(BatchThroughputEvent("batch-1", "job-open", "wait_provider_video", "provider_poll", 60, 120,
                                     outcome="running"))

    assert store.snapshot("batch-1")["finalized_qc_passed_mp4s_per_hour"] == 60.0
    assert store.snapshot("batch-1")["finalized_count"] == 1


def test_legacy_batch_without_throughput_key_remains_readable():
    runtime = _runtime_without_throughput_events()
    assert "throughput_receipt" not in runtime.get_batch("existing-batch")["rows"][0]
```

Run: `python -B -m pytest backend/tests/test_batch_throughput.py backend/tests/test_standard_usfr_batch_runtime.py -q`

Expected: FAIL because `BatchThroughputStore` and the receipt projection do not exist.

- [ ] **Step 2: Implement immutable, TTL-scoped event storage**

```python
@dataclass(frozen=True)
class BatchThroughputEvent:
    batch_id: str
    job_id: str
    stage: str
    capability: str
    started_at_ms: int
    ended_at_ms: int
    outcome: str
    provider_operation: str | None = None
    cache_hit: bool = False
    final_mp4_sha256: str | None = None


class RedisBatchThroughputStore:
    def record(self, event: BatchThroughputEvent) -> None: ...
    def snapshot(self, batch_id: str) -> dict[str, object] | None: ...
```

Persist redacted, canonical JSON events under the current batch TTL. Validate known outcome values, nonnegative timestamps, stage/capability text, and a 64-hex final digest. Never persist request bodies, Authorization headers, API keys, audio URLs, or media bytes.

- [ ] **Step 3: Project the receipt without changing the old timing schema**

```python
throughput = self._throughput_for_batch(batch_id)
if throughput is not None:
    projection["throughput_receipt"] = throughput
```

Wire the optional store through `build_standard_commercial_batch_runtime()` and `CommercialBatchRuntime`. Keep `timing_ledger` exactly as it is so old job receipts and existing deployment tests retain their contract.

- [ ] **Step 4: Verify the focused tests pass**

Run: `python -B -m pytest backend/tests/test_batch_throughput.py backend/tests/test_replication_timing.py backend/tests/test_standard_usfr_batch_runtime.py -q`

Expected: PASS; a legacy batch without an event key returns its existing public row unchanged.

- [ ] **Step 5: Commit the isolated observability foundation**

```powershell
git add backend/app/services/batch_throughput.py backend/app/replication_runtime.py backend/tests/test_batch_throughput.py backend/tests/test_standard_usfr_batch_runtime.py
git commit -m "feat: add temporary USFR batch throughput receipts"
```

### Task 2: Add Provider Capability Buckets and an Adaptive Capacity Controller

**Files:**
- Create: `backend/app/services/provider_capacity.py`
- Create: `backend/tests/test_provider_capacity.py`
- Modify: `backend/app/capability_work_queue.py`
- Modify: `backend/app/usfr_commercial_deployment.py`
- Modify: `backend/tests/test_capability_work_queue.py`
- Modify: `backend/tests/test_usfr_commercial_deployment.py`

**Interfaces:**
- Consumes: one of `runninghub_image`, `runninghub_audio_lipsync`, `youdao_asset`, `youdao_video`, `provider_poll_download`, `local_assembly_qc`; observed latency; outcome class.
- Produces: `AdaptiveCapacityController.acquire(capability)`, `release(lease)`, `observe(capability, outcome, latency_ms)`, and a redacted `CapacitySnapshot`.
- Invariant: it gates work only. It never calls `CreateAsset`, `CreateVideo`, or a retry function; ambiguous results produce `reconciliation_required`.

- [ ] **Step 1: Write failing AIMD, floor/ceiling, and ambiguous-error tests**

```python
def test_rate_limit_halves_capacity_but_never_below_the_configured_floor():
    controller = AdaptiveCapacityController(_policy(initial=8, minimum=2, maximum=12))
    controller.observe("youdao_video", outcome="rate_limited", latency_ms=100)
    assert controller.snapshot("youdao_video").limit == 4
    controller.observe("youdao_video", outcome="overloaded", latency_ms=100)
    assert controller.snapshot("youdao_video").limit == 2


def test_ambiguous_create_result_requires_reconciliation_and_never_releases_a_new_create_intent():
    signal = controller.observe("youdao_asset", outcome="ambiguous", latency_ms=1_000)
    assert signal.reconciliation_required is True
    assert signal.create_retry_allowed is False
```

Run: `python -B -m pytest backend/tests/test_provider_capacity.py -q`

Expected: FAIL because the controller and policy types do not exist.

- [ ] **Step 2: Implement deterministic capability policy**

```python
PROVIDER_CAPABILITIES = (
    "runninghub_image", "runninghub_audio_lipsync", "youdao_asset",
    "youdao_video", "provider_poll_download", "local_assembly_qc",
)

def next_limit(policy: CapacityPolicy, state: CapacityState, *, outcome: str, latency_ms: int) -> int:
    if outcome in {"rate_limited", "overloaded"} or latency_ms >= policy.p95_slow_ms:
        return max(policy.minimum, (state.limit + 1) // 2)
    if outcome == "succeeded" and state.clean_successes >= policy.increase_after_successes:
        return min(policy.maximum, state.limit + 1)
    return state.limit
```

Use a Redis-backed compare-and-set/lease implementation at deployment time and an injectable in-memory implementation in tests. Require explicit minimum, initial, maximum, increase window, and slow-latency threshold configuration; reject values outside `minimum <= initial <= maximum`.

- [ ] **Step 3: Keep existing message routing intact while adding sub-capability gates**

```python
class ProviderCapacityGate:
    def around(self, *, capability: str, operation: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]: ...
```

Continue routing standard `WorkMessage(job_id, stage, expected_version, dedupe_key)` through the existing five queues. Install the new gate immediately around actual Provider image, ASR/TTS/lip-sync, asset, video, lookup/download, and local assembly/QC operations, selected from immutable stage/request metadata. This avoids a `WorkMessage` schema change and does not create a sixth semantic stage.

- [ ] **Step 4: Emit controller decisions into the throughput ledger**

Record `capability`, admitted limit, inflight count, `rate_limited`, `overloaded`, `latency_slow`, and `reconciliation_required` as redacted event fields. Do not record raw Provider response text.

- [ ] **Step 5: Run focused regression tests**

Run: `python -B -m pytest backend/tests/test_provider_capacity.py backend/tests/test_capability_work_queue.py backend/tests/test_usfr_commercial_deployment.py -q`

Expected: PASS; the static queue configuration still works when `USFR_BATCH_SCHEDULER_MODE=static`.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/provider_capacity.py backend/app/capability_work_queue.py backend/app/usfr_commercial_deployment.py backend/tests/test_provider_capacity.py backend/tests/test_capability_work_queue.py backend/tests/test_usfr_commercial_deployment.py
git commit -m "feat: add provider-aware capacity control for USFR batches"
```

### Task 3: Dispatch Ready Work Fairly Across Batches

**Files:**
- Create: `backend/app/services/fair_dispatch.py`
- Create: `backend/tests/test_fair_dispatch.py`
- Modify: `backend/app/batch_scheduler.py`
- Modify: `backend/app/replication_runtime.py`
- Modify: `backend/tests/test_batch_scheduler.py`
- Modify: `backend/tests/test_standard_usfr_batch_runtime.py`

**Interfaces:**
- Consumes: a ready, dependency-satisfied canonical work message plus `batch_id` and positive integer batch weight.
- Produces: `WeightedFairReadyQueue.put()`, `pop(capability)`, and `remove(job_id, stage, version)`.
- Invariant: a job may only enqueue the next existing USFR stage after its predecessor checkpoint succeeds; dispatch ordering may change across independent jobs, never inside a job.

- [ ] **Step 1: Write failing fairness and dependency-order tests**

```python
def test_two_equal_batches_alternate_ready_work_instead_of_starving_the_small_batch():
    queue = WeightedFairReadyQueue()
    for index in range(4):
        queue.put(_ready("large", f"large-{index}"), weight=1)
    queue.put(_ready("small", "small-0"), weight=1)

    assert [queue.pop("storyboard_generation").job_id for _ in range(3)] == ["large-0", "small-0", "large-1"]


def test_next_stage_is_not_dispatchable_before_its_checkpoint_succeeds():
    queue.put(_ready("batch-a", "job-1", stage="run_qc", dependency="splice_timeline"), weight=1)
    assert queue.pop("assembly_qc") is None
```

Run: `python -B -m pytest backend/tests/test_fair_dispatch.py backend/tests/test_batch_scheduler.py -q`

Expected: FAIL because ready work is currently emitted directly in submission order.

- [ ] **Step 2: Implement virtual-finish weighted fairness**

```python
@dataclass(frozen=True)
class ReadyWork:
    batch_id: str
    job_id: str
    stage: str
    expected_version: int
    dedupe_key: str
    capability: str

def virtual_finish(previous_finish: float, global_virtual_time: float, weight: int) -> float:
    return max(previous_finish, global_virtual_time) + 1.0 / weight
```

Persist ready items under the existing batch TTL. The default weight is `1`; allow a bounded deployment-supplied weight only. A cancelled, completed, or version-mismatched item is discarded before queue delivery, never retried.

- [ ] **Step 3: Integrate only in adaptive mode**

```python
if self._scheduler_mode == "adaptive":
    self._fair_ready_queue.put(ready_work)
    return self._fair_ready_queue.dispatch_available()
return self._stage_driver.enqueue_next(job_id)
```

Leave the current direct `BatchScheduler` behavior untouched for local jobs and `static` mode. Use the existing job-store checkpoint/version and `CapabilityRoutedWorkQueue.enqueue()` for final delivery, so dedupe and ACK semantics remain authoritative.

- [ ] **Step 4: Run focused regression tests**

Run: `python -B -m pytest backend/tests/test_fair_dispatch.py backend/tests/test_batch_scheduler.py backend/tests/test_standard_usfr_batch_runtime.py -q`

Expected: PASS; each batch advances, while every job retains its normal stage order.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/fair_dispatch.py backend/app/batch_scheduler.py backend/app/replication_runtime.py backend/tests/test_fair_dispatch.py backend/tests/test_batch_scheduler.py backend/tests/test_standard_usfr_batch_runtime.py
git commit -m "feat: dispatch USFR batch work with weighted fairness"
```

### Task 4: Replace Per-Task Waiting With Centralized Known-Task Polling

**Files:**
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/provider_polling.py`
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_polling.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/redis_streams.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/ephemeral_worker.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/production_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_redis_streams.py`

**Interfaces:**
- Consumes: a known `provider_task_id`, exact provider intent/request SHA, job/stage/version, and next due timestamp.
- Produces: `ProviderPollCoordinator.register()`, `poll_due(limit)`, and `PollReceipt`.
- Invariant: it calls `lookup()` only. A missing or ambiguous task id returns `reconciliation_required`; it can never call a create API or generate a new request.

- [ ] **Step 1: Write failing coalescing and no-create tests**

```python
def test_pending_known_tasks_share_one_due_time_cycle_and_each_is_looked_up_once():
    coordinator = ProviderPollCoordinator(queue=_scheduled_queue(), lookup=_lookup_pending)
    coordinator.register(_known("job-1", "task-1", due_at_ms=100))
    coordinator.register(_known("job-2", "task-2", due_at_ms=100))

    receipts = coordinator.poll_due(now_ms=100, limit=10)
    assert [receipt.task_id for receipt in receipts] == ["task-1", "task-2"]
    assert _lookup_pending.calls == ["task-1", "task-2"]


def test_unknown_or_ambiguous_task_stops_for_reconciliation_without_create():
    receipt = coordinator.poll_due(now_ms=100, limit=1)[0]
    assert receipt.status == "reconciliation_required"
    assert create_video.call_count == 0
```

Run: `Set-Location 'C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication'; python -B -m pytest tests/test_provider_polling.py tests/test_redis_streams.py -q`

Expected: FAIL because no poll coordinator exists.

- [ ] **Step 2: Implement due-time polling on the existing Redis scheduler**

```python
class ProviderPollCoordinator:
    def register(self, intent: KnownProviderIntent) -> None:
        self.queue.schedule(job_id=intent.job_id, stage="wait_provider_video",
                            expected_version=intent.expected_version, dedupe_key=intent.dedupe_key,
                            due_at_ms=intent.due_at_ms)

    def poll_once(self, intent: KnownProviderIntent) -> PollReceipt:
        result = self.lookup({"task_id": intent.provider_task_id, "request_sha256": intent.request_sha256})
        return self._classify(result, intent)
```

Use the existing `schedule()`/`promote_due()` records and an adaptive, bounded next due-time. A pending result is rescheduled with the same intent; completed results advance the existing stage; terminal failures preserve the Provider receipt. Ambiguous network/HTTP results do not enqueue a new create intent.

- [ ] **Step 3: Wire `wait_provider_video` to one poll iteration**

Replace blocking loops with one `poll_once()` per delivered due item. Release the worker capacity lease after the poll completes; the coordinator owns any later due record. Preserve the stage name, state machine, and provider receipt shape.

- [ ] **Step 4: Verify focused tests pass**

Run: `Set-Location 'C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication'; python -B -m pytest tests/test_provider_polling.py tests/test_redis_streams.py tests/test_ephemeral_runtime.py tests/test_provider_idempotency_redis.py -q`

Expected: PASS; no test observes a second create call after a pending, timeout, 429, or ambiguous result.

- [ ] **Step 5: Commit**

```powershell
git add C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/provider_polling.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/redis_streams.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/ephemeral_worker.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/production_ports.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_polling.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_redis_streams.py
git commit -m "feat: coordinate known USFR provider task polling"
```

### Task 5: Reuse Only Exact, Safe Temporary Artifacts

**Files:**
- Create: `backend/app/services/temporary_artifact_reuse.py`
- Create: `backend/tests/test_temporary_artifact_reuse.py`
- Modify: `backend/app/replication_runtime.py`
- Modify: `backend/tests/test_batch_scheduler.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/production_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_idempotency_redis.py`

**Interfaces:**
- Consumes: explicit reuse kind, source bytes SHA-256, normalized provider/model/workflow contract SHA-256, and a TTL scope.
- Produces: `fingerprint_reuse_key()`, `get_verified()`, and `put_verified()`.
- Invariant: only `upload_completion_validation` and documented `provider_asset_registration` are reusable across jobs; source dynamics/ASR/OCR/intent/script/storyboard/Provider video/final MP4 are never cross-job cacheable.

- [ ] **Step 1: Write failing exact-fingerprint and forbidden-kind tests**

```python
def test_provider_asset_reuse_requires_matching_bytes_and_exact_provider_contract():
    cache.put_verified(_key(kind="provider_asset_registration", bytes_sha="a" * 64, contract_sha="b" * 64), {"asset_id": "asset-1"})
    assert cache.get_verified(_key(kind="provider_asset_registration", bytes_sha="a" * 64, contract_sha="b" * 64))["asset_id"] == "asset-1"
    assert cache.get_verified(_key(kind="provider_asset_registration", bytes_sha="a" * 64, contract_sha="c" * 64)) is None


def test_source_analysis_can_never_be_shared_between_two_jobs():
    with pytest.raises(ValueError, match="TEMPORARY_REUSE_KIND_FORBIDDEN"):
        cache.put_verified(_key(kind="source_analysis", bytes_sha="a" * 64, contract_sha="b" * 64), {})
```

Run: `python -B -m pytest backend/tests/test_temporary_artifact_reuse.py backend/tests/test_batch_scheduler.py -q`

Expected: FAIL because the reuse store and denylist do not exist.

- [ ] **Step 2: Implement allowlist-first fingerprinting**

```python
REUSABLE_KINDS = frozenset({"upload_completion_validation", "provider_asset_registration"})

def fingerprint_reuse_key(*, kind: str, bytes_sha256: str, contract_sha256: str) -> str:
    if kind not in REUSABLE_KINDS:
        raise ValueError("TEMPORARY_REUSE_KIND_FORBIDDEN")
    return sha256(canonical_json({"kind": kind, "bytes": bytes_sha256, "contract": contract_sha256})).hexdigest()
```

For Provider assets include asset type, provider, model/workflow version, required role, and all normalized request fields in `contract_sha256`; reject an expired, incomplete, inactive, or request-SHA-mismatched entry. Never cache or reuse a `CreateVideo` result.

- [ ] **Step 3: Integrate asset reuse before create, not after ambiguity**

```python
cached = reuse_store.get_verified(asset_key)
if cached is not None:
    return cached
receipt = provider.create_asset(request)  # called once only after an exact cache miss
reuse_store.put_verified(asset_key, receipt)
```

On 429, 5xx, timeout, reset, or ambiguous create response, do not write a cache entry and do not issue another create. Hand the preserved intent to existing reconciliation.

- [ ] **Step 4: Verify focused regression tests**

Run: `python -B -m pytest backend/tests/test_temporary_artifact_reuse.py backend/tests/test_batch_scheduler.py -q; Set-Location 'C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication'; python -B -m pytest tests/test_provider_idempotency_redis.py tests/test_youdao_seedance.py -q`

Expected: PASS; a matching asset can be reused, all semantic and final-media artifacts remain isolated.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/temporary_artifact_reuse.py backend/app/replication_runtime.py backend/tests/test_temporary_artifact_reuse.py backend/tests/test_batch_scheduler.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/production_ports.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_idempotency_redis.py
git commit -m "feat: reuse only exact temporary USFR provider assets"
```

### Task 6: Publish Actionable Batch Throughput and Provider Receipts

**Files:**
- Modify: `backend/app/services/batch_throughput.py`
- Modify: `backend/app/services/replication_timing.py`
- Modify: `backend/app/replication_runtime.py`
- Modify: `backend/tests/test_batch_throughput.py`
- Modify: `backend/tests/test_replication_timing.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/telemetry.py`
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_throughput_telemetry.py`

**Interfaces:**
- Consumes: event records from the capacity controller, fair dispatcher, poll coordinator, cache, timing ledger, and final QC.
- Produces: per-batch `throughput_receipt/v1` and per-operation `MetricsSink` records.
- Invariant: the receipt is operational and TTL-scoped, not a new user analytics API. All timestamps, counts, and SHA values are safe; secrets and raw media URLs are excluded.

- [ ] **Step 1: Write failing metrics projection tests**

```python
def test_receipt_exposes_queue_age_saturation_quantiles_cache_and_cost_efficiency():
    receipt = _store_with_completed_events().snapshot("batch-1")
    assert receipt["queue_age_ms"]["p95"] == 900
    assert receipt["provider"]["youdao_video"]["rate_limited_count"] == 1
    assert receipt["cache"]["hit_rate"] == 0.5
    assert receipt["cost"]["provider_creates_per_delivered_mp4"] == 1.0


def test_telemetry_record_does_not_allow_secret_or_url_fields():
    with pytest.raises(ValueError, match="TELEMETRY_FIELD_FORBIDDEN"):
        MetricsSink().record(run_id="job", stage="provider", status="succeeded", duration_seconds=1,
                             attributes={"authorization": "secret"})
```

Run: `python -B -m pytest backend/tests/test_batch_throughput.py backend/tests/test_replication_timing.py -q; Set-Location 'C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication'; python -B -m pytest tests/test_provider_throughput_telemetry.py -q`

Expected: FAIL because aggregate provider/cost/fairness fields and attribute filtering do not exist.

- [ ] **Step 2: Implement the receipt schema**

```python
{
    "schema_version": "throughput_receipt/v1",
    "finalized_qc_passed_mp4s_per_hour": 0.0,
    "queue_age_ms": {"p50": 0, "p95": 0},
    "provider": {"youdao_video": {"p50_ms": 0, "p95_ms": 0, "saturation": 0.0, "rate_limited_count": 0}},
    "cache": {"hit_rate": 0.0, "hits": 0, "misses": 0},
    "reconciliation_required_count": 0,
    "cost": {"provider_creates": 0, "provider_creates_per_delivered_mp4": None},
}
```

Calculate quantiles deterministically from stored integer milliseconds. Use `None`, not division by zero, when no MP4 has passed QC. Record fairness wait separately from Provider wait.

- [ ] **Step 3: Add cache-hit support without mutating legacy timing records**

Add a new optional `cache_decision` event to the batch ledger. Do not retrofit fields into `TimingLedger` stage records, whose exact serialized schema already has compatibility tests.

- [ ] **Step 4: Verify focused tests pass**

Run: `python -B -m pytest backend/tests/test_batch_throughput.py backend/tests/test_replication_timing.py backend/tests/test_standard_usfr_batch_runtime.py -q; Set-Location 'C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication'; python -B -m pytest tests/test_provider_throughput_telemetry.py tests/test_production_timing.py -q`

Expected: PASS; no receipt contains a key, authorization header, raw request, or media URL.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/batch_throughput.py backend/app/services/replication_timing.py backend/app/replication_runtime.py backend/tests/test_batch_throughput.py backend/tests/test_replication_timing.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/telemetry.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_throughput_telemetry.py
git commit -m "feat: expose redacted USFR batch throughput receipts"
```

### Task 7: Prove Throughput Gains With a Deterministic Batch Load Harness

**Files:**
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_aware_batch_load.py`
- Modify: `backend/tests/test_provider_capacity.py`
- Modify: `backend/tests/test_fair_dispatch.py`
- Modify: `backend/tests/test_standard_usfr_batch_runtime.py`

**Interfaces:**
- Consumes: fake monotonic clock, fake Redis, deterministic Provider outcome schedule, and a mixed batch matrix.
- Produces: reproducible static-versus-adaptive run reports; no network traffic and no paid task creation.
- Invariant: the harness verifies scheduling behavior only. It may not be presented as a real Provider media/effects validation.

- [ ] **Step 1: Write the failing mixed-load acceptance test**

```python
def test_adaptive_mode_delivers_more_finalized_jobs_than_static_mode_under_deterministic_rate_limits():
    static = run_load(mode="static", jobs=_mixed_jobs(), provider=_rate_limited_provider())
    adaptive = run_load(mode="adaptive", jobs=_mixed_jobs(), provider=_rate_limited_provider())

    assert adaptive.finalized_count > static.finalized_count
    assert adaptive.duplicate_create_count == 0
    assert adaptive.small_batch_first_delivery_at_ms <= adaptive.max_starvation_ms
```

Run: `Set-Location 'C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication'; python -B -m pytest tests/test_provider_aware_batch_load.py -q`

Expected: FAIL because no load harness or adaptive integration exists.

- [ ] **Step 2: Implement a deterministic fake Provider schedule**

```python
class DeterministicProvider:
    def create_video(self, request):
        self.create_count[request["intent_id"]] += 1
        return self.scripted_create_outcome(request["intent_id"])

    def lookup(self, intent):
        return self.scripted_lookup_outcome(intent["task_id"])
```

The fixture must cover RunningHub image/lip-sync, Youdao asset/video, pending polls, one 429, one slow response, one ambiguous result requiring reconciliation, music-enabled rows, language-only rows, and ordinary visual replacement rows.

- [ ] **Step 3: Add hard regression assertions**

```python
assert all(count <= 1 for count in report.create_count.values())
assert report.approval_count_by_job == {job_id: expected_approval_count(job) for job_id, job in report.jobs.items()}
assert report.semantic_stage_sequences_are_unchanged is True
assert report.source_analysis_shared_across_jobs is False
```

- [ ] **Step 4: Run load and targeted suites**

Run: `python -B -m pytest backend/tests/test_provider_capacity.py backend/tests/test_fair_dispatch.py backend/tests/test_standard_usfr_batch_runtime.py -q; Set-Location 'C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication'; python -B -m pytest tests/test_provider_aware_batch_load.py tests/test_provider_polling.py tests/test_provider_idempotency_redis.py -q`

Expected: PASS; adaptive mode increases deterministic throughput, preserves all semantic contracts, and creates no duplicate paid intent.

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/test_provider_capacity.py backend/tests/test_fair_dispatch.py backend/tests/test_standard_usfr_batch_runtime.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_aware_batch_load.py
git commit -m "test: cover provider-aware USFR batch throughput under load"
```

### Task 8: Add Feature Flags, Rollback Controls, and Operator Documentation

**Files:**
- Modify: `backend/app/usfr_commercial_deployment.py`
- Modify: `backend/app/replication_runtime.py`
- Modify: `backend/tests/test_usfr_commercial_deployment.py`
- Modify: `backend/tests/test_replication_runtime.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_skill_contract.py`

**Interfaces:**
- Consumes: deployment environment only.
- Produces: validated immutable `BatchSchedulerConfig` wired at startup and emitted in redacted receipts.
- Invariant: invalid configuration fails before any worker creates a paid Provider request. `static` remains an instant no-data-migration rollback mode.

- [ ] **Step 1: Write failing config validation tests**

```python
def test_adaptive_mode_requires_complete_bounded_capacity_and_poll_configuration():
    with pytest.raises(CommercialDeploymentError, match="USFR_BATCH_ADAPTIVE_MAX_YOUDAO_VIDEO_INVALID"):
        build_commercial_deployment_runtime(..., environment={"USFR_BATCH_SCHEDULER_MODE": "adaptive"})


def test_static_mode_uses_existing_queue_limits_and_does_not_construct_adaptive_ports():
    runtime = build_commercial_deployment_runtime(..., environment=_static_env())
    assert runtime.work_queue.concurrency_limits == _static_limits()
```

Run: `python -B -m pytest backend/tests/test_usfr_commercial_deployment.py backend/tests/test_replication_runtime.py -q`

Expected: FAIL because adaptive controls are not parsed or validated.

- [ ] **Step 2: Implement startup-only configuration**

```text
USFR_BATCH_SCHEDULER_MODE=static|adaptive
USFR_BATCH_ADAPTIVE_MIN_<CAPABILITY>=positive integer
USFR_BATCH_ADAPTIVE_INITIAL_<CAPABILITY>=positive integer
USFR_BATCH_ADAPTIVE_MAX_<CAPABILITY>=positive integer
USFR_BATCH_ADAPTIVE_INCREASE_AFTER_SUCCESSES=positive integer
USFR_BATCH_ADAPTIVE_P95_SLOW_MS=positive integer
USFR_BATCH_POLL_MIN_DELAY_MS=positive integer
USFR_BATCH_POLL_MAX_DELAY_MS=positive integer
USFR_BATCH_FAIR_DEFAULT_WEIGHT=positive integer
```

Accept no live environment mutation. `static` uses the current `USFR_BATCH_CONCURRENCY_*` variables unchanged. `adaptive` requires all six capability policies and rejects unsafe/missing values before the worker manager starts.

- [ ] **Step 3: Document the operating procedure in the Skill without changing semantics**

Add a short runtime subsection that states: capture a static baseline; activate adaptive mode for a controlled batch; inspect `throughput_receipt/v1`; revert to `static` on increased reconciliation, failed QC, or lower finalized MP4s/hour. Explicitly state that a 429/timeout is reconciled, never retried, and that this is an execution optimization only.

- [ ] **Step 4: Run full relevant verification**

Run: `python -B -m pytest backend/tests/test_batch_scheduler.py backend/tests/test_batch_throughput.py backend/tests/test_provider_capacity.py backend/tests/test_fair_dispatch.py backend/tests/test_temporary_artifact_reuse.py backend/tests/test_capability_work_queue.py backend/tests/test_replication_timing.py backend/tests/test_replication_runtime.py backend/tests/test_standard_usfr_batch_runtime.py backend/tests/test_usfr_commercial_deployment.py -q; Set-Location 'C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication'; python -B -m pytest tests/test_skill_contract.py tests/test_provider_polling.py tests/test_provider_aware_batch_load.py tests/test_provider_idempotency_redis.py tests/test_production_timing.py -q`

Expected: PASS; no test loosens the seven-slot, two-approval, two-Segment, idempotency, or language/music contracts.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/usfr_commercial_deployment.py backend/app/replication_runtime.py backend/tests/test_usfr_commercial_deployment.py backend/tests/test_replication_runtime.py C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_skill_contract.py
git commit -m "docs: add guarded provider-aware USFR batch scheduler controls"
```

## Self-Review

1. **Spec coverage:** Task 1 creates the baseline ledger; Tasks 2-4 remove the static-capacity, starvation, and blocking-poll bottlenecks; Task 5 adds only safe cache reuse; Task 6 gives the requested throughput evidence; Task 7 proves behavior under deterministic load; Task 8 supplies a guarded rollout and rollback. No task adds a user product system, a new approval, an extra Seedance segment, or a new fixed input slot.
2. **Paid-request safety:** Every task treats `CreateAsset` and `CreateVideo` as one-shot intents. Cache lookup precedes only known-safe creates; ambiguous results are reconciled by known task/intent lookup; polling is lookup-only.
3. **Type consistency:** `BatchThroughputEvent`, `AdaptiveCapacityController`, `ReadyWork`, `ProviderPollCoordinator`, and reuse fingerprints are introduced before their integrations. They keep the canonical `WorkMessage` and existing stage names unchanged.
4. **Rollback:** `USFR_BATCH_SCHEDULER_MODE=static` preserves the current static queue limit path without deleting receipts, job checkpoints, or Provider intent records.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-27-usfr-provider-aware-batch-throughput-optimization.md`.

Two execution options:

1. **Subagent-Driven (recommended):** dispatch a fresh subagent for each task, review after each task, and keep the static path as the control group.
2. **Inline Execution:** execute the tasks in this session with checkpoints after Tasks 1, 4, and 7.

Which approach?
