# USFR User-Editable Script Approval Design

**Status:** Awaiting user review

## Goal

For every USFR task except direct language-only localization, make one user-readable, user-editable script the sole script-stage artifact presented for modification and approval. Bind every accepted edit precisely to the original scene, speaker/singer, and content row before compiling it into the existing internal execution contracts.

## Scope

This design changes script presentation, edit ingestion, approval gating, and storyboard prerequisites. It does not add an input slot, a user account system, a third approval, a new Provider task, or a new video semantic stage.

## Route Rule

`direct_language_only` is true only when `source_video` plus `output_language` are the complete user change request and all six optional fixed slots and `background_music` are absent.

| Request type | User script | Storyboard | Existing execution route |
| --- | --- | --- | --- |
| `source_video + output_language` only | Do not create or display | Do not create or display | Existing ASR -> translation -> TTS -> lip-sync route |
| Any visual replacement, UI/tail replacement, music extension, or language plus any replacement | Create, allow edits, require explicit approval | Generate only after script approval; require explicit approval | Existing standard replication route |

No internal route label, cache state, or previously approved script may bypass the two user approvals on a non-language-only run.

## User-Visible Script

At the script stage, the user receives only a `User Editable Script v1` document. It contains no JSON, IDs such as UUID/SHA, Provider/model names, prompts, code, internal routing names, artifact paths, technical errors, or framework instructions.

Each document contains:

1. A short title, target language, and product/App name when supplied.
2. Ordered scene blocks with a human-readable scene number, source time range, and concise visual/action description.
3. Independent editable content rows for subtitles, dialogue/voiceover, sung lyrics, selling-point copy, proof/offer copy, screen text, CTA, and required disclaimer text.
4. A visible human-readable location key in the form `Scene 02 / Speaker A / Dialogue 01` or `Scene 03 / Screen Text 02`. This key is stable across revisions and is the only locator the user must preserve.
5. Speaker/singer fields using user-facing names: character, narrator, off-camera voice, singer, or chorus.
6. Performance fields only when useful to the user: emotion, pronunciation note, and delivery instruction.
7. Explicit `Must keep` and `Do not say` rows for approved brand/product facts and compliance constraints.

Empty categories are displayed as `None` and are not invented. A scene with no singing never receives a lyric row. A visible person with no spoken line remains visual-only rather than being assigned dialogue.

## Precision Binding Contract

Internally, every user-visible location key maps one-to-one to an immutable binding tuple:

`(scene_id, content_kind, content_row_id, speaker_or_singer_id, ordinal)`.

The tuple is not shown to the user. The user-facing key is deterministic from it and must remain unique within a revision.

When the edited document is submitted:

1. An unchanged location key preserves its original row and position.
2. A changed row updates only the matching tuple.
3. A deletion must be marked `Delete`; omission is not treated as deletion.
4. An insertion must state `Insert after: <user-facing location key>` and receives a new ordinal under the same scene/content kind.
5. A speaker/singer change updates only that row's assignment and forces speaker/visibility/lip-sync validation before internal compilation.
6. A duplicate, missing, altered, or ambiguous location key is rejected. The user receives a plain-language conflict list naming only the affected scenes and rows; the system must not guess, silently move text, or send a Provider request.
7. Every accepted edit produces a new user-script revision. The exact compiled internal script revision records the approved user-script revision digest as its parent.

## Multi-Speaker and Singing Rules

- Dialogue is turn-based. Every speaker turn is a separate row, even when two speakers share one scene or subtitle interval.
- Narration, off-camera dialogue, singing, and chorus are distinct content kinds; no row may be both dialogue and lyric.
- Subtitle text remains independently editable. A subtitle can summarize a spoken line, but the binding explicitly records its relationship rather than assuming equal text.
- A singer must have a lyric row; a chorus has an ordered member list and a shared lyric row only when the source contract permits group singing.
- User edits may change wording and speaker assignment, but cannot merge separate speakers by deleting their location keys. Such a change must be represented as explicit deletions plus an insertion.

## High-Density Copy Rules

- Each subtitle, dialogue turn, lyric line, selling point, proof, offer, screen-text line, and CTA is an independent row.
- The system never silently truncates, merges, or drops rows because a scene contains many text items.
- The user-facing script does not expose model duration thresholds. For every supported target language, natural translated/TTS duration is allowed.
- When content requires a visual or speech split, the user receives a plain-language edit choice that preserves all copy: keep as multiple sequential lines, move a named row to the next scene, or explicitly shorten that row. The system does not invent a shortened version.

## Approval State Machine

For all non-language-only runs:

1. Analyze source and target evidence using the existing stages.
2. Generate and persist `User Editable Script v1`.
3. Stop in `SCRIPT_AWAITING_APPROVAL`.
4. Accept zero or more user-script revisions. Each edit invalidates any downstream storyboard, segment, prompt, Provider, assembly, and QC artifacts.
5. Approve one exact user-script revision.
6. Compile that approved revision into the existing internal script contract.
7. Generate storyboard from that exact compiled script only.
8. Stop in `STORYBOARD_AWAITING_APPROVAL`.
9. Approve one exact storyboard revision, then continue the existing autonomous prompt, Provider, assembly, and QC sequence.

For `direct_language_only`, retain the existing no-approval localized-audio/lip-sync flow. It must not create a hidden user script or storyboard revision.

## Presentation Boundary

The script-stage API/UI response contains only the current user script, plain-language validation conflicts, and the commands to submit edits or approve it. It must not contain internal script revisions, prompt drafts, source analysis, request SHA values, queue/provider state, object keys, or technical implementation details.

Storyboard approval remains a separate visual presentation after script approval. It may show the approved scene labels and images needed for human review, but not script-stage internal implementation material.

## Acceptance Criteria

1. A language-only run creates no script revision, no storyboard revision, and no approval wait.
2. Every non-language-only route, including routes that previously used `route_1` or `local_only`, blocks before storyboard generation until an exact user-script revision is approved.
3. The user-script response contains only allowed user-facing fields.
4. At least two speakers, a narrator, a singer, and a chorus can coexist without any row changing identity or position after another row is edited.
5. Dense copy preserves every row through edit, compile, storyboard input, and final internal script binding.
6. Duplicate/missing/ambiguous keys fail before any storyboard or Provider work and return only user-readable conflict descriptions.
7. A script edit invalidates all downstream revisions; a storyboard always records the exact approved user-script parent.
8. The existing two-approval limit remains unchanged for non-language-only routes.

## Non-Goals

- No free-form, unstructured natural-language revision endpoint.
- No automatic shortening, speaker reassignment, or cross-scene text relocation.
- No exposure of technical prompts or internal artifacts to the user.
- No changes to the seven fixed slots, background music contract, final lip-sync MP4 rule, or Provider retry/idempotency policy.
