---
name: universal-source-fidelity-replication
description: Use when a user supplies a source viral video plus at least one fixed change input: a replacement slot (new product image, model image, UI screenshot, App Store URL, UI operation video, or tail video) or a supported output_language-only localization request; also use when a server must execute that source-fidelity workflow durably from intake through final MP4 delivery.
---

# Universal Source-Fidelity Replication

This is the canonical Skill. Use `$universal-source-fidelity-replication` for
new work. `$tiktok-ai-video-replication-factory` and
`$seedance-storyboard-replication` remain compatibility aliases and must route
to this contract rather than reintroducing their legacy behavior.

Run the complete production workflow from source evidence to final MP4. This is
the top-level skill. It owns intake, dependency routing, run directories,
approval gates, timing, assembly, QC, and delivery. Its bundled skills remain
single-purpose implementation modules.

For server execution, the temporary Redis job is authoritative. Use `server/`
with `references/server-api-contract.md`, `run-state-machine.md`,
`ephemeral-job-lifecycle.md`, `idempotency-and-provider-reconciliation.md`,
`adaptive-fidelity-recovery-loop.md`, and `error-code-contract.md`. The public
surface is `/api/v1/jobs`; every mutation uses the current `expected_version`
and every later request carries the job-scoped bearer capability returned once
at creation. There is no SQL, account, tenant, billing, history, analytics,
Outbox, or SSE subsystem in this video-only package.

`RedisEphemeralJobStore` owns the job `slots_manifest` snapshot, revisions, approvals, stage
checkpoints, Provider attempts, artifacts, recovery checkpoints, and TTL.
`RedisWorkQueue` owns dedupe, scheduling, reclaim, delivery, and ACK. Production
object references are verified against the exact job prefix, SHA-256, size,
MIME, and completion state before admission or worker materialization.

Before a paid call, freeze the exact canonical audited request SHA-256 and its
Segment/segment-plan authority in a Provider attempt. Duplicate, missing, or
extra Segment IDs fail closed. Every paid CreateVideo adapter receives the
exact canonical audited provider payload; `create_video(request)` is the
preferred Provider protocol. The canonical `segment_plan` JSON and its
`segment_plan_sha256` are the only Segment-membership authority. An ambiguous
Provider outcome is reconciled and never blindly resubmitted. Every worker publication is lease-fenced and ACK
occurs only after checkpoint completion. All Redis authority and
`temporary/{job_id}/...` objects expire; only a successful verified
`final/{job_id}/result.mp4` remains.

The factory is content- and product-type neutral. It accepts physical product,
App or digital product, service or brand video, creator/story video, and source
videos with arbitrary supported camera styles (locked-off, handheld, push/pull,
tracking, aerial, screen-recording, split-screen, overlays, or mixed media).
The maximum 30-second intake and at-most-two Seedance tasks are current factory
capacity limits, not a claim that the analysis method is ecommerce-only.

The authoritative contract for every run is
`references/universal-source-fidelity-contract.md` (the **Source Fidelity
Contract**). It records source truth, source logic, target truth, migration
plan, evidence, uncertainty, criticality, continuity, and the generation route
for every source interval. A generated result is not accepted merely because it
looks similar; it must satisfy the contract and the final QC evidence.

## Bundled Modules

Read only the modules required by the current input:

- `bundled-skills/parse-app-store-evidence/SKILL.md`: official Apple App Store
  or Google Play identity, icon, screenshots, hashes, and provenance.
- `bundled-skills/analyze-reference-video-dynamics/SKILL.md`: frame-accurate Cuts,
  action, camera, transitions, speech, sound, and timeline structure.
- `bundled-skills/replicate-source-ui-overlays/SKILL.md`: timed overlay geometry
  when an overlay must actually be replaced and replicated.
  The frozen overlay contract is carried as `source_overlay_contract` plus
  `overlay_render_mapping`; a declared semantic overlay without a validated
  mapping fails with `OVERLAY_RENDER_MAPPING_REQUIRED` before assembly.
  Stage-4 builds the canonical mapping with
  `server.overlay_mapping.build_overlay_render_mapping`: source geometry,
  timing, keyframes, opacity, z-order, and layer relation are copied exactly;
  readable text is allowed only for source wordmarks/subtitles/CTAs, and
  brand marks/graphics require an immutable target asset SHA. The bundled
  `server.overlay_renderer.DeterministicOverlayRenderer` paints deterministic
  text/assets and returns output-bound receipts; it never accepts a local
  workstation asset path in production.
  In active production, a mapping is not proof of pixels: the deterministic
  compositor must return `overlay_render_receipts` for every region/overlay,
  binding source-contract SHA, mapping SHA, payload SHA, frame windows, and the
  final output SHA. A copy-only renderer or missing receipt fails closed with
  `OVERLAY_RENDER_RECEIPT_REQUIRED`.
  An overlay renderer is a layer pass, not a complete timeline assembler. In
  active/production, `FfmpegCompositor` must receive an injected complete
  timeline renderer whenever any timeline region has
  `media_origin != source_interval` (including generated or opaque replacement
  media). The bundled `DeterministicOverlayRenderer` is permitted without that
  injection only for source-origin-only timelines; it must never make source
  pixels masquerade as generated or opaque output. An injected renderer marked
  `capability_kind=overlay_renderer` is likewise rejected as the carrier for
  any non-source region.
- `scripts/bind_input_slots.py` and
  `references/fixed-input-slot-contract.md`: deterministic seven-slot intake,
  the fixed `output_language` parameter, enabled input-contract-v2 extensions,
  admission gate, hashes, and default route binding.
- `scripts/skill_router.py`: deterministic selection of the bundled dynamics,
  overlay, App-evidence, Seedance-20, and factor-specific Seedance modules.
  It emits only logical package paths and a cacheable route digest; it never
  resolves a workstation path or creates a provider task.
- `scripts/seedance_prompt_compiler.py`: server-safe Invocation-B prompt
  projection, exact-line rendering, specialist snapshot checks, 5000-character
  budgeting, route-leakage blocking, and compiler digest generation.
- `server/`: stateless API, Redis job/CAS authority, Redis Streams queue,
  ephemeral worker/driver, temporary/final object lifecycle, recovery loop,
  typed errors, and executable capability bindings. The capability manifest
  alone is not an implementation.
- `server/bundle_resolver.py`: production Skill dependency boundary. Active
  workers must inject `ImmutableBundleResolver` with verified immutable bytes,
  package-relative paths, versions, and SHA-256 digests. `PathBundleResolver`
  and direct `Path`/`~/.codex` references are development-only; active
  production Invocation A/B rejects them before compilation.
- `server/high_fidelity_projection.py`: validated server-side projection from
  the immutable high-fidelity analysis and fixed-slot digests into the exact
  Invocation-A candidate/factor request. It runs inside `build_script`, adds no
  stage or Provider task, never invents a claim, and fails closed when required
  evidence or a 4-15 second generated-region contract is unavailable.
- `bundled-skills/seedance-storyboard-replication/SKILL.md`: route selection,
  weighted intent, storyboard generation, RunningHub image2 and Standard Model media upload,
  Seedance compilation/submission, `opaque_ui_demo`, supplied App tail-card
  assembly, and QC.

The bundled copies are the runtime source of truth for this factory. Do not
require standalone copies of those four bundled modules under
`~/.codex/skills/` to be installed. Exception: the external `seedance-20`
skill bytes are a mandatory final-prompt compiler and auditor, and in
production they must be supplied through `ImmutableBundleResolver` rather than
loaded from a workstation. If those bytes are unavailable, block before any
paid Seedance request; never substitute an unreviewed prompt.

## App Store Evidence Contract

When `app_store_url` is populated and the authoritative timeline retains a
generated UI/target-evidence carrier, use the bundled
`parse-app-store-evidence` module exactly once per run. When the timeline is
local-only or opaque-only, record the parser as skipped and do not fetch the
page. The parser accepts an official
Apple App Store or Google Play URL and emits one provider-neutral evidence
bundle; do not route the URL through a generic scraper or ask a generator to
interpret the page.

For Google Play, the accepted page shape is
`play.google.com/store/apps/details?id=...`. Preserve and reconcile the Google
package ID as `store_app_id` across the requested, final, and canonical URLs.
The `hl` parameter maps to `language`, the `gl` parameter maps to `storefront`,
and an absent or invalid `gl` is recorded as `default` with a warning rather
than guessed from the server or user locale. Preserve the resolved App name,
provider, icon, ordered screenshot records, device-family values, source/final
URLs, SHA-256 hashes, and private page/media provenance.

Google artwork may come only from official Google Play media hosts, including
the validated Google image CDN. Bind screenshots to explicit page markers and
their original order; unrelated Googleusercontent review, recommendation, or
other-App images are never admissible. If the page advertises official media
but a file cannot be fetched, decoded, hashed, or bound to the requested App,
block the run. Do not silently downgrade to `metadata_only`. `metadata_only`
is allowed only when the caller explicitly requests it or the resolved page
genuinely exposes no official pixels; a `generated_ui_demo` route requires
target-owned pixel evidence and must block on metadata-only evidence.

Downstream script, UI truth, storyboard, Seedance, and QC stages receive only
the validated evidence bundle plus its declared media references. They must
never hand the URL to a generator, use raw page HTML as a visual reference, or
infer features, navigation, prices, ratings, or UI states from the URL/icon.

For server deployment, the parser runs inside a server Worker/container. The
bundle, page provenance, and downloaded media are published under the job's
private temporary object prefix and referenced by immutable object key, MIME, byte size,
duration when applicable, and SHA-256. A local temporary directory is allowed
only as an ephemeral staging/cache area; it is never authoritative and must not
be required for a deployed run. Cache the validated bundle by normalized URL
and request digest, reuse it for later stages, and never fetch the same store
page again in the same run.

Throughout this Skill, a phrase such as `local source interval` or `assembled
locally` means server-side deterministic post-production over an
object-store-backed source interval; it never means reading the user's
workstation. The logical run directory may be mapped to an object-store prefix
or ephemeral worker volume, but no client-local file is a production
dependency.

## Source Fidelity Contract

Before generation, freeze one `source_fidelity_contract.json` from the
authoritative reference. It must preserve, or explicitly classify the
replacement of, the source scene graph, props and spatial relationships,
camera contract, atomic action graph, speech and delivery, ambience/Foley/
transition audio, overlays, selling-point logic, continuity ledger, evidence,
uncertainty, criticality, and generation route. Every field is labelled
`observed`, `inferred`, or `planned`; inferred/planned content must never be
written back as source fact.

Use the least destructive fidelity level that satisfies the evidence:

- **Level 0** — pixel/material fidelity: keep source plates, audio, overlays,
  or exact source motion and replace only authorized identity, product, brand,
  or copy layers.
- **Level 1** — structure/performance fidelity (default): keep Cut boundaries,
  composition, lens/camera path, atomic action order, gaze/pose, speech rhythm,
  audio events, transitions, CTA placement, and continuity while replacing
  identity/product truth with verified target evidence.
- **Level 2** — intent fidelity: keep hook, emotional turn, selling-point
  category, CTA, and broad pacing only. Mark the result `REINTERPRET`; never
  call it a complete or pixel-identical replication.

Every high-criticality element requires timecode/frame or audio evidence,
confidence, an uncertainty note, and a route (`KEEP`, `REPLACE`, `COMPOSITE`,
`REMOVE`, `REINTERPRET`, or `OPAQUE_SPLICE`). Unsupported target claims are
lowered or removed rather than invented. The contract is carried unchanged
into script, storyboard, Seedance input, timeline assembly, and QC.

### Mandatory visual and text handoff

The replacement-control route is fixed: **one complete source Cut contact sheet → one RunningHub Image2 call → one complete replacement-control sheet**. Per-Cut replacement generation and per-Cut source-frame validation are forbidden during this stage. Local face swap, ComfyUI, InsightFace, desktop image editors, and any non-Image2 generator are forbidden. A fixed-slot target image is target truth only and must never be accepted as the replacement-control sheet. The director-board Image2 request must use the replacement-control sheet as reference image 1.

The user-facing director board is not a free-form provider output. Every storyboard generation must first load and compile `bundled-skills/seedance-storyboard-replication/references/daohuo_storyboard_prompt.md`; this file is the sole director-board prompt and layout authority. Its exact byte SHA-256 must be bound into the provider prompt, layout receipt, storyboard metadata, and approval artifact. Missing bytes, a changed or incomplete template, an unresolved placeholder, or a receipt without the exact template SHA fails closed before Image2 or publication. No embedded fallback prompt, generic renderer, remembered layout, or alternate Markdown file may substitute for it.

RunningHub Image2 must generate the complete `usfr-cinematic-director-production-board/v1` defined by that template: shared creative header; character reference; face/hair detail; wardrobe/style detail; ordered storyboard Cut cards; target evidence or `none`; top-down camera/movement diagram; and the six bottom departments lighting, camera, palette, audio/tone, mood, and cinematography notes. The returned Image2 PNG is preserved as the approval artifact; deterministic code may validate it, bind receipts, extract a separate execution carrier, or add approved typography, but must not replace it with a remembered layout. Cut-card count and order must exactly match the approved Segment. A layout receipt binds the template path/SHA, every required region, Cut card, approval-board SHA, and execution-carrier SHA. Missing region, generic grid, wrong Cut count, missing receipt, stale SHA, or the former five-region information-board layout fails with `STORYBOARD_LAYOUT_QC_FAILED`; the image cannot be shown, approved, or submitted.

The gate records the `daohuo_storyboard_prompt.md` template SHA, creative header, character reference, face/hair, wardrobe/style, ordered storyboard Cut cards in `storyboard_grid`, target evidence, camera/movement diagram, lighting, camera, palette, audio/tone, mood, the distinct `seedance_visual_carrier`, and the layout receipt.

The approval artifact and Seedance reference are separate immutable files. `director_board_approval.png` is the only user-facing storyboard confirmation. `seedance_visual_carrier.png` is a labels-free image derived from the approved board's `storyboard_grid` visual layer. It must carry the approval-board SHA, layout-receipt SHA, exact ROI, Cut IDs, and its own SHA. The approval board itself, its headers, notes, control sheet, and layout receipt are forbidden in the paid Seedance payload.

For every source-fidelity generated region, the visual provenance chain is
mandatory and ordered: **source Cut frames → replacement-control sheet →
approved director board**. Extract the Cut frames from the frozen source
analysis; make the replacement-control sheet by replacing only the authorized
model/product/UI layers while preserving the observed scene, background,
camera, lighting, composition, and Cut order; then create the director board
from that control sheet plus the user-provided fixed-slot targets. The control
sheet is internal evidence, never a user-facing board and never a final
Seedance reference.

User-confirmed visible text is routed by physical carrier. **Scene-surface text** printed, written, painted, embroidered, displayed, or attached to a prop must be present in the replacement-control Image2 output and director-board Cut art. Freeze its exact wording, Cut/time window, carrier ID, surface relation, placement, style, and motion behavior. The same exact wording and carrier relation must be written explicitly into the Seedance Cut prompt. It moves, bends, folds, rotates, occludes, and tears with its carrier and must never become a screen-fixed post layer.

**Deterministic overlay text** such as subtitles, captions, CTA, headline, lower-third, or sticker is rendered on the approval board and final output by the deterministic compositor. Image2 and Seedance must not generate, read, or transcribe those glyphs. UI text stays in the deterministic UI/source-pixel/opaque UI lane. A normal `no unapproved text` negative suppresses invented text without suppressing approved scene-surface or overlay text. The editable user Markdown
document contains exactly these two top-level sections and no explanatory
preface, QA prose, or provider prompt:

## 角色、场景与连续性锁定

## 逐镜反解

Every source-fidelity Seedance request is fixed: use the matching original
source segment at `videoUrls[0]`; use the approved-board-bound `seedance_visual_carrier` at
`imageUrls[0]` / `@Image1`; then include only fixed-slot target references in
the remaining image positions. Source Cut/keyframe sheets and
replacement-control sheets must never be sent to Seedance. A route with zero
generated regions creates no Seedance request. The exact current 2-15 second
matching original source segment is mandatory at `videoUrls[0]`; the full
source video must never be uploaded to Seedance.

Reference order: matching original source segment at `videoUrls[0]`; approved-board-bound `seedance_visual_carrier` at `imageUrls[0]` / `@Image1`; then only fixed-slot target references. Source Cut/keyframe sheets, replacement-control sheets, user-facing director boards, and layout receipts must never be sent to Seedance.

## Fixed Input Slot Contract

The public intake has exactly seven fixed slots. The slot position is
authoritative; do not ask AI, OCR, filename heuristics, or pixel classifiers to
decide what an uploaded asset represents:

| Slot | Required | Accepted value | Direct role |
| --- | --- | --- | --- |
| `source_video` | yes | video, maximum 30 seconds | source viral video |
| `new_product_image` | no | image or image list | target product truth |
| `new_model_image` | no | image or image list | target character truth |
| `ui_screenshot` | no | image or image list | target UI truth |
| `app_store_url` | no | official HTTPS Apple App Store or Google Play URL | App evidence |
| `ui_operation_video` | no | video | opaque UI replacement |
| `tail_video` | no | video | opaque App tail-card replacement |

`background_music` is a public optional `input-contract-v2` extension, not an
eighth fixed slot. It never changes the seven slot roles or ordering. A valid
upload is written only to `extensions.background_music`, admits a
source-plus-change run, uses `seedance_audio_reference`, and is not a
`language_only` request. It is usable only when the deployment has bound the
`background_music_execution/v1` adapter. The fixed-B request carries exactly
one duration-bounded RunningHub Standard Model `audioUrls` item; the prompt
refers to it as `@Audio1`, while legacy `reference_audios` remains forbidden.

### Uploaded-audio replacement contract

Without an uploaded audio extension, keep the original source audio. With one,
freeze every observed source `music`, `bgm`, or `instrumental` event as the
only replacement windows. The replacement is silence-padded outside those
windows: never loop, stretch, advance, delay, or fill source non-music gaps.
This is equally required for songs and non-songs, so cut-in/cut-out matches the
source video exactly.

Before script review, an immutable SHA-bound classification must be `song` or
`non_song`; unknown/low-confidence classification blocks. `non_song` means
window-only replacement, with no lyrics, singer role, or lip sync. `song` must
carry timestamped lyrics in the editable script, with each sung line assigned
to an explicitly confirmed on-camera performer; user script approval freezes
both. Multi-person/multi-vocalist ambiguity blocks rather than guessing. The
final Seedance prompt uses only the confirmed exact lyrics and roles; it never
transcribes or changes lyrics after approval.

Keep QC lightweight, but retain hard classification/lyric evidence, exact
source-window timing, and per-performer lyric lip-sync checks. Use only audio
the user is authorized to use commercially.

`output_language` is a separate fixed parameter, not a media slot. Supported
values are `en`, `ja`, `ko`, `fr`, `de`, `es`, `pt`, `id`, and `zh`. The UI
default is unselected (`null`), not a prefilled language. When it is the only
change input, the run is admitted as `language_only=true`: preserve the source
visual/product/model/UI/tail routes according to the normal absent slot rules,
but regenerate localized dialogue/text/audio in the selected language while
preserving the source content, tone, timing, delivery, and meaning. This
language-only route bypasses the manual script approval and storyboard
approval loop and proceeds directly into Seedance compilation and provider
submission. The GPT drafting boundary must receive an explicit language-only
localization instruction so it preserves every non-language factor and
translates only dialogue and visible text into the selected language with
natural lip-sync.

Run `scripts/bind_input_slots.py` once after upload. It validates the fixed
slot's declared media/URL type, cardinality, path or upload-completion record,
SHA-256, and `output_language` when supplied, then writes
`analysis/input_slots.json`. Downstream stages read this immutable manifest and
never re-identify the files.

The formal Next gate is:

```text
source_video valid
AND (
  at least one of the six optional slots valid
  OR at least one enabled public input-contract-v2 extension valid
  OR output_language valid
)
```

Source-only input without a replacement slot and without `output_language` is
rejected with
`MIN_ONE_OPTIONAL_INPUT_REQUIRED`: disable Next, do not create a formal run,
do not analyze or generate, and do not create a paid task. Locale, voice,
platform, preferences, and an approved storyboard artifact do not count as an
optional media slot. A valid upload in any one optional slot admits the run.
A valid `background_music` extension also admits the run without changing the
seven fixed-slot order. A valid `output_language` also admits the run even when
all six optional slots are absent; this remains the only route that may use no
replacement media or extension.
Reject a source longer than 30 seconds with `INPUT_SOURCE_TOO_LONG` and HTTP
422 before creating a formal run, analysis artifact, or provider intent.

After admission, every absent slot receives a deterministic route:

- absent model image → keep source person/identity;
- absent product image → keep source product/packaging and evidenced source
  proof;
- absent UI screenshot, App URL, and UI operation video → keep the source UI
  interval as a server-side source-origin interval;
- absent tail video → omit the terminal source tail-card interval completely;
  end at the preceding source-body last active frame with no filler.

Create one run directory before analysis:

```text
<output-root>/<yyyy-mm-dd>/<run-id>/
  inputs/
  analysis/
  app_store/
  product_boards/
  reference_frames/
  storyboards/
  seedance/
  final/
```

Copy or bind inputs once, calculate SHA256 hashes, and write `run_manifest.json`.
Never overwrite a previous run and never write task-specific results back into
the factory skill.

The run directory above is a logical run directory. In production it is backed
by job-scoped object storage and worker-managed temporary volumes; it is not
the user's local filesystem.

## Route Selection

The public intake always starts from the fixed slot manifest. Route 1 may resume
only from its existing approved script plus storyboard artifact; the board image
cannot replace or override approved text, timing, claims, or audio. Those are
internal run artifacts, not public input slots. Otherwise reverse-write the
replacement script and stop for
**确认反解分镜脚本**.

Source-video semantic analysis still locates App/UI/tail intervals from frames,
interaction, and audio. It does not classify uploaded file roles. Bind the
routes deterministically from the manifest:

- UI operation video supplied → `opaque_ui_demo`;
- UI operation video absent, UI screenshot or App Store URL supplied →
  `generated_ui_demo`;
- all three UI slots absent → `source_ui_keep` server-side source-origin
  interval;
- tail video supplied → opaque App tail-card replacement;
- tail video absent → `omit_source_end_card` terminal omission route.

Read the timeline contract before routing any App region.

The **Opaque slice branch** is the route for supplied opaque UI or tail-card
media; it never changes semantic generation rules for other intervals.

## End-To-End Workflow

### Server command boundary

The HTTP adapter maps only typed `/api/v1/jobs` commands to the workflow.
Creation binds the fixed slots and returns a job capability; start, revision,
approval, result, and Provider reconciliation requests use CAS versions.
Clients poll the job snapshot and browse only script/storyboard revisions or
the final result handle. The server never accepts a client Provider key, final
Prompt, arbitrary reference list, local path, or legacy approval digest.

Before any CreateAsset/CreateVideo call, persist a job-scoped Provider attempt
with the exact audited request SHA-256. A lost response becomes `AMBIGUOUS`, is
reconciled by Provider lookup when available, and is never blindly submitted
again. Final assembly publishes a temporary MP4, QC binds the actual bytes, and
only then is the exact object promoted atomically to
`final/{job_id}/result.mp4`. Any media passed to a worker is materialized from a
verified private job object into a lease-local temporary directory.

### Twelve semantic stages and operational stage mapping

The workflow has exactly **12 semantic stages**. The service may expose more
operational worker entries because evidence resolution, approval waits, and
provider submit/poll are durable operations inside those semantic stages. The
server-side read-only projection is
`server.orchestrator.build_semantic_stage_mapping`; it is an
**operational stage mapping**, does not add a job-state stage, route, approval, or
Provider task.

Fixed image-slot binding is the target-truth boundary for product, model, and
UI screenshot evidence; App Store evidence may remain deferred until routing
proves that a generated UI carrier will consume it. When a semantic stage is
intentionally deferred, the mapping reports the deferred stage itself rather
than the earlier operational stage that exposed the ordering.

The canonical semantic names are, in order:

`intake_bind`, `target_truth`, `dynamics`, `region_overlay_route`, `intent`,
`script`, `region_duration`, `storyboard`, `prompt_audit`, `provider`,
`assembly`, `qc_delivery`.

App Store/UI evidence may be deliberately deferred until `route_regions` proves
that a generated UI carrier consumes it. That is recorded as **deferred target
truth** in the mapping projection and preserves the speed contract; it does not
reorder the public workflow or create another approval. `build_script` carries
the internal intent, script, and region-duration work, while the existing
approval, storyboard, prompt/audit, provider, assembly, and QC entries retain
their existing names and leases. The projection must report unknown operational
entries, approval count, provider stage-entry count, and the fixed maximum of
two Provider tasks for deployment audits.

1. **Validate and time intake**
   - Bind the seven fixed slots, `output_language`, and enabled
     input-contract-v2 extensions, then enforce the source-plus-change gate.
   - Probe the complete `source_video` and reject duration above 30 seconds.
   - Record input-copy, probe, and validation durations in `timing_log.json`.

2. **Resolve product truth only when needed**
   - If `app_store_url` is populated *and* Stage-4 routing has a generated UI
     or target-evidence carrier that can consume it, apply the **App Store
     Evidence Contract**: run the bundled Apple App Store/Google Play parser
     once per run, cache its validated evidence bundle and official pixels, and
     persist the bundle and provenance through the server object-store adapter.
   - If authoritative routing contains zero generated regions, mark App-store
     evidence as skipped and do not fetch the page; this preserves the existing
     local-only/opaque-only fast path.
   - If the slot is absent, do not browse for an App identity. Use only supplied
     slots and source-preserve defaults.

3. **Analyze source dynamics once**
   - Run the bundled dynamics module from frame zero through the exact decoded end.
   - Use GPT for the semantic inspection pass over adaptive keyframes,
     complete-timeline contact sheets, boundary frames around every
     edit/action/camera/lighting/overlay phase candidate, and full-resolution
     detail frames or crops when product, UI, text, hand, or facial evidence
     requires them.
   - Extract and transcribe audio separately. Reconcile spoken phrases, visible
     subtitles, music, sound effects, ambience, and meaningful silence with the
     visual timeline through separate audio transcription evidence.
   - Scene candidates and fixed-interval frames are hints only. They are never
     the sole evidence and never define the final Cut count.
   - Keep deterministic probing, dynamics rules, output schema, boundary
     reconciliation, validation, and acceptance inside the bundled dynamics
     module.
   - Reuse the validated Cut/action/camera/audio contract throughout the run.
   - When `high_fidelity_hybrid_v1` is active, validate the additive
     `extensions.high_fidelity_hybrid_v1` record in the same pass; semantic Cuts
     carry normalized topology, framing migration, performance phases, action
     endpoints, and audio/proof mappings, while opaque/source intervals carry
     technical metadata only.
   - The evidence-bound VLM adapter must preserve per-Cut temporal locality:
     every active semantic/source Cut needs at least one decoded sampled frame
     whose timestamp falls inside that Cut's half-open `[start_us, end_us)`
     interval. A frame SHA alone is not sufficient when identical pixels occur
     at multiple timestamps; the response must carry `timestamp_us` or fail
     closed as ambiguous. Foreign, missing, stale, or out-of-range frame
     evidence cannot reach the high-fidelity contract.
   - Build the deterministic `scripts/skill_router.py` record from those
     frozen factors. Cache its route digest and reuse the exact dependency
     snapshot for Invocation A and B; do not perform a second routine full-video
     analysis just because a specialist is selected.

4. **Classify App regions and choose UI handling**
    - Write `analysis/timeline_regions.json` with the existing semantic region
      types and explicit `media_origin`/`assembly_policy` fields.
      The canonical server bridge
      `bind_source_overlay_contract_to_timeline` must carry the immutable
      dynamics-pass `source_overlay_contract` (and its
      `source_overlay_contract_sha256`) into this Stage-4 envelope; it may not
      be regenerated, dropped, or inferred by the route port. The route stage
      persists the enriched regions in its existing completion transaction.
      If a `timeline_regions` artifact is published, `region_count`,
      `generation_required`, and `timeline_regions_sha256` must agree with the
      indexed rows or the run fails with
      `TIMELINE_REGION_PERSISTENCE_MISMATCH`.
    - Before any control-keyframe, storyboard, or Seedance Provider call, run
      `scripts/timeline_scope_preflight.py` against the fixed slots, the
      completed `timeline_regions`, the segment plan, and every text artifact
      being submitted. Pass the resulting scope receipt to both
      `runninghub_image2.py --scope-receipt` and
      `runninghub_seedance_submit.py --scope-receipt`. A missing-tail
    - Build the internal control-keyframe manifest from the complete ordered
      `source_dynamics_analysis.source_cuts`: it contains exactly one panel per
      source Cut, in the same order, with no fixed panel count or grid-size
      rule. Validate it with
      `bundled-skills/seedance-storyboard-replication/scripts/control_keyframe_contract.py`
      before its Image2 call. The control sheet is internal visual control only;
      it cannot replace the approved script or the user-facing director board,
      and it must never be uploaded to the final Seedance request.
    - A missing-tail
      `omit_source_end_card` route fails closed for every contiguous terminal
      exclusion cluster, regardless of whether it contains a transition,
      graphic page, store page, or another source-tail form. A submitted
      artifact may name only included Cuts, must not contain any region-specific
      prohibited terms, and may not end beyond the preceding source-body final
      frame.
    - Split UI visual evidence before control-keyframe and storyboard work.
      A `source_ui_keep` region is a source-pixel lane: it must use
      `storyboard_render_mode=source_pixels` and
      `control_keyframe_render_mode=source_pixels`, and can receive only an
      explicitly authorized deterministic rectangle replacement. It never
      enters Image Gen or Seedance. An `opaque_ui_demo` region supplied through
      `ui_operation_video` is an even higher-priority opaque lane: splice its
      user pixels, sample its own frames for storyboard review, and do not
      redraw, replace, OCR, interpret, or send it to any model. Every Image2
      call must declare `--covered-cut-id`; the scope receipt admits only
      generated visual Cuts and rejects source-pixel or opaque-UI Cuts.
    - Once a terminal source interval is classified as `excluded_app_end_card`,
      a supplied `tail_video` takes the opaque replacement route:
      exclude the source tail-card semantics and audit only technical active
      content. Use `trim_to_active_content` to remove leading and trailing black
      padding from video and audio together, reset timestamps without changing
      playback rate, preserve internal pixels/audio/animation, apply the source
      entry `transition_shell` exactly once, and end the final output at the
      replacement's last active frame. No final-frame padding, loop, freeze,
      black filler, or `atempo` is allowed. Recalculate the source-to-output
      mapping from the effective replacement duration. Never register or send
      the video to Image Gen/Seedance. Full-black media or a missing active
      interval blocks. Preserve and report internal black intervals rather than
      trimming them. A transition is complete only when a transition render
      receipt binds the rendered result to the exact source-shell SHA-256 and
      current final MP4 SHA-256; a stale receipt or metadata-only
      `transition_shell_applied` flag is insufficient.
    - A missing `tail_video` uses `omit_source_end_card`: exclude the complete
      source tail-card interval from text script, storyboards, selling-point
      mapping, Seedance prompt/assets, paid generation, and final assembly.
      End at the preceding source-body last active frame; do not render the tail
      entry transition or add filler, black frames, a freeze frame, Logo, or
      synthetic download animation.
    - A supplied target UI video is `opaque_ui_demo`: remove source UI pixels
      and splice the user video under the source `transition_shell`. Trim only
      leading and trailing black padding from video and audio together, reset
      timestamps without changing playback rate, preserve its active-content duration
      and all retained internal pixels/audio/animation, then recalculate the source-to-output mapping
      and every downstream timestamp
      from the effective duration. Use no final-frame padding, no audio padding,
      no atempo, loop, freeze, time stretch, OCR, redraw, or semantic rewrite;
      Block when the opaque media is missing, has no active content, or
      lacks the required transition evidence. Resolve display rotation metadata
      and use the explicit opaque audio policy: `opaque_audio_keep` is the
      default and requires target audio; `silence_allowed` may inject only a
      bounded silent stream. Source-voiceover preservation with target audio
      uses the bundled immutable `evidence_bound_mix` compositor and fails
      closed unless its renderer-produced final-bound receipt validates. The
      bundled `server.audio_route_guard` runs at compositor admission: in an
      active `high_fidelity_hybrid_v1` run it compares frozen ASR speech windows
      with every supplied opaque UI/tail interval and raises
      `AUDIO_LAYER_POLICY_REQUIRED` unless the region has a current pre-bound
      receipt or the renderer explicitly declares bundled mixer support. It
      never fabricates a mix, re-records speech, or treats an opaque clip as
      proof that source voiceover survived. Source-origin intervals and an
      explicitly omitted source tail remain compatible; the guard summary is
      persisted in the timeline manifest when the route passes.
      first and judge aspect from display dimensions rather than the encoded
      raster dimensions. A centered cover crop is allowed only within the 12%
      safe cover-crop limit; a larger crop or visible black padding blocks the
      run. Force the normalized compositor output sample aspect ratio to `1:1`
      before any xfade/concat; use an explicit high-fidelity `CRF=18`/`veryfast`
      intermediate encode and retain the input SAR only as provenance.
      Preserve every internal operation and internal black interval; never trim
      the middle of the UI demonstration. Require the same transition render
      receipt, source-shell SHA-256, and current final MP4 SHA-256 binding at
      entry and exit.
    - **UI-only frame-locked rebuild.** `opaque_ui_demo always wins`: when a
      user supplies `ui_operation_video`, retain the opaque route above and do
      not classify, redraw, OCR, or reinterpret its body. When no UI operation
      video is supplied, a source UI Cut may use `generated_ui_demo` for a
      populated `ui_screenshot` or `app_store_url`, or for an eligible
      `new_product_image`/`new_model_image` replacement or `output_language`
      localization. The generated UI region preserves the exact source
      transition shell at both entry and exit.
    - Each rebuilt UI Cut carries one immutable
      `source-ui-interaction/v1` contract. It freezes the source time and
      frame windows, viewport, language decision, and only the supported
      interaction classes (`drag`, `scroll`, `bounce`, `scale`, `rotate`,
      `opacity`, `tap`). Motion capture is `ui_roi_only` and
      `source_frame_locked`: drag, scroll, bounce, scale, rotation, opacity,
      and tap timing must follow the source frames without retiming or
      reinterpreting the interaction. The deterministic renderer validates the
      contract and its SHA-256 before it reads target evidence.
    - `ui_screenshot` and parsed official App evidence remain first-choice
      target UI evidence. With the frame-locked contract and no such UI
      evidence, `new_product_image` is preferred and `new_model_image` is the
      fallback solely as authorized replacement evidence. They never authorize
      renderer-authored UI copy: readable target text and layout must still be
      present in immutable target evidence or an approved UI page/state
      contract. For an `app_store_url`, the existing
      `parse_app_store_evidence` stage runs before `resolve_ui_evidence` and
      publishes the verified ordered `app_store_screenshot` artifact. The
      first UI evidence boundary may derive a one-state truth card from the
      exact target image with the independent bound OCR backend; this is
      evidence derivation, not renderer-authored truth. The truth card (copy,
      state order, and layout) is then immutable.
    - UI text preserves the source UI language when `output_language` is
      absent; when it is present, that language is the target for all visible
      UI copy. The render contract carries UTF-8 encoding with replacement
      glyphs forbidden. Any `?` replacement character, U+FFFD, pseudo-text,
      unreadable text, wrong layout/state, or unverified target copy blocks the
      UI interval. The renderer receives and echoes truth only; it may not
      create, revise, or self-authorise it.
    - UI analysis is limited to the already identified UI ROI and its frozen
      source frames. Validation is basic-anchor-only at the source first/last
      frames plus the existing declared UI states: no full-video deep analysis,
      no deep QA, and no automatic retry are introduced by this route. The UI
      rebuild does not create storyboard, Image Gen, or Seedance work; UI
      pixels, text, and interaction facts never enter Seedance.
    - **Fast UI acceptance profile.** Generated UI defaults to
      `fast_lightweight_v1`: one render attempt per immutable request, a 90%
      visual-motion/appearance target, and up to 20% non-text visual deviation
      is acceptable. It never spends paid or local render time on A/B variants,
      deep similarity scoring, or self-retry for that deviation. Motion
      estimation remains inside the frozen UI ROI, uses a bounded 480-pixel
      working edge before mapping vectors back to the source frame clock, and
      CPU rendering uses no more than two concurrent workers. Exact visible
      target text is intentionally separate: UTF-8 text, approved copy, and
      absence of replacement/placeholder glyphs remain 100% required.
    - **UI Sidecar retention.** After `run_qc` has passed and the final MP4 is
      successfully promoted, USFR binds every local generated-UI Sidecar request
      SHA to that final-video SHA and starts a fixed 24-hour retention clock.
      At expiry, the Sidecar deletes only its own matching temporary job cache
      (motion frames, UI render output, request/response cache, and receipts).
      It never deletes `final/{job_id}/result.mp4`, source assets, supplied
      opaque UI videos, or another request's directory.
    - When the source has no UI Cut, do not create a generated UI region or a
      source-ui interaction contract. Skip UI ROI analysis, OCR, redraw, and
      retiming entirely; normal non-UI product/model/language routing remains
      unchanged. When a source UI Cut has no UI replacement trigger, use
      `source_ui_keep` with `media_origin=source_interval` and
      `assembly_policy=splice_source_interval`.
    - Run the bundled overlay module only for intervals that remain semantic
      overlays; never inspect opaque media content. If a semantic overlay layer
      is declared but no validated overlay render mapping exists, block before
      assembly instead of silently dropping the source headline, subtitle,
      Logo/wordmark, CTA, or graphic layer.

 5. **Analyze weighted commercial intent**
    - If the validated timeline contains zero generated semantic regions, record
      the intent/voiceover/Seedance work as `skipped` in the existing timing
      ledger and take the local-only assembly/QC branch; do not spend a second
      semantic pass on facts that cannot affect the output. Go directly to the
      existing assembly/QC work with no reverse script, no storyboard, no Image
      Gen, no Invocation A/B, no CreateAsset, and no CreateVideo.
    - Use the bundled intent contract once. Weights must total 100 and map the
      source's commercial goal, attention hook, adult creator appeal when evidenced,
      product proof, emotional promise, trust, CTA, pacing, and compliance to Cuts.
    - Express each target selling point as `Feature → Mechanism → Benefit →
      Proof → CTA` in `selling_point_mapping.json`. Mark an unsupported source
      claim `unsupported`, lower it, or remove it; never invent a mechanism,
      result, review, statistic, or guarantee.
   - Keep reasoning concise and evidence-led. Do not infer sexual intent from
     appearance alone; preserve only non-explicit, adult, platform-compliant cues.
   - For the active profile, project the Source Intent Graph, Target Value Graph,
     claim atoms, affordance ledger, and layer ledger into the existing intent
     and selling-point contracts; unsupported claims are never script-eligible.

6. **Build or validate the replacement script**
   - Preserve every non-excluded source Cut's timing, action function, camera,
     transition, sound role, and weighted intent.
   - Replace identity/product/UI truth only for populated fixed slots. Absent
     slots remain source-preserve KEEP evidence.
   - If no populated slot changes a Cut's visible layer, assign that Cut
     `media_origin=source_interval` and
     `assembly_policy=splice_source_interval`; generate only Cuts actually
     affected by a supplied replacement slot.
   - `opaque_ui_demo`, `source_ui_keep`, and
     `excluded_app_end_card`/`omit_source_end_card` intervals do not appear
     as generated Cuts.
   - For `high_fidelity_hybrid_v1`, run non-provider Seedance-20 Invocation A
     here and freeze its candidate-region, fidelity-budget, reference-role, and
     exact line/audio sidecar before the existing Route 2 script gate (or as
     read-only enrichment for Route 1).
   - The canonical server bridge may use
     `server/high_fidelity_projection.py` to derive the exact Invocation-A
     request from the already validated analysis artifact and fixed-slot
     digests. A caller-supplied request remains authoritative only when it
     already satisfies the same strict signature and factor coverage.
   - Route 2 stops for **确认反解分镜脚本**.

 7. **Plan generated regions**
    - Apply the bundled duration planner only to contiguous generated regions;
      source-origin KEEP intervals are assembled server-side from verified
      object-store references and consume no
      storyboard or Seedance slot.
    - After the applicable script approval, freeze the final Stage-7 segment
      plan with one or two ordered `4-15s` generated segments. Each segment
      carries `segment_id`, output-global integer `start_ms`/`end_ms`, derived
      `duration_ms`, and the exact ordered Cut IDs. Pass that immutable plan to
      Invocation B; a missing plan, changed Cut coverage, overlap, duration
      mismatch, or line/proof/Foley/silence window crossing blocks before
      prompt compilation.
    - Invocation B performs the deterministic global-to-segment-local rebind
      through the bundled exact-line contract. A caller may omit final line
      rows and let the adapter inject the rebound rows; if rows are supplied,
      their segment-local coordinates must exactly match the deterministic
      rebind. Global-time or independently edited rows are invalid.
    - Keep a maximum of two generated regions, boards, and Seedance tasks.
    - Opaque UI and supplied tail-card media never consume an Image Gen or
      Seedance task/image slot. Dependency-locked regions stay ordered; all
      independent asset and segment work may run concurrently.

 8. **Generate and approve storyboards**
    - Load and compile the exact bundled `references/daohuo_storyboard_prompt.md` bytes before every storyboard generation. Bind its SHA-256 into the prompt, layout receipt, storyboard metadata, and approval artifact; no fallback prompt or renderer-authored replacement is permitted. Then use RunningHub image2
      client. Keep the required `16:9`, `2k`, `medium` settings and real model-
      generated Cut scenes.
    - Image2 produces only the ordered Cut visual sheet from the replacement-control sheet. The server then renders the fixed five-region professional approval board deterministically; generated Cut scenes remain real Image2 pixels.
    - Publish both `director_board_approval.png` and `seedance_visual_carrier.png` plus the validated layout receipt. They must have distinct SHA-256 values and mutual lineage.
    - Reject generic grids, the obsolete five-region information board, missing template SHA, missing required cinematic-production regions, wrong Cut-card count/order, missing layout receipt, or an execution carrier not bound to the approved `storyboard_grid` visual layer.
    - Derived source contact sheets or boundary frames may carry only structure,
      timing, camera, or environment evidence. Source identity, brand, UI, or text
      must not leak into an authorized replacement board or fixed-B asset map.
   - Stop for **确认故事板** after every new or revised board. This storyboard
     approval triggers autonomous Seedance compilation, submission, provider
     waiting, assembly, and QC.

 9. **Compile and audit the exact RunningHub Standard Model request internally**
    - After the latest storyboard approval, freeze `seedance_input_contract.json`.
      Recompile the final prompt through `seedance-20`, then build exactly one
      unauthorised pre-submit dry-run payload for that prompt version. Do not
      pass `--approved-request-sha256` on the dry run.
    - Upload the layout-validated `seedance_visual_carrier` and populated target reference images from
      the fixed slot manifest with RunningHub Standard Model binary upload. Every
      source-fidelity generated run also uploads exactly the matching current
      2-15 second original source segment as `videoUrls[0]`, bound by
      `usfr-video-reference/v1` to source/slice SHA-256 values, the frozen
      segment window, the approved-board-bound execution carrier at `@Image1`, and at least one target change.
      Source keyframe sheets and replacement-control sheets are never uploaded to
      Seedance; they are used only upstream to generate the director board. Opaque UI media
      and tail media remain forbidden. For a local source file, provide the
      frozen `segment_plan` to `runninghub_seedance_submit.py` with
      `--source-video-file`, `--segment-plan-file`, and `--segment-id`; it uses
      the complete source only when that file exactly equals the permitted
      window, otherwise it creates and reuses the matching FFmpeg slice before
      upload. RunningHub media upload is never automatically
      retried after a 429, 5xx, timeout, connection reset, or ambiguous response.
   - Build the complete prompt under 5000 characters and run dry-run.
   - Build the internal `seedance-20` request, redacted payload, and SHA-256.
    - Load only the factor-specific specialists selected by the immutable Skill
      route (`seedance-characters`, `seedance-camera`, `seedance-motion`,
      `seedance-lighting`, `seedance-audio`, or `seedance-sequence`). The root
      `seedance-20`, `seedance-prompt`, and `seedance-antislop` checks are always
      mandatory for a generated region.
      The compiler recomputes those checks from the structured segment, exact
      line contract, route exclusions, anti-slop rules, and immutable packaged
      Skill bytes; caller-supplied boolean flags are declarations only and
      cannot authorize a prompt. The resulting `rule_audit` records the root
      Skill SHA and recomputed check digest.
    - Run the script-to-prompt parity audit and compare approved Cut order,
      character lock, product lock, duration/timecodes,
      voiceover/audio, camera/actions/transitions, continuity, selling-point
      evidence, timeline-region routing, reference mapping, provider parameters,
      and negative constraints. Require zero ambiguity and no unresolved
      placeholders. Enter **internal request integrity approval** only after all
      checks pass; this is not a third user approval gate.
    - Invocation B must use the same packaged Seedance-20 snapshot as A and
      repeat every approved line, speaker, locale, time, proof, Foley, and
      silence window exactly. Its request must carry the frozen Stage-7
      `segment_plan`; the adapter records its canonical SHA-256 and compiles
      only the current segment's deterministically rebound local-time rows. A
      missing/invalid plan, snapshot mismatch, boundary crossing, or
      line-contract mutation blocks before CreateAsset/CreateVideo.
    - Submit the unchanged dry-run request only with
      `--approved-request-sha256 <dry-run-request-sha256>`. The parity audit,
      frozen input contract, and packaged Skill digest remain server-side
      integrity evidence and are not submitter flags.
    - Prompt-only repair stays inside this internal gate. A change to the
      approved script, storyboard, assets, or routes returns only to the existing
      relevant script/storyboard approval gate.

10. **Generate and resume safely**
    - Submit only the internally audited and validated digest.
    - The paid adapter uses `create_video(request)` with the exact canonical
      audited provider payload. A no-argument adapter is legacy compatibility
      only and cannot coexist with segmented mode in the same Run. Segment
      membership comes only from the canonical `segment_plan` JSON and its
      `segment_plan_sha256`; duplicate, missing, or extra Segment IDs fail
      closed before submission or assembly.
    - Save task IDs and raw responses. A plain `--resume-task-id` is a separate
      known-task route: it does not require a new prompt or duration, performs no
      asset preparation or payload build, and cannot carry new-request
      authorization, audit, script, or input-contract flags. It cannot be
      combined with `--dry-run`. Resume known IDs
      instead of creating duplicate paid tasks. Never silently retry an
      ambiguous provider failure.
    - Paid Seedance create is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. Preserve the exact audited request and reconcile provider state; resume only when a task ID is known. Query only a returned task ID, then download the successful MP4 immediately before its result URL expires.
    - For a one-or-two-Segment plan, submit every missing Segment intent in
      frozen plan order before polling. The first successful Segment remains
      in `PROVIDER_RUNNING`; only the exact complete successful Segment set may
      enter assembly. `/resume` and reconciliation accept explicit `intent_id`
      and `segment_id`; all ambiguous Segment intents must be reconciled before
      the blocker clears.

 11. **Assemble final video**
    - Standard route: use the bundled ordinary concatenation workflow.
    - Opaque/source-media route: write generated media paths and deterministic
      source interval paths into
      `analysis/timeline_regions.json`, then run the bundled
      `scripts/timeline_splice.py`. Supplied UI replaces its source UI interval,
      preserves its effective active-content duration, and shifts every later
      output boundary by the resulting duration delta; it never waits for the
      removed source interval or receives video/audio padding. A supplied tail
      video replaces the source tail-card region at its entry
      boundary after automatic leading/trailing black trim, while an absent tail
      video omits the source tail interval completely. The replacement's
      effective active duration is the final terminal authority; no source-
      duration wait, padding, loop, freeze, or black filler is permitted.
      Use decoded video stream duration—not container/audio overhang—as the
      source-to-output and final-frame authority. Aspect and crop checks use
      rotation-corrected display dimensions (not encoded width/height), and a
      rotation that changes display geometry must be re-encoded rather than
      stream-copied.
    - When the profile is active, validate the immutable layer/audio compositor
      manifest first and use FFmpeg as the default backend; optional HyperFrames
      or Remotion adapters require a passing benchmark.
      The injected renderer is the complete timeline carrier for every
      non-source region. The bundle includes
      `server.timeline_renderer.BundledTimelineRenderer`, which wraps the
      canonical FFmpeg timeline-splice implementation and resolves media only
      through the lease-owned context; deployments may inject it directly or a
      receipt-compatible sidecar. A semantic overlay renderer cannot substitute
      for generated/opaque timeline assembly; if a non-source region is present
      and no complete timeline renderer is configured, fail closed with
      `compositor timeline renderer is not configured for non-source regions`.
      The bundled overlay renderer remains a source-origin-only layer pass.
      The production loader accepts only absolute paths to bundled timeline and
      concat dependencies; relative, external, or workstation paths fail closed.
      Frozen Segments and Cuts form one unique ordered global closed set, and
      ordinary generated media cannot bypass exact Segment/Cut bindings.
      Provider video, ordinary generated video, generated UI, opaque UI, and
      tail-media carriers use natural decoded media duration: no padding,
      freeze, loop, or hidden retime. Per-Segment audio/video boundaries align
      before concat. Every non-source carrier and every declared source
      transition needs an exact
      final-output-bound receipt tied to its slot/artifact, Segment, plan digest,
      canonical source shell, and current final MP4 SHA-256. Source and omitted
      routes reject any media binding; manifest route, placement, and omission
      sets are exact.
    - Do not use FFmpeg `xfade=transition=dissolve` for mixed-codec production
      inputs: it can emit full-frame pixel noise despite normalized scale/SAR/
      fps/timebase. Render a linear dissolve with trimmed overlap streams, an
      alpha-ramped overlay, and deterministic concat; preserve exact source
      duration/transition receipts and fail closed for unsupported transition
      families.
    - A missing UI target is not a blocker when all UI slots are absent:
      source UI is spliced server-side from its verified source interval. A
      missing opaque UI video is a blocker only
      when the manifest says that supplied route was selected.

12. **Final QC and delivery**
    - Verify MP4 video/audio streams, dimensions, fps, duration, Cut order,
      character/product consistency, audio presence, and timeline placement.
    - Run boundary-aware black QC over every splice/transition window; one full
      black frame at a splice boundary, or any longer splice-boundary black
      interval, blocks delivery even when it is internal rather than leading or
      trailing media.
    - Missing required video/audio streams, `VIDEO_ENDS_BEFORE_AUDIO`,
      `AUDIO_VIDEO_DURATION_DRIFT`, `AUDIO_VIDEO_START_OFFSET`, or a
      missing/invalid transition render receipt is a technical hard failure.
      Decode-level `freezedetect` evidence is also recorded. A freeze becomes a
      hard failure only when the compositor manifest proves a generated/opaque
      carrier could have introduced it at an output edge or splice; static
      source shots and user-uploaded static tail/UI holds remain allowed only
      inside their input-lineage placement windows.
    - For opaque slices, QC only technical placement and stream integrity; do not
      semantically inspect their content.
    - Save `qc_report.json`, `timing_log.json`, request/response provenance, final
      SHA256, and `final/result.mp4`. In a server deployment, this is a logical
      artifact name; delivery is artifact metadata + signed download, never a
      client-local path.
    - If the profile is active, append the weighted high-fidelity QC extension
      (total >=85, high-criticality >=90, route/timeline 100%, UI OCR 100%, no
      hard failure) without changing the legacy QC schema or delivery artifact.
      Active production rejects a technical-only `passed=true`: the QC adapter
      must return the evidence-bearing weighted high-fidelity QC extension,
      its score must be recomputed by the packaged validator, and its non-empty
      factor set must pass every hard gate before publication. Every dimension
      and factor requires evidence whose target reference binds the actual
      final MP4 SHA-256; every source reference must resolve to an immutable
      input or upstream evidence artifact owned by the same Run. Structurally
      valid but stale or foreign evidence fails closed.
    - Active production requires every production QC StagePort (including
      `FfmpegQcEngine`) to call a deployment-injected evaluator on the inspected
      final media. Its result must preserve `qc_evaluator_response` and a
      receipt whose canonical request/response SHA, evaluator/model identity,
      final-output/source SHA set, and dimensions/factor digests match the bytes
      and evidence actually used. A real HTTPS semantic evaluator remains a
      deployment dependency; the bundled package does not claim a local
      comparator. Missing evaluator, missing receipt, or stale evidence blocks
      the existing QC stage. The receipt is persisted inside the weighted
      extension; a blocked report is diagnostic only and is never published as
      a passing technical-only artifact. Shadow, legacy, and explicit
      local-development paths retain their compatibility behavior and are not
      activation evidence for this gate.
      The bundled transport reference is
      `server.vision_backends.EvidenceBoundHttpSemanticQcEvaluator`; configure
      it from `USFR_QC_EVALUATOR_ENDPOINT`,
      `USFR_QC_EVALUATOR_MODEL_ID`, and `USFR_QC_EVALUATOR_MODEL_SHA256`.
      It sends `media_base64` and optional sampled-evidence bytes over the
      private HTTPS boundary and never sends a worker path. It validates the
      evaluator receipt before returning `qc_input` to the existing QC engine;
      a supplied request payload is compared exactly with the actual
      final/source/input artifact digests before transport; it is an adapter
      contract, not a bundled semantic model.

## Approval Gates

Only these two approval types are permitted:

- Route 2 only: **确认反解分镜脚本**.
- Route 1: **确认故事板** only.
- Route 2: **确认反解分镜脚本**, then **确认故事板**.

The contract phrase `storyboard approval triggers autonomous Seedance` means
storyboard approval triggers autonomous Seedance compilation, submission, provider
waiting, assembly, and QC. Prompt, image mapping, duration, model, ratio, and
payload checks remain internal integrity gates. Preserve the duplicate paid-task
safety rule: resume known task IDs and never create a duplicate submission.
No paid task before exact internal parity/integrity audit; this is an internal
integrity gate, not user approval.

## Performance Target and Critical Path

The factory has a **30-minute production target** for a standard run; this is a
throughput target, **not a cancellation deadline**. Preserve quality and parity
by using single-pass probes, cached contracts/assets, safe parallel work where
dependencies permit, and separate provider timing. Never cancel a valid provider
wait merely because the target has elapsed.

The speed design is fixed: one deterministic slot bind, one deterministic probe
and one semantic pass, cached contracts/assets, independent asset and segment work concurrent, and
dependency-locked work ordered. Compile once per `seedance-20` prompt version
and run one dry-run per version; perform local deterministic parity checks
afterward. The RunningHub Standard Model route is fixed to
`seedance-2.0-fast-token`, `720p`, `9:16`, and no legacy `reference_audios`
field. Every source-fidelity generated fixed-B request uses only the matching
original source segment at `videoUrls[0]` under `usfr-video-reference/v1`, the
approved-board-bound `seedance_visual_carrier` at `imageUrls[0]` / `@Image1`,
and only fixed-slot target references afterward. The approved director board,
source/control sheets, and layout receipt are forbidden Provider inputs. It has
a non-empty authorized target change. One
duration-bounded `audioUrls` item is
permitted only for the approved `background_music` extension, which must render
as `@Audio1` and remain bound to its music execution contract. Resume known task
IDs and never create duplicate paid tasks.

`probe_source` is the deterministic probe cache boundary. Its verified output
must carry the source SHA-256, duration, dimensions, and frame-rate fields;
later StageContexts expose that completed output to dynamics analysis. The
bundled FFmpeg dynamics adapter validates the source SHA/duration/fps and
reuses the payload, performing a fresh `ffprobe` only when the cache is absent.
A present but stale or malformed probe blocks the stage rather than silently
re-probing changed media. This is an internal optimization within the existing
stages and does not change approvals, job-state semantics, or Provider task limits. The
completed `analyze_dynamics` response (source dynamics plus its audio contract)
is likewise exposed as a read-only `stage_outputs` entry to the existing
`build_script` stage. `high_fidelity_projection` consumes that entry before
requesting a second materialization, so Invocation A/B share the same
analysis pass and no deployment handler needs to repeat VLM/ASR work.
The successful response contains only `final/result.mp4`.

### Production timing transitions

Use `scripts/production_timing.py` for every run and persist to the run's
`timing_log.json`:

- Construct `ProductionTiming` with the same log path and call `start()` before
  the first input probe. On resume, reuse that log; `start()` preserves the
  original start time and never restarts elapsed accounting.
- Pause/resume active accounting only around the two user waits:
  `pause_approval("script")` immediately before a reverse-script approval wait
  and `resume_approval("script")` immediately after it; likewise use
  `pause_approval("storyboard")` / `resume_approval("storyboard")` only around
  the storyboard approval wait. Do not exclude any other work or wait.
- Wrap each RunningHub image2 wait and RunningHub Standard Model Seedance wait with
  `start_stage(<stage-name>, provider=True)` and `end_stage(<stage-name>)`.
  Provider stages remain included in active processing and are also totaled
  separately as provider time.
- Invocation-A profile samples are nested observations inside the existing
  `build_script` stage; recording them must not open a new stage or be rejected
  merely because the enclosing stage is still running.
- Call `finish()` only after final MP4 QC. The 1800-second target is measurement only:
  a false `target_met` value never raises, cancels, or shortens a valid
  provider wait.
- Every transition is atomically persisted. Treat nested approval pauses,
  overlapping stages, resume-without-pause, and finish-without-start as invalid
  state instead of silently repairing or resetting the ledger.

## Time And Reasoning Budget

- One deterministic slot-binding pass and one deterministic parser/probe pass per input.
- One concise semantic pass over selected source evidence.
- Reuse every valid cached contract and asset manifest.
- Do not analyze `opaque_ui_demo` or supplied App tail-card contents.
- Do not repeat full-video inspection unless validation fails.
- Record wall-clock seconds and status for every stage, including skipped,
  optional, failed, approval-waiting, and resumed stages.

## Delivery Contract

After successful QC, the successful final response contains only final/result.mp4
as the logical delivered video artifact. The server returns artifact metadata +
signed download for that object; it does not require the user's local path. Do
not emit routine post-storyboard progress,
request previews, timing logs, or internal digests. The contract phrase
`blocker messages are allowed only when delivery cannot continue` is normative.

## Failure Boundary

Stop before a formal run when `source_video` or at least one valid optional
slot is missing. Stop without a new paid task when the object-store completion
adapter is unavailable for object references, credentials, required target
evidence for a selected generated route, asset registration, storyboard
approval, internal prompt/digest integrity validation, provider status, slice
duration, or timeline coverage is invalid. Preserve raw errors and recommend the
smallest next action. Never hide a failure with a collage, placeholder UI, black
frames, generated Logo animation, or duplicate submission.

## Optional `high_fidelity_hybrid_v1` profile

This is an additive internal execution profile based on the design snapshot
`2026-07-17-universal-high-fidelity-hybrid-seedance20-dual-stage-design.md`;
the deployable runtime authority is `references/high-fidelity-hybrid-v1.md`.
It does not change the seven fixed slots, two routes, twelve semantic
stages, two user approvals, fixed-B payload, or two-task limit. The bundled
`analyze-reference-video-dynamics` module performs one deep source pass and
`replicate-source-ui-overlays` freezes overlay geometry. A cached optional
`analysis/high_fidelity_analysis.json` adds a Source Intent Graph, Target Value
Graph, claim atoms, affordance ledger, and layer ledger; the legacy nine-key
intent weights remain integer values totaling 100.

That single pass also builds and validates the packaged adaptive evidence plan:
complete-timeline coverage, Cut-boundary neighborhoods, adaptive keyframes,
detail-crop triggers, and separate audio transcription evidence. The plan is
passed to the semantic backend and its digest is retained with the source
evidence; it does not add a stage or repeat full-video analysis.

The worker joins those strict semantic fields with raw dynamics, ASR/audio,
and timeline evidence through the internal `high-fidelity-analysis-envelope`.
Each nested contract is validated independently, its component and current-run
parent digests are checked, and the envelope carries one immutable
`projection_sha256`. Raw dynamics cannot be treated as high-fidelity analysis
by schema coincidence. Invocation A and B use that same digest and the
same rich shot/factor projection; a changed shot field, factor set, Cut order,
or segment binding fails before prompt compilation or a paid request.

Inside existing Stages 5–6, Seedance-20 **Invocation A** is a non-provider
executability/compiler pass. It uses the same packaged skill snapshot as B and
writes `analysis/seedance20_prescript_v1.json`, allocating one primary fidelity
spend per generated region, no more than two regions/four image roles, exact
speaker/locale/line timing, proof/Foley/silence windows, and action endpoints.
Route 1 is read-only; Route 2 can receive only evidence-bounded copy proposals
before the existing script approval. Local-only and opaque-only runs record A/B
as `skipped` in `timing_log.json` and skip semantic work that cannot affect
assembly.

After the existing storyboard approval, Invocation B must recompile the final
prompt through the packaged `seedance-20` skill, compare the same byte SHA and
all approved Cut/character/product/duration/voiceover/route factors, then run
the unchanged dry-run and 13-check internal integrity audit. Prompt-only repair
is allowed only when exact line and frozen digests remain unchanged. Production
workers package the dependency snapshot; `~/.codex/skills` is never deployment
authority.

Stage 11 may use the deterministic `hybrid_compositor.py` contract with FFmpeg
as the default backend. HyperFrames is enabled only for benchmarked complex
HTML/UI renders, Remotion stays opt-in, and MediaBunny is upload preflight. The
optional high-fidelity QC extension requires total score >=85, every
high-criticality factor >=90, route/timeline 100%, UI OCR 100%, and no hard
failure. Run `scripts/run_high_fidelity_shadow.py` over the bundled golden-case
matrix before activation and compare same-case baseline/candidate reports with
`scripts/compare_high_fidelity_runs.py`; these tools never create provider
tasks. Persist the weighted report as the existing QC extension sidecar (or
strict-schema-compatible `qc_report.json` projection); do not replace the
legacy report or public delivery artifact. Legacy runs without a profile
snapshot continue unchanged.

The compositor's immutable timeline manifest is the output-clock authority for
QC. When supplied UI/tail media changes the effective duration, QC compares the
decoded assembled streams with the manifest duration rather than forcing the
source-region sum. The final black scan uses a half-frame threshold so a single
black flash cannot pass; the same receipt records low-resolution `freezedetect`
intervals and output/input lineage allowlists. Stream start timestamps are
checked separately from total duration, so a delayed microphone track cannot be
silently re-zeroed by normalization. Transition mappings are exact-only: the default FFmpeg
backend must fail closed for `radial_zoom_blur`, `zoom_out`, and `zoom_back`
until dedicated renderers are injected; `hblur` or a plain fade is never an
equivalent success claim.

### Skill substitution and routing policy

Use the smallest proven module that improves fidelity without adding a stage or
local dependency:

- default source pass: `analyze-reference-video-dynamics`;
- timed semantic overlays: `replicate-source-ui-overlays`;
- App Store URL evidence: bundled `parse-app-store-evidence` exactly once only
  when a generated UI/target-evidence carrier can consume it; the validated
  zero-generated-region branch skips the fetch and parser entirely;
- final Seedance prompt/audit: `seedance-20`, `seedance-prompt`, and
  `seedance-antislop` (camera/motion/lighting/characters/audio subskills only
  when the contract contains that factor);
- deterministic assembly/QC: FFmpeg compositor and the existing splice path;
- `hyperframes` only for benchmarked complex generated HTML/UI graphics;
  `remotion` is disabled by default, `video-use` contributes only boundary/QC
  checks, and `mediabunny` is upload preflight rather than the server
  compositor.

Any alternative backend must pass the same-case quality and latency gates before
activation; otherwise the FFmpeg path remains authoritative.

### Source decomposition and prompt projection contract

The profile's fidelity gain comes from one evidence pass becoming more
specific, not from repeatedly asking a model to analyze the video. The bundled
dynamics module and its high-fidelity extension must cover each semantic Cut
with scene topology and normalized anchors; camera phases and framing
migration; light origin/vector, hardness, contrast, and temperature; posture,
gaze, expression, gesture, and microphone relationship; hand ownership,
contact points, object state sequence, proof event, and a completed endpoint;
exact speech/audio events, delivery/lip-sync risk, Foley, ambience, music, and
meaningful silence; and evidence ID, frame/time/audio anchor, provenance,
confidence, uncertainty, and blocker threshold. Opaque UI, source-origin UI,
and App-tail intervals carry technical boundaries and transition-shell data
only, never semantic UI, identity, OCR, claims, or source voice truth.

For an active `high_fidelity_hybrid_v1` run, the single semantic pass must
retain `extensions.high_fidelity_hybrid_v1` in `source_dynamics_analysis` and
the packaged high-fidelity extension validator must pass. A non-empty Cut list
or a status-only VLM response is not sufficient. Invocation A candidate
regions must carry a unique, non-empty `required_factor_ids` set and an exact
`factor_coverage` row for every ID; missing, extra, or unassigned factors fail
closed before any provider intent.

The active VLM evidence boundary is also temporal, not only cryptographic:
the server maps each referenced frame SHA back to the exact decoded sample
timestamps sent to the model and verifies that the reference lies inside its
own source/semantic Cut. Repeated identical frames across Cut boundaries are
treated as ambiguous unless the sidecar supplies the matching `timestamp_us`.
If the configured frame budget cannot place a sample inside every source Cut,
the active run fails closed before a semantic request is accepted. Shadow and
legacy adapters retain their compatibility behavior, but their evidence is not
eligible for production high-fidelity activation.

`scripts/skill_router.py` converts those frozen factors into a deterministic,
cacheable module route. It selects only the needed Seedance specialists:
`seedance-characters` for identity/performance, `seedance-camera` for
framing, `seedance-motion` for action physics/endpoints, `seedance-lighting`
for light/shadow, `seedance-audio` for dialogue/Foley/silence, and
`seedance-style`/`seedance-vfx` only when those factors are explicitly
evidenced, and `seedance-sequence` when two generated regions or multi-shot
continuity need a handoff. Generated regions always include the root `seedance-20`,
`seedance-prompt`, and `seedance-antislop`; no specialist is loaded merely
because it exists. The route emits package-relative paths and an exact digest,
never a workstation path.

The prompt projection remains inside the existing stages:

1. **Invocation A (pre-script):** run the root `seedance-20` skill plus the
   selected specialists as a non-provider executability pass. Allocate one
   primary fidelity spend per candidate region, one visible action and
   completed endpoint per shot/phase, at most four image roles, exact line and
   audio windows, and a 5000-character feasibility budget. Route 2 may receive
   evidence-bounded copy proposals before script approval; Route 1 is
   read-only. A never draws readable UI/long text or inspects opaque media.
2. **Invocation B (post-storyboard):** run the packaged root `seedance-20`
   compiler through `scripts/seedance_prompt_compiler.py` with
   `seedance-prompt` and `seedance-antislop` using the exact same
   dependency snapshot as A. Re-emit the approved Cut order,
   character/product locks, timing, exact dialogue, delivery/lip-sync,
   proof/Foley/silence, camera, motion, continuity, and negative constraints,
   then run the existing dry-run/parity/integrity audit. A changed frozen
   field, route-excluded token, unresolved placeholder, or ambiguity blocks
   before a paid call.

For active high-fidelity runs, Invocation B receives a structured segment,
the approved/rebound line contracts, frozen factor flags, and the complete
compiler-check set, or an immutable artifact already produced by that same
packaged compiler. A free-form `compiled_prompt` cannot bypass the packaged
`seedance-20`/`seedance-prompt`/`seedance-antislop` route. The compiler rejects
shot gaps/overlaps, a segment outside 4-15 seconds, a line/proof/Foley/silence
window outside its segment, a changed speaker or millisecond window, and any
declared Cut without either an approved line or explicit `No dialogue`
contract. The route-exclusion gate scans structured mapping keys and string
values, including compiler factors, as well as the final Prompt. Matching is
case-insensitive, separator-folded, camelCase-aware, and token-boundary safe;
an exact compact token is accepted but an unrelated substring is not.
`opaque_ui_demo`, `generated_ui_demo`, `opaque_app_tail_card`,
`excluded_app_end_card`, `omit_source_end_card`, `excluded_region`, and their
UI/tail truth, render, QC, or media carriers are rejected at payload build,
Invocation B, and the final paid-client boundary. The generated UI
remains in the deterministic UI renderer/timeline lane with OCR target 100; it
is never delegated to Seedance semantics or pixels. When a surrounding
person/device shell needs generation, it must be a separate ordinary generated
region and the verified UI is composited afterward.

Each active generated shot must explicitly carry scene topology, camera,
lighting, performance (including gaze/expression/gesture where applicable),
action, completed endpoint, product/UI truth, commercial proof, transition,
continuity, audio, and unique `factor_ids`. The compiled artifact freezes the
union as `required_factor_ids` and `prompt_factor_coverage`; the final prompt
must render every high-criticality field. A coarse action-only shot or a
rehashed prompt with missing factor coverage is invalid.

When the active route is `generated_ui_demo`, the UI capability must publish a
real `video/*` artifact with a non-empty ordered state sequence, per-state
decoded-frame/OCR/layout evidence, independent state-to-state animation
samples, and 100% text/layout checks. Static PNG normalization, anonymous OCR
records, renderer-authored truth, or a summary-only 100% flag are
development-only and fail closed in the active production manifest. If OCR is
run on encoded PNG/JPEG bytes, each state and animation receipt binds both
`decoded_frame_sha256` and the backend `input_sha256`; every animation sample
also binds its interval, decoded frame SHA, OCR/layout records, and records
digests.

The deployable reference binding is `server.vision_backends.EvidenceBoundHttpUiRenderer`:
it sends target-owned image bytes plus the immutable `ui_truth_card` and
`ui_render_contract` to a private HTTPS renderer, receives MP4 bytes and an
ordered state sequence bound to request/source/model/output digests, and lets
the existing independent OCR backend verify every decoded state. Inject it as
`DeterministicUiRenderer(render_backend=...)`; a production worker without a
real video renderer fails startup before leasing work. The fixed deployment
`capabilities` readiness check should include the renderer sidecar.
The bundled `server.real_capabilities.BundledAppStoreEvidenceParser` is the
default handler for the existing `parse_app_store_evidence` stage when a
deployment does not repeat that handler in its stage map. It runs the packaged
official Apple/Google parser once and publishes immutable bundle/screenshot
artifacts before the UI renderer is called; a missing screenshot or failed
download remains a hard evidence blocker.

Prompt-carrier priority is fixed: reference roles and opening state, action and
completed endpoint, exact dialogue/timing, proof/Foley/silence, identity and
product truth, motivated camera/light/sound, continuity handoff, then negative
constraints. Remove generic quality adjectives, duplicate reference prose,
secondary actions, and speculative mood language before removing any of those
high-criticality facts. This is an internal projection rule only; it adds no
user approval or job-state stage.

### Deployment dependency boundary

The router's dependency snapshot contains package-relative logical paths and
requires an exact byte digest at worker startup. Production workers resolve
those paths from the deployed container/bundle or job-private immutable
artifact; they never read `~/.codex/skills`, a client workstation, or a local
run directory as authority. A missing or changed `seedance-20` snapshot or
specialist dependency fails closed through the existing contract/prompt
integrity blocker before `CreateAsset` or `CreateVideo`. A media path created by
`MediaMaterializer` is valid only inside a lease-owned temporary directory and
is never persisted in a run, timeline, artifact, or event.

The bundle's `deployment/Dockerfile`, `deployment/requirements.lock`, and
`server/worker_entrypoint.py` form the service handoff boundary. They build a
versioned worker image and load a deployment-owned queue bootstrap through
`USFR_WORKER_BOOTSTRAP`; missing bootstrap, capability, or model artifacts fail
closed. The image is not a new workflow stage and never creates Provider work
at build time.

The deployment-owned `server/deployment_bootstrap.py` is the executable
service handoff: `USFR_DEPLOYMENT_FACTORY` must point to a packaged
`module:function` returning the service dependencies, worker startup manager,
Redis JobStore, Redis work queue, object store, cleanup sweeper, FastAPI app,
ephemeral worker manager, and readiness checks for Redis, object store, bundle,
models, capabilities, and Provider. It rejects local paths, requires matching
profile/capability snapshots, reconciles `USFR_PROFILE_MODE` (default
`shadow`), calls `EphemeralWorkerManager.validate_startup_capabilities()`
before HTTP serving or worker leasing, requires an immutable bundle resolver,
and exposes `/healthz` plus `/readyz`
probes. HTTP uses the
Uvicorn factory target `build_http_app`; the worker uses
`USFR_WORKER_BOOTSTRAP=server.deployment_bootstrap:run_worker`. Missing
wiring or failed checks fail closed and do not create a job-state stage or
Provider task.

The deployed worker must call stages through `server.provider_ports.StagePort`
with the lease-owned `server.ephemeral_worker.EphemeralStageContext`. The context is
job-scoped and contains only immutable slot descriptors, timeline-region
records, the frozen profile snapshot, and a temporary work directory. A stage
may obtain an ffmpeg/ffprobe path only through `context.materialize_slot()`;
the `MediaMaterializer` rechecks job prefix, completion state, MIME, size,
and SHA-256 and removes the copy when the stage returns. Passing a client path,
an object key directly to a media tool, or writing the ephemeral path into any
artifact is a deployment contract failure.

Generated/provider/intermediate media follows the same boundary through
`context.materialize_artifact(kind, sha256=... or artifact_id=...)`. Production
stages must select the exact immutable artifact digest/identity rather than
the oldest row of a kind. Its Redis artifact record must carry a job-scoped
object key, SHA-256, size/MIME metadata, and a server-minted publication
receipt; the worker rechecks HEAD metadata and streamed bytes
before yielding an ephemeral path. A StagePort cannot self-assert an `s3://`
or `https://` URI plus a hash. Production stage outputs must carry the receipt
from the configured artifact store, and Provider success is blocked until a
verified `provider_video` artifact has been published.
Stage adapters publish their own bytes only through `context.publish_artifact()`;
it mints the immutable artifact identity and receipt instead of accepting a
caller-supplied URI.

After loading the immutable profile snapshot, stage-capability manifest, and
executable `capability_ports` mapping, production workers must call
`EphemeralWorkerManager.validate_startup_capabilities()` before claiming the
first lease. This is a startup validation boundary, not a new job-state stage.

For an active `high_fidelity_hybrid_v1` run, the worker injects
`server.seedance_invocations.SeedanceInvocationAdapter`. `invoke_a()` is called
inside the existing script-building stage and produces the immutable
`seedance20_prescript_v1` sidecar without provider work. `invoke_b()` is called
inside the existing prompt/audit stages after storyboard approval; it validates
the same packaged Skill bytes, exact input/Cut/line digests, route-exclusion
rules, and the 5000-character prompt budget before the existing fixed-B dry-run
and paid-request gate. Neither method adds a stage, approval, slot, or provider
task. A missing or mismatched adapter fails closed; legacy runs with no profile
snapshot keep the unchanged legacy path.

Production injects the packaged root/prompt/anti-slop and selected specialist
files into `SeedanceInvocationAdapter`. The active profile accepts only a
structured `prompt_request` compiled inside the adapter or a validated
`compiled_prompt_artifact`; the raw-prompt compatibility path is legacy/local
only. Compiler output SHA, route SHA, loaded modules, exact line digest, and the
same root-Skill byte SHA are retained for the existing integrity audit.

Before serving an active high-fidelity profile in production, validate the
immutable `stage-capabilities/v1` manifest with
`server.capabilities.validate_stage_capability_manifest`. It must declare the
seven server capabilities: `dynamics_analyzer`, `asr_transcriber`,
`ocr_ui_renderer`, `seedance20_compiler`, `compositor`, `qc_engine`, and
`provider_adapter`, each with a non-local implementation reference, version,
and byte digest. This manifest check is only metadata: the worker must also
inject `capability_ports` and call
`server.capability_ports.validate_runtime_capability_ports`, which verifies the
required callable methods, adapter identity/digest parity, and non-empty
canonical evidence. Direct stages use `CapabilityStagePort`; existing script
and prompt handlers use `BoundStagePort` so Invocation A/B remains inside the
unchanged stage names. A generic callable, status-only sidecar, or capability
label without the validated real adapter fails with the existing
`CONTRACT_INVALID` path before any paid intent. Legacy and explicit
local-development workers retain their compatibility bypass.

The server bridge enforces a 120-second Invocation-A deadline inside the
existing `build_script` stage and records `seedance_invocation_a` status and
duration through the lease-owned timing sink. A timeout blocks that stage and
never creates a paid task; it does not cancel a valid external Provider wait.
Deployments must bind the sink to the existing `ProductionTiming` ledger (or
an equivalent transactional adapter) and publish timing state as an internal
artifact, never as a client-local path. The packaged deployment bootstrap
fails closed before serving or leasing an active/production profile when the
worker manager does not expose a callable lease-owned timing sink; shadow,
legacy, and disabled profiles retain the compatibility bypass.

The same executable mapping must be injected into `ReplicationService` and the
HTTP adapter. Before any durable intent read/create or Provider lookup, call
`server.capability_ports.validate_provider_callable_binding`: `create_asset`,
`create_video`, and `lookup` must be the exact bound methods of the validated
`provider_adapter` instance. An unrelated lambda, partial, mutated adapter
digest, or separately injected Provider client fails before CreateAsset,
CreateVideo, reconciliation, or `/resume` can contact the Provider. Explicit
shadow/legacy and local-development runs keep the compatibility path.

The bound ports must emit canonical evidence, not only a status: dynamics
must include non-empty frame-zero-to-end `source_dynamics_analysis` Cuts; ASR
must include `audio_contract` segments/silence; generated UI must include
`ui_truth_card`, `ui_render_contract`, immutable rendered media, and OCR/layout
both at 100%; Seedance A/B must return the validated artifact/prompt digest;
compositor must return an immutable output artifact and timeline manifest; QC
must return `passed=true` with its report. Empty or status-only sidecars block
publication.

For an active production `high_fidelity_hybrid_v1` run, every nested evidence
record in the high-fidelity analysis must also carry an `artifact_sha256` bound
to a fixed input-slot digest or a previously published upstream artifact. The
server-side Invocation-A projection enforces this binding before prompt or
Provider work; a plausible object key without byte evidence is rejected with
`EVIDENCE_DIGEST_UNBOUND`. Shadow, legacy, and local-development runs retain
their compatibility path. See
`references/high-fidelity-evidence-matrix.md` for the capability evidence
matrix and the boundary between executable proof and contract-only coverage.

The internal `server.ephemeral_driver.EphemeralStageDriver` is the only queue
bridge. API start enqueues the first executable operation; every completed
lease-fenced checkpoint advances the same twelve-stage plan; script and
storyboard approval resume it. It pauses exactly at both approval entries and
never bypasses them. `EphemeralWorkerManager` persists a returned script or
storyboard `RevisionManifest` before the next approval can be reached. A
passing `run_qc` may promote only its identified temporary MP4 to the exact
`final/{job_id}/result.mp4` key and set `SUCCEEDED`; no earlier stage can
publish a final. ACK remains after checkpoint completion, and Provider work
remains behind the frozen Provider-attempt boundary.

The bundled server adapters in `server.real_capabilities` are executable
reference implementations, not status mocks: FFmpeg dynamics owns complete
decoder coverage, production ASR requires either a pinned Whisper model/device
or an evidence-bound ASR adapter, the UI renderer requires exact OCR text and
bounding boxes/layout evidence, and the FFmpeg compositor/QC adapters publish
or inspect real media bytes. Heuristic analysis, pass-through composition,
self-consistency OCR, and synthesized artifact hashes are development-only
and cannot satisfy an active production manifest.

Production OCR/VLM injection uses the bundled evidence-bound interfaces in
`server.vision_backends` (or an interface-compatible deployment adapter).
Media is sent as exact rendered-image or sampled-frame bytes, never as a local
path. The response must bind the request, input/source/frame hashes, and pinned
model SHA. Bare callables and unbound record lists fail closed; consequently
`ocr_match_percent=100` is derived only after independent bound OCR records
match every expected string and bounding box, never from a caller-supplied
score.

Production audio-event injection uses `server.audio_backends` (or an
interface-compatible deployment adapter) alongside the pinned Whisper model.
Production ASR uses either that pinned local Whisper artifact/device or an
evidence-bound ASR adapter whose returned segments bind the exact extracted
WAV, request/response digests, segment digest, and pinned model identity; a
bare transcriber callback is never admissible.
The Foley/ambience/music/meaningful-silence classifier receives the exact
worker-extracted WAV bytes and must bind its response to the request digest,
input SHA, normalized event digest, and pinned model SHA. Its evidence receipt
is returned with the classification result rather than stored in shared mutable
adapter state. A bare audio classifier callable, fabricated event list,
out-of-range timing, or missing event kind fails closed; the resulting audio
contract retains both ASR and audio-event evidence for downstream prompt,
assembly, and QC stages.

### Profile activation gate

The deployable validation authority is `validation/case_catalog.json`: exactly
36 fully configured cases (10 physical product, 10 App, 5 service, 4 brand,
4 creator, and 3 mixed media). Routine changes run impacted coverage tags plus
the fixed six-case smoke set through `scripts/validation_catalog.py`. Cache
reuse requires the exact bundle, fixture, capability, model, and Provider
fingerprint. The complete 36-case matrix is permitted only for an immutable
release-candidate bundle and runs once at final activation.

Keep the profile in shadow mode until the bundled matrix has at least 18 cases,
the compatibility dry-run is 100% green, and at least 12 matched A/B outputs
show an average fidelity gain of >=10 points with no UI/claim regression and
active-time overhead within `min(120 seconds, 10% of baseline)`. Expand to
30–40 cross-category regression cases before making the profile the default for
new runs. Production/default activation must persist these three reports in the
immutable profile snapshot's `activation_evidence` and pass
`validate_activation_evidence`: 18+ no-provider/no-approval shadow cases,
12+ matched A/B cases with >=10 average gain and compatibility/time targets,
and 30–40 passing cross-category regression cases with zero UI/claim/hard
failures. `EphemeralWorkerManager.validate_startup_capabilities()` fails closed
when evidence is absent or stale; explicit shadow/legacy and local-development
runs retain the compatibility bypass. These are deployment gates, not extra
user approvals.
The matched A/B and cross-category reports must be produced with the active
QC evaluator-receipt gate enabled; a technical-only or self-reported weighted
score is not activation evidence.

Production activation evidence uses
`high-fidelity-activation-evidence/v1`: every report is a canonical immutable
artifact with `report_sha256`, a server-minted publication receipt, and a
receipt digest. The server recomputes case counts, zero-provider/approval/task
counters, A/B deltas, compatibility flags, and regression totals from the
recorded cases. Active/default startup must inject the deployment-owned receipt
verifier; a self-attested report, missing verifier, stale receipt, or claimed
aggregate mismatch fails closed. Shadow/legacy/local compatibility bypasses
remain unchanged.

### High-fidelity performance ledger

Invocation A is measured as internal non-provider work in the existing timing
ledger: p50 <=30 seconds, p95 <=60 seconds, and a hard per-invocation timeout
of 120 seconds. Total non-provider active-time increase versus a matched legacy
run is bounded by `min(120 seconds, 10% of baseline)`; approval pauses and
provider wait remain separately reported. Every optional/failed/skipped stage
records a status, duration, and profile revision, and no valid provider wait is
cancelled because the 30-minute value is only a throughput measurement target.
