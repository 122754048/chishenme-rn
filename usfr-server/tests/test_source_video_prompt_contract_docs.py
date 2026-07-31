from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "bundled-skills" / "seedance-storyboard-replication"


def test_every_seedance_authority_requires_the_source_video_transfer_boundary() -> None:
    documents = (
        ROOT / "SKILL.md",
        BUNDLED / "SKILL.md",
        BUNDLED / "references" / "seedance-prompt.md",
        BUNDLED / "references" / "runninghub-standard-seedance-api.md",
        BUNDLED / "references" / "seedance-20-integrity-gate.md",
        ROOT / "references" / "fixed-input-slot-contract.md",
        ROOT / "references" / "server-deployment-step-by-step.md",
        ROOT / "references" / "universal-source-fidelity-contract.md",
        ROOT / "runtime-skills" / "seedance-20" / "SKILL.md",
        ROOT / "runtime-skills" / "seedance-20" / "skills" / "seedance-prompt" / "SKILL.md",
    )
    required = (
        "@Video1 is the source reference video",
        "Do not copy or output any person or identity",
        "product/App or merchandise",
        "visible text",
        "original voice",
        "original narration",
        "original dialogue",
        "Generate only the approved",
        "seedance-20",
    )

    for path in documents:
        text = path.read_text(encoding="utf-8")
        for phrase in required:
            assert phrase in text, f"{path} is missing {phrase!r}"
