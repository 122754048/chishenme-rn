# USFR Route-First Speed and Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make deterministic route-first execution authoritative, reuse one frozen source-evidence bundle across the workflow, reduce duplicate model/tool calls and temporary files, while preserving both user reviews and all quality hard gates.

**Architecture:** Keep the existing fixed slots, Redis job state machine, twelve semantic stages, two review gates, Provider idempotency, and final QC. Strengthen `analysis_scope` into an enforceable execution contract, add one shared evidence/frame cache, make stages publish compact references instead of duplicate files, and split lightweight QC from factor-specific escalation.

**Tech Stack:** Python 3.12, FastAPI, Redis, MinIO/S3, Alibaba OSS, FFmpeg/FFprobe, GPT API, RunningHub, Seedance-20, pytest.

**实施状态（2026-07-30）：** Task 1–9 已在隔离部署副本完成。最新本地 Skill 能力、简化公共 HTTP API、路由优先执行、共享证据、条件工具、Prompt 缓存、分级 QC、永久 OSS 结果和临时文件清理规则已进入发布 ZIP。

**发布验证：** 完整回归 `1451 passed, 1 skipped`；重点路由/API/缓存/清理回归 `338 passed`；媒体与 QC 回归 `63 passed`。发布目录和 ZIP 全新解压目录均通过 `verify_bundle.py`、`verify_lightweight_bundle.py` 与真实本地 TCP 三接口烟测。当前工作站未安装 Docker，因此容器黑盒测试仍需在部署服务器执行，不能用本地 Python 烟测代替该项上线验收。

**最新发布物：** `exports/usfr-video-service-2026-07-29-deploy-windows.zip`，大小 `951232` 字节，SHA-256 `4708E3CF53BC2A8532EB9BCF6AA6A00FE0706CF109D5F704F46D88EB9D6A6279`。ZIP 含 `222` 个运行文件（`271` 个含目录条目），不含 `tests`、`.pytest_cache`、`__pycache__`、`*.pyc`、`.env`、日志、历史运行素材或 API Key。

## Global Constraints

- Canonical Skill root: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication`.
- Implement and verify in an isolated copy/worktree before syncing the canonical Skill or deployment ZIP.
- Every admitted public run requires editable script review followed by editable storyboard review.
- Source video maximum is 30 seconds; Provider video task count remains at most two.
- No quality threshold, timeline hard gate, UI OCR hard gate, Provider dedupe rule, or final QC hard gate may be weakened.
- Original OSS assets and permanent OSS final MP4s are never deleted.
- Use TDD for every behavior change and run the impacted route matrix after each task.

---

### Task 1: Make the route-first scope an executable contract

**Files:**
- Modify: `server/analysis_scope.py`
- Modify: `server/ephemeral_worker.py`
- Modify: `server/provider_ports.py`
- Test: `tests/test_analysis_scope.py`
- Test: `tests/test_ephemeral_runtime.py`

**Interfaces:**
- Consumes: fixed `slots_manifest` and existing `build_analysis_scope(manifest)`.
- Produces: `validate_tool_call(scope, tool_name, stage) -> None` and one immutable `execution_scope` in every `EphemeralStageContext`.

- [ ] **Step 1: Write failing tests for forbidden, deferred, and required tools**

```python
def test_skipped_tool_cannot_be_called():
    scope = build_analysis_scope(_opaque_ui_manifest())
    with pytest.raises(ReplicationError, match="tool is outside execution scope"):
        validate_tool_call(scope, "semantic_vlm", "analyze_dynamics")


def test_deferred_tool_requires_a_stage4_promotion_receipt():
    scope = build_analysis_scope(_app_manifest())
    with pytest.raises(ReplicationError, match="promotion receipt"):
        validate_tool_call(scope, "app_store_evidence", "resolve_app_evidence")
```

- [ ] **Step 2: Run tests and confirm they fail because enforcement is missing**

Run:

```text
python -m pytest tests/test_analysis_scope.py tests/test_ephemeral_runtime.py -q
```

Expected: new tests fail before any Provider call.

- [ ] **Step 3: Add the enforcement API**

```python
def validate_tool_call(
    scope: Mapping[str, Any],
    tool_name: str,
    stage: str,
    *,
    promotion_receipt: Mapping[str, Any] | None = None,
) -> None:
    decision = (scope.get("tools") or {}).get(tool_name)
    if not isinstance(decision, Mapping):
        raise ReplicationError("CONTRACT_INVALID", "tool is absent from execution scope")
    if decision.get("status") == "skipped":
        raise ReplicationError("CONTRACT_INVALID", "tool is outside execution scope")
    if decision.get("status") == "deferred":
        if not isinstance(promotion_receipt, Mapping):
            raise ReplicationError("CONTRACT_INVALID", "deferred tool requires a promotion receipt")
        if promotion_receipt.get("scope_sha256") != scope.get("scope_sha256"):
            raise ReplicationError("CONTRACT_INVALID", "promotion receipt scope mismatch")
```

- [ ] **Step 4: Inject and verify the immutable scope before every stage port**

Set `context.analysis_scope` once from the manifest. Reject stage results that declare a tool call not admitted by the scope. Do not ask GPT to validate the scope.

- [ ] **Step 5: Run tests**

```text
python -m pytest tests/test_analysis_scope.py tests/test_ephemeral_runtime.py tests/test_capability_ports.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```text
git add server/analysis_scope.py server/ephemeral_worker.py server/provider_ports.py tests/test_analysis_scope.py tests/test_ephemeral_runtime.py
git commit -m "perf: enforce route-first tool scope"
```

### Task 2: Freeze one shared source-evidence bundle

**Files:**
- Create: `server/source_evidence_bundle.py`
- Modify: `server/production_ports.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/ephemeral_worker.py`
- Test: `tests/test_source_evidence_bundle.py`
- Test: `tests/test_packaged_stages.py`

**Interfaces:**
- Consumes: `probe_source`, one dynamics result, optional ASR/OCR/audio evidence, and the final execution scope.
- Produces: `build_source_evidence_bundle(*, probe, timeline, execution_scope, semantic_evidence, audio_evidence, ui_evidence) -> dict[str, Any]`, `source_evidence_bundle_sha256`, and a read-only stage output reused by script, storyboard, Prompt, compositor, and QC.

- [ ] **Step 1: Write a failing test proving a second full analysis is rejected**

```python
def test_bundle_rejects_a_second_full_source_analysis():
    ledger = AnalysisInvocationLedger()
    ledger.record("semantic_vlm", scope="full_source")
    with pytest.raises(ReplicationError, match="full source analysis already completed"):
        ledger.record("semantic_vlm", scope="full_source")
```

- [ ] **Step 2: Run the new test and confirm RED**

```text
python -m pytest tests/test_source_evidence_bundle.py -q
```

- [ ] **Step 3: Implement the immutable bundle and invocation ledger**

```python
def build_source_evidence_bundle(
    *,
    probe: Mapping[str, Any],
    timeline: Mapping[str, Any],
    execution_scope: Mapping[str, Any],
    semantic_evidence: Mapping[str, Any] | None,
    audio_evidence: Mapping[str, Any] | None,
    ui_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    bundle = {
        "contract": "usfr-source-evidence-bundle/v1",
        "probe": dict(probe),
        "timeline": dict(timeline),
        "execution_scope_sha256": execution_scope["scope_sha256"],
        "semantic_evidence": dict(semantic_evidence or {}),
        "audio_evidence": dict(audio_evidence or {}),
        "ui_evidence": dict(ui_evidence or {}),
    }
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundle
```

- [ ] **Step 4: Make downstream stages consume the bundle**

Replace fresh source materialization or fresh full-video VLM/ASR calls in script, storyboard, Invocation A/B, and QC with the frozen bundle. Allow a supplemental call only when it carries `region_id`, `factor_id`, and an unresolved blocker from the bundle.

- [ ] **Step 5: Run impacted tests**

```text
python -m pytest tests/test_source_evidence_bundle.py tests/test_packaged_stages.py tests/test_production_ports.py tests/test_ephemeral_runtime.py -q
```

- [ ] **Step 6: Commit**

```text
git add server/source_evidence_bundle.py server/production_ports.py server/packaged_stages.py server/ephemeral_worker.py tests/test_source_evidence_bundle.py tests/test_packaged_stages.py
git commit -m "perf: reuse one frozen source evidence bundle"
```

### Task 3: Add condition gates for ASR, OCR, App Store, lyrics, UI, and Seedance

**Files:**
- Modify: `server/analysis_scope.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/real_capabilities.py`
- Modify: `server/singing_audio_router.py`
- Test: `tests/test_analysis_scope.py`
- Test: `tests/test_packaged_stages.py`
- Test: `tests/test_singing_audio_router.py`

**Interfaces:**
- Consumes: final Stage-4 region list and route-first scope.
- Produces: one `tool_execution_receipt` per tool with `status`, `reason`, `region_ids`, input digest, and output digest.

- [ ] **Step 1: Write route matrix tests**

```python
SLOT_IDS = (
    "source_video", "new_product_image", "new_model_image", "ui_screenshot",
    "app_store_url", "ui_operation_video", "tail_video",
)


def route_fixture(route: str) -> dict[str, Any]:
    slots = {
        slot_id: {"present": slot_id == "source_video"}
        for slot_id in SLOT_IDS
    }
    manifest = {
        "slots": slots,
        "routes": {},
        "extensions": {},
        "admission": {"language_only": False},
        "output_language": None,
    }
    slot_routes = {
        "model_only": "new_model_image",
        "product_only": "new_product_image",
        "app": "app_store_url",
        "ui_screenshot": "ui_screenshot",
        "ui_operation_video": "ui_operation_video",
        "tail_only": "tail_video",
    }
    if route == "language_only":
        manifest["admission"]["language_only"] = True
        manifest["output_language"] = "en"
    elif route in slot_routes:
        slots[slot_routes[route]]["present"] = True
    elif route in {"uploaded_music", "compound"}:
        manifest["extensions"]["background_music"] = {
            "extension_id": "input_contract_v2.background_music"
        }
        if route == "compound":
            slots["new_model_image"]["present"] = True
            slots["new_product_image"]["present"] = True
            slots["ui_screenshot"]["present"] = True
    else:
        raise AssertionError(f"unknown route fixture: {route}")
    return manifest


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        ("language_only", {"source_asr": "required", "semantic_vlm": "skipped", "app_store_evidence": "skipped"}),
        ("model_only", {"semantic_vlm": "required", "source_asr": "deferred", "app_store_evidence": "skipped"}),
        ("product_only", {"semantic_vlm": "required", "source_asr": "required", "app_store_evidence": "skipped"}),
        ("app", {"semantic_vlm": "required", "app_store_evidence": "deferred", "ui_rebuild": "deferred"}),
        ("ui_screenshot", {"source_ocr": "deferred", "target_ui_ocr": "deferred", "ui_rebuild": "deferred"}),
        ("ui_operation_video", {"semantic_vlm": "skipped", "ui_rebuild": "skipped", "seedance_video": "skipped"}),
        ("tail_only", {"semantic_vlm": "skipped", "source_asr": "skipped", "seedance_video": "skipped"}),
        ("uploaded_music", {"uploaded_music_alignment": "required", "source_asr": "deferred", "seedance_video": "deferred"}),
        ("compound", {"semantic_vlm": "required", "uploaded_music_alignment": "required", "ui_rebuild": "deferred"}),
    ],
)
def test_route_matrix(route, expected):
    scope = build_analysis_scope(route_fixture(route))
    assert {name: scope["tools"][name]["status"] for name in expected} == expected
    assert scope["user_review"]["script"]["status"] == "required"
    assert scope["user_review"]["storyboard"]["status"] == "required"
```

- [ ] **Step 2: Run tests and confirm current over-calling cases fail**

```text
python -m pytest tests/test_analysis_scope.py tests/test_singing_audio_router.py -q
```

- [ ] **Step 3: Implement Stage-4 promotion receipts**

```python
def promote_deferred_tool(
    *, scope: Mapping[str, Any], tool_name: str, region_ids: Sequence[str], reason: str
) -> dict[str, Any]:
    if not region_ids:
        raise ReplicationError("CONTRACT_INVALID", "tool promotion requires a region")
    return {
        "contract": "usfr-tool-promotion/v1",
        "scope_sha256": scope["scope_sha256"],
        "tool": tool_name,
        "region_ids": list(region_ids),
        "reason": reason,
    }
```

- [ ] **Step 4: Enforce audio branching**

```python
def uploaded_audio_tools(classification: Mapping[str, Any]) -> frozenset[str]:
    kind = classification.get("kind")
    if kind == "song":
        return frozenset({"lyrics", "singing_contract", "seedance_audio", "singing_lip_sync"})
    if kind == "non_song":
        return frozenset({"music_window_replace"})
    raise ReplicationError(
        "UPLOADED_AUDIO_CLASSIFICATION_REQUIRED",
        "uploaded audio must be frozen as song or non_song before script drafting",
    )
```

Call this once from the Stage-4 promotion boundary. The `non_song` branch must consume the frozen source music windows and must never promote lyric extraction or singing lip-sync.

- [ ] **Step 5: Run the matrix**

```text
python -m pytest tests/test_analysis_scope.py tests/test_packaged_stages.py tests/test_singing_audio_router.py tests/test_audio_backends.py -q
```

- [ ] **Step 6: Commit**

```text
git add server/analysis_scope.py server/packaged_stages.py server/real_capabilities.py server/singing_audio_router.py tests/test_analysis_scope.py tests/test_packaged_stages.py tests/test_singing_audio_router.py
git commit -m "perf: gate expensive tools by routed regions"
```

### Task 4: Reuse decoded frames across analysis, storyboards, and QC

**Files:**
- Create: `server/shared_frame_evidence.py`
- Modify: `server/production_ports.py`
- Modify: `server/packaged_stages.py`
- Modify: `server/real_capabilities.py`
- Test: `tests/test_shared_frame_evidence.py`
- Test: `tests/test_packaged_stages.py`

**Interfaces:**
- Consumes: source SHA, Cut boundaries, ROI requests, and exact timestamps.
- Produces: `SharedFrameManifest` with one object per unique `(source_sha256, timestamp_us, roi)`.

- [ ] **Step 1: Write a failing deduplication test**

```python
def test_same_timestamp_and_roi_are_decoded_once():
    cache = SharedFrameEvidenceStore(memory_backend)
    first = cache.get_or_create(source, timestamp_us=500_000, roi=None)
    second = cache.get_or_create(source, timestamp_us=500_000, roi=None)
    assert first.object_key == second.object_key
    assert memory_backend.decode_calls == 1
```

- [ ] **Step 2: Run the test and confirm RED**

```text
python -m pytest tests/test_shared_frame_evidence.py -q
```

- [ ] **Step 3: Implement content-addressed shared frames**

```python
@dataclass(frozen=True)
class SharedFrameRef:
    object_key: str
    sha256: str
    source_sha256: str
    timestamp_us: int
    roi: tuple[int, int, int, int] | None


class SharedFrameEvidenceStore:
    def get_or_create(self, source, *, timestamp_us: int, roi=None) -> SharedFrameRef:
        key = canonical_sha256({
            "source_sha256": source.sha256,
            "timestamp_us": timestamp_us,
            "roi": roi,
        })
        existing = self.backend.get(key)
        if existing is not None:
            return SharedFrameRef(**existing)
        created = self.decoder.decode_and_publish(source, timestamp_us=timestamp_us, roi=roi)
        self.backend.put_if_absent(key, asdict(created))
        return created
```

Use one bounded structural resolution and request full-resolution detail/ROI frames only from explicit evidence triggers. Storyboard control sheets and QC receive `SharedFrameRef` rows rather than decoding again.

- [ ] **Step 4: Add a file-count regression test**

```python
def test_adaptive_manifest_is_the_complete_frame_file_set(tmp_path):
    manifest = build_shared_frames(thirty_second_fixture, adaptive_plan)
    frame_objects = object_store.list_prefix(manifest["object_prefix"])
    assert len(frame_objects) == len(manifest["frames"])
    assert not list(tmp_path.rglob("frame_[0-9][0-9][0-9][0-9][0-9][0-9].png"))
```

- [ ] **Step 5: Run tests**

```text
python -m pytest tests/test_shared_frame_evidence.py tests/test_packaged_stages.py tests/test_production_ports.py -q
```

- [ ] **Step 6: Commit**

```text
git add server/shared_frame_evidence.py server/production_ports.py server/packaged_stages.py server/real_capabilities.py tests/test_shared_frame_evidence.py tests/test_packaged_stages.py
git commit -m "perf: reuse shared frame evidence"
```

### Task 5: Remove duplicate GPT review and compile work

**Files:**
- Modify: `server/production_ports.py`
- Modify: `server/seedance_invocations.py`
- Modify: `scripts/seedance_prompt_compiler.py`
- Test: `tests/test_production_ports.py`
- Test: `tests/test_seedance_invocations.py`
- Test: `tests/test_seedance_prompt_compiler.py`

**Interfaces:**
- Consumes: source evidence bundle, approved script revision, approved storyboard revision, and immutable route digest.
- Produces: one cached GPT script draft per script input digest and one compiled Prompt per approved prompt digest.

- [ ] **Step 1: Write failing call-count tests**

```python
def test_prompt_version_is_compiled_once():
    compiler = CountingCompiler()
    first = service.compile_prompt(request, compiler=compiler)
    second = service.compile_prompt(request, compiler=compiler)
    assert first == second
    assert compiler.calls == 1
```

- [ ] **Step 2: Confirm RED**

```text
python -m pytest tests/test_production_ports.py tests/test_seedance_invocations.py -q
```

- [ ] **Step 3: Add digest-keyed draft and compile caches**

```python
def prompt_cache_key(request: Mapping[str, Any]) -> str:
    return canonical_sha256({
        "source_bundle_sha256": request["source_bundle_sha256"],
        "route_sha256": request["route_sha256"],
        "approved_script_sha256": request["approved_script_sha256"],
        "approved_storyboard_sha256": request["approved_storyboard_sha256"],
        "segment_plan_sha256": request["segment_plan_sha256"],
        "output_language": request.get("output_language"),
        "model_identity": request["model_identity"],
        "seedance_skill_sha256": request["seedance_skill_sha256"],
    })


def compile_once(request, *, cache, compiler):
    key = prompt_cache_key(request)
    cached = cache.get(key)
    if cached is not None:
        return cached
    artifact = compiler.compile(request)
    cache.put_if_absent(key, artifact)
    return artifact
```

A changed user revision produces a new digest. Retrying the exact revision reuses the existing immutable artifact.

- [ ] **Step 4: Move deterministic checks out of GPT**

```python
def validate_deterministic_parity(*, approved, compiled, provider_request) -> None:
    require_equal(approved["cut_ids"], compiled["cut_ids"], "Cut order")
    require_equal(approved["line_contract_sha256"], compiled["line_contract_sha256"], "lines")
    require_equal(approved["segment_plan_sha256"], provider_request["segment_plan_sha256"], "plan")
    require_no_route_exclusions(compiled)
    require_no_placeholders(compiled["prompt"])
    require_exact_asset_map(compiled["asset_map"], provider_request)
```

This function runs locally after compilation. It must not call GPT to reconfirm a hash, field, timing window, revision, or Provider parameter.

- [ ] **Step 5: Run tests**

```text
python -m pytest tests/test_production_ports.py tests/test_seedance_invocations.py tests/test_seedance_prompt_compiler.py tests/test_public_idempotency.py -q
```

- [ ] **Step 6: Commit**

```text
git add server/production_ports.py server/seedance_invocations.py scripts/seedance_prompt_compiler.py tests/test_production_ports.py tests/test_seedance_invocations.py tests/test_seedance_prompt_compiler.py
git commit -m "perf: compile each approved prompt version once"
```

### Task 6: Add lightweight QC with factor-specific escalation

**Files:**
- Create: `server/qc_escalation.py`
- Modify: `server/real_capabilities.py`
- Modify: `server/ephemeral_worker.py`
- Test: `tests/test_qc_escalation.py`
- Test: `tests/test_high_fidelity_qc.py`

**Interfaces:**
- Consumes: technical QC result, route confidence, factor scores, and hard-failure records.
- Produces: `build_qc_plan(*, route: str, hard_failures: Sequence[str], factor_scores: Mapping[str, float], threshold: float = 90.0) -> dict[str, Any]`.

- [ ] **Step 1: Write failing tests for base-only and targeted escalation**

```python
def test_clean_technical_splice_uses_base_qc_only():
    plan = build_qc_plan(route="technical_splice", hard_failures=[], factor_scores={})
    assert plan["escalated_factors"] == []


def test_low_lip_sync_escalates_only_audio_performance():
    plan = build_qc_plan(
        route="uploaded_music_mv",
        hard_failures=[],
        factor_scores={"lip_sync": 78, "timeline": 100},
    )
    assert plan["escalated_factors"] == ["lip_sync"]
```

- [ ] **Step 2: Run tests and confirm RED**

```text
python -m pytest tests/test_qc_escalation.py -q
```

- [ ] **Step 3: Implement the plan without lowering gates**

```python
BASE_CHECKS = (
    "decode", "video_stream", "required_audio", "duration", "fps",
    "black_boundaries", "timeline_placement", "final_object_verification",
)


def build_qc_plan(*, route, hard_failures, factor_scores, threshold=90.0):
    escalated = sorted(
        factor for factor, score in factor_scores.items() if float(score) < threshold
    )
    return {
        "base_checks": list(BASE_CHECKS),
        "hard_failures": list(hard_failures),
        "escalated_factors": escalated,
        "prohibited_full_rerun": True,
        "route": route,
    }
```

Every route executes `BASE_CHECKS`. Escalation adds only named failing factors and cannot replace a base check.

- [ ] **Step 4: Run QC tests**

```text
python -m pytest tests/test_qc_escalation.py tests/test_high_fidelity_qc.py tests/test_timeline_splice_real_media.py -q
```

- [ ] **Step 5: Commit**

```text
git add server/qc_escalation.py server/real_capabilities.py server/ephemeral_worker.py tests/test_qc_escalation.py tests/test_high_fidelity_qc.py
git commit -m "perf: escalate qc by failing factor only"
```

### Task 7: Delete temporary media independently from public job metadata

**Files:**
- Modify: `server/cleanup.py`
- Modify: `server/redis_job_store.py`
- Modify: `server/ephemeral_worker.py`
- Modify: `server/deployment_bootstrap.py`
- Modify: `server/packaged_factory.py`
- Test: `tests/test_cleanup_sweeper.py`
- Test: `tests/test_ephemeral_runtime.py`
- Test: `tests/test_packaged_factory.py`

**Interfaces:**
- Consumes: terminal job state, `USFR_TEMPORARY_RETENTION_SECONDS`, and `USFR_JOB_TERMINAL_TTL_SECONDS`.
- Produces: an early temporary-object purge that retains the public job snapshot/Token until terminal TTL, followed by final Redis authority cleanup.

- [ ] **Step 1: Write failing split-retention tests**

```python
def test_temporary_media_expires_before_job_token_metadata():
    completed = complete_job(job_ttl_seconds=604800, temporary_retention_seconds=0)
    sweeper.sweep_once(now_ms())
    assert temporary.list_job_keys(completed.job_id) == ()
    assert jobs.get_job(completed.job_id) is not None
    assert permanent.has_final(completed.job_id)
```

- [ ] **Step 2: Confirm RED**

```text
python -m pytest tests/test_cleanup_sweeper.py tests/test_ephemeral_runtime.py -q
```

- [ ] **Step 3: Add a temporary-cleanup due index**

```python
def schedule_temporary_cleanup(self, *, job_id: str, terminal_at_ms: int, retention_seconds: int) -> None:
    due_ms = terminal_at_ms + retention_seconds * 1000
    self.redis.zadd(self._key("temporary_cleanup_due"), {job_id: due_ms})


def due_temporary_jobs(self, *, now_ms: int, limit: int = 100) -> list[str]:
    rows = self.redis.zrangebyscore(
        self._key("temporary_cleanup_due"), min=0, max=now_ms, start=0, num=limit
    )
    return [self._decode(row) for row in rows]
```

Terminal success/failure calls this method once. The existing job-authority cleanup due time remains the public job/Token expiry.

- [ ] **Step 4: Split cleanup operations**

```python
def purge_temporary_job(self, job_id: str) -> bool:
    self.temporary_store.delete_job(job_id)
    self._delete_owned_upload_scope(job_id)
    return True


def expire_job_authority(self, job_id: str) -> bool:
    self._validate_final_ref(job_id, self._snapshot(job_id))
    self._remove_redis_authority(job_id)
    return True
```

The Alibaba OSS FinalStore remains non-deleting. Original OSS URLs are never in the deletion namespace.

- [ ] **Step 5: Wire environment values**

```python
job_ttl_seconds = int(os.getenv("USFR_JOB_TERMINAL_TTL_SECONDS", "604800"))
temporary_retention_seconds = int(os.getenv("USFR_TEMPORARY_RETENTION_SECONDS", "172800"))
if job_ttl_seconds <= 0 or temporary_retention_seconds < 0:
    raise ValueError("retention values are invalid")
```

Allow `USFR_TEMPORARY_RETENTION_SECONDS=0` for immediate cleanup after verified success in batch deployments.

- [ ] **Step 6: Run lifecycle tests**

```text
python -m pytest tests/test_cleanup_sweeper.py tests/test_ephemeral_runtime.py tests/test_packaged_factory.py tests/test_aliyun_oss_final_store.py -q
```

- [ ] **Step 7: Commit**

```text
git add server/cleanup.py server/redis_job_store.py server/ephemeral_worker.py server/deployment_bootstrap.py server/packaged_factory.py tests/test_cleanup_sweeper.py tests/test_ephemeral_runtime.py tests/test_packaged_factory.py
git commit -m "perf: purge temporary media before job metadata expiry"
```

### Task 8: Add timing, call-count, file-count, and quality regression gates

**Files:**
- Create: `validation/performance/route_first_benchmark.py`
- Create: `validation/performance/route_first_thresholds.json`
- Modify: `validation/case_catalog.json`
- Modify: `scripts/validation_catalog.py`
- Test: `tests/test_route_first_benchmark.py`
- Test: `tests/test_case_matrix_runner.py`

**Interfaces:**
- Consumes: same-case baseline and candidate timing/call/file/QC reports.
- Produces: a release report that blocks activation when quality drops or duplicate calls/files exceed limits.

- [ ] **Step 1: Write failing threshold tests**

```python
def test_candidate_fails_when_quality_drops_even_if_faster():
    result = compare_runs(
        baseline={"quality": 90, "seconds": 120},
        candidate={"quality": 89, "seconds": 60},
    )
    assert result["passed"] is False
    assert "quality_regression" in result["failures"]
```

- [ ] **Step 2: Confirm RED**

```text
python -m pytest tests/test_route_first_benchmark.py -q
```

- [ ] **Step 3: Implement exact thresholds**

Create `validation/performance/route_first_thresholds.json` with exactly:

```json
{
  "minimum_throughput_gain": {
    "standard": 1.8,
    "compound_app_ui_audio": 1.3,
    "deterministic_splice": 3.0
  },
  "maximum_full_source_semantic_calls": 1,
  "maximum_relevant_tool_calls": 1,
  "maximum_quality_drop": 0,
  "maximum_hard_failures": 0,
  "temporary_file_policy": "not_above_adaptive_manifest"
}
```

Implement the release comparison as:

```python
def compare_runs(*, baseline, candidate, thresholds):
    failures = []
    if candidate["quality"] < baseline["quality"]:
        failures.append("quality_regression")
    if candidate["hard_failures"]:
        failures.append("hard_failure")
    if candidate["calls"]["full_source_semantic"] > 1:
        failures.append("duplicate_full_source_analysis")
    if candidate["temporary_files"] > candidate["adaptive_manifest_files"]:
        failures.append("temporary_file_overproduction")
    route_floor = thresholds["minimum_throughput_gain"][candidate["route_class"]]
    if baseline["videos_per_hour"] and candidate["videos_per_hour"] / baseline["videos_per_hour"] < route_floor:
        failures.append("throughput_target_missed")
    return {"passed": not failures, "failures": failures}
```

Reports must separately record active time excluding user waits, Provider wait, GPT/VLM/ASR/OCR/App Store/lyrics call counts, frame/file counts, QC scores, and hard failures.

- [ ] **Step 4: Run smoke and full matrices**

```text
python -m pytest tests/test_route_first_benchmark.py tests/test_case_matrix_runner.py -q
python scripts/validation_catalog.py --smoke
python scripts/validation_catalog.py --all --release-candidate
```

- [ ] **Step 5: Commit**

```text
git add validation/performance/route_first_benchmark.py validation/performance/route_first_thresholds.json validation/case_catalog.json scripts/validation_catalog.py tests/test_route_first_benchmark.py tests/test_case_matrix_runner.py
git commit -m "test: gate route-first speed without quality loss"
```

### Task 9: Sync the verified canonical Skill into the deployable ZIP

**Files:**
- Modify: deployment build staging copy only after all preceding tests pass.
- Update: `deployment/README.md`
- Update: `deployment/中文部署配置手册.md`
- Rebuild: `exports/usfr-video-service-2026-07-29-deploy-windows.zip`

**Interfaces:**
- Consumes: one verified immutable Skill tree and its runtime manifest.
- Produces: a self-contained deployment ZIP with identical workflow code, updated digests, public API, and no local paths/caches/tests/secrets.

- [ ] **Step 1: Run the full Skill test suite before copying**

```text
python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Register the new runtime files and verify immutable dependencies**

Add these exact records to `references/bundle_manifest.json` under `runtime_files`:

```json
{"path":"server/source_evidence_bundle.py","role":"one immutable source evidence bundle and invocation ledger"},
{"path":"server/shared_frame_evidence.py","role":"content-addressed adaptive frame and ROI evidence reuse"},
{"path":"server/qc_escalation.py","role":"base QC plus factor-specific escalation planning"},
{"path":"validation/performance/route_first_benchmark.py","role":"same-case speed call-count file-count and quality release gate"},
{"path":"validation/performance/route_first_thresholds.json","role":"immutable route-first activation thresholds"}
```

Do not change `references/runtime_skill_manifest.json` unless packaged Seedance Skill bytes changed. Verify the current digests with:

```text
python scripts/verify_bundle.py .
python scripts/verify_lightweight_bundle.py .
```

- [ ] **Step 3: Remove release-forbidden files**

Delete only from the staging directory:

```text
.pytest_cache/
**/__pycache__/
**/*.pyc
tests/
.env
replication_runs/
temporary media
API keys and logs
```

- [ ] **Step 4: Build and extract-verify the ZIP**

```text
python -m compileall "C:/Users/zhaocx04/Documents/New project/.tmp/usfr-route-first-release-check"
python "C:/Users/zhaocx04/Documents/New project/.tmp/usfr-route-first-release-check/scripts/verify_bundle.py" "C:/Users/zhaocx04/Documents/New project/.tmp/usfr-route-first-release-check"
python "C:/Users/zhaocx04/Documents/New project/.tmp/usfr-route-first-release-check/scripts/verify_lightweight_bundle.py" "C:/Users/zhaocx04/Documents/New project/.tmp/usfr-route-first-release-check"
python -B "C:/Users/zhaocx04/Documents/New project/.tmp/usfr-route-first-release-check/validation/e2e/local_public_http_smoke.py"
```

On a Docker host also run:

```text
docker compose -f deployment/docker-compose.yml config
docker compose -f deployment/docker-compose.yml --profile e2e up --build --abort-on-container-exit --exit-code-from e2e e2e
```

- [ ] **Step 5: Write release evidence**

Record ZIP byte size, SHA-256, file count, test counts, HTTP smoke result, container result, timing/call/file-count comparison, and the explicit statement that the canonical local Skill directory was not modified during staging.

- [ ] **Step 6: Commit documentation and release metadata**

```text
git add docs/superpowers/specs/2026-07-29-usfr-route-first-speed-and-retention-design.md docs/superpowers/plans/2026-07-29-usfr-route-first-speed-and-retention.md deployment/README.md deployment/中文部署配置手册.md
git commit -m "docs: define route-first speed and retention rollout"
```
