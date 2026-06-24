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
                mass=-1.0,  # invalid: must be > 0
            )

    def test_star_luminosity_only(self):
        """Hybrid mode: luminosity as sole input (no mass)."""
        star = Star(
            id="star_m",
            name="M Dwarf",
            spectral_class=SpectralClass.M,
            mass=None,
            luminosity=0.027,
        )
        assert star.mass is None
        assert star.luminosity == 0.027

    def test_star_both_mass_and_luminosity(self):
        """Hybrid mode: both mass and luminosity provided."""
        star = Star(
            id="star_both",
            name="Both",
            spectral_class=SpectralClass.G,
            mass=1.0,
            luminosity=1.0,
        )
        assert star.mass == 1.0
        assert star.luminosity == 1.0

    def test_star_neither_mass_nor_luminosity(self):
        """Reject: neither mass nor luminosity provided."""
        with pytest.raises(ValidationError, match="at least one"):
            Star(
                id="star_empty",
                name="Empty",
                spectral_class=SpectralClass.G,
                mass=None,
                luminosity=None,
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
