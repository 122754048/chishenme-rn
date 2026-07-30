# App Timeline Region and Opaque Media Contract

This contract routes App intervals before script, storyboard, image generation,
or Seedance planning. Source dynamics locate the interval; the fixed input
manifest selects its media origin. Every region is exactly one of the following
mutually exclusive values:

- `excluded_app_end_card`
- `opaque_ui_demo`
- `generated_ui_demo`

Write the result to `analysis/timeline_regions.json` with source-frame-accurate
`source_start`, `source_end`, evidence, confidence, `transition_shell`,
`media_origin`, and `assembly_policy`. A region cannot carry two route
labels.

Any ordinary Cut unaffected by a populated replacement slot may also use
`media_origin=source_interval` and
`assembly_policy=splice_source_interval`. Such a Cut is a local KEEP plate,
does not enter storyboard/Seedance generation, and is never sent as a provider
reference.

## Route 1: `excluded_app_end_card`

Use only for a terminal brand/download-only hold: App icon/wordmark, store
badge, QR code, download button/animation, or a brand tail card with no ongoing
person action, product use, conversation, or interactive UI state. This route has
exactly two tail-card outcomes:

### Supplied `tail_video`

Treat the supplied video as **opaque replacement media**. Apply the
`trim_to_active_content` policy while preserving its internal
pixels, audio, and animation, and apply the source entry transition exactly
once at the splice boundary. Automatically trim only leading and trailing
black padding from video and audio together, reset timestamps, and use the
resulting active window as the effective duration. Do not change playback rate,
loop, or freeze. no final-frame padding, no black filler, and no atempo.
Never OCR, redraw, recompose, semantically inspect, generate, or register/send
the tail card to Image Gen/Seedance. recalculate the source-to-output mapping
from the effective replacement duration and end at the last active frame.

The tail-card interval is omitted from the text script, omitted from every
storyboard, omitted from the Seedance prompt and assets, omitted from selling
point mapping, and omitted from paid generation duration. The splice manifest
must retain the removed source interval, source entry transition, supplied
duration, normalized duration, and recalculated output mapping.

### Missing `tail_video`

Use `omit_source_end_card`: remove the complete source tail-card interval from
the final timeline. End at the preceding source-body last active frame. Omit
the interval from the text script, every storyboard, the Seedance prompt and
assets, selling-point mapping, and paid generation duration. Never add filler,
black frames, a freeze frame, generated Logo, or synthetic download animation.

Normative wording for downstream contracts: **omit from the text script**;
**omit from every storyboard**; **omit from the Seedance prompt**; **omit from
paid generation duration**; **preserve the source entry transition** for a
supplied tail video; when it is missing, **omit the source tail interval** and
end at the preceding source-body frame.

Exact route contract: omit from the text script; omit from every storyboard;
omit from the Seedance prompt; omit from paid generation duration; preserve the
source entry transition exactly once for supplied tail media; omit the source
tail interval when no tail video is supplied.

Legacy manifests that contain a null media path may still be loaded for
backward-compatible audit/recovery. The fixed-slot binder emits
`omit_source_end_card` for new missing-tail runs; no source tail pixels or
audio enter final assembly.

Example:

```json
{
  "region_type": "excluded_app_end_card",
  "source_start": 12.48,
  "source_end": 15.04,
  "generation_policy": "never_generate",
  "script_policy": "omit_from_text_script",
  "storyboard_policy": "omit_from_every_storyboard",
  "seedance_policy": "omit_from_prompt_and_assets_and_duration",
  "tail_video": null,
  "media_origin": "source_interval",
  "assembly_policy": "splice_source_interval",
  "missing_behavior": "omit_source_tail",
  "transition_shell": {"entry": "source-matched"}
}
```

## Route 2: `opaque_ui_demo`

Use when the source interval is interactive UI (page/state changes, click,
scroll, input, match, chat, playback, loading, or navigation) and the user
supplied target UI video exists. Remove source UI pixels from the generated
timeline, splice the supplied target video at the same source interval, and
leave the user UI content unchanged. Apply the source entry/exit
`transition_shell`—direction, duration, easing, opacity, scale/mask, z-order,
and audio boundary events—without reading or reproducing source UI text.

The target UI video is never registered or sent to Image Gen/Seedance. Missing
opaque UI media, no active content, or missing transition-shell evidence is a
blocker. Do not silently fall back to generated UI. Trim only leading and
trailing black padding from video and audio together, reset timestamps without
changing playback rate, preserve its active-content duration and retained
internal pixels/audio/animation, and recalculate the source-to-output mapping
plus every downstream timestamp from the effective duration. Use no final-frame
padding, no audio padding, no atempo, loop, freeze, time stretch, OCR, redraw,
or semantic trim. Read display rotation metadata before aspect normalization.
The validator and normalization canvas use display dimensions; encoded width/
height remain audit fields. A centered cover crop is permitted only within the
12% safe cover-crop limit; a larger crop or visible black padding blocks.

Opaque replacement audio is explicit. The default `audio_policy` is
`opaque_audio_keep` and requires the uploaded UI/tail media to contain an
audio stream; it never silently replaces source voiceover. A media file with
no audio may declare `audio_policy=silence_allowed`, which injects a bounded
silent track only for that opaque interval and records the operation in the
splice manifest. Source-voiceover preservation with target audio uses
`evidence_bound_mix` only through the bundled immutable mixer. It preserves
only frozen source speech windows, ducks the opaque audio inside those windows,
and fails closed on missing audio, invalid timing, stale lineage, or a renderer
without the declared mixer capability; it must not be approximated by dropping
or replacing the source speech.

Every included region declares exactly one delivery policy:
`source_audio_keep`, `generated_audio_contract`, `opaque_audio_keep`,
`evidence_bound_mix`, or `silence_allowed`. Generated dialogue binds the
selected output language, translated meaning, exact line window, delivery
label (including whisper/light voice), and visible-speaker lip-sync evidence.
An `evidence_bound_mix` receipt binds source WAV SHA, opaque WAV SHA, request
SHA, output WAV SHA, duck curve, and the final MP4 SHA. Final audio QC verifies
line timing/meaning/delivery, lip-sync, Foley, ambience, meaningful silence,
unexpected silence, integrated loudness, true peak, boundary sample jumps,
stream start offset, and terminal A/V drift. It never repairs failures by
padding audio, trimming picture, or re-zeroing a delayed microphone track.

Input-contract-v2 reserves disabled interfaces named `OptionalInputExtension`,
`MusicTimelineAnalyzer`, and `BackgroundMusicCompositor`. No public background
music upload, readiness capability, or required runtime dependency is exposed.

At compositor admission, the server-side `audio_route_guard` compares the
frozen ASR speech windows with supplied opaque UI/tail intervals. An active
high-fidelity run blocks with `AUDIO_LAYER_POLICY_REQUIRED` unless the region
has a current pre-bound receipt or the renderer explicitly declares bundled
`evidence_bound_mix` support. Only that renderer may defer the receipt until
render completion, and publication remains blocked until the compositor
validates the renderer-produced final-bound receipt. Explicit upstream blocked
decisions remain blocked. The guard does not OCR, reinterpret opaque media, or
synthesize speech. Source-origin intervals and an explicitly omitted source
tail are outside this blocker.

When the fixed manifest has no UI operation video, screenshot, or App Store URL,
use the `source_ui_keep` region with
`media_origin=source_interval` and
`assembly_policy=splice_source_interval`. This source-origin form is local
source media, not user-supplied target UI; it is never OCR'ed, redrawn, retimed,
or sent to a provider.

```json
{
  "region_type": "opaque_ui_demo",
  "source_start": 5.20,
  "source_end": 8.70,
  "user_ui_video": "inputs/target_ui_demo.mp4",
  "generation_policy": "never_generate",
  "script_policy": "exclude_source_ui_semantics",
  "storyboard_policy": "exclude_source_ui_pixels",
  "seedance_policy": "exclude_prompt_and_task",
  "assembly_policy": "splice_opaque_media",
  "transition_shell": {"in": {}, "out": {}, "audio": {}, "z_order": "source-equivalent"}
}
```

## Route 3: `generated_ui_demo`

Use when the interval is interactive UI and no target UI video was supplied.
This route is generated/assembled, but it may not invent App truth. Require
target-owned UI evidence and both `ui_truth_card.json` and
`ui_render_contract.json`, including approved screen states, navigation,
copy, buttons, icons, permissions, loading states, viewport, safe area, grid,
fonts, type sizes, spacing, and transitions. Prefer deterministic rendering or
compositing of real target screenshots/recordings; use a video model only for
the surrounding hand/device/camera layer when UI pixels are not being drawn.
The truth card is frozen at intake from the uploaded UI screenshot or parsed
official App evidence. The renderer consumes/echoes that immutable object and
must not create, revise, or replace it.

Before a Take enters the final video:

- all visible copy must come from the target truth card and match character for
  character;
- OCR must match 100% and state/layout must match the render contract;
- garbled text, pseudo-text, random letters, wrong words, missing glyphs, wrong
  layout, wrong screen state, or an unverified target claim **block the run**;
- storyboard labels are only visual aids; they never carry full UI copy or
  hidden prompt instructions.

The accepted `ui_qc_report` is tamper-evident rather than a boolean assertion.
It binds the rendered media SHA-256, `ui_truth_card_sha256`,
`ui_render_contract_sha256`, `ocr_match_percent=100`,
`layout_match_percent=100`, the exact observed approved-copy array, and
non-empty frame-addressed OCR/layout evidence digests. Active multi-state
reports also bind `truth_basis`, `truth_source_sha256`,
`animation_qc_required=true`, `animation_interval_evidence`,
`animation_ocr_match_percent=100`, and
`animation_layout_match_percent=100`. A changed truth card, layout contract,
media file, percentage, provenance, or evidence row invalidates the Take.

For a multi-state generated UI, the truth card may additionally declare a
`states` array. Each state has a unique `state_id`, an integer `frame_ms`,
`expected_text`, and `expected_layout`. The QC report then carries a
`state_evidence` array with exactly the same state-id set. Every row records
`frame_sha256` (the SHA-256 of the decoded `rgb24` frame at `frame_ms`, using
the `ffmpeg-rawvideo-rgb24-v1` projection),
`truth_state_sha256`, and nested `ocr_evidence`/`layout_evidence` records.
Those nested receipts must include a digest of their records. By default,
`input_sha256` is the decoded frame SHA. When the OCR/layout backend receives
an encoded PNG/JPEG projection instead, the receipt must carry both
`decoded_frame_sha256` (equal to the decoded `rgb24` frame SHA) and
`input_sha256` (the exact encoded bytes sent to that backend). The timeline
compositor re-decodes each frame, checks the decoded binding, and preserves the
backend-input binding; a file/container SHA or a self-reported 100% summary
cannot prove an unseen screen state.

State snapshots are not sufficient for animated UI. Every state-to-state
interval is sampled at deterministic interior timestamps (two samples by
default, bounded to 1-8 per interval and 64 total by
`ui_render_contract.animation_qc`). Each sample
binds its decoded RGB24 SHA, exact OCR input SHA, independent OCR/layout
records and record digests. Replacement/box glyphs, text outside target truth,
no readable text, low-confidence OCR, geometry outside the rendered viewport,
or a position/size jump outside the interpolated target layout blocks the Take.

The stronger multi-state contract also requires:

- state `frame_ms` values are strictly increasing and each lies before the
  decoded UI video's visual end;
- `ui_render_contract.state_sequence` is required and is exactly the ordered
  `state_id` sequence (no hidden, skipped, or invented page);
- `ui_render_contract.viewport` is required; every expected layout box has
  finite positive geometry and lies completely inside that viewport, whose
  aspect ratio matches the decoded UI video within 1%;
  replacement, control, or surrogate Unicode characters are rejected before
  assembly;
- expected layout text order matches `expected_text`, element IDs are unique,
  and `approved_copy` covers the exact visible state-text set;
- `ui_render_contract.navigation` entries name known source/target states,
  an integer action time in that interval, and a matching interactive
  `element_id` in the source state's expected layout;
- top-level `ocr_evidence` and `layout_evidence` are the exact ordered
  projection of `state_evidence`, not a separate summary sidecar;
- every OCR state receipt identifies `request_sha256`, `response_sha256`,
  `model_id`, and `model_sha256` (and may declare
  `schema_version=usfr-ocr-evidence/v1`). Anonymous records plus a 100%
  flag are not executable evidence.

An interior `generated_ui_demo` region must declare both `transition_shell.entry`
and `transition_shell.exit`; the deterministic compositor renders those shells
and its receipts bind both the canonical source-shell digest and the current
final MP4 SHA-256. A stale receipt from a different render is invalid. A single generated UI
region covering the entire timeline has no external boundary and may omit the
shell. The splice QC still scans the actual overlap windows for black frames.

These checks bind the timeline contract; they do not replace independent OCR
inference. A production worker must obtain the nested OCR receipts from the
configured evidence-bound OCR backend and must provide a real generated-UI
video renderer for multi-state routes. A static PNG or self-consistency OCR
adapter is development-only and must fail closed under the active production
capability manifest.

## Timeline and transition invariants

Production closure is global rather than per-file: frozen Segments and Cuts form
one global closed set, with unique IDs and exact canonical order. Duplicate,
missing, or extra Segment/Cut membership fails closed. The rule is that ordinary generated media cannot bypass exact Segment/Cut bindings or substitute a kind-only/latest
artifact lookup for the canonical `segment_plan` JSON/SHA authority.

Provider video, ordinary generated video, generated UI, opaque UI, and supplied
tail media use natural decoded media duration. There is no padding, freeze,
loop, or hidden retime, and per-Segment audio/video boundaries align before
concat. Any mismatch between the decoded boundary, frozen Segment window, and
manifest placement blocks assembly.

The rule is that every non-source carrier and every declared source transition
requires an exact final-output-bound receipt. The receipt binds the selected fixed slot or
immutable artifact, Segment ID, `segment_plan_sha256`, canonical source shell,
placement interval, and current final MP4 SHA-256. It also requires that source and omitted routes reject any media binding. The manifest route, placement, and omission sets are exact; stale, duplicate, missing, or extra bindings fail closed.

The production loader accepts only absolute paths to bundled timeline and concat
dependencies. Relative, external, client, or workstation dependency paths are
not production authority.

Regions cover source time in order. Generated regions retain approved global Cut
numbers and timecodes. Supplied `opaque_ui_demo` media keeps its retained pixels,
audio, and animation, trims only leading/trailing black padding from video and
audio together, preserves its effective active-content duration, and shifts all
later output mappings by the actual duration delta. It receives no final-frame
padding, audio padding, atempo, loop, freeze, or time stretch. Supplied App
tail-card media trims only leading and trailing black padding, resets timestamps
without speed change, and ends at its last active frame. Missing tail media uses
`omit_source_end_card` and is removed from final assembly. Preserve the source
entry transition exactly once for supplied tail media and preserve the source
transition shell for supplied or source-origin UI. If a supplied opaque UI video
is selected but missing, stop.

Decoded video stream duration is the placement and final-frame authority;
container/audio encoder overhang is reported separately and may not extend the
visual timeline. Final QC scans every rendered overlap/hard-cut window and
blocks one full black frame at a splice boundary as well as any longer
splice-boundary black interval. Internal black away from a declared splice
window is retained as content evidence rather than blindly trimmed.

Both edge trimming and final QC use a conservative full-black detector:
`pic_th=1.0` after the technical probe. A black-background card containing a
sparse Logo/wordmark is active content, not removable padding and not a black
frame failure. Do not lower this threshold to `0.99`, which misclassifies small
target marks after downsampling; preserve internal black intervals and trim
only genuine edge padding.

Write `timeline_splice_manifest.json` with source ranges, final output ranges,
omitted intervals, `final_output_sha256`, transition-shell references, and
transition receipts carrying that same final-output digest, plus:

```json
{"missing_slice_behavior": "omit_source_end_card"}
```

Run:

```powershell
python scripts/timeline_splice.py `
  --contract analysis/timeline_regions.json `
  --output final/result.mp4 `
  --manifest final/timeline_splice_manifest.json
```
