# Youdao Seedance 2.0 Gateway

Use Youdao as the default Seedance provider. Read credentials only from
the worker environment or an explicit private `SEEDANCE_ENV_FILE`/`--env-file`
path; never write or print the API key elsewhere. A workstation
`~/.codex/secrets` file is development-only.

```dotenv
SEEDANCE_API_PROVIDER=youdao
YOUDAO_API_KEY=
YOUDAO_BASE_URL=https://openapi.youdao.com/llmgateway
YOUDAO_SEEDANCE_MODEL=seedance-2.0-fast
YOUDAO_SEEDANCE_RESOLUTION=720p
YOUDAO_PROJECT_NAME=default
```

## Authentication

All requests use JSON and these headers:

```text
x-api-key: ${YOUDAO_API_KEY}
Content-Type: application/json
```

Do not use a Bearer prefix.

## Asset lifecycle

Register only the approved storyboard, character, and product image URLs:

```text
POST /api/v1/assets?Action=CreateAsset
```

Send `URL`, `Name`, `AssetType=Image`, and `ProjectName=default`. `GroupId` is
optional. Read the asset identifier from `Result.id`, then poll:

```text
POST /api/v1/assets?Action=GetAsset
```

with `Id` and `ProjectName=default` until `Status=Active`. Use non-deadline polling
by returned state with bounded backoff; a production target is not a cancellation
deadline. Stop on
`Failed` or an explicit provider timeout. Cache successful Active mappings in
`youdao_assets.json` and reuse them across every segment; never upload the same
URL twice. Independent segment asset preparation may run concurrently, while
continuity-dependent assets keep their required ordering. Never register the
reference video, `opaque_ui_demo`, or supplied App tail-card media.

`CreateAsset` is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. It is non-idempotent: reuse a verified Active mapping when one already exists; otherwise preserve the source URL and reconcile provider state before any new registration. Automatic transient retry is limited to idempotent GetAsset/readiness calls.

## Video task

Create:

```text
POST /api/v1/video/tasks
```

Query:

```text
GET /api/v1/video/tasks/{taskId}?model={model}
```

Supported gateway models are `seedance-2.0` and `seedance-2.0-fast`. The factory
defaults to `seedance-2.0-fast`, `720p`, `9:16`, `generate_audio=true`, and
`watermark=false`. The fast model supports 480p and 720p, not 1080p or 4K.

The request `content` starts with one text item. Add each image as an
`image_url` item with `role=reference_image` and an `asset://asset-*` URL. The
prompt refers to those images as `图片1`, `图片2`, and so on; never put asset IDs
inside prompt prose. This factory accepts at most four images and never sends
`reference_videos` or `reference_audios`.

Valid task states are `submitting`, `queued`, `running`, `succeeded`, `failed`,
and `expired`. Poll until `succeeded`, extract the returned `video_url`, and stop
without automatic resubmission on `failed`, `expired`, or an unknown state. For
two independent segments, submit and poll concurrently; preserve ordering when
segment 2 requires segment 1 pixels. Reuse a known task ID rather than creating
a duplicate paid task.

`CreateVideo` is never automatically retried after a 429, 5xx, timeout, connection reset, or ambiguous response. The create call is non-idempotent: preserve the exact audited request, reconcile provider state, and resume only when a task ID is known. Transient retry remains available only for idempotent status/readiness calls.

Keep prompts under 5000 characters and durations from 4 through 15 seconds.
Compile through `seedance-20`, build the exact final payload, and generate one
unauthorised pre-audit dry-run request preview without authorization/audit/
contract flags. Run a script-to-prompt parity audit against that exact request,
save the internal SHA256 digest, then authorize the paid task internally with
the complete set `--audited-request-sha256`, `--audit-artifact`,
`--approved-script-sha256`, `--seedance-input-contract`, and
`--seedance20-skill-file`. Any digest mutation fails closed; unsafe asset
changes and duplicate paid retries remain blockers. Successful delivery returns
only `final/result.mp4` after final QC.

## Audited Factory submission requirements

The normal Factory route also passes `--seedance-input-contract` and
`--seedance20-skill-file` (defaulting to the installed root
`seedance-20/SKILL.md`). The frozen input contract is hashed from exact raw
bytes and must contain the approved-script digest, all eight required contract
digests, the exact 13 audit-check list, and the complete unique factor-ID set.
The installed skill file must declare `name: seedance-20`; its exact-byte hash
and authoritative metadata version must match the compiler artifact.

Only this audited Factory path enforces the fixed-B payload shape: model
`seedance-2.0-fast`, `resolution=720p`, `ratio=9:16`, duration 4–15,
`generate_audio=true`, `watermark=false`, one exact text item, and at most four
exact `reference_image` asset objects. Unknown fields and reference/UI,
tail-card, source-frame, or transition markers in any separator/case variant
are rejected. The unauthorised `--dry-run` is the only preview route and cannot
carry audited or legacy authorization. After that dry run, actual audited
submission is cache-only for Youdao assets: each mapping must be Active, carry
a non-empty `asset_id`, use exactly `asset://{asset_id}`, and match the client
project name. Missing or invalid provenance cannot register, poll, or rewrite
the manifest. Legacy `--approved-request-sha256` remains compatibility-only;
it is not the normal Factory path and cannot be mixed with audited flags. A
plain `--resume-task-id` is a separate known-task route: it does not require a
new prompt or duration, performs no asset preparation or payload build, cannot
be combined with `--dry-run`, and cannot carry any new-request authorization,
audit, script, or input-contract flags.

Source documentation:
`https://ai.youdao.com/DOCSIRMA/html/thinkflow/api/seedance/index.html` and the
nested Volcano Engine Seedance 2.0 parameter/private-asset documentation.
Asset manifests are protected by a cross-process lock keyed to the resolved
manifest path. The lock spans manifest reload, bounded registration/polling,
and atomic write. A later invocation therefore re-reads and reuses an Active
mapping; duplicate source URLs are registered once and input order is retained.

## Factory integrity and route invariants

After the latest storyboard approval, freeze `seedance_input_contract.json` and
recompile the final prompt through `seedance-20`. Build one exact dry-run
payload, then compare approved Cut order, character lock, product lock,
duration/timecodes, voiceover/audio, camera/actions/transitions, continuity,
selling-point evidence, timeline-region routing, reference mapping, provider
parameters, and negative constraints. Require zero ambiguity and no unresolved
placeholders before **internal request integrity approval**. This is not a
third user approval gate; prompt-only repair stays internal.

The fixed factory route is `seedance-2.0-fast`, `720p`, `9:16`, fixed-B image
references, no `reference_videos`, and no default `reference_audios`. Opaque UI
videos, source-origin UI intervals, and tail-card media are never registered,
never sent to Image Gen or Seedance, and never counted in paid generation
duration. A missing tail video uses `omit_source_end_card` and removes the
source terminal interval; missing supplied opaque UI media is a blocker.

Independent asset preparation and independent segment submission/polling may run
concurrently; dependency-locked work remains ordered. Reuse cached Active
assets and known task IDs. Never create duplicate paid tasks. Submit only the
unchanged internally audited digest, and after final QC deliver only
`final/result.mp4`.

For the optional high-fidelity profile, the worker must inject a packaged
Seedance-20 snapshot (for example `SEEDANCE20_SKILL_FILE`) and may bind the
immutable profile/prescript artifacts before Invocation B. The submitter never
falls back to `~/.codex/skills`; an absent or stale snapshot blocks before any
CreateAsset/CreateVideo call. `--resume-task-id` remains side-effect-free and
cannot carry profile, prescript, prompt, duration, audit, or authorization flags.
