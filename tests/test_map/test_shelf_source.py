"""Independent shelf geometry, sea-level displacement and background contacts."""

from __future__ import annotations

import numpy as np

from dreamulator.map.shelf_source import ShelfEnvelopeDifferenceSource


def source(*, protected: bool = False) -> ShelfEnvelopeDifferenceSource:
    index = np.arange(2000)
    y = 1 - 2 * (index + 0.5) / len(index)
    phi = index * np.pi * (3 - np.sqrt(5))
    xyz = np.column_stack(
        [
            np.sqrt(1 - y * y) * np.cos(phi),
            y,
            np.sqrt(1 - y * y) * np.sin(phi),
        ]
    )
    background = xyz[:, 0] * 60000
    return ShelfEnvelopeDifferenceSource(
        xyz,
        background,
        background,
        np.full(len(index), 80000),
        np.zeros(len(index)),
        radius_km=6371,
        shelf_break_depth_m=130,
        slope_m_per_km=70,
        active_flexure_mask=np.full(len(index), protected),
    )


def test_shelf_is_anchored_to_true_coast_and_retains_shallower_background() -> None:
    field = source()
    distance = np.array([-1.0, 0.0, 20.0, 40.0, 80.0, 120.0])
    lon = 90 + np.degrees(distance / 6371)
    q = field.query(np.zeros(len(lon)), lon)
    np.testing.assert_allclose(q["distance_km"][2:], distance[2:], atol=1e-7)
    np.testing.assert_allclose(q["replacement_m"][1:5], [0, -32.5, -65, -130], atol=1e-7)
    assert q["replacement_m"][0] == q["before_m"][0]
    assert q["replacement_m"][-1] == q["before_m"][-1]
    assert np.all(q["replacement_m"] >= q["before_m"])


def test_final_sea_level_moves_a_continuous_shore_by_depth_over_slope() -> None:
    field = source()
    level_shift = 18.0
    expected_distance = level_shift * 80 / 130
    distance = expected_distance + np.array([-0.001, 0.0, 0.001])
    q = field.query(np.zeros(len(distance)), 90 + np.degrees(distance / 6371))
    surface = q["replacement_m"] + level_shift
    assert surface[0] > 0 and surface[-1] < 0
    np.testing.assert_allclose(surface[1], 0, atol=1e-7)
    np.testing.assert_allclose(np.diff(surface), -np.diff(distance) * 130 / 80, atol=1e-7)


def test_shore_and_background_contacts_converge_and_queries_are_batch_independent() -> None:
    field = source()
    differences = []
    for step in (0.01, 0.001):
        q = field.query(np.array([0.0, 0.0]), 90 + np.degrees(np.array([-step, step]) / 6371))
        differences.append(float(np.ptp(q["replacement_m"])))
    assert differences[1] < differences[0] / 9
    lon = np.linspace(89, 92, 41)
    together = field.query(np.zeros(len(lon)), lon)["delta_m"]
    split = np.concatenate(
        [field.query(np.zeros(len(v)), v)["delta_m"] for v in np.array_split(lon, 5)]
    )
    np.testing.assert_array_equal(together, split)
    incoming = source(protected=True).query(np.zeros(len(lon)), lon)
    assert incoming["protected_mask"].all()
    np.testing.assert_array_equal(incoming["delta_m"], np.zeros(len(lon)))


def test_source_weights_compose_reference_and_shelf_on_the_same_triangles() -> None:
    reference = source()
    protected = reference.field.points[:, 1] > 0
    composed = ShelfEnvelopeDifferenceSource(
        reference.field.points,
        reference.field.values[:, 0],
        reference.field.values[:, 1],
        reference.field.values[:, 2],
        reference.field.values[:, 3],
        radius_km=6371,
        shelf_break_depth_m=130,
        slope_m_per_km=70,
        active_flexure_mask=protected,
        protection_policy="source-weight",
    )
    lat = np.linspace(-2, 2, 101)
    lon = np.full(len(lat), 90 + np.degrees(40 / 6371))
    actual = composed.query(lat, lon)
    envelope = reference.query(lat, lon)
    fraction = actual["shelf_fraction"]
    assert ((fraction > 0) & (fraction < 1)).any()
    assert np.all((fraction >= 0) & (fraction <= 1))
    np.testing.assert_allclose(actual["delta_m"], fraction * envelope["delta_m"], rtol=0, atol=1e-8)
    split = np.concatenate(
        [
            composed.query(lat[ids], lon[ids])["delta_m"]
            for ids in np.array_split(np.arange(len(lat)), 5)
        ]
    )
    np.testing.assert_array_equal(actual["delta_m"], split)
    xyz = composed.field.points
    nodes = composed.query(
        np.degrees(np.arcsin(xyz[:, 1])), np.degrees(np.arctan2(xyz[:, 2], xyz[:, 0]))
    )
    np.testing.assert_allclose(nodes["delta_m"][protected], 0, atol=1e-7, rtol=0)
    assert "numerical fraction" in composed.metadata["protection_weight_basis"]
    assert not composed.field.values.flags.writeable


def test_source_weight_boundary_response_converges_without_a_nearest_cell_switch() -> None:
    original = source()
    composed = ShelfEnvelopeDifferenceSource(
        original.field.points,
        *original.field.values.T,
        radius_km=6371,
        shelf_break_depth_m=130,
        slope_m_per_km=70,
        active_flexure_mask=original.field.points[:, 1] > 0,
        protection_policy="source-weight",
    )
    jumps = []
    for distance_km in (0.1, 0.01, 0.001):
        lat = np.degrees(np.array([-distance_km, distance_km]) / 6371)
        lon = np.full(2, 90 + np.degrees(40 / 6371))
        values = composed.query(lat, lon)["replacement_m"]
        jumps.append(float(np.ptp(values)))
    assert all(b < a * 0.12 for a, b in zip(jumps[:-1], jumps[1:], strict=True))
