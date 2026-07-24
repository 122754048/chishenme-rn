# Deployment Runtime Contract

The deployable image contains all workflow code, bundled skills, Seedance-20
runtime bytes, schemas, validation catalog, and contracts. Runtime operation
must not read the user's workstation or `~/.codex/skills`.

## Required processes and services

- stateless FastAPI process;
- Redis JobStore and Redis Streams;
- S3-compatible object storage;
- ephemeral worker process;
- cleanup sweeper process;
- deployment-injected model, Provider, compositor, UI, OCR, ASR, and semantic
  QC adapters.

`USFR_DEPLOYMENT_FACTORY` names a packaged `module:function` that returns the
same `DeploymentRuntime` to API, worker, and sweeper. Startup checks are exactly
Redis, object store, immutable bundle, models, executable capabilities, and
Provider. Missing or local-only bindings fail before serving or leasing work.

## Stage execution

The worker runs `EphemeralWorkerManager.process_work_message` with a claimed
Redis checkpoint and `EphemeralStageContext`. Media tools receive only verified
lease-local materializations of job-scoped object references. Stage output is
published under `temporary/{job_id}/...` and registered by immutable SHA-256.
API start, every successful checkpoint, and each script/storyboard approval
call the same `EphemeralStageDriver`; it advances the operational plan and
pauses exactly at the review stages. Language-only replacement is generation
work and therefore enters script, storyboard, Seedance, assembly, and QC rather
than falling through to a source-only splice.

The 12 semantic stages remain fixed. `build_semantic_stage_mapping` is an
operational stage mapping and does not add a job-state stage. Fixed image-slot
binding is the target-truth boundary; delayed App evidence reports deferred
target truth and the deferred stage itself.

## Timeline and fidelity invariants

Frozen Segments and Cuts form one global closed set; ordinary generated media
cannot bypass exact Segment/Cut bindings. Every source, generated, UI, opaque,
tail, and omitted interval uses natural decoded media duration with no padding,
freeze, loop, or hidden retime. Per-Segment audio/video boundaries align.
Every non-source carrier and every declared source transition requires an exact
final-output-bound receipt. Source and omitted routes reject any media binding;
manifest route, placement, and omission sets are exact.

The production loader accepts only absolute paths to bundled timeline and
concat dependencies. Supplied UI/tail keeps active content and source
transition-shell behavior; missing tail omits the source tail. One black frame
at a splice boundary is a hard failure.

## Capability and quality activation

The packaged Seedance-20 root, prompt, anti-slop, factor specialists, and
language modules are verified against `runtime_skill_manifest.json` before any
paid CreateVideo request. The profile remains Shadow until immutable activation
evidence satisfies `references/quality-activation-contract.md`.

Production semantic QC must be performed by a deployment-injected evaluator
bound to the actual final MP4 and source evidence. Unit tests, technical-only
reports, self-attested scores, or metadata-only cases are not release evidence.

## Lifecycle

All authority and intermediates are temporary. Object-completion requests bind
an exact `uploads/{upload_scope}/` prefix to the Redis job manifest, including
the language-only object upload route. The sweeper deletes that owned upload
prefix, job Redis keys, and `temporary/{job_id}/`; only a successful verified
`final/{job_id}/result.mp4` remains. See `ephemeral-job-lifecycle.md`.
