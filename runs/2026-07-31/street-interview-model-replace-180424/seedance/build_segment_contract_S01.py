from __future__ import annotations

import json
from pathlib import Path


RUN = Path(__file__).resolve().parents[1]


def shot(shot_id, start, end, performance, action, endpoint, audio, factors):
    return {
        "shot_id": shot_id,
        "start_ms": start,
        "end_ms": end,
        "shot_scale": "9:16 handheld medium portrait",
        "scene": "night street; woman center-right; microphone lower left",
        "camera": "35mm handheld micro-drift",
        "lighting": "cool left vending key; dark rear",
        "performance": performance,
        "action": action,
        "endpoint": endpoint,
        "product_or_ui_truth": "no product; @Image1 face; white top; black skirt",
        "commercial_proof": "interview only; no claim",
        "transition": "continuous phase",
        "continuity": "same scale, gaze left and microphone relation",
        "audio": audio,
        "factor_ids": factors,
    }


segment = {
    "segment_id": "S01",
    "cut_ids": ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"],
    "duration_ms": 10867,
    "output_global_start_ms": 0,
    "opening_state": "Blonde woman center-right, gaze left; microphone lower left.",
    "reference_roles": [
        {"slot": 1, "tag": "@Image1", "role": "authorized woman identity only"},
        {"slot": 2, "tag": "@Image2", "role": "approved director board C01-C04"},
        {"slot": 3, "tag": "@Image3", "role": "approved director board C05-C08"},
    ],
    "shots": [
        shot("C01-C05", 0, 6000, "C01 neutral listen; C02 small smile; C03 smile and nod; C04 playful tilt and sway; C05 amused listen", "hear DIA-001, say DIA-002 and DIA-003, then hear DIA-004", "ready to answer the follow-up", "DIA-001 to DIA-004; street ambience; no music", ["S01.C01C05.VISUAL", "S01.C01C05.ACTION", "S01.C01C05.AUDIO"]),
        shot("C06-C08", 6000, 10867, "C06 animated smile and subtle lean; C07 playful laugh and chin dip; C08 warm smile, hands together", "say DIA-005 and DIA-006, then finish the closing gesture", "stable smile, hands together", "DIA-005 and DIA-006, then laugh or breath tail; street ambience; no music", ["S01.C06C08.VISUAL", "S01.C06C08.ACTION", "S01.C06C08.AUDIO"]),
    ],
    "no_speech_contracts": [
        {"cut_id": "C08", "speech_mode": "none", "allowed_audio": ["laugh or breath tail", "street ambience"], "forbidden_audio": ["new dialogue", "background music"]}
    ],
    "locks": [
        "@Image1 fixes face and hair; @Image2 and @Image3 fix C01-C08 visual states.",
        "Keep white top, black skirt, night street, left key and microphone; generate no visible text."
    ],
    "negative_constraints": [
        "no original face, identity drift, wardrobe or background change",
        "no extra person, hand or microphone defect, invented or reordered Cut, copied voice or improvised line"
    ],
}

(RUN / "seedance" / "segment_S01_contract.json").write_text(
    json.dumps(segment, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({"status": "passed", "shot_count": len(segment["shots"])}, ensure_ascii=False))
