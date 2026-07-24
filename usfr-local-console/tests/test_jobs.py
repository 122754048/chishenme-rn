from pathlib import Path
import json

import pytest

from app.jobs import FileJobStore, JobNotFound, VersionConflict
from app.settings import sha256_file
from app.slots import build_intake, validate_intake


def make_validated_intake(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable-source")
    return validate_intake(
        build_intake(source_video=source, output_language="fr"),
        probe_duration=lambda _: 6.0,
    )


def test_job_copy_is_immutable_and_version_conflicts_fail(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = store.create(make_validated_intake(tmp_path))
    stored = store.job_dir(job.job_id) / "inputs" / "source_video.mp4"

    assert sha256_file(stored) == job.inputs["source_video"]["sha256"]
    with pytest.raises(VersionConflict):
        store.update(job.job_id, expected_version=999, mutate=lambda current: current)


def test_job_updates_are_versioned_and_append_an_event(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = store.create(make_validated_intake(tmp_path))
    changed = store.update(
        job.job_id,
        expected_version=job.version,
        mutate=lambda current: {**current, "stage": "SCRIPT_REVIEW"},
    )

    assert changed.version == job.version + 1
    events = (store.job_dir(job.job_id) / "events.ndjson").read_text(encoding="utf-8")
    assert '"event":"JOB_UPDATED"' in events


def test_job_creation_persists_input_contract_and_route_preview_atomically(tmp_path):
    source = tmp_path / "source.mp4"
    model = tmp_path / "model.png"
    source.write_bytes(b"source")
    model.write_bytes(b"model")
    store = FileJobStore(tmp_path / "data")

    job = store.create(
        validate_intake(
            build_intake(source_video=source, new_model_image=model, output_language="de"),
            probe_duration=lambda _: 6.0,
        )
    )

    execution_map = json.loads((store.job_dir(job.job_id) / "analysis" / "execution_map.json").read_text("utf-8"))
    input_slots = json.loads((store.job_dir(job.job_id) / "analysis" / "input_slots.json").read_text("utf-8"))
    target_truth = json.loads((store.job_dir(job.job_id) / "analysis" / "target_truth.json").read_text("utf-8"))
    assert execution_map["input_slots_sha256"] == job.execution_map["input_slots_sha256"]
    assert input_slots["source_video"]["sha256"] == job.inputs["source_video"]["sha256"]
    assert target_truth["facts"]["new_model_image"]["source_sha256"] == job.inputs["new_model_image"]["sha256"]
    assert job.route_preview["run_mode"] == "composite_replication"
    assert job.route_preview["deep_analysis"] == "once"


def test_freezing_source_contract_replaces_provisional_music_route_once(tmp_path):
    source = tmp_path / "source.mp4"
    music = tmp_path / "song.mp3"
    source.write_bytes(b"source")
    music.write_bytes(b"music")
    store = FileJobStore(tmp_path / "data")
    job = store.create(
        validate_intake(
            build_intake(source_video=source, background_music=music),
            probe_duration=lambda _: 3.0,
        )
    )

    frozen = store.freeze_source_contract(
        job.job_id,
        expected_version=job.version,
        source_contract={
            "regions": [{"region_id": "c01", "start_ms": 0, "end_ms": 3000, "kind": "body", "visible_singer": True}],
            "music_timeline_contract": {
                "windows": [{"source_start_frame": 0, "source_end_frame": 30, "output_start_frame": 0, "output_end_frame": 30, "duration_ms": 3000}]
            },
        },
    )

    music_contract = json.loads((store.job_dir(job.job_id) / "analysis" / "music_timeline_contract.json").read_text("utf-8"))
    execution_map = json.loads((store.job_dir(job.job_id) / "analysis" / "execution_map.json").read_text("utf-8"))
    assert frozen.execution_map["provisional"] is False
    assert music_contract["windows"][0]["source_start_frame"] == 0
    assert execution_map["background_music"]["timeline_contract_ref"] == "analysis/music_timeline_contract.json"
    music_preview = frozen.route_preview["background_music"]
    assert music_preview["timeline_status"] == "frozen"
    assert music_preview["source_windows"] == [
        {"source_start_frame": 0, "source_end_frame": 30, "output_start_frame": 0, "output_end_frame": 30}
    ]
    assert music_preview["visible_singer_regions"] == ["c01"]
    assert "singing_alignment_and_lip_sync_required" in music_preview["risks"]


def test_freezing_an_app_generation_contract_resolves_one_cached_official_bundle_and_binds_target_truth(tmp_path):
    calls = []

    def resolve_app_evidence(*, url, purpose):
        calls.append((url, purpose))
        return {
            "bundle_sha256": "a" * 64,
            "canonical_url": url,
            "app_id": "com.example.app",
            "screenshots": [{"sha256": "b" * 64, "source": "official"}],
            "icon": {"sha256": "c" * 64, "source": "official"},
            "allowed_claims": ["profile discovery"],
            "blocked_claims": ["guaranteed results"],
        }

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    store = FileJobStore(tmp_path / "data", app_evidence_resolver=resolve_app_evidence)
    job = store.create(
        validate_intake(
            build_intake(
                source_video=source,
                app_store_url="https://play.google.com/store/apps/details?id=com.example.app",
            ),
            probe_duration=lambda _: 3.0,
        )
    )

    frozen = store.freeze_source_contract(
        job.job_id,
        expected_version=job.version,
        source_contract={
            "regions": [{"region_id": "c01", "start_ms": 0, "end_ms": 3000, "kind": "body"}]
        },
    )

    target_truth = json.loads(
        (store.job_dir(job.job_id) / "analysis" / "target_truth.json").read_text(encoding="utf-8")
    )
    assert calls == [
        (
            "https://play.google.com/store/apps/details?id=com.example.app",
            ("claim_truth",),
        )
    ]
    assert target_truth["app_evidence_bundle_sha256"] == "a" * 64
    assert frozen.execution_map["app_evidence"]["existing_bundle_sha256"] == "a" * 64


def test_background_music_job_requires_frozen_music_timeline_before_it_can_leave_analysis(tmp_path):
    source = tmp_path / "source.mp4"
    music = tmp_path / "song.mp3"
    source.write_bytes(b"source")
    music.write_bytes(b"music")
    store = FileJobStore(tmp_path / "data")
    job = store.create(
        validate_intake(
            build_intake(source_video=source, background_music=music),
            probe_duration=lambda _: 3.0,
        )
    )

    with pytest.raises(ValueError, match="MUSIC_TIMELINE_CONTRACT_REQUIRED"):
        store.freeze_source_contract(
            job.job_id,
            expected_version=job.version,
            source_contract={"regions": [{"region_id": "c01", "start_ms": 0, "end_ms": 3000, "kind": "body"}]},
        )


def test_publishing_final_video_removes_all_job_history_but_keeps_the_mp4(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = store.create(make_validated_intake(tmp_path))

    receipt = store.publish_final_video(
        job.job_id,
        expected_version=job.version,
        payload=b"final-video-bytes",
    )

    assert receipt.job_id == job.job_id
    assert store.final_video_path(job.job_id).read_bytes() == b"final-video-bytes"
    assert not store.job_dir(job.job_id).exists()
    with pytest.raises(JobNotFound):
        store.get(job.job_id)
    assert sorted(path.relative_to(store.data_root).as_posix() for path in store.data_root.rglob("*") if path.is_file()) == [
        f"final/{job.job_id}/result.mp4"
    ]


def test_expired_temporary_jobs_are_purged_without_deleting_final_videos(tmp_path):
    store = FileJobStore(tmp_path / "data")
    expired = store.create(make_validated_intake(tmp_path))
    delivered = store.create(make_validated_intake(tmp_path))
    store.publish_final_video(delivered.job_id, expected_version=delivered.version, payload=b"final")

    import os

    os.utime(store.job_dir(expired.job_id), (0, 0))
    removed = store.purge_expired_jobs(ttl_seconds=1, now_epoch_seconds=2)

    assert removed == (expired.job_id,)
    assert not store.job_dir(expired.job_id).exists()
    assert store.final_video_path(delivered.job_id).read_bytes() == b"final"


def test_default_app_store_cache_is_job_temporary_and_is_removed_at_delivery(tmp_path):
    def resolve_app_evidence(*, url, purpose):
        del purpose
        return {
            "bundle_sha256": "a" * 64,
            "canonical_url": url,
            "app_id": "com.example.app",
            "screenshots": [{"sha256": "b" * 64, "source": "official"}],
            "icon": {"sha256": "c" * 64, "source": "official"},
        }

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    store = FileJobStore(tmp_path / "data", app_evidence_resolver=resolve_app_evidence)
    job = store.create(
        validate_intake(
            build_intake(
                source_video=source,
                app_store_url="https://play.google.com/store/apps/details?id=com.example.app",
            ),
            probe_duration=lambda _: 3.0,
        )
    )
    store.freeze_source_contract(
        job.job_id,
        expected_version=job.version,
        source_contract={"regions": [{"region_id": "c01", "start_ms": 0, "end_ms": 3000, "kind": "body"}]},
    )

    assert (store.job_dir(job.job_id) / "cache" / "app_evidence").is_dir()
    assert not (store.data_root / "app_evidence_cache").exists()
    store.publish_final_video(job.job_id, expected_version=store.get(job.job_id).version, payload=b"final")
    assert not (store.job_dir(job.job_id) / "cache").exists()
