from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ[name.strip()] = value.strip().strip('"').strip("'")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--role", choices=("main_male", "blonde_woman", "dark_hair_woman", "cat_humanoid"), required=True)
    args = parser.parse_args()

    load_env(args.env_file)
    sys.path.insert(0, str(args.skill_root))
    from server.runninghub_workflows import RunningHubWorkflowClient

    common = (
        "Create a clean 16:9 professional identity reference board for video character replacement. "
        "The board must show one approved character only: a large facial close-up plus front, left profile, right profile, "
        "and back or three-quarter views. Use neutral studio lighting and a plain background. Preserve the exact identity evidence "
        "from the supplied reference. Do not add text, logos, extra people, props, decorative frames, or beauty exaggeration. "
    )
    prompts = {
        "main_male": common + "Preserve the man's exact face, skin tone, shaved hairstyle, facial proportions, and athletic body proportions. Show natural hands and a neutral expression.",
        "blonde_woman": common + "Preserve the woman's exact face, green-hazel eyes, long voluminous blonde hair, facial proportions, and adult body proportions. Keep makeup natural and identity-stable.",
        "dark_hair_woman": common + "Preserve the woman's exact face, brown eyes, short dark curly hair, freckles, facial proportions, and adult body proportions. Keep the friendly identity stable across all views.",
        "cat_humanoid": common + (
            "Use the supplied ragdoll cat only as head identity evidence: blue eyes, pink nose, white muzzle and forehead blaze, "
            "dark seal-point ears and eye mask, and soft cream fur. Build a human-scale upright cat-headed character wearing the source-style black hoodie, "
            "with an anatomically human neck, shoulders, arms, hands, legs, and feet so it can hold a phone and walk arm-in-arm. "
            "The cat head must remain realistic and consistent. Do not create a quadruped cat, paws instead of human hands, a giant mascot head, or an animal body."
        ),
    }

    client = RunningHubWorkflowClient(
        api_key=os.environ["RUNNINGHUB_API_KEY"],
        base_url=os.environ["RUNNINGHUB_BASE_URL"],
        timeout_seconds=600,
        poll_interval_seconds=5,
    )
    result = client.run_image2(
        prompt=prompts[args.role],
        reference_images=[args.reference],
        template="model",
        aspect_ratio="16:9",
        resolution="2k",
        quality="medium",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result["image_bytes"])
    receipt = {
        "role": args.role,
        "reference_path": str(args.reference.resolve()),
        "result_url": result["result_url"],
        "task_id": result["task_id"],
        "receipt": result["receipt"],
    }
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"role": args.role, "task_id": result["task_id"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
