# USFR Fidelity Lineage Design

**Status:** User requirements are the approved design authority for this repair.

## Goal

Make every visual-replacement run preserve source visual truth while replacing only user-authorized targets, and make every paid Seedance request provably use the matching source segment plus the approved director storyboard.

## Root cause

The pipeline had a visual-control chain, but it did not bind the generated director board to the replacement-control receipt. The storyboard prompt also prohibited all readable text, so user-confirmed source text could disappear. The user-facing reverse-script renderer exposed internal explanations beyond the two editable sections.

## Design

1. Build source Cut keyframes, generate a source-anchored replacement-control sheet, and generate each director board from that control sheet plus authorized target references. Store the control-receipt SHA and approved-script SHA in every board artifact.
2. Treat the approved script as the sole text authority. For each Cut, carry a canonical list of confirmed visible-text rows (text, role, time window, placement, render mode). A director board must include the rows applicable to its segment and the board prompt must demand the exact literal text. Deterministic overlay rows remain marked for post-production rather than delegated to Seedance.
3. Before paid submission, require a lineage envelope tying the source-video slice, the exact approved board, its board artifact SHA/revision, the board's replacement-control receipt, the frozen segment plan, and the authorized target changes. The provider payload must be exactly `videoUrls[0]=source slice`, `imageUrls[0]=approved board`, followed only by user target assets; source keyframe/control sheets are forbidden.
4. Render the user editable markdown only as `角色、场景与连续性锁定` followed by `逐镜反解`. Preserve evidence, approvals, receipts, and execution/QC notes in server-only artifacts.

## Error handling

Missing or stale source slice, unapproved board, missing control receipt, source/control sheet leakage, unmatched segment, unconfirmed visible text, or malformed user document must fail before any paid request. Existing source-audio and uploaded-audio rules remain unchanged.

## Verification

Add red/green tests for all lineage and text cases, run focused tests, then the full skill test suite and bundle runtime closure check. Inspect Git status/remotes before committing and pushing without overwriting unrelated work.
