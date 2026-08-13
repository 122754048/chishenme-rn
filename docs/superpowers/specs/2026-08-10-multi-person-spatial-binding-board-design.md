# Multi-Person Spatial Binding Board Design

## Objective

Test whether one additional internal visual map can make Seedance bind four existing identity assets to four explicit source-video people in one request. Keep the four identity images, their order, the source video, duration, audio policy, and RunningHub parameters unchanged.

## Evidence and premise

- Detailed target appearance text improved the measured result from 1/4 to 2/4.
- Prompt compression regressed to 1/4 and disturbed source timing.
- An explicit identity-authority sentence stayed at 2/4.
- The best measured result is therefore 2/4, not a verified hard model limit.
- The unresolved variable is visual association between each target identity and its source position.

## Design

Create one 1080x1920 internal PNG, `spatial_binding_board_v1.png`, from the four already-approved identity images. It is a cast-position map, not a new identity source:

- top left: TARGET_BLONDE / SRC_BLONDE / first-frame left;
- top center: TARGET_MAN / SRC_MAN / first-frame center;
- top right: TARGET_DARK / SRC_DARK / first-frame right;
- lower left: TARGET_CAT / SRC_ALIEN / enters from left at 3.15s.

The board uses large square crops, neutral background, stable tags, source IDs, and locator labels. It is appended as `@Image5`; `@Image1..4` remain the only face/identity authorities. The prompt adds one role boundary: `@Image5 maps target tags to source positions only; it supplies no independent identity, wardrobe, motion, camera, or style.`

## Isolation

The experiment lives only under `analysis/private/reinbow_person_replace`. No public input slot, USFR stage, asset type, provider parameter, or existing template changes before a 4/4 result. A failed board is discarded without changing the formal Skill.

## Acceptance

- One RunningHub request contains five images and one video.
- The original four image SHA values and order are unchanged.
- The request SHA is new and duplicate submission remains blocked.
- QC at matched source times confirms all four target identities, while source wardrobe, body motion, phones, composition, and sequence remain usable.
- If fewer than four succeed, record the exact maximum and do not repeat the same board.

## Verified fallback after board failure

The board test reached only 1/4; the best Provider result remains 2/4. Complete the remaining two human identities locally in one batch over the best Provider video. InsightFace embeddings identify the two source tracks from the first frame and keep assignment unique across frames; `inswapper_128.fp16.onnx` changes only the two authorized face regions. The successful Seedance man and cat, all bodies, wardrobe, motion, camera, props, background, and source audio remain untouched. This is a post-processing lane after one simultaneous four-person Provider request, not a sequence of paid per-person generations.
