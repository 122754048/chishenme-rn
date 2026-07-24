# Update And Maintenance Playbook

This document tells future developers where to make changes in Universal
Source-Fidelity Replication and how to verify those changes.

## 1. The Rule

Keep the public workflow stable unless the product owner explicitly changes it.

Stable means:

- seven fixed media slots stay fixed;
- `output_language` remains a separate fixed parameter;
- source video maximum remains 30 seconds unless explicitly changed;
- script review and storyboard review remain the only user review gates;
- the 12 semantic stages remain the workflow backbone;
- supplied UI and supplied tail stay opaque media replacements;
- missing tail means omit source tail, never add black padding;
- final Seedance prompts must pass through the packaged Seedance-20 compiler
  and audit path;
- production runtime must not read local workstation files or installed desktop
  skills.

Do not add a new slot, new public approval gate, new provider request shape, or
new durable storage system casually.

## 2. Files By Responsibility

### Public workflow contract

Update these when the user-facing process changes:

- `SKILL.md`
- `references/server-api-contract.md`
- `references/fixed-input-slot-contract.md`
- `references/deployment-runtime-contract.md`
- `references/production-readiness-status.md`

If a behavior is not written in `SKILL.md`, future agents may not preserve it.

### API and job lifecycle

Update these when request/response behavior, job state, approvals, or result
handles change:

- `server/fastapi_router.py`
- `server/job_models.py`
- `server/job_store.py`
- `server/redis_job_store.py`
- `server/ephemeral_driver.py`
- `server/ephemeral_worker.py`
- `server/review_models.py`
- `server/review_workflow.py`
- `server/result_handles.py`
- `server/recovery_models.py`
- `server/recovery_workflow.py`
- `schemas/job.schema.json`
- `schemas/upload_completion.schema.json`
- `schemas/script_revision.schema.json`
- `schemas/storyboard_revision.schema.json`
- `schemas/result_handle.schema.json`

Add or update tests under `tests/` for every API behavior change.

### Fixed input slots and language

Update these when input slot rules, language rules, or admission rules change:

- `scripts/bind_input_slots.py`
- `schemas/input_slots.schema.json`
- `server/fastapi_router.py`
- `server/intake.py`
- `scripts/validation_catalog.py`
- `validation/case_catalog.json`
- `tests/test_job_api.py`
- `tests/test_validation_catalog.py`
- `tests/test_skill_contract.py`

Current fixed inputs:

- `source_video`
- `new_product_image`
- `new_model_image`
- `ui_screenshot`
- `app_store_url`
- `ui_operation_video`
- `tail_video`
- `output_language` as a parameter, not a media slot

If adding a language, update the accepted language list in validation code,
API validation, exact-line/audio contracts if needed, and add at least one
catalog case or existing case coverage tag for that language.

### App Store and Google Play evidence

Update these when App Store or Google Play parsing changes:

- `bundled-skills/parse-app-store-evidence/SKILL.md`
- `bundled-skills/parse-app-store-evidence/scripts/parse_app_store.py`
- `bundled-skills/parse-app-store-evidence/references/evidence-contract.md`
- `server/real_capabilities.py`
- `server/orchestrator.py`
- parser-related tests under `tests/`
- `validation/case_catalog.json` for Apple/Google coverage cases

Rules to preserve:

- Use official Apple App Store or Google Play evidence only.
- Google Play URL shape is `play.google.com/store/apps/details?id=...`.
- Preserve package ID, language, storefront, icon, screenshots, hashes, and
  provenance.
- Do not let a generic scraper or generator infer UI truth from raw page HTML.
- Generated UI blocks if official pixel evidence is missing when it is
  required.

### Source video analysis

Update these when improving source fidelity, camera/action/audio analysis, or
frame evidence:

- `bundled-skills/analyze-reference-video-dynamics/SKILL.md`
- `bundled-skills/analyze-reference-video-dynamics/scripts/probe_video.py`
- `bundled-skills/analyze-reference-video-dynamics/scripts/validate_dynamics.py`
- `bundled-skills/analyze-reference-video-dynamics/scripts/validate_high_fidelity_extension.py`
- `scripts/high_fidelity_analysis.py`
- `server/high_fidelity_envelope.py`
- `server/high_fidelity_projection.py`
- `server/vision_backends.py`
- `tests/test_vision_backends.py`
- `tests/test_high_fidelity_projection.py`

Any new analysis evidence must bind to an input slot SHA or published artifact
SHA. Do not accept unbound text claims as production evidence.

### UI overlays and deterministic visual replacement

Update these when overlay geometry, text, logos, or source UI overlays change:

- `bundled-skills/replicate-source-ui-overlays/SKILL.md`
- `bundled-skills/replicate-source-ui-overlays/scripts/overlay_frame_plan.py`
- `bundled-skills/replicate-source-ui-overlays/scripts/validate_overlay_contract.py`
- `server/overlay_mapping.py`
- `server/overlay_renderer.py`
- `scripts/build_overlay_render_mapping.py`
- overlay/timeline renderer tests under `tests/`

Readable text must be deterministic and OCR-verifiable. Do not ask Seedance to
draw long UI text.

### Seedance prompt generation

Update these when prompt structure, prompt audit, factor routing, or Seedance
model rules change:

- `runtime-skills/seedance-20/SKILL.md`
- `runtime-skills/seedance-20/skills/*/SKILL.md`
- `scripts/skill_router.py`
- `scripts/seedance_prescript.py`
- `scripts/seedance_prompt_compiler.py`
- `server/seedance_invocations.py`
- `server/high_fidelity_projection.py`
- `bundled-skills/seedance-storyboard-replication/references/seedance-20-integrity-gate.md`
- `tests/test_seedance_prompt_compiler.py`
- `tests/test_seedance_integrity_gate.py`
- `tests/test_server_seedance_invocations.py`
- `tests/test_skill_router.py`

Rules to preserve:

- Invocation A happens inside script building and does not create provider
  work.
- Invocation B happens after storyboard approval.
- The compiled prompt must match approved cuts, locks, dialogue, timing, Foley,
  silence, camera, motion, product/UI truth, and continuity.
- Route names such as `opaque_ui_demo`, `generated_ui_demo`, and tail-card
  carriers must not leak into paid Seedance prompts.
- Generated UI pixels stay in deterministic UI renderer/timeline assembly, not
  in Seedance semantic generation.

### Provider and RunningHub/Seedance submission

Update these when paid provider calls, asset upload, polling, reconciliation,
or provider payload shape changes:

- `bundled-skills/seedance-storyboard-replication/scripts/seedance_submit.py`
- `bundled-skills/seedance-storyboard-replication/scripts/runninghub_image2.py`
- `server/provider_ports.py`
- `server/production_ports.py`
- `server/capability_ports.py`
- `server/packaged_factory.py`
- `tests/test_youdao_seedance.py`
- `tests/test_provider_idempotency_redis.py`
- `tests/test_capability_ports.py`

Rules to preserve:

- Paid request payload is frozen and hashed before the provider call.
- Ambiguous provider outcomes are reconciled by lookup.
- Never blindly resubmit a possibly charged create call.
- The server owns provider credentials. Clients do not send provider keys.

### Timeline assembly, UI splice, tail splice, and black-frame prevention

Update these when final video assembly, UI insertion, tail insertion, duration,
transition, audio crossfade, or black-frame detection changes:

- `bundled-skills/seedance-storyboard-replication/scripts/timeline_splice.py`
- `bundled-skills/seedance-storyboard-replication/scripts/concat_videos.py`
- `scripts/hybrid_compositor.py`
- `server/timeline_renderer.py`
- `server/real_capabilities.py`
- `server/audio_mixer.py`
- `tests/test_timeline_splice.py`
- `tests/test_timeline_splice_real_media.py`
- `tests/test_concat_videos.py`
- `tests/test_container_video_e2e_contract.py`

Rules to preserve:

- Supplied UI uses its natural active duration.
- Supplied tail uses its natural active duration.
- Missing tail omits the source tail interval.
- Do not pad with black video.
- One black frame at a splice boundary is a hard failure.
- A transition receipt must bind to the actual final MP4 SHA.

### Audio replication and source-audio behavior

Update these when changing speech, voice, music, Foley, ambience, silence,
ducking, loudness, lip-sync, or source-audio refill:

- `server/audio_backends.py`
- `server/audio_mixer.py`
- `server/audio_route_guard.py`
- `server/performance_audio_contracts.py`
- `server/real_capabilities.py`
- `schemas/exact_line_contract.schema.json`
- `tests/test_audio_backends.py`
- `tests/test_performance_audio_contracts.py`
- `tests/test_real_capabilities.py`

Rules to preserve:

- Final audio evidence must bind to the decoded current final MP4.
- ASR evidence must bind to exact extracted WAV bytes.
- Language must match `output_language`.
- Foley, ambience, meaningful silence, loudness, true peak, boundary jumps, and
  terminal drift are QC factors.
- Shadow/local compatibility may be looser, but active production must fail
  closed without real evidence.

### Generated UI renderer and OCR

Update these when generated UI routing, UI clarity, UI text, or OCR/layout
validation changes:

- `server/vision_backends.py`
- `server/real_capabilities.py`
- `server/orchestrator.py`
- `schemas/high_fidelity_analysis.schema.json`
- `tests/test_vision_backends.py`
- `tests/test_high_fidelity_projection.py`
- `validation/case_catalog.json`

Rules to preserve:

- Generated UI must publish a real `video/*` artifact.
- Every state must have decoded-frame SHA, OCR evidence, and layout evidence.
- OCR/layout target is 100 percent.
- Static PNG normalization is development-only.

### Quality gates and 36-case validation

Update these when acceptance criteria, case coverage, or evaluator receipts
change:

- `validation/case_catalog.json`
- `validation/tools/run_case_matrix.py`
- `validation/tools/validate_case_results.py`
- `scripts/validation_catalog.py`
- `references/quality-activation-contract.md`
- `references/production-readiness-status.md`
- `tests/test_validation_catalog.py`
- `tests/test_case_matrix_runner.py`
- `tests/test_high_fidelity_benchmark_artifacts.py`

Rules to preserve:

- Do not full-run all 36 cases on every small change.
- Incremental validation must run selected impact cases plus the fixed smoke set.
- Production promotion requires one full immutable 36-case run with real
  provider/model/evaluator evidence.
- Self-reported scores are not production evidence.

### Recovery loop

Update these when changing fallback behavior after normal tools fail:

- `references/adaptive-fidelity-recovery-loop.md`
- `server/recovery_bridge.py`
- `server/recovery_executor.py`
- `server/recovery_workflow.py`
- `server/recovery_models.py`
- `tests/test_recovery_bridge.py`
- `tests/test_recovery_executor.py`
- `tests/test_recovery_workflow.py`

Rules to preserve:

- Recovery adds no public slot.
- Recovery adds no public approval gate.
- Recovery returns its passing candidate through the original failed stage's
  artifact kind.
- Recovery may use any deployed and authorized tool, but every tool invocation
  must record a receipt.

## 3. How To Make A Change

Use this exact order:

1. Write down the requested behavior in one sentence.
2. Find the responsibility section above.
3. Update the smallest set of files.
4. Add or update tests for the changed behavior.
5. Run focused tests.
6. Run bundle verification.
7. Update `references/production-readiness-status.md` if the deployment or
   evidence status changed.
8. Export a clean package from Git for handoff.

Do not edit generated caches. Do not commit `.pytest_cache`, `.ruff_cache`, or
`__pycache__`.

## 4. Focused Test Commands

Run these after API or intake changes:

```bash
python -m pytest tests/test_job_api.py tests/test_server_fastapi_router.py -q
```

Run these after validation catalog changes:

```bash
python -m pytest tests/test_validation_catalog.py tests/test_case_matrix_runner.py -q
```

Run these after UI/tail splice or black-frame changes:

```bash
python -m pytest tests/test_timeline_splice.py tests/test_timeline_splice_real_media.py tests/test_concat_videos.py -q
```

Run these after Seedance prompt changes:

```bash
python -m pytest tests/test_seedance_prompt_compiler.py tests/test_seedance_integrity_gate.py tests/test_server_seedance_invocations.py tests/test_skill_router.py -q
```

Run these after audio changes:

```bash
python -m pytest tests/test_audio_backends.py tests/test_performance_audio_contracts.py tests/test_real_capabilities.py -q
```

Run these after deployment/runtime changes:

```bash
python -m pytest tests/test_bundle_runtime_closure.py tests/test_bundle_resolver.py tests/test_container_video_e2e_contract.py tests/test_production_ports.py -q
```

Run these before saying a package is ready:

```bash
python -B scripts/verify_bundle.py .
python -B scripts/verify_lightweight_bundle.py .
python -m pytest -q
```

If the local working directory contains Python cache directories, verify from a
fresh Git archive instead:

```bash
mkdir -p /tmp/usfr-package-check/repo
git archive --format=tar --output=/tmp/usfr-package-check/bundle.tar HEAD deployable-skills/universal-source-fidelity-replication
tar -xf /tmp/usfr-package-check/bundle.tar -C /tmp/usfr-package-check/repo
cd /tmp/usfr-package-check/repo/deployable-skills/universal-source-fidelity-replication
PYTHONDONTWRITEBYTECODE=1 python -B scripts/verify_bundle.py .
PYTHONDONTWRITEBYTECODE=1 python -B scripts/verify_lightweight_bundle.py .
```

## 5. Incremental Versus Full Validation

Use incremental validation during development:

```bash
python -B scripts/validation_catalog.py \
  --catalog validation/case_catalog.json \
  --changed-tag app \
  --changed-tag generated_ui
```

This selects impacted cases plus the fixed smoke set. It avoids spending money
on every case after every small change.

Use full 36-case validation only for release candidates:

```bash
export USFR_VALIDATION_ALLOW_PAID=true
export USFR_VALIDATION_EVALUATOR_TOKEN=<private-evaluator-token>

python -B validation/tools/run_case_matrix.py \
  --catalog validation/case_catalog.json \
  --fixture-manifest /secure/usfr-fixtures/fixtures.manifest.json \
  --context /secure/usfr-release/dependency-context.json \
  --api-base-url https://usfr-api.internal \
  --evaluator-url https://qc.internal/v1/usfr-case-evaluate \
  --mode immutable_release \
  --max-parallel 2 \
  --output /secure/usfr-release/36-case-results.json
```

Then validate:

```bash
python -B validation/tools/validate_case_results.py \
  --catalog validation/case_catalog.json \
  --results /secure/usfr-release/36-case-results.json \
  --mode immutable_release
```

## 6. Updating The 36-Case Catalog

The catalog is a coverage contract, not a folder of media files.

When replacing placeholder fixture records with real release fixtures:

1. Keep the same `case_id` values unless coverage truly changes.
2. Upload real media to private object storage.
3. Compute actual SHA-256 for every source and replacement asset.
4. Replace `asset_id` with the private fixture identifier used by your fixture
   manifest, or keep the existing logical fixture name if your manifest maps it.
5. Replace placeholder SHA values with actual SHA values.
6. Recompute `fixture_fingerprint`.
7. Recompute `toolchain_sha256` if tool/model/provider dependencies changed.
8. Run `tests/test_validation_catalog.py`.
9. Run a release matrix before using the catalog as production evidence.

Never count placeholder fixture SHA values as real acceptance evidence.

## 7. Updating Deployment Adapters

Most provider/model changes should be made outside this core package, inside
the deployment-owned module named by `USFR_PORT_FACTORY`.

Change the core package only when the adapter interface itself changes.

For a provider/model upgrade:

1. Update the deployment adapter.
2. Update the adapter `capability_identity()` version and SHA.
3. Update dependency context used by release validation.
4. Run impacted incremental cases.
5. Run full 36-case release validation before production promotion.

## 8. Release Package Handoff

Use a clean Git archive as the handoff package:

```bash
git archive --format=tar --output=usfr-release-<commit>.tar HEAD deployable-skills/universal-source-fidelity-replication
```

Before handoff, verify:

```bash
python -B scripts/verify_bundle.py .
python -B scripts/verify_lightweight_bundle.py .
python -m pytest -q
```

The handoff package must include:

- `SKILL.md`
- `server/`
- `scripts/`
- `bundled-skills/`
- `runtime-skills/`
- `references/`
- `schemas/`
- `deployment/`
- `validation/case_catalog.json`
- `validation/tools/`
- `tests/`

It must not include:

- local run outputs;
- private customer media;
- provider API keys;
- `.pytest_cache`;
- `.ruff_cache`;
- `__pycache__`;
- workstation absolute paths;
- local skill paths;
- fake production receipts.

## 9. Common Mistakes

Mistake: "The video plays, so QC passed."

Correction: Playable video is only technical evidence. Production needs source
fidelity, language, UI OCR/layout, audio, claims, identity, route, timeline, and
semantic evaluator receipts.

Mistake: "The user uploaded a tail video, so match the source tail duration."

Correction: Use the uploaded tail's natural active duration. Never pad black.

Mistake: "The user did not upload a tail video, so keep the source tail."

Correction: Omit the source tail-card interval.

Mistake: "Let Seedance generate UI text."

Correction: Generated UI text belongs to the deterministic UI renderer plus OCR
validation. Seedance should not draw long UI text.

Mistake: "A failed paid provider request can be retried."

Correction: If the request may have reached the provider, mark it ambiguous and
use provider lookup/reconciliation.

Mistake: "A local path is fine inside a server artifact."

Correction: Production artifacts use object-store references and SHA-256
receipts. Worker local paths are temporary only.

## 10. When To Update This Document

Update this playbook whenever:

- a new public input is added;
- an existing route changes;
- a provider interface changes;
- a new model backend is required;
- the 36-case acceptance standard changes;
- deployment environment variables change;
- quality gates change.

If the code changes but this document does not, the next server developer will
repeat the same mistakes.
