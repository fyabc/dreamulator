"""Continental shelf on submerged continental crust (terrain_synthesizer)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_synthesizer import _apply_continental_shelf

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh


@pytest.fixture(scope="module")
def base() -> tuple[TerrainPipelineConfig, CVTMesh]:
    # small planet: ~97 km spacing, so the 31–88 km margin belts are resolved
    cfg = TerrainPipelineConfig(num_nodes=3000, seed=7, lloyd_iterations=2, radius_km=1500.0)
    return cfg, generate_cvt_mesh(cfg)


def _world(base: tuple[TerrainPipelineConfig, CVTMesh], drowned_band_deg: float):
    """A polar-cap continent (lat > 30°) with continental crust reaching further south."""
    cfg, mesh = base
    lat = np.array([c.lat for c in mesh.cells])
    elevation = np.where(lat > 30.0, 500.0, -4000.0)
    for c, la in zip(mesh.cells, lat, strict=True):
        c.crust_type = "continental" if la > 30.0 - drowned_band_deg else "oceanic"
        c.elevation = 0.0
    return cfg, mesh, elevation, lat


def test_land_unchanged_and_ocean_stays_ocean(base) -> None:
    cfg, mesh, z, _ = _world(base, 6.0)
    out = _apply_continental_shelf(mesh, z.copy(), cfg, np.random.default_rng(0))
    assert np.array_equal(out > 0, z > 0)
    assert np.array_equal(out[z > 0], z[z > 0])
    assert out[z <= 0].max() < 0.0


def _shelf_extent_km(mesh, out, lat) -> float:
    """Farthest distance (km) south of the 30° coast still above the shelf break."""
    shallow = (out > -130.0 * 1.06) & (out <= 0.0) & (lat < 30.0)
    return float(np.radians(30.0 - lat[shallow].min()) * 1500.0) if shallow.any() else 0.0


def test_drowned_crust_widens_the_shelf(base) -> None:
    cfg, mesh, z, lat = _world(base, 6.0)  # ~670 km of drowned continental crust
    wide = _apply_continental_shelf(mesh, z.copy(), cfg, np.random.default_rng(0))
    cfg, mesh, z, lat = _world(base, 0.0)  # COB at the coastline: passive belt only
    belt = _apply_continental_shelf(mesh, z.copy(), cfg, np.random.default_rng(0))
    assert _shelf_extent_km(mesh, wide, lat) > _shelf_extent_km(mesh, belt, lat) > 0.0


def test_active_margin_shelf_is_narrower(base) -> None:
    cfg, mesh, z, lat = _world(base, 0.0)
    passive = _apply_continental_shelf(mesh, z.copy(), cfg, np.random.default_rng(0))
    for c in mesh.cells:  # a convergent boundary right at the coast
        c.distance_to_boundary_km = 50.0
        c.convergence_rate_cm_yr = 5.0
    active = _apply_continental_shelf(mesh, z.copy(), cfg, np.random.default_rng(0))
    first_ring = (lat < 30.0) & (lat > 28.0)
    assert np.median(active[first_ring]) < np.median(passive[first_ring])


def test_disabled_by_nonpositive_width(base) -> None:
    cfg, mesh, z, _ = _world(base, 6.0)
    off = TerrainPipelineConfig(**{**cfg.__dict__, "shelf_width_km": 0.0})
    out = _apply_continental_shelf(mesh, z.copy(), off, np.random.default_rng(0))
    assert np.array_equal(out, z)


def test_stage_crust_capture_distinguishes_drowned_crust_land_and_unknown_labels(base) -> None:
    cfg, mesh, z, lat = _world(base, 6.0)
    # A drowned continental margin remains crust; elevated oceanic material and
    # an unresolved label remain separate from the shelf's continental domain.
    drowned = int(np.flatnonzero((lat > 24) & (lat < 30))[0])
    elevated_oceanic = int(np.flatnonzero(lat < 20)[0])
    unknown = int(np.flatnonzero(lat < 0)[-1])
    z[elevated_oceanic] = 20
    mesh.cells[unknown].crust_type = None
    disabled = TerrainPipelineConfig(**{**cfg.__dict__, "shelf_width_km": 0.0})
    fields: dict[str, np.ndarray] = {}
    rng = np.random.default_rng(8)
    reference_rng = np.random.default_rng(8)
    result = _apply_continental_shelf(mesh, z.copy(), disabled, rng, source_fields=fields)
    crust = fields["shelf_continental_crust_mask"]
    assert crust[drowned] and z[drowned] < 0
    assert not crust[elevated_oceanic] and z[elevated_oceanic] > 0
    assert not crust[unknown]
    assert not crust.flags.writeable
    np.testing.assert_array_equal(result, z)
    np.testing.assert_array_equal(rng.random(20), reference_rng.random(20))


def test_explicit_down_going_flexure_keeps_incoming_floor_and_random_sequence(base) -> None:
    cfg, mesh, z, lat = _world(base, 0.0)
    # A source-defined part of the ocean lies on the incoming plate. The
    # opposite side remains eligible for the same shelf calculation.
    incoming = (lat < 30) & (lat > 10) & (mesh.cell_xyz[:, 0] > 0)
    old_rng, new_rng = np.random.default_rng(8), np.random.default_rng(8)
    control = _apply_continental_shelf(mesh, z.copy(), cfg, old_rng)
    result = _apply_continental_shelf(mesh, z.copy(), cfg, new_rng, active_flexure=incoming)
    assert np.any(control[incoming] != z[incoming])
    np.testing.assert_array_equal(result[incoming], z[incoming])
    np.testing.assert_array_equal(result[~incoming], control[~incoming])
    np.testing.assert_array_equal(old_rng.random(20), new_rng.random(20))
    np.testing.assert_array_equal(result > 0, control > 0)
