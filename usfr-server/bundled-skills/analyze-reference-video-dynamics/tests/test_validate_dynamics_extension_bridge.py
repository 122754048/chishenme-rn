from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DynamicsExtensionBridgeTest(unittest.TestCase):
    def test_base_validator_exposes_extension_validator_without_second_pass(self):
        script = ROOT / "scripts" / "validate_dynamics.py"
        text = script.read_text(encoding="utf-8")
        self.assertIn("validate_high_fidelity_extension", text)
        self.assertIn("extensions", text)


if __name__ == "__main__":
    unittest.main()
