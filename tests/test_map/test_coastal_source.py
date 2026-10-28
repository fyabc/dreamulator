"""Coastal source boundaries, fixed physical width and reference-stage identity."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.coastal_source import (
    CoastalPlainDifferenceSource,
    ShelfCoastalDifferenceSource,
    coastal_source_from_native,
)
from dreamulator.map.shelf_source import ShelfEnvelopeDifferenceSource


def source(width: float) -> CoastalPlainDifferenceSource:
    index = np.arange(500)
    north = 1 - 2 * (index + 0.5) / len(index)
    phi = index * np.pi * (3 - np.sqrt(5))
    xyz = np.column_stack(
        [np.sqrt(1 - north * north) * np.cos(phi), north, np.sqrt(1 - north * north) * np.sin(phi)]
    )
    z = xyz[:, 0] * 1000
    return CoastalPlainDifferenceSource(
        xyz,
        z,
        z,
        np.full(len(z), 30.0),
        width_km=width,
        radius_km=6371,
        max_plain_elevation_m=500,
        mountain_fraction=0.15,
    )


def test_disabled_stage_replays_reference_and_preserves_the_ocean() -> None:
    field = source(0)
    delta, land = field.evaluate(np.array([0.0, 10.0, -20.0]), np.array([0.0, 89.0, 100.0]))
    np.testing.assert_array_equal(delta, 0)
    np.testing.assert_array_equal(land, 0)
    active = source(100)
    result = active.query(np.array([0.0]), np.array([100.0]))
    np.testing.assert_array_equal(result["replacement_m"], result["before_m"])


def test_sequential_disabled_coastal_stage_carries_the_shelf_surface() -> None:
    original = source(0)
    xyz = original.field.points
    z = original.field.values[:, 0] * 60
    reference = CoastalPlainDifferenceSource(
        xyz,
        z,
        z,
        np.zeros(len(z)),
        width_km=0,
        radius_km=6371,
        max_plain_elevation_m=500,
        mountain_fraction=0.15,
    )
    shelf = ShelfEnvelopeDifferenceSource(
        xyz,
        z,
        z,
        np.full(len(z), 80000),
        np.zeros(len(z)),
        radius_km=6371,
        shelf_break_depth_m=130,
        slope_m_per_km=70,
        protection_policy="source-weight",
    )
    assert shelf.coast is not None
    sequential = ShelfCoastalDifferenceSource(
        shelf, reference, shelf.coast, shoreline_reference="same source surface"
    )
    lat, lon = np.zeros(5), np.array([89.5, 90.0, 90.1, 90.3, 91.0])
    before = shelf.query(lat, lon)
    actual = sequential.query(lat, lon)
    np.testing.assert_array_equal(actual["replacement_m"], before["replacement_m"])
    assert np.any(actual["delta_m"] > 0)
    np.testing.assert_allclose(actual["delta_m"], before["delta_m"], rtol=0, atol=1e-8)
    assert sequential.metadata["stage_order"] == "shelf surface, shared shoreline, coastal profile"


def test_width_is_measured_from_geometry_and_has_no_grid_distance_floor() -> None:
    narrow, wide = source(10), source(100)
    lat, lon = np.array([0.0]), np.array([89.8])
    a, b = narrow.query(lat, lon), wide.query(lat, lon)
    np.testing.assert_array_equal(a["replacement_m"], a["before_m"])
    assert b["distance_km"][0] == pytest.approx(np.radians(0.2) * 6371, abs=1e-7)
    assert b["replacement_m"][0] > b["before_m"][0]
    assert b["replacement_m"][0] >= 30


def test_common_vertical_datum_shift_preserves_the_profile_difference() -> None:
    base = source(100)
    xyz, values = base.field.points, base.field.values.copy()
    # A steep source reaches the mountain part of the profile inside 100 km.
    values[:, :2] *= 40
    original = CoastalPlainDifferenceSource(
        xyz,
        values[:, 0],
        values[:, 1],
        values[:, 2],
        width_km=100,
        radius_km=6371,
        max_plain_elevation_m=500,
        mountain_fraction=0.15,
    )
    offset = 1200.0
    shifted = CoastalPlainDifferenceSource(
        xyz,
        values[:, 0] + offset,
        values[:, 1] + offset,
        values[:, 2] + offset,
        width_km=100,
        radius_km=6371,
        max_plain_elevation_m=500,
        mountain_fraction=0.15,
        sea_level_m=offset,
    )
    lat, lon = np.zeros(100), np.linspace(89, 91, 100)
    expected, actual = original.query(lat, lon), shifted.query(lat, lon)
    np.testing.assert_allclose(actual["delta_m"], expected["delta_m"], atol=1e-9)
    np.testing.assert_allclose(
        actual["replacement_m"], expected["replacement_m"] + offset, atol=1e-9
    )


def test_native_factory_replays_the_explicit_source_and_checks_stage_linkage() -> None:
    original = source(100)
    points, values = original.field.points, original.field.values
    fields = {
        "xyz": points,
        "after_shelf_m": values[:, 0],
        "before_coastal_plain_m": values[:, 0],
        "after_coastal_plain_m": values[:, 1],
        "coastal_lowland_target_m": values[:, 2],
    }
    metadata = {
        "format": "terrain-source-fields-v1",
        "cell_count": len(points),
        "radius_km": 6371,
        "sha256": "archive",
        "source": {"terrain_fingerprint": "reference", "sea_level_m": 0},
    }
    parameters = {
        "width_km": 100,
        "max_plain_elevation_m": 500,
        "mountain_fraction": 0.15,
        "profile_reference": "fixed input trial",
    }
    rebuilt = coastal_source_from_native(fields, metadata, **parameters)
    lat, lon = np.zeros(51), np.linspace(88, 92, 51)
    np.testing.assert_allclose(rebuilt.evaluate(lat, lon)[0], original.evaluate(lat, lon)[0])
    assert rebuilt.metadata["native_provenance"]["terrain_fingerprint"] == "reference"
    fields["after_shelf_m"] = values[:, 0] + 1
    with pytest.raises(ValueError, match="same stage"):
        coastal_source_from_native(fields, metadata, **parameters)


def test_footprint_support_covers_changes_in_the_old_stage_beyond_the_new_width() -> None:
    original = source(10)
    points, values = original.field.points, original.field.values.copy()
    # Frozen old lowland changes extend farther inland than the new 10 km width.
    changed = (points[:, 0] > 0) & (points[:, 0] < 0.2)
    values[changed, 1] -= 200
    field = CoastalPlainDifferenceSource(
        points,
        values[:, 0],
        values[:, 1],
        values[:, 2],
        width_km=10,
        radius_km=6371,
        max_plain_elevation_m=500,
        mountain_fraction=0.15,
    )
    latitude = np.zeros(1001)
    longitude = np.linspace(0, 180, len(latitude))
    supported = field.footprint_support(latitude, longitude, 0, 6371)
    delta = field.evaluate(latitude, longitude)[0]
    assert np.any((abs(delta) > 1e-7) & (longitude < 85))
    np.testing.assert_array_equal(delta[~supported], 0)
    with pytest.raises(ValueError, match="radii"):
        field.footprint_support(latitude, longitude, 0, 6400)
