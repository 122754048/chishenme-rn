from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from server.errors import ReplicationError
from server.media_probe import probe_source


class ServerMediaProbeTest(unittest.TestCase):
    def test_probe_returns_hash_and_media_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.mp4"
            path.write_bytes(b"source")
            completed = type("Result", (), {"returncode": 0, "stdout": '{"format":{"duration":"1.5","format_name":"mov,mp4"},"streams":[{"codec_type":"video","width":720,"height":1280,"r_frame_rate":"30/1"},{"codec_type":"audio"}]}' , "stderr": ""})()
            with patch("server.media_probe.subprocess.run", return_value=completed):
                result = probe_source(path)
        self.assertEqual(result["duration_seconds"], 1.5)
        self.assertTrue(result["has_audio"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_probe_blocks_duration_over_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.mp4"
            path.write_bytes(b"source")
            completed = type("Result", (), {"returncode": 0, "stdout": '{"format":{"duration":"31"},"streams":[{"codec_type":"video"}]}', "stderr": ""})()
            with patch("server.media_probe.subprocess.run", return_value=completed):
                with self.assertRaises(ReplicationError) as ctx:
                    probe_source(path)
        self.assertEqual(ctx.exception.code, "INPUT_SOURCE_TOO_LONG")


if __name__ == "__main__":
    unittest.main()
