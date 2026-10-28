"""Finite-area precipitation transfer at seams, poles and source discontinuities."""

import numpy as np
import pytest

from dreamulator.gcm.area_remap import gaussian_rectilinear_coverage
from dreamulator.gcm.native_partition import gaussian_parent_partition


def partition(radius: float = 6371.0):
    mu, _ = np.polynomial.legendre.leggauss(8)
    return gaussian_parent_partition(
        np.degrees(np.arcsin(mu)),
        np.arange(16) * 22.5,
        radius_km=radius,
        spacing_km=radius / 10,
    )


@pytest.mark.parametrize("start", [-180.0, 0.0, 170.0, 890.0])
def test_global_target_preserves_every_source_area_and_component_month(start) -> None:
    p = partition()
    cover = gaussian_rectilinear_coverage(
        p, np.linspace(-90, 90, 31), np.linspace(start, start + 360, 49)
    )
    np.testing.assert_allclose(cover.source_covered_area_km2, p.area_km2, rtol=2e-12)
    rng = np.random.default_rng(85)
    native = rng.uniform(0, 500, (2, 12, len(p.parent_area_km2)))
    prior = rng.uniform(0, 500, (2, 12, len(p.area_km2)))
    native[:, :, 7] = 0
    depths = p.conservative_depths(native, prior_mm=prior)
    volumes = cover.integrals(depths)
    np.testing.assert_allclose(
        volumes.sum(axis=(-2, -1)), (native * p.parent_area_km2).sum(axis=-1), rtol=2e-12
    )
    np.testing.assert_allclose(cover.means(np.ones(len(p.area_km2))), 1, rtol=2e-12)
    np.testing.assert_allclose(cover.area_km2.sum(), 4 * np.pi * p.radius_km**2, rtol=2e-12)
    assert (cover.overlap_km2.data > 0).all()


def test_cell_crossing_rain_boundary_uses_spherical_area_not_centre() -> None:
    p = partition()
    depths = np.where(p.latitude > 0, 200.0, 0.0)
    cover = gaussian_rectilinear_coverage(p, np.array([-10.0, 30.0]), np.array([170.0, 190.0]))
    wet_fraction = np.sin(np.radians(30)) / (np.sin(np.radians(30)) - np.sin(np.radians(-10)))
    np.testing.assert_allclose(cover.means(depths), 200 * wet_fraction, rtol=2e-12)
    # The centre sample is 200 mm; the finite cell includes dry southern area.
    assert float(cover.means(depths).item()) < 200
    np.testing.assert_allclose(
        cover.integrals(depths).sum(), np.dot(depths, cover.source_covered_area_km2), rtol=2e-12
    )


def test_polar_crop_periodicity_and_radius_scaling() -> None:
    p, q = partition(), partition(12742.0)
    lat, lon = np.array([87.0, 89.0, 90.0]), np.array([350.0, 360.0, 370.0])
    a, b = (gaussian_rectilinear_coverage(s, lat, lon) for s in (p, q))
    shifted = gaussian_rectilinear_coverage(p, lat, lon + 720)
    depths = np.arange(len(p.area_km2), dtype=float) + 1
    np.testing.assert_allclose(a.means(depths), b.means(depths), rtol=2e-12)
    np.testing.assert_allclose(b.integrals(depths), a.integrals(depths) * 4, rtol=2e-12)
    np.testing.assert_allclose(shifted.integrals(depths), a.integrals(depths), rtol=2e-12)
