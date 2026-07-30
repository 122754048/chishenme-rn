# Route 2: Universal Reverse-Storyboard Contract

Use this reference when the fixed input manifest admits a source video and no
internal approved storyboard script. It is reusable across physical products, Apps/digital
products, services, brands, creator stories, performances, tutorials, and
no-product formats, with any supported camera language. It contains no task-
specific identity, product, brand, locale, timecode, or approval result.

## Input responsibilities

- The source video supplies timing, Cut order, scene graph, props, camera,
  atomic actions, transitions, speech/delivery, ambience/Foley/transition audio,
  overlays, continuity, and evidence.
- Populated fixed slots lock only the corresponding authorized target identity,
  product, UI, or App truth.
- When a target slot is absent, keep the corresponding source identity/product/
  UI truth as a Level-0 KEEP/source interval; do not invent a replacement.
- Never promote an unverified source claim to a new target claim, and never
  upload source UI or source tail pixels to a generation provider.

## Analysis rules

1. Probe the complete source from frame zero to the exact decoded end. Record
   dimensions, fps, audio streams, and source hash.
2. Build the `Source Fidelity Contract` before reverse-writing. For each Cut,
   preserve scene graph, props, camera, atomic action graph, speech/delivery,
   ambience/Foley/transition audio, overlays, selling-point logic, continuity,
   evidence, uncertainty, criticality, confidence, and generation route.
3. Label every field `observed`, `inferred`, or `planned`; inferred and planned
   content is never source fact. Use boundary frames and audio evidence rather
   than fixed-second sampling to determine Cuts.
4. Decompose high-level actions into atomic states (for example
   `before → approach → contact → grasp → apply_force → move → reveal → hold`).
   Record contact points, force direction, trajectory, speed, pauses,
   corrections, and end state.
5. Preserve shot scale, lens feel, camera position/path, focus, exposure,
   movement, transition direction/easing, and screen/prop continuity.
6. Record speech words, delivery, breath, pauses, room tone, Foley onsets,
   transition risers, and meaningful silence on the visual timeline.
7. For every target selling point write
   `Feature → Mechanism → Benefit → Proof → CTA` in
   `selling_point_mapping.json`. Unsupported claims are `unsupported`, lowered,
   or removed; never fill them with model guesses.

## App region routing

Locate App intervals from source dynamics, then route them from the fixed input
manifest before writing the script:

- `excluded_app_end_card`: terminal Logo/download-only interval. A supplied
  `tail_video` is opaque replacement media: preserve its internal pixels,
  audio, and animation; apply the source entry transition exactly once; use
  `trim_to_active_content` to trim
  only leading/trailing black padding from video and audio together; reset
  timestamps without changing playback rate; and end at the last active frame.
  Do not add final-frame padding, loop, freeze, black filler, or `atempo`.
  Omit it from the text script, every storyboard, Seedance prompt/assets,
  selling-point mapping, and paid generation duration. If missing, use
  `omit_source_end_card` and remove the complete source tail interval from
  final assembly. Never register or send it to Image Gen/Seedance.
- `opaque_ui_demo`: interactive UI interval with a supplied target UI video.
  Exclude source UI semantics, splice the target video under the source
  `transition_shell`, and block if opaque media is missing or unrepairable.
- `generated_ui_demo`: interactive UI interval without supplied target video.
  Use only when a UI screenshot or App Store URL is populated. Require
  target-owned evidence, `ui_truth_card.json`, and
  `ui_render_contract.json`; prefer deterministic rendering/compositing and
  require OCR 100%. Garbled text, pseudo-text, wrong layout/state, or unsupported
  copy blocks the run.
- `source_ui_keep`: when UI video, screenshot, and App Store URL are all absent,
  keep the source UI interval locally with no OCR, redraw, retime, or provider
  upload.

Do not create generated Cut cards for `excluded_app_end_card`, source-origin
`opaque_ui_demo`, `source_ui_keep`, or `generated_ui_demo`. generated_ui_demo
is excluded from the semantic script and every storyboard; route its approved
UI states, layout, interaction timing, and readable pixels to the deterministic
UI renderer/timeline lane. Only the non-UI device shell, hand, camera, or
character action may remain as an ordinary generated region. generated_ui_demo is excluded from the semantic script and every storyboard. Keep exact source
boundaries, media origin, and transition-shell evidence in
`analysis/timeline_regions.json`.

## Output table

Produce one row per generated/semantic Cut, in source order:

| Cut | time | source scene/camera/action | target replacement | speech/audio | continuity/evidence | route |
|---|---:|---|---|---|---|---|

Each row states the complete visible action and intended result, target identity
and product/UI/service truth, camera and transition, exact spoken line or
`no voiceover`, audio events, negative constraints, evidence references,
confidence, and the selected fidelity level:

- **Level 0** — retain pixels/material/motion and replace only authorized layers.
- **Level 1** — retain structure, performance, rhythm, audio events, and CTA
  placement while replacing target truth (default).
- **Level 2** — retain hook, emotion, selling-point category, CTA, and broad
  pacing; mark the migration `REINTERPRET` and do not claim complete replication.

## Approval boundary

Route 2 stops after the reverse script at the existing script approval gate.
Do not generate storyboards, register assets, or create a Seedance task before
that approval. User edits update the run artifact only; never write task data
back into this reference file.
# Review revision and Route approval matrix

Route approvals are explicit and remain valid across arbitrary review
iterations: Route 2 requires source + script approval; Route 1 requires a valid
approved script in the same task and does not imply storyboard approval; Route
0 is a no-generation/blocker path. Direct edit, instruction-only edit, and
regenerate are distinct review modes. A per-Cut storyboard revision reuses
unchanged neighbors where continuity requires, but invalidates downstream
Prompt, Segment Plan, and provider payload whenever the script SHA, manifest
SHA, ordered Cut SHA list, or Segment Plan SHA changes.

The final compiler/provider binding carries `output_language` (`en`, `ja`, `ko`,
`fr`, `de`, `es`, `pt`, `id`, or `zh`), the approved script and storyboard
manifest SHA-256 values, the ordered per-Cut image SHA list, and the Segment Plan
SHA. Exact localized dialogue rows must use that language. Opaque UI and tail
assets stay outside Seedance semantics and payloads.
