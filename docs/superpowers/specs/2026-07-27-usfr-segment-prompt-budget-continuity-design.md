# USFR Segment Prompt Budget and Continuity De-duplication Design

**Status:** Awaiting user review

## Goal

Before a non-language-only USFR task presents its editable script, compile a
deterministic Seedance preview for every planned generated segment and prove
that each final prompt will contain at most 5,000 characters. At the same time,
show a continuous world only once in the user script: the first cut establishes
the shared scene, subject, product, wardrobe, and environment; later
uninterrupted cuts state only what changes.

This prevents a task from reaching prompt submission before discovering an
over-length prompt. It also removes repeated visual setup such as describing
the same tree in two consecutive cuts, without deleting dialogue, lyrics,
selling points, or any other necessary content.

## Scope

This applies to every route that builds Seedance generated segments. It runs as
private work inside the existing `build_script` stage before the existing script
approval. It creates no Provider task, public stage, input slot, or additional
approval.

`direct_language_only` remains unchanged: it creates neither an editable
script nor a Seedance prompt, so it has no segment prompt budget work.

The design does not change the seven fixed slots, background-music semantics,
audio/lip-sync routes, storyboard approval, Provider retries, or final-media
assembly rules.

## Seedance 2.0 Rules Adopted

The implementation follows the sequence and prompt-writing rules in
`C:\Users\zhaocx04\.codex\skills\seedance-20`:

1. Plan the story globally but compile only one generation-sized segment at a
   time.
2. Treat a scene as the continuity/re-anchor unit. An uninterrupted cut may
   inherit its accepted scene state; a scene boundary or a new independent
   generation must open from the canonical anchors again.
3. Preserve continuity locks: character identity, wardrobe, screen geography,
   product state, environment, and completed action endpoints do not drift.
4. Each prompt describes the current segment only. It names the subject,
   visible change, camera, and required constraints; scene information already
   carried by an anchor/reference is not repeated.
5. Keep final prompts in natural language and below the verified surface
   budget.

The Seedance compression guidance is narrowed by the approved USFR rule:
this feature may remove only information that is proven duplicate because the
same canonical continuity fact already applies. It must not remove non-duplicate
background details, secondary actions, emotional direction, dialogue, lyrics,
selling copy, proof, CTA, or safety/compliance constraints merely to save
characters.

## Definitions

- **Cut:** One ordered source-derived visual unit in the approved script.
- **Generated segment:** One 4-15 second Seedance request containing one or
  more ordered cuts.
- **Continuity scope:** Adjacent cuts in the same scene that have compatible
  time, location, cast/product, and screen-geography state. An editorial scene
  change, incompatible state, or an intervening cut that breaks any lock ends
  the scope.
- **Canonical continuity fact:** An evidence-backed fact such as the large tree
  in the environment, a character's wardrobe, a product's visible state, or the
  left/right placement of a subject. It has one owning cut inside a continuity
  scope.
- **Anchor cut:** The first cut that establishes the facts inherited by later
  cuts.

Facts are identified from the source analysis and fixed-slot evidence, not from
text similarity. Two differently worded instructions are never treated as the
same fact just because they look similar.

## Script and Continuity Projection

During `build_script`, the continuity planner derives an ordered private ledger
from the source cuts. For each fact it records its owning cut, valid scope,
locks, and the later cuts that inherit it.

The user-facing script projects that ledger as follows:

1. The anchor cut contains the complete shared visual setup once.
2. A following inheriting cut begins with a plain-language continuation such as
   `Continue from the previous shot` and contains only its new action, camera,
   timing, dialogue, lyric, on-screen copy, or other change.
3. The inherited description itself is not repeated. In particular, Cut 2 does
   not repeat `the large tree` after Cut 1 has established that the same tree
   remains in the continuous scene.
4. A changed or newly visible fact is written in the cut where it first becomes
   necessary. It is never discarded as a duplicate.
5. Dialogue turns, narration, lyrics, chorus, subtitles, selling points,
   proof/offer, screen text, CTA, and disclaimers retain their existing stable
   user-facing rows. They are never de-duplicated by this feature.

The user script contains only creative material and continuation wording; it
does not expose fact IDs, prompt counts, model names, hashes, or planner state.
When a user edit changes an anchor or a later cut, the planner recomputes the
ledger and returns the updated user script for the normal script review. It may
remove only a newly repeated inherited visual fact; it must preserve all other
edited content and bindings.

## Segment Budget Flow

1. Project cuts and user-editable rows using the continuity ledger.
2. Partition ordered cuts into provisional legal generated segments. A split is
   permitted only at a cut boundary; cut order, timing, and content never move
   or disappear.
3. Compile every provisional segment using the same Seedance prompt rendering,
   reference-role rules, line contracts, and continuity anchors used by the
   final compiler.
4. Record an internal `prompt_budget_plan` for each segment: segment/cut
   membership, anchor ownership, exact preview character count, and a digest of
   the preview compiler inputs.
5. Only present the script when every preview prompt is at most 5,000
   characters. The budget plan is private and is bound to the user-script
   revision.
6. After script approval and storyboard approval, the final compiler must use
   the frozen segment membership and approved continuity projection. It repeats
   the length check as an integrity guard. A late prompt may not add material
   that was not included in the preview budget.

The final check remains a fail-closed safety guard, but an ordinary valid task
must already have passed the exact preview before the user sees the script and
must not discover the 5,000-character limit at Provider submission.

## Overflow Policy

When a provisional segment exceeds 5,000 characters:

1. Remove only visual statements proven redundant by the same continuity
   ledger. Recompile the exact preview.
2. If it remains over budget, automatically repartition at legal cut boundaries
   into additional generated segments. All cut content remains intact and stays
   in chronological order.
3. Re-run the exact preview for every new segment.
4. If one unsplittable cut still exceeds the limit, stop before script approval
   and return a plain-language script-stage conflict naming the affected scene
   and editable content rows. The conflict asks for an explicit rewrite or a
   user-approved visual split; it never truncates or silently shortens content.

An isolated generated segment may need to restate the canonical scene anchor to
Seedance because a separate Provider request has no memory of the previous
segment. That internal re-anchor is necessary information, not duplicate user
script content. The user-facing script still establishes the fact once and uses
continuation wording for its uninterrupted cuts.

## Edit, Approval, and Invalidation Rules

- Script edits keep the existing stable row bindings and do not add a third
  approval gate.
- Any script edit reruns continuity projection, segment partitioning, and
  exact-preview budgeting before the edited revision can be approved.
- A changed anchor invalidates every inheriting cut's private projection and
  every downstream storyboard, prompt, Provider, assembly, and QC artifact.
- A changed later cut invalidates its affected generated segment and all
  downstream artifacts, while retaining unrelated user-script rows.
- The existing script approval freezes the exact user script plus its private
  continuity and budget-plan digests. The existing storyboard approval remains
  the only second approval.

## Acceptance Criteria

1. Two adjacent cuts in one continuity scope that both contain the same tree
   show the tree only in the anchor cut of the user script and only once in the
   generated segment prompt.
2. A later cut with a new tree, a new location, different wardrobe, a changed
   product state, or incompatible screen geography retains the new necessary
   description.
3. Identical wording alone does not authorize removal; deduplication requires
   proof that the same canonical fact is inherited through an unbroken scope.
4. Dialogue, narration, subtitle, lyric, chorus, selling-point, proof/offer,
   screen-text, CTA, and disclaimer rows survive unchanged, including dense and
   multi-speaker scripts.
5. Every generated segment has an exact preview prompt length of at most 5,000
   characters before the editable script is displayed or approved.
6. A 5,001-character provisional segment is first de-duplicated, then split at
   a cut boundary if possible; it never reaches storyboard or Provider work as
   an over-length prompt.
7. An unsplittable over-limit cut reports only the affected user-facing scene
   and rows, with no truncation, silent rewrite, Provider task, or technical
   implementation detail.
8. A final compiler attempt whose content diverges from the frozen preview or
   exceeds 5,000 characters fails before any paid Provider request.
9. Direct language-only tasks and all unrelated fixed-slot, audio, lip-sync,
   and approval-count behavior remain unchanged.

## Non-Goals

- No semantic similarity engine that merges differently worded creative ideas.
- No automatic shortening of necessary information.
- No additional user confirmation beyond the existing script and storyboard
  approvals.
- No public exposure of prompts, budget numbers, hashes, provider/model names,
  or continuity-ledger implementation details in the editable script.
