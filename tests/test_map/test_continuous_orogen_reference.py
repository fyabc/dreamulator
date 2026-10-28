"""Common reconstruction for mountain contributions and continuous backgrounds."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.orogen_source import (
    CollisionProfileField,
    ContactCollisionProfileField,
    ContinuousOrogenReplacement,
    FrozenOrogenReplacement,
)
from dreamulator.map.paleo_sutures import lonlat_to_xyz


def points(n: int = 500) -> np.ndarray:
    index = np.arange(n)
    north = 1 - 2 * (index + 0.5) / n
    angle = index * np.pi * (3 - np.sqrt(5))
    radius = np.sqrt(1 - north**2)
    return np.column_stack([radius * np.cos(angle), north, radius * np.sin(angle)])


class ConstantProfile:
    def __init__(self, height: float) -> None:
        self.height = height

    def __call__(self, xyz: np.ndarray) -> np.ndarray:
        return np.full(xyz.shape[:-1], self.height)

    @property
    def metadata(self) -> dict:
        return {"constant_m": self.height}


def source() -> FrozenOrogenReplacement:
    xyz = points()
    return FrozenOrogenReplacement(
        ConstantProfile(2500),
        xyz,
        np.ones(len(xyz), dtype=bool),
        1000 * (1 + xyz[:, 0]),
        400 * (1 + xyz[:, 1]),
        500 * (1 + xyz[:, 2]),
        reference_id="common-reference",
    )


def latlon(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.degrees(np.arcsin(xyz[:, 1])), np.degrees(np.arctan2(xyz[:, 2], xyz[:, 0]))


def test_native_vertices_replay_the_original_transfer_without_changing_its_policy() -> None:
    original = source()
    continuous = original.continuous_reconstruction()
    lat, lon = latlon(original.xyz)
    np.testing.assert_allclose(
        continuous.evaluate(lat, lon)[0], original.evaluate(lat, lon)[0], rtol=0, atol=1e-8
    )
    assert isinstance(continuous, ContinuousOrogenReplacement)
    assert original.metadata["kind"] == "frozen-orogen-replacement-v1"
    assert continuous.metadata["kind"] == "continuous-orogen-replacement-v1"
    assert continuous.metadata["reference_id"] == original.reference_id
    assert continuous.metadata["reconstruction_sha256"] == continuous.reference_field.sha256


def test_continuous_reference_removes_nearest_cell_jumps() -> None:
    original = source()
    continuous = original.continuous_reconstruction()
    edges = continuous.reference_field.faces[:, :2]
    midpoint = original.xyz[edges].sum(axis=1)
    midpoint /= np.linalg.norm(midpoint, axis=1, keepdims=True)
    nearest = original.tree.query(midpoint, k=2)[1]
    candidates = (np.sort(nearest, axis=1) == np.sort(edges, axis=1)).all(axis=1)
    jumps = abs(original.selected_m[edges[:, 0]] - original.selected_m[edges[:, 1]])
    i = int(np.argmax(np.where(candidates, jumps, 0)))
    assert candidates[i] and jumps[i] > 10
    tangent = original.xyz[edges[i, 1]] - original.xyz[edges[i, 0]]
    tangent -= np.dot(tangent, midpoint[i]) * midpoint[i]
    tangent /= np.linalg.norm(tangent)
    queries = midpoint[i] + np.array([-1e-8, 1e-8])[:, None] * tangent
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    lat, lon = latlon(queries)
    old, new = original.evaluate(lat, lon)[0], continuous.evaluate(lat, lon)[0]
    assert abs(old[1] - old[0]) > 10
    assert abs(new[1] - new[0]) < 1e-3


def test_dominant_unselected_relief_and_fractional_crust_are_applied_together() -> None:
    xyz = points()
    crust = xyz[:, 1] > 0
    original = FrozenOrogenReplacement(
        ConstantProfile(1000),
        xyz,
        crust,
        np.zeros(len(xyz)),
        np.zeros(len(xyz)),
        np.zeros(len(xyz)),
        reference_id="coverage",
    )
    continuous = original.continuous_reconstruction()
    lat, lon = np.zeros(201), np.linspace(-180, 180, 201)
    query = lonlat_to_xyz(np.column_stack([lon, lat]))
    coverage = continuous.reference_field(query)[:, 3]
    assert np.any((coverage > 0.1) & (coverage < 0.9))
    np.testing.assert_allclose(continuous.evaluate(lat, lon)[0], 1000 * coverage, atol=1e-10)
    dominant = FrozenOrogenReplacement(
        ConstantProfile(1000),
        xyz,
        crust,
        np.zeros(len(xyz)),
        np.full(len(xyz), 2000),
        np.zeros(len(xyz)),
        reference_id="dominant",
    ).continuous_reconstruction()
    np.testing.assert_array_equal(dominant.evaluate(lat, lon)[0], 0)


def test_same_reconstructed_selected_profile_has_numerical_zero_response() -> None:
    original = source()
    continuous = original.continuous_reconstruction()

    class ReferenceProfile(ConstantProfile):
        def __call__(self, xyz: np.ndarray) -> np.ndarray:
            return continuous.reference_field(xyz)[:, 0]

    continuous.profile_field = ReferenceProfile(0)
    lat, lon = np.linspace(-80, 80, 1001), np.linspace(-180, 180, 1001)
    np.testing.assert_allclose(continuous.evaluate(lat, lon)[0], 0, rtol=0, atol=1e-10)


def test_support_encloses_old_continuous_contributions_and_new_known_profiles() -> None:
    xyz = points()
    axis = lonlat_to_xyz(np.array([[0, -2], [0, 2]]))
    profile = CollisionProfileField(
        axis[None, :, :], np.array([30.0]), 6371, 9.80665, 650, 300, segment_id="axis"
    )
    original = FrozenOrogenReplacement(
        profile,
        xyz,
        np.ones(len(xyz), dtype=bool),
        np.where(xyz[:, 0] < -0.98, 1000, 0),
        np.zeros(len(xyz)),
        np.zeros(len(xyz)),
        reference_id="sparse-contribution",
    )
    continuous = original.continuous_reconstruction()
    rng = np.random.default_rng(45)
    lat = np.degrees(np.arcsin(rng.uniform(-1, 1, 10000)))
    lon = rng.uniform(-180, 180, 10000)
    support = continuous.footprint_support(lat, lon, 10, 6371)
    assert support.any() and not support.all()
    np.testing.assert_array_equal(continuous.evaluate(lat[~support], lon[~support])[0], 0)


def competing_arcs(
    contact: bool, retained: float = 10000
) -> CollisionProfileField | ContactCollisionProfileField:
    axis = lonlat_to_xyz(np.array([[0, -2], [0, 2], [2, -2], [2, 0]])).reshape(2, 2, 3)
    if contact:
        return ContactCollisionProfileField(
            axis,
            axis,
            np.full((2, 2), retained),
            retained,
            6371,
            9.80665,
            650,
            300,
            segment_id="competing-arcs",
        )
    return CollisionProfileField(
        axis, np.full(2, retained), 6371, 9.80665, 650, 300, segment_id="competing-arcs"
    )


@pytest.mark.parametrize("contact", [False, True])
def test_arc_envelope_removes_nearest_arc_switch_and_preserves_parameters(contact: bool) -> None:
    source = competing_arcs(contact)
    endcaps = source.with_continuous_endcaps()
    candidate = source.with_continuous_arc_envelope()
    path = lonlat_to_xyz(np.column_stack([np.linspace(1.2, 1.3, 2001), np.ones(2001)]))
    projection = source.geometry.project(path)
    assert set(projection.segment_index) == {0, 1}
    assert np.max(abs(np.diff(endcaps(path)))) > 100
    assert np.max(abs(np.diff(candidate(path)))) < 1
    assert "arc_combination" not in source.metadata
    assert candidate.mean_retained_km == source.mean_retained_km
    if isinstance(source, CollisionProfileField):
        assert isinstance(candidate, CollisionProfileField)
        assert candidate.axis_field is source.axis_field
        assert candidate.axis_field.integral_after == source.axis_field.integral_after
    else:
        assert isinstance(candidate, ContactCollisionProfileField)
        assert candidate.parameter_sha256 == source.parameter_sha256


@pytest.mark.parametrize("contact", [False, True])
@pytest.mark.parametrize("retained", [0, 10, 10000])
def test_single_arc_envelope_preserves_both_flanks_and_open_end_continuity(
    contact: bool, retained: float
) -> None:
    axis = lonlat_to_xyz(np.array([[0, -1], [0, 1]]))[None, :, :]
    if contact:
        source = ContactCollisionProfileField(
            axis,
            axis,
            np.full((1, 2), retained),
            retained,
            6371,
            9.80665,
            650,
            300,
            segment_id="single-arc",
        )
    else:
        source = CollisionProfileField(
            axis, np.array([retained]), 6371, 9.80665, 650, 300, segment_id="single-arc"
        )
    candidate = source.with_continuous_arc_envelope()
    inside = lonlat_to_xyz(np.column_stack([np.linspace(-5, 5, 1001), np.zeros(1001)]))
    np.testing.assert_allclose(candidate(inside), source(inside), rtol=0, atol=1e-8)
    path = lonlat_to_xyz(np.array([[-1e-7, 2], [1e-7, 2]]))
    assert abs(np.diff(candidate(path))[0]) < 1e-3


@pytest.mark.parametrize("contact", [False, True])
def test_arc_envelope_is_rotation_shape_and_batch_invariant(contact: bool) -> None:
    source = competing_arcs(contact)
    candidate = source.with_continuous_arc_envelope()
    query = lonlat_to_xyz(np.array([[1.25, 1], [0, 3], [2, 3], [80, -30]]))
    expected = candidate(query)
    np.testing.assert_allclose(candidate(query.reshape(2, 2, 3)), expected.reshape(2, 2), atol=1e-8)
    np.testing.assert_allclose(
        np.concatenate([candidate(query[:2]), candidate(query[2:])]), expected, atol=1e-8
    )
    rotation, _ = np.linalg.qr(np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 1.0], [3.0, 1.0, 5.0]]))
    axis = source.geometry.segments @ rotation
    if contact:
        rotated = ContactCollisionProfileField(
            axis,
            axis,
            np.full((2, 2), 10000.0),
            10000,
            6371,
            9.80665,
            650,
            300,
            segment_id="rotated",
        )
    else:
        rotated = CollisionProfileField(
            axis, np.full(2, 10000.0), 6371, 9.80665, 650, 300, segment_id="rotated"
        )
    np.testing.assert_allclose(
        rotated.with_continuous_arc_envelope()(query @ rotation), expected, rtol=0, atol=1e-8
    )
    assert expected[-1] == 0
    assert expected.min() >= 0 and expected.max() <= source.cap_km * 1000
