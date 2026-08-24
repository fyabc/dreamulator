"""Tests for shared physical-parameter resolution (engine/physical_inputs.py).

Covers the satellite-aware stellar lookup (moon → host planet → host star),
derived-over-input luminosity precedence, Kepler's-third-law orbital period,
fallback/default behavior, and the all-or-nothing coherence rule for the
stellar forcing pair.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml

from dreamulator.engine.physical_inputs import (
    build_system_catalog,
    check_body_field_consistency,
    resolve_and_apply_physical_parameters,
    resolve_orbital_elements,
    resolve_stellar_forcing,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.models.planet import Planet

if TYPE_CHECKING:
    from pathlib import Path


class _StubEngine:
    """Duck-typed BaseEngine stand-in exposing a fixed relative-path → file map."""

    def __init__(self, files: dict[str, Path]) -> None:
        self._files = files

    def find_input(self, relative_path: str) -> Path | None:
        return self._files.get(relative_path)


def _write(tmp_path: Path, name: str, data: dict[str, Any]) -> Path:
    path = tmp_path / name
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    return path


def _make_planet(pid: str, orbits: str) -> Planet:
    return Planet(
        id=pid,
        name=pid,
        orbits=orbits,
        mass=1.0,
        radius=1.0,
        axial_tilt_deg=0.0,
        rotation_period_days=3.25,
    )


# Mirrors the nacrea system: habitable moon around a gas giant at 0.2795 AU
# around a 0.0357 L_sun / 0.4499 M_sun M-dwarf.
_GAIA_STELLAR: dict[str, Any] = {
    "stars": [{"id": "star_ignis", "luminosity": 0.0357, "mass": 0.449864}],
    "orbits": [
        # Heliocentric orbit (drives the seasonal insolation cycle): e = 0.005.
        {
            "body_id": "planet_aegis",
            "parent_id": "star_ignis",
            "semi_major_axis_au": 0.2795,
            "eccentricity": 0.005,
        },
        # Satellite link — must NOT be added to the heliocentric distance
        # (eps^2 ≈ 0.03% time-averaged error; see physical_inputs docstring),
        # and its eccentricity (0.002, the tidal-heating source) must NOT be
        # mistaken for the heliocentric eccentricity.
        {
            "body_id": "satellite_nacrea",
            "parent_id": "planet_aegis",
            "semi_major_axis_au": 0.00494,
            "eccentricity": 0.002,
        },
    ],
}


def test_satellite_resolves_host_star_distance_and_period(tmp_path: Path) -> None:
    stellar = _write(tmp_path, "stellar.yaml", _GAIA_STELLAR)
    engine = _StubEngine({"stellar.yaml": stellar})
    planet = _make_planet("satellite_nacrea", "planet_aegis")

    lum, dist, period, warnings = resolve_stellar_forcing(engine, planet)

    assert lum == 0.0357
    assert dist == 0.2795  # host planet's distance, not +0.00494
    # Kepler: 365.25 × sqrt(0.2795³ / 0.449864) ≈ 80.47 days
    # (physical_params.md: 78 h lock + 80.5-day stellar year)
    assert period == pytest.approx(80.47, rel=1e-3)
    assert warnings == []


def test_derived_luminosity_overrides_input(tmp_path: Path) -> None:
    stellar = _write(tmp_path, "stellar.yaml", _GAIA_STELLAR)
    derived = _write(
        tmp_path,
        "stellar_derived.yaml",
        {"stars": [{"id": "star_ignis", "computed_luminosity": 0.036}]},
    )
    engine = _StubEngine({"stellar.yaml": stellar, "stellar_derived.yaml": derived})
    planet = _make_planet("planet_aegis", "star_ignis")

    lum, dist, period, warnings = resolve_stellar_forcing(engine, planet)

    assert lum == 0.036
    assert dist == 0.2795
    assert period == pytest.approx(80.47, rel=1e-3)
    assert warnings == []


def test_direct_planet_around_star(tmp_path: Path) -> None:
    stellar = _write(
        tmp_path,
        "stellar.yaml",
        {
            "stars": [{"id": "star_sol", "luminosity": 1.0, "mass": 1.0}],
            "orbits": [
                {"body_id": "planet_earth", "parent_id": "star_sol", "semi_major_axis_au": 1.0}
            ],
        },
    )
    engine = _StubEngine({"stellar.yaml": stellar})
    planet = _make_planet("planet_earth", "star_sol")

    lum, dist, period, warnings = resolve_stellar_forcing(engine, planet)

    assert (lum, dist) == (1.0, 1.0)
    assert period == pytest.approx(365.25)
    assert warnings == []


def test_missing_stellar_mass_keeps_default_period(tmp_path: Path) -> None:
    stellar = _write(
        tmp_path,
        "stellar.yaml",
        {
            "stars": [{"id": "star_sol", "luminosity": 1.0}],  # no mass
            "orbits": [{"body_id": "planet_x", "parent_id": "star_sol", "semi_major_axis_au": 1.0}],
        },
    )
    engine = _StubEngine({"stellar.yaml": stellar})
    planet = _make_planet("planet_x", "star_sol")

    lum, dist, period, warnings = resolve_stellar_forcing(engine, planet)

    assert (lum, dist) == (1.0, 1.0)
    assert period is None
    assert any("mass" in w for w in warnings)


def test_legacy_layout_without_orbit_entry_keeps_coherent_defaults(tmp_path: Path) -> None:
    """planet.orbits names the star directly but no orbit entry exists.

    Luminosity is resolvable via the legacy fallback, distance is not; the
    pair must come back all-None (coherent defaults) rather than a mixed
    resolved-luminosity / default-distance combination.
    """
    stellar = _write(tmp_path, "stellar.yaml", {"stars": [{"id": "star_sol", "luminosity": 1.0}]})
    engine = _StubEngine({"stellar.yaml": stellar})
    planet = _make_planet("planet_x", "star_sol")

    lum, dist, period, warnings = resolve_stellar_forcing(engine, planet)

    assert lum is None
    assert dist is None
    assert period is None
    assert any("orbital elements" in w for w in warnings)


def test_no_stellar_data_is_silent_defaults(tmp_path: Path) -> None:
    engine = _StubEngine({})
    planet = _make_planet("planet_x", "star_missing")

    lum, dist, period, warnings = resolve_stellar_forcing(engine, planet)

    assert lum is None
    assert dist is None
    assert period is None
    assert warnings == []


def test_heliocentric_eccentricity_ignores_satellite_orbit(tmp_path: Path) -> None:
    """Seasonal eccentricity = the star-orbiting member's e, not the moon's.

    The satellite's own orbit eccentricity (0.002) is the tidal-heating source;
    the seasonal insolation cycle follows the heliocentric orbit (0.005).
    """
    stellar = _write(tmp_path, "stellar.yaml", _GAIA_STELLAR)
    engine = _StubEngine({"stellar.yaml": stellar})
    planet = _make_planet("satellite_nacrea", "planet_aegis")

    ecc, is_satellite, warnings = resolve_orbital_elements(engine, planet)

    assert ecc == pytest.approx(0.005)  # heliocentric, NOT the satellite's 0.002
    assert is_satellite is True
    assert warnings == []


def test_parent_chain_cycle_is_guarded(tmp_path: Path) -> None:
    stellar = _write(
        tmp_path,
        "stellar.yaml",
        {
            "stars": [{"id": "star_s", "luminosity": 0.5}],
            "orbits": [
                {"body_id": "body_a", "parent_id": "body_b", "semi_major_axis_au": 0.1},
                {"body_id": "body_b", "parent_id": "body_a", "semi_major_axis_au": 0.2},
            ],
        },
    )
    engine = _StubEngine({"stellar.yaml": stellar})
    planet = _make_planet("body_a", "body_b")

    lum, dist, period, warnings = resolve_stellar_forcing(engine, planet)

    assert lum is None
    assert dist is None
    assert period is None
    assert warnings  # unresolved host star + missing orbital elements


def test_resolve_and_apply_full_chain(tmp_path: Path) -> None:
    stellar = _write(tmp_path, "stellar.yaml", _GAIA_STELLAR)
    planets = _write(
        tmp_path,
        "planets.yaml",
        {
            "planets": [
                {
                    "id": "satellite_nacrea",
                    "name": "Nacrea",
                    "orbits": "planet_aegis",
                    "mass": 1.2,
                    "radius": 1.07,
                    "rotation_period_days": 3.25,
                    "axial_tilt_deg": 0.0,
                    "atmosphere": {"greenhouse_factor": 33.0},
                }
            ]
        },
    )
    engine = _StubEngine({"stellar.yaml": stellar, "planets.yaml": planets})
    config = TerrainPipelineConfig()

    warnings = resolve_and_apply_physical_parameters(engine, config)

    assert warnings == []
    assert config.stellar_luminosity_sol == 0.0357
    assert config.orbital_distance_au == 0.2795
    assert config.orbital_period_days == pytest.approx(80.47, rel=1e-3)
    assert config.axial_tilt_deg == 0.0
    assert config.rotation_period_days == 3.25
    assert config.radius_km == pytest.approx(1.07 * 6371.0)  # 6816.97 km
    assert config.gravity_m_s2 == pytest.approx(9.81 * 1.2 / 1.07**2)  # ≈ 10.29
    assert config.albedo == 0.3  # Planet model default
    assert config.greenhouse_warming_K == 33.0
    assert config.surface_pressure_hpa == pytest.approx(1013.25)  # 1 atm default
    assert config.eccentricity == pytest.approx(0.005)  # heliocentric, not satellite 0.002


# ===================================================================
# nacrea system fixtures (shared by build_system_catalog tests)
# ===================================================================

_GAIA_STELLAR_WITH_BODIES: dict[str, Any] = {
    "stars": [{"id": "star_ignis", "luminosity": 0.0414, "mass": 0.4665, "age_gyr": 5.9}],
    "orbits": [
        {
            "body_id": "planet_aegis",
            "parent_id": "star_ignis",
            "semi_major_axis_au": 0.2504,
            "eccentricity": 0.005,
        },
        {
            "body_id": "satellite_nacrea",
            "parent_id": "planet_aegis",
            "semi_major_axis_au": 0.00494,
            "eccentricity": 0.002,
        },
    ],
    "bodies": [{"id": "planet_aegis", "mass_earth": 508.5}],
}

_GAIA_PLANET_YAML: dict[str, Any] = {
    "planets": [
        {
            "id": "satellite_nacrea",
            "name": "Nacrea",
            "orbits": "planet_aegis",
            "mass": 1.2,
            "radius": 1.07,
            "rotation_period_days": 3.25,
            "axial_tilt_deg": 9.0,
            "albedo": 0.30,
            "atmosphere": {"greenhouse_factor": 62.0},
        }
    ]
}


def _gaia_stub(tmp_path: Path) -> _StubEngine:
    stellar = _write(tmp_path, "stellar.yaml", _GAIA_STELLAR_WITH_BODIES)
    # Engine-computed stellar results from a prior build (incl. T_eff, which
    # the authored stellar.yaml does not carry) — needed for the HZ check.
    derived = _write(
        tmp_path,
        "stellar_derived.yaml",
        {"stars": [{"id": "star_ignis", "computed_temperature": 3931.0}]},
    )
    planets = _write(tmp_path, "planets.yaml", _GAIA_PLANET_YAML)
    return _StubEngine(
        {"stellar.yaml": stellar, "stellar_derived.yaml": derived, "planets.yaml": planets}
    )


# check_body_field_consistency — stellar bodies vs planets.yaml drift
# ===================================================================


def _planet_model(pid: str, **overrides: Any) -> Planet:
    base: dict[str, Any] = {
        "id": pid,
        "name": pid,
        "orbits": "star_x",
        "mass": 1.2,
        "radius": 1.07,
        "rotation_period_days": 3.25,
        "axial_tilt_deg": 9.0,
        "albedo": 0.30,
    }
    base.update(overrides)
    return Planet(**base)


def test_consistency_check_passes_when_aligned() -> None:
    bodies = [
        {
            "id": "satellite_nacrea",
            "mass_earth": 1.2,
            "radius_km": 1.07 * 6371.0,
            "rotation_period_days": 3.25,
            "axial_tilt_deg": 9.0,
            "albedo": 0.30,
        }
    ]
    assert check_body_field_consistency(bodies, [_planet_model("satellite_nacrea")]) == []


def test_consistency_check_detects_drift() -> None:
    """The three real nacrea drifts fixed in 2026-08 must all be caught."""
    bodies = [
        {"id": "planet_aegis", "albedo": 0.34},  # vs 0.343 (0.87%)
        {"id": "sat_c", "radius_km": 2840.0},  # vs 0.45 R⊕ = 2867 km (0.93%)
        {"id": "sat_v", "radius_km": 2470.0},  # vs 0.39 R⊕ = 2485 km (0.59%)
    ]
    planets = [
        _planet_model("planet_aegis", albedo=0.343),
        _planet_model("sat_c", mass=0.05, radius=0.45),
        _planet_model("sat_v", mass=0.03, radius=0.39),
    ]
    warnings = check_body_field_consistency(bodies, planets)
    assert len(warnings) == 3
    assert any("planet_aegis" in w and "albedo" in w for w in warnings)
    assert any("sat_c" in w and "radius_km" in w for w in warnings)
    assert any("sat_v" in w and "radius_km" in w for w in warnings)


def test_consistency_check_skips_bodies_absent_from_planets() -> None:
    """Bodies with no planets.yaml entry (e.g. scenery planets) are not checked."""
    bodies = [{"id": "planet_jupiter", "mass_earth": 317.8, "albedo": 0.343}]
    assert check_body_field_consistency(bodies, [_planet_model("planet_earth")]) == []


# ===================================================================
# build_system_catalog — merged stellar.yaml + planets.yaml catalog
# ===================================================================


def test_build_system_catalog_nacrea(tmp_path: Path) -> None:
    catalog, warnings = build_system_catalog(_gaia_stub(tmp_path))
    assert warnings == []

    # Stars carry computed physics + habitable zones
    (star,) = catalog["stars"]
    assert star["id"] == "star_ignis"
    assert star["luminosity_sol"] == pytest.approx(0.0414)
    assert star["temperature_k"] == pytest.approx(3931.0)
    assert "habitable_zone" in star
    assert star["habitable_zone_center_au"] == pytest.approx(0.2994, rel=1e-2)

    # Union of bodies: planet_aegis (bodies only) + satellite_nacrea (planets only)
    assert sorted(b["id"] for b in catalog["bodies"]) == ["planet_aegis", "satellite_nacrea"]
    by_id = {b["id"]: b for b in catalog["bodies"]}
    nacrea = by_id["satellite_nacrea"]
    assert nacrea["in_planets_yaml"] is True
    assert nacrea["orbit"]["period_days"] == pytest.approx(3.245, rel=1e-2)
    assert nacrea["physical"]["gravity_m_s2"] == pytest.approx(10.28, rel=1e-3)
    assert nacrea["atmosphere"]["greenhouse_factor"] == pytest.approx(62.0)
    assert nacrea["derived"]["tidally_locked"] is True
    assert nacrea["derived"]["solar_day_days"] == pytest.approx(3.42, rel=1e-2)
    assert nacrea["derived"]["in_conservative_habitable_zone"] is True
    # Calendar + instellation facts (the values nacrea docs derive by hand)
    assert nacrea["derived"]["days_per_year"] == pytest.approx(19.6, rel=1e-2)
    assert nacrea["derived"]["instellation_w_m2"] == pytest.approx(1361.0 * 0.6603, rel=1e-2)
    assert nacrea["derived"]["season_length_days"] == pytest.approx(67.0 / 4.0, rel=1e-2)
    assert nacrea["derived"]["polar_circle_latitude_deg"] == pytest.approx(81.0)
    assert nacrea["derived"]["polar_day_at_pole_days"] == pytest.approx(33.5, rel=1e-2)

    # Parent planet's heliocentric orbit is the satellite's "year" (67 Earth days)
    aegis = by_id["planet_aegis"]
    assert aegis["orbit"]["period_days"] == pytest.approx(67.0, rel=1e-2)

    # Target body is flagged for the frontend; no role-flattened duplicate
    assert catalog["target_body_id"] == "satellite_nacrea"
    assert "target_parameters" not in catalog


def test_build_system_catalog_earth_analog(tmp_path: Path) -> None:
    """Sanity: Sun/Earth analog reproduces textbook values via the catalog."""
    stellar = _write(
        tmp_path,
        "stellar.yaml",
        {
            "stars": [{"id": "star_sol", "luminosity": 1.0, "mass": 1.0, "age_gyr": 4.6}],
            "orbits": [
                {
                    "body_id": "planet_earth",
                    "parent_id": "star_sol",
                    "semi_major_axis_au": 1.0,
                    "eccentricity": 0.017,
                }
            ],
        },
    )
    planets = _write(
        tmp_path,
        "planets.yaml",
        {
            "planets": [
                {
                    "id": "planet_earth",
                    "name": "Earth",
                    "orbits": "star_sol",
                    "mass": 1.0,
                    "radius": 1.0,
                    "rotation_period_days": 0.997,
                    "axial_tilt_deg": 23.44,
                    "albedo": 0.3,
                }
            ]
        },
    )
    engine = _StubEngine({"stellar.yaml": stellar, "planets.yaml": planets})

    catalog, warnings = build_system_catalog(engine)

    assert warnings == []
    (earth,) = catalog["bodies"]
    assert earth["id"] == "planet_earth"
    assert earth["orbit"]["period_days"] == pytest.approx(365.25, rel=1e-3)
    derived = earth["derived"]
    assert derived["solar_day_days"] == pytest.approx(1.0, rel=1e-2)
    assert derived["days_per_year"] == pytest.approx(365.35, rel=1e-2)
    assert derived["instellation_w_m2"] == pytest.approx(1361.0, rel=1e-2)
    assert derived["equilibrium_temperature_k"] == pytest.approx(255.0, rel=1e-2)
    assert derived["polar_circle_latitude_deg"] == pytest.approx(66.56)


def test_build_system_catalog_warns_on_drift(tmp_path: Path) -> None:
    """Duplicated fields that diverge surface as catalog warnings."""
    stellar = dict(_GAIA_STELLAR_WITH_BODIES)
    drifted_bodies = [
        {"id": "satellite_nacrea", "mass_earth": 1.2, "albedo": 0.25}  # vs 0.30
    ]
    stellar = {**stellar, "bodies": drifted_bodies}
    stellar_file = _write(tmp_path, "stellar.yaml", stellar)
    derived = _write(
        tmp_path,
        "stellar_derived.yaml",
        {"stars": [{"id": "star_ignis", "computed_temperature": 3931.0}]},
    )
    planets = _write(tmp_path, "planets.yaml", _GAIA_PLANET_YAML)
    engine = _StubEngine(
        {"stellar.yaml": stellar_file, "stellar_derived.yaml": derived, "planets.yaml": planets}
    )

    catalog, warnings = build_system_catalog(engine)

    assert any("albedo" in w and "satellite_nacrea" in w for w in warnings)
    assert any("albedo" in w for w in catalog.get("warnings", []))


def test_build_system_catalog_without_inputs(tmp_path: Path) -> None:
    catalog, warnings = build_system_catalog(_StubEngine({}))
    assert catalog == {}
    assert any("stellar.yaml" in w for w in warnings)
