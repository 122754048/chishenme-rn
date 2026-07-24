from io import BytesIO
import hashlib
from pathlib import Path
import tempfile
import unittest

from server.artifacts import LocalArtifactStore
from server.errors import ReplicationError
from server.intake import bind_uploaded_slots


class ServerIntakeArtifactsTest(unittest.TestCase):
    def test_unknown_slot_and_source_only_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            with self.assertRaises(ReplicationError) as unknown:
                bind_uploaded_slots({"source_video": source, "unexpected": source})
            self.assertEqual(unknown.exception.code, "INPUT_SLOT_INVALID")
            with self.assertRaises(ReplicationError) as only_source:
                bind_uploaded_slots({"source_video": source})
            self.assertEqual(only_source.exception.code, "MIN_ONE_OPTIONAL_INPUT_REQUIRED")

    def test_artifact_store_is_run_scoped_and_hash_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LocalArtifactStore(Path(temp))
            artifact = store.put_stream(
                run_id="run-1",
                artifact_id="product-1",
                stream=BytesIO(b"product"),
                content_type="image/png",
            )
            self.assertTrue(Path(artifact["path"]).is_file())
            self.assertIn(str(Path(temp) / "run-1"), artifact["path"])
            self.assertEqual(artifact["sha256"], hashlib.sha256(b"product").hexdigest())
            with self.assertRaises(ReplicationError) as mismatch:
                store.put_stream(
                    run_id="run-1",
                    artifact_id="bad",
                    stream=BytesIO(b"product"),
                    content_type="image/png",
                    expected_sha256="0" * 64,
                )
            self.assertEqual(mismatch.exception.code, "ARTIFACT_HASH_MISMATCH")

    def test_artifact_id_cannot_escape_run_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            store = LocalArtifactStore(Path(temp))
            with self.assertRaises(ReplicationError) as ctx:
                store.put_stream(run_id="run-1", artifact_id="../escape", stream=BytesIO(b"x"), content_type="video/mp4")
            self.assertEqual(ctx.exception.code, "INPUT_SLOT_INVALID")


if __name__ == "__main__":
    unittest.main()
