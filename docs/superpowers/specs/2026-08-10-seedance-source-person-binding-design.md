# Seedance Universal Source-Object Binding Design

## Objective

Make every Seedance video-edit replacement deterministic enough for production use by binding each uploaded target asset to one evidence-backed object track in the source video. The same internal contract covers people, products, Apps, backgrounds/scenes, garments, jewelry, and accessories. The workflow must stop before a paid call when the source object cannot be uniquely located or when the shot exceeds the calibrated replacement envelope.

The first calibration target is the central male in the Reinbow source video during a 3–5 second interval. Calibration is not the terminal deliverable. The terminal deliverable is the fully assembled Reinbow video with all four approved character replacements visibly successful. Success means each target identity is present while source wardrobe, body motion, phone interaction, framing, lighting, background, timing, and unrelated objects remain unchanged.

The enhancement must not change the existing user-visible workflow: fixed input slots, one reverse-script approval, the twenty-step `video-edit-v2` process, RunningHub Provider route, and the two user-facing deliverables remain unchanged. Only internal evidence, binding, asset-board, prompt, capability, and QC contracts are strengthened.

## Evidence and corrected assumptions

- The RunningHub request already used `realPersonMode=true` and `conversionSlots=["all"]`; missing provider flags did not explain the two direct S01 failures. The active V2 payload builder nevertheless contains a contradictory `false/[]` default and must be corrected before the generic workflow is trusted.
- The retry already described the four source roles in prose. Therefore prose detail alone is insufficient.
- The active V2 prompt compiler drops `replaces_tag` before compiling asset-reference lines, reducing a model board to a generic `@ImageN binds PersonX` declaration. The paid prompt does not carry a deterministic source-person locator unless the free-form replacement instruction happens to repeat it.
- The current model asset-board template creates a multi-panel face/full-body/front/side/back board. The Morphic Seedance 2.0 guide is third-party field evidence, not an official guarantee, but it specifically warns that multi-angle face sheets can be interpreted as several people. This matches the observed failure and the Seedance attention-budget model.
- The cat-headed character succeeds because it has a large, unique, high-contrast identity region. The three human replacements are smaller and closer to the source appearance class, so returned adherence must be calibrated independently.

## Architecture

### 0. Universal object contract

`source_object_id` is the common key across all editable layers. Each registry entry declares `object_type`, visual locator, active Cut/time window, source state, motion/attachment behavior, confidence, and preservation boundary. Type-specific fields extend rather than replace this common core:

- person: face area, occlusion, wardrobe, trajectory, interaction;
- product/accessory/jewelry: geometry, scale, carrier/owner, hand contact, occlusion;
- garment: wearer ID, body attachment, fit, folds, print and closure state;
- App/UI: device ID, screen region, interaction state, text/render route;
- scene/background: spatial region, depth layer, lighting relation, foreground exclusions.

Every approved target binding declares exactly one `source_object_id`, one target asset, one `replacement_scope`, and one `preserve_scope`. Input order, filename, OCR, and generic labels such as “the product” are never mapping authority.

### 1. Source-object registry

Create a canonical registry from the frozen source-content timeline and approved object evidence. Each editable object has:

- `source_object_id`: stable ID such as `PERSON_A`, `PRODUCT_A`, `GARMENT_A`, or `SCENE_BG_A`;
- `object_type`;
- `role`: human-readable role;
- `first_seen_ms` and active window;
- `visual_locator`: two or three stable traits covering initial screen position, source wardrobe, hair/category, or held prop;
- `trajectory`: short description of movement through the calibrated segment;
- `binding_confidence` from 0 to 1;
- `min_face_area_ratio` and `max_occlusion_ratio` when evidence is available.

An internal speaker ID is not a sufficient visual locator. Input ordering is never mapping authority. Person-specific fields remain required for model replacement.

### 2. Approved model binding

Every target binding keeps its `asset_tag` and explicitly names one `source_object_id` through `replaces_tag`. Model bindings additionally carry:

- `source_person_descriptor`, rendered from the frozen registry;
- `identity_scope`, initially `face_hair_skin`;
- `binding_confidence` copied from the source registry.

Two target assets cannot replace the same source object in one pass unless the contract explicitly defines a compatible shared layer, such as a garment sharing its wearer. A binding whose `replaces_tag` is missing from the registry, whose descriptor is empty, whose type is incompatible, or whose confidence is below its type threshold fails before Image2 or Seedance submission.

### 3. Identity-only model reference

Replace the current multi-angle model board with one dominant, clean portrait:

- one person only;
- head and upper shoulders large in frame;
- neutral background and even lighting;
- front or slight three-quarter view;
- no multi-person collage, front/side/back strip, target wardrobe sheet, or body-pose sheet;
- no attempt to make the image control source clothing, pose, gesture, or body trajectory.

The board template version becomes `model-identity-v3`. Other asset-board templates remain unchanged.

### 4. Compact binding-first prompt

The compiled edit prompt begins exactly with `编辑视频：` and places identity bindings before generic preservation prose. For each model:

`将 @Image1 中的单一人物定义为 Subject 1。Subject 1@Image1 仅控制脸部、发型与肤色身份。严格编辑 @Video1：将【SRC_A：0.00秒首次位于画面中央、穿黑色彩虹连帽衫并持手机的男性】沿其完整轨迹替换为 Subject 1；服装、体型、表情、视线、动作、口型时序、手机交互与位置来自该源人物。`

The compiler must use one stable label per person and must not alternate among pronouns, source role names, and asset tags. Duplicate negative clauses are removed. Unchanged dialogue is not repeated as a generation instruction.

### 5. Audio preservation

An identity-only edit uses `preserve_unmodified_audio`. The prompt does not restate unchanged dialogue. Provider audio generation remains surface-contract compliant, but assembly restores the approved source audio for unchanged windows. This prevents ordinary identity calibration from spending prompt and joint audio-video capacity on recreating speech.

### 6. Capability gate

Before a paid call, classify the segment:

- `calibration_ready`: one model replacement, confidence at least 0.85, face area at least 4% where measurable, occlusion no more than 35%, and duration 3–5 seconds;
- `testable_multi_person`: two model replacements with distinct locators and no complex contact;
- `manual_review_required`: three or more simultaneous human replacements, ambiguous locator, small face, heavy occlusion, or complex contact/prop handoff;
- `hybrid_route_recommended`: returned adherence fails twice under a single-variable calibration budget.

These are local production thresholds, not official Seedance limits.

Non-person types receive equivalent measured gates: minimum visible area, source/target category compatibility, attachment/contact complexity, text/UI routing, motion, occlusion, and simultaneous replacement count. Deterministic UI and overlay routes remain deterministic; the universal binding contract does not move them into Seedance.

## Calibration procedure

1. Extract a 3–5 second Reinbow interval where the central male is large and continuously visible.
2. Use only the central-male target portrait and the source clip.
3. Compile a short binding-first edit prompt with unchanged audio excluded from generation instructions.
4. Dry-run and audit the exact RunningHub request.
5. Submit once, download immediately, and create a source/result/target contact sheet.
6. Evaluate identity, source preservation, temporal stability, and collateral changes.
7. If identity fails, change one variable only in this order: portrait crop, prompt locator, clip window. Do not add more people during calibration.
8. After two controlled failures with the same signature, change the execution decomposition rather than stacking adjectives: shorter source-bound segments, one primary identity per pass, accepted-pass lineage, or a type-appropriate deterministic post route. Continue until all four approved character replacements pass final QC.

## Acceptance criteria

- Target identity is recognizable in at least 80% of sampled frames where the face is at least 64 pixels tall.
- Source-specific facial traits that contradict the target, such as facial hair or source hairstyle, do not persist across the majority of eligible frames.
- No identity switching or face reversion lasting more than three consecutive frames.
- Source hoodie, body motion, phone count/color/contact, camera path, background, lighting, and non-target people remain materially unchanged.
- No extra people, duplicated faces, blank regions, mosaic, or unintended text.
- Request audit proves exact image order, source slice, prompt, `realPersonMode=true`, and `conversionSlots=["all"]`.

## Risks and fallback

Morphic guidance is practitioner evidence and may be surface-specific. A successful syntax change does not guarantee returned adherence. Small side faces and arm-in-arm contact remain high-risk even after deterministic mapping. If Seedance cannot hold a human identity after controlled decomposition, a tracked identity post route may be used inside the existing assembly/QC phase, while the same source-object mapping remains the authority. This does not add a user-visible workflow or approval gate.
