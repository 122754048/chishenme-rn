import json
from pathlib import Path

import whisper


audio = Path(r"C:\Users\zhaocx04\Documents\New project\final\2026-07-28\usfr-61bb156889e04fdbada3d62977d0a1b3\analysis\source_audio.wav")
output = Path(r"C:\Users\zhaocx04\Documents\New project\final\2026-07-28\usfr-61bb156889e04fdbada3d62977d0a1b3\analysis\asr\source_audio.json")
model = whisper.load_model("base")
result = model.transcribe(str(audio), fp16=False, verbose=False)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "complete", "language": result.get("language")}, ensure_ascii=False))
