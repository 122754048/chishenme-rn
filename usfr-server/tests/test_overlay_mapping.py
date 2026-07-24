from __future__ import annotations

import hashlib
import json
import unittest

from server.overlay_mapping import OverlayMappingError, build_overlay_render_mapping


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _contract() -> dict:
    return {
        "contract": "source-ui-overlay-motion",
        "contract_version": 1,
        "reference_duration_us": 2_000_000,
        "source_width": 320,
        "source_height": 180,
        "coordinate_space": "rotation_corrected_source_visible_frame_normalized",
        "target_mapping": "source_normalized_composition_to_target_frame",
        "attachment": "screen_space",
        "time_range_semantics": "start_inclusive_end_exclusive",
        "cuts": [
            {
                "cut": 1,
                "start_us": 0,
                "end_us": 2_000_000,
                "source_overlays": [
                    {
                        "overlay_id": "cta-1",
                        "kind": "cta_text",
                        "start_us": 0,
                        "end_us": 2_000_000,
                        "start_rect": [0.1, 0.2, 0.8, 0.2],
                        "end_rect": [0.1, 0.2, 0.8, 0.2],
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
                            {"time_us": 0, "bbox": [0.1, 0.2, 0.8, 0.2], "rotation_deg": 0, "opacity": 1},
                            {"time_us": 2_000_000, "bbox": [0.1, 0.2, 0.8, 0.2], "rotation_deg": 0, "opacity": 1},
                        ],
                        "observed_text": "SOURCE CTA",
                    },
                    {
                        "overlay_id": "brand-1",
                        "kind": "brand_mark",
                        "start_us": 500_000,
                        "end_us": 1_500_000,
                        "start_rect": [0.05, 0.05, 0.2, 0.1],
                        "end_rect": [0.05, 0.05, 0.2, 0.1],
                        "start_rotation_deg": 0,
                        "end_rotation_deg": 0,
                        "start_opacity": 1,
                        "end_opacity": 1,
                        "motion_phase": "static",
                        "motion_path": "screen-space hold",
                        "z_index": 11,
                        "layer_relation": "above source plate",
                        "interpolation": "hold",
                        "keyframes": [
                            {"time_us": 500_000, "bbox": [0.05, 0.05, 0.2, 0.1], "rotation_deg": 0, "opacity": 1},
                            {"time_us": 1_500_000, "bbox": [0.05, 0.05, 0.2, 0.1], "rotation_deg": 0, "opacity": 1},
                        ],
                        "observed_text": None,
                    },
                ],
            }
        ],
    }


class OverlayMappingTest(unittest.TestCase):
    def test_all_output_languages_build_deterministic_readable_text_payloads(self) -> None:
        samples = {
            "en": "Shop now",
            "ja": "今すぐ購入",
            "ko": "지금 구매",
            "fr": "Achetez maintenant",
            "de": "Jetzt kaufen",
            "es": "Compra ahora",
            "pt": "Compre agora",
            "id": "Beli sekarang",
            "zh": "立即购买",
        }
        contract = _contract()
        selling_point = dict(contract["cuts"][0]["source_overlays"][0])
        selling_point.update(
            overlay_id="selling-1",
            kind="selling_point",
            observed_text="SOURCE BENEFIT",
        )
        contract["cuts"][0]["source_overlays"] = [selling_point]
        region = {
            "region_id": "R01",
            "region_type": "generated",
            "media_origin": "generated",
            "assembly_policy": "generate_region",
            "source_start_us": 0,
            "source_end_us": 2_000_000,
        }
        for language, text in samples.items():
            with self.subTest(language=language):
                mapping = build_overlay_render_mapping(
                    contract,
                    [region],
                    replacements={
                        "selling-1": {
                            "text": text,
                            "language": language,
                            "font_sha256": "f" * 64,
                            "supported_codepoints": sorted({ord(char) for char in text}),
                        }
                    },
                    output_language=language,
                )
                payload = mapping["regions"][0]["overlays"][0]["payload"]
                self.assertEqual(payload["output_language"], language)
                self.assertEqual(payload["text"], text)
                self.assertEqual(payload["font_sha256"], "f" * 64)
                self.assertRegex(payload["glyph_coverage_sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(payload["verification_required"])

    def test_missing_glyph_and_wrong_language_block_readable_overlay_mapping(self) -> None:
        contract = _contract()
        region = {
            "region_id": "R01",
            "region_type": "generated",
            "source_start_us": 0,
            "source_end_us": 2_000_000,
        }
        with self.assertRaisesRegex(OverlayMappingError, "glyph"):
            build_overlay_render_mapping(
                contract,
                [region],
                replacements={
                    "cta-1": {
                        "text": "立即购买",
                        "language": "zh",
                        "font_sha256": "f" * 64,
                        "supported_codepoints": [ord("立")],
                    },
                    "brand-1": {
                        "asset_sha256": "a" * 64,
                        "artifact_kind": "target_logo",
                    },
                },
                output_language="zh",
            )
        with self.assertRaisesRegex(OverlayMappingError, "output_language"):
            build_overlay_render_mapping(
                contract,
                [region],
                replacements={
                    "cta-1": {
                        "text": "今すぐ購入",
                        "language": "en",
                        "font_sha256": "f" * 64,
                        "supported_codepoints": sorted({ord(char) for char in "今すぐ購入"}),
                    },
                    "brand-1": {
                        "asset_sha256": "a" * 64,
                        "artifact_kind": "target_logo",
                    },
                },
                output_language="ja",
            )

    def test_seedance_prompt_cannot_receive_readable_overlay_tokens(self) -> None:
        contract = _contract()
        with self.assertRaisesRegex(OverlayMappingError, "Seedance-readable-text"):
            build_overlay_render_mapping(
                contract,
                [
                    {
                        "region_id": "R01",
                        "region_type": "generated",
                        "source_start_us": 0,
                        "source_end_us": 2_000_000,
                        "segment_prompt": "Model holds product while text says SHOP NOW",
                    }
                ],
                replacements={
                    "cta-1": {"text": "SHOP NOW"},
                    "brand-1": {
                        "asset_sha256": "a" * 64,
                        "artifact_kind": "target_logo",
                    },
                },
            )

    def test_builder_copies_source_geometry_and_emits_target_owned_payloads(self) -> None:
        contract = _contract()
        mapping = build_overlay_render_mapping(
            contract,
            [
                {
                    "region_id": "R01",
                    "region_type": "generated",
                    "media_origin": "generated",
                    "assembly_policy": "generate_region",
                    "source_start_us": 0,
                    "source_end_us": 2_000_000,
                }
            ],
            replacements={
                "cta-1": {"text": "TARGET CTA", "color": "white", "font_size": 28},
                "brand-1": {
                    "render_mode": "deterministic_asset",
                    "asset_sha256": "a" * 64,
                    "artifact_kind": "target_logo",
                },
            },
        )
        self.assertEqual(mapping["contract"], "target-overlay-render-mapping")
        self.assertEqual(mapping["source_overlay_contract_sha256"], _sha(contract))
        entries = {row["overlay_id"]: row for row in mapping["regions"][0]["overlays"]}
        self.assertEqual(entries["cta-1"]["render_mode"], "deterministic_text")
        self.assertEqual(entries["cta-1"]["payload"]["text"], "TARGET CTA")
        self.assertEqual(entries["cta-1"]["payload_sha256"], _sha(entries["cta-1"]["payload"]))
        self.assertEqual(entries["cta-1"]["source_overlay"]["start_rect"], [0.1, 0.2, 0.8, 0.2])
        self.assertEqual(entries["brand-1"]["render_mode"], "deterministic_asset")
        self.assertEqual(entries["brand-1"]["asset_sha256"], "a" * 64)

    def test_brand_mark_cannot_be_silently_converted_to_text(self) -> None:
        contract = _contract()
        with self.assertRaises(OverlayMappingError):
            build_overlay_render_mapping(
                contract,
                [{"region_id": "R01", "region_type": "generated", "source_start_us": 0, "source_end_us": 2_000_000}],
                replacements={"brand-1": {"text": "FORGED WORDMARK"}},
            )

    def test_builder_accepts_a_logical_overlay_id_reused_across_adjacent_cuts(self) -> None:
        contract = _contract()
        contract["cuts"].append({
            "cut": 2,
            "start_us": 2_000_000,
            "end_us": 2_500_000,
            "source_overlays": [{
                **contract["cuts"][0]["source_overlays"][0],
                "start_us": 2_000_000,
                "end_us": 2_500_000,
                "start_rect": [0.12, 0.2, 0.76, 0.2],
                "end_rect": [0.12, 0.2, 0.76, 0.2],
                "keyframes": [
                    {"time_us": 2_000_000, "bbox": [0.12, 0.2, 0.76, 0.2], "rotation_deg": 0, "opacity": 1},
                    {"time_us": 2_500_000, "bbox": [0.12, 0.2, 0.76, 0.2], "rotation_deg": 0, "opacity": 1},
                ],
            }],
        })
        mapping = build_overlay_render_mapping(
            contract,
            [{"region_id": "R01", "region_type": "generated", "source_start_us": 0, "source_end_us": 2_500_000}],
            replacements={"cta-1": {"text": "TARGET CTA"}, "brand-1": {"asset_sha256": "a" * 64, "artifact_kind": "target_logo"}},
        )
        self.assertEqual([row["overlay_id"] for row in mapping["regions"][0]["overlays"]].count("cta-1"), 1)

    def test_builder_rejects_local_asset_path_by_default(self) -> None:
        with self.assertRaises(OverlayMappingError):
            build_overlay_render_mapping(
                _contract(),
                [{"region_id": "R01", "region_type": "generated", "source_start_us": 0, "source_end_us": 2_000_000}],
                replacements={"brand-1": {"asset_sha256": "a" * 64, "asset_path": "C:/client/logo.png"}},
            )


if __name__ == "__main__":
    unittest.main()
