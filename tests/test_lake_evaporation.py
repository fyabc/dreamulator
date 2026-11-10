"""Energy-based open-water evaporation: physics, terminal-lake verdict, canvas channel."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.engine import lake_evaporation as le

if TYPE_CHECKING:
    from pathlib import Path

WARM = np.full((1, 12), 20.0)
SUN = np.full((1, 12), 400.0)


def _annual(t=WARM, q=SUN, cloud=0.4, z=0.0) -> float:
    return float(le.open_water_evaporation(t, q, np.array([cloud]), np.array([z]))[0])


def test_annual_is_the_sum_of_the_months() -> None:
    monthly = le.open_water_evaporation_monthly(WARM, SUN, np.array([0.4]), np.array([0.0]))
    assert monthly.shape == (1, 12)
    assert _annual() == pytest.approx(float(monthly.sum()))


def test_magnitude_is_lake_like() -> None:
    # a warm sunny lowland lake evaporates on the order of 1.5-2.5 m/yr
    assert 1200.0 < _annual() < 2600.0


def test_more_sun_and_less_cloud_evaporate_more() -> None:
    assert _annual(q=SUN * 1.2) > _annual()
    assert _annual(cloud=0.2) > _annual(cloud=0.7)


def test_height_raises_the_share_of_energy_in_evaporation() -> None:
    # lower pressure -> smaller psychrometric constant -> larger Delta/(Delta+gamma)
    assert _annual(z=4500.0) > _annual(z=0.0)


def test_frozen_months_do_not_evaporate() -> None:
    t = np.array([[-8, -6, -2, 2, 6, 10, 12, 11, 7, 2, -3, -7]], dtype=float)
    monthly = le.open_water_evaporation_monthly(t, SUN, np.array([0.4]), np.array([4700.0]))
    assert (monthly[t < le.ICE_COVER_THRESHOLD_C] == 0.0).all()
    assert (monthly[t >= le.ICE_COVER_THRESHOLD_C] > 0.0).all()


def test_no_sun_no_evaporation() -> None:
    assert _annual(q=np.zeros((1, 12))) == 0.0


def test_cold_plateau_exceeds_hamon_severalfold() -> None:
    # the step-0 diagnosis: Hamon puts a cold clear plateau lake at ~200 mm/yr
    from dreamulator.engine.climate_physics import potential_evapotranspiration_hamon

    t = np.array([[-12, -9, -5, 0, 4, 8, 10, 9, 6, 0, -6, -10]], dtype=float)
    q = np.array([[230, 280, 340, 390, 420, 430, 425, 400, 350, 300, 245, 215]], dtype=float)
    energy = _annual(t=t, q=q, cloud=0.4, z=4700.0)
    hamon = 0.9 * float(potential_evapotranspiration_hamon(t, 365.25 / 12)[0])
    assert energy > 2.0 * hamon
    assert 300.0 < energy < 1000.0


def test_terminal_verdict_uses_the_open_water_channel() -> None:
    from dreamulator.map.prog_erosion import terminal_lakes

    # one lake (2x2 cells) fed by a single donor cell with a little inflow
    lake = np.zeros((6, 6), bool)
    lake[2:4, 2:4] = True
    receiver = np.full(36, -1, np.int64)
    receiver[1 * 6 + 2] = 2 * 6 + 2  # donor above the lake
    acc = np.ones((6, 6))
    kw = dict(
        land=np.ones((6, 6), bool),
        precip_mm=np.full((6, 6), 200.0),
        temp_c=np.full((6, 6), -5.0),  # Hamon x 0.9 ~ 184 mm < P: pass-through
        runoff_land_mean_mm=300.0,
    )
    assert not terminal_lakes(lake, receiver, acc, **kw).any()
    wet = terminal_lakes(lake, receiver, acc, open_water_mm=np.full((6, 6), 900.0), **kw)
    assert wet[2:4, 2:4].all()  # 4 cells x (900 - 200) mm > 1 cell x 300 mm


def test_load_astronomy_reads_the_orbit(tmp_path: Path) -> None:
    from dreamulator.map.td_canvas_build import load_astronomy

    meta = {
        "stellar_luminosity_sol": 1.0,
        "orbital_distance_au": 1.0,
        "orbital_period_days": 365.25,
        "axial_tilt_deg": 23.44,
        "eccentricity": 0.0167,
    }
    (tmp_path / "climate_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    astro = load_astronomy(tmp_path)
    assert astro is not None
    assert astro["perihelion_day"] == 0.0 and astro["perihelion_day_assumed"]
    meta["perihelion_day"] = 3.0
    (tmp_path / "climate_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    astro = load_astronomy(tmp_path)
    assert astro is not None and astro["perihelion_day"] == 3.0
    assert "perihelion_day_assumed" not in astro
    assert load_astronomy(tmp_path / "missing") is None


def test_lake_evaporation_channel_on_the_coarse_grid() -> None:
    from dreamulator.map import td_canvas as tc
    from dreamulator.map.td_canvas_build import lake_evaporation_channel

    geom = tc.CanvasGeometry(30.0, 90.0, 6371.0, 8)
    t = np.full((12, 8, 8), 15.0)
    astro = {
        "stellar_luminosity_sol": 1.0,
        "orbital_distance_au": 1.0,
        "orbital_period_days": 365.25,
        "axial_tilt_deg": 23.44,
        "eccentricity": 0.0,
        "perihelion_day": 0.0,
    }
    low, meta = lake_evaporation_channel(geom, t, np.zeros((8, 8)), None, astro)
    high, _ = lake_evaporation_channel(geom, t, np.full((8, 8), 4000.0), None, astro)
    cloudy, meta_c = lake_evaporation_channel(
        geom, t, np.zeros((8, 8)), np.full((8, 8), 0.9), astro
    )
    assert low.shape == (8, 8) and (low > 0).all()
    assert (high > low).all() and (cloudy < low).all()
    assert "Earth land-mean" in meta["cloud_source"]
    assert "GCM" in meta_c["cloud_source"]
    assert meta["solar_constant_w_m2"] == pytest.approx(1361.0)
