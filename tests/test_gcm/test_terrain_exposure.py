"""Geometry and water-budget contracts of terrain-exposure refinement."""

import numpy as np

from dreamulator.gcm.native_partition import NativePrecipitationField, gaussian_parent_partition
from dreamulator.gcm.terrain_exposure import (
    refine_large_scale_precipitation,
    terrain_exposure_index,
    upwind_coordinates,
)


def test_exposure_flat_datum_and_reversed_ridge():
    lat = np.zeros(9)
    lon = np.linspace(-1.5, 1.5, 9)
    args = {"integration_spacing_km": 50.0}
    flat = terrain_exposure_index(lat, lon, np.pi / 2, 6371.0, lambda a, b: a * 0 + 500, **args)
    np.testing.assert_array_equal(flat, np.ones(9))

    def ridge(a, b):
        return 1500 * np.exp(-((((b + 180) % 360 - 180) / 0.5) ** 2))

    east = terrain_exposure_index(lat, lon, np.pi / 2, 6371.0, ridge, **args)
    west = terrain_exposure_index(lat, lon, -np.pi / 2, 6371.0, ridge, **args)
    shifted = terrain_exposure_index(
        lat, lon, np.pi / 2, 6371.0, lambda a, b: ridge(a, b) + 1000, **args
    )
    np.testing.assert_allclose(east, west[::-1], rtol=0, atol=1e-12)
    np.testing.assert_allclose(east, shifted, rtol=0, atol=1e-12)
    assert east[3] > east[5]
    assert (east > 0).all()


def test_ray_preserves_dateline_and_polar_distance():
    lat = np.array([0.0, 89.5])
    lon = np.array([179.9, 0.0])
    dest_lat, dest_lon = upwind_coordinates(lat, lon, np.pi, 300.0, 6371.0)
    a, b = np.radians(lat), np.radians(dest_lat)
    cosine = np.sin(a) * np.sin(b) + np.cos(a) * np.cos(b) * np.cos(np.radians(dest_lon - lon))
    np.testing.assert_allclose(6371.0 * np.arccos(cosine), 300, atol=2e-10)
    assert np.isfinite(dest_lat).all()


def test_refinement_conserves_components_and_retains_convection():
    lat = np.degrees(np.arcsin(np.polynomial.legendre.leggauss(4)[0]))
    p = gaussian_parent_partition(lat, np.arange(8) * 45.0, radius_km=6371, spacing_km=5000)
    native = np.full((2, 12, 32), 20.0)
    native[0, 0, 0] = 0
    baseline = NativePrecipitationField(p, native, p.conservative_depths(native), {})
    ratio = np.stack([np.linspace(0.5, 2, len(p.area_km2)), np.ones(len(p.area_km2))])
    weights = np.full((12, 2, 32), 0.5)
    result = refine_large_scale_precipitation(baseline, ratio, weights, provenance={})
    np.testing.assert_array_equal(result.component_monthly_mm[1], baseline.component_monthly_mm[1])
    np.testing.assert_allclose(
        p.parent_integrals(result.component_monthly_mm), native * p.parent_area_km2, rtol=1e-14
    )
    unchanged = refine_large_scale_precipitation(baseline, ratio, weights * 0, provenance={})
    np.testing.assert_allclose(
        unchanged.component_monthly_mm, baseline.component_monthly_mm, atol=1e-14
    )
