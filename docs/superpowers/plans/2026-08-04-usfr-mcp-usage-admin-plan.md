# USFR MCP Usage, Administration, and Secret Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce configurable daily output and monthly budget limits, provide minimum internal administration, transfer complete asset ownership, and prove secrets never leave the server boundary.

**Architecture:** A transactional usage ledger reserves estimated cost before paid work and settles/releases it from observed Provider outcomes. Admin APIs update PostgreSQL-backed policies. Audit and redaction middleware record actions without credentials or private payloads.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/PostgreSQL, MCP SDK, pytest, structured logging.

## Global Constraints

- Default 50 outputs per user per day.
- Default CNY 10,000 company spend per calendar month.
- 70%, 90%, and 100% budget thresholds.
- All policy values are mutable through admin controls.
- Admin tools require `usfr:admin`.
- No API key, capability token, signed URL, password, OAuth code, or refresh token may be logged or returned.

---

### Task 1: Implement transactional usage reservation and settlement

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/usage/ledger.py`
- Create: `usfr-mcp/src/usfr_mcp/usage/pricing.py`
- Create: `usfr-mcp/tests/test_usage_ledger.py`

**Interfaces:**
- Produces: `reserve_usage(session: Session, request: ReservationRequest) -> UsageReservation`
- Produces: `settle_usage(session: Session, reservation_id: UUID, actual_cny: Decimal, provider_receipt_id: str) -> UsageEvent`
- Produces: `release_usage(session: Session, reservation_id: UUID, reason: str) -> UsageEvent`

- [ ] **Step 1: Write concurrent overspend tests**

```python
def test_concurrent_reservations_cannot_exceed_monthly_budget(ledger, company):
    ledger.set_monthly_budget(company.id, Decimal("100"))
    assert ledger.reserve(company.user_a, JOB_A, 1, Decimal("60"))
    with pytest.raises(MonthlyBudgetExceeded):
        ledger.reserve(company.user_b, JOB_B, 1, Decimal("60"))

def test_release_returns_reserved_capacity(ledger, reservation):
    ledger.release(reservation.id, "definitive_create_failure")
    assert ledger.summary(reservation.company_id).reserved_cny == Decimal("0")
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_usage_ledger.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement serializable reservation**

Lock the company settings/month bucket and user daily bucket in one transaction. Count successful, running, and reserved outputs against the daily limit. Count settled plus reserved CNY against the monthly limit.

```python
def reserve_usage(session: Session, request: ReservationRequest) -> UsageReservation:
    policy = repository.lock_policy(session)
    daily = repository.lock_daily_bucket(session, request.user_id, request.day)
    monthly = repository.lock_month_bucket(session, request.month)
    enforce_limits(policy, daily, monthly, request)
    return repository.create_reservation(session, request)
```

- [ ] **Step 4: Implement pricing snapshots**

Persist a versioned estimate input per request: Provider operation, segment count/duration, image calls, audio/lip-sync calls, currency, and price-config SHA. Do not invent prices; require configured values and fail closed when a paid route lacks a price entry.

```python
def estimate_cost(route: PaidRoute, prices: PriceConfig) -> Money:
    price = prices.require(route.operation, route.model)
    return Money(currency="CNY", amount=price.fixed + price.per_second * route.duration_seconds)
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_usage_ledger.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/usage usfr-mcp/tests/test_usage_ledger.py
git commit -m "feat(usage): reserve and settle provider spend"
```

### Task 2: Integrate quotas with single and batch creation

**Files:**
- Modify: `usfr-mcp/src/usfr_mcp/replication/service.py`
- Modify: `usfr-mcp/src/usfr_mcp/batch/service.py`
- Modify: `usfr-mcp/src/usfr_mcp/batch/scheduler.py`
- Create: `usfr-mcp/tests/test_usage_integration.py`

**Interfaces:**
- Single confirmation reserves one output.
- Batch confirmation reserves the declared output count or approved per-child staged amount according to configured policy.
- Scheduler verifies reservation validity before each child starts.

- [ ] **Step 1: Write gate tests**

```python
def test_daily_limit_blocks_before_usfr_create(service, user_at_limit, fake_usfr):
    with pytest.raises(DailyOutputLimitExceeded):
        service.confirm(user_at_limit.preview_id, user_at_limit.preview_sha)
    assert fake_usfr.create_calls == 0

def test_batch_budget_failure_starts_no_pilot(batch_service, over_budget_preview, fake_usfr):
    with pytest.raises(MonthlyBudgetExceeded):
        batch_service.confirm(over_budget_preview.id, over_budget_preview.sha256)
    assert fake_usfr.create_calls == 0
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_usage_integration.py -v`
Expected: FAIL.

- [ ] **Step 3: Add reservation boundaries**

Reserve before copied-USFR Job creation. Release on definitive pre-provider failure/cancellation. Keep reservations for ambiguous Provider outcomes until reconciliation. Settle on final Provider/accounting receipts, not on client-reported success.

```python
with transaction() as session:
    reservation = usage.reserve(session, request)
    try:
        job = usfr.create_job(payload)
    except DefinitiveCreateFailure:
        usage.release(session, reservation.id, "definitive_create_failure")
        raise
```

- [ ] **Step 4: Add threshold events**

Emit audit/notification events at first crossing of 70%, 90%, and 100% in a month. At 100%, reject new paid calls while allowing status polling, artifact retrieval, and reconciliation.

```python
def threshold_for(percent: Decimal) -> int | None:
    if percent >= 100:
        return 100
    if percent >= 90:
        return 90
    if percent >= 70:
        return 70
    return None
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_usage_integration.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/replication/service.py usfr-mcp/src/usfr_mcp/batch/service.py usfr-mcp/src/usfr_mcp/batch/scheduler.py usfr-mcp/tests/test_usage_integration.py
git commit -m "feat(usage): enforce limits before paid job creation"
```

### Task 3: Add minimum admin API and MCP tools

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/admin/service.py`
- Create: `usfr-mcp/src/usfr_mcp/admin/api.py`
- Create: `usfr-mcp/src/usfr_mcp/tools/admin.py`
- Create: `usfr-mcp/tests/test_admin.py`

**Interfaces:**
- Tools/endpoints: `create_user`, `disable_user`, `get_usage_summary`, `update_usage_limits`, `update_batch_concurrency`.

- [ ] **Step 1: Write authorization tests**

```python
def test_regular_user_cannot_update_limits(mcp_user_client):
    result = mcp_user_client.call_tool("update_usage_limits", {"daily_output_limit": 100})
    assert result.is_error

def test_admin_change_is_effective_for_new_reservations(admin_service, admin):
    admin_service.update_limits(admin, daily_output_limit=25)
    assert admin_service.get_limits().daily_output_limit == 25
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_admin.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement admin operations**

Create users with a one-time initial-password reset requirement. Disabling a user revokes OAuth refresh tokens, blocks new work, and leaves running Provider attempts recoverable by admins. Validate limits: daily outputs positive, budget positive, concurrency 1–20.

```python
def disable_user(admin: Principal, user_id: UUID) -> None:
    require_admin(admin)
    repository.disable_user(user_id)
    oauth_repository.revoke_refresh_tokens(user_id)
    audit.record(admin, "user.disable", "user", user_id)
```

- [ ] **Step 4: Add sanitized usage summaries**

Return output counts, settled/reserved CNY, batch counts, threshold state, and date range. Exclude prompts, source URLs, Provider payloads, and credentials.

```python
def public_usage_summary(summary: UsageSummary) -> dict[str, object]:
    return {"outputs": summary.outputs, "settled_cny": str(summary.settled_cny), "reserved_cny": str(summary.reserved_cny), "threshold": summary.threshold}
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_admin.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/admin usfr-mcp/src/usfr_mcp/tools/admin.py usfr-mcp/tests/test_admin.py
git commit -m "feat(admin): add internal users and configurable limits"
```

### Task 4: Implement complete ownership transfer

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/admin/transfers.py`
- Modify: `usfr-mcp/src/usfr_mcp/tools/admin.py`
- Create: `usfr-mcp/tests/test_asset_transfer.py`

**Interfaces:**
- Tool: `transfer_user_assets(from_user_id, to_user_id) -> TransferReceipt`

- [ ] **Step 1: Write atomicity and access tests**

```python
def test_transfer_moves_complete_graph_and_revokes_old_owner(transfer_service, users, owned_graph):
    receipt = transfer_service.transfer(users.admin, users.old.id, users.new.id)
    assert receipt.source_master_count == owned_graph.source_count
    assert not transfer_service.can_access(users.old, owned_graph.source_id)
    assert transfer_service.can_access(users.new, owned_graph.source_id)

def test_transfer_rolls_back_on_conflict(transfer_service, conflicting_graph):
    with pytest.raises(TransferConflict):
        transfer_service.transfer(*conflicting_graph.users)
    assert conflicting_graph.original_ownership_unchanged()
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_asset_transfer.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement one-transaction graph transfer**

Move Source Masters, analysis caches, assets, replications, batches, artifacts, and applicable usage ownership references without copying object bytes. Resolve target-owner SHA conflicts by explicit error; never silently merge histories.

```python
def transfer_graph(session: Session, source_user: UUID, target_user: UUID) -> TransferReceipt:
    graph = repository.lock_owned_graph(session, source_user)
    repository.assert_no_target_conflicts(session, target_user, graph)
    repository.reassign_owner(session, graph, target_user)
    return TransferReceipt.from_graph(graph, source_user, target_user)
```

- [ ] **Step 4: Record immutable transfer receipt**

Store actor, source user, target user, affected IDs/counts, before/after ownership digest, timestamp, and reason. Do not include signed URLs or object-store credentials.

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_asset_transfer.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/admin/transfers.py usfr-mcp/src/usfr_mcp/tools/admin.py usfr-mcp/tests/test_asset_transfer.py
git commit -m "feat(admin): transfer complete employee asset ownership"
```

### Task 5: Add structured audit logging and secret redaction

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/security/redaction.py`
- Create: `usfr-mcp/src/usfr_mcp/security/audit.py`
- Create: `usfr-mcp/src/usfr_mcp/security/logging.py`
- Create: `usfr-mcp/tests/test_secret_hygiene.py`

**Interfaces:**
- Produces: `redact(value: object) -> object`
- Produces: `record_audit(actor, action, subject_type, subject_id, metadata) -> None`

- [ ] **Step 1: Write exhaustive secret tests**

```python
@pytest.mark.parametrize("secret_key", [
    "authorization", "api_key", "capability_token", "refresh_token",
    "signed_url", "provider_payload", "password",
])
def test_redactor_removes_secret_fields(secret_key):
    value = redact({secret_key: "secret-value", "safe": "ok"})
    assert "secret-value" not in json.dumps(value)
    assert value["safe"] == "ok"
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_secret_hygiene.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement recursive redaction**

Redact case-insensitive key aliases, bearer patterns, query signatures, and configured secret values. Apply before serialization to logs, audit metadata, MCP error content, and public error responses.

```python
def redact(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: "[REDACTED]" if is_secret_key(key) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return redact_secret_patterns(value) if isinstance(value, str) else value
```

- [ ] **Step 4: Add audit coverage**

Record login, user create/disable, preview confirmation, reviews, pilot approval, retries, limit changes, asset deletion, ownership transfer, and Provider reconciliation. Store stable IDs and digests rather than private content.

```python
def record_audit(actor: Principal, action: str, subject_type: str, subject_id: UUID, metadata: Mapping[str, object]) -> None:
    repository.insert_audit(actor.user_id, action, subject_type, subject_id, redact(metadata))
```

- [ ] **Step 5: Run full security suite and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_secret_hygiene.py tests/test_oauth.py tests/test_admin.py tests/test_asset_transfer.py -q`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/security usfr-mcp/tests/test_secret_hygiene.py
git commit -m "feat(security): redact secrets and audit control actions"
```
