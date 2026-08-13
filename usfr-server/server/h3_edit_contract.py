"""Fail-closed model ownership and compact H3 video-edit requests."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse


H3_STABLE_DIALOGUE_LANGUAGES = {
    "ar": "阿拉伯语", "zh": "中文", "en": "英语", "fr": "法语",
    "de": "德语", "it": "意大利语", "ja": "日语", "ko": "韩语",
    "pt": "葡萄牙语", "ru": "俄语", "es": "西班牙语",
}
_ASSET_LABELS = {"model": "人物", "product": "商品", "app": "App", "scene": "背景",
                 "garment": "服装", "jewelry": "饰品", "accessory": "配件"}
_SEEDANCE_REF = re.compile(r"@(Video|Image|Audio)\s*\d*", re.I)
_H3_IMAGE_REF = re.compile(r"图片(\d+)")


class H3EditContractError(ValueError):
    pass


def select_generation_owner(*, change_language: bool, mv_target_song: bool,
                            visual_asset_types: Sequence[str]) -> dict[str, object]:
    del visual_asset_types
    if change_language:
        return {"owner": "h3", "route": "h3_language_compound", "single_model": True}
    if mv_target_song:
        return {"owner": "h3", "route": "h3_mv_song", "single_model": True}
    return {"owner": "seedance", "route": "seedance_visual_edit", "single_model": True}


def compile_h3_prompt(*, target_language: str | None, dialogue: str | None,
                      bindings: Sequence[Mapping[str, Any]], preserve: str,
                      mv_target_song: bool = False, has_audio: bool = False,
                      experimental_language_approved: bool = False) -> str:
    locale = str(target_language or "").casefold()
    if locale and locale not in H3_STABLE_DIALOGUE_LANGUAGES and not experimental_language_approved:
        raise H3EditContractError("H3_EXPERIMENTAL_LANGUAGE_APPROVAL_REQUIRED")
    ordered = sorted((dict(row) for row in bindings), key=lambda row: int(row.get("image_index", 0)))
    if [row.get("image_index") for row in ordered] != list(range(1, len(ordered) + 1)):
        raise H3EditContractError("H3_IMAGE_REFERENCE_MISMATCH")
    parts: list[str] = []
    for row in ordered:
        index = int(row["image_index"])
        kind = str(row.get("asset_type") or "")
        instruction = str(row.get("instruction") or "").strip()
        label = _ASSET_LABELS.get(kind, "元素")
        if kind == "model":
            parts.append(f"将视频1中的人物替换为图片{index}中的人物。")
        elif kind == "product":
            suffix = instruction.removeprefix("替换商品").lstrip("并")
            parts.append(f"将原商品替换为图片{index}中的商品" + (f"并{suffix}" if suffix else "") + "。")
        elif kind == "scene":
            parts.append(f"将背景替换为图片{index}中的背景。")
        else:
            parts.append(f"将原{label}替换为图片{index}中的{label}。")
    if mv_target_song:
        if not has_audio:
            raise H3EditContractError("H3_MV_AUDIO_REQUIRED")
        parts.append("人物演唱音频1中的歌曲，口型与音频1同步。")
    elif locale:
        if not str(dialogue or "").strip():
            raise H3EditContractError("H3_APPROVED_DIALOGUE_REQUIRED")
        language = H3_STABLE_DIALOGUE_LANGUAGES.get(locale, locale)
        parts.append(f"人物用{language}说：{str(dialogue).strip()} 人物口型与{language}同步。")
    parts.append(f"保持视频1的{str(preserve).strip()}。")
    return "".join(parts)


def _public_https(value: object) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise H3EditContractError("H3_PUBLIC_HTTPS_MEDIA_REQUIRED")
    return parsed.geturl()


def build_h3_request(*, prompt: str, image_urls: Sequence[str], video_urls: Sequence[str],
                     audio_urls: Sequence[str], duration: int, resolution: str = "768P",
                     ratio: str = "adaptive") -> dict[str, object]:
    text = str(prompt or "").strip()
    if _SEEDANCE_REF.search(text):
        raise H3EditContractError("H3_SEEDANCE_SYNTAX_MIXED")
    if len(video_urls) != 1 or not 5 <= int(duration) <= 15:
        raise H3EditContractError("H3_VIDEO_CONTRACT_INVALID")
    if len(image_urls) > 9 or len(audio_urls) > 3:
        raise H3EditContractError("H3_MEDIA_LIMIT_EXCEEDED")
    referenced = sorted({int(value) for value in _H3_IMAGE_REF.findall(text)})
    if referenced != list(range(1, len(image_urls) + 1)):
        raise H3EditContractError("H3_IMAGE_REFERENCE_MISMATCH")
    if ("音频1" in text) != bool(audio_urls):
        raise H3EditContractError("H3_AUDIO_REFERENCE_MISMATCH")
    return {
        "prompt": text,
        "imageUrls": [_public_https(value) for value in image_urls],
        "videoUrls": [_public_https(value) for value in video_urls],
        "audioUrls": [_public_https(value) for value in audio_urls],
        "resolution": resolution, "duration": str(int(duration)), "ratio": ratio,
    }


__all__ = ["H3EditContractError", "H3_STABLE_DIALOGUE_LANGUAGES", "build_h3_request",
           "compile_h3_prompt", "select_generation_owner"]
