# Ephemeral Job Lifecycle

The production authority is a temporary Redis job plus S3-compatible object
storage. There is no SQL database, account, tenant, history, analytics, Outbox,
or SSE subsystem in this video-only package.

## Authority

- `RedisEphemeralJobStore` owns the job snapshot, CAS version, revisions,
  approvals, stage checkpoints, Provider attempts, artifact registry, recovery
  checkpoints, and TTL.
- `RedisWorkQueue` owns active/scheduled delivery, dedupe, reclaim, and ACK.
- `uploads/{upload_scope}/...` contains pre-job upload completions owned by the
  accepted job. Object-completion intake requires one validated exact scope,
  verifies every object with the configured store, and freezes that scope into
  the Redis slot manifest.
- `temporary/{job_id}/...` contains inputs, analysis, storyboards, prompts,
  generated segments, splice intermediates, QC evidence, and recovery data.
- `final/{job_id}/result.mp4` is the only long-lived output.

Every mutation uses the current job version. A stale version fails closed. A
worker ACK occurs only after its lease-fenced stage checkpoint is completed.
Provider `AMBIGUOUS` state is never resubmitted automatically.

`build_script` and `generate_storyboards` return typed revision manifests that
the Worker writes to Redis before their approval boundary becomes reachable.
Only a `run_qc` result with `qc_passed=true` may promote its exact temporary
MP4 to `final/{job_id}/result.mp4`; all other stages are forbidden from
publishing a final result.

## Retention

The sweeper refuses cleanup while a Provider attempt is `SUBMITTING`,
`RUNNING`, or `AMBIGUOUS`. For a successful job it deletes all job Redis keys
plus the exact owned `uploads/{upload_scope}/` and `temporary/{job_id}/`
prefixes while preserving the exact verified final MP4. For a failed, expired,
cancelled, or aborted job it deletes upload/temporary authority and any final
object. If upload ownership exists but the upload-store lifecycle adapter is
missing, cleanup fails closed and retains Redis authority for retry. Cleanup
never accepts the broad `uploads/`, `temporary/`, or `final/` roots.

No local workstation path, installed Skill path, or worker temporary directory
is durable authority.
