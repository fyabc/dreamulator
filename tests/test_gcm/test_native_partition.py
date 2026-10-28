"""Native spherical area, dry-parent isolation and monthly closure integration."""

import numpy as np
import pytest

from dreamulator.gcm.native_partition import NativePrecipitationField, gaussian_parent_partition
from dreamulator.gcm.precipitation_shares import ComponentDriver, monthly_component_shares


def grid(nlat: int = 8, nlon: int = 16) -> tuple[np.ndarray, np.ndarray]:
    mu, _ = np.polynomial.legendre.leggauss(nlat)
    return np.degrees(np.arcsin(mu)), np.arange(nlon) * 360.0 / nlon


def test_full_sphere_and_each_native_quadrature_parent_are_covered() -> None:
    lat, lon = grid()
    part = gaussian_parent_partition(lat, lon, radius_km=6371.0, spacing_km=500.0)
    _, weights = np.polynomial.legendre.leggauss(len(lat))
    expected = np.repeat(weights * 2 * np.pi / len(lon) * 6371.0**2, len(lon))
    np.testing.assert_allclose(
        part.parent_integrals(np.ones(len(part.area_km2))), expected, rtol=7e-15
    )
    np.testing.assert_allclose(part.area_km2.sum(), 4 * np.pi * 6371.0**2, rtol=7e-15)
    assert (part.area_km2 > 0).all()
    assert part.mu_edges[0] == -1 and part.mu_edges[-1] == 1
    assert part.area_roundoff_relative_max < 1e-12


def test_centres_seam_poles_and_periodic_queries_keep_native_ownership() -> None:
    lat, lon = grid()
    p = gaussian_parent_partition(lat, lon, radius_km=6371.0, spacing_km=500.0)
    np.testing.assert_array_equal(p.locate(p.latitude, p.longitude), np.arange(len(p.area_km2)))
    la = np.array([-90.0, -40.0, 0.0, 47.0, 90.0])
    lo = np.array([-180.0, -359.0, 0.0, 359.0, 180.0])
    np.testing.assert_array_equal(p.locate(la, lo), p.locate(la, lo + 720))
    parent = p.parent_index[p.locate(la, lo)]
    assert parent[0] // len(lon) == 0
    assert parent[-1] // len(lon) == len(lat) - 1
    assert parent[2] % len(lon) == 0


def test_each_component_and_month_preserves_its_parent_budget_with_unequal_child_areas() -> None:
    lat, lon = grid()
    p = gaussian_parent_partition(lat, lon, radius_km=6371.0, spacing_km=500.0)
    rng = np.random.default_rng(31)
    native = rng.uniform(0, 300, size=(2, 12, len(p.parent_area_km2)))
    native[:, :, 7] = 0
    prior = rng.uniform(0, 200, size=(2, 12, len(p.area_km2)))
    prior[:, :, p.parent_index == 14] = 0
    output = p.conservative_depths(native, prior_mm=prior)
    np.testing.assert_allclose(p.parent_integrals(output), native * p.parent_area_km2, rtol=7e-15)
    assert not output[:, :, p.parent_index == 7].any()
    np.testing.assert_array_equal(
        output[:, :, p.parent_index == 14],
        native[:, :, 14, None] * np.ones((p.parent_index == 14).sum()),
    )
    np.testing.assert_allclose(
        p.parent_integrals(p.conservative_depths(native)), native * p.parent_area_km2, rtol=7e-15
    )


def test_real_area_partition_is_accepted_by_supported_and_unresolved_monthly_closure() -> None:
    lat, lon = grid(4, 8)
    p = gaussian_parent_partition(lat, lon, radius_km=6371.0, spacing_km=500.0)
    native = np.arange(len(p.parent_area_km2), dtype=float) + 1
    prior = 5 + np.cos(np.radians(p.longitude))
    depth = p.conservative_depths(native, prior_mm=prior)
    for parent in range(len(native)):
        s = slice(p.offsets[parent], p.offsets[parent + 1])
        baseline = depth[s]
        common = dict(
            parent_area_m2=p.parent_area_km2[parent] * 1e6,
            parent_budget_mm_m2=native[parent] * p.parent_area_km2[parent] * 1e6,
        )
        unchanged = monthly_component_shares(baseline, p.area_km2[s] * 1e6, driver=None, **common)
        np.testing.assert_array_equal(unchanged.depth_mm, baseline)
        driver = ComponentDriver(
            baseline * 0.6, baseline * np.linspace(0.1, 2, len(baseline)), baseline * 0.4
        )
        changed = monthly_component_shares(baseline, p.area_km2[s] * 1e6, driver=driver, **common)
        np.testing.assert_allclose(
            np.dot(p.area_km2[s] * 1e6, changed.depth_mm), common["parent_budget_mm_m2"], rtol=7e-15
        )


def test_archive_roundtrip_and_query_batches_keep_component_budgets(tmp_path) -> None:
    lat, lon = grid(4, 8)
    p = gaussian_parent_partition(lat, lon, radius_km=6371.0, spacing_km=500.0)
    rng = np.random.default_rng(19)
    native = rng.uniform(0, 100, (2, 12, len(p.parent_area_km2)))
    native[:, :, 3] = 0
    depths = p.conservative_depths(native, prior_mm=rng.uniform(0, 100, (2, 12, len(p.area_km2))))
    field = NativePrecipitationField(p, native, depths, {"test": True})
    path = tmp_path / "rain.npz"
    field.save(path)
    restored = NativePrecipitationField.load(path)
    np.testing.assert_array_equal(restored.component_monthly_mm, depths)
    np.testing.assert_array_equal(restored.partition.area_km2, p.area_km2)
    expected = depths.sum(axis=0)
    np.testing.assert_array_equal(restored.sample_monthly(p.latitude, p.longitude), expected)
    split = len(p.latitude) // 2
    batches = [
        restored.sample_monthly(p.latitude[s], p.longitude[s])
        for s in (slice(0, split), slice(split, None))
    ]
    np.testing.assert_array_equal(np.concatenate(batches, axis=-1), expected)
    broken = depths.copy()
    broken[0, 0, 0] += 1
    with pytest.raises(ValueError, match="conserve"):
        NativePrecipitationField(p, native, broken, {})
