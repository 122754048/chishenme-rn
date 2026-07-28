import pytest

from app.audio_routes import (
    AudioRouteError,
    build_audio_route,
    build_background_music_route,
    validate_background_music_delivery,
)


def test_language_only_uses_audio1_but_composite_localization_does_not_take_full_video_fast_lane():
    language_only = build_audio_route(
        execution_map={"run_mode": "language_only", "regions": []},
        output_language="de",
        opaque_policies={},
    )
    composite = build_audio_route(
        execution_map={
            "run_mode": "composite_replication",
            "regions": [{"region_id": "c01", "media_origin": "generated"}],
        },
        output_language="de",
        opaque_policies={},
    )

    assert language_only["mode"] == "language_only_audio1"
    assert composite["mode"] == "composite_localization"


def test_opaque_localized_video_requires_explicit_audio_policy():
    execution_map = {
        "run_mode": "composite_replication",
        "regions": [{"region_id": "ui01", "media_origin": "opaque_ui"}],
    }

    with pytest.raises(AudioRouteError, match="AUDIO_LAYER_POLICY_REQUIRED"):
        build_audio_route(execution_map=execution_map, output_language="ja", opaque_policies={})

    route = build_audio_route(
        execution_map=execution_map,
        output_language="ja",
        opaque_policies={"ui01": "opaque_audio_mute_with_localized_voiceover"},
    )
    assert route["regions"][0]["audio_owner"] == "localized_voiceover_mix"


def test_background_music_contract_preserves_source_frames_and_exact_uploaded_audio():
    route = build_background_music_route(
        source_music_timeline={
            "windows": [
                {
                    "source_start_frame": 12,
                    "source_end_frame": 42,
                    "output_start_frame": 12,
                    "output_end_frame": 42,
                    "duration_ms": 3000,
                }
            ]
        },
        uploaded_audio={"sha256": "a" * 64, "duration_ms": 6000, "start_offset_ms": 0},
        visible_singer_regions=[],
    )

    assert route["provider_route"] == "runninghub_standard_audio_urls"
    assert route["provider_upload"] == "runninghub_binary_media_upload"
    assert route["provider_request_field"] == "audioUrls"
    assert route["prompt_reference_tag"] == "@Audio1"
    assert route["final_audio_source"] == "uploaded_exact_audio"
    assert route["windows"][0]["uploaded_start_ms"] == 0
    assert route["windows"][0]["uploaded_end_ms"] == 3000
    assert route["singing_qa"]["status"] == "skipped"


def test_background_music_rejects_timeline_drift_and_insufficient_song_duration():
    with pytest.raises(AudioRouteError, match="BACKGROUND_MUSIC_TIMELINE_MISMATCH"):
        build_background_music_route(
            source_music_timeline={
                "windows": [
                    {
                        "source_start_frame": 12,
                        "source_end_frame": 42,
                        "output_start_frame": 13,
                        "output_end_frame": 42,
                        "duration_ms": 3000,
                    }
                ]
            },
            uploaded_audio={"sha256": "a" * 64, "duration_ms": 6000},
            visible_singer_regions=[],
        )


def test_background_music_rejects_invalid_uploaded_sha_and_non_monotonic_source_windows():
    valid_window = {
        "source_start_frame": 12,
        "source_end_frame": 42,
        "output_start_frame": 12,
        "output_end_frame": 42,
        "duration_ms": 3000,
    }
    with pytest.raises(AudioRouteError, match="BACKGROUND_MUSIC_INPUT_INVALID"):
        build_background_music_route(
            source_music_timeline={"windows": [valid_window]},
            uploaded_audio={"sha256": "z" * 64, "duration_ms": 6000},
            visible_singer_regions=[],
        )
    with pytest.raises(AudioRouteError, match="MUSIC_TIMELINE_CONTRACT_INVALID"):
        build_background_music_route(
            source_music_timeline={
                "windows": [
                    valid_window,
                    {
                        "source_start_frame": 30,
                        "source_end_frame": 60,
                        "output_start_frame": 30,
                        "output_end_frame": 60,
                        "duration_ms": 3000,
                    },
                ]
            },
            uploaded_audio={"sha256": "a" * 64, "duration_ms": 6000},
            visible_singer_regions=[],
        )
    with pytest.raises(AudioRouteError, match="BACKGROUND_MUSIC_DURATION_INSUFFICIENT"):
        build_background_music_route(
            source_music_timeline={
                "windows": [
                    {
                        "source_start_frame": 12,
                        "source_end_frame": 42,
                        "output_start_frame": 12,
                        "output_end_frame": 42,
                        "duration_ms": 3000,
                    }
                ]
            },
            uploaded_audio={"sha256": "a" * 64, "duration_ms": 2999},
            visible_singer_regions=[],
        )


def test_visible_singer_requires_alignment_and_lip_sync_qa_receipts():
    source_timeline = {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "duration_ms": 3000,
            }
        ]
    }
    with pytest.raises(AudioRouteError, match="SINGING_ALIGNMENT_REQUIRED"):
        build_background_music_route(
            source_music_timeline=source_timeline,
            uploaded_audio={"sha256": "a" * 64, "duration_ms": 3000},
            visible_singer_regions=[{"region_id": "c01", "visible": True}],
        )

    route = build_background_music_route(
        source_music_timeline=source_timeline,
        uploaded_audio={"sha256": "a" * 64, "duration_ms": 3000},
        visible_singer_regions=[
            {
                "region_id": "c01",
                "visible": True,
                "lyrics_phoneme_alignment": {"passed": True, "receipt_sha256": "b" * 64},
                "lip_sync_qa": {"passed": True, "receipt_sha256": "c" * 64},
            }
        ],
    )
    assert route["singing_qa"]["status"] == "required"


def test_visible_singer_rejects_non_digest_alignment_and_lip_sync_receipts():
    source_timeline = {
        "windows": [
            {
                "source_start_frame": 0,
                "source_end_frame": 30,
                "output_start_frame": 0,
                "output_end_frame": 30,
                "duration_ms": 3000,
            }
        ]
    }
    with pytest.raises(AudioRouteError, match="SINGING_ALIGNMENT_REQUIRED"):
        build_background_music_route(
            source_music_timeline=source_timeline,
            uploaded_audio={"sha256": "a" * 64, "duration_ms": 3000},
            visible_singer_regions=[
                {
                    "region_id": "c01",
                    "visible": True,
                    "lyrics_phoneme_alignment": {"passed": True, "receipt_sha256": "not-a-digest"},
                    "lip_sync_qa": {"passed": True, "receipt_sha256": "c" * 64},
                }
            ],
        )


def test_final_mix_receipt_binds_exact_uploaded_music_fragments_to_final_audio():
    route = build_background_music_route(
        source_music_timeline={
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
        uploaded_audio={"sha256": "a" * 64, "duration_ms": 3000},
        visible_singer_regions=[],
    )

    validate_background_music_delivery(
        route=route,
        final_audio_sha256="d" * 64,
        mix_receipt={
            "passed": True,
            "final_audio_sha256": "d" * 64,
            "uploaded_audio_sha256": "a" * 64,
            "window_receipts": [
                {
                    "source_start_frame": 0,
                    "source_end_frame": 30,
                    "output_start_frame": 0,
                    "output_end_frame": 30,
                    "uploaded_start_ms": 0,
                    "uploaded_end_ms": 3000,
                    "fragment_sha256": "e" * 64,
                    "looped": False,
                    "time_stretched": False,
                    "pitch_shifted": False,
                    "generated_substitute": False,
                }
            ],
        },
    )
