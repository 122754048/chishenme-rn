# USFR UI Interaction Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild source-video UI interactions deterministically when only new product/model evidence is supplied, while retaining the existing opaque UI-video route and skipping absent source UI at zero added cost.

**Architecture:** Keep the public seven-slot contract unchanged. Add a small source-UI interaction contract that converts already-identified UI Cuts into exact frame windows and supported per-frame transform tracks. Route eligible product/model-only UI Cuts into the existing `generated_ui_demo` lane, then require the existing renderer boundary to receive the frozen interaction contract and a UTF-8 target copy contract.

**Tech Stack:** Python 3.12, existing OpenCV dependency, FFmpeg, existing `DeterministicUiRenderer`/`EvidenceBoundHttpUiRenderer` boundary, pytest.

## Global Constraints

- Do not add a public input slot or change the seven existing slot meanings.
- `ui_operation_video` remains `opaque_ui_demo`; no semantic UI redraw is run for its body.
- Only detected source UI Cuts may enter UI reconstruction; a source with no UI remains zero-cost for this feature.
- Do not send UI pixels, UI text, or UI animation to Seedance.
- UI target text is UTF-8, preserves source language when `output_language` is null, and uses the requested language when present.
- Do not add deep QA, frame-by-frame full-video comparison, automatic retry, or extra Provider work.
- Do not modify non-UI routing, script/storyboard approvals, audio, Seedance prompts, tail handling, or product/model generation.

---

### Task 1: Freeze minimal source UI interaction contracts

**Files:**
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/ui_interaction_contract.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_ui_interaction_contract.py`

**Interfaces:**
- Consumes: one source UI region and its source Cut facts.
- Produces: `build_source_ui_interaction_contract(region, source_language)` returning canonical `source-ui-interaction/v1` data with exact frame window, target language, supported motion slots, and basic QA sampling points.

- [ ] **Step 1: Write the failing tests** for UI eligibility, source-language fallback, target-language override, and rejection of an interval with invalid timing.
- [ ] **Step 2: Run** `pytest tests/test_ui_interaction_contract.py -q` and confirm import failure.
- [ ] **Step 3: Implement** a dependency-free contract builder and validator. It records only frozen time/frame facts, never performs full-video analysis.
- [ ] **Step 4: Run** `pytest tests/test_ui_interaction_contract.py -q` and confirm pass.

### Task 2: Route product/model-only source UI into the existing generated UI lane

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_packaged_stages.py`

**Interfaces:**
- Consumes: source Cut UI classification, fixed slot presence, and `output_language`.
- Produces: existing `generated_ui_demo` region fields plus `source_ui_interaction_contract` for the deterministic UI renderer.

- [ ] **Step 1: Write failing tests** proving: product/model-only UI Cuts become `generated_ui_demo`; non-UI Cuts retain their current route; supplied UI video remains `opaque_ui_demo`; absent UI source creates no generated UI region.
- [ ] **Step 2: Run** `pytest tests/test_packaged_stages.py -q` and confirm only the new assertions fail.
- [ ] **Step 3: Implement** a narrow UI-Cut classifier and attach the Task-1 contract only to eligible generated UI regions. Preserve all other region policies byte-for-byte.
- [ ] **Step 4: Run** `pytest tests/test_packaged_stages.py -q` and confirm pass.

### Task 3: Bind target content and language safely at the renderer boundary

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/real_capabilities.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_real_capabilities.py`

**Interfaces:**
- Consumes: `source_ui_interaction_contract`, fixed product/model assets, and approved UI copy.
- Produces: an immutable renderer request that carries UTF-8 target copy and interaction facts; no source UI identity/text becomes target truth.

- [ ] **Step 1: Write failing tests** showing the UI renderer rejects malformed interaction contracts, forwards target-language metadata, and leaves ordinary screenshot/App routes unchanged.
- [ ] **Step 2: Run** `pytest tests/test_real_capabilities.py -q` and confirm the new cases fail for missing support.
- [ ] **Step 3: Implement** only the request-validation and evidence binding required by the existing renderer abstraction. The actual renderer remains deterministic and may use an injected Remotion service; no local fallback may invent UI text.
- [ ] **Step 4: Run** `pytest tests/test_real_capabilities.py -q` and confirm pass.

### Task 4: Document the UI-only contract and run focused regression

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/bundled-skills/seedance-storyboard-replication/SKILL.md`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_skill_contract.py`

**Interfaces:**
- Documents the unchanged opaque UI route, automatic source-UI rebuild eligibility, language rule, no-Seedance rule, and basic-only validation.

- [ ] **Step 1: Write failing contract assertions** for the new documented route and unchanged `opaque_ui_demo` priority.
- [ ] **Step 2: Run** `pytest tests/test_skill_contract.py -q` and confirm assertion failure.
- [ ] **Step 3: Update only UI route documentation** and bundled storyboard route exclusions.
- [ ] **Step 4: Run focused suite** `pytest tests/test_ui_interaction_contract.py tests/test_packaged_stages.py tests/test_real_capabilities.py tests/test_skill_contract.py -q`.
- [ ] **Step 5: Run related full regression** `pytest tests/test_fixed_input_slot_contract.py tests/test_source_ui_interval_contract.py tests/test_timeline_region_contract.py tests/test_timeline_splice_real_media.py -q`.
