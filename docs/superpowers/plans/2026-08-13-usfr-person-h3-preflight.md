# USFR Person and H3 Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and execute each task inline.

**Goal:** Add paid-call preflight for canonical person assets and force every H3 request through the two-document background compiler and audit, without changing public scripts, UI media semantics, or QC.

**Architecture:** Extend the existing person asset preparer and H3 edit contract rather than adding workflow stages. H3 compilation emits a versioned document receipt consumed by the existing audit stage. Existing marketing analysis remains before script publication; existing UI splice remains opaque and position-driven.

**Tech Stack:** Python 3.12, Pillow, pytest, existing USFR packaged stages.

## Global Constraints

- No new QC stage, metric, retry, or approval.
- Public reverse storyboard structure remains unchanged and must not expose model names or binding syntax.
- Seedance binding and prompt rules are untouched.
- UI operation video is never interpreted; only its approved placement is executed.

### Task 1: Canonical person preflight

**Files:**
- Modify: `scripts/prepare_person_identity_assets.py`
- Modify: `tests/test_prepare_person_identity_assets.py`

- [ ] Add failing tests for EXIF orientation receipt, exact source/output dimensions, deterministic SHA, invalid crop and non-single-person evidence.
- [ ] Run the focused test and verify RED.
- [ ] Implement the minimum manifest fields and fail-closed validation before any provider-facing asset use.
- [ ] Run focused tests and verify GREEN.

### Task 2: H3 document-governed compiler

**Files:**
- Create: `references/h3-official-document-contract.md`
- Modify: `server/h3_edit_contract.py`
- Modify: `tests/test_h3_edit_contract.py`

- [ ] Add failing tests requiring the six ordered sections, English body, `<d>` target-language dialogue, stable speaker IDs, final speech boundary, and a two-document receipt.
- [ ] Add failing tests rejecting legacy handwritten short prompts and stale/missing document receipts.
- [ ] Run tests and verify RED.
- [ ] Implement the minimum compiler and request audit fields.
- [ ] Run tests and verify GREEN.

### Task 3: Existing H3 stage integration

**Files:**
- Modify: `server/packaged_stages.py`
- Modify: `tests/test_packaged_stages.py`

- [ ] Add a failing integration test proving `H3PromptStage` emits the document receipt and `H3AuditStage` rejects altered Prompt bytes.
- [ ] Run the test and verify RED.
- [ ] Wire the existing compile/audit stages to the new contract without adding a stage.
- [ ] Run the test and verify GREEN.

### Task 4: Preserve public-script, commercial-analysis, UI and QC boundaries

**Files:**
- Modify only tests if the existing implementation already satisfies the contracts.

- [ ] Add/extend regression assertions: public script contains no H3/model/binding terms; commercial reasoning is required before script generation; UI operation media does not enter analysis; stage list/QC catalog is unchanged.
- [ ] Run the focused tests. If they pass immediately, record them as existing behavior rather than changing production code.

### Task 5: Verification

- [ ] Run all focused tests for person assets, H3 contracts/stages, public content, marketing analysis and UI opacity.
- [ ] Run the complete Skill test suite.
- [ ] Compare stage names and QC catalog before/after; assert no additions.
- [ ] Review diffs and confirm no Seedance prompt/binding file changed.
