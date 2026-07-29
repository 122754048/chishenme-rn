import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from line_contract import (  # noqa: E402
    canonical_line,
    line_digest,
    render_line_for_prompt,
    render_no_speech,
    rebind_line_contracts,
    validate_line_contracts,
)


def _line():
    return {
        "line_id": "VO-001",
        "cut_id": "C01",
        "source_content_timeline_sha256": "a" * 64,
        "content_type": "spoken",
        "speaker_assignment": {
            "status": "CONFIRMED",
            "speaker_id": "CHARACTER_A",
            "role": "creator",
            "visibility": "on_camera",
            "confidence": 0.94,
            "evidence_sha256": "b" * 64,
        },
        "candidate_region_id": "CR-01",
        "segment_id": None,
        "speaker": {
            "id": "CHARACTER_A",
            "role": "creator",
            "visibility": "on_camera",
            "voice_policy": "generic rights-cleared target voice; no source voice imitation",
        },
        "language": {"bcp47": "en-US", "script": "Latn"},
        "time": {
            "time_base": "output_global_ms",
            "start_ms": 200,
            "end_ms": 1850,
            "duration_ms": 1650,
            "duration_is_derived": True,
            "segment_start_ms": None,
            "segment_end_ms": None,
            "cut_ids": ["C01"],
            "cross_cut_reason": None,
            "planned_safe_margin_ms": 250,
        },
        "text": {"exact": "All right, let's open it.", "normalized": "all right let's open it", "pronunciation_notes": []},
        "delivery": {"tone": "close-mic conversational", "pace": "brisk", "emphasis": ["open"], "volume": "natural", "breath": "single breath group", "mic_distance": "close", "accent_or_locale": "natural target locale"},
        "lip_sync": {"priority": "high", "face_visibility": "clear frontal mouth", "occlusion": "none", "head_motion_limit": "small", "articulation": "clear", "allowed_tolerance_ms": 200, "speaker_face_ref": "CHARACTER_A"},
        "proof_events": [
            {
                "id": "PROOF-001",
                "kind": "package_contact",
                "modality": ["visual", "audio"],
                "start_ms": 1900,
                "end_ms": 2050,
                "claim_ids": ["CLM-001"],
                "required": True,
                "hard_fail": True,
            }
        ],
        "foley_events": [
            {
                "id": "FOLEY-001",
                "kind": "package_friction",
                "start_ms": 2100,
                "end_ms": 2350,
                "relation": "after_line",
                "onset_tolerance_ms": 200,
                "required": True,
                "loudness_policy": "audible_but_does_not_mask_dialogue",
            }
        ],
        "silence_windows": [
            {
                "id": "SIL-001",
                "start_ms": 1850,
                "end_ms": 2100,
                "kind": "post_line_pause",
                "min_quiet_dbfs": -30.0,
                "required": True,
            }
        ],
        "music_policy": {"mode": "none", "windows": []},
        "claim_ids": ["CLM-001"],
        "qc_contract": {"asr_profile": "en-US-canonical-v1", "speaker_check": "role", "language_check": "BCP-47 detector en-US", "line_tolerance_ms": 350, "proof_sync_tolerance_ms": 200, "foley_sync_tolerance_ms": 200, "hard_fail_flags": ["word_change"]},
        "criticality": "H",
    }


class LineContractTest(unittest.TestCase):
    def test_rejects_pending_speaker_assignment_from_source_content_timeline(self):
        value = _line()
        value["speaker_assignment"] = {
            "status": "PENDING_ASSIGNMENT",
            "reason": "multiple_visible_lip_sync_candidates",
            "candidate_speaker_ids": ["CHARACTER_A", "CHARACTER_B"],
        }

        with self.assertRaisesRegex(ValueError, "PENDING_ASSIGNMENT"):
            canonical_line(value)

    def test_rejects_confirmed_assignment_that_changes_the_approved_speaker(self):
        value = _line()
        value["speaker_assignment"]["speaker_id"] = "CHARACTER_B"

        with self.assertRaisesRegex(ValueError, "speaker_assignment.*speaker.id"):
            canonical_line(value)

    def test_duration_is_derived_and_prompt_repeats_exact_text(self):
        line = canonical_line(_line())
        self.assertEqual(line["time"]["duration_ms"], 1650)
        prompt = render_line_for_prompt(line)
        self.assertIn('says exactly, "All right, let\'s open it."', prompt)
        self.assertIn("close-mic", prompt)
        self.assertIn("Lip-sync high", prompt)
        self.assertIn("FOLEY-001", prompt)
        self.assertIn("SIL-001", prompt)
        self.assertIn("No music", prompt)

    def test_rejects_duration_or_text_mutation(self):
        value = _line()
        value["time"]["duration_ms"] = 1
        with self.assertRaises(ValueError):
            canonical_line(value)
        value = _line()
        value["text"]["normalized"] = "different"
        with self.assertRaises(ValueError):
            canonical_line(value)

    def test_rejects_hans_dialogue_with_question_mark_placeholders(self):
        value = _line()
        value["language"] = {"bcp47": "zh-CN", "script": "Hans"}
        value["text"] = {"exact": "????", "normalized": "", "pronunciation_notes": []}

        with self.assertRaisesRegex(ValueError, "language text degradation"):
            canonical_line(value)

    def test_rejects_unauthorised_voice_reference_and_duplicate_ids(self):
        value = _line()
        value["speaker"]["voice_policy"] = "copy source voiceprint"
        with self.assertRaises(ValueError):
            validate_line_contracts([value])
        with self.assertRaises(ValueError):
            validate_line_contracts([_line(), copy.deepcopy(_line())])

    def test_no_speech_contract_is_explicit_and_canonical(self):
        no_speech = {"cut_id": "C02", "speech_mode": "none", "silence_windows": [], "allowed_audio": ["room tone"], "forbidden_audio": ["new dialogue", "background music"]}
        validate_line_contracts([], no_speech_cuts=[no_speech])
        self.assertEqual(render_no_speech(no_speech), "No dialogue")

    def test_rebind_rejects_boundary_crossing_line(self):
        with self.assertRaises(ValueError):
            rebind_line_contracts([_line()], [{"segment_id": "S01", "start_ms": 0, "end_ms": 1000, "cut_ids": ["C01"]}])

    def test_rebind_maps_proof_foley_silence_and_prompt_times_to_segment_local(self):
        line = _line()
        line["time"].update({"start_ms": 1200, "end_ms": 1850, "duration_ms": 650})
        line["proof_events"][0].update({"start_ms": 1900, "end_ms": 2050})
        line["foley_events"][0].update({"start_ms": 2100, "end_ms": 2350})
        line["silence_windows"][0].update({"start_ms": 1850, "end_ms": 1900})
        rebound = rebind_line_contracts(
            [line],
            [{"segment_id": "S01", "start_ms": 1000, "end_ms": 3000, "cut_ids": ["C01"]}],
        )[0]
        self.assertEqual(rebound["time"]["segment_start_ms"], 200)
        self.assertEqual(rebound["time"]["segment_end_ms"], 850)
        self.assertEqual(rebound["proof_events"][0]["segment_start_ms"], 900)
        self.assertEqual(rebound["foley_events"][0]["segment_start_ms"], 1100)
        self.assertEqual(rebound["silence_windows"][0]["segment_end_ms"], 900)
        self.assertIn("Dialogue 0.20-0.85s", render_line_for_prompt(rebound))

    def test_digest_changes_on_semantic_mutation(self):
        first = line_digest(_line())
        changed = _line()
        changed["text"]["exact"] = "All right, let's close it."
        changed["text"]["normalized"] = "all right let's close it"
        self.assertNotEqual(first, line_digest(changed))

    def test_rejects_missing_delivery_lip_sync_audio_or_qc_fields(self):
        cases = (
            ("delivery", "tone"),
            ("lip_sync", "allowed_tolerance_ms"),
            ("proof_events", "id"),
            ("foley_events", "loudness_policy"),
            ("silence_windows", "min_quiet_dbfs"),
            ("music_policy", "mode"),
            ("qc_contract", "asr_profile"),
        )
        for section, field in cases:
            value = _line()
            target = value[section][0] if isinstance(value[section], list) else value[section]
            del target[field]
            with self.subTest(section=section, field=field), self.assertRaisesRegex(ValueError, field):
                canonical_line(value)

    def test_approved_line_freezes_complete_performance_and_audio_contract(self):
        mutations = (
            ("delivery", "tone", "generic"),
            ("lip_sync", "priority", "low"),
            ("proof_events", "start_ms", 1950),
            ("foley_events", "loudness_policy", "loud"),
            ("silence_windows", "min_quiet_dbfs", -10.0),
            ("music_policy", "mode", "approved"),
            ("qc_contract", "line_tolerance_ms", 999),
        )
        approved = _line()
        for section, field, replacement in mutations:
            value = _line()
            target = value[section][0] if isinstance(value[section], list) else value[section]
            target[field] = replacement
            with self.subTest(section=section, field=field), self.assertRaisesRegex(ValueError, "approved line mutation"):
                validate_line_contracts([value], approved_lines=[approved])

    def test_final_line_set_cannot_drop_an_approved_line(self):
        with self.assertRaisesRegex(ValueError, "approved line set"):
            validate_line_contracts([], approved_lines=[_line()])

    def test_exact_line_schema_requires_execution_contract_fields(self):
        from jsonschema import Draft202012Validator

        schema_path = ROOT / "schemas" / "exact_line_contract.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(_line())


if __name__ == "__main__":
    unittest.main()
