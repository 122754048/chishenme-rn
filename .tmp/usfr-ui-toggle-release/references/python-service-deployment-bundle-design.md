# Python Full-Video Service Deployment Bundle

## Approved decision

Package the canonical Universal Source Fidelity Replication Skill as a
standalone Python video service for one Linux host. Docker Compose is the
deployment target. Java is an optional upstream caller only; it does not
replace the Python video worker.

## Goal and boundary

The deployed service must contain every canonical workflow script, bundled
module, Seedance compiler/auditor, server contract, deterministic FFmpeg
assembler, and cleanup rule. A running deployment must never read a client
workstation path, a Codex Skill install, a prior run directory, or a mounted
source checkout.

All semantic inference is performed through the configured GPT API. This
includes source-video understanding, visual and audio evidence reconciliation,
commercial-intent analysis, selling-point reasoning, script proposals,
storyboard instructions, route-sensitive review, and semantic QC. The worker
must not substitute a local model, heuristic, another LLM, or a model bundled
in the image for any of those decisions.

RunningHub remains the existing media-workflow provider: Image2, Seedance
video, the approved Whisper/ASR workflow, TTS, and final lip-sync work. FFmpeg
and the deterministic UI/timeline/overlay code remain local server-side
execution, not semantic inference. All remote calls use server-owned
credentials. A required GPT or RunningHub capability that is missing or not
ready blocks the affected job before any paid task is submitted.

## Options considered

1. **Python full-video package (selected).** The existing Python contracts and
   media/runtime code are packaged without a rewrite. This preserves fidelity,
   approval gates, provider idempotency, and FFmpeg behavior.
2. **Java rewrite.** Rejected: provider and GPU wait dominate latency, while
   rewriting Python media/AI code would add quality and stability risk.
3. **Remote-provider-only orchestrator.** Rejected: it would remove
   deterministic assembly, quality gates, exact-line compilation, and safe
   object lifecycle behavior.

## Runtime topology

    caller or Java business service
            |
            v
    API container -- Redis (temporary job state and queue)
            |
            +--> Worker container -- RunningHub / GPT-compatible VLM /
            |                         ASR, OCR, UI-renderer and QC endpoints
            |
            +--> Sweeper container
                             |
                             v
                 MinIO: uploads + temporary job objects + final MP4 only

API, worker, and sweeper use the same immutable image. Redis has no durable
history mode. MinIO persists only named-volume media storage. The service may
be run behind a reverse proxy, but the package does not introduce accounts,
billing, tenant history, analytics, or a database.

## Local-Skill parity

Packaging changes the execution location only. It must preserve the canonical
local Skill behavior exactly:

- the seven fixed input slots, optional background-music extension, and
  output-language behavior;
- the source-plus-change admission gate and deterministic route binding;
- one source probe and one GPT semantic analysis pass, with no global
  re-analysis;
- the same twelve semantic stages, two existing approval types, and approval
  invalidation rules;
- source/UI/tail routing, timeline scope gate, control-keyframe and storyboard
  rules, at-most-two generated segments, exact-line contracts, and
  Seedance-20 compilation/audit;
- RunningHub provider submission, provider reconciliation, deterministic
  assembly, QC hard gates, and the existing temporary/final object lifecycle.

The server service must use the same package-relative files and byte digests as
the local canonical Skill. It may not silently simplify, omit, reorder, or
replace a route merely to make deployment lighter.

## Packaged capability closure

The image includes a packaged production port factory, rather than requiring
the caller to provide a separate video-port Python module. Its adapters bind
the existing stage and capability contracts:

- GPT API source dynamics, semantic audio evidence reconciliation, script
  drafting, and exact-line validation;
- RunningHub Image2, Seedance Standard Model, TTS, and final lip-sync workflow
  calls;
- deterministic UI/timeline/overlay rendering and FFmpeg assembly;
- GPT API OCR/layout and semantic-QC evidence boundaries;
- provider create/query/reconciliation and final artifact publication.

The factory receives endpoints, model identities, workflow identifiers, and
credentials only from the deployment environment. It emits the existing
capability identities and fails closed when a declared production capability
is unavailable. high_fidelity_hybrid_v1 remains Shadow until its existing
activation evidence gates pass; this packaging work must not promote it.

## Configuration and secrets

The ZIP contains .env.example with blank values and comments. The operator
copies it to .env on the server. No secret, generated media, cache, Git
history, source run, or workstation path enters the ZIP or image.

The required configuration groups are:

- one 32-byte USFR_CAPABILITY_SECRET;
- one GPT API base URL, API key, model identifier, and pinned configuration
  digest used by every semantic inference adapter;
- RunningHub image/video/asset key and URL set;
- deployed TTS/final lip-sync workflow IDs when those routes are enabled;
- MinIO credentials, bucket, and retention values.

The normal compose defaults wire Redis and MinIO internally. The operator
normally changes only .env; no Python module path is configured.

## Object lifecycle

Uploads use the exact uploads/{upload_scope}/ prefix. A valid job owns a
unique temporary/{job_id}/ prefix. Inputs, frames, audio, analysis,
storyboards, provider responses, generated segments, and QC evidence remain
temporary. The sweeper deletes those prefixes and the corresponding Redis
authority after terminal completion; only a QC-approved
final/{job_id}/result.mp4 survives successful cleanup. Failed, expired, and
cancelled jobs retain no final object.

## Lightweight and stability rules

- One image, three small process containers; no duplicate source tree, local
  run volume, cache volume, or development test data in the production target.
- FFmpeg is included because it is required for deterministic assembly and
  does not reduce quality.
- The image contains no local LLM/VLM/OCR/QC model weights. GPT API is the
  single semantic inference authority, which keeps the server package light
  and makes its reasoning behavior centrally configurable.
- API readiness validates Redis, MinIO, immutable bundle bytes, all model
  adapters, all capability ports, and provider wiring. A non-ready server
  returns 503 and cannot create paid work.
- Redis Stream leases, CAS versions, frozen provider payload digests, and
  reconciliation prevent duplicate paid provider tasks.

## Deliverable

The final artifact is usfr-python-video-service.zip. It is a Docker build
context containing the immutable bundle, Compose topology, configuration
template, package verifier, deployment/readiness commands, and release
validation scripts. It starts with:

    cp .env.example .env
    # fill server-owned secrets and endpoint values
    docker compose up -d --build

## Verification

Before delivery, validate all of the following without a local Skill path:

1. bundle verifier and no-workstation-dependency tests;
2. Docker image build from the ZIP build context;
3. Compose healthz and readyz with Redis and MinIO;
4. no-provider API/queue/approval/cleanup E2E;
5. a user-authorized, paid RunningHub smoke only after credentials are present;
6. MinIO assertion that a succeeded cleanup leaves only the exact final MP4.

No paid provider task is created by packaging, build, readiness, or default
E2E verification.
