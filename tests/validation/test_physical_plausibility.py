"""Tier 3 — physical plausibility / monotonicity assertions.

From ``docs/design/climate-validation.md`` §7.4: pure-theory tests that
require no reference dataset. Passing tests guard the current behavior;
xfail tests document physics the engine does not yet implement (they flip
to XPASS — loudly — when the physics lands).
"""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.engine.climate_physics import (
    equilibrium_temperature,
    latitude_temperature,
    seasonal_temperature,
)
from tests.validation.conftest import build_validation_mesh, run_climate


def test_temperature_rises_with_luminosity():
    low = run_climate(build_validation_mesh(), stellar_luminosity_sol=0.5)
    high = run_climate(build_validation_mesh(), stellar_luminosity_sol=1.5)
    assert high["t_mean"] > low["t_mean"] + 5.0


def test_temperature_rises_with_greenhouse():
    t0 = run_climate(build_validation_mesh(), greenhouse_warming_K=0.0)["t_mean"]
    t33 = run_climate(build_validation_mesh(), greenhouse_warming_K=33.0)["t_mean"]
    t80 = run_climate(build_validation_mesh(), greenhouse_warming_K=80.0)["t_mean"]
    assert t33 > t0
    assert t80 > t33


def test_temperature_falls_with_albedo():
    dark = run_climate(build_validation_mesh(), albedo=0.1)
    bright = run_climate(build_validation_mesh(), albedo=0.6)
    assert bright["t_mean"] < dark["t_mean"]


def test_no_atmosphere_limit_matches_equilibrium():
    """With zero greenhouse warming, land temperature follows the EBM chain:
    t_eq → latitude gradient. Wiring check against the same pure functions."""
    mesh = build_validation_mesh(all_land=True)
    for cell in mesh.cells:
        cell.elevation = 0.0  # isolate the latitude-gradient wiring
    stats = run_climate(mesh, greenhouse_warming_K=0.0, albedo=0.306)

    teq = equilibrium_temperature(1.0, 1.0, albedo=0.306)
    lat_rad = np.radians(np.array([c.lat for c in mesh.cells]))
    expected = latitude_temperature(teq - 273.15, lat_rad, 40.0)
    assert np.allclose(stats["t_array"], expected, atol=1.0)


def test_high_obliquity_widens_seasonal_range():
    """Annual temperature range grows with axial tilt (seasonal amplitude ∝ √sin ε)."""
    mesh = build_validation_mesh()
    lat_rad = np.radians(np.array([c.lat for c in mesh.cells]))
    t0 = seasonal_temperature(np.zeros(len(lat_rad)), lat_rad, axial_tilt_deg=0.0)
    t45 = seasonal_temperature(np.zeros(len(lat_rad)), lat_rad, axial_tilt_deg=45.0)
    assert t45["annual_range"].max() > t0["annual_range"].max() + 5.0


# --- Known gaps: expected failures until the physics is implemented --------


@pytest.mark.xfail(reason="Engine has no ice-albedo feedback; no bistability yet", strict=False)
def test_ice_albedo_bistability():
    """A perturbed cold start should stay cold (Snowball branch)."""
    raise AssertionError("not implemented in engine")


@pytest.mark.xfail(reason="Annual mean is obliquity-independent in current model", strict=False)
def test_high_obliquity_warms_poles_annually():
    raise AssertionError("not implemented in engine")


@pytest.mark.xfail(reason="Hadley width hardcoded at 30°; pending 3A.6", strict=False)
def test_hadley_width_depends_on_rotation():
    raise AssertionError("not implemented in engine (climate-engine.md Phase 3A.6)")
