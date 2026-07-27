# USFR Segment Prompt Budget and Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Prove every Seedance generated segment is at most 5,000 characters before script approval, and show shared visual facts only once across uninterrupted cuts.

**Architecture:** Add a deterministic continuity projection that owns evidence-backed visual facts and a deterministic prompt-budget planner that runs the packaged Seedance compiler against every planned segment. Carry the private projection and budget plan through the existing script revision and Invocation-B integrity boundaries; add neither a public stage nor a user approval.

**Tech Stack:** Python 3.12, dataclasses, existing high-fidelity projection, packaged Seedance compiler, Redis ephemeral revisions, FastAPI, pytest.

## Global Constraints

- Apply only to non-language-only routes that build Seedance generated segments; keep direct-language-only unchanged.
- Keep the existing maximum of two generated regions, boards, and Seedance tasks. Split only at an allowed Cut boundary when the second region is available.
- Preserve seven slots, background music, lip sync, TTS concurrency, Provider retry/idempotency behavior, and the existing two approvals.
- Inherit a fact only when adjacent Cuts share the same canonical fact ID and the same validated evidence. Never use text similarity.
- Remove only inherited visual setup. Do not remove dialogue, narration, subtitles, lyrics, chorus, selling point, proof/offer, screen text, CTA, disclaimer, action, timing, product truth, or compliance constraints.
- Do not modify C:\Users\zhaocx04\.codex\skills\seedance-20.
- Keep prompts, character counts, hashes, provider/model names, and planner internals out of the public script response.
- Final preview/compile mismatch must block before a paid Provider request.

---

## File Structure

- Create C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\continuity_projection.py: evidence-only fact ownership and private user/prompt projection.
- Create C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\prompt_budget.py: exact compiler preview, legal repartition, stored-plan revalidation, and public conflicts.
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\user_editable_script.py: use only projected visual prose.
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\high_fidelity_projection.py: derive facts from existing evidence and preflight the Invocation-A candidates.
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\seedance_prompt_compiler.py: render an anchor once and inherited later shots without duplicate facts.
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\review_models.py, server\ephemeral_service.py, and server\seedance_invocations.py: freeze and verify the private budget plan.
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md: document the approved public behavior.
- Create tests\test_continuity_projection.py and tests\test_prompt_budget.py; extend test_user_editable_script.py, test_high_fidelity_projection.py, test_seedance_prompt_compiler.py, test_review_service.py, test_seedance_prescript.py, and test_cleanup_contract.py.

### Task 1: Evidence-Backed Continuity Projection

**Files:**
- Create C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\continuity_projection.py
- Create C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_continuity_projection.py

**Interfaces:**
- build_continuity_projection(cuts, *, segment_cut_ids) -> ContinuityProjection
- ContinuityProjection.projected_visual(cut_id) -> str
- ContinuityProjection.apply_to_segment(segment) -> dict[str, Any]
- Invalid or non-adjacent continuity claims raise ValueError before a Provider path.

- [ ] **Step 1: Write failing anchor/inheritance tests**

~~~python
def test_adjacent_cuts_with_one_evidenced_tree_show_the_tree_once():
    projection = build_continuity_projection(
        [
            {
                "cut_id": "C01",
                "scene_id": "temple",
                "visual": "A large cedar tree stands beside the temple path.",
                "continuity_facts": [{
                    "fact_id": "ENV-TREE-01",
                    "kind": "environment",
                    "text": "A large cedar tree stands beside the temple path.",
                    "source_evidence_ids": ["E-11"],
                    "scope_cut_ids": ["C01", "C02"],
                }],
            },
            {
                "cut_id": "C02",
                "scene_id": "temple",
                "visual": "The same large cedar tree remains behind her as she raises the phone.",
                "continuity_facts": [{
                    "fact_id": "ENV-TREE-01",
                    "kind": "environment",
                    "text": "A large cedar tree stands beside the temple path.",
                    "source_evidence_ids": ["E-11"],
                    "scope_cut_ids": ["C01", "C02"],
                }],
            },
        ],
        segment_cut_ids={"S01": ("C01", "C02")},
    )
    assert projection.projected_visual("C01") == "A large cedar tree stands beside the temple path."
    assert projection.projected_visual("C02") == "Continue from the previous shot. She raises the phone."
~~~

- [ ] **Step 2: Run the failing test**

Run: python -B -m pytest tests/test_continuity_projection.py::test_adjacent_cuts_with_one_evidenced_tree_show_the_tree_once -q

Expected: FAIL because server.continuity_projection is absent.

- [ ] **Step 3: Implement immutable facts and projections**

~~~python
@dataclass(frozen=True)
class ContinuityFact:
    fact_id: str
    kind: str
    text: str
    source_evidence_ids: tuple[str, ...]
    scope_cut_ids: tuple[str, ...]

@dataclass(frozen=True)
class ContinuityProjection:
    facts: tuple[ContinuityFact, ...]
    owner_by_fact_id: Mapping[str, str]
    inherited_fact_ids_by_cut: Mapping[str, tuple[str, ...]]
    visual_by_cut_id: Mapping[str, str]

    def projected_visual(self, cut_id: str) -> str:
        return self.visual_by_cut_id[cut_id]
~~~

Normalize a fact only when all scope Cuts are adjacent, have one scene ID, and repeat the exact fact ID, text, and evidence IDs. Keep the later Cut's non-fact visual clause. Do not add fuzzy matching.

- [ ] **Step 4: Write changed-state tests**

~~~python
@pytest.mark.parametrize(
    "second",
    [
        {"scene_id": "street", "fact_id": "ENV-TREE-01", "evidence": "E-11"},
        {"scene_id": "temple", "fact_id": "ENV-TREE-02", "evidence": "E-11"},
        {"scene_id": "temple", "fact_id": "ENV-TREE-01", "evidence": "E-99"},
    ],
)
def test_changed_scene_fact_or_evidence_keeps_later_visual(second):
    projection = build_continuity_projection(_cuts_with_second(second), segment_cut_ids={"S01": ("C01", "C02")})
    assert "large cedar tree" in projection.projected_visual("C02")
~~~

- [ ] **Step 5: Run the focused suite**

Run: python -B -m pytest tests/test_continuity_projection.py -q

Expected: PASS, including non-adjacent, changed-fact, changed-product-state, and changed-wardrobe cases.

- [ ] **Step 6: Commit**

~~~bash
git add C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\continuity_projection.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_continuity_projection.py
git commit -m "feat: project USFR continuity anchors"
~~~

### Task 2: Show Continuity Once in the User Script

**Files:**
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\user_editable_script.py
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_user_editable_script.py

**Interfaces:**
- Extend build_user_editable_script with continuity_projection: ContinuityProjection | None = None.
- Preserve all existing public fields, stable row keys, storage compatibility, and editing behavior.

- [ ] **Step 1: Write the failing user-script test**

~~~python
def test_public_script_shows_continuation_without_private_fact_data():
    document = build_user_editable_script(
        _continuous_tree_cuts(),
        title="Temple app video",
        output_language="pt",
        product_name="Tribe",
        continuity_projection=_tree_projection(),
    )
    public = document.to_public_dict()
    assert public["scenes"][0]["visual"] == "A large cedar tree stands beside the temple path."
    assert public["scenes"][1]["visual"] == "Continue from the previous shot. She raises the phone."
    assert "ENV-TREE-01" not in repr(public)
~~~

- [ ] **Step 2: Run the failing test**

Run: python -B -m pytest tests/test_user_editable_script.py::test_public_script_shows_continuation_without_private_fact_data -q

Expected: FAIL because the builder does not accept a continuity projection.

- [ ] **Step 3: Use projected visual prose only**

~~~python
visual = (
    continuity_projection.projected_visual(scene_id)
    if continuity_projection is not None
    else str(cut.get("visual") or cut.get("scene") or cut.get("action") or "").strip() or "None"
)
scenes.append(UserEditableScene(scene_number, scene_id, start_ms, end_ms, visual))
~~~

Validate exact Cut coverage before indexing. Do not serialize fact IDs, evidence IDs, segment IDs, or planner data in UserEditableScript.

- [ ] **Step 4: Add dense-content regression test**

~~~python
def test_continuity_never_merges_dialogue_lyrics_or_sales_rows():
    document = build_user_editable_script(
        _two_continuous_cuts_with_two_speakers_lyrics_and_cta(),
        title="App video",
        output_language="pt",
        product_name="Tribe",
        continuity_projection=_tree_projection(),
    )
    assert [row.kind for row in document.rows] == [
        "dialogue", "lyrics", "selling_point", "dialogue", "chorus", "cta"
    ]
~~~

- [ ] **Step 5: Run the two suites**

Run: python -B -m pytest tests/test_continuity_projection.py tests/test_user_editable_script.py -q

Expected: PASS.

- [ ] **Step 6: Commit**

~~~bash
git add C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\user_editable_script.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_user_editable_script.py
git commit -m "feat: show USFR continuity in user scripts"
~~~

### Task 3: Render One Continuity Anchor Per Seedance Segment

**Files:**
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\seedance_prompt_compiler.py
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_seedance_prompt_compiler.py

**Interfaces:**
- Extend compile_prompt with continuity_projection: Mapping[str, Any] | None = None.
- Add _format_continuity_anchor(anchor) and extend _format_shot with inherited_fact_ids.
- Include canonical continuity input in source-contract and output-digest validation.

- [ ] **Step 1: Write the failing compiler test**

~~~python
def test_compiler_renders_shared_tree_once_and_later_shot_as_continuation(tmp_path):
    artifact = module.compile_prompt(
        segment=_two_shot_tree_segment(),
        line_contracts=[_line_for("C01"), _line_for("C02")],
        factors={"camera": True, "audio": True},
        skill_files=_skill_files(tmp_path),
        compiler_checks={name: True for name in module.COMPILER_CHECKS},
        continuity_projection=_tree_prompt_projection(),
    )
    assert artifact["prompt"].count("large cedar tree") == 1
    assert "Shot SH02" in artifact["prompt"]
    assert "inherits anchor facts ENV-TREE-01" in artifact["prompt"]
~~~

- [ ] **Step 2: Run the failing test**

Run: python -B -m pytest tests/test_seedance_prompt_compiler.py::test_compiler_renders_shared_tree_once_and_later_shot_as_continuation -q

Expected: FAIL because compile_prompt has no projection parameter and repeats the tree.

- [ ] **Step 3: Render the anchor and retain every non-inherited field**

~~~python
def _format_continuity_anchor(anchor: Mapping[str, Any]) -> str:
    return "Continuity anchor: " + "; ".join(
        f"{item['kind']}: {item['text']}" for item in anchor["facts"]
    ) + "."

def _format_shot(shot: Mapping[str, Any], index: int, *, inherited_fact_ids: Sequence[str] = ()) -> str:
    inherited = f" Inherits anchor facts {', '.join(inherited_fact_ids)}." if inherited_fact_ids else ""
    return _format_non_inherited_shot_fields(shot, index, inherited_fact_ids) + inherited
~~~

The non-inherited formatter removes only exact fields represented by validated fact IDs. It keeps changed scene, action, endpoint, product truth, camera, lighting, performance, transition, audio, factor IDs, locks, and constraints.

- [ ] **Step 4: Add parity tests**

~~~python
def test_compiler_keeps_new_product_state_when_environment_is_inherited(tmp_path):
    segment = _two_shot_tree_segment()
    segment["shots"][1]["product_or_ui_truth"] = "The opened package reveals the new blue refill pouch."
    artifact = module.compile_prompt(
        segment=segment,
        line_contracts=[_line_for("C01"), _line_for("C02")],
        factors={"camera": True, "audio": True},
        skill_files=_skill_files(tmp_path),
        compiler_checks={name: True for name in module.COMPILER_CHECKS},
        continuity_projection=_tree_prompt_projection(),
    )
    assert artifact["prompt"].count("large cedar tree") == 1
    assert "new blue refill pouch" in artifact["prompt"]

def test_compiler_rejects_unknown_cut_or_fact_in_projection(tmp_path):
    projection = _tree_prompt_projection()
    projection["inherited_fact_ids_by_cut"]["C02"] = ["ENV-NOT-DECLARED"]
    with pytest.raises(ValueError, match="continuity projection"):
        module.compile_prompt(
            segment=_two_shot_tree_segment(),
            line_contracts=[_line_for("C01"), _line_for("C02")],
            factors={"camera": True, "audio": True},
            skill_files=_skill_files(tmp_path),
            compiler_checks={name: True for name in module.COMPILER_CHECKS},
            continuity_projection=projection,
        )

def test_validate_compiled_prompt_rejects_rehashed_anchor_drift(tmp_path):
    artifact = _compiled_tree_artifact(tmp_path)
    artifact["continuity_projection"]["anchors"][0]["facts"][0]["text"] = "A different tree."
    artifact["compiler"]["output_sha256"] = module._sha_json(module._content_without_hash(artifact))
    with pytest.raises(ValueError, match="deterministic compiled prompt"):
        module.validate_compiled_prompt(
            artifact,
            skill_files=_skill_files(tmp_path),
            line_contracts=[_line_for("C01"), _line_for("C02")],
        )
~~~

The first test must show one tree but both distinct product states. The other two must reject before a payload can be prepared.

- [ ] **Step 5: Run compiler regressions**

Run: python -B -m pytest tests/test_seedance_prompt_compiler.py -q

Expected: PASS.

- [ ] **Step 6: Commit**

~~~bash
git add C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\scripts\seedance_prompt_compiler.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_seedance_prompt_compiler.py
git commit -m "feat: compile USFR continuity anchors once"
~~~

### Task 4: Exact Preflight and Legal Two-Region Repartition

**Files:**
- Create C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\prompt_budget.py
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\high_fidelity_projection.py
- Create C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_prompt_budget.py
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_high_fidelity_projection.py

**Interfaces:**
- build_prompt_budget_plan(*, candidates, line_contracts, continuity_projection, factors, skill_files) -> PromptBudgetPlan
- select_budgeted_candidates(*, candidates, compiler, split_candidate) -> tuple[list[dict[str, Any]], PromptBudgetPlan]
- Overflow raises ReplicationError with code SCRIPT_PROMPT_BUDGET_EXCEEDED and only public scene_numbers and row_keys.

- [ ] **Step 1: Write the failing exact-preview test**

~~~python
def test_budget_plan_uses_real_compiler_and_records_each_segment_length(tmp_path):
    plan = build_prompt_budget_plan(
        candidates=[_candidate_with_exact_compiler_inputs("S01")],
        line_contracts=[],
        continuity_projection=_tree_projection(),
        factors={"camera": True},
        skill_files=_skill_files(tmp_path),
    )
    assert plan.entries[0].segment_id == "S01"
    assert plan.entries[0].prompt_characters == len(plan.entries[0].preview_prompt)
    assert plan.entries[0].prompt_characters <= 5000
    assert len(plan.sha256) == 64
~~~

- [ ] **Step 2: Run the failing test**

Run: python -B -m pytest tests/test_prompt_budget.py::test_budget_plan_uses_real_compiler_and_records_each_segment_length -q

Expected: FAIL because server.prompt_budget is absent.

- [ ] **Step 3: Implement exact compiler preview**

~~~python
@dataclass(frozen=True)
class PromptBudgetEntry:
    segment_id: str
    cut_ids: tuple[str, ...]
    prompt_characters: int
    preview_prompt: str
    compiler_output_sha256: str

def build_prompt_budget_plan(*, candidates, line_contracts, continuity_projection, factors, skill_files):
    entries = tuple(
        _compile_preview(candidate, line_contracts, continuity_projection, factors, skill_files)
        for candidate in candidates
    )
    return PromptBudgetPlan(entries=entries, continuity_sha256=continuity_projection.sha256)
~~~

Compile with the packaged seedance_prompt_compiler and candidate-local time/line contracts. Do not estimate character overhead.

- [ ] **Step 4: Write failing split and hard-block tests**

~~~python
def test_over_limit_candidate_splits_at_allowed_boundary(monkeypatch):
    candidates, plan = select_budgeted_candidates(
        candidates=[_two_cut_candidate(allowed_split_cut_ids=["C01"])],
        compiler=_over_limit_only_when_combined,
    )
    assert [candidate["cut_ids"] for candidate in candidates] == [["C01"], ["C02"]]
    assert all(entry.prompt_characters <= 5000 for entry in plan.entries)

def test_unsplittable_or_third_candidate_returns_public_conflict(monkeypatch):
    with pytest.raises(ReplicationError, match="SCRIPT_PROMPT_BUDGET_EXCEEDED") as error:
        select_budgeted_candidates(
            candidates=[_two_cut_candidate(allowed_split_cut_ids=[])],
            compiler=_always_over_limit,
        )
    assert error.value.details == {
        "scene_numbers": [1],
        "row_keys": ["Scene 01 / Screen Text 01"],
    }
~~~

- [ ] **Step 5: Implement constrained repartition**

~~~python
def select_budgeted_candidates(*, candidates, compiler, split_candidate):
    plan = _plan(candidates, compiler)
    overflow = next((entry for entry in plan.entries if entry.prompt_characters > 5000), None)
    if overflow is None:
        return list(candidates), plan
    replacement = split_candidate(overflow.segment_id)
    if replacement is None or len(candidates) - 1 + len(replacement) > 2:
        raise _public_budget_conflict(overflow)
    return select_budgeted_candidates(
        candidates=_replace_candidate(candidates, overflow.segment_id, replacement),
        compiler=compiler,
        split_candidate=split_candidate,
    )
~~~

Use the existing high-fidelity timing/candidate projection for each replacement. Preserve Cut order, bounds, factor coverage, line windows, and the existing 4-15 second and two-region rules.

- [ ] **Step 6: Run the planner inside Invocation A**

In build_invocation_a_request, derive continuity facts only from shared validated factor/evidence records, call select_budgeted_candidates, and return continuity_projection plus prompt_budget_plan with the existing candidate_regions. Preserve the current greater-than-two fail-closed branch.

- [ ] **Step 7: Run focused preflight suites**

Run: python -B -m pytest tests/test_prompt_budget.py tests/test_high_fidelity_projection.py tests/test_seedance_prescript.py -q

Expected: PASS.

- [ ] **Step 8: Commit**

~~~bash
git add C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\prompt_budget.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\high_fidelity_projection.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_prompt_budget.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_high_fidelity_projection.py
git commit -m "feat: preflight USFR Seedance prompt budgets"
~~~

### Task 5: Freeze the Plan Across Edits and Final Compilation

**Files:**
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\review_models.py
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ephemeral_service.py
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\seedance_invocations.py
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_review_service.py
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_seedance_prescript.py

**Interfaces:**
- RevisionManifest gains optional private continuity_projection and prompt_budget_plan mappings.
- complete_user_editable_script gains optional continuity_projection and prompt_budget_plan.
- edit_user_script revalidates a stored plan before appending a revision.
- SeedanceInvocationAdapter.invoke_b accepts prompt_budget_plan and proves its selected entry matches the final compiler artifact.

- [ ] **Step 1: Write the failing persistence test**

~~~python
def test_script_revision_persists_private_budget_without_public_leak(service, job):
    service.complete_user_editable_script(
        job.job_id,
        expected_version=job.version,
        document=_user_document(),
        inputs_sha256="a" * 64,
        continuity_projection=_tree_projection().to_storage_dict(),
        prompt_budget_plan=_budget_plan().to_storage_dict(),
    )
    manifest = service.job_store.get_current_revision(job.job_id, "script")
    assert manifest.prompt_budget_plan["entries"][0]["prompt_characters"] < 5000
    assert "prompt_budget_plan" not in service.get_user_script(job.job_id)
~~~

- [ ] **Step 2: Run the failing test**

Run: python -B -m pytest tests/test_review_service.py::test_script_revision_persists_private_budget_without_public_leak -q

Expected: FAIL because RevisionManifest has no private plan fields.

- [ ] **Step 3: Persist and revalidate**

~~~python
def edit_user_script(self, job_id, *, expected_version, edits):
    manifest, document = self._current_user_script(job_id)
    edited = apply_user_script_edits(document, edits)
    validate_stored_prompt_budget_plan(edited, manifest.prompt_budget_plan)
    return self.complete_user_editable_script(
        job_id,
        expected_version=expected_version,
        document=edited,
        inputs_sha256=manifest.inputs_sha256,
        continuity_projection=manifest.continuity_projection,
        prompt_budget_plan=rebuild_prompt_budget_plan(edited, manifest.prompt_budget_plan),
    )
~~~

A generated script with no budget plan fails closed. Omitted rows, key bindings, and current downstream invalidations stay unchanged.

- [ ] **Step 4: Write failing Invocation-B parity tests**

~~~python
def test_invocation_b_rejects_prompt_different_from_frozen_preview():
    with pytest.raises(ReplicationError, match="PROMPT_INTEGRITY_FAILED"):
        adapter.invoke_b(
            context=_context(),
            segment_plan=_segment_plan(),
            prompt_budget_plan=_budget_plan_with_wrong_preview_sha(),
            prompt_request=_prompt_request(),
        )
~~~

Add separate failures for changed segment ID, changed Cut order, and 5,001 characters. Each must occur before Provider authorization.

- [ ] **Step 5: Bind the final compiler result**

~~~python
def _validate_prompt_budget_binding(plan, *, segment_id, cut_ids, compiled_artifact):
    entry = _budget_entry_for_segment(plan, segment_id)
    if tuple(entry["cut_ids"]) != tuple(cut_ids):
        raise ValueError("frozen prompt-budget Cut order changed")
    if entry["compiler_output_sha256"] != compiled_artifact["compiler"]["output_sha256"]:
        raise ValueError("compiled prompt differs from frozen preflight")
~~~

Convert these failures through the existing PROMPT_INTEGRITY_FAILED boundary. Keep seedance_submit.py as its existing independent 1-5000 payload guard.

- [ ] **Step 6: Run review and compiler suites**

Run: python -B -m pytest tests/test_review_service.py tests/test_seedance_prescript.py tests/test_seedance_prompt_compiler.py tests/test_server_fastapi_router.py -q

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\review_models.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ephemeral_service.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\seedance_invocations.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_review_service.py C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_seedance_prescript.py
git commit -m "feat: freeze USFR prompt budget approvals"
~~~

### Task 6: Document Behavior and Verify Regressions

**Files:**
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md
- Modify C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_cleanup_contract.py

- [ ] **Step 1: Write the failing documentation test**

~~~python
def test_skill_requires_pre_script_segment_feasibility_and_continuity_inheritance():
    skill = _read_skill()
    assert "Establish a continuous scene once; later uninterrupted cuts state only what changes." in skill
    assert "Before script confirmation, verify every Seedance generated segment fits the 5000-character prompt limit." in skill
    assert "Never remove dialogue, lyrics, selling points, or other necessary content to meet the limit." in skill
~~~

- [ ] **Step 2: Run the failing test**

Run: python -B -m pytest tests/test_cleanup_contract.py::test_skill_requires_pre_script_segment_feasibility_and_continuity_inheritance -q

Expected: FAIL because the approved wording is absent.

- [ ] **Step 3: Add only this public contract beside existing script approval rules**

~~~markdown
For a continuous scene, establish shared visual information once. Each uninterrupted following cut states only the new action, camera, dialogue, lyric, text, or changed visual fact. Before script confirmation, verify that every Seedance generated segment fits the 5000-character prompt limit. Remove only proven repeated visual setup; never remove dialogue, lyrics, selling points, or other necessary content.
~~~

- [ ] **Step 4: Run focused and regression suites**

Run: python -B -m pytest tests/test_continuity_projection.py tests/test_prompt_budget.py tests/test_user_editable_script.py tests/test_high_fidelity_projection.py tests/test_seedance_prescript.py tests/test_seedance_prompt_compiler.py tests/test_review_service.py tests/test_review_workflow.py tests/test_ephemeral_runtime.py tests/test_server_fastapi_router.py tests/test_job_api.py tests/test_production_ports.py tests/test_cleanup_contract.py -p no:cacheprovider -q

Expected: PASS. Report unrelated pre-existing failures separately without changing unrelated files.

- [ ] **Step 5: Verify packaged closure**

Run: python -B scripts/verify_lightweight_bundle.py

Expected: Feature source/tests are in the bundle closure. Record any pre-existing cache cleanliness report separately and do not delete caches in this task.

- [ ] **Step 6: Commit**

~~~bash
git add C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_cleanup_contract.py
git commit -m "docs: describe USFR prompt feasibility"
~~~

## Plan Self-Review

**Spec coverage:** Tasks 1-3 cover evidence-only fact ownership, user script display, and one-anchor prompt rendering. Task 4 performs exact preflight and constrained automatic splitting before script approval. Task 5 persists/rechecks the plan after edits and rejects final drift. Task 6 documents the user-visible rule and verifies the full affected surface.

**Scope check:** The plan does not add an approval, stage, slot, Provider call, semantic fuzzy matcher, or third generated region. It preserves direct language-only, fixed slots, music, lip-sync, and dense/multi-speaker rows.

**Type consistency:** ContinuityProjection is created in Task 1 and consumed by Tasks 2-4. PromptBudgetPlan is created in Task 4, persisted in Task 5, and never appears in public script output.

**Placeholder scan:** No implementation section relies on an unspecified validation or deferred step.
