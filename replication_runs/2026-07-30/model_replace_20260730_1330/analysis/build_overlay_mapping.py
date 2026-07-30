from pathlib import Path
import hashlib
import json

RUN = Path(__file__).resolve().parents[1]
contract_path = RUN / "analysis" / "source_overlay_contract.json"
mapping_path = RUN / "analysis" / "overlay_render_mapping.json"
font_path = Path(r"C:\Windows\Fonts\NotoSansArabic-Bold.ttf")

def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

source_contract = json.loads(contract_path.read_text(encoding="utf-8"))
source_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
font_sha = hashlib.sha256(font_path.read_bytes()).hexdigest()
glyph_sha = hashlib.sha256("\u0646\u0641\u0633\u0643\u062a\u062a\u0639\u0631\u0641\u0639\u0644\u0649\u0635\u062d\u0627\u0628\u062c\u062f\u0627\u062f\u0643\u062f\u0647\u061f\u0639\u0627\u064a\u0632\u062a\u0628\u0642\u0649\u0645\u0634\u0644\u0648\u062d\u062f\u0643\u0648\u0633\u0639\u064a\u062f\u0648\u062a\u062a\u0648\u0627\u0635\u0644\u0645\u0639\u0646\u0627\u0633\u0632\u064a\u0643\u061f\u064a\u0628\u0642\u0649\u0644\u0627\u0632\u0645\u062a\u062c\u0631\u0628SUGO!".encode("utf-8")).hexdigest()

def text_payload(text, window_ms, rect):
    payload = {
        "text": text,
        "output_language": None,
        "font_sha256": font_sha,
        "glyph_coverage_sha256": glyph_sha,
        "window_ms": window_ms,
        "rect": rect,
        "render_style": {"fill_rgb": [4, 184, 253], "outline_rgb": [0, 0, 0], "outline_px": 5, "font": "Noto Sans Arabic Bold"},
    }
    return {"validated": True, "overlay_id": None, "render_mode": "deterministic_text", "text": text, "payload": payload, "payload_sha256": digest(payload)}

e1 = text_payload("\u0646\u0641\u0633\u0643 \u062a\u062a\u0639\u0631\u0641 \u0639\u0644\u0649 \u0635\u062d\u0627\u0628 \u062c\u062f\u0627\u062f \u0643\u062f\u0647\u061f", [0, 3240], [0.10, 0.43, 0.80, 0.08])
e1["overlay_id"] = "subtitle_live_01"
e2 = text_payload("\u0639\u0627\u064a\u0632 \u062a\u0628\u0642\u0649 \u0645\u0634 \u0644\u0648\u062d\u062f\u0643 \u0648\u0633\u0639\u064a\u062f\\N\u0648\u062a\u062a\u0648\u0627\u0635\u0644 \u0645\u0639 \u0646\u0627\u0633 \u0632\u064a\u0643\u061f", [3240, 6480], [0.10, 0.42, 0.80, 0.12])
e2["overlay_id"] = "subtitle_live_02"
e3 = text_payload("\u064a\u0628\u0642\u0649 \u0644\u0627\u0632\u0645 \u062a\u062c\u0631\u0628 SUGO!", [6480, 6800], [0.16, 0.47, 0.68, 0.06])
e3["overlay_id"] = "subtitle_live_03"

mapping = {
    "contract": "target-overlay-render-mapping",
    "contract_version": 1,
    "source_overlay_contract_sha256": source_sha,
    "regions": [{"region_id": "R01_live_identity_replace", "overlays": [e1, e2, e3]}],
    "notes": "Approved Arabic subtitle text is rendered deterministically after Seedance; geometry follows the frozen source overlay contract.",
}
mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
print(source_sha)
print(digest(mapping))
