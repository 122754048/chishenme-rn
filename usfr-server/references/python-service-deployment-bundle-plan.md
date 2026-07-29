# Python Full-Video Service Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver one Docker Compose ZIP that runs the canonical local Skill as
a Python API, Worker, Sweeper, Redis, and MinIO service without reading a
workstation path or requiring an external Python port-factory module.

**Architecture:** Add a packaged port factory that binds the existing server
stage/capability interfaces to GPT API reasoning and the existing RunningHub
media workflows. Keep all existing slot, route, approval, provider,
timeline, QC, and cleanup contracts unchanged. Add a deterministic ZIP
builder that copies only deployment runtime bytes and configuration templates.

**Tech Stack:** Python 3.12, FastAPI, Redis Streams, MinIO, Docker Compose,
FFmpeg, GPT API, RunningHub API, pytest, zipfile.

## Global Constraints

- GPT API is the only semantic inference authority.
- RunningHub retains the local Skill media-workflow roles.
- Preserve seven slots, the optional background-music extension, twelve
  semantic stages, approval behavior, and at-most-two Seedance tasks.
- The server must not read a user device path, Codex Skill install path, local
  run directory, or external port-factory Python module.
- Redis, uploads, and temporary objects expire; a successful QC-approved
  final/job-id/result.mp4 is the only retained media object.
- No provider task may be created by image build, packaging, readiness, or
  default no-provider tests.
- The distribution contains no secret, cache, Git metadata, test result,
  source input, generated intermediate, or final video.

---

### Task 1: Add one GPT API evidence gateway

**Files:**

- Create: server/gpt_evidence_gateway.py
- Create: tests/test_gpt_evidence_gateway.py
- Modify: server/production_ports.py

**Interfaces:**

- Consumes: ProductionEnvironment and immutable job media bytes materialized by
  EphemeralStageContext.
- Produces: GptEvidenceGateway with analyze, recognize, evaluate, and
  capability_identity methods. Every response includes request SHA-256,
  response SHA-256, source/media SHA-256, model identity, and a versioned
  evidence receipt.
- Used by: Task 2 packaged port factory.

- [ ] **Step 1: Write the failing gateway contract tests**

    def test_gateway_rejects_local_path_and_requires_gpt_response_receipt():
        gateway = GptEvidenceGateway(config=valid_config, request_json=fake_response)
        with pytest.raises(GptEvidenceError, match="local path"):
            gateway.analyze(path="C:/source.mp4", evidence={})

    def test_gateway_binds_media_and_model_identity_to_every_receipt():
        result = gateway.recognize(media_bytes=b"ui", expected_text=["Buy"])
        assert result["input_sha256"] == sha256(b"ui").hexdigest()
        assert result["model_sha256"] == MODEL_SHA
        assert result["receipt"]["schema_version"] == "usfr-gpt-evidence/v1"

- [ ] **Step 2: Run the focused test to verify it fails**

    Run: python -B -m pytest tests/test_gpt_evidence_gateway.py -q
    Expected: FAIL because gpt_evidence_gateway does not exist.

- [ ] **Step 3: Implement the minimal GPT gateway**

    class GptEvidenceGateway:
        def analyze(self, *, media_bytes: bytes, evidence: Mapping[str, Any]) -> Mapping[str, Any]: ...
        def recognize(self, *, media_bytes: bytes, expected_text: Sequence[str]) -> Mapping[str, Any]: ...
        def evaluate(self, *, media_bytes: bytes, rubric: Mapping[str, Any]) -> Mapping[str, Any]: ...
        def capability_identity(self) -> Mapping[str, str]: ...

    The gateway must call only the configured HTTPS GPT API URL, attach the
    configured model identifier, reject local paths and unhashed bytes, and
    validate a structured object before returning it. Reuse
    ProductionEnvironment URL, credential, public-host, and model-config
    checks; add no second model-provider configuration.

- [ ] **Step 4: Extend ProductionEnvironment with one shared GPT model
  identity**

    Add fields for the configured model SHA-256 and optional API endpoint
    suffix. Preserve existing OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
    and OPENAI_MODEL_CONFIG_SHA256 validation. Do not store the credential in
    the dataclass or receipts.

- [ ] **Step 5: Run focused gateway and existing production-port tests**

    Run: python -B -m pytest tests/test_gpt_evidence_gateway.py tests/test_production_ports.py -q
    Expected: PASS.

### Task 2: Package the real service port factory

**Files:**

- Create: server/packaged_ports.py
- Create: tests/test_packaged_ports.py
- Modify: server/packaged_factory.py
- Modify: server/__init__.py

**Interfaces:**

- Consumes: environment-only ProductionEnvironment, GptEvidenceGateway,
  RunningHub configuration, ImmutableBundleResolver, and the existing real
  capability classes.
- Produces: build_ports() -> Mapping[str, Any] with every EXECUTABLE_STAGES
  name in stage_ports and every REQUIRED_CAPABILITIES name in capability_ports.
- Used by: packaged_factory._ports when USFR_PORT_FACTORY is unset.

- [ ] **Step 1: Write failing packaged-port tests**

    def test_default_packaged_port_factory_has_exact_stage_and_capability_sets(monkeypatch):
        configure_all_server_environment(monkeypatch)
        ports = build_ports()
        assert set(ports["stage_ports"]) == set(EXECUTABLE_STAGES)
        assert set(ports["capability_ports"]) == set(REQUIRED_CAPABILITIES)

    def test_default_factory_never_uses_local_skill_or_external_python_module(monkeypatch):
        configure_all_server_environment(monkeypatch)
        monkeypatch.delenv("USFR_PORT_FACTORY", raising=False)
        runtime = build_runtime(redis_client=memory_redis, s3_client=memory_s3, bucket="media")
        assert runtime.worker_manager.profile_bundle_resolver.immutable is True

- [ ] **Step 2: Run the focused tests to verify failure**

    Run: python -B -m pytest tests/test_packaged_ports.py tests/test_packaged_factory.py -q
    Expected: FAIL because server.packaged_ports does not exist and the default
    factory rejects missing ports.

- [ ] **Step 3: Bind direct capabilities to existing concrete adapters**

    build_ports() must create:

    - FfmpegDynamicsAnalyzer with a GPT-backed semantic analyzer;
    - an ASR adapter that calls the configured existing RunningHub Whisper
      workflow and returns the current audio-contract schema;
    - DeterministicUiRenderer with GPT-backed OCR/layout evidence and the
      existing deterministic video renderer boundary;
    - SeedanceInvocationAdapter using the packaged ImmutableBundleResolver;
    - FfmpegCompositor with BundledTimelineRenderer;
    - FfmpegQcEngine with a GPT-backed semantic evaluator;
    - RunningHubSeedanceProvider for asset/video create and lookup.

    Wrap each adapter with BoundRuntimeCapability using immutable
    implementation, version, and SHA-256 identities. Build direct stages with
    CapabilityStagePort and composite stages with BoundStagePort plus the
    existing high-fidelity stage adapter. Existing handlers remain responsible
    for bind_inputs, probe_source, route_regions, App Store parsing,
    segment_plan, provider polling, and revision manifests.

- [ ] **Step 4: Change packaged_factory default selection**

    Replace the non-readiness missing-port error with:

    if not spec and not readiness_only:
        result = packaged_ports.build_ports()

    Preserve explicit USFR_PORT_FACTORY override validation for advanced
    deployments and preserve readiness-only ports for infrastructure tests.

- [ ] **Step 5: Verify startup validation**

    Run: python -B -m pytest tests/test_packaged_ports.py tests/test_packaged_factory.py tests/test_capability_ports.py tests/test_no_workstation_dependency.py -q
    Expected: PASS. A missing GPT or RunningHub variable must make readiness
    false and must not create a Provider task.

### Task 3: Make Compose self-contained and configuration-light

**Files:**

- Create: deployment/.env.example
- Create: deployment/.dockerignore
- Modify: deployment/Dockerfile
- Modify: deployment/docker-compose.yml
- Modify: deployment/README.md
- Create: tests/test_deployment_bundle_config.py
- Modify: tests/test_deployment_image_contract.py

**Interfaces:**

- Consumes: one operator-created deployment/.env file.
- Produces: default Compose topology with api, worker, sweeper, redis, minio,
  and minio-init services. USFR_PORT_FACTORY defaults to
  server.packaged_ports:build_ports.
- Used by: Task 4 ZIP builder and the final server operator.

- [ ] **Step 1: Write failing Compose/configuration tests**

    def test_compose_starts_minio_and_initializes_the_private_bucket_by_default():
        compose = load_yaml("deployment/docker-compose.yml")
        assert "minio" in compose["services"]
        assert "minio-init" in compose["services"]
        assert compose["services"]["api"]["environment"]["USFR_PORT_FACTORY"] == "${USFR_PORT_FACTORY:-server.packaged_ports:build_ports}"

    def test_env_example_has_no_secret_value_and_only_server_configuration():
        values = dotenv_values("deployment/.env.example")
        assert values["USFR_PORT_FACTORY"] == "server.packaged_ports:build_ports"
        assert values["RUNNINGHUB_API_KEY"] == ""
        assert values["OPENAI_API_KEY"] == ""

- [ ] **Step 2: Run configuration tests to verify failure**

    Run: python -B -m pytest tests/test_deployment_bundle_config.py tests/test_deployment_image_contract.py -q
    Expected: FAIL because MinIO is E2E-only and the default port factory is
    empty.

- [ ] **Step 3: Implement the single-file operator configuration**

    deployment/.env.example must contain blank secrets and documented defaults
    for USFR_CAPABILITY_SECRET, OPENAI variables, RUNNINGHUB variables, the
    Whisper workflow, TTS/lip-sync workflow IDs, MinIO credentials, bucket,
    API port, and retention. Do not include a host path, a local Python module
    path, a source media path, a generated artifact, or an actual secret.

    Make MinIO and bucket initialization part of normal Compose startup.
    API, Worker, and Sweeper must depend on healthy Redis and completed
    minio-init before readiness. The production Docker target must include only
    runtime package bytes, deployment configuration, and the immutable bundle;
    .dockerignore must exclude caches, Git files, tests, validation fixtures,
    media files, local environment files, and output directories.

- [ ] **Step 4: Run Docker-contract tests**

    Run: python -B -m pytest tests/test_deployment_bundle_config.py tests/test_deployment_image_contract.py tests/test_bundle_runtime_closure.py -q
    Expected: PASS.

### Task 4: Build a deterministic standalone ZIP

**Files:**

- Create: scripts/package_python_service.py
- Create: tests/test_package_python_service.py
- Modify: scripts/verify_bundle.py
- Modify: deployment/README.md

**Interfaces:**

- Consumes: the canonical bundle root and output ZIP path.
- Produces: package_python_service(bundle_root: Path, output_zip: Path) ->
  Mapping[str, Any] with package_sha256, file_count, and required-path list.
- Used by: the release command that writes
  exports/usfr-python-video-service.zip.

- [ ] **Step 1: Write failing ZIP-content tests**

    def test_release_zip_contains_runtime_and_excludes_local_state(tmp_path):
        result = package_python_service(ROOT, tmp_path / "usfr-python-video-service.zip")
        names = set(zipfile.ZipFile(result["path"]).namelist())
        assert "docker-compose.yml" in names
        assert ".env.example" in names
        assert "server/packaged_ports.py" in names
        assert not any(name.startswith((".git/", "__pycache__/", ".pytest_cache/", "final/", "runs/")) for name in names)

    def test_release_zip_manifest_matches_every_packaged_file(tmp_path):
        result = package_python_service(ROOT, tmp_path / "bundle.zip")
        assert result["package_sha256"] == sha256(Path(result["path"]).read_bytes()).hexdigest()

- [ ] **Step 2: Run ZIP tests to verify failure**

    Run: python -B -m pytest tests/test_package_python_service.py -q
    Expected: FAIL because package_python_service does not exist.

- [ ] **Step 3: Implement an allowlist ZIP builder**

    The builder must package deployment files at ZIP root, then server,
    scripts, bundled-skills, runtime-skills, references, schemas, and
    SKILL.md. It must call verify_bundle before writing, reject a source tree
    containing cache directories or local .env values, write a canonical
    package-manifest.json with every member SHA-256, and use fixed ZIP
    timestamps for reproducible bytes. It must never package a test directory,
    validation fixture, Git directory, source video, temporary artifact, or
    final MP4.

- [ ] **Step 4: Document the build and server commands**

    Add the exact commands:

    python -B scripts/package_python_service.py --output exports/usfr-python-video-service.zip
    unzip usfr-python-video-service.zip
    cp .env.example .env
    docker compose up -d --build

    State that unzip, image build, and readiness create no paid task.

- [ ] **Step 5: Run ZIP and bundle checks**

    Run: python -B scripts/verify_bundle.py .
    Expected: bundle is valid.

    Run: python -B -m pytest tests/test_package_python_service.py tests/test_skill_contract.py -q
    Expected: PASS.

### Task 5: Validate the deployment package and create the deliverable

**Files:**

- Create: deployment/verify-release.ps1
- Create: tests/test_release_verifier_contract.py
- Create: exports/usfr-python-video-service.zip

**Interfaces:**

- Consumes: the ZIP produced in Task 4 and a Docker-capable Linux host.
- Produces: a release verification report with bundle SHA, image build status,
  Compose health status, and no-provider E2E status.
- Used by: the server operator before inserting production credentials.

- [ ] **Step 1: Write failing release-verifier contract test**

    def test_release_verifier_requires_zip_hash_and_never_runs_provider_smoke_by_default():
        script = read_text("deployment/verify-release.ps1")
        assert "Get-FileHash" in script
        assert "RUN_PROVIDER_SMOKE" in script
        assert "if ($env:RUN_PROVIDER_SMOKE -ne 'true')" in script

- [ ] **Step 2: Run the verifier test to verify failure**

    Run: python -B -m pytest tests/test_release_verifier_contract.py -q
    Expected: FAIL because verify-release.ps1 does not exist.

- [ ] **Step 3: Implement no-provider release verification**

    The script must validate ZIP SHA-256, extract into a fresh directory,
    reject an extracted path containing .git, cache directories, .env, media,
    or a workstation-path reference, run Docker Compose build, wait for
    healthz and readyz, run the packaged no-provider E2E profile, and verify
    that MinIO contains only final/job-id/result.mp4 after cleanup. A paid
    RunningHub smoke is permitted only when RUN_PROVIDER_SMOKE equals true and
    the operator explicitly provides all provider credentials.

- [ ] **Step 4: Run the complete no-provider regression suite**

    Run: python -B -m pytest tests/test_gpt_evidence_gateway.py tests/test_packaged_ports.py tests/test_deployment_bundle_config.py tests/test_package_python_service.py tests/test_release_verifier_contract.py tests/test_packaged_factory.py tests/test_deployment_image_contract.py tests/test_no_workstation_dependency.py -q
    Expected: PASS.

- [ ] **Step 5: Create and inspect the final ZIP**

    Run: python -B scripts/package_python_service.py --output C:/Users/zhaocx04/Documents/New project/exports/usfr-python-video-service.zip
    Expected: package output prints a SHA-256 and contains no secret or media.

    Run: python -B deployment/verify-release.ps1 -Package C:/Users/zhaocx04/Documents/New project/exports/usfr-python-video-service.zip
    Expected: no-provider validation passes on a Docker-capable host; on this
    Windows host without Docker, report the exact environment blocker and do
    not claim Compose execution passed.
