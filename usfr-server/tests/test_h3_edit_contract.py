from __future__ import annotations

import pytest

from server.h3_edit_contract import (
    H3EditContractError,
    build_h3_request,
    compile_h3_prompt,
    select_generation_owner,
)


def test_language_change_owns_every_compound_visual_edit() -> None:
    decision = select_generation_owner(
        change_language=True,
        mv_target_song=False,
        visual_asset_types=("model", "product", "scene", "app"),
    )
    assert decision == {
        "owner": "h3",
        "route": "h3_language_compound",
        "single_model": True,
    }


def test_mv_target_song_uses_h3_and_visual_only_uses_seedance() -> None:
    assert select_generation_owner(
        change_language=False, mv_target_song=True, visual_asset_types=("model",)
    )["owner"] == "h3"
    assert select_generation_owner(
        change_language=False, mv_target_song=False, visual_asset_types=("model", "product")
    ) == {"owner": "seedance", "route": "seedance_visual_edit", "single_model": True}


def test_compact_h3_prompt_uses_continuous_chinese_references() -> None:
    prompt = compile_h3_prompt(
        target_language="de",
        dialogue="Schauen wir uns das Produkt an.",
        bindings=(
            {"image_index": 1, "asset_type": "model", "instruction": "替换人物"},
            {"image_index": 2, "asset_type": "product", "instruction": "替换商品并开盖展示"},
            {"image_index": 3, "asset_type": "scene", "instruction": "替换背景"},
        ),
        preserve="镜头、动作和剪辑节奏",
    )
    assert prompt == (
        "将视频1中的人物替换为图片1中的人物。"
        "将原商品替换为图片2中的商品并开盖展示。"
        "将背景替换为图片3中的背景。"
        "人物用德语说：Schauen wir uns das Produkt an. 人物口型与德语同步。"
        "保持视频1的镜头、动作和剪辑节奏。"
    )
    assert "@Video" not in prompt and "@Image" not in prompt and "@Audio" not in prompt


def test_h3_request_rejects_mixed_syntax_and_discontinuous_images() -> None:
    with pytest.raises(H3EditContractError, match="H3_SEEDANCE_SYNTAX_MIXED"):
        build_h3_request(
            prompt="将@Video1改为德语。",
            image_urls=(), video_urls=("https://example.com/source.mp4",), audio_urls=(),
            duration=15,
        )
    with pytest.raises(H3EditContractError, match="H3_IMAGE_REFERENCE_MISMATCH"):
        build_h3_request(
            prompt="使用视频1和图片2。",
            image_urls=("https://example.com/a.png",),
            video_urls=("https://example.com/source.mp4",), audio_urls=(), duration=15,
        )


def test_h3_dialogue_language_whitelist_and_request_contract() -> None:
    with pytest.raises(H3EditContractError, match="H3_EXPERIMENTAL_LANGUAGE_APPROVAL_REQUIRED"):
        compile_h3_prompt(target_language="nl", dialogue="Hallo", bindings=(), preserve="画面")
    payload = build_h3_request(
        prompt="将视频1中的人物替换为图片1中的人物。人物用德语说：Hallo. 人物口型与德语同步。保持视频1的画面。",
        image_urls=("https://example.com/person.png",),
        video_urls=("https://example.com/source.mp4",), audio_urls=(), duration=15,
    )
    assert payload["resolution"] == "768P"
    assert payload["ratio"] == "adaptive"
    assert payload["duration"] == "15"
