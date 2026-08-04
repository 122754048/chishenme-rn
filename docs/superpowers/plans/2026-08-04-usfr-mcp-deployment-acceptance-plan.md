# USFR MCP Deployment and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the MCP control plane and copied USFR runtime for one-server Linux deployment, prove readiness/recovery, and complete Shadow acceptance before internal rollout.

**Architecture:** A root Docker Compose file runs Caddy, MCP/API, PostgreSQL, Redis, MinIO, copied USFR API, Worker, and Sweeper. OSS stores persistent media. Readiness blocks missing Provider/model/classifier capabilities. E2E drivers exercise the real public MCP and Jobs boundaries.

**Tech Stack:** Docker Compose, Caddy, PostgreSQL 16, Redis 7.4, MinIO, Python 3.12, pytest, MCP Inspector, OSS, OpenAI, RunningHub.

## Global Constraints

- Only ports 80/443 are public in production.
- Redis, PostgreSQL, MinIO 9000/9001, and copied USFR 8080 remain private.
- Production requires HTTPS and an approved domain.
- The uploaded-audio classifier endpoint/model/digest/token must be configured for music routes.
- Real Provider work begins in Shadow and expands gradually to at most 20 internal users.

---

### Task 1: Build the production Compose topology and Caddy edge

**Files:**
- Create: `usfr-mcp/deployment/docker-compose.yml`
- Create: `usfr-mcp/deployment/Dockerfile`
- Create: `usfr-mcp/deployment/Caddyfile`
- Create: `usfr-mcp/deployment/.env.example`
- Create: `usfr-mcp/tests/test_deployment_contract.py`

**Interfaces:**
- Services: `caddy`, `mcp-api`, `mcp-worker`, `postgres`, `redis`, `minio`, `minio-init`, `usfr-api`, `usfr-worker`, `usfr-sweeper`.

- [ ] **Step 1: Write deployment contract tests**

```python
def test_only_edge_ports_are_published(compose):
    assert compose["services"]["caddy"]["ports"] == ["80:80", "443:443"]
    for name in {"postgres", "redis", "minio", "usfr-api"}:
        assert "ports" not in compose["services"][name]

def test_env_example_contains_no_secret_values(env_example):
    for key in (
        "OPENAI_API_KEY", "RUNNINGHUB_API_KEY", "RUNNINGHUB_SEEDANCE_API_KEY",
        "USFR_OSS_ACCESS_KEY_SECRET", "USFR_MCP_JWT_SIGNING_SECRET",
    ):
        assert env_example[key] == ""
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_deployment_contract.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement images and services**

Build the MCP image from `usfr-mcp/`. Build the runtime image from generated `usfr-runtime/`. Mount persistent named volumes for PostgreSQL and Caddy state; MinIO remains temporary but survives ordinary container restart. Add health checks and dependency conditions.

```yaml
services:
  mcp-api:
    build: {context: .., dockerfile: deployment/Dockerfile}
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
      usfr-api: {condition: service_healthy}
  usfr-api:
    build: {context: ../../usfr-runtime, dockerfile: deployment/Dockerfile}
```

- [ ] **Step 4: Configure Caddy**

Route `/mcp`, OAuth metadata/routes, admin API, and health endpoints to `mcp-api`. Do not route copied-USFR, MinIO, Redis, or PostgreSQL publicly. Set request-body limits suitable for metadata calls; media bytes upload directly to signed object-store URLs.

```caddyfile
{$USFR_MCP_DOMAIN} {
    encode zstd gzip
    reverse_proxy /mcp* mcp-api:8081
    reverse_proxy /.well-known/* mcp-api:8081
    reverse_proxy /oauth/* mcp-api:8081
    reverse_proxy /admin/* mcp-api:8081
    reverse_proxy /healthz mcp-api:8081
    reverse_proxy /readyz mcp-api:8081
}
```

- [ ] **Step 5: Validate and commit**

Run: `docker compose -f usfr-mcp/deployment/docker-compose.yml config`
Expected: valid config with no unresolved required variables when using a test env.
Run: `cd usfr-mcp; python -m pytest tests/test_deployment_contract.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/deployment usfr-mcp/tests/test_deployment_contract.py
git commit -m "build(mcp): add single-server production topology"
```

### Task 2: Enforce Provider, bundle, and music-classifier readiness

**Files:**
- Modify: `usfr-mcp/src/usfr_mcp/readiness.py`
- Create: `usfr-mcp/src/usfr_mcp/readiness_checks.py`
- Create: `usfr-mcp/tests/test_production_readiness.py`

**Interfaces:**
- Produces: `collect_readiness(settings: Settings) -> ReadinessReport`
- Required checks: PostgreSQL, Redis, object store, runtime digest, copied-USFR ready, OpenAI config, RunningHub config, audio classifier, OAuth signing, Caddy public URL.

- [ ] **Step 1: Write fail-closed tests**

```python
def test_music_route_readiness_fails_without_classifier(settings):
    settings.audio_classifier_endpoint = None
    report = collect_readiness(settings)
    assert report.ready is False
    assert report.checks["uploaded_audio_classifier"].status == "missing"

def test_runtime_digest_mismatch_blocks_readiness(settings, runtime_manifest, changed_file):
    assert collect_readiness(settings).checks["runtime_bundle"].status == "digest_mismatch"
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_production_readiness.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement readiness probes**

Probe dependencies with bounded timeouts and sanitized details. Require the four approved uploaded-audio classifier environment values. Recompute the imported runtime tree digest at startup and compare it with `runtime-origin.json`.

```python
def collect_readiness(settings: Settings) -> ReadinessReport:
    checks = {
        "postgres": check_postgres(), "redis": check_redis(),
        "runtime_bundle": check_runtime_digest(), "usfr": check_usfr_ready(),
        "uploaded_audio_classifier": check_audio_classifier(settings),
    }
    return ReadinessReport(checks=checks)
```

- [ ] **Step 4: Add route-aware readiness**

Global `/readyz` requires all capabilities needed for enabled production routes. Preview additionally returns a typed blocker when a specific requested route is unavailable, without exposing endpoints or tokens.

```python
def require_route_ready(route: ReplicationRoute, report: ReadinessReport) -> None:
    for capability in ROUTE_CAPABILITIES[route]:
        if not report.checks[capability].passed:
            raise RouteCapabilityUnavailable(capability)
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_production_readiness.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/readiness.py usfr-mcp/src/usfr_mcp/readiness_checks.py usfr-mcp/tests/test_production_readiness.py
git commit -m "feat(mcp): fail readiness on missing production capabilities"
```

### Task 3: Add backup, restore, cleanup, and restart recovery

**Files:**
- Create: `usfr-mcp/scripts/backup_control_plane.py`
- Create: `usfr-mcp/scripts/restore_control_plane.py`
- Create: `usfr-mcp/src/usfr_mcp/recovery/reconciler.py`
- Create: `usfr-mcp/tests/test_restart_recovery.py`
- Create: `usfr-mcp/docs/operations.md`

**Interfaces:**
- Commands: `python scripts/backup_control_plane.py`, `python scripts/restore_control_plane.py --backup backups/2026-08-04T000000Z`
- Produces: `reconcile_after_startup() -> RecoverySummary`

- [ ] **Step 1: Write restart tests**

```python
def test_restart_does_not_duplicate_paid_job(recovery, ambiguous_child, fake_usfr):
    summary = recovery.reconcile_after_startup()
    assert summary.reconciled == 1
    assert fake_usfr.create_calls == 0

def test_backup_manifest_binds_database_and_runtime_digests(backup):
    manifest = backup.run()
    assert len(manifest.database_dump_sha256) == 64
    assert len(manifest.runtime_tree_sha256) == 64
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_restart_recovery.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement recovery**

On startup, scan non-terminal replications and batch items. Poll existing copied-USFR Jobs using stored capabilities; never call create for an item with a USFR job ID or Provider attempt. Resume queued scheduling only after authorization and usage reservations validate.

```python
def reconcile_after_startup() -> RecoverySummary:
    for item in repository.non_terminal_items():
        if item.usfr_job_id:
            reconcile_existing_job(item)
        elif item.state == "queued":
            scheduler.requeue_if_authorized(item)
    return repository.recovery_summary()
```

- [ ] **Step 4: Implement backups**

Create a PostgreSQL dump plus a signed manifest containing schema version, runtime digest, application version, object-prefix inventory digest, and timestamp. Do not include `.env` or decrypted secrets. Document daily backup and quarterly restore drill commands.

```python
manifest = BackupManifest(
    schema_revision=current_alembic_revision(),
    database_dump_sha256=sha256_file(dump_path),
    runtime_tree_sha256=runtime_origin.runtime_tree_sha256,
    object_inventory_sha256=object_store.inventory_digest("persistent/"),
)
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_restart_recovery.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/scripts/backup_control_plane.py usfr-mcp/scripts/restore_control_plane.py usfr-mcp/src/usfr_mcp/recovery usfr-mcp/tests/test_restart_recovery.py usfr-mcp/docs/operations.md
git commit -m "feat(mcp): add backup and restart reconciliation"
```

### Task 4: Build deterministic no-provider E2E coverage

**Files:**
- Create: `usfr-mcp/validation/e2e/fake_usfr.py`
- Create: `usfr-mcp/validation/e2e/driver.py`
- Create: `usfr-mcp/tests/test_mcp_e2e_contract.py`

**Interfaces:**
- Command: `python -m validation.e2e.driver`

- [ ] **Step 1: Write the E2E contract test**

Cover OAuth login, upload completion, Source Master creation, single preview/confirmation, script and storyboard review, final result, explicit 20-song batch preview, Pilot final approval, five-way scheduling, one definitive failure, one ambiguous Provider state, retry/reconciliation, usage settlement, and ownership isolation.

```python
def test_complete_mcp_contract(e2e):
    user = e2e.create_user("operator")
    source = e2e.upload_source(user, "source.mp4")
    single = e2e.run_single_to_success(user, source)
    assert single.final_sha256

    batch = e2e.preview_song_batch(user, source, count=20)
    assert batch.task_count == 20
    assert batch.cartesian_products == 0
    created = e2e.confirm_batch(user, batch)
    assert e2e.provider_create_count(created.id) == 1
    e2e.approve_pilot_to_final(created.id)
    e2e.run_batch_until_idle(created.id, fail_ordinal=7, ambiguous_ordinal=9)
    snapshot = e2e.get_batch(created.id)
    assert snapshot.max_observed_concurrency == 5
    assert snapshot.failed_count == 1
    assert snapshot.ambiguous_count == 1
    assert e2e.secret_scan().findings == []
```

- [ ] **Step 2: Run the test**

Run: `cd usfr-mcp; python -m pytest tests/test_mcp_e2e_contract.py -v`
Expected: FAIL before the driver exists.

- [ ] **Step 3: Implement deterministic adapters**

The fake copied-USFR server must emit real state transitions and immutable sample Markdown/PNG/MP4 artifacts but zero external Provider calls. Record every create/review/artifact request so assertions can prove no post-Pilot child starts early and no Cartesian output is generated.

```python
class FakeUsfrService:
    def create_job(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("create", payload))
        return self.jobs.create(payload, state="SCRIPT_AWAITING_APPROVAL")

    def provider_create_count(self) -> int:
        return sum(1 for kind, _ in self.calls if kind == "provider_create")
```

- [ ] **Step 4: Run E2E**

Run: `docker compose -f usfr-mcp/deployment/docker-compose.yml --profile e2e up --build --abort-on-container-exit --exit-code-from e2e`
Expected: exit 0; exactly 20 batch items, exactly one Pilot before approval, maximum five concurrent children, and zero leaked secrets.

- [ ] **Step 5: Commit**

```powershell
git add usfr-mcp/validation usfr-mcp/tests/test_mcp_e2e_contract.py usfr-mcp/deployment/docker-compose.yml
git commit -m "test(mcp): add deterministic end-to-end workflow"
```

### Task 5: Run real Shadow acceptance and prepare internal rollout

**Files:**
- Create: `usfr-mcp/validation/shadow/case_catalog.json`
- Create: `usfr-mcp/validation/shadow/run_shadow.py`
- Create: `usfr-mcp/docs/internal-rollout.md`
- Create: `usfr-mcp/docs/incident-runbook.md`

**Interfaces:**
- Command: `python -m validation.shadow.run_shadow --catalog validation/shadow/case_catalog.json`

- [ ] **Step 1: Define the fixed Shadow catalog**

Include at minimum: one physical-product single, one model replacement single, one song replacement single, one language-only single, one generated UI case, one opaque UI case, one tail case, one 5-person batch, one 5-song batch, one 5-language batch, one explicit paired people+song batch, one partial-failure batch, and one restart/reconciliation case.

- [ ] **Step 2: Implement result capture**

For each case record input/manifest/runtime/provider/model digests, Provider task IDs, elapsed/provider time, cost estimate/actual, approval counts, child concurrency, final SHA, QC result, and sanitized errors. Fail the run on secret leakage, unexpected output count, early child start, duplicate paid attempt, or budget violation.

```python
def evaluate_case(case: ShadowCase, result: ShadowResult) -> None:
    assert result.output_count == case.expected_output_count
    assert result.early_child_provider_calls == 0
    assert result.duplicate_paid_attempts == 0
    assert result.secret_findings == []
```

- [ ] **Step 3: Execute single and five-way real tests**

Run: `cd usfr-mcp; python -m validation.shadow.run_shadow --catalog validation/shadow/case_catalog.json`
Expected: all hard gates pass; results are diagnostic until manually accepted for internal use.

- [ ] **Step 4: Complete operational review**

Verify HTTPS, OAuth callback, Provider budgets, OSS lifecycle, PostgreSQL backup, Caddy renewal, alert delivery, 70/90/100 threshold behavior, account disable, asset transfer, and incident stop controls. Document exact commands in the two runbooks.

- [ ] **Step 5: Roll out gradually**

Start with two employees for three working days, then five employees, then at most 20 after error rate, duplicate Provider attempts, budget accounting, and final delivery remain within the approved gates. Keep concurrency at five until observed CPU, network, Provider-rate, and cost evidence supports an increase.

- [ ] **Step 6: Commit**

```powershell
git add usfr-mcp/validation/shadow usfr-mcp/docs/internal-rollout.md usfr-mcp/docs/incident-runbook.md
git commit -m "docs(mcp): add shadow validation and rollout runbooks"
```

### Task 6: Final verification gate

**Files:**
- Create: `usfr-mcp/scripts/verify_release.py`
- Create: `usfr-mcp/tests/test_release_gate.py`

**Interfaces:**
- Command: `python scripts/verify_release.py`

- [ ] **Step 1: Write release-gate assertions**

The gate must verify: clean runtime digest, local Skill hash unchanged from the recorded baseline, migration head, complete test suite, Ruff, Docker config, deterministic E2E, required readiness, backup restore drill receipt, Shadow report presence, no secret scan findings, and no paid duplicate-attempt findings.

```python
def test_release_gate_has_all_hard_requirements(release_verifier):
    report = release_verifier.run()
    assert set(report.checks) == {
        "runtime_digest", "local_skill_digest", "migration_head", "pytest",
        "ruff", "docker_config", "deterministic_e2e", "readiness",
        "backup_restore_receipt", "shadow_report", "secret_scan",
        "duplicate_paid_attempts",
    }
    assert report.release_ready == all(item.passed for item in report.checks.values())
```

- [ ] **Step 2: Implement the gate**

Emit one canonical JSON report and exit non-zero on any missing or failed check. Never downgrade missing real Provider/classifier evidence to a warning for production readiness.

```python
def main() -> int:
    report = ReleaseVerifier.from_environment().run()
    print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    return 0 if report.release_ready else 1
```

- [ ] **Step 3: Run all verification**

Run: `cd usfr-mcp; python -m pytest -q`
Expected: PASS.
Run: `cd usfr-mcp; python -m ruff check src tests validation scripts tools`
Expected: `All checks passed!`
Run: `cd usfr-mcp; python scripts/verify_release.py`
Expected: exit 0 and `"release_ready": true` only after real Shadow evidence is present.

- [ ] **Step 4: Commit**

```powershell
git add usfr-mcp/scripts/verify_release.py usfr-mcp/tests/test_release_gate.py
git commit -m "test(mcp): add production release verification gate"
```
