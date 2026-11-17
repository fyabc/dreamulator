"""Independent orientation controls and bounded-file scan invariants."""

from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.media.diagnose_river_directions import DirectionStats, plane_control, summarize


def test_reversal_and_subdivision_preserve_length_statistics() -> None:
    whole = DirectionStats()
    whole.add(np.array([[2.0, 0.0], [1.0, 1.0]]))
    split = DirectionStats()
    split.add(np.array([[-1.0, 0.0], [-1.0, 0.0], [-0.5, -0.5], [-0.5, -0.5]]))
    for key in ("length_km", "cos8", "within_5deg_of_grid_percent"):
        assert whole.report()[key] == pytest.approx(split.report()[key])
    np.testing.assert_allclose(whole.histogram_km, split.histogram_km)


def test_uniform_axial_directions_have_no_eightfold_signal() -> None:
    # Midpoint samples at 0.5-degree spacing avoid the grid-window boundaries.
    angle = np.radians(np.arange(0.25, 180, 0.5))
    stats = DirectionStats()
    stats.add(np.column_stack((np.cos(angle), np.sin(angle))))
    report = stats.report()
    assert report["within_5deg_of_grid_percent"] == pytest.approx(100 * 10 / 45)
    assert report["harmonic8_magnitude"] == pytest.approx(0, abs=1e-12)


def test_grid_and_halfway_directions_have_opposite_signals() -> None:
    for offset, expected in ((0, 1), (22.5, -1)):
        theta = np.radians(np.arange(0, 180, 45) + offset)
        stats = DirectionStats()
        stats.add(np.column_stack((np.cos(theta), np.sin(theta))))
        assert stats.report()["cos8"] == pytest.approx(expected)
        assert stats.report()["within_5deg_of_grid_percent"] == (100 if offset == 0 else 0)


def test_file_scan_rejects_missing_data_and_is_batch_invariant(tmp_path) -> None:
    path = tmp_path / "rivers.line.npy"
    lines = np.array(
        [
            [[0, 0], [1, 0]],
            [[0, 0], [0, 2]],
            [[0, 0], [0, 0]],
            [[np.nan, 0], [1, 1]],
            [[0, 0], [0.1, 0.1]],
        ]
    )
    np.save(path, lines)
    (tmp_path / "rivers.meta.json").write_text('{"km_per_px": 0.1}', encoding="utf-8")
    first = summarize(path, batch_size=1)
    second = summarize(path, batch_size=20)
    assert first == second
    assert first["nonfinite_segments"] == 1
    assert first["zero_length_segments"] == 1
    assert first["groups"]["all"]["segments"] == 3
    assert first["groups"]["at_least_4pixels"]["length_km"] == 3
    json.dumps(first, allow_nan=False)


def test_empty_product_has_explicit_unmeasured_status(tmp_path) -> None:
    path = tmp_path / "rivers.line.npy"
    np.save(path, np.empty((0, 2, 2)))
    assert summarize(path)["groups"]["all"]["status"] == "no_valid_segments"
    np.save(path, np.zeros((3, 4)))
    with pytest.raises(ValueError, match="shape"):
        summarize(path)


def test_existing_export_keeps_plane_direction_error() -> None:
    rows = plane_control()
    assert len(rows) == 72
    assert max(r["raw_error_deg"] for r in rows) == pytest.approx(22.25)
    assert [r["exported_error_deg"] for r in rows] == pytest.approx(
        [r["raw_error_deg"] for r in rows]
    )
