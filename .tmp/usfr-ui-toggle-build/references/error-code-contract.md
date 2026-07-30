# Error Code Contract

Errors are JSON objects with `code`, `category`, `message`, `stage`, `run_id`,
`retryable`, `user_action_required`, `correlation_id`, `occurred_at`,
`provider`, `provider_code`, `details`, and `next_actions`.

| Code | HTTP | Meaning |
| --- | ---: | --- |
| `INPUT_SOURCE_REQUIRED` | 400 | Source video missing |
| `INPUT_SOURCE_INVALID` | 422 | Source video cannot be decoded or probed |
| `INPUT_SLOT_INVALID` | 400 | Slot type/path/hash invalid |
| `INPUT_REQUEST_INVALID` | 400 | HTTP request body or header violates the typed command contract |
| `OBJECT_STORE_UNAVAILABLE` | 503 | Object-store completion adapter is not configured |
| `OBJECT_STORE_REQUIRED` | 503 | Production input must use a verified private object-store reference |
| `MIN_ONE_OPTIONAL_INPUT_REQUIRED` | 422 | Only source video was supplied |
| `INPUT_SOURCE_TOO_LONG` | 422 | Source exceeds 30 seconds |
| `STATE_CONFLICT` | 409 | Illegal command or stale version |
| `APPROVAL_REQUIRED` | 409 | Required approval is absent |
| `APPROVAL_STALE` | 409 | Approval hash/version no longer matches |
| `CONTRACT_INVALID` | 422 | Contract/schema validation failed |
| `PROMPT_INTEGRITY_FAILED` | 422 | Seedance-20 parity/audit failed |
| `ASSET_CREATE_AMBIGUOUS` | 503 | CreateAsset outcome unknown |
| `VIDEO_CREATE_AMBIGUOUS` | 503 | CreateVideo outcome unknown |
| `PROVIDER_SUBMISSION_FENCED` | 409 | Another active CreateVideo intent owns the same Run/operation/Segment fence |
| `PROVIDER_TASK_ID_MISMATCH` | 409 | Provider lookup/status identity differs from the durable intent/task binding |
| `PROVIDER_RECONCILIATION_REQUIRED` | 409 | Polling is blocked until an ambiguous provider intent is reconciled |
| `PROVIDER_RECONCILIATION_UNAVAILABLE` | 503 | No provider lookup adapter is configured |
| `PROVIDER_AUTH_FAILED` | 502 | Provider credentials rejected |
| `PROVIDER_RATE_LIMITED` | 429 | Provider rate limit |
| `PROVIDER_TASK_FAILED` | 502 | Known provider task failure |
| `PROVIDER_TIMEOUT` | 504 | Bounded provider wait expired |
| `ARTIFACT_HASH_MISMATCH` | 422 | Stored bytes differ from contract |
| `ARTIFACT_METADATA_MISMATCH` | 422 | Stored object size, MIME, or completion metadata differs from contract |
| `ARTIFACT_URI_REQUIRED` | 503 | Production final/QC artifact has not been bound to a private object-store URI |
| `ARTIFACT_CONFLICT` | 409 | Immutable artifact ID already maps to different bytes |
| `ARTIFACT_NOT_FOUND` | 404 | Requested artifact is not available for the authenticated run |
| `ARTIFACT_STORE_UNAVAILABLE` | 503 | Artifact publication or local atomic store is unavailable |
| `ASSEMBLY_FAILED` | 422 | Timeline assembly failed |
| `AUDIO_LAYER_POLICY_REQUIRED` | 422 | Source speech overlaps supplied opaque UI/tail media without a valid pre-bound receipt or an explicitly capable bundled mixer, or the renderer-produced final-bound receipt fails validation |
| `QC_FAILED` | 422 | Final quality gate failed |
| `IDEMPOTENCY_CONFLICT` | 409 | Key reused with different digest |
| `IDEMPOTENCY_IN_PROGRESS` | 409 | Another worker owns the same command reservation |
| `IDEMPOTENCY_RECONCILIATION_REQUIRED` | 409 | A crash-left reservation is blocked pending operator/external-side-effect reconciliation |
| `IDEMPOTENCY_RECOVERED_AFTER_RESTART` | 409 | A crash-left reservation was reopened for safe retry |
| `IDEMPOTENCY_KEY_INVALID` | 400 | Idempotency key is empty or exceeds the contract limit |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | Mutating request omitted Idempotency-Key |
| `WORKER_LEASE_LOST` | 409 | Worker lost its lease |
| `WORKER_LEASE_ACTIVE` | 409 | Another worker still holds the stage lease |
| `STAGE_EXECUTION_IN_PROGRESS` | 409 | Prior stage execution is unknown and cannot be auto-replayed |
| `RUN_NOT_FOUND` | 404 | Run does not exist for the authenticated tenant |
| `TENANT_REQUIRED` | 401 | Authenticated tenant context is missing |
| `ACTOR_REQUIRED` | 401 | Authenticated actor context is missing for an approval |
| `AUTH_INVALID` | 401 | Bearer authentication is invalid |
| `AUTH_REQUIRED` | 401 | Bearer authentication is required |
| `INTERNAL_ERROR` | 500 | Unexpected server error |
