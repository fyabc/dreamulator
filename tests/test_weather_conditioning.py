"""Weather-pack frame conditioning (L1 adapter) tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.media.weather_conditioning import (
    WeatherFrame,
    blend_weather_frames,
    load_weather_frame,
)

if TYPE_CHECKING:
    from pathlib import Path

FRAMES, NLAT, NLON = 5, 16, 32

_FIELDS = (
    "cloud_total",
    "cloud_low",
    "cloud_mid",
    "cloud_high",
    "cloud_top_height",
    "u_mid",
    "v_mid",
    "u_high",
    "v_high",
)


def _write_pack(
    root: Path,
    fields: dict[str, np.ndarray],
    *,
    subsolar_lon: float = 350.0,
    subsolar_lons: list[float] | None = None,
) -> Path:
    """Write a minimal valid pack: meta.json + fields/*.npy + tracks.json."""
    pack = root / "pack"
    (pack / "fields").mkdir(parents=True)
    lat = -90.0 + (np.arange(NLAT) + 0.5) * 180.0 / NLAT
    lon = (np.arange(NLON) + 0.5) * 360.0 / NLON
    for name in _FIELDS:
        arr = fields.get(name)
        if arr is None:
            arr = np.zeros((FRAMES, NLAT, NLON), dtype=np.float32)
        np.save(pack / "fields" / f"{name}.npy", arr)
    (pack / "tracks.json").write_text(json.dumps({"tracks": []}), encoding="utf-8")
    if subsolar_lons is None:
        subsolar_lons = [subsolar_lon] * FRAMES
    meta = {
        "format": "weather-pack-v1",
        "frames": FRAMES,
        "grid": {
            "lat_deg": [round(float(v), 5) for v in lat],
            "lon_deg": [round(float(v), 5) for v in lon],
        },
        "time": {
            "hours_since_start": [6.0 * t for t in range(FRAMES)],
            "subsolar_lat_deg": [10.0] * FRAMES,
            "subsolar_lon_deg": subsolar_lons,
        },
        "calendar": {"frame_interval_h": 6.0},
    }
    (pack / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return pack


def test_time_mean_and_edge_window(tmp_path: Path) -> None:
    """Centred 3-frame mean; the sequence edges shrink to 2 frames."""
    total = np.stack(
        [np.full((NLAT, NLON), 0.10 + 0.05 * t, dtype=np.float32) for t in range(FRAMES)]
    )
    pack = _write_pack(tmp_path, {"cloud_total": total})
    wf = load_weather_frame(pack, 2, 64, 32)
    # A uniform field is invariant under both smoothing passes, so the output
    # is exactly the centred window mean.
    assert wf.cover.shape == (32, 64)
    np.testing.assert_allclose(wf.cover, 0.20, atol=1e-6)
    assert wf.meta["time_window_frames"] == 3
    assert wf.meta["time_window_span_h"] == 12.0
    assert wf.hours == 12.0
    # Frame 0 has no predecessor: frames {0, 1} only.
    wf0 = load_weather_frame(pack, 0, 64, 32)
    np.testing.assert_allclose(wf0.cover, (0.10 + 0.15) / 2, atol=1e-6)
    assert wf0.meta["time_window_frames"] == 2
    assert wf0.meta["time_window_span_h"] == 6.0


def test_gaussian_smoothing_spreads_a_spike(tmp_path: Path) -> None:
    """The spatial pass replaces near-binary values with a spread field."""
    total = np.full((FRAMES, NLAT, NLON), 0.30, dtype=np.float32)
    total[:, NLAT // 2, NLON // 2] = 1.0
    pack = _write_pack(tmp_path, {"cloud_total": total})
    wf = load_weather_frame(pack, 2, 64, 32)
    assert wf.cover.max() < 0.55  # the spike is no longer near-binary
    assert wf.cover.min() > 0.29  # a positive field stays positive
    assert 0.29 < wf.cover.mean() < 0.32  # mass roughly preserved


def test_vertical_split_from_cloud_top(tmp_path: Path) -> None:
    """Tops below the split band go deck, tops above go cirrus."""
    lat = -90.0 + (np.arange(NLAT) + 0.5) * 180.0 / NLAT
    north = lat > 0.0
    top = np.zeros((FRAMES, NLAT, NLON), dtype=np.float32)
    top[:, north] = 1.0  # stratus deck: visible top below the split band
    top[:, ~north] = 12.0  # cirrus/deep convection: top above the band
    total = np.full((FRAMES, NLAT, NLON), 0.6, dtype=np.float32)
    pack = _write_pack(tmp_path, {"cloud_total": total, "cloud_top_height": top})
    wf = load_weather_frame(pack, 2, 64, 32)
    # Output rows run north to south.  Deep in either hemisphere the
    # classification is exact: shares 1/0 against a cos-latitude mean of 0.5
    # → the on-shell weight doubles, the off-shell one clips to 0.25; only
    # the equatorial rows cross the smoothstep band.
    assert wf.low_weight.shape == (32, 64)
    np.testing.assert_allclose(wf.low_weight[0], 2.0, atol=0.35)
    np.testing.assert_allclose(wf.low_weight[-1], 0.25, atol=0.35)
    assert wf.low_weight[:8].mean() > 1.2
    assert wf.low_weight[-8:].mean() < 0.8
    # cos-latitude symmetry: the global mean weight is near one.
    assert 0.85 < wf.low_weight.mean() < 1.15
    # The shells move oppositely and stay inside the clip range.
    assert wf.high_weight[:8].mean() < 0.8
    for w in (wf.low_weight, wf.high_weight):
        assert np.all((w >= 0.25) & (w <= 3.0))
    assert "cloud_top_height" in wf.meta["vertical_split"]


def test_cloud_top_clear_sky_nan(tmp_path: Path) -> None:
    """NaN tops (clear sky) never leak into the weights."""
    top = np.full((FRAMES, NLAT, NLON), np.nan, dtype=np.float32)
    total = np.full((FRAMES, NLAT, NLON), 0.5, dtype=np.float32)
    pack = _write_pack(tmp_path, {"cloud_total": total, "cloud_top_height": top})
    wf = load_weather_frame(pack, 2, 64, 32)
    # Everywhere clear: the masked mean has no signal, so every cell
    # classifies as deck and both weights stay at their neutral one.
    assert np.isfinite(wf.low_weight).all()
    assert np.isfinite(wf.high_weight).all()
    np.testing.assert_allclose(wf.low_weight, 1.0, atol=1e-6)
    np.testing.assert_allclose(wf.high_weight, 1.0, atol=1e-6)


def test_winds_from_pack(tmp_path: Path) -> None:
    """Deck winds come from u_mid/v_mid, cirrus winds from u_high/v_high."""
    fields = {
        "u_mid": np.full((FRAMES, NLAT, NLON), 3.0, dtype=np.float32),
        "v_mid": np.full((FRAMES, NLAT, NLON), -4.0, dtype=np.float32),
        "u_high": np.full((FRAMES, NLAT, NLON), 30.0, dtype=np.float32),
        "v_high": np.full((FRAMES, NLAT, NLON), 0.0, dtype=np.float32),
    }
    pack = _write_pack(tmp_path, fields)
    wf = load_weather_frame(pack, 2, 64, 32)
    np.testing.assert_allclose(wf.wind_east, 3.0, atol=1e-6)
    np.testing.assert_allclose(wf.wind_north, -4.0, atol=1e-6)
    np.testing.assert_allclose(wf.wind_east_high, 30.0, atol=1e-6)
    np.testing.assert_allclose(wf.wind_north_high, 0.0, atol=1e-6)
    assert wf.meta["wind_fields"]["deck"] == "u_mid/v_mid (sigma ~0.57)"
    assert wf.meta["wind_fields"]["cirrus"] == "u_high/v_high (sigma ~0.32)"


def test_subsolar_and_meta(tmp_path: Path) -> None:
    """Sub-solar longitude converts to the media convention; meta records all."""
    pack = _write_pack(tmp_path, {"cloud_total": np.full((FRAMES, NLAT, NLON), 0.4, np.float32)})
    wf = load_weather_frame(pack, 3, 64, 32)
    assert wf.subsolar_lat_deg == 10.0
    assert wf.subsolar_lon_deg == -10.0  # 350°E → −10°
    assert wf.hours == 18.0
    m = wf.meta
    assert m["frame"] == 3
    assert m["frames_total"] == FRAMES
    assert m["space_sigma_grid_units"] == 1.0
    assert m["cover_field"] == "cloud_total"
    assert m["subsolar_lon_deg"] == -10.0


def test_fractional_frame_interpolation(tmp_path: Path) -> None:
    """A fractional frame blends the two bracketing processed frames."""
    total = np.stack(
        [np.full((NLAT, NLON), 0.10 + 0.05 * t, dtype=np.float32) for t in range(FRAMES)]
    )
    lons = [350.0 + 28.0 * t for t in range(FRAMES)]
    pack = _write_pack(tmp_path, {"cloud_total": total}, subsolar_lons=lons)
    wf = load_weather_frame(pack, 2.5, 64, 32)
    # Frame 2's window {1, 2, 3} averages to 0.20, frame 3's to 0.25.
    np.testing.assert_allclose(wf.cover, 0.225, atol=1e-6)
    assert wf.frame == 2.5
    assert wf.hours == 15.0
    assert wf.meta["frame"] == 2.5
    assert wf.meta["frame_interpolation"] == "linear blend of frames 2 and 3"
    # Sub-solar longitudes 406°→434° become 46→74 in media convention; the
    # half-step blend is 60 without wrapping the long way.
    np.testing.assert_allclose(wf.subsolar_lon_deg, 60.0, atol=1e-6)


def _bare_frame(cover: float, lon: float, shape: tuple[int, int] = (4, 8)) -> WeatherFrame:
    arr = np.full(shape, cover)
    return WeatherFrame(
        cover=arr,
        low_weight=arr.copy(),
        high_weight=arr.copy(),
        wind_east=arr.copy(),
        wind_north=arr.copy(),
        wind_east_high=arr.copy(),
        wind_north_high=arr.copy(),
        frame=1.0,
        hours=6.0,
        subsolar_lat_deg=0.0,
        subsolar_lon_deg=lon,
        meta={},
    )


def test_blend_weather_frames() -> None:
    """Blend lerps arrays, hours and frame index; the seam takes the short way."""
    a = _bare_frame(0.2, 170.0)
    b = _bare_frame(0.4, -170.0)  # 20° east of a, across the ±180 seam
    mid = blend_weather_frames(a, b, 0.5)
    np.testing.assert_allclose(mid.cover, 0.3, atol=1e-12)
    assert mid.frame == 1.0  # both inputs sit at frame 1
    assert mid.hours == 6.0
    # 170° + half of the +20° short-way delta lands on the seam itself.
    np.testing.assert_allclose(mid.subsolar_lon_deg, -180.0, atol=1e-12)
    # A quarter blend stays on a's side of the seam.
    quarter = blend_weather_frames(a, b, 0.25)
    np.testing.assert_allclose(quarter.subsolar_lon_deg, 175.0, atol=1e-12)
    with pytest.raises(ValueError, match="grid"):
        blend_weather_frames(a, _bare_frame(0.1, 0.0, shape=(2, 4)), 0.5)


def test_frame_bounds(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, {})
    with pytest.raises(ValueError, match="outside"):
        load_weather_frame(pack, FRAMES, 64, 32)
    # A half step short of the end would need the nonexistent frame N.
    with pytest.raises(ValueError, match="outside"):
        load_weather_frame(pack, FRAMES - 0.5, 64, 32)
    with pytest.raises(ValueError, match="outside"):
        load_weather_frame(pack, -0.5, 64, 32)
    # The last frame itself is fine (its edge window shrinks).
    load_weather_frame(pack, FRAMES - 1, 64, 32)


def test_clouds_globe_uses_weather_frame(tmp_path: Path) -> None:
    """clouds_globe consumes the frame: pack cover, shells and sub-solar sun."""
    from dreamulator.media import cloud_render as cr
    from tests.test_cloud_render import _toy_mesh

    total = np.full((FRAMES, NLAT, NLON), 0.5, dtype=np.float32)
    pack = _write_pack(tmp_path / "src", {"cloud_total": total})
    wf = load_weather_frame(pack, 2, 64, 32)
    out = tmp_path / "out"
    # Engine mesh (no GCM fields): the pack still drives the conditioning.
    cr.clouds_globe(
        _toy_mesh(), out, radius_km=6800.0, width=64, height=32, globe_res=32, weather=wf
    )
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["weather_pack"]["frame"] == 2
    assert meta["weather_pack"]["pack"].endswith("pack")
    assert meta["cover_field"].startswith("GCM weather pack")
    assert meta["vertical_cloud_weights"].startswith("weather pack")
    # The sun follows the pack's sub-solar point when not set explicitly.
    assert meta["globe"]["sun_lon_deg"] == wf.subsolar_lon_deg
    assert meta["globe"]["sun_lat_deg"] == wf.subsolar_lat_deg
    assert (out / "globe.png").is_file()
    assert (out / "clouds.png").is_file()
