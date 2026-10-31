"""Spherical source continuity and independent exhaustive coastline distances."""

from __future__ import annotations

import numpy as np

from dreamulator.map.paleo_sutures import lonlat_to_xyz
from dreamulator.map.spherical_terrain import SphericalCoastGeometry, SphericalPointTerrainField
from dreamulator.map.terrain_source import SphericalSegmentGeometry


def globe_points(n: int = 300) -> np.ndarray:
    index = np.arange(n)
    z = 1 - 2 * (index + 0.5) / n
    phi = index * np.pi * (3 - np.sqrt(5))
    return np.column_stack([np.sqrt(1 - z * z) * np.cos(phi), np.sqrt(1 - z * z) * np.sin(phi), z])


def test_spherical_interpolation_preserves_vertices_and_convex_combinations() -> None:
    xyz = globe_points()
    data = np.column_stack([xyz[:, 0] * 1000, xyz[:, 2] * 2000])
    field = SphericalPointTerrainField(xyz, data)
    np.testing.assert_allclose(field(xyz), data, atol=1e-8)
    ids = field.faces[:30]
    w = np.array([0.2, 0.3, 0.5])
    q = np.einsum("i,nij->nj", w, xyz[ids])
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    expected = np.einsum("i,nij->nj", w, data[ids])
    np.testing.assert_allclose(field(q), expected, atol=1e-8)
    xyz[:] = 0
    data[:] = 0
    np.testing.assert_allclose(field(q), expected, atol=1e-8)


def test_source_contour_is_on_the_same_reconstructed_surface() -> None:
    xyz = globe_points()
    field = SphericalPointTerrainField(xyz, xyz[:, 0] * 3000)
    segments = field.contour_segments()
    assert len(segments) > 10
    q = segments.mean(axis=1)
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    np.testing.assert_allclose(field(q), 0, atol=1e-8)
    coast = SphericalCoastGeometry(segments, 6371)
    np.testing.assert_allclose(coast.distance_km(q), 0, atol=1e-7)


def test_basis_reconstructs_inactive_bound_responses_continuously() -> None:
    xyz = globe_points()
    field = SphericalPointTerrainField(xyz, xyz[:, 0] * 3000)
    face = field.faces[10]
    proportions = np.array([[0.2, 0.3, 0.5], [0.0, 0.0, 1.0]])
    q = proportions @ field.points[face]
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    vertices, weights = field.basis(q)
    np.testing.assert_array_equal(np.einsum("ni,ni->n", weights, field.values[vertices]), field(q))
    cap = np.full(len(xyz), np.inf)
    cap[face[0]] = 100.0
    response = np.sum(weights * np.maximum(1000.0 - cap[vertices], 0), axis=1)
    np.testing.assert_allclose(response, [180.0, 0.0], atol=1e-7)
    assert (weights >= 0).all()
    np.testing.assert_allclose(weights.sum(axis=1), 1.0, atol=1e-15)


def test_indexed_coast_distances_match_exhaustive_arcs_across_the_dateline() -> None:
    nodes = lonlat_to_xyz(np.array([[165, 70], [175, 71], [-179, 69], [-168, 72], [-160, 65]]))
    arcs = np.stack([nodes[:-1], nodes[1:]], axis=1)
    coast = SphericalCoastGeometry(arcs, 6371)
    q = globe_points(400)
    expected = SphericalSegmentGeometry(arcs).project(q).distance_rad * 6371
    np.testing.assert_allclose(coast.distance_km(q), expected, atol=1e-7)
    limit = 5000.0
    actual = coast.distance_km(q, maximum_km=limit)
    np.testing.assert_allclose(actual[expected <= limit], expected[expected <= limit], atol=1e-7)
    assert np.isinf(actual[expected > limit]).all()


def test_local_weights_preserve_fine_controls_and_spherical_face_interiors() -> None:
    controls = lonlat_to_xyz(np.array([[10.0, 20.0], [10.00002, 20.0], [10.0, 20.0001]]))
    xyz = np.r_[globe_points(), controls]
    values = np.r_[np.zeros(300), [-130.0, 0.0, 100.0]]
    field = SphericalPointTerrainField(xyz, values, stable_weights=True)
    np.testing.assert_allclose(field(xyz), values, rtol=0, atol=1e-7)
    faces = field.faces[np.all(field.faces >= 300, axis=1)]
    assert len(faces) == 1
    weights = np.array([0.2, 0.3, 0.5])
    q = np.einsum("i,nij->nj", weights, xyz[faces])
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    expected = np.einsum("i,ni->n", weights, values[faces])
    np.testing.assert_allclose(field(q), expected, rtol=0, atol=1e-6)


def test_local_face_walk_resolves_dense_curve_triangle_interiors() -> None:
    controls = lonlat_to_xyz(np.column_stack([np.linspace(-5, 5, 1201), np.zeros(1201)]))
    xyz = np.r_[globe_points(), controls]
    values = xyz[:, 2] * 1200 + xyz[:, 1] * 340
    field = SphericalPointTerrainField(xyz, values, stable_weights=True)
    faces = field.faces[np.any(field.faces >= 300, axis=1)]
    weights = np.array([0.15, 0.35, 0.5])
    q = np.einsum("i,nij->nj", weights, xyz[faces])
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    expected = np.einsum("i,ni->n", weights, values[faces])
    np.testing.assert_allclose(field(q), expected, rtol=0, atol=1e-7)
    np.testing.assert_allclose(
        field(q), np.concatenate([field(p) for p in np.array_split(q, 5)]), rtol=0, atol=1e-10
    )


def test_c1_field_reproduces_vertices_and_joins_faces_smoothly() -> None:
    from dreamulator.map.spherical_terrain import SphericalC1Field

    xyz = globe_points(2000)
    smooth = np.sin(3 * xyz[:, 0]) * np.cos(2 * xyz[:, 1]) + xyz[:, 2] ** 2
    field = SphericalC1Field(xyz, np.column_stack([smooth * 1000, xyz[:, 0]]))
    np.testing.assert_allclose(field(xyz), np.column_stack([smooth * 1000, xyz[:, 0]]), atol=1e-6)
    # Off-vertex accuracy beats the linear reconstruction on the same faces.
    rng = np.random.default_rng(4)
    q = rng.normal(size=(4000, 3))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    truth = (np.sin(3 * q[:, 0]) * np.cos(2 * q[:, 1]) + q[:, 2] ** 2) * 1000
    c1 = np.abs(field(q)[:, 0] - truth).max()
    linear = np.abs(field.linear(q)[:, 0] - truth).max()
    assert c1 < 0.35 * linear
    # Directional derivative across a shared edge agrees from both faces.
    face = field.linear.faces[50]
    a, b = field.linear.points[face[0]], field.linear.points[face[1]]
    mid = (a + b) / np.linalg.norm(a + b)
    tangent = np.cross(mid, b - a)
    tangent /= np.linalg.norm(tangent)
    h = 1e-5
    sides = []
    for sign in (1, -1):
        near = mid + sign * h * tangent
        far = mid + sign * 2 * h * tangent
        near, far = (p / np.linalg.norm(p) for p in (near, far))
        sides.append((field(far[None])[0, 0] - field(near[None])[0, 0]) / h * sign)
    jump_c1 = abs(sides[0] - sides[1])
    lin = []
    for sign in (1, -1):
        near = mid + sign * h * tangent
        far = mid + sign * 2 * h * tangent
        near, far = (p / np.linalg.norm(p) for p in (near, far))
        lin.append((field.linear(far[None])[0, 0] - field.linear(near[None])[0, 0]) / h * sign)
    assert jump_c1 < 1e-3 * max(abs(lin[0] - lin[1]), 1.0) + 1e-2
