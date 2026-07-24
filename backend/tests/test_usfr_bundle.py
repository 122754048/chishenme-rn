import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.usfr_bundle import UsfrBundleError, build_usfr_bundle, verify_usfr_bundle
from app.usfr_commercial_deployment import (
    CommercialDeploymentError,
    verify_deployment_usfr_bundle,
    verify_deployment_usfr_bundle_path,
)


def _source_bundle(root: Path) -> Path:
    files = {
        "SKILL.md": b"canonical usfr skill\n",
        "server/__init__.py": b"\n",
        "server/packaged_factory.py": b"PACKAGE = 'canonical'\n",
        "references/runtime_skill_manifest.json": b'{"schema_version":1}\n',
        "runtime-skills/seedance-20/SKILL.md": b"seedance\n",
        "bundled-skills/analysis/SKILL.md": b"analysis\n",
        "scripts/compile_prompt.py": b"print('compile')\n",
        "server/__pycache__/ignored.pyc": b"compiled",
    }
    for relative_path, payload in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return root


def test_builds_a_complete_immutable_usfr_bundle_and_detects_tampering(tmp_path):
    source = _source_bundle(tmp_path / "source")
    output = tmp_path / "deployment-bundle"
    skill_sha256 = hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest()

    receipt = build_usfr_bundle(
        source_root=source,
        output_root=output,
        expected_skill_sha256=skill_sha256,
    )

    assert (output / "server" / "packaged_factory.py").read_text(encoding="utf-8") == "PACKAGE = 'canonical'\n"
    assert (output / "runtime-skills" / "seedance-20" / "SKILL.md").is_file()
    assert not (output / "server" / "__pycache__").exists()
    assert receipt == verify_usfr_bundle(
        output,
        expected_skill_sha256=skill_sha256,
        expected_tree_sha256=receipt["source_tree_sha256"],
    )

    (output / "server" / "packaged_factory.py").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(UsfrBundleError, match="USFR_BUNDLE_FILE_DIGEST_MISMATCH"):
        verify_usfr_bundle(
            output,
            expected_skill_sha256=skill_sha256,
            expected_tree_sha256=receipt["source_tree_sha256"],
        )


def test_rejects_a_mismatched_skill_digest_before_writing_a_bundle(tmp_path):
    source = _source_bundle(tmp_path / "source")
    output = tmp_path / "deployment-bundle"

    with pytest.raises(UsfrBundleError, match="USFR_BUNDLE_SKILL_DIGEST_MISMATCH"):
        build_usfr_bundle(source_root=source, output_root=output, expected_skill_sha256="0" * 64)

    assert not output.exists()


def test_rejects_a_self_consistent_forged_manifest_without_the_pinned_tree_digest(tmp_path):
    source = _source_bundle(tmp_path / "source")
    output = tmp_path / "deployment-bundle"
    skill_sha256 = hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest()
    receipt = build_usfr_bundle(
        source_root=source,
        output_root=output,
        expected_skill_sha256=skill_sha256,
    )

    (source / "server" / "packaged_factory.py").write_text("forged\n", encoding="utf-8")
    forged = build_usfr_bundle(
        source_root=source,
        output_root=tmp_path / "forged-bundle",
        expected_skill_sha256=skill_sha256,
    )
    (output / "server" / "packaged_factory.py").write_text("forged\n", encoding="utf-8")
    (output / "usfr_bundle_manifest.json").write_text(json.dumps(forged), encoding="utf-8")

    with pytest.raises(UsfrBundleError, match="USFR_BUNDLE_TREE_DIGEST_MISMATCH"):
        verify_usfr_bundle(
            output,
            expected_skill_sha256=skill_sha256,
            expected_tree_sha256=receipt["source_tree_sha256"],
        )


def test_deployment_verifies_the_packaged_server_bundle_before_runtime_bootstrap(tmp_path):
    source = _source_bundle(tmp_path / "source")
    output = tmp_path / "deployment-bundle"
    skill_sha256 = hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest()
    receipt = build_usfr_bundle(
        source_root=source,
        output_root=output,
        expected_skill_sha256=skill_sha256,
    )
    server_module = SimpleNamespace(__file__=str(output / "server" / "__init__.py"))

    assert verify_deployment_usfr_bundle(
        server_module=server_module,
        environment={
            "USFR_DEPLOYMENT_BUNDLE_SKILL_SHA256": skill_sha256,
            "USFR_DEPLOYMENT_BUNDLE_TREE_SHA256": receipt["source_tree_sha256"],
        },
    ) == output

    with pytest.raises(CommercialDeploymentError, match="COMMERCIAL_DEPLOYMENT_BUNDLE_DIGEST_REQUIRED"):
        verify_deployment_usfr_bundle(server_module=server_module, environment={})


def test_deployment_verifies_an_unimported_server_package_file(tmp_path):
    source = _source_bundle(tmp_path / "source")
    output = tmp_path / "deployment-bundle"
    skill_sha256 = hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest()
    receipt = build_usfr_bundle(
        source_root=source,
        output_root=output,
        expected_skill_sha256=skill_sha256,
    )

    assert verify_deployment_usfr_bundle_path(
        server_package_file=output / "server" / "__init__.py",
        environment={
            "USFR_DEPLOYMENT_BUNDLE_SKILL_SHA256": skill_sha256,
            "USFR_DEPLOYMENT_BUNDLE_TREE_SHA256": receipt["source_tree_sha256"],
        },
    ) == output


def test_bundle_builder_module_emits_the_pinned_deployment_receipt(tmp_path):
    source = _source_bundle(tmp_path / "source")
    output = tmp_path / "deployment-bundle"
    skill_sha256 = hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.usfr_bundle",
            "--source-root",
            str(source),
            "--output-root",
            str(output),
            "--expected-skill-sha256",
            skill_sha256,
        ],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[1],
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["source_tree_sha256"] == verify_usfr_bundle(
        output,
        expected_skill_sha256=skill_sha256,
        expected_tree_sha256=json.loads(completed.stdout)["source_tree_sha256"],
    )["source_tree_sha256"]
