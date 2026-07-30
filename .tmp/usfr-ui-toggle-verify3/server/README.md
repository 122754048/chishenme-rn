# Lightweight Video-Only Server Runtime

This package runs the Universal Source-Fidelity Replication workflow with a
stateless API, Redis job authority/Streams queue, S3-compatible temporary media,
an ephemeral worker, and a cleanup sweeper. It intentionally contains no SQL,
account, tenant, payment, order, subscription, quota, history, analytics,
Outbox, or SSE control plane.

## Processes

- API: `server.deployment_bootstrap:build_http_app`
- Worker: `python -m server.worker_entrypoint` with
  `USFR_PROCESS_ROLE=worker`
- Sweeper: the same entrypoint with `USFR_PROCESS_ROLE=sweeper`

Set `USFR_DEPLOYMENT_FACTORY=package.module:create_runtime`. The factory must
return `DeploymentRuntime` or the documented equivalent mapping containing a
Redis JobStore, Redis work queue, object store, cleanup sweeper, FastAPI app,
ephemeral worker manager, and the exact readiness checks. The module must be
inside the deployed image; workstation and `~/.codex/skills` paths are rejected.

## Runtime authority

`RedisEphemeralJobStore` owns job CAS state, revisions, approvals, stage
checkpoints, Provider attempts, artifacts, recovery checkpoints, and TTL.
`RedisWorkQueue` owns delivery, reclaim, scheduling, and ACK. The worker uses
`EphemeralStageContext` and may materialize media only from verified job-scoped
object references into its lease-local temporary directory.

`EphemeralStageDriver` projects the existing twelve-stage plan into executable
queue entries. API start enqueues the first stage; successful Worker checkpoint
completion enqueues the next stage; script/storyboard approval resumes the same
driver. It pauses exactly at the two review boundaries. A `build_script` port
must append its revision manifest before returning, and a
`generate_storyboards` port must append its storyboard revision manifest before
returning, so the review APIs can browse and approve immutable artifacts.

Accepted object-completion inputs use one exact `uploads/{upload_scope}/...`
namespace that is frozen into the job manifest. All worker intermediates use
`temporary/{job_id}/...`. The only persistent object is
`final/{job_id}/result.mp4`. `CleanupSweeper` removes the owned upload scope,
Redis authority, and all temporary objects after completion/expiry while
preserving only a verified successful final MP4.

## Safety and fidelity

- Seven fixed media slots; `output_language` is a separate fixed parameter.
- Script and storyboard revisions use CAS and downstream invalidation.
- The latest approved revision digests bind Segment planning, Seedance-20,
  Provider submission, assembly, and QC.
- Provider ambiguous outcomes are reconciled and never blindly resubmitted.
- Supplied UI/tail media keeps natural active duration and is never padded.
- Missing tail omits the source tail interval.
- Recovery re-enters through the failed stage's existing artifact contract.
- Startup requires an immutable packaged Seedance-20 bundle and executable
  capability bindings.

See `references/server-api-contract.md`, `ephemeral-job-lifecycle.md`,
`adaptive-fidelity-recovery-loop.md`, and `deployment-runtime-contract.md`.
