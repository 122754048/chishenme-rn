# Seedance Provider-Only Multi-Subject Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and evaluate one audited Seedance 2.0 request that independently binds four target assets to four source-video tracks without any local video modification.

**Architecture:** Add a provider-only multi-subject prompt contract and request builder. The builder sends four independent identity references plus the source video, omits the spatial binding board, records immutable reference order and request SHA-256, and fails on unchanged submissions. Local code performs request preparation and QC only; the delivered MP4 is the direct Seedance result.

**Tech Stack:** Python 3.12, pytest, RunningHub Standard Seedance API, FFprobe for read-only media inspection.

## Global Constraints

- Exactly one Seedance create call per changed candidate request.
- Exactly four independent image references in continuous one-based order; human references control identity and visible wardrobe, while the cat controls head identity only.
- No canvas-edge, mask, region-guidance, node-ID, or binding-board assumptions.
- No local face swap, inpainting, frame replacement, compositing, or audio replacement.
- A changed paid attempt must have a new request SHA-256 and one documented primary change variable.
- Human object-level visual review is the final identity authority.

---

### Task 1: Provider-only multi-subject request contract

**Files:**
- Create: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_provider_only_multi_subject_binding.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/scripts/seedance_prompt_compiler.py`

**Interfaces:**
- Produces: `compile_provider_only_multi_subject_prompt(source_video: str, bindings: Sequence[Mapping[str, Any]]) -> dict[str, Any]`.
- The returned object contains `prompt`, `image_tags`, `source_object_ids`, and `provider_only=True`.

- [ ] Write tests requiring continuous `@Image1..4`, unique source IDs, compound source locators, per-track wardrobe policy, source-identity exclusion, no target-face prose duplication, and rejection of a fifth binding/control-board reference.
- [ ] Run the focused test and verify it fails because the compiler function is absent.
- [ ] Implement the smallest deterministic compiler satisfying the contract.
- [ ] Run the focused test and the existing prompt-compiler suite.

### Task 2: Disable local identity completion for provider-only jobs

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/tests/test_local_multi_identity_completion.py`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/server/local_identity_completion.py`

**Interfaces:**
- Extend `build_local_identity_completion_plan(..., provider_only: bool = False)`.
- When `provider_only=True`, it returns `action="existing_recovery_route"`, `reason="provider_only_policy"`, and `provider_create_calls=0` without authorizing local execution.

- [ ] Add a failing test proving provider-only jobs cannot select `local_multi_track_completion`.
- [ ] Run it and confirm the existing function incorrectly authorizes the local route.
- [ ] Add the provider-only fail-closed branch without changing behavior for unrelated workflows.
- [ ] Run local-completion and V2 recovery regression tests.

### Task 3: Reinbow audited request builder

**Files:**
- Create: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/four_person_seedance_provider_only.py`
- Create: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/test_four_person_seedance_provider_only.py`

**Interfaces:**
- `build_request() -> tuple[dict[str, Any], dict[str, Any]]` returns the provider payload and audit receipt.
- Image order is man, blonde woman, dark-haired woman, cat; `videoUrls` contains only the source video.

- [ ] Write failing tests requiring four image URLs, no binding-board URL, one source video, `realPersonMode=true`, `conversionSlots=["all"]`, compact prompt, provider-only audit flag, and unchanged-request rejection.
- [ ] Run the test and verify failure because the builder is absent.
- [ ] Implement upload reuse, deterministic payload construction, request hashing, dry-run output, submit/query/download, and duplicate-hash refusal.
- [ ] Run the case tests and inspect the dry-run request manually.

### Task 4: One changed Seedance attempt and object-level QC

**Files:**
- Produce: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/four_person_provider_only/request.redacted.json`
- Produce: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/four_person_provider_only/audit.json`
- Produce: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/four_person_provider_only/result.mp4`
- Produce: `C:/Users/zhaocx04/Documents/New project/analysis/private/reinbow_person_replace/four_person_provider_only/qc.json`

**Interfaces:**
- The Seedance result is immutable and is never rewritten locally.

- [ ] Run dry-run and verify the request differs from every prior submitted request hash.
- [ ] Record the single primary change as `reference_role_architecture_v2`.
- [ ] Submit exactly one RunningHub task and poll its returned task ID.
- [ ] Download the direct provider MP4 and verify its SHA-256, dimensions, duration, streams, and frame count without mutation.
- [ ] Extract read-only review frames and score all four identities separately.
- [ ] Deliver only if human review confirms `4/4`; otherwise report the measured count and choose the next changed variable without local repair.

### Task 5: Skill documentation and regression closure

**Files:**
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/SKILL.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/local-multi-track-identity-completion.md`
- Modify: `C:/Users/zhaocx04/.codex/skills/universal-source-fidelity-replication/references/bundle_manifest.json`

**Interfaces:**
- Documents provider-only multi-subject binding as the active route when local compute is prohibited.
- Keeps non-person product/App/scene/garment routes unchanged.

- [ ] Add a failing documentation test for provider-only routing and the prohibition on binding-board uploads.
- [ ] Run it and verify the existing Skill still advertises local completion without the provider-only exception.
- [ ] Add concise routing documentation and register any new runtime file.
- [ ] Run focused tests, V2 contract tests, bundle closure, and lightweight bundle checks with bytecode/cache creation disabled.

## Self-review

- Every paid attempt is hash-audited and changed.
- The plan contains no local video-editing path.
- The four image indices and four source-track locators are explicit.
- Unsupported `edges`/mask fields are excluded.
- Existing product, App, UI, scene, garment, jewelry, and accessory routes are not replaced.
