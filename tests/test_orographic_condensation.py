"""CLIM-02 slice 1: orographic condensation as an in-budget flux sink.

The migration (astra rethinking §5.2/§7) replaces the post-budget
orographic add-on (fabricated water) and the multiplicative föhn shadow
(deleted water) with one conservative mechanism: the moisture flux crossing
an uphill edge is attenuated by the Clausius–Clapeyron lift-drying factor
φ = 1 − exp(−Δz/H_cc), and the condensed share rains out at the windward
cell.  The guards here: exact conservation of the precipitation *product*
(ΣA·P = ΣA·E), the windward-wet / leeward-dry response, and the CC scale
physics — all with zero free parameters.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from dreamulator.engine.climate_physics import (
    cc_lift_drying_scale,
    evaporation_rate,
)
from dreamulator.map.climate_simulator import _solve_moisture_budget
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import TerrainPipelineConfig

N_LON = 36
N_LAT = 9


def _ridge_mesh(ridge_top_m: float = 3000.0) -> tuple[CVTMesh, np.ndarray]:
    """Regular lon/lat grid with a meridional ridge; uniform westerly wind.

    Ridge profile: elevation rises smoothly from 0 at lon = 70° to
    *ridge_top_m* at lon = 90° and falls back to 0 at lon = 110° (a cosine
    hill over 40° ≈ 4400 km — Andes-scale width).  Everything else is flat
    (ocean at sea level).  Cells carry the ``neighbors`` list — the budget's
    directed edge table reads that field, not the mesh-level adjacency dict.
    """
    lats = np.linspace(-70.0, 70.0, N_LAT)
    lons = np.linspace(-180.0, 180.0 - 360.0 / N_LON, N_LON)
    n = N_LON * N_LAT

    def ridged(lon: float) -> float:
        if 70.0 <= lon <= 110.0:
            frac = (lon - 70.0) / 40.0  # 0..1 over the hill
            return ridge_top_m * 0.5 * (1.0 - math.cos(2.0 * math.pi * frac))
        return 0.0

    def neighbors_of(i: int) -> list[int]:
        j_lat, j_lon = divmod(i, N_LON)
        nbrs = [
            j_lat * N_LON + (j_lon - 1) % N_LON,  # west
            j_lat * N_LON + (j_lon + 1) % N_LON,  # east
        ]
        if j_lat > 0:
            nbrs.append((j_lat - 1) * N_LON + j_lon)
        if j_lat < N_LAT - 1:
            nbrs.append((j_lat + 1) * N_LON + j_lon)
        return nbrs

    cells = []
    for i in range(n):
        lon = float(lons[i % N_LON])
        lat = float(lats[i // N_LON])
        lon_rad = math.radians(lon)
        lat_rad = math.radians(lat)
        cells.append(
            VoronoiCell(
                id=i,
                lon=lon,
                lat=lat,
                x=math.cos(lat_rad) * math.cos(lon_rad),
                y=math.sin(lat_rad),
                z=math.cos(lat_rad) * math.sin(lon_rad),
                area_km2=510_000_000.0 / n,
                elevation=ridged(lon),
                neighbors=neighbors_of(i),
            )
        )
    adjacency = {str(i): neighbors_of(i) for i in range(n)}
    mesh = CVTMesh(seed=42, num_cells=n, cells=cells, adjacency=adjacency)

    # Uniform westerly (toward increasing longitude) on the physical east
    # basis: d(position)/d(lon) = (−sin λ, 0, cos λ).
    lon_rad = np.radians(np.array([c.lon for c in cells]))
    east = np.stack([-np.sin(lon_rad), np.zeros(n), np.cos(lon_rad)], axis=1)
    return mesh, 5.0 * east


def _run_budget(mesh: CVTMesh, wind: np.ndarray, t_c: float = 30.0):
    n = mesh.num_cells
    nodes = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    t = np.full(n, t_c)
    is_ocean = np.ones(n, dtype=bool)
    config = TerrainPipelineConfig()
    w, p = _solve_moisture_budget(mesh, wind, is_ocean, t, nodes, config)
    areas = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
    e = evaporation_rate(t, is_ocean, config.evaporation_base_mm)
    return w, p, e, areas


def _zonal_mean(field: np.ndarray) -> np.ndarray:
    """Mid-latitude 3-row zonal mean, shape (N_LON,)."""
    return field.reshape(N_LAT, N_LON)[N_LAT // 2 - 1 : N_LAT // 2 + 2].mean(axis=0)


_LONS = np.linspace(-180.0, 180.0 - 360.0 / N_LON, N_LON)


class TestOrographicCondensation:
    def test_conservation_exact(self):
        """ΣA·(rainout + orographic) == ΣA·E — the product conserves water."""
        mesh, wind = _ridge_mesh()
        w, p, e, areas = _run_budget(mesh, wind)
        # Warm ocean, no land (no Budyko feedback), cold trap far from biting.
        assert (p * areas).sum() == pytest.approx((e * areas).sum(), rel=1e-9), (
            "orographic condensation broke the exact ΣP = ΣE identity"
        )

    def test_windward_wet_leeward_dry(self):
        """Condensation rains on the windward slope; the lee column dries.

        In a steady conservative budget the windward *total* barely rises —
        the orographic condensation mostly relabels rain the column would
        have produced anyway (k·W drops as the attenuated inflow arrives;
        P_oro replaces it).  The distinctive signatures are the positive
        P_oro component on the climbing cells and the *leeward* depletion:
        the flux leaving the crest is depleted, so the lee column water and
        rain both fall below the flat background.
        """
        mesh, wind = _ridge_mesh()
        w, p, *_ = _run_budget(mesh, wind)
        k = 365.25 / 9.0
        p_oro = p - w * k
        prof_oro = _zonal_mean(p_oro)
        prof_w = _zonal_mean(w)
        prof_p = _zonal_mean(p)

        climbing = (_LONS >= 70.0) & (_LONS <= 90.0)  # upwind slope + crest
        leeward = (_LONS > 90.0) & (_LONS <= 120.0)  # downwind descent
        flat = _LONS < 30.0

        # 1. The condensation term exists, concentrated on the climbing cells.
        assert prof_oro[climbing].max() > 100.0, "no orographic condensation"
        # 2. Rain shadow: leeward column water and rain below the flat
        #    background, while the windward rain carries the orographic bump
        #    (the climbing column itself is the driest — it rains out
        #    fastest — so the contrast is in P, not W).
        assert prof_w[leeward].mean() < prof_w[flat].mean(), (
            "leeward column not dried vs flat background"
        )
        assert prof_p[climbing].mean() > prof_p[flat].mean(), "no windward orographic rain bump"
        assert prof_p[leeward].mean() < prof_p[flat].mean(), (
            "leeward rain not depleted — shadow did not emerge in P"
        )

    def test_ridge_vs_flat_redistributes(self):
        """Ridge vs flattened mesh at identical E/wind: windward gains,
        far-leeward loses — a redistribution, not creation."""
        mesh_ridge, wind = _ridge_mesh()
        mesh_flat, _ = _ridge_mesh(ridge_top_m=0.0)
        _, p_ridge, _, _ = _run_budget(mesh_ridge, wind)
        _, p_flat, _, _ = _run_budget(mesh_flat, wind)

        pr = _zonal_mean(p_ridge)
        pf = _zonal_mean(p_flat)
        windward = (_LONS >= 80.0) & (_LONS <= 90.0)  # above-LCL climbing cells
        far_lee = (_LONS >= 130.0) & (_LONS <= 170.0)
        assert (pr[windward] > pf[windward]).mean() > 0.8
        assert (pr[far_lee] < pf[far_lee]).mean() > 0.8


class TestCcLiftDryingScale:
    def test_anchor_288k(self):
        h = float(cc_lift_drying_scale(np.array([14.85]), np.array([6.5]))[0])
        assert h == pytest.approx(2353.0, rel=2e-3)

    def test_monotone_in_temperature_and_lapse(self):
        warm = cc_lift_drying_scale(np.array([25.0]), np.array([6.5]))[0]
        cool = cc_lift_drying_scale(np.array([5.0]), np.array([6.5]))[0]
        assert warm > cool  # warmer → weaker drying per lift

        steep = cc_lift_drying_scale(np.array([14.85]), np.array([9.8]))[0]
        gentle = cc_lift_drying_scale(np.array([14.85]), np.array([4.5]))[0]
        assert steep < gentle  # steeper lapse → stronger drying

    def test_two_km_lift_condenses_majority(self):
        """φ = 1 − exp(−2000/2353) ≈ 0.57 — a 2 km lift condenses most of
        the transiting moisture, in-family with the retired 0.4 heuristic."""
        h = float(cc_lift_drying_scale(np.array([14.85]), np.array([6.5]))[0])
        phi_2km = 1.0 - math.exp(-2000.0 / h)
        assert 0.4 < phi_2km < 0.75


class TestCoastalRainoutFactor:
    """CLIM-02 slice 3: coastal asymmetry as a k_rain modulation."""

    def test_factor_bounds_and_signs(self):
        from dreamulator.map.climate_simulator import _coastal_rainout_factor

        # Land sector lon ∈ [60°, 120°], ocean elsewhere; strong westerly.
        n = N_LON * N_LAT
        lons = np.array([c.lon for c in _ridge_mesh()[0].cells])
        # Build a flat land-island mesh from the ridge builder (elevation → 0,
        # land mask by longitude sector).
        mesh, wind = _ridge_mesh(ridge_top_m=0.0)
        is_land = (lons >= 60.0) & (lons <= 120.0)
        # Broadcast the land sector across all latitudes.
        is_land = np.tile(
            (np.linspace(-180, 180 - 360.0 / N_LON, N_LON) >= 60.0)
            & (np.linspace(-180, 180 - 360.0 / N_LON, N_LON) <= 120.0),
            N_LAT,
        )
        is_ocean = ~is_land
        t = np.full(n, 25.0)
        nodes = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
        f = _coastal_rainout_factor(mesh, n, is_land, is_ocean, wind, t, nodes)

        assert np.all((f >= 0.5 - 1e-12) & (f <= 1.5 + 1e-12))
        assert np.all(f[~is_land] == 1.0)  # ocean / inland: no modulation
        # Under a westerly, west-coast cells (lon=60 boundary) are windward
        # (f > 1) and east-coast cells (lon=120) are leeward (f < 1).
        west_edge = np.flatnonzero(is_land & (np.abs(lons - 60.0) < 1e-6))
        east_edge = np.flatnonzero(is_land & (np.abs(lons - 120.0) < 1e-6))
        assert len(west_edge) and len(east_edge)
        assert np.all(f[west_edge] > 1.0)
        assert np.all(f[east_edge] < 1.0)


class TestSubPlanetRainoutFactor:
    """CLIM-02 slice 4: the sub-planet convective anchor as a k_rain gate."""

    def test_disabled_when_warming_zero(self):
        from dreamulator.map.climate_simulator import _sub_planet_rainout_factor

        cfg = TerrainPipelineConfig(sub_planet_warming_c=0.0)
        lat = np.zeros(4)
        lon = np.zeros(4)
        f = _sub_planet_rainout_factor(lat, lon, cfg)
        assert np.all(f == 1.0)

    def test_gaussian_peak_and_decay(self):
        from dreamulator.map.climate_simulator import _sub_planet_rainout_factor

        cfg = TerrainPipelineConfig(sub_planet_warming_c=1.0)
        # Radial distances from the default sub-point (0°, 0°): 0, 15, 30, 90°.
        lat = np.radians([0.0, 0.0, 0.0, 90.0])
        lon = np.radians([0.0, 15.0, 30.0, 0.0])
        f = _sub_planet_rainout_factor(lat, lon, cfg)
        assert f[0] == pytest.approx(1.2)  # peak: 1 + 200/1000
        assert f[1] == pytest.approx(1.0 + 0.2 * np.exp(-0.5))
        assert f[2] == pytest.approx(1.0 + 0.2 * np.exp(-2.0))
        assert f[3] == pytest.approx(1.0, abs=1e-3)  # far side ≈ no gate
        assert np.all(f >= 1.0)  # enhancement only, never suppression
