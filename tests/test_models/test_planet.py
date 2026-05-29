"""Tests for planet models."""

import pytest
from pydantic import ValidationError

from dreamulator.models.planet import Atmosphere, Planet, PlanetType


class TestPlanet:
    def test_valid_planet(self):
        planet = Planet(
            id="planet_terra",
            name="Terra",
            orbits="star_sol",
            planet_type=PlanetType.TERRESTRIAL,
            mass=1.0,
            radius=1.0,
        )
        assert planet.id == "planet_terra"
        assert planet.albedo == 0.3  # default

    def test_invalid_albedo(self):
        with pytest.raises(ValidationError):
            Planet(
                id="planet_bad",
                name="Bad",
                orbits="star_sol",
                mass=1.0,
                radius=1.0,
                albedo=1.5,  # must be 0-1
            )


class TestAtmosphere:
    def test_valid_atmosphere(self):
        atm = Atmosphere(
            surface_pressure_atm=1.0,
            composition={"N2": 0.78, "O2": 0.21, "Ar": 0.01},
        )
        assert atm.surface_pressure_atm == 1.0

    def test_bad_composition_sum(self):
        with pytest.raises(ValidationError, match="sum to"):
            Atmosphere(
                surface_pressure_atm=1.0,
                composition={"N2": 0.5, "O2": 0.1},  # sums to 0.6, too far from 1.0
            )
