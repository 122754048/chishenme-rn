from __future__ import annotations

from array import array
from contextlib import ExitStack, contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import wave

import server.timeline_renderer as timeline_renderer
from server.timeline_renderer import (
    BundledTimelineRenderer,
    TimelineRendererError,
    _frozen_binding_order,
    _timeline_module,
)


def _make_clip(
    path: Path,
    *,
    color: str,
    duration: float,
    frequency: int = 440,
    include_audio: bool = True,
    audio_volume: float = 1.0,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=320x568:r=30",
    ]
    if include_audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000",
            ]
        )
    command.extend(
        [
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if include_audio:
        if audio_volume != 1.0:
            command.extend(["-af", f"volume={audio_volume}"])
        command.extend(["-c:a", "aac", "-ar", "48000", "-ac", "2"])
    else:
        command.append("-an")
    command.append(str(path))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)


class _Context:
    allow_local_paths = True
    timeline_regions: tuple[dict, ...]
    work_dir: Path


class _Materialized:
    def __init__(self, path: Path):
        self.path = path


class _ProductionContext(_Context):
    allow_local_paths = False

    def __init__(self, work_dir: Path, media: Path):
        self.work_dir = work_dir
        self.media = media

    @contextmanager
    def materialize_slot(self, slot_id: str):
        self.assert_slot_id = slot_id
        yield _Materialized(self.media)


class _ArtifactProductionContext(_Context):
    allow_local_paths = False

    def __init__(self, work_dir: Path, media: Path):
        self.work_dir = work_dir
        self.media = media
        self.artifact_kind = None
        self.artifact_kwargs = {}
        self.artifacts = ()

    @contextmanager
    def materialize_artifact(self, kind: str, **kwargs):
        self.artifact_kind = kind
        self.artifact_kwargs = dict(kwargs)
        yield _Materialized(self.media)


class _PreboundMixArtifactContext(_Context):
    allow_local_paths = True

    def __init__(
        self,
        root: Path,
        mixed_media: Path,
        source_media: Path | None = None,
    ):
        self.work_dir = root / "work"
        self.work_dir.mkdir(exist_ok=True)
        self.mixed_media = mixed_media
        self.source_media = source_media
        self.mixed_sha256 = hashlib.sha256(mixed_media.read_bytes()).hexdigest()
        self.artifacts = (
            {
                "kind": "evidence_bound_mixed_region",
                "artifact_id": "prebound-mixed-region",
                "sha256": self.mixed_sha256,
            },
        )

    @contextmanager
    def materialize_artifact(self, kind: str, **kwargs):
        if (
            kind != "evidence_bound_mixed_region"
            or kwargs.get("artifact_id") != "prebound-mixed-region"
            or kwargs.get("sha256") != self.mixed_sha256
        ):
            raise AssertionError((kind, kwargs))
        yield _Materialized(self.mixed_media)

    @contextmanager
    def materialize_slot(self, slot_id: str, *, index: int = 0):
        if slot_id != "source_video" or index != 0 or self.source_media is None:
            raise AssertionError((slot_id, index))
        yield _Materialized(self.source_media)


class _SegmentArtifactProductionContext(_Context):
    allow_local_paths = False
    expect_audio = True

    def __init__(self, work_dir: Path, media_by_artifact_id: dict[str, Path]):
        self.work_dir = work_dir
        self.media_by_artifact_id = media_by_artifact_id
        self.artifact_calls: list[tuple[str, dict[str, str]]] = []
        self.artifacts = tuple(
            {
                "kind": "provider_video",
                "artifact_id": artifact_id,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for artifact_id, path in media_by_artifact_id.items()
        )

    @contextmanager
    def materialize_artifact(self, kind: str, **kwargs):
        artifact_id = str(kwargs.get("artifact_id") or "")
        self.artifact_calls.append((kind, dict(kwargs)))
        yield _Materialized(self.media_by_artifact_id[artifact_id])


class BundledTimelineRendererTest(unittest.TestCase):
    def test_bundled_renderer_exposes_prebound_and_deferred_verification_media(self):
        from server.audio_mixer import EvidenceBoundAudioMixer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            prebound_opaque = root / "prebound-opaque.mp4"
            deferred_opaque = root / "deferred-opaque.mp4"
            prebound_mixed = root / "prebound-mixed.mp4"
            output = root / "timeline.mp4"
            _make_clip(source, color="blue", duration=2.0, frequency=1000)
            _make_clip(
                prebound_opaque,
                color="green",
                duration=1.0,
                frequency=440,
            )
            _make_clip(
                deferred_opaque,
                color="red",
                duration=1.0,
                frequency=660,
            )
            module = _timeline_module()
            prebound_active = module.detect_active_window(
                prebound_opaque,
                duration=1.0,
                fps=30.0,
            )
            prebound_mixer = EvidenceBoundAudioMixer(
                implementation="tests:PreboundEvidenceBoundAudioMixer",
                version="0.9.0",
            )
            deferred_mixer = EvidenceBoundAudioMixer()
            prebound_receipt = prebound_mixer.mix_region(
                source_media=source,
                opaque_media=prebound_opaque,
                output_path=prebound_mixed,
                region_id="prebound-ui",
                source_start_us=0,
                source_end_us=1_000_000,
                speech_windows=[
                    {"event_id": "A1", "start_us": 200_000, "end_us": 600_000}
                ],
                mix_policy={"duck_gain_db": -12.0},
                active_window=prebound_active,
                source_media_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                opaque_media_sha256=hashlib.sha256(
                    prebound_opaque.read_bytes()
                ).hexdigest(),
            )
            prebound_receipt["final_output_sha256"] = "f" * 64
            context = _PreboundMixArtifactContext(root, prebound_mixed)
            context.expect_audio = True
            context.source_media_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            context.audio_mix_verification_dir = root / "verification"
            context.timeline_regions = (
                {
                    "region_id": "prebound-ui",
                    "region_type": "opaque_ui_demo",
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "audio_policy": "evidence_bound_mix",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_path": str(prebound_opaque),
                    "transition_shell": {"exit": {"type": "hard_cut"}},
                    "media_sha256": hashlib.sha256(
                        prebound_opaque.read_bytes()
                    ).hexdigest(),
                    "mixer_receipt": prebound_receipt,
                },
                {
                    "region_id": "deferred-tail",
                    "region_type": "excluded_app_end_card",
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "audio_policy": "evidence_bound_mix",
                    "source_start_us": 1_000_000,
                    "source_end_us": 2_000_000,
                    "media_path": str(deferred_opaque),
                    "transition_shell": {"entry": {"type": "hard_cut"}},
                    "media_sha256": hashlib.sha256(
                        deferred_opaque.read_bytes()
                    ).hexdigest(),
                },
            )
            context.audio_route_guard = {
                "regions": [
                    {
                        "region_id": "prebound-ui",
                        "audio_policy": "evidence_bound_mix",
                        "mixer_receipt_status": "verified_prebound_receipt",
                        "speech_windows": [
                            {
                                "event_id": "A1",
                                "start_us": 200_000,
                                "end_us": 600_000,
                            }
                        ],
                    },
                    {
                        "region_id": "deferred-tail",
                        "audio_policy": "evidence_bound_mix",
                        "mixer_receipt_status": "pending_renderer_receipt",
                        "speech_windows": [
                            {
                                "event_id": "A2",
                                "start_us": 1_200_000,
                                "end_us": 1_600_000,
                            }
                        ],
                    },
                ]
            }

            result = BundledTimelineRenderer(audio_mixer=deferred_mixer).render(
                source,
                output,
                context,
            )

            verification_rows = result["audio_mixer_verification_media"]
            self.assertEqual(
                [item["region_id"] for item in verification_rows],
                ["prebound-ui", "deferred-tail"],
            )
            prebound_verification = verification_rows[0]
            self.assertEqual(
                hashlib.sha256(
                    Path(prebound_verification["opaque_media_path"]).read_bytes()
                ).hexdigest(),
                prebound_receipt["opaque_media_sha256"],
            )
            self.assertEqual(
                hashlib.sha256(
                    Path(prebound_verification["mixed_region_path"]).read_bytes()
                ).hexdigest(),
                prebound_receipt["mixed_region_sha256"],
            )
            placements = {
                item["region_id"]: item
                for item in result["timeline_manifest"]["placements"]
            }
            self.assertEqual(
                placements["prebound-ui"]["carrier_receipts"][0][
                    "carrier_sha256"
                ],
                prebound_receipt["mixed_region_sha256"],
            )

            from server.real_capabilities import FfmpegCompositor

            prebound_receipt["final_output_sha256"] = hashlib.sha256(
                output.read_bytes()
            ).hexdigest()
            publication_context = _PreboundMixArtifactContext(
                root,
                prebound_mixed,
                source,
            )
            publication_context.profile_snapshot = {
                "profile": "high_fidelity_hybrid_v1",
                "activation_mode": "active",
            }
            publication_context.audio_contract = {
                "schema_version": "audio-contract/v1",
                "segments": [
                    {"segment_id": "A1", "start_ms": 200, "end_ms": 600},
                    {"segment_id": "A2", "start_ms": 1200, "end_ms": 1600},
                ],
            }
            publication_context.timeline_regions = context.timeline_regions
            composed = FfmpegCompositor(
                renderer=BundledTimelineRenderer(audio_mixer=deferred_mixer)
            ).compose(context=publication_context, input_artifacts=[])
            published_receipts = composed["timeline_manifest"][
                "audio_mixer_receipts"
            ]
            self.assertEqual(
                [item["region_id"] for item in published_receipts],
                ["prebound-ui", "deferred-tail"],
            )
            self.assertEqual(
                composed["timeline_manifest"]["audio_route_guard"]["status"],
                "passed_final_bound_evidence_bound_mix",
            )

    def test_evidence_bound_audio_mixer_creates_playable_region_and_receipt(self):
        from server.audio_mixer import (
            AudioMixerError,
            EvidenceBoundAudioMixer,
            validate_evidence_bound_mix_receipt_media,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            opaque = root / "opaque.mp4"
            output = root / "mixed.mp4"
            _make_clip(source, color="blue", duration=1.0, frequency=1000)
            _make_clip(opaque, color="green", duration=1.0, frequency=440)
            active_window = _timeline_module().detect_active_window(
                opaque,
                duration=1.0,
                fps=30.0,
            )

            receipt = EvidenceBoundAudioMixer().mix_region(
                source_media=source,
                opaque_media=opaque,
                output_path=output,
                region_id="opaque-ui",
                source_start_us=0,
                source_end_us=1_000_000,
                speech_windows=[
                    {"event_id": "A1", "start_us": 200_000, "end_us": 600_000}
                ],
                mix_policy={"duck_gain_db": -12.0, "fade_in_ms": 20, "fade_out_ms": 20},
                active_window=active_window,
                source_media_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                opaque_media_sha256=hashlib.sha256(opaque.read_bytes()).hexdigest(),
            )

            self.assertTrue(output.is_file())
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,start_time:format=duration",
                    "-of",
                    "json",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            probe_payload = json.loads(probe.stdout)
            stream_types = {
                item["codec_type"] for item in probe_payload["streams"]
            }
            self.assertEqual(stream_types, {"audio", "video"})
            self.assertTrue(
                all(
                    abs(float(item.get("start_time") or 0.0)) <= 0.001
                    for item in probe_payload["streams"]
                ),
                probe_payload,
            )
            self.assertAlmostEqual(
                float(probe_payload["format"]["duration"]),
                1.0,
                delta=0.05,
            )
            self.assertEqual(receipt["schema_version"], "evidence-bound-audio-mix/v1")
            self.assertEqual(receipt["region_id"], "opaque-ui")
            self.assertEqual(receipt["sample_rate"], 48000)
            self.assertEqual(receipt["channels"], 2)
            self.assertNotEqual(receipt["output_wav_sha256"], receipt["source_wav_sha256"])
            self.assertNotEqual(receipt["output_wav_sha256"], receipt["opaque_wav_sha256"])
            self.assertEqual(receipt["duck_curve"][1]["gain_db"], -12.0)
            self.assertEqual(receipt["speech_windows"][0]["event_id"], "A1")
            self.assertEqual(
                receipt["mixed_region_sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )
            decoded = root / "mixed-mono.wav"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(output),
                    "-vn", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(decoded),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            with wave.open(str(decoded), "rb") as handle:
                samples = array("h", handle.readframes(handle.getnframes()))
            window_size = 1_200
            def tone_amplitudes(frequency: int) -> list[float]:
                result = []
                for offset in range(0, len(samples) - window_size + 1, window_size):
                    chunk = samples[offset : offset + window_size]
                    real = sum(
                        value
                        * math.cos(2 * math.pi * frequency * index / 48_000)
                        for index, value in enumerate(chunk, start=offset)
                    )
                    imaginary = sum(
                        value
                        * math.sin(2 * math.pi * frequency * index / 48_000)
                        for index, value in enumerate(chunk, start=offset)
                    )
                    result.append(math.hypot(real, imaginary) / window_size)
                return result

            speech_amplitudes = tone_amplitudes(1000)
            threshold = max(speech_amplitudes) * 0.6
            active_windows = [
                index for index, amplitude in enumerate(speech_amplitudes)
                if amplitude >= threshold
            ]
            self.assertAlmostEqual(
                active_windows[0] * 0.025,
                0.2,
                delta=0.025,
                msg=f"{probe_payload} {[round(item, 1) for item in speech_amplitudes]}",
            )
            self.assertAlmostEqual((active_windows[-1] + 1) * 0.025, 0.6, delta=0.025)

            opaque_amplitudes = tone_amplitudes(440)
            outside_level = sum(
                opaque_amplitudes[index] for index in (*range(2, 7), *range(28, 35))
            ) / 12
            first_inside_db = 20 * math.log10(opaque_amplitudes[8] / outside_level)
            inside_level = sum(opaque_amplitudes[9:20]) / 11
            inside_db = 20 * math.log10(inside_level / outside_level)
            self.assertAlmostEqual(first_inside_db, -12.0, delta=1.5)
            self.assertAlmostEqual(inside_db, -12.0, delta=1.5)

            peak_probe = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostats", "-i", str(output),
                    "-filter_complex", "ebur128=peak=true", "-f", "null", "-",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            peak_matches = re.findall(
                r"Peak:\s+(-?\d+(?:\.\d+)?) dBFS",
                peak_probe.stderr,
            )
            self.assertTrue(peak_matches, peak_probe.stderr)
            self.assertLessEqual(float(peak_matches[-1]), -0.1)

            forged = json.loads(json.dumps(receipt))
            forged["source_wav_sha256"] = "1" * 64
            forged["opaque_wav_sha256"] = "2" * 64
            forged["output_wav_sha256"] = "3" * 64
            request = {
                "schema_version": forged["schema_version"],
                "region_id": forged["region_id"],
                "source_media_sha256": forged["source_media_sha256"],
                "opaque_media_sha256": forged["opaque_media_sha256"],
                "source_wav_sha256": forged["source_wav_sha256"],
                "opaque_wav_sha256": forged["opaque_wav_sha256"],
                "source_start_us": forged["source_start_us"],
                "source_end_us": forged["source_end_us"],
                "target_active_duration_us": forged["target_active_duration_us"],
                "speech_windows": forged["speech_windows"],
                "mix_policy": forged["mix_policy"],
            }
            forged["request_sha256"] = hashlib.sha256(
                json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            with self.assertRaisesRegex(AudioMixerError, "decoded PCM SHA-256"):
                validate_evidence_bound_mix_receipt_media(
                    receipt=forged,
                    source_media=source,
                    opaque_media=opaque,
                    mixed_media=output,
                    active_window=active_window,
                    region_id="opaque-ui",
                    source_start_us=0,
                    source_end_us=1_000_000,
                    frozen_speech_windows=[
                        {"event_id": "A1", "start_us": 200_000, "end_us": 600_000}
                    ],
                    mix_policy={
                        "duck_gain_db": -12.0,
                        "fade_in_ms": 20,
                        "fade_out_ms": 20,
                    },
                )

    def test_source_audio_performance_assembler_resumes_g02_at_global_source_position(self):
        from server.audio_mixer import SourceAudioPerformanceAssembler

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            g01 = root / "g01.mp4"
            ui = root / "ui.mp4"
            g02 = root / "g02.mp4"
            tail = root / "tail.mp4"
            output = root / "output.mp4"
            _make_clip(g01, color="blue", duration=1.0, frequency=200)
            _make_clip(ui, color="green", duration=0.6, frequency=440)
            _make_clip(g02, color="purple", duration=1.0, frequency=200)
            _make_clip(tail, color="orange", duration=0.4, frequency=600)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x240:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=900:sample_rate=48000:duration=1",
                    "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(source),
                ],
                check=True,
                capture_output=True,
            )

            receipt = SourceAudioPerformanceAssembler().assemble(
                source_media=source,
                output_path=output,
                source_media_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                regions=[
                    {"region_id": "G01", "media": g01, "audio_mode": "source_master", "source_start_us": 0, "source_end_us": 1_000_000},
                    {"region_id": "U01", "media": ui, "audio_mode": "opaque_audio_keep"},
                    {"region_id": "G02", "media": g02, "audio_mode": "source_master", "source_start_us": 2_000_000, "source_end_us": 3_000_000},
                    {"region_id": "E01", "media": tail, "audio_mode": "opaque_audio_keep"},
                ],
            )

            self.assertTrue(output.is_file())
            self.assertEqual(receipt["regions"][2]["source_start_us"], 2_000_000)
            self.assertEqual(receipt["regions"][2]["audio_mode"], "source_master")
            self.assertEqual(receipt["regions"][1]["audio_mode"], "opaque_audio_keep")
            self.assertEqual(receipt["forbidden_operations"], ["atempo", "loop", "stretch", "freeze", "black_padding", "audio_padding"])
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(output)],
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertAlmostEqual(float(probe.stdout.strip()), 3.0, delta=0.08)
            g02_wav = root / "g02.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.7", "-t", "0.4", "-i", str(output), "-vn", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(g02_wav)],
                check=True,
                capture_output=True,
            )
            with wave.open(str(g02_wav), "rb") as handle:
                samples = array("h", handle.readframes(handle.getnframes()))
            def amplitude(frequency: int) -> float:
                real = sum(value * math.cos(2 * math.pi * frequency * index / 48_000) for index, value in enumerate(samples))
                imaginary = sum(value * math.sin(2 * math.pi * frequency * index / 48_000) for index, value in enumerate(samples))
                return math.hypot(real, imaginary) / len(samples)
            self.assertGreater(amplitude(900), amplitude(300) * 8)

    def test_source_audio_performance_remux_preserves_visual_timeline_and_opaque_audio(self):
        from server.audio_mixer import SourceAudioPerformanceAssembler

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            rendered = root / "rendered.mp4"
            ui = root / "ui.mp4"
            output = root / "output.mp4"
            _make_clip(rendered, color="purple", duration=2.6, frequency=111)
            _make_clip(ui, color="green", duration=0.6, frequency=440)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x240:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=900:sample_rate=48000:duration=1",
                    "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(source),
                ],
                check=True,
                capture_output=True,
            )

            receipt = SourceAudioPerformanceAssembler().remux_rendered_timeline(
                source_media=source,
                rendered_video=rendered,
                output_path=output,
                source_media_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                regions=[
                    {"region_id": "G01", "audio_mode": "source_master", "source_start_us": 0, "source_end_us": 1_000_000},
                    {"region_id": "U01", "audio_mode": "opaque_audio_keep", "media": ui},
                    {"region_id": "G02", "audio_mode": "source_master", "source_start_us": 2_000_000, "source_end_us": 3_000_000},
                ],
                placements=[
                    {"region_id": "G01", "output_start": 0.0, "output_end": 1.0},
                    {"region_id": "U01", "output_start": 1.0, "output_end": 1.6},
                    {"region_id": "G02", "output_start": 1.6, "output_end": 2.6},
                ],
            )

            self.assertTrue(output.is_file())
            self.assertEqual(receipt["regions"][2]["source_start_us"], 2_000_000)
            self.assertEqual(receipt["regions"][1]["opaque_media_sha256"], hashlib.sha256(ui.read_bytes()).hexdigest())
            self.assertEqual(receipt["rendered_visual_sha256"], hashlib.sha256(rendered.read_bytes()).hexdigest())
            self.assertEqual(receipt["final_output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            g02_wav = root / "g02-remux.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.7", "-t", "0.4", "-i", str(output), "-vn", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(g02_wav)],
                check=True,
                capture_output=True,
            )
            with wave.open(str(g02_wav), "rb") as handle:
                samples = array("h", handle.readframes(handle.getnframes()))

            def amplitude(frequency: int) -> float:
                real = sum(value * math.cos(2 * math.pi * frequency * index / 48_000) for index, value in enumerate(samples))
                imaginary = sum(value * math.sin(2 * math.pi * frequency * index / 48_000) for index, value in enumerate(samples))
                return math.hypot(real, imaginary) / len(samples)

            self.assertGreater(amplitude(900), amplitude(300) * 8)

    def test_source_audio_performance_remux_uses_receipted_crossfade_for_visual_overlap(self):
        from server.audio_mixer import SourceAudioPerformanceAssembler

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            rendered = root / "rendered.mp4"
            ui = root / "ui.mp4"
            output = root / "output.mp4"
            _make_clip(rendered, color="purple", duration=2.4, frequency=111)
            _make_clip(ui, color="green", duration=0.6, frequency=440)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x240:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=900:sample_rate=48000:duration=1",
                    "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
                ],
                check=True,
                capture_output=True,
            )

            receipt = SourceAudioPerformanceAssembler().remux_rendered_timeline(
                source_media=source,
                rendered_video=rendered,
                output_path=output,
                source_media_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                regions=[
                    {"region_id": "G01", "audio_mode": "source_master", "source_start_us": 0, "source_end_us": 1_000_000},
                    {"region_id": "U01", "audio_mode": "opaque_audio_keep", "media": ui},
                    {"region_id": "G02", "audio_mode": "source_master", "source_start_us": 2_000_000, "source_end_us": 3_000_000},
                ],
                placements=[
                    {"region_id": "G01", "output_start": 0.0, "output_end": 1.0},
                    {"region_id": "U01", "output_start": 0.8, "output_end": 1.4},
                    {"region_id": "G02", "output_start": 1.4, "output_end": 2.4},
                ],
                transition_receipts=[
                    {"boundary_index": 0, "rendered": True, "audio_rendered": True, "audio_transition": "crossfade", "audio_fade_duration": 0.05, "source_shell_sha256": "a" * 64},
                ],
            )

            self.assertTrue(output.is_file())
            self.assertEqual(receipt["boundaries"][0]["audio_transition"], "crossfade")
            self.assertEqual(receipt["regions"][2]["source_start_us"], 2_000_000)

    def test_evidence_bound_audio_mixer_fails_closed_on_invalid_media_and_windows(self):
        from server.audio_mixer import AudioMixerError, EvidenceBoundAudioMixer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            opaque = root / "opaque.mp4"
            silent = root / "silent.mp4"
            _make_clip(source, color="blue", duration=1.0, frequency=880)
            _make_clip(opaque, color="green", duration=0.5, frequency=440)
            _make_clip(
                silent,
                color="red",
                duration=0.5,
                include_audio=False,
            )
            active_window = _timeline_module().detect_active_window(
                opaque,
                duration=0.5,
                fps=30.0,
            )
            mixer = EvidenceBoundAudioMixer()
            common = {
                "source_media": source,
                "output_path": root / "mixed.mp4",
                "region_id": "opaque-ui",
                "source_start_us": 0,
                "source_end_us": 1_000_000,
                "mix_policy": None,
                "active_window": active_window,
                "source_media_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }

            with self.assertRaisesRegex(AudioMixerError, "requires audio and video"):
                mixer.mix_region(
                    **common,
                    opaque_media=silent,
                    opaque_media_sha256=hashlib.sha256(silent.read_bytes()).hexdigest(),
                    speech_windows=[
                        {"event_id": "A1", "start_us": 100_000, "end_us": 300_000}
                    ],
                )
            for speech_windows, message in (
                ([{"event_id": "A1", "start_us": 300_000, "end_us": 300_000}], "invalid"),
                ([{"event_id": "A1", "start_us": 900_000, "end_us": 1_100_000}], "outside"),
                ([{"event_id": "A1", "start_us": 300_000, "end_us": 700_000}], "active duration"),
            ):
                with self.subTest(message=message), self.assertRaisesRegex(
                    AudioMixerError,
                    message,
                ):
                    mixer.mix_region(
                        **common,
                        opaque_media=opaque,
                        opaque_media_sha256=hashlib.sha256(opaque.read_bytes()).hexdigest(),
                        speech_windows=speech_windows,
                    )
            for mix_policy in (
                {"duck_gain_db": -30.0},
                {"fade_in_ms": 200.0},
            ):
                with self.subTest(mix_policy=mix_policy), self.assertRaisesRegex(
                    AudioMixerError,
                    "outside supported bounds",
                ):
                    mixer.mix_region(
                        **{**common, "mix_policy": mix_policy},
                        opaque_media=opaque,
                        opaque_media_sha256=hashlib.sha256(opaque.read_bytes()).hexdigest(),
                        speech_windows=[
                            {"event_id": "A1", "start_us": 100_000, "end_us": 300_000}
                        ],
                    )
            with self.assertRaisesRegex(AudioMixerError, "immutable source media"):
                EvidenceBoundAudioMixer(
                    production=True,
                    sha256="a" * 64,
                ).mix_region(
                    **{**common, "source_media_sha256": None},
                    opaque_media=opaque,
                    opaque_media_sha256=hashlib.sha256(opaque.read_bytes()).hexdigest(),
                    speech_windows=[
                        {"event_id": "A1", "start_us": 100_000, "end_us": 300_000}
                    ],
                )

    def test_evidence_bound_audio_mixer_ducks_opaque_tone_at_exact_window(self):
        from server.audio_mixer import EvidenceBoundAudioMixer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            opaque = root / "opaque.mp4"
            output = root / "mixed.mp4"
            decoded = root / "mixed-mono.wav"
            _make_clip(source, color="blue", duration=1.0, frequency=1000)
            _make_clip(opaque, color="green", duration=1.0, frequency=440)
            active_window = _timeline_module().detect_active_window(
                opaque,
                duration=1.0,
                fps=30.0,
            )
            EvidenceBoundAudioMixer().mix_region(
                source_media=source,
                opaque_media=opaque,
                output_path=output,
                region_id="opaque-ui",
                source_start_us=0,
                source_end_us=1_000_000,
                speech_windows=[
                    {"event_id": "A1", "start_us": 200_000, "end_us": 600_000}
                ],
                mix_policy={"duck_gain_db": -12.0},
                active_window=active_window,
                source_media_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                opaque_media_sha256=hashlib.sha256(opaque.read_bytes()).hexdigest(),
            )
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(output),
                    "-vn", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(decoded),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            with wave.open(str(decoded), "rb") as handle:
                samples = array("h", handle.readframes(handle.getnframes()))
            window_size = 1_200
            amplitudes = []
            for offset in range(0, len(samples) - window_size + 1, window_size):
                chunk = samples[offset : offset + window_size]
                real = sum(
                    value * math.cos(2 * math.pi * 440 * index / 48_000)
                    for index, value in enumerate(chunk, start=offset)
                )
                imaginary = sum(
                    value * math.sin(2 * math.pi * 440 * index / 48_000)
                    for index, value in enumerate(chunk, start=offset)
                )
                amplitudes.append(math.hypot(real, imaginary) / window_size)
            outside = sum(amplitudes[index] for index in (*range(2, 7), *range(28, 35))) / 12
            first_inside_db = 20 * math.log10(amplitudes[8] / outside)
            deep_inside_db = 20 * math.log10((sum(amplitudes[9:20]) / 11) / outside)

            self.assertAlmostEqual(first_inside_db, -12.0, delta=1.5)
            self.assertAlmostEqual(deep_inside_db, -12.0, delta=1.5)

    def test_evidence_bound_duck_curve_is_half_open_and_coalesces_adjacent_windows(self):
        from server.audio_mixer import _duck_gain_expression, _receipt_duck_curve

        policy = {"duck_gain_db": -12.0}
        windows = [
            {"local_start_us": 250_000, "local_end_us": 500_000},
            {"local_start_us": 500_000, "local_end_us": 750_000},
        ]
        self.assertEqual(
            _receipt_duck_curve(windows, policy=policy),
            [
                {"time_us": 0, "gain_db": 0.0},
                {"time_us": 250_000, "gain_db": -12.0},
                {"time_us": 750_000, "gain_db": 0.0},
            ],
        )
        expression = _duck_gain_expression(windows, policy=policy)
        rendered = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "aevalsrc=1:s=48000:d=1",
                "-af",
                f"aeval='val(0)*{expression}':c=mono",
                "-f",
                "f32le",
                "-",
            ],
            capture_output=True,
            check=True,
        )
        samples = array("f")
        samples.frombytes(rendered.stdout)
        duck_linear = 10 ** (-12.0 / 20.0)
        self.assertAlmostEqual(samples[11_999], 1.0, delta=1e-6)
        self.assertAlmostEqual(samples[12_000], duck_linear, delta=1e-6)
        self.assertAlmostEqual(samples[23_999], duck_linear, delta=1e-6)
        self.assertAlmostEqual(samples[24_000], duck_linear, delta=1e-6)
        self.assertAlmostEqual(samples[35_999], duck_linear, delta=1e-6)
        self.assertAlmostEqual(samples[36_000], 1.0, delta=1e-6)

    def test_evidence_bound_audio_mixer_limits_overload_to_configured_true_peak(self):
        from server.audio_mixer import EvidenceBoundAudioMixer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            opaque = root / "opaque.mp4"
            output = root / "mixed.mp4"
            _make_clip(
                source,
                color="blue",
                duration=1.0,
                frequency=1000,
                audio_volume=8.0,
            )
            _make_clip(
                opaque,
                color="green",
                duration=1.0,
                frequency=440,
                audio_volume=8.0,
            )
            active_window = _timeline_module().detect_active_window(
                opaque,
                duration=1.0,
                fps=30.0,
            )
            EvidenceBoundAudioMixer().mix_region(
                source_media=source,
                opaque_media=opaque,
                output_path=output,
                region_id="overloaded-ui",
                source_start_us=0,
                source_end_us=1_000_000,
                speech_windows=[
                    {"event_id": "A1", "start_us": 50_000, "end_us": 950_000}
                ],
                mix_policy={
                    "duck_gain_db": -3.0,
                    "source_gain_db": 6.0,
                    "limiter_true_peak_db": -1.0,
                },
                active_window=active_window,
                source_media_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                opaque_media_sha256=hashlib.sha256(opaque.read_bytes()).hexdigest(),
            )

            peak_probe = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-nostats", "-i", str(output),
                    "-filter_complex", "ebur128=peak=true", "-f", "null", "-",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            peak_matches = re.findall(
                r"Peak:\s+(-?\d+(?:\.\d+)?) dBFS",
                peak_probe.stderr,
            )
            self.assertTrue(peak_matches, peak_probe.stderr)
            self.assertLessEqual(float(peak_matches[-1]), -0.8)

    @staticmethod
    def _assert_no_forbidden_timeline_fillers(value: object) -> None:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
        for forbidden in (
            "tpad",
            "apad",
            "loop=",
            "-stream_loop",
            "color=c=black",
            "duplicate_last_frame",
            "stop_mode=clone",
        ):
            if forbidden in serialized:
                raise AssertionError(f"forbidden timeline operation present: {forbidden}")
        if __import__("re").search(r"setpts\s*=\s*(?:[0-9.]|[^,;]*\*)", serialized):
            raise AssertionError("forbidden setpts speed factor present")

    def test_loads_bundled_timeline_module_even_when_name_is_preloaded(self) -> None:
        fake_module = SimpleNamespace(__file__="C:/foreign/timeline_splice.py")
        expected = (
            Path(__file__).resolve().parents[1]
            / "bundled-skills"
            / "seedance-storyboard-replication"
            / "scripts"
            / "timeline_splice.py"
        ).resolve()

        with patch.dict(sys.modules, {"timeline_splice": fake_module}):
            module = _timeline_module()

        self.assertIsNot(module, fake_module)
        self.assertEqual(Path(module.__file__).resolve(), expected)

    def test_loader_does_not_allow_preloaded_foreign_concat_dependency(self) -> None:
        foreign = SimpleNamespace(__file__="C:/foreign/concat_videos.py")
        package_name = "_usfr_bundled_timeline_splice_pkg"
        with patch.dict(sys.modules, {"concat_videos": foreign}):
            sys.modules.pop(f"{package_name}.timeline_splice", None)
            sys.modules.pop(f"{package_name}.concat_videos", None)
            sys.modules.pop("_usfr_bundled_timeline_splice", None)
            module = _timeline_module()
            dependency = sys.modules.get(f"{module.__package__}.concat_videos")
        self.assertIsNot(dependency, foreign)
        self.assertEqual(
            Path(dependency.__file__).resolve(),
            (
                Path(__file__).resolve().parents[1]
                / "bundled-skills"
                / "seedance-storyboard-replication"
                / "scripts"
                / "concat_videos.py"
            ).resolve(),
        )

    def test_global_segment_bindings_require_exact_unique_frozen_plan_consumption(self) -> None:
        plan_sha, context = self._frozen_binding_fixture()
        regions = [
            {
                "region_type": "generated",
                "media_origin": "generated_media",
                "segment_plan_sha256": plan_sha,
                "cut_ids": ["C01"],
                "media_artifact_bindings": [
                    {"segment_id": "S01", "segment_plan_sha256": plan_sha}
                ],
            },
            {
                "region_type": "generated",
                "media_origin": "generated_media",
                "segment_plan_sha256": plan_sha,
                "cut_ids": ["C01"],
                "media_artifact_bindings": [
                    {"segment_id": "S01", "segment_plan_sha256": plan_sha}
                ],
            },
        ]
        validator = getattr(timeline_renderer, "_timeline_segment_bindings", None)
        self.assertTrue(callable(validator), "global segment validator is missing")
        with self.assertRaisesRegex(TimelineRendererError, "unique|closed|coverage"):
            validator(regions, context=context, production=True)

    def test_source_routes_reject_singular_and_slot_media_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=1.0)
            context = _Context()
            context.work_dir = root / "work"
            context.timeline_regions = (
                {
                    "region_id": "source-bound",
                    "region_type": "source_ui_keep",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                    "slot_id": "ui",
                    "media_artifact_id": "forbidden",
                },
            )
            with self.assertRaisesRegex(TimelineRendererError, "media binding"):
                BundledTimelineRenderer(production=True, sha256="b" * 64).render(
                    source, output, context
                )

    def test_production_generated_region_requires_plural_provider_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = _ArtifactProductionContext(root / "work", root / "missing.mp4")
            with ExitStack() as stack:
                with self.assertRaisesRegex(TimelineRendererError, "plural|bindings"):
                    BundledTimelineRenderer(production=True, sha256="b" * 64)._materialize_region(
                        {
                            "region_type": "generated",
                            "media_origin": "generated_media",
                            "artifact_id": "singular",
                        },
                        context=context,
                        stack=stack,
                    )

    def test_provider_binding_requires_actual_materialized_bytes_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "segment.mp4"
            _make_clip(media, color="blue", duration=0.5)
            plan_sha, context = self._frozen_binding_fixture()
            context.materialize_artifact = lambda kind, **kwargs: _Materialized(media)
            with ExitStack() as stack:
                with self.assertRaisesRegex(TimelineRendererError, "different SHA-256"):
                    BundledTimelineRenderer(production=True, sha256="b" * 64)._materialize_region(
                        {
                            "region_type": "generated",
                            "media_origin": "generated_media",
                            "segment_plan_sha256": plan_sha,
                            "cut_ids": ["C01"],
                            "media_artifact_bindings": [
                                {
                                    "segment_id": "S01",
                                    "segment_plan_sha256": plan_sha,
                                    "artifact_id": "artifact-s01",
                                    "sha256": "f" * 64,
                                    "kind": "provider_video",
                                }
                            ],
                        },
                        context=context,
                        stack=stack,
                    )

    @staticmethod
    def _frozen_binding_fixture() -> tuple[str, SimpleNamespace]:
        plan = {
            "segments": [
                {"segment_id": "S01", "cut_ids": ["C01"]},
                {"segment_id": "S02", "cut_ids": ["C02"]},
            ]
        }
        canonical_json = json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        plan_sha = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        context = SimpleNamespace(
            artifacts=(
                {
                    "kind": "segment_plan",
                    "sha256": plan_sha,
                    "metadata": {"canonical_json": canonical_json},
                },
            )
        )
        return plan_sha, context

    def test_rejects_nonexact_cut_membership_with_extra_cut(self) -> None:
        plan_sha, context = self._frozen_binding_fixture()
        with self.assertRaisesRegex(TimelineRendererError, "Cut membership"):
            _frozen_binding_order(
                {"segment_plan_sha256": plan_sha, "cut_ids": ["C01", "C99"]},
                [{"segment_id": "S01"}],
                context=context,
            )

    def test_rejects_nonexact_cut_membership_with_reversed_cut_order(self) -> None:
        plan_sha, context = self._frozen_binding_fixture()
        with self.assertRaisesRegex(TimelineRendererError, "Cut membership"):
            _frozen_binding_order(
                {"segment_plan_sha256": plan_sha, "cut_ids": ["C02", "C01"]},
                [{"segment_id": "S01"}, {"segment_id": "S02"}],
                context=context,
            )

    def test_rejects_nonexact_cut_membership_when_region_cuts_are_missing(self) -> None:
        plan_sha, context = self._frozen_binding_fixture()
        with self.assertRaisesRegex(TimelineRendererError, "Cut membership"):
            _frozen_binding_order(
                {"segment_plan_sha256": plan_sha},
                [{"segment_id": "S01"}],
                context=context,
            )

    def test_rejects_provider_bindings_on_source_interval_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=2.0)

            context = _ArtifactProductionContext(root / "work", source)
            context.timeline_regions = (
                {
                    "region_id": "source-bound",
                    "region_type": "generated",
                    "source_start_us": 0,
                    "source_end_us": 2_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                    "media_artifact_bindings": [{"invalid": "must not be ignored"}],
                },
            )

            with self.assertRaisesRegex(
                TimelineRendererError,
                "media binding",
            ):
                BundledTimelineRenderer(
                    production=True,
                    sha256="b" * 64,
                ).render(source, output, context)

    def test_rejects_provider_bindings_on_omitted_tail_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=2.0)

            context = _ArtifactProductionContext(root / "work", source)
            context.timeline_regions = (
                {
                    "region_id": "source-body",
                    "region_type": "source_ui_keep",
                    "source_start_us": 0,
                    "source_end_us": 1_500_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
                {
                    "region_id": "omitted-tail-bound",
                    "region_type": "omit_source_end_card",
                    "source_start_us": 1_500_000,
                    "source_end_us": 2_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "omit_source_end_card",
                    "media_artifact_bindings": [{"invalid": "must not be ignored"}],
                },
            )

            with self.assertRaisesRegex(
                TimelineRendererError,
                "media binding",
            ):
                BundledTimelineRenderer(
                    production=True,
                    sha256="b" * 64,
                ).render(source, output, context)

    def test_normalizes_source_ui_keep_and_omitted_tail_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=2.0)

            context = _Context()
            context.work_dir = root / "work"
            context.timeline_regions = (
                {
                    "region_id": "source-ui",
                    "region_type": "source_ui_keep",
                    "source_start_us": 0,
                    "source_end_us": 1_500_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
                {
                    "region_id": "source-tail",
                    "region_type": "omit_source_end_card",
                    "source_start_us": 1_500_000,
                    "source_end_us": 2_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "omit_source_end_card",
                },
            )

            result = BundledTimelineRenderer(
                production=False,
                sha256="a" * 64,
            ).render(source, output, context)

            self.assertTrue(output.is_file())
            manifest = result["timeline_manifest"]
            self.assertEqual(manifest["placements"][0]["region_type"], "generated")
            self.assertEqual(
                manifest["omitted_intervals"][0]["region_type"],
                "excluded_app_end_card",
            )

    def test_projects_flat_source_transition_shell_to_required_boundary_phases(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            ui = root / "ui.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=2.0)
            _make_clip(ui, color="blue", duration=1.0)

            context = _Context()
            context.work_dir = root / "work"
            context.timeline_regions = (
                {
                    "region_id": "body",
                    "region_type": "source_ui_keep",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                    "transition_shell": {"kind": "push_left", "duration_ms": 200},
                },
                {
                    "region_id": "ui",
                    "region_type": "opaque_ui_demo",
                    "source_start_us": 1_000_000,
                    "source_end_us": 2_000_000,
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "media_path": str(ui),
                    "transition_shell": {"kind": "push_left", "duration_ms": 200},
                },
            )

            manifest = BundledTimelineRenderer(
                production=False,
                sha256="a" * 64,
            ).render(source, output, context)["timeline_manifest"]

            self.assertTrue(manifest["placements"][0]["transition_shell_applied"]["exit"])
            self.assertTrue(manifest["placements"][1]["transition_shell_applied"]["entry"])

    def test_flat_transition_shell_normalizes_to_entry_and_exit_once(self) -> None:
        shell = {
            "kind": "dissolve",
            "duration_frames": 6,
            "curve": "linear",
            "direction": "left",
            "audio": {"policy": "crossfade", "fade_seconds": 0.03},
            "z_order": "incoming_over_outgoing",
        }

        normalized = timeline_renderer._transition_shell(
            shell,
            index=1,
            region_count=3,
            expand_flat=True,
        )

        self.assertEqual(set(normalized), {"entry", "exit", "audio", "z_order"})
        self.assertEqual(normalized["entry"], normalized["exit"])
        self.assertEqual(normalized["entry"]["type"], "dissolve")
        self.assertNotIn("audio", normalized["entry"])
        self.assertNotIn("z_order", normalized["entry"])
        self._assert_no_forbidden_timeline_fillers(normalized)

    def test_opaque_ui_without_source_interval_requires_approved_insertion_cut(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            ui = root / "ui.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=1.0)
            _make_clip(ui, color="blue", duration=1.0)
            context = _Context()
            context.work_dir = root / "work"
            context.timeline_regions = (
                {
                    "region_id": "ui-insertion",
                    "region_type": "opaque_ui_demo",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "media_path": str(ui),
                    "source_interval_evidenced": False,
                    "approved_insertion_cut": False,
                    "transition_shell": {"kind": "hard_cut"},
                },
            )

            with self.assertRaisesRegex(
                TimelineRendererError,
                "approved insertion cut",
            ):
                BundledTimelineRenderer(
                    production=False,
                    sha256="a" * 64,
                ).render(source, output, context)
            self._assert_no_forbidden_timeline_fillers(context.timeline_regions)

    def test_supplied_tail_without_source_tail_appends_after_last_active_body_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            tail = root / "tail.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=2.0)
            _make_clip(tail, color="blue", duration=0.6)
            context = _Context()
            context.work_dir = root / "work"
            context.timeline_regions = (
                {
                    "region_id": "body",
                    "region_type": "source_ui_keep",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
                {
                    "region_id": "tail",
                    "region_type": "opaque_tail",
                    "source_start_us": 1_000_000,
                    "source_end_us": 2_000_000,
                    "media_origin": "user_upload",
                    "media_path": str(tail),
                    "source_tail_detected": False,
                    "approved_insertion_cut": True,
                    "transition_shell": {"entry": {"type": "hard_cut"}},
                },
            )

            manifest = BundledTimelineRenderer(
                production=False,
                sha256="a" * 64,
            ).render(source, output, context)["timeline_manifest"]

            body, appended_tail = manifest["placements"]
            self.assertEqual(appended_tail["assembly_policy"], "tail_append")
            self.assertTrue(appended_tail["tail_append"])
            self.assertEqual(appended_tail["output_start"], body["output_end"])
            self.assertAlmostEqual(appended_tail["output_duration"], 0.6, delta=0.08)
            self._assert_no_forbidden_timeline_fillers(manifest)

    def test_appended_tail_uses_planned_transition_when_no_source_terminal_shell_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            tail = root / "tail.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=2.0)
            _make_clip(tail, color="blue", duration=0.6)
            context = _Context()
            context.work_dir = root / "work"
            context.timeline_regions = (
                {
                    "region_id": "body",
                    "region_type": "source_ui_keep",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
                {
                    "region_id": "tail",
                    "region_type": "opaque_tail",
                    "source_start_us": 1_000_000,
                    "source_end_us": 2_000_000,
                    "media_origin": "user_upload",
                    "media_path": str(tail),
                    "source_tail_detected": False,
                    "approved_insertion_cut": True,
                    "planned_transition_shell": {
                        "type": "dissolve",
                        "duration_frames": 3,
                        "curve": "linear",
                    },
                },
            )

            manifest = BundledTimelineRenderer(
                production=False,
                sha256="a" * 64,
            ).render(source, output, context)["timeline_manifest"]

            tail_placement = manifest["placements"][-1]
            self.assertTrue(tail_placement["planned_transition"])
            self.assertTrue(tail_placement["transition_shell_applied"]["entry"])
            self.assertEqual(manifest["transition_renders"][-1]["source_type"], "dissolve")
            self._assert_no_forbidden_timeline_fillers(manifest)

    def test_every_non_source_carrier_receipt_binds_current_final_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            ui = root / "ui.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=2.0)
            _make_clip(ui, color="blue", duration=1.0)
            context = _ProductionContext(root / "work", ui)
            context.timeline_regions = (
                {
                    "region_id": "body",
                    "region_type": "source_ui_keep",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
                {
                    "region_id": "ui",
                    "region_type": "opaque_ui_demo",
                    "source_start_us": 1_000_000,
                    "source_end_us": 2_000_000,
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "metadata": {
                        "slot_id": "ui_operation_video",
                        "media_sha256": hashlib.sha256(ui.read_bytes()).hexdigest(),
                    },
                    "transition_shell": {"kind": "hard_cut"},
                },
            )

            manifest = BundledTimelineRenderer(
                production=True,
                sha256="b" * 64,
            ).render(source, output, context)["timeline_manifest"]

            final_sha = hashlib.sha256(output.read_bytes()).hexdigest()
            non_source = [
                item
                for item in manifest["placements"]
                if item["media_origin"] != "source_interval"
            ]
            self.assertTrue(non_source)
            for placement in non_source:
                receipts = placement.get("provider_carrier_receipts") or placement.get(
                    "carrier_receipts"
                )
                self.assertTrue(receipts)
                self.assertEqual(
                    {receipt["final_output_sha256"] for receipt in receipts},
                    {final_sha},
                )
            self._assert_no_forbidden_timeline_fillers(manifest)

    def test_generated_ui_region_materializes_generated_ui_video_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ui = root / "ui.mp4"
            _make_clip(ui, color="blue", duration=1.0)
            context = _ArtifactProductionContext(root / "work", ui)
            renderer = BundledTimelineRenderer(
                production=True,
                sha256="b" * 64,
            )

            with ExitStack() as stack:
                path = renderer._materialize_region(
                    {"region_type": "generated_ui_demo"},
                    context=context,
                    stack=stack,
                )

            self.assertEqual(path, ui.resolve())
            self.assertEqual(context.artifact_kind, "generated_ui_video")

    def test_production_generated_regions_reject_inferred_provider_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated = root / "generated.mp4"
            _make_clip(generated, color="blue", duration=1.0)
            context = _ArtifactProductionContext(root / "work", generated)
            context.artifacts = (
                {
                    "kind": "provider_video",
                    "artifact_id": "artifact-r1",
                    "sha256": "1" * 64,
                    "metadata": {"region_id": "R01"},
                },
                {
                    "kind": "provider_video",
                    "artifact_id": "artifact-r2",
                    "sha256": "2" * 64,
                    "metadata": {"region_id": "R02"},
                },
            )
            renderer = BundledTimelineRenderer(
                production=True,
                sha256="b" * 64,
            )

            with ExitStack() as stack:
                with self.assertRaisesRegex(TimelineRendererError, "plural provider bindings"):
                    renderer._materialize_region(
                        {"region_id": "R02", "region_type": "generated"},
                        context=context,
                        stack=stack,
                    )

    def test_renders_two_provider_segments_as_one_generated_region_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            first = root / "segment-1.mp4"
            second = root / "segment-2.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=3.0)
            _make_clip(first, color="blue", duration=0.7)
            _make_clip(second, color="green", duration=0.8)

            segment_plan = {
                "segments": [
                    {"segment_id": "S01", "cut_ids": ["C01"]},
                    {"segment_id": "S02", "cut_ids": ["C02"]},
                ]
            }
            segment_plan_raw = json.dumps(
                segment_plan,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            segment_plan_sha = __import__("hashlib").sha256(
                segment_plan_raw.encode("utf-8")
            ).hexdigest()

            context = _SegmentArtifactProductionContext(
                root / "work",
                {
                    "artifact-s01": first,
                    "artifact-s02": second,
                },
            )
            context.artifacts += (
                {
                    "kind": "segment_plan",
                    "artifact_id": "artifact-plan",
                    "sha256": segment_plan_sha,
                    "metadata": {
                        "canonical_json": segment_plan_raw,
                        "segments": segment_plan["segments"],
                    },
                },
            )
            context.timeline_regions = (
                {
                    "region_id": "source-before",
                    "region_type": "source_ui_keep",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
                {
                    "region_id": "generated-body",
                    "region_type": "generated",
                    "cut_ids": ["C01", "C02"],
                    "source_start_us": 1_000_000,
                    "source_end_us": 2_000_000,
                    "media_origin": "generated_media",
                    "assembly_policy": "splice_generated_media",
                    "segment_plan_sha256": segment_plan_sha,
                    "transition_shell": {
                        "entry": {"type": "push_left", "duration_seconds": 0.1},
                        "exit": {"type": "push_left", "duration_seconds": 0.1},
                    },
                    "media_artifact_bindings": [
                        {
                            "segment_id": "S01",
                            "segment_plan_sha256": segment_plan_sha,
                            "artifact_id": "artifact-s01",
                            "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
                            "kind": "provider_video",
                        },
                        {
                            "segment_id": "S02",
                            "segment_plan_sha256": segment_plan_sha,
                            "artifact_id": "artifact-s02",
                            "sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
                            "kind": "provider_video",
                        },
                    ],
                },
                {
                    "region_id": "source-after",
                    "region_type": "source_ui_keep",
                    "source_start_us": 2_000_000,
                    "source_end_us": 3_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
            )

            manifest = BundledTimelineRenderer(
                production=True,
                sha256="b" * 64,
            ).render(source, output, context)["timeline_manifest"]

            self.assertTrue(output.is_file())
            self.assertEqual(
                context.artifact_calls,
                [
                    (
                        "provider_video",
                        {"artifact_id": "artifact-s01", "sha256": hashlib.sha256(first.read_bytes()).hexdigest()},
                    ),
                    (
                        "provider_video",
                        {"artifact_id": "artifact-s02", "sha256": hashlib.sha256(second.read_bytes()).hexdigest()},
                    ),
                ],
            )
            self.assertEqual(len(manifest["placements"]), 3)
            self.assertEqual(len(manifest["transition_renders"]), 2)
            generated = manifest["placements"][1]
            self.assertEqual(generated["duration_policy"], "natural_media_duration")
            self.assertFalse(generated["retimed"])
            self.assertAlmostEqual(generated["actual_video_duration"], 1.5, delta=0.08)
            self.assertAlmostEqual(generated["effective_media_duration"], 1.5, delta=0.08)
            receipts = generated["provider_carrier_receipts"]
            self.assertEqual(
                [(item["segment_id"], item["artifact_id"]) for item in receipts],
                [("S01", "artifact-s01"), ("S02", "artifact-s02")],
            )
            self.assertEqual(
                [item["artifact_sha256"] for item in receipts],
                [
                    hashlib.sha256(first.read_bytes()).hexdigest(),
                    hashlib.sha256(second.read_bytes()).hexdigest(),
                ],
            )
            self.assertEqual(
                {item["segment_plan_sha256"] for item in receipts},
                {segment_plan_sha},
            )
            self.assertEqual(
                {item["final_output_sha256"] for item in receipts},
                {manifest["final_output_sha256"]},
            )
            self.assertTrue(
                manifest["placements"][1]["transition_shell_applied"]["entry"]
            )
            self.assertTrue(
                manifest["placements"][1]["transition_shell_applied"]["exit"]
            )

    def test_rejects_provider_segment_bindings_out_of_frozen_plan_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "segment-1.mp4"
            second = root / "segment-2.mp4"
            _make_clip(first, color="blue", duration=0.5)
            _make_clip(second, color="green", duration=0.5)
            plan = {
                "segments": [
                    {"segment_id": "S01", "cut_ids": ["C01"]},
                    {"segment_id": "S02", "cut_ids": ["C02"]},
                ]
            }
            plan_raw = json.dumps(
                plan,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            plan_sha = __import__("hashlib").sha256(plan_raw.encode("utf-8")).hexdigest()
            context = _SegmentArtifactProductionContext(
                root / "work",
                {"artifact-s01": first, "artifact-s02": second},
            )
            context.artifacts += (
                {
                    "kind": "segment_plan",
                    "artifact_id": "artifact-plan",
                    "sha256": plan_sha,
                    "metadata": {"canonical_json": plan_raw, "segments": plan["segments"]},
                },
            )
            region = {
                "region_id": "generated-body",
                "region_type": "generated",
                "cut_ids": ["C01", "C02"],
                "segment_plan_sha256": plan_sha,
                "media_artifact_bindings": [
                    {
                        "segment_id": "S02",
                        "segment_plan_sha256": plan_sha,
                        "artifact_id": "artifact-s02",
                        "sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
                        "kind": "provider_video",
                    },
                    {
                        "segment_id": "S01",
                        "segment_plan_sha256": plan_sha,
                        "artifact_id": "artifact-s01",
                        "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
                        "kind": "provider_video",
                    },
                ],
            }

            with ExitStack() as stack:
                with self.assertRaisesRegex(Exception, "frozen segment plan order"):
                    BundledTimelineRenderer(
                        production=True,
                        sha256="b" * 64,
                    )._materialize_region(
                        region,
                        context=context,
                        stack=stack,
                    )

    def test_renders_source_and_opaque_regions_with_transition_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            ui = root / "ui.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=3.0)
            _make_clip(ui, color="blue", duration=1.6)

            context = _Context()
            context.work_dir = root / "work"
            context.timeline_regions = (
                {
                    "region_id": "body",
                    "region_type": "generated",
                    "source_start_us": 0,
                    "source_end_us": 1_500_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                    "media_path": str(source),
                    "transition_shell": {
                        "exit": {"type": "push_left", "duration_seconds": 0.2}
                    },
                },
                {
                    "region_id": "ui",
                    "region_type": "opaque_ui_demo",
                    "source_start_us": 1_500_000,
                    "source_end_us": 3_000_000,
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "media_path": str(ui),
                    "transition_shell": {
                        "entry": {"type": "push_left", "duration_seconds": 0.2}
                    },
                },
            )

            renderer = BundledTimelineRenderer(
                production=False,
                sha256="a" * 64,
            )
            result = renderer.render(source, output, context)

            self.assertTrue(output.is_file())
            manifest = result["timeline_manifest"]
            self.assertTrue(result["timeline_manifest_path"].is_file())
            self.assertTrue(manifest["transition_renders"][0]["rendered"])
            self.assertTrue(manifest["placements"][0]["transition_shell_applied"]["exit"])
            self.assertTrue(manifest["placements"][1]["transition_shell_applied"]["entry"])
            serialized = json.dumps(manifest, ensure_ascii=False)
            self.assertNotIn(str(source), serialized)
            self.assertNotIn(str(ui), serialized)

    def test_production_resolves_slot_from_nested_persisted_region_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            ui = root / "ui.mp4"
            output = root / "result.mp4"
            _make_clip(source, color="red", duration=2.0)
            _make_clip(ui, color="blue", duration=1.0)

            context = _ProductionContext(root / "work", ui)
            context.timeline_regions = (
                {
                    "region_id": "body",
                    "region_type": "generated",
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                    "media_origin": "source_interval",
                    "assembly_policy": "splice_source_interval",
                },
                {
                    "region_id": "ui",
                    "region_type": "opaque_ui_demo",
                    "source_start_us": 1_000_000,
                    "source_end_us": 2_000_000,
                    "media_origin": "user_upload",
                    "assembly_policy": "splice_opaque_media",
                    "metadata": {
                        "slot_id": "ui_operation_video",
                        "media_sha256": hashlib.sha256(ui.read_bytes()).hexdigest(),
                    },
                    "transition_shell": {"kind": "hard_cut"},
                },
            )

            renderer = BundledTimelineRenderer(
                production=True,
                sha256="b" * 64,
            )
            result = renderer.render(source, output, context)

            self.assertTrue(output.is_file())
            self.assertEqual(context.assert_slot_id, "ui_operation_video")
            self.assertEqual(result["capability_identity"]["capability_kind"], "timeline_renderer")


if __name__ == "__main__":
    unittest.main()
