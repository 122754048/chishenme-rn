from __future__ import annotations

import json

import pytest

from fixtures import (
    full_frame_contract,
    make_drag_video,
    make_target_ui,
    probe_video,
    roi_contract,
    video_with_motion_outside_roi,
)
from track_extractor import ExtractorError, extract_tracks


def test_dense_flow_transfers_horizontal_drag(tmp_path):
    result = extract_tracks(
        make_drag_video(tmp_path, frames=12, dx=48),
        make_target_ui(tmp_path),
        full_frame_contract(12),
        tmp_path / "out",
    )

    track = json.loads(result["track_path"].read_text(encoding="utf-8"))
    assert len(track["frames"]) == 12
    assert track["frames"][-1]["translation_x"] >= 35
    assert probe_video(result["video_path"])["codec_name"] == "h264"
    assert int(probe_video(result["video_path"])["nb_read_frames"]) == 12


def test_extractor_rejects_contract_larger_than_motion_reference(tmp_path):
    contract = full_frame_contract(18)

    with pytest.raises(ExtractorError, match="frame window"):
        extract_tracks(
            make_drag_video(tmp_path, frames=6, dx=20),
            make_target_ui(tmp_path),
            contract,
            tmp_path / "out",
        )


def test_analysis_never_uses_motion_outside_ui_roi(tmp_path):
    result = extract_tracks(
        video_with_motion_outside_roi(tmp_path),
        make_target_ui(tmp_path),
        roi_contract(),
        tmp_path / "out",
    )

    track = json.loads(result["track_path"].read_text(encoding="utf-8"))
    assert abs(track["frames"][-1]["translation_x"]) < 2
    assert abs(track["frames"][-1]["translation_y"]) < 2
