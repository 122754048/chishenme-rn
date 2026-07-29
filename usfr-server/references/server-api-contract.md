# Jobs API Contract

The video-only HTTP surface is `/api/v1/jobs`. It is stateless apart from the
temporary Redis JobStore and exposes no account, tenant, history, analytics,
billing, generic artifact browser, event stream, or SQL-backed Run API.

## Authentication and concurrency

`POST /api/v1/jobs` returns a high-entropy job capability once. Every later job
request requires `Authorization: Bearer <capability>`. Only its hash is stored.
Every mutation carries `expected_version`; Redis CAS rejects stale writers.

## Endpoints

- `POST /api/v1/jobs`: validate the seven fixed slots and optional
  `output_language`, create temporary job authority, and return the capability.
  Any object-store upload completion also requires one safe `upload_scope`;
  every object key must be inside `uploads/{upload_scope}/`, and the configured
  object store must verify
  its key, SHA-256, size, MIME, and video duration before admission. The valid
  source-video-plus-language route uses the same verification and ownership
  path rather than bypassing intake.
- `GET /api/v1/jobs/{job_id}`: current temporary job snapshot.
- `POST /api/v1/jobs/{job_id}/start`: enter analysis.
- `GET /api/v1/jobs/{job_id}/scripts`: browse script revisions.
- `POST /api/v1/jobs/{job_id}/scripts/revise`: direct edit, instruction-based
  edit, regeneration, or selected-Cut regeneration.
- `POST /api/v1/jobs/{job_id}/scripts/{revision}/approve`: approve the exact
  revision SHA-256.
- Equivalent storyboard list/revise/approve endpoints.
- `POST /api/v1/jobs/{job_id}/provider/reconcile`: deployment-owned ambiguous
  Provider reconciliation boundary; unavailable deployments return 503 and do
  not resubmit.
- `GET /api/v1/jobs/{job_id}/result`: final MP4 result handle only.

The API does not accept a client Provider key, arbitrary final Prompt,
unregistered reference list, local path, or legacy approval digest. Preview
URLs are signed by the object-store adapter. An expired/deleted job returns
`JOB_GONE` (410).
