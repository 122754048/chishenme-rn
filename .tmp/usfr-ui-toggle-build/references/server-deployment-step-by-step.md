# Server Deployment Step By Step

This document is the plain-language handoff for deploying Universal
Source-Fidelity Replication as a server-side video workflow.


## 1. What This Package Is

This package is the video workflow engine.

It provides:

- a FastAPI Jobs API;
- a Redis-backed job state store;
- a Redis Streams worker queue;
- an S3-compatible media store contract;
- a worker that runs source-video analysis, script review, storyboard review,
  Seedance prompt compilation, provider submission, assembly, QC, and final MP4
  publication;
- a cleanup sweeper that deletes temporary inputs and intermediates after the
  job is done;
- bundled workflow skills, bundled Seedance-20 prompt rules, schemas, tests,
  and validation tools.

It does not provide:

- user accounts;
- billing;
- subscription plans;
- order management;
- long-term project history;
- analytics dashboards;
- a web upload UI;
- provider accounts or provider API keys.

Your backend must wrap this package with your own account/payment/front-end
system if you need those business features.

## 2. The Runtime Shape

Run the same image in three process roles:

- API process: accepts upload-completion records, creates jobs, exposes review
  APIs, and returns the final result handle.
- Worker process: consumes Redis Streams messages and executes video stages.
- Sweeper process: deletes expired job state and temporary media.

The workflow stores authority in Redis and media in S3-compatible object
storage. It must not read user workstation paths, desktop files, or installed
local skills.

## 3. Required Infrastructure

Prepare these services before starting the package:

- Python image or container based on Python 3.12.
- FFmpeg available in the worker image.
- Redis 7 or compatible Redis service.
- S3-compatible object storage, such as AWS S3, MinIO, Ceph, or another private
  S3 endpoint.
- A packaged deployment module that returns the runtime factory.
- A packaged port module that returns all real video/model/provider adapters.
- HTTPS endpoints or local model services for OCR, VLM, ASR, audio-event
  classification, generated UI rendering, and semantic QC.
- Provider credentials for GPT and RunningHub/Seedance.

The provided Dockerfile already installs Python dependencies and FFmpeg. Your
deployment still must inject credentials and real adapters.

## 4. Build The Image

Run this from the package root, the directory that contains `SKILL.md`,
`server/`, `scripts/`, `deployment/`, `references/`, and `validation/`.

```bash
docker build -f deployment/Dockerfile -t usfr:<immutable-tag> .
```

Use a real immutable tag, for example a Git commit SHA. Do not use `latest` for
production.

The Docker build runs:

```bash
python -B scripts/verify_bundle.py /opt/usfr
```

If the build fails here, stop. The package is incomplete or contains forbidden
runtime state.

## 5. Environment Variables

Set these variables for all three processes unless a row says otherwise.

```bash
USFR_DEPLOYMENT_FACTORY=server.packaged_factory:build_runtime
USFR_PORT_FACTORY=my_deployment.video_ports:build_ports
USFR_PROFILE_MODE=shadow
USFR_CAPABILITY_SECRET=<at-least-32-utf8-bytes>
USFR_REDIS_URL=redis://redis:6379/0
USFR_S3_ENDPOINT=https://s3.example.internal
USFR_S3_BUCKET=usfr-media
AWS_ACCESS_KEY_ID=<object-store-access-key>
AWS_SECRET_ACCESS_KEY=<object-store-secret-key>
AWS_DEFAULT_REGION=us-east-1
```

Use `USFR_PROFILE_MODE=shadow` for the first deployment. Move to `active` or
`production` only after the 36-case real quality acceptance passes with real
model/provider evidence.

The API process command is:

```bash
python -B -m uvicorn server.deployment_bootstrap:build_http_app --factory --host 0.0.0.0 --port 8080
```

The worker process uses:

```bash
USFR_PROCESS_ROLE=worker
USFR_WORKER_BOOTSTRAP=server.deployment_bootstrap:run_worker
python -B -m server.worker_entrypoint
```

The sweeper process uses:

```bash
USFR_PROCESS_ROLE=sweeper
USFR_SWEEPER_BOOTSTRAP=server.deployment_bootstrap:run_sweeper
python -B -m server.worker_entrypoint
```

## 6. What The Port Factory Must Do

`USFR_PORT_FACTORY` must point to a Python function inside the deployed image.
Example:

```bash
USFR_PORT_FACTORY=my_deployment.video_ports:build_ports
```

That function must return this shape:

```python
def build_ports():
    return {
        "stage_ports": {
            "probe_source": probe_source_port,
            "bind_input_slots": bind_input_slots_port,
            "analyze_dynamics": analyze_dynamics_port,
            "parse_app_store_evidence": parse_app_store_evidence_port,
            "build_script": build_script_port,
            "generate_storyboards": generate_storyboards_port,
            "compile_seedance20_prompt": compile_seedance20_prompt_port,
            "audit_seedance_request": audit_seedance_request_port,
            "submit_provider": submit_provider_port,
            "assemble_final": assemble_final_port,
            "run_qc": run_qc_port,
            "publish_result": publish_result_port,
        },
        "capability_ports": {
            "dynamics_analyzer": dynamics_analyzer,
            "asr_transcriber": asr_transcriber,
            "ocr_ui_renderer": ocr_ui_renderer,
            "seedance20_compiler": seedance20_compiler,
            "compositor": compositor,
            "qc_engine": qc_engine,
            "provider_adapter": provider_adapter,
        },
        "invocation_adapter": seedance_invocation_adapter,
        "recovery_bridge": adaptive_recovery_bridge,
    }
```

Every port must expose a stable `capability_identity()` or equivalent identity
record containing implementation name, version, and SHA-256 or immutable digest
of the deployed code/model/config.

If a port is only a fake readiness stub, do not use it for production video
generation.

## 7. How To Handle Each External Capability

### GPT API

Use GPT for reasoning-heavy workflow stages:

- source video semantic analysis;
- script generation and script revision;
- storyboard text planning;
- source selling-point extraction;
- target product selling-point replacement;
- localization into the requested output language;
- reviewer edit application;
- recovery-loop strategy selection when normal routes fail.

Put your GPT key in your deployment environment, for example:

```bash
OPENAI_API_KEY=<server-owned-openai-key>
OPENAI_MODEL=gpt-5.6-terra
```

These variable names are suggested for your adapter. The core package does not
read arbitrary GPT variables by itself. Your `USFR_PORT_FACTORY` code reads
them and calls the GPT API inside the relevant stage or capability ports.

Never accept a GPT key from the client request. The server owns provider
credentials.

### RunningHub And Seedance Provider

Use RunningHub for storyboard image generation and RunningHub Standard Model
Seedance for final video generation.

Your provider adapter must implement:

- `create_asset(...)` for storyboard/reference asset registration;
- `create_video(...)` for paid video generation;
- `lookup(...)` for provider reconciliation when a request outcome is
  ambiguous.

The workflow already creates provider intents and hashes the exact request
payload before the paid call. Your adapter must not mutate the prompt, duration,
reference list, model, or payload after the audit hash is frozen.

Required adapter-owned environment:

```bash
RUNNINGHUB_API_KEY=<server-owned-runninghub-key>
RUNNINGHUB_SEEDANCE_API_KEY=<enterprise-shared-runninghub-standard-model-key>
RUNNINGHUB_SEEDANCE_CREATE_URL=https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video
RUNNINGHUB_SEEDANCE_QUERY_URL=https://www.runninghub.cn/openapi/v2/query
RUNNINGHUB_SEEDANCE_UPLOAD_URL=https://www.runninghub.cn/openapi/v2/media/upload/binary
```

The video request must be the direct documented Standard Model body. Every
source-fidelity generated segment uploads the exact current 2-15 second matching
original source segment at `videoUrls[0]`, the approved director board at
`imageUrls[0]` / `@Image1`, then only fixed-slot target references; it may also
carry one eligible current-segment audio fragment. Source Cut/keyframe sheets
and replacement-control sheets must never be sent to Seedance, and the full
source video must never be uploaded. Opaque UI video and tail video remain
forbidden. The Seedance key is separate so an ordinary RunningHub workflow key
is never sent to the enterprise-only standard-model API.

Reference order: matching original source segment at `videoUrls[0]`; approved
director board at `imageUrls[0]` / `@Image1`; then only fixed-slot target
references. Source Cut/keyframe sheets and replacement-control sheets must never
be sent to Seedance.

If the HTTP request times out after a paid create call may have reached the
provider, return an ambiguous state and let `/provider/reconcile` use
`lookup(...)`. Do not blindly submit a second paid job.

### Redis

Redis stores temporary job authority, CAS versions, stage checkpoints,
approvals, provider attempts, recovery checkpoints, and queue messages.

Required variable:

```bash
USFR_REDIS_URL=redis://redis:6379/0
```

### S3 Or MinIO

S3-compatible object storage stores uploads, temporary media, and final MP4s.

The required object key layout is:

```text
uploads/{upload_scope}/...
temporary/{job_id}/...
final/{job_id}/result.mp4
```

Only `final/{job_id}/result.mp4` should remain after a successful job cleanup.

Required variables:

```bash
USFR_S3_ENDPOINT=https://s3.example.internal
USFR_S3_BUCKET=usfr-media
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
AWS_DEFAULT_REGION=us-east-1
```

For AWS S3, `USFR_S3_ENDPOINT` may be omitted if your boto3 configuration
already targets AWS.

### OCR And VLM

OCR verifies readable text. VLM or semantic vision verifies source fidelity,
model/product identity, UI clarity, storyboard/final-video semantic quality,
and other visual factors.

Your adapter must send media bytes or sampled frame bytes to the model. Do not
send a worker local path as evidence.

Suggested adapter-owned environment:

```bash
USFR_OCR_URL=https://ocr.internal/v1/ocr
USFR_OCR_TOKEN=<token>
USFR_OCR_MODEL_SHA256=<64-char-model-digest>
USFR_VLM_URL=https://vlm.internal/v1/analyze
USFR_VLM_TOKEN=<token>
USFR_VLM_MODEL_SHA256=<64-char-model-digest>
```

Generated UI requires 100 percent text and layout checks. If OCR finds garbled
text, missing text, wrong language, or bad layout, block the job or enter the
recovery loop. Do not publish a final video with failed UI OCR.

### ASR And Audio Event Classifier

ASR verifies dialogue text, timing, language, delivery windows, and lip-sync
related evidence. The audio-event classifier verifies Foley, ambience, music,
meaningful silence, ducking, and boundary audio quality.

Suggested adapter-owned environment:

```bash
USFR_ASR_URL=https://asr.internal/v1/transcribe
USFR_ASR_TOKEN=<token>
USFR_ASR_MODEL_SHA256=<64-char-model-digest>
USFR_AUDIO_EVENT_URL=https://audio-events.internal/v1/classify
USFR_AUDIO_EVENT_TOKEN=<token>
USFR_AUDIO_EVENT_MODEL_SHA256=<64-char-model-digest>
```

The adapter must bind responses to the exact extracted WAV bytes and model
identity. A plain text transcript without media/model digest is not enough for
production acceptance.

### Generated UI Renderer

Use this when the user did not provide a UI operation video but did provide UI
screenshots or an App Store/Google Play URL.

The renderer must output:

- a real MP4, not a static PNG renamed as video;
- ordered UI states;
- decoded-frame SHA-256 values;
- OCR records for every readable string;
- layout records for every expected UI element;
- animation samples between states.

Suggested adapter-owned environment:

```bash
USFR_UI_RENDERER_URL=https://ui-renderer.internal/v1/render
USFR_UI_RENDERER_TOKEN=<token>
USFR_UI_RENDERER_MODEL_SHA256=<64-char-model-digest>
```

If this renderer cannot produce clear UI text, disable generated UI production
and require users to upload `ui_operation_video` instead.

### Semantic QC Evaluator

This is the final independent evaluator. It decides whether the final MP4
actually satisfies the case contract, not merely whether FFmpeg produced a
playable file.

Suggested adapter-owned environment:

```bash
USFR_SEMANTIC_QC_URL=https://qc.internal/v1/evaluate
USFR_SEMANTIC_QC_TOKEN=<token>
USFR_SEMANTIC_QC_MODEL_SHA256=<64-char-model-digest>
```

The response must include evaluator identity, request SHA, response SHA, final
MP4 SHA, source evidence binding, per-factor scores, hard-failure list, and a
receipt digest.

## 8. Start In Readiness Mode First

Before connecting paid providers, check infrastructure wiring:

```bash
USFR_DEPLOYMENT_FACTORY=server.packaged_factory:build_runtime
USFR_READINESS_ONLY=true
USFR_CAPABILITY_SECRET=<at-least-32-bytes>
USFR_REDIS_URL=redis://redis:6379/0
USFR_S3_ENDPOINT=http://minio:9000
USFR_S3_BUCKET=usfr-media
python -B -m uvicorn server.deployment_bootstrap:build_http_app --factory --host 0.0.0.0 --port 8080
```

Then call:

```bash
curl --fail http://localhost:8080/healthz
curl --fail http://localhost:8080/readyz
```

`/healthz` means the HTTP process is alive.

`/readyz` means Redis, object storage, bundle, models, capabilities, and
provider wiring are ready.

Do not run real video jobs until `/readyz` returns `status=ready`.

## 9. Basic Job Flow

The public API is `/api/v1/jobs`.

The front end uploads media to S3 first. Then it sends upload-completion
records to `POST /api/v1/jobs`.

The required input rules are:

- `source_video` is required and must be 30 seconds or shorter.
- The user must also provide at least one replacement/change input.
- `output_language` is a fixed parameter. Source video plus output language is
  allowed because it changes the final video language.
- If `ui_operation_video` is provided, the source UI interval is removed and
  the uploaded UI video is inserted with source-like transition behavior.
- If `tail_video` is provided, the source tail-card is removed and the uploaded
  tail is appended at its own natural duration.
- If `tail_video` is missing, the source tail-card is omitted. Do not pad black
  frames.

Typical API order:

```text
POST /api/v1/jobs
POST /api/v1/jobs/{job_id}/start
GET  /api/v1/jobs/{job_id}/scripts
POST /api/v1/jobs/{job_id}/scripts/{revision}/approve
GET  /api/v1/jobs/{job_id}/storyboards
POST /api/v1/jobs/{job_id}/storyboards/{revision}/approve
GET  /api/v1/jobs/{job_id}/result
```

Some routes need only storyboard approval. Some local-only routes need no
approval. The case catalog declares the expected approval count.

## 10. 36-Case Real Quality Acceptance

The package contains the 36-case coverage catalog at:

```text
validation/case_catalog.json
```

Current important status:

- The catalog is configured.
- The catalog covers physical products, apps, services, brands, creator videos,
  and mixed-media videos.
- The 78 real fixture assets are not bundled in the deployable tree.
- The catalog fixture SHA values are placeholders until the private fixture set
  is published.
- Therefore real 36-case quality acceptance cannot be completed from this
  package alone.

To complete real acceptance, the server team must do all of this:

1. Collect the 78 real fixture assets named by the catalog.
2. Upload them to private S3-compatible object storage.
3. Compute actual SHA-256, MIME, size, and video duration for every asset.
4. Create a private fixture manifest with schema
   `usfr-validation-fixtures/v1`.
5. Update or generate the release catalog so every catalog SHA matches the
   actual published fixture SHA.
6. Build the production image with the exact commit under test.
7. Start API, Worker, Sweeper, Redis, object storage, GPT, RunningHub/Seedance,
   OCR, VLM, ASR, audio-event, UI-renderer, and semantic-QC adapters.
8. Prepare dependency context JSON with immutable SHA-256 values for bundle,
   capabilities, models, provider, and prompt compiler.
9. Run the immutable release matrix with paid validation explicitly enabled.
10. Validate the result report.

Fixture manifest shape:

```json
{
  "schema_version": "usfr-validation-fixtures/v1",
  "assets": {
    "fixtures/a01/source.mp4": {
      "object_key": "uploads/release-2026-07-22/fixtures/a01/source.mp4",
      "sha256": "<actual-64-char-sha256>",
      "size_bytes": 123456,
      "content_type": "video/mp4",
      "duration_seconds": 12.34,
      "etag": "<object-store-etag>",
      "status": "completed",
      "verified": true,
      "receipt_sha256": "<64-char-receipt-sha256>"
    }
  }
}
```

Dependency context shape:

```json
{
  "bundle_sha256": "<64-char-digest>",
  "capability_sha256": "<64-char-digest>",
  "model_sha256": "<64-char-digest>",
  "provider_sha256": "<64-char-digest>",
  "prompt_compiler_sha256": "<64-char-digest>"
}
```

Run command:

```bash
export USFR_VALIDATION_ALLOW_PAID=true
export USFR_VALIDATION_EVALUATOR_TOKEN=<private-evaluator-token>

python -B validation/tools/run_case_matrix.py \
  --catalog validation/case_catalog.json \
  --fixture-manifest /secure/usfr-fixtures/fixtures.manifest.json \
  --context /secure/usfr-release/dependency-context.json \
  --api-base-url https://usfr-api.internal \
  --evaluator-url https://qc.internal/v1/usfr-case-evaluate \
  --mode immutable_release \
  --max-parallel 2 \
  --output /secure/usfr-release/36-case-results.json
```

Then validate the report:

```bash
python -B validation/tools/validate_case_results.py \
  --catalog validation/case_catalog.json \
  --results /secure/usfr-release/36-case-results.json \
  --mode immutable_release
```

The acceptance is passed only if all of these are true:

- all 36 cases executed;
- no missing or reused release case;
- every fixture receipt is verified;
- every final MP4 has a valid SHA-256 and private result handle;
- route and timeline match 100 percent;
- generated UI OCR and layout are 100 percent;
- readable text OCR is 100 percent;
- total score is at least 85;
- every high-criticality factor is at least 90;
- there are no claim failures;
- there are no hard failures;
- the evaluator receipt binds the actual final MP4 and source evidence.

If any case fails, do not promote the profile. Fix the failed stage or adapter,
rerun the failed impact cases plus the fixed smoke set, and run a full immutable
36-case matrix before production promotion.

## 11. What Done Means For First Production

First production deployment is allowed only after:

- `docker build` passes;
- `/readyz` passes with real ports, not readiness-only stubs;
- a real single job completes from upload to final MP4;
- supplied UI insertion has no black frame or hard cut artifact;
- supplied tail uses natural duration and never pads black;
- generated UI passes OCR/layout 100 percent;
- language-only localization produces the selected language;
- final audio QC passes with real ASR/audio-event evidence;
- 36-case immutable release matrix passes;
- `USFR_PROFILE_MODE` can be promoted from `shadow` according to release policy.

Until then, the correct status is: deployable workflow core is ready for server
integration, but production quality acceptance is not complete.
