---
name: replicate-source-ui-overlays
description: "Extract and freeze the exact timing, normalized screen position, size, rotation, opacity, trajectory, interpolation, z-order, and layer relationship of UI, logos, brand marks, wordmarks, subtitles, CTA text, and graphic overlays in any source video. Use when a video-generation, recreation, editing, compositing, storyboard, or QA workflow must replace overlay content while preserving the source video's overlay animation and placement exactly."
---

# Replicate Source UI Overlays

## Objective

Create a platform-neutral source overlay contract. Permit downstream replacement of content identity only; preserve timing and geometry.

## Required references

Read [references/overlay-contract.md](references/overlay-contract.md) before analysis or mapping.

## Workflow

1. Obtain exact source Cut boundaries from a frame-accurate dynamics analysis.
2. Inspect every Cut for visible UI, logo, brand mark, wordmark, subtitle, CTA, or graphic layers.
3. Split a Cut at overlay visibility, motion-phase, direction, scale, rotation, opacity, or occlusion/layer changes.
4. Write `source_overlay_contract.json`.
5. Generate a QA sampling plan if useful:

   ```text
   python scripts/overlay_frame_plan.py source_overlay_contract.json --output overlay_frame_plan.json
   ```

6. Validate:

   ```text
   python scripts/validate_overlay_contract.py source_overlay_contract.json
   ```

## Exact-replication rules

- Use rotation-corrected visible-frame normalized coordinates and screen-space attachment.
- Give every motion phase ordered keyframes covering the Cut start and exclusive end boundary.
- Use `hold` only for identical keyframes. Use `linear` only for one monotonic phase.
- Reuse an overlay ID across adjacent Cuts only while the same logical overlay continues.
- Split enter, hold, translate, scale, rotate, transform, and exit phases instead of combining them in prose.
- A brand mark replacement changes pixels only. It must not add an App name, wordmark, label, or CTA.
- Source absence is binding: no source logo means no target logo; no source wordmark means no target wordmark.
- Keep overlays in screen space. Do not attach them to a person, product, device, camera tracker, or generated subject.
- Preserve feed scrolling direction, speed phase, crop, columns/rows, freeze points, and layer occlusion. Do not turn moving UI into static panels.

## Downstream mapping

Map each source overlay exactly once and in the same order. Copy all geometry fields unchanged. A downstream workflow may add only render payload fields such as a validated replacement asset ID or approved replacement text for a matching source text overlay.

## Output boundary

Do not parse App-store pages, select replacement materials, write a new story, generate a storyboard, or submit a video model. Return the overlay contract and factual QA findings only.
