from __future__ import annotations

import json
import os
from pathlib import Path
import time
from urllib import request


ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "provider_once"
ENV_FILE = Path(r"C:\Users\zhaocx04\Documents\usfr-v2-secrets\.env")
TASK_ID = "2087381955506491393"


for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def post_json(url: str, payload: dict) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['RUNNINGHUB_SEEDANCE_API_KEY']}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


while True:
    status = post_json(os.environ["RUNNINGHUB_SEEDANCE_QUERY_URL"], {"taskId": TASK_ID})
    (RUN_DIR / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = str(status.get("status") or "").upper()
    print(json.dumps({"taskId": TASK_ID, "status": state}, ensure_ascii=False), flush=True)
    if state == "SUCCESS":
        video_url = next(row["url"] for row in status["results"] if row.get("outputType") == "mp4")
        with request.urlopen(video_url, timeout=180) as response:
            (RUN_DIR / "result.mp4").write_bytes(response.read())
        break
    if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
        raise SystemExit(f"PROVIDER_{state}")
    time.sleep(10)
