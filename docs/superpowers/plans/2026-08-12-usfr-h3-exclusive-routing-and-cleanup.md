# USFR H3 Exclusive Routing and Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route MV singing and every language-change request, including compound visual edits, through one H3 generation path while preserving Seedance visual editing and the deterministic UI-operation splice.

**Architecture:** Add a small model-owner decision module and an isolated H3 request contract/provider. Existing intake and script approval remain, but the provider compiler is selected by the frozen task intent. After new H3 paths are reachable and tested, remove only the superseded final-language lip-sync and song lip-sync runtime closure plus proven-unreachable UI redraw code.

**Tech Stack:** Python 3.12, pytest, RunningHub H3 REST API, FFmpeg, JSON audit receipts.

## Global Constraints

- One generated segment uses exactly one model: H3 or Seedance.
- Any target-language change or MV target-song performance selects H3.
- Ordinary visual-only edits select Seedance and retain existing binding behavior.
- Never alter `ui_operation_video` deterministic splice behavior.
- No unchanged paid retry; this implementation uses mocked provider contract tests only.
- Local Skill and `usfr-server` receive the same explicit changed files.

---

### Task 1: Freeze routing and prompt contracts

**Files:**
- Create: `server/h3_edit_contract.py`
- Create: `tests/test_h3_edit_contract.py`

- [ ] Write failing tests for language compound → H3, MV song → H3, visual-only → Seedance, mixed syntax rejection, continuous image indexes, and 11-language whitelist.
- [ ] Run `pytest -q tests/test_h3_edit_contract.py` and confirm RED.
- [ ] Implement the minimal immutable route decision and compact H3 prompt/request validation.
- [ ] Run the test and confirm GREEN.

### Task 2: Add the H3 RunningHub provider boundary

**Files:**
- Create: `server/runninghub_h3.py`
- Create: `tests/test_runninghub_h3.py`
- Modify: `server/runninghub_workflows.py`

- [ ] Write failing tests for endpoint, payload fields, no automatic retry, status polling, and one MP4 result.
- [ ] Implement upload/create/query/download using the existing RunningHub transport conventions.
- [ ] Verify targeted tests pass.

### Task 3: Switch task ownership without changing visual bindings

**Files:**
- Modify: `server/audio_lane_router.py`
- Modify: `server/analysis_scope.py`
- Modify: `server/orchestrator.py`
- Modify: `server/packaged_ports.py`
- Modify: `server/packaged_stages.py`
- Test: `tests/test_audio_lane_router.py`
- Test: `tests/test_analysis_scope.py`
- Test: `tests/test_ephemeral_runtime.py`

- [ ] Add failing ownership tests proving language compound and MV song cannot enter Seedance or a post-generation lip-sync stage.
- [ ] Add H3 compile/audit/submit/wait stages while leaving all Seedance binding compiler code unchanged.
- [ ] Verify targeted route tests pass.

### Task 4: Remove superseded runtime closure

**Files:**
- Delete: `server/runninghub_final_lip_sync.py`
- Delete: `server/runninghub_song_lip_sync.py`
- Delete/update their direct tests and imports.
- Modify: `references/bundle_manifest.json`
- Modify: `scripts/verify_bundle.py`

- [ ] Prove new route tests pass before deletion.
- [ ] Remove the old language lip-sync, song AI App request builder, segment-render-only code, constants, environment variables, bundle entries, and current documentation.
- [ ] Run a static import scan proving no runtime import remains.

### Task 5: Remove only proven-unreachable UI redraw

**Files:**
- Candidate only after dependency proof: `server/remotion_react_ui.py`, obsolete sidecar references, and redraw-only configuration.
- Protected: `scripts/source_ui_pixels.py`, `ui_operation_video` splice code, receipts, audio guards, and tests.

- [ ] Record protected-file SHA-256 values before changes.
- [ ] Run static and dynamic import scans for each redraw candidate.
- [ ] Delete only candidates with no current runtime consumer.
- [ ] Run UI splice and opaque-pixel tests and confirm protected hashes are unchanged except documentation references explicitly approved here.

### Task 6: Synchronize and verify

**Files:**
- Modify matching explicit files under `usfr-server/`.
- Modify current Skill/reference/deployment documentation only where it contradicts the new route.

- [ ] Copy only the explicit change set from local Skill to deployment package.
- [ ] Run H3 targeted tests, Seedance binding regression, product/App adaptation regression, UI-operation splice regression, bundle verification, and full pytest.
- [ ] Run `rg` proving the old Provider routes are unreachable and H3/Seedance syntax is isolated.
- [ ] Record final protected-file hashes and test counts.
