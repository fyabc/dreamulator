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
  ``tc_potential_intensity``.  The cloud-shield size is not a canon constant:
  it is the largest radius at which the storm's own wind still dominates the
  ambient wind difference across the shield (author ruling 2026-10-25: the
  wind data outrank the old 1500–2500 km canon size), so calm inner tropics
  allow broad gyres and the westerly ramp toward the jet clips shields to
  compact cores trailing downwind cirrus plumes.

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
from dreamulator.media.cyclone_render import Cyclone, holland_wind_m_s

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
#: Anvil-cirrus lifetime (h): the downwind plume length is this times the
#: local upper-level wind speed.  Observed thick-anvil lifetimes are 6–12 h
#: and thin cirrus up to ~2 days; 36 h takes the upper thin-cirrus end.
CIRRUS_LIFETIME_H = 36.0
#: Longest drawn plume (km): beyond this the streak dissolves into the
#: ambient deck rather than reading as one storm's outflow.
PLUME_MAX_KM = 4000.0
#: Coherent-shield clip (km).  Below ~250 km the storm is smaller than the
#: video texture can show; above 1500 km the shield would exceed anything the
#: planet's weak ambient flow could wrap around the vortex.
SHIELD_LO_KM = 250.0
SHIELD_HI_KM = 1500.0
#: Extratropical detection gates.  T42 resolves planetary-wave troughs, not
#: individual frontal cyclones; detections this polar or with a core radius
#: this large are the circumpolar vortex, not storms (measured in the nacrea
#: pack: detections at −85° with rmax ≈ 1700 km, "Vmax" 200+ m/s; tracked
#: fronts stay in the 500–1000 km range).
EXTRATROPICAL_MAX_ABS_LAT = 70.0
EXTRATROPICAL_MAX_RMAX_KM = 1200.0
#: Minimum upper-level wind (m/s) that streaks a visible plume.
PLUME_MIN_WIND_M_S = 3.0
#: Earth's rotation rate (rad/s), the fallback when a pack lacks a sidereal day.
_OMEGA_EARTH = 7.292115e-5


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


def _pack_omega(pack: WeatherPack) -> float:
    """Planetary rotation rate (rad/s) from the pack's sidereal day."""
    day_h = float((pack.meta.get("calendar") or {}).get("sidereal_day_h", 0.0) or 0.0)
    return 2.0 * math.pi / (day_h * 3600.0) if day_h > 0.0 else _OMEGA_EARTH


def coherent_shield_km(
    *,
    rmax_km: float,
    central_pressure_hpa: float,
    environment_pressure_hpa: float,
    lat_deg: float,
    omega_rad_s: float,
    radius_km: float,
    wind_lat: np.ndarray,
    wind_m_s: np.ndarray,
    lo_km: float = SHIELD_LO_KM,
    hi_km: float = SHIELD_HI_KM,
) -> float:
    """Largest cloud-shield radius (km) the ambient wind field lets stay coherent.

    A vortex holds its own cloud pattern only where its tangential wind
    dominates the ambient wind difference across the shield: outside that
    radius the environment advects and shears the cloud faster than the
    vortex can wrap it (the same reason Jupiter's large vortices sit in
    shear zones whose speed matches their rim winds).  The shield is the
    largest radius where the Holland wind still exceeds that difference,
    clipped to ``[lo_km, hi_km]``.  ``wind_m_s`` is the ambient wind at the
    storm's longitude on the ascending ``wind_lat`` grid (one pack frame).
    """
    rs = np.geomspace(max(2.5 * rmax_km, lo_km), hi_km, 64)
    storm_v = np.asarray(
        holland_wind_m_s(
            rs,
            rmax_km=rmax_km,
            central_pressure_hpa=central_pressure_hpa,
            environment_pressure_hpa=environment_pressure_hpa,
            lat_deg=lat_deg,
            omega=omega_rad_s,
        ),
        dtype=float,
    )
    deg_per_km = 180.0 / (math.pi * radius_km)
    u_north = np.interp(lat_deg + rs * deg_per_km, wind_lat, wind_m_s)
    u_south = np.interp(lat_deg - rs * deg_per_km, wind_lat, wind_m_s)
    ok = storm_v >= np.abs(u_north - u_south)
    if not ok[0]:
        return lo_km
    # last radius before the first failure (arrays are short; the loop is clear)
    shield = hi_km
    for good, r in zip(ok.tolist(), rs.tolist(), strict=False):
        if good:
            shield = r
        else:
            break
    return float(shield)


def cyclones_at_frame(
    pack: WeatherPack, frame: float, *, include_stationary: bool = False
) -> list[Cyclone]:
    """Real moving extratropical cyclones from the pack at ``frame``.

    The pack's quasi-stationary lows are skipped unless ``include_stationary``
    (QA only), and its tropical tracks are never used here — they are monsoon
    depressions at T42; tropical cyclones come from
    :class:`TropicalCycloneSource` instead.  Detections beyond the latitude
    and core-size gates are the circumpolar vortex / planetary-wave troughs,
    not individual storms, and are skipped.
    """
    omega = _pack_omega(pack)
    out: list[Cyclone] = []
    for track in pack.tracks:
        if track.get("kind") != "extratropical":
            continue
        if track.get("stationary", False) and not include_stationary:
            continue
        state = _track_state(track, float(frame))
        if state is None:
            continue
        if abs(state["lat"]) > EXTRATROPICAL_MAX_ABS_LAT:
            continue
        if state["rmax_km"] > EXTRATROPICAL_MAX_RMAX_KM:
            continue
        seed = (int(track.get("id", 0)) * _SEED_MULT) % (2**31 - 1)
        # Life-edge fade: a track is alive only between its first and last
        # points, but a video composites frame by frame — without a fade the
        # comma pops in and out at full amplitude the moment the track starts
        # or ends.  The deficit ramps over the first/last 6 h of track life,
        # so the cloud grows and dissolves with the detection window.
        frames_all = [float(p["frame"]) for p in track["points"]]
        edge_h = 6.0 / (pack.meta.get("calendar") or {}).get("frame_interval_h", 6.0) or 1.0
        edge = min(frame - frames_all[0], frames_all[-1] - frame, edge_h) / edge_h
        fade = max(0.0, min(1.0, edge))
        deficit = max(state["environment_hpa"] - state["psl_hpa"], 0.0) * fade
        out.append(
            Cyclone(
                lat_deg=state["lat"],
                lon_deg=_media_lon(state["lon"]),
                kind="extratropical",
                central_pressure_hpa=state["environment_hpa"] - deficit,
                environment_pressure_hpa=state["environment_hpa"],
                rmax_km=state["rmax_km"],
                outer_radius_km=state["outer_radius_km"],
                motion_east_m_s=state["motion_east_m_s"],
                motion_north_m_s=state["motion_north_m_s"],
                shape_seed=seed or 1,
                omega_rad_s=omega,
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
        ocean_fraction: np.ndarray | None = None,
    ) -> None:
        self.pack = pack
        self.radius_km = float(radius_km)
        self.omega_rad_s = _pack_omega(pack)
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
        u_mid = np.asarray(pack.field("u_mid"), dtype=np.float64)
        belt = np.abs(lat_grid) >= GENESIS_MIN_ABS_LAT
        # The potential fields carry small negatives in hostile environments
        # (measured: GPI down to -0.002, PI to -1 m/s); as probabilities they
        # mean "no potential", so clip to zero.
        gpi = np.maximum(np.asarray(pack.field("tc_genesis_potential"), dtype=np.float64), 0.0)
        # Tropical cyclogenesis happens over open water — the energy source is
        # the warm ocean, not the land the GCM grid happens to sit on.  The
        # model's GPI field does not encode surface type (it happily peaks over
        # the interior of continents), so the ocean mask from the planet map
        # gates it when the caller provides one on the pack grid.
        if ocean_fraction is not None:
            if np.shape(ocean_fraction) != gpi.shape[1:]:
                raise ValueError(
                    f"ocean_fraction shape {np.shape(ocean_fraction)} does not match "
                    f"the pack grid {gpi.shape[1:]}"
                )
            gpi = gpi * np.clip(np.asarray(ocean_fraction, dtype=np.float64), 0.0, 1.0)
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
            rmax_km = float(rng.uniform(100.0, 220.0))
            # Coherent shield at peak intensity against the ambient wind at
            # genesis (see coherent_shield_km): the environment, not a canon
            # constant, sizes the storm.  Invert Holland at Rmax for the peak
            # deficit, same as .at() does per frame.
            dp_peak = peak * peak * math.e * _AIR_DENSITY_KG_M3 / (_HOLLAND_B * 100.0)
            outer = coherent_shield_km(
                rmax_km=rmax_km,
                central_pressure_hpa=1012.0 - dp_peak,
                environment_pressure_hpa=1012.0,
                lat_deg=lat,
                omega_rad_s=self.omega_rad_s,
                radius_km=self.radius_km,
                wind_lat=lat_grid,
                wind_m_s=u_mid[f_idx, :, ilon],
            )
            self.genesis.append(
                _Genesis(
                    frame=float(f_idx),
                    lat=lat,
                    lon=lon % 360.0,
                    peak_vmax_m_s=peak,
                    duration_frames=duration_h / self.interval_h,
                    rmax_km=rmax_km,
                    outer_radius_km=outer,
                    shape_seed=int(rng.integers(1, 2**31 - 1)),
                )
            )

    def _wind_at(
        self, frame: float, lat: float, lon: float, u_name: str, v_name: str
    ) -> tuple[float, float]:
        """One level's (eastward, northward) wind (m/s) at a point, pack grid.

        The pack stores 6-hour snapshots; fractional frames interpolate
        linearly in time between the two bracketing frames.  Snapping to the
        nearest frame instead would step the steering flow and the plume
        length/bearing once per pack frame — visible as a jumping cloud stripe
        in per-frame-composited videos (user QA 2026-10-25).
        """
        k0 = min(max(int(math.floor(frame)), 0), self.n_frames - 1)
        k1 = min(k0 + 1, self.n_frames - 1)
        frac = frame - k0 if k1 > k0 else 0.0
        lat_q = np.array([lat])
        lon_q = np.array([lon])
        u_a = float(
            np.asarray(
                bilinear_to_points(
                    self.pack.lat,
                    self.pack.lon,
                    np.asarray(self.pack.field(u_name)[k0], dtype=np.float64),
                    lat_q,
                    lon_q,
                )[0]
            )
        )
        v_a = float(
            np.asarray(
                bilinear_to_points(
                    self.pack.lat,
                    self.pack.lon,
                    np.asarray(self.pack.field(v_name)[k0], dtype=np.float64),
                    lat_q,
                    lon_q,
                )[0]
            )
        )
        if frac <= 0.0 or k1 == k0:
            return u_a, v_a
        u_b = float(
            np.asarray(
                bilinear_to_points(
                    self.pack.lat,
                    self.pack.lon,
                    np.asarray(self.pack.field(u_name)[k1], dtype=np.float64),
                    lat_q,
                    lon_q,
                )[0]
            )
        )
        v_b = float(
            np.asarray(
                bilinear_to_points(
                    self.pack.lat,
                    self.pack.lon,
                    np.asarray(self.pack.field(v_name)[k1], dtype=np.float64),
                    lat_q,
                    lon_q,
                )[0]
            )
        )
        return _lerp(u_a, u_b, frac), _lerp(v_a, v_b, frac)

    def _steering(self, frame: float, lat: float, lon: float) -> tuple[float, float]:
        """Mid-level wind (m/s) at one point, pack grid convention."""
        return self._wind_at(frame, lat, lon, "u_mid", "v_mid")

    def _trajectory(self, g: _Genesis, frame: float) -> tuple[float, float, float, float, float]:
        """Integrate the steering flow from genesis to ``frame``.

        Returns (lat, lon, u, v, life_used) in the pack convention; ``u``/``v``
        are the local steering wind for the template's motion asymmetry, and
        ``life_used`` is the life budget spent so far — frames burn faster in
        the equatorial dead zone (see :func:`_life_weight`).  The legs use the
        wind at their midpoint, and the returned motion is the wind at the
        requested (fractional) frame and final position, so both the track and
        the motion vector are continuous across pack-frame boundaries — the
        template's motion asymmetry and the envelope axis follow the steering
        flow, and a stepping vector visibly snaps them every 6 h.
        """
        lat, lon = g.lat, g.lon
        radius_m = self.radius_km * 1000.0
        f = g.frame
        life_used = 0.0
        while f < frame - 1.0e-9:
            nxt = min(f + 1.0, frame)
            dt_s = (nxt - f) * self.interval_h * 3600.0
            life_used += (nxt - f) * _life_weight(lat)
            u, v = self._steering(0.5 * (f + nxt), lat, lon)
            cos_lat = max(math.cos(math.radians(lat)), 1.0e-3)
            lon = (lon + math.degrees(u * dt_s / (radius_m * cos_lat))) % 360.0
            lat = min(max(lat + math.degrees(v * dt_s / radius_m), -88.0), 88.0)
            f = nxt
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
            # Downwind plume from the local upper-level wind: the outflow
            # streaks with the ambient flow, so its length and bearing are the
            # environment's, not the storm's spin.
            uh, vh = self._wind_at(frame, lat, lon, "u_high", "v_high")
            high_speed = math.hypot(uh, vh)
            if high_speed > PLUME_MIN_WIND_M_S:
                plume_km = min(CIRRUS_LIFETIME_H * 3600.0 * high_speed / 1000.0, PLUME_MAX_KM)
                plume_bearing = math.degrees(math.atan2(uh, vh))
            else:
                plume_km = 0.0
                plume_bearing = 90.0
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
                    omega_rad_s=self.omega_rad_s,
                    plume_km=plume_km,
                    plume_bearing_deg=plume_bearing,
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
    ocean_fraction: np.ndarray | None = None,
) -> list[Cyclone]:
    """The frame's full cyclone set: real extratropical + canon tropical.

    ``tropical`` lets a frame sequence (the L4 video) reuse one source so the
    sampled genesis events stay identical across calls; without it a source is
    built per call — still deterministic for the same (pack, seed).
    ``ocean_fraction`` (pack grid) gates tropical genesis to open water when
    ``tropical`` is not given.
    """
    source = (
        tropical
        if tropical is not None
        else TropicalCycloneSource(
            pack, seed=seed, radius_km=radius_km, ocean_fraction=ocean_fraction
        )
    )
    return cyclones_at_frame(pack, frame, include_stationary=include_stationary) + source.at(frame)


__all__ = [
    "CIRRUS_LIFETIME_H",
    "EXTRATROPICAL_MAX_ABS_LAT",
    "EXTRATROPICAL_MAX_RMAX_KM",
    "GENESIS_MIN_ABS_LAT",
    "PLUME_MAX_KM",
    "SHIELD_HI_KM",
    "SHIELD_LO_KM",
    "TROPICAL_PER_YEAR",
    "TropicalCycloneSource",
    "coherent_shield_km",
    "cyclones_at_frame",
    "weather_cyclones_at_frame",
]
