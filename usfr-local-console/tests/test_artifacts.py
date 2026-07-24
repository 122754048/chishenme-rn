from pathlib import Path

import pytest

from app.artifacts import ArtifactError, ArtifactRegistry, open_registered_artifact
from app.jobs import FileJobStore
from app.slots import build_intake, validate_intake


def create_job(store: FileJobStore, temp_dir: Path):
    temp_dir.mkdir(parents=True, exist_ok=True)
    source = temp_dir / "source.mp4"
    source.write_bytes(b"source")
    return store.create(
        validate_intake(build_intake(source_video=source, output_language="fr"), probe_duration=lambda _: 5)
    )


def test_artifact_download_rejects_paths_outside_the_registered_job_root(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)

    with pytest.raises(ArtifactError, match="ARTIFACT_NOT_REGISTERED"):
        open_registered_artifact(store, job.job_id, "../../.env")


def test_registered_artifact_can_only_be_resolved_by_its_artifact_id(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)
    registry = ArtifactRegistry(store)
    receipt = registry.register_bytes(
        job.job_id,
        job.version,
        role="final_video",
        filename="result.mp4",
        mime_type="video/mp4",
        payload=b"final",
    )

    assert open_registered_artifact(store, job.job_id, receipt.artifact_id).read_bytes() == b"final"
