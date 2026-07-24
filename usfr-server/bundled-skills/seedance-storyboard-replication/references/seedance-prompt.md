# Seedance Prompt Assembly

Build the final Seedance 2.0 prompt in this order.

## Source Of Truth

The approved 完整分镜脚本 is the execution source of truth. The reference video is used upstream only to reverse-engineer motion, pacing, transitions, and shooting style and to generate the approved segment storyboards. The current segment storyboard supplies visual composition, identity, product, and scene reference to Seedance.

The storyboard image is a visual reference; do not rely on text rendered inside the storyboard image. 不要依赖故事板图片中的文字，也不要要求 Seedance 自行识别图片里的完整脚本、口播或备注。Repeat the complete approved script as prompt text.

Use the fixed B route for both workflow routes: keep the original video local after analysis, do not upload it for Seedance, and 禁止发送 `reference_videos`.

1. Actual image-number mapping. Under Youdao, every image is registered with CreateAsset, polled until `Status=Active`, and sent as an `asset://asset-*` reference; no COS service is required:
   - `@图片1` is 当前分段故事板 only, such as `storyboards/segment_01_v1.png` for task 1 or `storyboards/segment_02_v1.png` for task 2.
   - `@图片2` is the optional character board only when `new_model_image` is populated.
   - `@图片3` is product board 1 only when `new_product_image` is populated.
   - `@图片4` is optional product board 2 only when additional supplied product evidence is populated.
   - Do not invent an image reference for an absent slot. Source-origin KEEP
     intervals are excluded from the prompt and provider payload.
2. State the global segment plan, selected narrative split, current segment index, source time range, segment-local duration, incoming continuity state, outgoing continuity state, and adjacent segment handoff. No reference video is available to Seedance.
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
7. Global negative constraints: no subtitles, no screen text, no invented shots, no reordered Cuts, no product deformation, no identity drift.
8. Keep the whole prompt under 5000 characters with no unresolved image-number placeholders and no generic time placeholders. Compress repeated global wording before shortening any Cut's script facts. If the approved segment prompt cannot fit without losing facts, ask the user to simplify the segment instead of omitting them.

Never use vague substitutions such as “follow the storyboard,” “same as the reference,” or “continue similarly” in place of the Cut fields above.

After assembling the complete prompt, compile it through `seedance-20`, build the exact final payload, and run one unauthorised pre-audit dry-run request without audited/legacy authorization, audit, script, or input-contract flags. Then run a script-to-prompt parity audit against that exact request, save the audit and internal SHA256 digest, and submit only with the complete set `--audited-request-sha256`, `--audit-artifact`, `--approved-script-sha256`, `--seedance-input-contract`, and `--seedance20-skill-file`. Any prompt, image mapping, timing, or payload mutation invalidates the digest and requires a fresh dry-run and audit. This is an internal integrity authorization, not a user approval gate.

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

Use `@图片1` as the current segment storyboard visual reference, `@图片2` as the character board, and `@图片3` as the product board. Do not read instructions from text inside `@图片1`. Follow the full Cut text for timing, motion, and transitions. Keep the exact person identity from `@图片2`. Keep the exact product appearance from `@图片3`: same color, shape, material, logo placement, packaging details, and real use method. Do not redraw or redesign the product. No reference video is sent to Seedance.

Segment context: Segment 1/2, global source `00.0-14.0s`, local duration `14.0s`. Incoming state: opening state, product off-screen in the user's right hand. Outgoing state: product held upright at chest height, front logo facing camera, character looking toward product, soft window light from camera left. Segment 2 must start from that outgoing state.

Create a vertical 9:16 natural ecommerce experience video, realistic phone-shot style, soft indoor daylight, handheld but stable. No subtitles and no screen text.

Cut 1
- 时间: `00.0-03.0s`
- 脚本描述: At a kitchen counter, the user reaches into frame, takes the product from beside a cup, raises it to chest height, and turns its front toward camera.
- 镜头: Medium shot at counter height; stable handheld phone feeling; slight push-in following the hand; hard cut at the completed turn.
- 人物与产品: Match the face, hair, outfit, and body proportion from `@图片2`; product must match `@图片3` and remain unobstructed.
- 口播内容: “这个小东西我最近每天都会用。”
- 备注: Soft window daylight; light room tone and hand contact sound; no subtitles, no extra product, no deformed fingers.

Cut 2
- 时间: `03.0-06.5s`
- 脚本描述: The hand slowly rotates the product from front to side, pauses on the key texture, then tilts it so the material catches the light.
- 镜头: Tight close-up; small controlled arc movement; shallow depth of field; match cut from Cut 1 hand position.
- 人物与产品: Same hand, sleeve, product scale, color, material, and logo placement as Cut 1 and `@图片3`; no redesign.
- 口播内容: “主要是细节做得很扎实。”
- 备注: Subtle handling and material-friction sound; preserve left-to-right motion continuity; no screen text, no warped logo.

Cut 3
- 时间: `06.5-11.0s`
- 脚本描述: Over the user's shoulder, show the complete real use action: open the product, apply it to the intended area, finish the action, and set it beside the result.
- 镜头: Over-shoulder medium close-up; follow the hand with a small downward tilt; no missing action steps.
- 人物与产品: Same character identity and outfit from `@图片2`; exact product construction and real use method from `@图片3`.
- 口播内容: “用起来比我想的顺手很多。”
- 备注: Realistic use sound and small countertop movement; natural speed; no invented usage, no product-body intersection.

Cut 4
- 时间: `11.0-15.0s`
- 脚本描述: Present the clean final result with the product upright beside it; the user relaxes in the background while the product remains the visual anchor.
- 镜头: Clean result shot; hold steady for one second, then gently push in; end on a still product frame.
- 人物与产品: Maintain the same person, room direction, light direction, and exact product appearance from prior Cuts.
- 口播内容: “想要省事一点，可以直接试这个。”
- 备注: Natural room tone, no background music; no sales banner, subtitle, extra logo, extra character, or identity drift.

Negative: no subtitles, no floating text, no extra logo, no extra character, no invented scene, no reordered Cuts, no product shape change, no wrong color, no identity drift.
The exact dry-run payload is audited by `seedance-20`; write the audit JSON
artifact before submitting with `--audited-request-sha256`,
`--audit-artifact`, `--approved-script-sha256`,
`--seedance-input-contract`, and `--seedance20-skill-file`. The artifact must
bind the request and compiled prompt digests and pass every required boolean
check.

## Audited Factory contract and submission closure

Freeze `seedance_input_contract.json` after storyboard approval and pass it with
`--seedance-input-contract`. Its raw bytes are hashed and must bind the exact
approved-script digest, all eight required contract digests, the unique 13-key
audit-check list, and every applicable factor ID. The audit ledger must equal
that frozen factor-ID set exactly. Pass `--seedance20-skill-file` for the
installed root `seedance-20/SKILL.md`; its frontmatter name, exact-byte hash,
and metadata version must match compiler provenance.

The audited payload is fixed-B only: Youdao model `seedance-2.0-fast`, 720p,
9:16, 4–15 seconds, `generate_audio=true`, `watermark=false`, exact text and
reference-image item shapes, no unknown provider fields, and no reference,
opaque-UI, tail-card, source-frame, or transition markers in snake/kebab/
spaced/camel variants. The unauthorised dry run is explicitly pre-audit and
cannot carry audited or legacy authorization. After it, actual audited
submission must reuse only cached Active mappings with a non-empty ID, exact
`asset://{asset_id}` URI, and matching project name; invalid provenance must
fail without registration, polling, or manifest writes.
The complete CLI authorization set is `--audited-request-sha256`,
`--audit-artifact`, `--approved-script-sha256`, `--seedance-input-contract`,
and `--seedance20-skill-file` alongside the ordinary prompt/duration/ratio/
image/output/provider timing flags. `--approved-request-sha256` is legacy
compatibility-only and cannot be mixed with audited authorization. A plain
`--resume-task-id` is a separate known-task route: it does not require a new
prompt or duration, performs no asset preparation or payload build, cannot be
combined with `--dry-run`, and cannot carry any new-request authorization,
audit, script, or input-contract flags.

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
