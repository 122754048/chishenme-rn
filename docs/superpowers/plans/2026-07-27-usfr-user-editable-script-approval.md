# USFR User-Editable Script Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a single user-editable script the required first approval for every non-language-only USFR run, then generate the storyboard only from that exact approved script.

**Architecture:** Add a small, deterministic user-script document module that projects internal cuts into stable, user-facing rows and validates structured edits without exposing internal identifiers. Reuse the existing revision lifecycle for persistence, while requiring two review gates for every non-language-only execution route and binding storyboard generation to the compiled approved user-script digest.

**Tech Stack:** Python 3.12, dataclasses, existing ephemeral JobStore/ReplicationService, FastAPI adapter, pytest.

## Global Constraints

- Preserve the sole exemption: `source_video + output_language` with no optional fixed slot and no `background_music` creates neither a script nor storyboard approval gate.
- Every other request has exactly two user approvals: editable script, then storyboard.
- The user-facing script contains no code, JSON, hash, object key, provider/model name, prompt, route, analysis, artifact, or technical error.
- User-visible row keys are deterministic and map internally to an immutable `(scene_id, content_kind, content_row_id, speaker_or_singer_id, ordinal)` binding.
- Omitted rows are preserved; deletion is explicit; insertions name `Insert after: <key>`; ambiguous keys fail before storyboard or Provider work.
- Preserve all dense-copy rows and multi-speaker/narrator/singer/chorus identities. Do not infer shortening, deletion, movement, or reassignment.
- Do not modify fixed-slot semantics, background-music behavior, language-only lip-sync final-MP4 behavior, TTS concurrency, batch scheduling, queues, Provider retry policy, or unrelated cleanup work.

---

## File Structure

- Create `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\user_editable_script.py`: public document model, deterministic public-key projection, structured edit parser, plain-language conflict validation, and compiler input.
- Modify `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\review_models.py`: retain revision storage but add a private parent binding for a compiled approved user script.
- Modify `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\review_workflow.py`: classify direct language-only explicitly and make all other routes require both review gates.
- Modify `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ephemeral_service.py`: create/edit/approve public script revisions and return public script views only.
- Modify `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ephemeral_driver.py`: stop every non-language-only run at script approval and use the approved compiled script parent for storyboards.
- Modify `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\fastapi_router.py`: expose only public script document, edit command, approval command, and plain-language conflicts at the script boundary.
- Modify `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\orchestrator.py`: ensure all non-language-only plans contain both gates and report two approvals.
- Modify `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md`: describe the user-editable script contract and preserve only the direct-language exception.
- Add focused tests in `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_user_editable_script.py` and extend the existing review/service/router/driver test modules.

### Task 1: Define the User-Script Contract and Edit Validator

**Files:**
- Create: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\user_editable_script.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_user_editable_script.py`

**Interfaces:**
- Produces `build_user_editable_script(cuts, *, title, output_language, product_name) -> UserEditableScript`.
- Produces `apply_user_script_edits(document, edits) -> UserEditableScript`.
- Produces `compile_approved_user_script(document) -> tuple[dict[str, Any], ...]`.
- Raises `ReplicationError("USER_SCRIPT_CONFLICT", message, details={"conflicts": [...]})` with public scene/row names only.

- [ ] **Step 1: Write failing tests for stable public keys and allowed content projection**

```python
def test_projection_keeps_dialogue_lyrics_and_screen_text_as_independent_rows():
    document = build_user_editable_script(_cuts_with_two_speakers_singer_and_dense_copy(), title="App video", output_language="pt", product_name="Tribe")
    assert [row.key for row in document.rows] == [
        "Scene 01 / Speaker A / Dialogue 01",
        "Scene 01 / Narrator / Voiceover 01",
        "Scene 01 / Singer / Lyrics 01",
        "Scene 01 / Screen Text 01",
    ]
    assert "sha256" not in document.to_public_dict()
    assert "route" not in document.to_public_dict()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -B -m pytest tests/test_user_editable_script.py::test_projection_keeps_dialogue_lyrics_and_screen_text_as_independent_rows -q`

Expected: FAIL because `server.user_editable_script` does not exist.

- [ ] **Step 3: Implement the smallest immutable projection model**

```python
@dataclass(frozen=True)
class UserScriptRow:
    key: str
    scene_number: int
    kind: str
    speaker: str | None
    text: str
    binding: tuple[str, str, str, str | None, int]

def build_user_editable_script(cuts, *, title, output_language, product_name):
    # derive one public row for each user-editable source row; retain binding privately
    ...
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -B -m pytest tests/test_user_editable_script.py::test_projection_keeps_dialogue_lyrics_and_screen_text_as_independent_rows -q`

Expected: PASS.

- [ ] **Step 5: Write failing tests for exact edit binding, explicit deletion, insertion, and conflicts**

```python
def test_edit_changes_only_the_addressed_dialogue_row():
    changed = apply_user_script_edits(_document(), [{"key": "Scene 01 / Speaker A / Dialogue 01", "text": "New sentence"}])
    assert changed.row("Scene 01 / Speaker A / Dialogue 01").text == "New sentence"
    assert changed.row("Scene 01 / Narrator / Voiceover 01").text == "Original narration"

def test_omitted_row_is_not_deleted_and_delete_must_be_explicit():
    assert len(apply_user_script_edits(_document(), []).rows) == len(_document().rows)
    changed = apply_user_script_edits(_document(), [{"key": "Scene 01 / Screen Text 01", "action": "Delete"}])
    assert "Scene 01 / Screen Text 01" not in [row.key for row in changed.rows]

def test_duplicate_or_unknown_key_returns_only_public_conflicts():
    with pytest.raises(ReplicationError, match="USER_SCRIPT_CONFLICT") as error:
        apply_user_script_edits(_document(), [{"key": "Scene 88 / Speaker Z / Dialogue 01", "text": "x"}])
    assert error.value.details["conflicts"] == ["Scene 88 / Speaker Z / Dialogue 01 was not found."]
```

- [ ] **Step 6: Run the focused tests and verify RED**

Run: `python -B -m pytest tests/test_user_editable_script.py -q`

Expected: FAIL because edit validation is not implemented.

- [ ] **Step 7: Implement minimal structured edits and compilation**

```python
def apply_user_script_edits(document, edits):
    # reject duplicate/missing/changed keys; preserve omitted rows; only Delete removes a row
    # Insert requires an existing "insert_after" public key and derives a new private ordinal
    ...

def compile_approved_user_script(document):
    # return internal cut rows with private bindings only; never alter row identity/order/text
    ...
```

- [ ] **Step 8: Run focused tests and full contract suite**

Run: `python -B -m pytest tests/test_user_editable_script.py tests/test_review_workflow.py -q`

Expected: PASS.

### Task 2: Enforce the Two-Gate Route Rule and Stage Plan

**Files:**
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\review_workflow.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\orchestrator.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_review_workflow.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_ephemeral_runtime.py`

**Interfaces:**
- `resolve_review_route(..., direct_language_only: bool = False) -> ReviewRoute` returns `local_only` only when `direct_language_only=True`; all other input returns the two-gate route.
- `build_stage_plan(...)` contains exactly `await_script_approval` and `await_storyboard_approval` for every non-language-only plan.

- [ ] **Step 1: Write failing tests for the only local-only exemption and route-1 rejection**

```python
def test_matching_old_script_does_not_bypass_a_new_non_language_only_script_approval():
    approved = RevisionManifest.script(revision=2, object_key="x", sha256="a" * 64, inputs_sha256="b" * 64)
    assert resolve_review_route(seedance_required=True, approved_script=approved, current_script_inputs_sha256="b" * 64) == "route_2"

def test_only_explicit_direct_language_only_has_no_review_route():
    assert resolve_review_route(seedance_required=False, approved_script=None, current_script_inputs_sha256="a" * 64, direct_language_only=True) == "local_only"
    assert resolve_review_route(seedance_required=False, approved_script=None, current_script_inputs_sha256="a" * 64, direct_language_only=False) == "route_2"
```

- [ ] **Step 2: Run route tests and verify RED**

Run: `python -B -m pytest tests/test_review_workflow.py -q`

Expected: FAIL because matching scripts still select `route_1` and non-generated work selects `local_only`.

- [ ] **Step 3: Implement direct-language-only classification and remove cache bypasses**

```python
def resolve_review_route(..., direct_language_only: bool = False) -> ReviewRoute:
    if direct_language_only:
        return "local_only"
    # validate language, then require the normal two-approval route regardless of cached revisions
    return "route_2"
```

- [ ] **Step 4: Write the failing stage-plan assertion**

```python
def test_non_language_only_stage_plan_always_has_two_approval_entries():
    plan = build_stage_plan(_non_language_only_manifest(), review_route="route_2")
    assert [stage["name"] for stage in plan].count("await_script_approval") == 1
    assert [stage["name"] for stage in plan].count("await_storyboard_approval") == 1
```

- [ ] **Step 5: Run stage-plan test and verify RED**

Run: `python -B -m pytest tests/test_ephemeral_runtime.py::test_every_non_language_only_plan_has_script_and_storyboard_approvals -q`

Expected: FAIL for the existing local-only/no-generation branch or reuse branch.

- [ ] **Step 6: Implement the minimal plan change and approval projection**

```python
# Preserve the language_only return branch.
# For every other execution route, append build_script, await_script_approval,
# generate_storyboards, await_storyboard_approval, then existing downstream stages.
```

- [ ] **Step 7: Run impacted suites**

Run: `python -B -m pytest tests/test_review_workflow.py tests/test_ephemeral_runtime.py -q`

Expected: PASS.

### Task 3: Persist, Approve, and Compile Public Script Revisions

**Files:**
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\review_models.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ephemeral_service.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_review_service.py`

**Interfaces:**
- `ReplicationService.get_user_script(job_id) -> dict[str, Any]` returns the public document only.
- `ReplicationService.edit_user_script(job_id, *, expected_version, edits) -> snapshot` validates and appends a current script revision.
- `ReplicationService.approve_user_script(job_id, *, revision, expected_version) -> snapshot` compiles exactly the approved public revision and stores its private digest parent for storyboard generation.

- [ ] **Step 1: Write failing service tests for a public-only response and downstream invalidation**

```python
def test_get_user_script_never_leaks_internal_manifest_fields(service, seeded_job):
    view = service.get_user_script(seeded_job)
    assert set(view) == {"title", "target_language", "product_name", "scenes", "must_keep", "do_not_say"}
    assert "object_key" not in repr(view)
    assert "sha256" not in repr(view)

def test_edit_invalidates_storyboard_and_provider_work(service, seeded_job):
    updated = service.edit_user_script(seeded_job, expected_version=1, edits=[{"key": "Scene 01 / Speaker A / Dialogue 01", "text": "Changed"}])
    assert updated.state == "SCRIPT_AWAITING_APPROVAL"
    assert updated.approved_storyboard_sha256 is None
```

- [ ] **Step 2: Run service tests and verify RED**

Run: `python -B -m pytest tests/test_review_service.py -q`

Expected: FAIL because the public-script service methods do not exist.

- [ ] **Step 3: Implement revision wrapping and private compilation parent**

```python
def edit_user_script(self, job_id, *, expected_version, edits):
    document = self._current_user_script_document(job_id)
    edited = apply_user_script_edits(document, edits)
    return self._append_public_script_revision(job_id, expected_version, edited)

def approve_user_script(self, job_id, *, revision, expected_version):
    # CAS-approve that exact revision, compile only it, and retain compiled digest privately.
    ...
```

- [ ] **Step 4: Run service tests and regression tests**

Run: `python -B -m pytest tests/test_review_service.py tests/test_job_api.py -q`

Expected: PASS.

### Task 4: Wire Driver and HTTP Boundary to the Public Contract

**Files:**
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\ephemeral_driver.py`
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\server\fastapi_router.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_ephemeral_runtime.py`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_server_fastapi_router.py`

**Interfaces:**
- The driver pauses before storyboard creation for all non-language-only jobs and resumes only with an approved compiled-script parent.
- Script HTTP responses serialize the user script / public conflicts / expected version only; they never serialize raw `RevisionManifest` dictionaries.

- [ ] **Step 1: Write a failing driver test for the non-language-only pause**

```python
def test_driver_does_not_generate_storyboard_before_user_script_approval(worker, non_language_job):
    worker.run_once(non_language_job)
    assert worker.snapshot(non_language_job).state == "SCRIPT_AWAITING_APPROVAL"
    assert worker.calls_for("generate_storyboards") == []
```

- [ ] **Step 2: Run driver test and verify RED**

Run: `python -B -m pytest tests/test_ephemeral_runtime.py::test_driver_does_not_generate_storyboard_before_user_script_approval -q`

Expected: FAIL because reused/local routes can continue without a script gate.

- [ ] **Step 3: Implement the driver pause and exact storyboard parent check**

```python
if not snapshot.admission.language_only and not snapshot.approved_script_sha256:
    return pause_at_script_approval(snapshot)

# Before storyboard persistence, reject any parent that differs from the
# approved user-script-derived compiled digest.
```

- [ ] **Step 4: Write failing HTTP contract tests**

```python
def test_script_endpoint_returns_only_user_script_fields(client, job_id):
    payload = client.get(f"/jobs/{job_id}/script").json()
    assert "document" in payload
    assert "object_key" not in str(payload)
    assert "provider" not in str(payload).lower()

def test_ambiguous_edit_returns_plain_language_conflicts_without_storyboard_work(client, job_id):
    response = client.post(f"/jobs/{job_id}/script/edits", json={"edits": [{"key": "Scene 99 / Screen Text 01", "text": "x"}]})
    assert response.status_code == 422
    assert response.json()["conflicts"] == ["Scene 99 / Screen Text 01 was not found."]
```

- [ ] **Step 5: Run HTTP tests and verify RED**

Run: `python -B -m pytest tests/test_server_fastapi_router.py -q`

Expected: FAIL because endpoints serialize internal revisions or do not accept public edit payloads.

- [ ] **Step 6: Implement the smallest public-only serializers and commands**

```python
def _public_script_response(document, *, version):
    return {"document": document.to_public_dict(), "version": version}

# Map USER_SCRIPT_CONFLICT to {"conflicts": [...]} and do not propagate
# technical details in this script-stage response.
```

- [ ] **Step 7: Run driver and router suites**

Run: `python -B -m pytest tests/test_ephemeral_runtime.py tests/test_server_fastapi_router.py -q`

Expected: PASS.

### Task 5: Document the User Confirmation Contract and Verify Regression Coverage

**Files:**
- Modify: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md`
- Test: `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\tests\test_cleanup_contract.py`
- Test: all focused suites from Tasks 1-4.

**Interfaces:**
- `SKILL.md` states the public script format, exact edit instructions, script-to-storyboard dependency, and the sole direct-language-only exemption without exposing internal execution details to users.

- [ ] **Step 1: Add a failing documentation-contract assertion**

```python
def test_skill_requires_public_script_approval_before_storyboard_for_every_non_language_only_run():
    skill = _read_skill()
    assert "Only a direct language-only request skips script and storyboard confirmation." in skill
    assert "Omission is not deletion; write Delete beside the exact row." in skill
    assert "Generate the storyboard only from the exact approved user script." in skill
```

- [ ] **Step 2: Run the documentation test and verify RED**

Run: `python -B -m pytest tests/test_cleanup_contract.py::test_skill_requires_public_script_approval_before_storyboard_for_every_non_language_only_run -q`

Expected: FAIL because the exact public-edit contract is not yet present.

- [ ] **Step 3: Add only the approved public-facing contract to `SKILL.md`**

```markdown
For every request other than a direct language-only change, show one User Editable Script before making a storyboard. Show only scenes, timing, visuals, subtitles, dialogue, lyrics, speaker/singer, selling points, proof/offer, on-screen text, CTA, tone, pronunciation, Must keep, and Do not say. Keep the location key unchanged when editing. Omission is not deletion; write Delete beside the exact row. Generate the storyboard only from the exact approved user script.
```

- [ ] **Step 4: Run the documentation test and focused full suite**

Run: `python -B -m pytest tests/test_user_editable_script.py tests/test_review_workflow.py tests/test_review_service.py tests/test_orchestrator.py tests/test_ephemeral_runtime.py tests/test_server_fastapi_router.py tests/test_job_api.py tests/test_cleanup_contract.py -p no:cacheprovider -q`

Expected: PASS.

- [ ] **Step 5: Run the repository verification scripts without changing cleanup scope**

Run: `python -B scripts/verify_lightweight_bundle.py`

Expected: report existing cache-file cleanliness failure, if present, separately from the feature verification; do not delete unrelated cache files in this task.

## Plan Self-Review

Coverage: Task 1 implements exact user-visible rows, multi-speaker/singing, dense-copy preservation, explicit edits, and compilation. Task 2 removes route/cache skips and preserves the direct-language exception. Tasks 3-4 enforce persistence, invalidation, storyboard parentage, and the public API boundary. Task 5 documents the approved interaction and runs feature regressions.

Placeholder scan: no `TODO`, deferred implementation, or unspecified validation step remains. All new functions are defined under Task 1 or Task 3, and later task signatures use the same names.
