"""Per-frame conditioning from the GCM weather pack — the L1 adapter of the
orbital weather-globe chain.

The weather pack (:mod:`dreamulator.gcm.weather_pack`) stores instantaneous
6-hourly T42 fields.  This module turns one frame into the conditioning the
media chain consumes: the large-scale cover (total cloud), the two-shell
vertical split (the visible cloud top classifies deck versus cirrus), the
sub-solar point and the advecting winds — the mid-level flow (sigma ≈ 0.57)
that transports the low/mid cloud shell and the high-level flow (sigma ≈
0.32) that carries the cirrus shell (the L4 advection input).

Smoothing recipe (agreed with the GCM side, 2026-10-23): the raw
instantaneous cloud fields are nearly binary — at frame 400, 68% of grid
points sit below 0.05 or above 0.95 — so before driving the texture they are

1. averaged over the ``time_window`` frames centred on the target (default
   3 frames = 18 h; the 6-hour lag-1 correlation is 0.66 and lag-2 is 0.46,
   so a 3-frame mean keeps weather-scale structure while 5 frames start
   erasing it), then
2. Gaussian-smoothed on the native grid with sigma in grid units (default
   1.0 ≈ 310 km at the equator; the two-end fraction drops 68% → 23% with
   the spatial step alone → 16% with both, correlation with the raw field
   0.82).

The winds go through the same two passes, which matches their role: the
texture warp and the L4 advection both want the resolved mean flow, not the
6-hour snapshot noise.  At the sequence edges the window shrinks to the
available frames (the first and last frame are a 2-frame mean).  Longitude
wraps and latitude edge-replicates in the spatial pass.  The parameters land
in the render ``meta.json`` so shots stay attributable.  This is
rendering-side conditioning only; pack files are read, never written.

Fractional frames: a float ``frame`` blends the two bracketing integer frames
after each is fully processed (window mean, spatial smoothing, vertical
split), so callers stepping finer than the pack's 6-hour interval — the L4
video, for example — get a continuous field.  Sub-solar longitude blends the
short way around, keeping the day cycle continuous across the 0°/360° seam.

Epistemic status (per engine discipline §9): numerical stabilisation of a
model field for rendering (an agreed recipe, not an observation fit); the
fields themselves are GCM output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.ndimage import gaussian_filter1d

from dreamulator.gcm.to_mesh import bilinear_to_points
from dreamulator.gcm.weather_pack import WeatherPack, load_pack
from dreamulator.media.cloud_render import shell_weights_from_shares

if TYPE_CHECKING:
    from pathlib import Path

#: Frames in the centred time mean (3 × 6 h = 18 h window).
PACK_TIME_WINDOW = 3
#: Gaussian smoothing sigma in native grid units (1 T42 grid step ≈ 310 km at the equator).
PACK_SPACE_SIGMA = 1.0

#: Visible cloud-top heights at/below this km classify all deck; at/above the
#: companion all cirrus (smoothstep between).  Diagnosis 2026-10-24: the
#: annual distribution is bimodal — marine stratocumulus tops near 1 km,
#: cirrus anvils near 10–12 km — with the valley across this band, and the
#: band midpoint (6.5 km) reproduces the global cirrus share of the layer
#: -amount split (0.52 versus 0.548), so switching evidence keeps the total.
SHELL_SPLIT_LOW_KM = 4.75
SHELL_SPLIT_HIGH_KM = 8.25

#: Pack fields the frame loader reads: cloud conditioning (total cover plus
#: the visible cloud top that classifies the two shells) and the two
#: advecting wind levels.
_FRAME_FIELDS = (
    "cloud_total",
    "cloud_top_height",
    "u_mid",
    "v_mid",
    "u_high",
    "v_high",
)

#: How the wind fields map onto the two cloud shells (recorded in meta).
_WIND_FIELDS_META = {
    "deck": "u_mid/v_mid (sigma ~0.57)",
    "cirrus": "u_high/v_high (sigma ~0.32)",
}


@dataclass
class WeatherFrame:
    """One weather-pack frame rasterised onto the export equirect grid.

    All arrays are ``(height, width)`` in the media-chain convention (rows
    north to south, columns −180° to 180°).  ``cover``/``low_weight``/
    ``high_weight`` are the conditioning of the still renderer: the weights
    are the two-shell multipliers of
    :func:`cloud_render.shell_weights_from_shares`, with the shares
    classified by the visible cloud top (deck below the split band, cirrus
    above); the winds are the advecting
    flows in m/s — ``wind_east``/``wind_north`` (mid level, sigma ≈ 0.57)
    transport the low/mid cloud shell, ``wind_east_high``/
    ``wind_north_high`` (sigma ≈ 0.32) the cirrus shell.  ``frame`` may be
    fractional (an interpolation).  ``subsolar_lon_deg`` is in the media
    convention (−180…180), unlike the pack's 0…360.  ``meta`` is copied
    verbatim into the render ``meta.json``.
    """

    cover: np.ndarray
    low_weight: np.ndarray
    high_weight: np.ndarray
    wind_east: np.ndarray
    wind_north: np.ndarray
    wind_east_high: np.ndarray
    wind_north_high: np.ndarray
    frame: float
    hours: float
    subsolar_lat_deg: float
    subsolar_lon_deg: float
    meta: dict[str, Any]


def _resample_equirect(
    lat_grid: np.ndarray, lon_grid: np.ndarray, values: np.ndarray, width: int, height: int
) -> np.ndarray:
    """Bilinear-resample one native-grid field onto the export equirect grid.

    Same pixel-centre convention as ``WeatherPack.frame_equirect``: rows north
    to south, columns −180° to 180°.
    """
    lat = 90.0 - (np.arange(height, dtype=np.float64) + 0.5) / height * 180.0
    lon = (np.arange(width, dtype=np.float64) + 0.5) / width * 360.0 - 180.0
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    return np.asarray(bilinear_to_points(lat_grid, lon_grid, values, la, lo), dtype=np.float64)


def _smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _integer_frame(
    pack: WeatherPack,
    frame: int,
    width: int,
    height: int,
    *,
    time_window: int,
    space_sigma: float,
) -> WeatherFrame:
    """Process one integer pack frame: window mean, smoothing, resample."""
    n = int(pack.meta["frames"])
    half = max(time_window, 1) // 2
    idx = [t for t in range(frame - half, frame + half + 1) if 0 <= t < n]

    def smoothed(name: str) -> np.ndarray:
        arr = pack.field(name)
        mean = np.mean([np.asarray(arr[t], dtype=np.float64) for t in idx], axis=0)
        if not np.isfinite(mean).all():
            mean = np.where(np.isfinite(mean), mean, float(np.nanmean(mean)))
        # Separable Gaussian: longitude wraps, latitude edge-replicates.
        out = gaussian_filter1d(mean, space_sigma, axis=1, mode="wrap")
        return np.asarray(gaussian_filter1d(out, space_sigma, axis=0, mode="nearest"))

    def smoothed_top(name: str) -> np.ndarray:
        """Cloud-top smoothing where NaN means clear, not missing.

        Both passes are cloud-frequency weighted (sum of z·m over sum of m):
        a clear cell must not drag the tops of its cloudy neighbours down.
        Deep inside clear regions the height tends to 0, which classifies as
        deck — harmless, those cells carry no cloud to draw.
        """
        arrs = [np.asarray(pack.field(name)[t], dtype=np.float64) for t in idx]
        masks = np.stack([np.isfinite(a) for a in arrs])
        m_mean = masks.mean(axis=0)
        z_num = np.sum([np.where(m, a, 0.0) for a, m in zip(arrs, masks, strict=True)], axis=0)
        z_mean = z_num / np.maximum(m_mean * len(idx), 1e-9)
        num = gaussian_filter1d(z_mean * m_mean, space_sigma, axis=1, mode="wrap")
        den = gaussian_filter1d(m_mean, space_sigma, axis=1, mode="wrap")
        num = np.asarray(gaussian_filter1d(num, space_sigma, axis=0, mode="nearest"))
        den = np.asarray(gaussian_filter1d(den, space_sigma, axis=0, mode="nearest"))
        return np.asarray(num / np.maximum(den, 1e-3))

    fields = {name: smoothed(name) for name in _FRAME_FIELDS if name != "cloud_top_height"}
    cover = np.clip(fields["cloud_total"], 0.0, 1.0)
    z_top = smoothed_top("cloud_top_height")
    # Visible-top classification: the topmost cloud a space view sees decides
    # which shell draws the cell (deep-convective tops go to the cirrus shell
    # even though the low layers are cloudy too).
    high_share = _smoothstep(SHELL_SPLIT_LOW_KM, SHELL_SPLIT_HIGH_KM, z_top)
    low_share = 1.0 - high_share
    # cos-latitude weighting: the lat-lon grid over-represents the poles, the
    # CVT mesh (the annual path) is near equal-area.
    cos_lat = np.broadcast_to(np.cos(np.radians(pack.lat))[:, None], cover.shape)
    low_w, high_w = shell_weights_from_shares(low_share, high_share, cover, mean_weights=cos_lat)
    # The near-bimodal shares make the clip floor absorb the off-shell
    # deficit while the on-shell multiplier stays unclipped, so the unweighted
    # mean weight sits slightly above one (measured 1.17 on f273) and the
    # split adds a few percent of texture opacity.  That is harmless — the
    # cover field itself is untouched and the area-weighted budget stays
    # near one — and renormalising would push weights outside the clip range
    # for no visible gain, so the bias is accepted and recorded here.

    tmeta = pack.meta["time"]
    hours = float(tmeta["hours_since_start"][frame])
    sub_lat = float(tmeta["subsolar_lat_deg"][frame])
    sub_lon = float(tmeta["subsolar_lon_deg"][frame])
    sub_lon_media = (sub_lon + 180.0) % 360.0 - 180.0
    span_h = float(tmeta["hours_since_start"][idx[-1]] - tmeta["hours_since_start"][idx[0]])

    def resample(values: np.ndarray) -> np.ndarray:
        return _resample_equirect(pack.lat, pack.lon, values, width, height)

    return WeatherFrame(
        cover=resample(cover),
        low_weight=resample(low_w),
        high_weight=resample(high_w),
        wind_east=resample(fields["u_mid"]),
        wind_north=resample(fields["v_mid"]),
        wind_east_high=resample(fields["u_high"]),
        wind_north_high=resample(fields["v_high"]),
        frame=float(frame),
        hours=hours,
        subsolar_lat_deg=sub_lat,
        subsolar_lon_deg=sub_lon_media,
        meta={
            "pack": str(pack.path),
            "frame": frame,
            "frames_total": n,
            "hours_since_start": hours,
            "time_window_frames": len(idx),
            "time_window_span_h": span_h,
            "space_sigma_grid_units": space_sigma,
            "smoothing": (
                "centred frame mean, then Gaussian on the native grid "
                "(longitude wraps, latitude edge-replicates)"
            ),
            "cover_field": "cloud_total",
            "vertical_split": (
                "cloud_top_height smoothstep 4.75-8.25 km "
                "(visible top classifies the two shells; clear = deck)"
            ),
            "wind_fields": dict(_WIND_FIELDS_META),
            "subsolar_lat_deg": sub_lat,
            "subsolar_lon_deg": sub_lon_media,
        },
    )


def blend_weather_frames(a: WeatherFrame, b: WeatherFrame, frac: float) -> WeatherFrame:
    """Linearly blend two fully processed frames (``frac`` = weight of ``b``).

    Both frames must share the raster grid; each is already window-averaged,
    smoothed and vertically split, so the blend is a convex combination of the
    two rendered states (cover and weights stay inside their ranges).
    Sub-solar longitude blends the short way around, which keeps the day
    cycle continuous across the 0°/360° seam — valid while the pack's
    per-frame sub-solar advance stays under 180° (≈ 29° here).
    """
    if a.cover.shape != b.cover.shape:
        raise ValueError("frames must share the same raster grid to blend")
    frac = float(np.clip(frac, 0.0, 1.0))

    def mix(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return (1.0 - frac) * x + frac * y

    delta_lon = (b.subsolar_lon_deg - a.subsolar_lon_deg + 180.0) % 360.0 - 180.0
    sub_lon = (a.subsolar_lon_deg + frac * delta_lon + 180.0) % 360.0 - 180.0
    meta = dict(a.meta)
    meta["frame"] = (1.0 - frac) * a.frame + frac * b.frame
    meta["frame_interpolation"] = f"linear blend of frames {a.frame:g} and {b.frame:g}"
    meta["subsolar_lon_deg"] = sub_lon
    return WeatherFrame(
        cover=mix(a.cover, b.cover),
        low_weight=mix(a.low_weight, b.low_weight),
        high_weight=mix(a.high_weight, b.high_weight),
        wind_east=mix(a.wind_east, b.wind_east),
        wind_north=mix(a.wind_north, b.wind_north),
        wind_east_high=mix(a.wind_east_high, b.wind_east_high),
        wind_north_high=mix(a.wind_north_high, b.wind_north_high),
        frame=(1.0 - frac) * a.frame + frac * b.frame,
        hours=(1.0 - frac) * a.hours + frac * b.hours,
        subsolar_lat_deg=(1.0 - frac) * a.subsolar_lat_deg + frac * b.subsolar_lat_deg,
        subsolar_lon_deg=sub_lon,
        meta=meta,
    )


def frame_from_pack(
    pack: WeatherPack,
    frame: float,
    width: int,
    height: int,
    *,
    time_window: int = PACK_TIME_WINDOW,
    space_sigma: float = PACK_SPACE_SIGMA,
) -> WeatherFrame:
    """Load one frame from an already-open pack (see the module docstring).

    A fractional ``frame`` fully processes the two bracketing integer frames
    and blends the results (:func:`blend_weather_frames`), so callers stepping
    finer than the pack's 6-hour interval get a continuous field.  Reusing the
    open ``pack`` handle avoids re-reading ``meta.json`` on every call of a
    frame sequence.
    """
    n = int(pack.meta["frames"])
    if not 0 <= frame <= n - 1:
        raise ValueError(f"frame {frame} is outside the pack's 0…{n - 1}")
    base = int(math.floor(frame))
    frac = float(frame) - base
    a = _integer_frame(pack, base, width, height, time_window=time_window, space_sigma=space_sigma)
    if frac == 0.0:
        return a
    b = _integer_frame(
        pack, base + 1, width, height, time_window=time_window, space_sigma=space_sigma
    )
    return blend_weather_frames(a, b, frac)


def load_weather_frame(
    pack_dir: str | Path,
    frame: float,
    width: int,
    height: int,
    *,
    time_window: int = PACK_TIME_WINDOW,
    space_sigma: float = PACK_SPACE_SIGMA,
) -> WeatherFrame:
    """Load, smooth and rasterise one pack frame (see the module docstring)."""
    return frame_from_pack(
        load_pack(pack_dir),
        frame,
        width,
        height,
        time_window=time_window,
        space_sigma=space_sigma,
    )


__all__ = [
    "PACK_SPACE_SIGMA",
    "PACK_TIME_WINDOW",
    "SHELL_SPLIT_HIGH_KM",
    "SHELL_SPLIT_LOW_KM",
    "WeatherFrame",
    "blend_weather_frames",
    "frame_from_pack",
    "load_weather_frame",
]
