"""Cyclone detection and tracking on a GCM Gaussian grid (pure functions, no IO).

The method follows TempestExtremes (Ullrich & Zarzycki 2017; Ullrich et al. 2021):

- **Detect** (``DetectNodes``): sea-level-pressure minima that are the lowest
  point within a merge distance and pass a closed-contour test, i.e. pressure
  rises by at least ``closed_contour_dp_hpa`` within ``closed_contour_radius_km``
  in every direction (checked in eight azimuth sectors).
- **Cyclonic and over low ground**: the low-level relative vorticity near the
  centre must be cyclonic and at least ``min_vorticity_s`` (the TRACK threshold
  of Hodges 1995 for T42 850 hPa vorticity, 1 × 10⁻⁵ s⁻¹ on Earth), which
  rejects shallow heat lows; centres where the GCM surface is higher than
  ``max_surface_height_m`` are skipped, because the sea-level pressure there is
  a hypothetical reduction (the same 1500 m threshold the climate projection
  uses).
- **Warm core**: the 300–500 hPa thickness at the centre exceeds the thickness
  everywhere on a ring by ``warm_core_dz_m`` (the TempestExtremes tropical
  cyclone criterion, a thickness maximum over the storm).
- **Stitch** (``StitchNodes``): candidates in consecutive frames are linked to
  the nearest candidate the storm can reach at ``max_speed_m_s``; tracks
  shorter than ``min_duration_h`` are dropped.  Tracks that never get farther
  than ``min_endpoint_km`` from their first point are kept but flagged
  ``stationary`` (the farthest point rather than the end point, so a storm that
  circles a pole is not mistaken for a stationary one): on
  Earth that TempestExtremes filter removes spurious topographic lows, while on
  a slow rotator with weak eddies long-lived, nearly stationary lows are part of
  the weather, so the choice is left to the consumer.  A track is tropical when
  at least half of its points are warm-cored over open water and it forms
  between 5° and 35° latitude; heat lows over land are also warm-cored, so the
  ocean condition is what separates them.

Epistemic class: the thresholds are observation-fitted detection criteria
(TempestExtremes defaults for reanalysis), not physics.  The structural length
scales (merge distance, closed-contour and warm-core radii) are the Earth values
multiplied by ``rotation_scale = Ω⊕ / Ω``, because synoptic systems scale with
the deformation radius ``L_R = N H / f``: a planet rotating at a third of
Earth's rate has systems about three times as wide.  The vorticity threshold
scales with ``f``, i.e. divides by ``rotation_scale``.  The minimum lifetime,
the stationary-track distance, the pressure drop and the translation speed keep
their Earth values: they reject short-lived noise and mis-linked points at a
6-hourly cadence and are not properties of the storms (on nacrea's GCM the
northern-hemisphere systems live a few days, the southern ones about ten).  On
a T42 grid (about 300 km) the radius of maximum wind cannot be smaller than one
grid spacing; ``rmax_km`` is reported as resolved.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

EARTH_ROTATION_RAD_S = 7.2921e-5

#: TempestExtremes reference values on Earth (great-circle degrees converted to km).
_EARTH_KM_PER_DEG = 111.195
_TE_MERGE_DEG = 6.0
_TE_CLOSED_CONTOUR_DEG = 5.5
_TE_WARM_CORE_DEG = 6.5
_TE_MIN_DURATION_H = 54.0
_TE_MAX_STEP_DEG_PER_6H = 8.0
_TE_MIN_ENDPOINT_DEG = 8.0
_TRACK_MIN_VORTICITY_S = 1.0e-5
_N_SECTORS = 8


@dataclass(frozen=True)
class DetectionParams:
    """Detection and stitching thresholds (see the module docstring)."""

    rotation_scale: float = 1.0
    closed_contour_dp_hpa: float = 2.0
    warm_core_dz_m: float = 6.0
    max_gap_frames: int = 0
    max_surface_height_m: float = 1500.0

    @property
    def min_vorticity_s(self) -> float:
        return _TRACK_MIN_VORTICITY_S / self.rotation_scale

    @property
    def merge_km(self) -> float:
        return _TE_MERGE_DEG * _EARTH_KM_PER_DEG * self.rotation_scale

    @property
    def closed_contour_radius_km(self) -> float:
        return _TE_CLOSED_CONTOUR_DEG * _EARTH_KM_PER_DEG * self.rotation_scale

    @property
    def warm_core_radius_km(self) -> float:
        return _TE_WARM_CORE_DEG * _EARTH_KM_PER_DEG * self.rotation_scale

    @property
    def min_duration_h(self) -> float:
        return _TE_MIN_DURATION_H

    @property
    def min_endpoint_km(self) -> float:
        return _TE_MIN_ENDPOINT_DEG * _EARTH_KM_PER_DEG

    @property
    def max_speed_m_s(self) -> float:
        return _TE_MAX_STEP_DEG_PER_6H * _EARTH_KM_PER_DEG * 1000.0 / (6 * 3600.0)

    def describe(self) -> dict[str, float]:
        return {
            "rotation_scale": self.rotation_scale,
            "closed_contour_dp_hpa": self.closed_contour_dp_hpa,
            "closed_contour_radius_km": round(self.closed_contour_radius_km, 1),
            "merge_km": round(self.merge_km, 1),
            "warm_core_dz_m": self.warm_core_dz_m,
            "warm_core_radius_km": round(self.warm_core_radius_km, 1),
            "min_duration_h": round(self.min_duration_h, 1),
            "max_speed_m_s": round(self.max_speed_m_s, 1),
            "min_endpoint_km": round(self.min_endpoint_km, 1),
            "max_gap_frames": self.max_gap_frames,
            "min_vorticity_s": self.min_vorticity_s,
            "max_surface_height_m": self.max_surface_height_m,
        }


@dataclass
class Candidate:
    """One cyclone centre in one frame."""

    lat: float
    lon: float
    psl_hpa: float
    environment_hpa: float
    outer_radius_km: float
    vmax_m_s: float
    rmax_km: float
    warm_core: bool
    over_ocean: bool = True


@dataclass
class TrackPoint(Candidate):
    frame: int = 0
    time_h: float = 0.0
    motion_east_m_s: float = 0.0
    motion_north_m_s: float = 0.0


@dataclass
class Track:
    track_id: int
    kind: str
    points: list[TrackPoint] = field(default_factory=list)
    stationary: bool = False

    @property
    def duration_h(self) -> float:
        return self.points[-1].time_h - self.points[0].time_h if self.points else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.track_id,
            "kind": self.kind,
            "stationary": self.stationary,
            "duration_h": round(self.duration_h, 2),
            "points": [
                {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(p).items()}
                for p in self.points
            ],
        }


class GridGeometry:
    """Unit vectors and helpers for a regular-longitude grid (pure)."""

    def __init__(self, lat_deg: np.ndarray, lon_deg: np.ndarray, radius_km: float) -> None:
        self.lat = np.asarray(lat_deg, dtype=float)
        self.lon = np.asarray(lon_deg, dtype=float)
        self.radius_km = radius_km
        la, lo = np.meshgrid(np.radians(self.lat), np.radians(self.lon), indexing="ij")
        self.xyz = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)
        self.lat2d, self.lon2d = la, lo

    def distance_km(self, j: int, i: int) -> np.ndarray:
        dot = np.clip(self.xyz @ self.xyz[j, i], -1.0, 1.0)
        out: np.ndarray = np.arccos(dot) * self.radius_km
        return out

    def bearing(self, j: int, i: int) -> np.ndarray:
        """Initial bearing (radians, clockwise from north) from cell (j, i) to every cell."""
        la0, lo0 = self.lat2d[j, i], self.lon2d[j, i]
        dlon = self.lon2d - lo0
        y = np.sin(dlon) * np.cos(self.lat2d)
        x = np.cos(la0) * np.sin(self.lat2d) - np.sin(la0) * np.cos(self.lat2d) * np.cos(dlon)
        out: np.ndarray = np.arctan2(y, x) % (2 * math.pi)
        return out


def _neighbour_minima(psl: np.ndarray) -> np.ndarray:
    """Cells not higher than their eight neighbours (periodic in longitude)."""
    padded = np.pad(psl, ((1, 1), (0, 0)), mode="edge")
    padded = np.concatenate([padded[:, -1:], padded, padded[:, :1]], axis=1)
    centre = padded[1:-1, 1:-1]
    is_min = np.ones_like(psl, dtype=bool)
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            if dj == 0 and di == 0:
                continue
            is_min &= (
                centre
                <= padded[1 + dj : padded.shape[0] - 1 + dj, 1 + di : padded.shape[1] - 1 + di]
            )
    return is_min


def _sector_extreme(
    values: np.ndarray, dist: np.ndarray, bearing: np.ndarray, radius_km: float, use_max: bool
) -> np.ndarray:
    """Per azimuth sector, the max (or min) of ``values`` within ``radius_km``; NaN if empty."""
    sector = (bearing / (2 * math.pi) * _N_SECTORS).astype(int) % _N_SECTORS
    inside = (dist > 0.0) & (dist <= radius_km)
    out = np.full(_N_SECTORS, np.nan)
    for s in range(_N_SECTORS):
        sel = inside & (sector == s)
        if sel.any():
            out[s] = values[sel].max() if use_max else values[sel].min()
    return out


def _parabolic_offset(fm: float, f0: float, fp: float) -> float:
    """Sub-grid offset (in grid steps, within ±0.5) of the extremum of a 3-point parabola."""
    denom = fm - 2.0 * f0 + fp
    if denom <= 0.0:
        return 0.0
    return float(np.clip(0.5 * (fm - fp) / denom, -0.5, 0.5))


def _radial_profile(
    psl: np.ndarray, dist: np.ndarray, bin_km: float, max_km: float
) -> tuple[np.ndarray, np.ndarray]:
    edges = np.arange(0.0, max_km + bin_km, bin_km)
    centres, means = [], []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        sel = (dist >= a) & (dist < b)
        if sel.any():
            centres.append(0.5 * (a + b))
            means.append(float(psl[sel].mean()))
    return np.asarray(centres), np.asarray(means)


def detect_candidates(
    psl_hpa: np.ndarray,
    wind_speed: np.ndarray,
    thickness_m: np.ndarray | None,
    geom: GridGeometry,
    params: DetectionParams,
    *,
    vorticity_s: np.ndarray | None = None,
    surface_height_m: np.ndarray | None = None,
    ocean: np.ndarray | None = None,
) -> list[Candidate]:
    """Cyclone centres in one frame (``DetectNodes`` with a closed-contour test).

    All fields are ``(nlat, nlon)`` on ``geom``'s grid: sea-level pressure (hPa),
    low-level wind speed (m/s), 300–500 hPa thickness (m, for the warm-core test),
    low-level relative vorticity (1/s), the GCM surface height (m) and the ocean
    mask (True = open water).
    """
    psl = np.asarray(psl_hpa, dtype=float)
    js, is_ = np.nonzero(_neighbour_minima(psl))
    order = np.argsort(psl[js, is_])
    accepted: list[tuple[int, int]] = []
    out: list[Candidate] = []
    nlat, nlon = psl.shape
    hemisphere = np.sign(geom.lat)[:, None] * np.ones_like(psl)
    for k in order:
        j, i = int(js[k]), int(is_[k])
        if surface_height_m is not None and surface_height_m[j, i] > params.max_surface_height_m:
            continue
        if any(geom.distance_km(a, b)[j, i] < params.merge_km for a, b in accepted):
            continue
        dist = geom.distance_km(j, i)
        bearing = geom.bearing(j, i)
        p0 = psl[j, i]
        ring_max = _sector_extreme(psl, dist, bearing, params.closed_contour_radius_km, True)
        if np.isnan(ring_max).any() or (ring_max - p0 < params.closed_contour_dp_hpa).any():
            continue
        bin_km = max(geom.radius_km * math.radians(180.0 / nlat), 1.0)
        if vorticity_s is not None:
            near = dist <= 1.5 * bin_km
            cyclonic = float((vorticity_s * hemisphere)[near].max())
            if cyclonic < params.min_vorticity_s:
                continue
        accepted.append((j, i))
        # sub-grid centre from a parabola through the neighbouring rows and columns
        dlat = 0.0
        if 0 < j < nlat - 1:
            off = _parabolic_offset(psl[j - 1, i], p0, psl[j + 1, i])
            dlat = off * (geom.lat[j + 1] - geom.lat[j - 1]) / 2.0
        off = _parabolic_offset(psl[j, (i - 1) % nlon], p0, psl[j, (i + 1) % nlon])
        dlon = off * (360.0 / nlon)
        # outer radius: where the azimuthal-mean pressure stops rising (≤ 0.5 hPa per bin)
        r, prof = _radial_profile(psl, dist, bin_km, 3.0 * params.closed_contour_radius_km)
        outer, env = float(r[-1]), float(prof[-1])
        for m in range(1, len(prof)):
            if prof[m] - prof[m - 1] < 0.5:
                outer, env = float(r[m - 1]), float(prof[m - 1])
                break
        inside = dist <= max(outer, bin_km)
        jw, iw = np.unravel_index(np.argmax(np.where(inside, wind_speed, -np.inf)), psl.shape)
        warm = False
        if thickness_m is not None:
            near = dist <= bin_km
            th0 = float(thickness_m[near].max())
            ring_min = _sector_extreme(
                thickness_m, dist, bearing, params.warm_core_radius_km, False
            )
            warm = bool(
                not np.isnan(ring_min).any() and (th0 - ring_min >= params.warm_core_dz_m).all()
            )
        out.append(
            Candidate(
                lat=float(geom.lat[j] + dlat),
                lon=float((geom.lon[i] + dlon) % 360.0),
                psl_hpa=float(p0),
                environment_hpa=env,
                outer_radius_km=outer,
                vmax_m_s=float(wind_speed[jw, iw]),
                rmax_km=float(max(dist[jw, iw], bin_km)),
                warm_core=warm,
                over_ocean=bool(ocean[j, i]) if ocean is not None else True,
            )
        )
    return out


def _gc_km(lat1: float, lon1: float, lat2: float, lon2: float, radius_km: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return math.acos(max(-1.0, min(1.0, c))) * radius_km


def stitch_tracks(
    frames: list[list[Candidate]],
    times_h: np.ndarray,
    params: DetectionParams,
    radius_km: float,
) -> list[Track]:
    """Link per-frame candidates into tracks (``StitchNodes``, greedy nearest neighbour)."""
    active: list[tuple[list[TrackPoint], int]] = []  # (points, last frame index)
    finished: list[list[TrackPoint]] = []
    for f, cands in enumerate(frames):
        t = float(times_h[f])
        pairs = []
        for a, (pts, last) in enumerate(active):
            gap = f - last
            reach = params.max_speed_m_s * (t - pts[-1].time_h) * 3.6
            for c_idx, c in enumerate(cands):
                d = _gc_km(pts[-1].lat, pts[-1].lon, c.lat, c.lon, radius_km)
                if gap <= params.max_gap_frames + 1 and d <= reach:
                    pairs.append((d, a, c_idx))
        used_a, used_c = set(), set()
        for _, a, c_idx in sorted(pairs):
            if a in used_a or c_idx in used_c:
                continue
            used_a.add(a)
            used_c.add(c_idx)
            active[a][0].append(TrackPoint(**asdict(cands[c_idx]), frame=f, time_h=t))
            active[a] = (active[a][0], f)
        still = []
        for a, (pts, last) in enumerate(active):
            if a in used_a or f - last <= params.max_gap_frames:
                still.append((pts, last))
            else:
                finished.append(pts)
        active = still
        for c_idx, c in enumerate(cands):
            if c_idx not in used_c:
                active.append(([TrackPoint(**asdict(c), frame=f, time_h=t)], f))
    finished.extend(pts for pts, _ in active)

    tracks: list[Track] = []
    for pts in finished:
        if len(pts) < 2 or pts[-1].time_h - pts[0].time_h < params.min_duration_h:
            continue
        moved = max(_gc_km(pts[0].lat, pts[0].lon, q.lat, q.lon, radius_km) for q in pts)
        _fill_motion(pts, radius_km)
        warm_share = sum(p.warm_core and p.over_ocean for p in pts) / len(pts)
        tropical = warm_share >= 0.5 and 5.0 <= abs(pts[0].lat) < 35.0
        tracks.append(
            Track(
                track_id=len(tracks),
                kind="tropical" if tropical else "extratropical",
                points=pts,
                stationary=moved < params.min_endpoint_km,
            )
        )
    return tracks


def _fill_motion(pts: list[TrackPoint], radius_km: float) -> None:
    """Centred-difference translation velocity (m/s, east and north) along a track."""
    for k, p in enumerate(pts):
        a, b = pts[max(k - 1, 0)], pts[min(k + 1, len(pts) - 1)]
        dt = (b.time_h - a.time_h) * 3600.0
        if dt <= 0:
            continue
        dlon = ((b.lon - a.lon + 180.0) % 360.0) - 180.0
        mean_lat = math.radians(0.5 * (a.lat + b.lat))
        p.motion_east_m_s = math.radians(dlon) * math.cos(mean_lat) * radius_km * 1000.0 / dt
        p.motion_north_m_s = math.radians(b.lat - a.lat) * radius_km * 1000.0 / dt


__all__ = [
    "EARTH_ROTATION_RAD_S",
    "Candidate",
    "DetectionParams",
    "GridGeometry",
    "Track",
    "TrackPoint",
    "detect_candidates",
    "stitch_tracks",
]
