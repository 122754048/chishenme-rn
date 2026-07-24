import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from hybrid_compositor import (  # noqa: E402
    build_composite_manifest,
    choose_backend,
    validate_composite_manifest,
)


class HybridCompositorTest(unittest.TestCase):
    def _manifest(self):
        return build_composite_manifest(
            region_id="R01",
            base_plate={"origin": "source", "object_key": "private/source.mp4"},
            layers=[
                {
                    "layer_id": "product",
                    "route": "COMPOSITE",
                    "fidelity_level": 1,
                    "asset": {"object_key": "private/product.png", "sha256": "a" * 64},
                    "matte": {"kind": "alpha"},
                    "tracking": {"space": "normalized_0_1", "method": "planar"},
                    "occlusion": {"kind": "mask"},
                    "z_order": 2,
                    "lighting_match": {"key_vector": [0, 0, 1], "color_temp_k": 4200},
                }
            ],
            audio_layers=[],
            output_artifact={"object_key": "private/R01.mp4", "sha256": "b" * 64},
        )

    def test_manifest_requires_matte_tracking_and_occlusion_for_composite(self):
        manifest = self._manifest()
        validate_composite_manifest(manifest)
        manifest["layers"][0]["tracking"] = None
        with self.assertRaises(ValueError):
            validate_composite_manifest(manifest)

    def test_opaque_layer_cannot_be_semantically_rewritten(self):
        manifest = self._manifest()
        manifest["layers"][0]["route"] = "OPAQUE_SPLICE"
        manifest["layers"][0]["opaque_policy"] = "ocr_and_redraw"
        with self.assertRaises(ValueError):
            validate_composite_manifest(manifest)

    def test_backend_policy_prefers_ffmpeg_and_gates_optional_renderers(self):
        self.assertEqual(choose_backend({"complex_ui": False}, {}), "ffmpeg")
        self.assertEqual(choose_backend({"complex_ui": True}, {"hyperframes_html_ui": False}), "ffmpeg")
        self.assertEqual(choose_backend({"complex_ui": True}, {"hyperframes_html_ui": True}), "ffmpeg")
        self.assertEqual(
            choose_backend(
                {"complex_ui": True},
                {
                    "hyperframes_html_ui": {
                        "status": "enabled",
                        "domain": "complex_html_ui",
                        "activation_report_sha256": "a" * 64,
                    }
                },
            ),
            "hyperframes_html_ui",
        )
        self.assertEqual(
            choose_backend(
                {"prefer_remotion": True},
                {
                    "remotion_react_ui": {
                        "status": "enabled",
                        "domain": "programmable_overlays",
                        "activation_report_sha256": "b" * 64,
                    }
                },
            ),
            "ffmpeg",
        )

    def test_remotion_ui_is_selected_only_for_a_benchmarked_deterministic_ui_interval(self):
        report_sha = "b" * 64
        requirements = {
            "route": "generated_ui_demo",
            "target_ui_evidence_sha256": "c" * 64,
            "deterministic_ui_rebuild_allowed": True,
            "ui_truth_card_sha256": "d" * 64,
            "ui_render_contract_sha256": "e" * 64,
            "source_interval_contract_sha256": "f" * 64,
            "motion_actions": ["perspective", "parallax"],
            "existing_renderer_equivalent": False,
            "benchmark_activation_report_sha256": report_sha,
        }
        capabilities = {
            "remotion_react_ui": {
                "status": "enabled",
                "domain": "programmable_overlays",
                "activation_report_sha256": report_sha,
            }
        }

        self.assertEqual(choose_backend(requirements, capabilities), "remotion_react_ui")
        self.assertEqual(
            choose_backend({**requirements, "route": "opaque_ui_demo"}, capabilities),
            "ffmpeg",
        )

    def test_backend_policy_rejects_enabled_record_without_immutable_report(self):
        capabilities = {
            "hyperframes_html_ui": {
                "status": "enabled",
                "domain": "complex_html_ui",
                "activation_report_sha256": None,
            }
        }
        self.assertEqual(choose_backend({"complex_ui": True}, capabilities), "ffmpeg")


if __name__ == "__main__":
    unittest.main()
