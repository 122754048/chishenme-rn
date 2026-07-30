# Seedance-20 Invocation A contract

`seedance20_prescript_v1` is an internal, non-provider executability sidecar.
It runs inside the existing intent/script work (Route 2) or as read-only
enrichment after an approved script is loaded (Route 1). It does not add a
public slot, route, RunState, stage, approval, CreateAsset, or CreateVideo.

The artifact records the exact packaged `seedance-20` skill name, metadata
version, byte SHA-256, parent input digests, candidate generated regions, legal
split Cuts, fidelity-budget allocation, reference roles (maximum four), action
endpoint, audio strategy, and exact line contracts. Opaque UI, supplied tail
media, and source-origin intervals are boundary/technical inputs only; their
contents never enter A or B.

Each candidate is fail-closed unless it carries a non-empty shot budget whose
durations exactly cover the candidate and whose every shot has a primary action
and concrete endpoint; a `background_strategy`; a non-empty performance
strategy; an action-state list ending in a required `completed` state; and an
audio strategy with music policy, ambience, Foley IDs, and silence-window IDs.
Every spoken line must carry a `candidate_region_id`, belong to one of that
region's Cuts, and have an explicit `voiceover_timing_plan` carrier
(`prompt` or `postproduction`). A line carrier cannot be omitted, duplicated,
or point to an unknown line. The paid-boundary bridge repeats these checks after
digest validation so recomputing a sidecar hash cannot bypass them.

Invocation A is provisional. The existing duration planner remains the sole
authority for final segment IDs and boundaries. After script approval, the
worker deterministically rebinds global integer-millisecond line/proof/Foley/
silence windows to one segment and rejects any boundary crossing. A stale skill
snapshot, invalid JSON, unsupported claim, more than two candidate regions, or
more than four reference roles fails closed before any paid request.

For an active `high_fidelity_hybrid_v1` run, the existing prompt stage must
pass the frozen final `segment_plan` into `invoke_b(...)`. The plan contains one
or two ordered `4-15s` generated segments with unique `segment_id`,
output-global integer `start_ms`/`end_ms`, derived `duration_ms`, and exact
ordered `cut_ids`; its Cut union must equal Invocation A's generated Cut set.
Invocation B selects one current segment, validates its prompt ID/duration/Cut
order/global origin, and calls `rebind_line_contracts(...)` for every approved
line plus proof, Foley, and silence windows. Missing plans, overlaps, Cut drift,
boundary crossings, or supplied global-time rows fail before prompt
compilation. The result records the canonical segment-plan SHA-256 without
adding a public digest, stage, approval, or provider task.

The worker validates the sidecar with
`validate_prescript_artifact(...)` and uses
`rebind_line_contracts(..., segment_plan)` for the deterministic local-time
rebind; these helpers are internal adapters, not new public API or workflow
stages.

Route 1 text, speaker, language, claims, and approved Cut timing are immutable;
Route 2 may receive an evidence-bounded copy proposal before its existing
script approval. Invocation B must validate the same snapshot and compile the
final prompt through the installed `seedance-20` skill before the unchanged
fixed-B integrity audit.

The worker injects the versioned skill snapshot through its deployment package
or `SEEDANCE20_SKILL_FILE`. A workstation `~/.codex/skills` path is never an
authoritative dependency and is not persisted in the run artifact.
