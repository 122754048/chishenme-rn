from pathlib import Path

from app.execution_map import build_execution_map, classify_run_mode
from app.slots import build_intake, validate_intake


def _file(path: Path, content: bytes = b"input") -> Path:
    path.write_bytes(content)
    return path


def _source_contract() -> dict[str, object]:
    return {
        "regions": [
            {"region_id": "c01", "start_ms": 0, "end_ms": 1000, "kind": "body"},
            {"region_id": "ui01", "start_ms": 1000, "end_ms": 2000, "kind": "ui"},
            {"region_id": "tail", "start_ms": 2000, "end_ms": 3000, "kind": "tail"},
        ]
    }


def test_classify_run_mode_reserves_language_only_for_source_plus_language_only():
    assert classify_run_mode(optional_slot_ids=set(), output_language="de") == "language_only"
    assert classify_run_mode(optional_slot_ids={"new_model_image"}, output_language="de") == "composite_replication"
    assert classify_run_mode(
        optional_slot_ids=set(), output_language=None, extension_ids={"background_music"}
    ) == "composite_replication"


def test_execution_map_routes_opaque_ui_and_tail_without_seedance_segments(tmp_path):
    validated = validate_intake(
        build_intake(
            source_video=_file(tmp_path / "source.mp4"),
            new_model_image=_file(tmp_path / "model.png"),
            ui_operation_video=_file(tmp_path / "ui.mp4"),
            tail_video=_file(tmp_path / "tail.mp4"),
            output_language="de",
        ),
        probe_duration=lambda _: 3.0,
    )

    execution_map = build_execution_map(
        intake=validated,
        source_contract=_source_contract(),
        target_truth={"app_evidence": None},
    )

    by_id = {region["region_id"]: region for region in execution_map["regions"]}
    assert execution_map["run_mode"] == "composite_replication"
    assert by_id["c01"]["media_origin"] == "generated"
    assert by_id["ui01"]["media_origin"] == "opaque_ui"
    assert by_id["tail"]["media_origin"] == "opaque_tail"
    assert "ui01" not in execution_map["generated_segment_ids"]
    assert "tail" not in execution_map["generated_segment_ids"]


def test_execution_map_preserves_complete_non_overlapping_source_region_coverage(tmp_path):
    validated = validate_intake(
        build_intake(
            source_video=_file(tmp_path / "source.mp4"),
            ui_screenshot=_file(tmp_path / "ui.png"),
        ),
        probe_duration=lambda _: 3.0,
    )

    execution_map = build_execution_map(
        intake=validated,
        source_contract=_source_contract(),
        target_truth={"app_evidence": None},
    )

    assert [region["region_id"] for region in execution_map["regions"]] == ["c01", "ui01", "tail"]
    assert execution_map["regions"][1]["media_origin"] == "generated_ui"
    assert execution_map["tail_route"] == "omit_source_end_card"
