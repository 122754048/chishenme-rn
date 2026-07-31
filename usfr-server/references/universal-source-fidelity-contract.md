# Universal Source Fidelity Contract

In a server run this contract is an immutable artifact owned by the durable
run aggregate. Its SHA-256, schema version, producer stage, and parent run
version are persisted before downstream work. Local copies are snapshots and
cannot authorize a transition, approval, or provider submission.

This is the authoritative, provider-neutral contract for a source-video
replication run. It applies to physical products, Apps or digital products,
services, brands, creator/story videos, and no-product source videos, regardless
of camera style (locked-off, handheld, push/pull, tracking, aerial,
screen-recording, split-screen, overlays, or mixed media). It is a contract for
what is observed, what must remain, what may be replaced, and how every interval
will be generated or assembled—not a claim that every source needs ecommerce
UGC treatment.

## Fixed input admission

The public intake is bound by
`references/fixed-input-slot-contract.md`. `source_video` is mandatory,
and at least one fixed change input must be valid before a formal run can
proceed: either one of the six optional replacement slots or the separate
`output_language` parameter. Source-only input without a replacement slot and
without `output_language` is rejected with `MIN_ONE_OPTIONAL_INPUT_REQUIRED`.
Reject a source longer than 30 seconds with `INPUT_SOURCE_TOO_LONG` and HTTP
422 before creating a formal run, analysis artifact, Image Gen request, or
provider intent.

The slot position is authoritative. A supplied file is never reclassified by
AI, OCR, filename, or pixel inspection. Absent target slots become
`source_preserve` decisions, while the source video remains the only source
of dynamic/Cut evidence.

## Contract envelope

Freeze `source_fidelity_contract.json` before writing the replacement script.
Each source interval/Cut records at least:

```json
{
  "cut_id": "S01_SH03",
  "time": {"start_ms": 2500, "end_ms": 3900, "start_frame": 60, "end_frame": 93},
  "scene_graph": {},
  "props_and_entities": [],
  "camera": {},
  "atomic_action_graph": [],
  "speech_delivery": {},
  "audio": {"ambience": [], "foley": [], "transitions": []},
  "overlays": [],
  "selling_point_logic": {},
  "continuity_in": {},
  "continuity_out": {},
  "evidence": [],
  "uncertainty": [],
  "criticality": "H",
  "confidence": 0.92,
  "state": {"observed": {}, "inferred": {}, "planned": {}},
  "generation_route": "KEEP",
  "media_origin": "source_interval",
  "assembly_policy": "splice_source_interval"
}
```

`observed` is directly supported by frames, audio, OCR/ASR, tracking, or user
assets. `inferred` is an evidence-backed interpretation. `planned` is a target
replacement, localization, generation, or post-production decision. Never write
an inferred or planned value back as source fact. High-criticality evidence must
include a timecode/frame or audio reference, method, confidence, uncertainty,
and an explicit blocker threshold.

The contract preserves the source scene graph (foreground, midground,
background, props, spatial relationships, occlusion, state, and off-screen
sound), camera (shot scale, lens feel, position, focus, exposure, movement,
speed/acceleration, shake, blur, and cut sync), atomic action graph, speech and
delivery, ambience/Foley/transition audio, overlays, selling-point logic,
continuity, evidence, uncertainty, criticality, and the generation route.

## Fidelity levels

### Level 0 — pixel/material fidelity

Keep source plates, source audio, source overlays, or exact source motion and
replace only an authorized identity, product, brand, or copy layer. Use this for
backgrounds, screen recordings, logos, text, or complex motion whose pixels are
the value of the source. Route sensitive media through deterministic compositing
or an opaque splice.

### Level 1 — structure/performance fidelity (default)

Keep Cut boundaries, composition, camera path, atomic action order, gaze/pose,
speech rhythm, audio events, transitions, CTA placement, and continuity while
replacing identity/product truth with verified target evidence. This is the
default for a supported source video and is the level used for normal storyboard
and Seedance planning.

### Level 2 — intent fidelity

Keep only the hook, emotional turn, selling-point category, CTA, and broad
pacing. Mark the migration `REINTERPRET`; do not call it a complete replication
or imply pixel identity. When target and source physical forms are incompatible,
explicitly state what function and expression position are retained.

## Universal source/target/migration records

Every run produces these parallel views:

- `source_truth`: scene, props, camera, action, speech, audio, overlays, and
  continuity facts;
- `source_logic`: hook, proof, trust, emotion, CTA, and selling-point chain;
- `target_truth`: verified product/service/App facts, approved copy, UI evidence,
  and permitted claims;
- `migration_plan`: `KEEP`, `REPLACE`, `COMPOSITE`, `REMOVE`, `REINTERPRET`, or
  `OPAQUE_SPLICE` for each entity/layer and its generator/post route.

The target may not inherit an unsupported source claim. For each selling point,
write `Feature → Mechanism → Benefit → Proof → CTA` and save it in
`selling_point_mapping.json`. If the target cannot prove a source claim, mark it
`unsupported`, lower or remove the expression, and never fill the gap by model
guessing.

## App region routing

Source-video App regions are located from visual/audio dynamics, then routed
deterministically from the fixed input manifest:

1. `excluded_app_end_card`: terminal brand/download-only interval with no ongoing
   interaction or narrative action. It is excluded from the text script, every
   storyboard, selling-point mapping, Seedance prompt/assets, and paid generation
   duration. A supplied `tail_video` is opaque replacement media: keep
   its internal pixels, audio, and animation; apply its source entry transition
   exactly once; automatically trim only leading and trailing black padding
   from video and audio with matching `trim`/`atrim` and timestamp reset; and
   never register/send it to Image Gen or Seedance. Use no final-frame padding,
   loop, freeze, black filler, playback-rate change, or atempo. Recalculate the
   source-to-output mapping from the effective replacement duration and end at
   the last active frame. Full-black media or a missing active interval blocks;
   preserve and report internal black intervals rather than trimming them. A
   transition render receipt must bind the rendered entry result to the exact
   source-shell SHA-256 and current final MP4 SHA-256; a stale receipt or a
   metadata-only transition flag is not proof. When no
   tail video is supplied, use
   `omit_source_end_card`, omit the complete source interval from final assembly,
   do not render the removed tail's entry transition, and end at the preceding
   source-body last active frame without filler.
2. `opaque_ui_demo`: interactive source UI interval for which the user supplied
   a target UI video. Remove source UI pixels and splice the supplied video under
   the source `transition_shell`. Trim only leading/trailing black padding from
   video and audio together, reset timestamps without changing playback rate,
   preserve its active-content duration and all retained internal pixels/audio/
   animation, and recalculate the source-to-output mapping plus downstream
   timestamps from the effective duration. Use no final-frame padding, no audio
   padding, no atempo, loop, freeze, time stretch, OCR, redraw, or semantic
   rewrite. Missing media, no active content, or missing transition evidence is
   a blocker. Resolve display rotation metadata first and apply the aspect rule
   to display dimensions, while retaining encoded dimensions for provenance. A
   centered crop is allowed only within the 12% safe cover-crop limit; a larger
   crop or visible black padding blocks. The technical normalization filter must
   set output sample aspect ratio to `1:1` before any transition compositor; a
   non-square output SAR must never reach xfade or concat.
   Preserve every internal UI operation and internal black interval; never trim
   the middle of the UI demonstration. Entry and exit each require a transition
   render receipt bound to the exact source-shell SHA-256 and current final MP4
   SHA-256.
3. `generated_ui_demo`: interactive source UI interval with no supplied target UI
   video but a supplied UI screenshot or App Store URL. Require target-owned UI
   evidence, `ui_truth_card.json`, and `ui_render_contract.json`. Prefer
   deterministic render/composite. The truth card is immutable and must be
   sourced from the uploaded screenshot or parsed official App evidence; the
   renderer may consume/echo it but cannot author or mutate it. OCR/layout must
   match 100% at every declared state and at independently sampled frames in
   each state-to-state animation interval. Replacement/mojibake glyphs,
   unreadable transition text, out-of-viewport geometry, pseudo-text, wrong
   layout, wrong state, or an unverified claim blocks the run.
   The accepted QC artifact binds `ui_truth_card_sha256`,
   `ui_render_contract_sha256`, `ocr_match_percent=100`,
   `layout_match_percent=100`, source-truth provenance, state and animation
   decoded-frame/input OCR receipts, `animation_interval_evidence`,
   `animation_ocr_match_percent=100`, `animation_layout_match_percent=100`,
   and the exact media digest.
 4. `source_ui_keep`: interactive source UI interval when all UI target slots are
   absent. Keep the source pixels/audio server-side through verified
   tenant-private object storage or a lease-owned temporary volume with the
   same `media_origin=source_interval` and
   `assembly_policy=splice_source_interval`; do not OCR, redraw, retime, or send
   it to a generation provider. A client-workstation path is never authority.

The compositor publishes an immutable timeline manifest containing the actual
output duration. Final QC compares decoded media duration with that manifest,
not with the source interval sum, because supplied UI/tail media may be
shorter or longer after permitted edge-black trimming. A missing or mismatched
manifest blocks production; black-scan uses a half-frame threshold so a single
30-fps black flash cannot pass.

The black-padding detector is conservative about content: its `pic_th` must
require a genuinely full-black decoded frame (`1.0`), even when the scan uses a
low-resolution probe. A sparse non-black Logo, wordmark, or download mark on a
black App card is active content and must not be classified as all-black media;
only true edge padding may be trimmed. This same rule applies to the server QC
scan and the deterministic splice scan.
When a multi-region compositor manifest does not carry output-clock placement
or transition receipts, QC fails closed instead of guessing source time equals
output time after an elastic replacement. The same technical receipt records
low-resolution `freezedetect` intervals. A repeated/frozen interval is a hard
failure only when output/input lineage proves that generated or opaque
assembly introduced it at an edge or splice; static source content and a
user-uploaded static hold remain allowed inside their declared placement
window. Stream start timestamps are checked independently of stream duration,
so a delayed voice track cannot be silently re-zeroed.

FFmpeg transition mappings are exact-only. `radial_zoom_blur` is not equivalent
to `hblur`, and `zoom_out`/`zoom_back` are not equivalent to a plain fade;
until dedicated renderers are injected, those transitions fail closed with
`TRANSITION_BACKEND_CAPABILITY_REQUIRED` rather than being
reported as a successful approximation.

An interval cannot receive two labels. If an end-card candidate overlaps real UI
interaction, UI classification wins and the tail-card candidate is retained only
as an uncertainty note for review.

## Generation and assembly route

The contract freezes before script, storyboard, and Seedance input. Opaque
media is never sent to a generation provider. Every source-fidelity generated
segment sends exactly one matching original 2-15 second source segment at
`videoUrls[0]`, bound by `usfr-video-reference/v1` to the source and slice
SHA-256 values and frozen segment window; it sends one-to-nine images under
`continuous-present-role-order/v1` and
`usfr-multimodal-reference-binding/v2`: model identity, product/App truth,
every original approved director-board PNG page, then explicitly scoped
additional references. The required upstream chain is source Cut frames →
replacement-control sheet → approved director board. Source Cut/keyframe sheets
and replacement-control sheets must never be sent to Seedance. Generated regions inherit exact global
Cut numbers, source timecodes, continuity handoff, voiceover/audio events,
selling-point evidence, and negative constraints. A route change invalidates the
downstream contract and returns to the relevant existing approval gate.

Every approved storyboard page is uploaded as its original confirmed PNG.
`seedance_execution_carrier.png` and a single `storyboard_url` are forbidden.
Enforce `uploaded_tags == binding_tags == prompt_tags`. @Video1 and @Audio1 are
independent namespaces and never consume image indices. Source Cut/keyframe
sheets and replacement-control sheets must never be sent to Seedance. The full
source video must never be uploaded to Seedance.

Confirmed visible text is routed by carrier. Scene-surface text is part of a
physical prop/material and must be present in the replacement-control sheet and
approved director board with exact wording, carrier ID, surface relation, and
placement. It moves, bends, folds, rotates, occludes, and tears with its carrier,
and this behavior must be written explicitly into the Seedance Cut prompt.
Deterministic overlay text is a screen-space subtitle/caption/CTA/headline layer
rendered by the overlay compositor; Seedance must not generate, read, or
transcribe overlay glyphs. UI text stays in the deterministic UI/source-pixel/
opaque route. Never flatten scene-surface text into a screen-fixed post layer.

If routing produces zero generated regions, the existing local-only branch is
mandatory: no reverse script, no storyboard, no Image Gen request, no
Seedance-20 Invocation A or B, no CreateAsset, no CreateVideo, and no creative
approval. Region-boundary planning, deterministic source/opaque assembly,
transition rendering, and technical QC still run. Derived source contact sheets
or boundary frames may carry structure, timing, camera, environment, and
approved scene-surface text evidence; source identity, unauthorized brand/UI,
and deterministic overlay text must not leak into a replacement storyboard or
fixed-B provider asset map.

The final QC report checks structural timing and continuity, visual identity and
product truth, speech/delivery and audio onset, overlay placement, selling-point
proof, App UI OCR/layout, route compliance, and absence of unsupported claims.
Decoded video stream duration is the visual timeline authority, and every
   hard-cut/transition overlap receives boundary-aware black detection; one full
   black frame at a splice boundary, or any longer splice-boundary black
   interval, is a technical hard failure.
Missing required video/audio streams, `VIDEO_ENDS_BEFORE_AUDIO`,
`AUDIO_VIDEO_DURATION_DRIFT`, `AUDIO_VIDEO_START_OFFSET`, or a
missing/invalid transition render receipt is also a technical hard failure.
Any failed high-criticality check blocks delivery; a visual resemblance alone is
not acceptance evidence.
For active high-fidelity QC, every dimension and factor evidence set must bind
at least one `target_ref.artifact_sha256` to the exact final MP4 bytes. Every
`source_ref.artifact_sha256` must be present in the current Run's immutable
input slots or upstream evidence artifacts. A syntactically valid score whose
references belong to another output or Run is not admissible evidence.
Active production additionally requires a deployment-owned independent QC
evaluator receipt (`high-fidelity-qc-evaluator-receipt/v1`). The server binds
that receipt to a canonical request/response digest, evaluator/model identity,
the exact final/source media set, and the dimensions/factor digests it uses;
missing or stale evaluator evidence blocks publication. Shadow, legacy, and
explicit local-development runs retain their compatibility path.

## Additive high-fidelity analysis projection

The internal profile `high_fidelity_hybrid_v1` may persist
`analysis/high_fidelity_analysis.json` as an immutable sidecar. This sidecar
does not change the public workflow, the seven fixed inputs, Route 1/Route 2,
the two approval types, RunState, server stages, provider payload, task count,
or final delivery. Runs without the profile continue to use the legacy
contracts without backfill.

The sidecar contains the Source Intent Graph
`Attention -> Curiosity -> Understanding -> Belief -> Desire -> Action -> Loop`,
the target-owned Target Value Graph, one migration edge per source node using
`exact|functional|intent_only|unsupported`, evidence-bearing claim atom
records, an affordance ledger, and a per-Cut layer ledger. All routes and
fidelity levels reuse the existing enums.

The exact legacy nine-key integer intent contract remains authoritative and
must total 100. The deep graph is only a deterministic compatibility
projection: every point is assigned once to a legacy key and Cut allocation.
Claim atoms project only to the existing
`supported|unsupported|reinterpreted` status. Unsupported claims remain audit
records and never enter the approved script or prompt.

Every high-criticality node, claim, affordance, and layer requires private
object-store-safe evidence, confidence, uncertainty, blocker threshold, and an
actual carrier. App screenshots prove only the visible state; they cannot prove
an unseen operation or result. Opaque/source-origin intervals stay
route-excluded and receive technical metadata only.
