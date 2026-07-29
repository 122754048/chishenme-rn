import json
from pathlib import Path
import sys
import tempfile
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from bind_input_slots import (  # noqa: E402
    InputSlotError,
    OPTIONAL_SLOTS,
    SLOT_ORDER,
    bind_slots,
    validate_slots,
)


class FixedInputSlotContractTest(unittest.TestCase):
    def _files(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "source.mp4").write_bytes(b"source-video")
        (root / "product.png").write_bytes(b"product-image")
        (root / "model.jpg").write_bytes(b"model-image")
        (root / "screen.png").write_bytes(b"ui-image")
        (root / "ui.mp4").write_bytes(b"ui-video")
        (root / "tail.mp4").write_bytes(b"tail-video")
        (root / "song.mp3").write_bytes(b"uploaded-song")
        return tmp, root

    def test_source_only_is_blocked_before_formal_manifest(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        report = validate_slots({"source_video": root / "source.mp4"})
        self.assertFalse(report["admission"]["can_proceed"])
        self.assertEqual(
            report["admission"]["blocker_code"],
            "MIN_ONE_OPTIONAL_INPUT_REQUIRED",
        )
        with self.assertRaisesRegex(InputSlotError, "MIN_ONE_OPTIONAL_INPUT_REQUIRED"):
            bind_slots({"source_video": root / "source.mp4"})

    def test_source_plus_output_language_admits_language_only_run(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        manifest = bind_slots(
            {"source_video": root / "source.mp4"},
            output_language="zh",
        )
        self.assertTrue(manifest["admission"]["can_proceed"])
        self.assertEqual(manifest["admission"]["minimum_optional_slots"], 0)
        self.assertEqual(manifest["admission"]["optional_present_count"], 0)
        self.assertTrue(manifest["admission"]["language_only"])
        self.assertEqual(manifest["output_language"], "zh")
        self.assertEqual(manifest["routes"]["product"], "source_preserve")
        self.assertEqual(manifest["routes"]["character"], "source_preserve")
        self.assertEqual(manifest["routes"]["ui"], "source_ui_keep")
        self.assertEqual(manifest["routes"]["tail"], "omit_source_end_card")

    def test_background_music_is_an_optional_extension_not_an_eighth_slot(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)

        manifest = bind_slots(
            {"source_video": root / "source.mp4"},
            background_music=root / "song.mp3",
        )

        self.assertTrue(manifest["admission"]["can_proceed"])
        self.assertFalse(manifest["admission"]["language_only"])
        self.assertEqual(manifest["slot_order"], list(SLOT_ORDER))
        self.assertNotIn("background_music", manifest["slots"])
        music = manifest["extensions"]["background_music"]
        self.assertEqual(music["extension_id"], "input_contract_v2.background_music")
        self.assertEqual(music["provider_route"], "seedance_audio_reference")
        self.assertTrue(music["sha256"])
        self.assertEqual(manifest["routes"]["background_music"], "seedance_audio_reference")
        schema = json.loads(
            (ROOT / "schemas" / "input_slots.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.validate(manifest, schema)

    def test_invalid_output_language_is_rejected(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        with self.assertRaisesRegex(InputSlotError, "output_language"):
            validate_slots({"source_video": root / "source.mp4"}, output_language="xx")

    def test_output_language_can_be_supplied_in_input_mapping(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        manifest = bind_slots(
            {
                "source_video": root / "source.mp4",
                "output_language": "JA",
            }
        )
        self.assertTrue(manifest["admission"]["language_only"])
        self.assertEqual(manifest["output_language"], "ja")

    def test_one_valid_optional_slot_admits_run_and_defaults_missing_slots(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        manifest = bind_slots(
            {
                "source_video": root / "source.mp4",
                "new_product_image": root / "product.png",
            }
        )
        self.assertIn("admission", manifest)
        self.assertTrue(manifest["admission"]["can_proceed"])
        self.assertEqual(manifest["admission"]["optional_present_count"], 1)
        self.assertEqual(manifest["routes"]["product"], "replace_from_slot")
        self.assertEqual(manifest["routes"]["character"], "source_preserve")
        self.assertEqual(manifest["routes"]["ui"], "source_ui_keep")
        self.assertEqual(manifest["routes"]["tail"], "omit_source_end_card")

    def test_fixed_slot_role_is_used_without_filename_classification(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        renamed = root / "anything.bin"
        renamed.write_bytes(b"image-payload")
        with self.assertRaisesRegex(InputSlotError, "image file"):
            bind_slots(
                {
                    "source_video": root / "source.mp4",
                    "new_product_image": renamed,
                }
            )

    def test_unknown_slot_is_rejected(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        with self.assertRaisesRegex(InputSlotError, "unknown input slot"):
            validate_slots(
                {
                    "source_video": root / "source.mp4",
                    "some_other_file": root / "product.png",
                }
            )

    def test_slot_types_and_hashes_are_stable(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        first = bind_slots(
            {
                "source_video": root / "source.mp4",
                "ui_operation_video": root / "ui.mp4",
            }
        )
        second = bind_slots(
            {
                "source_video": root / "source.mp4",
                "ui_operation_video": root / "ui.mp4",
            }
        )
        self.assertEqual(first, second)
        self.assertIn("slot_order", first)
        self.assertEqual(first["slot_order"], list(SLOT_ORDER))
        self.assertEqual(first["slots"]["ui_operation_video"]["role"], "opaque_ui_demo")
        self.assertTrue(first["slots"]["source_video"]["sha256"])

    def test_ui_route_priority_is_deterministic(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        opaque = bind_slots(
            {
                "source_video": root / "source.mp4",
                "ui_screenshot": root / "screen.png",
                "ui_operation_video": root / "ui.mp4",
            }
        )
        generated = bind_slots(
            {
                "source_video": root / "source.mp4",
                "ui_screenshot": root / "screen.png",
            }
        )
        self.assertIn("routes", opaque)
        self.assertIn("routes", generated)
        self.assertEqual(opaque["routes"]["ui"], "opaque_ui_demo")
        self.assertEqual(generated["routes"]["ui"], "generated_ui_demo")

    def test_app_store_url_is_a_fixed_url_slot(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        manifest = bind_slots(
            {
                "source_video": root / "source.mp4",
                "app_store_url": "https://apps.apple.com/us/app/example/id123456789",
            }
        )
        self.assertIn("slots", manifest)
        self.assertEqual(manifest["slots"]["app_store_url"]["role"], "app_store_evidence")
        self.assertEqual(manifest["routes"]["ui"], "generated_ui_demo")

    def test_google_play_url_is_a_fixed_url_slot(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        manifest = bind_slots(
            {
                "source_video": root / "source.mp4",
                "app_store_url": "https://play.google.com/store/apps/details?id=com.example.social",
            }
        )
        self.assertTrue(manifest["slots"]["app_store_url"]["valid"])
        self.assertEqual(manifest["slots"]["app_store_url"]["role"], "app_store_evidence")

    def test_single_value_slots_reject_multiple_values(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        with self.assertRaisesRegex(InputSlotError, "only accepts one value"):
            validate_slots(
                {
                    "source_video": [root / "source.mp4", root / "source.mp4"],
                    "new_product_image": root / "product.png",
                }
            )

    def test_all_fixed_slots_are_declared_and_optional_count_is_six(self):
        self.assertEqual(len(OPTIONAL_SLOTS), 6)
        self.assertEqual(len(SLOT_ORDER), 7)
        self.assertEqual(SLOT_ORDER[0], "source_video")

    def test_manifest_can_be_written_as_json(self):
        tmp, root = self._files()
        self.addCleanup(tmp.cleanup)
        output = root / "analysis" / "input_slots.json"
        manifest = bind_slots(
            {
                "source_video": root / "source.mp4",
                "tail_video": root / "tail.mp4",
            },
            output_path=output,
        )
        self.assertTrue(output.is_file())
        self.assertIsInstance(manifest, dict)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), manifest)
        self.assertEqual(manifest["routes"]["tail"], "opaque_app_tail_card")


if __name__ == "__main__":
    unittest.main()
