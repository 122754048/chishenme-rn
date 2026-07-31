---
name: seedance-storyboard-replication
description: Use when a user needs storyboard and Seedance execution for an approved source-video replication across physical products, Apps/digital products, services, brands, or no-product formats, including opaque or generated UI routes.
---

# Seedance Storyboard Replication

Turn an approved source-video contract into model-generated storyboards and a
RunningHub Standard Model Seedance 2.0 Fast task for each generated region. The skill is universal across
physical products, Apps/digital products, services, brands, and no-product
formats; source camera style and content type come from the contract. It owns
route selection, approval gates, prompt assembly, RunningHub media upload,
Seedance submission, timeline assembly, and final QC.

## Fixed user surface

This module inherits the root two-artifact user contract. Do not invoke
`brainstorming`, create or request approval of a design document, present
multiple processing approaches, or pause for a scope/plan/technical decision.
The first user pause is the downloadable `user_script_markdown` file at
`analysis/reverse_storyboard_script.md`. Pasting
the script inline in chat is not a valid script-approval artifact. The second
user pause is the actual `image/png` director storyboard image set at
`storyboards/segment_XX_vN.png`. A text-only
storyboard description is not a valid storyboard-approval artifact.

The replacement-control sheet is internal-only and must never be presented, linked, previewed, or bundled in the user approval response. The second gate publishes only the ordered director-board PNG page set. The approval set supports at most two director-board PNG pages, and a page may contain at most four Cut cards. When a Segment has five to eight Cuts, paginate it into exactly two contiguous pages before Image2. All pages for the current storyboard revision form one ordered approval set and receive one confirmation together. Board pages do not create extra approvals or additional Seedance tasks.

A director-board page may contain at most four Cut cards.

No scope, approach, design, plan, duration, split, reference-allocation, prompt, generation, or QC confirmation is permitted. Non-blocking progress
updates may request no reply. Lyrics, performer assignment, duration and split
decisions, and reference allocation must be exposed inside the script document
or director board as applicable, never as another question. After the director
board is approved, compilation, upload, submission, waiting, assembly, and QC
continue automatically.

## Route Selection

The top-level binder has already frozen the seven fixed input slots. The slot
position is authoritative; this module must not classify uploaded files by
filename, pixels, OCR, or model judgment. A formal run exists only when
`source_video` is valid and at least one of the six optional slots is valid.
Source-only input is rejected with `MIN_ONE_OPTIONAL_INPUT_REQUIRED`.
Reject a source longer than 30 seconds with `INPUT_SOURCE_TOO_LONG` and HTTP
422 before creating a formal run, analysis artifact, Image Gen request, or
provider intent.

- **路线一：已有内部批准脚本**: a resumed run contains the existing approved
  script and storyboard artifact. The approved script is immutable text/timing/
  claim/audio authority; the board is visual evidence and cannot replace or
  override it. Do not ask for script approval again.
- **路线二：固定槽位源视频**: the manifest contains the source video plus at
  least one optional slot. Reverse-engineer the source video and stop for
  **确认反解分镜脚本** before storyboard generation.

Both routes support at most nine images and enforce
`continuous-present-role-order/v1`. @Image1 is the new model identity when a
model replacement is populated; product or App truth follows the model
identity when populated; approved director storyboard PNG pages follow the
populated target-truth images; and additional verified references follow only
with an explicit purpose and Cut scope. Absent logical roles do not create
placeholder images: later present roles compact left and the actual index/tag
is frozen in the binding manifest. Record the allocation inside existing
artifacts; never create a separate reference-allocation confirmation.

Every approved storyboard page is uploaded as its original confirmed PNG. The
workflow must not generate, merge, crop, or substitute an execution carrier.
`seedance_execution_carrier.png` is forbidden. A single `storyboard_url` is
invalid. The exact invariant is
`uploaded_tags == binding_tags == prompt_tags`. @Video1 is a video-slot
reference and never consumes an image index. @Audio1 is an audio-slot reference
and never consumes an image index.

Both routes use the **固定 B 方案**. For every source-fidelity generated region,
the mandatory visual chain is **source Cut frames → replacement-control sheet →
approved director board**. The source frames establish the original scene,
background, camera, lighting, composition, and Cut order; the control sheet
replaces only authorized target layers; the director board is generated from
that control sheet plus fixed-slot targets. After storyboard approval retain the
source evidence as server-side, verified tenant-private object storage.

The control transformation is exactly **one complete source Cut contact sheet → one RunningHub Image2 call → one complete replacement-control sheet**. Per-Cut replacement generation and per-Cut source-frame validation are forbidden during control creation. Local face swap, ComfyUI, InsightFace, desktop image editors, and any non-Image2 generator are forbidden. A fixed-slot target image is target truth only and must never be accepted as the replacement-control sheet. The result must be a distinct Image2-generated PNG whose receipt records `single_sheet_image_to_image` and `image2_call_count=1`.

After that one internal control transformation, paginate the director-board publication independently of Segment/task planning. Keep global Cut order and use at most two pages with at most four Cut cards per page; seven portrait Cuts require a 3+4 split. On a four-Cut 9:16 page, use four equal-width full-height portrait cards in one row, with proportional fit-contain scaling. Empty card margins are acceptable; crop-to-fill, horizontal compression, vertical stretching, and body-proportion changes are forbidden. Cut scene images must remain large enough to judge face identity, pose, hands, microphone/product/prop relations, action endpoint and composition. A page with squeezed or distorted people, cropped required evidence, unreadable actions, or less visual evidence than its source Cut fails publication and must be regenerated.

Cut scene images must preserve the source portrait-frame aspect ratio without horizontal or vertical stretching. Proportional fit-contain scaling is the required four-Cut portrait-page operation.

For that single Image2 call, reference image 1 is the complete source contact
sheet and controls every non-replacement property. The prompt names each later
reference from the fixed manifest and limits it to its authorized model,
product, or App-product replacement layer. Pose, action, gesture, facial
expression, gaze, mouth state, head/body angle, wardrobe unless explicitly
authorized, hands, product interaction, camera, crop, subject scale/position,
background, lighting, props, occlusion, panel count/order, and continuity must
remain unchanged. The director-board Image2 request must use the
replacement-control sheet as reference image 1; fixed-slot targets follow only
as identity/product truth and cannot override the control sheet.

Every source-fidelity generated Seedance request uploads exactly the matching
2-15 second original source segment at `videoUrls[0]` plus the ordered image set
from `usfr-multimodal-reference-binding/v2`.
Its `usfr-video-reference/v1` receipt binds source-video/source-slice SHA-256,
segment ID/time window, the approved board, and at least one authorized target
change. Source keyframe sheets and replacement-control sheets are upstream-only
director-board evidence: they must never be sent to Seedance or occupy an
`@Image` slot in the final request. Route confirmed visible text by carrier.
**Scene-surface text** on paper, packaging, clothing, signs, or physical props
must be generated into the replacement-control sheet and director board with
exact wording, carrier ID, surface relation, placement, and style. It moves,
bends, folds, rotates, occludes, and tears with its carrier. The exact wording
and physical behavior must be written explicitly into the Seedance Cut prompt.
**Deterministic overlay text** such as subtitles, captions, CTAs, headlines, or
lower-thirds is rendered before approval and in final post; Seedance must not
generate, read, or transcribe those overlay glyphs. The full source video must never be uploaded. Opaque
UI-operation media and tail media remain forbidden. The exact fixed-B payload uses `generateAudio=true`; legacy
`reference_videos` is forbidden, there is no legacy `reference_audios` field,
and implicit audio references are forbidden. The approved
`background_music` extension is the sole exception: upload one
duration-bounded fragment as `audioUrls[0]` and require `@Audio1` in the
compiled prompt.

Reference order is the actual continuous provider image order frozen by the
binding sidecar; source Cut/keyframe sheets and replacement-control sheets must
never be sent to Seedance.
This rule also applies to Route 1 even when the user supplied an approved script
together with a reference video.

Both routes consume the frozen `Source Fidelity Contract`. Preserve source scene
graph, props, camera, atomic action graph, speech/delivery,
ambience/Foley/transition audio, overlays, selling-point logic, continuity,
evidence, uncertainty, criticality, and generation route. Explicitly label
`observed`, `inferred`, and `planned` values. Use Level 0 pixel/material,
Level 1 structure/performance (default), or Level 2 intent fidelity; Level 2 is
`REINTERPRET`, never a claim of complete replication.

## App Region Routing and Opaque Media

Read `references/timeline-slice-contract.md` before handling App intervals.
Source-video dynamics locate the intervals; the fixed manifest chooses the
media route. Use `media_origin` and `assembly_policy` to distinguish a
supplied opaque replacement from a source interval preserved server-side through
verified tenant-private object storage or a lease-owned temporary volume.

- `excluded_app_end_card` is a terminal brand/download-only interval. A supplied
  tail video is opaque replacement media: use `trim_to_active_content` to remove
  only leading/trailing black padding from video and audio together, preserve
  its internal pixels/audio/animation, reset timestamps without speed change,
  apply the source entry transition exactly once, and make the last active tail
  frame the final output endpoint. No final-frame padding, loop, freeze, black
  filler, or atempo is allowed. Recalculate source-to-output mapping from the
  effective duration and never register/send it to Image Gen or Seedance. Omit
  it from the text script, every storyboard, the Seedance prompt/assets,
  selling-point mapping, and paid generation duration. If missing, use
  `omit_source_end_card` and remove the source tail interval from final assembly;
  do not render the removed tail's entry transition or add replacement filler.
  Full-black media or a missing active interval blocks; preserve and report
  internal black intervals. A transition render receipt must bind the rendered
  entry result to the exact source-shell SHA-256 and current final MP4 SHA-256;
  stale receipts and metadata alone are not proof.
- `opaque_ui_demo` is interactive UI with a supplied target UI video. Remove
  source UI pixels and splice the target video under the source
  `transition_shell`. Trim only leading/trailing black padding from video and
  audio together, reset timestamps without changing playback rate, preserve its active-content duration
  and all retained internal pixels/audio/animation, and recalculate the source-to-output mapping
  plus every downstream timestamp
  from the effective duration. Use no final-frame padding, no audio padding,
  no atempo, loop, freeze, time stretch, OCR, redraw, or semantic inspection.
  Block if opaque media is missing, has no active content, or lacks the required
  transition evidence. Preserve every internal UI operation and internal black
  interval; never trim the middle of the demonstration. Entry and exit each
  require a transition render receipt bound to the exact source-shell SHA-256
  and current final MP4 SHA-256.
  Resolve display rotation metadata and use
  display dimensions before choosing the normalization canvas. A centered cover
  crop is allowed only within the 12% safe cover-crop limit; a larger crop or
  visible black padding blocks the run.
  Opaque replacement audio defaults to `audio_policy=opaque_audio_keep` and
  must not silently overwrite source voiceover. A target UI/tail file with no
  audio may opt into `audio_policy=silence_allowed`, which injects only a
  bounded silent track and records it in the splice manifest. Source-voiceover
  preservation with target audio uses `audio_policy=evidence_bound_mix` only
  through the bundled immutable mixer; missing target audio, invalid frozen
  speech windows, stale lineage, or an incapable renderer fails closed.
- Semantic overlay replacement remains a separate evidence lane. Freeze the
  source `source_overlay_contract` and a target `overlay_render_mapping` before
  assembly; if a semantic overlay is declared but no validated mapping exists,
  fail closed with `OVERLAY_RENDER_MAPPING_REQUIRED`. Source transition shells
  remain authoritative (including `xfade=transition=dissolve` and any
  alpha-ramped overlay); technical A/V QC never substitutes for semantic
  overlay QC and must not silently drop a headline, subtitle, logo/wordmark, or
  CTA layer. Active production additionally requires
  `overlay_render_receipts` for every mapped region/overlay, bound to the
  source-contract SHA, mapping SHA, payload SHA, frame windows, and final
  output SHA; a copy-only renderer fails with `OVERLAY_RENDER_RECEIPT_REQUIRED`.
  The server builds this mapping with
  `server.overlay_mapping.build_overlay_render_mapping`, copying source
  geometry/timing/keyframes exactly. Readable text is allowed only for source
  wordmarks/subtitles/CTAs; brand marks and graphics require an immutable target
  asset SHA. `server.overlay_renderer.DeterministicOverlayRenderer` is the
  default deterministic text/asset layer pass for source-origin-only
  timelines; it is not a complete timeline renderer and cannot assemble
  generated or opaque regions.
- In active/production, any timeline region whose `media_origin` is not
  `source_interval` requires the deployment's injected complete timeline
  renderer. A missing renderer fails closed with
  `compositor timeline renderer is not configured for non-source regions`.
  An injected renderer marked `capability_kind=overlay_renderer` is treated
  the same way and cannot carry a non-source region.
  Never invoke the semantic overlay pass over `source_video` as a substitute
  for generated, opaque, or elastic timeline assembly.
- **UI-only frame-locked rebuild:** `opaque_ui_demo always wins`; a supplied
  UI operation video remains opaque and retains its source transition shell.
  Without that video, a detected source UI Cut may route to
  `generated_ui_demo` for target UI evidence, an authorized
  `new_product_image`/`new_model_image` replacement, or visible UI language
  localization. It carries `source-ui-interaction/v1`, which freezes exact
  source time/frame windows, viewport, target language, and the supported
  `drag`, `scroll`, `bounce`, `scale`, `rotate`, `opacity`, and `tap` motion
  classes. Motion is `ui_roi_only` and `source_frame_locked`; the renderer must
  preserve source-frame timing and the source transition shell.
- Target screenshots/App evidence stay preferred. Product/model evidence may
  bind the replacement object only; it cannot authorize invented readable UI
  copy. The target truth card and page/state/layout contract must carry all
  rendered text. Preserve source UI language unless `output_language` is set,
  then localize visible UI text to that language using UTF-8 with replacement
  glyphs forbidden. Any garbled or unverified text blocks the UI interval.
  Validation is basic-anchor-only, with no automatic retry and no full-video
  deep analysis.
- `generated_ui_demo` never enters Seedance, Image Gen, scripts, or
  storyboards. When the source has no UI Cut, skip UI ROI analysis, redraw, and
  UI QC entirely. The ordinary non-UI route is unchanged.
- `generated_ui_demo` requires target-owned evidence, `ui_truth_card.json`, and
  `ui_render_contract.json`; prefer deterministic rendering/compositing. The
  truth card is immutable evidence from the uploaded screenshot or parsed
  official App evidence; the renderer may consume/echo it but cannot author or
  mutate it. OCR/layout must match 100% at every declared state and at
  independently sampled state-to-state animation frames; replacement/mojibake
  glyphs, unreadable transition text, out-of-viewport geometry, pseudo-text,
  wrong layout/state, or unsupported copy blocks the run.
  `ui_qc_report` must bind the media SHA-256, `ui_truth_card_sha256`,
  `ui_render_contract_sha256`, `ocr_match_percent=100`,
  `layout_match_percent=100`, immutable truth provenance,
  `animation_interval_evidence`, `animation_ocr_match_percent=100`,
  `animation_layout_match_percent=100`, and non-empty OCR/layout frame
  evidence. When
  `ui_truth_card.states` is present, `ui_qc_report.state_evidence` must contain
  exactly one row for every state. Each row binds the state id and frame time,
  the exact truth-state digest, the decoded RGB24 frame SHA, and OCR/layout
  record digests whose input SHA equals that decoded frame. The compositor
  recomputes every state and animation-frame SHA from the actual media; a
  container/media hash, renderer-authored truth, or self-reported 100% score
  cannot substitute for this check.
- `source_ui_keep` is interactive UI when all three UI slots are absent. Keep
  the source interval server-side through verified tenant-private object
  storage or a lease-owned temporary volume, with no OCR, redraw, retime, or
  provider upload.

If authoritative routing produces zero generated regions, take the existing
local-only branch. Create no reverse script, no storyboard, no Image Gen
request, no Seedance-20 Invocation A or B, no CreateAsset, no CreateVideo, and
no creative approval. Continue only with region-boundary planning,
deterministic source/opaque assembly, transition rendering, and technical QC.

Only ordinary regions affected by a populated replacement slot enter semantic
scripts, storyboards, and paid generation. The generated UI remains in the
deterministic UI renderer/timeline lane: `generated_ui_demo` itself is omitted
from the semantic script, every storyboard, Image Gen, the Seedance prompt and
assets, and paid generation duration, just like `opaque_ui_demo` and
`excluded_app_end_card`/`omit_source_end_card`. If a surrounding person, hand,
device shell, or camera plate must be generated, route that shell as a separate
ordinary generated region and composite the verified UI pixels afterward; the
UI route and its truth/render/QC payloads never enter Seedance semantics. Any
unaffected ordinary Cut is a source-origin KEEP interval.
Plan each contiguous generated region independently with
global timecodes and the fixed 4–15 second task limits. Opaque and source-origin
intervals never count toward generated duration, storyboard count, or Seedance
task count. Keep at most two boards/tasks total. If routing would create more
than two generated regions, or a region would require more tasks than remain,
stop with a blocker. After generation, write paths into `analysis/timeline_regions.json`,
run `scripts/timeline_splice.py`, save `timeline_splice_manifest.json`, and
verify source-to-output placement. Opaque and source-origin media remain local
only as server-side object-store-backed or lease-materialized media and are
never legacy provider assets or client-workstation dependencies.

## Evidence and Analysis Routing

Use the smallest necessary upstream analysis and cache every result in the current run directory:

- When the user supplies an Apple App Store or Google Play URL and no valid bundle exists, use `$parse-app-store-evidence` once. Store its bundle and official media under `app_store/`. Reuse a valid bundle for every later stage; never fetch the same page again in the same run.
- Derive at most five concise product feature/selling-point bullets from the verified App name, metadata, and official screenshots. Do not infer claims from the icon or URL, and do not perform extra browsing when the evidence bundle is sufficient.
- For Route 2, use `$analyze-reference-video-dynamics` once before writing the reverse script. Reuse its probe, scene candidates, Cut boundaries, action/camera phases, and event timing instead of repeating free-form video analysis.
- Use `$replicate-source-ui-overlays` only when the source contains a visible moving or timed Logo, UI, subtitle, CTA, wordmark, or graphic layer whose geometry must be preserved. Skip it when no such overlay exists or when overlay placement is irrelevant to the approved replacement. Do not run semantic overlay analysis inside `opaque_ui_demo` or supplied `excluded_app_end_card`; retain only their source boundaries and transition shells.
- Overlay analysis preserves source timing and geometry only. Replacement pixels must come from the verified product evidence, never from the source-video brand.
- Derived source contact sheets and boundary frames may carry structure,
  timing, camera, environment, and approved scene-surface text evidence. Source
  identity, unauthorized brand/UI, and deterministic overlay text must not leak
  into a replacement storyboard or the fixed-B provider asset map.
- Before Route 2 reverse-writing, run one concise intent pass and save `analysis/intent_weighted_contract.json`. Read `references/intent-analysis.md` for the schema. The pass must identify the source video's primary commercial intent, audience hook, character appeal, product proof, emotional promise, CTA/conversion role, pacing role, and platform-safety boundary, then assign integer weights totaling 100. Reuse this cached contract; do not repeatedly speculate about intent during every Cut.
- Intent weights are constraints on the reverse script, not decoration. The weighted categories must be reflected in the script's opening hook, action emphasis, product/UI evidence, voiceover, CTA, and negative constraints. If a source uses an attractive adult model or mild body movement to stop the scroll, describe it neutrally as an adult-attractiveness/attention hook and preserve only non-explicit, platform-compliant framing: no nudity, exposed intimate areas, fetish focus, coercion, or sexual acts. Do not infer sexual intent from appearance alone; require framing, movement, copy, or repeated emphasis as evidence.

Time budget: one deterministic parser/probe pass per input, one concise semantic pass over selected boundary/key frames, and no repeated full-video inspection unless validation fails. Prefer cached contracts and omit optional analysis that cannot change the storyboard or final prompt.

Immediately after upload, validate duration internally before creative work.
Record the resulting duration/split decision in the downloadable script file;
an optional progress update must remain non-blocking and request no reply:

- **参考视频最长 30 秒**. Reject anything longer and ask the user to trim it before reverse engineering.
- **15 秒以内最稳定**: one storyboard and one Seedance generation avoid cross-task identity and motion drift.
- `>15s` through `17s`: retime to one 15-second storyboard/task under the approved threshold rule.
- **18-30 秒**: exactly two independently submitted but continuity-locked clips, therefore **最多两张故事板**. Record the boundary limitation and continuity handoff in the script document instead of asking for a separate confirmation. A 30-second source must have a natural handoff at 15 seconds.

## Route 1: Existing Storyboard Script

Use this route when the user already uploaded or pasted a confirmed storyboard script.

1. Validate the reference-video duration internally.
2. Materialize the supplied script as the downloadable
   `user_script_markdown` artifact and stop once for **确认反解分镜脚本**. The
   user must receive the file, not an inline transcription.
3. Analyze the approved script's action completions, spoken-sentence endings,
   story beats, and scene transitions. For more than 17 seconds, select one
   explicit **剧情切点** in the legal range and pass it to
   `scripts/segment_plan.py --split-boundary`; 禁止为了均衡时长自动选择.
4. If no approved Cut boundary is safe, return the issue inside the existing
   script-file revision gate; do not create a separate boundary approval.
   Never hard-cut or create a third segment.
5. Read `references/daohuo_storyboard_prompt.md`. Write
   `continuity_manifest.json`, then run `scripts/runninghub_image2.py` once per
   planned segment to generate `storyboards/segment_01_v1.png` and, only when
   required, `storyboards/segment_02_v1.png`.
6. Stop once for **确认故事板** with the actual PNG image set. When two segments
   exist, generate and automatically continuity-check the complete pair before
   showing either board to the user. Show the pair together as one
   storyboard-set revision and one user confirmation.
7. If the user requests changes, revise only the affected board. A change to
   segment 1 regenerates and rechecks segment 2 because its incoming state
   depends on segment 1; a change isolated to segment 2 does not regenerate
   segment 1. Return the repaired set to the same storyboard confirmation.
8. Only after storyboard approval, compile one complete Seedance prompt per
   segment through `seedance-20`, then run the internal Seedance Integrity Gate
   before any API submission.

## Route 2: Fixed-Slot Source Video

Use this route when the fixed manifest has a valid source video and at least one
valid optional slot. Populated product/model/UI slots become target truth;
absent slots remain source-preserve KEEP evidence.

1. Validate the reference-video duration and give the duration guidance above. Run or reuse the cached `$analyze-reference-video-dynamics` contract.
2. If the dynamics contract reports meaningful timed overlays, run or reuse `$replicate-source-ui-overlays`; otherwise explicitly record that overlay analysis was skipped.
3. Read `references/fukeGem.md` and reverse-engineer the source video into the
   requested Chinese storyboard script using the cached dynamics, optional
   overlay contract, and only the populated fixed-slot evidence. Keep absent
   character/product/UI truth on the source-preserve route.
4. Write `analysis/intent_weighted_contract.json` from the source evidence, then apply its weighted intent to the reverse script. The script must state the primary intent, weight table, evidence, and which Cuts carry each high-weight intent. Do not add a new character or claim that the source does not support.
5. Publish the real `user_script_markdown` file and stop only for
   **确认反解分镜脚本**. Present a file link; do not paste the document inline
   as a substitute. Do not generate storyboard images yet.
6. After script approval, select and validate an existing approved Cut boundary with `scripts/segment_plan.py --split-boundary`; 禁止为了均衡时长自动选择. If no approved boundary is safe, stop with a blocker requiring storyboard-script revision or approval.
7. Read `references/daohuo_storyboard_prompt.md`. Write `continuity_manifest.json`, then run `scripts/runninghub_image2.py` once per planned segment to generate one or exactly two `16:9 横版电影制作板` images.
8. Stop once for **确认故事板** only after the actual PNG director board or
   complete PNG set exists. For two segments, first generate both boards, make
   segment 2 consume segment 1 plus the frozen continuity locks, and complete
   automatic pair QA. Show every PNG together as one storyboard-set revision;
   a text description is not a review artifact. Revise with
   `scripts/runninghub_image2.py` until the user approves the set-wide
   continuity through this one confirmation entry.
9. Only after all storyboard approvals, compile one complete Seedance prompt per segment through `seedance-20`, then run the internal Seedance Integrity Gate before any API submission.

## Storyboard Approval Loop

The storyboard is the main user-facing quality gate.

- Use `references/daohuo_storyboard_prompt.md` as the only storyboard prompt and layout source. Reading and compiling this exact file is a mandatory runtime dependency for every generation and revision, not optional guidance. Follow its **固定骨架 + 动态填充** contract: keep the layout and constraints fixed, replace every placeholder with the current approved script, character, product, reference-video role, and exact short labels, reject unresolved placeholders, and bind the file's exact byte SHA-256 into the Image2 request, layout receipt, storyboard metadata, and approval artifact. Missing bytes/SHA, an embedded fallback prompt, the obsolete five-region information board, or any alternate template fails closed. Never maintain, remember, or improvise a second generic storyboard prompt.
- Keep the two visual artifacts strictly separate. `reference_frames/control_keyframes.png` is an internal replication-control sheet with exactly one ordered panel for every source Cut. Its panel count and Cut ID order must equal `source_dynamics_analysis.source_cuts`; no fixed panel count, range, or grid size is allowed. It may be supplied only to the upstream Image2 director-board call, but it must never be shown to the user as the director storyboard, be used as the board layout, or be uploaded to Seedance. The user-facing deliverables are the image-model-generated 16:9 director-board PNG pages defined by `daohuo_storyboard_prompt.md`; their final `@ImageN` values come only from the ordered multimodal binding.
- Before the control-keyframe image2 call, build and validate `reference_frames/control_keyframes_manifest.json` using `scripts/control_keyframe_contract.py`. The validation receipt must prove that every source Cut appears once, in source order, and that no legacy fixed-panel rule is present. The control sheet only locks replacement identity, camera, action, expression, and environment; it never replaces the approved script or director storyboard.
- Before an image2 call, reject the prompt as `DIRECTOR_STORYBOARD_LAYOUT_REQUIRED` unless it has the template's director-board structure: shared top direction, character/style and detail reference area, ordered Cut-card storyboard area, environment/camera movement plan, and concise bottom lighting/camera/palette/audio/mood/cinematography notes. A generic equal-cell contact sheet, a bare control-keyframe grid, blank Cut placeholders, or a post-generated collage of source UI screenshots is not a director storyboard and must not be presented for approval.
- Use the RunningHub `gpt-image-2/image-to-image-official-stable` actual image-generation model through `scripts/runninghub_image2.py` for storyboard generation and targeted revisions. The Cut scene images must be model-generated visualizations, not a deterministic collage of source photos and screenshots.
- Read `references/runninghub-image2-api.md` before the first storyboard call. Pass the filled prompt with `--prompt-file`, and pass only the necessary 1-10 character, product, contact-sheet, or adjacent-board references with repeated `--reference-image`. Keep the defaults `16:9`, `2k`, and `medium` unless the user explicitly approves a quality change.
- A preview embedded only in the chat is not a storyboard artifact. The call is complete only when `storyboards/segment_XX_vN.png`, its matching `.meta.json`, `image2.request.redacted.json`, `image2.task_id.txt`, and `image2.status.json` exist in the run directory and the PNG is visually inspected at original resolution.
- RunningHub credentials come from worker-injected environment variables or an
  explicit deployment `--env-file`/`SEEDANCE_ENV_FILE`; `~/.codex/secrets` is a
  development adapter only. Never put a key in a command, prompt, saved
  request, log, or skill file. Do not automatically retry a failed or ambiguous
  image2 submit because it may create a duplicate paid task; resume a known
  task with `--resume-task-id`.
- Never substitute PIL, ImageMagick, FFmpeg, HTML, canvas, or other deterministic layout code for storyboard scene generation. Deterministic tools may only assemble a product board from unchanged product pixels or add clean typography after model generation.
- If the image-generation tool is unavailable, cannot accept the required references, or does not return an accessible artifact, stop and report the blocker. Do not silently create a collage or label it as a generated storyboard.
- Generate the user-facing `16:9 横版电影制作板` from the complete approved final timeline, not from planned provider segments and never as separate images per Cut. When the final timeline is 15 seconds or less, it is exactly one `SEGMENT 1/1` board containing every included Cut in global order. Each board must include character/style reference, person detail close-ups, applicable product or App reference, environment/movement plan, all ordered storyboard frames, lighting/mood notes, audio/tone notes, and cinematography notes.
- Keep global Cut numbers, final-timeline timecodes, and shared identity/product/environment locks on the complete director board. Internal Seedance segments inherit the approved board and their exact textual Cut instructions after approval; they do not create a partial user-facing storyboard.
- `continuity_manifest.json` must record `character_identity_lock`, `wardrobe_lock`, `product_interaction_lock`, `segment_01_final_state`, and `segment_02_opening_state`, plus character pose/expression/outfit, product location/orientation/open state, prop positions, environment, light direction, screen direction, camera state, outgoing action, incoming action, voiceover handoff, environment sound, and boundary frame intent.
- 故事板图片只承载视觉参考和重要事项。Each Cut card may show only its Cut number, time range, one short key action, and one critical identity/product constraint. Do not typeset the full script, long voiceover, or dense production notes into the generated image.
- Treat the approved script as the source of truth. 完整分镜脚本必须作为文本写入 Seedance prompt, including every Cut's script description, camera/action direction, voiceover, sound, continuity, and negative constraints.
- 不要让 Seedance 从故事板图片中识别完整脚本. The storyboard image is a visual reference, not a text transport. If image2 deforms a short label, remove it or add it later with deterministic typography; never preserve garbled text for submission.
- Preserve the confirmed Cut order. Do not invent shots, reorder Cuts, or turn product scenes into unrelated lifestyle scenes.
- Product fidelity matters more than visual novelty. Product boards must preserve the user's original product pixels rather than AI-redrawing the product.
- Every Cut card must visualize that Cut's approved camera angle and physical action. Do not repeat the same uncropped source portrait across different action Cuts, and do not use a character reference photo itself as the finished scene image.
- When a Cut calls for both the replacement character and replacement product, show both in the generated Cut scene with the approved spatial relationship. A separate character panel plus a separate product panel does not satisfy this requirement.
- Show the intended subject extent for each Cut. Full-page UI and end-card Cuts must display the complete vertical page inside the card; person/product Cuts must not accidentally crop away required head, hands, body action, phone, package, Logo, or product body.
- The preceding UI/end-card storyboard rule applies only when those Cuts are being generated. `opaque_ui_demo` and `excluded_app_end_card` intervals must not appear as generated storyboard Cut cards at all.
- Before asking for approval, visually inspect the exported board at original resolution and compare every Cut against the approved script. Reject and regenerate the board if any Cut is duplicated, half-visible, unrelated, missing the new person/product, or merely reuses a source asset without scene synthesis.
- Save `storyboards/segment_XX_vN.meta.json` beside every generated board. Record `generator_kind: image_model`, the tool/model name when available, prompt path, reference inputs, output dimensions, generation duration, and revision reason. Missing or false generator provenance invalidates the board.
- Do not ask for approval after the first board of a two-board set. Generate both boards, check the pair's identity, wardrobe, product interaction, screen direction, and boundary handoff, then ask for the existing single storyboard approval. A changed first-segment boundary invalidates and regenerates both boards; an isolated second-segment correction regenerates only the second board.

## Image Allocation Gate

Before calling Seedance, compile one ordered image-role manifest and its
`usfr-multimodal-reference-binding/v2` sidecar. The actual provider array is
continuous and contains one to nine images: present model identity first,
present product/App truth second, every original approved director-board page
next, then only explicitly scoped additional references. Each descriptor binds
the exact URL, SHA-256, artifact name, `@ImageN`, role, Cut IDs, purpose, and
storyboard page/approval-set data where applicable. Duplicate indices, tags,
URLs, SHA values, page numbers, or overlapping storyboard Cut scopes fail
closed. Uploads without Prompt use and Prompt tags without uploads also fail.

Never send a whole-video storyboard to both tasks. Keep the full reference
video in verified tenant-private object storage or a lease-owned server-side
temporary volume; it remains the source-analysis master and must never be
uploaded to Seedance. For each generated task, upload its exact current 2-15
second matching original source segment at `videoUrls[0]` and the complete
ordered image set. Source Cut/keyframe sheets and replacement-control sheets
must never be sent to Seedance.

## Seedance Internal Integrity Gate

Both Route 1 and Route 2 must pass the internal Seedance Integrity Gate after the latest storyboard approval; normal submission needs no user confirmation.

The external installed `seedance-20` skill is mandatory for this compile/audit
step and is not vendored by this bundled module. If it is unavailable, stop
before any paid request.

1. Compile through `seedance-20`, preserving the complete approved Cuts, one-to-nine-image binding, fixed-B payload, and all negative constraints.
2. Build the exact final payload and run `scripts/runninghub_seedance_submit.py --dry-run` once as the pre-submit preview; do not create a paid task at this step.
3. Run the `seedance-20` script-to-prompt parity audit against that exact dry-run request and write the required audit JSON artifact (`auditor`, `status`, exact request/prompt digests, approved script digest, compiler provenance, contract digests, factor coverage, zero ambiguities, and every required check in `references/seedance-20-integrity-gate.md`).
4. Submit only the exact audited payload with `--approved-request-sha256 <digest>` matching the saved dry-run request SHA-256; audit, script, and contract artifacts remain server-side integrity evidence.
5. The Factory executor owns two-segment concurrency: it starts both independent single-task CLI invocations before waiting for either. Preserve ordering where segment 2 requires segment 1 pixels; dependency-locked segment 2 remains sequential.
6. Upload only the required storyboard/target/audio references to the RunningHub Standard Model account, poll known task IDs statefully and without a deadline, and never create duplicate paid tasks.
7. Finalize and deliver only `final/result.mp4`; successful delivery contains no extra artifacts.
8. Unsafe asset changes, a failed parity audit, digest mutation, or a duplicate paid retry remain blockers. Resume known tasks instead of creating duplicate paid tasks.

## Universal selling-point mapping

Save `selling_point_mapping.json` before storyboard generation. Every target
claim is a `Feature → Mechanism → Benefit → Proof → CTA` chain tied to source
evidence, target evidence, Cut/time range, confidence, criticality, and route.
If a target cannot prove the source claim, mark it `unsupported`, lower it, or
remove it. Never invent a mechanism, result, review, statistic, certification,
or guarantee to fill the original position.

## Seedance input freeze and integrity contract

After the latest storyboard approval, freeze `seedance_input_contract.json`.
Recompile the final prompt through `seedance-20` and build exactly one dry-run
payload for each prompt version. Compare the approved Cut order, character lock,
product lock, duration and timecodes, voiceover and audio, camera/actions/
transitions, continuity, selling-point evidence, timeline-region routing,
reference mapping, provider parameters, and negative constraints. Require zero
ambiguity and no unresolved placeholders.

Only then enter **internal request integrity approval** and submit the unchanged
digest. This is not a third user approval gate. Prompt-only repair does not ask
the user again; a change to an approved script, storyboard, asset, or route
returns only to the existing relevant approval gate. A failed parity check,
digest mutation, unsafe asset change, or duplicate paid retry is a blocker.

### Audited Factory closure

The audited dry run stores the approved-script digest, the eight contract
digests, the exact unique 13-check list, and the non-empty unique
`required_factor_ids` list as server-side integrity evidence. The ledger
factor-ID set must equal that frozen list exactly. The audit stores the raw-byte
`seedance_input_contract_sha256` and validates it before any provider call.

The installed root `seedance-20/SKILL.md` is required before the paid path. Its
frontmatter must name `seedance-20`; its exact-byte SHA-256 and metadata version
must match compiler provenance. The audited payload is strictly RunningHub
Standard Model fixed-B plus the approved `background_music` extension when supplied:
`seedance-2.0-fast-token`, `720p`, `9:16`, duration 4–15, `generateAudio=true`,
and documented direct image/audio/video URL fields: at most one exact `audioUrls`
item carrying `@Audio1`, one exact matching original source segment at
`videoUrls[0]` under `usfr-video-reference/v1`, and the approved director board
    with the complete ordered image-binding digest. It enables `realPersonMode` and has a non-empty target change
receipt. It must not upload the source-keyframe sheet or replacement-control
sheet; those have already done their work upstream. The normal unauthorised dry run cannot carry
`--approved-request-sha256`. Actual submission uses only
`--approved-request-sha256 <dry-run-request-sha256>` for the exact saved
payload. Every uploaded URL must bind to the exact local input SHA-256 and
remain valid for the selected RunningHub account; missing, expired, or invalid
upload provenance blocks before paid creation. A plain `--resume-task-id` is a separate known-task route,
does not require a new prompt or duration, performs no asset preparation or
payload build, cannot be combined with `--dry-run`, cannot carry authorization/
audit/script/input-contract flags, and is not a new audited authorization.

## Duration Planning

Use `scripts/segment_plan.py` after the script has approved Cut boundaries.
Calculate duration only from the ordered contiguous generated regions in
`timeline_regions.json`; `opaque_ui_demo` and supplied or omitted
`excluded_app_end_card` intervals consume zero storyboard/task slots.

- A generated region from `4s` through `15s`: submit one task at that region's approved duration.
- A generated region shorter than `4s`: merge only with adjacent continuous generated material at an approved Cut boundary, or route it to deterministic postproduction/source compositing; never submit an illegal duration or cross an opaque interval.
- One generated region `> 15s` and `<= 17s`: submit one 15-second task and compress its approved generated timing into 15 seconds.
- One generated region `> 17s` and `<= 30s`: require exactly two 5-15 second segments and exactly two storyboards. The legal split range is `max(5, total-15)` through `min(15, total-5)`.
- Two discontiguous generated regions: each must fit one 4-15 second task. Never create an empty task merely because the original source duration exceeded 17 seconds.
- The Skill chooses the boundary from story meaning; `segment_plan.py` only validates the chosen `--split-boundary`. It must never invent or balance the split.
- If no valid approved boundary exists, or the generated-region plan would exceed two total tasks, stop with a blocker requiring storyboard-script revision or a different postproduction route. Never hard-cut and never add a third storyboard.

## RunningHub Standard Model Seedance Submission

Read `references/seedance-prompt.md` and `references/runninghub-standard-seedance-api.md` before assembling the final request.

1. Verify the stored storyboard approval receipt and the internal one-to-nine-image
   allocation contract. Do not ask the user to confirm or acknowledge the
   allocation again.
2. Upload the approved director board first, then the populated fixed-slot target references, optional duration-bounded audio fragment, and the matching 2-15 second original source segment. For a local source intake, pass `--source-video-file`, `--segment-plan-file`, and `--segment-id` to `scripts/runninghub_seedance_submit.py`: it materializes that exact frozen window locally before upload, reuses the complete source only when it is itself the 2-15 second window, and otherwise writes a cached FFmpeg slice. Bind every returned public HTTPS URL to its exact input SHA-256; do not reuse an expired URL from another account.
3. Run `scripts/runninghub_seedance_submit.py --dry-run` with `--image-role-manifest`. The request uses exactly the matching original source segment at `videoUrls[0]` plus `usfr-video-reference/v1` and the complete ordered image binding. Do not upload source keyframe sheets or replacement-control sheets at this stage. The approved dry run and paid submission must reuse the same source-slice SHA-256. Opaque UI and tail media are forbidden.
4. Build each segment prompt under 5000 characters. Repeat that segment's complete approved Cuts as text, with global Cut numbers, local timecodes, the actual `@Image1` through `@Image9` mapping in use, incoming/outgoing continuity anchors, 脚本描述, camera/action direction, product/person identity lock, 口播内容, sound, continuity, and 备注. Never replace these fields with “follow the storyboard image.”
5. Do not use any legacy `reference_audios` field. Approved uploaded music is
   accepted only as one `audioUrls` item plus an explicit `@Audio1` prompt
   reference.
6. Audio policy: request voiceover plus environment/action sound, and **不默认添加背景音乐** unless the user explicitly asks for music or uploads `background_music`.
7. Run one dry-run, save the exact prompt/request and `approval_preview.json`, then complete the `seedance-20` parity audit, write the audit artifact, and authorize the exact digest.
8. Submit through `seedance-2.0-fast-token/multimodal-video` at `720p`, `9:16`, duration 4–15, with the matching original source segment at `videoUrls[0]`, the complete ordered image binding, and optional one `audioUrls` entry for `@Audio1`. Use `generateAudio=true` and an `--approved-request-sha256` matching the audited dry run.
9. When `opaque_ui_demo` or supplied `excluded_app_end_card` exists, submit only contiguous generated regions. Never upload or send those opaque videos to RunningHub Seedance, and never mention their visual contents in the Seedance prompt.

Never make a paid Seedance call until the latest storyboard has been approved and the internal parity audit authorizes the exact audited digest. Normal submission does not require a user prompt confirmation.

## Download, Concatenation, and QC

When a Seedance task completes, immediately download the returned `results[].url` MP4 to `result.mp4`; successful delivery is MP4-only at `final/result.mp4`.

- For a single task, probe the MP4 with `scripts/concat_videos.py` or FFprobe and confirm a video stream exists.
- For two segments, concatenate with FFmpeg through `scripts/concat_videos.py` at the approved story boundary and preserve audio. Do not add a crossfade by default.
- If audio was requested and any expected segment audio stream is missing, fail before concatenation and report the segment path.
- After concatenation, run final QC and verify the final MP4 has video, has expected audio, and roughly matches the planned duration.
- Missing required video/audio streams, `VIDEO_ENDS_BEFORE_AUDIO`,
  `AUDIO_VIDEO_DURATION_DRIFT`, or a missing/invalid transition render receipt
  is a technical hard failure. Decoded video stream duration is the visual
  endpoint authority; container duration or audio overhang cannot create wait
  time, padding, or black output.
- Under `opaque_ui_demo` or supplied `excluded_app_end_card`, use
  `scripts/timeline_splice.py` instead of ordinary whole-video concatenation.
  Supplied UI preserves its effective active-content duration and shifts every
  later output boundary by the actual duration delta, with no video/audio
  padding or source-duration wait. A supplied App tail card starts at the
  removed source tail-card entry boundary, trims only inactive
  leading/trailing black padding, and updates the final endpoint from its
  effective active duration. When the tail is absent, omit the source terminal
  interval. Verify no filler, freeze, black gap, or unapproved rate change is
  introduced. QC is structural/technical only for opaque/source media, not
  semantic.
  Timeline mapping uses decoded video stream duration rather than container or
  AAC overhang. Final QC scans every splice window; one full black frame at a
  splice boundary, or any longer splice-boundary black interval, blocks even
  when it is internal to the completed file.

## Failure and Resume Rules

- Save `task_id.txt`, `request.redacted.json`, `approval_preview.json`, `create_response.json`, `status.json`, and `failure.json` when applicable.
- Use `--resume-task-id` to continue a known Seedance task instead of submitting a duplicate paid task.
- Retry 429 and transient 5xx responses only for idempotent query/readiness calls. RunningHub media upload is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Paid Seedance create is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Preserve the audited request, reconcile provider state, and resume only a known task ID. Treat 401/403 as configuration errors.
- If a required RunningHub upload fails, expires, or cannot be bound to its local SHA-256, do not submit Seedance.
- Reject a planned or dry-run payload with a non-empty `videoUrls` unless it has exactly one current-segment URL, a valid `usfr-video-reference/v1` receipt, and a complete `usfr-multimodal-reference-binding/v2` sidecar. Missing target changes, any missing approved storyboard page, a wrong segment window, opaque UI, or tail media blocks before submission.
- `[SY_ERR:10] PROVIDER_MODERATION_ERROR: TRADEMARK`: do not retry unchanged.
  Clearly report the trademark moderation point. Any compliant copy or asset
  change must return through the existing script-file or storyboard-image
  revision gate; never create a separate moderation or asset approval. Never
  silently remove a product logo.
- A bare `[SY_ERR:10] PROVIDER_MODERATION_ERROR` has no known subtype. Report it as an unspecified moderation failure and preserve the raw message; never infer `TRADEMARK` unless the provider returned that token.
- `[SY_ERR:10] Read timed out`, `s3 upload failed`, or `connection reset by peer`: treat as an ambiguous provider media-fetch failure. Do not change the prompt or create a replacement paid task. Preserve the original audited request, enter the existing provider-reconciliation/user-action blocker, and resume only when a known task ID or authoritative provider lookup resolves the outcome.
- `video_reference ... DURATION_TOO_LONG`: keep the existing task unmodified, report the invalid reference window, and require a current source segment shortened to 15 seconds or less. Do not submit another paid task until the corrected dry run is approved.
- Unknown provider failures are never automatically resubmitted. Preserve the raw message in `failure.json` and tell the user what failed.
- If storyboard approval is unclear, stop and ask for approval instead of assuming.
- Never print or copy real credentials. The worker reads only its injected
  environment or explicit private deployment config; workstation secret paths
  are not production authority.

## High-fidelity hybrid profile (additive)

When the server run snapshot selects `high_fidelity_hybrid_v1`, follow the
dual-stage requirements captured in the canonical profile reference
`references/high-fidelity-hybrid-v1.md` (design snapshot:
`2026-07-17-universal-high-fidelity-hybrid-seedance20-dual-stage-design.md`)
and deepen the
existing stages without changing routes, approvals, provider limits, or the
one-to-nine-image map. The single dynamics pass may emit
`analysis/high_fidelity_analysis.json` (Source Intent Graph, Target Value
Graph, claim atoms, affordance ledger, and layer ledger). Use the bundled
`analyze-reference-video-dynamics` and `replicate-source-ui-overlays` modules;
opaque UI/tail media remains route-excluded.

Before this internal work, the worker evaluates the top-level
`scripts/skill_router.py` contract from the frozen analysis flags. The router
selects only the needed Seedance specialists and emits a package-relative
dependency snapshot; it never uses a filename classifier, workstation path, or
raw source media as a role signal. The selected route is cached by its
canonical digest and must be identical for Invocation A and B.

Persist the complete package-relative dependency snapshot for the root `seedance-20`, `seedance-prompt`, and `seedance-antislop`, plus every selected
specialist, including ordered module names, versions, exact per-file byte
SHA-256 values, and the canonical route digest. Invocation A and B must validate
that same complete snapshot. An active-profile Invocation B accepts only a
structured `prompt_request` compiled by that snapshot or its validated
`compiled_prompt_artifact`; a free-form/raw `compiled_prompt` compatibility
path is forbidden before a paid request.

Inside the existing intent/script work, run Seedance-20 **Invocation A** as a
non-provider executability pass. Persist
`analysis/seedance20_prescript_v1.json` with the packaged skill byte SHA,
candidate regions, legal split Cuts, one primary fidelity spend per region,
reference roles (maximum four), action endpoints, and exact integer-ms line,
proof, Foley, and silence contracts. Route 1 is read-only; Route 2 may receive
evidence-bounded copy proposals before the existing script approval. The
existing duration planner alone chooses final segment boundaries and performs
global-to-local rebind; lines and proof events may not cross a task boundary.

After storyboard approval, Invocation B must compile the exact final prompt
through `scripts/seedance_prompt_compiler.py` and the same packaged
`seedance-20` snapshot, repeat approved dialogue and
timing verbatim, then run the existing unauthorized dry-run and 13-check audit.
No paid task is allowed before zero ambiguity, no unresolved placeholders, and
fixed-B closure. Every source-fidelity generated run sends its exact approved
source segment in `videoUrls[0]` under `usfr-video-reference/v1`, the approved
complete ordered image binding; opaque media never enters the request. The approved `background_music` extension uses one
`audioUrls` item plus prompt `@Audio1`.
Bind `@Audio1` to a silence-padded reference audible only in original source
music cut-in/cut-out windows; never loop, stretch, advance, delay, or fill
non-music gaps. Classify uploaded audio before script approval. `non_song` is
window-only replacement with no lyrics, singer, or lip sync. `song` requires a
timestamped lyric transcript in the editable script and one explicitly
confirmed on-camera performer per sung line; user confirmation freezes both.
Multi-person/multi-vocalist ambiguity blocks. Invocation B uses only frozen
lyrics/roles, preserves hard timing and per-performer lip-sync checks, and
keeps ordinary QC lightweight. The user must hold the required audio rights.
The compiler recomputes the root Skill checks from the structured segment,
exact line contract, route exclusions, anti-slop rules, and immutable Skill
bytes; caller-supplied boolean checks are not authorization. The compiled
artifact carries a `rule_audit` with the root Skill SHA and recomputed check
digest.

The source-to-prompt projection is lossless for high-criticality factors:
scene topology/framing, camera phases, light vectors, performance/gaze/
expression/gesture, object state and completed endpoint, exact speech timing,
delivery/lip-sync, proof/Foley/silence, continuity, and negative constraints.
Generic quality adjectives, duplicate reference descriptions, and secondary
actions are removed before any of these fields are shortened. A readable UI or
long text is never delegated to Seedance; it follows the existing deterministic
generated-UI contract or opaque splice route.

Stage 11 uses `hybrid_compositor.py` with FFmpeg by default. HyperFrames HTML UI
is conditional on a passing benchmark; Remotion is opt-in and MediaBunny is
upload preflight only. The optional QC extension requires total >=85,
high-criticality factors >=90, route/timeline 100%, UI OCR 100%, and no hard
failure. Legacy runs without a profile snapshot bypass this extension.
For an active profile, every weighted dimension and factor must include a
target reference bound to the actual final MP4 SHA-256, and all source
references must belong to the same Run's immutable inputs or upstream evidence
artifacts. Stale or foreign evidence cannot authorize delivery.
## Review revisions and final Seedance binding

Use the approval matrix Route 2/Route 1/Route 0: Route 1 means a valid
approved script in the same task and never assumes an approved storyboard;
Route 0 is a blocker/no-generation path. Direct edit, instruction-only edit,
and regenerate are separate review modes. Review iterations are unbounded
(arbitrary review iterations).
Partial storyboard regeneration is per-Cut, with continuity-neighbor reuse;
the one-or-two reference limit applies only to Seedance Segments, never to
storyboard Cut images.

Bind the final compiled Prompt and Provider Payload to the latest approved
script SHA, storyboard manifest SHA, ordered per-Cut image SHA list, Segment
Plan SHA, and `output_language` enum (`en`, `ja`, `ko`, `fr`, `de`, `es`, `pt`,
`id`, `zh`). Exact localized dialogue/text rows must match that language.
The binding field names are `approved_storyboard_manifest_sha256` and
`approved_storyboard_cut_sha256s`.
Any change to one binding invalidates downstream Prompt and provider artifacts.
`seedance20_prescript_v1.revision` is always `1`; user review revision counts
must never be copied into it. Route-excluded opaque UI and tail inputs never
enter Seedance Prompt or Provider Payload.
