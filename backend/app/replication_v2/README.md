# Replication v2 production wiring

`app.replication_v2` mounts the canonical Universal Source-Fidelity server
without copying its orchestration logic into the application. Development may
construct the mount from a SQLite database path. Production is fail-closed.

## Required production adapters

Production must inject all three dependencies:

1. `repository`: an authoritative, non-SQLite transactional repository that
   implements the complete repository surface consumed by the canonical
   `server.fastapi_router`, `server.service`, and workers. It must preserve
   tenant isolation, compare-and-swap run versions, idempotency reservations,
   provider intents/tasks, leases, immutable artifacts, and mutation plus
   outbox publication in the same transaction. It must also implement
   `recover_inflight_provider_intents()`. PostgreSQL is the intended production
   implementation; local files and cache snapshots are never authoritative.
2. `object_store`: a tenant-scoped private object-store adapter with both
   `head(object_key=..., tenant_id=...)` and
   `signed_download(run_id=..., artifact_id=...)`. `head` must return the
   completed object's authoritative hash, byte size, MIME type, completion
   state, and video duration when applicable. `signed_download` must return a
   short-lived private URL after the caller's run ownership has been checked.
3. `provider_lookup`: a callable accepting a persisted provider-intent mapping
   and returning the already-created task/asset identity plus its status. It is
   a read/reconciliation port only: it must never create or blindly retry a
   CreateAsset/CreateVideo request.

An optional `artifact_store` may additionally implement `put_stream(...)` for
the canonical `ReplicationService.publish_artifact` helper. If omitted,
workers must bind verified private artifact URIs through their own publication
adapter before production QC; hash-only final artifacts are rejected.

When `APP_ENV` is `prod` or `production`, the wrapper rejects a missing adapter,
an injected canonical `SQLiteRepository`, an object store lacking either
required method, or a non-callable Provider lookup. It also passes
`allow_local_paths=False` and `allow_unsigned_artifact_uris=False` to the
canonical API.

## Injection options

An application factory may inject dependencies directly:

```python
mount_replication_v2(
    app,
    repository=postgres_replication_repository,
    object_store=private_object_store,
    artifact_store=private_artifact_store,
    provider_lookup=provider_status_lookup,
)
```

The existing `app.main:app` entrypoint mounts during module import, so
production deployments should set one server-controlled factory path:

```text
APP_ENV=production
REPLICATION_RUNTIME_FACTORY=deployment.replication_runtime:build_runtime
```

The zero-argument factory returns only these keys:

```python
def build_runtime():
    return {
        "repository": build_postgres_replication_repository(),
        "object_store": build_private_object_store(),
        "artifact_store": build_private_artifact_store(),
        "provider_lookup": build_provider_status_lookup(),
    }
```

Explicit function arguments take precedence over factory values. Provider
credentials and object-store credentials belong in the deployment secret
manager used by the factory; clients must never submit them.
