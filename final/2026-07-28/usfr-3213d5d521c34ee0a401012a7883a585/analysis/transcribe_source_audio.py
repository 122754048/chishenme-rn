import json
from pathlib import Path

import whisper


audio = Path(r"C:\Users\zhaocx04\Documents\New project\final\2026-07-28\usfr-3213d5d521c34ee0a401012a7883a585\analysis\source_audio.wav")
output = Path(r"C:\Users\zhaocx04\Documents\New project\final\2026-07-28\usfr-3213d5d521c34ee0a401012a7883a585\analysis\asr\source_audio.json")
model = whisper.load_model("base")
result = model.transcribe(str(audio), fp16=False, verbose=False)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "complete", "language": result.get("language")}, ensure_ascii=False))
