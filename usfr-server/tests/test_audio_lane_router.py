from __future__ import annotations

import pytest

from server.audio_lane_router import (
    ROUTE_H3_LANGUAGE_EDIT,
    ROUTE_H3_MV_EDIT,
    ROUTE_GENERATED_DIALOGUE,
    ROUTE_SONG_LIP_SYNC,
    ROUTE_VOICEOVER_TTS,
    AudioLaneRouteError,
    route_audio_line,
    validate_lip_sync_workflow,
)


def test_normal_on_camera_spoken_person_uses_seedance_generation_prompt() -> None:
    route = route_audio_line(
        content_type="spoken",
        visibility="on_camera",
        operation_mode="normal_replication",
    )

    # Language-only no longer has a separate TTS + non-song lip-sync lane:
    # Seedance 2.0 rewrites the spoken line into the target language directly
    # from the edit prompt, exactly like normal replication.
    assert route["replacement_route"] == ROUTE_GENERATED_DIALOGUE
    assert route["external_lip_sync"] is False


def test_language_change_uses_h3_for_on_camera_speech() -> None:
    route = route_audio_line(
        content_type="spoken", visibility="on_camera", operation_mode="language_only"
    )
    assert route["replacement_route"] == ROUTE_H3_LANGUAGE_EDIT
    assert route["provider_owner"] == "h3"
    assert route["external_lip_sync"] is False
    assert route["tts_required"] is False


def test_language_only_spoken_never_requests_an_external_lip_sync_workflow() -> None:
    route = route_audio_line(
        content_type="spoken",
        visibility="on_camera",
        operation_mode="language_only",
    )

    with pytest.raises(AudioLaneRouteError, match="EXTERNAL_LIP_SYNC_FORBIDDEN"):
        validate_lip_sync_workflow(route=route, workflow_id="2080140197518823426")


@pytest.mark.parametrize("operation_mode", ["normal_replication", "language_only"])
def test_voiceover_uses_reference_tts_and_never_uses_a_lip_sync_workflow(operation_mode: str) -> None:
    route = route_audio_line(
        content_type="spoken",
        visibility="voiceover",
        operation_mode=operation_mode,
    )

    assert route["replacement_route"] == ROUTE_VOICEOVER_TTS
    assert route["tts_required"] is True
    assert route["voice_reference_required"] is True
    assert route["external_lip_sync"] is False
    with pytest.raises(AudioLaneRouteError, match="VOICEOVER_LIP_SYNC_FORBIDDEN"):
        validate_lip_sync_workflow(route=route, workflow_id="2080140197518823426")


def test_song_is_the_only_permitted_external_lip_sync_workflow() -> None:
    song = route_audio_line(
        content_type="sung",
        visibility="on_camera",
        operation_mode="normal_replication",
    )

    assert song["replacement_route"] == ROUTE_H3_MV_EDIT
    assert song["provider_owner"] == "h3"
    with pytest.raises(AudioLaneRouteError, match="EXTERNAL_LIP_SYNC_FORBIDDEN"):
        validate_lip_sync_workflow(route=song, workflow_id="2082759080288296961")
