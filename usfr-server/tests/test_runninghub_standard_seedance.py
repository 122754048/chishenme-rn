from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from config import ConfigurationError, Settings, build_redacted_provider_preflight, load_settings  # noqa: E402
from server.runninghub_standard_contract import (  # noqa: E402
    RunningHubStandardPayloadError,
    validate_runninghub_standard_payload_contract,
)
from runninghub_seedance_submit import (  # noqa: E402
    PayloadError,
    RunningHubStandardSeedanceClient,
    RunningHubSeedanceError,
    build_runninghub_standard_payload,
    main,
    validate_runninghub_standard_payload,
    write_create_reconciliation_receipt,
)
import runninghub_seedance_submit as seedance_submit  # noqa: E402
from source_video_reference import SourceVideoReference  # noqa: E402


def test_shared_standard_contract_rejects_audio_without_a_visual_reference() -> None:
    payload = {
        "prompt": "Use @Audio1 exactly.",
        "resolution": "720p",
        "duration": "5",
        "imageUrls": [],
        "videoUrls": [],
        "audioUrls": ["https://media.example/song-clip.mp3"],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": False,
        "conversionSlots": [],
        "returnLastFrame": False,
        "seed": -1,
    }

    try:
        validate_runninghub_standard_payload_contract(payload)
    except RunningHubStandardPayloadError as error:
        assert "image reference" in str(error)
    else:
        raise AssertionError("an audio reference without an approved visual reference must be rejected")


def test_cli_uploads_song_audio_to_the_runninghub_audio_urls_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class UploadOnlyClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def upload_file(self, path: Path) -> str:
            return f"https://media.example/{path.name}"

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Use @Audio1 as the exact uploaded song reference.", encoding="utf-8")
    song = tmp_path / "song.mp3"
    song.write_bytes(b"song")
    settings = Settings(
        runninghub_api_key="workflow-key",
        runninghub_base_url="https://www.runninghub.ai",
        runninghub_seedance_api_key="standard-key",
        runninghub_seedance_create_url="https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
        runninghub_seedance_query_url="https://www.runninghub.cn/openapi/v2/query",
        runninghub_seedance_upload_url="https://www.runninghub.cn/openapi/v2/media/upload/binary",
        seedance_api_provider="runninghub_standard",
    )
    monkeypatch.setattr(seedance_submit, "RunningHubStandardSeedanceClient", UploadOnlyClient)
    monkeypatch.setattr(seedance_submit, "load_settings", lambda _: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runninghub_seedance_submit.py",
            "--prompt-file",
            str(prompt),
            "--duration",
            "5",
            "--image-url",
            "https://media.example/board.png",
            "--audio-file",
            str(song),
            "--output-dir",
            str(tmp_path),
            "--dry-run",
        ],
    )

    assert main() == 0
    payload = json.loads((tmp_path / "request.redacted.json").read_text(encoding="utf-8"))
    assert payload["audioUrls"] == ["https://media.example/song.mp3"]
    assert payload["videoUrls"] == []
    assert "reference_audios" not in payload


def test_cli_submits_the_exact_dry_run_payload_without_reuploading_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class UploadAndCreateClient:
        upload_calls: list[Path] = []
        created_payloads: list[dict[str, object]] = []

        def __init__(self, *_: object, **__: object) -> None:
            self.last_response: dict[str, object] = {}

        def upload_file(self, path: Path) -> str:
            self.upload_calls.append(path)
            return f"https://media.example/upload-{len(self.upload_calls)}-{path.name}"

        def create_video(self, payload: dict[str, object]) -> str:
            self.created_payloads.append(payload)
            self.last_response = {"taskId": "task-123"}
            return "task-123"

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Keep the approved performance.", encoding="utf-8")
    board = tmp_path / "board.png"
    board.write_bytes(b"board")
    settings = Settings(
        runninghub_api_key="workflow-key",
        runninghub_base_url="https://www.runninghub.ai",
        runninghub_seedance_api_key="standard-key",
        runninghub_seedance_create_url="https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
        runninghub_seedance_query_url="https://www.runninghub.cn/openapi/v2/query",
        runninghub_seedance_upload_url="https://www.runninghub.cn/openapi/v2/media/upload/binary",
        seedance_api_provider="runninghub_standard",
    )
    monkeypatch.setattr(seedance_submit, "RunningHubStandardSeedanceClient", UploadAndCreateClient)
    monkeypatch.setattr(seedance_submit, "load_settings", lambda _: settings)
    common_args = [
        "runninghub_seedance_submit.py",
        "--prompt-file",
        str(prompt),
        "--duration",
        "5",
        "--image-file",
        str(board),
        "--output-dir",
        str(tmp_path),
    ]

    monkeypatch.setattr(sys, "argv", [*common_args, "--dry-run"])
    assert main() == 0
    approved_sha = json.loads((tmp_path / "approval_preview.json").read_text(encoding="utf-8"))["request_sha256"]
    dry_run_payload = json.loads((tmp_path / "request.redacted.json").read_text(encoding="utf-8"))
    asset_bindings = json.loads((tmp_path / "asset_bindings.json").read_text(encoding="utf-8"))
    assert asset_bindings["image_file_bindings"] == [
        {
            "sha256": "859169b38185780daa5497983ff20d2994390058d8a71f2847ac7846f970971e",
            "url": "https://media.example/upload-1-board.png",
        }
    ]

    monkeypatch.setattr(sys, "argv", [*common_args, "--approved-request-sha256", approved_sha])
    assert main() == 0

    assert UploadAndCreateClient.upload_calls == [board]
    assert UploadAndCreateClient.created_payloads == [dry_run_payload]
    assert (tmp_path / "task_id.txt").read_text(encoding="utf-8") == "task-123"


def test_cli_rejects_question_mark_placeholder_before_media_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class UploadProbeClient:
        upload_calls: list[Path] = []

        def __init__(self, *_: object, **__: object) -> None:
            pass

        def upload_file(self, path: Path) -> str:
            self.upload_calls.append(path)
            return "https://media.example/uploaded-board.png"

    prompt = tmp_path / "prompt.md"
    prompt.write_text('TARGET_MALE says exactly, "????".', encoding="utf-8")
    board = tmp_path / "board.png"
    board.write_bytes(b"board")
    settings = Settings(
        runninghub_api_key="workflow-key",
        runninghub_base_url="https://www.runninghub.ai",
        runninghub_seedance_api_key="standard-key",
        runninghub_seedance_create_url="https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
        runninghub_seedance_query_url="https://www.runninghub.cn/openapi/v2/query",
        runninghub_seedance_upload_url="https://www.runninghub.cn/openapi/v2/media/upload/binary",
        seedance_api_provider="runninghub_standard",
    )
    monkeypatch.setattr(seedance_submit, "RunningHubStandardSeedanceClient", UploadProbeClient)
    monkeypatch.setattr(seedance_submit, "load_settings", lambda _: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runninghub_seedance_submit.py",
            "--prompt-file",
            str(prompt),
            "--duration",
            "5",
            "--image-file",
            str(board),
            "--output-dir",
            str(tmp_path),
            "--dry-run",
        ],
    )

    with pytest.raises(PayloadError, match="question-mark placeholder"):
        main()
    assert UploadProbeClient.upload_calls == []


def test_standard_payload_uses_documented_fields_and_keeps_source_video_out() -> None:
    payload = build_runninghub_standard_payload(
        "Use @Audio1 exactly.",
        13,
        "9:16",
        ["https://media.example/board.png", "https://media.example/model.jpg"],
        ["https://media.example/song-clip.mp3"],
        real_person_mode=True,
    )

    assert payload == {
        "prompt": "Use @Audio1 exactly.",
        "resolution": "720p",
        "duration": "13",
        "imageUrls": [
            "https://media.example/board.png",
            "https://media.example/model.jpg",
        ],
        "videoUrls": [],
        "audioUrls": ["https://media.example/song-clip.mp3"],
        "generateAudio": True,
        "ratio": "9:16",
        "realPersonMode": True,
        "conversionSlots": ["all"],
        "returnLastFrame": False,
        "seed": -1,
    }


def test_standard_payload_accepts_one_source_segment_video_reference() -> None:
    payload = build_runninghub_standard_payload(
        "Follow @Image1 and the reference video motion.",
        13,
        "9:16",
        ["https://media.example/approved-storyboard.png", "https://media.example/new-model.jpg"],
        [],
        video_urls=["https://media.example/source-s01.mp4"],
        real_person_mode=True,
    )

    assert payload["videoUrls"] == ["https://media.example/source-s01.mp4"]
    assert payload["imageUrls"][0] == "https://media.example/approved-storyboard.png"
    assert payload["realPersonMode"] is True
    assert payload["conversionSlots"] == ["all"]


def test_cli_freezes_one_uploaded_source_segment_with_target_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class UploadOnlyClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def upload_file(self, path: Path) -> str:
            return f"https://media.example/{path.name}"

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Follow @Image1 and preserve the reference motion.", encoding="utf-8")
    board = tmp_path / "approved-storyboard.png"
    board.write_bytes(b"board")
    source_segment = tmp_path / "source-s01.mp4"
    source_segment.write_bytes(b"source-segment")
    source_video_sha256 = hashlib.sha256(b"entire-source-video").hexdigest()
    settings = Settings(
        runninghub_api_key="workflow-key",
        runninghub_base_url="https://www.runninghub.ai",
        runninghub_seedance_api_key="standard-key",
        runninghub_seedance_create_url="https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
        runninghub_seedance_query_url="https://www.runninghub.cn/openapi/v2/query",
        runninghub_seedance_upload_url="https://www.runninghub.cn/openapi/v2/media/upload/binary",
        seedance_api_provider="runninghub_standard",
    )
    monkeypatch.setattr(seedance_submit, "RunningHubStandardSeedanceClient", UploadOnlyClient)
    monkeypatch.setattr(seedance_submit, "load_settings", lambda _: settings)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runninghub_seedance_submit.py",
            "--prompt-file",
            str(prompt),
            "--duration",
            "8",
            "--image-file",
            str(board),
            "--video-file",
            str(source_segment),
            "--source-video-sha256",
            source_video_sha256,
            "--segment-id",
            "S01",
            "--segment-start-ms",
            "0",
            "--segment-end-ms",
            "8000",
            "--target-change",
            "new_model_image:" + ("a" * 64),
            "--output-dir",
            str(tmp_path),
            "--dry-run",
            "--real-person-mode",
        ],
    )

    assert main() == 0
    payload = json.loads((tmp_path / "request.redacted.json").read_text(encoding="utf-8"))
    bindings = json.loads((tmp_path / "asset_bindings.json").read_text(encoding="utf-8"))
    assert payload["videoUrls"] == ["https://media.example/source-s01.mp4"]
    assert bindings["video_reference"]["segment_id"] == "S01"
    assert bindings["video_reference"]["source_video_sha256"] == source_video_sha256
    assert bindings["video_reference"]["target_changes"] == [
        {"kind": "new_model_image", "sha256": "a" * 64}
    ]


def test_cli_prepares_the_frozen_source_segment_from_source_video_and_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class UploadOnlyClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def upload_file(self, path: Path) -> str:
            return f"https://media.example/{path.name}"

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Follow @Image1 and preserve the reference motion.", encoding="utf-8")
    board = tmp_path / "approved-storyboard.png"
    board.write_bytes(b"board")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    plan = tmp_path / "segment_plan.json"
    plan.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "segment_id": "S01",
                        "start_ms": 0,
                        "end_ms": 8_000,
                        "duration_ms": 8_000,
                        "cut_ids": ["C01"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    source_segment = tmp_path / "source-reference-S01.mp4"
    source_segment.write_bytes(b"prepared-segment")
    prepared = SourceVideoReference(
        path=source_segment,
        source_video_sha256=hashlib.sha256(b"source").hexdigest(),
        source_slice_sha256=hashlib.sha256(b"prepared-segment").hexdigest(),
        segment_id="S01",
        start_ms=0,
        end_ms=8_000,
        reused_source=False,
    )
    calls: list[dict[str, object]] = []

    def materialize(**kwargs: object) -> SourceVideoReference:
        calls.append(dict(kwargs))
        return prepared

    settings = Settings(
        runninghub_api_key="workflow-key",
        runninghub_base_url="https://www.runninghub.ai",
        runninghub_seedance_api_key="standard-key",
        runninghub_seedance_create_url="https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
        runninghub_seedance_query_url="https://www.runninghub.cn/openapi/v2/query",
        runninghub_seedance_upload_url="https://www.runninghub.cn/openapi/v2/media/upload/binary",
        seedance_api_provider="runninghub_standard",
    )
    monkeypatch.setattr(seedance_submit, "RunningHubStandardSeedanceClient", UploadOnlyClient)
    monkeypatch.setattr(seedance_submit, "load_settings", lambda _: settings)
    monkeypatch.setattr(seedance_submit, "materialize_source_video_reference", materialize)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runninghub_seedance_submit.py",
            "--prompt-file",
            str(prompt),
            "--duration",
            "8",
            "--image-file",
            str(board),
            "--source-video-file",
            str(source),
            "--segment-plan-file",
            str(plan),
            "--segment-id",
            "S01",
            "--target-change",
            "new_model_image:" + ("a" * 64),
            "--output-dir",
            str(tmp_path / "submission"),
            "--dry-run",
            "--real-person-mode",
        ],
    )

    assert main() == 0
    output_dir = tmp_path / "submission"
    payload = json.loads((output_dir / "request.redacted.json").read_text(encoding="utf-8"))
    bindings = json.loads((output_dir / "asset_bindings.json").read_text(encoding="utf-8"))
    assert calls == [
        {
            "source_video": source,
            "segment_plan": json.loads(plan.read_text(encoding="utf-8")),
            "segment_id": "S01",
            "output_dir": output_dir / "source_video_references",
        }
    ]
    assert payload["videoUrls"] == ["https://media.example/source-reference-S01.mp4"]
    assert bindings["video_reference"]["source_video_sha256"] == prepared.source_video_sha256
    assert bindings["video_reference"]["source_slice_sha256"] == prepared.source_slice_sha256


def test_standard_payload_validation_rejects_route_excluded_markers_in_all_values() -> None:
    payload = build_runninghub_standard_payload(
        "Keep the verified performance.",
        8,
        "9:16",
        ["https://media.example/board.png"],
        [],
        real_person_mode=False,
    )
    payload["prompt"] = "Recreate the source video framing."
    payload["imageUrls"] = ["https://media.example/opaque-ui-frame.png"]

    try:
        validate_runninghub_standard_payload(payload, fixed_b=True)
    except PayloadError as error:
        assert "route leakage" in str(error)
    else:
        raise AssertionError("route-excluded prompt and media values must be rejected")


def test_standard_payload_validation_rejects_unresolved_prompt_placeholder() -> None:
    payload = build_runninghub_standard_payload(
        "Keep the approved action in frame.",
        8,
        "9:16",
        ["https://media.example/board.png"],
        [],
        real_person_mode=False,
    )
    payload["prompt"] = "Keep {{approved_action}} in frame."

    try:
        validate_runninghub_standard_payload(payload, fixed_b=True)
    except PayloadError as error:
        assert "unresolved placeholders" in str(error)
    else:
        raise AssertionError("unresolved prompt placeholders must be rejected")


def test_standard_payload_validation_rejects_non_public_literal_media_hosts() -> None:
    for host in (
        "localhost",
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "[::1]",
        "[fc00::1]",
        "[fe80::1]",
    ):
        payload = build_runninghub_standard_payload(
            "Keep the verified performance.",
            8,
            "9:16",
            ["https://media.example/board.png"],
            [],
            real_person_mode=False,
        )
        payload["imageUrls"] = [f"https://{host}/board.png"]
        try:
            validate_runninghub_standard_payload(payload, fixed_b=True)
        except PayloadError as error:
            assert "public HTTPS" in str(error)
        else:
            raise AssertionError(f"{host} must not be accepted as public media")


def test_standard_client_posts_payload_without_legacy_wrapper_or_generic_key() -> None:
    calls: list[dict[str, object]] = []

    def request_json(**kwargs: object) -> tuple[int, dict[str, object]]:
        calls.append(dict(kwargs))
        return 200, {"taskId": "task-123"}

    payload = build_runninghub_standard_payload(
        "Keep the verified performance.",
        5,
        "9:16",
        ["https://media.example/board.png"],
        [],
        real_person_mode=False,
    )
    client = RunningHubStandardSeedanceClient(
        "standard-key",
        request_json=request_json,
    )

    assert client.create_video(payload) == "task-123"
    assert calls == [
        {
            "method": "POST",
            "url": "https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video",
            "headers": {
                "Authorization": "Bearer standard-key",
                "Content-Type": "application/json",
            },
            "json_body": payload,
            "timeout": 90,
        }
    ]


def test_missing_task_id_writes_a_redacted_reconciliation_receipt(tmp_path: Path) -> None:
    def request_json(**_: object) -> tuple[int, dict[str, object]]:
        return 200, {
            "code": 400,
            "message": "standard model entitlement is unavailable",
            "requestToken": "do-not-persist",
        }

    payload = build_runninghub_standard_payload(
        "Keep the verified performance.",
        5,
        "9:16",
        ["https://media.example/board.png"],
        [],
        real_person_mode=False,
    )
    client = RunningHubStandardSeedanceClient("standard-key", request_json=request_json)

    with pytest.raises(RunningHubSeedanceError, match="omitted taskId"):
        client.create_video(payload)

    receipt = write_create_reconciliation_receipt(tmp_path, client)
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    assert saved["status"] == "AMBIGUOUS"
    assert saved["response"]["code"] == 400
    assert saved["response"]["message"] == "standard model entitlement is unavailable"
    assert saved["response"]["requestToken"] == "[REDACTED]"


def test_explicit_permission_rejection_is_not_classified_as_ambiguous(tmp_path: Path) -> None:
    def request_json(**_: object) -> tuple[int, dict[str, object]]:
        return 200, {
            "taskId": "",
            "status": "",
            "errorCode": "40311",
            "errorMessage": "Access denied. Please contact the platform to enable permissions.",
            "results": None,
        }

    payload = build_runninghub_standard_payload(
        "Keep the verified performance.",
        5,
        "9:16",
        ["https://media.example/board.png"],
        [],
        real_person_mode=False,
    )
    client = RunningHubStandardSeedanceClient("standard-key", request_json=request_json)

    with pytest.raises(RunningHubSeedanceError, match="40311.*Access denied"):
        client.create_video(payload)

    receipt = write_create_reconciliation_receipt(tmp_path, client)
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    assert saved["status"] == "REJECTED"
    assert saved["error_code"] == "40311"
    assert saved["automatic_paid_retry"] is False


def test_standard_provider_configuration_uses_a_dedicated_enterprise_key() -> None:
    settings = load_settings(
        environ={
            "RUNNINGHUB_API_KEY": "workflow-key",
            "RUNNINGHUB_SEEDANCE_API_KEY": "enterprise-standard-key",
        }
    )

    settings.require_seedance()
    assert settings.seedance_api_provider == "runninghub_standard"
    assert settings.runninghub_seedance_api_key == "enterprise-standard-key"
    preflight = build_redacted_provider_preflight(
        environ={"RUNNINGHUB_SEEDANCE_API_KEY": "enterprise-standard-key"}
    )
    assert preflight["runninghub_seedance_api_key"] == "present"
    assert set(settings.__dataclass_fields__) == {
        "runninghub_api_key",
        "runninghub_base_url",
        "runninghub_seedance_api_key",
        "runninghub_seedance_create_url",
        "runninghub_seedance_query_url",
        "runninghub_seedance_upload_url",
        "seedance_api_provider",
    }
    assert not any("youdao" in key.lower() for key in preflight)


def test_standard_provider_requires_a_dedicated_seedance_key() -> None:
    settings = load_settings(
        environ={
            "RUNNINGHUB_API_KEY": "workflow-key",
            "SEEDANCE_API_PROVIDER": "runninghub_standard",
        }
    )

    with pytest.raises(ConfigurationError, match="RUNNINGHUB_SEEDANCE_API_KEY"):
        settings.require_seedance()
    assert settings.runninghub_seedance_api_key == ""
    preflight = build_redacted_provider_preflight(
        environ={
            "RUNNINGHUB_API_KEY": "workflow-key",
            "SEEDANCE_API_PROVIDER": "runninghub_standard",
        }
    )
    assert preflight["runninghub_seedance_api_key"] == "missing"
    assert preflight["seedance_api_provider"] == "runninghub_standard"


def test_legacy_youdao_provider_label_is_not_silently_migrated() -> None:
    settings = load_settings(
        environ={
            "RUNNINGHUB_API_KEY": "workflow-key",
            "RUNNINGHUB_SEEDANCE_API_KEY": "seedance-key",
            "SEEDANCE_API_PROVIDER": "youdao",
        }
    )

    with pytest.raises(ConfigurationError, match="SEEDANCE_API_PROVIDER"):
        settings.require_seedance()
    assert settings.seedance_api_provider == "youdao"
