"""Polar ice sheet post-pass tests (perfect-plastic dome, caps, idempotency)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from dreamulator.map.ice_sheets import (
    RHO_ICE_KG_M3,
    annual_mean_insolation,
    apply_polar_ice_sheets,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig


def _flat_world(n: int = 4000, land_frac: float = 0.5) -> object:  # noqa: ANN401
    """Tiny CVT mesh with a synthetic north-pole land cap for dome tests."""
    from dreamulator.map.cvt_mesh import generate_cvt_mesh

    cfg = TerrainPipelineConfig(num_nodes=n, lloyd_iterations=1, seed=7)
    mesh = generate_cvt_mesh(cfg)
    # Land north of 45°N + a narrow maritime strip, ocean elsewhere; flat bed 200 m
    for c in mesh.cells:
        c.elevation = 200.0 if c.lat > 45.0 else -3000.0
        c.ice_thickness_m = None
    return mesh


def test_dome_profile_matches_perfect_plastic():
    mesh = _flat_world()
    cfg = TerrainPipelineConfig(num_nodes=4000, lloyd_iterations=1, seed=7)
    cfg = dataclasses.replace(
        cfg,
        ice_sheet_insolation_fraction=2.0,  # everything eligible → gate trivially open
        ice_maritime_distance_km=0.0,  # no maritime downgrade → full dome
    )
    apply_polar_ice_sheets(mesh, cfg)

    iced = [c for c in mesh.cells if (c.ice_thickness_m or 0) > 0]
    assert len(iced) > 50, "dome should cover the polar land cap"
    # Coastline untouched: land stays land, ocean untouched
    n_iced = 0
    for c in mesh.cells:
        if c.lat <= 45.0:
            assert c.ice_thickness_m is None
            assert c.elevation == pytest.approx(-3000.0)
        else:
            assert c.elevation >= 200.0  # surface = bed + ice (margin cells: h = 0)
            assert c.elevation - (c.ice_thickness_m or 0.0) == pytest.approx(200.0, abs=1e-6)
            if (c.ice_thickness_m or 0.0) > 0.0:
                n_iced += 1
    assert n_iced > 50

    # Perfect-plastic envelope: h ≤ sqrt(2τ·x/(ρg)) with x = distance to margin;
    # the margin cell itself has h ≈ 0
    tau = cfg.ice_sheet_driving_stress_kpa * 1000.0
    coeff = 2.0 * tau / (RHO_ICE_KG_M3 * cfg.gravity_m_s2)
    # Pole cell (farthest from margin) — its thickness must satisfy the profile
    # bound with x ≤ the cap's maximum radius (~45° ≈ 5000 km on Earth-size).
    pole = max(mesh.cells, key=lambda c: c.lat)
    h_pole = pole.ice_thickness_m or 0.0
    x_max_m = np.radians(45.0) * cfg.radius_km * 1000.0
    assert 0.0 < h_pole <= np.sqrt(coeff * x_max_m) * 1.05
    # And a plausible ice-sheet scale (≥ 1 km at multi-1000-km half-width)
    assert h_pole > 1000.0


def test_idempotent_rerun():
    mesh = _flat_world()
    cfg = dataclasses.replace(
        TerrainPipelineConfig(num_nodes=4000, lloyd_iterations=1, seed=7),
        ice_sheet_insolation_fraction=2.0,
    )
    apply_polar_ice_sheets(mesh, cfg)
    snap = np.array([c.elevation for c in mesh.cells])
    ice_snap = np.array([c.ice_thickness_m or 0.0 for c in mesh.cells])
    apply_polar_ice_sheets(mesh, cfg)
    snap2 = np.array([c.elevation for c in mesh.cells])
    ice_snap2 = np.array([c.ice_thickness_m or 0.0 for c in mesh.cells])
    assert np.allclose(snap, snap2, atol=1e-6)
    assert np.allclose(ice_snap, ice_snap2, atol=1e-6)


def test_maritime_downgrade_to_caps():
    """A small polar island (fully maritime) gets no dome — caps only above the snow line."""
    mesh = _flat_world()
    # Shrink land to a tiny cluster around the pole: everything within 600 km of ocean
    for c in mesh.cells:
        c.elevation = 200.0 if c.lat > 88.0 else -3000.0
        # raise one mountain on the island to exceed the snow line
    mountain = max(mesh.cells, key=lambda c: c.lat)
    mountain.elevation = 1800.0
    cfg = dataclasses.replace(
        TerrainPipelineConfig(num_nodes=4000, lloyd_iterations=1, seed=7),
        ice_sheet_insolation_fraction=2.0,
        ice_maritime_distance_km=700.0,
        ice_cap_snowline_m=1200.0,
        ice_cap_max_m=500.0,
    )
    stats = apply_polar_ice_sheets(mesh, cfg)
    assert stats["dome_cells"] == 0.0, "fully-maritime island must not build a dome"
    assert stats["cap_cells"] >= 1.0, "the above-snowline mountain gets a cap"
    assert (mountain.ice_thickness_m or 0.0) == pytest.approx(min((1800.0 - 1200.0) * 0.5, 500.0))


def test_thermal_gate_follows_the_star():
    """A dimmer star ices further equatorward — gate is flux-aware, not a fixed latitude."""
    lat = np.radians(np.array([0.0, 45.0, 70.0, 89.0]))
    q_earth = annual_mean_insolation(lat, 23.44, 1361.0)
    q_dim = annual_mean_insolation(lat, 23.44, 1361.0 * 0.6)
    # Monotonic decrease poleward on both
    assert q_earth[3] < q_earth[1] < q_earth[0]
    # Dimmer star: lower insolation everywhere → the 240 W/m² threshold sits equatorward
    assert (q_dim < q_earth).all()
    latq = np.degrees(lat)
    assert (latq[q_earth < 240.0].min() if (q_earth < 240.0).any() else 90) > (
        latq[q_dim < 240.0].min() if (q_dim < 240.0).any() else 90
    )


def test_disabled_is_noop():
    mesh = _flat_world()
    before = [c.elevation for c in mesh.cells]
    cfg = dataclasses.replace(
        TerrainPipelineConfig(num_nodes=4000, lloyd_iterations=1, seed=7),
        ice_sheet_enabled=False,
    )
    apply_polar_ice_sheets(mesh, cfg)
    assert [c.elevation for c in mesh.cells] == before
    assert all(c.ice_thickness_m is None for c in mesh.cells)
