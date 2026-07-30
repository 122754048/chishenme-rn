#!/usr/bin/env python3
from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic frame-sampling plan from an overlay contract.")
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fps-num", type=int, default=30)
    parser.add_argument("--fps-den", type=int, default=1)
    args = parser.parse_args()
    value = json.loads(args.json_file.read_text(encoding="utf-8"))
    duration = int(value["reference_duration_us"])
    frame_us = max(1, int(round(1_000_000 * float(Fraction(args.fps_den, args.fps_num)))))
    reasons: dict[int, set[str]] = {0: {"video_start"}, max(0, duration - frame_us): {"last_rendered_frame"}}
    for cut in value.get("cuts", []):
        start, end = int(cut["start_us"]), int(cut["end_us"])
        reasons.setdefault(start, set()).add(f"cut_{cut['cut']}_start")
        reasons.setdefault(max(start, end - frame_us), set()).add(f"cut_{cut['cut']}_last_frame")
        for overlay in cut.get("source_overlays", []):
            overlay_id = overlay["overlay_id"]
            for keyframe in overlay.get("keyframes", []):
                time_us = min(max(0, int(keyframe["time_us"])), max(0, duration - frame_us))
                reasons.setdefault(time_us, set()).add(f"overlay_{overlay_id}_keyframe")
    plan = {"contract": "overlay-frame-plan", "contract_version": 1, "reference_duration_us": duration, "fps_num": args.fps_num, "fps_den": args.fps_den, "samples": [{"time_us": time_us, "reasons": sorted(items)} for time_us, items in sorted(reasons.items())]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
