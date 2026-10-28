"""Independent integral, boundary, topology and query checks for along-axis transfer."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.orogen_transfer import ConservativeArcField
from dreamulator.map.paleo_sutures import lonlat_to_xyz


def arcs(path: list[list[float]]) -> np.ndarray:
    nodes = lonlat_to_xyz(np.array(path))
    return np.stack([nodes[:-1], nodes[1:]], axis=1)


@pytest.mark.parametrize("smoothing", [0.0, 300.0])
def test_nonuniform_axis_preserves_its_independently_integrated_budget(smoothing: float) -> None:
    segments = arcs([[0, 0], [0.1, 0], [1, 0], [4, 0], [5, 0]])
    values = np.array([0.0, 5, 80, 10])
    field = ConservativeArcField(segments, values, 6371, smoothing)
    angle = np.radians(np.array([0.1, 0.9, 3.0, 1.0]))
    expected = float(angle @ values * 6371)
    # Independent Gaussian quadrature queries the source rather than its stored integral.
    q, w = np.polynomial.legendre.leggauss(20)
    fraction, w = (q + 1) / 2, w / 2
    lon = np.array([0, 0.1, 1, 4])[:, None] + np.degrees(angle)[:, None] * fraction
    xyz = lonlat_to_xyz(np.column_stack([lon.ravel(), np.zeros(lon.size)]))
    integrated = float(angle @ (field(xyz).reshape(4, -1) @ w) * 6371)
    assert integrated == pytest.approx(expected, rel=2e-12)
    assert field.integral_after == pytest.approx(expected, rel=2e-12)
    assert field.node_values.min() >= 0
    assert field.node_values.max() <= values.max()


def test_constant_and_disconnected_sources_have_zero_exchange() -> None:
    first = arcs([[0, 0], [1, 0], [2, 0]])
    second = arcs([[0, 0.2], [1, 0.2], [2, 0.2]])
    field = ConservativeArcField(
        np.concatenate([first, second]), np.array([7, 7, 60, 60]), 6371, 300
    )
    np.testing.assert_allclose(field.endpoints[:2], 7, atol=1e-12)
    np.testing.assert_allclose(field.endpoints[2:], 60, atol=1e-12)


def test_branches_share_one_vertex_and_preserve_the_total_budget() -> None:
    nodes = lonlat_to_xyz(np.array([[0, 0], [1, 0], [1, 1], [2, 0]]))
    field = ConservativeArcField(
        nodes[np.array([[0, 1], [1, 2], [1, 3]])], np.array([0, 30, 60]), 6371, 300
    )
    np.testing.assert_allclose(
        field.endpoints[:, [1, 0, 0]][[0, 1, 2], [0, 1, 2]], field(nodes[1]), atol=1e-10
    )
    assert field.integral_after == pytest.approx(field.integral_before, rel=1e-12)


def test_arc_order_orientation_rotation_and_query_batches_leave_values_unchanged() -> None:
    segments = arcs([[170, 0], [179, 1], [-178, 2], [-170, 1]])
    values = np.array([2.0, 70, 10])
    field = ConservativeArcField(segments, values, 6371, 300)
    reversed_field = ConservativeArcField(segments[::-1, ::-1], values[::-1], 6371, 300)
    rotated = ConservativeArcField(segments[..., [1, 2, 0]], values, 6371, 300)
    q = lonlat_to_xyz(np.array([[175, 3], [179, -3], [-173, 2], [-171, 1]]))
    expected = field(q)
    np.testing.assert_allclose(reversed_field(q), expected, rtol=0, atol=1e-10)
    np.testing.assert_allclose(rotated(q[:, [1, 2, 0]]), expected, rtol=0, atol=1e-10)
    np.testing.assert_allclose(
        np.concatenate([field(p) for p in np.array_split(q, 2)]), expected, atol=1e-10
    )
    segments[:] = 0
    values[:] = 0
    np.testing.assert_array_equal(field(q), expected)


def test_continuous_extension_has_no_jump_at_a_nearest_arc_switch() -> None:
    field = ConservativeArcField(arcs([[0, 0], [1, 0], [1, 1]]), np.array([5.0, 90]), 6371, 300)
    centre = np.array([0.7, 0.3])
    pairs = [
        lonlat_to_xyz(np.array([centre + [-e, e], centre + [e, -e]])) for e in [1e-3, 1e-5, 1e-7]
    ]
    differences = [float(np.ptp(field(pair))) for pair in pairs]
    assert differences[2] < differences[1] < differences[0]
    assert differences[2] < 1e-4
