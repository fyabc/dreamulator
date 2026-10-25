"""Tests for the L3 parametric cyclone templates."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from dreamulator.media import cyclone_render as cr
from dreamulator.media import cyclone_tracks as ct


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


def test_extratropical_erosion_breaks_the_shield() -> None:
    cyc = cr.Cyclone(
        lat_deg=55.0,
        lon_deg=20.0,
        kind="extratropical",
        central_pressure_hpa=975.0,
        rmax_km=450.0,
        outer_radius_km=1800.0,
        motion_east_m_s=9.0,
    )
    low = cr.cyclone_alpha(
        [cyc],
        height=128,
        width=256,
        radius_km=6800.0,
        erosion=np.full((128, 256), 0.2),
    )
    high = cr.cyclone_alpha(
        [cyc],
        height=128,
        width=256,
        radius_km=6800.0,
        erosion=np.full((128, 256), 0.9),
    )
    assert high.mean() > low.mean()
    assert np.allclose(
        high,
        cr.cyclone_alpha(
            [cyc],
            height=128,
            width=256,
            radius_km=6800.0,
            erosion=np.full((128, 256), 0.9),
        ),
    )
    try:
        cr.cyclone_alpha([cyc], height=64, width=128, radius_km=6800.0, erosion=np.zeros((10, 10)))
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched erosion shape must be rejected")


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


def test_cyclone_wind_field_direction_and_taper() -> None:
    # Grid centres: lat 20.5 / lon 0.5 are exact 1-degree grid points.
    north = cr.Cyclone(
        lat_deg=20.5,
        lon_deg=0.5,
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        rmax_km=100.0,
        outer_radius_km=1000.0,
    )
    east, northward = cr.cyclone_wind_field([north], height=180, width=360, radius_km=6800.0)
    row = 69  # lat 20.5
    centre_col = 180  # lon 0.5
    east_col = 181  # lon 1.5: ~111 km east of the centre
    # Northern-hemisphere cyclone: counter-clockwise, so the east side flows north.
    assert northward[row, east_col] > 5.0
    assert abs(east[row, east_col]) < 0.3 * northward[row, east_col]
    # North of the centre the flow is westward.
    north_row = 68  # lat 21.5
    assert east[north_row, centre_col] < -5.0
    assert abs(northward[north_row, centre_col]) < 0.3 * abs(east[north_row, centre_col])
    # Far outside the tapered outer radius the vortex contributes nothing.
    assert abs(east[row, 210]) + abs(northward[row, 210]) < 0.1
    # The axis itself has no tangential wind.
    assert abs(east[row, centre_col]) + abs(northward[row, centre_col]) < 0.1

    south = cr.Cyclone(
        lat_deg=-20.5,
        lon_deg=0.5,
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        rmax_km=100.0,
        outer_radius_km=1000.0,
    )
    east_s, north_s = cr.cyclone_wind_field([south], height=180, width=360, radius_km=6800.0)
    south_row = 110  # lat -20.5
    # Southern-hemisphere cyclone: clockwise, so the east side flows south.
    assert north_s[south_row, east_col] < -5.0


def test_extratropical_vortex_is_suppressed() -> None:
    extra = cr.Cyclone(
        lat_deg=20.5,
        lon_deg=0.5,
        kind="extratropical",
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        rmax_km=100.0,
        outer_radius_km=1000.0,
    )
    east, north = cr.cyclone_wind_field([extra], height=64, width=128, radius_km=6800.0)
    assert not np.any(east)
    assert not np.any(north)


def test_cyclone_wind_field_zero_without_deficit() -> None:
    quiet = cr.Cyclone(
        lat_deg=20.5,
        lon_deg=0.5,
        central_pressure_hpa=1010.0,
        environment_pressure_hpa=1010.0,
    )
    east, north = cr.cyclone_wind_field([quiet], height=32, width=64, radius_km=6800.0)
    assert not np.any(east)
    assert not np.any(north)


def _shortest_delta(a: float, b: float) -> float:
    return (b - a + 180.0) % 360.0 - 180.0


def test_texture_warp_rotates_with_cyclonic_sense() -> None:
    """The texture warp moves features in the same sense as the vortex wind.

    A single cloud speck due east of a northern-hemisphere storm centre must
    move toward smaller compass bearing (north-east) — counter-clockwise —
    matching the wind field's northward flow on the storm's east flank.
    """
    height, width = 360, 720
    cyc = cr.Cyclone(
        lat_deg=20.0,
        lon_deg=0.0,
        kind="tropical",
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        rmax_km=150.0,
        outer_radius_km=2000.0,
    )
    alpha = np.zeros((height, width))
    dlon = np.degrees(800.0 / (6371.0 * np.cos(np.radians(20.0))))
    row = int((90.0 - 20.0) / 180.0 * height)
    col = int((0.0 + dlon + 180.0) / 360.0 * width)
    alpha[row, col] = 1.0
    warped = cr.warp_cyclone_texture(alpha, [cyc], radius_km=6371.0)
    peak = np.unravel_index(np.argmax(warped), warped.shape)
    plat = 90.0 - peak[0] * 180.0 / height
    plon = peak[1] * 360.0 / width - 180.0
    bearing = float(np.degrees(np.arctan2(plon * np.cos(np.radians(20.0)), plat - 20.0)) % 360.0)
    assert _shortest_delta(90.0, bearing) < 0.0  # east flank curls north


def test_pattern_spin_rate_in_observed_range() -> None:
    """The rigid pattern rate must land in the observed TC rotation band.

    Satellite timelapses of mature tropical cyclones show the cloud pattern
    turning roughly 0.3–1.5 revolutions per day; the eye-wall wind turns
    several times faster, which is exactly what the rigid compositing must
    not follow.
    """
    canon = cr.Cyclone(
        lat_deg=16.2,
        lon_deg=-91.1,
        kind="tropical",
        central_pressure_hpa=911.8,
        environment_pressure_hpa=1012.0,
        rmax_km=125.2,
        outer_radius_km=1924.4,
        omega_rad_s=2.3228e-5,
    )
    rate = cr.pattern_spin_rate_rad_s(canon)
    rot_per_day = rate * 86400.0 / (2.0 * np.pi)
    assert 0.2 < rot_per_day < 1.5
    # Extratropical commas are frontal and do not rotate in this model.
    extra = cr.Cyclone(
        lat_deg=-52.9,
        lon_deg=108.7,
        kind="extratropical",
        rmax_km=1672.0,
        outer_radius_km=1840.0,
    )
    assert cr.pattern_spin_rate_rad_s(extra) == 0.0


def _ring_profile(cyc: cr.Cyclone, spin_deg: float, radius_km: float) -> np.ndarray:
    """Azimuthal alpha profile of the tropical template on one ring."""
    height, width = 512, 1024
    fbm = cr.template_fbm_stack(height, width, 41)
    spun = cr.Cyclone(**{**cyc.__dict__, "spin_deg": spin_deg})
    alpha = cr.cyclone_alpha(
        [spun], height=height, width=width, radius_km=6817.0, seed=41, fbm_stack=fbm
    )
    prof = np.zeros(360)
    for k, bearing in enumerate(np.arange(360) * 1.0):
        lat_p = cyc.lat_deg + (radius_km / 111.0) * np.cos(np.radians(bearing))
        lon_p = cyc.lon_deg + (radius_km / (111.0 * max(np.cos(np.radians(cyc.lat_deg)), 0.2)))
        lon_p = lon_p * np.sin(np.radians(bearing))
        r0 = int(round((90.0 - lat_p) / 180.0 * height)) % height
        c0 = int(round((lon_p + 180.0) / 360.0 * width)) % width
        prof[k] = alpha[r0, c0]
    return prof


def test_spin_rotates_bands_cyclonically() -> None:
    """Positive spin moves the band crests in the cyclonic sense.

    In the northern hemisphere that is counter-clockwise on the map (bearing
    decreasing); in the southern hemisphere clockwise (bearing increasing).
    """
    north = cr.Cyclone(
        lat_deg=20.0,
        lon_deg=0.0,
        kind="tropical",
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        rmax_km=800.0,
        outer_radius_km=4000.0,
        motion_east_m_s=6.0,
        motion_north_m_s=0.0,
    )
    radius_km = 2.5 * north.rmax_km
    base = _ring_profile(north, 0.0, radius_km)
    spun = _ring_profile(north, 40.0, radius_km)
    # Correlate the spun ring against the base ring shifted by -40° (north):
    # the best match should sit near the cyclonic shift, not near zero.
    errors = {
        shift: float(np.mean((spun - np.roll(base, shift)) ** 2))
        for shift in (-40, 0, 40, 140, -140, 180)
    }
    best_north = min(errors, key=errors.get)
    assert abs(best_north - (-40)) <= 45  # cyclonic, not zero or opposite

    south = cr.Cyclone(
        lat_deg=-20.0,
        lon_deg=0.0,
        kind="tropical",
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        rmax_km=800.0,
        outer_radius_km=4000.0,
        motion_east_m_s=6.0,
        motion_north_m_s=0.0,
    )
    base_s = _ring_profile(south, 0.0, radius_km)
    spun_s = _ring_profile(south, 40.0, radius_km)
    errors_s = {
        shift: float(np.mean((spun_s - np.roll(base_s, shift)) ** 2))
        for shift in (-40, 0, 40, 140, -140, 180)
    }
    best_south = min(errors_s, key=errors_s.get)
    assert abs(best_south - 40) <= 45


def test_cyclone_alpha_accepts_precomputed_fbm() -> None:
    """Injecting the fbm stack must reproduce the computed-fields result."""
    cyc = cr.Cyclone(
        lat_deg=12.0,
        lon_deg=40.0,
        kind="tropical",
        central_pressure_hpa=960.0,
        environment_pressure_hpa=1010.0,
        rmax_km=200.0,
        outer_radius_km=1500.0,
    )
    default = cr.cyclone_alpha([cyc], height=128, width=256, radius_km=6817.0, seed=41)
    fbm = cr.template_fbm_stack(128, 256, 41)
    injected = cr.cyclone_alpha(
        [cyc], height=128, width=256, radius_km=6817.0, seed=41, fbm_stack=fbm
    )
    np.testing.assert_array_equal(default, injected)


def test_holland_wind_is_planet_aware() -> None:
    """A slower planet weakens the Coriolis correction, so V rises slightly.

    v = sqrt(c² + (rf/2)²) − rf/2 with the cyclostrophic part c: smaller f
    moves v toward c from below wherever c > 0.
    """
    args: dict[str, Any] = dict(
        rmax_km=120.0,
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        lat_deg=45.0,
    )
    r = np.array([60.0, 120.0, 300.0])
    earth = cr.holland_wind_m_s(r, **args)
    slow = cr.holland_wind_m_s(r, omega=7.292115e-5 / 3.0, **args)
    assert np.all(slow > earth)


def test_coherent_shield_limited_by_ambient_shear() -> None:
    """A flat ambient wind admits the maximum shield; a westerly ramp clips it.

    The shield solver's physical claim: where the ambient wind difference
    across the storm exceeds the storm's own tangential wind, the cloud
    pattern belongs to the environment, not the vortex.
    """
    lat = np.arange(-89.5, 90.0, 2.8)
    args: dict[str, Any] = dict(
        rmax_km=125.0,
        central_pressure_hpa=945.0,
        environment_pressure_hpa=1012.0,
        lat_deg=16.0,
        omega_rad_s=7.292115e-5 / 3.0,
        radius_km=6817.0,
    )
    flat = ct.coherent_shield_km(wind_lat=lat, wind_m_s=np.zeros_like(lat), **args)
    assert flat == ct.SHIELD_HI_KM
    # 1.2 m/s per degree ≈ the nacrea subtropical westerly ramp: ~20 m/s
    # difference across a 1000 km shield.
    ramp = ct.coherent_shield_km(wind_lat=lat, wind_m_s=1.2 * lat, **args)
    assert ct.SHIELD_LO_KM <= ramp < ct.SHIELD_HI_KM


def test_plume_extends_downwind() -> None:
    """A plume-bearing storm brightens downwind of the core, not upwind."""
    cyc = cr.Cyclone(
        lat_deg=16.0,
        lon_deg=0.0,
        kind="tropical",
        central_pressure_hpa=950.0,
        environment_pressure_hpa=1010.0,
        rmax_km=200.0,
        outer_radius_km=600.0,
        plume_km=2500.0,
        plume_bearing_deg=90.0,
    )
    alpha = cr.cyclone_alpha([cyc], height=256, width=512, radius_km=6817.0, seed=41)
    lat = 90.0 - (np.arange(256) + 0.5) / 256 * 180.0
    lon = (np.arange(512) + 0.5) / 512 * 360.0 - 180.0
    row = int(np.argmin(np.abs(lat - 16.0)))
    col = int(np.argmin(np.abs(lon - 0.0)))
    # 10–30 px ≈ 7–21° ≈ 0.8–2.4 Mm downwind along the plume axis.
    east = alpha[row - 6 : row + 6, col + 10 : col + 30].mean()
    west = alpha[row - 6 : row + 6, col - 30 : col - 10].mean()
    assert east > west + 0.05
    # The envelope follows the plume, so the deck blends toward it downwind.
    env = cr.cyclone_envelope([cyc], height=256, width=512, radius_km=6817.0, seed=41)
    east_env = env[row - 6 : row + 6, col + 10 : col + 30].mean()
    west_env = env[row - 6 : row + 6, col - 30 : col - 10].mean()
    assert east_env > west_env


def test_gyre_and_hurricane_are_different_regimes() -> None:
    """A broad shield in calm air draws a looser spiral and shallower eye.

    Same shape seed, so the only difference is the regime carried by the
    environment fields (plume length and shield size).
    """
    gyre = cr.Cyclone(
        lat_deg=12.0,
        lon_deg=0.0,
        kind="tropical",
        central_pressure_hpa=985.0,
        environment_pressure_hpa=1010.0,
        rmax_km=300.0,
        outer_radius_km=1400.0,
        plume_km=0.0,
        shape_seed=77,
    )
    hurricane = replace(gyre, outer_radius_km=600.0, plume_km=1500.0)
    g = cr._shape_of(gyre)
    h = cr._shape_of(hurricane)
    assert g.band_pitch < h.band_pitch
    assert g.eye_fraction < h.eye_fraction


class _StubPack:
    """Minimal pack surface for ``cyclones_at_frame`` (tracks + calendar)."""

    def __init__(self, tracks: list[dict[str, Any]]) -> None:
        self.tracks = tracks
        self.meta: dict[str, Any] = {"calendar": {"sidereal_day_h": 75.2}}


def _track(tid: int, lat: float, rmax_km: float) -> dict[str, Any]:
    point = {
        "frame": 0.0,
        "lat": lat,
        "lon": 100.0,
        "psl_hpa": 975.0,
        "environment_hpa": 1010.0,
        "rmax_km": rmax_km,
        "outer_radius_km": 1200.0,
        "motion_east_m_s": 8.0,
        "motion_north_m_s": 0.0,
    }
    return {
        "id": tid,
        "kind": "extratropical",
        "stationary": False,
        "points": [point, {**point, "frame": 100.0}],
    }


def test_extratropical_gates_skip_circumpolar_detections() -> None:
    """Polar or wave-trough-scale detections are not storms; mid-latitude ones pass."""
    pack = _StubPack(
        [
            _track(1, -84.6, 400.0),  # polar vortex edge
            _track(2, -52.9, 1700.0),  # planetary-wave trough scale
            _track(3, -52.9, 500.0),  # a plausible frontal cyclone
        ]
    )
    kept = ct.cyclones_at_frame(pack, 10.0)
    assert [c.lat_deg for c in kept] == [-52.9]
    # The passing storm carries the pack's rotation rate.
    assert abs(kept[0].omega_rad_s - 2 * np.pi / (75.2 * 3600.0)) < 1e-12


def test_extratropical_deficit_fades_at_life_edges() -> None:
    """A track's cloud must grow in and dissolve out, not pop at full amplitude."""
    pack = _StubPack([_track(3, -52.9, 500.0)])
    mid = ct.cyclones_at_frame(pack, 10.0)[0]
    edge = ct.cyclones_at_frame(pack, 0.25)[0]
    assert mid.deficit_hpa == 35.0
    # Frame 0.25 of a 6-h frame cadence: 1.5 h into life → deficit ≈ 25%.
    assert 0.2 * 35.0 < edge.deficit_hpa < 0.3 * 35.0


class _FieldPack:
    """Minimal pack surface for ``TropicalCycloneSource`` (fields + calendar)."""

    def __init__(self, frames: int = 4) -> None:
        self.lat = np.arange(-86.4, 90.0, 2.8125 * 2)
        self.lon = np.arange(1.40625, 360.0, 2.8125)
        nlat, nlon = self.lat.size, self.lon.size
        self._u = np.broadcast_to(
            np.arange(frames, dtype=float)[:, None, None], (frames, nlat, nlon)
        ).copy()
        self._v = -self._u
        self.meta: dict[str, Any] = {
            "frames": frames,
            "calendar": {"sidereal_day_h": 75.2, "frame_interval_h": 6.0},
            "time": {"hours_since_start": [6.0 * k for k in range(frames)], "orbital_phase": None},
        }

    def field(self, name: str) -> np.ndarray:
        if name == "u_mid" or name == "u_high":
            return self._u
        if name == "v_mid" or name == "v_high":
            return self._v
        shape = (self.meta["frames"], self.lat.size, self.lon.size)
        if name == "tc_genesis_potential":
            return np.ones(shape)
        return np.zeros(shape)


def test_wind_at_interpolates_between_pack_frames() -> None:
    """Fractional frames must blend the bracketing 6-h snapshots.

    Snapping to the nearest frame steps the steering wind and the plume
    length once per pack frame — the jumping cloud stripe of user QA.
    """
    src = ct.TropicalCycloneSource(_FieldPack(), seed=1, radius_km=6817.0)
    u, v = src._wind_at(1.5, 0.0, 10.0, "u_mid", "v_mid")
    assert u == 1.5 and v == -1.5
    u0, v0 = src._wind_at(1.0, 0.0, 10.0, "u_mid", "v_mid")
    assert u0 == 1.0 and v0 == -1.0


def test_ocean_mask_gates_genesis() -> None:
    """All-land mask → zero genesis weight → no tropical storms at any frame."""
    pack = _FieldPack()
    nlat, nlon = pack.lat.size, pack.lon.size
    src = ct.TropicalCycloneSource(
        pack, seed=1, radius_km=6817.0, ocean_fraction=np.zeros((nlat, nlon))
    )
    assert src.genesis == []
    try:
        ct.TropicalCycloneSource(pack, seed=1, ocean_fraction=np.zeros((3, 4)))
    except ValueError:
        pass
    else:
        raise AssertionError("mask shape mismatch must be rejected")
