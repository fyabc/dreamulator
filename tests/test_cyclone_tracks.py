"""Real-track and canon-parametric cyclone source (L3 adapter) tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.gcm.weather_pack import load_pack
from dreamulator.media.cyclone_render import Cyclone
from dreamulator.media.cyclone_tracks import (
    GENESIS_MIN_ABS_LAT,
    TropicalCycloneSource,
    _life_weight,
    cyclones_at_frame,
    weather_cyclones_at_frame,
)
from tests.test_weather_conditioning import FRAMES, NLAT, NLON, _write_pack

if TYPE_CHECKING:
    from pathlib import Path


def _write_tracks(pack: Path, tracks: list[dict]) -> Path:
    (pack / "tracks.json").write_text(json.dumps({"tracks": tracks}), encoding="utf-8")
    return pack


def _point(frame: int, **over: float) -> dict:
    base = {
        "lat": -40.0,
        "lon": 350.0,
        "psl_hpa": 990.0,
        "environment_hpa": 1020.0,
        "outer_radius_km": 2500.0,
        "vmax_m_s": 25.0,
        "rmax_km": 800.0,
        "warm_core": False,
        "over_ocean": True,
        "frame": frame,
        "time_h": 6.0 * frame,
        "motion_east_m_s": 10.0,
        "motion_north_m_s": -5.0,
    }
    base.update(over)
    return base


def _track(track_id: int, kind: str, stationary: bool, points: list[dict]) -> dict:
    return {
        "id": track_id,
        "kind": kind,
        "stationary": stationary,
        "duration_h": 6.0 * max(len(points) - 1, 1),
        "points": points,
    }


def _gpi_pack(tmp_path: Path) -> Path:
    """A pack whose genesis potential sits on one belt row at one frame."""
    lat = -90.0 + (np.arange(NLAT) + 0.5) * 180.0 / NLAT
    row = int(np.argmin(np.abs(lat - 16.875)))
    gpi = np.zeros((FRAMES, NLAT, NLON), dtype=np.float32)
    gpi[2, row, :] = 1.0
    pi = np.full((FRAMES, NLAT, NLON), 60.0, dtype=np.float32)
    pack = _write_pack(tmp_path, {})
    np.save(pack / "fields" / "tc_genesis_potential.npy", gpi)
    np.save(pack / "fields" / "tc_potential_intensity.npy", pi)
    return _write_tracks(pack, [])


def _write_drift_pack(tmp_path: Path, v_mid: float, frames: int) -> Path:
    """A long pack with genesis on one row and a uniform meridional steering.

    ``v_mid`` is a constant northward wind (m/s), so every sampled storm rides
    the same drift — slow enough (about 0.9°/frame at 5 m/s) that the
    equatorial dead zone is crossed over many frames, as in a real pack.
    """
    lat = -90.0 + (np.arange(NLAT) + 0.5) * 180.0 / NLAT
    lon = (np.arange(NLON) + 0.5) * 360.0 / NLON
    row = int(np.argmin(np.abs(lat - 16.875)))
    shape = (frames, NLAT, NLON)
    fields = {
        name: np.zeros(shape, dtype=np.float32)
        for name in (
            "cloud_total",
            "cloud_low",
            "cloud_mid",
            "cloud_high",
            "u_mid",
            "u_high",
            "v_high",
        )
    }
    fields["v_mid"] = np.full(shape, v_mid, dtype=np.float32)
    gpi = np.zeros(shape, dtype=np.float32)
    gpi[2, row, :] = 1.0
    pi = np.full(shape, 60.0, dtype=np.float32)

    pack = tmp_path / "drift-pack"
    (pack / "fields").mkdir(parents=True)
    for name, arr in fields.items():
        np.save(pack / "fields" / f"{name}.npy", arr)
    np.save(pack / "fields" / "tc_genesis_potential.npy", gpi)
    np.save(pack / "fields" / "tc_potential_intensity.npy", pi)
    meta = {
        "format": "weather-pack-v1",
        "frames": frames,
        "grid": {
            "lat_deg": [round(float(v), 5) for v in lat],
            "lon_deg": [round(float(v), 5) for v in lon],
        },
        "time": {
            "hours_since_start": [6.0 * t for t in range(frames)],
            "subsolar_lat_deg": [10.0] * frames,
            "subsolar_lon_deg": [350.0] * frames,
        },
        "calendar": {"frame_interval_h": 6.0},
    }
    (pack / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return _write_tracks(pack, [])


def test_track_interpolation(tmp_path: Path) -> None:
    """A fractional frame lerps position, pressure and radii between points."""
    pack = _write_pack(tmp_path, {})
    _write_tracks(
        pack,
        [
            _track(
                7,
                "extratropical",
                False,
                [
                    _point(2, lat=-40.0, lon=350.0, psl_hpa=990.0, rmax_km=800.0),
                    _point(
                        4,
                        lat=-42.0,
                        lon=10.0,
                        psl_hpa=980.0,
                        rmax_km=1000.0,
                        environment_hpa=1018.0,
                        outer_radius_km=2600.0,
                    ),
                ],
            )
        ],
    )
    loaded = load_pack(pack)
    storms = cyclones_at_frame(loaded, 3.0)
    assert len(storms) == 1
    cyc = storms[0]
    assert isinstance(cyc, Cyclone)
    assert cyc.kind == "extratropical"
    assert cyc.lat_deg == -41.0
    # 350°→10° crosses the pack seam the short way (+20°): half-step is 0°.
    assert cyc.lon_deg == 0.0
    assert cyc.central_pressure_hpa == 985.0
    assert cyc.environment_pressure_hpa == 1019.0
    assert cyc.rmax_km == 900.0
    assert cyc.outer_radius_km == 2550.0
    assert cyc.motion_east_m_s == 10.0
    assert cyc.shape_seed != 0
    # Integer end frames and out-of-life frames.
    assert cyclones_at_frame(loaded, 4.0)[0].lat_deg == -42.0
    assert cyclones_at_frame(loaded, 1.9) == []
    assert cyclones_at_frame(loaded, 4.5) == []


def test_stationary_and_tropical_filtering(tmp_path: Path) -> None:
    """Stationary lows are QA-only; the pack's tropical tracks are never used."""
    pack = _write_pack(tmp_path, {})
    _write_tracks(
        pack,
        [
            _track(1, "extratropical", False, [_point(0), _point(2)]),
            _track(2, "extratropical", True, [_point(0), _point(2)]),
            _track(3, "tropical", False, [_point(0, lat=15.0), _point(2, lat=16.0)]),
        ],
    )
    loaded = load_pack(pack)
    default = cyclones_at_frame(loaded, 1.0)
    assert len(default) == 1  # only the moving extratropical
    with_stationary = cyclones_at_frame(loaded, 1.0, include_stationary=True)
    assert len(with_stationary) == 2
    assert all(c.kind == "extratropical" for c in with_stationary)


def test_tropical_source_canon(tmp_path: Path) -> None:
    """Genesis respects the belt and potential field; lifecycle is bounded."""
    pack = load_pack(_gpi_pack(tmp_path))
    a = TropicalCycloneSource(pack, seed=41, radius_km=6816.97)
    b = TropicalCycloneSource(pack, seed=41, radius_km=6816.97)
    assert a.genesis and len(a.genesis) == len(b.genesis)  # deterministic
    assert all(g.frame == 2.0 for g in a.genesis)  # only the GPI frame draws
    assert all(11.0 <= g.lat <= 23.0 for g in a.genesis)  # belt row + cell jitter
    assert all(18.0 <= g.peak_vmax_m_s <= 60.0 for g in a.genesis)  # PI cap 60
    assert all(1500.0 <= g.outer_radius_km <= 2500.0 for g in a.genesis)
    # Alive at genesis and just after (steering wind is zero in this pack).
    alive = a.at(2.5)
    assert len(alive) == len(a.genesis)
    assert all(c.kind == "tropical" for c in alive)
    # Spin-up at genesis: Vmax 12 m/s -> ~3 hPa deficit via Holland inversion.
    for c in a.at(2.0):
        assert c.environment_pressure_hpa - c.central_pressure_hpa < 5.0
    # Before genesis: none.
    assert a.at(1.0) == []


def test_tropical_source_lifecycle_ramp(tmp_path: Path) -> None:
    """Intensity spins up from genesis over the early lifetime."""
    pack = load_pack(_gpi_pack(tmp_path))
    src = TropicalCycloneSource(pack, seed=41, radius_km=6816.97)
    early = src.at(2.0)[0]
    later = src.at(4.0)[0]
    dp_early = early.environment_pressure_hpa - early.central_pressure_hpa
    dp_later = later.environment_pressure_hpa - later.central_pressure_hpa
    assert dp_later > dp_early


def test_life_weight_rates() -> None:
    """The burn rate is 1.0 at and beyond the belt edge and peaks at the equator."""
    assert _life_weight(GENESIS_MIN_ABS_LAT) == 1.0
    assert _life_weight(30.0) == 1.0
    assert _life_weight(90.0) == 1.0
    assert _life_weight(0.0) == 16.0  # 1 + K with K = 15
    assert _life_weight(-5.0) == _life_weight(5.0)  # symmetric
    # Closer to the equator burns faster.
    assert _life_weight(2.0) > _life_weight(4.0) > _life_weight(6.0)


def test_tropical_equatorial_decay(tmp_path: Path) -> None:
    """A storm steered into the dead zone dissipates there, not past the equator."""
    pack = load_pack(_write_drift_pack(tmp_path, v_mid=-5.0, frames=24))
    src = TropicalCycloneSource(pack, seed=41, radius_km=6816.97)
    assert src.genesis, "the pack must sample at least one storm"
    # Early life: alive and well inside the belt.
    early = src.at(4.0)
    assert early and all(c.lat_deg > GENESIS_MIN_ABS_LAT for c in early)
    # The southward drift (about 0.9°/frame) carries every storm into the
    # dead zone; each must burn out inside it — none may cross the equator,
    # and by the end of the pack all have dissipated (life spent ~56 frames
    # there, above the 16–40-frame duration range).
    for frame in range(4, 24):
        for c in src.at(float(frame)):
            assert c.lat_deg > 0.0, f"storm crossed the equator by frame {frame}"
    assert src.at(23.9) == []
    # A mirror pack (northward drift from the same belt row) stays healthy:
    # the drift never enters the dead zone, so at a nominal age of 8 frames
    # every storm (minimum duration 16 frames) is still alive.
    north = load_pack(_write_drift_pack(tmp_path / "mirror", v_mid=5.0, frames=24))
    nsrc = TropicalCycloneSource(north, seed=41, radius_km=6816.97)
    assert nsrc.at(10.0) != []


def test_weather_cyclones_union(tmp_path: Path) -> None:
    """The frame set is the real extratropical plus the canon tropical."""
    pack = _write_pack(tmp_path, {})
    lat = -90.0 + (np.arange(NLAT) + 0.5) * 180.0 / NLAT
    row = int(np.argmin(np.abs(lat - 16.875)))
    gpi = np.zeros((FRAMES, NLAT, NLON), dtype=np.float32)
    gpi[1, row, :] = 1.0
    pi = np.full((FRAMES, NLAT, NLON), 55.0, dtype=np.float32)
    np.save(pack / "fields" / "tc_genesis_potential.npy", gpi)
    np.save(pack / "fields" / "tc_potential_intensity.npy", pi)
    _write_tracks(pack, [_track(1, "extratropical", False, [_point(0), _point(2)])])
    loaded = load_pack(pack)
    combined = weather_cyclones_at_frame(loaded, 1.5, seed=41, radius_km=6816.97)
    kinds = sorted(c.kind for c in combined)
    assert "extratropical" in kinds and "tropical" in kinds
    # Reusing one source keeps the sampled events identical across calls.
    src = TropicalCycloneSource(loaded, seed=41, radius_km=6816.97)
    again = weather_cyclones_at_frame(loaded, 1.5, seed=41, radius_km=6816.97, tropical=src)
    assert sorted(c.kind for c in again) == kinds
    assert len([c for c in again if c.kind == "tropical"]) == len(
        [c for c in combined if c.kind == "tropical"]
    )
