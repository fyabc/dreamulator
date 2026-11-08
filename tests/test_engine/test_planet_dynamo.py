"""Unit tests for the gas-giant dynamo estimate (engine/planet_dynamo.py).

Anchors: Jupiter-anchored ratio form returns the anchor exactly for Jupiter
inputs; the literature cross-check (5 M_Jup at 1 Gyr ~ 5-12x Jupiter in
Christensen et al. 2009) lands on the documented low side (~3.7x) because the
single-point anchor omits dynamo-depth variation; the dipole chain reproduces
nacrea's hand-derived numbers (coupled_magnetic.md).
"""

from __future__ import annotations

import math

import pytest

from dreamulator.engine.planet_dynamo import (
    JUPITER_EQ_DIPOLE_UT,
    JUPITER_MASS_EARTH,
    JUPITER_RADIUS_KM,
    dipole_field_at_distance_ut,
    dipole_moment_am2,
    estimate_intrinsic_luminosity_w,
    estimate_magnetic_field_ut,
)


def test_jupiter_anchor_is_exact() -> None:
    """Table-consistent Jupiter inputs reproduce the 428 uT anchor exactly."""
    assert estimate_magnetic_field_ut(JUPITER_MASS_EARTH, JUPITER_RADIUS_KM, 5.0) == pytest.approx(
        JUPITER_EQ_DIPOLE_UT, rel=1e-12
    )


def test_authored_luminosity_overrides_table() -> None:
    """An authored luminosity replaces the table track for the ratio."""
    table_l = estimate_intrinsic_luminosity_w(508.5 / JUPITER_MASS_EARTH, 5.9)
    with_table = estimate_magnetic_field_ut(508.5, 71355.0, 5.9)
    with_author = estimate_magnetic_field_ut(508.5, 71355.0, 5.9, luminosity_w=table_l)
    assert with_table == pytest.approx(with_author, rel=1e-12)


def test_literature_crosscheck_5mj_young() -> None:
    """5 M_Jup at 1 Gyr: paper says 5-12x Jupiter; anchor runs ~1.5x low."""
    b = estimate_magnetic_field_ut(5.0 * JUPITER_MASS_EARTH, JUPITER_RADIUS_KM, 1.0)
    ratio = b / JUPITER_EQ_DIPOLE_UT
    assert 3.0 < ratio < 5.0


def test_grid_monotonicity() -> None:
    """At fixed age, luminosity rises with mass; at fixed mass it falls with age."""
    for age in (0.1, 1.0, 10.0):
        assert estimate_intrinsic_luminosity_w(5.0, age) > estimate_intrinsic_luminosity_w(1.0, age)
    for mass in (0.5, 1.0, 5.0):
        assert estimate_intrinsic_luminosity_w(mass, 0.5) > estimate_intrinsic_luminosity_w(
            mass, 5.0
        )


def test_grid_edge_clamping_is_finite() -> None:
    """Masses/ages outside the digitized grid clamp to the nearest edge."""
    assert math.isfinite(estimate_intrinsic_luminosity_w(0.01, 0.01))
    assert math.isfinite(estimate_magnetic_field_ut(0.01, 70000.0, 50.0))
    # A 1 M_Jup body at 50 Gyr clamps to the 10 Gyr edge: luminosity ratio 1,
    # so the estimate is just the radius term.
    assert estimate_magnetic_field_ut(JUPITER_MASS_EARTH, JUPITER_RADIUS_KM, 50.0) == pytest.approx(
        JUPITER_EQ_DIPOLE_UT
    )


def test_dipole_chain_matches_nacrea_hand_derivation() -> None:
    """400 uT at 71,355 km -> 1.453e27 A m^2; at 723,300 km -> 0.384 uT."""
    moment = dipole_moment_am2(400.0, 71355.0)
    assert moment == pytest.approx(1.453e27, rel=1e-3)
    assert dipole_field_at_distance_ut(400.0, 71355.0, 723300.0) == pytest.approx(0.384, rel=1e-3)
    # r^-3 falloff sanity: field at 2 radii is 1/8 of the surface value.
    assert dipole_field_at_distance_ut(400.0, 71355.0, 2 * 71355.0) == pytest.approx(50.0)
