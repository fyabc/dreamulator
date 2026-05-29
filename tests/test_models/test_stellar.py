"""Tests for stellar models."""

import pytest
from pydantic import ValidationError

from dreamulator.models.stellar import (
    LuminosityClass,
    OrbitalElements,
    SpectralClass,
    Star,
    StellarSystem,
)


class TestStar:
    def test_valid_star(self):
        star = Star(
            id="star_sol",
            name="Sol",
            spectral_class=SpectralClass.G,
            luminosity_class=LuminosityClass.V,
            mass=1.0,
        )
        assert star.id == "star_sol"
        assert star.mass == 1.0
        assert star.metallicity == 0.0

    def test_star_with_optional_fields(self):
        star = Star(
            id="star_sol",
            name="Sol",
            spectral_class=SpectralClass.G,
            mass=1.0,
            luminosity=1.0,
            temperature=5778.0,
            radius=1.0,
        )
        assert star.luminosity == 1.0
        assert star.temperature == 5778.0

    def test_star_invalid_mass(self):
        with pytest.raises(ValidationError):
            Star(
                id="star_bad",
                name="Bad",
                spectral_class=SpectralClass.G,
                mass=-1.0,  # invalid
            )


class TestOrbitalElements:
    def test_valid_orbit(self):
        orbit = OrbitalElements(
            body_id="planet_terra",
            parent_id="star_sol",
            semi_major_axis_au=1.0,
            eccentricity=0.017,
        )
        assert orbit.body_id == "planet_terra"
        assert orbit.eccentricity == 0.017

    def test_invalid_eccentricity(self):
        with pytest.raises(ValidationError):
            OrbitalElements(
                body_id="planet_bad",
                parent_id="star_sol",
                semi_major_axis_au=1.0,
                eccentricity=1.5,  # must be < 1
            )


class TestStellarSystem:
    def test_valid_system(self):
        system = StellarSystem(
            name="Solar System",
            stars=[
                Star(id="star_sol", name="Sol", spectral_class=SpectralClass.G, mass=1.0)
            ],
        )
        assert len(system.stars) == 1

    def test_duplicate_star_ids_rejected(self):
        with pytest.raises(ValidationError, match="unique"):
            StellarSystem(
                name="Bad System",
                stars=[
                    Star(id="star_a", name="A", spectral_class=SpectralClass.G, mass=1.0),
                    Star(id="star_a", name="A2", spectral_class=SpectralClass.K, mass=0.8),
                ],
            )
