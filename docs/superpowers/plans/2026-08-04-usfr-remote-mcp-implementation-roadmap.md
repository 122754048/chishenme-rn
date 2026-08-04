# USFR Remote MCP MVP Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an internally hosted remote MCP that wraps an immutable copied USFR runtime, supports single and explicitly authorized batch replication, preserves source-analysis reuse, and enforces configurable usage budgets.

**Architecture:** Build a new `usfr-mcp/` control plane beside an imported, hash-pinned `usfr-runtime/` copy of the supplied ZIP. PostgreSQL owns permanent product metadata; Redis and the copied USFR Jobs API retain execution authority; OSS owns persistent media; the MCP control plane exposes OAuth-protected Streamable HTTP tools and never reveals Provider secrets.

**Tech Stack:** Python 3.12, FastAPI 0.116, MCP Python SDK, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7.4, boto3/OSS-compatible storage, httpx, Authlib, argon2-cffi, pytest, Ruff, Docker Compose, Caddy.

## Global Constraints

- Never modify `C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\SKILL.md` or any file below that Skill directory.
- Import from `C:\Users\zhaocx04\Documents\我的POPO\usfr-optimized-gap-closure-2026-07-30-with-env-linux-fixed-v2.zip`; exclude `.env`, caches, generated artifacts, and all secret values.
- Preserve the copied USFR runtime's Jobs API, Redis authority, Provider idempotency, song/non-song classifier contract, lip-sync routing, assembly, and QC behavior.
- Public input exposes eight media slots; internally map `background_music` to the copied runtime's `audio` field / existing background-music contract.
- A batch contains at most 20 outputs and defaults to five concurrent child jobs; both values are configurable within the approved limits.
- User intent is the sole batch-combination authority. Never create Cartesian products, cycle shorter lists, truncate unmatched lists, or infer pairings from filenames.
- No paid Job may be created before the user confirms the deterministic execution summary.
- No non-pilot batch Job may start before the pilot script, storyboard, and final MP4 have been approved.
- Default limits: 50 outputs per user per day and CNY 10,000 company spend per month; values live in PostgreSQL settings, not constants in orchestration code.
- Provider keys, USFR capability tokens, signed upload credentials, internal prompts, and provider payloads never appear in MCP tool results, public errors, logs, or permanent user-visible artifacts.
- MVP uses local accounts and OAuth 2.1 authorization-code + PKCE; it does not include enterprise SSO, MFA, device binding, IP allowlists, or single-session enforcement.

---

## Plan Suite

Implement the following plans in order. Each plan ends with a working, independently reviewable system increment.

1. [Foundation, runtime import, persistence, OAuth, and MCP shell](2026-08-04-usfr-mcp-foundation-auth-plan.md)
2. [Source Library, uploads, and single-replication integration](2026-08-04-usfr-mcp-source-single-plan.md)
3. [Explicit-intent batch orchestration and pilot authorization](2026-08-04-usfr-mcp-batch-plan.md)
4. [Usage ledger, admin controls, secret hygiene, and audit](2026-08-04-usfr-mcp-usage-admin-plan.md)
5. [Linux deployment, recovery, and acceptance validation](2026-08-04-usfr-mcp-deployment-acceptance-plan.md)

## Phase Exit Gates

### Phase 1 exit

- `usfr-runtime/` can be recreated deterministically from the supplied ZIP without copying `.env`.
- Runtime and local Skill SHA-256 values are recorded and tested.
- PostgreSQL migrations create users, OAuth grants/tokens, settings, Source Masters, Jobs, Batches, artifacts, usage reservations, and audit events.
- A user can authenticate through OAuth authorization-code + PKCE and call a read-only MCP `whoami` tool.

### Phase 2 exit

- A user can upload or register all eight public slots through signed object-store operations.
- The same user's exact Source Master and analysis version can be reused; another user cannot discover or reuse it.
- A confirmed single-job summary creates exactly one copied-USFR Job.
- Script/storyboard review resources and the final MP4 are available through MCP without exposing the USFR capability token.

### Phase 3 exit

- Explicit batch intent produces a deterministic preview with no paid calls.
- Ambiguous multi-asset inputs return `clarification_required`.
- Pilot final approval signs the immutable batch authorization.
- Remaining child Jobs run with bounded concurrency, partial success, safe retry, and Provider reconciliation.

### Phase 4 exit

- Daily user output limits, monthly company budget, reservations, settlement, and release are transactionally enforced.
- Admins can create/disable users, change limits/concurrency, transfer complete asset ownership, and inspect sanitized usage/audit data.
- Secret-scanning tests cover MCP content, public errors, application logs, and persisted public metadata.

### Phase 5 exit

- One Docker Compose command starts Caddy, MCP/API, PostgreSQL, Redis, MinIO, copied USFR API, Worker, and Sweeper.
- Readiness fails when the uploaded-audio classifier or required Provider/model capabilities are missing.
- Shadow E2E covers real single, pilot-gated batch, five-way concurrency, partial failure, restart recovery, cost accounting, and final-only delivery.

## Review and Commit Policy

- Use TDD for every task: failing test, minimal implementation, focused test pass, broader regression, commit.
- Commit only files named by the current task. Preserve unrelated user changes and untracked files.
- Run `git diff --check` before every commit.
- Run the copied USFR contract subset after any adapter or deployment change; never modify runtime behavior merely to satisfy the new control plane.
- Keep commits phase-local and revertible; do not combine OAuth, batch scheduling, and deployment changes in one commit.

## Spec Coverage Matrix

| Approved design area | Implementing plan |
| --- | --- |
| Immutable local Skill and sanitized ZIP import | Foundation Tasks 1 and 6; Deployment Task 6 |
| Local accounts, OAuth, MCP `/mcp` | Foundation Tasks 3–5 |
| Eight slots and background-music projection | Source/Single Tasks 1, 4, and 5 |
| Unified single/batch preview and ambiguity questions | Source/Single Task 5; Batch Task 1 |
| Source Master ownership and permanent original | Source/Single Tasks 1–2 |
| Real analysis reuse rather than metadata-only cache | Source/Single Task 3 |
| Single script/storyboard approvals and final result | Source/Single Task 6 |
| Permanent script, storyboard, and MP4 archive | Source/Single Task 6 |
| Explicit Batch Intent and no permutations | Batch Tasks 1–2 |
| Fixed Pilot and final-MP4 authorization | Batch Tasks 2–3 |
| Pilot-only versus batch-wide revisions | Batch Task 3 |
| Automatic child approvals, concurrency five | Batch Task 4 |
| Partial success, cancellation, retry, reconciliation | Batch Task 5 |
| Daily 50, monthly CNY 10,000, reservations | Usage/Admin Tasks 1–2 |
| Configurable users, limits, concurrency | Usage/Admin Task 3 |
| Complete employee asset transfer | Usage/Admin Task 4 |
| Secret redaction and audit | Usage/Admin Task 5 |
| Linux Compose, private service ports, HTTPS | Deployment Task 1 |
| Music-classifier and Provider readiness | Deployment Task 2 |
| Backup and restart recovery | Deployment Task 3 |
| Deterministic and real Shadow acceptance | Deployment Tasks 4–6 |
