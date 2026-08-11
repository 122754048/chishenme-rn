# Seedance Compact Fail-Closed Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every official `universal-source-fidelity-replication` visual replacement use the proven concise Seedance multi-object binding shape through one fail-closed contract for one to nine people, products, Apps, scenes, garments, jewelry, and accessories.

**Architecture:** Extend the server-owned approved binding schema with explicit person wardrobe modes and target evidence, then make both `compile_edit_prompt()` and the compatibility `compile_provider_only_multi_subject_prompt()` delegate to one compact compiler. Carry a hashed compiler receipt through the existing V2 input contract, request audit, and bound Provider request so a self-declared JSON audit cannot authorize a paid call.

**Tech Stack:** Python 3.12, pytest, RunningHub Seedance 2.0 Standard payload contract, SHA-256 canonical JSON receipts, Markdown Skill/reference contracts.

## Global Constraints

- `video-edit-v2` remains the only active workflow entrypoint.
- One request supports one through nine continuous image references; `imageUrls[N-1] == @ImageN`.
- Every visual replacement selects `provider_only_multi_object_binding` before a paid call.
- Provider prompts use short positive state declarations and the successful Reinbow semantic shape.
- Person modes are mutually exclusive: `identity_and_wardrobe_from_reference` or `head_identity_preserve_source_wardrobe`.
- Missing descriptor, scope, confidence, target evidence, clean UTF-8, continuous indices, or canonical receipt fails before CreateVideo.
- No local face swap, inpainting, frame replacement, compositing, re-encoding, audio replacement, or per-person paid generation.
- Product, App, scene, garment, jewelry, accessory, UI, audio, tail, assembly, QC, and recovery behavior remains intact.
- Provider `SUCCESS` is not visual acceptance; object-level human QC remains authoritative.
- No paid Seedance request is required by this implementation plan.

---

### Task 1: Canonical person modes in the approved edit contract

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_edit_contracts.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/approved_edit_contract.py`

**Interfaces:**
- Consumes: approved visual bindings passed to `build_approved_edit_script()`.
- Produces: canonical model bindings containing `wardrobe_policy`, `target_identity_descriptor`, and conditionally `source_wardrobe_descriptor`.
- Accepted policies: `identity_and_wardrobe_from_reference`, `head_identity_preserve_source_wardrobe`.

- [ ] **Step 1: Add failing tests for the two mutually exclusive person modes**

Add tests that build one model binding with each policy:

```python
def test_model_binding_requires_explicit_reference_wardrobe_policy() -> None:
    binding = _approved_model_binding()
    binding.update({
        "wardrobe_policy": "identity_and_wardrobe_from_reference",
        "target_identity_descriptor": "red mesh sleeveless top, bright green crossbody strap, silver chain",
    })
    contract = approved_edit_contract.build_approved_edit_script([binding], [_replacement_row(binding["asset_tag"])])
    assert contract["asset_bindings"][0]["wardrobe_policy"] == "identity_and_wardrobe_from_reference"


def test_model_binding_requires_named_source_wardrobe_for_head_only_mode() -> None:
    binding = _approved_model_binding()
    binding.update({
        "wardrobe_policy": "head_identity_preserve_source_wardrobe",
        "source_wardrobe_descriptor": "black hoodie",
        "replacement_scope": "head identity",
    })
    contract = approved_edit_contract.build_approved_edit_script([binding], [_replacement_row(binding["asset_tag"])])
    assert contract["asset_bindings"][0]["source_wardrobe_descriptor"] == "black hoodie"
```

- [ ] **Step 2: Add failing conflict and omission tests**

Cover these exact failures:

```python
@pytest.mark.parametrize("missing", ["wardrobe_policy", "binding_confidence", "preserve_scope"])
def test_model_binding_fails_when_required_binding_evidence_is_missing(missing: str) -> None:
    binding = _approved_model_binding()
    binding.update({
        "wardrobe_policy": "identity_and_wardrobe_from_reference",
        "target_identity_descriptor": "verified target wardrobe",
    })
    binding.pop(missing, None)
    with pytest.raises(ReplicationError, match="approved asset binding source or identity is invalid"):
        approved_edit_contract.build_approved_edit_script([binding], [_replacement_row(binding["asset_tag"])])


def test_complete_target_appearance_cannot_preserve_source_wardrobe() -> None:
    binding = _approved_model_binding()
    binding.update({
        "wardrobe_policy": "head_identity_preserve_source_wardrobe",
        "source_wardrobe_descriptor": "black hoodie",
        "replacement_scope": "identity, appearance, and wardrobe",
    })
    with pytest.raises(ReplicationError, match="person wardrobe policy conflicts with replacement scope"):
        approved_edit_contract.build_approved_edit_script([binding], [_replacement_row(binding["asset_tag"])])
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_v2_edit_contracts.py -k "wardrobe_policy or source_wardrobe or complete_target_appearance" -q
```

Expected: FAIL because the current binding allowlist rejects the new fields or accepts an ambiguous model contract.

- [ ] **Step 4: Implement minimal canonicalization**

In `server/approved_edit_contract.py`:

```python
_PERSON_WARDROBE_POLICIES = {
    "identity_and_wardrobe_from_reference",
    "head_identity_preserve_source_wardrobe",
}
```

Add `wardrobe_policy` and `source_wardrobe_descriptor` to `binding_fields`. For any model binding carrying source-object evidence:

```python
if asset_type == "model":
    if wardrobe_policy not in _PERSON_WARDROBE_POLICIES:
        invalid = True
    elif wardrobe_policy == "identity_and_wardrobe_from_reference":
        invalid = invalid or not target_identity_descriptor or bool(source_wardrobe_descriptor)
    else:
        invalid = (
            invalid
            or not source_wardrobe_descriptor
            or "wardrobe" in replacement_scope.casefold()
            or "complete appearance" in replacement_scope.casefold()
        )
```

Copy the validated fields into the canonical binding so its SHA-256 covers the policy.

- [ ] **Step 5: Run focused and approved-contract tests**

Run:

```powershell
python -m pytest tests/test_v2_edit_contracts.py -k "approved_edit or wardrobe_policy or source_wardrobe" -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```powershell
git add server/approved_edit_contract.py tests/test_v2_edit_contracts.py
git commit -m "feat: require explicit person wardrobe binding modes"
```

---

### Task 2: One compact compiler for formal and compatibility calls

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_only_multi_subject_binding.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_seedance_prompt_compiler.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/scripts/seedance_prompt_compiler.py`

**Interfaces:**
- Produces: `compile_provider_only_multi_object_prompt(*, source_video: str, bindings: Sequence[Mapping[str, Any]]) -> dict[str, Any]`.
- Retains: `compile_provider_only_multi_subject_prompt()` as a strict compatibility adapter.
- Result fields: `prompt`, `normalized_bindings`, `image_tags`, `source_object_ids`, `binding_contract_sha256`, `prompt_sha256`, `compiler_version`, `provider_only`.

- [ ] **Step 1: Replace the previous weak assertions with the accepted Reinbow golden shape**

The four binding fixture must include `preserve_scope`, `binding_confidence`, and the new policies. Assert:

```python
prompt = result["prompt"]
assert "Subject 1: opening-center man" in prompt
assert "exact @Image1 identity and wardrobe: red mesh sleeveless top, bright green crossbody strap, silver chain" in prompt
assert "exact @Image2 identity and wardrobe: black thin-strap top and delicate pendant necklace" in prompt
assert "exact @Image3 identity and wardrobe: light cream thin-strap top and pearl stud earrings" in prompt
assert "exact @Image4 head identity, wearing the source black hoodie" in prompt
assert prompt.count("same continuing physical track") == 1
assert "do not" not in prompt.casefold()
assert "never" not in prompt.casefold()
assert len(prompt) <= 1300
```

- [ ] **Step 2: Add failing strict-adapter tests**

```python
@pytest.mark.parametrize("missing", ["preserve_scope", "binding_confidence", "target_tag", "asset_type"])
def test_compatibility_compiler_rejects_weak_binding_defaults(missing: str) -> None:
    bindings = _bindings()
    bindings[0].pop(missing)
    with pytest.raises(ValueError, match="SOURCE_OBJECT_BINDING_REQUIRED"):
        compile_provider_only_multi_subject_prompt(source_video="@Video1", bindings=bindings)


def test_compatibility_compiler_rejects_appearance_source_wardrobe_conflict() -> None:
    bindings = _bindings()
    bindings[0]["wardrobe_policy"] = "head_identity_preserve_source_wardrobe"
    bindings[0]["replacement_scope"] = "complete identity, appearance, and wardrobe"
    bindings[0]["source_wardrobe_descriptor"] = "black hoodie"
    with pytest.raises(ValueError, match="PERSON_WARDROBE_SCOPE_CONFLICT"):
        compile_provider_only_multi_subject_prompt(source_video="@Video1", bindings=bindings)
```

- [ ] **Step 3: Add generalized mixed-object tests**

For counts `1, 2, 4, 5, 6, 9`, build bindings cycling through model, product, app, scene, and garment. Assert continuous tags, one sentence per binding, type-specific preservation text, a single shared track sentence, and no tenth reference.

- [ ] **Step 4: Add encoding and determinism tests**

```python
def test_compact_prompt_is_clean_utf8_and_deterministic() -> None:
    first = compile_provider_only_multi_object_prompt(source_video="@Video1", bindings=_bindings())
    second = compile_provider_only_multi_object_prompt(source_video="@Video1", bindings=_bindings())
    encoded = first["prompt"].encode("utf-8")
    assert encoded.decode("utf-8") == first["prompt"]
    assert "\ufffd" not in first["prompt"]
    assert first["prompt_sha256"] == second["prompt_sha256"]
    assert first["binding_contract_sha256"] == second["binding_contract_sha256"]
```

- [ ] **Step 5: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_provider_only_multi_subject_binding.py tests/test_seedance_prompt_compiler.py -k "compact or weak_binding or wardrobe or mixed_object or deterministic" -q
```

Expected: FAIL because the current helper omits confidence/scope validation, omits target wardrobe evidence, and returns no canonical hashes.

- [ ] **Step 6: Implement the compact compiler**

Add canonical JSON hashing and one normalizer. Generate exactly:

```python
lines = [
    "Multi-subject replacement based on @Video1.",
    "@Video1 supplies the full motion, camera, blocking, timing, occlusion, lighting, background, props, contacts, and audio.",
    *mapping_lines,
    "Each mapped Subject or Object remains the same continuing physical track through movement, occlusion, interaction, and crossing.",
    "All mapped tracks follow their source motion, contact, perspective, lighting, and timing.",
]
prompt = V2_EDIT_PROMPT_PREFIX + " " + " ".join(lines)
```

Person mapping branches:

```python
if wardrobe_policy == "identity_and_wardrobe_from_reference":
    line = f"Subject {index}: {locator} becomes {reference} with exact {reference} identity and wardrobe: {target_identity_descriptor}."
else:
    line = f"Subject {index}: {locator} becomes {reference} with exact {reference} head identity, wearing the source {source_wardrobe_descriptor}."
```

Use the type recipes from the approved design for product, App, scene, and garment. Return hashes over normalized bindings and UTF-8 prompt bytes. Make `compile_provider_only_multi_subject_prompt()` call this function without adding defaults.

- [ ] **Step 7: Route formal visual binding lines through the compact compiler**

Inside `compile_edit_prompt()`, when the normalized visual bindings carry the full source-object contract, compile their visual section with `compile_provider_only_multi_object_prompt()`. Append approved dialogue, physical-text, language, continuity, and audio directives using the existing logic; do not duplicate visual binding prose.

- [ ] **Step 8: Run focused compiler tests**

Run:

```powershell
python -m pytest tests/test_provider_only_multi_subject_binding.py tests/test_seedance_prompt_compiler.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```powershell
git add scripts/seedance_prompt_compiler.py tests/test_provider_only_multi_subject_binding.py tests/test_seedance_prompt_compiler.py
git commit -m "feat: compile concise fail-closed Seedance bindings"
```

---

### Task 3: Carry the canonical receipt through formal V2 compilation

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_packaged_stage_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`

**Interfaces:**
- Consumes: compact compiler receipt in each `compiled_prompt`.
- Produces: `provider_only_binding_receipt` in `seedance_input_contract` and `seedance_request_audit`.
- Receipt fields: `contract`, `compiler_version`, `binding_mode`, `binding_contract_sha256`, `prompt_sha256`, `image_tags`, `source_object_ids`.

- [ ] **Step 1: Add a failing formal-route receipt test**

Run the existing V2 packaged-stage harness with four model bindings and assert:

```python
segment = output["seedance_input_contract"]["segments"][0]
receipt = segment["compiled_prompt"]["provider_only_binding_receipt"]
assert receipt["contract"] == "provider-only-multi-object-binding/v1"
assert receipt["binding_mode"] == "provider_only_multi_object_binding"
assert receipt["image_tags"] == ["@Image1", "@Image2", "@Image3", "@Image4"]
assert len(receipt["binding_contract_sha256"]) == 64
assert len(receipt["prompt_sha256"]) == 64
```

- [ ] **Step 2: Add a failing paid-call guard test**

Delete or corrupt the receipt between compile and request audit, run `SeedanceRequestAuditStage`, and assert `ReplicationError.code == "SOURCE_OBJECT_BINDING_REQUIRED"`. Verify the fake Provider has zero create calls.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_v2_packaged_stage_ports.py -k "provider_only_binding_receipt or missing_binding_receipt" -q
```

Expected: FAIL because no canonical receipt is currently published or checked.

- [ ] **Step 4: Publish the receipt in `SeedancePromptStage._run_v2`**

Add the full policy fields to `_compiler_asset_bindings()`. When `binding_mode == "provider_only_multi_object_binding"`, require the compiler output receipt and copy it into the segment contract. Convert any missing/invalid receipt into:

```python
raise _replication_error(
    "SOURCE_OBJECT_BINDING_REQUIRED",
    f"canonical provider-only binding receipt is missing for {segment_id}",
)
```

- [ ] **Step 5: Verify receipt against final board order in `SeedanceRequestAuditStage`**

Before `build_edit_provider_payload()`:

```python
expected_tags = [f"@Image{index}" for index in range(1, len(bindings) + 1)]
if receipt["image_tags"] != expected_tags:
    raise _replication_error("SOURCE_OBJECT_BINDING_REQUIRED", "binding receipt image order is stale")
if sha256(prompt.encode("utf-8")).hexdigest() != receipt["prompt_sha256"]:
    raise _replication_error("SOURCE_OBJECT_BINDING_REQUIRED", "binding receipt prompt hash is stale")
```

Include the verified receipt in each `seedance-request-audit/v2` segment.

- [ ] **Step 6: Run V2 packaged-stage tests**

Run:

```powershell
python -m pytest tests/test_v2_packaged_stage_ports.py -k "provider_only or binding_receipt or seedance_prompt or request_audit" -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```powershell
git add server/packaged_stages.py tests/test_v2_packaged_stage_ports.py
git commit -m "feat: bind compact prompt receipt to V2 audit"
```

---

### Task 4: Enforce the receipt at the bound Provider request boundary

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_production_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_packaged_stage_ports.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/production_ports.py`

**Interfaces:**
- Extends `_BoundProviderPayload` with `provider_only_binding_receipt`.
- Extends `_provider_request(..., provider_only_binding_receipt=None)`.
- Production preflight verifies the receipt immediately before the paid HTTP transport.

- [ ] **Step 1: Add a failing bound-request test**

For a V2 request with image URLs, call `_provider_request()` without the receipt and assert `SOURCE_OBJECT_BINDING_REQUIRED`. A V2 request with a valid receipt must return `_BoundProviderPayload` whose receipt is preserved as a private attribute and absent from the public JSON payload.

- [ ] **Step 2: Add a failing production preflight test**

Construct an otherwise valid authorized V2 `_BoundProviderPayload`, corrupt `prompt_sha256` or `image_tags`, and call `RunningHubSeedanceProvider.create_video()`. Assert `ProductionPortsError` occurs before `_request_json()` and before API-key use produces a paid transport.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_production_ports.py tests/test_v2_packaged_stage_ports.py -k "provider_only_binding_receipt or binding_receipt_preflight" -q
```

Expected: FAIL because the private request object does not carry or verify the receipt.

- [ ] **Step 4: Extend `_BoundProviderPayload` and `_provider_request()`**

Store the receipt as an attribute, not a Provider JSON field. For V2 payloads with visual references, require it and verify:

- contract/version marker;
- `binding_mode == provider_only_multi_object_binding`;
- prompt SHA against `payload["prompt"]`;
- image tag count/order against `payload["imageUrls"]`;
- 64-character binding contract SHA.

- [ ] **Step 5: Recheck the receipt in production preflight**

Add `_validate_server_provider_only_binding_receipt(request)` and call it from `create_video()` before `_server_provider_request_authorization_preflight()`. Preserve existing compatibility only for requests with no video URL and no visual image references; an official V2 visual edit has no compatibility bypass.

- [ ] **Step 6: Run focused Provider-boundary tests**

Run:

```powershell
python -m pytest tests/test_production_ports.py tests/test_v2_packaged_stage_ports.py -k "provider_only or authorization or create_video" -q
```

Expected: PASS with zero transport calls for invalid receipts.

- [ ] **Step 7: Commit Task 4**

```powershell
git add server/packaged_stages.py server/production_ports.py tests/test_production_ports.py tests/test_v2_packaged_stage_ports.py
git commit -m "feat: enforce binding receipt before Seedance create"
```

---

### Task 5: Segment, encoding, and exact-array regression guards

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_only_multi_subject_binding.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_v2_edit_contracts.py`
- Modify only if a regression test fails: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/scripts/seedance_prompt_compiler.py`
- Modify only if a regression test fails: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/packaged_stages.py`

**Interfaces:**
- Verifies existing V2 source-slice receipt and UTF-8 behavior remain part of the canonical request authority.

- [ ] **Step 1: Add exact image-array audit tests**

Assert the final board manifest URLs and the Provider payload satisfy:

```python
assert len(payload["imageUrls"]) == len(receipt["image_tags"])
assert receipt["image_tags"] == [f"@Image{i}" for i in range(1, len(payload["imageUrls"]) + 1)]
```

Swap two URLs after audit and assert the existing image-reference binding validation rejects the request before Provider creation.

- [ ] **Step 2: Add source-slice truth tests**

Create a segment contract whose audit claims a slice SHA but whose uploaded source reference is the full-source SHA without `source_is_full_segment` evidence. Assert `PROMPT_INTEGRITY_FAILED`. Add the valid case where the published immutable upload is the exact segment and the request passes.

- [ ] **Step 3: Add UTF-8 prompt round-trip tests**

Assert the exact `编辑视频：` prefix, target wardrobe punctuation, and any Chinese approved text survive JSON serialization and deserialization. Reject `\ufffd`, NUL, and known mojibake fragments before payload creation with `PROMPT_ENCODING_INVALID`.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest tests/test_provider_only_multi_subject_binding.py tests/test_v2_edit_contracts.py -k "image_array or source_slice or utf8 or encoding" -q
```

Expected: newly added corruption cases fail before any implementation adjustment; valid existing slice cases remain green. Apply only the minimal guard needed for failing cases.

- [ ] **Step 5: Re-run focused tests after minimal fixes**

Run the same command. Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```powershell
git add scripts/seedance_prompt_compiler.py server/packaged_stages.py tests/test_provider_only_multi_subject_binding.py tests/test_v2_edit_contracts.py
git commit -m "test: guard Seedance binding array slice and encoding"
```

---

### Task 6: Update the Skill contract and bundle documentation

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_only_multi_subject_docs.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_skill_contract.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/provider-only-multi-subject-binding.md`
- Modify if runtime files change: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/bundle_manifest.json`

**Interfaces:**
- Documents the exact compact recipe and official-entrypoint authority future windows must follow.

- [ ] **Step 1: Add failing documentation tests**

Require the Skill/reference to contain:

```python
required = {
    "identity_and_wardrobe_from_reference",
    "head_identity_preserve_source_wardrobe",
    "provider-only-multi-object-binding/v1",
    "SOURCE_OBJECT_BINDING_REQUIRED",
    "imageUrls[N-1] == @ImageN",
    "Provider SUCCESS is not visual acceptance",
}
```

Also assert the reference contains the concise person/product/App/scene/garment recipes and does not claim guaranteed visual success.

- [ ] **Step 2: Run documentation tests and verify RED**

Run:

```powershell
python -m pytest tests/test_provider_only_multi_subject_docs.py tests/test_skill_contract.py -q
```

Expected: FAIL because the new mode and receipt names are not documented.

- [ ] **Step 3: Update `SKILL.md` concisely**

Replace the current provider-only paragraph with the canonical entrypoint rule, two person modes, receipt requirement, and guarantee boundary. Keep detailed recipes in the reference to avoid bloating the frequently loaded Skill.

- [ ] **Step 4: Update the binding reference**

Document:

- one-to-nine independent target boards;
- detailed evidence in the audit, compact declarations in Prompt;
- the two person modes;
- successful Reinbow semantic example without task ID or case narration;
- type-specific positive recipes;
- canonical receipt and paid-call rejection;
- object-level QC and no visual guarantee.

- [ ] **Step 5: Run documentation and Skill validation**

Run:

```powershell
python -m pytest tests/test_provider_only_multi_subject_docs.py tests/test_skill_contract.py -q
python "C:/Users/zhaocx04/.codex/skills/.system/skill-creator/scripts/quick_validate.py" "C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication"
```

Expected: tests PASS and validation exits `0`.

- [ ] **Step 6: Commit Task 6**

```powershell
git add SKILL.md references/provider-only-multi-subject-binding.md references/bundle_manifest.json tests/test_provider_only_multi_subject_docs.py tests/test_skill_contract.py
git commit -m "docs: enforce compact multi-object binding contract"
```

---

### Task 7: Full regression and bundle closure

**Files:**
- Verify only unless failures require scoped fixes.

**Interfaces:**
- Confirms the compact binding change does not replace or break unrelated routes.

- [ ] **Step 1: Run the focused binding suites**

```powershell
python -m pytest tests/test_provider_only_multi_subject_binding.py tests/test_seedance_prompt_compiler.py tests/test_v2_edit_contracts.py tests/test_v2_packaged_stage_ports.py tests/test_production_ports.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run bundle closure and lightweight validation**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/test_bundle_runtime_closure.py tests/test_lightweight_bundle_contract.py -q
python scripts/verify_bundle.py
python scripts/verify_lightweight_bundle.py
```

Expected: all commands exit `0`; no cache or workstation-path violations.

- [ ] **Step 3: Run the full Skill regression suite**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -q
```

Expected: zero failures. Record the exact passed/skipped counts from this fresh run; do not reuse historical counts.

- [ ] **Step 4: Verify the successful-case compiler fixture without a paid call**

Compile the four approved Reinbow bindings locally and compare semantic clauses, image order, person modes, prompt/hash determinism, and receipt fields with the golden test. Do not submit RunningHub CreateVideo.

- [ ] **Step 5: Inspect the final diff for scope**

```powershell
git diff --stat HEAD~6..HEAD
git status --short
```

Confirm only binding compiler/contract, receipt enforcement, tests, Skill/reference, and bundle registration changed. Preserve unrelated pre-existing workspace changes.

- [ ] **Step 6: Final verification commit if Task 7 required fixes**

If no files changed, do not create an empty commit. If scoped fixes were required:

```powershell
git add scripts/seedance_prompt_compiler.py server/approved_edit_contract.py server/packaged_stages.py server/production_ports.py SKILL.md references/provider-only-multi-subject-binding.md references/bundle_manifest.json tests/test_provider_only_multi_subject_binding.py tests/test_seedance_prompt_compiler.py tests/test_v2_edit_contracts.py tests/test_v2_packaged_stage_ports.py tests/test_production_ports.py tests/test_provider_only_multi_subject_docs.py tests/test_skill_contract.py
git commit -m "fix: close Seedance binding regression gaps"
```

## Self-review checklist

- Every design requirement maps to a task.
- Task 1 defines the exact canonical person mode fields used by Tasks 2–6.
- Task 2 defines the receipt hashes consumed by Tasks 3–4.
- Task 3 binds the receipt to formal V2 compilation and final asset-board order.
- Task 4 rechecks authority immediately before paid transport.
- Task 5 covers image order, true source slicing, and clean UTF-8.
- Task 6 updates the discoverable Skill without case-specific narration.
- Task 7 proves unrelated asset, audio, UI, tail, assembly, QC, and recovery routes remain intact.
- No step requires a paid Provider request or local video modification.
