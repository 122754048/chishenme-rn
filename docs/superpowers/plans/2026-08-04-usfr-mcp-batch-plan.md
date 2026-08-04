# USFR MCP Explicit Batch Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user-authorized batch replication with no inferred combinations, a fixed first-row pilot, final-MP4 release authorization, bounded concurrency, partial success, and safe retry.

**Architecture:** Batch preview freezes a canonical manifest before any paid work. One Pilot child uses the single-replication flow plus final-result approval. Approval signs a batch authorization; the scheduler then creates remaining child Jobs while enforcing the immutable intent and concurrency limits.

**Tech Stack:** Python 3.12, SQLAlchemy/PostgreSQL, Redis scheduling locks, MCP SDK, pytest.

## Global Constraints

- At most 20 child outputs.
- No Cartesian products or implicit pairing.
- Asset counts and correspondence must match the user's explicit Batch Intent.
- The first manifest item is always the Pilot.
- Remaining children cannot start before final Pilot MP4 approval.
- Default batch concurrency is five, configurable from one to 20.

---

### Task 1: Define Batch Intent and ambiguity validation

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/batch/intents.py`
- Create: `usfr-mcp/src/usfr_mcp/batch/manifest.py`
- Create: `usfr-mcp/tests/test_batch_intents.py`

**Interfaces:**
- Produces enum: `BatchIntent`
- Produces: `build_batch_manifest(request: BatchPreviewInput) -> BatchManifest`
- Produces error: `BatchClarificationRequired(reason, questions)`

- [ ] **Step 1: Write no-combination tests**

```python
def test_twenty_songs_create_twenty_items_without_product(source, songs):
    manifest = build_batch_manifest(BatchPreviewInput(
        intent="replace_music", source_id=source.id, music_asset_ids=songs,
    ))
    assert len(manifest.items) == 20
    assert all(item.model_asset_ids == () for item in manifest.items)

def test_people_and_songs_without_pairing_is_ambiguous(source, people, songs):
    with pytest.raises(BatchClarificationRequired):
        build_batch_manifest(BatchPreviewInput(
            source_id=source.id, model_groups=people, music_asset_ids=songs,
        ))
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_batch_intents.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement explicit intents**

Support `replace_people`, `replace_music`, `localize_languages`, `pair_people_music`, `pair_people_language`, `pair_music_language`, and `pair_people_music_language`. Paired intents require equal list lengths. A shared value may apply to all only when the request explicitly marks it `shared=true`.

```python
class BatchIntent(StrEnum):
    REPLACE_PEOPLE = "replace_people"
    REPLACE_MUSIC = "replace_music"
    LOCALIZE_LANGUAGES = "localize_languages"
    PAIR_PEOPLE_MUSIC = "pair_people_music"
    PAIR_PEOPLE_MUSIC_LANGUAGE = "pair_people_music_language"
```

- [ ] **Step 4: Implement canonical manifest and summary**

Assign ordinals `1..N`, freeze exact asset IDs/languages, source ID, shared slots, intent, and output count. Render a deterministic Chinese summary that explicitly says which fields vary, which remain fixed, and that no permutation is performed.

```python
def build_batch_manifest(request: BatchPreviewInput) -> BatchManifest:
    rows = intent_builder(request.intent).build_rows(request)
    if not 1 <= len(rows) <= 20:
        raise BatchSizeInvalid(len(rows))
    return BatchManifest(items=tuple(BatchItemInput(i + 1, **row) for i, row in enumerate(rows)))
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_batch_intents.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/batch/intents.py usfr-mcp/src/usfr_mcp/batch/manifest.py usfr-mcp/tests/test_batch_intents.py
git commit -m "feat(batch): add explicit intent manifest validation"
```

### Task 2: Persist batch previews and confirm the Pilot only

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/batch/service.py`
- Create: `usfr-mcp/src/usfr_mcp/tools/batch.py`
- Modify: `usfr-mcp/src/usfr_mcp/tools/replication.py`
- Create: `usfr-mcp/tests/test_batch_preview.py`

**Interfaces:**
- `preview_replication()` returns `suggested_mode="batch"` plus manifest SHA.
- `confirm_and_create_replication()` creates one Batch and exactly one Pilot child.

- [ ] **Step 1: Write paid-call gate tests**

```python
def test_batch_preview_creates_no_jobs(batch_service, input, fake_usfr):
    preview = batch_service.preview(input)
    assert preview.task_count == 20
    assert fake_usfr.create_calls == 0

def test_confirm_creates_only_pilot(batch_service, confirmed_preview, fake_usfr):
    batch = batch_service.confirm(confirmed_preview.id, confirmed_preview.sha256)
    assert fake_usfr.create_calls == 1
    assert batch.items[0].role == "pilot"
    assert all(item.usfr_job_id is None for item in batch.items[1:])
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_batch_preview.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement preview persistence**

Persist the canonical manifest, manifest SHA, execution summary, owner, expiry, and `awaiting_confirmation` state. Confirmation requires exact SHA and owner, then creates Batch/BatchItem rows and only the ordinal-one Pilot replication.

```python
def confirm_preview(self, principal: Principal, preview_id: UUID, expected_sha: str) -> BatchHandle:
    preview = self.previews.require_exact(principal.user_id, preview_id, expected_sha)
    batch = self.repository.create_batch(preview)
    self.replications.create_pilot(batch.items[0])
    return BatchHandle.from_model(batch)
```

- [ ] **Step 4: Add batch-state projection**

Public states: `preview`, `pilot_script`, `pilot_storyboard`, `pilot_generating`, `pilot_result_approval`, `authorized`, `running`, `partial_success`, `succeeded`, `failed`, `cancelled`.

```python
def project_batch_state(batch: Batch) -> str:
    if batch.authorization is None:
        return project_pilot_state(batch.pilot)
    if batch.succeeded_count == batch.total_count:
        return "succeeded"
    if batch.terminal_count == batch.total_count:
        return "partial_success"
    return "running"
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_batch_preview.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/batch/service.py usfr-mcp/src/usfr_mcp/tools/batch.py usfr-mcp/src/usfr_mcp/tools/replication.py usfr-mcp/tests/test_batch_preview.py
git commit -m "feat(batch): create pilot-gated batch previews"
```

### Task 3: Add Pilot revision scopes and final-result authorization

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/batch/authorization.py`
- Create: `usfr-mcp/src/usfr_mcp/batch/pilot.py`
- Modify: `usfr-mcp/src/usfr_mcp/tools/batch.py`
- Create: `usfr-mcp/tests/test_pilot_authorization.py`

**Interfaces:**
- Tool: `revise_pilot(batch_handle, instruction, scope)`
- Tool: `approve_pilot_result(batch_handle, expected_result_sha256)`
- Produces: `BatchExecutionAuthorization`

- [ ] **Step 1: Write authorization tests**

```python
def test_batch_wide_revision_invalidates_manifest(batch_service, pilot_ready):
    old_sha = pilot_ready.manifest_sha256
    updated = batch_service.revise_pilot(pilot_ready.handle, "change shared CTA", "batch_wide")
    assert updated.manifest_sha256 != old_sha
    assert updated.authorization is None

def test_final_approval_binds_all_required_hashes(batch_service, pilot_succeeded):
    auth = batch_service.approve_pilot_result(
        pilot_succeeded.handle, pilot_succeeded.result_sha256
    )
    assert auth.manifest_sha256 == pilot_succeeded.manifest_sha256
    assert auth.pilot_result_sha256 == pilot_succeeded.result_sha256
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_pilot_authorization.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement revision scopes**

`pilot_only` creates a new Pilot revision without changing remaining item inputs. `batch_wide` applies only explicitly supported shared-template changes, recomputes the manifest SHA, clears prior authorization, and keeps remaining children unstarted. Reject scope/content conflicts with a typed clarification error.

```python
def revise_pilot(batch: Batch, instruction: str, scope: RevisionScope) -> Batch:
    validate_revision_scope(batch, instruction, scope)
    if scope is RevisionScope.BATCH_WIDE:
        batch.replace_manifest(apply_shared_revision(batch.manifest, instruction))
    batch.clear_authorization()
    return batch
```

- [ ] **Step 4: Implement signed authorization**

Canonicalize and HMAC-sign batch ID, owner, manifest SHA, intent, pilot script/storyboard/result SHA values, allowed variations, issue time, and authorization version. Verify signature before every non-pilot child creation.

```python
def sign_authorization(payload: AuthorizationPayload, secret: bytes) -> BatchExecutionAuthorization:
    body = canonical_json(payload.model_dump(mode="json"))
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return BatchExecutionAuthorization(payload=payload, signature=signature)
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_pilot_authorization.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/batch/authorization.py usfr-mcp/src/usfr_mcp/batch/pilot.py usfr-mcp/src/usfr_mcp/tools/batch.py usfr-mcp/tests/test_pilot_authorization.py
git commit -m "feat(batch): authorize execution from approved pilot result"
```

### Task 4: Implement bounded child scheduling and automatic reviews

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/batch/scheduler.py`
- Create: `usfr-mcp/src/usfr_mcp/batch/worker.py`
- Create: `usfr-mcp/tests/test_batch_scheduler.py`

**Interfaces:**
- Produces: `BatchScheduler.schedule(batch_id: UUID) -> ScheduleResult`
- Produces: `advance_child(item: BatchItem, authorization: BatchExecutionAuthorization) -> ChildSnapshot`

- [ ] **Step 1: Write concurrency and gate tests**

```python
def test_scheduler_never_exceeds_default_five(scheduler, authorized_batch_20):
    result = scheduler.schedule(authorized_batch_20.id)
    assert result.started == 5
    assert result.queued == 14

def test_scheduler_rejects_unsigned_or_changed_manifest(scheduler, tampered_batch):
    with pytest.raises(BatchAuthorizationInvalid):
        scheduler.schedule(tampered_batch.id)
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_batch_scheduler.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement transactional leasing**

Use PostgreSQL row locks plus Redis short leases to select the next queued items without double-starting. Calculate effective concurrency as the minimum of batch, user, company, and deployment limits.

```python
def lease_next_items(batch_id: UUID, limits: ConcurrencyLimits) -> list[BatchItem]:
    available = min(limits.batch, limits.user, limits.company, limits.deployment) - running_count(batch_id)
    return repository.lock_queued_items(batch_id, limit=max(available, 0), skip_locked=True)
```

- [ ] **Step 4: Implement automatic child review progression**

For non-pilot children only, monitor copied-USFR state. When script or storyboard review is ready, record the actual artifact SHA and call approve automatically under the valid Batch Authorization. Never synthesize approval for the Pilot or for a child whose manifest inputs differ.

```python
def advance_child(item: BatchItem, authorization: BatchExecutionAuthorization) -> ChildSnapshot:
    verify_item_authorized(item, authorization)
    snapshot = usfr.get_job(item.internal_handle)
    if snapshot.state in {"SCRIPT_AWAITING_APPROVAL", "STORYBOARD_AWAITING_APPROVAL"}:
        archive_current_review(item, snapshot)
        snapshot = usfr.review(item.internal_handle, action="approve")
    return ChildSnapshot.from_usfr(snapshot)
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_batch_scheduler.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/batch/scheduler.py usfr-mcp/src/usfr_mcp/batch/worker.py usfr-mcp/tests/test_batch_scheduler.py
git commit -m "feat(batch): schedule authorized children with bounded concurrency"
```

### Task 5: Implement partial success, cancellation, retry, and reconciliation

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/batch/recovery.py`
- Modify: `usfr-mcp/src/usfr_mcp/tools/batch.py`
- Create: `usfr-mcp/tests/test_batch_recovery.py`

**Interfaces:**
- Tools: `get_batch`, `retry_failed_batch_items`, `cancel_queued_batch_items`
- Produces item states: `queued`, `running`, `succeeded`, `failed`, `provider_ambiguous`, `cancelled`.

- [ ] **Step 1: Write recovery tests**

```python
def test_failed_item_does_not_block_other_items(batch_runner, batch_with_one_failure):
    snapshot = batch_runner.run_until_idle(batch_with_one_failure.id)
    assert snapshot.succeeded_count == snapshot.total_count - 1
    assert snapshot.failed_count == 1

def test_retry_does_not_resubmit_ambiguous_provider_item(recovery, ambiguous_item):
    with pytest.raises(ProviderReconciliationRequired):
        recovery.retry([ambiguous_item.id])
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_batch_recovery.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement retry eligibility**

Allow retry only for definitive failures and only under the unchanged Batch Authorization. Ambiguous Provider states must call the copied-USFR reconciliation/status path first. Successful items are immutable and excluded from retry selection.

```python
def retry(items: Sequence[BatchItem], authorization: BatchExecutionAuthorization) -> RetryResult:
    eligible = [item for item in items if item.state == "failed"]
    if any(item.state == "provider_ambiguous" for item in items):
        raise ProviderReconciliationRequired()
    return repository.requeue(eligible, authorization.manifest_sha256)
```

- [ ] **Step 4: Implement queue cancellation**

Cancel only children that have not created a paid Provider attempt. Return exact cancelled/skipped IDs and leave running/succeeded/ambiguous children unchanged.

```python
def cancel_queued(items: Sequence[BatchItem]) -> CancellationResult:
    cancellable = [item for item in items if item.state == "queued" and item.provider_attempt_id is None]
    skipped = [item.id for item in items if item not in cancellable]
    repository.cancel(cancellable)
    return CancellationResult(cancelled=[item.id for item in cancellable], skipped=skipped)
```

- [ ] **Step 5: Run full batch suite and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_batch_*.py -q`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/batch/recovery.py usfr-mcp/src/usfr_mcp/tools/batch.py usfr-mcp/tests/test_batch_recovery.py
git commit -m "feat(batch): add partial success and safe recovery"
```
