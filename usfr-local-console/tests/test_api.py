import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.artifacts import ArtifactRegistry
from app.jobs import FileJobStore
from app.settings import Settings
from app.slots import build_intake, validate_intake


def make_settings(tmp_path: Path) -> Settings:
    skill = tmp_path / "SKILL.md"
    skill.write_text("skill", encoding="utf-8")
    return Settings(
        host="127.0.0.1",
        port=8765,
        data_root=tmp_path / "data",
        skill_path=skill,
        skill_sha256=hashlib.sha256(b"skill").hexdigest(),
        runninghub_api_key="secret-key",
    )


def make_app(tmp_path: Path):
    settings = make_settings(tmp_path)
    store = FileJobStore(settings.data_root)
    return create_app(settings=settings, store=store, probe_duration=lambda _: 5), store


def test_create_job_requires_source_and_a_change(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        files={"source_video": ("source.mp4", b"source", "video/mp4")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "MIN_ONE_OPTIONAL_INPUT_REQUIRED"


def test_create_job_accepts_background_music_upload_extension(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        files={
            "source_video": ("source.mp4", b"source", "video/mp4"),
            "background_music": ("song.mp3", b"music", "audio/mpeg"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["admission"]["background_music"] is True
    assert payload["routes"]["background_music"] == "seedance_audio_reference"
    assert payload["inputs"]["background_music"]["mime_type"] == "audio/mpeg"


def test_create_job_returns_route_preview_without_browser_inference(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        data={"output_language": "de"},
        files={
            "source_video": ("source.mp4", b"source", "video/mp4"),
            "new_model_image": ("model.png", b"model", "image/png"),
            "ui_operation_video": ("ui.mp4", b"ui", "video/mp4"),
        },
    )

    assert response.status_code == 201
    preview = response.json()["route_preview"]
    assert preview["run_mode"] == "composite_replication"
    assert preview["deep_analysis"] == "once"
    assert "ui_ocr_renderer" in preview["skip_modules"]


def test_composite_localization_records_selected_opaque_audio_policy(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        data={
            "output_language": "ja",
            "opaque_audio_policy": "opaque_audio_target_verified",
        },
        files={
            "source_video": ("source.mp4", b"source", "video/mp4"),
            "ui_operation_video": ("ui.mp4", b"ui", "video/mp4"),
        },
    )

    assert response.status_code == 201
    assert response.json()["execution_map"]["audio_policy"]["ui"] == "opaque_audio_target_verified"


def test_api_serves_registered_artifact_but_not_env_file(tmp_path):
    app, store = make_app(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    job = store.create(
        validate_intake(build_intake(source_video=source, output_language="fr"), probe_duration=lambda _: 5)
    )
    artifact = ArtifactRegistry(store).register_bytes(
        job.job_id,
        job.version,
        role="final_video",
        filename="result.mp4",
        mime_type="video/mp4",
        payload=b"video",
    )
    client = TestClient(app)

    ok = client.get(f"/api/jobs/{job.job_id}/artifacts/{artifact.artifact_id}")
    missing = client.get(f"/api/jobs/{job.job_id}/artifacts/.env")

    assert ok.status_code == 200
    assert missing.status_code == 404


def test_response_never_contains_runninghub_key(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)

    assert "secret-key" not in client.get("/api/health").text


def test_api_serves_only_registered_immutable_job_inputs(tmp_path):
    app, store = make_app(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    job = store.create(
        validate_intake(build_intake(source_video=source, output_language="fr"), probe_duration=lambda _: 5)
    )
    client = TestClient(app)

    ok = client.get(f"/api/jobs/{job.job_id}/inputs/source_video")
    missing = client.get(f"/api/jobs/{job.job_id}/inputs/.env")

    assert ok.status_code == 200
    assert missing.status_code == 404
