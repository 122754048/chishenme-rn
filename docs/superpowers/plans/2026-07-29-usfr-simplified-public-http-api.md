# USFR Simplified Public HTTP API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-endpoint public FastAPI façade that accepts permanent OSS URLs, imports media into job-scoped temporary storage, preserves the existing USFR engine, exposes only script/storyboard review, publishes final MP4 files to permanent Alibaba Cloud OSS, passes real HTTP tests, and produces a refreshed Windows deployment ZIP.

**Architecture:** Keep the current Redis job/CAS, artifact, review, provider, worker and quality contracts behind a new public façade. Add one durable pre-semantic `import_sources` worker operation that converts public URLs into the existing immutable seven-slot manifest, then run the unchanged semantic pipeline. Keep internal endpoints out of the public application and project internal state into five public statuses.

**Tech Stack:** Python 3.11, FastAPI 0.116.1, Pydantic 2.11.9, Redis 7.4, Redis Streams, boto3/MinIO, Alibaba Cloud OSS Python SDK, FFmpeg/ffprobe, pytest, Docker Compose.

## Global Constraints

- Public OpenAPI exposes exactly `POST /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`, and `POST /api/v1/jobs/{job_id}/review`.
- `source_video` is required and at least one real change input is required.
- Media request values are permanent HTTPS OSS URLs; `app_store_url` is an official Apple App Store or Google Play URL.
- Source video duration is at most 30 seconds and is rejected before GPT, RunningHub, Seedance or other paid work.
- The API never accepts or returns client SHA, size, MIME, duration, revision, CAS version, object key, upload scope, Provider parameters or Provider task IDs.
- Every route pauses for editable script review and storyboard review, including language-only and local/opaque routes.
- UI operation video defaults to muted visual replacement; screenshots, operation video, or both may be supplied.
- Original OSS objects are never deleted, moved or overwritten by USFR.
- Temporary MinIO objects expire; only the verified final MP4 is permanent.
- Token remains job-scoped and only its HMAC digest is stored.
- Duplicate create/review requests cannot create duplicate paid Provider work.
- Do not include API keys, tokens, local runs, caches, tests or generated media in the release ZIP.

---

### Task 1: Public request models, stable token derivation and idempotency authority

**Files:**
- Create: `server/public_api_models.py`
- Create: `server/public_idempotency.py`
- Modify: `server/capability_tokens.py`
- Modify: `server/redis_job_store.py`
- Test: `tests/test_public_idempotency.py`
- Test: `tests/test_capability_tokens.py`

**Interfaces:**
- Consumes: deployment capability secret and Redis client.
- Produces: `PublicJobCreate`, `PublicReviewRequest`, `derive_capability(secret, job_id, idempotency_key)`, `RedisIdempotencyStore.claim(...)`, and `RedisEphemeralJobStore.create_job(..., job_id, initial_state)`.

- [ ] **Step 1: Write failing public model tests**

```python
def test_public_job_create_requires_source_and_one_change():
    with pytest.raises(ValidationError):
        PublicJobCreate(source_video="https://bucket.oss-cn-hangzhou.aliyuncs.com/source.mp4")


def test_public_job_create_accepts_ui_video_and_screenshots_together():
    request = PublicJobCreate(
        source_video="https://bucket.oss-cn-hangzhou.aliyuncs.com/source.mp4",
        ui_screenshots=["https://bucket.oss-cn-hangzhou.aliyuncs.com/ui.png"],
        ui_operation_video="https://bucket.oss-cn-hangzhou.aliyuncs.com/ui.mp4",
    )
    assert request.ui_screenshots and request.ui_operation_video
```

- [ ] **Step 2: Run the model tests and verify failure**

Run: `python -m pytest tests/test_public_idempotency.py -q`

Expected: FAIL because `server.public_api_models` does not exist.

- [ ] **Step 3: Implement strict public models**

```python
class PublicJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_video: HttpUrl
    new_product_images: tuple[HttpUrl, ...] = ()
    new_model_images: tuple[HttpUrl, ...] = ()
    ui_screenshots: tuple[HttpUrl, ...] = ()
    app_store_url: HttpUrl | None = None
    ui_operation_video: HttpUrl | None = None
    tail_video: HttpUrl | None = None
    audio: HttpUrl | None = None
    output_language: Literal["en", "ja", "ko", "fr", "de", "es", "pt", "id", "zh"] | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not any((self.new_product_images, self.new_model_images, self.ui_screenshots,
                    self.app_store_url, self.ui_operation_video, self.tail_video,
                    self.audio, self.output_language)):
            raise ValueError("at least one change input is required")
        return self


class PublicReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "revise"]
    content: str | None = None
```

- [ ] **Step 4: Write failing deterministic-token and idempotency tests**

```python
def test_derived_capability_is_stable_and_only_digest_is_persisted():
    one = derive_capability(b"x" * 32, "job1", "5b0939ec-2a42-46c0-a95e-3a19b23495aa")
    two = derive_capability(b"x" * 32, "job1", "5b0939ec-2a42-46c0-a95e-3a19b23495aa")
    assert one == two
    assert len(one) == 43


def test_idempotency_replay_returns_same_job_and_rejects_changed_body(redis_client):
    store = RedisIdempotencyStore(redis_client, prefix="test")
    first = store.claim(key="request-1", request_sha256="a" * 64, proposed_job_id="job1", ttl_seconds=3600)
    replay = store.claim(key="request-1", request_sha256="a" * 64, proposed_job_id="job2", ttl_seconds=3600)
    assert first.job_id == replay.job_id == "job1"
    with pytest.raises(IdempotencyConflict):
        store.claim(key="request-1", request_sha256="b" * 64, proposed_job_id="job3", ttl_seconds=3600)
```

- [ ] **Step 5: Implement stable HMAC capability and Redis SET-NX claim**

```python
def derive_capability(secret: bytes, job_id: str, idempotency_key: str) -> str:
    payload = f"usfr-public-capability/v1\0{job_id}\0{idempotency_key}".encode("utf-8")
    raw = hmac.new(secret, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
```

`RedisIdempotencyStore.claim` stores only canonical request SHA, job ID and expiry. The same key and same body returns the original job. The same key and a different body raises `INVALID_REQUEST`.

- [ ] **Step 6: Allow caller-supplied job ID and initial state**

Change `RedisEphemeralJobStore.create_job` to accept:

```python
def create_job(
    self,
    *,
    slots_manifest: Mapping[str, Any],
    capability_token_hash: str,
    ttl_seconds: int,
    correlation_id: str | None = None,
    job_id: str | None = None,
    initial_state: str = "INTAKE_VALIDATED",
) -> JobSnapshot:
```

The default preserves existing callers. Public creation supplies a UUID hex job ID and `IMPORTING`.

- [ ] **Step 7: Run focused tests**

Run: `python -m pytest tests/test_public_idempotency.py tests/test_capability_tokens.py tests/test_redis_job_store.py -q`

Expected: PASS.

### Task 2: Secure durable OSS URL import operation

**Files:**
- Create: `server/remote_media_import.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/packaged_ports.py`
- Modify: `server/ephemeral_driver.py`
- Modify: `server/ephemeral_worker.py`
- Test: `tests/test_remote_media_import.py`
- Test: `tests/test_ephemeral_runtime.py`

**Interfaces:**
- Consumes: `PublicJobCreate` canonical projection in `slots_manifest.public_intake`, `S3ObjectStore`, worker temp directory and configured allowlisted OSS hosts.
- Produces: `RemoteMediaImporter.import_request(job_id, request) -> dict`, `ImportSourcesStage.run(...) -> {"slots_manifest": manifest}`, and a completed immutable seven-slot manifest.

- [ ] **Step 1: Write failing URL security tests**

```python
@pytest.mark.parametrize("url", [
    "http://bucket.oss-cn-hangzhou.aliyuncs.com/a.mp4",
    "https://127.0.0.1/a.mp4",
    "https://localhost/a.mp4",
    "https://minio:9000/a.mp4",
])
def test_import_policy_rejects_unsafe_urls(url):
    with pytest.raises(ReplicationError):
        OssUrlPolicy(["*.oss-cn-hangzhou.aliyuncs.com"]).validate(url)
```

- [ ] **Step 2: Run importer tests and verify failure**

Run: `python -m pytest tests/test_remote_media_import.py -q`

Expected: FAIL because the importer does not exist.

- [ ] **Step 3: Implement URL policy and redirect revalidation**

`OssUrlPolicy.validate` must require HTTPS, match `USFR_ALLOWED_OSS_HOSTS`, resolve DNS, reject private/loopback/link-local/reserved/multicast addresses, and re-run the same checks after every redirect. Use a redirect-disabled `urllib.request` opener and allow at most three redirects.

```python
class OssUrlPolicy:
    def validate(self, url: str) -> ValidatedUrl: ...


class RemoteMediaImporter:
    def import_request(self, *, job_id: str, request: Mapping[str, Any]) -> dict[str, Any]: ...
```

- [ ] **Step 4: Implement bounded streaming download and real media probe**

Download in 1 MiB chunks into the lease-owned temp directory. Enforce configured byte and time limits while streaming. Probe video/audio with `ffprobe`, verify images with Pillow, derive the real MIME, duration, width, height and FPS, and reject source duration above 30 seconds before returning a completion record.

```python
completion = {
    "object_key": object_key,
    "sha256": digest,
    "size_bytes": size,
    "content_type": detected_mime,
    "duration_seconds": duration,
    "status": "completed",
}
```

- [ ] **Step 5: Upload imported bytes once and bind the existing manifest**

Write media under `uploads/{job_id}/{slot_id}/{index}-{sha256}{suffix}`. Pass the resulting completion records to `bind_uploaded_slots(..., upload_scope=job_id)`, set `output_language`, force `review_route="route_2"`, and add:

```python
manifest.setdefault("extensions", {})["ui_operation_policy"] = {
    "audio_policy": "mute",
    "screenshot_assist": bool(ui_screenshots and ui_operation_video),
}
```

- [ ] **Step 6: Add `import_sources` as a pre-semantic worker operation**

`EphemeralStageDriver.enqueue_next` must special-case `snapshot.state == "IMPORTING"` and enqueue only `import_sources`. `ImportSourcesStage` returns the completed manifest. `EphemeralWorkerManager._apply_result_authority` atomically replaces `slots_manifest`, sets state to `ANALYZING`, then ordinary stage planning begins.

- [ ] **Step 7: Run focused tests**

Run: `python -m pytest tests/test_remote_media_import.py tests/test_ephemeral_runtime.py tests/test_server_intake_artifacts.py -q`

Expected: PASS, including redirect-to-private rejection and no paid-stage enqueue before import succeeds.

### Task 3: Three-endpoint public façade and public state projection

**Files:**
- Create: `server/public_fastapi_router.py`
- Create: `server/public_job_projection.py`
- Modify: `server/packaged_factory.py`
- Test: `tests/test_public_fastapi_router.py`
- Test: `tests/test_server_api_contract.py`

**Interfaces:**
- Consumes: job store, review service, object store, stage driver, idempotency store and capability secret.
- Produces: `create_public_app(...) -> FastAPI` and public JSON projections.

- [ ] **Step 1: Write failing route and OpenAPI tests**

```python
def test_public_route_set_is_exact(client):
    paths = {route.path for route in client.app.routes if isinstance(route, APIRoute)}
    assert paths == {
        "/api/v1/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/review",
    }


def test_openapi_does_not_expose_internal_contract_fields(client):
    encoded = json.dumps(client.get("/openapi.json").json())
    for forbidden in ("expected_version", "expected_sha256", "upload_scope", "object_key", "provider/reconcile"):
        assert forbidden not in encoded
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/test_public_fastapi_router.py -q`

Expected: FAIL because `create_public_app` does not exist.

- [ ] **Step 3: Implement create endpoint**

`POST /api/v1/jobs` validates `Idempotency-Key`, stores only the public intake projection, creates an `IMPORTING` job, enqueues `import_sources`, and returns exactly:

```python
return {
    "job_id": snapshot.job_id,
    "access_token": token,
    "status": "importing",
}
```

- [ ] **Step 4: Implement public status projection**

```python
PUBLIC_STATES = {
    "IMPORTING": "importing",
    "INTAKE_VALIDATED": "processing",
    "ANALYZING": "processing",
    "SUCCEEDED": "completed",
    "FAILED": "failed",
}
```

If the current script revision exists and is not approved, return `waiting_review/script` with editable content. If the current storyboard revision exists and is not approved, return `waiting_review/storyboard` with signed preview URLs. `SUCCEEDED` returns only the permanent OSS `result_url`.

- [ ] **Step 5: Implement unified review endpoint**

For `action=approve`, load the current internal revision and use its server-known SHA and current CAS version. For script `action=revise`, treat `content` as the complete updated script. For storyboard `action=revise`, treat `content` as the regeneration instruction. Reject review outside the active review state with `REVIEW_NOT_ALLOWED`.

- [ ] **Step 6: Mount only the public app in production**

Change `server.packaged_factory.build_runtime` from importing `fastapi_router.create_app` to `public_fastapi_router.create_public_app`. Keep the current internal router importable for internal compatibility tests, but do not mount it on the production public listener.

- [ ] **Step 7: Run contract tests**

Run: `python -m pytest tests/test_public_fastapi_router.py tests/test_server_api_contract.py tests/test_review_service.py -q`

Expected: PASS.

### Task 4: Mandatory script and storyboard review for every route

**Files:**
- Modify: `server/orchestrator.py`
- Modify: `server/ephemeral_driver.py`
- Modify: `server/analysis_scope.py`
- Modify: `server/intake.py`
- Modify: `SKILL.md`
- Modify: `references/fixed-input-slot-contract.md`
- Modify: `references/server-api-contract.md`
- Test: `tests/test_job_api.py`
- Test: `tests/test_analysis_scope.py`
- Test: `tests/test_skill_contract.py`

**Interfaces:**
- Consumes: completed immutable slot manifest.
- Produces: a stage plan with exactly two user review waits for language-only, generated, local-only and opaque routes.

- [ ] **Step 1: Write failing mandatory-gate tests**

```python
def test_every_route_has_script_and_storyboard_review(tmp_path):
    source = tmp_path / "source.mp4"
    ui_video = tmp_path / "ui.mp4"
    tail_video = tmp_path / "tail.mp4"
    source.write_bytes(b"source")
    ui_video.write_bytes(b"ui")
    tail_video.write_bytes(b"tail")
    manifests = (
        validate_slots({"source_video": str(source)}, output_language="ja"),
        validate_slots({"source_video": str(source), "ui_operation_video": str(ui_video)}),
        validate_slots({"source_video": str(source), "tail_video": str(tail_video)}),
    )
    for manifest in manifests:
        names = [item["name"] for item in build_stage_plan(manifest)]
        assert names.count("await_script_approval") == 1
        assert names.count("await_storyboard_approval") == 1
```

- [ ] **Step 2: Run and verify current failure**

Run: `python -m pytest tests/test_job_api.py tests/test_analysis_scope.py -q`

Expected: FAIL for language-only and non-generated routes.

- [ ] **Step 3: Normalize every admitted run to route 2 review semantics**

Remove `review_route="local_only"` from language-only intake. `build_stage_plan` must always include `build_script`, `await_script_approval`, `generate_storyboards`, and `await_storyboard_approval`; local/opaque storyboards use source or opaque frames and must not create Seedance work when generation is unnecessary.

- [ ] **Step 4: Remove language-only approval bypasses in the driver**

Replace conditions such as:

```python
if stage == "generate_storyboards" and not language_only and not snapshot.approved_script_sha256:
```

with unconditional approval checks for all routes.

- [ ] **Step 5: Update canonical documentation text**

Replace the old language-only bypass and local-only review statements with the latest rule: every run exposes editable script and storyboard review, and storyboard approval triggers autonomous remaining execution.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_job_api.py tests/test_analysis_scope.py tests/test_skill_contract.py tests/test_universal_fidelity_contract.py -q`

Expected: PASS with exactly two approval waits and no extra user gate.

### Task 5: UI screenshots, UI operation video and combined UI replacement

**Files:**
- Modify: `scripts/bind_input_slots.py`
- Modify: `server/analysis_scope.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/audio_route_guard.py`
- Modify: `scripts/timeline_splice.py`
- Modify: `SKILL.md`
- Modify: `references/fixed-input-slot-contract.md`
- Test: `tests/test_fixed_input_slot_contract.py`
- Test: `tests/test_timeline_splice_real_media.py`
- Test: `tests/test_source_ui_interval_contract.py`

**Interfaces:**
- Consumes: `ui_screenshot`, `ui_operation_video`, source UI intervals and `extensions.ui_operation_policy`.
- Produces: direct replacement for operation-video routes, screenshot-guided correction when both inputs exist, exact source UI interval removal, muted replacement audio and unchanged master audio timeline.

- [ ] **Step 1: Write failing route tests for the three UI cases**

```python
def test_ui_routes_distinguish_screenshot_operation_and_combined():
    base = {name: False for name in SLOT_ORDER}
    screenshot = dict(base, source_video=True, ui_screenshot=True)
    operation = dict(base, source_video=True, ui_operation_video=True)
    combined = dict(base, source_video=True, ui_screenshot=True, ui_operation_video=True)
    assert _route_defaults(screenshot)["ui"] == "generated_ui_demo"
    assert _route_defaults(operation)["ui"] == "opaque_ui_demo"
    assert _route_defaults(combined)["ui"] == "opaque_ui_demo"
    request = PublicJobCreate(
        source_video="https://bucket.oss-cn-hangzhou.aliyuncs.com/source.mp4",
        ui_screenshots=["https://bucket.oss-cn-hangzhou.aliyuncs.com/ui.png"],
        ui_operation_video="https://bucket.oss-cn-hangzhou.aliyuncs.com/ui.mp4",
    )
    assert request.ui_screenshots and request.ui_operation_video
```

- [ ] **Step 2: Write failing real-media tests for old-UI removal and mute**

Create a colored source UI interval with an audible tone and a differently colored UI operation clip with a second tone. Assert output pixels contain no old UI at the replaced interval and output audio contains the master track but not the operation-video tone.

- [ ] **Step 3: Keep deterministic route authority and add combined evidence**

Keep `opaque_ui_demo` as the direct-operation carrier so UI media never reaches Seedance. When screenshots are also supplied, retain their immutable hashes as UI visual truth and set `screenshot_assist=true`; do not discard them merely because operation video exists.

- [ ] **Step 4: Implement bounded UI operation fit**

Within already identified source UI intervals only: remove leading/trailing idle or black padding, split on deterministic operation boundaries when multiple source UI intervals exist, and allow bounded playback adjustment configured by `USFR_UI_OPERATION_MIN_RATE=0.85` and `USFR_UI_OPERATION_MAX_RATE=1.20`. If the requested mapping cannot fit within those limits, fail before final assembly instead of hiding the mismatch.

- [ ] **Step 5: Mute operation video and preserve master audio**

Set the default UI operation audio policy to `mute`. Timeline assembly must replace the UI video layer while retaining the source/newly generated master narration, singing, TTS and BGM timeline. No UI operation clip audio reaches the final mix unless a future explicit contract enables it.

- [ ] **Step 6: Use screenshots only as bounded visual truth**

When both are supplied, compare/rebuild only the identified UI ROI and required static states. The operation video remains the motion authority. The screenshot may fill missing first/last/static states and calibrate copy/layout, but cannot trigger a global ShotCraft, Remotion or Seedance pass.

- [ ] **Step 7: Run UI tests**

Run: `python -m pytest tests/test_fixed_input_slot_contract.py tests/test_timeline_splice_real_media.py tests/test_source_ui_interval_contract.py -q`

Expected: PASS with no old UI frames and no operation-video audio in the final mix.

### Task 6: Permanent Alibaba Cloud OSS final delivery

**Files:**
- Create: `server/aliyun_oss_final_store.py`
- Modify: `server/packaged_factory.py`
- Modify: `deployment/requirements.lock`
- Modify: `deployment/requirements-control-plane.lock`
- Test: `tests/test_aliyun_oss_final_store.py`
- Test: `tests/test_packaged_factory.py`

**Interfaces:**
- Consumes: verified temporary MP4 `ArtifactRef`, internal MinIO reader and Alibaba OSS credentials.
- Produces: `AliyunOssFinalStore.promote(job_id, source) -> ArtifactRef` with `metadata.public_url`.

- [ ] **Step 1: Write failing final-store tests**

```python
def test_final_store_uploads_exact_bytes_and_returns_public_url(fake_oss, source_ref):
    result = store.promote(job_id="job1", source=source_ref)
    assert result.sha256 == source_ref.sha256
    assert result.metadata["public_url"] == "https://cdn.example.com/usfr/final/job1/result.mp4"
```

- [ ] **Step 2: Add the official OSS SDK dependency**

Add `oss2==2.19.1` to both deployment requirement locks. Keep model weights and local development packages out of the control-plane image.

- [ ] **Step 3: Implement immutable final publication**

Upload to `USFR_OSS_FINAL_PREFIX/final/{job_id}/result.mp4`, attach SHA-256 metadata, reject an existing key with different bytes, verify object length and metadata after upload, and return the normalized public URL from `USFR_OSS_PUBLIC_BASE_URL`.

- [ ] **Step 4: Wire separate internal and permanent stores**

Internal temporary media continues using MinIO. `USFR_OSS_ENDPOINT`, `USFR_OSS_BUCKET`, `USFR_OSS_ACCESS_KEY_ID`, `USFR_OSS_ACCESS_KEY_SECRET`, `USFR_OSS_PUBLIC_BASE_URL`, and `USFR_OSS_FINAL_PREFIX` configure the permanent result store. Production readiness fails when any value is missing.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_aliyun_oss_final_store.py tests/test_packaged_factory.py -q`

Expected: PASS and final result projection contains only the public URL.

### Task 7: Failure state, retry boundary and simplified public errors

**Files:**
- Modify: `server/job_models.py`
- Modify: `server/redis_job_store.py`
- Modify: `server/deployment_bootstrap.py`
- Modify: `server/public_job_projection.py`
- Test: `tests/test_public_failures.py`
- Test: `tests/test_redis_job_store.py`

**Interfaces:**
- Consumes: `ReplicationError` from import or pipeline stages.
- Produces: terminal `FAILED` snapshot with a public-safe error and retryable internal stage retry up to three attempts.

- [ ] **Step 1: Write failing failure-projection tests**

```python
def test_source_too_long_is_public_and_no_paid_stage_runs(runtime):
    result = run_import_failure(code="INPUT_SOURCE_TOO_LONG")
    assert result["status"] == "failed"
    assert result["error"] == {
        "code": "SOURCE_TOO_LONG",
        "message": "源视频不能超过30秒",
        "retryable": False,
    }
    assert runtime.provider_calls == []
```

- [ ] **Step 2: Add a JSON-safe terminal error field to `JobSnapshot`**

```python
public_error: Mapping[str, Any] | None = None
```

Allow CAS updates only after strict validation of `code`, `message` and `retryable`.

- [ ] **Step 3: Add lease-fenced stage failure handling**

Transient errors are re-enqueued with the same dedupe authority up to three attempts. Permanent errors mark the checkpoint failed, set job state `FAILED`, preserve only the simplified error, ACK the queue message and keep the worker alive. Ambiguous paid Provider errors remain reconciliation-only and are never blindly retried.

- [ ] **Step 4: Map internal errors to seven public codes**

Map to `INVALID_REQUEST`, `ACCESS_DENIED`, `SOURCE_UNAVAILABLE`, `UNSUPPORTED_MEDIA`, `SOURCE_TOO_LONG`, `REVIEW_NOT_ALLOWED`, or `PROCESSING_FAILED`. Do not expose stack traces, local paths, raw Provider errors or object keys.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_public_failures.py tests/test_redis_job_store.py tests/test_recovery_driver.py -q`

Expected: PASS, worker survives permanent input failure, and paid attempts remain zero.

### Task 8: Deployment configuration, Chinese manual and black-box HTTP tests

**Files:**
- Modify: `.env.example`
- Modify: `deployment/docker-compose.yml`
- Modify: `deployment/README.md`
- Modify: `deployment/中文部署配置手册.md`
- Modify: `validation/e2e/driver.py`
- Create: `validation/e2e/public_http_driver.py`
- Modify: `tests/test_deployment_bundle_config.py`
- Modify: `tests/test_container_video_e2e_contract.py`

**Interfaces:**
- Consumes: Docker Compose services, Redis, MinIO, fake or real Provider ports and OSS settings.
- Produces: deployable one-`.env` configuration and a black-box client that only uses the three public endpoints.

- [ ] **Step 1: Write failing deployment/OpenAPI assertions**

Assert Compose exposes only API port 8080 publicly by default, contains all OSS and URL allowlist settings, and the E2E driver never submits internal slot completion data.

- [ ] **Step 2: Update `.env.example` and Compose**

Add:

```dotenv
USFR_ALLOWED_OSS_HOSTS=*.oss-cn-hangzhou.aliyuncs.com
USFR_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
USFR_OSS_BUCKET=
USFR_OSS_ACCESS_KEY_ID=
USFR_OSS_ACCESS_KEY_SECRET=
USFR_OSS_PUBLIC_BASE_URL=
USFR_OSS_FINAL_PREFIX=usfr
USFR_JOB_TERMINAL_TTL_SECONDS=604800
USFR_TEMPORARY_RETENTION_SECONDS=172800
USFR_UI_OPERATION_MIN_RATE=0.85
USFR_UI_OPERATION_MAX_RATE=1.20
```

- [ ] **Step 3: Implement the black-box public HTTP driver**

The driver must create a job using URL fields, poll with `Authorization: Bearer`, revise or approve the script, revise or approve the storyboard, wait for completion, download the final URL and decode it with ffprobe. It cannot import any `server.*` module.

- [ ] **Step 4: Rewrite the Chinese deployment manual around the three endpoints**

Document OSS upload ownership, environment variables, startup, health checks, the create/status/review examples, result persistence, temporary cleanup, log redaction and real validation commands. Remove all old `/start`, `slots`, upload-completion, revision and Provider reconcile examples.

- [ ] **Step 5: Run deployment tests**

Run: `python -m pytest tests/test_deployment_bundle_config.py tests/test_container_video_e2e_contract.py -q`

Expected: PASS.

### Task 9: Full verification and refreshed Windows deployment ZIP

**Files:**
- Create: `exports/usfr-video-service-2026-07-29-deploy-windows.zip`
- Create: `exports/usfr-video-service-2026-07-29-http-validation-report.md`

**Interfaces:**
- Consumes: verified local Skill tree and deployment configuration.
- Produces: self-contained deployment ZIP and evidence-backed HTTP validation report.

- [ ] **Step 1: Run focused public API suite**

Run:

```powershell
python -m pytest tests/test_public_idempotency.py tests/test_remote_media_import.py tests/test_public_fastapi_router.py tests/test_public_failures.py tests/test_aliyun_oss_final_store.py -q
```

Expected: PASS.

- [ ] **Step 2: Run impacted USFR regression suite**

Run:

```powershell
python -m pytest tests/test_job_api.py tests/test_server_api_contract.py tests/test_ephemeral_runtime.py tests/test_analysis_scope.py tests/test_fixed_input_slot_contract.py tests/test_timeline_splice_real_media.py tests/test_packaged_factory.py tests/test_deployment_bootstrap.py -q
```

Expected: PASS.

- [ ] **Step 3: Run Docker black-box HTTP flow**

Run:

```powershell
docker compose --env-file .env -f deployment/docker-compose.yml up -d --build redis minio minio-init api worker sweeper
docker compose --env-file .env -f deployment/docker-compose.yml run --rm e2e python -B -m validation.e2e.public_http_driver
```

Expected: create returns `importing`; both reviews pause and resume correctly; final status is `completed`; final URL downloads and ffprobe succeeds.

- [ ] **Step 4: Verify public OpenAPI over real HTTP**

Run:

```powershell
$schema = Invoke-RestMethod http://127.0.0.1:8080/openapi.json
$schema.paths.PSObject.Properties.Name
```

Expected: exactly `/api/v1/jobs`, `/api/v1/jobs/{job_id}`, and `/api/v1/jobs/{job_id}/review`, plus health probes outside the business API schema only if explicitly configured with `include_in_schema=false`.

- [ ] **Step 5: Build a clean ZIP from the current Skill tree**

Copy only `agents`, `bundled-skills`, `deployment`, `references`, `runtime-skills`, `schemas`, `scripts`, `server`, `validation`, `.dockerignore`, `.env.example`, `.gitignore`, `SKILL.md`, and the Chinese manual into a fresh temporary staging directory. Exclude `tests`, `__pycache__`, `.pytest_cache`, local runs, `.env`, API keys, media, logs and previous ZIP files. Create the final ZIP atomically after validation.

- [ ] **Step 6: Verify ZIP content and startup**

Extract the final ZIP to a new temporary directory, run `python -m compileall server scripts`, run the bundle verifier, and run Docker Compose configuration validation from the extracted copy.

- [ ] **Step 7: Write the validation report**

Record test commands, exit codes, public routes, job state transitions, result URL reachability, Docker image/build identity and ZIP SHA-256. Redact all secrets and access tokens.
