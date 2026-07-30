from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping


class UserDirectorStoryboardError(ValueError):
    pass


REQUIRED_ANCHORS = (
    "Use case: infographic-diagram",
    "Primary request:",
    "Layout contract: usfr-professional-director-board/v1",
    "Fixed layout:",
    "Storyboard cards:",
    "Exact allowed text:",
    "Text constraints:",
    "Avoid:",
)
REQUIRED_LAYOUT_REGIONS = (
    "direction_header:",
    "character_target_column:",
    "storyboard_grid:",
    "camera_column:",
    "continuity_footer:",
)
FORBIDDEN_GENERIC_LAYOUTS = (
    "generic seven-panel grid",
    "ordinary seven-grid",
    "seven equal panels",
)
CUT_CARD_PATTERN = re.compile(r"^\s*\d+\.\s+Cut\s+(C\d{2})\s*,", re.MULTILINE)
CUT_ID_PATTERN = re.compile(r"\bC\d{2}\b")


def validate_user_director_storyboard(
    prompt: str, scope_receipt: Mapping[str, Any]
) -> dict[str, Any]:
    if scope_receipt.get("status") != "passed":
        raise UserDirectorStoryboardError("director storyboard requires a passed timeline scope receipt")

    expected = scope_receipt.get("allowed_cut_ids")
    if not isinstance(expected, list) or not expected or any(not isinstance(item, str) for item in expected):
        raise UserDirectorStoryboardError("director storyboard scope has no allowed Cut IDs")

    missing = [anchor for anchor in REQUIRED_ANCHORS if anchor not in prompt]
    missing.extend(region for region in REQUIRED_LAYOUT_REGIONS if region not in prompt)
    if missing:
        raise UserDirectorStoryboardError("director storyboard layout is incomplete: " + ", ".join(missing))

    normalized = " ".join(prompt.casefold().split())
    generic = [pattern for pattern in FORBIDDEN_GENERIC_LAYOUTS if pattern in normalized]
    if generic:
        raise UserDirectorStoryboardError("director storyboard generic layout is forbidden: " + ", ".join(generic))

    card_ids = CUT_CARD_PATTERN.findall(prompt)
    if card_ids != expected:
        raise UserDirectorStoryboardError(
            "director storyboard Cut coverage must match the complete approved timeline in order"
        )

    excluded = scope_receipt.get("excluded_cut_ids")
    if not isinstance(excluded, list):
        excluded = []
    mentioned = set(CUT_ID_PATTERN.findall(prompt))
    leaked = sorted(set(excluded) & mentioned)
    if leaked:
        raise UserDirectorStoryboardError(
            "director storyboard contains excluded Cuts: " + ", ".join(leaked)
        )

    return {
        "schema_version": "usfr-user-director-storyboard/v1",
        "status": "passed",
        "approval_cut_ids": card_ids,
        "layout_anchors": list(REQUIRED_ANCHORS),
        "layout_regions": list(REQUIRED_LAYOUT_REGIONS),
        "layout_id": "usfr-professional-director-board/v1",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate full Cut coverage for a user-facing director storyboard."
    )
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--scope-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    prompt = args.prompt_file.read_text(encoding="utf-8-sig")
    scope_receipt = json.loads(args.scope_receipt.read_text(encoding="utf-8-sig"))
    receipt = validate_user_director_storyboard(prompt, scope_receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
