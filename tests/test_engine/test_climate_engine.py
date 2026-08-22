"""Tests for the planet → simulation config physical-parameter mapping.

The mapping now lives in the shared ``engine.physical_inputs`` module (used
by both the geological and climate engines); these tests cover the pure
apply step.
"""

from __future__ import annotations

from typing import Any

import pytest

from dreamulator.engine.physical_inputs import apply_physical_parameters
from dreamulator.map.pipeline_types import TerrainPipelineConfig
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


def _build(
    planet: Planet,
    stellar_luminosity: float | None,
    orbital_distance_au: float | None,
) -> TerrainPipelineConfig:
    config = TerrainPipelineConfig()
    apply_physical_parameters(config, planet, stellar_luminosity, orbital_distance_au)
    return config


def test_zero_axial_tilt_is_preserved():
    """A tidally locked body's explicit tilt=0.0 must survive (no seasons).

    Regression: a truthiness check once replaced 0.0 with Earth's 23.44°,
    silently giving every zero-tilt world fictitious seasons.
    """
    planet = _make_planet(axial_tilt_deg=0.0, rotation_period_days=3.25)
    config = _build(planet, stellar_luminosity=0.0357, orbital_distance_au=0.28)
    assert config.axial_tilt_deg == 0.0
    assert config.rotation_period_days == 3.25
    assert config.stellar_luminosity_sol == 0.0357
    assert config.orbital_distance_au == 0.28


def test_earth_like_values_pass_through():
    planet = _make_planet(axial_tilt_deg=23.44, rotation_period_days=1.0)
    config = _build(planet, 1.0, 1.0)
    assert config.axial_tilt_deg == 23.44
    assert config.rotation_period_days == 1.0
    assert config.radius_km == 6371.0


def test_greenhouse_from_atmosphere():
    planet = _make_planet(atmosphere={"greenhouse_factor": 21.0})
    config = _build(planet, None, None)
    assert config.greenhouse_warming_K == 21.0


def test_none_stellar_forcing_leaves_defaults():
    """Unresolved forcing must keep the coherent Earth-like default pair."""
    planet = _make_planet()
    config = _build(planet, None, None)
    assert config.stellar_luminosity_sol == 1.0
    assert config.orbital_distance_au == 1.0


def test_radius_in_earth_units_is_converted():
    planet = _make_planet(radius=1.07)
    config = _build(planet, None, None)
    assert config.radius_km == pytest.approx(1.07 * 6371.0)


def test_planet_albedo_gravity_and_pressure_are_applied():
    planet = _make_planet(
        mass=1.2,
        radius=1.07,
        albedo=0.25,
        atmosphere={"surface_pressure_atm": 1.5, "greenhouse_factor": 40.0},
    )
    config = _build(planet, None, None)
    assert config.albedo == 0.25
    assert config.gravity_m_s2 == pytest.approx(9.81 * 1.2 / 1.07**2)
    assert config.surface_pressure_hpa == pytest.approx(1.5 * 1013.25)
    assert config.greenhouse_warming_K == 40.0
