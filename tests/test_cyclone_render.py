"""Tests for the L3 parametric cyclone templates."""

from __future__ import annotations

import numpy as np

from dreamulator.media import cyclone_render as cr


def test_holland_profile_peaks_near_rmax() -> None:
    r = np.array([30.0, 120.0, 600.0, 2000.0])
    v = cr.holland_wind_m_s(
        r,
        rmax_km=120.0,
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        lat_deg=15.0,
    )
    assert v.shape == r.shape
    assert np.all(v >= 0.0)
    # Maximum wind is at (or very near) Rmax, not on the axis or far outside.
    assert v[1] > v[0]
    assert v[1] > v[2]
    # A deeper deficit drives a stronger storm.
    weak = cr.holland_wind_m_s(
        r,
        rmax_km=120.0,
        central_pressure_hpa=990.0,
        environment_pressure_hpa=1010.0,
        lat_deg=15.0,
    )
    assert np.all(v >= weak)


def test_holland_b_from_pressure_and_wind() -> None:
    b = cr.holland_b_1980(50.0, central_pressure_hpa=950.0, environment_pressure_hpa=1010.0)
    assert 1.0 <= b <= 2.5
    # A stronger storm at the same deficit has a larger B.
    b_strong = cr.holland_b_1980(70.0, central_pressure_hpa=950.0, environment_pressure_hpa=1010.0)
    assert b_strong > b
    # No pressure deficit → the lower clip.
    assert (
        cr.holland_b_1980(50.0, central_pressure_hpa=1010.0, environment_pressure_hpa=1010.0) == 1.0
    )


def test_tropical_eye_and_eyewall() -> None:
    cyc = cr.Cyclone(
        lat_deg=15.0,
        lon_deg=90.0,
        central_pressure_hpa=950.0,
        rmax_km=600.0,
        outer_radius_km=2400.0,
    )
    alpha = cr.cyclone_alpha([cyc], height=256, width=512, radius_km=6800.0)
    lat = 90.0 - (np.arange(256) + 0.5) / 256 * 180.0
    lon = (np.arange(512) + 0.5) / 512 * 360.0 - 180.0
    row = int(np.argmin(np.abs(lat - 15.0)))
    col = int(np.argmin(np.abs(lon - 90.0)))
    eye = alpha[row, col]
    # One grid row north of the centre is roughly Rmax (0.70° ≈ 78 km at 256 rows).
    eyewall_row = int(np.argmin(np.abs(lat - (15.0 + 600.0 / 111.2))))
    eyewall = alpha[eyewall_row, col]
    assert eye < 0.05
    assert eyewall > 0.3
    # Far from the storm the template vanishes.
    assert alpha[0, 0] < 0.02


def test_envelope_peaks_at_centre() -> None:
    cyc = cr.Cyclone(
        lat_deg=15.0,
        lon_deg=90.0,
        central_pressure_hpa=950.0,
        rmax_km=600.0,
        outer_radius_km=2400.0,
    )
    env = cr.cyclone_envelope([cyc], height=256, width=512, radius_km=6800.0)
    lat = 90.0 - (np.arange(256) + 0.5) / 256 * 180.0
    lon = (np.arange(512) + 0.5) / 512 * 360.0 - 180.0
    row = int(np.argmin(np.abs(lat - 15.0)))
    col = int(np.argmin(np.abs(lon - 90.0)))
    assert env[row, col] > 0.9
    assert env[0, 0] < 0.05


def test_eye_clear_mask() -> None:
    cyc = cr.Cyclone(
        lat_deg=15.0,
        lon_deg=90.0,
        central_pressure_hpa=950.0,
        rmax_km=600.0,
        outer_radius_km=2400.0,
    )
    clear = cr.cyclone_clear([cyc], height=256, width=512, radius_km=6800.0)
    lat = 90.0 - (np.arange(256) + 0.5) / 256 * 180.0
    lon = (np.arange(512) + 0.5) / 512 * 360.0 - 180.0
    row = int(np.argmin(np.abs(lat - 15.0)))
    col = int(np.argmin(np.abs(lon - 90.0)))
    assert clear[row, col] > 0.8
    assert clear[0, 0] < 0.05


def test_extratropical_comma_deterministic() -> None:
    cyc = cr.Cyclone(
        lat_deg=55.0,
        lon_deg=20.0,
        kind="extratropical",
        central_pressure_hpa=975.0,
        rmax_km=450.0,
        outer_radius_km=1800.0,
        motion_east_m_s=9.0,
    )
    a1 = cr.cyclone_alpha([cyc], height=128, width=256, radius_km=6800.0)
    a2 = cr.cyclone_alpha([cyc], height=128, width=256, radius_km=6800.0)
    np.testing.assert_array_equal(a1, a2)
    assert a1.max() > 0.2
    assert np.all((a1 >= 0.0) & (a1 <= 1.0))


def test_composite_alpha_screen() -> None:
    base = np.array([0.0, 0.5, 1.0])
    template = np.array([0.0, 0.0, 0.5])
    out = cr.composite_alpha(base, template)
    np.testing.assert_allclose(out, [0.0, 0.5, 1.0])
    mixed = cr.composite_alpha(np.array([0.5]), np.array([0.5]))[0]
    assert 0.5 < mixed <= 1.0


def test_synthetic_tracks_bands_and_seed() -> None:
    tracks = cr.synthetic_cyclones(11)
    assert len(tracks) == 6
    tropical = [c for c in tracks if c.kind == "tropical"]
    extra = [c for c in tracks if c.kind == "extratropical"]
    assert len(tropical) == 2 and len(extra) == 4
    assert all(10.0 <= abs(c.lat_deg) <= 25.0 for c in tropical)
    assert all(52.0 <= abs(c.lat_deg) <= 58.0 for c in extra)
    assert tracks == cr.synthetic_cyclones(11)
    assert tracks != cr.synthetic_cyclones(12)


def test_warp_cyclone_texture_local_and_deterministic() -> None:
    h, w = 128, 256
    yy, xx = np.mgrid[0:h, 0:w]
    base = ((np.sin(xx / 9.0) + np.cos(yy / 7.0)) * 0.25 + 0.5).astype(np.float64)
    cyc = cr.Cyclone(lat_deg=0.0, lon_deg=0.0, rmax_km=120.0, outer_radius_km=2000.0)
    out1 = cr.warp_cyclone_texture(base, [cyc], radius_km=6800.0)
    out2 = cr.warp_cyclone_texture(base, [cyc], radius_km=6800.0)
    np.testing.assert_array_equal(out1, out2)
    assert out1.shape == base.shape
    # The warp is local: the far corner is untouched.
    assert out1[0, 0] == base[0, 0]
    # Inside the storm footprint the field is reorganised.
    assert not np.allclose(out1, base)


def test_empty_track_set_is_zero() -> None:
    out = cr.cyclone_alpha([], height=16, width=32, radius_km=6800.0)
    assert out.shape == (16, 32)
    assert not out.any()
