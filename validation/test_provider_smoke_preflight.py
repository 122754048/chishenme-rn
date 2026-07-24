import hashlib
import json

from validation.provider_smoke_preflight import (
    LOCAL_RUNNINGHUB_SMOKE_CONTRACT,
    REQUIRED_PROVIDER_CONFIGURATION,
    build_provider_smoke_preflight,
)


def test_preflight_reports_not_run_when_provider_configuration_is_missing(tmp_path):
    source_video = tmp_path / "source.mp4"
    background_music = tmp_path / "song.wav"
    source_video.write_bytes(b"source-video")
    background_music.write_bytes(b"uploaded-song")

    receipt = build_provider_smoke_preflight(
        source_video=source_video,
        background_music=background_music,
        environment={},
    )

    assert receipt["status"] == "NOT_RUN"
    assert receipt["provider_tasks_created"] == 0
    assert receipt["missing_configuration"] == list(REQUIRED_PROVIDER_CONFIGURATION)
    assert receipt["execution_manifest"] == []


def test_ready_preflight_emits_one_create_budget_per_real_smoke_step_without_secrets(tmp_path):
    source_video = tmp_path / "source.mp4"
    background_music = tmp_path / "song.wav"
    source_video.write_bytes(b"source-video")
    background_music.write_bytes(b"uploaded-song")
    environment = {
        name: f"test-secret-value-{index}"
        for index, name in enumerate(REQUIRED_PROVIDER_CONFIGURATION, start=1)
    }

    receipt = build_provider_smoke_preflight(
        source_video=source_video,
        background_music=background_music,
        environment=environment,
    )

    assert receipt["status"] == "READY_FOR_EXPLICIT_EXECUTION"
    assert receipt["runninghub_contract"] == LOCAL_RUNNINGHUB_SMOKE_CONTRACT
    assert receipt["runninghub_contract_sha256"] == hashlib.sha256(
        json.dumps(LOCAL_RUNNINGHUB_SMOKE_CONTRACT, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert receipt["provider_tasks_created"] == 0
    assert [step["step_id"] for step in receipt["execution_manifest"]] == [
        "runninghub_storyboard_image",
        "runninghub_asr",
        "runninghub_tts",
        "runninghub_lip_sync",
        "youdao_audio_asset",
        "youdao_seedance_video",
    ]
    assert all(step["maximum_create_attempts"] == 1 for step in receipt["execution_manifest"])
    assert all(step["ambiguous_outcome_policy"] == "query_or_reconcile_only" for step in receipt["execution_manifest"])
    rendered = json.dumps(receipt, ensure_ascii=True)
    assert all(value not in rendered for value in environment.values())


def test_local_smoke_uses_the_user_documented_primary_lipsync_contract_not_deployment_fallback_fields(tmp_path):
    source_video = tmp_path / "source.mp4"
    background_music = tmp_path / "song.wav"
    source_video.write_bytes(b"source-video")
    background_music.write_bytes(b"uploaded-song")

    receipt = build_provider_smoke_preflight(
        source_video=source_video,
        background_music=background_music,
        environment={
            "RUNNINGHUB_API_KEY": "runninghub-test-key",
            "YOUDAO_API_KEY": "youdao-test-key",
            "YOUDAO_BASE_URL": "https://openapi.youdao.test/llmgateway",
        },
    )

    assert REQUIRED_PROVIDER_CONFIGURATION == (
        "RUNNINGHUB_API_KEY",
        "YOUDAO_API_KEY",
        "YOUDAO_BASE_URL",
    )
    assert receipt["status"] == "READY_FOR_EXPLICIT_EXECUTION"
    assert LOCAL_RUNNINGHUB_SMOKE_CONTRACT == {
        "upload_url": "https://www.runninghub.ai/openapi/v2/media/upload/binary",
        "query_url": "https://www.runninghub.ai/openapi/v2/query",
        "asr": {"workflow_id": "2080170949061038081", "node_id": "1", "field_name": "video"},
        "tts": {
            "workflow_id": "2080177717619118082",
            "audio_node_id": "4",
            "audio_field_name": "audio",
            "prompt_node_id": "11",
            "prompt_field_name": "prompt",
        },
        "lip_sync": {
            "url": "https://www.runninghub.ai/openapi/v2/run/ai-app/2080140197518823426",
            "workflow_id": "2080140197518823426",
            "audio_node_id": "3",
            "audio_field_name": "audio",
            "video_node_id": "6",
            "video_field_name": "video",
        },
    }
