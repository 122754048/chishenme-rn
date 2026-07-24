from pathlib import Path

import pytest

from app.settings import DEFAULT_SKILL_PATH, Settings, SkillChangedError


def test_settings_uses_localhost_and_creates_only_console_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("USFR_CONSOLE_DATA_ROOT", str(tmp_path / "data"))
    settings = Settings.load()

    assert settings.host == "127.0.0.1"
    assert settings.data_root == tmp_path / "data"
    assert settings.data_root.is_dir()


def test_settings_detects_a_changed_skill_file(tmp_path, monkeypatch):
    skill = tmp_path / "SKILL.md"
    skill.write_text("before", encoding="utf-8")
    monkeypatch.setenv("USFR_SKILL_PATH", str(skill))
    settings = Settings.load()

    skill.write_text("after", encoding="utf-8")

    with pytest.raises(SkillChangedError):
        settings.assert_skill_unchanged()


def test_settings_reads_an_optional_commercial_batch_api_url(tmp_path, monkeypatch):
    monkeypatch.setenv("USFR_CONSOLE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("USFR_COMMERCIAL_BATCH_API_URL", "http://127.0.0.1:8000/api/v1/commercial-batches")

    settings = Settings.load()

    assert settings.commercial_batch_api_url == "http://127.0.0.1:8000/api/v1/commercial-batches"


def test_settings_reads_the_temporary_job_retention_window(tmp_path, monkeypatch):
    monkeypatch.setenv("USFR_CONSOLE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("USFR_CONSOLE_TEMP_TTL_SECONDS", "86400")

    settings = Settings.load()

    assert settings.temporary_job_ttl_seconds == 86400


def test_default_skill_path_is_the_repository_owned_usfr_server():
    assert DEFAULT_SKILL_PATH == Path(__file__).resolve().parents[2] / "usfr-server" / "SKILL.md"
