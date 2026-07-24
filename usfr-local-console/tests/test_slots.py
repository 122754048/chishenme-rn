from pathlib import Path

import pytest

from app.slots import IntakeError, build_intake, validate_intake


def make_video(tmp_path: Path) -> Path:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"not-a-real-video")
    return video


def test_source_only_without_language_or_optional_slot_is_rejected(tmp_path):
    intake = build_intake(source_video=make_video(tmp_path), output_language=None)

    with pytest.raises(IntakeError, match="MIN_ONE_OPTIONAL_INPUT_REQUIRED"):
        validate_intake(intake, probe_duration=lambda _: 8.0)


def test_language_only_is_admitted_and_routes_absent_slots_deterministically(tmp_path):
    result = validate_intake(
        build_intake(source_video=make_video(tmp_path), output_language="de"),
        probe_duration=lambda _: 8.0,
    )

    assert result.admission["language_only"] is True
    assert result.routes["tail_video"] == "omit_source_end_card"


def test_background_music_extension_is_admitted_without_becoming_fixed_slot(tmp_path):
    music = tmp_path / "song.mp3"
    music.write_bytes(b"music")

    result = validate_intake(
        build_intake(source_video=make_video(tmp_path), background_music=music),
        probe_duration=lambda _: 8.0,
    )

    assert "background_music" not in result.optional_files
    assert result.extension_files["background_music"] == music
    assert result.admission["has_optional_input"] is True
    assert result.admission["language_only"] is False
    assert result.admission["background_music"] is True
    assert result.routes["background_music"] == "seedance_audio_reference"


def test_model_plus_language_is_composite_not_language_only(tmp_path):
    model = tmp_path / "model.png"
    model.write_bytes(b"model")

    result = validate_intake(
        build_intake(source_video=make_video(tmp_path), new_model_image=model, output_language="de"),
        probe_duration=lambda _: 8.0,
    )

    assert result.admission["language_only"] is False
    assert result.routes["semantic"] == "full_replication"


def test_source_duration_above_30_seconds_is_rejected(tmp_path):
    intake = build_intake(source_video=make_video(tmp_path), output_language="de")

    with pytest.raises(IntakeError, match="SOURCE_VIDEO_TOO_LONG"):
        validate_intake(intake, probe_duration=lambda _: 30.01)
