# USFR MCP Source Library and Single Replication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure media upload, owner-isolated Source Masters and analysis-cache reuse, then deliver the complete single-replication workflow through MCP.

**Architecture:** MCP-managed assets are uploaded to private OSS/MinIO keys and recorded in PostgreSQL. The control plane creates copied-USFR Jobs through the public `/api/v1/jobs` surface, stores the one-time capability encrypted/server-side, and projects review artifacts and final results back through authorized MCP resources.

**Tech Stack:** Python 3.12, FastAPI, MCP SDK, SQLAlchemy, PostgreSQL, boto3/OSS, httpx, pytest.

## Global Constraints

- Eight public slots; `background_music` maps to copied-USFR `audio`.
- Exact source reuse is owner-scoped and version-scoped.
- No client-local path is persisted as media authority.
- No formal Job or paid call before deterministic summary confirmation.
- Do not expose copied-USFR capability tokens.

---

### Task 1: Implement private upload sessions and immutable asset admission

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/storage/object_store.py`
- Create: `usfr-mcp/src/usfr_mcp/storage/uploads.py`
- Create: `usfr-mcp/src/usfr_mcp/tools/uploads.py`
- Create: `usfr-mcp/tests/test_uploads.py`

**Interfaces:**
- Produces: `create_upload_session(principal, slot, filename, content_type, size_bytes, sha256) -> UploadSession`
- Produces: `complete_upload(principal, upload_id) -> AssetDescriptor`
- MCP tools: `create_upload_session`, `complete_asset_upload`

- [ ] **Step 1: Write failing ownership and hash tests**

```python
def test_complete_upload_rejects_mismatched_sha(service, user, uploaded_object):
    uploaded_object.metadata["sha256"] = "0" * 64
    with pytest.raises(UploadIntegrityError):
        service.complete_upload(user, uploaded_object.upload_id)

def test_other_user_cannot_complete_upload(service, user_a_upload, user_b):
    with pytest.raises(NotFoundError):
        service.complete_upload(user_b, user_a_upload.id)
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_uploads.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement upload lifecycle**

Use keys `uploads/{user_id}/{upload_id}/{safe_filename}`. Verify completion state, exact key, MIME, size, and streamed SHA-256 before creating an immutable asset row. Return signed upload URLs with short expiry; never return OSS credentials.

```python
def complete_upload(principal: Principal, upload_id: UUID) -> AssetDescriptor:
    upload = owned_upload(upload_id, principal.user_id)
    metadata = object_store.verify_completed(upload.object_key)
    verify_asset_metadata(upload, metadata)
    return persist_asset(upload, metadata)
```

- [ ] **Step 4: Add slot validators**

Enforce video/image/audio/URL roles by declared slot. `background_music` accepts one audio asset per single Job. `source_video` enforces the copied runtime's maximum duration before preview can succeed.

```python
SLOT_MEDIA = {"source_video": "video", "background_music": "audio", "new_model_image": "image"}

def validate_slot(slot: str, asset: AssetDescriptor) -> None:
    if asset.media_kind != SLOT_MEDIA[slot]:
        raise SlotMediaTypeError(slot)
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_uploads.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/storage usfr-mcp/src/usfr_mcp/tools/uploads.py usfr-mcp/tests/test_uploads.py
git commit -m "feat(mcp): add immutable private asset uploads"
```

### Task 2: Build owner-isolated Source Masters and analysis-cache indexing

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/source_library/service.py`
- Create: `usfr-mcp/src/usfr_mcp/source_library/cache_keys.py`
- Create: `usfr-mcp/src/usfr_mcp/tools/sources.py`
- Create: `usfr-mcp/tests/test_source_library.py`

**Interfaces:**
- Produces: `get_or_create_source_master(owner_id: UUID, source: Asset) -> SourceMaster`
- Produces: `find_analysis_cache(owner_id, source_sha256, profile, model_sha256, contract_version) -> AnalysisCache | None`
- MCP tools: `list_source_masters`, `get_source_master`, `delete_source_master`

- [ ] **Step 1: Write cache isolation tests**

```python
def test_same_owner_exact_version_hits_cache(source_service, owner, source_asset, analysis_version):
    first = source_service.create_cache(owner.id, source_asset, analysis_version)
    assert source_service.find_cache(owner.id, source_asset.sha256, analysis_version).id == first.id

def test_other_owner_cannot_probe_same_sha(source_service, owner_a_cache, owner_b):
    assert source_service.find_cache(
        owner_b.id, owner_a_cache.source_sha256, owner_a_cache.analysis_version
    ) is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd usfr-mcp; python -m pytest tests/test_source_library.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement Source Master identity and cache keys**

Use `(owner_user_id, source_sha256)` for Source Master uniqueness and the full approved analysis-version tuple for cache uniqueness. Promote an admitted source upload to `persistent/{owner_user_id}/sources/{source_master_id}/original` with an immutable publication receipt; keep it until owner/admin deletion. Public list/get responses must omit cross-user existence hints and internal object keys.

```python
def get_or_create_source_master(owner_id: UUID, source: Asset) -> SourceMaster:
    master = repository.find_source(owner_id, source.sha256)
    return master or repository.create_source(owner_id, object_store.promote_source(source))
```

- [ ] **Step 4: Implement deletion semantics**

Deleting a Source Master removes the source object after ownership and reference checks, marks future direct reuse unavailable, but keeps analysis cache metadata, scripts, storyboards, and final outputs unless the caller separately requests allowed artifact deletion.

```python
def delete_source_master(owner_id: UUID, source_id: UUID) -> None:
    source = repository.require_owned_source(owner_id, source_id)
    object_store.delete(source.object_key)
    repository.mark_source_deleted(source.id)
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_source_library.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/source_library usfr-mcp/src/usfr_mcp/tools/sources.py usfr-mcp/tests/test_source_library.py
git commit -m "feat(mcp): add owner-isolated source library"
```

### Task 3: Add the copied-runtime Analysis Cache Bridge

**Files:**
- Create: `usfr-runtime/server/analysis_cache_bridge.py`
- Create: `usfr-runtime/server/internal_api_models.py`
- Create: `usfr-runtime/server/internal_fastapi_router.py`
- Modify: `usfr-runtime/server/deployment_bootstrap.py`
- Modify: `usfr-runtime/server/ephemeral_driver.py`
- Create: `usfr-runtime/tests/test_analysis_cache_bridge.py`
- Create: `usfr-mcp/src/usfr_mcp/source_library/runtime_bridge.py`
- Create: `usfr-mcp/tests/test_analysis_cache_runtime_bridge.py`

**Interfaces:**
- Copied-runtime internal create field: `analysis_cache_ref: InternalAnalysisCacheRef | None`
- Produces copied-runtime artifact: `reusable_source_analysis/v1`
- Produces: `publish_analysis_cache(replication_id) -> AnalysisCache`
- Produces: `build_runtime_cache_ref(cache_id) -> InternalAnalysisCacheRef`

- [ ] **Step 1: Write first-run publication and reuse tests**

```python
def test_first_run_publishes_reusable_analysis(runtime, completed_analysis_job):
    artifact = runtime.publish_reusable_analysis(completed_analysis_job.id)
    assert artifact.contract == "reusable_source_analysis/v1"
    assert artifact.source_sha256 == completed_analysis_job.source_sha256

def test_cache_ref_skips_probe_and_dynamics(runtime, valid_cache_ref):
    job = runtime.create_internal_job(analysis_cache_ref=valid_cache_ref)
    assert job.stage_status("probe_source") == "SUCCEEDED"
    assert job.stage_status("analyze_dynamics") == "SUCCEEDED"
    assert runtime.provider_calls == 0
```

- [ ] **Step 2: Run both test files**

Run: `cd usfr-runtime; python -m pytest tests/test_analysis_cache_bridge.py -v`
Expected: FAIL.
Run: `cd usfr-mcp; python -m pytest tests/test_analysis_cache_runtime_bridge.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement immutable cache publication**

After the first valid dynamics/audio analysis checkpoint, publish one canonical bundle containing probe output, source dynamics analysis, audio contract, source overlay contract, evidence digests, analysis profile, model SHA values, contract version, source SHA, and bundle SHA. The MCP control plane verifies it and promotes the bytes to `persistent/{owner_user_id}/sources/{source_master_id}/analysis/{analysis_version}/{bundle_sha256}.json`. Publish through the existing artifact store; never serialize worker-local paths.

```python
def build_reusable_analysis(stage_outputs: Mapping[str, object]) -> ReusableSourceAnalysis:
    bundle = ReusableSourceAnalysis.from_stage_outputs(stage_outputs)
    bundle.validate_complete()
    return bundle.with_sha256(bundle.canonical_sha256())
```

- [ ] **Step 4: Implement validated cache admission**

Add an internal-only `/internal/v1/jobs` request path that accepts the normal public job fields plus `analysis_cache_ref`. Do not add that field to `PublicJobCreate`. Verify a control-plane service credential, object key prefix, publication receipt, bytes, MIME, source SHA, analysis profile, model SHA, contract version, and bundle SHA. On success, materialize the bundle into the copied runtime's probe/dynamics stage outputs and checkpoints. Caddy must never route `/internal`; any mismatch falls closed and runs no Provider call.

```python
@router.post("/internal/v1/jobs", status_code=202)
def create_internal_job(payload: InternalJobCreate, _: ServicePrincipal = Depends(require_control_plane)):
    cached = cache_bridge.verify_and_load(payload.analysis_cache_ref) if payload.analysis_cache_ref else None
    return service.create_job(payload.public_fields(), precompleted_analysis=cached)
```

- [ ] **Step 5: Connect the Source Library**

When a first Job reaches the reusable-analysis publication point, store the immutable OSS artifact reference in the owner-scoped AnalysisCache row. On an exact cache hit, pass the internal reference during copied-runtime Job creation. Do not expose the internal field in public MCP schemas or user-visible summaries.

```python
def resolve_runtime_analysis(owner_id: UUID, source: SourceMaster, version: AnalysisVersion):
    cache = source_repository.find_cache(owner_id, source.source_sha256, version)
    return build_internal_cache_ref(cache) if cache else None
```

- [ ] **Step 6: Verify regression and commit**

Run: `cd usfr-runtime; python -m pytest tests/test_analysis_cache_bridge.py tests/test_server_fastapi_router.py tests/test_ephemeral_runtime.py -q`
Expected: PASS.
Run: `cd usfr-mcp; python -m pytest tests/test_analysis_cache_runtime_bridge.py tests/test_source_library.py -q`
Expected: PASS.

```powershell
git add usfr-runtime/server/analysis_cache_bridge.py usfr-runtime/server/internal_api_models.py usfr-runtime/server/internal_fastapi_router.py usfr-runtime/server/deployment_bootstrap.py usfr-runtime/server/ephemeral_driver.py usfr-runtime/tests/test_analysis_cache_bridge.py usfr-mcp/src/usfr_mcp/source_library/runtime_bridge.py usfr-mcp/tests/test_analysis_cache_runtime_bridge.py
git commit -m "feat(runtime): reuse verified source analysis caches"
```

### Task 4: Implement the copied-USFR public API client and capability vault

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/usfr_client/client.py`
- Create: `usfr-mcp/src/usfr_mcp/usfr_client/models.py`
- Create: `usfr-mcp/src/usfr_mcp/usfr_client/capability_vault.py`
- Create: `usfr-mcp/tests/test_usfr_client.py`

**Interfaces:**
- Produces: `UsfrClient.create_job(payload: PublicJobCreate) -> CreatedUsfrJob`
- Produces: `UsfrClient.get_job(handle: InternalJobHandle) -> UsfrJobSnapshot`
- Produces: `UsfrClient.review(handle, action, content=None) -> UsfrJobSnapshot`
- Produces: `UsfrClient.fetch_artifact(handle, logical_name) -> bytes`

- [ ] **Step 1: Write exact-payload and secret tests**

```python
def test_background_music_maps_to_audio(usfr_client, fake_http, asset_urls):
    usfr_client.create_job(PublicJobCreate(background_music=asset_urls.music, **asset_urls.base))
    assert fake_http.last_json["audio"] == asset_urls.music
    assert "background_music" not in fake_http.last_json

def test_created_job_public_projection_hides_capability(usfr_client, fake_http, minimal_request):
    result = usfr_client.create_job(minimal_request)
    assert result.public.job_handle
    assert "capability" not in json.dumps(result.public.model_dump()).lower()
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_usfr_client.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement API methods**

Call only the copied runtime's public endpoints: `POST /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`, `GET /api/v1/jobs/{job_id}/artifacts/{logical_name}`, and `POST /api/v1/jobs/{job_id}/review`. Apply strict timeouts and preserve typed public errors.

```python
class UsfrClient:
    def create_job(self, payload: PublicJobCreate) -> CreatedUsfrJob:
        response = self.http.post("/api/v1/jobs", json=payload.model_dump(mode="json"))
        return CreatedUsfrJob.model_validate(response.raise_for_status().json())
```

- [ ] **Step 4: Implement capability vault**

Encrypt the one-time USFR capability using the control-plane secret-encryption key before storing it. Decrypt only inside the HTTP client, never in tool handlers or logs. Rotate the encryption key through a versioned key identifier.

```python
def seal_capability(token: str, key: Fernet, key_id: str) -> SealedSecret:
    return SealedSecret(key_id=key_id, ciphertext=key.encrypt(token.encode("utf-8")))
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_usfr_client.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/usfr_client usfr-mcp/tests/test_usfr_client.py
git commit -m "feat(mcp): integrate copied USFR public API"
```

### Task 5: Implement deterministic single-job preview and confirmation

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/replication/models.py`
- Create: `usfr-mcp/src/usfr_mcp/replication/ports.py`
- Create: `usfr-mcp/src/usfr_mcp/replication/preview.py`
- Create: `usfr-mcp/src/usfr_mcp/replication/service.py`
- Create: `usfr-mcp/src/usfr_mcp/tools/replication.py`
- Create: `usfr-mcp/tests/test_single_replication.py`

**Interfaces:**
- MCP tool: `preview_replication(input) -> ReplicationPreview`
- MCP tool: `confirm_and_create_replication(preview_id, expected_sha256) -> ReplicationHandle`
- `ReplicationPreview.suggested_mode` is `single`, `batch`, or `clarification_required`.
- Produces protocol: `UsageAuthorizer.reserve(user_id, subject_id, output_count, estimate_cny) -> UsageReservationHandle`

- [ ] **Step 1: Write preview gate tests**

```python
def test_single_preview_creates_no_usfr_job(service, valid_single_input, fake_usfr):
    preview = service.preview(valid_single_input)
    assert preview.suggested_mode == "single"
    assert fake_usfr.create_calls == 0

def test_confirmation_requires_exact_preview_sha(service, preview):
    with pytest.raises(PreviewChangedError):
        service.confirm(preview.id, expected_sha256="0" * 64)
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_single_replication.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement canonical preview**

Canonicalize asset IDs, source master, output language, mode, and route summary. Store the immutable preview payload and SHA. The Chinese execution summary must state output count, changed slots, preserved slots, and that no Cartesian combinations are performed.

```python
def build_preview(request: ReplicationPreviewInput) -> ReplicationPreview:
    canonical = canonicalize_preview(request)
    return ReplicationPreview(payload=canonical, sha256=sha256_json(canonical), execution_summary=render_summary(canonical))
```

- [ ] **Step 4: Implement confirmation**

In one transaction, verify preview ownership/status/SHA, create a replication row, call the injected `UsageAuthorizer`, build the copied-USFR payload, create exactly one USFR Job, and save the encrypted capability. Provide an allow-all development adapter only for unit tests and explicit local mode; production readiness rejects it. Roll back local state and release reservations if job creation fails definitively.

```python
def confirm(self, principal: Principal, preview_id: UUID, expected_sha256: str) -> ReplicationHandle:
    preview = self.previews.require_confirmable(principal.user_id, preview_id, expected_sha256)
    reservation = self.usage.reserve(principal.user_id, preview.id, 1, preview.estimate_cny)
    return self._create_usfr_job(preview, reservation)
```

- [ ] **Step 5: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_single_replication.py -v`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/replication usfr-mcp/src/usfr_mcp/tools/replication.py usfr-mcp/tests/test_single_replication.py
git commit -m "feat(mcp): add confirmed single replication flow"
```

### Task 6: Project script, storyboard, revisions, and final MP4 through MCP

**Files:**
- Create: `usfr-mcp/src/usfr_mcp/replication/reviews.py`
- Create: `usfr-mcp/src/usfr_mcp/replication/resources.py`
- Create: `usfr-mcp/src/usfr_mcp/replication/archiver.py`
- Modify: `usfr-mcp/src/usfr_mcp/tools/replication.py`
- Create: `usfr-mcp/tests/test_replication_reviews.py`

**Interfaces:**
- Tools: `get_replication`, `revise_script`, `approve_script`, `revise_storyboard`, `approve_storyboard`
- Resources: `usfr://replications/{handle}/script`, `usfr://replications/{handle}/storyboard/{page}`, `usfr://replications/{handle}/result`

- [ ] **Step 1: Write review-state tests**

```python
def test_script_approval_calls_exact_current_review(replication_service, awaiting_script):
    snapshot = replication_service.approve_script(awaiting_script.handle)
    assert snapshot.state != "SCRIPT_AWAITING_APPROVAL"

def test_result_resource_is_owner_only(resource_service, user_b, user_a_result):
    with pytest.raises(NotFoundError):
        resource_service.read_result(user_b, user_a_result.handle)

def test_approved_artifacts_are_archived_permanently(archiver, approved_replication):
    receipt = archiver.archive_current(approved_replication.id)
    assert receipt.script_sha256 == approved_replication.script_sha256
    assert receipt.storyboard_sha256s == approved_replication.storyboard_sha256s
    assert receipt.final_mp4_sha256 == approved_replication.final_mp4_sha256
```

- [ ] **Step 2: Run tests**

Run: `cd usfr-mcp; python -m pytest tests/test_replication_reviews.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement state projection**

Map copied-USFR states into stable MCP states: `queued`, `analyzing`, `awaiting_script`, `awaiting_storyboard`, `generating`, `qc`, `succeeded`, `failed`, `provider_ambiguous`. Return the smallest valid next action.

```python
STATE_MAP = {"SCRIPT_AWAITING_APPROVAL": "awaiting_script", "STORYBOARD_AWAITING_APPROVAL": "awaiting_storyboard", "SUCCEEDED": "succeeded"}

def project_state(snapshot: UsfrJobSnapshot) -> str:
    return STATE_MAP.get(snapshot.state, "generating")
```

- [ ] **Step 4: Implement resources and revisions**

Proxy only the actual current Markdown/PNG/final MP4 artifacts after ownership checks. Revision instructions call public `review` with `action=revise`; approvals call `action=approve`. Never persist signed preview URLs longer than their expiry.

```python
def approve_script(principal: Principal, handle: str) -> ReplicationSnapshot:
    replication = repository.require_owned_replication(principal.user_id, handle)
    return project(client.review(replication.internal_handle, action="approve"))
```

- [ ] **Step 5: Archive permanent user artifacts**

On script approval, copy the exact Markdown bytes to `persistent/{owner_user_id}/replications/{replication_id}/script/{sha256}.md`. On storyboard approval, copy each exact PNG page to the matching storyboard prefix. On success, copy the final MP4 to `persistent/{owner_user_id}/replications/{replication_id}/final/{sha256}.mp4`. Verify bytes and publication receipts before updating artifact rows. Keep historical approved versions; do not archive internal control sheets, prompts, Provider downloads, or temporary QC files.

```python
def archive_bytes(owner_id: UUID, replication_id: UUID, kind: str, payload: bytes, suffix: str) -> Artifact:
    digest = hashlib.sha256(payload).hexdigest()
    key = f"persistent/{owner_id}/replications/{replication_id}/{kind}/{digest}.{suffix}"
    receipt = object_store.publish_verified(key, payload)
    return repository.record_artifact(replication_id, kind, digest, receipt)
```

- [ ] **Step 6: Verify and commit**

Run: `cd usfr-mcp; python -m pytest tests/test_replication_reviews.py -v`
Expected: PASS.
Run: `cd usfr-mcp; python -m pytest tests/test_uploads.py tests/test_source_library.py tests/test_usfr_client.py tests/test_single_replication.py tests/test_replication_reviews.py -q`
Expected: PASS.

```powershell
git add usfr-mcp/src/usfr_mcp/replication usfr-mcp/src/usfr_mcp/tools/replication.py usfr-mcp/tests/test_replication_reviews.py
git commit -m "feat(mcp): expose single-job reviews and results"
```
