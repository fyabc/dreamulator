"""Tests for author paleo-sutures (paleo_sutures)."""

from __future__ import annotations

import numpy as np

from dreamulator.map.paleo_sutures import (
    AuthorSuture,
    load_sutures,
    lonlat_to_xyz,
    polyline_geometry,
    resolve_side,
)


def test_side_of_an_eastward_path_is_left_to_the_north() -> None:
    path = np.array([[0.0, 0.0], [30.0, 0.0]])
    pts = lonlat_to_xyz(np.array([[15.0, 5.0], [15.0, -5.0], [15.0, 0.5]]))
    dist, side = polyline_geometry(pts, path)
    assert side[0] == 1 and side[1] == -1
    np.testing.assert_allclose(np.degrees(dist[2]), 0.5, atol=1e-6)


def test_compass_side_resolution() -> None:
    path = np.array([[0.0, 0.0], [30.0, 0.0]])
    pts = lonlat_to_xyz(np.array([[15.0, 10.0], [15.0, -10.0]]))
    side = np.array([1.0, -1.0])
    w = np.ones(2)
    assert resolve_side("north", pts, side, w, path) == 1
    assert resolve_side("south", pts, side, w, path) == -1
    assert resolve_side("left", pts, side, w, path) == 1


def test_load_sutures(tmp_path) -> None:
    f = tmp_path / "plate_history.yaml"
    f.write_text(
        "sutures:\n  - id: s1\n    collision_age_myr: 50\n    path: [[0, 0], [10, 5]]\n"
        "    moving_side: southwest\n",
        encoding="utf-8",
    )
    (s,) = load_sutures(f)
    assert isinstance(s, AuthorSuture) and s.collision_age_myr == 50.0 and s.width_km == 150.0
    assert s.path.shape == (2, 2)
    assert load_sutures(tmp_path / "missing.yaml") == []
