"""Old orogens along paleo-sutures (map/paleo_orogens.py)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.paleo_orogens import (
    DECAY_MYR,
    RESIDUAL_CREST_M,
    paleo_orogen_relief,
    residual_crest_m,
)
from dreamulator.map.paleo_sutures import AuthorSuture
from dreamulator.map.pipeline_types import TerrainPipelineConfig


def test_residual_crest_decay() -> None:
    assert residual_crest_m(0.0, 3000.0) == pytest.approx(3000.0)
    assert residual_crest_m(DECAY_MYR, 3000.0) == pytest.approx(
        RESIDUAL_CREST_M + (3000.0 - RESIDUAL_CREST_M) / math.e
    )
    # old belts approach the residual, never below it
    assert residual_crest_m(1000.0, 3000.0) == pytest.approx(RESIDUAL_CREST_M, abs=1.0)
    assert residual_crest_m(50.0, 100.0) == pytest.approx(RESIDUAL_CREST_M)


def test_relief_along_suture_only_on_land_crust() -> None:
    cfg = TerrainPipelineConfig(num_nodes=4000, lloyd_iterations=1, seed=3)
    mesh = generate_cvt_mesh(cfg)
    for c in mesh.cells:
        c.crust_type = "continental" if c.lon < 0 else "oceanic"
    s = AuthorSuture(
        id="s",
        name="s",
        collision_age_myr=70.0,
        path=np.array([[-60.0, -40.0], [-60.0, 40.0]]),
        width_km=500.0,
    )
    relief = paleo_orogen_relief(mesh, [s], 2000.0, cfg.radius_km)
    lon = np.array([c.lon for c in mesh.cells])
    lat = np.array([c.lat for c in mesh.cells])
    assert (relief[lon >= 0] == 0.0).all()
    crest = residual_crest_m(70.0, 2000.0)
    assert 0.0 < relief.max() <= crest
    # near the path the belt reaches most of its crest; beyond the wedge half-width
    # (2 km / tan 0.6° ≈ 191 km) it is zero
    near = (np.abs(lon + 60.0) < 0.5) & (np.abs(lat) < 30.0)
    assert relief[near].min() > 0.6 * crest
    far = (lon < -65.0) & (np.abs(lat) < 30.0)
    assert (relief[far] == 0.0).all()
    # no sutures (or no age) → no old orogens
    assert not paleo_orogen_relief(mesh, [], 2000.0, cfg.radius_km).any()
    s0 = AuthorSuture(id="u", name="u", collision_age_myr=None, path=s.path)
    assert not paleo_orogen_relief(mesh, [s0], 2000.0, cfg.radius_km).any()
