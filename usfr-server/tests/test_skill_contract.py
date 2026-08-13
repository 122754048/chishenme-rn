import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_bundle import verify_bundle  # noqa: E402


def _read(relative: str) -> str:
    return " ".join((ROOT / relative).read_text(encoding="utf-8").split())


def test_main_skill_is_one_v2_video_edit_entrypoint_with_composable_inputs() -> None:
    skill = _read("SKILL.md")
    assert "name: universal-source-fidelity-replication" in skill
    assert "source video plus approved change inputs" in skill
    assert "video-edit-v2" in skill
    assert "single video-edit replication entrypoint" in skill
    for value in (
        "source_video (required)", "new_model_image", "new_product_image",
        "garment", "scene", "ui_screenshot", "app_store_url",
        "ui_operation_video", "tail_video", "background_music",
        "output_language", "change instruction", "analysis only",
        "explicit modification",
    ):
        assert value.casefold() in skill.casefold()


def test_main_skill_documents_v2_edit_boundary_prompt_and_single_approval() -> None:
    skill = _read("SKILL.md")
    for value in (
        "@Video1 is the edit object", "≤15s", "at most two natural-Cut segments",
        "terminal logo/download tail", "UI Cuts are preserved", "编辑视频：",
        "frame-for-frame", "one user file", "one script approval",
        "plan_segments", "hidden deterministic Cut execution plan",
    ):
        assert value in skill
    for forbidden in ("storyboard approval", "storyboard @Image", "storyboard receipt"):
        assert forbidden not in skill.casefold()
    assert "prompt approval" not in skill.lower()


def test_main_skill_documents_routes_text_audio_complexity_and_recovery() -> None:
    skill = _read("SKILL.md")
    for value in (
        "deterministic FFmpeg splice", "App asset board + Seedance edit",
        "source UI keep", "generation_surface", "deterministic overlay/UI",
        "approved time window and region", "music-only", "voice/dialogue",
        "H3 MV edit", "UI monologue", "split_required", "pass1",
        "pass2", "provider retry once", "QC pass2 retry once", "must enter reconcile",
        "hard cut", "continuity",
    ):
        assert value.casefold() in skill.casefold()


def test_document_layers_are_canonical_and_quarantine_legacy_routes() -> None:
    skill = _read("SKILL.md")
    fixed = _read("references/fixed-input-slot-contract.md")
    universal = _read("references/universal-source-fidelity-contract.md")
    v2 = _read("references/video-edit-v2-contract.md")
    assert "Canonical runtime contract: `references/video-edit-v2-contract.md`" in skill
    assert "Legacy quarantine" in universal
    assert "not reachable from `video-edit-v2`" in universal
    assert "fixed-input-slots/v2" in fixed
    assert "generation_surface" in v2
    assert "storyboard images are not generated, uploaded, or bound" in v2
    assert "legacy quarantine" in skill.casefold()
    assert "Invocation A" not in skill + fixed + v2
    assert "generated_ui_demo" not in skill + fixed + v2
    assert "replacement-control" not in skill + fixed + v2


def test_docs_allow_only_neutral_attractiveness_language() -> None:
    documents = (
        "SKILL.md",
        "references/fixed-input-slot-contract.md",
        "references/universal-source-fidelity-contract.md",
        "references/video-edit-v2-contract.md",
        "bundled-skills/seedance-storyboard-replication/SKILL.md",
    )
    combined = "\n".join(_read(relative).casefold() for relative in documents)
    for forbidden in ("sexual", "suggestive", "sexy", "seductive", "erotic"):
        assert forbidden not in combined
    assert "other attractiveness labels fail closed" in combined


def test_documented_operational_safety_and_bundle_closure_remain() -> None:
    skill = _read("SKILL.md")
    assert "server-side" in skill
    assert "never a workstation path" in skill
    assert "USFR_FFMPEG_ENCODER" in skill
    assert "USFR_FFMPEG_THREADS" in skill
    manifest = json.loads(_read("references/bundle_manifest.json"))
    assert "seedance-storyboard-replication" in {
        str(row.get("name") or "") for row in manifest["modules"]
    }
    assert (ROOT / "references" / "video-edit-v2-contract.md").is_file()
