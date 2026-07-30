"""CLI for the deterministic Stage-4 overlay mapping builder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.overlay_mapping import build_overlay_render_mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Build target-overlay-render-mapping/v1 from frozen source evidence.")
    parser.add_argument("source_contract", type=Path)
    parser.add_argument("timeline_regions", type=Path)
    parser.add_argument("--replacements", type=Path)
    parser.add_argument("--allow-local-paths", action="store_true", help="development-only local asset path compatibility")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.source_contract.read_text(encoding="utf-8"))
    timeline = json.loads(args.timeline_regions.read_text(encoding="utf-8"))
    replacements = {}
    if args.replacements is not None:
        replacements = json.loads(args.replacements.read_text(encoding="utf-8"))
    mapping = build_overlay_render_mapping(
        contract,
        timeline,
        replacements=replacements,
        allow_local_paths=args.allow_local_paths,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(mapping, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
