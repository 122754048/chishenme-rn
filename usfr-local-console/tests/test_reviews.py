from pathlib import Path

from app.jobs import FileJobStore
from app.reviews import (
    approve_script_revision,
    approve_storyboard_revision,
    create_script_revision,
    create_storyboard_revision,
)
from app.slots import build_intake, validate_intake


def create_job(store: FileJobStore, temp_dir: Path):
    temp_dir.mkdir(parents=True, exist_ok=True)
    source = temp_dir / "source.mp4"
    source.write_bytes(b"source")
    return store.create(
        validate_intake(build_intake(source_video=source, output_language="fr"), probe_duration=lambda _: 5)
    )


def test_editing_an_approved_script_requires_a_new_revision(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)
    revision = create_script_revision(store, job.job_id, job.version, "draft")
    approve_script_revision(
        store,
        job.job_id,
        revision.number,
        revision.sha256,
        expected_version=revision.job_version,
    )

    edited = create_script_revision(store, job.job_id, revision.job_version + 1, "changed")

    assert edited.number == revision.number + 1


def test_storyboard_approval_binds_the_exact_artifact_digest(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)
    revision = create_storyboard_revision(store, job.job_id, job.version, {"frames": ["board.png"]})

    approved = approve_storyboard_revision(
        store,
        job.job_id,
        revision.number,
        revision.sha256,
        expected_version=revision.job_version,
    )

    assert approved.stage == "CODEX_REQUIRED"
    assert approved.reviews["storyboard"][0]["approved"] is True
