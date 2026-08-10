# Seedance Universal Source-Object Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic source-object binding for every supported edit layer, validate it first with a 3–5 second Reinbow central-male calibration, and deliver the complete Reinbow video with all four approved character replacements successful.

**Architecture:** A universal source-object registry validates evidence-backed visual locators for people, products, Apps, backgrounds, garments, jewelry, and accessories. Type-specific target boards and a binding-first V2 prompt compiler preserve the existing twenty-step workflow while making every paid replacement explicit. A calibrated capability gate selects safe decomposition without adding user-visible slots, approvals, Provider routes, or deliverables.

**Tech Stack:** Python 3, pytest, FFmpeg, Pillow, RunningHub Image2, RunningHub Seedance 2.0 Standard API.

## Global Constraints

- Use the local `universal-source-fidelity-replication` and packaged `seedance-20` rules.
- Do not map model assets to source people by input order.
- Do not claim Morphic guidance is an official Seedance guarantee.
- Use one-variable retries and at most two paid calibration attempts for the same failure signature.
- Preserve unrelated workspace changes and never stage unrelated files.
- Every paid request must be dry-run audited before submission.

---

### Task 1: Canonical source-object registry

**Files:**
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/source_object_binding.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/source_content_timeline.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_source_object_binding.py`

**Interfaces:**
- Produces: `build_source_object_registry(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]`
- Produces: `validate_target_bindings(bindings, registry) -> list[dict[str, Any]]`
- Consumes: frozen person tracks, product/prop evidence, garment attachment, App/device regions, and scene evidence.

- [ ] Write failing tests proving stable IDs and visual locators for every supported object type, duplicate IDs fail, speaker-only tracks fail for model replacement, input order never changes mapping, incompatible types fail, and low confidence fails closed.
- [ ] Run `python -m pytest tests/test_source_object_binding.py -q` and confirm the new tests fail.
- [ ] Implement strict canonicalization for `source_object_id`, `object_type`, `visual_locator`, active window, state/trajectory/attachment, confidence, visible-area ratio, and occlusion ratio.
- [ ] Extend `source_content_timeline.py` to preserve these fields without changing audio speaker-assignment behavior.
- [ ] Run the focused tests and the existing source-timeline tests.

### Task 2: Bind every approved target asset to source-object IDs

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/approved_edit_contract.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/production_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_edit_contracts.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_packaged_stage_ports.py`

**Interfaces:**
- Consumes: registry from Task 1.
- Produces: canonical bindings with `replaces_tag=source_object_id`, `source_object_descriptor`, `replacement_scope`, `preserve_scope`, and `binding_confidence`; model bindings also carry `identity_scope=face_hair_skin`.

- [ ] Add failing tests showing explicit person/product/App/scene/garment/accessory mappings survive canonical ordering and reach asset-board and prompt stages.
- [ ] Add failing tests showing missing, unknown, duplicated, or ambiguous `replaces_tag` values stop before provider creation.
- [ ] Extend the approved binding schema and canonical SHA coverage with the three new fields.
- [ ] Replace `_source_person_descriptors` order pairing with registry lookup by `replaces_tag`.
- [ ] Run the focused V2 contract and packaged-stage tests.

### Task 3: Replace multi-angle human boards with identity portraits

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/runninghub_workflows.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/runninghub_standard_contract.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_runninghub_workflows.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_edit_contracts.py`

**Interfaces:**
- Produces: `model-identity-v3` board receipts and one-person portrait boards.

- [ ] Write a failing test asserting the model template requests one dominant head-and-shoulders portrait and excludes multi-view, A-pose, side/back strips, and wardrobe control.
- [ ] Write a failing receipt-lineage test for `model-identity-v3`.
- [ ] Implement the identity-only prompt and version routing while leaving garment, scene, product, and app templates unchanged.
- [ ] Update manifest validation to accept the new model template only for model assets.
- [ ] Run workflow and V2 manifest tests.

### Task 4: Compile binding-first prompts and preserve unchanged audio

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/scripts/seedance_prompt_compiler.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/runninghub_standard_contract.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_seedance_prompt_compiler.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_runninghub_standard_seedance.py`

**Interfaces:**
- Consumes: canonical binding fields from Task 2.
- Produces: prompt lines defining `Subject N`, repeating `Subject N@ImageN`, naming the source-person locator, and limiting the image to `face_hair_skin`.

- [ ] Write failing tests that require identity definitions before generic preservation text and prohibit generic `@ImageN binds PersonN` for model assets.
- [ ] Write a failing test that unchanged dialogue is absent from an identity-only prompt and yields `preserve_unmodified_audio`.
- [ ] Pass source-person fields from the asset-board manifest into `compile_edit_prompt`.
- [ ] Implement compact positive bindings and enforce the 1500-character compact target for a one-person calibration prompt.
- [ ] Correct the V2 provider payload to `realPersonMode=true` and `conversionSlots=["all"]` whenever `@Video1` is present.
- [ ] Run prompt compiler and RunningHub payload tests.

### Task 5: Add the calibrated universal replacement capability gate

**Files:**
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/replacement_capability.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_replacement_capability.py`

**Interfaces:**
- Produces: `assess_replacement(bindings, registry, duration_ms, interaction_flags) -> dict[str, Any]` with decisions `calibration_ready`, `direct_fit`, `split_required`, `manual_review_required`, or `hybrid_route_recommended`.

- [ ] Write the decision-table tests for object type, counts, confidence, visible area, occlusion, duration, attachment/contact, UI/text route, and motion complexity.
- [ ] Implement the local thresholds exactly as specified in the design.
- [ ] Invoke the gate before Image2 and Seedance paid calls and publish its digest in request audit evidence.
- [ ] Run the focused tests and provider-boundary regression tests.

### Task 6: Regression verification and Skill documentation

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/video-edit-v2-contract.md`
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/source-person-binding-contract.md`

- [ ] Document deterministic source-person IDs, identity-only portraits, Morphic evidence grade, capability decisions, and the retry budget.
- [ ] Run `python -m pytest tests/test_source_object_binding.py tests/test_replacement_capability.py tests/test_seedance_prompt_compiler.py tests/test_runninghub_standard_seedance.py tests/test_v2_edit_contracts.py tests/test_v2_packaged_stage_ports.py -q`.
- [ ] Run the full USFR test suite and record exact pass/fail counts.
- [ ] Inspect `git diff` or filesystem diffs to ensure no unrelated user files changed.

### Task 7: Reinbow central-male calibration

**Files:**
- Create under: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/calibration_b/`

- [ ] Freeze `SRC_A` with the descriptor “0.00秒首次位于画面中央、穿黑色彩虹连帽衫并持手机的男性”.
- [ ] Extract a 3–5 second source window in which SRC_A remains large and visible.
- [ ] Create or crop one clean target identity portrait; do not use the existing multi-angle board.
- [ ] Generate the audited binding-first prompt and request JSON.
- [ ] Dry-run and verify image order, source-slice SHA, prompt tags, `realPersonMode=true`, and `conversionSlots=["all"]`.
- [ ] Submit the approved request to RunningHub, poll, download, and preserve receipts.
- [ ] Generate a time-matched contact sheet comparing source, result, and target.
- [ ] Score the acceptance criteria. If the first take fails, change only one of portrait crop, locator wording, or clip window and perform the one remaining paid attempt.
- [ ] Record either `accepted` with evidence or `hybrid_route_recommended` with the two controlled failure receipts.

### Task 8: Four-character expansion, assembly, and final QC

**Files:**
- Create under: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/four_character_edit/`
- Deliver: `C:/Users/zhaocx04/Documents/New project/exports/reinbow_four_character_replacement_final.mp4`

- [ ] Promote the accepted central-male calibration rules to the remaining source-bound segments.
- [ ] Replace the blonde woman, dark-haired woman, and alien/cat identity using type-appropriate single-reference boards and the smallest safe simultaneous set.
- [ ] Preserve accepted-pass lineage so later passes cannot silently revert earlier identities.
- [ ] Assemble source-bound segments without retiming and restore approved original audio where unchanged.
- [ ] Generate final contact sheets across all character appearances and verify all four identities, source wardrobe/actions, phone interactions, background, camera, and exact duration.
- [ ] Repeat controlled decomposition until every character passes final QC.

### Task 9: Reusable universal handoff

**Files:**
- Create: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/calibration_b/calibration_report.md`
- Update: `C:/Users/zhaocx04/Documents/New project/analysis/reverse_storyboard_script.md` only if the approved replacement mapping changes.

- [ ] Document the final source-person registry, target binding, portrait recipe, prompt pattern, paid-attempt ledger, QC result, and next routing decision.
- [ ] Re-run the exact final verification commands immediately before declaring the goal complete.
- [ ] Document generic recipes and tests for person, product, App, scene/background, garment, jewelry, and accessory replacement without changing the user-visible workflow.
- [ ] Mark the goal complete only after the final four-character MP4 passes QC and the universal binding regression suite passes.
