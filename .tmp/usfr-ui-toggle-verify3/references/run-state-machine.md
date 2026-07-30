# Ephemeral Job State and Stage Contract

Redis stores one versioned temporary `JobSnapshot`; stage checkpoints and
revision manifests are separate job-scoped hashes with matching TTL. This is a
video-generation state contract, not a durable product-history database.

## Semantic workflow

The workflow retains exactly 12 semantic stages:

`intake_bind`, `target_truth`, `dynamics`, `region_overlay_route`, `intent`,
`script`, `region_duration`, `storyboard`, `prompt_audit`, `provider`,
`assembly`, `qc_delivery`.

Operational worker names may be more granular. The read-only
`build_semantic_stage_mapping` projection is an operational stage mapping; it
does not add a job-state stage, approval, route, or Provider task. Fixed
image-slot binding is the target-truth boundary. Deferred App evidence reports
the deferred stage itself as deferred target truth.

## Approval states

- local-only route: zero user approvals.
- Route 1: storyboard approval only.
- Route 2: script approval, then storyboard approval.

Editing or regenerating a script invalidates all storyboard, Segment, Prompt,
Provider, assembly, and QC authority. Editing a storyboard invalidates Segment,
Prompt, Provider, assembly, and QC authority. Only the latest approved script
and storyboard SHA set may enter post-approval work.

## Work checkpoints

A stage claim binds job ID, stage, dedupe key, owner, version, and lease. Only
the current owner may complete it. Redis Streams ACK follows successful
checkpoint completion. Expired leases are reclaimable; completed dedupe keys
are not re-executed. Provider `AMBIGUOUS` state blocks blind retry.

Adaptive Fidelity Recovery is temporary state inside the failed stage and
reinjects its passing candidate through that stage's existing artifact kind.
