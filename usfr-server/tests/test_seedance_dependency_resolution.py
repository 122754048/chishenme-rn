import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from config import DEFAULT_ENV_FILE, load_settings, resolve_env_file  # noqa: E402
from runninghub_seedance_submit import (  # noqa: E402
    PayloadError,
    build_runninghub_standard_payload,
)


class SeedanceDependencyResolutionTest(unittest.TestCase):
    def test_no_home_directory_fallback(self):
        self.assertIsNone(DEFAULT_ENV_FILE)
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_env_file())

    def test_worker_environment_file_is_resolved(self):
        with patch.dict(os.environ, {"SEEDANCE_ENV_FILE": "/worker/config/seedance.env"}, clear=True):
            self.assertEqual(resolve_env_file(), Path("/worker/config/seedance.env"))
        self.assertEqual(
            resolve_env_file(environ={"SEEDANCE_ENV_FILE": "/injected/config.env"}),
            Path("/injected/config.env"),
        )

    def test_environment_requires_the_dedicated_runninghub_standard_key(self):
        settings = load_settings(None, environ={})
        with self.assertRaisesRegex(Exception, "RUNNINGHUB_SEEDANCE_API_KEY"):
            settings.require_seedance()

    def test_standard_payload_accepts_documented_video_reference_without_loading_a_legacy_submitter(self):
        payload = build_runninghub_standard_payload(
            "Keep the approved action.",
            5,
            "9:16",
            ["https://media.example/board.png"],
            [],
            video_urls=["https://media.example/source-s01.mp4"],
            real_person_mode=True,
        )
        self.assertEqual(payload["videoUrls"], ["https://media.example/source-s01.mp4"])
        self.assertFalse((SCRIPTS / "seedance_submit.py").exists())
        with self.assertRaises(PayloadError):
            build_runninghub_standard_payload(
                "Use @Audio1.",
                5,
                "9:16",
                [],
                ["https://media.example/song.mp3"],
                real_person_mode=False,
            )


if __name__ == "__main__":
    unittest.main()
