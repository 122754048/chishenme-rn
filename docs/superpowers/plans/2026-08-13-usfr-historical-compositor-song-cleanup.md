# USFR Historical Compositor and Song Route Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove three historical runtime routes after extracting the current V2 behavior they were accidentally coupled to.

**Architecture:** Current H3/Seedance provider outputs continue through the existing deterministic `FfmpegCompositor`. Historical UI backend selection and song-segment manifest rendering are deleted rather than replaced. Current source-audio window analysis remains in `singing_audio_router.py` and related V2 contracts.

**Tech Stack:** Python, pytest, FFmpeg contracts, JSON bundle manifest.

## Global Constraints

- Do not modify person/multi-object binding or person asset rules.
- Do not modify source/new-product selling-point, pain-point, audience, Hook, Matcher, or action-adaptation logic.
- Do not modify `ui_operation_video` deterministic FFmpeg splice.
- Do not mix H3 and Seedance or add another paid request.
- Preserve current marketing-analysis and UI-operation files byte-for-byte where possible.

---

### Task 1: Structural removal contract

**Files:**
- Create: `tests/test_historical_runtime_cleanup.py`

- [ ] Add assertions that retired modules, bundle entries, legacy assembly contract, and Remotion registration are absent, while H3 MV, marketing analysis, binding, and UI-operation contracts remain.
- [ ] Run the test and verify it fails against the historical runtime.

### Task 2: Decouple current H3 MV assembly

**Files:**
- Modify: `server/orchestrator.py`
- Modify: `server/real_capabilities.py`
- Delete: `server/song_lip_sync_contract.py`

- [ ] Remove the legacy assembly input contract from H3 MV stage planning.
- [ ] Remove manifest loading/rendering/receipt branches from the compositor.
- [ ] Retain ordinary provider-video segment assembly and source audio protection analysis.
- [ ] Run orchestration, H3 and compositor tests.

### Task 3: Remove historical UI rendering backends

**Files:**
- Modify: `server/packaged_factory.py`
- Modify: `server/ephemeral_worker.py`
- Modify: `server/__init__.py`
- Modify: `scripts/verify_bundle.py`
- Modify: `references/bundle_manifest.json`
- Delete: `server/remotion_react_ui.py`
- Delete: `server/ui_sidecar_runtime.py`
- Delete: `server/ui_sidecar_retention.py`
- Delete: `scripts/hybrid_compositor.py`
- Delete: dedicated historical backend tests and validation policy.

- [ ] Remove factory registration and sidecar finalization.
- [ ] Remove bundle declarations and historical tests.
- [ ] Keep current FFmpeg compositor and UI-operation splice unchanged.

### Task 4: Contracts, regression and bundle closure

**Files:**
- Modify: `SKILL.md`
- Modify: affected contract tests only where they assert removed history.

- [ ] Document that old song manifest and generated-UI backend routes are removed.
- [ ] Run targeted protected-capability tests.
- [ ] Run full pytest and bundle verification.
- [ ] Verify protected hashes and scan for retired runtime symbols.
