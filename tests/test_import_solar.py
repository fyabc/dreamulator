"""Tests for the solar-system reference-world import machinery (UCC-01 4d).

Covers the grid sampler (bilinear interior, lon wrap, lat clamp, NaN fallback)
and the climate_monthly.msgpack round-trip (bin_days travels with the data).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dreamulator.import_solar_common import (
    load_monthly_climate,
    sample_regular_grid,
    write_climate_monthly,
)

# 3×4 toy grid: rows north→south (lat 60, 0, −60), cols west→east (lon 0, 90, 180, 270).
_LATS = np.array([60.0, 0.0, -60.0])
_LONS = np.array([0.0, 90.0, 180.0, 270.0])
_GRID = np.array(
    [
        [1.0, 2.0, 3.0, 4.0],
        [5.0, 6.0, 7.0, 8.0],
        [9.0, 10.0, 11.0, 12.0],
    ]
)
_KW = {"lat_start": 60.0, "dlat": -60.0, "lon_start": 0.0, "dlon": 90.0}


def test_sample_at_grid_nodes() -> None:
    lats = np.array([60.0, 0.0, -60.0, 0.0])
    lons = np.array([0.0, 90.0, 180.0, 270.0])
    out = sample_regular_grid(_GRID, lats=lats, lons=lons, **_KW)
    np.testing.assert_allclose(out, [1.0, 6.0, 11.0, 8.0])


def test_sample_bilinear_interior() -> None:
    # Midpoint between (60N,0E)=1, (60N,90E)=2, (0N,0E)=5, (0N,90E)=6 → 3.5.
    out = sample_regular_grid(_GRID, lats=np.array([30.0]), lons=np.array([45.0]), **_KW)
    assert out[0] == pytest.approx(3.5)


def test_sample_longitude_wraps() -> None:
    # lon 315 sits between 270 (col 3) and 0 (col 0, wrapped).
    out = sample_regular_grid(_GRID, lats=np.array([0.0]), lons=np.array([315.0]), **_KW)
    assert out[0] == pytest.approx(0.5 * (8.0 + 5.0))
    # −45 ≡ 315
    out_neg = sample_regular_grid(_GRID, lats=np.array([0.0]), lons=np.array([-45.0]), **_KW)
    assert out_neg[0] == pytest.approx(out[0])


def test_sample_latitude_clamps_at_poles() -> None:
    # Beyond the last row: clamps to the edge row (no extrapolation).
    out = sample_regular_grid(_GRID, lats=np.array([-75.0]), lons=np.array([90.0]), **_KW)
    assert out[0] == pytest.approx(10.0)
    out_n = sample_regular_grid(_GRID, lats=np.array([80.0]), lons=np.array([90.0]), **_KW)
    assert out_n[0] == pytest.approx(2.0)


def test_sample_nan_falls_back_to_nearest_valid_corner() -> None:
    grid = _GRID.astype(float).copy()
    grid[1, 1] = np.nan  # (0N, 90E) invalid
    out = sample_regular_grid(grid, lats=np.array([0.0]), lons=np.array([90.0]), **_KW)
    # Exact node hit on the NaN node: bilinear is NaN → fallback to the first
    # valid corner in (v00, v01, v10, v11) order = grid[1, 2] = 7.0 (east
    # neighbour of the invalid node).
    assert out[0] == pytest.approx(7.0)


def test_monthly_roundtrip_preserves_values_and_bin_days(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    t = rng.normal(-40.0, 30.0, size=(137, 12))
    p = np.abs(rng.normal(5.0, 5.0, size=(137, 12)))
    bin_days = 686.98 / 12  # Martian month
    write_climate_monthly(tmp_path, t, p, bin_days=bin_days, month_0="ls_0")
    t2, p2, bd2 = load_monthly_climate(tmp_path / "climate_monthly.msgpack")
    # int16 quantization: relative precision ~1e-4 of the range.
    np.testing.assert_allclose(t2, t, atol=0.02)
    np.testing.assert_allclose(p2, p, atol=0.02)
    assert bd2 == pytest.approx(bin_days)
