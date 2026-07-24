"""Contract tests for the additive high-fidelity execution profile.

These tests intentionally exercise the snapshot boundary rather than any
workflow route.  A profile snapshot is internal run metadata: it must pin the
dependency bytes used by Invocation A/B while remaining safe to persist in a
server/object-store artifact and must not widen the public seven-slot API.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from high_fidelity_profile import (  # noqa: E402
    ProfileSnapshotError,
    build_profile_snapshot,
    validate_profile_snapshot,
)


class HighFidelityProfileSnapshotTest(unittest.TestCase):
    def _dependency(self, root: Path, *, version: str = "6.6.0") -> Path:
        path = root / "seedance-20" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            "name: seedance-20\n"
            f"metadata:\n  version: \"{version}\"\n"
            "---\n\nPinned skill bytes.\n",
            encoding="utf-8",
        )
        return path

    def test_snapshot_has_exact_profile_and_does_not_add_public_contract_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependency = self._dependency(root)
            snapshot = build_profile_snapshot(
                "high_fidelity_hybrid_v1",
                {"seedance-20": dependency},
                {
                    "activation_mode": "shadow",
                    "parent_digests": {
                        "source_fidelity_contract_sha256": "a" * 64,
                    },
                    "artifact": {
                        "tenant_id": "tenant-1",
                        "run_id": "run-1",
                        "uri": "s3://private-bucket/run-1/profile.json",
                    },
                },
            )

            self.assertEqual(snapshot["profile"], "high_fidelity_hybrid_v1")
            self.assertEqual(snapshot["schema_version"], "high-fidelity-profile/v1")
            self.assertEqual(snapshot["activation_mode"], "shadow")
            self.assertEqual(snapshot["dependencies"][0]["name"], "seedance-20")
            self.assertEqual(snapshot["dependencies"][0]["version"], "6.6.0")
            self.assertNotIn("slots", snapshot)
            self.assertNotIn("routes", snapshot)
            self.assertNotIn("run_state", snapshot)
            self.assertNotIn("stages", snapshot)

    def test_snapshot_pins_exact_dependency_bytes_and_uses_object_store_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependency = self._dependency(root)
            expected_digest = hashlib.sha256(dependency.read_bytes()).hexdigest()
            snapshot = build_profile_snapshot(
                "high_fidelity_hybrid_v1",
                {"seedance-20": dependency},
                {
                    "artifact": {
                        "tenant_id": "tenant-1",
                        "run_id": "run-1",
                        "uri": "s3://private-bucket/run-1/profile.json",
                    }
                },
            )
            dependency_record = snapshot["dependencies"][0]
            self.assertEqual(dependency_record["sha256"], expected_digest)
            self.assertEqual(dependency_record["package_path"], "seedance-20/SKILL.md")
            self.assertNotIn(str(root), json.dumps(snapshot))
            self.assertEqual(snapshot["artifact"]["uri"], "s3://private-bucket/run-1/profile.json")
            self.assertTrue(snapshot["artifact"]["sha256"])

    def test_snapshot_rejects_noncanonical_activation_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependency = self._dependency(root)
            with self.assertRaisesRegex(ProfileSnapshotError, "activation_mode"):
                build_profile_snapshot(
                    "high_fidelity_hybrid_v1",
                    {"seedance-20": dependency},
                    {
                        "activation_mode": "ACTIVE",
                        "artifact": {"uri": "s3://private/run/profile.json"},
                    },
                )

    def test_stale_dependency_snapshot_fails_before_invocation_b(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependency = self._dependency(root)
            snapshot = build_profile_snapshot(
                "high_fidelity_hybrid_v1",
                {"seedance-20": dependency},
                {"artifact": {"uri": "s3://private/run/profile.json"}},
            )
            validate_profile_snapshot(snapshot, {"seedance-20": dependency})
            dependency.write_text(dependency.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
            with self.assertRaises(ProfileSnapshotError):
                validate_profile_snapshot(snapshot, {"seedance-20": dependency})

    def test_legacy_run_without_profile_snapshot_bypasses_validation(self):
        # Existing runs created before the profile have no snapshot and must
        # continue through the unchanged legacy path.
        self.assertIsNone(validate_profile_snapshot(None, {}))
        self.assertIsNone(validate_profile_snapshot({}, {}))

    def test_wrong_profile_name_and_missing_dependency_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependency = self._dependency(root)
            with self.assertRaises(ProfileSnapshotError):
                build_profile_snapshot("legacy", {"seedance-20": dependency}, {})
            snapshot = build_profile_snapshot(
                "high_fidelity_hybrid_v1",
                {"seedance-20": dependency},
                {"artifact": {"uri": "s3://private/run/profile.json"}},
            )
            with self.assertRaises(ProfileSnapshotError):
                validate_profile_snapshot(snapshot, {})

    def test_package_paths_cannot_escape_the_packaged_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependency = self._dependency(root)
            with self.assertRaises(ProfileSnapshotError):
                build_profile_snapshot(
                    "high_fidelity_hybrid_v1",
                    {
                        "seedance-20": {
                            "path": dependency,
                            "package_path": "/outside/SKILL.md",
                        }
                    },
                    {"artifact": {"uri": "s3://private/run/profile.json"}},
                )



if __name__ == "__main__":
    unittest.main()
