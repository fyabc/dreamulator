"""Cone source volume, present-day area, shared surface and frozen geometry."""

from dataclasses import replace

import numpy as np
import pytest
from scipy.integrate import quad

from dreamulator.map.island_source import (
    FrozenVolcanicReplacement,
    VolcanicCone,
    VolcanicConeField,
)
from dreamulator.map.paleo_sutures import lonlat_to_xyz


def cone() -> VolcanicCone:
    return VolcanicCone("v1", "hotspot", 0, 0, -3000, 1000, 6000, 60, 7200 * np.pi)


def test_evolved_flank_volume_and_emergent_radius_share_one_profile() -> None:
    p = cone()
    assert p.relief_m == 4000 and p.radius_km == 40
    assert p.emergent_radius_km == 10
    integral = quad(
        lambda r: 2 * np.pi * r * float(p.relief_at_distance_m(np.array(r))) / 1000, 0, p.radius_km
    )[0]
    assert integral == pytest.approx(p.volume_km3, rel=1e-12)
    assert p.floor_elevation_m + float(p.relief_at_distance_m(np.array(10))) == pytest.approx(0)
    radius = 6371.0
    spherical = quad(
        lambda r: (
            2
            * np.pi
            * radius
            * np.sin(r / radius)
            * float(p.relief_at_distance_m(np.array(r)))
            / 1000
        ),
        0,
        p.radius_km,
    )[0]
    assert spherical == pytest.approx(p.spherical_volume_km3(radius), rel=1e-12)
    assert p.volume_km3 * 0.999 < spherical <= p.volume_km3


def test_absolute_surface_respects_summit_background_support_and_overlap() -> None:
    p = cone()
    field = VolcanicConeField([p], 6371)
    distances = np.array([0, 5, 10, 40, 41])
    xyz = lonlat_to_xyz(np.column_stack([np.degrees(distances / 6371), np.zeros(5)]))
    floor = np.full(5, -3000.0)
    actual = field.surface_m(xyz, floor)
    np.testing.assert_allclose(actual, [1000, 500, 0, -3000, -3000], atol=1e-8)
    higher = np.full(5, 1500.0)
    np.testing.assert_array_equal(field.surface_m(xyz, higher), higher)
    other = replace(p, source_id="v2", summit_elevation_m=2000)
    both = VolcanicConeField([p, other], 6371)
    np.testing.assert_allclose(
        both.surface_m(xyz, floor), VolcanicConeField([other], 6371).surface_m(xyz, floor)
    )
    np.testing.assert_array_equal(actual, field.surface_m(xyz.reshape((1, 5, 3)), floor[None])[0])


def test_replacement_zero_control_and_datum_translation() -> None:
    xyz = np.concatenate([np.eye(3), -np.eye(3)])
    reference = np.full(6, -100.0)
    control = FrozenVolcanicReplacement(
        [],
        xyz,
        reference,
        reference,
        planet_radius_km=6371,
        reference_id="accepted",
        background_reference_id="same",
    )
    lat, lon = np.array([0.0, 20.0]), np.array([0.0, 40.0])
    np.testing.assert_array_equal(control.evaluate(lat, lon)[0], [0, 0])
    baseline = FrozenVolcanicReplacement(
        [cone()],
        xyz,
        reference,
        reference - 400,
        planet_radius_km=6371,
        reference_id="accepted",
        background_reference_id="recomputed",
    )
    shifted_cone = replace(cone(), floor_elevation_m=-2300, summit_elevation_m=1700)
    shifted = FrozenVolcanicReplacement(
        [shifted_cone],
        xyz,
        reference + 700,
        reference + 300,
        planet_radius_km=6371,
        reference_id="shifted",
        background_reference_id="shifted-response",
    )
    np.testing.assert_allclose(
        shifted.evaluate(lat, lon)[0], baseline.evaluate(lat, lon)[0], atol=1e-10
    )


def test_deposit_meets_sloping_substrate_and_retains_single_body_volume() -> None:
    p = cone()
    field = VolcanicConeField([p], 6371)
    distance = np.array([0, 10, p.radius_km - 1e-5, p.radius_km, p.radius_km + 1e-5])
    xyz = lonlat_to_xyz(np.column_stack([np.degrees(distance / 6371), np.zeros(len(distance))]))
    thickness = field.thickness_m(xyz)
    np.testing.assert_allclose(thickness, [4000, 3000, 0.001, 0, 0], atol=1e-7)
    substrate = -3000 - distance * 10
    deposited = substrate + thickness
    assert abs(deposited[-3] - deposited[-2]) < 0.002
    integral = quad(
        lambda r: (
            2
            * np.pi
            * 6371
            * np.sin(r / 6371)
            * field.thickness_m(lonlat_to_xyz(np.array([[np.degrees(r / 6371), 0]])))[0]
            / 1000
        ),
        0,
        p.radius_km,
    )[0]
    assert integral == pytest.approx(p.spherical_volume_km3(6371), rel=1e-10)
