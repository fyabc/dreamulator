"""Shared ice geometry, lake-at-rest balance and counted marine export."""

import numpy as np
import pytest
from scipy.spatial import SphericalVoronoi

from dreamulator.map.ice_mass_balance import annual_ice_balance
from dreamulator.map.spherical_ice_flow import (
    evolve_spherical_ice,
    flow_spherical_ice,
    spherical_ice_mesh,
)


def _geometry(*, marine: bool = False, rotation: np.ndarray | None = None):
    rng = np.random.default_rng(12)
    points = rng.normal(size=(40, 3))
    points /= np.linalg.norm(points, axis=1)[:, None]
    voronoi = SphericalVoronoi(points)
    voronoi.sort_vertices_of_regions()
    owners: dict[tuple[int, int], list[int]] = {}
    for i, region in enumerate(voronoi.regions):
        for a, b in zip(region, region[1:] + region[:1], strict=True):
            owners.setdefault(tuple(sorted((a, b))), []).append(i)
    faces = np.array(list(owners.values()))
    vertices = voronoi.vertices[np.array(list(owners))]
    ocean = points[:, 2] < -0.2 if marine else np.zeros(len(points), dtype=bool)
    if rotation is not None:
        points, vertices = points @ rotation, vertices @ rotation
    return spherical_ice_mesh(
        points,
        voronoi.calculate_areas() * 200_000**2,
        faces,
        vertices,
        ~ocean,
        ocean,
        radius_m=200_000,
    )


def test_constant_ice_surface_over_rough_bed_is_stationary():
    mesh = _geometry()
    bed = np.linspace(-200, 600, len(mesh.cell_indices))
    initial = 1200 - bed
    final, budget = flow_spherical_ice(mesh, bed, initial, elapsed_yr=100, gravity_m_s2=9.81)
    np.testing.assert_array_equal(final, initial)
    assert budget.ocean_export_m3 == budget.residual_m3 == 0


def test_unequal_cell_areas_conserve_volume_while_ice_enters_bare_land():
    mesh = _geometry()
    initial = np.zeros(len(mesh.cell_indices))
    initial[0] = 1800
    final, budget = flow_spherical_ice(
        mesh,
        np.zeros_like(initial),
        initial,
        elapsed_yr=20,
        gravity_m_s2=9.81,
    )
    assert np.count_nonzero(final) > 1
    assert final.min() >= 0
    assert final[0] < initial[0]
    assert budget.final_volume_m3 == pytest.approx(budget.initial_volume_m3, rel=1e-12)


def test_absorbing_ocean_export_closes_budget_and_is_rotation_invariant():
    mesh = _geometry(marine=True)
    initial = np.full(len(mesh.cell_indices), 1800.0)
    bed = np.zeros_like(initial)
    final, budget = flow_spherical_ice(mesh, bed, initial, elapsed_yr=20, gravity_m_s2=9.81)
    assert budget.ocean_export_m3 > 0
    assert budget.final_volume_m3 < budget.initial_volume_m3
    assert budget.final_volume_m3 + budget.ocean_export_m3 == pytest.approx(
        budget.initial_volume_m3,
        rel=1e-12,
    )
    closed, closed_budget = flow_spherical_ice(
        mesh,
        bed,
        initial,
        elapsed_yr=20,
        gravity_m_s2=9.81,
        open_ocean=False,
    )
    np.testing.assert_array_equal(closed, initial)
    assert closed_budget.ocean_export_m3 == 0
    angle = 0.7
    rotation = np.array(
        [[np.cos(angle), np.sin(angle), 0], [-np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
    )
    rotated, _ = flow_spherical_ice(
        _geometry(marine=True, rotation=rotation),
        bed,
        initial,
        elapsed_yr=20,
        gravity_m_s2=9.81,
    )
    np.testing.assert_allclose(rotated, final, rtol=1e-12, atol=1e-10)


def test_shared_annual_balance_matches_seasonal_budget_with_limited_ice():
    mesh = _geometry()
    initial = np.full(len(mesh.cell_indices), 0.05)
    snow = np.broadcast_to(np.arange(12)[:, None] * 3.0, (12, len(initial))).copy()
    pdd = np.broadcast_to(np.arange(12)[::-1, None] * 2.0, snow.shape).copy()
    reference = initial.copy()
    for _ in range(4):
        reference = annual_ice_balance(reference, snow, pdd).ice_equivalent_m
    final, budget = evolve_spherical_ice(
        mesh,
        np.zeros_like(initial),
        initial,
        np.stack([snow, snow]),
        np.stack([pdd, pdd]),
        np.array([0.0, 4.0]),
        elapsed_yr=4,
        gravity_m_s2=9.81,
    )
    np.testing.assert_allclose(final, reference, rtol=1e-12, atol=1e-12)
    assert budget.ocean_export_m3 == 0
    assert abs(budget.residual_m3) < 1e-12 * budget.snowfall_volume_m3
