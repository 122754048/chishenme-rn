from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


RUN = Path(__file__).resolve().parents[1]
SKILL = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication")
MODULE_PATH = SKILL / "bundled-skills" / "seedance-storyboard-replication" / "scripts" / "runninghub_image2.py"
sys.path.insert(0, str(MODULE_PATH.parent))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


spec = importlib.util.spec_from_file_location("usfr_runninghub_image2", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load bundled RunningHub Image2 adapter")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

env_file = Path(os.environ.get("SEEDANCE_ENV_FILE", ""))
if not env_file.is_file():
    raise RuntimeError("SEEDANCE_ENV_FILE is unavailable")
load_env(env_file)
api_key = os.environ.get("RUNNINGHUB_API_KEY", "")
if not api_key:
    raise RuntimeError("RUNNINGHUB_API_KEY is unavailable")

prompt_path = RUN / "reference_frames" / "replacement_control_prompt.txt"
source_sheet = RUN / "reference_frames" / "source_cut_contact_sheet.png"
target_image = RUN / "inputs" / "new_model_image.png"
output_path = RUN / "reference_frames" / "replacement_control_sheet.png"

client = module.RunningHubClient(
    api_key,
    base_url=os.environ.get("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai"),
    request_timeout=180,
)
prompt = prompt_path.read_text(encoding="utf-8-sig").strip()
task_file = RUN / "reference_frames" / "replacement_control_task_id.txt"
if task_file.is_file() and task_file.read_text(encoding="utf-8").strip():
    task_id = task_file.read_text(encoding="utf-8").strip()
else:
    uploaded_urls = [client.upload_image(source_sheet), client.upload_image(target_image)]
    payload = module.build_payload(prompt, uploaded_urls, aspect_ratio="16:9", resolution="2k", quality="medium")
    task_id = client.create(payload)
    write_json(RUN / "reference_frames" / "replacement_control_create_response.json", client.last_create_response)
    task_file.write_text(task_id, encoding="utf-8")
result_url = client.wait_for_result(task_id, timeout=1800, poll_interval=5)
write_json(RUN / "reference_frames" / "replacement_control_status.json", client.last_status_response)
client.download_result(result_url, output_path)

source_sha = sha256(source_sheet)
target_sha = sha256(target_image)
output_sha = sha256(output_path)
if output_sha in {source_sha, target_sha}:
    raise RuntimeError("replacement-control output is not distinct from its references")

receipt = {
    "schema_version": "usfr-replacement-control-receipt/v1",
    "status": "passed",
    "generation_mode": "single_sheet_image_to_image",
    "image2_call_count": 1,
    "task_id": task_id,
    "model": module.MODEL_NAME,
    "model_api_id": module.MODEL_API_ID,
    "source_cut_ids": ["C01", "C02", "C03", "C04", "C05", "C06", "C07"],
    "panel_count": 7,
    "reference_roles": [
        {"slot": 1, "role": "complete_source_cut_contact_sheet", "sha256": source_sha},
        {"slot": 2, "role": "target_character_identity_only", "sha256": target_sha},
    ],
    "prompt_path": str(prompt_path),
    "prompt_sha256": sha256(prompt_path),
    "output_path": str(output_path),
    "replacement_control_sheet_sha256": output_sha,
    "required_director_board_reference_sha256": output_sha,
    "forbidden_as_final_seedance_reference": True,
}
write_json(RUN / "reference_frames" / "replacement_control_receipt.json", receipt)
print(json.dumps({"task_id": task_id, "output": str(output_path), "sha256": output_sha}, ensure_ascii=False))
