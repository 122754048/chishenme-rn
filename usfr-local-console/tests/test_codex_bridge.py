import json
from pathlib import Path

import pytest

from app.codex_bridge import BridgeError, export_codex_task, finalize_codex_result, import_codex_result
from app.jobs import FileJobStore
from app.slots import build_intake, validate_intake


def create_job(store: FileJobStore, temp_dir: Path):
    temp_dir.mkdir(parents=True, exist_ok=True)
    source = temp_dir / "source.mp4"
    source.write_bytes(b"source")
    return store.create(
        validate_intake(build_intake(source_video=source, output_language="fr"), probe_duration=lambda _: 5)
    )


def test_exported_task_binds_job_version_and_input_hashes(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)

    task = export_codex_task(store, job, stage="semantic_analysis_required")

    assert task["expected_job_version"] == job.version
    assert task["inputs"]["source_video"]["sha256"] == job.inputs["source_video"]["sha256"]
    assert task["runtime_packet"]["execution_map"]["run_mode"] == "language_only"
    assert "SKILL.md" not in str(task["runtime_packet"])


def test_export_rejects_a_runtime_packet_whose_input_slots_digest_no_longer_matches_the_job(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)
    execution_map_path = store.job_dir(job.job_id) / "analysis" / "execution_map.json"
    execution_map = json.loads(execution_map_path.read_text(encoding="utf-8"))
    execution_map["input_slots_sha256"] = "0" * 64
    execution_map_path.write_text(json.dumps(execution_map), encoding="utf-8")

    with pytest.raises(BridgeError, match="CODEX_RUNTIME_PACKET_UNAVAILABLE"):
        export_codex_task(store, job, stage="semantic_analysis_required")


def test_import_rejects_a_result_from_another_job(tmp_path):
    store = FileJobStore(tmp_path / "data")
    first = create_job(store, tmp_path / "first")
    second = create_job(store, tmp_path / "second")
    payload = export_codex_task(store, first, stage="semantic_analysis_required")
    payload["result"] = {"kind": "script_revision", "script_text": "draft"}
    finalize_codex_result(payload)

    with pytest.raises(BridgeError, match="CODEX_BRIDGE_RESULT_REJECTED"):
        import_codex_result(store, second.job_id, second.version, payload)


def test_valid_script_result_creates_the_only_script_review_gate(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)
    payload = export_codex_task(store, job, stage="semantic_analysis_required")
    payload["result"] = {"kind": "script_revision", "script_text": "approved draft"}
    finalize_codex_result(payload)

    imported = import_codex_result(store, job.job_id, job.version, payload)

    assert imported.stage == "SCRIPT_REVIEW"
    assert imported.reviews["script"][0]["content"] == "approved draft"


def test_semantic_import_freezes_the_source_contract_before_script_review(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)
    payload = export_codex_task(store, job, stage="semantic_analysis_required")
    payload["result"] = {
        "kind": "script_revision",
        "script_text": "approved draft",
        "source_contract": {
            "regions": [{"region_id": "c01", "start_ms": 0, "end_ms": 5000, "kind": "body"}],
        },
    }
    finalize_codex_result(payload)

    imported = import_codex_result(store, job.job_id, job.version, payload)

    assert imported.execution_map["provisional"] is False
    assert (store.job_dir(job.job_id) / "analysis" / "source_fidelity_contract.json").is_file()


def test_qa_import_persists_the_structured_timing_ledger_for_display(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)
    payload = export_codex_task(store, job, stage="qa_review_ready")
    payload["result"] = {
        "kind": "qa_receipt",
        "receipt": {
            "passed": True,
            "timing_ledger": {
                "queue_wait_ms": 120,
                "active_ms": 800,
                "provider_wait_ms": 600,
                "stages": [{"name": "provider_wait", "status": "succeeded"}],
            },
            "regions": [
                {
                    "region_id": "source_full",
                    "checks": {"timeline_placement": {"passed": True}},
                }
            ],
            "final_technical": {"passed": True},
        },
    }
    finalize_codex_result(payload)

    imported = import_codex_result(store, job.job_id, job.version, payload)

    assert imported.timing_ledger["provider_wait_ms"] == 600
    assert imported.qa_receipt["passed"] is True


def test_qa_import_rejects_a_summary_only_receipt_that_does_not_cover_the_runtime_matrix(tmp_path):
    store = FileJobStore(tmp_path / "data")
    job = create_job(store, tmp_path)
    payload = export_codex_task(store, job, stage="qa_review_ready")
    payload["result"] = {"kind": "qa_receipt", "receipt": {"passed": True}}
    finalize_codex_result(payload)

    with pytest.raises(BridgeError, match="QA_COVERAGE_REQUIRED"):
        import_codex_result(store, job.job_id, job.version, payload)


def test_background_music_qa_import_requires_final_delivery_receipt(tmp_path):
    source = tmp_path / "source.mp4"
    music = tmp_path / "song.mp3"
    source.write_bytes(b"source")
    music.write_bytes(b"music")
    store = FileJobStore(tmp_path / "data")
    job = store.create(
        validate_intake(build_intake(source_video=source, background_music=music), probe_duration=lambda _: 3)
    )
    frozen = store.freeze_source_contract(
        job.job_id,
        expected_version=job.version,
        source_contract={
            "regions": [{"region_id": "c01", "start_ms": 0, "end_ms": 3000, "kind": "body"}],
            "music_timeline_contract": {
                "windows": [
                    {"source_start_frame": 0, "source_end_frame": 30, "output_start_frame": 0, "output_end_frame": 30, "duration_ms": 3000}
                ]
            },
        },
    )
    payload = export_codex_task(store, frozen, stage="qa_review_ready")
    payload["result"] = {
        "kind": "qa_receipt",
        "receipt": {
            "passed": True,
            "regions": [
                {"region_id": "c01", "checks": {"timeline_placement": {"passed": True}}}
            ],
            "final_technical": {"passed": True},
        },
    }
    finalize_codex_result(payload)

    with pytest.raises(BridgeError, match="BACKGROUND_MUSIC_MIX_RECEIPT_REQUIRED"):
        import_codex_result(store, frozen.job_id, frozen.version, payload)


def test_background_music_qa_import_persists_verified_final_delivery_receipt(tmp_path):
    source = tmp_path / "source.mp4"
    music = tmp_path / "song.mp3"
    source.write_bytes(b"source")
    music.write_bytes(b"music")
    store = FileJobStore(tmp_path / "data")
    job = store.create(
        validate_intake(build_intake(source_video=source, background_music=music), probe_duration=lambda _: 3)
    )
    frozen = store.freeze_source_contract(
        job.job_id,
        expected_version=job.version,
        source_contract={
            "regions": [{"region_id": "c01", "start_ms": 0, "end_ms": 3000, "kind": "body"}],
            "music_timeline_contract": {
                "windows": [
                    {"source_start_frame": 0, "source_end_frame": 30, "output_start_frame": 0, "output_end_frame": 30, "duration_ms": 3000}
                ]
            },
        },
    )
    uploaded_sha256 = frozen.inputs["background_music"]["sha256"]
    route = {
        "provider_route": "seedance_audio_reference",
        "provider_asset_type": "Audio",
        "provider_content_type": "audio_url",
        "provider_content_role": "reference_audio",
        "prompt_reference_tag": "@Audio1",
        "forbidden_provider_field": "reference_audios",
        "uploaded_audio_sha256": uploaded_sha256,
        "final_audio_source": "uploaded_exact_audio",
        "allow_loop_or_time_stretch": False,
        "singing_qa": {
            "status": "skipped",
            "reason": "no_visible_singing_person",
            "regions": [],
        },
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 3000,
            }
        ],
    }
    payload = export_codex_task(store, frozen, stage="qa_review_ready")
    payload["result"] = {
        "kind": "qa_receipt",
        "receipt": {
            "passed": True,
            "regions": [
                {"region_id": "c01", "checks": {"timeline_placement": {"passed": True}}}
            ],
            "final_technical": {"passed": True},
        },
        "background_music_delivery": {
            "route": route,
            "final_audio_sha256": "d" * 64,
            "mix_receipt": {
                "passed": True,
                "final_audio_sha256": "d" * 64,
                "uploaded_audio_sha256": uploaded_sha256,
                "window_receipts": [
                    {
                        **route["windows"][0],
                        "fragment_sha256": "e" * 64,
                        "looped": False,
                        "time_stretched": False,
                        "pitch_shifted": False,
                        "generated_substitute": False,
                    }
                ],
            },
        },
    }
    finalize_codex_result(payload)

    imported = import_codex_result(store, frozen.job_id, frozen.version, payload)

    assert imported.qa_receipt["background_music_delivery"]["final_audio_sha256"] == "d" * 64
    persisted_map = json.loads(
        (store.job_dir(frozen.job_id) / "analysis" / "execution_map.json").read_text(encoding="utf-8")
    )
    assert imported.execution_map["background_music"]["final_audio_sha256"] == "d" * 64
    assert imported.execution_map["background_music"]["delivery_status"] == "verified"
    assert imported.execution_map["background_music"]["singing_qa"] == route["singing_qa"]
    assert persisted_map["background_music"] == imported.execution_map["background_music"]


def test_background_music_qa_import_rejects_skipping_a_visible_singer(tmp_path):
    source = tmp_path / "source.mp4"
    music = tmp_path / "song.mp3"
    source.write_bytes(b"source")
    music.write_bytes(b"music")
    store = FileJobStore(tmp_path / "data")
    job = store.create(
        validate_intake(build_intake(source_video=source, background_music=music), probe_duration=lambda _: 3)
    )
    frozen = store.freeze_source_contract(
        job.job_id,
        expected_version=job.version,
        source_contract={
            "regions": [
                {
                    "region_id": "c01",
                    "start_ms": 0,
                    "end_ms": 3000,
                    "kind": "body",
                    "visible_singer": True,
                }
            ],
            "music_timeline_contract": {
                "windows": [
                    {
                        "source_start_frame": 0,
                        "source_end_frame": 30,
                        "output_start_frame": 0,
                        "output_end_frame": 30,
                        "duration_ms": 3000,
                    }
                ]
            },
        },
    )
    uploaded_sha256 = frozen.inputs["background_music"]["sha256"]
    route = {
        "provider_route": "seedance_audio_reference",
        "provider_asset_type": "Audio",
        "provider_content_type": "audio_url",
        "provider_content_role": "reference_audio",
        "prompt_reference_tag": "@Audio1",
        "forbidden_provider_field": "reference_audios",
        "uploaded_audio_sha256": uploaded_sha256,
        "final_audio_source": "uploaded_exact_audio",
        "allow_loop_or_time_stretch": False,
        "singing_qa": {
            "status": "skipped",
            "reason": "no_visible_singing_person",
            "regions": [],
        },
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 3000,
            }
        ],
    }
    payload = export_codex_task(store, frozen, stage="qa_review_ready")
    payload["result"] = {
        "kind": "qa_receipt",
        "receipt": {
            "passed": True,
            "regions": [
                {"region_id": "c01", "checks": {"timeline_placement": {"passed": True}}}
            ],
            "final_technical": {"passed": True},
        },
        "background_music_delivery": {
            "route": route,
            "final_audio_sha256": "d" * 64,
            "mix_receipt": {
                "passed": True,
                "final_audio_sha256": "d" * 64,
                "uploaded_audio_sha256": uploaded_sha256,
                "window_receipts": [
                    {
                        **route["windows"][0],
                        "fragment_sha256": "e" * 64,
                        "looped": False,
                        "time_stretched": False,
                        "pitch_shifted": False,
                        "generated_substitute": False,
                    }
                ],
            },
        },
    }
    finalize_codex_result(payload)

    with pytest.raises(BridgeError, match="SINGING_ALIGNMENT_REQUIRED"):
        import_codex_result(store, frozen.job_id, frozen.version, payload)
