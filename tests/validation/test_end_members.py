"""Tier 2 — solar-system end-member reproduction.

From ``docs/design/climate-validation.md`` §7.5: the most cost-effective
generalization test for an EBM-grade engine — can the physics produce the
known end states from known parameters?
"""

from __future__ import annotations

from tests.validation.conftest import build_validation_mesh, run_climate

# Venus: 0.723 AU, Bond albedo 0.75 (dense H2SO4 clouds), 92 bar CO2.
_VENUS = {
    "stellar_luminosity_sol": 1.0,
    "orbital_distance_au": 0.723,
    "albedo": 0.75,
    "greenhouse_warming_K": 500.0,
    "surface_pressure_hpa": 92.0 * 1013.25,
    "gravity_m_s2": 8.87,
    "orbital_period_days": 224.7,
    "axial_tilt_deg": 2.6,
}

# Mars: 1.524 AU, albedo 0.25, 6 mbar CO2, ~3 K greenhouse.
_MARS = {
    "stellar_luminosity_sol": 1.0,
    "orbital_distance_au": 1.524,
    "albedo": 0.25,
    "greenhouse_warming_K": 3.0,
    "surface_pressure_hpa": 6.1,
    "gravity_m_s2": 3.71,
    "orbital_period_days": 687.0,
    "axial_tilt_deg": 25.2,
}

# gaia-m: habitable-zone center of the Ignis system (see planets.yaml).
_GAIAM = {
    "stellar_luminosity_sol": 0.0357,
    "orbital_distance_au": 0.2795,
    "greenhouse_warming_K": 72.0,
    "albedo": 0.30,
    "gravity_m_s2": 10.29,
    "orbital_period_days": 80.47,
    "rotation_period_days": 3.25,
    "axial_tilt_deg": 0.0,
}


def test_venus_reproduces_runaway_state():
    stats = run_climate(build_validation_mesh(all_land=True), **_VENUS)
    # Venus surface ≈ 737 K (464 °C); engine chain gives teq ≈ 232 K + 500 K.
    # Temperature-only assertions: Köppen is undefined at runaway temperatures.
    assert stats["t_min"] > 300.0
    assert (stats["t_array"] > 50.0).all()


def test_mars_reproduces_frozen_state():
    stats = run_climate(build_validation_mesh(all_land=True), **_MARS)
    assert stats["t_mean"] < -40.0
    assert stats["t_max"] < 20.0
    # No temperate/tropical classes on a frozen Mars.
    for code in ("Cfb", "Cfa", "Af", "Aw"):
        assert code not in stats["koppen_counts"]


def test_airless_body_follows_equilibrium():
    """Zero greenhouse, low albedo → surface tracks radiative equilibrium."""
    stats = run_climate(
        build_validation_mesh(all_land=True),
        greenhouse_warming_K=0.0,
        albedo=0.1,
        # Ocean-free mesh: the SST anchor must not leak onto land cells.
    )
    from dreamulator.engine.climate_physics import equilibrium_temperature

    teq_c = equilibrium_temperature(1.0, 1.0, albedo=0.1) - 273.15
    # Land mean ≈ teq minus the latitude-gradient + lapse redistribution
    assert stats["t_land_mean"] < teq_c
    assert stats["t_land_mean"] > teq_c - 25.0


def test_gaiam_hz_center_is_not_snowball():
    """gaia-m at HZ center with Earth-equivalent GHG (78 K) must support a
    temperate regime — the world sits at the HZ center, not the inner edge.
    (Uses 78 K, the measured Earth-equivalent value, as the regime anchor.)"""
    params = dict(_GAIAM)
    params["greenhouse_warming_K"] = 78.0
    stats = run_climate(build_validation_mesh(ocean_bands=(0, 1, 10, 11)), **params)
    # Not a full snowball: global mean above freezing, warm cells survive.
    assert stats["t_mean"] > 0.0
    assert stats["t_max"] > 15.0
    # Liquid-water climate regimes (tropical or temperate) exist on land.
    habitable = [k for k in stats["koppen_counts"] if k[:1] in ("A", "C")]
    assert habitable, f"no liquid-water regimes: {stats['koppen_counts']}"
    # Ice caps must not dominate the land surface.
    land_cells = int(stats["land_mask"].sum())
    assert stats["koppen_counts"].get("EF", 0) < 0.5 * land_cells
