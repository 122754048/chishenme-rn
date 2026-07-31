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

import server.runninghub_standard_contract as standard_contract
import runninghub_seedance_submit as submit

from config import build_redacted_provider_preflight, load_settings  # noqa: E402
from server.runninghub_standard_contract import (  # noqa: E402
    RunningHubStandardPayloadError,
    validate_runninghub_standard_payload_contract,
    validate_video_reference_binding,
)
from runninghub_seedance_submit import (  # noqa: E402
    PayloadError,
    RunningHubStandardSeedanceClient,
    build_runninghub_standard_payload,
    main,
    validate_runninghub_standard_payload,
)


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


def test_submitter_builds_ordered_image_binding_from_role_manifest(tmp_path: Path) -> None:
    model = tmp_path / "model.png"
    board1 = tmp_path / "segment_01_v1_page_1.png"
    board2 = tmp_path / "segment_01_v1_page_2.png"
    model.write_bytes(b"model")
    board1.write_bytes(b"board-one")
    board2.write_bytes(b"board-two")
    paths = [model, board1, board2]
    approval = hashlib.sha256(b"approval").hexdigest()
    manifest = {
        "schema_version": "usfr-image-role-manifest/v1",
        "approval_set_sha256": approval,
        "images": [
            {
                "role": "new_model_identity",
                "artifact_name": model.name,
                "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "cut_ids": ["C01", "C02", "C03"],
                "page": None,
                "approval_set_sha256": None,
                "purpose": "replace model identity only",
            },
            {
                "role": "director_storyboard",
                "artifact_name": board1.name,
                "sha256": hashlib.sha256(board1.read_bytes()).hexdigest(),
                "cut_ids": ["C01", "C02"],
                "page": 1,
                "approval_set_sha256": approval,
                "purpose": "approved director storyboard page 1",
            },
            {
                "role": "director_storyboard",
                "artifact_name": board2.name,
                "sha256": hashlib.sha256(board2.read_bytes()).hexdigest(),
                "cut_ids": ["C03"],
                "page": 2,
                "approval_set_sha256": approval,
                "purpose": "approved director storyboard page 2",
            },
        ],
    }
    path = tmp_path / "image-role-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    urls = [f"https://media.example/{item.name}" for item in paths]
    payload = {
        "prompt": "@Image1 model. @Image2 board page one. @Image3 board page two. @Video1 motion.",
        "imageUrls": urls,
    }

    binding = submit._build_image_reference_binding(
        payload=payload,
        image_urls=urls,
        image_files=paths,
        direct_url_count=0,
        manifest_path=path,
    )

    assert binding["schema_version"] == "usfr-multimodal-reference-binding/v2"
    assert [row["tag"] for row in binding["image_bindings"]] == ["@Image1", "@Image2", "@Image3"]
    assert [row["page"] for row in binding["image_bindings"]] == [None, 1, 2]


def test_cli_rejects_direct_audio_inputs_without_an_orchestrated_segment_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runninghub_seedance_submit.py",
            "--audio-url",
            "https://media.example/full-song.mp3",
            "--output-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2


def test_cli_persists_provider_failure_evidence_when_a_known_task_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed known task remains auditable and is never silently discarded."""

    class Settings:
        runninghub_seedance_api_key = "test-key"
        runninghub_seedance_create_url = "https://provider.example/create"
        runninghub_seedance_query_url = "https://provider.example/query"
        runninghub_seedance_upload_url = "https://provider.example/upload"

        def require_seedance(self) -> None:
            return None

    class FailedClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.last_status_response: dict[str, object] = {}

        def get_status(self, _task_id: str) -> dict[str, object]:
            self.last_status_response = {
                "taskId": "task-failed",
                "status": "FAILED",
                "errorCode": "SY_ERR:10",
                "errorMessage": "provider moderation rejection",
            }
            return self.last_status_response

        def clock(self) -> float:
            return 0.0

        def sleep(self, _seconds: float) -> None:
            raise AssertionError("a failed task must not sleep or retry")

    monkeypatch.setattr(submit, "load_settings", lambda _path: Settings())
    monkeypatch.setattr(submit, "RunningHubStandardSeedanceClient", FailedClient)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runninghub_seedance_submit.py",
            "--resume-task-id",
            "task-failed",
            "--output-dir",
            str(tmp_path),
            "--poll",
        ],
    )

    with pytest.raises(submit.TaskFailedError, match="provider moderation rejection"):
        submit.main()

    evidence = json.loads((tmp_path / "failure.json").read_text(encoding="utf-8"))
    assert evidence["task_id"] == "task-failed"
    assert evidence["provider_status"]["status"] == "FAILED"
    assert evidence["provider_status"]["errorCode"] == "SY_ERR:10"


def test_standard_payload_accepts_one_bound_source_video_reference() -> None:
    payload = build_runninghub_standard_payload(
        "Keep the approved performance and framing.",
        13,
        "9:16",
        ["https://media.example/board.png", "https://media.example/model.jpg"],
        [],
        video_urls=["https://media.example/source-s01.mp4"],
        real_person_mode=True,
    )

    binding = {
        "schema_version": "usfr-video-reference/v1",
        "url": "https://media.example/source-s01.mp4",
        "source_video_sha256": "a" * 64,
        "source_slice_sha256": "b" * 64,
        "segment_id": "S01",
        "segment_plan_sha256": "d" * 64,
        "source_video_reference_artifact_id": "source-reference-artifact",
        "start_ms": 0,
        "end_ms": 11_042,
        "image_reference_binding_sha256": "e" * 64,
        "target_changes": [
            {"kind": "new_model_image", "sha256": "c" * 64},
        ],
    }

    validate_runninghub_standard_payload_contract(payload)
    validate_video_reference_binding(payload, binding)

    with pytest.raises(RunningHubStandardPayloadError, match="distinct bounded slice"):
        validate_video_reference_binding(
            payload, {**binding, "source_slice_sha256": binding["source_video_sha256"]}
        )


def test_final_reference_lineage_rejects_an_internal_control_asset_or_wrong_source_slice() -> None:
    """Only the approved board, source slice, and fixed target images reach Seedance."""

    payload = build_runninghub_standard_payload(
        "@Image1 fixes the approved director board while @Image2 fixes the model identity.",
        4,
        "9:16",
        ["https://media.example/board.png", "https://media.example/model.png"],
        [],
        video_urls=["https://media.example/source-s01.mp4"],
        real_person_mode=True,
    )
    lineage = {
        "schema_version": "seedance-final-reference-lineage/v1",
        "segment_id": "S01",
        "segment_plan_sha256": "a" * 64,
        "ordered_image_urls": list(payload["imageUrls"]),
        "ordered_video_urls": list(payload["videoUrls"]),
        "approved_board": {
            "artifact_id": "storyboard-artifact",
            "object_key": "temporary/job/storyboard.png",
            "kind": "storyboard_image",
            "sha256": "b" * 64,
            "segment_id": "S01",
            "storyboard_revision": 2,
            "storyboard_manifest_sha256": "c" * 64,
            "url": payload["imageUrls"][0],
            "source_video_sha256": "d" * 64,
            "source_keyframe_sheet_sha256": "e" * 64,
            "replacement_control_keyframe_sheet_sha256": "f" * 64,
            "replacement_control_keyframe_receipt_sha256": "0" * 64,
            "replacement_target_sha256s": ["1" * 64],
            "approved_visible_text_locks_sha256": "2" * 64,
        },
        "source_reference": {
            "artifact_id": "source-reference-artifact",
            "object_key": "temporary/job/source-s01.mp4",
            "kind": "source_video_reference",
            "sha256": "3" * 64,
            "source_video_sha256": "d" * 64,
            "segment_id": "S01",
            "segment_plan_sha256": "a" * 64,
            "start_ms": 0,
            "end_ms": 4000,
            "url": payload["videoUrls"][0],
        },
        "allowed_target_changes": [
            {
                "kind": "new_model_image",
                "sha256": "1" * 64,
                "image_slot": 2,
                "url": payload["imageUrls"][1],
            }
        ],
        "forbidden_artifact_kinds": [
            "source_keyframe_sheet",
            "replacement_control_keyframe_sheet",
            "replacement_control_keyframe_receipt",
        ],
    }

    validator = getattr(standard_contract, "validate_final_reference_lineage", None)
    assert callable(validator)
    validator(payload, lineage)

    forged = {
        **lineage,
        "ordered_image_urls": [payload["imageUrls"][0], "https://media.example/replacement-control.png"],
        "allowed_target_changes": [
            {
                "kind": "replacement_control_keyframe_sheet",
                "sha256": "f" * 64,
                "image_slot": 2,
                "url": "https://media.example/replacement-control.png",
            }
        ],
    }
    forged_payload = {**payload, "imageUrls": list(forged["ordered_image_urls"])}
    with pytest.raises(RunningHubStandardPayloadError, match="final reference lineage"):
        validator(forged_payload, forged)


def test_video_reference_binding_requires_the_frozen_plan_and_source_reference_artifact() -> None:
    payload = build_runninghub_standard_payload(
        "@Image1 preserves the approved director board.",
        4,
        "9:16",
        ["https://media.example/board.png", "https://media.example/model.png"],
        [],
        video_urls=["https://media.example/source-s01.mp4"],
        real_person_mode=True,
    )
    incomplete = {
        "schema_version": "usfr-video-reference/v1",
        "url": payload["videoUrls"][0],
        "source_video_sha256": "a" * 64,
        "source_slice_sha256": "b" * 64,
        "segment_id": "S01",
        "start_ms": 0,
        "end_ms": 4000,
        "storyboard_url": payload["imageUrls"][0],
        "target_changes": [{"kind": "new_model_image", "sha256": "c" * 64}],
    }

    with pytest.raises(RunningHubStandardPayloadError, match="complete usfr-video-reference"):
        validate_video_reference_binding(payload, incomplete)


def test_standard_payload_requires_a_complete_immutable_audio_slice_binding() -> None:
    payload = build_runninghub_standard_payload(
        "Use @Audio1 only for this approved music window.",
        4,
        "9:16",
        ["https://media.example/board.png"],
        ["https://media.example/song-s01.wav"],
        real_person_mode=False,
    )
    binding = {
        "schema_version": "usfr-background-music-reference/v1",
        "url": payload["audioUrls"][0],
        "source_audio_sha256": "a" * 64,
        "source_slice_sha256": "b" * 64,
        "segment_id": "S01",
        "start_ms": 0,
        "end_ms": 4000,
        "segment_plan_sha256": "c" * 64,
        "replacement_timing_policy": "source_music_cut_in_out_exact",
        "source_music_windows": [
            {
                "event_id": "M01",
                "source_start_ms": 0,
                "source_end_ms": 4000,
                "segment_start_ms": 0,
                "segment_end_ms": 4000,
                "uploaded_start_ms": 0,
                "uploaded_end_ms": 4000,
            }
        ],
    }

    validator = getattr(standard_contract, "validate_audio_reference_binding", None)
    assert callable(validator)
    validator(payload, binding)

    with pytest.raises(RunningHubStandardPayloadError, match="audio reference binding"):
        validator(payload, {**binding, "url": "https://media.example/full-song.wav"})


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
