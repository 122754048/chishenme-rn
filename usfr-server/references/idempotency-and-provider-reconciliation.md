# Redis Idempotency and Provider Reconciliation

Job mutation idempotency comes from Redis CAS plus operation-specific dedupe
keys. Stage execution additionally uses a lease-fenced checkpoint and Redis
Streams message dedupe. There is no relational idempotency table or Outbox.

Before a paid call, store a `ProviderAttempt` containing operation, exact
canonical request SHA-256, Segment ID where applicable, Segment-plan SHA-256,
status, and provider task ID/receipt when known. One frozen Segment may have
only one active attempt for the same request authority.

Results are classified as:

- `PREPARED`: no provider request sent.
- `SUBMITTING`: request boundary entered.
- `RUNNING`: provider task ID known.
- `SUCCEEDED` or `FAILED`: terminal known outcome.
- `AMBIGUOUS`: request may have been accepted but no trustworthy result is
  known.

Timeouts, connection resets, 429, and 5xx after the submission boundary never
cause automatic resubmission. If the Provider supports lookup, reconcile using
the stored exact request/task authority. If it cannot establish the outcome,
keep the job blocked. Recovery may change the method only when the frozen goal
contract permits it; it cannot erase or duplicate an unresolved paid attempt.
