"""Real-track and canon-parametric cyclone sources for the orbital chain (L3).

The weather pack's ``tracks.json`` carries TempestExtremes-style tracks with
per-6-hour points (position, central and environment pressure, radii, motion
vector).  This module turns them into the media chain's :class:`Cyclone`
entries at a render frame.

Selection rules (agreed with the GCM side, 2026-10-23):

* moving extratropical cyclones drive the comma templates by default;
* the quasi-stationary lows are hidden by default (QA toggle only) — they are
  mostly land heat lows and basin lows, and drawing them as storms misleads;
* the pack's tropical tracks are not used: at T42 they are monsoon
  depressions, not resolved tropical cyclones.  Tropical cyclones come from
  the parametric canon instead (author ruling, design-notes 0020): about
  8 per local year (a creative canon constant), genesis positions and seasons
  drawn from ``tc_genesis_potential`` outside |lat| < 8°, intensity capped by
  ``tc_potential_intensity``, outer cloud shield 1500–2500 km.

The tropical storms move with the pack's mid-level steering flow integrated
from genesis, so recurvature emerges from the ambient wind rather than being
imposed.  A warm-core vortex cannot sustain itself where the planetary
vorticity fades, so when steering carries a storm into the equatorial dead
zone (|lat| < 8°) its life budget burns faster and it dissipates there
rather than crossing the equator.  Everything is seeded and deterministic
given (pack, seed).

Epistemic status (per engine discipline §9): the extratropical half is model
output passed through; the tropical half is a parametric template on top of
model-derived potential fields — the count is a creative-canon constant, the
position/season distribution and the intensity cap are model fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.gcm.to_mesh import bilinear_to_points
from dreamulator.media.cyclone_render import Cyclone

if TYPE_CHECKING:
    from dreamulator.gcm.weather_pack import WeatherPack

#: Tropical cyclones per local year (canon, design-notes 0020).
TROPICAL_PER_YEAR = 8.0
#: Genesis belt: no generation inside |lat| < 8° (canon).
GENESIS_MIN_ABS_LAT = 8.0
#: sin of the belt edge, the vorticity reference for the dead-zone burn rate.
_SIN_MIN_LAT = math.sin(math.radians(GENESIS_MIN_ABS_LAT))
#: Extra life-budget burn rate at the equator relative to the belt edge.
#: Calibrated so a storm steered into the dead zone dissipates within one to
#: two days, around 3–6° latitude (Earth: tropical cyclones almost never
#: survive inside ±5°; the Coriolis term cannot support the vortex).
_EQUATOR_DECAY_K = 15.0
#: Holland profile shape for the pressure-deficit inversion.
_HOLLAND_B = 1.5
#: Near-surface air density (kg/m³), matches ``cyclone_render``.
_AIR_DENSITY_KG_M3 = 1.15
#: Seed derivation multiplier for real-track shape seeds (Knuth multiplicative).
_SEED_MULT = 2654435761


def _media_lon(lon_deg: float) -> float:
    """Pack grid longitude (0…360) to the media convention (−180…180)."""
    return (float(lon_deg) + 180.0) % 360.0 - 180.0


def _lerp(a: float, b: float, t: float) -> float:
    return (1.0 - t) * a + t * b


def _lerp_lon(a: float, b: float, t: float) -> float:
    """Shortest-way longitude blend in the pack convention (0…360)."""
    delta = (b - a + 180.0) % 360.0 - 180.0
    return (a + t * delta) % 360.0


def _life_weight(lat_deg: float) -> float:
    """Life-budget burn rate per frame at ``lat_deg`` (1.0 outside the belt).

    Sustaining a warm-core vortex needs planetary vorticity; the rate scales
    with the vorticity deficit ``1 − sin|lat|/sin 8°`` so it is 1.0 at and
    poleward of the genesis-belt edge and 1 + K at the equator.
    """
    s = math.sin(math.radians(min(abs(lat_deg), 90.0))) / _SIN_MIN_LAT
    return 1.0 + _EQUATOR_DECAY_K * max(0.0, 1.0 - s)


def _track_state(track: dict[str, Any], frame: float) -> dict[str, float] | None:
    """Interpolated point state of one track at ``frame``, None outside life."""
    points = track.get("points") or []
    if not points:
        return None
    frames = [float(p["frame"]) for p in points]
    if frame < frames[0] or frame > frames[-1]:
        return None
    for k in range(len(points) - 1):
        if frames[k] <= frame <= frames[k + 1]:
            span = frames[k + 1] - frames[k]
            t = 0.0 if span <= 0.0 else (frame - frames[k]) / span
            p0, p1 = points[k], points[k + 1]
            return {
                "lat": _lerp(float(p0["lat"]), float(p1["lat"]), t),
                "lon": _lerp_lon(float(p0["lon"]), float(p1["lon"]), t),
                "psl_hpa": _lerp(float(p0["psl_hpa"]), float(p1["psl_hpa"]), t),
                "environment_hpa": _lerp(
                    float(p0["environment_hpa"]), float(p1["environment_hpa"]), t
                ),
                "rmax_km": _lerp(float(p0["rmax_km"]), float(p1["rmax_km"]), t),
                "outer_radius_km": _lerp(
                    float(p0["outer_radius_km"]), float(p1["outer_radius_km"]), t
                ),
                "motion_east_m_s": _lerp(
                    float(p0["motion_east_m_s"]), float(p1["motion_east_m_s"]), t
                ),
                "motion_north_m_s": _lerp(
                    float(p0["motion_north_m_s"]), float(p1["motion_north_m_s"]), t
                ),
            }
    # Frame exactly at the last point (or a zero-span bracket).
    last = points[-1]
    return {
        "lat": float(last["lat"]),
        "lon": float(last["lon"]),
        "psl_hpa": float(last["psl_hpa"]),
        "environment_hpa": float(last["environment_hpa"]),
        "rmax_km": float(last["rmax_km"]),
        "outer_radius_km": float(last["outer_radius_km"]),
        "motion_east_m_s": float(last["motion_east_m_s"]),
        "motion_north_m_s": float(last["motion_north_m_s"]),
    }


def cyclones_at_frame(
    pack: WeatherPack, frame: float, *, include_stationary: bool = False
) -> list[Cyclone]:
    """Real moving extratropical cyclones from the pack at ``frame``.

    The pack's quasi-stationary lows are skipped unless ``include_stationary``
    (QA only), and its tropical tracks are never used here — they are monsoon
    depressions at T42; tropical cyclones come from
    :class:`TropicalCycloneSource` instead.
    """
    out: list[Cyclone] = []
    for track in pack.tracks:
        if track.get("kind") != "extratropical":
            continue
        if track.get("stationary", False) and not include_stationary:
            continue
        state = _track_state(track, float(frame))
        if state is None:
            continue
        seed = (int(track.get("id", 0)) * _SEED_MULT) % (2**31 - 1)
        out.append(
            Cyclone(
                lat_deg=state["lat"],
                lon_deg=_media_lon(state["lon"]),
                kind="extratropical",
                central_pressure_hpa=state["psl_hpa"],
                environment_pressure_hpa=state["environment_hpa"],
                rmax_km=state["rmax_km"],
                outer_radius_km=state["outer_radius_km"],
                motion_east_m_s=state["motion_east_m_s"],
                motion_north_m_s=state["motion_north_m_s"],
                shape_seed=seed or 1,
            )
        )
    return out


@dataclass(frozen=True)
class _Genesis:
    """One sampled genesis event; the lifecycle is derived deterministically."""

    frame: float
    lat: float
    lon: float
    peak_vmax_m_s: float
    duration_frames: float
    rmax_km: float
    outer_radius_km: float
    shape_seed: int


def _lifecycle_vmax(tau: float, peak: float) -> float:
    """Intensity over the storm life ``tau`` ∈ [0, 1]: spin-up, hold, decay."""
    floor = 12.0

    def smoothstep(lo: float, hi: float, x: float) -> float:
        t = min(max((x - lo) / (hi - lo), 0.0), 1.0)
        return t * t * (3.0 - 2.0 * t)

    if tau < 0.25:
        return _lerp(floor, peak, smoothstep(0.0, 0.25, tau))
    if tau < 0.70:
        return peak
    return _lerp(peak, floor, smoothstep(0.70, 1.0, tau))


class TropicalCycloneSource:
    """Parametric tropical cyclones per the canon, drawn once from the pack.

    Genesis times follow the per-frame total of ``tc_genesis_potential``
    (so the seasonal peaks live in the field itself), positions follow the
    field at the genesis frame outside |lat| < 8°, and the peak intensity is a
    fraction of ``tc_potential_intensity`` at the genesis point.  Storm
    positions at later frames integrate the pack's mid-level steering flow
    from genesis, so motion and recurvature come from the model environment.
    Deterministic given (pack, seed).
    """

    def __init__(
        self,
        pack: WeatherPack,
        *,
        seed: int = 4100,
        radius_km: float = 6371.0,
        per_year: float = TROPICAL_PER_YEAR,
    ) -> None:
        self.pack = pack
        self.radius_km = float(radius_km)
        self.interval_h = float((pack.meta.get("calendar") or {}).get("frame_interval_h", 6.0))
        self.n_frames = int(pack.meta["frames"])
        tmeta = pack.meta["time"]
        hours = tmeta["hours_since_start"]
        span_h = float(hours[-1] - hours[0])
        phase = tmeta.get("orbital_phase")
        advance = float(phase[-1] - phase[0]) if phase and len(phase) > 1 else 0.0
        # Local-year length from the orbital phase where available.
        year_h = span_h / advance if advance > 0.05 else span_h

        rng = np.random.default_rng(int(seed))
        lat_grid = np.asarray(pack.lat, dtype=float)
        belt = np.abs(lat_grid) >= GENESIS_MIN_ABS_LAT
        # The potential fields carry small negatives in hostile environments
        # (measured: GPI down to -0.002, PI to -1 m/s); as probabilities they
        # mean "no potential", so clip to zero.
        gpi = np.maximum(np.asarray(pack.field("tc_genesis_potential"), dtype=np.float64), 0.0)
        weights = np.where(belt[None, :, None], gpi, 0.0).sum(axis=(1, 2))
        total = float(weights.sum())
        n_events = int(rng.poisson(per_year * span_h / year_h)) if total > 0.0 else 0

        pi = np.maximum(np.asarray(pack.field("tc_potential_intensity"), dtype=np.float64), 0.0)
        lon_grid = np.asarray(pack.lon, dtype=float)
        self.genesis: list[_Genesis] = []
        for _ in range(n_events):
            f_idx = int(rng.choice(self.n_frames, p=weights / total))
            frame_field = np.where(belt[:, None], gpi[f_idx], 0.0)
            flat = frame_field.ravel()
            cell = int(rng.choice(flat.size, p=flat / flat.sum()))
            ilat, ilon = divmod(cell, frame_field.shape[1])
            dlat = lat_grid[1] - lat_grid[0] if lat_grid.size > 1 else 0.0
            dlon = lon_grid[1] - lon_grid[0] if lon_grid.size > 1 else 0.0
            lat = float(lat_grid[ilat]) + float(rng.uniform(-0.5, 0.5)) * dlat
            lon = float(lon_grid[ilon]) + float(rng.uniform(-0.5, 0.5)) * dlon
            peak = float(np.clip(rng.uniform(0.55, 1.0) * float(pi[f_idx, ilat, ilon]), 18.0, 75.0))
            duration_h = float(rng.uniform(96.0, 240.0))
            self.genesis.append(
                _Genesis(
                    frame=float(f_idx),
                    lat=lat,
                    lon=lon % 360.0,
                    peak_vmax_m_s=peak,
                    duration_frames=duration_h / self.interval_h,
                    rmax_km=float(rng.uniform(100.0, 220.0)),
                    outer_radius_km=float(rng.uniform(1500.0, 2500.0)),
                    shape_seed=int(rng.integers(1, 2**31 - 1)),
                )
            )

    def _steering(self, frame: float, lat: float, lon: float) -> tuple[float, float]:
        """Mid-level wind (m/s) at one point, pack grid convention."""
        k = min(max(int(round(frame)), 0), self.n_frames - 1)
        u = float(
            np.asarray(
                bilinear_to_points(
                    self.pack.lat,
                    self.pack.lon,
                    np.asarray(self.pack.field("u_mid")[k], dtype=np.float64),
                    np.array([lat]),
                    np.array([lon]),
                )[0]
            )
        )
        v = float(
            np.asarray(
                bilinear_to_points(
                    self.pack.lat,
                    self.pack.lon,
                    np.asarray(self.pack.field("v_mid")[k], dtype=np.float64),
                    np.array([lat]),
                    np.array([lon]),
                )[0]
            )
        )
        return u, v

    def _trajectory(self, g: _Genesis, frame: float) -> tuple[float, float, float, float, float]:
        """Integrate the steering flow from genesis to ``frame``.

        Returns (lat, lon, u, v, life_used) in the pack convention; ``u``/``v``
        are the local steering wind for the template's motion asymmetry, and
        ``life_used`` is the life budget spent so far — frames burn faster in
        the equatorial dead zone (see :func:`_life_weight`).
        """
        lat, lon = g.lat, g.lon
        radius_m = self.radius_km * 1000.0
        f = g.frame
        u = v = 0.0
        life_used = 0.0
        while f < frame - 1.0e-9:
            nxt = min(f + 1.0, frame)
            dt_s = (nxt - f) * self.interval_h * 3600.0
            life_used += (nxt - f) * _life_weight(lat)
            u, v = self._steering(f, lat, lon)
            cos_lat = max(math.cos(math.radians(lat)), 1.0e-3)
            lon = (lon + math.degrees(u * dt_s / (radius_m * cos_lat))) % 360.0
            lat = min(max(lat + math.degrees(v * dt_s / radius_m), -88.0), 88.0)
            f = nxt
        if frame <= g.frame + 1.0e-9:
            u, v = self._steering(frame, lat, lon)
        return lat, lon, u, v, life_used

    def at(self, frame: float) -> list[Cyclone]:
        """All canon tropical cyclones alive at ``frame``.

        A storm is alive while its life budget lasts; the budget burns at the
        frame rate outside the genesis belt and faster in the equatorial dead
        zone, so storms steered toward the equator weaken and dissipate there
        instead of crossing it.
        """
        out: list[Cyclone] = []
        for g in self.genesis:
            if frame < g.frame - 1.0e-9:
                continue
            lat, lon, u, v, life_used = self._trajectory(g, frame)
            if life_used >= g.duration_frames:
                continue
            tau = life_used / g.duration_frames
            vmax = _lifecycle_vmax(tau, g.peak_vmax_m_s)
            # Invert Holland (1980) at Rmax: Vmax² = B·Δp/(ρ·e) → Δp.
            dp_hpa = vmax * vmax * math.e * _AIR_DENSITY_KG_M3 / (_HOLLAND_B * 100.0)
            env = 1012.0
            out.append(
                Cyclone(
                    lat_deg=lat,
                    lon_deg=_media_lon(lon),
                    kind="tropical",
                    central_pressure_hpa=env - dp_hpa,
                    environment_pressure_hpa=env,
                    rmax_km=g.rmax_km,
                    outer_radius_km=g.outer_radius_km,
                    motion_east_m_s=u,
                    motion_north_m_s=v,
                    shape_seed=g.shape_seed,
                )
            )
        return out


def weather_cyclones_at_frame(
    pack: WeatherPack,
    frame: float,
    *,
    seed: int = 4100,
    include_stationary: bool = False,
    radius_km: float = 6371.0,
    tropical: TropicalCycloneSource | None = None,
) -> list[Cyclone]:
    """The frame's full cyclone set: real extratropical + canon tropical.

    ``tropical`` lets a frame sequence (the L4 video) reuse one source so the
    sampled genesis events stay identical across calls; without it a source is
    built per call — still deterministic for the same (pack, seed).
    """
    source = (
        tropical
        if tropical is not None
        else TropicalCycloneSource(pack, seed=seed, radius_km=radius_km)
    )
    return cyclones_at_frame(pack, frame, include_stationary=include_stationary) + source.at(frame)


__all__ = [
    "GENESIS_MIN_ABS_LAT",
    "TROPICAL_PER_YEAR",
    "TropicalCycloneSource",
    "cyclones_at_frame",
    "weather_cyclones_at_frame",
]
