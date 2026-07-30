# Source UI overlay contract

## Top-level output

Write `source_overlay_contract.json` with:

- `contract`: `source-ui-overlay-motion`
- `contract_version`: `1`
- `reference_duration_us`
- `source_width`, `source_height`
- `coordinate_space`: `rotation_corrected_source_visible_frame_normalized`
- `target_mapping`: `source_normalized_composition_to_target_frame`
- `attachment`: `screen_space`
- `time_range_semantics`: `start_inclusive_end_exclusive`
- ordered, gap-free `cuts`
- `notes`

Every Cut contains `cut`, `start_us`, `end_us`, and `source_overlays`. Use an empty array when no composited overlay is visible.

## Overlay fields

- `overlay_id`
- `kind`: `brand_mark`, `logo`, `wordmark`, `readable_wordmark`, `subtitle`, `selling_point`, `selling_point_text`, `cta`, `cta_text`, `graphic`, `ui`, or `other`
- `start_us`, `end_us`, equal to the containing Cut
- `start_rect`, `end_rect`: normalized `x`, `y`, `width`, `height`
- `start_rotation_deg`, `end_rotation_deg`
- `start_opacity`, `end_opacity`
- `motion_phase`: `static`, `enter`, `translate`, `scale`, `rotate`, `transform`, or `exit`
- factual `motion_path`
- `z_index`
- factual `layer_relation`
- `interpolation`: `hold` or `linear`
- ordered `keyframes`
- optional `observed_text`; it must be null for `brand_mark`

Every keyframe contains `time_us`, `bbox`, `rotation_deg`, and `opacity`.

## Mapping rule

A target mapping copies the entire source record and adds only:

- `source_overlay_id`
- `render_mode`: `replacement_asset`, `approved_text`, `generic_graphic`, or `omit`
- `asset_ids`
- optional target `text`

Do not change source timing, rectangle, keyframes, interpolation, rotation, opacity, motion path, z-index, or layer relation.

Text is allowed only when mapped to a source `wordmark`, `subtitle`, or `cta_text`. A source `brand_mark` can never create text.

Readable wordmarks, subtitles, selling points, and CTA layers are rendered
deterministically after generated video. They carry the selected
`output_language` (`null|en|ja|ko|fr|de|es|pt|id|zh`), an immutable font SHA,
an exact glyph-coverage digest, and final-frame OCR/layout evidence at 100%.
Readable target tokens must never be placed in a Seedance Segment Prompt.
Brand names, Logos, trademarks, and packaging truth remain immutable asset
payloads and are never translated. Supplied opaque UI and tail media are not
rewritten or OCR-localized by this mapping.

## Server target-render mapping

The source-level mapping above is converted before assembly to the canonical
server contract `target-overlay-render-mapping/v1`. The server form is the only
mapping accepted by the timeline/compositor gate:

- top-level `source_overlay_contract_sha256` binds the mapping to the immutable
  source contract;
- `regions[]` binds each `region_id` to the complete set of overlapping
  `overlay_id` values;
- each entry is `validated: true`, uses `render_mode` `deterministic_text` or
  `deterministic_asset`, and carries a lowercase `payload_sha256` (plus exact
  text or `asset_sha256` where applicable).

The source geometry, timing, keyframes, interpolation, opacity, z-order, and
layer relation remain unchanged during this conversion. A mapping or a
technical A/V pass is not proof that pixels were rendered: active production
also requires an `overlay_render_receipts[]` record bound to the final output
SHA and every region/overlay payload.
