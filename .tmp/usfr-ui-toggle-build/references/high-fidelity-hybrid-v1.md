# `high_fidelity_hybrid_v1` profile snapshot

This profile is the deployable projection of
`2026-07-17-universal-high-fidelity-hybrid-seedance20-dual-stage-design.md`.
The design's public compatibility contract remains frozen; this reference only
adds internal evidence, A/B compiler, capability, and QC checks inside existing
stages. Keep the profile in `shadow`/feature-flag mode until the design's
golden-case and matched A/B gates pass.

`high_fidelity_hybrid_v1` is an internal, additive execution profile. It is
selected by server deployment configuration and is never a new upload slot,
route, RunState, HTTP field, approval, or provider task. The existing fixed
seven-slot intake and two approval gates remain authoritative.

## Immutable compatibility anchor

The profile preserves the seven fixed slots, Route 1 and Route 2, the existing
twelve semantic stages, the same two approval types, the fixed-B provider
request, and at most two generated tasks. Invocation A remains a non-provider
pre-script executability pass inside existing intent/script work; Route 1 is
read-only and Route 2 may propose evidence-bounded copy before its existing
script approval. Invocation B remains after storyboard approval and must compile
and audit the exact approved prompt before any paid request.

A zero-generated-region run takes the existing local-only branch: no reverse
script, no storyboard, no Image Gen, no Invocation A/B, no CreateAsset, no
CreateVideo, and no creative approval. Region-boundary analysis, deterministic
splice/compositor work, transition rendering, and technical QC still run.

The current canonical media contract overrides stale draft examples in the
design snapshot. Supplied App tail media uses `trim_to_active_content` and ends
at its last active frame; missing tail media uses `omit_source_end_card`.
`source_end_card_keep` and a no-trim tail policy are not active routes. Supplied
UI likewise keeps its active-content duration and shifts downstream mapping;
neither UI nor tail media receives filler, freeze, playback-rate change, or
audio/video padding.

Stage-11 publishes the assembled-video and timeline-manifest receipts
together. The manifest `duration_us` is the authoritative elastic output clock
for QC; source-region coverage is validated separately. Production QC scans at
a half-frame black threshold, records `freezedetect` intervals, checks stream
start-time alignment independently of total duration, and rejects any missing
or mismatched manifest. Static source/user-upload holds are allowed only when
the manifest carries input-lineage placement evidence; a generated/opaque
carrier freeze at an edge or splice is a hard failure.
The default FFmpeg transition backend is exact-only and rejects
`radial_zoom_blur`, `zoom_out`, and `zoom_back` until dedicated renderers are
deployed; a blur or ordinary fade cannot authorize those source motions.

## Snapshot boundary

Workers call `scripts/high_fidelity_profile.py` at run creation:

```python
snapshot = build_profile_snapshot(
    "high_fidelity_hybrid_v1",
    {"seedance-20": packaged_seedance_skill_path},
    {
        "activation_mode": "shadow",
        "parent_digests": {"source_fidelity_contract_sha256": "..."},
        "artifact": {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "uri": "s3://private-bucket/runs/<run>/analysis/profile.json",
        },
    },
)
```

The snapshot stores the profile/schema/config digests, immutable parent
contract digests, creation time, activation mode, and each packaged dependency
name/version/byte SHA-256. Only a package-relative path is persisted; a
workstation path, environment variable, or client-local URI is never emitted.
The artifact envelope is immutable metadata for the existing object-store
artifact path (`kind`, schema version, private URI, tenant/run ownership, and
hash), not a second source of run state.

## A/B consistency

Invocation A and Invocation B must validate the same snapshot before compiling
or paying for a request. `validate_profile_snapshot` compares dependency names,
versions, package-relative paths, and exact bytes. A changed skill file,
missing dependency, schema mismatch, or tampered snapshot fails closed before a
provider call; workers must restore the pinned package or rebuild dependent
artifacts under the existing approval rules. A legacy run with no snapshot
(`None` or `{}`) bypasses this profile validator and follows the unchanged
legacy workflow; it is not backfilled.

Production stores the JSON through the existing tenant-private artifact adapter
and signed-download flow. Local paths are development adapters only and cannot
become deployment authority.

## Feasibility and renderer policy

Before enabling the profile by default, run the metadata-only shadow matrix with
`scripts/run_high_fidelity_shadow.py` over
`validation/high_fidelity/golden_cases.json`; it must not create a provider task
or user approval. Phase 0 requires at least 18 cross-category shadow cases and
100% compatibility closure. Compare an approved baseline with
`scripts/compare_high_fidelity_runs.py` and retain the same-case fidelity and
active-time evidence required by the dual-stage design. The default compositor
backend is FFmpeg. HyperFrames HTML UI and Remotion React UI are optional
worker adapters and remain disabled until that benchmark demonstrates the
quality and timing thresholds; MediaBunny is limited to client preflight.

Each compared case must carry `fidelity_score`, `active_seconds`, and the
complete compatibility metric set: fixed slots, existing approvals, fixed-B
provider, duplicate-task protection, high-criticality claim evidence (100%),
exact voiceover content (100%), action-chain coverage (at least 90%), zero UI
errors, zero claim regressions, and zero hard failures. Missing metrics fail
closed. The comparison gate requires at least 12 matched cases, an average
fidelity gain of at least 10 points, and active-time overhead within
`min(120 seconds, 10% of the matched baseline)`.
The active weighted QC artifact also carries `media_bindings`: the exact final
MP4 SHA-256 and the immutable same-Run input/upstream evidence digests allowed
as sources. Every dimension and factor requires at least one final-output-bound
target reference, and all source references must be members of that allowed
set. A stale output digest or foreign Run evidence blocks acceptance even when
the supplied scores and schema shape otherwise look valid.
Active production requires all production QC StagePort implementations,
including `FfmpegQcEngine`, to call a deployment-injected evaluator. The stage
preserves `qc_evaluator_response`; the outer boundary recomputes the canonical
request and response digests and requires the evaluator receipt to bind its
implementation, model, final/source media, dimensions, and factor scores. A
real HTTPS semantic evaluator remains a deployment dependency; the bundle does
not pretend that a local comparator is production evidence. Missing evaluator
evidence or a stale receipt blocks the existing QC stage and is never converted
into a technical-only pass; shadow/local compatibility remains unchanged.
The deployable transport reference is
`server.vision_backends.EvidenceBoundHttpSemanticQcEvaluator`. It is configured
with `USFR_QC_EVALUATOR_ENDPOINT`, `USFR_QC_EVALUATOR_MODEL_ID`, and
`USFR_QC_EVALUATOR_MODEL_SHA256`, sends `media_base64` plus optional sampled
evidence bytes, and never sends a worker path. The external HTTPS service still
owns semantic comparison and model inference; the adapter only enforces the
existing receipt contract.
Phase 3 requires 30-40 cross-category regression cases before the profile may
become the default; until then it remains shadow/feature-flag only. The server
serializes these three reports under `activation_evidence` in the immutable
profile snapshot. Production evidence uses
`high-fidelity-activation-evidence/v1`: every report is a canonical JSON
artifact with an exact `report_sha256`, a server-minted immutable publication
receipt, and a receipt digest. The server recomputes case counts, zero-work
counters, fidelity/time deltas, compatibility flags, and regression totals from
the case records; caller-supplied aggregate booleans are never authoritative.
`validate_activation_evidence` requires an injected server receipt verifier for
active/default mode, so a self-attested JSON report cannot activate the profile.
Missing verifier, missing artifact, stale SHA/receipt, or aggregate mismatch
fails closed. `EphemeralWorkerManager.validate_startup_capabilities()` and the
HTTP/service boundaries pass this verifier through only as deployment-owned
metadata. Explicit shadow/legacy and local-development runs retain the
compatibility bypass. This is deployment evidence, not a new stage, approval,
or provider call.

## Deterministic Skill route

The worker calls `scripts/skill_router.py` after the single dynamics pass and
before the existing intent/script work. The output is an immutable
`universal-fidelity-skill-routing/v1` record with `analysis_pass_count=1`, an
ordered module list, `provider_modules`, a canonical `route_sha256`, and
package-relative `dependency_snapshot` entries. A local-only or opaque-only
run's semantic route contains only the bundled dynamics module; it never loads
Seedance or App-evidence modules that cannot affect output. The existing
region-boundary analysis, deterministic splice/compositor, transition-shell
render, and technical QC still run because they are the output-producing path.

For generated regions the route always includes the existing storyboard
adapter, root `seedance-20`, `seedance-prompt`, and `seedance-antislop`. It adds
`seedance-characters`, `seedance-camera`, `seedance-motion`,
`seedance-lighting`, `seedance-audio`, or `seedance-sequence` only when the
frozen analysis requires those factors. The exact route digest is part of the
Invocation A/B parent input digest. A missing or changed dependency blocks
before any paid task; no absolute path or `~/.codex` location is valid.
