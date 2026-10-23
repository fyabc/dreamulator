"""Weather layer pack helpers and cyclone tracking (dreamulator.gcm.weather_pack / cyclones)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from dreamulator.gcm.cyclones import DetectionParams, GridGeometry, detect_candidates, stitch_tracks
from dreamulator.gcm.weather_pack import (
    R_DRY_J_KG_K,
    cloud_top,
    hypsometric_heights,
    subsolar_point,
)

LAT = np.linspace(-88.6, 88.6, 64)
LON = np.arange(128) * 360.0 / 128
RADIUS_KM = 6817.0


def _low(lat0: float, lon0: float, depth: float = 15.0, width_km: float = 800.0) -> np.ndarray:
    geom = GridGeometry(LAT, LON, RADIUS_KM)
    j = int(np.argmin(abs(LAT - lat0)))
    i = int(np.argmin(abs(LON - lon0)))
    d = geom.distance_km(j, i)
    return 1013.0 - depth * np.exp(-((d / width_km) ** 2))


def test_cloud_top_weights_the_highest_visible_layer() -> None:
    cl = np.zeros((3, 1, 1))
    cl[:, 0, 0] = [0.5, 0.0, 1.0]  # half-covering cirrus over an overcast low deck
    p = np.array([200.0, 500.0, 900.0])[:, None, None]
    ctp, cth = cloud_top(cl, p, p / 100.0)
    assert ctp[0, 0] == pytest.approx(0.5 * 200 + 0.5 * 900)
    assert cth[0, 0] == pytest.approx(5.5)
    clear, _ = cloud_top(np.zeros((3, 1, 1)), p, p)
    assert np.isnan(clear[0, 0])


def test_hypsometric_heights_of_an_isothermal_column() -> None:
    sigma_half = np.array([0.1, 0.5, 1.0])
    ta = np.full((2, 1, 1), 250.0)
    full, half = hypsometric_heights(ta, sigma_half, np.zeros((1, 1)), 10.0)
    scale = R_DRY_J_KG_K * 250.0 / 10.0
    assert half[0, 0, 0] == pytest.approx(scale * math.log(10.0))
    assert half[1, 0, 0] == pytest.approx(scale * math.log(2.0))
    assert full[1, 0, 0] == pytest.approx(scale * math.log(1.0 / math.sqrt(0.5)))


def test_subsolar_point_tracks_the_zenith_maximum() -> None:
    la, lo = np.meshgrid(np.radians(LAT), np.radians(LON), indexing="ij")
    s_lat, s_lon = math.radians(12.0), math.radians(200.0)
    czen = np.sin(la) * math.sin(s_lat) + np.cos(la) * math.cos(s_lat) * np.cos(lo - s_lon)
    lat, lon = subsolar_point(czen, LAT, LON)
    assert lat == pytest.approx(12.0, abs=0.3)
    assert lon == pytest.approx(200.0, abs=0.3)


def test_detect_finds_a_closed_low_and_rejects_terrain_and_anticyclonic_vorticity() -> None:
    geom = GridGeometry(LAT, LON, RADIUS_KM)
    params = DetectionParams(rotation_scale=1.0)
    psl = _low(45.0, 100.0)
    wind = np.full_like(psl, 5.0)
    found = detect_candidates(psl, wind, None, geom, params)
    assert len(found) == 1
    assert found[0].lat == pytest.approx(45.0, abs=2.0) and found[0].lon == pytest.approx(
        100, abs=2
    )
    assert found[0].environment_hpa > found[0].psl_hpa
    high = np.zeros_like(psl)
    high[np.unravel_index(np.argmin(psl), psl.shape)] = 3000.0
    assert not detect_candidates(psl, wind, None, geom, params, surface_height_m=high)
    anticyclonic = np.full_like(psl, -1e-4)
    assert not detect_candidates(psl, wind, None, geom, params, vorticity_s=anticyclonic)


def test_detect_skips_a_low_without_a_closed_contour() -> None:
    geom = GridGeometry(LAT, LON, RADIUS_KM)
    shallow = _low(45.0, 100.0, depth=1.0)
    assert not detect_candidates(shallow, np.zeros_like(shallow), None, geom, DetectionParams())


def test_stitch_links_a_moving_low_and_measures_its_motion() -> None:
    geom = GridGeometry(LAT, LON, RADIUS_KM)
    params = DetectionParams(rotation_scale=1.0)
    hours = np.arange(0.0, 96.0, 6.0)
    frames = [
        detect_candidates(_low(45.0, 100.0 + 1.5 * k), np.zeros((64, 128)), None, geom, params)
        for k in range(hours.size)
    ]
    tracks = stitch_tracks(frames, hours, params, RADIUS_KM)
    assert len(tracks) == 1 and tracks[0].kind == "extratropical"
    assert not tracks[0].stationary  # moved 22.5° of longitude
    assert len(tracks[0].points) == hours.size
    east = np.median([p.motion_east_m_s for p in tracks[0].points])
    expected = math.radians(1.5) * math.cos(math.radians(45.0)) * RADIUS_KM * 1000 / (6 * 3600)
    assert east == pytest.approx(expected, rel=0.35)
    short = stitch_tracks(frames[:3], hours[:3], params, RADIUS_KM)
    assert short == []  # shorter than the minimum lifetime
