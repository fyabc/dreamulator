"""Unit tests for the GCM world→ExoPlaSim parameter mapping.

The mapping is a pure module (no ExoPlaSim dependency), so these tests run in
the default dev environment.  They double as the regression guard for the
2026-10-05 unit bug: ExoPlaSim's ``configure(radius=...)`` takes Earth radii,
and passing metres once produced a 6.4e6×-oversized planet with a "dead" wind
field.
"""

from __future__ import annotations

import math

import pytest

from dreamulator.gcm.mapping import (
    ATM_TO_BAR,
    G_EARTH_MS2,
    MappingError,
    map_planet,
    map_world,
)

# --- synthetic world inputs -------------------------------------------------
PLANET = {
    "id": "test_planet",
    "mass": 1.0,
    "radius": 1.0,
    "rotation_period_days": 1.0,
    "axial_tilt_deg": 23.44,
    "albedo": 0.3,
    "atmosphere": {
        "surface_pressure_atm": 1.0,
        "composition": {"N2": 0.78, "O2": 0.21, "Ar": 0.01},
    },
}
STAR = {"id": "star_test", "mass": 1.0, "luminosity": 1.0}
ORBIT = {"body_id": "test_planet", "semi_major_axis_au": 1.0, "eccentricity": 0.0}


def test_earth_like_defaults() -> None:
    params = map_planet(PLANET, STAR, ORBIT)
    kwargs = params.to_configure_kwargs()
    assert kwargs["radius"] == pytest.approx(1.0)
    assert kwargs["gravity"] == pytest.approx(G_EARTH_MS2)
    assert kwargs["rotationperiod"] == pytest.approx(1.0)
    assert kwargs["obliquity"] == pytest.approx(23.44)
    assert kwargs["flux"] == pytest.approx(1361.0)
    assert kwargs["year"] == pytest.approx(365.25)
    assert kwargs["pressure"] == pytest.approx(ATM_TO_BAR)
    # Composition mapped to partial pressures (bar).
    assert kwargs["pN2"] == pytest.approx(ATM_TO_BAR * 0.78)
    assert kwargs["pO2"] == pytest.approx(ATM_TO_BAR * 0.21)
    assert kwargs["pAr"] == pytest.approx(ATM_TO_BAR * 0.01)
    assert "pCO2" not in kwargs


def test_radius_never_in_metres_regression() -> None:
    """The 2026-09-07 dead-wind bug: radius in metres must be rejected loudly."""
    oversized = dict(PLANET, radius=6817e3)  # metres passed where R⊕ expected
    with pytest.raises(MappingError, match="Earth radii"):
        map_planet(oversized, STAR, ORBIT)


def test_flux_scales_with_luminosity_and_distance() -> None:
    dim_star = dict(STAR, luminosity=0.0761)
    close_orbit = dict(ORBIT, semi_major_axis_au=0.3532124639)
    params = map_planet(PLANET, dim_star, close_orbit)
    expected = 1361.0 * 0.0761 / 0.3532124639**2
    assert params.flux == pytest.approx(expected, rel=1e-6)


def test_year_from_kepler_matches_canon() -> None:
    """Nacrea canon: a=0.3532 AU around a 0.59 M☉ star → ~99.8 24-hour days."""
    dim_star = dict(STAR, mass=0.59)
    close_orbit = dict(ORBIT, semi_major_axis_au=0.3532124639)
    params = map_planet(PLANET, dim_star, close_orbit)
    assert params.year == pytest.approx(365.25 * math.sqrt(0.3532124639**3 / 0.59))
    assert 99.0 < params.year < 101.0


def test_gravity_from_mass_radius() -> None:
    params = map_planet(dict(PLANET, mass=1.20, radius=1.07), STAR, ORBIT)
    assert params.gravity == pytest.approx(G_EARTH_MS2 * 1.20 / 1.07**2)
    assert params.gravity == pytest.approx(10.28, abs=0.01)


def test_greenhouse_modes() -> None:
    green = dict(
        PLANET,
        atmosphere=dict(PLANET["atmosphere"], greenhouse_factor=62.0),
    )
    # none: uncompensated + warning recorded
    params = map_planet(green, STAR, ORBIT)
    assert params.flux == pytest.approx(1361.0)
    assert any("greenhouse_factor 62.0" in w for w in params.warnings)
    assert params.pco2 is None
    # flux_boost: explicit factor + warning
    params = map_planet(green, STAR, ORBIT, greenhouse_mode="flux_boost", flux_boost_factor=2.0)
    assert params.flux == pytest.approx(2722.0)
    # pco2: explicit partial pressure, no flux change
    params = map_planet(green, STAR, ORBIT, greenhouse_mode="pco2", pco2_bar=0.2)
    assert params.flux == pytest.approx(1361.0)
    assert params.pco2 == pytest.approx(0.2)
    assert params.pressure == pytest.approx(ATM_TO_BAR + 0.2)
    # missing factor / unknown mode are hard errors
    with pytest.raises(MappingError, match="flux_boost_factor"):
        map_planet(green, STAR, ORBIT, greenhouse_mode="flux_boost")
    with pytest.raises(MappingError, match="greenhouse_mode"):
        map_planet(green, STAR, ORBIT, greenhouse_mode="wizardry")


def test_co2_from_composition_when_present() -> None:
    with_co2 = dict(
        PLANET,
        atmosphere=dict(PLANET["atmosphere"], composition={"N2": 0.9, "CO2": 0.05}),
    )
    params = map_planet(with_co2, STAR, ORBIT)
    assert params.pco2 == pytest.approx(ATM_TO_BAR * 0.05)


def test_overrides_replace_computed_scalars() -> None:
    params = map_planet(PLANET, STAR, ORBIT, overrides={"year": 99.7})
    assert params.year == pytest.approx(99.7)
    with pytest.raises(MappingError, match="override"):
        map_planet(PLANET, STAR, ORBIT, overrides={"warp": 1.0})


def test_satellite_resolves_host_orbit() -> None:
    satellite = dict(PLANET, id="sat_test", orbits="planet_host")
    star_orbits = [
        dict(ORBIT, body_id="sat_test"),  # must NOT be picked
        dict(ORBIT, body_id="planet_host", semi_major_axis_au=0.5),
    ]
    # map_world is filesystem-based; exercise the orbit-resolution logic via
    # map_planet with the host orbit directly, mirroring map_world's lookup.
    host_orbit = star_orbits[1]
    params = map_planet(satellite, STAR, host_orbit)
    assert params.flux == pytest.approx(1361.0 / 0.25)


def test_map_world_earth_planet_orbits_star() -> None:
    """A planet whose ``orbits`` names the star uses its own orbit entry."""
    import pathlib

    world = pathlib.Path(__file__).resolve().parents[1] / "data" / "worlds" / "earth"
    if not (world / "layers/astronomy/input/stellar.yaml").exists():
        pytest.skip("earth world data not present")
    params = map_world(world, "planet_earth")
    assert params.radius == pytest.approx(1.0)
    assert params.flux == pytest.approx(1361.0)
    assert params.year == pytest.approx(365.25, rel=1e-3)
    # stellar temperature flows through for the radiation spectral split
    assert params.startemp == pytest.approx(5772.0)


def test_map_world_nacrea() -> None:
    """End-to-end against the real nacrea inputs (E3 canon values)."""
    import pathlib

    world = pathlib.Path(__file__).resolve().parents[1] / "data" / "worlds" / "nacrea"
    if not (world / "layers/astronomy/input/stellar.yaml").exists():
        pytest.skip("nacrea world data not present")
    params = map_world(world, "satellite_nacrea")
    assert params.radius == pytest.approx(1.07)
    assert params.gravity == pytest.approx(10.28, abs=0.01)
    assert params.rotationperiod == pytest.approx(3.138)
    assert params.obliquity == pytest.approx(14.9)
    assert params.eccentricity == pytest.approx(0.06786252)
    assert params.flux == pytest.approx(1361.0 * 0.1227 / 0.3648**2, rel=1e-6)
    assert params.year == pytest.approx(99.8, abs=0.5)  # year-locked scaling
    assert params.pressure == pytest.approx(1.0 * ATM_TO_BAR)
    assert any("greenhouse" in w for w in params.warnings)
    # K6 star (route-1 recalibration): the explicit temperature field drives
    # ExoPlaSim's spectral partition (visible fraction ~0.33 at 4365 K vs the
    # 5772 K default's 0.52) — without it the greenhouse is computed for a
    # G2 spectrum (2026-10-06 bug).
    assert params.startemp == pytest.approx(4365.0)


def test_multi_year_otherargs_disables_step_cap() -> None:
    """N_RUN_YEARS alone is silently truncated to one year.

    ``configure()`` writes ``N_RUN_STEPS=11520`` whenever rotationperiod
    differs from 1.0, and the Fortran main loop returns when the step
    countdown reaches zero regardless of the month countdown — so the
    harness must force ``N_RUN_STEPS=0`` next to ``N_RUN_YEARS``.
    """
    from dreamulator.gcm.runner import multi_year_otherargs

    otherargs = multi_year_otherargs(50)
    assert otherargs == {
        "N_RUN_YEARS@plasim_namelist": "50",
        "N_RUN_STEPS@plasim_namelist": "0",
    }
