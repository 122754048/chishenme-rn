from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compose_starts_minio_and_initializes_the_private_bucket_by_default() -> None:
    compose = (ROOT / "deployment" / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  minio:\n" in compose
    assert "  minio-init:\n" in compose
    assert "USFR_PORT_FACTORY: ${USFR_PORT_FACTORY:-server.packaged_ports:build_ports}" in compose
    minio_start = compose.index("  minio:\n")
    minio_end = compose.index("\n  minio-init:\n", minio_start)
    assert "profiles:" not in compose[minio_start:minio_end]
    assert "minio-init:\n      condition: service_completed_successfully" in compose


def test_distribution_has_one_safe_root_environment_template() -> None:
    template = ROOT / ".env.example"

    assert template.is_file()
    content = template.read_text(encoding="utf-8")
    assert "USFR_CAPABILITY_SECRET=" in content
    assert "OPENAI_API_KEY=" in content
    assert "RUNNINGHUB_SEEDANCE_API_KEY=" in content
    assert "RUNNINGHUB_WHISPER_WORKFLOW_ID=" in content
    assert "RUNNINGHUB_WHISPER_INPUT_NODE_ID=12" in content
    assert "your-" not in content.casefold()


def test_compose_forwards_every_required_runninghub_standard_media_setting() -> None:
    compose = (ROOT / "deployment" / "docker-compose.yml").read_text(encoding="utf-8")

    for name in (
        "RUNNINGHUB_SEEDANCE_CREATE_URL",
        "RUNNINGHUB_SEEDANCE_QUERY_URL",
        "RUNNINGHUB_SEEDANCE_UPLOAD_URL",
    ):
        assert f"{name}: ${{{name}:-}}" in compose
