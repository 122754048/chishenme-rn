import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from skill_router import SkillRouteError, build_skill_route  # noqa: E402


class SkillRouterContractTest(unittest.TestCase):
    def test_local_only_route_skips_seedance_and_provider_skills(self):
        route = build_skill_route(
            generated_regions=0,
            factors={"camera": True, "audio": True},
            overlay_required=False,
            app_store_url_present=False,
        )
        self.assertEqual(
            route["modules"],
            ["analyze-reference-video-dynamics"],
        )
        self.assertEqual(route["provider_modules"], [])
        self.assertEqual(route["analysis_pass_count"], 1)

    def test_local_only_route_does_not_parse_app_store_when_no_generated_ui_can_use_it(self):
        route = build_skill_route(
            generated_regions=0,
            factors={"audio": True},
            overlay_required=False,
            app_store_url_present=True,
        )
        self.assertEqual(route["modules"], ["analyze-reference-video-dynamics"])
        self.assertNotIn("parse-app-store-evidence", route["dependency_snapshot"])

    def test_generated_route_selects_only_needed_seedance_specialists(self):
        route = build_skill_route(
            generated_regions=1,
            factors={
                "camera": True,
                "motion": True,
                "lighting": False,
                "performance": True,
                "audio": True,
                "multi_shot": False,
            },
            overlay_required=True,
            app_store_url_present=True,
        )
        self.assertEqual(
            route["modules"],
            [
                "analyze-reference-video-dynamics",
                "replicate-source-ui-overlays",
                "parse-app-store-evidence",
                "seedance-storyboard-replication",
                "seedance-20",
                "seedance-prompt",
                "seedance-antislop",
                "seedance-characters",
                "seedance-camera",
                "seedance-motion",
                "seedance-audio",
            ],
        )
        self.assertEqual(route["provider_modules"], ["seedance-storyboard-replication"])
        self.assertTrue(route["dependency_snapshot"]["seedance-20"]["package_path"].startswith("dependencies/"))
        self.assertFalse(any("\\" in item["package_path"] or item["package_path"].startswith("/") for item in route["dependency_snapshot"].values()))

    def test_two_regions_or_multishot_adds_sequence_skill_once(self):
        route = build_skill_route(
            generated_regions=2,
            factors={"multi_shot": True},
            overlay_required=False,
            app_store_url_present=False,
        )
        self.assertEqual(route["modules"].count("seedance-sequence"), 1)
        self.assertLess(route["modules"].index("seedance-prompt"), route["modules"].index("seedance-sequence"))

    def test_invalid_region_count_and_absolute_dependency_are_rejected(self):
        with self.assertRaises(SkillRouteError):
            build_skill_route(generated_regions=3, factors={})
        with self.assertRaises(SkillRouteError):
            build_skill_route(
                generated_regions=1,
                factors={},
                dependency_root="C:\\Users\\zhaocx04\\.codex\\skills",
            )

    def test_route_is_deterministic_and_cacheable(self):
        kwargs = dict(
            generated_regions=1,
            factors={"audio": True, "camera": True},
            overlay_required=False,
            app_store_url_present=False,
        )
        first = build_skill_route(**kwargs)
        second = build_skill_route(**kwargs)
        self.assertEqual(first, second)
        self.assertRegex(first["route_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
