from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.errors import ReplicationError
from server.object_store import ArtifactRef, FinalVideoStore, S3ObjectStore, TemporaryMediaStore


class MemoryS3:
    """Small injected boto3-shaped fake; tests never use a network client."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}

    def head_object(self, *, Bucket: str, Key: str):
        if Key not in self.objects:
            raise KeyError(Key)
        item = self.objects[Key]
        return {
            "ContentLength": len(item["body"]),
            "ContentType": item["content_type"],
            "Metadata": {"sha256": item["sha256"]},
            "Key": Key,
        }

    def put_object(self, *, Bucket: str, Key: str, Body, ContentType: str, Metadata, **kwargs):
        if kwargs.get("IfNoneMatch") == "*" and Key in self.objects:
            raise PreconditionFailed()
        body = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.objects[Key] = {"body": body, "content_type": ContentType, "sha256": Metadata["sha256"]}
        return {}

    def get_object(self, *, Bucket: str, Key: str):
        if Key not in self.objects:
            raise KeyError(Key)
        item = self.objects[Key]
        return {"Body": BytesIO(item["body"])}

    def copy_object(self, *, Bucket: str, Key: str, CopySource, **kwargs):
        if kwargs.get("IfNoneMatch") == "*" and Key in self.objects:
            raise PreconditionFailed()
        source_key = CopySource["Key"]
        if source_key not in self.objects:
            raise KeyError(source_key)
        source = self.objects[source_key]
        self.objects[Key] = dict(source)
        return {}

    def delete_object(self, *, Bucket: str, Key: str):
        self.objects.pop(Key, None)
        return {}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, **kwargs):
        return {"Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]}

    def generate_presigned_url(self, operation_name: str, *, Params, ExpiresIn: int):
        return f"memory://{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


class PreconditionFailed(Exception):
    response = {"ResponseMetadata": {"HTTPStatusCode": 412}, "Error": {"Code": "PreconditionFailed"}}


class InterleavingS3(MemoryS3):
    def __init__(self):
        super().__init__()
        self.put_barrier = threading.Barrier(2)
        self.copy_barrier = threading.Barrier(2)

    def put_object(self, *, Bucket: str, Key: str, Body, ContentType: str, Metadata, **kwargs):
        body = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.put_barrier.wait(timeout=5)
        if kwargs.get("IfNoneMatch") == "*" and Key in self.objects:
            raise PreconditionFailed()
        self.objects[Key] = {"body": body, "content_type": ContentType, "sha256": Metadata["sha256"]}
        return {}

    def copy_object(self, *, Bucket: str, Key: str, CopySource, **kwargs):
        self.copy_barrier.wait(timeout=5)
        if kwargs.get("IfNoneMatch") == "*" and Key in self.objects:
            raise PreconditionFailed()
        return super().copy_object(Bucket=Bucket, Key=Key, CopySource=CopySource, **kwargs)


@pytest.fixture()
def stores():
    client = MemoryS3()
    base = S3ObjectStore(client, bucket="private-test")
    return client, TemporaryMediaStore(base), FinalVideoStore(base)


def test_temporary_put_head_download_and_exact_job_prefix(stores, tmp_path: Path):
    _client, temporary, _final = stores
    payload = b"video-bytes"
    ref = temporary.put_bytes(job_id="job-1", logical_path="intermediates/assembled.mp4", data=payload, content_type="video/mp4")
    assert isinstance(ref, ArtifactRef)
    assert ref.object_key == "temporary/job-1/intermediates/assembled.mp4"
    assert ref.sha256 == sha256(payload).hexdigest()
    assert temporary.head(ref) == ref
    destination = temporary.download_to(ref=ref, destination=tmp_path / "out.mp4")
    assert destination.read_bytes() == payload
    assert temporary.list_job_keys("job-1") == (ref.object_key,)


@pytest.mark.parametrize("logical_path", ["../other", "/absolute", "a/../../b", "a\\b", "a?x"])
def test_temporary_rejects_traversal_and_cross_job_paths(stores, logical_path: str):
    _client, temporary, _final = stores
    with pytest.raises(ReplicationError):
        temporary.put_bytes(job_id="job-1", logical_path=logical_path, data=b"x", content_type="application/octet-stream")

    with pytest.raises(ReplicationError):
        temporary.head(
            ArtifactRef(
                artifact_id="x",
                kind="object",
                object_key="temporary/job-2/x",
                sha256=sha256(b"x").hexdigest(),
                content_type="application/octet-stream",
                size_bytes=1,
            )
        )


def test_same_key_same_bytes_is_idempotent_but_different_bytes_conflict(stores):
    _client, temporary, _final = stores
    first = temporary.put_bytes(job_id="job-1", logical_path="x.bin", data=b"one", content_type="application/octet-stream")
    replay = temporary.put_bytes(job_id="job-1", logical_path="x.bin", data=b"one", content_type="application/octet-stream")
    assert replay == first
    with pytest.raises(ReplicationError) as ctx:
        temporary.put_bytes(job_id="job-1", logical_path="x.bin", data=b"two", content_type="application/octet-stream")
    assert ctx.value.http_status == 409


def test_final_promotion_verifies_copy_then_deletes_only_source(stores):
    client, temporary, final = stores
    source = temporary.put_bytes(job_id="job-1", logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    promoted = final.promote(job_id="job-1", source=source)
    assert promoted.object_key == "final/job-1/result.mp4"
    assert promoted.content_type == "video/mp4"
    assert promoted.sha256 == source.sha256
    assert "temporary/job-1/assembled.mp4" not in client.objects
    assert final.exists(promoted)
    assert final.promote(job_id="job-1", source=source) == promoted


def test_final_promotion_conflicts_on_different_existing_bytes(stores):
    _client, temporary, final = stores
    first = temporary.put_bytes(job_id="job-1", logical_path="a.mp4", data=b"one", content_type="video/mp4")
    final.promote(job_id="job-1", source=first)
    second = temporary.put_bytes(job_id="job-1", logical_path="b.mp4", data=b"two", content_type="video/mp4")
    with pytest.raises(ReplicationError) as ctx:
        final.promote(job_id="job-1", source=second)
    assert ctx.value.http_status == 409
    assert second.object_key in _client.objects


def test_object_store_signed_get_validates_expiry(stores):
    _client, temporary, final = stores
    source = temporary.put_bytes(job_id="job-1", logical_path="x.mp4", data=b"x", content_type="video/mp4")
    promoted = final.promote(job_id="job-1", source=source)
    assert final.signed_get(promoted, expires_seconds=30).startswith("memory://")
    with pytest.raises(ReplicationError):
        final.signed_get(promoted, expires_seconds=0)


def test_concurrent_different_payloads_same_key_have_one_conditional_winner():
    client = InterleavingS3()
    store = S3ObjectStore(client, bucket="private-test")

    def upload(payload: bytes):
        try:
            return store.put_stream(object_key="temporary/job-1/race.bin", stream=BytesIO(payload), content_type="application/octet-stream")
        except BaseException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(upload, (b"first", b"second")))
    successes = [value for value in results if not isinstance(value, BaseException)]
    assert len(successes) == 1
    errors = [value for value in results if isinstance(value, BaseException)]
    assert len(errors) == 1 and isinstance(errors[0], ReplicationError) and errors[0].http_status == 409
    assert client.objects["temporary/job-1/race.bin"]["body"] in {b"first", b"second"}


def test_concurrent_copy_to_same_key_has_one_conditional_winner(stores):
    _client, temporary, _final = stores
    source_a = temporary.put_bytes(job_id="job-1", logical_path="a.bin", data=b"first", content_type="application/octet-stream")
    source_b = temporary.put_bytes(job_id="job-1", logical_path="b.bin", data=b"second", content_type="application/octet-stream")
    client = InterleavingS3()
    client.objects[source_a.object_key] = {"body": b"first", "content_type": "application/octet-stream", "sha256": source_a.sha256}
    client.objects[source_b.object_key] = {"body": b"second", "content_type": "application/octet-stream", "sha256": source_b.sha256}
    store = S3ObjectStore(client, bucket="private-test")

    def copy(source):
        return store.copy(source_key=source.object_key, destination_key="final/job-1/result.mp4", expected_sha256=source.sha256)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(copy, source) for source in (source_a, source_b)]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except BaseException as exc:
                results.append(exc)
    assert sum(not isinstance(value, BaseException) for value in results) == 1
    errors = [value for value in results if isinstance(value, BaseException)]
    assert len(errors) == 1 and isinstance(errors[0], ReplicationError) and errors[0].http_status == 409


def test_copy_without_conditional_provider_path_streams_through_conditional_put():
    class CopyUnsupported(MemoryS3):
        def copy_object(self, **_kwargs):
            raise TypeError("IfNoneMatch unsupported")

    client = CopyUnsupported()
    source_body = b"source"
    source_key = "temporary/job-1/source.bin"
    client.objects[source_key] = {"body": source_body, "content_type": "application/octet-stream", "sha256": sha256(source_body).hexdigest()}
    store = S3ObjectStore(client, bucket="private-test")
    result = store.copy(source_key=source_key, destination_key="temporary/job-1/copy.bin", expected_sha256=sha256(source_body).hexdigest())
    assert result.sha256 == sha256(source_body).hexdigest()
    assert client.objects["temporary/job-1/copy.bin"]["body"] == source_body


def test_boto3_shaped_client_uses_low_level_conditional_put_not_upload_fileobj():
    class Boto3Shaped(MemoryS3):
        def upload_fileobj(self, *_args, **_kwargs):
            raise AssertionError("upload_fileobj ExtraArgs must not be used")

        def copy_object(self, **_kwargs):
            raise TypeError("conditional copy unsupported")

    client = Boto3Shaped()
    store = S3ObjectStore(client, bucket="private-test")
    payload = b"boto3-shaped"
    digest = sha256(payload).hexdigest()
    uploaded = store.put_stream(
        object_key="temporary/job-1/source.bin",
        stream=BytesIO(payload),
        content_type="application/octet-stream",
        expected_sha256=digest,
    )
    copied = store.copy(
        source_key=uploaded.object_key,
        destination_key="temporary/job-1/copy.bin",
        expected_sha256=digest,
    )
    assert copied.sha256 == digest


def test_final_replay_validates_existing_metadata_and_source_before_delete(stores):
    client, temporary, final = stores
    source = temporary.put_bytes(job_id="job-1", logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    promoted = final.promote(job_id="job-1", source=source)
    # Recreate a source for replay and corrupt the final metadata first.
    replay = temporary.put_bytes(job_id="job-1", logical_path="replay.mp4", data=b"video", content_type="video/mp4")
    client.objects[promoted.object_key]["content_type"] = "application/octet-stream"
    with pytest.raises(ReplicationError):
        final.promote(job_id="job-1", source=replay)
    assert replay.object_key in client.objects

    client.objects[promoted.object_key]["content_type"] = "video/mp4"
    client.objects[replay.object_key]["sha256"] = sha256(b"tampered").hexdigest()
    with pytest.raises(ReplicationError):
        final.promote(job_id="job-1", source=replay)
    assert replay.object_key in client.objects


def test_final_exists_and_signed_get_require_exact_final_ref_metadata(stores):
    _client, temporary, final = stores
    source = temporary.put_bytes(job_id="job-1", logical_path="assembled.mp4", data=b"video", content_type="video/mp4")
    promoted = final.promote(job_id="job-1", source=source)
    assert final.exists(promoted)
    wrong_key = ArtifactRef("x", "final", "temporary/job-1/x", promoted.sha256, "video/mp4", promoted.size_bytes)
    assert not final.exists(wrong_key)
    wrong_type = ArtifactRef("x", "final", promoted.object_key, promoted.sha256, "application/octet-stream", promoted.size_bytes)
    assert not final.exists(wrong_type)
    with pytest.raises(ReplicationError):
        final.signed_get(wrong_key)
    with pytest.raises(ReplicationError):
        final.signed_get(wrong_type)
