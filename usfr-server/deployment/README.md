# Stateless deployment boundary

Build one image for the API, Redis Streams Worker, and cleanup Sweeper:

```text
docker build -f deployment/Dockerfile -t usfr:<immutable-tag> .
```

The image contains the verified Universal Source Fidelity bundle, the existing
seven fixed input slots, and the existing twelve-stage video workflow. Runtime
state is short-lived Redis metadata; media is stored in a private S3-compatible
object store. Production does not load workstation Skill paths and does not
require a relational persistence, identity, billing, history, or Outbox layer.

## Deployment factory

The image includes `server.packaged_factory:build_runtime`, which is the
default `USFR_DEPLOYMENT_FACTORY`. The function
returns already-constructed dependencies with this exact shape:

```python
{
    "job_store": redis_ephemeral_job_store,
    "work_queue": redis_streams_work_queue,
    "object_store": s3_compatible_object_store,
    "cleanup_sweeper": cleanup_sweeper,
    "service": fastapi_app_or_zero_argument_factory,
    "worker_manager": video_worker_manager,
    "readiness_checks": {
        "redis": check_redis,
        "object_store": check_object_store,
        "bundle": check_immutable_bundle,
        "models": check_model_adapters,
        "capabilities": check_video_capabilities,
        "provider": check_provider_ports,
    },
}
```

The Worker manager must keep `allow_local_paths=False`, use an immutable
packaged bundle resolver, expose all seven existing capability ports, and
implement `validate_startup_capabilities()` plus
`process_work_message(message=..., checkpoint=..., owner=...)`. This explicit
adapter contract rejects the legacy persistence-backed Worker instead of
calling its incompatible `execute_stage(...)` signature after a Redis claim.

The six readiness names are exact. Legacy persistence and identity dependencies
are rejected at startup rather than silently accepted by the factory.

Real video execution also requires `USFR_PORT_FACTORY` to name a packaged
`module:function` returning complete `stage_ports` and `capability_ports`.
Missing real ports fail startup. `USFR_READINESS_ONLY=true` is permitted only
for infrastructure E2E; its ports deliberately raise if work is dispatched and
therefore cannot be used as video-generation evidence.

## Process commands

API:

```text
python -B -m uvicorn server.deployment_bootstrap:build_http_app --factory --host 0.0.0.0 --port 8080
```

Worker (the image default):

```text
USFR_PROCESS_ROLE=worker
USFR_WORKER_BOOTSTRAP=server.deployment_bootstrap:run_worker
python -B -m server.worker_entrypoint
```

The Worker reads Redis Streams messages, claims the job-scoped stage checkpoint,
executes the existing video stage, commits `complete_stage()`, and only then
ACKs the stream message. A failure before checkpoint commit leaves the delivery
pending for lease recovery.

Sweeper:

```text
USFR_PROCESS_ROLE=sweeper
USFR_SWEEPER_BOOTSTRAP=server.deployment_bootstrap:run_sweeper
python -B -m server.worker_entrypoint
```

The Sweeper calls `CleanupSweeper.sweep_once()` on a short interval. Cleanup is
idempotent and preserves the exact final `result.mp4` according to the existing
object lifecycle contract.

## Compose topology

`deployment/docker-compose.yml` defines Redis Standalone plus the API, Worker,
and Sweeper processes. Supply a packaged factory and any S3-compatible endpoint:

```text
USFR_DEPLOYMENT_FACTORY=server.packaged_factory:build_runtime
USFR_PORT_FACTORY=my_deployment.video_ports:build_ports
USFR_S3_ENDPOINT=https://s3.example.internal
USFR_S3_BUCKET=usfr-media
docker compose -f deployment/docker-compose.yml up --build redis api worker sweeper
```

For local integration only, the `e2e` profile also starts MinIO and can run a
real-MP4 control-flow driver. The E2E target is explicit: production remains
the default Docker target and does not contain `validation/e2e`.

```text
USFR_CAPABILITY_SECRET=<at-least-32-bytes>
USFR_DOCKER_TARGET=e2e
USFR_PORT_FACTORY=validation.e2e.ports:build_ports
USFR_INSTALL_MODE=control-plane
docker compose -f deployment/docker-compose.yml --profile e2e up --build --abort-on-container-exit --exit-code-from e2e e2e
```

This path uploads small source/UI/tail MP4s to MinIO, creates a job through the
public API, waits at and approves both script and storyboard revisions, runs
the Redis Worker through assembly and QC, invokes `CleanupSweeper`, downloads
the final playable MP4, rejects black intervals, and asserts that object
storage adds only the current job's `final/{job_id}/result.mp4` while its exact
upload and temporary prefixes are removed. Prior jobs' successful final MP4s
remain valid. The packaged ports are
deterministic E2E doubles, so this is container/control-flow evidence only; it
is not Seedance, generated-UI, semantic-fidelity, or ad-grade quality evidence.

For the fast infrastructure-only E2E, set a stable secret and explicitly enable
the non-executable readiness mode:

```text
USFR_CAPABILITY_SECRET=<at-least-32-bytes>
USFR_READINESS_ONLY=true
USFR_INSTALL_MODE=control-plane
docker compose -f deployment/docker-compose.yml --profile e2e up --build redis minio minio-init api
# In another shell: curl --fail http://localhost:8080/readyz
```

Use `USFR_INSTALL_MODE=full` with a real packaged port factory for actual video
generation.

MinIO is not production authority. Production may use AWS S3, MinIO, Ceph, or
another S3-compatible private endpoint through the injected object-store client.

`/healthz` is liveness-only. `/readyz` returns 503 until all six required
dependencies report ready. Neither endpoint creates a job, stage, Provider task,
or durable event history.

For step-by-step server setup, read
`references/server-deployment-step-by-step.md`. For future workflow and adapter
updates, read `references/update-maintenance-playbook.md`. After the server is
configured, run `references/post-deployment-test-plan.md` before the full
36-case release matrix.
