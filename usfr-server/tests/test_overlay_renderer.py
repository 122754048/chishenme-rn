from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import contextmanager

from server.media_materializer import MaterializedMedia
from server.real_capabilities import CapabilityUnavailable, FfmpegCompositor
from server.overlay_renderer import (
    DeterministicOverlayRenderer,
    OverlayRenderError,
    validate_readable_overlay_evidence,
)


class _OverlayContext:
    def __init__(self, source: Path, work_dir: Path, regions: tuple[dict, ...]) -> None:
        self.source = source
        self.work_dir = work_dir
        self.timeline_regions = regions
        self.profile_snapshot = {
            "profile": "high_fidelity_hybrid_v1",
            "activation_mode": "active",
        }

    @contextmanager
    def materialize_slot(self, slot_id: str, *, index: int = 0):
        data = self.source.read_bytes()
        yield MaterializedMedia(
            path=self.source,
            job_id="job-test",
            object_key="tenant/source.mp4",
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type="video/mp4",
            metadata={},
        )

    def publish_artifact(self, *, kind, stream, content_type, expected_sha256, metadata=None):
        data = stream.read()
        return {
            "kind": kind,
            "sha256": hashlib.sha256(data).hexdigest(),
            "uri": f"s3://tenant/{kind}",
            "metadata": {"object_key": f"tenant/{kind}", "size_bytes": len(data), "content_type": content_type, **(metadata or {})},
        }


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class DeterministicOverlayRendererTest(unittest.TestCase):
    def test_readable_overlay_receipt_binds_final_output_and_independent_ocr(self) -> None:
        frame = b"decoded-final-frame"
        frame_sha = hashlib.sha256(frame).hexdigest()
        final_sha = "a" * 64
        receipt = {
            "render_mode": "deterministic_text",
            "expected_text": "立即下载",
            "expected_bbox": [0.1, 0.8, 0.8, 0.1],
            "output_language": "zh",
            "z_index": 20,
            "payload_sha256": "b" * 64,
            "overlay_render_mapping_sha256": "c" * 64,
        }
        evidence = {
            "input_sha256": frame_sha,
            "records": [
                {
                    "text": "立即下载",
                    "bbox": [0.1, 0.8, 0.8, 0.1],
                    "confidence": 1.0,
                    "language": "zh",
                    "z_index": 20,
                }
            ],
        }

        validated = validate_readable_overlay_evidence(
            receipt,
            frame_bytes=frame,
            evidence=evidence,
            final_output_sha256=final_sha,
        )

        self.assertEqual(validated["final_output_sha256"], final_sha)
        self.assertEqual(validated["ocr_match_percent"], 100)
        self.assertEqual(validated["layout_match_percent"], 100)
        self.assertEqual(validated["frame_digests"], [frame_sha])

    def test_readable_overlay_evidence_blocks_text_layout_language_zorder_and_stale_sha(self) -> None:
        frame = b"decoded-final-frame"
        frame_sha = hashlib.sha256(frame).hexdigest()
        base_receipt = {
            "render_mode": "deterministic_text",
            "expected_text": "立即下载",
            "expected_bbox": [0.1, 0.8, 0.8, 0.1],
            "output_language": "zh",
            "z_index": 20,
            "payload_sha256": "b" * 64,
            "overlay_render_mapping_sha256": "c" * 64,
        }
        mutations = {
            "wrong language": {"language": "en"},
            "mojibake": {"text": "绔嬪嵆涓嬭浇"},
            "wrong bounding box": {"bbox": [0.2, 0.8, 0.7, 0.1]},
            "wrong z-order": {"z_index": 10},
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                record = {
                    "text": "立即下载",
                    "bbox": [0.1, 0.8, 0.8, 0.1],
                    "confidence": 1.0,
                    "language": "zh",
                    "z_index": 20,
                    **mutation,
                }
                with self.assertRaises(OverlayRenderError):
                    validate_readable_overlay_evidence(
                        base_receipt,
                        frame_bytes=frame,
                        evidence={"input_sha256": frame_sha, "records": [record]},
                        final_output_sha256="a" * 64,
                    )
        with self.assertRaisesRegex(OverlayRenderError, "final output"):
            validate_readable_overlay_evidence(
                {**base_receipt, "final_output_sha256": "d" * 64},
                frame_bytes=frame,
                evidence={
                    "input_sha256": frame_sha,
                    "records": [
                        {
                            "text": "立即下载",
                            "bbox": [0.1, 0.8, 0.8, 0.1],
                            "confidence": 1.0,
                            "language": "zh",
                            "z_index": 20,
                        }
                    ],
                },
                final_output_sha256="a" * 64,
            )

    @staticmethod
    def _provider_compositor_fixture(root: Path) -> tuple[Path, _OverlayContext, dict, dict]:
        source = root / "source.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.8",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise unittest.SkipTest("ffmpeg unavailable")
        output_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        plan_sha = hashlib.sha256(b"provider-segment-plan").hexdigest()
        artifact_sha = output_sha
        receipt = {
            "kind": "provider_video",
            "segment_id": "S01",
            "artifact_id": "provider-s01",
            "artifact_sha256": artifact_sha,
            "segment_plan_sha256": plan_sha,
            "segment_sha256": artifact_sha,
            "carrier_sha256": artifact_sha,
            "combined_carrier_sha256": artifact_sha,
            "final_output_sha256": output_sha,
        }
        region = {
            "region_id": "R01",
            "region_type": "generated",
            "media_origin": "generated_media",
            "assembly_policy": "generate_region",
            "source_start_us": 0,
            "source_end_us": 800_000,
            "segment_plan_sha256": plan_sha,
            "media_artifact_bindings": [
                {
                    "segment_id": "S01",
                    "segment_plan_sha256": plan_sha,
                    "artifact_id": "provider-s01",
                    "sha256": artifact_sha,
                    "kind": "provider_video",
                }
            ],
        }
        context = _OverlayContext(source, root / "work", (region,))
        context.artifacts = [
            {
                "kind": "provider_video",
                "artifact_id": "provider-s01",
                "sha256": artifact_sha,
                "segment_id": "S01",
                "segment_plan_sha256": plan_sha,
            }
        ]
        manifest = {
            "contract": "universal-timeline-regions",
            "placements": [
                {
                    "region_id": "R01",
                    "region_type": "generated",
                    "source_start_us": 0,
                    "source_end_us": 800_000,
                    "output_start": 0.0,
                    "output_end": 0.8,
                    "provider_carrier_receipts": [receipt],
                }
            ],
            "omitted_intervals": [],
            "transition_renders": [],
            "duration_us": 800_000,
            "final_output_sha256": output_sha,
        }
        return source, context, manifest, receipt

    @staticmethod
    def _timeline_renderer_for_manifest(manifest: dict):
        def render(source: Path, output: Path, _context: _OverlayContext):
            output.write_bytes(source.read_bytes())
            return {"output_path": output, "timeline_manifest": manifest}

        render.capability_kind = "timeline_renderer"
        render.version = "test"
        render.sha256 = "d" * 64
        render.capability_identity = lambda: {
            "capability_kind": "timeline_renderer",
            "implementation": "tests.timeline_renderer",
            "version": "test",
            "sha256": "d" * 64,
        }
        return render

    def test_active_production_rejects_empty_renderer_manifest_for_non_source_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, context, _manifest, _receipt = self._provider_compositor_fixture(root)
            renderer = self._timeline_renderer_for_manifest({})

            with self.assertRaisesRegex(
                CapabilityUnavailable,
                "non-empty renderer timeline manifest",
            ):
                FfmpegCompositor(
                    renderer=renderer,
                    production=True,
                    sha256="e" * 64,
                ).compose(context=context, input_artifacts=[])

    def test_active_production_rejects_missing_provider_carrier_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, context, manifest, _receipt = self._provider_compositor_fixture(root)
            manifest["placements"][0].pop("provider_carrier_receipts")
            renderer = self._timeline_renderer_for_manifest(manifest)

            with self.assertRaisesRegex(
                CapabilityUnavailable,
                "provider carrier consumption",
            ):
                FfmpegCompositor(
                    renderer=renderer,
                    production=True,
                    sha256="e" * 64,
                ).compose(context=context, input_artifacts=[])

    def test_active_production_rejects_stale_provider_carrier_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, context, manifest, _receipt = self._provider_compositor_fixture(root)
            manifest["placements"][0]["provider_carrier_receipts"][0][
                "final_output_sha256"
            ] = "f" * 64
            renderer = self._timeline_renderer_for_manifest(manifest)

            with self.assertRaisesRegex(
                CapabilityUnavailable,
                "provider carrier receipt does not bind",
            ):
                FfmpegCompositor(
                    renderer=renderer,
                    production=True,
                    sha256="e" * 64,
                ).compose(context=context, input_artifacts=[])

    def test_active_production_rejects_foreign_provider_carrier_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, context, manifest, _receipt = self._provider_compositor_fixture(root)
            manifest["placements"][0]["provider_carrier_receipts"][0][
                "artifact_id"
            ] = "foreign-artifact"
            renderer = self._timeline_renderer_for_manifest(manifest)

            with self.assertRaisesRegex(
                CapabilityUnavailable,
                "provider carrier receipt does not match",
            ):
                FfmpegCompositor(
                    renderer=renderer,
                    production=True,
                    sha256="e" * 64,
                ).compose(context=context, input_artifacts=[])

    def test_active_production_rejects_incomplete_renderer_region_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _source, context, manifest, _receipt = self._provider_compositor_fixture(root)
            manifest["placements"] = []
            renderer = self._timeline_renderer_for_manifest(manifest)

            with self.assertRaisesRegex(
                CapabilityUnavailable,
                "renderer timeline manifest region coverage",
            ):
                FfmpegCompositor(
                    renderer=renderer,
                    production=True,
                    sha256="e" * 64,
                ).compose(context=context, input_artifacts=[])

    def test_renders_exact_text_payload_and_returns_pixel_bound_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            output = root / "rendered.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")

            contract = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 800_000,
                "source_width": 320,
                "source_height": 180,
                "coordinate_space": "rotation_corrected_source_visible_frame_normalized",
                "target_mapping": "source_normalized_composition_to_target_frame",
                "attachment": "screen_space",
                "time_range_semantics": "start_inclusive_end_exclusive",
                "cuts": [{
                    "cut": 1,
                    "start_us": 0,
                    "end_us": 800_000,
                    "source_overlays": [{
                        "overlay_id": "cta-1",
                        "kind": "cta_text",
                        "start_us": 0,
                        "end_us": 800_000,
                        "start_rect": [0.1, 0.2, 0.8, 0.3],
                        "end_rect": [0.1, 0.2, 0.8, 0.3],
                        "start_rotation_deg": 0,
                        "end_rotation_deg": 0,
                        "start_opacity": 1,
                        "end_opacity": 1,
                        "motion_phase": "static",
                        "motion_path": "screen-space hold",
                        "z_index": 10,
                        "layer_relation": "above source plate",
                        "interpolation": "hold",
                        "keyframes": [
                            {"time_us": 0, "bbox": [0.1, 0.2, 0.8, 0.3], "rotation_deg": 0, "opacity": 1},
                            {"time_us": 800_000, "bbox": [0.1, 0.2, 0.8, 0.3], "rotation_deg": 0, "opacity": 1},
                        ],
                    }],
                }],
            }
            payload = {
                "text": "TARGET CTA",
                "color": "white",
                "font_size": 28,
                "align": "center",
            }
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": _sha(contract),
                "regions": [{
                    "region_id": "R01",
                    "overlays": [{
                        "overlay_id": "cta-1",
                        "validated": True,
                        "render_mode": "deterministic_text",
                        "payload": payload,
                        "payload_sha256": _sha(payload),
                    }],
                }],
            }
            regions = ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 800_000,
                "source_overlay_contract": contract,
                "overlay_render_mapping": mapping,
            },)

            result = DeterministicOverlayRenderer().render(source, output, _OverlayContext(source, root, regions))

            self.assertTrue(output.is_file())
            self.assertNotEqual(source.read_bytes(), output.read_bytes())
            self.assertEqual(result["overlay_render_receipts"][0]["overlay_id"], "cta-1")
            self.assertEqual(result["overlay_render_receipts"][0]["payload_sha256"], _sha(payload))
            self.assertEqual(result["overlay_render_receipts"][0]["output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(result["overlay_render_receipts"][0]["frame_windows"], [{"start_us": 0, "end_us": 800_000}])

    def test_active_compositor_uses_bundled_renderer_when_no_renderer_is_injected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            contract = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 800_000,
                "source_width": 320,
                "source_height": 180,
                "coordinate_space": "rotation_corrected_source_visible_frame_normalized",
                "target_mapping": "source_normalized_composition_to_target_frame",
                "attachment": "screen_space",
                "time_range_semantics": "start_inclusive_end_exclusive",
                "cuts": [{
                    "cut": 1,
                    "start_us": 0,
                    "end_us": 800_000,
                    "source_overlays": [{
                        "overlay_id": "cta-1",
                        "kind": "cta_text",
                        "start_us": 0,
                        "end_us": 800_000,
                        "start_rect": [0.1, 0.2, 0.8, 0.3],
                        "end_rect": [0.1, 0.2, 0.8, 0.3],
                        "start_rotation_deg": 0,
                        "end_rotation_deg": 0,
                        "start_opacity": 1,
                        "end_opacity": 1,
                        "motion_phase": "static",
                        "motion_path": "screen-space hold",
                        "z_index": 10,
                        "layer_relation": "above source plate",
                        "interpolation": "hold",
                        "keyframes": [
                            {"time_us": 0, "bbox": [0.1, 0.2, 0.8, 0.3], "rotation_deg": 0, "opacity": 1},
                            {"time_us": 800_000, "bbox": [0.1, 0.2, 0.8, 0.3], "rotation_deg": 0, "opacity": 1},
                        ],
                    }],
                }],
            }
            payload = {"text": "TARGET CTA", "color": "white", "font_size": 28, "align": "center"}
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": _sha(contract),
                "regions": [{"region_id": "R01", "overlays": [{
                    "overlay_id": "cta-1",
                    "validated": True,
                    "render_mode": "deterministic_text",
                    "payload": payload,
                    "payload_sha256": _sha(payload),
                }]}],
            }
            context = _OverlayContext(source, root, ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 800_000,
                "source_overlay_contract": contract,
                "overlay_render_mapping": mapping,
            },))

            output = FfmpegCompositor().compose(context=context, input_artifacts=[])

            self.assertEqual(output["status"], "ready")
            self.assertEqual(len(output["overlay_render_receipts"]), 1)
            self.assertTrue(output["timeline_manifest"]["overlay_render_receipts_required"])

    def test_render_decodes_declared_window_and_attaches_final_ocr_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            output = root / "verified.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            contract = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 800_000,
                "source_width": 320,
                "source_height": 180,
                "cuts": [{
                    "cut": 1,
                    "start_us": 0,
                    "end_us": 800_000,
                    "source_overlays": [{
                        "overlay_id": "cta-verified",
                        "kind": "cta_text",
                        "start_us": 0,
                        "end_us": 800_000,
                        "start_rect": [0.1, 0.2, 0.8, 0.3],
                        "end_rect": [0.1, 0.2, 0.8, 0.3],
                        "start_rotation_deg": 0,
                        "end_rotation_deg": 0,
                        "start_opacity": 1,
                        "end_opacity": 1,
                        "z_index": 10,
                        "keyframes": [
                            {"time_us": 0, "bbox": [0.1, 0.2, 0.8, 0.3], "rotation_deg": 0, "opacity": 1},
                            {"time_us": 800_000, "bbox": [0.1, 0.2, 0.8, 0.3], "rotation_deg": 0, "opacity": 1},
                        ],
                    }],
                }],
            }
            payload = {
                "text": "SHOP NOW",
                "output_language": "en",
                "font_sha256": "f" * 64,
                "glyph_coverage_sha256": "e" * 64,
                "verification_required": True,
                "font_size": 28,
            }
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": _sha(contract),
                "output_language": "en",
                "regions": [{"region_id": "R01", "overlays": [{
                    "overlay_id": "cta-verified",
                    "validated": True,
                    "render_mode": "deterministic_text",
                    "payload": payload,
                    "payload_sha256": _sha(payload),
                }]}],
            }
            context = _OverlayContext(source, root, ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 800_000,
                "source_overlay_contract": contract,
                "overlay_render_mapping": mapping,
            },))

            class OcrBackend:
                @staticmethod
                def recognize(frame_bytes: bytes) -> dict:
                    return {
                        "input_sha256": hashlib.sha256(frame_bytes).hexdigest(),
                        "records": [{
                            "text": "SHOP NOW",
                            "bbox": [0.1, 0.2, 0.8, 0.3],
                            "confidence": 1.0,
                            "language": "en",
                            "z_index": 10,
                        }],
                    }

            receipt = DeterministicOverlayRenderer(
                ocr_backend=OcrBackend()
            ).render(source, output, context)["overlay_render_receipts"][0]
            self.assertEqual(receipt["ocr_match_percent"], 100)
            self.assertEqual(receipt["layout_match_percent"], 100)
            self.assertEqual(
                receipt["final_output_sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )
            self.assertEqual(len(receipt["frame_digests"]), 1)

    def test_renders_deterministic_asset_payload_from_immutable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            asset = root / "logo.png"
            output = root / "rendered-asset.mp4"
            for path, command in (
                (
                    source,
                    [
                        "ffmpeg", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.8",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
                    ],
                ),
                (
                    asset,
                    [
                        "ffmpeg", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=white:s=40x20:d=1",
                        "-frames:v", "1", str(asset),
                    ],
                ),
            ):
                result = subprocess.run(command, capture_output=True)
                if result.returncode != 0:
                    self.skipTest("ffmpeg unavailable")
            payload = {
                "asset_sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                "artifact_kind": "target_logo",
                "fit": "fill",
                "asset_path": str(asset),
            }
            contract = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 800_000,
                "source_width": 320,
                "source_height": 180,
                "coordinate_space": "rotation_corrected_source_visible_frame_normalized",
                "target_mapping": "source_normalized_composition_to_target_frame",
                "attachment": "screen_space",
                "time_range_semantics": "start_inclusive_end_exclusive",
                "cuts": [{
                    "cut": 1,
                    "start_us": 0,
                    "end_us": 800_000,
                    "source_overlays": [{
                        "overlay_id": "logo-1",
                        "kind": "brand_mark",
                        "start_us": 0,
                        "end_us": 800_000,
                        "start_rect": [0.1, 0.1, 0.25, 0.15],
                        "end_rect": [0.1, 0.1, 0.25, 0.15],
                        "start_rotation_deg": 0,
                        "end_rotation_deg": 0,
                        "start_opacity": 1,
                        "end_opacity": 1,
                        "motion_phase": "static",
                        "motion_path": "screen-space hold",
                        "z_index": 10,
                        "layer_relation": "above source plate",
                        "interpolation": "hold",
                        "keyframes": [
                            {"time_us": 0, "bbox": [0.1, 0.1, 0.25, 0.15], "rotation_deg": 0, "opacity": 1},
                            {"time_us": 800_000, "bbox": [0.1, 0.1, 0.25, 0.15], "rotation_deg": 0, "opacity": 1},
                        ],
                        "observed_text": None,
                    }],
                }],
            }
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": _sha(contract),
                "regions": [{
                    "region_id": "R01",
                    "overlays": [{
                        "overlay_id": "logo-1",
                        "validated": True,
                        "render_mode": "deterministic_asset",
                        "payload": payload,
                        "payload_sha256": _sha(payload),
                        "asset_sha256": payload["asset_sha256"],
                    }],
                }],
            }
            context = _OverlayContext(source, root, ({
                "region_id": "R01",
                "region_type": "generated",
                "media_origin": "generated",
                "assembly_policy": "generate_region",
                "source_start_us": 0,
                "source_end_us": 800_000,
                "source_overlay_contract": contract,
                "overlay_render_mapping": mapping,
            },))
            context.artifacts = [{
                "kind": "target_logo",
                "sha256": payload["asset_sha256"],
                "artifact_id": "logo-1",
                "metadata": {"object_key": "tenant/target_logo.png", "content_type": "image/png"},
            }]
            context.materialize_artifact = lambda kind, **_kwargs: contextmanager(lambda: None)()
            # Development renderer accepts an explicit asset path when no object-store
            # materializer is available; the payload SHA still binds the bytes.
            result = DeterministicOverlayRenderer().render(source, output, context)
            self.assertTrue(output.is_file())
            self.assertEqual(result["overlay_render_receipts"][0]["asset_sha256"], payload["asset_sha256"])
            self.assertEqual(result["overlay_render_receipts"][0]["output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_renders_linear_translation_for_deterministic_text_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            output = root / "moving.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                self.skipTest("ffmpeg unavailable")
            contract = {
                "contract": "source-ui-overlay-motion",
                "contract_version": 1,
                "reference_duration_us": 800_000,
                "source_width": 320,
                "source_height": 180,
                "cuts": [{"cut": 1, "start_us": 0, "end_us": 800_000, "source_overlays": [{
                    "overlay_id": "moving-cta",
                    "kind": "cta_text",
                    "start_us": 0,
                    "end_us": 800_000,
                    "start_rect": [0.05, 0.2, 0.25, 0.2],
                    "end_rect": [0.55, 0.2, 0.25, 0.2],
                    "start_rotation_deg": 0,
                    "end_rotation_deg": 0,
                    "start_opacity": 1,
                    "end_opacity": 1,
                    "motion_phase": "translate",
                    "motion_path": "left to right",
                    "z_index": 5,
                    "layer_relation": "above source plate",
                    "interpolation": "linear",
                    "keyframes": [
                        {"time_us": 0, "bbox": [0.05, 0.2, 0.25, 0.2], "rotation_deg": 0, "opacity": 1},
                        {"time_us": 800_000, "bbox": [0.55, 0.2, 0.25, 0.2], "rotation_deg": 0, "opacity": 1},
                    ],
                    "observed_text": "SOURCE",
                }]}],
            }
            payload = {"text": "MOVE", "color": "white", "font_size": 24}
            mapping = {
                "contract": "target-overlay-render-mapping",
                "contract_version": 1,
                "source_overlay_contract_sha256": _sha(contract),
                "regions": [{"region_id": "R01", "overlays": [{
                    "overlay_id": "moving-cta",
                    "validated": True,
                    "render_mode": "deterministic_text",
                    "payload": payload,
                    "payload_sha256": _sha(payload),
                }]}],
            }
            context = _OverlayContext(source, root, ({
                "region_id": "R01", "region_type": "generated", "media_origin": "generated",
                "assembly_policy": "generate_region", "source_start_us": 0, "source_end_us": 800_000,
                "source_overlay_contract": contract, "overlay_render_mapping": mapping,
            },))
            result = DeterministicOverlayRenderer().render(source, output, context)
            self.assertTrue(output.is_file())
            self.assertEqual(result["overlay_render_receipts"][0]["render_mode"], "deterministic_text")


if __name__ == "__main__":
    unittest.main()
