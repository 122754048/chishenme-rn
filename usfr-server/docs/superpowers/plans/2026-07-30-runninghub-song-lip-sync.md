# RunningHub Song Lip-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route only classified uploaded songs through the supplied RunningHub AI App after Seedance video generation, with up to two independent segment jobs submitted concurrently.

**Architecture:** Add a dedicated song-only request builder and RunningHub client operation; preserve the existing general final lip-sync workflow unchanged. The post-process coordinator accepts generated-person segment files and an approved song timing contract, validates eligibility and exact time windows, then downloads and returns result bytes indexed by `segment_id` for timeline replacement.

**Tech Stack:** Python 3, pytest, existing `RunningHubWorkflowClient`, immutable artifact receipts.

## Global Constraints

- Only `uploaded_audio_classification.kind == "song"` is eligible.
- Opaque UI, tail media, and `non_song` inputs never reach this workflow.
- The endpoint is `run/ai-app/2082759080288296961`; nodes are 228/video, 125/audio, 325/start, and 326/end.
- Do not auto-retry a create request after an ambiguous outcome; retain task IDs and poll them.
- Run at most two independent segment jobs concurrently, immediately download successful MP4 results, and record input/output SHA-256s, time bounds, request SHA, and task ID.
- Seedance receives no song audio, lyric text, or singing command; the timing/lyrics contract remains for the post-process route.

---

### Task 1: Freeze the dedicated AI App request shape

**Files:**
- Create: `server/runninghub_song_lip_sync.py`
- Test: `tests/test_runninghub_song_lip_sync.py`

**Interfaces:**
- Produces `build_song_lip_sync_provider_request(audio_input, video_input, song_start, song_end) -> dict[str, Any]`.

- [x] **Step 1: Write a failing request-shape test**
- [x] **Step 2: Run `pytest -q tests/test_runninghub_song_lip_sync.py` and verify RED**
- [x] **Step 3: Implement exact AI App payload and strict time/media validation**
- [x] **Step 4: Run the same test and verify GREEN**

### Task 2: Execute eligible generated segments concurrently

**Files:**
- Modify: `server/runninghub_workflows.py`
- Test: `tests/test_runninghub_workflows.py`

**Interfaces:**
- Produces `RunningHubWorkflowClient.run_song_lip_sync_segments(...) -> dict[str, dict[str, Any]]`.

- [x] **Step 1: Write failing tests for two independent submissions, result download, receipt binding, and non-eligible input rejection**
- [x] **Step 2: Run targeted pytest and verify RED**
- [x] **Step 3: Implement bounded two-worker submission/polling using the exact request builder**
- [x] **Step 4: Run targeted pytest and verify GREEN**

### Task 3: Keep song metadata out of Seedance

**Files:**
- Modify: `server/packaged_stages.py`
- Test: `tests/test_packaged_stages.py`, `tests/test_seedance_prompt_compiler.py`

**Interfaces:**
- `SeedancePromptStage` retains validated song timing as post-process data but compiles no song audio/lyrics/performance instruction into Seedance.

- [x] **Step 1: Write a failing test proving an eligible song segment has no Seedance audio/lyric prompt input**
- [x] **Step 2: Run the focused test and verify RED**
- [x] **Step 3: Make the smallest compiler boundary change**
- [x] **Step 4: Run the focused test and verify GREEN**

### Task 4: Verify the unchanged surrounding routes

**Files:**
- Test: existing focused test suites.

- [x] **Step 1: Run `pytest -q tests/test_runninghub_song_lip_sync.py tests/test_runninghub_workflows.py tests/test_packaged_stages.py tests/test_seedance_prompt_compiler.py tests/test_performance_audio_contracts.py`**
- [x] **Step 2: Inspect the diff to confirm no UI, tail, or non-song code paths were changed**
