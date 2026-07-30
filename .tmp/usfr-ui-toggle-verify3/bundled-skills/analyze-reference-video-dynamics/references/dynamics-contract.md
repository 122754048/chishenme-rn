# Reference-video dynamics contract

## Probe output

`video_probe.json` is deterministic media metadata and candidate timing, not the final semantic analysis.

## Final output

Write `source_dynamics_analysis.json` with:

- `contract`: `reference-video-dynamics`
- `contract_version`: `1`
- `reference_duration_us`
- `source_width`, `source_height`
- `fps_num`, `fps_den`
- `source_cut_count`
- ordered `source_cuts`
- ordered `source_events`
- `notes`

Every Cut contains:

- `cut`, `start_us`, `end_us`
- `subject_presence`: `identifiable`, `partial_or_hands`, `transition_residue`, `screen_pixels_only`, `none`, or `uncertain`
- non-empty `content_roles`
- `scene`, `action`, `camera`, `transition`, `end_state`
- `certainty`: `certain` or `uncertain`

Every event contains:

- `event`
- `kind`: `voiceover`, `dialogue`, `subtitle`, `sfx`, `music`, `ambience`, or `silence`
- `start_us`, `end_us`
- `source_cut_start`, `source_cut_end`
- `text`
- `certainty`: `certain`, `uncertain`, `inaudible`, or `not_applicable`

## Cut policy

Split on edits and on phase changes inside continuous shots. UI/Logo overlay geometry may be described by a separate overlay contract, but its visibility and motion phase changes still create dynamics boundaries.

The final analysis must remain usable by advertising, film recreation, animation, product demo, UI promo, video editing, and model-independent generation workflows.

## Optional high-fidelity extension

When the persisted run profile is `high_fidelity_hybrid_v1`, the existing
dynamics artifact may add `extensions.high_fidelity_hybrid_v1`. Legacy
artifacts without this extension remain valid. The extension deepens the same
single semantic pass; it never authorizes a second routine full-video pass.

For every semantic Cut, record normalized scene topology and geometry,
source-to-9:16 framing migration, lighting vectors, expression, gaze, posture,
gesture, microphone relationship, the complete object/action state sequence
through a completed end state, and exact speech/audio-to-proof mappings. Every
factor carries observed/inferred/planned provenance, confidence, uncertainty,
criticality, blocker threshold, and time/frame/audio evidence.

Opaque UI, source-origin UI, and excluded/omitted App-tail intervals are
route-excluded from semantic inspection. They carry Cut boundaries,
transition-shell data, and technical metadata only. They must not carry source
identity, brand, product/App truth, claims, OCR, ASR, or inferred affordances.

Validate the additive record after the base dynamics validator:

```text
python scripts/validate_high_fidelity_extension.py source_dynamics_analysis.json
```
