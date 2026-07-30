# USFR deployable video service

This package exposes the latest packaged Universal Source Fidelity workflow as
a Python/FastAPI service. The public API has only three business endpoints:

- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/review`

The caller submits permanent Alibaba Cloud OSS URLs. The service derives file
hashes, MIME, size, duration, dimensions, FPS, internal revisions, Provider
requests, and CAS versions. Those internal fields never appear in the public
request model.

## Storage boundary

- Original user assets remain permanently in the caller-managed OSS bucket.
- Job-private downloads, frames, audio, ASR evidence, storyboards, Provider
  outputs, and assembly files live only in the built-in private MinIO service.
- After a terminal success or terminal failure, MinIO working files are due
  for immediate task-scoped cleanup by default
  (`USFR_TEMPORARY_RETENTION_SECONDS=0`).
- Redis keeps the job status and access-token authority for 7 days by default,
  independently of media cleanup, so the caller can still query the result.
- The verified final MP4 is uploaded to Alibaba Cloud OSS and returned as a
  permanent public URL.
- The service never deletes or overwrites the original OSS objects or the
  permanent final video.

MinIO ports are not published by default. Only the API port is exposed.

## Quick start

Copy `.env.example` to `.env`, fill all required secrets, then run:

```text
docker compose -f deployment/docker-compose.yml config
docker compose -f deployment/docker-compose.yml up -d --build
docker compose -f deployment/docker-compose.yml ps
docker compose -f deployment/docker-compose.yml logs --tail=200 api worker sweeper
```

Health probes:

```text
GET /healthz
GET /readyz
```

They are excluded from OpenAPI and do not create a job or Provider task.

## Required configuration

Core:

```dotenv
USFR_CAPABILITY_SECRET=<at-least-32-random-UTF-8-bytes>
USFR_ALLOWED_OSS_HOSTS=*.oss-cn-hangzhou.aliyuncs.com
```

Alibaba Cloud OSS permanent output:

```dotenv
USFR_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
USFR_OSS_BUCKET=<bucket-name>
USFR_OSS_ACCESS_KEY_ID=<access-key-id>
USFR_OSS_ACCESS_KEY_SECRET=<access-key-secret>
USFR_OSS_PUBLIC_BASE_URL=https://<permanent-public-bucket-or-CDN-domain>
USFR_OSS_FINAL_PREFIX=usfr
```

UI route switch:

```dotenv
# Default false. With no UI screenshot/store URL, source UI is kept even when
# the source video contains UI interaction. Set true only to allow automatic
# UI redraw for product/model/language replacement. Explicit ui_screenshots or
# app_store_url always enable the target-UI route, and ui_operation_video
# always keeps the opaque splice route.
USFR_UI_REBUILD_ENABLED=false
```

GPT and RunningHub:

```dotenv
OPENAI_API_KEY=<key>
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=<model>
OPENAI_MODEL_CONFIG_SHA256=<deployment-model-config-sha256>

RUNNINGHUB_API_KEY=<key>
RUNNINGHUB_SEEDANCE_API_KEY=<key>
RUNNINGHUB_WHISPER_WORKFLOW_ID=<workflow-id>
RUNNINGHUB_WHISPER_INPUT_NODE_ID=12

USFR_UPLOADED_AUDIO_CLASSIFIER_ENDPOINT=https://<private-classifier>/v1/classify
USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_ID=<model-id>
USFR_UPLOADED_AUDIO_CLASSIFIER_MODEL_SHA256=<64-hex-model-digest>
USFR_UPLOADED_AUDIO_CLASSIFIER_API_TOKEN=<optional-bearer-token>
```

The uploaded-audio classifier settings are optional as a group. Leave them all
empty when the public `audio` field is not enabled. If a job contains `audio`,
the service classifies the exact imported bytes before script review and fails
before any paid video call when the classifier is absent, ambiguous, or not
bound to the imported SHA-256. Active/production profiles require HTTPS.

See `.env.example` and `中文部署配置手册.md` for the complete list.

## Public API example

Create and start automatically:

```http
POST /api/v1/jobs
Idempotency-Key: 8cb97827-8b19-4ca8-b819-c4f03a8baac0
Content-Type: application/json

{
  "source_video": "https://bucket.oss-cn-hangzhou.aliyuncs.com/source.mp4",
  "new_model_images": [
    "https://bucket.oss-cn-hangzhou.aliyuncs.com/model.jpg"
  ]
}
```

Response:

```json
{
  "job_id": "job-id",
  "access_token": "job-scoped-token",
  "status": "importing"
}
```

Every later request uses:

```http
Authorization: Bearer <access_token>
```

Poll `GET /api/v1/jobs/{job_id}`. When `status=waiting_review`, approve or
revise through the single review endpoint:

```json
{"action":"approve"}
```

```json
{"action":"revise","content":"complete revised script or storyboard instruction"}
```

The service always requests script review first and storyboard review second.
After storyboard approval it autonomously compiles, submits, waits, assembles,
checks, uploads, and returns:

```json
{
  "job_id": "job-id",
  "status": "completed",
  "result_url": "https://cdn.example.com/usfr/final/job-id/result.mp4"
}
```

## Process topology

- `api`: stateless FastAPI public shell.
- `worker`: Redis Streams consumer executing the packaged workflow.
- `sweeper`: removes job-private MinIO and Redis state without deleting OSS
  source assets or permanent final videos.
- `redis`: temporary job/CAS/lease/Provider authority.
- `minio`: private temporary object storage.

The production image does not read `~/.codex/skills` or a workstation path.
Runtime Skill files and Seedance compiler dependencies are bundled and verified
by digest.

## Validation

Local TCP smoke test, useful when Docker is unavailable:

```text
python -B -m validation.e2e.local_public_http_smoke
```

Container control-flow E2E:

```text
USFR_CAPABILITY_SECRET=<at-least-32-bytes>
USFR_DOCKER_TARGET=e2e
USFR_PORT_FACTORY=validation.e2e.ports:build_ports
USFR_INSTALL_MODE=control-plane
docker compose -f deployment/docker-compose.yml --profile e2e up --build --abort-on-container-exit --exit-code-from e2e e2e
```

The container driver uses only the three public business endpoints. It checks
OpenAPI closure, idempotent creation, invalid-token rejection, both reviews,
permanent result URL download, and a playable audio/video MP4. The E2E media
ports are deterministic control-flow doubles, not advertising-quality evidence.
