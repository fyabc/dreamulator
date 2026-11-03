"""Sky-background framework tests: pure derivation + model validation.

The framework's contract is determinism (seeded starfield reproduces exactly),
the planetarium split (static directions + magnitudes, frozen as unit vectors),
and the hybrid magnitude input (authored magnitude, or luminosity + distance).
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from dreamulator.engine.sky_background import (
    derive_sky_background,
    derive_star,
    generate_starfield,
    magnitude_from_luminosity,
    unit_vector_ecliptic,
)
from dreamulator.models.sky_background import (
    BackgroundStar,
    SkyBackgroundInput,
    StarfieldSpec,
    StarVariability,
    WanderingObject,
)


def test_unit_vector_from_ecliptic_angles() -> None:
    x, y, z = unit_vector_ecliptic(90.0, 0.0)
    assert (x, y, z) == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)
    pole = unit_vector_ecliptic(0.0, 90.0)
    assert pole == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)
    vec = unit_vector_ecliptic(321.5, 55.1)
    assert math.hypot(*vec) == pytest.approx(1.0, abs=1e-12)


def test_magnitude_from_luminosity_matches_hand_value() -> None:
    # 210 L_sun at 148 pc: M = 4.74 - 2.5*log10(210) = -1.07; m = M + 5*log10(148) - 5
    expected = 4.74 - 2.5 * math.log10(210.0) + 5 * math.log10(148.0) - 5
    assert magnitude_from_luminosity(210.0, 148.0) == pytest.approx(expected, abs=1e-9)
    assert magnitude_from_luminosity(210.0, 148.0) == pytest.approx(4.78, abs=0.01)


def test_starfield_is_seeded_and_bounded() -> None:
    spec = StarfieldSpec(seed=7, count=120, magnitude_limit=6.5)
    first = generate_starfield(spec)
    second = generate_starfield(spec)
    assert first == second  # reproducibility discipline
    other = generate_starfield(StarfieldSpec(seed=8, count=120, magnitude_limit=6.5))
    assert other != first
    assert len(first) == 120
    for star in first:
        assert 0.0 <= star.magnitude <= 6.5
        assert math.hypot(*star.unit) == pytest.approx(1.0, abs=1e-3)  # rounded to 1e-6
        assert star.source == "starfield"
    assert generate_starfield(StarfieldSpec(seed=1, count=0)) == []


def test_background_star_requires_a_magnitude_route() -> None:
    with pytest.raises(ValidationError):
        BackgroundStar(id="s", ecliptic_lon_deg=1.0, ecliptic_lat_deg=1.0)
    with pytest.raises(ValidationError):
        BackgroundStar(id="s", ecliptic_lon_deg=1.0, ecliptic_lat_deg=1.0, luminosity_sol=2.0)
    star = BackgroundStar(
        id="s", ecliptic_lon_deg=1.0, ecliptic_lat_deg=1.0, luminosity_sol=2.0, distance_pc=10.0
    )
    assert derive_star(star).source == "authored"


def test_variability_round_trip_and_validation() -> None:
    star = BackgroundStar(
        id="v",
        ecliptic_lon_deg=1.0,
        ecliptic_lat_deg=1.0,
        magnitude=-0.7,
        temperature_k=18000.0,
        variability=StarVariability(
            type="gamma_cassiopeiae",
            magnitude_range=(-1.3, -0.3),  # irregular: no period
        ),
    )
    derived = derive_star(star)
    assert derived.variability is not None
    assert derived.variability.magnitude_range == (-1.3, -0.3)
    assert derived.variability.period_days is None
    with pytest.raises(ValidationError):
        StarVariability(type="x", magnitude_range=(-0.3, -1.3))  # reversed bounds
    # procedural field stars never carry variability
    assert all(s.variability is None for s in generate_starfield(StarfieldSpec(seed=1, count=2)))


def test_wandering_objects_round_trip() -> None:
    source = SkyBackgroundInput(
        wandering_objects=[
            WanderingObject(
                id="w1",
                name="IDS J201.3-34.8",
                object_type="m_dwarf_binary",
                ecliptic_lon_deg=201.3,
                ecliptic_lat_deg=-34.8,
                distance_pc=24.0,
                magnitude=9.3,
                close_approach_au=68000.0,
                encounter_age_myr=92.0,
            )
        ],
    )
    derived = derive_sky_background(source)
    (w,) = derived.wandering_objects
    assert math.hypot(*w.unit[:2]) > 0
    assert w.close_approach_au == 68000.0
    assert w.encounter_age_myr == 92.0
    assert w.magnitude == 9.3  # naked-eye invisible: the sky view never renders these


def test_derive_merges_authored_and_procedural_stars() -> None:
    source = SkyBackgroundInput(
        starfield=StarfieldSpec(seed=3, count=5, magnitude_limit=6.0),
        stars=[
            BackgroundStar(
                id="named",
                ecliptic_lon_deg=10.0,
                ecliptic_lat_deg=20.0,
                magnitude=1.5,
                temperature_k=5000.0,
            )
        ],
    )
    derived = derive_sky_background(source)
    assert len(derived.stars) == 6
    assert derived.stars[0].id == "named"
    assert derived.stars[0].source == "authored"
    assert all(s.source == "starfield" for s in derived.stars[1:])
    assert derived.galactic_band is None
    assert derived.transient_events == []
