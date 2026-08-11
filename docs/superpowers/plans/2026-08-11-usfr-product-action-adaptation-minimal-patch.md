# USFR Product Action Adaptation Minimal Patch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the existing compact provider-only binding prompt while ensuring approved product/App operations survive from the user script into exact Seedance time-window instructions; person, scene, and garment bindings remain behaviorally unchanged.

**Architecture:** Add one small operational-action policy to approved replacement rows, expose only a fixed concise business script, and change the compact prompt compiler so it skips redundant direct-binding rows but retains approved operational product/App rows. The existing provider-only binding compiler remains the sole owner of identity/index mapping; no person binding code, person asset contract, wardrobe policy, or person prompt recipe is modified.

**Tech Stack:** Python 3, pytest, existing USFR v2 contracts, deterministic Seedance prompt compiler, Markdown user-script renderer.

## Global Constraints

- Do not modify person identity binding rules, person asset preparation, wardrobe policy, person source-track mapping, or person prompt recipes.
- Keep `imageUrls[N-1] == @ImageN`, continuous `@Image1..N`, and the current provider-only binding receipt unchanged.
- Use one Seedance request for all approved replacement targets.
- Apply action adaptation only to product/App or another operational target represented by the existing product/App lanes.
- Person, scene/background, garment/clothing, and non-operational accessory replacements use `direct_binding` and create no action-adaptation prompt text.
- The first public script may be approved directly or modified. A user modification is internally interpreted and executed without publishing a second public script.
- Final Seedance prompt wording stays short, positive, direct, and free of marketing analysis.
- Do not perform a paid Seedance call during unit implementation or regression testing.

---

### Task 1: Freeze the Operational Replacement Contract

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/approved_edit_contract.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/production_ports.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_edit_contracts.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_phase2_real_stage_ports.py`

**Interfaces:**
- Consumes: existing canonical replacement rows and their bound asset type.
- Produces: canonical replacement row field `execution_mode: Literal["direct_binding", "adapt_action"]`.
- Rule: `adapt_action` is valid only for `product` and `app`; all `model`, `scene`, and `garment` rows must be `direct_binding`.

- [ ] **Step 1: Write failing contract tests**

Add tests proving that an operational product row is preserved and that a person row cannot enter the action-adaptation lane:

```python
def test_product_replacement_accepts_adapt_action_execution_mode():
    script = build_approved_edit_script(
        [_product_binding("ProductA")],
        [{
            "change_id": "CH01",
            "kind": "replacement",
            "start_ms": 1000,
            "end_ms": 3000,
            "asset_tag": "ProductA",
            "instruction": "Subject 1 opens @Image1, drinks it, and shows a natural pleased reaction",
            "execution_mode": "adapt_action",
        }],
    )
    assert script["change_rows"][0]["execution_mode"] == "adapt_action"


def test_person_replacement_rejects_adapt_action_execution_mode():
    with pytest.raises(ReplicationError, match="execution_mode"):
        build_approved_edit_script(
            [_valid_person_binding("PersonA")],
            [{
                "change_id": "CH01",
                "kind": "replacement",
                "start_ms": 0,
                "end_ms": 3000,
                "asset_tag": "PersonA",
                "instruction": "replace the approved person identity",
                "execution_mode": "adapt_action",
            }],
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_v2_edit_contracts.py -k "execution_mode" -q
```

Expected: FAIL because `execution_mode` is not accepted or validated.

- [ ] **Step 3: Add the minimal canonical field**

In `approved_edit_contract.py`:

```python
_REPLACEMENT_EXECUTION_MODES = {"direct_binding", "adapt_action"}

# Add "execution_mode" to allowed_fields.

execution_mode = str(row.get("execution_mode") or "direct_binding").strip().casefold()
asset_type_by_tag = {str(binding["asset_tag"]): str(binding["asset_type"]) for binding in provisional}
asset_type = asset_type_by_tag[asset_tag]
if execution_mode not in _REPLACEMENT_EXECUTION_MODES:
    raise ReplicationError("INVALID_INPUT", "replacement change row execution_mode is invalid")
if execution_mode == "adapt_action" and asset_type not in {"product", "app"}:
    raise ReplicationError("INVALID_INPUT", "replacement change row execution_mode is not valid for this asset type")
row["execution_mode"] = execution_mode
```

In the strict GPT schema in `production_ports.py`, add:

```python
"execution_mode": {"type": "string", "enum": ["direct_binding", "adapt_action"]},
```

Add an internal script-planning instruction stating that person, scene, and garment rows use `direct_binding`; only product/App rows that require use or operation use `adapt_action`. This instruction is GPT-internal and must never enter the Seedance prompt or public Markdown.

- [ ] **Step 4: Run contract and schema tests**

Run:

```powershell
python -m pytest tests/test_v2_edit_contracts.py tests/test_phase2_real_stage_ports.py -q
```

Expected: PASS, including existing person-binding contract tests.

- [ ] **Step 5: Commit the contract change**

```powershell
git add server/approved_edit_contract.py server/production_ports.py tests/test_v2_edit_contracts.py tests/test_phase2_real_stage_ports.py
git commit -m "feat: classify operational product replacements"
```

---

### Task 2: Publish the Fixed Concise User Script

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/user_script_document.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_user_script_document.py`

**Interfaces:**
- Consumes: canonical bindings, change rows, and source Cut timing.
- Produces: one Markdown document containing only core product information, the four-column script table, and two execution choices.
- Person/background/clothing rows remain visible as replacement actions but do not receive product-operation analysis.

- [ ] **Step 1: Replace the old public-projection expectations with failing concise-format tests**

```python
def test_v2_user_script_uses_only_the_fixed_business_format():
    markdown = render_v2_user_script_markdown(
        _v2_script_revision(),
        source_dynamics_sha256="e" * 64,
        source_content_timeline_sha256="f" * 64,
        source_cuts=_source_cuts(),
    )
    assert markdown.startswith("# 视频替换脚本")
    assert "## 核心信息" in markdown
    assert "| 时间 | 画面与人物动作 | 商品/App 操作与展示 | 口播/字幕 |" in markdown
    assert "回复“直接执行”" in markdown
    assert "直接写出修改内容" in markdown
    for hidden in (
        "营销分析", "资产替换绑定", "哈希", "Matcher", "segment plan",
        "@Image", "source_index", "binding_confidence", "验收标准",
    ):
        assert hidden.casefold() not in markdown.casefold()
```

Add a mixed-request test asserting that a person replacement appears only in `画面与人物动作`, while an `adapt_action` product row appears only in `商品/App 操作与展示`.

- [ ] **Step 2: Run the renderer test and verify RED**

Run:

```powershell
python -m pytest tests/test_user_script_document.py -k "fixed_business_format or mixed_request" -q
```

Expected: FAIL because the current renderer exposes marketing and binding sections.

- [ ] **Step 3: Implement the fixed renderer without changing hidden authority**

Refactor only `render_v2_user_script_markdown` to emit:

```python
lines = [
    "# 视频替换脚本",
    "",
    "## 核心信息",
    "",
    f"- 品牌：{brand_text}",
    f"- 产品/App：{product_text}",
    f"- 主要展示重点：{display_focus}",
    "",
    "## 视频脚本",
    "",
    "| 时间 | 画面与人物动作 | 商品/App 操作与展示 | 口播/字幕 |",
    "|---|---|---|---|",
    *table_rows,
    "",
    "## 请确认",
    "",
    "- 回复“直接执行”：按以上脚本开始生成。",
    "- 直接写出修改内容：系统按你的修改理解并开始生成，无需再次确认。",
]
```

Populate product/App operation cells only from `execution_mode == "adapt_action"`. Put model, scene, garment, and direct-binding rows in the visual/action cell. Do not expose any internal field names.

Update `SKILL.md` workflow text to state:

```text
The first script document is the only public script projection. “直接执行” approves it.
If the user supplies modifications, interpret them internally, update the hidden canonical change rows, and execute without publishing a second script document.
Operational adaptation applies only to product/App use or operation. Person, scene, and garment changes continue through direct binding.
```

- [ ] **Step 4: Run renderer and public-content tests**

Run:

```powershell
python -m pytest tests/test_user_script_document.py tests/test_public_content_policy.py -q
```

Expected: PASS; the public script contains no technical authority data.

- [ ] **Step 5: Commit the public-script change**

```powershell
git add server/user_script_document.py SKILL.md tests/test_user_script_document.py
git commit -m "feat: simplify the v2 user script"
```

---

### Task 3: Preserve Operational Actions in the Compact Seedance Prompt

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/scripts/seedance_prompt_compiler.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_only_multi_subject_binding.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_packaged_stage_ports.py`

**Interfaces:**
- Consumes: replacement rows with `change_id`, `execution_mode`, time window, asset tag/type, and approved instruction.
- Produces: unchanged compact binding text plus one short positive time-window sentence for each `adapt_action` product/App row.
- Produces audit list `operational_change_ids` and SHA-256 coverage receipt.

- [ ] **Step 1: Write the regression that reproduces the SUNNY POP failure**

```python
def test_compact_prompt_keeps_product_operation_but_not_person_binding_instruction():
    result = compile_edit_prompt(
        asset_bindings=_person_and_product_bindings(),
        replacements=[
            {
                "change_id": "PERSON01",
                "window": "00:00.000-00:05.000",
                "target": "PersonA",
                "asset_type": "model",
                "execution_mode": "direct_binding",
                "instruction": "replace the approved person identity",
            },
            {
                "change_id": "PRODUCT01",
                "window": "00:01.200-00:03.800",
                "target": "ProductA",
                "asset_type": "product",
                "execution_mode": "adapt_action",
                "instruction": "Subject 1 picks up @Image2, opens the bottle, drinks it, and shows a natural pleased reaction",
            },
        ],
        dialogue_changes=[],
    )
    assert "opens the bottle, drinks it" in result["prompt"]
    assert "replace the approved person identity" not in result["prompt"]
    assert result["operational_change_ids"] == ["PRODUCT01"]
```

Add an App equivalent and a test asserting that scene/garment/person direct bindings do not gain time-window action prose. Snapshot the existing four-person prompt before implementation and assert exact equality afterward.

- [ ] **Step 2: Run the compact-prompt tests and verify RED**

Run:

```powershell
python -m pytest tests/test_provider_only_multi_subject_binding.py -k "keeps_product_operation or app_operation or four_person" -q
```

Expected: FAIL because the compact branch currently executes `continue` for all mapped replacements and drops product/App action rows.

- [ ] **Step 3: Forward operational authority from the stage**

In `SeedancePromptStage._run_v2`, forward the canonical fields:

```python
replacements.append({
    "change_id": str(row["change_id"]),
    "execution_mode": str(row.get("execution_mode") or "direct_binding"),
    "window": window,
    "target": asset_tag,
    "instruction": str(row.get("instruction") or ""),
    "asset_type": binding["asset_type"],
})
```

After compilation, compare the expected `adapt_action` change IDs for the segment with `compiled["operational_change_ids"]`. Raise `PROMPT_INTEGRITY_FAILED` before any paid request if they differ.

- [ ] **Step 4: Change only the compact replacement-row branch**

In `compile_edit_prompt`, replace the unconditional compact `continue` with:

```python
execution_mode = str(item.get("execution_mode") or "direct_binding").strip().casefold()
change_id = str(item.get("change_id") or "").strip()
if compact_binding_result is not None and target in binding_by_tag:
    if execution_mode == "direct_binding":
        continue
    if execution_mode != "adapt_action" or replacement_kind not in {"product", "app"} or not change_id:
        raise EditPromptContractError("OPERATIONAL_ACTION_CONTRACT_INVALID")
    lines.append(f"{window}: {instruction}.")
    operational_change_ids.append(change_id)
    continue
```

Return deterministic coverage:

```python
result["operational_change_ids"] = operational_change_ids
result["operational_change_ids_sha256"] = _sha_json(operational_change_ids)
```

Do not edit `compile_provider_only_multi_object_prompt`, especially its person mapping lines and wardrobe branches.

- [ ] **Step 5: Run compiler and packaged-stage tests**

Run:

```powershell
python -m pytest tests/test_provider_only_multi_subject_binding.py tests/test_v2_packaged_stage_ports.py tests/test_seedance_prompt_compiler.py -q
```

Expected: PASS. The existing four-person prompt snapshot is unchanged; product/App operational instructions appear once with exact windows.

- [ ] **Step 6: Commit the lossless compiler change**

```powershell
git add server/packaged_stages.py scripts/seedance_prompt_compiler.py tests/test_provider_only_multi_subject_binding.py tests/test_v2_packaged_stage_ports.py tests/test_seedance_prompt_compiler.py
git commit -m "fix: preserve product actions in compact prompts"
```

---

### Task 4: Freeze Skill Rules and Run Full Regression

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/provider-only-multi-subject-binding.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/bundle_manifest.json`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_bundle_runtime_closure.py`
- Test: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_only_multi_subject_docs.py`
- Test: all existing USFR tests.

**Interfaces:**
- Consumes: implemented execution-mode and coverage behavior.
- Produces: packaged rule documentation and a release-closed bundle whose manifest hashes match the modified files.

- [ ] **Step 1: Write failing documentation and bundle assertions**

Add assertions that the binding reference explicitly states:

```text
Operational action adaptation is product/App-only.
Person, scene, garment, and non-operational accessory replacements remain direct bindings.
Compact binding never authorizes dropping an approved adapt_action time-window instruction.
User modifications are interpreted internally and do not create a second public script approval document.
```

Also assert that the bundle manifest retains the active compiler, production planner, and provider-only rule reference with roles that describe operational-action preservation. The manifest is a path/role catalog; it does not store these files' content hashes.

- [ ] **Step 2: Run bundle tests and verify RED**

Run:

```powershell
python -m pytest tests/test_bundle_runtime_closure.py tests/test_provider_only_multi_subject_docs.py -q
```

Expected: FAIL until the reference and manifest are synchronized.

- [ ] **Step 3: Update the rule reference and bundle manifest**

Document the exact scope boundary and operational-row integrity rule. Update only the existing role strings for `scripts/seedance_prompt_compiler.py`, `server/production_ports.py`, and `references/provider-only-multi-subject-binding.md`; do not add unrelated runtime entries.

- [ ] **Step 4: Run targeted regression**

Run:

```powershell
python -m pytest tests/test_user_script_document.py tests/test_v2_edit_contracts.py tests/test_phase2_real_stage_ports.py tests/test_provider_only_multi_subject_binding.py tests/test_v2_packaged_stage_ports.py tests/test_seedance_prompt_compiler.py tests/test_bundle_runtime_closure.py tests/test_provider_only_multi_subject_docs.py -q
```

Expected: all PASS.

- [ ] **Step 5: Run the complete Skill suite**

Run:

```powershell
python -m pytest tests -q
```

Expected: all tests PASS with no changed four-person person-binding snapshot.

- [ ] **Step 6: Run static integrity checks**

Run:

```powershell
python -m compileall server scripts
python scripts/verify_bundle.py .
python scripts/verify_lightweight_bundle.py .
git diff --check
rg -n "adapt_action" server scripts references tests
```

Expected: compilation and both bundle verifiers succeed, `git diff --check` is clean, and `adapt_action` appears only in product/App policy, action propagation, documentation, and tests.

- [ ] **Step 7: Commit the packaged rule update**

```powershell
git add references/provider-only-multi-subject-binding.md references/bundle_manifest.json tests/test_bundle_runtime_closure.py tests/test_provider_only_multi_subject_docs.py
git commit -m "docs: freeze operational asset adaptation rules"
```

---

## Final Verification Checklist

- [ ] The four-person provider-only prompt remains exactly unchanged.
- [ ] Person asset and wardrobe-policy tests remain unchanged and pass.
- [ ] Person, background/scene, and clothing/garment replacements use direct binding only.
- [ ] “舔糖果” to bottled orange juice compiles as an approved open/drink/reaction time-window action, not a copied lick action.
- [ ] Unsupported old-product effects do not enter the approved operational instruction.
- [ ] App operation rows retain ordered interaction and result display.
- [ ] The public script contains only core information, the four-column table, and the two execution choices.
- [ ] A user modification is interpreted internally without a second public script document.
- [ ] Every approved `adapt_action` row appears exactly once in the paid Seedance prompt.
- [ ] No paid Provider request is made during implementation verification.
