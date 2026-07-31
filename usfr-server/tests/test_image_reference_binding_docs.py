from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "bundled-skills" / "seedance-storyboard-replication"


def test_all_seedance_authorities_share_the_nine_image_binding_contract() -> None:
    documents = (
        ROOT / "SKILL.md",
        BUNDLED / "SKILL.md",
        BUNDLED / "references" / "seedance-prompt.md",
        BUNDLED / "references" / "runninghub-standard-seedance-api.md",
    )
    required = (
        "at most nine images",
        "continuous-present-role-order/v1",
        "@Image1 is the new model identity when a model replacement is populated",
        "product or App truth follows the model identity when populated",
        "approved director storyboard PNG pages follow the populated target-truth images",
        "uploaded_tags == binding_tags == prompt_tags",
        "@Video1 is a video-slot reference and never consumes an image index",
        "@Audio1 is an audio-slot reference and never consumes an image index",
        "seedance_execution_carrier.png",
    )
    for path in documents:
        text = " ".join(path.read_text(encoding="utf-8").split())
        for phrase in required:
            assert phrase in text, f"{path} is missing: {phrase}"


def test_docs_forbid_legacy_single_storyboard_binding_and_require_all_approved_pages() -> None:
    documents = (
        ROOT / "SKILL.md",
        BUNDLED / "SKILL.md",
        BUNDLED / "references" / "seedance-prompt.md",
        BUNDLED / "references" / "runninghub-standard-seedance-api.md",
    )
    for path in documents:
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert "Every approved storyboard page is uploaded as its original confirmed PNG" in text
        assert "A single `storyboard_url` is invalid" in text
        assert "must not generate, merge, crop, or substitute an execution carrier" in text
