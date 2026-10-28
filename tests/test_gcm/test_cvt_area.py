"""Global finite CVT areas and each native parent/component/month water quota."""

import numpy as np
import pytest
from scipy.spatial import SphericalVoronoi

from dreamulator.gcm.cvt_area import CvtPrecipitationCoverage, cvt_precipitation_coverage
from dreamulator.gcm.native_partition import NativePrecipitationField, gaussian_parent_partition


def sites(n: int = 128):
    i = np.arange(n)
    latitude = np.degrees(np.arcsin(1 - 2 * (i + 0.5) / n))
    longitude = (i * 137.50776405003785) % 360
    return latitude, longitude


@pytest.fixture(scope="module")
def setup():
    mu, _ = np.polynomial.legendre.leggauss(8)
    partition = gaussian_parent_partition(
        np.degrees(np.arcsin(mu)), np.arange(16) * 22.5, radius_km=6371.0, spacing_km=600.0
    )
    lat, lon = sites()
    return partition, lat, lon, cvt_precipitation_coverage(partition, lat, lon)


def test_complete_native_area_constant_field_and_each_month_component_budget(setup) -> None:
    p, lat, lon, coverage = setup
    cells = coverage.cells
    np.testing.assert_allclose(cells.source_covered_area_km2, p.area_km2, rtol=4e-15)
    np.testing.assert_allclose(cells.means(np.ones(len(p.area_km2))), 1, rtol=4e-15)
    np.testing.assert_allclose(cells.area_km2.sum(), 4 * np.pi * p.radius_km**2, rtol=4e-15)
    rng = np.random.default_rng(85)
    native = rng.uniform(0, 300, (2, 12, len(p.parent_area_km2)))
    native[:, :, 7] = 0
    depth = p.conservative_depths(native, prior_mm=rng.uniform(0, 300, (2, 12, len(p.area_km2))))
    field = NativePrecipitationField(p, native, depth, {})
    target = cells.means(field.component_monthly_mm)
    np.testing.assert_allclose(
        (target * cells.area_km2).sum(axis=-1),
        (native * p.parent_area_km2).sum(axis=-1),
        rtol=5e-15,
    )
    assigned = field.component_monthly_mm * cells.source_covered_area_km2
    np.testing.assert_allclose(
        np.add.reduceat(assigned, p.offsets[:-1], axis=-1), native * p.parent_area_km2, rtol=5e-15
    )
    assert (target >= 0).all()
    assert (cells.overlap_km2.data > 0).all()


def test_area_checked_by_independent_spherical_triangle_solid_angles(setup) -> None:
    p, lat, lon, coverage = setup
    la, lo = np.radians(lat), np.radians(lon)
    xyz = np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])
    sv = SphericalVoronoi(xyz)
    sv.sort_vertices_of_regions()
    area = []
    for region in sv.regions:
        vertices = sv.vertices[region]
        angle = 0.0
        for k in range(1, len(vertices) - 1):
            a, b, c = vertices[[0, k, k + 1]]
            angle += 2 * np.arctan2(
                np.dot(a, np.cross(b, c)), 1 + np.dot(a, b) + np.dot(b, c) + np.dot(c, a)
            )
        area.append(abs(angle) * p.radius_km**2)
    np.testing.assert_allclose(coverage.geometric_area_km2, area, rtol=2e-13)
    np.testing.assert_allclose(coverage.cells.area_km2, area, rtol=2e-6)


def test_archive_roundtrip_rejects_other_sites_and_corrupted_areas(setup, tmp_path) -> None:
    p, lat, lon, coverage = setup
    path = tmp_path / "coverage.npz"
    coverage.save(path)
    restored = CvtPrecipitationCoverage.load(path, p, lat, lon)
    np.testing.assert_array_equal(restored.cells.area_km2, coverage.cells.area_km2)
    values = np.arange(len(p.area_km2), dtype=float)
    np.testing.assert_array_equal(restored.cells.means(values), coverage.cells.means(values))
    with pytest.raises(ValueError, match="geometry"):
        CvtPrecipitationCoverage.load(path, p, lat + 0.001, lon)
    with np.load(path) as archive:
        data = {k: archive[k] for k in archive.files}
    data["area_km2"] = data["area_km2"] + 1
    np.savez_compressed(path, **data)
    with pytest.raises(ValueError, match="area ledger"):
        CvtPrecipitationCoverage.load(path, p, lat, lon)
