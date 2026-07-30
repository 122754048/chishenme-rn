"""Deterministic, user-editable reverse-script Markdown projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .visible_text_contract import VisibleTextContractError, canonicalize_visible_text_locks


_FIRST_HEADING = "## 角色、场景与连续性锁定"
_SECOND_HEADING = "## 逐镜反解"


class UserScriptDocumentError(ValueError):
    """Raised when a revision cannot be safely shown as an editable document."""


def _text(value: Any, *, field: str, fallback: str = "—") -> str:
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise UserScriptDocumentError(f"{field} must be a string")
    return value if value.strip() else fallback


def _milliseconds(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UserScriptDocumentError(f"{field} must be a non-negative integer millisecond")
    return value


def _cell(value: str) -> str:
    """Keep arbitrary approved text inside one Markdown table cell."""

    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _format_time(start_ms: int, end_ms: int) -> str:
    return f"{start_ms / 1000:.2f}–{end_ms / 1000:.2f}s"


def _cuts(script_revision: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(script_revision, Mapping):
        raise UserScriptDocumentError("script_revision must be an object")
    raw = script_revision.get("cuts")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or not raw:
        raise UserScriptDocumentError("script_revision.cuts must be a non-empty array")
    cuts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(raw, start=1):
        if not isinstance(value, Mapping):
            raise UserScriptDocumentError(f"script_revision.cuts[{index}] must be an object")
        cut_id = _text(value.get("cut_id"), field=f"script_revision.cuts[{index}].cut_id", fallback="")
        if not cut_id or cut_id in seen:
            raise UserScriptDocumentError("script_revision cuts must have unique non-empty cut_id values")
        seen.add(cut_id)
        start_ms = _milliseconds(value.get("start_ms"), field=f"script_revision.cuts[{index}].start_ms")
        end_ms = _milliseconds(value.get("end_ms"), field=f"script_revision.cuts[{index}].end_ms")
        if end_ms <= start_ms:
            raise UserScriptDocumentError(f"script_revision.cuts[{index}] end_ms must be after start_ms")
        cuts.append({**dict(value), "cut_id": cut_id, "start_ms": start_ms, "end_ms": end_ms})
    return cuts


def _cut_visible_text(locks: Sequence[Mapping[str, Any]], *, cut_id: str) -> str:
    values: list[str] = []
    for lock in locks:
        if cut_id not in lock["cut_ids"]:
            continue
        if lock["disposition"] == "remove":
            values.append("移除")
        else:
            values.append(str(lock["approved_text"]))
    return "；".join(values) if values else "—"


def _role_or_product(cut: Mapping[str, Any]) -> str:
    for key in ("character_lock", "character", "visual"):
        value = cut.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "—"


def _continuity(cut: Mapping[str, Any]) -> str:
    for key in ("continuity", "camera"):
        value = cut.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "—"


def _audio_and_delivery(cut: Mapping[str, Any]) -> str:
    dialogue = _text(cut.get("dialogue"), field="script_revision cut dialogue")
    delivery = _text(cut.get("delivery"), field="script_revision cut delivery")
    if dialogue == "—":
        return delivery
    if delivery == "—":
        return dialogue
    return f"{dialogue}；{delivery}"


def render_user_script_markdown(
    script_revision: Mapping[str, Any], visible_text_locks: Sequence[Mapping[str, Any]]
) -> str:
    """Render only the two user-editable reverse-script sections.

    The data is intentionally projected as tables rather than a prose report:
    the caller receives no evidence hashes, provider metadata, QC rules, or
    execution commentary.  Frozen visible-text locks are canonicalized before
    display so the document can never show text that is not in its approval
    sidecar.
    """

    cuts = _cuts(script_revision)
    try:
        locks = canonicalize_visible_text_locks(visible_text_locks)
    except VisibleTextContractError as exc:
        raise UserScriptDocumentError("visible_text_locks are invalid") from exc
    cut_ids = {cut["cut_id"] for cut in cuts}
    if any(cut_id not in cut_ids for lock in locks for cut_id in lock["cut_ids"]):
        raise UserScriptDocumentError("visible_text_locks reference a Cut outside script_revision")

    lines = [
        _FIRST_HEADING,
        "",
        "| 镜头 | 角色/商品 | 场景 | 连续性锁定 |",
        "| --- | --- | --- | --- |",
    ]
    for cut in cuts:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(cut["cut_id"]),
                    _cell(_role_or_product(cut)),
                    _cell(_text(cut.get("scene"), field="script_revision cut scene")),
                    _cell(_continuity(cut)),
                )
            )
            + " |"
        )

    lines.extend(
        (
            "",
            _SECOND_HEADING,
            "",
            "| 镜头 | 时间 | 画面与动作 | 镜头语言 | 台词与语气 | 可见文字/字幕 |",
            "| --- | --- | --- | --- | --- |",
        )
    )
    for cut in cuts:
        scene = _text(cut.get("scene"), field="script_revision cut scene")
        action = _text(cut.get("action"), field="script_revision cut action")
        visual_action = action if scene == "—" else scene if action == "—" else f"{scene}；{action}"
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(cut["cut_id"]),
                    _cell(_format_time(cut["start_ms"], cut["end_ms"])),
                    _cell(visual_action),
                    _cell(_text(cut.get("camera"), field="script_revision cut camera")),
                    _cell(_audio_and_delivery(cut)),
                    _cell(_cut_visible_text(locks, cut_id=cut["cut_id"])),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


__all__ = ["UserScriptDocumentError", "render_user_script_markdown"]
