from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path


ROOT = Path(r"C:\Users\zhaocx04\Documents\New project\analysis\private\h3_compound_person_product_scene_language")
ENV_PATH = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
TASK_PATH = ROOT / "task_attempt1.json"
STATUS_PATH = ROOT / "status_attempt1.json"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def post(url: str, api_key: str, payload: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    env = load_env()
    task_id = json.loads(TASK_PATH.read_text(encoding="utf-8"))["task_id"]
    base_url = env.get("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai").rstrip("/")
    deadline = time.monotonic() + 1800
    while True:
        result = post(
            f"{base_url}/openapi/v2/query",
            env["RUNNINGHUB_API_KEY"],
            {"taskId": task_id},
        )
        STATUS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        status = str(result.get("status") or "").upper()
        print(json.dumps({"taskId": task_id, "status": status}, ensure_ascii=False), flush=True)
        if status in {"SUCCESS", "FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(task_id)
        time.sleep(10)


if __name__ == "__main__":
    main()
