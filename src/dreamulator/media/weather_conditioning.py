"""Per-frame conditioning from the GCM weather pack — the L1 adapter of the
orbital weather-globe chain.

The weather pack (:mod:`dreamulator.gcm.weather_pack`) stores instantaneous
6-hourly T42 fields.  This module turns one frame into the conditioning the
media chain consumes: the large-scale cover (total cloud), the two-shell
vertical split (low/mid versus high cloud) and the sub-solar point.

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

At the sequence edges the window shrinks to the available frames (the first
and last frame are a 2-frame mean).  Longitude wraps and latitude
edge-replicates in the spatial pass.  The parameters land in the render
``meta.json`` so shots stay attributable.  This is rendering-side
conditioning only; pack files are read, never written.

Epistemic status (per engine discipline §9): numerical stabilisation of a
model field for rendering (an agreed recipe, not an observation fit); the
fields themselves are GCM output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.ndimage import gaussian_filter1d

from dreamulator.gcm.to_mesh import bilinear_to_points
from dreamulator.gcm.weather_pack import load_pack
from dreamulator.media.cloud_render import vertical_split_weights

if TYPE_CHECKING:
    from pathlib import Path

#: Frames in the centred time mean (3 × 6 h = 18 h window).
PACK_TIME_WINDOW = 3
#: Gaussian smoothing sigma in native grid units (1 T42 grid step ≈ 310 km at the equator).
PACK_SPACE_SIGMA = 1.0

#: Pack fields the frame loader reads.
_FRAME_FIELDS = ("cloud_total", "cloud_low", "cloud_mid", "cloud_high")


@dataclass
class WeatherFrame:
    """One weather-pack frame rasterised onto the export equirect grid.

    ``cover``/``low_weight``/``high_weight`` are ``(height, width)`` arrays in
    the media-chain convention (rows north to south, columns −180° to 180°).
    The weights are the two-shell multipliers of
    :func:`cloud_render.vertical_split_weights`.  ``subsolar_lon_deg`` is in
    the media convention (−180…180), unlike the pack's 0…360.  ``meta`` is
    copied verbatim into the render ``meta.json``.
    """

    cover: np.ndarray
    low_weight: np.ndarray
    high_weight: np.ndarray
    frame: int
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


def load_weather_frame(
    pack_dir: str | Path,
    frame: int,
    width: int,
    height: int,
    *,
    time_window: int = PACK_TIME_WINDOW,
    space_sigma: float = PACK_SPACE_SIGMA,
) -> WeatherFrame:
    """Load, smooth and rasterise one pack frame (see the module docstring)."""
    pack = load_pack(pack_dir)
    n = int(pack.meta["frames"])
    if not 0 <= frame < n:
        raise ValueError(f"frame {frame} is outside the pack's 0…{n - 1}")
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

    fields = {name: smoothed(name) for name in _FRAME_FIELDS}
    cover = np.clip(fields["cloud_total"], 0.0, 1.0)
    low_amount = np.clip(fields["cloud_low"] + fields["cloud_mid"], 0.0, 1.0)
    high_amount = np.clip(fields["cloud_high"], 0.0, 1.0)
    # cos-latitude weighting: the lat-lon grid over-represents the poles, the
    # CVT mesh (the annual path) is near equal-area.
    cos_lat = np.broadcast_to(np.cos(np.radians(pack.lat))[:, None], low_amount.shape)
    low_w, high_w = vertical_split_weights(low_amount, high_amount, mean_weights=cos_lat)

    tmeta = pack.meta["time"]
    hours = float(tmeta["hours_since_start"][frame])
    sub_lat = float(tmeta["subsolar_lat_deg"][frame])
    sub_lon = float(tmeta["subsolar_lon_deg"][frame])
    sub_lon_media = (sub_lon + 180.0) % 360.0 - 180.0
    span_h = float(tmeta["hours_since_start"][idx[-1]] - tmeta["hours_since_start"][idx[0]])

    return WeatherFrame(
        cover=_resample_equirect(pack.lat, pack.lon, cover, width, height),
        low_weight=_resample_equirect(pack.lat, pack.lon, low_w, width, height),
        high_weight=_resample_equirect(pack.lat, pack.lon, high_w, width, height),
        frame=frame,
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
            "subsolar_lat_deg": sub_lat,
            "subsolar_lon_deg": sub_lon_media,
        },
    )


__all__ = [
    "PACK_SPACE_SIGMA",
    "PACK_TIME_WINDOW",
    "WeatherFrame",
    "load_weather_frame",
]
