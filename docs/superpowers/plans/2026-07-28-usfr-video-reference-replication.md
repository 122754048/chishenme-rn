# USFR Video-Reference Replication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Let each generated Seedance segment use its matching source-video slice as a reference while requiring an approved target replacement and preserving the existing storyboard approval flow.

**Architecture:** RunningHub Standard Seedance accepts a bounded `videoUrls` array. The existing fixed-B adapter will bind one source-derived segment URL only after validating its exact time window, source SHA-256, and target-change manifest. `@Image1` remains the approved storyboard; the internal control sheet has one ordered panel per source Cut and is never promoted into the final asset role.

**Tech Stack:** Python 3.12, pytest, RunningHub Standard Model API, canonical JSON SHA-256 receipts.

## Global Constraints

- Keep the seven fixed slots, the script and storyboard approval gates, the at-most-two-provider-task limit, audio behavior, and default lightweight QA unchanged.
- A source video can be sent only as the matching 2-15 second generation segment, never as opaque UI/tail media and never as a source-only copy task.
- Each video-reference request must contain an authorized replacement: target model, product, App/UI, approved target copy/selling-point change, localized dialogue/lyrics, or background music.
- Do not automatically retry upload or paid create calls; freeze source-slice, target, prompt, payload, and task receipts before submission.
- `@Image1` is always the approved storyboard; the source slice is carried only in `videoUrls[0]`.

---

### Task 1: Define the Video-Reference Payload Contract

**Files:**
- Modify: `usfr-server/server/runninghub_standard_contract.py`
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py`
- Test: `usfr-server/tests/test_runninghub_standard_seedance.py`

- [x] Add failing tests for one valid bounded source-video URL, source-only rejection, multiple/empty target-change rejection, and source-window length validation.
- [x] Run the focused tests and confirm they fail because `videoUrls` is currently forced empty.
- [x] Implement a canonical `video_reference` binding with a single HTTPS URL, `segment_id`, start/end milliseconds, source SHA-256, and a non-empty target-change list.
- [x] Make the adapter preserve `videoUrls=[source_slice_url]` and reject any other video-reference role.
- [x] Run the focused tests until they pass.

### Task 2: Bind the Reference to Existing Segment and Prompt Authority

**Files:**
- Modify: `usfr-server/server/production_ports.py`
- Modify: `usfr-server/server/high_fidelity_ports.py`
- Modify: `usfr-server/server/seedance_invocations.py`
- Test: `usfr-server/tests/test_production_ports.py`
- Test: `usfr-server/tests/test_high_fidelity_ports.py`

- [x] Add failing tests proving that a video reference is accepted only for the frozen segment, includes an approved storyboard image as `@Image1`, and fails closed without a real replacement.
- [x] Run the focused tests and confirm they fail under the old `videoUrls=[]` policy.
- [x] Pass only the matching source segment binding through production ports and include its immutable fields in the canonical provider-request SHA-256.
- [x] Retain the existing rejection of opaque UI-operation and tail media as video references.
- [x] Run focused port tests until they pass.

### Task 3: Document and Regression-Proof the Route

**Files:**
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/references/runninghub-standard-seedance-api.md`
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/SKILL.md`
- Modify: `usfr-server/SKILL.md`
- Modify: `usfr-server/tests/test_skill_contract.py`

- [x] Add a failing contract assertion for source-video reference plus a required target change, with storyboard retained as `@Image1`.
- [x] Run the contract test and confirm it fails before documentation/contract updates.
- [x] Replace the stale blanket `videoUrls=[]` rule with the segment-bounded video-reference route and its exact prohibitions.
- [x] Run focused tests. The full suite was attempted separately and remains blocked only by pre-existing/generated cache-purity checks, which are reported separately.

### Task 4: Automatically Materialize the Matching Source Segment

**Files:**
- Add: `usfr-server/bundled-skills/seedance-storyboard-replication/scripts/source_video_reference.py`
- Modify: `usfr-server/bundled-skills/seedance-storyboard-replication/scripts/runninghub_seedance_submit.py`
- Modify: `usfr-server/scripts/verify_bundle.py`
- Modify: `usfr-server/references/bundle_manifest.json`
- Test: `usfr-server/tests/test_source_video_reference.py`
- Test: `usfr-server/tests/test_runninghub_standard_seedance.py`

- [x] Add and run failing tests for direct use of a matching short source, exact S01/S02 FFmpeg windows, the 15-second upper bound, opaque-media rejection, and frozen-slice reuse.
- [x] Materialize one exact source-video window from the immutable `segment_plan` with no Provider request; reuse a complete short source or an otherwise matching cached slice.
- [x] Add `--source-video-file` and `--segment-plan-file` to the audited submitter, deriving all source hashes and segment metadata before the existing dry-run/paid-submit path.
- [x] Package the module in the server bundle and synchronize it into the local Skill runtime copy.
- [x] Run focused source-reference and submission tests until they pass.
