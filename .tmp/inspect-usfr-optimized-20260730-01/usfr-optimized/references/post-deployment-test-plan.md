# Post-Deployment Test Plan

This is the step-by-step test plan to use after the server team deploys
Universal Source-Fidelity Replication.

The goal is not to run all 36 cases immediately. The goal is to prove the
service can accept real inputs, generate a real video, expose the two review
points, splice UI and tail media without black frames, localize language, and
produce evidence the product owner can inspect. After that, expand into
targeted quality tests and finally the full 36-case release acceptance.

## 1. Test Rules

Use real server deployment, not local desktop files.

Every test must record:

- service image tag;
- Git commit;
- `USFR_PROFILE_MODE`;
- API base URL;
- provider/model adapter versions;
- source input names and SHA-256 values;
- selected `output_language`;
- job ID;
- final MP4 SHA-256;
- script revision SHA-256 if a script review happened;
- storyboard revision SHA-256 if a storyboard review happened;
- pass/fail result;
- reason for failure if it failed;
- final MP4 download link or private object key.

Do not call a test passed just because the MP4 plays. A playable MP4 is only
the first check. Each test below has its own pass criteria.

## 2. Before Submitting Any Video Job

Run these readiness checks.

### Test 0.1: API health

Command:

```bash
curl --fail https://<api-host>/healthz
```

Pass criteria:

- HTTP 200;
- response `status` is `ok`;
- response names the profile mode.

Fail action:

- service process is not deployed correctly;
- do not submit jobs.

### Test 0.2: dependency readiness

Command:

```bash
curl --fail https://<api-host>/readyz
```

Pass criteria:

- HTTP 200;
- response `status` is `ready`;
- Redis check is ready;
- object store check is ready;
- bundle check is ready;
- models check is ready;
- capabilities check is ready;
- provider check is ready.

Fail action:

- if `models`, `capabilities`, or `provider` is not ready, the server has not
  injected real adapters;
- if `object_store` is not ready, uploads and final MP4 publication will fail;
- if `redis` is not ready, jobs cannot run.

### Test 0.3: object upload completion

Upload one small MP4 under:

```text
uploads/manual-smoke-001/source.mp4
```

Then verify the object-store record includes:

- object key;
- SHA-256;
- size;
- MIME;
- duration;
- completed status.

Pass criteria:

- video duration is detected;
- duration is 30 seconds or shorter;
- SHA-256 is lowercase 64 characters;
- object key is inside exactly one `uploads/{upload_scope}/` prefix.

Fail action:

- fix object-store upload completion before testing video generation.

## 3. Submission Format

Every manual test should submit the same API shape.

Create job:

```bash
curl -X POST https://<api-host>/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @job-create.json
```

Example `job-create.json`:

```json
{
  "slots": {
    "source_video": {
      "object_key": "uploads/manual-smoke-001/source.mp4",
      "sha256": "<source-video-sha256>",
      "size_bytes": 123456,
      "content_type": "video/mp4",
      "duration_seconds": 12.34,
      "status": "completed"
    }
  },
  "output_language": "zh"
}
```

The response returns:

- `job_id`;
- `capability_token`;
- `version`.

Save those three values. Every later job request uses:

```bash
Authorization: Bearer <capability_token>
```

Start job:

```bash
curl -X POST https://<api-host>/api/v1/jobs/<job_id>/start \
  -H "Authorization: Bearer <capability_token>" \
  -H "Content-Type: application/json" \
  -d '{"expected_version": <version>}'
```

Approve latest script revision when required:

```bash
curl https://<api-host>/api/v1/jobs/<job_id>/scripts \
  -H "Authorization: Bearer <capability_token>"
```

Then:

```bash
curl -X POST https://<api-host>/api/v1/jobs/<job_id>/scripts/<revision>/approve \
  -H "Authorization: Bearer <capability_token>" \
  -H "Content-Type: application/json" \
  -d '{"expected_version": <version>, "expected_sha256": "<script-sha256>"}'
```

Approve latest storyboard revision when required:

```bash
curl https://<api-host>/api/v1/jobs/<job_id>/storyboards \
  -H "Authorization: Bearer <capability_token>"
```

Then:

```bash
curl -X POST https://<api-host>/api/v1/jobs/<job_id>/storyboards/<revision>/approve \
  -H "Authorization: Bearer <capability_token>" \
  -H "Content-Type: application/json" \
  -d '{"expected_version": <version>, "expected_sha256": "<storyboard-sha256>"}'
```

Poll result:

```bash
curl https://<api-host>/api/v1/jobs/<job_id>/result \
  -H "Authorization: Bearer <capability_token>"
```

## 4. Phase 1: Flow Smoke Tests

Run these first. They prove the deployed service can move from input to final
MP4.

### Test 1.1: language-only source replication

Inputs:

- source viral video;
- `output_language=zh`;
- no product image;
- no model image;
- no UI screenshot;
- no App Store URL;
- no UI operation video;
- no tail video.

Purpose:

- prove source video plus language is accepted;
- prove language-only generation route works;
- prove missing tail is omitted;
- prove final MP4 is generated.

Pass criteria:

- job is accepted;
- script revision appears;
- storyboard revision appears;
- final MP4 exists;
- final MP4 has no terminal black padding;
- spoken/content language is Chinese;
- source product and source person are not intentionally replaced;
- final result ends before any source tail-card interval if the source has one.

Fail action:

- if job is rejected, check input admission and `output_language` handling;
- if video remains in the source language, check GPT localization, ASR, and
  Seedance prompt language routing;
- if black appears at the end, check tail omission assembly.

### Test 1.2: physical product replacement

Inputs:

- source viral product video;
- `new_product_image`;
- `output_language=en`.

Purpose:

- prove product replacement route works;
- prove new product evidence enters script/storyboard/Seedance;
- prove absent model image keeps the source person style or identity route.

Pass criteria:

- final video uses the new product, not the source product;
- selling points are adapted to the new product;
- unsupported source claims are removed or softened;
- source camera/pacing/action structure remains recognizable;
- no black frame at boundaries;
- final MP4 passes technical QC.

Fail action:

- if the old product appears, check fixed slot binding and product truth card;
- if the product mutates, check reference image quality and product lock in the
  Seedance prompt compiler;
- if claims are wrong, check script target-truth replacement.

### Test 1.3: model replacement

Inputs:

- source creator or UGC video;
- `new_model_image`;
- `output_language=en`.

Purpose:

- prove character/model identity replacement route works.

Pass criteria:

- final video uses the new model identity;
- pose/gaze/action rhythm follows the source;
- speech timing is close to the source;
- no unrelated face or body identity appears;
- lip-sync and delivery are acceptable for an internal smoke pass.

Fail action:

- if identity drifts, check model lock, reference image suitability, and
  Seedance character specialist route;
- if speech timing drifts badly, check ASR/exact-line contract.

## 5. Phase 2: App Product Tests

Run these after Phase 1 passes.

### Test 2.1: supplied UI operation video replacement

Inputs:

- source App ad;
- `new_model_image`;
- `ui_operation_video`;
- `output_language=en`;
- no tail video.

Purpose:

- prove source UI interval is removed;
- prove uploaded UI operation video is inserted;
- prove source-like transition behavior is preserved;
- prove missing tail is omitted.

Pass criteria:

- uploaded UI video appears exactly as supplied except for technical
  normalization;
- source UI interval is not visible;
- no black frame before or after the UI insert;
- no hard unwanted cut if the source used a transition;
- final video does not wait for the source UI duration if the uploaded UI has a
  different natural duration;
- no tail-card remains unless supplied.

Fail action:

- black before/after UI means timeline splice or transition receipt failure;
- wrong UI duration means natural-duration policy is not being honored;
- source UI still visible means route binding failed.

### Test 2.2: supplied UI plus supplied tail

Inputs:

- source App ad;
- `ui_operation_video`;
- `tail_video`;
- `output_language=en`.

Purpose:

- prove both opaque UI replacement and opaque tail-card replacement work in one
  job.

Pass criteria:

- uploaded UI appears in the source UI interval;
- uploaded tail appears at the end;
- uploaded tail uses its own natural duration;
- final video stops when uploaded tail ends;
- no black padding after tail;
- no source tail-card is visible.

Fail action:

- if video pads to the source tail duration, fix tail assembly duration policy;
- if source tail remains, fix tail interval removal;
- if final audio pops at tail boundary, check audio crossfade policy.

### Test 2.3: generated UI from screenshot

Inputs:

- source App ad;
- `ui_screenshot`;
- `output_language=ja`;
- no UI operation video;
- no tail video.

Purpose:

- prove generated UI route works when user does not provide UI video.

Pass criteria:

- generated UI video is clear;
- UI text is Japanese when expected;
- no garbled UI text;
- OCR/layout QC reports 100 percent for required text and layout;
- final video has no black frame around generated UI;
- source UI is replaced or transformed according to the route contract.

Fail action:

- if text is garbled, block generated UI release and require uploaded
  `ui_operation_video` until renderer improves;
- if generated UI is static only, check UI renderer output contract;
- if OCR is not independent, check OCR/VLM adapter receipts.

### Test 2.4: Google Play App Store evidence

Inputs:

- source App ad;
- official Google Play URL;
- `output_language=ja`;
- no UI operation video.

Purpose:

- prove Google Play parser is wired in production.

Pass criteria:

- parser records package ID from `id=...`;
- `hl` becomes language;
- `gl` becomes storefront or default warning;
- icon/screenshots are fetched from official Google media hosts;
- generated UI uses validated target-owned evidence;
- no generic scraper evidence is used.

Fail action:

- if parser uses raw HTML as visual truth, fix parser adapter;
- if screenshot download fails, block generated UI instead of silently
  downgrading.

### Test 2.5: Apple App Store evidence

Inputs:

- source App ad;
- official Apple App Store URL;
- `new_model_image`;
- `output_language=ko`;
- no UI operation video.

Purpose:

- prove Apple evidence route works with model replacement.

Pass criteria:

- official App identity is preserved;
- icon/screenshots are bound by SHA;
- model replacement appears in non-UI generated regions;
- generated UI stays readable;
- final claims match available App evidence.

Fail action:

- if App features are invented, fix script target-truth constraints;
- if model replacement leaks into UI demo incorrectly, check region routing.

## 6. Phase 3: Audio And Localization Tests

Run these once visual flow is stable.

### Test 3.1: whisper or quiet microphone video

Inputs:

- source video with quiet speaking or microphone whisper;
- `new_model_image`;
- `output_language=zh`.

Purpose:

- prove delivery style, speech rhythm, and close-mic tone are captured.

Pass criteria:

- final speech is Chinese;
- delivery remains quiet/whisper-like if source was whisper-like;
- microphone relationship is preserved when visible;
- no loud generic narrator voice replaces the source tone;
- Foley/ambience is not erased unexpectedly.

Fail action:

- if delivery becomes generic, check audio/delivery fields in exact-line
  contract and Seedance audio specialist routing;
- if microphone disappears, check high-critical prop factor coverage.

### Test 3.2: unboxing and Foley

Inputs:

- source unboxing or ASMR product video;
- `new_product_image`;
- `output_language=en`.

Purpose:

- prove action sound, object contact, package opening, taps, peel, and silence
  windows are preserved when relevant.

Pass criteria:

- action order follows the source;
- key object-contact sounds appear near the correct action windows;
- source-style silence or ambience is preserved where meaningful;
- no music or voice covers important ASMR moments unless the source did.

Fail action:

- if Foley timing is wrong, check audio-event classifier and exact-line/Foley
  windows;
- if action endpoint is incomplete, check motion/action endpoint contract.

### Test 3.3: language set sample

Inputs:

- one short source video with clear speech;
- run it once each for `en`, `ja`, `ko`, `fr`, `de`, `es`, `pt`, `id`, `zh`.

Purpose:

- prove every configured language can complete the chain.

Pass criteria:

- all nine jobs finish;
- each final video uses the selected language;
- script/storyboard/final prompt do not mix languages except for brand names or
  source-owned UI text;
- no language causes provider rejection.

Fail action:

- if one language fails, check language validator, GPT localization prompt,
  Seedance vocabulary module, ASR language check, and final audio QC.

## 7. Phase 4: Edge And Failure Tests

Run these before opening the service to real users.

### Test 4.1: source video too long

Inputs:

- source video longer than 30 seconds;
- one optional input.

Pass criteria:

- API rejects before creating paid provider work;
- error identifies source duration limit.

### Test 4.2: source-only without language or replacement

Inputs:

- source video only;
- no output language;
- no optional media or URL.

Pass criteria:

- API rejects the job;
- no worker stage starts;
- no provider task is created.

### Test 4.3: invalid App Store URL

Inputs:

- source video;
- invalid or unsupported App URL.

Pass criteria:

- parser blocks with a clear error;
- generated UI is not attempted from untrusted evidence.

### Test 4.4: provider ambiguous outcome

Inputs:

- use a controlled provider adapter or staging provider failure mode that times
  out after create request submission may have happened.

Pass criteria:

- job enters ambiguous/reconciliation state;
- system does not submit a duplicate paid job;
- `/provider/reconcile` uses provider lookup;
- result resumes only after reconciliation.

### Test 4.5: cleanup

Inputs:

- any successful job.

Pass criteria:

- `final/{job_id}/result.mp4` remains;
- owned `uploads/{upload_scope}/` is deleted;
- `temporary/{job_id}/` is deleted;
- Redis job authority expires or is removed according to TTL policy;
- no unrelated upload or final prefix is deleted.

## 8. Phase 5: Business Pilot Test Set

After Phases 1-4 pass, run a small business pilot before the full 36-case
release matrix.

Recommended pilot set:

- 2 physical product videos;
- 2 App videos with supplied UI;
- 1 App video with supplied UI plus supplied tail;
- 1 App video with generated UI from screenshot;
- 1 App video with Google Play URL;
- 1 creator/UGC model replacement video;
- 1 language-only localization video;
- 1 whisper/ASMR video.

Pass criteria:

- at least 8 of 10 are usable after one normal generation;
- no hard failures in UI/tail black frames;
- no generated UI乱码;
- no wrong product identity;
- no wrong model identity in high-visibility shots;
- no unsupported product/App claims;
- no final result requires manual file surgery outside the workflow.

If fewer than 8 of 10 are usable, keep the service internal and fix the most
common failure type first.

## 9. Full 36-Case Release Acceptance

Run full 36-case validation only after the pilot set is acceptable.

Use:

```bash
export USFR_VALIDATION_ALLOW_PAID=true
export USFR_VALIDATION_EVALUATOR_TOKEN=<private-evaluator-token>

python -B validation/tools/run_case_matrix.py \
  --catalog validation/case_catalog.json \
  --fixture-manifest /secure/usfr-fixtures/fixtures.manifest.json \
  --context /secure/usfr-release/dependency-context.json \
  --api-base-url https://<api-host> \
  --evaluator-url https://<qc-host>/v1/usfr-case-evaluate \
  --mode immutable_release \
  --max-parallel 2 \
  --output /secure/usfr-release/36-case-results.json
```

Then:

```bash
python -B validation/tools/validate_case_results.py \
  --catalog validation/case_catalog.json \
  --results /secure/usfr-release/36-case-results.json \
  --mode immutable_release
```

Pass criteria:

- 36 cases executed;
- zero hard failures;
- route and timeline values are 100 percent;
- generated UI OCR/layout is 100 percent;
- readable text OCR is 100 percent;
- total score is at least 85;
- high-criticality factors are at least 90;
- no claim failure;
- evaluator receipts bind the actual final MP4 and source evidence.

## 10. How To Report A Failed Test

For every failure, send one report with this shape:

```json
{
  "test_id": "2.1",
  "job_id": "<job-id>",
  "profile_mode": "shadow",
  "source_video_sha256": "<sha256>",
  "replacement_slots": ["ui_operation_video", "new_model_image"],
  "output_language": "en",
  "final_mp4_sha256": "<sha256-if-produced>",
  "failure_type": "black_frame_before_ui",
  "where_seen": "00:07.120 before uploaded UI begins",
  "expected": "source-like transition into uploaded UI with no black frame",
  "actual": "one black frame and hard cut",
  "links": {
    "final_video": "<private-url-or-object-key>",
    "source_video": "<private-url-or-object-key>",
    "ui_video": "<private-url-or-object-key>",
    "logs": "<private-url-or-log-id>"
  }
}
```

Use one failure type per report. If one video has three independent problems,
file three reports. This makes repair faster.

## 11. Stop Conditions

Stop testing and fix deployment first if any of these happen:

- `/readyz` is not ready;
- uploads cannot be verified by SHA-256;
- source duration is not detected;
- script or storyboard revisions never appear;
- Provider create requests duplicate after timeout;
- final result has no SHA-256;
- generated UI has unreadable text;
- supplied UI/tail creates black padding;
- cleanup deletes unrelated objects.

Do not continue to 36-case validation while any stop condition is unresolved.

## 12. Recommended Order For The Product Owner

Submit tests to the server team in this order:

1. Test 0.1 and 0.2 readiness screenshots.
2. Test 1.1 language-only source replication.
3. Test 1.2 physical product replacement.
4. Test 2.1 supplied UI operation video.
5. Test 2.2 supplied UI plus supplied tail.
6. Test 2.3 generated UI from screenshot.
7. Test 3.1 whisper or quiet microphone.
8. Test 4.5 cleanup.
9. Phase 5 business pilot set.
10. Full 36-case release acceptance.

This order finds the highest-risk integration problems early while keeping
provider spend under control.
