# USFR Backend

This service exposes only the Universal Source-Fidelity Replication runtime:

- `GET /health`
- `/api/v1/replication/*` for the canonical durable USFR workflow
- `/api/v1/commercial-batches/*` for commercial batch admission, recovery, and results

The repository-owned canonical package is [`../usfr-server`](../usfr-server).
It contains fixed-slot intake, language-only RunningHub ASR/TTS/lip-sync,
background-music singing, composite product/model/App/UI/tail routes, deep
analysis, QA, and deployment contracts.

## Local validation

```powershell
cd backend
python -m pytest -q
```

For the local visual MVP, run `../usfr-local-console/start.ps1`. It reads the
same repository-owned Skill and sends commercial batches only to this API; it
never falls back to a local file queue.

## Deployment

Build a verified immutable package from `../usfr-server`:

```text
python -m app.usfr_bundle ^
  --source-root <repository>/usfr-server ^
  --output-root <image-build-context>/usfr-bundle ^
  --expected-skill-sha256 <sha256-of-SKILL.md>
```

Use the emitted skill and tree hashes with:

```text
REPLICATION_RUNTIME_FACTORY=app.usfr_commercial_deployment:build_replication_runtime
USFR_DEPLOYMENT_FACTORY=app.usfr_commercial_deployment:build_deployment_runtime
```

The deployment factory fails closed without its Redis, object-store,
capability, bundle, and provider settings. `background_music` additionally
requires a real deployment-owned execution adapter; it never falls back to
TTS, looping, or time-stretching.
