# USFR Fidelity Lineage and User Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make source-fidelity replication fail closed unless every director board derives from per-Cut source frames and authorized replacement evidence, every Seedance request carries the matching source segment plus the approved board, and confirmed visible text is both user-editable and rendered on the director board.

**Architecture:** Keep internal visual-control artifacts upstream-only. Publish cryptographically bound lineage on the board and a private final-reference sidecar at the audit boundary; verify that sidecar at audit, submit, and provider boundaries. Carry source-visible-text observations into a canonical user-confirmed lock contract, render only the two user-facing script sections, and deterministically place the confirmed text on the review board after Image2 generation.

**Tech Stack:** Python 3, pytest, Pillow, FFmpeg/ffprobe, existing Redis ephemeral job store, RunningHub Standard Model contract.

## Global Constraints

- Do not regenerate or mutate the current run in `replication_runs/2026-07-29/character_swap_20260729_2326`.
- Preserve the existing uploaded-audio, song lyric, multi-performer, and exact music cut-in/cut-out contracts.
- A visual replacement always follows `source Cut frames -> replacement-control sheet -> approved director board`; no control/keyframe sheet may reach Seedance.
- Every paid Seedance request uses the matching original source segment at `videoUrls[0]`, the approved director board at `imageUrls[0]` (`@Image1`), then only fixed-slot model/product targets.
- User-visible Markdown has exactly `## 角色、场景与连续性锁定` and `## 逐镜反解`; evidence, QC, request hashes, and execution rules remain internal JSON artifacts.
- Only edit the live skill at `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication`; mirror it to the Git branch only after verification. Never use `git add .` or `git add -A`.

---

### Task 1: Freeze visible-text observations and user-confirmed locks

**Files:**

- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\source_content_timeline.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\capability_ports.py`
- Create: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\visible_text_contract.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ephemeral_service.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\redis_job_store.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\fastapi_router.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_source_content_timeline.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_review_service.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_revision_cas.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_server_api_contract.py`

**Interfaces:**

- Produces `visible-text-locks/v1`: `{text_id, cut_ids, start_ms, end_ms, kind, source_evidence_sha256, approved_text, disposition, placement}` rows and canonical `visible_text_locks_sha256`.
- `disposition` is exactly `keep`, `replace`, or `remove`; `keep`/`replace` require a non-empty `approved_text`, while `remove` requires empty `approved_text`.
- The existing `script_approval` contract gains `visible_text_locks` and `visible_text_locks_sha256`; it remains compatible with an empty list when the source has no visible text.

- [ ] **Step 1: Write failing timeline tests**

```python
def test_merges_source_event_and_overlay_text_into_cut_bound_visible_text() -> None:
    timeline = build_source_content_timeline(
        source_video_sha256=SOURCE_SHA,
        source_dynamics_analysis=_analysis_with_source_event_subtitle(),
        audio_contract=_audio(),
        source_overlay_contract=_overlay_with_observed_text(),
    )
    assert [(row["text_id"], row["text"], row["cut_ids"]) for row in timeline["visible_text"]] == [
        ("event:2", "Uninstall!", ["C03"]),
        ("overlay:uninstall_response_01", "Uninstall!", ["C03"]),
    ]

def test_visible_text_locks_reject_an_unapproved_or_foreign_source_row() -> None:
    with pytest.raises(VisibleTextContractError, match="source evidence"):
        validate_visible_text_locks([_lock(text_id="foreign", source_evidence_sha256="f" * 64)], timeline=_timeline())
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_source_content_timeline.py -k 'source_event or visible_text_locks'`

Expected: FAIL because the timeline has no `source_events`/overlay merge and `visible_text_contract` does not exist.

- [ ] **Step 3: Implement the minimal canonical visible-text contract**

```python
def validate_visible_text_locks(
    locks: Sequence[Mapping[str, Any]], *, timeline: Mapping[str, Any]
) -> list[dict[str, Any]]:
    # Match each lock to exactly one timeline visible_text row, preserve the
    # source window/cut IDs/evidence SHA, enforce disposition and exact text,
    # sort by source start time and return canonical dictionaries.
```

Extend `build_source_content_timeline(..., source_overlay_contract=None)` to normalize existing OCR rows, `source_events` whose kind is `subtitle`, `cta`, `visible_text`, or `text`, and overlay `observed_text` rows. De-duplicate only identical source evidence rows; retain their source placement when available. In `capability_ports.py`, pass `dynamics.get("source_overlay_contract")` when it is a mapping.

Thread `visible_text_locks` through `RevisionApprovalModel`, `ReplicationService.approve_script_revision`, and `_canonical_script_approval`. Require locks whenever the frozen source-content timeline contains visible text, and reject a missing, changed, foreign, duplicate, or incomplete lock set. Leave line-contract validation unchanged.

- [ ] **Step 4: Verify GREEN and compatibility**

Run: `pytest -q tests/test_source_content_timeline.py tests/test_review_service.py tests/test_revision_cas.py tests/test_server_api_contract.py`

Expected: PASS; existing empty-visible-text approvals remain valid and a source-text approval fails without locks.

### Task 2: Render the two-section editable script and supply confirmed text to storyboard drafting

**Files:**

- Create: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\user_script_document.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\production_ports.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\packaged_stages.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_user_script_document.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_production_ports.py`

**Interfaces:**

- `render_user_script_markdown(script_revision, visible_text_locks) -> str` returns only the two permitted `##` headings.
- Storyboard GPT evidence contains only the current approved script's validated visible-text locks and their SHA; no draft may invent, drop, or mutate them.
- Each script Cut exposes a `visible_text_locks` array, and each storyboard Cut echoes `visible_text_locks` exactly.

- [ ] **Step 1: Write failing document and planner tests**

```python
def test_user_script_document_has_only_the_two_editable_sections() -> None:
    markdown = render_user_script_markdown(_script_revision(), _locks())
    assert re.findall(r"^## .+$", markdown, flags=re.M) == [
        "## 角色、场景与连续性锁定", "## 逐镜反解"
    ]
    assert "可见文字/字幕" in markdown
    assert "生成与后期执行规则" not in markdown

def test_storyboard_evidence_requires_the_approved_visible_text_lock_sha() -> None:
    with pytest.raises(ProductionPortsError, match="visible text"):
        planner._revision_evidence(_context_with_missing_approved_text_locks(), kind="storyboard")
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_user_script_document.py tests/test_production_ports.py -k 'user_script_document or visible_text_lock'`

Expected: FAIL because no renderer or storyboard lock projection exists.

- [ ] **Step 3: Implement deterministic user document and planner projection**

```python
def render_user_script_markdown(
    script_revision: Mapping[str, Any], visible_text_locks: Sequence[Mapping[str, Any]]
) -> str:
    return "\n".join([
        "## 角色、场景与连续性锁定", _continuity_table(script_revision),
        "", "## 逐镜反解", _cut_table(script_revision, visible_text_locks), "",
    ])
```

Add strict schemas for `visible_text_locks` to script and storyboard revisions, enforce that script values match source evidence and storyboard values match the approved script sidecar. Publish `user_script_markdown` beside the internal script revision as a text artifact; keep it outside prompt/QC/evidence artifacts. Storyboard evidence must obtain the approved sidecar from the job store, validate its script SHA/revision, and project only canonical locks for the current Cut.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/test_user_script_document.py tests/test_production_ports.py`

Expected: PASS; the Markdown has exactly two sections and storyboard drafting fails closed if confirmed text is absent or altered.

### Task 3: Bind director-board lineage, deterministic board text, and final reference lineage

**Files:**

- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\control_keyframe_contract.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\packaged_stages.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\runninghub_standard_contract.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\production_ports.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_control_keyframe_contract.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_packaged_stages.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_runninghub_standard_seedance.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_production_ports.py`

**Interfaces:**

- Board metadata carries `replacement_control_keyframe_receipt_sha256`, `replacement_control_keyframe_sheet_sha256`, `source_keyframe_sheet_sha256`, `source_video_sha256`, `replacement_target_sha256s`, `approved_visible_text_locks_sha256`, and `storyboard_revision`.
- `seedance-final-reference-lineage/v1` is an internal sidecar with the current `segment_id`, `segment_plan_sha256`, source-slice artifact, approved board descriptor/manifest, allowed target slot digests, ordered provider URLs, and forbidden internal kinds.
- Extend `usfr-video-reference/v1` with `segment_plan_sha256` and `source_video_reference_artifact_id`.

- [ ] **Step 1: Write failing lineage tests**

```python
def test_board_metadata_binds_every_control_lineage_input_and_text_lock() -> None:
    result = _storyboard_stage().run(context=_visual_context(two_product_images=True), input_artifacts=[])
    metadata = result["storyboard_images"][0]["metadata"]
    assert metadata["replacement_target_sha256s"] == [MODEL_SHA, PRODUCT_1_SHA, PRODUCT_2_SHA]
    assert metadata["source_video_sha256"] == SOURCE_SHA
    assert metadata["approved_visible_text_locks_sha256"] == TEXT_LOCK_SHA

def test_audit_rejects_wrong_board_revision_or_forged_control_sheet_lineage() -> None:
    with pytest.raises(ReplicationError, match="approved storyboard|control receipt"):
        _audit().run(context=_context_with_forged_board_lineage(), input_artifacts=[])

def test_final_reference_lineage_rejects_an_internal_control_asset_or_wrong_source_slice() -> None:
    with pytest.raises(RunningHubStandardPayloadError, match="final reference lineage"):
        validate_final_reference_lineage(_payload_with_control_sheet(), _forged_lineage())
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_control_keyframe_contract.py tests/test_packaged_stages.py tests/test_runninghub_standard_seedance.py tests/test_production_ports.py -k 'lineage or control or source_slice or storyboard_not_owned'`

Expected: FAIL because multi-image hashes, approved board ownership, plan SHA, and final internal sidecar are not enforced.

- [ ] **Step 3: Implement the minimum fail-closed chain**

```python
def _final_reference_lineage(
    *, payload: Mapping[str, Any], segment_id: str, plan_sha256: str,
    board: Mapping[str, Any], source_ref: Mapping[str, Any], targets: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    return {
        "schema_version": "seedance-final-reference-lineage/v1",
        "segment_id": segment_id, "segment_plan_sha256": plan_sha256,
        "ordered_image_urls": list(payload["imageUrls"]),
        "ordered_video_urls": list(payload["videoUrls"]),
        "approved_board": dict(board), "source_reference": dict(source_ref),
        "allowed_target_changes": [dict(row) for row in targets],
        "forbidden_artifact_kinds": ["source_keyframe_sheet", "replacement_control_keyframe_sheet", "replacement_control_keyframe_receipt"],
    }
```

Collect every actual target digest in fixed slot order before creating the control manifest. Make the board prompt consume the packaged `daohuo_storyboard_prompt.md` template with literal approved labels. After Image2 returns, use Pillow to add an exact, high-contrast, deterministic text strip for every `keep`/`replace` lock covered by the segment; never ask Image2/Seedance to fabricate the glyphs. Bind the final board bytes and the lock SHA in metadata.

In audit, use `get_current_revision(job_id, "storyboard")` (or its exact store equivalent) to prove approved status, current revision, manifest SHA, and Cut-to-board mapping. Materialize and validate the control receipt for visual replacement. Reuse `materialize_source_video_reference()` by default, while preserving injected test segmenters; publish slice metadata and binding. Recompute the canonical segment-plan SHA and require exact row coverage before uploading anything.

Carry the final sidecar through `_BoundProviderPayload`; validate it in `SeedanceAuditStage`, `SubmitProviderVideoStage`, and `RunningHubSeedanceProvider.create_video()` before transport. Keep it out of the external JSON provider body.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/test_control_keyframe_contract.py tests/test_packaged_stages.py tests/test_runninghub_standard_seedance.py tests/test_production_ports.py`

Expected: PASS; internal visual sheets cannot enter final input slots, every final request has its matching original source segment at `videoUrls[0]`, and `@Image1` is exactly the user-approved board.

### Task 4: Align the skill contract, test it against the baseline failure, and publish

**Files:**

- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\SKILL.md`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\references\seedance-prompt.md`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\references\runninghub-standard-seedance-api.md`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\references\seedance-20-integrity-gate.md`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\references\daohuo_storyboard_prompt.md`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_skill_contract_docs.py`

- [ ] **Step 1: Write failing documentation-contract tests**

```python
def test_skill_requires_control_chain_source_segment_approved_board_and_two_section_script() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "source Cut frames -> replacement-control sheet -> approved director board" in text
    assert "videoUrls[0]" in text and "@Image1" in text
    assert "## 角色、场景与连续性锁定" in text
    assert "## 逐镜反解" in text
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_skill_contract_docs.py`

Expected: FAIL because current guidance permits optional/no video reference and does not define the exact two-section user document or deterministic board-text rule.

- [ ] **Step 3: Edit only the affected rules**

State the exact visual chain as a positive recipe, make matching source segment + approved director board mandatory for every source-fidelity Seedance invocation, forbid `source_keyframe_sheet`, `replacement_control_keyframe_sheet`, and `replacement_control_keyframe_receipt` in final references, and require confirmed text to be on a deterministic director-board layer. Move internal evidence/intent/QC language out of the user script contract. Keep source audio / uploaded song handling unchanged.

- [ ] **Step 4: Verify all required behavior**

Run: `pytest -q tests/test_source_content_timeline.py tests/test_review_service.py tests/test_revision_cas.py tests/test_server_api_contract.py tests/test_user_script_document.py tests/test_control_keyframe_contract.py tests/test_packaged_stages.py tests/test_runninghub_standard_seedance.py tests/test_production_ports.py tests/test_skill_contract_docs.py`

Expected: PASS with no paid provider calls.

- [ ] **Step 5: Run the skill green pressure scenario and publish the verified source**

Re-run the baseline scenario with the updated skill. It must answer: internal source Cut frames -> replacement-control sheet -> director board; `imageUrls=[approved_board, targets...]`; `videoUrls=[matching_source_segment]`; exact confirmed text on deterministic board layer; exactly two user-document headings.

After the tests and pressure scenario pass, mirror the live skill to the controlled repository source path `C:\Users\zhaocx04\Documents\New project\usfr-server`, explicitly stage only `usfr-server` and the plan/spec files intentionally owned by this task, commit on `codex/usfr-commercial-clean`, and push `HEAD:codex/usfr-commercial-clean`.

