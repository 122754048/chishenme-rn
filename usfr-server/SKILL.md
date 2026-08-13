---
name: universal-source-fidelity-replication
description: Use when a source video plus approved change inputs must be replicated as an approved video edit.
---

# Universal Source-Fidelity Replication

This Skill has one single video-edit replication entrypoint: `video-edit-v2`.
It turns an approved source-video segment into a controlled edit, rather than
creating a new video from a loose brief. Canonical runtime contract:
`references/video-edit-v2-contract.md`.

## V2 authority and migration status

`video-edit-v2` is the only active entrypoint. Legacy storyboard, prompt-
invocation, high-fidelity profile, and UI-sidecar packages may remain packaged
for regression or recovery, but they are quarantine-only: they are not a
fallback, an active approval gate, or a second Provider route.

The runtime audio migration is verified at the model-ownership boundary. The active
`server/audio_lane_router.py`, `server/analysis_scope.py`, and V2 stage-plan
tests route every language-change request and every target-song MV through one H3
edit, while visual-only edits remain on Seedance. A generated segment never runs
both models and has no external post-generation lip-sync stage. `VoiceoverTtsStage`/`run_tts` is retained only
for an approved off-camera voiceover lane and must never be used for
language-only or on-camera speech. The non-V2
`language_only_cloud_lip_sync` reason and lower-level legacy client/config
references remain migration evidence, not proof of an active V2 route. Until
those remnants are either quarantined with tests or removed after a dependency
review, the audio migration gate is not complete.

## Intake and boundary

`source_video (required)` is the edit object. The optional, composable inputs
are `new_model_image`, `new_product_image`, garment, scene, `ui_screenshot`,
`app_store_url`, `ui_operation_video`, `tail_video`, `background_music`,
`output_language`, and a change instruction. Bind the existing public media
slots with `scripts/bind_input_slots.py`; garment and scene enter through a
multi-value `new_model_image` upload and an approved binding table that fixes
`source_index + SHA-256 + asset_type`, never filename/OCR inference. A source with no approved change
is analysis only: request an explicit modification and never create a no-op
paid edit.

`@Video1 is the edit object`. A Provider segment covers at most `≤15s`, and the
active editable duration remains at most 30 seconds. Segment planning has
natural Cut priority. When a 15–30 second source has no legal natural Cut,
`frame_midpoint_fallback` selects the nearest legal midpoint on a fixed 24 fps
grid and emits `forced-continuity-boundary/v1`; this grid selects the boundary
only and never retimes source footage. Exactly two contiguous segments cover
the active interval without overlap or missing time. First identify and remove
only a confirmed terminal logo/download tail. UI Cuts are preserved unless an
approved UI route replaces them. A two-segment edit uses a hard cut and an
explicit continuity handoff. Natural-Cut planning still produces at most two
natural-Cut segments before the midpoint fallback is considered.

## Workflow

1. Freeze source Cut, timing, audio, visible-text, and terminal-tail evidence.
   Extract the original hook mechanics, then map the target product or App's
   feature, pain point, proof, and display/operation affordance to that same
   mechanics. Different categories require different demonstrations.
2. Publish one user file, `analysis/reverse_storyboard_script.md`, then pause
   only for one script approval. There are no storyboard, prompt, plan,
   duration, or QC approval gates.
   The first public script offers two choices: `直接执行` approves it as-is;
   a natural-language modification is interpreted into the hidden canonical
   change rows and then executed without publishing a second public script.
3. `plan_segments` consumes approved script change rows, source Cut evidence,
   and internal asset-board authority to freeze the hidden deterministic Cut
   execution plan. It is not a user file or approval gate.
4. Compile the deterministic v2 prompt and immutable request audit; submit only
   after its server-side integrity check. A worker uses verified private object
   storage and lease-owned temporary media; a path is never a workstation path.
5. Assemble, perform deterministic overlay/UI work, run final QC, and deliver
   only the verified final MP4.

The five phases above expand into one twenty-step V2 operating flow. These are
process semantics, not permission to add user gates or new RunState stages:

1. Bind typed input slots and immutable upload receipts.
2. Reject a source with no approved change as analysis-only; never create a
   no-op paid edit.
3. Probe and lightly decompose the source into Cuts, timing, camera, action,
   terminal-tail, visible-text, and preservation evidence.
4. Analyze source audio once into immutable windows for singing, spoken,
   voiceover, music, SFX, ambience, silence, visibility, and replacement
   policy; every later stage reuses this result.
5. Analyze target product, App, model, garment, scene, UI, tail, language, and
   audio evidence without inventing unsupported claims.
6. Run the Replication Matcher before any paid Provider call; return
   `direct_fit`, `adapt_fit`, or `unsuitable` and stop on an unsuitable or
   unresolved match.
7. Build `analysis/reverse_storyboard_script.md` from source evidence, target
   evidence, Matcher output, and exact editable change rows.
8. Publish the file and obtain the single script approval; no storyboard,
   prompt, duration, split, or QC approval is user-visible.
9. Generate only the required target asset boards with the appropriate
   reference structure.
10. Freeze asset identity, source index, SHA-256, asset type, stable tags,
    image references, and first-use mapping.
11. Freeze the hidden `plan_segments` Cut/segment plan, including continuity,
    audio windows, text routes, UI/tail routes, and handoff evidence.
12. Select exactly one generation owner: H3 for a target-song MV or any
    language change, otherwise Seedance for visual-only edits. Never run both
    for the same generated segment.
13. Compile that owner's compact deterministic V2 edit prompt from the approved
    script and frozen plan without mixing H3 and Seedance reference syntax.
14. Audit the exact Provider request, digests, references, and Matcher receipt
    server-side before the paid create call.
15. Submit and poll only the selected Provider edit using the immutable source
    and approved target references.
16. For an approved target-song MV or any language change, use the single H3 edit
    selected before generation; never schedule a second lip-sync or Seedance pass.
17. Apply deterministic post-processing for UI-operation video, terminal tail,
    approved music windows, subtitles/headlines/CTA/price, and physical-text
    routes; do not regenerate a deterministic UI or tail in Seedance.
18. Run final QC within the bounded budget. A confirmed Provider failure or
    eligible pass2 QC failure may use its one owned retry; reconcile ambiguous
    Provider outcomes first and never stack Provider and QC retries.
19. Publish only the verified final MP4 with its final artifact receipt.
20. Remove or expire job-scoped temporary material and retain only the approved
    script artifact plus final MP4 as user-facing deliverables.

For `frame_midpoint_fallback`, seam QC checks identity, object state, hand and
surface contact, action direction, camera continuity, audio continuity, black
frames, duplicate frames, and missing frames at the forced boundary.

The hidden `plan_segments` plan is not a user file or approval gate. A worker
uses verified private object storage and lease-owned temporary media; a path is
never a workstation path.

## User-visible artifact boundary

The user sees exactly two deliverables: the downloadable
`analysis/reverse_storyboard_script.md` and the verified final MP4. Asset
boards, source frames, audio analysis, prompt/audit payloads, segment plans,
Provider receipts, UI splice receipts, QC reports, and temporary files remain
internal evidence. Inline script text, storyboard images, and intermediate
boards are not substitutes for the two artifacts.

The prompt begins `编辑视频：`. It lists only approved replacements, additions,
and exact dialogue/text windows. All unmodified content remains
frame-for-frame preserved.

## Assets and hidden Cut plan

Canonical asset preparation produces boards for `model/garment/scene/product/app`.
Every person/model target first becomes one `1024 x 1024` PNG
`model-identity-v3-local-crop` asset: one identity, identity-dominant square
composition, clear face, and the visible target wardrobe/accessory evidence needed by
the approved scope. Use a deterministic crop/resize when the supplied image can satisfy
that contract; use RunningHub Image2 only when it cannot, and require the generated
result to satisfy the same square contract. RunningHub Image2 remains the canonical
generator for required garment/scene/product/app boards. Use stable person/product tags and explicit
source-role mapping: multiple models cannot replace one source person, while a
garment may share its mapped person. Image references are continuous
`@Image1..N`, and `uploaded_tags == binding_tags == prompt_tags`. Every board
must retain its source slot/index, target asset type, upload SHA, board SHA,
first-use Cut, and replacement-object tag. A failed board is a hard failure;
the original upload is never silently substituted.

The Matcher receipt, approved script SHA, asset-binding SHA, audio-window SHA,
segment-plan SHA, and Provider request SHA form one paid-call authority chain.
No paid call is valid without all applicable members of that chain.

`plan_segments` keeps Cut order, timing, movement, action purpose, target
display/operation steps, dialogue/text windows, segment allocation, continuity
handoff, and postproduction routes as internal deterministic authority. In
`video-edit-v2`, storyboard images are not generated, uploaded, or bound.

## Routes, text, and audio

- No UI asset: source UI keep (`source_ui_keep`; runtime `preserve_source_ui`).
- `ui_operation_video`: deterministic FFmpeg splice
  (`deterministic_ui_operation_splice`; runtime `splice_ui_operation_video`).
- `ui_screenshot` or `app_store_url`: App asset board + Seedance edit
  (`app_asset_board_edit`; runtime `app_asset_seedance_edit`).
- Tail choices are trim source logo/download, supplied tail splice, or no tail
  card; the selected execution authority is retained through assembly.

`ui_operation_video` is a deterministic FFmpeg splice over the approved source
window. A confirmed terminal logo/download tail is trimmed, a supplied tail is
spliced, or the source tail is preserved; Seedance never guesses a tail card.

Only `generation_surface` physical text—scene, prop, paper, wardrobe, or
packaging text—may be an edit prompt replacement. Subtitle, headline, CTA,
price, and UI text are deterministic overlay/UI postproduction. Watermark work
requires an approved time window and region; never blur, mask, or guess.

Audio preserves by default and is classified once into reusable time windows.
`music-only` replaces only approved music. The `voice/dialogue` lane preserves
approved spoken-window semantics. Any target-song MV uses one `H3 MV edit`, and any request
containing a language change use a single H3 edit, including compound person,
product, App, scene, garment, jewelry, or accessory edits. Visual-only edits use
Seedance. Ordinary on-camera speech uses the selected generation prompt without an
external lip-sync workflow. Changed off-camera `voiceover` remains
Seedance-first. Only when the assembled picture passes and targeted QC proves
a voiceover-only failure (`missing_line`, `omitted_words`, `wrong_words`,
`wrong_language`, `absent_voiceover`, or `severe_timbre_drift`) may
`VoiceoverTtsStage`/`run_tts` replace that failed contiguous block without face
lip-sync. Workflow `2080177717619118082` receives source reference audio at
`4.audio` and user-approved plain text at `11.prompt`; Whisper timestamps and
metadata never enter the prompt. One block permits one create attempt, after
which failure or ambiguity requires reconcile/manual review. This exception
does not apply to unchanged audio, language-only, or on-camera speech.
MV target-song editing is owned by H3 in the generation request. Source audio
classification and UI monologue protection remain analysis/assembly evidence,
but they never trigger a post-generation song workflow.

## Complexity, recovery, and safety

Score unique edit capabilities. At `score == 3.0`, the edit is within the
threshold; above it, `split_required` fixes pass1 to model/person,
dialogue/language, and garment, and pass2 to product, UI/app, scene, and
physical text. If pass1 alone exceeds the threshold, return
`manual_review_required`.

Provider retry once and QC pass2 retry once are mutually exclusive for a
single pass. A confirmed provider failure can retry only its owned pass once;
an ambiguous result must enter reconcile before any new create. A final QC
failure in pass2 retries pass2 while reusing accepted pass1 authority. A
pass1-factor final-QC failure is manual review, never a guessed rerun. Any
changed upstream approval or digest marks dependent authority
`needs_recompute` before it can run. Physical deletion of compatibility files is
not part of this document-only patch: it requires the dependency map, dynamic
load scan, targeted regression, and full release validation to agree.

When object-level QC proves that an accepted Provider video has only partial
person identity failures, the existing assembly/QC flow may select
`local_multi_track_completion`. It does not add a RunState stage, approval, or Provider call.
One local execution reuses the accepted Provider video and binds
all eligible failed tracks by `source_object_id + target_asset_sha256`, using
`embedding_plus_motion_unique_assignment`; it never performs paid per-person
generation. Eligibility is strictly `person + face_identity_only`, a verified
capability receipt must cover the number of failed tracks, accepted tracks are
protected, and ambiguous or missing detections keep the Provider pixels.
The completed output must packet-copy the complete source audio stream and pass
the ordinary final QC. Any product/App/scene/garment/jewelry/accessory failure
stays on the existing generic recovery or manual-review route. See
`references/local-multi-track-identity-completion.md`.

For every approved visual replacement, select `provider_only_multi_object_binding`
before the paid call. The same rule covers one to nine independently indexed people,
products, Apps, scenes, garments, jewelry, and accessories, subject to the Provider's
nine-image request limit. Bind independent single-object assets in continuous
@Image1..N order; one multi-angle board may describe one object, while a group portrait,
mixed-product sheet, binding board, or source-control sheet is not a target asset. Use
opening-frame or first-appearance calibration from source position, visible traits,
wardrobe/prop/contact evidence, and entry time, then attach each mapping to the same
continuing physical track. Compile compact positive state declarations and keep
`imageUrls[N-1] == @ImageN` as an audited invariant. The image controls the target
appearance; text states only the approved replacement and preservation scopes. Every
person binding must declare exactly one evidence-conditioned policy:
`identity_and_wardrobe_from_reference` when the target image visibly supplies clothing,
or `identity_from_reference_preserve_source_wardrobe` with a named source garment when
`target_wardrobe_evidence=absent`. These policies apply identically to one, two, four,
five, six, or any other supported person count; they never apply to non-person assets.
Product, App, scene, garment, jewelry, and accessory bindings retain their type-specific
geometry, contact, screen-plane, perspective, lighting, shadow, occlusion, and
interaction rules. Missing evidence, conflicting wardrobe scope, discontinuous indices,
or a missing/stale `provider-only-multi-object-binding/v1` receipt fails before the paid
call with `SOURCE_OBJECT_BINDING_REQUIRED`; the runtime never falls back to a vague
prompt. Deliver the direct Provider MP4 with no local video processing. Provider SUCCESS
is not visual acceptance; object-level human QC is still required. See
`references/provider-only-multi-subject-binding.md`.

Operational action adaptation is a product/App-only execution layer. A replacement row
uses `adapt_action` only when a product or App must perform an approved use, operation,
interaction, or visible-result sequence. Pure visual replacements use `direct_binding`:
person, scene, and garment bindings, including background and clothing changes, continue
through the existing compact binding route without action adaptation. The compact
compiler must retain every approved time-window action exactly once. This layer must not
read, rewrite, reorder, regenerate, or change the weight of any person binding or person
Prompt line.

Before compiling any person binding, require profile
`model-identity-v3-local-crop`, MIME `image/png`, dimensions `1024 x 1024`, one
identity subject, layout `identity_dominant`, and composition
`close_portrait_square`, `upper_body_square`, or `full_body_square`. Face or upper-
wardrobe work uses the first two; complete visible wardrobe replacement uses
`full_body_square` while preserving usable face detail. A missing or mismatched person
asset contract fails with `PERSON_ASSET_FORMAT_REQUIRED`. This rule is person-only and
does not change product, App, scene, garment, jewelry, or accessory asset formats.

Use neutral marketing language such as visual appeal, friendly presence,
professional presence, person state, and composition focus. Other attractiveness
labels fail closed. Preserve a private, server-side artifact authority
chain and fail closed on stale, foreign, or missing evidence.

## Document ownership and legacy quarantine

This file owns workflow; `references/fixed-input-slot-contract.md` owns intake
schema; and `references/universal-source-fidelity-contract.md` owns shared
fidelity/routing rules. The bundled storyboard package is legacy quarantine
only, not a `video-edit-v2` owner. Compatibility code remains for regression,
but it is not reachable from `video-edit-v2`. Legacy storyboard, prompt-
invocation, high-fidelity, and UI-sidecar material is quarantine-only and must
never become a fallback route.

Performance configuration remains deployment-owned: `USFR_FFMPEG_ENCODER`
defaults to `libx264` and may select `h264_nvenc`; `USFR_FFMPEG_THREADS`
limits encoder threads.
