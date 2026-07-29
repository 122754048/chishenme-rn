from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_docker_build_context_contains_the_packaged_runtime_bundle() -> None:
    dockerfile = (ROOT / "deployment" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY deployment /opt/usfr/deployment" in dockerfile
    assert "RUN python -B scripts/verify_bundle.py /opt/usfr" in dockerfile
    assert "COPY server /opt/usfr/server" in dockerfile
    assert "COPY bundled-skills /opt/usfr/bundled-skills" in dockerfile
    assert "COPY runtime-skills /opt/usfr/runtime-skills" in dockerfile
    assert "COPY validation /opt/usfr/validation" not in dockerfile
    assert "COPY validation/case_catalog.json /opt/usfr/validation/case_catalog.json" in dockerfile
    assert "COPY validation/high_fidelity/golden_cases.json /opt/usfr/validation/high_fidelity/golden_cases.json" in dockerfile
    assert "COPY validation/high_fidelity/backend_policy.json /opt/usfr/validation/high_fidelity/backend_policy.json" in dockerfile
    assert "COPY SKILL.md /opt/usfr/SKILL.md" in dockerfile
    assert "USFR_INSTALL_MODE=full" in dockerfile
    assert "requirements-control-plane.lock" in dockerfile


def test_image_declares_worker_and_sweeper_bootstrap_targets() -> None:
    dockerfile = (ROOT / "deployment" / "Dockerfile").read_text(encoding="utf-8")
    assert "USFR_PROCESS_ROLE=worker" in dockerfile
    assert "USFR_WORKER_BOOTSTRAP=server.deployment_bootstrap:run_worker" in dockerfile
    assert "USFR_SWEEPER_BOOTSTRAP=server.deployment_bootstrap:run_sweeper" in dockerfile
    assert 'CMD ["python", "-B", "-m", "server.worker_entrypoint"]' in dockerfile
    assert 'ENTRYPOINT ["python", "-B", "-m", "server.worker_entrypoint"]' not in dockerfile


def test_compose_defines_stateless_redis_api_worker_and_sweeper_topology() -> None:
    compose_path = ROOT / "deployment" / "docker-compose.yml"
    assert compose_path.is_file()
    compose = compose_path.read_text(encoding="utf-8")
    for service in ("redis", "api", "worker", "sweeper"):
        assert re.search(rf"(?m)^  {service}:\s*$", compose)
    assert "server.deployment_bootstrap:build_http_app" in compose
    assert "USFR_PROCESS_ROLE: worker" in compose
    assert "USFR_PROCESS_ROLE: sweeper" in compose
    assert "USFR_S3_ENDPOINT" in compose
    assert "server.packaged_factory:build_runtime" in compose
    assert "USFR_READINESS_ONLY" in compose
    assert re.search(r"(?m)^  minio-init:\s*$", compose)
    assert re.search(r"(?m)^\s+profiles:\s*\n\s+- e2e\s*$", compose)


def test_compose_uses_redis_standalone_and_has_no_relational_database() -> None:
    compose = (ROOT / "deployment" / "docker-compose.yml").read_text(encoding="utf-8").lower()
    assert "redis:" in compose
    assert "redis-server" in compose
    assert "cluster-enabled" not in compose
    assert "postgres" not in compose
    assert "mysql" not in compose
    assert "sqlite" not in compose


def test_dockerignore_excludes_generated_caches_and_tests_but_keeps_runtime_contracts() -> None:
    content = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\*\*/__pycache__/?$", content)
    assert re.search(r"(?m)^\*\*/\.pytest_cache/?$", content)
    assert re.search(r"(?m)^tests/?$", content)
    assert "deployment/" not in content
    assert "server/" not in content
