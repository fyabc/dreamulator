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
