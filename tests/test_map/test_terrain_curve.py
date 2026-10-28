"""Connected curve evidence, indexed projection and prescribed slope profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.paleo_sutures import lonlat_to_xyz
from dreamulator.map.spherical_terrain import SphericalCoastGeometry
from dreamulator.map.terrain_curve import (
    CurveEvidence,
    SphericalCurveBoundary,
    SphericalTerrainCurve,
    contour_source_curves,
    load_terrain_curves,
    rational_profile_fraction,
    save_terrain_curves,
)
from dreamulator.map.terrain_source import SphericalSegmentGeometry

if TYPE_CHECKING:
    from pathlib import Path


def evidence(epoch_myr: float = 0.0) -> CurveEvidence:
    return CurveEvidence("observation", "declared analytic test", 0.0, epoch_myr)


def test_curve_projection_matches_exhaustive_finite_arcs_and_query_batches() -> None:
    nodes = lonlat_to_xyz(np.array([[165, 70], [175, 71], [-179, 69], [-168, 72], [-160, 65]]))
    arcs = np.stack([nodes[:-1], nodes[1:]], axis=1)
    geom = SphericalCoastGeometry(arcs, 6371)
    rng = np.random.default_rng(2)
    q = rng.normal(size=(501, 3))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    oracle = SphericalSegmentGeometry(arcs).project(q)
    actual = geom.project(q)
    np.testing.assert_allclose(actual.distance_rad, oracle.distance_rad, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(actual.segment_index, oracle.segment_index)
    np.testing.assert_allclose(actual.fraction, oracle.fraction, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(actual.side, oracle.side)
    np.testing.assert_allclose(actual.distance_rad * 6371, geom.distance_km(q), atol=1e-8)
    batches = [geom.project(part) for part in np.array_split(q, 7)]
    for key in ("segment_index", "fraction", "distance_rad", "side"):
        np.testing.assert_array_equal(
            getattr(actual, key), np.concatenate([getattr(b, key) for b in batches])
        )
    limited = geom.project(q, maximum_km=5000)
    absent = actual.distance_rad * 6371 > 5000
    assert (limited.segment_index[absent] == -1).all()
    assert np.isinf(limited.distance_rad[absent]).all()
    assert np.isnan(limited.fraction[absent]).all()


def test_ordered_curve_samples_preserve_side_values_and_source_availability() -> None:
    nodes = lonlat_to_xyz(np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]))
    height = np.array([0.0, 10.0, 20.0])
    left = np.array([2.0, 4.0, 6.0])
    right = np.array([3.0, 5.0, 7.0])
    curve = SphericalTerrainCurve(
        "front",
        "mountain_front",
        nodes,
        radius_km=6371,
        datum="test",
        geometry_evidence=evidence(),
        height_m=height,
        height_evidence=evidence(),
        slope_left_m_per_km=left,
        slope_left_evidence=evidence(),
        slope_right_m_per_km=right,
        slope_right_evidence=evidence(),
    )
    q = lonlat_to_xyz(np.array([[0.5, 1.0], [0.5, -1.0]]))
    actual = curve.query(q)
    np.testing.assert_allclose(actual["height_m"], 5.0, atol=1e-8)
    np.testing.assert_allclose(actual["slope_left_m_per_km"], 3.0, atol=1e-8)
    np.testing.assert_allclose(actual["slope_right_m_per_km"], 4.0, atol=1e-8)
    np.testing.assert_array_equal(actual["side"], [1.0, -1.0])
    nodes[:] = 0
    height[:] = -100
    left[:] = -100
    np.testing.assert_array_equal(curve.query(q)["height_m"], actual["height_m"])
    absent = curve.query(q, maximum_km=1)
    assert np.isnan(absent["height_m"]).all()
    geometry_only = SphericalTerrainCurve(
        "crust",
        "crust_boundary",
        curve.xyz,
        radius_km=6371,
        datum="geometry only",
        geometry_evidence=evidence(),
    )
    assert np.isnan(geometry_only.query(q)["height_m"]).all()
    assert np.isnan(geometry_only.query(q)["slope_left_m_per_km"]).all()


@pytest.mark.parametrize(
    "a,b", [(0.0, 0.0), (0.1, 10.0), (1.0, 1.0), (15.0, 0.3), (1000.0, 2000.0)]
)
def test_rational_profile_is_bounded_monotone_and_replays_endpoint_slopes(
    a: float, b: float
) -> None:
    t = np.linspace(0, 1, 10001)
    v = rational_profile_fraction(t, np.array(a), np.array(b))
    assert v[0] == 0 and v[-1] == 1
    assert (np.diff(v) >= -1e-14).all()
    step = 1e-9 / max(1, a, b)
    near = rational_profile_fraction(np.array([step, 1 - step]), np.array(a), np.array(b))
    np.testing.assert_allclose([near[0] / step, (1 - near[1]) / step], [a, b], rtol=1e-2, atol=1e-3)
    if a == b == 1:
        np.testing.assert_array_equal(v, t)


def test_curve_archive_roundtrip_keeps_connected_nodes_and_missing_values(tmp_path: Path) -> None:
    nodes = lonlat_to_xyz(np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]))
    curve = SphericalTerrainCurve(
        "a",
        "front",
        nodes,
        radius_km=6371,
        datum="sea",
        geometry_evidence=evidence(),
        height_m=np.array([0.0, np.nan, 20.0]),
        height_evidence=evidence(),
    )
    path = tmp_path / "curves.npz"
    save_terrain_curves(path, [curve], reference_id="frozen-1")
    restored, meta = load_terrain_curves(path, expected_reference_id="frozen-1")
    assert meta["reference_id"] == "frozen-1" and restored[0].sha256 == curve.sha256
    np.testing.assert_array_equal(restored[0].xyz, nodes)
    np.testing.assert_array_equal(restored[0].height_m, curve.height_m)
    with pytest.raises(ValueError, match="different frozen"):
        load_terrain_curves(path, expected_reference_id="other")
    with path.open("ab") as stream:
        stream.write(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        load_terrain_curves(path)


def test_connected_boundary_selects_declared_components_without_filling_missing_height() -> None:
    curves = []
    for i in range(2):
        nodes = lonlat_to_xyz(np.array([[10 * i, 0.0], [10 * i + 1, 0.0]]))
        curves.append(
            SphericalTerrainCurve(
                str(i),
                "front",
                nodes,
                radius_km=6371,
                datum="sea",
                geometry_evidence=evidence(),
                height_m=np.full(2, 20.0) if i == 0 else None,
                height_evidence=evidence() if i == 0 else None,
            )
        )
    boundary = SphericalCurveBoundary(curves)
    q = lonlat_to_xyz(np.array([[0.5, 1.0], [10.5, 1.0]]))
    values = boundary.query(q)
    assert values["height_m"][0] == 20.0 and np.isnan(values["height_m"][1])
    np.testing.assert_array_equal(values["side"], [1.0, 1.0])
    np.testing.assert_allclose(values["distance_km"], 111.19492664455873, atol=1e-6)


def test_source_contour_export_preserves_all_connected_edges_and_geographic_orientation() -> None:
    from test_spherical_terrain import globe_points

    from dreamulator.map.spherical_terrain import SphericalPointTerrainField

    xyz = globe_points()
    values = xyz[:, 1] * 1500
    field = SphericalPointTerrainField(xyz, values)
    curves = contour_source_curves(field, 0.0, 6371.0, "frozen-test", epoch_myr=0.0)
    assert curves and all(curve.closed for curve in curves)
    assert sum(len(curve.xyz) - 1 for curve in curves) == len(field.contour_segments())
    for curve in curves:
        np.testing.assert_array_equal(curve.height_m, np.zeros(len(curve.xyz)))
        mid = curve.xyz[:2].sum(0)
        mid /= np.linalg.norm(mid)
        left = -np.cross(curve.xyz[0], curve.xyz[1])
        left /= np.linalg.norm(left)
        q = np.cos(1e-6) * mid + np.sin(1e-6) * left
        assert field(q) > 0
        assert curve.slope_left_m_per_km is None
