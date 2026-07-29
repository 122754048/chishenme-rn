import sys
import tempfile
import unittest
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "bundled-skills" / "seedance-storyboard-replication" / "scripts"))

from high_fidelity_profile import (  # noqa: E402
    build_profile_snapshot,
    validate_profile_snapshot,
)
from seedance_prescript import (  # noqa: E402
    build_prescript_artifact,
    validate_prescript_artifact,
)


class PayloadError(ValueError):
    pass


def validate_prescript_snapshot_file(prescript_path: Path, skill_file: Path) -> None:
    try:
        artifact = json.loads(prescript_path.read_text(encoding="utf-8-sig"))
        compiler = artifact.get("compiler") if isinstance(artifact, dict) else None
        inputs = compiler.get("input_digests") if isinstance(compiler, dict) else {}
        validate_prescript_artifact(artifact, skill_file, inputs)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PayloadError(str(error)) from error


def validate_profile_snapshot_file(snapshot_path: Path, skill_file: Path) -> None:
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        validate_profile_snapshot(snapshot, {"seedance-20": skill_file})
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PayloadError(str(error)) from error


class SeedanceProfileBridgeTest(unittest.TestCase):
    def _candidate(self):
        return {
            "candidate_region_id": "CR-01",
            "cut_ids": ["C01"],
            "allowed_split_cut_ids": [],
            "forbidden_split_cut_ids": ["C01"],
            "duration_ms": 4000,
            "primary_fidelity_spend": "motion",
            "secondary_fidelity_spend": "identity",
            "economized_factors": [],
            "mode": "fixed_b_image_reference",
            "single_take_or_multishot": "single_take",
            "shot_budget": [{"shot_id": "SHOT-01", "duration_ms": 4000, "primary_action": "open package", "endpoint": "package open"}],
            "reference_role_plan": [{"role": "storyboard", "slot": 1}],
            "background_strategy": "KEEP",
            "performance_strategy": {"gaze": "camera"},
            "action_state_requirements": [{"phase": "completed", "state": "package open", "required": True}],
            "audio_strategy": {"music_policy": "none", "ambience": "room tone", "foley_event_ids": [], "silence_window_ids": []},
            "voiceover_timing_plan": [],
            "prompt_carrier_plan": [],
            "postproduction_carrier_plan": [],
            "hard_blockers": [],
            "warnings": [],
        }

    def test_prescript_bridge_rejects_mutated_payload_without_output_digest_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text(
                "---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n",
                encoding="utf-8",
            )
            artifact = build_prescript_artifact(
                route="route_2",
                candidate_regions=[],
                line_contracts=[],
                factor_coverage=[],
                skill_file=skill,
                input_digests={"source_fidelity_contract": "a" * 64},
            )
            artifact["candidate_regions"].append(
                {
                    "candidate_region_id": "region-1",
                    "cut_ids": ["C1"],
                    "duration_ms": 4000,
                    "primary_fidelity_spend": "motion",
                    "reference_role_plan": [],
                }
            )
            prescript = root / "prescript.json"
            prescript.write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_prescript_snapshot_file(prescript, skill)

    def test_prescript_bridge_revalidates_execution_fields_after_a_valid_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            artifact = build_prescript_artifact(
                route="route_2",
                candidate_regions=[self._candidate()],
                line_contracts=[],
                factor_coverage=[],
                skill_file=skill,
                input_digests={},
            )
            del artifact["candidate_regions"][0]["background_strategy"]
            canonical = json.loads(json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            canonical["compiler"].pop("output_sha256", None)
            artifact["compiler"]["output_sha256"] = hashlib.sha256(
                json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            prescript = root / "prescript.json"
            prescript.write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaisesRegex(PayloadError, "background_strategy"):
                validate_prescript_snapshot_file(prescript, skill)

    def test_profile_snapshot_bridge_checks_seedance_bytes_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            snapshot = build_profile_snapshot("high_fidelity_hybrid_v1", {"seedance-20": skill}, {"artifact": {"uri": "s3://private/profile.json"}})
            profile = root / "profile.json"
            import json
            profile.write_text(json.dumps(snapshot), encoding="utf-8")
            validate_profile_snapshot_file(profile, skill)
            skill.write_text(skill.read_text(encoding="utf-8") + "changed", encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_profile_snapshot_file(profile, skill)

    def test_prescript_bridge_rejects_wrong_skill_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            prescript = root / "prescript.json"
            prescript.write_text('{"profile":"seedance20_prescript_v1","compiler":{"skill_sha256":"' + "0" * 64 + '","version":"6.6.0"}}', encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_prescript_snapshot_file(prescript, skill)

    def test_profile_bridge_rejects_artifact_hash_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            snapshot = build_profile_snapshot("high_fidelity_hybrid_v1", {"seedance-20": skill}, {"artifact": {"uri": "s3://private/profile.json"}})
            snapshot["artifact"]["sha256"] = "0" * 64
            profile = root / "profile.json"
            import json
            profile.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_profile_snapshot_file(profile, skill)

    def test_profile_bridge_rejects_snapshot_version_that_disagrees_with_skill_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            snapshot = build_profile_snapshot(
                "high_fidelity_hybrid_v1",
                {"seedance-20": skill},
                {
                    "dependency_versions": {"seedance-20": "6.5.0"},
                    "artifact": {"uri": "s3://private/profile.json"},
                },
            )
            profile = root / "profile.json"
            import json
            profile.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_profile_snapshot_file(profile, skill)

    def test_profile_bridge_rejects_stale_profile_schema_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            snapshot = build_profile_snapshot("high_fidelity_hybrid_v1", {"seedance-20": skill}, {"artifact": {"uri": "s3://private/profile.json"}})
            snapshot["schema_sha256"] = "0" * 64
            canonical = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            canonical.pop("snapshot_sha256", None)
            canonical["artifact"].pop("sha256", None)
            digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            snapshot["snapshot_sha256"] = digest
            snapshot["artifact"]["sha256"] = digest
            profile = root / "profile.json"
            profile.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_profile_snapshot_file(profile, skill)

    def test_profile_bridge_rejects_local_artifact_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            snapshot = build_profile_snapshot("high_fidelity_hybrid_v1", {"seedance-20": skill}, {"artifact": {"uri": "s3://private/profile.json"}})
            snapshot["artifact"]["uri"] = str(root / "profile.json")
            canonical = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            canonical.pop("snapshot_sha256", None)
            canonical["artifact"].pop("sha256", None)
            digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            snapshot["snapshot_sha256"] = digest
            snapshot["artifact"]["sha256"] = digest
            profile = root / "profile.json"
            profile.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_profile_snapshot_file(profile, skill)

    def test_profile_bridge_rejects_local_dependency_path_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            snapshot = build_profile_snapshot("high_fidelity_hybrid_v1", {"seedance-20": skill}, {"artifact": {"uri": "s3://private/profile.json"}})
            snapshot["dependencies"][0]["source_path"] = str(skill)
            canonical = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            canonical.pop("snapshot_sha256", None)
            canonical["artifact"].pop("sha256", None)
            digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            snapshot["snapshot_sha256"] = digest
            snapshot["artifact"]["sha256"] = digest
            profile = root / "profile.json"
            profile.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_profile_snapshot_file(profile, skill)

    def test_profile_bridge_rejects_unknown_profile_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            snapshot = build_profile_snapshot("high_fidelity_hybrid_v1", {"seedance-20": skill}, {"artifact": {"uri": "s3://private/profile.json"}})
            snapshot["revision"] = 2
            canonical = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            canonical.pop("snapshot_sha256", None)
            canonical["artifact"].pop("sha256", None)
            digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            snapshot["snapshot_sha256"] = digest
            snapshot["artifact"]["sha256"] = digest
            profile = root / "profile.json"
            profile.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_profile_snapshot_file(profile, skill)

    def test_profile_bridge_rejects_invalid_parent_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: seedance-20\nmetadata:\n  version: 6.6.0\n---\n", encoding="utf-8")
            snapshot = build_profile_snapshot("high_fidelity_hybrid_v1", {"seedance-20": skill}, {"parent_digests": {"source": "a" * 64}, "artifact": {"uri": "s3://private/profile.json"}})
            snapshot["parent_digests"]["source"] = "a" * 63 + "G"
            canonical = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            canonical.pop("snapshot_sha256", None)
            canonical["artifact"].pop("sha256", None)
            digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            snapshot["snapshot_sha256"] = digest
            snapshot["artifact"]["sha256"] = digest
            profile = root / "profile.json"
            profile.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(PayloadError):
                validate_profile_snapshot_file(profile, skill)


if __name__ == "__main__":
    unittest.main()
