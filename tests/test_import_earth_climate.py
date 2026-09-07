"""Unit tests for the earth climate importer's ocean-current step.

The earth world is import-only (never engine-built), so its surface currents
come from driving the engine's Stommel solver with the observed NCEP wind.
These tests pin the *convention* (engine-internal mirrored east basis, see the
FIXME at ``climate_simulator.py:517``) on a small synthetic basin: trade-wind
forcing must produce a westward stored surface current, matching the
engine-built earth/climate-dev anchor (Gulf Stream NE-ward, SEC W-ward).

Self-contained mesh builders (tests/test_map has no __init__.py, so helpers
cannot be imported across test modules).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.import_earth_climate import (
    _apply_observed_currents,
    _compute_ocean_currents,
    _load_soda_climatology,
    _sample_monthly,
    _sample_monthly_nan_tolerant,
)

if TYPE_CHECKING:
    from dreamulator.map.models import VoronoiCell


def _cell(
    idx: int,
    lon: float,
    lat: float,
    x: float,
    y: float,
    z: float,
    area_km2: float,
    elevation: float,
    crust_type: str,
    neighbors: list[int],
) -> VoronoiCell:  # type: ignore[valid-type]
    """Minimal VoronoiCell factory (same pattern as test_ocean_circulation)."""
    from dreamulator.map.models import VoronoiCell

    return VoronoiCell(
        id=idx,
        lon=lon,
        lat=lat,
        x=x,
        y=y,
        z=z,
        area_km2=area_km2,
        elevation=elevation,
        crust_type=crust_type,
        water_class="land" if elevation > 0 else "ocean",
        neighbors=neighbors,
    )


def _build_basin(
    n_lon: int = 24,
    n_lat: int = 14,
    lon_range: tuple[float, float] = (-60.0, 0.0),
    lat_range: tuple[float, float] = (5.0, 65.0),
) -> list[VoronoiCell]:  # type: ignore[valid-type]
    """Closed rectangular ocean basin (border ring = land) on a spherical patch."""
    cells: list = []
    total_area = 510_000_000.0
    n = n_lon * n_lat
    lons = np.linspace(lon_range[0], lon_range[1], n_lon)
    lats = np.linspace(lat_range[0], lat_range[1], n_lat)

    for j in range(n_lat):
        for i in range(n_lon):
            idx = j * n_lon + i
            lon, lat = float(lons[i]), float(lats[j])
            lat_rad, lon_rad = math.radians(lat), math.radians(lon)
            cos_lat = math.cos(lat_rad)
            x = cos_lat * math.cos(lon_rad)
            y = math.sin(lat_rad)
            z = cos_lat * math.sin(lon_rad)

            is_border = i == 0 or i == n_lon - 1 or j == 0 or j == n_lat - 1
            elev, crust = (1000.0, "continental") if is_border else (-3000.0, "oceanic")

            neighbors: list[int] = []
            if i > 0:
                neighbors.append(j * n_lon + (i - 1))
            if i < n_lon - 1:
                neighbors.append(j * n_lon + (i + 1))
            if j > 0:
                neighbors.append((j - 1) * n_lon + i)
            if j < n_lat - 1:
                neighbors.append((j + 1) * n_lon + i)

            cells.append(_cell(idx, lon, lat, x, y, z, total_area / n, elev, crust, neighbors))
    return cells


def _gyre_wind(cells: list[VoronoiCell]) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[valid-type]
    """Subtropical-gyre wind: easterlies south of 25N, westerlies north of 40N.

    Components are TRUE-east/TRUE-north (m/s), like the imported NCEP wind.
    """
    we = np.empty(len(cells))
    for i, c in enumerate(cells):
        if c.lat < 25.0:
            we[i] = -8.0
        elif c.lat > 40.0:
            we[i] = 8.0
        else:
            we[i] = -8.0 + 16.0 * (c.lat - 25.0) / 15.0
    wn = np.zeros(len(cells))
    return we, wn


class TestComputeOceanCurrents:
    def test_ocean_cells_filled_land_untouched(self) -> None:
        cells = _build_basin()
        we, wn = _gyre_wind(cells)
        _compute_ocean_currents(cells, we, wn)

        ocean = [c for c in cells if c.water_class == "ocean"]
        land = [c for c in cells if c.water_class == "land"]
        assert len(ocean) >= 20  # above the _MIN_BASIN_CELLS cutoff
        for c in ocean:
            assert c.ocean_current_east_m_s is not None
            assert c.ocean_current_north_m_s is not None
            assert math.isfinite(c.ocean_current_east_m_s)
            assert math.isfinite(c.ocean_current_north_m_s)
        for c in land:
            assert c.ocean_current_east_m_s is None
            assert c.ocean_current_north_m_s is None

    def test_trade_wind_band_flows_westward(self) -> None:
        """Convention anchor: under easterlies the *stored* current is westward.

        Mirrors the engine-built earth/climate-dev result (N Pacific trades:
        stored u = −0.012 m/s).  If the mirrored-east composition in
        ``_compute_ocean_currents`` (or the engine FIXME it tracks) changes,
        this test flips sign and must be revisited deliberately.
        """
        cells = _build_basin()
        we, wn = _gyre_wind(cells)
        _compute_ocean_currents(cells, we, wn)

        south = [
            c.ocean_current_east_m_s
            for c in cells
            if c.water_class == "ocean" and 10.0 < c.lat < 24.0 and -55.0 < c.lon < -5.0
        ]
        north = [
            c.ocean_current_east_m_s
            for c in cells
            if c.water_class == "ocean" and 45.0 < c.lat < 60.0 and -55.0 < c.lon < -5.0
        ]
        assert south and north
        assert float(np.mean(south)) < 0.0  # westward under the trades
        assert float(np.mean(north)) > 0.0  # eastward under the westerlies

    def test_no_ocean_basins_is_noop(self) -> None:
        cells = _build_basin()
        for c in cells:
            c.water_class = "land"
        we = np.zeros(len(cells))
        wn = np.zeros(len(cells))
        _compute_ocean_currents(cells, we, wn)  # must not raise
        assert all(c.ocean_current_east_m_s is None for c in cells)


def _write_soda_nc(path) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[no-untyped-def]
    """Synthetic SODA-like climatology: uniform u/v, NaN far-southern edge.

    SODA convention: 0..360 longitude (wrap-tested against −180..180 cells),
    ascending latitude, month 1..12.
    """
    import xarray as xr

    lat = np.arange(-80.0, 91.0, 5.0)
    lon = np.arange(0.5, 360.0, 5.0)
    u = np.full((12, len(lat), len(lon)), -0.4, dtype=np.float32)
    v = np.full((12, len(lat), len(lon)), 0.15, dtype=np.float32)
    u[:, lat < -70.0, :] = np.nan
    v[:, lat < -70.0, :] = np.nan
    xr.Dataset(
        {"u": (("month", "lat", "lon"), u), "v": (("month", "lat", "lon"), v)},
        coords={"month": np.arange(1, 13), "lat": lat, "lon": lon},
        attrs={"climatology_years": "1993-2022"},
    ).to_netcdf(path)
    return lat, lon


class TestObservedCurrents:
    def test_load_soda_climatology(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        nc = tmp_path / "soda_currents_mon_clim.nc"
        lat, lon = _write_soda_nc(nc)
        u, v, la, lo, attrs = _load_soda_climatology(nc)
        assert u.shape == v.shape == (12, len(lat), len(lon))
        assert np.allclose(la, lat) and np.allclose(lo, lon)
        assert attrs["climatology_years"] == "1993-2022"
        assert np.isnan(u[:, lat < -70.0, :]).all()

    def test_apply_observed_currents(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        nc = tmp_path / "soda_currents_mon_clim.nc"
        lat, lon = _write_soda_nc(nc)
        u, v, *_ = _load_soda_climatology(nc)

        cells = _build_basin()
        lats = np.array([c.lat for c in cells])
        lons = np.array([c.lon for c in cells])
        n = _apply_observed_currents(cells, lats, lons, u, v, lat, lon)

        ocean = [c for c in cells if c.water_class == "ocean"]
        assert n == len(ocean)
        for c in ocean:
            # 0..360 lon wrap + uniform field → every ocean cell sees (-0.4, 0.15)
            assert c.ocean_current_east_m_s == pytest.approx(-0.4, abs=0.02)
            assert c.ocean_current_north_m_s == pytest.approx(0.15, abs=0.02)
        for c in cells:
            if c.water_class == "land":
                assert c.ocean_current_east_m_s is None

    def test_nan_region_stays_empty(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        nc = tmp_path / "soda_currents_mon_clim.nc"
        lat, lon = _write_soda_nc(nc)
        u, v, *_ = _load_soda_climatology(nc)

        la, lo = math.radians(-78.0), math.radians(10.0)
        far_south = _cell(
            0,
            10.0,
            -78.0,
            math.cos(la) * math.cos(lo),
            math.sin(la),
            math.cos(la) * math.sin(lo),
            1000.0,
            -3000.0,
            "oceanic",
            [],
        )
        n = _apply_observed_currents(
            [far_south], np.array([-78.0]), np.array([10.0]), u, v, lat, lon
        )
        assert n == 0  # SODA's uncovered far-southern ocean → cell keeps None
        assert far_south.ocean_current_east_m_s is None

    def test_nan_tolerant_sampler(self) -> None:
        lat = np.array([0.0, 1.0, 2.0])
        lon = np.array([0.0, 1.0, 2.0])
        monthly = np.ones((12, 3, 3))
        monthly[:, 0, :] = np.nan  # "land" row bleeding into bilinear stencils

        # bilinear at lat 0.6 touches the NaN row → nearest-grid fallback (row 1)
        out = _sample_monthly_nan_tolerant(monthly, lat, lon, np.array([0.6]), np.array([1.0]))
        assert np.isfinite(out).all()
        assert float(out[0, 0]) == pytest.approx(1.0)

        # nearest grid point is itself NaN (lat 0.2 → row 0) → stays NaN
        out2 = _sample_monthly_nan_tolerant(monthly, lat, lon, np.array([0.2]), np.array([1.0]))
        assert not np.isfinite(out2).any()

        # all-finite grid → identical to the plain bilinear sampler
        finite = np.ones((12, 3, 3))
        pts_lat, pts_lon = np.array([0.5]), np.array([0.5])
        assert np.allclose(
            _sample_monthly_nan_tolerant(finite, lat, lon, pts_lat, pts_lon),
            _sample_monthly(finite, lat, lon, pts_lat, pts_lon),
        )
