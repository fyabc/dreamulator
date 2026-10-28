"""Continuous sources: source identity, geometric integration, and coastal mixed cells."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.map.terrain_source import (
    FrozenStageTerrainField,
    PointTerrainField,
    PolylineGeometry,
    ProjectedTerrainSource,
    RasterTerrainField,
    SphericalSegmentGeometry,
    average_rectangles,
    sample_canvas,
    transition_profile,
)


def test_mixed_cell_has_land_even_when_mean_height_is_negative() -> None:
    geom = CanvasGeometry(67, 179, 6371, 8)
    source = ProjectedTerrainSource(geom, lambda x, y: np.where(x > 0, 100.0, -1000.0), {})
    result = average_rectangles(source, geom, *map(np.array, [-20, -20, 20, 20]))
    assert result.height_m == pytest.approx(-450)
    assert result.land_fraction == pytest.approx(0.5)


def test_spherical_area_and_height_integrals_agree_when_footprint_is_split() -> None:
    geom = CanvasGeometry(76, -179, 6371, 8)
    source = ProjectedTerrainSource(geom, lambda x, y: 1500 + 0.001 * x**2 + y / 3, {})
    whole = average_rectangles(source, geom, *map(np.array, [2000, 1000, 3000, 2000]))
    edges = np.linspace(0, 1000, 5)
    x0, y0 = np.meshgrid(2000 + edges[:-1], 1000 + edges[:-1])
    parts = average_rectangles(source, geom, x0, y0, x0 + 250, y0 + 250)
    assert parts.area_km2.sum() == pytest.approx(whole.area_km2, rel=1e-12)
    assert np.sum(parts.height_m * parts.area_km2) == pytest.approx(
        whole.height_m * whole.area_km2, rel=1e-12
    )
    assert whole.area_km2 < 1_000_000


def test_feature_distance_uses_segments_and_profile_has_fixed_physical_width() -> None:
    feature = PolylineGeometry([np.array([[-1000, 0], [1000, 0], [1000, 1000]])])
    x, y = np.array([0, 1100, -1100]), np.array([20, 500, 0])
    np.testing.assert_allclose(feature.distance_km(x, y), [20, 100, 100])
    profile = transition_profile(
        np.array([0, 25, 50, 100, 200]), 100, np.array(150), np.array(1000)
    )
    np.testing.assert_allclose(profile, [150, 282.8125, 575, 1000, 1000])
    with pytest.raises(ValueError, match="width"):
        transition_profile(np.array(1), 0, np.array(150), np.array(1000))


def test_raster_adapter_preserves_bilinear_surface_and_reports_missing_support() -> None:
    x, y = np.array([-20, 0, 20]), np.array([-30, 0, 30])
    xx, yy = np.meshgrid(x, y)
    values = 20 + xx + 2 * yy + xx * yy / 10
    field = RasterTerrainField(x, y, values)
    qx, qy = np.array([-17, 3, 19]), np.array([12, -13, 21])
    expected = 20 + qx + 2 * qy + qx * qy / 10
    values[:] = -1000
    np.testing.assert_allclose(field(qx, qy), expected)
    assert np.isnan(field(np.array(25), np.array(0)))


def test_curved_coast_coverage_matches_spherical_cap_area() -> None:
    """An independent spherical-cap area checks both the coast indicator and Jacobian."""
    geom = CanvasGeometry(70, 179, 6371, 8)
    source = ProjectedTerrainSource(
        geom, lambda x, y: np.where(np.hypot(x, y) < 1000, 100.0, -1000.0), {}
    )
    edges = np.linspace(-1200, 1200, 97)
    x0, y0 = np.meshgrid(edges[:-1], edges[:-1])
    result = average_rectangles(source, geom, x0, y0, x0 + 25, y0 + 25)
    area = float(np.sum(result.land_fraction * result.area_km2))
    expected = 2 * np.pi * geom.radius_km**2 * (1 - np.cos(1000 / geom.radius_km))
    assert area == pytest.approx(expected, rel=5e-4)


def test_frozen_stage_replays_reference_after_nonlinear_reconstruction() -> None:
    """Independent limiting of a cell delta used to alter an unchanged reference terrain."""
    rng = np.random.default_rng(42)
    xy = rng.uniform(-400, 400, (80, 2))
    before = rng.uniform(-5000, 2000, len(xy))
    after = before + rng.uniform(-1000, 1000, len(xy))
    first = PointTerrainField(xy, before)
    last = PointTerrainField(xy, after)
    independent_delta = PointTerrainField(xy, after - before)
    qx, qy = np.meshgrid(np.linspace(-200, 200, 25), np.linspace(-200, 200, 25))
    expected = last(qx, qy)
    assert np.isfinite(expected).all()
    assert np.max(abs(first(qx, qy) + independent_delta(qx, qy) - expected)) > 100
    field = FrozenStageTerrainField(first, last, first)
    np.testing.assert_array_equal(field(qx, qy), expected)
    geom = CanvasGeometry(0, 0, 6371, 8)
    actual = sample_canvas(ProjectedTerrainSource(geom, field, {}), geom)
    reference = sample_canvas(ProjectedTerrainSource(geom, last, {}), geom)
    np.testing.assert_array_equal(actual.height_m, reference.height_m)
    np.testing.assert_array_equal(actual.land_fraction, reference.land_fraction)


def test_frozen_stage_change_is_local_and_independent_of_query_batches() -> None:
    xy = np.array([(x, y) for x in [-300, 0, 300] for y in [-300, 0, 300]])
    first = PointTerrainField(xy, -1000 + xy[:, 0] * 4)
    last = PointTerrainField(xy, -1200 + xy[:, 0] * 5 + xy[:, 1])

    def replacement(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return np.asarray(first(x, y) + np.where(x**2 + y**2 < 50**2, 250.0, 0.0))

    field = FrozenStageTerrainField(first, last, replacement)
    qx, qy = np.meshgrid(np.linspace(-200, 200, 41), np.linspace(-200, 200, 41))
    h = field(qx, qy)
    changed = qx**2 + qy**2 < 50**2
    np.testing.assert_array_equal(h[~changed], last(qx, qy)[~changed])
    np.testing.assert_allclose((h - last(qx, qy))[changed], 250)
    pieces = [field(x, y) for x, y in zip(qx, qy, strict=True)]
    np.testing.assert_array_equal(np.array(pieces), h)


def test_frozen_stage_chain_agrees_with_direct_reference_endpoints() -> None:
    xy = np.array([(x, y) for x in [-300, 0, 300] for y in [-300, 0, 300]])
    first = PointTerrainField(xy, xy[:, 0] + 20)
    middle = PointTerrainField(xy, xy[:, 1] * 0.5 - 50)
    last = PointTerrainField(xy, xy[:, 0] * xy[:, 1] / 200 + 100)

    def replacement(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return np.asarray(first(x, y) + 30 * np.exp(-(x**2 + y**2) / 100**2))

    first_stage = FrozenStageTerrainField(first, middle, replacement)
    composed = FrozenStageTerrainField(middle, last, first_stage)
    direct = FrozenStageTerrainField(first, last, replacement)
    qx, qy = np.meshgrid(np.linspace(-200, 200, 31), np.linspace(-200, 200, 31))
    np.testing.assert_allclose(composed(qx, qy), direct(qx, qy), rtol=0, atol=1e-12)


def test_spherical_feature_projection_uses_finite_arcs_and_cross_track_position() -> None:
    from dreamulator.map.paleo_sutures import lonlat_to_xyz, polyline_geometry

    path = np.array([[170.0, 0], [-170.0, 0], [-170.0, 15]])
    vertices = lonlat_to_xyz(path)
    geometry = SphericalSegmentGeometry(np.stack([vertices[:-1], vertices[1:]], axis=1))
    q = lonlat_to_xyz(np.array([[180.0, 5], [165.0, 0], [-170.0, 20], [0, 20]]))
    result = geometry.project(q)
    np.testing.assert_allclose(result.distance_rad, polyline_geometry(q, path)[0], atol=1e-12)
    np.testing.assert_allclose(result.fraction[:3], [0.5, 0, 1], atol=1e-12)
    np.testing.assert_array_equal(result.segment_index[:3], [0, 0, 1])
    np.testing.assert_allclose(result.distance_rad[:3], np.radians([5, 5, 5]), atol=1e-12)
    with pytest.raises(ValueError, match="non-antipodal"):
        SphericalSegmentGeometry(np.array([[vertices[0], -vertices[0]]]))
