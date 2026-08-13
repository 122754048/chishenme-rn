# USFR Commercial Reason Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require every commercially promoted product, App, garment, jewelry, accessory, or device to rebuild a credible audience-stop and continue-watching reason before script approval and paid generation.

**Architecture:** Extend only the evidence-bound marketing-analysis contract and the user-script planning input. Add a `commercial_role` independent from technical `asset_type`, plus an evidence-bound `ad_reasoning` object. Validate it before script creation and expose only approved business-facing actions, dialogue, and product proof in the existing public script. Do not modify any binding, prompt compiler, prompt syntax, provider routing, or generation request code.

**Tech Stack:** Python 3.12, pytest, existing USFR `video-edit-v2` contracts.

## Global Constraints

- Do not modify person or multi-object binding rules, formats, indices, mappings, receipts, or audits.
- Do not modify Seedance or H3 prompt compilers, prompt wording, prompt structure, weighting, or reference syntax.
- Do not modify provider routing, UI splice, segmentation, audio, assembly, retry, or QC.
- Preserve existing selling-point and pain-point semantics; add required commercial-reason fields without renaming or weakening existing fields.
- Product-ad reasoning applies by `commercial_role`, not only by technical `asset_type`.
- Unsupported claims must remain blocked; cross-category replacement alone is not `unsuitable`.

---

### Task 1: Add commercial-reason validation

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/marketing_analysis_contract.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_marketing_analysis_contract.py`

**Interfaces:**
- Consumes: one per-asset marketing-analysis row.
- Produces: normalized `commercial_role` and `ad_reasoning` with audience, pain intensity, source hook, stop trigger, continuation reason, proof payoff, counterintuitive contrast, evidence boundary, and removed source claims.

- [ ] Write failing tests for promoted garment analysis, missing ad-reasoning fields, and non-promoted direct replacement.
- [ ] Run the focused test and verify the expected failure.
- [ ] Add the minimal normalization and validation functions.
- [ ] Run the focused test and verify it passes.

### Task 2: Require the fields from target analysis and script schema

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/production_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_commercial_reasoning.py`

**Interfaces:**
- Consumes: source hook evidence and target asset evidence.
- Produces: immutable marketing-analysis rows carrying commercial intent into script planning.

- [ ] Write failing schema and stage-projection tests.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Add required-output descriptions, JSON schema fields, and normalized stage projection.
- [ ] Run focused tests and verify they pass.

### Task 3: Make the public script reflect the rebuilt ad reason without exposing internals

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/user_script_document.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_commercial_reasoning.py`

**Interfaces:**
- Consumes: approved change rows and normalized commercial-reason evidence.
- Produces: the existing public script structure with business-facing display focus, actions, dialogue, and proof only.

- [ ] Write a failing test proving a garment sold as the core product receives the rebuilt stop/continue/proof logic while technical fields stay hidden.
- [ ] Run the focused test and verify failure.
- [ ] Add the smallest public projection needed to present the approved ad reason.
- [ ] Run focused tests and verify they pass.

### Task 4: Document and verify the frozen boundaries

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_commercial_reasoning.py`

**Interfaces:**
- Consumes: the completed analysis contract.
- Produces: a concise workflow rule future calls must follow.

- [ ] Add a test that hashes protected binding and prompt files before/after the change and asserts unchanged contents.
- [ ] Add concise Skill documentation stating that commercial role is independent from asset type and that cross-category edits rebuild the advertising reason.
- [ ] Run focused marketing/user-script tests.
- [ ] Run protected binding and prompt regression tests.
- [ ] Run full Skill regression and bundle validation.

