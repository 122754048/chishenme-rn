# Seedance Provider-Only Multi-Subject Binding Design

## Objective

Generate one Seedance 2.0 video request that replaces all four source subjects in the Reinbow source video. No local face swap, inpainting, frame replacement, compositing, or local video-generation fallback may contribute to the delivered MP4.

## Verified constraints

- RunningHub's standard `seedance-2.0-token/multimodal-video` request accepts ordered `imageUrls` and `videoUrls`; it does not expose canvas `edges`, masks, or region-guidance fields.
- Prompt references are one-based and must match upload order exactly: `imageUrls[0] == @Image1` through `imageUrls[3] == @Image4`.
- The source subjects move during the clip. Left/center/right is calibration evidence for the opening frame, not a persistent identity.
- Seedance 2.0 publicly documents multi-subject consistency and complex editing as fragile. A 4/4 result is an empirical target, not a guaranteed model property.

## Reference topology

Use exactly five provider assets:

1. `@Image1`: target identity for the original opening-center man in the black rainbow hoodie.
2. `@Image2`: target identity for the original opening-left blonde woman in the mint-green top.
3. `@Image3`: target identity for the original opening-right dark-haired woman in the gray halter top with sunglasses on her head.
4. `@Image4`: ragdoll-cat head identity for the gray alien entering from frame-left at approximately 3.15 seconds.
5. `@Video1`: source authority for shot order, composition, camera path, blocking, actions, occlusion, contact, timing, body trajectory, props, lighting, background, and audio rhythm only.

Do not upload the spatial binding board or any group/reference-control sheet. Each image has one identity role. Image references must not transfer pose, background, framing, or motion. For the three human targets, visible wardrobe evidence in the corresponding image replaces the source wardrobe. The cat reference controls the alien figure's head identity only; its source black hoodie remains because the cat image contains no human-scale garment evidence.

## Prompt structure

The prompt is compact and ordered by binding priority:

1. Declare `@Video1` as the sole motion/composition source and explicitly exclude every source identity.
2. Declare four independent mappings in `@Image1` to `@Image4` order.
3. For each source track, use opening position plus persistent clothing/prop/entry-time evidence.
4. State that the mapping follows the same physical track after movement or crossing; screen position is not re-evaluated later.
5. Replace the three human tracks' identity and visible wardrobe from their respective image. Preserve source body trajectory, action, hand/object contact, camera, lighting, background, timing, and audio. Preserve the alien track's source hoodie while replacing its head with the cat.
6. Require all four mappings in the same generation and prohibit identity mixing.

Do not re-describe target facial details already visible in the images. Dense visual identity comes from the image reference; text carries mapping, motion inheritance, and exclusions only.

## Provider-only enforcement

- The accepted deliverable must be the direct MP4 returned by the audited Seedance task.
- `provider_create_calls` for one candidate request is exactly one.
- Any local identity-completion route is disabled for this workflow.
- Local tools may hash, inspect, download, and QC the provider output, but may not alter video or audio frames.
- A retry requires a changed request SHA-256 and a documented single changed variable. Unchanged paid retries are forbidden.

## Acceptance and failure reporting

Object-level QC evaluates the man, blonde woman, dark-haired woman, and cat separately. Success is `4/4` identity replacement while source motion, wardrobe, composition, timing, and interactions remain usable. Human review is authoritative over automated similarity metrics.

If the result remains below `4/4`, report the exact achieved count and failed identities. Do not claim success, apply a local repair, or reinterpret a face overlay as full Seedance identity replacement.
