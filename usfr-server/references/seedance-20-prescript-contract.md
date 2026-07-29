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

For an active `high_fidelity_hybrid_v1` run, `invoke_b(...)` requires the
frozen final `segment_plan`. It contains one or two ordered generated segments;
each segment has a unique `segment_id`, output-global integer `start_ms` and
`end_ms`, a derived `duration_ms` from 4000 through 15000, and unique ordered
`cut_ids`. The plan's Cut union must equal Invocation A's generated Cut set.
Invocation B selects exactly one current segment, verifies the prompt segment's
ID, duration, Cut order, and global origin, then calls
`rebind_line_contracts(...)` over every approved line and its proof, Foley, and
silence windows. It compiles only the current segment's rebound rows. If the
caller supplies final line rows, they must already match the deterministic
segment-local coordinates exactly; global-time or independently rebound rows
are rejected. The B result records `segment_plan_sha256`, `segment_id`, and the
current segment Cut IDs without adding a required public digest or workflow
stage.

Route 1 text, speaker, language, claims, and approved Cut timing are immutable;
Route 2 may receive an evidence-bounded copy proposal before its existing script
approval. Invocation B must validate the same snapshot and compile the final
prompt through the installed `seedance-20` skill before the unchanged fixed-B
integrity audit.

The server-side Invocation-B boundary is
`scripts/seedance_prompt_compiler.py`. It loads the root and only the
factor-specific Seedance skill files selected by the immutable route, records
their logical package paths and exact byte hashes, renders every approved line
with `says exactly` wording and integer-millisecond timing, and rejects prompts
over 5000 characters, route-excluded media fields, missing exact lines, stale
skill hashes, or a changed line-contract digest. It is a deterministic bridge
around the packaged `seedance-20` skill, not a replacement for that skill and
not a provider call.

The active profile supplies Invocation B with structured segment/line/factor
inputs or an immutable artifact already compiled by that packaged boundary. A
raw free-form prompt is a legacy/local compatibility input and cannot authorize
an active high-fidelity paid request. The compiler additionally proves that
shots cover the complete 4-15 second segment without gaps or overlaps; every
approved line, proof, Foley, and protected-silence window remains inside the
segment; speaker and millisecond rendering are unchanged; and each declared
Cut has approved speech or the canonical `No dialogue` contract. Readable App
UI text is carried only by a deterministic UI render contract with OCR target
100, never by Seedance-generated pixels.
