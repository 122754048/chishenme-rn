import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication\bundled-skills\seedance-storyboard-replication")
RUN = Path(r"C:\Users\zhaocx04\Documents\New project\replication_runs\2026-07-30\character_swap_20260730_152001")
sys.path.insert(0, str(ROOT.parents[2]))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("runninghub_seedance_submit", ROOT / "scripts" / "runninghub_seedance_submit.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
settings = module.load_settings(RUN / "private" / "runninghub.env")
client = module.RunningHubStandardSeedanceClient(settings.runninghub_seedance_api_key, create_url=settings.runninghub_seedance_create_url, query_url=settings.runninghub_seedance_query_url, upload_url=settings.runninghub_seedance_upload_url)
status = client.get_status("2082742471552815105")
output = RUN / "provider" / "seedance" / "S01"
(output / "status.json").write_text(json.dumps(module._redact_provider_response(status), ensure_ascii=False, indent=2), encoding="utf-8")
print(str(status.get("status") or ""))
if str(status.get("status") or "").upper() == "SUCCESS":
    for item in status.get("results") or []:
        if str(item.get("outputType") or "").lower() == "mp4":
            client.download_video(str(item["url"]), output / "result.mp4")
            print("DOWNLOADED")
            break
