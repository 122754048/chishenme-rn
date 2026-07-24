import copy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "adaptive_evidence_plan.py"
spec = importlib.util.spec_from_file_location("adaptive_evidence_plan", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def _probe():
    return {
        "contract": "reference-video-probe",
        "contract_version": 1,
        "duration_us": 10_000_000,
        "source_width": 1080,
        "source_height": 1920,
        "fps_num": 30,
        "fps_den": 1,
        "scene_cut_candidates_us": [2_000_000, 7_000_000],
        "audio_streams": [{"codec": "aac", "sample_rate": 48000, "channels": 2}],
    }


def test_build_plan_covers_exact_end_and_keeps_one_cached_pass():
    value = module.build_evidence_plan(_probe(), source_sha256="a" * 64)

    assert value["contract"] == "high-fidelity-evidence-plan"
    assert value["profile"] == "high_fidelity_hybrid_v1"
    assert value["analysis_pass_count"] == 1
    assert value["coverage"]["start_us"] == 0
    assert value["coverage"]["end_us"] == 10_000_000
    assert value["coverage"]["complete_timeline_required"] is True
    assert value["evidence"]["complete_timeline"]["start_us"] == 0
    assert value["evidence"]["complete_timeline"]["end_us"] == 10_000_000
    assert len(value["evidence"]["boundary_neighborhoods"]) >= 2
    assert len(value["evidence"]["adaptive_keyframes"]) >= 4
    assert value["evidence"]["audio"]["transcription_required"] is True


def test_scene_candidates_are_hints_not_the_only_evidence():
    value = module.build_evidence_plan(_probe(), source_sha256="b" * 64)
    evidence = value["evidence"]

    assert evidence["complete_timeline"]["method"] == "complete_timeline_contact_sheet"
    assert evidence["detail_crops"]["required_when"]
    assert evidence["audio"]["method"] == "separate_audio_transcription_and_waveform"
    assert value["candidate_policy"] == "hints_only"


def test_opaque_intervals_are_technical_only():
    opaque = [{
        "cut": 3,
        "region_type": "opaque_ui_demo",
        "start_us": 4_000_000,
        "end_us": 6_000_000,
        "transition_shell": {"kind": "fade", "duration_ms": 120},
        "technical_stream": {"width": 1080, "height": 1920, "fps_num": 30, "fps_den": 1},
    }]
    value = module.build_evidence_plan(_probe(), source_sha256="c" * 64, opaque_intervals=opaque)
    assert value["opaque_intervals"] == opaque
    module.validate_evidence_plan(value)

    bad = copy.deepcopy(value)
    bad["opaque_intervals"][0]["semantic_action"] = "tap"
    with pytest.raises(ValueError, match="technical metadata only"):
        module.validate_evidence_plan(bad)


def test_plan_rejects_second_pass_and_absolute_artifact_paths():
    value = module.build_evidence_plan(_probe(), source_sha256="d" * 64)
    value["analysis_pass_count"] = 2
    with pytest.raises(ValueError, match="analysis_pass_count"):
        module.validate_evidence_plan(value)

    value = module.build_evidence_plan(_probe(), source_sha256="e" * 64)
    value["evidence"]["complete_timeline"]["artifact_path"] = r"C:\frames\sheet.png"
    with pytest.raises(ValueError, match="artifact paths"):
        module.validate_evidence_plan(value)
