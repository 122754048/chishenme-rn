import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"),
)

from seedance_submit import (  # noqa: E402
    DEFAULT_SEEDANCE20_SKILL_FILE,
    PayloadError,
    _validate_audited_factory_parameters,
    resolve_seedance20_skill_file,
)
from config import DEFAULT_ENV_FILE, load_settings, resolve_env_file  # noqa: E402


class SeedanceDependencyResolutionTest(unittest.TestCase):
    def test_no_home_directory_fallback(self):
        self.assertIsNone(DEFAULT_SEEDANCE20_SKILL_FILE)
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_seedance20_skill_file())

    def test_worker_environment_is_resolved_and_cli_wins(self):
        with patch.dict(os.environ, {"SEEDANCE20_SKILL_FILE": "/worker/pinned/SKILL.md"}, clear=True):
            self.assertEqual(
                resolve_seedance20_skill_file(),
                Path("/worker/pinned/SKILL.md"),
            )
            self.assertEqual(
                resolve_seedance20_skill_file("/explicit/SKILL.md"),
                Path("/explicit/SKILL.md"),
            )

    def test_audited_path_fails_closed_without_pinned_snapshot(self):
        with self.assertRaisesRegex(PayloadError, "packaged Seedance-20 snapshot"):
            _validate_audited_factory_parameters(
                prompt="short prompt",
                provider="youdao",
                model="seedance-2.0",
                resolution="720p",
                ratio="9:16",
                duration=4,
                input_contract_path=Path("missing-contract.json"),
                approved_script_sha256="a" * 64,
                skill_file=None,
            )

    def test_environment_configuration_has_no_home_directory_fallback(self):
        self.assertIsNone(DEFAULT_ENV_FILE)
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_env_file())
            settings = load_settings(None, environ={})
        with self.assertRaisesRegex(Exception, "YOUDAO_API_KEY"):
            settings.require_seedance()

    def test_worker_environment_file_is_resolved(self):
        with patch.dict(os.environ, {"SEEDANCE_ENV_FILE": "/worker/config/seedance.env"}, clear=True):
            self.assertEqual(resolve_env_file(), Path("/worker/config/seedance.env"))
        self.assertEqual(
            resolve_env_file(environ={"SEEDANCE_ENV_FILE": "/injected/config.env"}),
            Path("/injected/config.env"),
        )


if __name__ == "__main__":
    unittest.main()
