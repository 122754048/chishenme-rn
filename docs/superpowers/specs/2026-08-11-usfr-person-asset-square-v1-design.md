# USFR Person Asset Square v1 Design

## Objective

Standardize every person replacement asset on the format proven by the accepted Seedance 2.0 four-subject `4/4` case, without changing any non-person replacement route.

## Evidence

The accepted case used four independent `1024 x 1024` PNG assets under template `model-identity-v3-local-crop`. Each asset contained one identity only, with a large clear face and the visible target hair, wardrobe, or accessory evidence. The Seedance request bound those assets in continuous physical order as `@Image1..@Image4`.

## Person Asset Contract

- Output: `1024 x 1024` PNG, one person or person-like identity per file.
- Composition: identity-dominant square crop with a clear face. Include as much visible target wardrobe and accessories as the approved replacement scope requires.
- Face/upper-wardrobe work: use a close or upper-body crop matching the proven case.
- Complete-wardrobe work: keep the same square single-person format, but widen the crop enough to show the required garment evidence while retaining usable face detail.
- Prohibit group portraits, contact sheets, multi-angle panels, duplicate faces, labels, binding diagrams, and mixed assets.
- One person asset occupies exactly one continuous `@ImageN` index.
- Visible target clothing selects `identity_and_wardrobe_from_reference`. Missing clothing evidence selects `identity_from_reference_preserve_source_wardrobe` for the missing source garment scope.
- A valid source image may be normalized by deterministic crop/resize. RunningHub Image2 is used only when the supplied image cannot yield a valid single-person asset; generated output must satisfy the same square contract.

## Isolation

Product, App, scene, garment, jewelry, and accessory assets retain their existing type-specific board formats and binding rules. This change must not route non-person assets through the person square format.

## Failure Closure

Before a paid Seedance call, fail with `PERSON_ASSET_FORMAT_REQUIRED` when a person asset is not PNG, not `1024 x 1024`, contains multiple identities/panels, lacks a usable identity anchor, or is not mapped one-to-one to its `@ImageN` reference. Never silently substitute the original upload after a required generated asset fails.

## Verification

- Baseline test must show the current Skill does not require the proven square format.
- Updated tests must cover one, two, four, and six people; visible and absent wardrobe evidence; full-wardrobe square composition; invalid multi-panel/group assets; and non-person route isolation.
- Existing provider-only binding and bundle regression suites must remain green.
