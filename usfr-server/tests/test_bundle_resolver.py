from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from high_fidelity_profile import (  # noqa: E402
    build_profile_snapshot,
    validate_profile_snapshot,
)
from server.bundle_resolver import (  # noqa: E402
    BundleResolverError,
    ImmutableBundleResolver,
)
from server.errors import ReplicationError  # noqa: E402
from server.seedance_invocations import SeedanceInvocationAdapter  # noqa: E402
from activation_fixture import strict_activation_evidence  # noqa: E402


def _skill_bytes(name: str, version: str = "6.6.0") -> bytes:
    return (
        f"---\nname: {name}\nmetadata:\n  version: {version}\n---\n"
    ).encode("utf-8")


def _activation_evidence() -> dict:
    return {
        "shadow": {"status": "shadow", "case_count": 18, "provider_calls": 0, "user_approvals": 0, "paid_tasks": 0, "compatibility_pass": True},
        "matched_ab": {"case_count": 12, "average_fidelity_delta": 10, "compatibility_pass": True, "within_active_time_target": True, "meets_targets": True},
        "regression": {"case_count": 30, "passed": True, "hard_failures": 0, "ui_errors": 0, "claim_regressions": 0},
    }


def _candidate() -> dict:
    return {
        "candidate_region_id": "CR-01",
        "cut_ids": ["C01"],
        "required_factor_ids": ["HFH.C01.ACTION.ENDPOINT"],
        "allowed_split_cut_ids": [],
        "forbidden_split_cut_ids": ["C01"],
        "duration_ms": 8000,
        "primary_fidelity_spend": "motion",
        "secondary_fidelity_spend": "identity",
        "economized_factors": ["background_microtexture"],
        "mode": "fixed_b_image_reference",
        "single_take_or_multishot": "single_take",
        "shot_budget": [{
            "shot_id": "SHOT-01",
            "duration_ms": 8000,
            "primary_action": "open package",
            "endpoint": "package open",
        }],
        "reference_role_plan": [{"role": "storyboard", "slot": 1}],
        "background_strategy": "KEEP",
        "performance_strategy": {"gaze": "camera", "gesture": "two hands"},
        "action_state_requirements": [{"phase": "completed", "state": "package open", "required": True}],
        "audio_strategy": {"music_policy": "none", "ambience": "room tone", "foley_event_ids": [], "silence_window_ids": []},
        "voiceover_timing_plan": [],
        "prompt_carrier_plan": [],
        "postproduction_carrier_plan": [],
        "hard_blockers": [],
        "warnings": [],
    }


def _factor_coverage() -> list[dict]:
    return [{"factor_id": "HFH.C01.ACTION.ENDPOINT", "candidate_region_id": "CR-01", "source_pointer": "/source/C01/action/endpoint", "contract_pointer": "/contracts/source_fidelity_contract.json#/cuts/C01/action/endpoint", "carrier": "prompt", "criticality": "H"}]


class ImmutableBundleResolverTest(unittest.TestCase):
    def _resolver(self) -> ImmutableBundleResolver:
        return ImmutableBundleResolver({
            "seedance-20": {
                "bytes": _skill_bytes("seedance-20"),
                "version": "6.6.0",
                "package_path": "dependencies/seedance-20/SKILL.md",
            },
            "seedance-prompt": {
                "bytes": _skill_bytes("seedance-prompt"),
                "version": "6.6.0",
                "package_path": "dependencies/seedance-20/skills/seedance-prompt/SKILL.md",
            },
            "seedance-antislop": {
                "bytes": _skill_bytes("seedance-antislop"),
                "version": "6.6.0",
                "package_path": "dependencies/seedance-20/skills/seedance-antislop/SKILL.md",
            },
        })

    def test_resolver_is_immutable_and_path_free(self):
        resolver = self._resolver()
        self.assertTrue(resolver.immutable)
        self.assertEqual(resolver.get_bytes("seedance-20"), _skill_bytes("seedance-20"))
        self.assertEqual(resolver.metadata("seedance-20")["package_path"], "dependencies/seedance-20/SKILL.md")
        with self.assertRaises(TypeError):
            resolver.entries["seedance-20"] = {}  # type: ignore[index]
        with self.assertRaises(BundleResolverError):
            ImmutableBundleResolver({"seedance-20": Path("C:/Users/client/.codex/SKILL.md")})

    def test_object_resolver_materializes_verified_private_bytes(self):
        payload = _skill_bytes("seedance-20")

        class Reader:
            def read_bytes(self, object_key):
                self.object_key = object_key
                return payload

        reader = Reader()
        resolver = ImmutableBundleResolver.from_object_resolver(
            reader,
            {
                "seedance-20": {
                    "object_key": "s3://private/dependencies/seedance-20/SKILL.md",
                    "version": "6.6.0",
                    "package_path": "dependencies/seedance-20/SKILL.md",
                }
            },
        )
        self.assertEqual(reader.object_key, "s3://private/dependencies/seedance-20/SKILL.md")
        self.assertEqual(resolver.get_bytes("seedance-20"), payload)

    def test_package_manifest_materializes_verified_bundle_bytes(self):
        resolver = ImmutableBundleResolver.from_package_manifest(
            ROOT / "references" / "runtime_skill_manifest.json",
            package_root=ROOT,
        )
        self.assertEqual(resolver.metadata("seedance-20")["version"], "6.6.0")
        self.assertIn("seedance-prompt", resolver.names())
        self.assertTrue(resolver.get("seedance-20").package_path.startswith("runtime-skills/"))

    def test_profile_snapshot_build_and_validation_use_immutable_bytes(self):
        resolver = self._resolver()
        snapshot = build_profile_snapshot(
            "high_fidelity_hybrid_v1",
            resolver,
            {"activation_mode": "active", "activation_evidence": strict_activation_evidence(ROOT), "artifact": {"uri": "s3://private/run/profile.json"}},
            activation_evidence_verifier=lambda receipt: receipt,
        )
        validate_profile_snapshot(snapshot, resolver, activation_evidence_verifier=lambda receipt: receipt)
        self.assertEqual(snapshot["dependencies"][0]["package_path"], "dependencies/seedance-20/SKILL.md")

    def test_active_profile_rejects_path_dependency_map(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "SKILL.md"
            path.write_bytes(_skill_bytes("seedance-20"))
            with self.assertRaises(ValueError):
                build_profile_snapshot(
                    "high_fidelity_hybrid_v1",
                    {"seedance-20": path},
                    {"activation_mode": "active", "activation_evidence": strict_activation_evidence(ROOT), "artifact": {"uri": "s3://private/run/profile.json"}},
                    activation_evidence_verifier=lambda receipt: receipt,
                )

    def test_active_production_invocation_uses_resolver_and_rejects_local_path(self):
        resolver = self._resolver()
        adapter = SeedanceInvocationAdapter(bundle_resolver=resolver, production=True)
        artifact = adapter.invoke_a(
            route="route_2",
            candidate_regions=[_candidate()],
            line_contracts=[],
            factor_coverage=_factor_coverage(),
            input_digests={"source": "a" * 64},
        )
        self.assertEqual(artifact["compiler"]["skill"], "seedance-20")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "SKILL.md"
            path.write_bytes(_skill_bytes("seedance-20"))
            with self.assertRaises(ReplicationError):
                SeedanceInvocationAdapter(skill_file=path, production=True)


if __name__ == "__main__":
    unittest.main()
