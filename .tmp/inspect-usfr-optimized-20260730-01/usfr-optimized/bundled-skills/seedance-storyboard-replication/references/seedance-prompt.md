# Seedance Prompt Assembly

Build the final Seedance 2.0 prompt in this order.

## Source Of Truth

The approved 完整分镜脚本 is the execution source of truth. For every
source-fidelity generated segment, the original source is reverse-engineered
into source Cut frames, which create a replacement-control sheet, which creates
the approved director board. The current matching original source segment and
the approved director board supply the fixed Seedance references.

The storyboard image is a visual reference; do not rely on text rendered inside
the storyboard image for script instructions. Route visible text by carrier.
**Scene-surface text** is part of a physical prop or material and must already
exist in the replacement-control sheet and director board. Repeat its exact
wording, carrier, surface location, and physical behavior in the relevant Cut:
it moves, bends, folds, rotates, occludes, and tears with its carrier. This
scene-surface text must be written explicitly into the Seedance Cut prompt.
**Deterministic overlay text** such as subtitles/captions/CTAs is composited in
post and Seedance must not generate, read, or transcribe those overlay glyphs.
不要依赖故事板图片自行识别完整脚本、口播或备注。Repeat the complete approved script as prompt text.

Use the fixed B route for every source-fidelity generated segment: upload exactly
one matching frozen original source segment at `videoUrls[0]` plus at most nine
images bound by `usfr-multimodal-reference-binding/v2` under
`continuous-present-role-order/v1`. @Image1 is the new model
identity when a model replacement is populated; product or App truth follows
the model identity when populated; approved director storyboard PNG pages
follow the populated target-truth images; additional verified references follow
only with explicit purpose and Cut scope. Absent roles compact left without a
placeholder, and the actual index/tag is frozen in the binding sidecar. Source
Cut/keyframe sheets and replacement-control sheets must never be sent to
Seedance. The matching source segment is the exact current 2-15 second window;
the full source video must never be uploaded. 禁止发送 `reference_videos`.

Every approved storyboard page is uploaded as its original confirmed PNG. The
workflow must not generate, merge, crop, or substitute an execution carrier.
`seedance_execution_carrier.png` is forbidden. A single `storyboard_url` is
invalid. Enforce `uploaded_tags == binding_tags == prompt_tags`. @Video1 is a
video-slot reference and never consumes an image index. @Audio1 is an
audio-slot reference and never consumes an image index.

The `seedance-20` compiler must append this literal block to every prompt that
binds `videoUrls[0]`:

`@Video1 is the source reference video only for shot structure, composition, camera path, blocking, action timing, pacing, transitions, and delivery rhythm. Do not copy or output any person or identity, product/App or merchandise, visible text, original voice, original narration, or original dialogue from @Video1. Generate only the approved characters, target product/App evidence, exact visible text, voices, narration, dialogue, actions, and audio explicitly specified by this prompt and its bound image and audio references.`

1. Actual image-number mapping. Upload only approved target truth, original
   approved storyboard pages, and explicitly scoped additional references.
   Bind each returned public HTTPS URL to immutable SHA-256 evidence. Compile
   the actual continuous order from present roles:
   - `@Image1` is the new model identity when populated.
   - The next `@ImageN` is product or App truth when populated.
   - The next one or two `@ImageN` values are the original approved director-board pages in page order.
   - `@Image5` through `@Image9` may be used only for additional verified references with explicit Cut scope and purpose.
   - An absent role creates no placeholder. The next present role compacts left
     and its actual index/tag is recorded in the sidecar and repeated in the Prompt.
2. State the global segment plan, selected narrative split, current segment index, source time range, segment-local duration, incoming continuity state, outgoing continuity state, and adjacent segment handoff. `videoUrls[0]` controls only the matching source motion, camera rhythm, and environment continuity; it never replaces the approved director board or target truth.
3. Global product and character identity locks. Keep product shape, color, logo, packaging, material, scale, and use method consistent. Keep face, hairstyle, outfit, body proportion, and temperament consistent when a character board exists.
4. 当前分段的完整分镜脚本, repeated Cut by Cut. Keep global Cut numbers and segment-local timecodes. Every Cut must include all of these fields:
   - `时间`: segment-local `00.0-02.5s` style timecode.
   - `脚本描述`: the complete visible scene, subject, action progression, and intended result.
   - `镜头`: shot size, angle, lens feeling, camera movement, and transition.
   - `人物与产品`: identity, pose/use action, product position, product fidelity, and continuity locks.
   - `口播内容`: exact spoken line, or explicitly `无口播`.
   - `备注`: environment/action sound, lighting, mood, speed, continuity, and Cut-local negative constraints.
5. Voiceover plus environment/action sound; no background music by default.
6. Boundary continuity constraints. For segment 1, end in the exact outgoing state needed by segment 2. For segment 2, start from the exact incoming state produced by segment 1. Separate generations may not perfectly match frames, so the prompt must lock pose, product position, environment direction, screen direction, lighting, and audio handoff in text.
7. Global negative constraints: no model-generated subtitles, no unapproved
   floating text, no invented shots, no reordered Cuts, no unapproved product
   deformation, and no identity drift. This does not suppress approved scene-
   surface text or deterministic overlay text.
8. Keep the whole prompt under 5000 characters with no unresolved image-number placeholders and no generic time placeholders. Compress repeated global wording before shortening any Cut's script facts. If the approved segment prompt cannot fit without losing facts, ask the user to simplify the segment instead of omitting them.

Never use vague substitutions such as “follow the storyboard,” “same as the reference,” or “continue similarly” in place of the Cut fields above.

After assembling the complete prompt, recompile the final prompt through
`seedance-20`, build the exact direct Standard Model payload, and run one
unauthorised pre-audit dry-run with `runninghub_seedance_submit.py --dry-run`.
Then run a script-to-prompt parity audit against that exact request, save the
audit and internal SHA256 digest, and submit only with
`--approved-request-sha256`. Audit, script, storyboard, segment, and compiler
artifacts remain server-side integrity evidence. Any prompt, image mapping,
timing, or payload mutation invalidates the digest and requires a fresh dry-run
and audit. This is an internal integrity authorization, not a user approval
gate.

## Required post-storyboard integrity sequence

After the latest storyboard approval, freeze `seedance_input_contract.json`.
Normative sequence: recompile the final prompt through `seedance-20`
(professional capability,
allocation, reference-role, directing, and anti-slop checks), then build one
exact dry-run payload for that prompt version. The parity audit must compare:

- approved Cut order;
- character lock and product lock;
- duration and timecodes;
- voiceover and audio;
- camera, actions, and transitions;
- continuity and boundary handoff;
- selling-point evidence;
- timeline-region routing;
- reference mapping and image roles;
- provider parameters; and
- negative constraints.

The result must have **zero ambiguity** and no unresolved placeholders. Enter
**internal request integrity approval** only after every check passes, then
submit the unchanged digest with the audit artifact. This approval is internal,
not a third user approval gate. Prompt-only repair stays internal; changing an
approved script, storyboard, asset, or route returns to the already existing
relevant approval gate.

## Four-Cut Example

This is a physical-product example only. It is not the default structure or
visual language for App, service, brand, creator/story, or no-product routes;
those routes compile from their approved Source Fidelity Contract and Cut text.

Use `@Image1` as the character identity, `@Image2` as product truth, and `@Image3` as the approved director-board page in this three-image example. Do not read instructions from text inside `@Image3`. Follow the full Cut text for timing, motion, and transitions. Keep the exact person identity from `@Image1`. Keep the exact product appearance from `@Image2`: same color, shape, material, logo placement, packaging details, and real use method. Do not redraw or redesign the product. The matching original source slice is always `videoUrls[0]` / `@Video1` under `usfr-video-reference/v1`; opaque UI and tail media never enter the request.

Segment context: Segment 1/2, global source `00.0-14.0s`, local duration `14.0s`. Incoming state: opening state, product off-screen in the user's right hand. Outgoing state: product held upright at chest height, front logo facing camera, character looking toward product, soft window light from camera left. Segment 2 must start from that outgoing state.

Create a vertical 9:16 natural ecommerce experience video, realistic phone-shot style, soft indoor daylight, handheld but stable. No model-generated subtitles and no model-generated screen text.

Cut 1
- 时间: `00.0-03.0s`
- 脚本描述: At a kitchen counter, the user reaches into frame, takes the product from beside a cup, raises it to chest height, and turns its front toward camera.
- 镜头: Medium shot at counter height; stable handheld phone feeling; slight push-in following the hand; hard cut at the completed turn.
- 人物与产品: Match the face, hair, outfit, and body proportion from `@Image1`; product must match `@Image2` and remain unobstructed.
- 口播内容: “这个小东西我最近每天都会用。”
- 备注: Soft window daylight; light room tone and hand contact sound; no subtitles, no extra product, no deformed fingers.

Cut 2
- 时间: `03.0-06.5s`
- 脚本描述: The hand slowly rotates the product from front to side, pauses on the key texture, then tilts it so the material catches the light.
- 镜头: Tight close-up; small controlled arc movement; shallow depth of field; match cut from Cut 1 hand position.
- 人物与产品: Same hand, sleeve, product scale, color, material, and logo placement as Cut 1 and `@Image2`; no redesign.
- 口播内容: “主要是细节做得很扎实。”
- 备注: Subtle handling and material-friction sound; preserve left-to-right motion continuity; no model-generated screen text, no warped logo.

Cut 3
- 时间: `06.5-11.0s`
- 脚本描述: Over the user's shoulder, show the complete real use action: open the product, apply it to the intended area, finish the action, and set it beside the result.
- 镜头: Over-shoulder medium close-up; follow the hand with a small downward tilt; no missing action steps.
- 人物与产品: Same character identity and outfit from `@Image1`; exact product construction and real use method from `@Image2`.
- 口播内容: “用起来比我想的顺手很多。”
- 备注: Realistic use sound and small countertop movement; natural speed; no invented usage, no product-body intersection.

Cut 4
- 时间: `11.0-15.0s`
- 脚本描述: Present the clean final result with the product upright beside it; the user relaxes in the background while the product remains the visual anchor.
- 镜头: Clean result shot; hold steady for one second, then gently push in; end on a still product frame.
- 人物与产品: Maintain the same person, room direction, light direction, and exact product appearance from prior Cuts.
- 口播内容: “想要省事一点，可以直接试这个。”
- 备注: Natural room tone, no background music; no sales banner, subtitle, extra logo, extra character, or identity drift.

Negative: no model-generated subtitles, no unapproved floating text, no extra logo, no extra character, no invented scene, no reordered Cuts, no product shape change, no wrong color, no identity drift. These negatives do not suppress approved scene-surface text or deterministic overlay text.
The exact dry-run payload is audited by `seedance-20`; write the audit JSON
artifact before submitting with `--approved-request-sha256`. The artifact must
bind the request and compiled prompt digests and pass every required boolean
check.

## Audited Factory contract and submission closure

Freeze `seedance_input_contract.json` after storyboard approval. Its raw bytes
remain server-side and bind the exact approved-script digest, all required
contract digests, the unique audit-check list, and every applicable factor ID.
The audit ledger must equal that frozen factor-ID set exactly. The packaged
compiler loads the installed root `seedance-20/SKILL.md`; its frontmatter name,
exact-byte hash, and metadata version must match compiler provenance.

The audited payload is fixed-B only: RunningHub model
`seedance-2.0-fast-token`, `720p`, `9:16`, 4–15 seconds,
`generateAudio=true`, the matching original source slice at `videoUrls[0]` under
`usfr-video-reference/v1`, and the complete ordered one-to-nine-image binding.
Source Cut/keyframe
sheets and replacement-control sheets must never be sent to Seedance. The request
uses documented `imageUrls`, optional one duration-bounded `audioUrls`
item for approved `background_music`, no unknown
provider fields, and no reference, opaque-UI, tail-card, source-frame, or
transition markers in snake/kebab/spaced/camel variants. A supplied music file
must appear in prompt text as `@Audio1`; never use top-level
`reference_audios`. The unauthorised dry run is explicitly pre-audit. Actual
submission reuses the exact digest from that dry run; an invalid upload receipt
or expired URL blocks without a retry or a paid request. A plain
`--resume-task-id` is a separate known-task route: it does not require a new
prompt or duration, performs no asset preparation or payload build, cannot be
combined with `--dry-run`, and cannot carry any new-request authorization.

## Exact line contract under the high-fidelity profile

For every generated Cut with speech, the prompt compiler consumes the frozen
integer-millisecond line contract (`line_id`, exact text, speaker, BCP-47
locale, delivery, microphone distance, lip-sync limits, proof/Foley/silence
windows, music policy, and QC tolerances). Invocation B repeats the exact line
and time; it may not paraphrase, add, duplicate, translate, change a number or
negation, or assign the line to another speaker. `planned_safe_margin_ms` is
distinct from observed QC tolerance and cannot move an approved event.

Cuts without speech carry `speech_mode=none`, explicit allowed/forbidden audio,
and the canonical prompt phrase **No dialogue**. The model is not invited to
improvise speech or background music. `voiceover_and_audio` audit coverage also
checks proof/Foley/silence alignment, segment-boundary legality, and exact line
hash parity before the fixed-B request is authorized.
