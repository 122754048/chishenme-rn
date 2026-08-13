# Seedance Compact Fail-Closed Multi-Object Binding Design

## Objective

Make every official invocation of `universal-source-fidelity-replication` compile visual replacements through one fail-closed Seedance 2.0 binding contract. The generated Provider prompt must follow the proven `4/4` Reinbow shape: short positive state declarations, continuous `@Image1..N` indexing, one concise source locator per target, explicit target evidence only when it disambiguates the target, and one shared physical-track continuation sentence.

This design applies to one through nine independently referenced people, products, Apps, scenes, garments, jewelry, and accessories without changing the existing `video-edit-v2` workflow, asset-board generation, audio, UI, tail, assembly, QC, or recovery architecture.

## Guarantee boundary

The Skill can guarantee request construction, validation, routing, auditability, and fail-closed behavior. It cannot guarantee that Seedance will visually execute every valid request. Provider `SUCCESS` remains separate from object-level visual acceptance.

“Works from any window” means every official Skill execution uses the same canonical validator and compiler. An arbitrary script that reads credentials and sends its own HTTP request is outside the Skill contract; Skill-owned Provider submission must reject requests without the canonical binding receipt.

## Verified successful pattern

The accepted Reinbow request established the reusable pattern:

- `imageUrls[N-1] == @ImageN` for four independent target boards.
- Three human targets used identity plus visible wardrobe from their corresponding images.
- The cat target used head identity from its image while preserving the source black hoodie.
- Source position, source wardrobe, prop, and entry time were concise first-appearance locators, not continuing identity authority.
- All mappings remained attached to their original physical tracks after movement, interaction, occlusion, and crossing.
- One Provider request produced a human-reviewed `4/4` result without local video alteration.

The successful result is empirical evidence for the prompt shape, not proof that all future material will achieve the same visual score.

## Architecture

### Canonical binding contract

Every replacement enters one normalized record containing:

- continuous `reference` (`@Image1..N`);
- unique `source_object_id`;
- `asset_type` (`model`, `product`, `app`, `scene`, or `garment`; jewelry and accessories use the product lane while retaining their semantic subtype);
- concise `source_locator` based on first appearance;
- stable `target_tag`;
- `replacement_scope`;
- `preserve_scope`;
- `binding_confidence >= 0.85`;
- asset-specific target evidence;
- source and target asset hashes.

Missing, ambiguous, discontinuous, contradictory, or low-confidence records fail before a paid call with `SOURCE_OBJECT_BINDING_REQUIRED`. More than nine references fail with `IMAGE_REFERENCE_LIMIT`.

### Mutually exclusive person modes

Each person binding selects exactly one mode:

1. `identity_and_wardrobe_from_reference`
   - The reference image controls identity, hair, visible clothing, and visible accessories supported by the image.
   - Source clothing may appear only inside the source locator.
2. `identity_from_reference_preserve_source_wardrobe`
   - The reference controls the declared face/head/hair identity scope.
   - The named source body and garment remain.

The compiler must reject a binding that combines complete target appearance with preserved source wardrobe. It must also reject target clothing prose that is unsupported by the corresponding target evidence.

### Canonical compiler and submission receipt

Create one canonical compact compiler used by both the formal V2 path and the retained low-level compatibility function. The compatibility function must normalize into the same contract and cannot supply weaker defaults.

The compiler returns:

- the compact Prompt;
- ordered image tags and source object IDs;
- normalized bindings;
- binding-contract SHA-256;
- prompt SHA-256;
- a canonical compiler/version marker.

Skill-owned Provider submission accepts only a request carrying this receipt and verifies it against the final `imageUrls`, Prompt, source video, and request hash. Writing `provider_only: true` into an arbitrary JSON file is not sufficient authority.

## Compact Prompt contract

Detailed evidence remains in the binding audit. The Provider Prompt contains only:

1. one short `@Video1` authority sentence;
2. one mapping sentence per target in `@Image1..N` order;
3. one shared physical-track continuation sentence;
4. one shared source-performance preservation sentence when required.

### Person recipes

Identity and wardrobe from reference:

```text
Subject N: [concise source locator] becomes @ImageN with exact @ImageN identity and wardrobe: [short verified target wardrobe/accessory anchor].
```

Head identity with source wardrobe:

```text
Subject N: [concise source locator] becomes @ImageN with exact @ImageN head identity, wearing the source [named garment].
```

### Other asset recipes

```text
Object N (product): [source locator] becomes @ImageN with the target geometry, color, markings, and packaging from @ImageN; preserve contact, scale, perspective, motion, light, shadow, and occlusion.
Object N (app): [source screen locator] becomes @ImageN with the approved App identity and interface from @ImageN; preserve device geometry, screen plane, gestures, reflections, camera, and timing.
Object N (scene): [source environment locator] becomes @ImageN with the target environment from @ImageN; preserve subjects, foreground interaction, camera path, depth, lighting direction, and timing.
Object N (garment): [source garment locator] becomes @ImageN with the garment appearance, material, color, and construction from @ImageN; preserve wearer identity, body motion, fit contact, folds, lighting, and occlusion.
```

The compiler emits only the recipes required by the current bindings. It does not add generic cinematic language, repeated quality adjectives, node IDs, masks, spatial-map instructions, unsupported facial prose, or long negative clauses.

## Source segmentation integrity

An audit claim such as `0.00-10.48s` is valid only when the immutable uploaded source is that exact slice or the Provider request has verified start/end semantics. A duration field alone does not prove the source slice. The paid-call integrity check compares the segment receipt with the actual uploaded video hash and request fields.

## Encoding integrity

The canonical prompt prefix and all generated text must round-trip as UTF-8. Replacement characters, mojibake signatures, or control characters fail before submission with `PROMPT_ENCODING_INVALID`.

## Compatibility and unchanged capabilities

- Keep `video-edit-v2` as the only active workflow entrypoint.
- Keep the existing one-to-nine image limit and independent asset-board topology.
- Keep product, App, scene, garment, jewelry, accessory, UI, audio, tail, assembly, and QC routes intact.
- Keep the low-level compiler symbol only as a compatibility adapter; it must delegate to the canonical contract.
- Quarantine project-specific direct scripts from Skill authority. They remain historical evidence and are not official execution entrypoints.
- Do not add local face swap, inpainting, compositing, re-encoding, audio replacement, or per-person paid generation.

## Testing strategy

Use TDD and verify the regression before changing production code.

1. Add failing tests reproducing the observed bypass:
   - three human bindings using complete target identity and visible wardrobe from their references;
   - missing `preserve_scope` or `binding_confidence` accepted by the low-level helper;
   - a self-declared `provider_only` audit accepted without a canonical receipt;
   - an audit claiming a slice not represented by the uploaded source/request;
   - mojibake in the generated prefix.
2. Add a golden test for the accepted Reinbow prompt shape and its four ordered mappings.
3. Add generalized tests for 1, 2, 4, 5, 6, and 9 bindings across people, products, Apps, scenes, garments, jewelry, and accessories.
4. Verify conflicts fail before any mocked Provider create call.
5. Run focused compiler/contract tests, V2 packaged-stage tests, Skill documentation tests, bundle closure, lightweight bundle validation, and the full Skill regression suite.

No paid Seedance request is required to validate this implementation. Future real outputs still require object-level human QC.

## Acceptance criteria

- Every official visual replacement selects `provider_only_multi_object_binding` before submission.
- Formal V2 and compatibility calls produce the same normalized contract and compact Prompt.
- The successful Reinbow mapping compiles to the same concise semantic structure.
- Person wardrobe modes are explicit and mutually exclusive.
- `imageUrls[N-1] == @ImageN` is audited against the final payload.
- Missing evidence, scope, confidence, receipt, segment integrity, or clean UTF-8 blocks the paid call.
- Existing non-binding capabilities and their tests remain unchanged.
- Documentation does not claim guaranteed visual success from Seedance.

## Risks and mitigations

- **Model variance:** A valid request may still fail visually. Mitigation: object-level QC and truthful measured replacement counts.
- **Overfitting to Reinbow:** Exact wardrobe text is case-specific. Mitigation: require short target evidence extracted from each independent asset, not copied global prose.
- **Compatibility breakage:** Existing callers may omit newly required fields. Mitigation: fail with a specific migration error and update official callers; do not silently restore weak defaults.
- **Prompt growth with nine targets:** Repeated scopes can exceed Provider limits. Mitigation: use compact per-type recipes and shared continuation/preservation sentences.
- **Out-of-band HTTP:** Arbitrary scripts can bypass Skill-owned code. Mitigation: treat them as outside authority and require canonical receipts in all official Provider clients.
