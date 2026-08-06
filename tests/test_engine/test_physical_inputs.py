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
    resolve_and_apply_physical_parameters,
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


# Mirrors the gaia-m system: habitable moon around a gas giant at 0.2795 AU
# around a 0.0357 L_sun / 0.4499 M_sun M-dwarf.
_GAIA_STELLAR: dict[str, Any] = {
    "stars": [{"id": "star_ignis", "luminosity": 0.0357, "mass": 0.449864}],
    "orbits": [
        {"body_id": "planet_aegis", "parent_id": "star_ignis", "semi_major_axis_au": 0.2795},
        # Satellite link — must NOT be added to the heliocentric distance
        # (eps^2 ≈ 0.03% time-averaged error; see physical_inputs docstring).
        {"body_id": "satellite_gaiam", "parent_id": "planet_aegis", "semi_major_axis_au": 0.00494},
    ],
}


def test_satellite_resolves_host_star_distance_and_period(tmp_path: Path) -> None:
    stellar = _write(tmp_path, "stellar.yaml", _GAIA_STELLAR)
    engine = _StubEngine({"stellar.yaml": stellar})
    planet = _make_planet("satellite_gaiam", "planet_aegis")

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
                    "id": "satellite_gaiam",
                    "name": "Gaia-M",
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
