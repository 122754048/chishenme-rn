# USFR Frame-Midpoint Segment Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `video-edit-v2` to split a 15–30 second single-Cut source into two legal Seedance segments on a deterministic fixed 24 fps midpoint grid while preserving natural-Cut priority and adding forced-boundary continuity evidence.

**Architecture:** Add one pure 24 fps midpoint helper near `SegmentPlanStage`, then use it only when no legal natural Cut exists. Forced splits duplicate the spanning source Cut authority into both segment-local execution records with clipped timing, publish a `forced_continuity_boundary/v1` receipt, and feed its carry-forward state into the existing second-segment continuity prompt. Existing natural-Cut, binding, action-adaptation, complexity, audio, text, and retry behavior remains unchanged.

**Tech Stack:** Python 3.12, pytest, existing USFR `server/packaged_stages.py`, Markdown contracts.

## Global Constraints

- Natural Cut remains the first choice.
- Fallback uses a fixed 24 fps time grid; it does not retime source footage.
- Effective editable duration must remain at most 30 seconds.
- Exactly two contiguous segments cover the complete active interval with no overlap or gap.
- Each Provider segment remains at most 15 seconds.
- Person/object bindings and compact Prompt lines are unchanged.
- Existing retry and QC budgets are unchanged.

---

### Task 1: Specify the deterministic 24 fps boundary helper

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_packaged_stage_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`

**Interfaces:**
- Produces: `SegmentPlanStage._frame_midpoint_boundary_ms(active_end_ms: int) -> dict[str, int | str]`
- Receipt fields: `boundary_mode`, `grid_fps_num`, `grid_fps_den`, `boundary_frame_index`, `boundary_time_us`, `boundary_ms`.

- [ ] **Step 1: Write failing helper tests**

Add parameterized assertions for 16,000 ms → frame 192 / 8,000 ms; 29,000 ms → frame 348 / 14,500 ms; 30,000 ms → frame 360 / 15,000 ms. Add rejection tests for `<=15,000` and `>30,000` inputs.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_v2_packaged_stage_ports.py" -k "frame_midpoint_boundary" -q
```

Expected: FAIL because `_frame_midpoint_boundary_ms` does not exist.

- [ ] **Step 3: Implement the pure helper**

Use integer arithmetic on microseconds. Select the legal 24 fps grid frame nearest `active_end_ms / 2`; ties select the earlier frame. Validate both resulting segment durations are positive and at most 15,000 ms.

- [ ] **Step 4: Run helper tests and verify GREEN**

Run the same pytest command. Expected: PASS.

### Task 2: Use fallback when no legal natural Cut exists

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_packaged_stage_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`

**Interfaces:**
- Consumes: `_frame_midpoint_boundary_ms(active_end_ms)`.
- Produces: `segment_plan.boundary_mode`, `selected_split_boundary_ms`, and two contiguous segment rows.

- [ ] **Step 1: Convert existing blocker tests to failing fallback expectations**

Add a single-Cut 29-second fixture and assert segments `(0, 14500)` and `(14500, 29000)`. Change the “all natural cuts cross performance” and “all legal cuts cross dialogue” tests to assert fallback rather than rejection. Preserve the existing natural-Cut test and assert `boundary_mode == "natural_cut"`.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_v2_packaged_stage_ports.py" -k "segment_plan_stage and (single_cut or natural_cut or performance or dialogue)" -q
```

Expected: fallback cases fail with `SEGMENT_PLAN_INVALID`.

- [ ] **Step 3: Implement minimal planner fallback**

Keep legal natural-Cut selection unchanged. When it yields no boundary, call the helper and set `boundary_mode="frame_midpoint_fallback"`. Allow one source Cut to span both segment rows by assigning the Cut to every segment it intersects, while clipping segment-local execution timing to the segment range.

- [ ] **Step 4: Verify focused tests GREEN**

Run the same command. Expected: PASS.

### Task 3: Publish forced continuity evidence and feed the second prompt

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_packaged_stage_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`

**Interfaces:**
- Produces: `segment_plan.forced_continuity_boundary` with contract `forced-continuity-boundary/v1`.
- Existing `inter_segment_state["S01->S02"].carry_forward` remains the prompt-facing interface.

- [ ] **Step 1: Write failing continuity assertions**

For the 29-second single-Cut case assert the forced receipt contains fixed 24 fps grid evidence, boundary time/frame, `continues_across_boundary`, source Cut ID on both sides, and carry-forward state. Add a prompt-stage test asserting segment two receives the existing concise `Continuity: carry forward approved ...` suffix.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_v2_packaged_stage_ports.py" -k "forced_continuity or carry_forward" -q
```

Expected: FAIL because the receipt is absent or spanning-Cut state cannot be resolved.

- [ ] **Step 3: Implement continuity receipt**

Build the receipt from frozen source Cut state and approved windows that cross the boundary. For a spanning Cut, use that Cut on both sides and carry forward its action/start/end state, source tags, product/App steps, and crossing window IDs. Reuse the existing prompt suffix path; do not change binding lines.

- [ ] **Step 4: Verify continuity tests GREEN**

Run the same command. Expected: PASS.

### Task 4: Add seam-QC authority and update contracts

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_edit_contracts.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_skill_contract_docs.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/video-edit-v2-contract.md`

**Interfaces:**
- Documents: `frame_midpoint_fallback`, fixed 24 fps grid, `forced-continuity-boundary/v1`, seam QC requirements.

- [ ] **Step 1: Add failing documentation contract assertions**

Assert both documents name the fallback, fixed 24 fps grid, natural-Cut priority, maximum 30-second active duration, and seam checks for identity/object/contact/camera/audio plus black/duplicate/missing frames.

- [ ] **Step 2: Run docs tests and verify RED**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_v2_edit_contracts.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_skill_contract_docs.py" -q
```

Expected: FAIL on missing fallback language.

- [ ] **Step 3: Apply minimal contract updates**

Update only duration planning, continuity, and final QC sections. Preserve all binding and action-adaptation text verbatim.

- [ ] **Step 4: Verify docs tests GREEN**

Run the same command. Expected: PASS.

### Task 5: Regression verification

**Files:**
- Verify only; no new behavior.

- [ ] **Step 1: Run targeted segment and prompt tests**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_v2_packaged_stage_ports.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_v2_edit_contracts.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_skill_contract_docs.py" -q
```

Expected: PASS.

- [ ] **Step 2: Run binding and product-action regression suites**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_provider_only_multi_subject_binding.py" "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_product_action_adaptation.py" -q
```

Expected: PASS with no Prompt/binding behavior changes.

- [ ] **Step 3: Run complete Skill tests**

```powershell
python -m pytest "C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests" -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit implementation**

Commit only the relevant Skill source, tests, and contract files; leave unrelated user worktree changes untouched.
