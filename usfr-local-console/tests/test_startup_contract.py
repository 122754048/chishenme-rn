from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_start_script_binds_loopback_only():
    script = (ROOT / "start.ps1").read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in script
    assert "0.0.0.0" not in script


def test_readme_declares_skill_is_read_only_and_no_openai_api_is_needed():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "does not modify the Skill" in readme
    assert "OpenAI API" in readme
