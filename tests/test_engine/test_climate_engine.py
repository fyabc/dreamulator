"""Tests for the climate engine's planet → simulation config mapping."""

from __future__ import annotations

from typing import Any

from dreamulator.engine.climate import _build_terrain_config
from dreamulator.models.planet import Planet


def _make_planet(**overrides: Any) -> Planet:
    base: dict[str, Any] = {
        "id": "satellite_test",
        "name": "Test Moon",
        "orbits": "planet_host",
        "mass": 1.0,
        "radius": 1.0,
    }
    base.update(overrides)
    return Planet(**base)


def test_zero_axial_tilt_is_preserved():
    """A tidally locked body's explicit tilt=0.0 must survive (no seasons).

    Regression: a truthiness check once replaced 0.0 with Earth's 23.44°,
    silently giving every zero-tilt world fictitious seasons.
    """
    planet = _make_planet(axial_tilt_deg=0.0, rotation_period_days=3.25)
    config = _build_terrain_config(planet, stellar_luminosity=0.0357, orbital_distance_au=0.28)
    assert config.axial_tilt_deg == 0.0
    assert config.rotation_period_days == 3.25
    assert config.stellar_luminosity_sol == 0.0357
    assert config.orbital_distance_au == 0.28


def test_earth_like_values_pass_through():
    planet = _make_planet(axial_tilt_deg=23.44, rotation_period_days=1.0)
    config = _build_terrain_config(planet, 1.0, 1.0)
    assert config.axial_tilt_deg == 23.44
    assert config.rotation_period_days == 1.0
    assert config.radius_km == 6371.0
