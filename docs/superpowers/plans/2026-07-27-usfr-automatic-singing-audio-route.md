# USFR Automatic Singing Audio Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically route uploaded audio to verified singing only for evidenced music-video performances, otherwise use exact background-music replacement.

**Architecture:** Reuse the frozen source content timeline for a constant-cost eligibility decision. Only an eligible source invokes one bounded uploaded-audio lyric transcription; the selected immutable result builds the existing performance contract, Seedance prompt, audio-driven lip-sync repair and QC path.

**Tech Stack:** Python, existing `source_content_timeline`, `background_music_execution`, pytest, RunningHub/Seedance adapters.

## Global Constraints

- Do not add a public slot, user approval gate, full-video re-analysis, or more than one target-audio transcription.
- Evidence uncertainty defaults to BGM replacement.
- UI/tail/source-only intervals never enter the singing adapter.
- Keep all artifacts temporary until final-video user acceptance.

---

### Task 1: Add deterministic singing-candidate routing

**Files:**
- Create: `usfr-server/server/singing_audio_router.py`
- Test: `usfr-server/tests/test_singing_audio_router.py`

- [ ] Write tests proving that a sung source line with exactly one on-camera active mouth routes to `pending_uploaded_lyrics`, while spoken, instrumental, ambiguous-speaker and low-confidence examples route to `background_music_replacement`.
- [ ] Run `pytest tests/test_singing_audio_router.py -v` and verify the tests fail because the router does not exist.
- [ ] Implement `route_uploaded_audio(source_content_timeline, *, overlap_threshold=0.80, mouth_threshold=0.80)` returning an immutable route receipt with reason and eligible source windows.
- [ ] Run the same tests and verify they pass.

### Task 2: Bind verified lyrics to the existing execution contract

**Files:**
- Modify: `backend/app/background_music_execution.py`
- Modify: `backend/app/background_music_local_mvp.py`
- Test: `backend/tests/test_background_music_execution.py`

- [ ] Write a failing test proving an eligible route with timestamped uploaded lyrics compiles `verified_singing`, and incomplete lyric evidence deterministically falls back to BGM.
- [ ] Run the test and verify it fails against the current caller-controlled intent.
- [ ] Replace the caller-controlled mode selection with the router receipt and validated lyric contract; retain exact existing contract hashes and BGM behavior.
- [ ] Run the focused backend tests and verify they pass.

### Task 3: Apply singing lip-sync only to eligible generated regions

**Files:**
- Modify: `backend/app/background_music_execution.py`
- Test: `backend/tests/test_background_music_execution.py`

- [ ] Write a failing test proving only approved singing regions request the audio-driven lip-sync adapter, while UI and BGM regions never do.
- [ ] Run the test and verify it fails.
- [ ] Add the adapter request/receipt binding and fail-closed QC boundary without changing Seedance task limits or approvals.
- [ ] Run all affected tests and verify they pass.

### Task 4: Repair the current 14-second run

**Files:**
- Runtime only: a new temporary USFR run directory

- [ ] Reuse the approved script/storyboards and the uploaded 90–104 second song fragment.
- [ ] Regenerate and audio-drive only 0–4 and 10–14 seconds; preserve 4–10 seconds of source UI.
- [ ] Validate output audio/timecode, lip-sync evidence, identity continuity, splice black frames and freezes.
- [ ] Retain artifacts until user accepts the repaired MP4, then remove the temporary run directory.
