from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

try:
    from scripts.verify_lightweight_bundle import verify_lightweight_bundle
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from verify_lightweight_bundle import verify_lightweight_bundle


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_SEEDANCE_RUNTIME_SKILLS = {
    "seedance-20",
    "seedance-prompt",
    "seedance-antislop",
    "seedance-camera",
    "seedance-motion",
    "seedance-lighting",
    "seedance-characters",
    "seedance-audio",
    "seedance-sequence",
    "seedance-style",
    "seedance-vfx",
    "seedance-vocab-en",
    "seedance-vocab-es",
    "seedance-vocab-ja",
    "seedance-vocab-ko",
    "seedance-vocab-zh",
}


REQUIRED_MODULE_FILES = {
    "parse-app-store-evidence": ["SKILL.md", "scripts/parse_app_store.py"],
    "analyze-reference-video-dynamics": [
        "SKILL.md",
        "scripts/probe_video.py",
        "scripts/validate_dynamics.py",
        "scripts/validate_dynamics_quality.py",
        "scripts/validate_high_fidelity_extension.py",
        "scripts/compare_analyzer_results.py",
        "scripts/adaptive_evidence_plan.py",
        "references/dynamics-contract.md",
        "references/analysis-quality-contract.md",
    ],
    "replicate-source-ui-overlays": [
        "SKILL.md",
        "scripts/overlay_frame_plan.py",
        "scripts/validate_overlay_contract.py",
    ],
    "seedance-storyboard-replication": [
        "SKILL.md",
        "scripts/config.py",
        "scripts/concat_videos.py",
        "scripts/media_quality.py",
        "scripts/segment_plan.py",
        "scripts/runninghub_image2.py",
        "scripts/seedance_submit.py",
        "scripts/timeline_splice.py",
    ],
}

REQUIRED_TOP_LEVEL_FILES = (
    "scripts/bind_input_slots.py",
    "scripts/high_fidelity_profile.py",
    "scripts/high_fidelity_analysis.py",
    "scripts/line_contract.py",
    "scripts/seedance_prescript.py",
    "scripts/seedance_prompt_compiler.py",
    "scripts/skill_router.py",
    "scripts/build_overlay_render_mapping.py",
    "scripts/hybrid_compositor.py",
    "scripts/high_fidelity_qc.py",
    "scripts/production_timing.py",
    "scripts/run_high_fidelity_shadow.py",
    "scripts/compare_high_fidelity_runs.py",
    "scripts/validation_catalog.py",
    "scripts/verify_lightweight_bundle.py",
)

REQUIRED_SERVER_FILES = (
    "server/__init__.py",
    "server/README.md",
    "server/errors.py",
    "server/job_models.py",
    "server/job_store.py",
    "server/redis_job_store.py",
    "server/redis_streams.py",
    "server/ephemeral_service.py",
    "server/intake.py",
    "server/artifacts.py",
    "server/fastapi_router.py",
    "server/orchestrator.py",
    "server/overlay_mapping.py",
    "server/overlay_renderer.py",
    "server/ephemeral_worker.py",
    "server/seedance_invocations.py",
    "server/high_fidelity_ports.py",
    "server/high_fidelity_envelope.py",
    "server/high_fidelity_projection.py",
    "server/provider_ports.py",
    "server/production_ports.py",
    "server/media_materializer.py",
    "server/telemetry.py",
    "server/media_probe.py",
    "server/digests.py",
    "server/ephemeral_driver.py",
    "server/capabilities.py",
    "server/capability_ports.py",
    "server/audio_backends.py",
    "server/audio_mixer.py",
    "server/performance_audio_contracts.py",
    "server/vision_backends.py",
    "server/object_store.py",
    "server/cleanup.py",
    "server/capability_tokens.py",
    "server/result_handles.py",
    "server/review_models.py",
    "server/review_workflow.py",
    "server/recovery_models.py",
    "server/recovery_workflow.py",
    "server/recovery_executor.py",
    "server/recovery_bridge.py",
    "server/real_capabilities.py",
    "server/timeline_renderer.py",
    "server/deployment_bootstrap.py",
    "server/packaged_factory.py",
    "server/worker_entrypoint.py",
    "references/server-api-contract.md",
    "references/run-state-machine.md",
    "references/idempotency-and-provider-reconciliation.md",
    "references/error-code-contract.md",
    "references/ephemeral-job-lifecycle.md",
    "references/adaptive-fidelity-recovery-loop.md",
    "references/quality-activation-contract.md",
    "schemas/input_slots.schema.json",
    "schemas/upload_completion.schema.json",
    "schemas/job.schema.json",
    "schemas/artifact.schema.json",
    "schemas/queue_message.schema.json",
    "schemas/provider_attempt.schema.json",
    "schemas/result_handle.schema.json",
    "schemas/script_revision.schema.json",
    "schemas/storyboard_revision.schema.json",
    "schemas/recovery_checkpoint.schema.json",
    "schemas/error.schema.json",
)

REQUIRED_RUNTIME_CONTRACTS = (
    "references/runtime_skill_manifest.json",
    "references/universal-source-fidelity-contract.md",
    "references/fixed-input-slot-contract.md",
    "references/high-fidelity-hybrid-v1.md",
    "references/high-fidelity-evidence-matrix.md",
    "references/seedance-20-prescript-contract.md",
    "references/skill-routing-contract.md",
    "references/deployment-runtime-contract.md",
    "schemas/high_fidelity_profile.schema.json",
    "schemas/high_fidelity_analysis.schema.json",
    "schemas/exact_line_contract.schema.json",
    "schemas/high_fidelity_qc.schema.json",
    "schemas/stage_capabilities.schema.json",
    "bundled-skills/seedance-storyboard-replication/references/seedance-20-prescript-contract.md",
    "bundled-skills/seedance-storyboard-replication/references/hybrid-compositor-contract.md",
    "validation/high_fidelity/golden_cases.json",
    "validation/case_catalog.json",
    "validation/high_fidelity/backend_policy.json",
    "references/production-readiness-status.md",
    "bundled-skills/seedance-storyboard-replication/references/seedance-20-integrity-gate.md",
)

REQUIRED_DEPLOYMENT_FILES = (
    "deployment/Dockerfile",
    "deployment/requirements.lock",
    "deployment/requirements-control-plane.lock",
    "deployment/README.md",
    "deployment/docker-compose.yml",
)


def verify_bundle(root: Path) -> list[str]:
    failures: list[str] = list(verify_lightweight_bundle(root))
    manifest_path = root / "references" / "bundle_manifest.json"
    if not manifest_path.is_file():
        return [f"missing manifest: {manifest_path}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = {item["name"] for item in manifest.get("modules", [])}
    declared_runtime = {
        item.get("path")
        for item in manifest.get("runtime_files", [])
        if isinstance(item, dict)
    }
    for relative in REQUIRED_TOP_LEVEL_FILES + (
        "references/fixed-input-slot-contract.md",
    ):
        if relative not in declared_runtime:
            failures.append(f"runtime file not declared: {relative}")
    for relative in REQUIRED_SERVER_FILES:
        if relative not in declared_runtime:
            failures.append(f"runtime file not declared: {relative}")
    for relative in REQUIRED_DEPLOYMENT_FILES:
        if relative not in declared_runtime:
            failures.append(f"deployment file not declared: {relative}")
    for name, required_files in REQUIRED_MODULE_FILES.items():
        if name not in declared:
            failures.append(f"module not declared: {name}")
        module_root = root / "bundled-skills" / name
        for relative in required_files:
            if not (module_root / relative).is_file():
                failures.append(f"missing {name}/{relative}")
    for relative in REQUIRED_RUNTIME_CONTRACTS:
        if not (root / relative).is_file():
            failures.append(f"missing runtime contract: {root / relative}")
    for relative in REQUIRED_TOP_LEVEL_FILES:
        if not (root / relative).is_file():
            failures.append(f"missing top-level runtime file: {root / relative}")
    for relative in REQUIRED_SERVER_FILES:
        if not (root / relative).is_file():
            failures.append(f"missing server runtime file: {root / relative}")
    for relative in REQUIRED_DEPLOYMENT_FILES:
        if not (root / relative).is_file():
            failures.append(f"missing deployment file: {root / relative}")
    runtime_manifest_path = root / "references" / "runtime_skill_manifest.json"
    if runtime_manifest_path.is_file():
        try:
            runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            failures.append(f"invalid runtime Skill manifest: {exc}")
        else:
            records = runtime_manifest.get("dependencies") if isinstance(runtime_manifest, dict) else None
            if runtime_manifest.get("schema_version") != 1 or not isinstance(records, list):
                failures.append("runtime Skill manifest schema is invalid")
            else:
                names = [record.get("name") for record in records if isinstance(record, dict)]
                if set(names) != REQUIRED_SEEDANCE_RUNTIME_SKILLS or len(names) != len(set(names)):
                    failures.append("runtime Skill manifest dependency set is incomplete or duplicated")
                for record in records:
                    if not isinstance(record, dict):
                        failures.append("runtime Skill manifest dependency must be an object")
                        continue
                    name = record.get("name")
                    relative = record.get("package_path")
                    expected_sha = record.get("sha256")
                    if (
                        not isinstance(relative, str)
                        or not relative.startswith("runtime-skills/seedance-20/")
                        or ".." in relative.split("/")
                    ):
                        failures.append(f"runtime Skill package path is invalid: {name}")
                        continue
                    path = root / relative
                    if not path.is_file():
                        failures.append(f"missing runtime Skill dependency: {relative}")
                        continue
                    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                    if not isinstance(expected_sha, str) or _SHA256.fullmatch(expected_sha) is None or expected_sha != actual_sha:
                        failures.append(f"runtime Skill dependency SHA mismatch: {name}")
                    if record.get("version") != "6.6.0":
                        failures.append(f"runtime Skill dependency version mismatch: {name}")
        if not (root / "runtime-skills" / "seedance-20" / "LICENSE").is_file():
            failures.append("missing runtime Seedance-20 license")
    forbidden = list(root.rglob("__pycache__"))
    forbidden.extend(root.rglob(".pytest_cache"))
    failures.extend(f"forbidden cache directory: {path}" for path in forbidden)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify bundled factory skill modules.")
    parser.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    failures = verify_bundle(args.root)
    if failures:
        raise SystemExit("\n".join(failures))
    print("bundle is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
