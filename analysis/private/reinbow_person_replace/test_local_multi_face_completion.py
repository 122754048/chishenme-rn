from __future__ import annotations

import numpy as np

from local_multi_face_completion import assign_unique_tracks


def test_assign_unique_tracks_uses_embeddings_not_detector_order() -> None:
    templates = {
        "SRC_BLONDE": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        "SRC_MAN": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        "SRC_DARK": np.array([0.0, 0.0, 1.0], dtype=np.float32),
    }
    candidates = [
        {"embedding": np.array([0.01, 0.02, 0.99], dtype=np.float32), "center": (0.82, 0.30)},
        {"embedding": np.array([0.99, 0.01, 0.02], dtype=np.float32), "center": (0.18, 0.31)},
        {"embedding": np.array([0.02, 0.99, 0.01], dtype=np.float32), "center": (0.50, 0.28)},
    ]

    assignment = assign_unique_tracks(
        templates,
        candidates,
        previous_centers={"SRC_BLONDE": (0.18, 0.31), "SRC_MAN": (0.50, 0.28), "SRC_DARK": (0.82, 0.30)},
    )

    assert assignment == {"SRC_BLONDE": 1, "SRC_MAN": 2, "SRC_DARK": 0}
    assert len(set(assignment.values())) == 3


def test_assign_unique_tracks_can_leave_occluded_track_unassigned() -> None:
    templates = {
        "SRC_BLONDE": np.array([1.0, 0.0], dtype=np.float32),
        "SRC_DARK": np.array([0.0, 1.0], dtype=np.float32),
    }
    candidates = [
        {"embedding": np.array([0.99, 0.01], dtype=np.float32), "center": (0.20, 0.30)},
    ]

    assignment = assign_unique_tracks(
        templates,
        candidates,
        previous_centers={"SRC_BLONDE": (0.20, 0.30), "SRC_DARK": (0.80, 0.30)},
    )

    assert assignment == {"SRC_BLONDE": 0}

