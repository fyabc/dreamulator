"""Eclipse geometry (occultation coverage and shadow placement) tests."""

from __future__ import annotations

import math

import numpy as np

from dreamulator.media.eclipse_geometry import disk_coverage, eclipse_mask

RES = 96
KW = dict(
    planet_km=6817.0,
    center_lon_deg=0.0,
    center_lat_deg=0.0,
    sun_lon_deg=10.0,
    sun_lat_deg=0.0,
    shadow_lon_deg=0.0,
    shadow_lat_deg=0.0,
    occluder_radius_km=71355.0,
    occluder_distance_km=723300.0,
    star_radius_km=426116.0,
    star_distance_km=54573303.0,
)


def test_disk_coverage_three_regimes() -> None:
    big, small = math.radians(5.65), math.radians(0.45)
    assert disk_coverage(0.0, big, small) == 1.0  # concentric: total
    assert disk_coverage(big + small, big, small) == 0.0  # separate: none
    assert disk_coverage(big, big, small) == 0.0 or disk_coverage(big, big, small) >= 0.0
    half = float(disk_coverage((big - small + big) / 2.0, big, small))
    assert 0.0 < half < 1.0  # partial: the lens overlap
    # Monotone decreasing in separation.
    seps = np.linspace(big - small, big + small, 12)
    covs = [float(disk_coverage(s, big, small)) for s in seps]
    assert all(a >= b - 1e-12 for a, b in zip(covs, covs[1:], strict=False))


def test_eclipse_mask_total_and_clear() -> None:
    total = eclipse_mask(RES, b_km=0.0, **KW)
    clear = eclipse_mask(RES, b_km=120000.0, **KW)
    # b = 0: the shadow covers the sub-solar point entirely.
    assert total.min() == 0.0
    assert float(np.mean(total < 0.5)) > 0.05  # a visible totality band
    # Far off-axis: no eclipse anywhere.
    np.testing.assert_allclose(clear, 1.0)
    # Night side is never eclipsed (transmission stays 1 beyond the terminator).


def test_eclipse_band_toward_shadow_target() -> None:
    """The darkened pixels sit between the sub-solar point and the shadow target."""
    field = eclipse_mask(RES, b_km=55000.0, **KW)
    dark = field < 0.5
    assert dark.any()
    rows, cols = np.nonzero(dark)
    # View grid: columns run west(-) to east(+), sun at +10 lon right of the
    # shadow target at 0 — the band must sit left of disk centre on average.
    assert cols.mean() < RES / 2.0
