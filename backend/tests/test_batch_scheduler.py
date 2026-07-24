from app.batch_manifest import BatchManifestError, parse_batch_manifest
from app.batch_scheduler import BatchScheduler


class _Queue:
    def __init__(self):
        self.messages = []

    def enqueue(self, message):
        self.messages.append(message)


def _row(row_id: str, source: str) -> dict[str, object]:
    return {
        "row_id": row_id,
        "slots": {
            "source_video": source,
            "new_product_image": None,
            "new_model_image": None,
            "ui_screenshot": None,
            "app_store_url": None,
            "ui_operation_video": None,
            "tail_video": None,
        },
        "extensions": {"background_music": None},
        "output_language": "de",
        "opaque_audio_policy": {},
    }


def test_batch_manifest_keeps_each_row_as_an_independent_fixed_slot_job():
    rows = parse_batch_manifest([_row("physical", "source-a"), _row("app", "source-b")])
    created = []
    scheduler = BatchScheduler(create_job=lambda row: created.append(row) or f"job-{row.row_id}")

    result = scheduler.submit_rows(rows)

    assert [item["job_id"] for item in result] == ["job-physical", "job-app"]
    assert [row.row_id for row in created] == ["physical", "app"]


def test_invalid_row_isolated_and_source_analysis_cache_is_never_shared_across_jobs():
    scheduler = BatchScheduler(create_job=lambda row: f"job-{row.row_id}")
    valid = parse_batch_manifest([_row("one", "same-source")])[0]

    result = scheduler.submit_rows([valid, {"row_id": "broken", "slots": {}}])

    assert result[0]["status"] == "queued"
    assert result[1]["status"] == "rejected"
    assert scheduler.claim_source_analysis("job-one", "same-source") is True
    assert scheduler.claim_source_analysis("job-one", "same-source") is False
    assert scheduler.claim_source_analysis("job-two", "same-source") is True


def test_batch_manifest_rejects_unknown_extension_and_missing_source_video():
    invalid_extension = _row("bad-extension", "source")
    invalid_extension["extensions"] = {"voice_clone": "voice.mp3"}
    with_source_missing = _row("missing-source", "")

    try:
        parse_batch_manifest([invalid_extension])
    except BatchManifestError as error:
        assert str(error) == "BATCH_EXTENSION_UNSUPPORTED"
    else:
        raise AssertionError("expected extension rejection")
    try:
        parse_batch_manifest([with_source_missing])
    except BatchManifestError as error:
        assert str(error) == "BATCH_SOURCE_VIDEO_REQUIRED"
    else:
        raise AssertionError("expected source rejection")


def test_batch_manifest_preserves_object_store_upload_completion_records():
    source_sha = "a" * 64
    music_sha = "b" * 64
    rows = parse_batch_manifest(
        [
            {
                "row_id": "completed-upload",
                "slots": {
                    "source_video": {
                        "object_key": "uploads/batch-scope/source.mp4",
                        "sha256": source_sha,
                        "size_bytes": 128,
                        "content_type": "video/mp4",
                        "duration_seconds": 12.0,
                        "status": "completed",
                    }
                },
                "extensions": {
                    "background_music": {
                        "object_key": "uploads/batch-scope/song.mp3",
                        "sha256": music_sha,
                        "size_bytes": 64,
                        "content_type": "audio/mpeg",
                        "duration_seconds": 30.0,
                        "status": "completed",
                    }
                },
                "output_language": None,
                "opaque_audio_policy": {},
            }
        ]
    )

    assert rows[0].slots["source_video"] == {
        "object_key": "uploads/batch-scope/source.mp4",
        "sha256": source_sha,
        "size_bytes": 128,
        "content_type": "video/mp4",
        "duration_seconds": 12.0,
        "status": "completed",
    }
    assert rows[0].extensions["background_music"] == {
        "object_key": "uploads/batch-scope/song.mp3",
        "sha256": music_sha,
        "size_bytes": 64,
        "content_type": "audio/mpeg",
        "duration_seconds": 30.0,
        "status": "completed",
    }
