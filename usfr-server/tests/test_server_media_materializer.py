from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import tempfile

import pytest

from server.errors import ReplicationError
from server.media_materializer import MediaMaterializer


class _Store:
    def __init__(self, payload: bytes, *, content_type: str = "video/mp4") -> None:
        self.payload = payload
        self.content_type = content_type
        self.head_calls: list[str] = []
        self.stream_calls: list[str] = []

    def head(self, object_key: str):
        self.head_calls.append(object_key)
        return {
            "object_key": object_key,
            "sha256": sha256(self.payload).hexdigest(),
            "size_bytes": len(self.payload),
            "content_type": self.content_type,
            "status": "completed",
        }

    def open_stream(self, object_key: str):
        self.stream_calls.append(object_key)
        return BytesIO(self.payload)


def test_materializes_job_scoped_object_and_cleans_context_path():
    payload = b"media-bytes"
    digest = sha256(payload).hexdigest()
    store = _Store(payload)
    with tempfile.TemporaryDirectory() as work:
        with MediaMaterializer(store).materialize(
            job_id="job-1",
            object_key="temporary/job-1/source.mp4",
            expected_sha256=digest,
            expected_size_bytes=len(payload),
            work_dir=Path(work),
        ) as media:
            assert media.path.is_file()
            assert media.path.read_bytes() == payload
            assert media.job_id == "job-1"
        assert not media.path.exists()
    assert store.head_calls == ["temporary/job-1/source.mp4"]
    assert store.stream_calls == ["temporary/job-1/source.mp4"]


def test_materializes_final_result_and_rejects_cross_job_or_legacy_prefix_keys():
    payload = b"media"
    digest = sha256(payload).hexdigest()
    materializer = MediaMaterializer(_Store(payload))
    with materializer.materialize(job_id="job-1", object_key="final/job-1/result.mp4", expected_sha256=digest):
        pass
    with pytest.raises(ReplicationError):
        with materializer.materialize(job_id="job-1", object_key="temporary/job-2/x.mp4", expected_sha256=digest):
            pass
    with pytest.raises(ReplicationError):
        with materializer.materialize(job_id="job-1", object_key="legacy-a/source.mp4", expected_sha256=digest):
            pass


def test_materializer_verifies_head_and_stream_hash_size_and_chunks():
    class BadHead(_Store):
        def head(self, object_key: str):
            value = super().head(object_key)
            value["sha256"] = "a" * 64
            return value

    with pytest.raises(ReplicationError):
        with MediaMaterializer(BadHead(b"media")).materialize(job_id="job-1", object_key="temporary/job-1/x", expected_sha256=sha256(b"media").hexdigest()):
            pass

    class BadStream(_Store):
        def open_stream(self, object_key: str):
            return _NonByteStream()

    class _NonByteStream:
        def read(self, _size):
            return "not bytes"

    with pytest.raises(ReplicationError):
        with MediaMaterializer(BadStream(b"media")).materialize(job_id="job-1", object_key="temporary/job-1/x", expected_sha256=sha256(b"media").hexdigest()):
            pass


def test_materializer_rejects_unsafe_filename_and_oversized_stream():
    payload = b"media"
    digest = sha256(payload).hexdigest()
    with pytest.raises(ReplicationError):
        with MediaMaterializer(_Store(payload)).materialize(job_id="job-1", object_key="temporary/job-1/x", expected_sha256=digest, filename="../escape"):
            pass
    with pytest.raises(ReplicationError):
        with MediaMaterializer(_Store(payload), max_bytes=2).materialize(job_id="job-1", object_key="temporary/job-1/x", expected_sha256=digest):
            pass


def test_materializer_rejects_symlink_ancestor_of_work_dir(tmp_path: Path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    payload = b"media"
    with pytest.raises(ReplicationError):
        with MediaMaterializer(_Store(payload)).materialize(
            job_id="job-1",
            object_key="temporary/job-1/x",
            expected_sha256=sha256(payload).hexdigest(),
            work_dir=link / "nested",
        ):
            pass
