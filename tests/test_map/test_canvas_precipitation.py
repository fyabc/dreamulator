"""Projected area convergence, polar geometry and actual rainfall-boundary splitting."""

import numpy as np
import pytest

from dreamulator.gcm.native_partition import gaussian_parent_partition
from dreamulator.map.canvas_precipitation import canvas_precipitation_coverage
from dreamulator.map.td_canvas import CanvasGeometry


def source(radius: float = 6371.0):
    mu, _ = np.polynomial.legendre.leggauss(8)
    return gaussian_parent_partition(
        np.degrees(np.arcsin(mu)), np.arange(16) * 22.5, radius_km=radius, spacing_km=radius / 12
    )


@pytest.mark.parametrize("latitude", [0.0, 60.0, 89.95, 90.0, -90.0])
def test_footprint_area_against_independent_dense_projection_quadrature(latitude) -> None:
    p = source()
    g = CanvasGeometry(latitude, 180.0, p.radius_km, 8)
    result = canvas_precipitation_coverage(p, g)
    c = result.cells
    # Integrate the projection Jacobian over the full square with a separate
    # midpoint rule rather than the operator's per-cell Gaussian rule.
    axis = (np.arange(1000) + 0.5) / 1000 * 2 * g.half_km - g.half_km
    x, y = np.meshgrid(axis, axis)
    expected = np.sinc(np.hypot(x, y) / (np.pi * g.radius_km)).mean() * (2 * g.half_km) ** 2
    np.testing.assert_allclose(c.area_km2.sum(), expected, rtol=2e-6)
    np.testing.assert_allclose(c.means(np.ones(len(p.area_km2))), 1.0, rtol=2e-14)
    assert (c.area_km2 > 0).all() and (c.overlap_km2.data > 0).all()
    assert result.max_area_relative_error <= 2e-6
    assert result.max_overlap_change_relative <= 2e-6


def test_cross_equator_and_longitude_seam_gives_analytic_rain_share() -> None:
    p = source()
    # Latitude zero passes through cells rather than lying on their grid edge.
    g = CanvasGeometry(0.04, 180.0, p.radius_km, 8)
    c = canvas_precipitation_coverage(p, g).cells
    depths = np.where(p.latitude > 0, 200.0, 0.0)
    mean = c.means(depths)
    assert ((mean > 0) & (mean < 200)).any()
    np.testing.assert_allclose(
        c.integrals(depths).sum(), np.dot(depths, c.source_covered_area_km2), rtol=2e-14
    )
    # Independent fine integration through the shared public projection.
    lat, _ = g.coarse_centres_latlon(oversample=128)
    a = (np.arange(g.ncell * 128) + 0.5) * 23 / 128 - g.half_km
    x, y = np.meshgrid(a, a[::-1])
    jac = np.sinc(np.hypot(x, y) / (np.pi * g.radius_km))
    oracle = ((lat > 0) * jac).reshape(8, 128, 8, 128).sum(axis=(1, 3))
    oracle /= jac.reshape(8, 128, 8, 128).sum(axis=(1, 3))
    np.testing.assert_allclose(mean, oracle * 200, atol=1.6)
    shifted = canvas_precipitation_coverage(p, CanvasGeometry(0.04, -180.0, p.radius_km, 8)).cells
    np.testing.assert_allclose(shifted.means(depths), mean, rtol=2e-12)


def test_component_month_crop_volume_radius_and_subdivision_convergence() -> None:
    p = source()
    g = CanvasGeometry(40.0, 169.0, p.radius_km, 8)
    a = canvas_precipitation_coverage(p, g).cells
    tight = canvas_precipitation_coverage(
        p, g, relative_tolerance=2e-7, max_subdivisions=4096
    ).cells
    rng = np.random.default_rng(85)
    native = rng.uniform(0, 200, (2, 12, len(p.parent_area_km2)))
    native[:, :, 0] = 0
    depths = p.conservative_depths(native, prior_mm=rng.uniform(0, 300, (2, 12, len(p.area_km2))))
    expected = (depths * a.source_covered_area_km2).sum(axis=-1)
    np.testing.assert_allclose(a.integrals(depths).sum(axis=(-2, -1)), expected, rtol=2e-14)
    # L1 geometry convergence also bounds intensities from a discontinuous source.
    assert abs(a.means(depths) - tight.means(depths)).max() < 0.003
    assert a.source_covered_area_km2[0] == 0
    q = source(12742.0)
    b = canvas_precipitation_coverage(q, CanvasGeometry(40.0, 169.0, q.radius_km, 16)).cells
    np.testing.assert_allclose(b.area_km2.sum(), a.area_km2.sum() * 4, rtol=2e-6)


def test_pole_inside_cell_has_full_longitude_cap_and_positive_area() -> None:
    p = source()
    g = CanvasGeometry(89.96, 27.0, p.radius_km, 7)
    c = canvas_precipitation_coverage(p, g).cells
    values = np.arange(len(p.area_km2), dtype=float)
    np.testing.assert_allclose(
        c.integrals(values).sum(), values @ c.source_covered_area_km2, rtol=2e-14
    )
    assert (c.area_km2 > 0).all()
