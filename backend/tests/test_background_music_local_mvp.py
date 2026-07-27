from __future__ import annotations

from pathlib import Path
import math
import shutil
import subprocess
import sys
import wave

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[2] / "usfr-server"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from app.background_music_local_mvp import DevelopmentOnlyBackgroundMusicMvpHarness  # noqa: E402


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required for the development-only local media MVP",
)


def _write_tone_wave(
    path: Path,
    *,
    seconds: int,
    active_ranges: list[tuple[int, int]],
    frequency: int,
    sample_rate: int = 48_000,
    channels: int = 1,
    sample_width: int = 2,
    frequencies_by_second: list[int] | None = None,
) -> None:
    amplitude = {2: 12_000, 4: 786_432_000}[sample_width]
    samples: list[int] = []
    for index in range(seconds * sample_rate):
        is_active = any(start * sample_rate <= index < end * sample_rate for start, end in active_ranges)
        selected_frequency = frequencies_by_second[min(index // sample_rate, len(frequencies_by_second) - 1)] if frequencies_by_second else frequency
        samples.append(int(amplitude * math.sin(2 * math.pi * selected_frequency * index / sample_rate)) if is_active else 0)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(
            b"".join(
                sample.to_bytes(sample_width, "little", signed=True) * channels
                for sample in samples
            )
        )


def _decode_pcm(path: Path, *, codec: str = "pcm_s16le", sample_format: str = "s16le") -> bytes:
    return subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            codec,
            "-f",
            sample_format,
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout


def _encode_uploaded_audio(source: Path, destination: Path, *, codec: str) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-c:a",
        {"mp3": "libmp3lame", "aac": "aac", "flac": "flac"}[codec],
    ]
    if codec == "aac":
        command.extend(("-f", "adts"))
    command.append(str(destination))
    subprocess.run(command, check=True)


def _make_source_video(tmp_path: Path) -> Path:
    source_audio = tmp_path / "source_audio.wav"
    _write_tone_wave(source_audio, seconds=3, active_ranges=[(0, 1), (2, 3)], frequency=440)
    source_video = tmp_path / "source.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x90:r=30:d=3",
            "-i",
            str(source_audio),
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            str(source_video),
        ],
        check=True,
    )
    return source_video


def test_development_only_local_mvp_archives_routes_and_preserves_source_music_windows(tmp_path: Path):
    source_video = _make_source_video(tmp_path)
    uploaded_song = tmp_path / "uploaded_song.wav"
    _write_tone_wave(
        uploaded_song,
        seconds=2,
        active_ranges=[(0, 2)],
        frequency=220,
        sample_rate=44_100,
        channels=2,
        frequencies_by_second=[220, 880],
    )

    result = DevelopmentOnlyBackgroundMusicMvpHarness(run_root=tmp_path / "mvp-run").run(
        source_video=source_video,
        background_music=uploaded_song,
        visible_singer_regions=[],
    )

    assert result["environment"] == "development-only"
    assert result["route"] == "background_music_replace_sing"
    assert result["language_only"] is False
    assert result["tts_used"] is False
    assert result["console_job"]["route"] == "composite_replication"
    assert result["console_job"]["admission"]["language_only"] is False
    assert Path(result["console_job"]["inputs"]["source_video"]["archive_path"]).is_file()
    assert Path(result["console_job"]["inputs"]["background_music"]["archive_path"]).is_file()
    assert Path(result["intake"]["source_video"]["archive_path"]).is_file()
    assert Path(result["intake"]["background_music"]["archive_path"]).is_file()
    assert result["audio_asset_receipt"]["AssetType"] == "Audio"
    assert result["audio_asset_receipt"]["asset_type"] == "Audio"
    assert result["provider_payload"]["content"] == [
        {"type": "text", "text": result["provider_payload"]["content"][0]["text"]},
        {
            "type": "audio_url",
            "role": "reference_audio",
            "audio_url": {"url": result["audio_asset_receipt"]["asset_uri"]},
        },
    ]
    assert "@Audio1" in result["provider_payload"]["content"][0]["text"]
    assert "reference_audios" not in result["provider_payload"]
    assert result["provider_execution"] == {
        "environment": "development-only",
        "submit_provider_video": {"status": "completed", "output": "local_source_video_passthrough"},
        "wait_provider_video": {"status": "completed", "output": "local_source_video_passthrough"},
    }
    assert result["music_execution_contract"]["mode"] == "background_music_replacement"
    assert result["music_execution_contract"]["lyric_lip_sync_policy"] == "No lyric lip-sync"
    assert result["music_execution_audit_receipt_artifact"]["kind"] == "background_music_audit_receipt"
    assert result["provider_output_artifact"]["kind"] == "background_music_provider_output"
    assert [
        {
            key: window[key]
            for key in (
                "source_start_frame",
                "source_end_frame",
                "output_start_frame",
                "output_end_frame",
                "uploaded_start_ms",
                "uploaded_end_ms",
            )
        }
        for window in result["music_timeline_contract"]["windows"]
    ] == [
        {
            "source_start_frame": 0,
            "source_end_frame": 30,
            "output_start_frame": 0,
            "output_end_frame": 30,
            "uploaded_start_ms": 0,
            "uploaded_end_ms": 1000,
        },
        {
            "source_start_frame": 60,
            "source_end_frame": 90,
            "output_start_frame": 60,
            "output_end_frame": 90,
            "uploaded_start_ms": 1000,
            "uploaded_end_ms": 2000,
        },
    ]
    assert [
        (window["uploaded_start_sample"], window["uploaded_end_sample"])
        for window in result["music_timeline_contract"]["windows"]
    ] == [(0, 44_100), (44_100, 88_200)]
    assert [
        (window["output_start_ms"], window["output_end_ms"])
        for window in result["music_timeline_contract"]["windows"]
    ] == [(0, 1000), (2000, 3000)]
    assert result["music_timeline_contract"]["meaningful_silence_output_intervals"] == [
        {"output_start_ms": 1000, "output_end_ms": 2000}
    ]
    assert result["music_timeline_contract"]["output_duration_ms"] == 3000
    assert all(
        set(window) >= {
            "source_entry",
            "source_exit",
            "fade_in",
            "fade_out",
            "silence_before",
            "silence_after",
            "transition",
        }
        for window in result["music_timeline_contract"]["windows"]
    )
    assert result["music_timeline_contract_artifact"]["sha256"] == result["music_timeline_contract_sha256"]
    assert result["mix_receipt"]["uploaded_audio_sha256"] == result["intake"]["background_music"]["sha256"]
    assert all(
        receipt[flag] is False
        for receipt in result["mix_receipt"]["window_receipts"]
        for flag in ("looped", "time_stretched", "pitch_shifted", "generated_substitute")
    )
    assert all(
        receipt["final_audio_fragment_sha256"] == receipt["fragment_sha256"]
        for receipt in result["mix_receipt"]["window_receipts"]
    )
    assert result["mix_receipt"]["silence_window_receipts"] == [
        {"output_start_frame": 30, "output_end_frame": 60, "all_zero": True}
    ]
    assert Path(result["final_audio_path"]).is_file()
    assert Path(result["final_video_path"]).is_file()
    assert result["mix_receipt"]["uploaded_pcm_format"] == {
        "sample_rate": 44_100,
        "channels": 2,
        "sample_format": "s16le",
    }
    assert result["mix_receipt"]["final_audio_pcm_format"] == result["mix_receipt"]["uploaded_pcm_format"]
    uploaded_pcm = _decode_pcm(uploaded_song)
    final_pcm = _decode_pcm(Path(result["final_audio_path"]))
    assert _decode_pcm(Path(result["final_video_path"])) == final_pcm
    bytes_per_sample = 2 * 2
    assert final_pcm[:44_100 * bytes_per_sample] == uploaded_pcm[:44_100 * bytes_per_sample]
    assert final_pcm[44_100 * bytes_per_sample : 88_200 * bytes_per_sample] == b"\0" * (44_100 * bytes_per_sample)
    assert final_pcm[88_200 * bytes_per_sample : 132_300 * bytes_per_sample] == uploaded_pcm[44_100 * bytes_per_sample : 88_200 * bytes_per_sample]
    assert result["singing_qa"] == {
        "status": "skipped",
        "reason": "no_lyric_lip_sync",
        "regions": [],
    }


def test_development_only_local_mvp_binds_visible_singer_alignment_and_lip_sync_to_final_mix(tmp_path: Path):
    source_video = _make_source_video(tmp_path)
    uploaded_song = tmp_path / "uploaded_song.wav"
    _write_tone_wave(uploaded_song, seconds=2, active_ranges=[(0, 2)], frequency=220)

    result = DevelopmentOnlyBackgroundMusicMvpHarness(run_root=tmp_path / "mvp-run").run(
        source_video=source_video,
        background_music=uploaded_song,
        visible_singer_regions=[
            {
                "region_id": "歌手-01",
                "visible": True,
                "lyrics": "la la",
                "source_start_frame": 0,
                "source_end_frame": 30,
            }
        ],
    )

    assert result["singing_qa"]["status"] == "passed"
    assert result["singing_qa"]["mode"] == "development-only"
    assert result["music_execution_contract"]["mode"] == "verified_singing"
    assert result["music_execution_contract"]["uploaded_audio_route"] == {
        "contract": "uploaded-audio-route/v1",
        "mode": "pending_uploaded_lyrics",
        "reason": "confirmed_source_music_video_performance",
        "eligible_source_windows": [
            {
                "line_id": "local-singing-1",
                "speaker_id": "CHARACTER_1",
                "start_ms": 0,
                "end_ms": 1000,
                "source_line_evidence_sha256": result["music_execution_contract"]["performance_line_contract"]["cuts"][0]["speaker_assignment"]["evidence_sha256"],
            }
        ],
        "max_uploaded_lyric_transcriptions": 1,
    }
    assert result["music_execution_contract"]["performance_line_contract_sha256"] is not None
    region = result["singing_qa"]["regions"][0]
    assert region["lyrics_phoneme_alignment"]["passed"] is True
    assert region["lyrics_phoneme_alignment"]["lyrics"] == "la la"
    assert region["lyrics_phoneme_alignment"]["phonemes"] == ["L", "A", "L", "A"]
    assert region["lyrics_phoneme_alignment"]["final_video_sha256"] == result["final_video_sha256"]
    assert region["lip_sync_qa"]["passed"] is True
    assert region["lip_sync_qa"]["final_video_sha256"] == result["final_video_sha256"]
    assert result["music_timeline_contract_artifact"]["sha256"] == result["music_timeline_contract_sha256"]
    assert result["mix_receipt"]["final_video_sha256"] == result["final_video_sha256"]
    assert result["mix_receipt"]["singing_receipts"] == [
        {
            "region_id": "歌手-01",
            "alignment_receipt_sha256": region["lyrics_phoneme_alignment"]["receipt_sha256"],
            "lip_sync_receipt_sha256": region["lip_sync_qa"]["receipt_sha256"],
        }
    ]


def test_development_only_local_mvp_preserves_32_bit_pcm_fragment_format(tmp_path: Path):
    source_video = _make_source_video(tmp_path)
    uploaded_song = tmp_path / "uploaded_song_32bit.wav"
    _write_tone_wave(
        uploaded_song,
        seconds=2,
        active_ranges=[(0, 2)],
        frequency=220,
        sample_rate=44_100,
        channels=2,
        sample_width=4,
        frequencies_by_second=[220, 880],
    )

    result = DevelopmentOnlyBackgroundMusicMvpHarness(run_root=tmp_path / "mvp-run").run(
        source_video=source_video,
        background_music=uploaded_song,
        visible_singer_regions=[],
    )

    assert result["mix_receipt"]["uploaded_pcm_format"] == {
        "sample_rate": 44_100,
        "channels": 2,
        "sample_format": "s32le",
    }
    assert result["mix_receipt"]["final_audio_pcm_format"] == result["mix_receipt"]["uploaded_pcm_format"]
    uploaded_pcm = _decode_pcm(uploaded_song, codec="pcm_s32le", sample_format="s32le")
    final_pcm = _decode_pcm(Path(result["final_audio_path"]), codec="pcm_s32le", sample_format="s32le")
    video_pcm = _decode_pcm(Path(result["final_video_path"]), codec="pcm_s32le", sample_format="s32le")
    bytes_per_sample = 2 * 4
    assert video_pcm == final_pcm
    assert final_pcm[:44_100 * bytes_per_sample] == uploaded_pcm[:44_100 * bytes_per_sample]
    assert final_pcm[88_200 * bytes_per_sample : 132_300 * bytes_per_sample] == uploaded_pcm[44_100 * bytes_per_sample : 88_200 * bytes_per_sample]


@pytest.mark.parametrize("codec", ["mp3", "aac", "flac"])
def test_development_only_local_mvp_validates_compressed_upload_fragments_as_decoded_pcm(
    tmp_path: Path, codec: str
):
    source_video = _make_source_video(tmp_path)
    uncompressed_song = tmp_path / "song_source.wav"
    uploaded_song = tmp_path / f"uploaded_song.{codec}"
    _write_tone_wave(
        uncompressed_song,
        seconds=2,
        active_ranges=[(0, 2)],
        frequency=220,
        sample_rate=44_100,
        channels=2,
        frequencies_by_second=[220, 880],
    )
    _encode_uploaded_audio(uncompressed_song, uploaded_song, codec=codec)

    result = DevelopmentOnlyBackgroundMusicMvpHarness(run_root=tmp_path / "mvp-run").run(
        source_video=source_video,
        background_music=uploaded_song,
        visible_singer_regions=[],
    )

    uploaded_pcm = _decode_pcm(uploaded_song)
    final_pcm = _decode_pcm(Path(result["final_audio_path"]))
    assert _decode_pcm(Path(result["final_video_path"])) == final_pcm
    assert all(
        "uploaded_byte_offset" not in receipt
        and "final_audio_byte_offset" not in receipt
        and receipt["fragment_sha256"] == receipt["pcm_fragment_sha256"]
        for receipt in result["mix_receipt"]["window_receipts"]
    )
    bytes_per_frame = 2 * 2
    assert final_pcm[:44_100 * bytes_per_frame] == uploaded_pcm[:44_100 * bytes_per_frame]
    assert final_pcm[88_200 * bytes_per_frame : 132_300 * bytes_per_frame] == uploaded_pcm[
        44_100 * bytes_per_frame : 88_200 * bytes_per_frame
    ]
