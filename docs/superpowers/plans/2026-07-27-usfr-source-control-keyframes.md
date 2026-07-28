# USFR Source Control Keyframes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create private source-derived replacement control keyframes after script approval, render storyboards from those controls with the exact same RunningHub image2 model, and make deep QA an explicit default-off option.

**Architecture:** Keep the existing source analysis, script approval, storyboard approval, segment planning, and provider stages. Add a private control-keyframe manifest and a local runner that invokes the existing `runninghub_image2.py` model adapter with source keyframe first and target assets after it. Storyboard manifests bind the approved script and control-keyframe manifest. A new QA policy has basic checks always on and deep checks opt-in; it never creates a retry or a Provider task.

**Tech Stack:** Python 3, pytest, FFmpeg, existing RunningHub image2 adapter, existing storyboard manifests, JSON SHA-256 contracts.

## Global Constraints

- Do not add a new user approval, queue stage, segment, paid video task, or automatic retry.
- Direct `language_only` remains unchanged and creates no script, storyboard, or control-keyframe artifact.
- Control keyframes are private run artifacts. Only the existing storyboard is user-visible.
- The control-keyframe image model, API ID, aspect ratio, resolution, quality, upload path, task receipt format, and single-create policy must be identical to storyboard image generation.
- The source frame is the first image reference. The prompt allows changes only to admitted target slots; all other visual facts are source-preserved.
- Deep QA defaults to false and must not run, block, or retry when disabled.

---

### Task 1: Control-Keyframe Contract and Same-Model Runner

**Files:**
- Create: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\scripts\control_keyframes.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\scripts\runninghub_image2.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_control_keyframes.py`

**Interfaces:**
- `build_control_keyframe_manifest(...) -> dict[str, Any]` validates script lineage, unique ordered Cut/phase anchors, source-frame SHA bindings, admitted replacement slots, and the image2 model fingerprint.
- `render_control_keyframe(...) -> dict[str, Any]` delegates exactly once to `runninghub_image2.run_generation`, first using the immutable source keyframe and then target references.

- [x] Write failing contract and same-model delegation tests.
- [x] Run the new tests and verify they fail because the required behavior was absent.
- [x] Implement the immutable manifest, source-preservation prompt builder, exact-time extractor, and same-model runner.
- [x] Run the new tests and verify they pass.

### Task 2: Bind Controls to Storyboard Revisions

**Files:**
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\scripts\storyboard_manifest.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\review_workflow.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_storyboard_manifest.py`

**Interfaces:**
- A source-replication storyboard manifest must carry `control_keyframe_manifest_sha256` and the exact ordered control-keyframe SHA list.
- Script edits invalidate the control-keyframe artifact together with the existing storyboard invalidation. Storyboard-only review remains the existing single user-visible artifact.

- [x] Write failing tests for missing/stale control-keyframe lineage and script invalidation.
- [x] Run them and verify the expected failure.
- [x] Add optional backward-compatible fields for unrelated legacy callers, with required enforcement for a source-control manifest.
- [x] Run storyboard and review workflow tests.

### Task 3: Default-Off QA Policy

**Files:**
- Create: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\qa_policy.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\high_fidelity_qc.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_qa_policy.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_high_fidelity_qc.py`

**Interfaces:**
- `resolve_qa_policy(value) -> dict[str, Any]` emits `mode=basic` by default and exposes the full deep-check list only when `deep_qa.enabled=true`.
- Basic QA validates only lineage, file decode, stream presence, duration/boundaries, and final path.
- Deep QA evidence remains accepted only when enabled; neither mode permits automatic regeneration or a Provider call.

- [x] Write failing tests for default basic mode and enabled deep mode.
- [x] Run tests and verify the expected default-QA runtime failure.
- [x] Implement the policy and make the QC runtime short-circuit deep scans, evaluator calls, and complex audio checks unless explicitly enabled.
- [x] Run QA tests.

### Task 4: Skill Contracts and Regression Verification

**Files:**
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication\SKILL.md`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_skill_contract.py`

- [x] Document the approved order: source frames, script approval, private same-model controls, storyboard approval, video generation.
- [x] Document basic/default-off deep QA and the immutable no-automatic-retry rule.
- [x] Run the affected contract and feature tests with cache-provider disabled.

## Verification

Run:

```powershell
python -B -m pytest tests/test_control_keyframes.py tests/test_storyboard_manifest.py tests/test_qa_policy.py tests/test_high_fidelity_qc.py tests/test_skill_contract.py -q -p no:cacheprovider
```

Expected: all tests pass except only any documented unrelated historical artifact-purity failure; no cache directory is deleted by this work.
