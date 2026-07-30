# Simplified Public Jobs API Contract

The deployable video service exposes exactly three public endpoints under
`/api/v1/jobs`. The Web client submits permanent Alibaba Cloud OSS URLs and
real business options only. It never submits SHA-256, byte size, MIME, duration,
FPS, revision, Redis version, object key, Provider task data, Seedance Prompt,
or approval digest.

The service remains internally strict. It downloads and probes each URL,
derives immutable media metadata, copies verified work bytes into the temporary
job store, and uses Redis CAS, revisions, Provider attempts, artifact receipts,
and quality evidence without exposing those fields publicly.

## Authentication and idempotency

- `POST /api/v1/jobs` requires a Web-generated high-entropy
  `Idempotency-Key`.
- A successful create returns `job_id`, one job-scoped `access_token`, and the
  public status.
- Every later request sends the token only as
  `Authorization: Bearer <access_token>`.
- The server stores only the token hash. The token is bound to one job.
- Replaying the same idempotency key with the identical body returns the same
  job and deterministically re-derived token without importing or charging
  twice. Reusing the key with a different body is rejected.
- Redis `expected_version`, revision numbers, and approval SHA values remain
  automatic internal concerns; callers never send them.

## Public endpoints

### `POST /api/v1/jobs`

Create, import, validate, and start a job in one call. `source_video` is
required and must be at most 30 seconds. At least one other supported option is
required: product image, model image, UI screenshot, App Store URL, UI operation
video, tail video, background music, or `output_language`.

The request contains URL-valued business fields only. The service allows only
configured OSS hosts for media and official Apple App Store or Google Play
hosts for `app_store_url`. It rechecks DNS and redirects, streams downloads,
probes actual bytes, and rejects unsupported or oversized media before any paid
model or Provider call.

Successful response:

```json
{
  "job_id": "job_123",
  "access_token": "job-scoped-secret",
  "status": "importing"
}
```

### `GET /api/v1/jobs/{job_id}`

Return only the minimal public projection:

- `importing`: OSS media is being downloaded and verified;
- `processing`: analysis, generation, assembly, or QC is running;
- `waiting_review`: the current editable script or storyboard is ready;
- `completed`: the permanent OSS `result_url` is available;
- `failed`: a stable public error is available.

Script review returns exactly one editable two-section Markdown document. It
does not expose internal JSON, SHA, line contracts, or revision metadata.
Storyboard review returns its preview image URLs. Completed jobs return only
the permanent OSS result URL in addition to job identity and status.

### `POST /api/v1/jobs/{job_id}/review`

The server infers whether the current review is the script or storyboard.

Approve:

```json
{"action":"approve"}
```

Revise:

```json
{"action":"revise","content":"完整修改后的两段式 Markdown 文字脚本，或故事板修改要求"}
```

Every admitted route pauses first for editable script review and then for
editable storyboard review. This includes language-only, opaque UI replacement,
tail-only, and uploaded-audio routes. Lightweight routes skip irrelevant deep
analysis or paid tools, not the two user reviews. Duplicate approval is
idempotent and cannot advance twice or create a duplicate paid task.

## UI operation video rules

- UI screenshot only: rebuild only the identified source UI intervals when a
  deterministic rebuild is the best route.
- UI operation video only: remove the source UI interval and splice the
  submitted operation video; its audio is muted by default.
- Both supplied: the operation video owns action and navigation while screenshots
  own style, text, button positions, and key-state calibration.
- UI tools never run globally. Non-UI intervals retain their normal route.

## Storage and result lifecycle

- Original user media remains permanently in the caller-managed OSS bucket.
- Verified working copies and all intermediate evidence live under the
  temporary job prefix and are deleted after terminal completion according to
  the configured retention policy.
- Only a verified final MP4 is promoted to
  `USFR_OSS_FINAL_PREFIX/final/{job_id}/result.mp4` and returned through the
  permanent HTTPS OSS/CDN base URL.
- Cleanup never deletes or overwrites original OSS media or the permanent final
  MP4.

## Non-public compatibility surface

The package may retain internal adapters and typed service methods for workers,
tests, reconciliation, and migration. They are not mounted by
`server.public_fastapi_router`, must not appear in public OpenAPI, and are not
called by the Web client. The public OpenAPI allowlist is exactly the three
endpoints above.
