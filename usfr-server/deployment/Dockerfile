# Build context: the root of the universal-source-fidelity-replication bundle.
# The image contains the server package and deterministic contracts only;
# credentials, model weights, object-store adapters, and provider clients are
# injected by the deployment environment.
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    USFR_PROFILE_MODE=shadow \
    USFR_PROCESS_ROLE=worker \
    USFR_WORKER_BOOTSTRAP=server.deployment_bootstrap:run_worker \
    USFR_SWEEPER_BOOTSTRAP=server.deployment_bootstrap:run_sweeper

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates fonts-noto-cjk fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/usfr
ARG USFR_INSTALL_MODE=full
# Keep the complete deployment contract in the image.  The verifier checks
# Dockerfile, requirements.lock, and README together so a built image carries
# the same handoff metadata that was reviewed at source.
COPY deployment /opt/usfr/deployment
# A GPU build should override the PyTorch index and base image in its CI
# pipeline; the lock remains the single version authority.
RUN python -m pip install --upgrade pip \
    && if [ "$USFR_INSTALL_MODE" = "control-plane" ]; then \
         python -m pip install -r /opt/usfr/deployment/requirements-control-plane.lock; \
       elif [ "$USFR_INSTALL_MODE" = "full" ]; then \
         python -m pip install --extra-index-url https://download.pytorch.org/whl/cu124 -r /opt/usfr/deployment/requirements.lock; \
       else \
         echo "USFR_INSTALL_MODE must be control-plane or full" >&2; exit 2; \
       fi

COPY server /opt/usfr/server
COPY scripts /opt/usfr/scripts
COPY bundled-skills /opt/usfr/bundled-skills
COPY runtime-skills /opt/usfr/runtime-skills
COPY references /opt/usfr/references
COPY schemas /opt/usfr/schemas
COPY validation/case_catalog.json /opt/usfr/validation/case_catalog.json
COPY validation/high_fidelity/golden_cases.json /opt/usfr/validation/high_fidelity/golden_cases.json
COPY validation/high_fidelity/backend_policy.json /opt/usfr/validation/high_fidelity/backend_policy.json
COPY SKILL.md /opt/usfr/SKILL.md

# Fail at image build if the deployable bundle is incomplete.  Runtime
# capability identities and model SHA checks still occur at worker startup.
RUN python -B scripts/verify_bundle.py /opt/usfr

# The default process is the queue worker; deployments may override the
# command with the documented Uvicorn factory for the HTTP API.
EXPOSE 8080
CMD ["python", "-B", "-m", "server.worker_entrypoint"]

# Container-only deterministic video ports and API driver. This target is
# selected explicitly by the E2E profile and is never the default final image.
FROM runtime AS e2e
COPY validation/e2e /opt/usfr/validation/e2e

# Keep production as the final/default target, without validation/e2e bytes.
FROM runtime AS production
