"""Tests for stellar models."""

import pytest
from pydantic import ValidationError

from dreamulator.models.stellar import (
    LuminosityClass,
    OrbitalElements,
    OrbitingBody,
    Star,
    StellarSystem,
)


class TestStar:
    def test_valid_star(self):
        star = Star(
            id="star_sol",
            name="Sol",
            spectral_class="G2",
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
            spectral_class="G2",
            mass=1.0,
            luminosity=1.0,
            temperature=5778.0,
            radius=1.0,
        )
        assert star.luminosity == 1.0
        assert star.temperature == 5778.0

    def test_star_coarse_spectral_class(self):
        """Coarse spectral class (letter only, no digit) is still valid."""
        star = Star(
            id="star_coarse",
            name="Coarse",
            spectral_class="G",
            mass=1.0,
        )
        assert star.spectral_class == "G"

    def test_star_invalid_spectral_class(self):
        """Reject spectral class that doesn't match MK pattern."""
        with pytest.raises(ValidationError, match="spectral_class"):
            Star(
                id="star_bad_type",
                name="BadType",
                spectral_class="X9",
                mass=1.0,
            )

    def test_star_invalid_mass(self):
        with pytest.raises(ValidationError):
            Star(
                id="star_bad",
                name="Bad",
                spectral_class="G2",
                mass=-1.0,  # invalid: must be > 0
            )

    def test_star_luminosity_only(self):
        """Hybrid mode: luminosity as sole input (no mass)."""
        star = Star(
            id="star_m",
            name="M Dwarf",
            spectral_class="M1",
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
            spectral_class="G2",
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
                spectral_class="G2",
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
            stars=[Star(id="star_sol", name="Sol", spectral_class="G2", mass=1.0)],
        )
        assert len(system.stars) == 1

    def test_duplicate_star_ids_rejected(self):
        with pytest.raises(ValidationError, match="unique"):
            StellarSystem(
                name="Bad System",
                stars=[
                    Star(id="star_a", name="A", spectral_class="G2", mass=1.0),
                    Star(id="star_a", name="A2", spectral_class="K5", mass=0.8),
                ],
            )


class TestOrbitingBody:
    def test_valid_moon(self):
        body = OrbitingBody(
            id="satellite_moon",
            name="Moon",
            mass_earth=0.0123,
            radius_km=1737.4,
            rotation_period_days=27.3217,
            axial_tilt_deg=6.687,
            albedo=0.136,
        )
        assert body.id == "satellite_moon"
        assert body.body_type == "natural_satellite"
        assert body.mass_earth == 0.0123
        assert body.radius_km == 1737.4

    def test_asteroid_with_surface(self):
        body = OrbitingBody(
            id="satellite_companion",
            name="Companion",
            body_type="trojan_asteroid",
            mass_earth=1.5e-11,
            radius_km=12.0,
            surface={"composition": "silicate_metal", "has_atmosphere": False},
        )
        assert body.body_type == "trojan_asteroid"
        assert body.surface is not None
        assert body.surface["composition"] == "silicate_metal"

    def test_system_with_bodies(self):
        """StellarSystem accepts both orbits and bodies for moons."""
        system = StellarSystem(
            name="Solar System",
            stars=[Star(id="star_sol", name="Sol", spectral_class="G2", mass=1.0)],
            orbits=[
                OrbitalElements(
                    body_id="planet_earth",
                    parent_id="star_sol",
                    semi_major_axis_au=1.0,
                    eccentricity=0.017,
                ),
                OrbitalElements(
                    body_id="satellite_moon",
                    parent_id="planet_earth",
                    semi_major_axis_au=0.00257,
                    eccentricity=0.0549,
                ),
            ],
            bodies=[
                OrbitingBody(id="satellite_moon", name="Moon", mass_earth=0.0123, radius_km=1737.4),
            ],
        )
        assert len(system.bodies) == 1
        assert system.bodies[0].id == "satellite_moon"

    def test_system_without_bodies(self):
        """StellarSystem works fine without bodies (backward compatible)."""
        system = StellarSystem(
            name="Simple",
            stars=[Star(id="star_s", name="S", spectral_class="G", mass=1.0)],
        )
        assert system.bodies == []
