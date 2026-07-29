from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.user_script_document import render_user_script_markdown


SOURCE_SHA = "a" * 64


def _locks() -> list[dict[str, object]]:
    return [
        {
            "text_id": "subtitle:01",
            "cut_ids": ["C01"],
            "start_ms": 0,
            "end_ms": 1000,
            "kind": "subtitle",
            "source_evidence_sha256": SOURCE_SHA,
            "approved_text": "Keep this text",
            "disposition": "keep",
            "placement": {"bbox": {"x": 0.2, "y": 0.7, "width": 0.6, "height": 0.1}},
        },
        {
            "text_id": "cta:02",
            "cut_ids": ["C02"],
            "start_ms": 1000,
            "end_ms": 2000,
            "kind": "cta",
            "source_evidence_sha256": "b" * 64,
            "approved_text": "Buy now",
            "disposition": "replace",
            "placement": {},
        },
    ]


def _script_revision() -> dict[str, object]:
    return {
        "cuts": [
            {
                "cut_id": "C01",
                "start_ms": 0,
                "end_ms": 1000,
                "scene": "Kitchen counter",
                "action": "Picks up the product",
                "camera": "Close-up",
                "dialogue": "Look at this",
                "delivery": "Natural",
                "audio_events": ["room tone"],
                "visual": "Model holds the product",
            },
            {
                "cut_id": "C02",
                "start_ms": 1000,
                "end_ms": 2000,
                "scene": "Kitchen counter",
                "action": "Shows the product detail",
                "camera": "Medium shot",
                "dialogue": "It folds flat",
                "delivery": "Confident",
                "audio_events": ["room tone"],
                "visual": "Same model and product",
            },
        ]
    }


def test_user_script_document_has_only_the_two_editable_sections() -> None:
    markdown = render_user_script_markdown(_script_revision(), _locks())

    assert re.findall(r"^## .+$", markdown, flags=re.M) == [
        "## 角色、场景与连续性锁定",
        "## 逐镜反解",
    ]
    assert "可见文字/字幕" in markdown
    assert "Keep this text" in markdown
    assert "Buy now" in markdown
    assert "request_evidence_sha256" not in markdown
    assert "生成与后期执行规则" not in markdown


def test_user_script_document_uses_only_confirmed_text_and_escapes_markdown_cells() -> None:
    locks = _locks()
    locks[0]["approved_text"] = "A | B\nC"
    locks[1]["approved_text"] = ""
    locks[1]["disposition"] = "remove"

    markdown = render_user_script_markdown(_script_revision(), locks)

    assert "A \\| B<br>C" in markdown
    assert "移除" in markdown
    assert "Buy now" not in markdown
