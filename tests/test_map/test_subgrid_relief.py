"""Sub-grid relief and peak elevation (map/subgrid_relief.py)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.subgrid_relief import subgrid_relief
from dreamulator.map.terrain_pipeline import run_terrain_pipeline


@pytest.fixture(scope="module")
def mesh():
    cfg = TerrainPipelineConfig(num_nodes=2000, lloyd_iterations=1, seed=3)
    return run_terrain_pipeline(cfg, stages=["mesh"], cache=None).mesh


def test_flat_land_has_no_relief(mesh) -> None:
    for c in mesh.cells:
        c.elevation = 500.0
    std, peak = subgrid_relief(mesh, 6371.0)
    assert np.allclose(std, 0.0) and np.allclose(peak, 500.0)


def test_relief_grows_with_slope_saturates_and_skips_ocean(mesh) -> None:
    lat = np.array([c.lat for c in mesh.cells])
    stds = []
    for k in (5.0, 50.0, 500.0):  # m per degree of latitude
        for c, la in zip(mesh.cells, lat, strict=True):
            c.elevation = 100.0 + k * (la + 60.0) if la > -60 else -3000.0
        std, peak = subgrid_relief(mesh, 6371.0)
        ocean = lat <= -60
        assert np.isnan(std[ocean]).all() and np.isnan(peak[ocean]).all()
        band = (lat > -30) & (lat < 30)
        stds.append(float(np.median(std[band])))
        assert np.allclose(peak[band], 100.0 + k * (lat[band] + 60.0) + 3.5 * std[band])
    assert stds[0] < stds[1] < stds[2]
    # tenfold slope: near-linear at low slope, saturating at high slope
    assert stds[1] / stds[0] == pytest.approx(10.0, rel=0.1)
    assert stds[2] / stds[1] < 8.0
