"""Trench flexure of the subducting plate (map/trench_flexure.py)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.orogen_contract import build_orogen_contract, contact_polarity
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline
from dreamulator.map.trench_flexure import (
    AXIS_DEFLECTION_M,
    cell_mean_factor,
    flexural_parameter_km,
    trench_relief,
    trench_sources,
)

TINY = dict(num_nodes=1500, lloyd_iterations=1, num_plates=8, seed=7, tectonic_duration_my=20.0)


def test_flexural_parameter_earth_and_gravity_scaling() -> None:
    # Te = 25 km, E = 70 GPa, ν = 0.25, ρm − ρw = 2270 kg/m³ → α ≈ 65 km on Earth
    assert flexural_parameter_km(9.81) == pytest.approx(64.6, abs=0.3)
    assert flexural_parameter_km(2 * 9.81) == pytest.approx(64.6 * 2**-0.25, abs=0.3)


def test_cell_mean_factor() -> None:
    alpha = 64.6
    # 54 km axis cell averages 0.62 of the axis deflection; the next ring 0.10
    assert cell_mean_factor(np.array([0.0]), 54.0, alpha)[0] == pytest.approx(0.617, abs=0.005)
    assert cell_mean_factor(np.array([54.0]), 54.0, alpha)[0] == pytest.approx(0.105, abs=0.005)
    # tiny cells recover the point profile, including the outer rise (negative factor)
    x = np.array([0.0, np.pi * alpha])
    point = np.exp(-x / alpha) * np.cos(x / alpha)
    assert cell_mean_factor(x, 1e-3, alpha) == pytest.approx(point, abs=1e-4)
    # the profile ends at 3π/2·α where w = 0: beyond it nothing
    assert cell_mean_factor(np.array([1.5 * np.pi * alpha + 1.0]), 54.0, alpha)[0] == 0.0


@pytest.fixture(scope="module")
def built():
    cfg = TerrainPipelineConfig(**TINY)
    res = run_terrain_pipeline(
        cfg, stages=["mesh", "plates", "tectonics", "boundaries"], cache=None
    )
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    return cfg, res, contract


def test_polarity_ocean_contacts_faster_plate_down(built) -> None:
    cfg, res, _ = built
    pol = contact_polarity(res.mesh, res.plates, cfg.radius_km)
    pairs: dict[frozenset[str], set[str]] = {}
    for kind, down, over in pol.values():
        assert down != over
        if kind == "ocean":
            pairs.setdefault(frozenset((down, over)), set()).add(down)
    # one down-going plate per ocean–ocean pair
    assert all(len(v) == 1 for v in pairs.values())


def test_trench_only_on_down_going_oceanic_cells(built) -> None:
    cfg, res, contract = built
    sources = trench_sources(res.mesh, res.plates, contract, cfg.radius_km)
    relief, axis, sub = trench_relief(res.mesh, res.plates, contract, cfg.radius_km, 9.81)
    if not sources:
        pytest.skip("tiny world has no subducting oceanic contact")
    cells = res.mesh.cells
    down_plates = set(sources.values())
    touched = np.flatnonzero(relief != 0.0)
    assert sub[touched].all()
    for i in touched:
        assert cells[i].crust_type == "oceanic"
        assert cells[i].plate_id in down_plates
    # moat bounded by the axis deflection; the outer rise is small
    assert relief.min() >= -AXIS_DEFLECTION_M
    assert relief.max() <= 0.05 * AXIS_DEFLECTION_M
    # the axis point lies W0 below the seafloor, i.e. below the cell mean
    ax = np.flatnonzero(np.isfinite(axis))
    assert set(ax.tolist()) == set(sources)
    assert np.allclose(relief[ax] + axis[ax], -AXIS_DEFLECTION_M)
    assert (axis[ax] < 0.0).all()


def test_forearc_wedge(built) -> None:
    import math

    from dreamulator.map.trench_flexure import FOREARC_SLOPE_DEG, forearc

    cfg, res, contract = built
    n = len(res.mesh.cells)
    # tiny-world cells are ~580 km apart: a deep axis makes the wedge span several cells
    axis_mean = np.full(n, -40000.0)
    surface, width = forearc(res.mesh, contract, axis_mean, cfg.radius_km)
    andean = [s for s in contract.segments if s.kind == "andean"]
    if not andean:
        pytest.skip("tiny world has no ocean–continent margin")
    # the wedge reaches sea level at |axis| / tan α
    expect = 40.0 / math.tan(math.radians(FOREARC_SLOPE_DEG))
    assert all(w == pytest.approx(expect) for w in width.values())
    assert set(width) == {k for s in andean for k in s.cell_ids}
    cap = np.isfinite(surface)
    assert cap.any()
    assert (surface[cap] >= -40000.0).all() and (surface[cap] < 6000.0 + 1e-6).all()
    # the down-going plate's own axis cells are never bounded (the wedge sits on the other side)
    cells = res.mesh.cells
    for seg in andean:
        for k in seg.cell_ids:
            if cells[k].plate_id == seg.pro_plate and cells[k].crust_type == "oceanic":
                assert not cap[k]
