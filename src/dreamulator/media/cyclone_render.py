"""Parametric cyclone templates — layer L3 of the orbital weather-globe chain.

The GCM layer pack (L1) will supply cyclone tracks: time, centre position,
central pressure (or vorticity), radius of maximum wind and type (tropical or
extratropical).  This module turns one such track entry into a cloud-opacity
template that is composited over the L2 procedural texture.  Until L1 lands,
``synthetic_cyclones`` supplies a climatological placeholder track set so the
visual grammar can be settled first (same precedent as the L2 prototype).

Tropical cyclones use the Holland (1980) surface-pressure/wind profile for the
intensity scale, an eye, an eyewall ring, a cirrus shield and logarithmic
spiral rainbands.  Extratropical cyclones use a Shapiro–Keyser style comma
cloud with a frontal band, oriented by the translation vector.  The template
is a *rendering* layer: positions and intensities are data, not free
parameters; only the band geometry is a visual choice.

All geometry is computed on the sphere in kilometres, so the equirectangular
output is seamless at the antimeridian and has no polar pinch.  Deterministic
given (cyclones, grid, radius, seed).

References:
    Holland, G. J. (1980). An analytic model of the wind and pressure
    profiles in hurricanes. *Monthly Weather Review*, 108, 1212–1218.
    Shapiro, M. A., & Keyser, D. (1990). Fronts, jet streams and the
    tropopause. In *Extratropical Cyclones* (Palmen memorial volume).

Existing implementations checked (formulas/concepts only, no code copied):
    CLIMADA ``trop_cyclone_windfields`` (Holland 1980/2008/2010 wind fields);
    ``paratc``, ``pyStorms`` and ``tcwindfields`` for the same family of
    parametric profiles; Lygia ``sdf/spiralSDF`` and the OpenProcessing
    generative-hurricane sketches for the log-spiral band field (Lygia is
    under the Prosperity/Patron license, so its shader code is not reused).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from dreamulator.map.noise_kernels import fbm_on_points

__all__ = [
    "Cyclone",
    "composite_alpha",
    "cyclone_alpha",
    "cyclone_clear",
    "cyclone_envelope",
    "holland_b_1980",
    "holland_wind_m_s",
    "synthetic_cyclones",
    "warp_cyclone_texture",
]

CycloneKind = Literal["tropical", "extratropical"]

#: Earth's rotation rate (rad/s); the Coriolis term only shapes the inner core.
_OMEGA = 7.292115e-5
#: Near-surface air density (kg/m³), Holland's reference value.
_AIR_DENSITY_KG_M3 = 1.15

#: Nacrea tropical-cyclone outer cloud shield (km): 2–3× Earth, 1500–2500 km
#: per the GCM scaling note.  The L1 track entry may override it.
_TROPICAL_OUTER_KM = 1800.0


@dataclass(frozen=True)
class Cyclone:
    """One cyclone track entry.

    ``central_pressure_hpa`` and ``environment_pressure_hpa`` set the intensity
    through the pressure deficit; ``rmax_km`` is the radius of maximum wind.
    ``outer_radius_km`` is the cloud-shield scale (tropical) or the comma
    scale (extratropical).  ``motion_*`` orient the asymmetry and the
    extratropical comma.  ``shape_seed`` selects the per-storm geometry
    (eye fraction, band count, pitch, asymmetry); 0 means the fixed defaults.
    """

    lat_deg: float
    lon_deg: float
    kind: CycloneKind = "tropical"
    central_pressure_hpa: float = 970.0
    environment_pressure_hpa: float = 1010.0
    rmax_km: float = 120.0
    outer_radius_km: float = _TROPICAL_OUTER_KM
    motion_east_m_s: float = 0.0
    motion_north_m_s: float = 0.0
    shape_seed: int = 0

    @property
    def deficit_hpa(self) -> float:
        return max(self.environment_pressure_hpa - self.central_pressure_hpa, 0.0)

    @property
    def strength(self) -> float:
        """Template amplitude ∈ [0.15, 1]; 40 hPa deficit saturates."""
        return float(np.clip(self.deficit_hpa / 40.0, 0.15, 1.0))


@dataclass(frozen=True)
class _Shape:
    eye_fraction: float
    band_count: int
    band_pitch: float
    asymmetry: float
    core_scale: float
    shear_phase: float


def _shape_of(cyc: Cyclone) -> _Shape:
    """Per-storm geometry; a track with ``shape_seed=0`` uses fixed defaults.

    Azimuthal wavenumbers 1 and 2 dominate organised tropical-cyclone bands;
    wavenumber 3 and higher are suppressed by filamentation (vortex Rossby
    wave literature), so ``band_count`` is capped at 2.
    """
    if cyc.shape_seed == 0:
        return _Shape(
            eye_fraction=0.24,
            band_count=1,
            band_pitch=3.6,
            asymmetry=0.30,
            core_scale=1.8,
            shear_phase=0.0,
        )
    rng = np.random.default_rng(cyc.shape_seed)
    return _Shape(
        eye_fraction=float(rng.uniform(0.14, 0.30)),
        band_count=int(rng.integers(1, 3)),
        band_pitch=float(rng.uniform(2.4, 5.2)),
        asymmetry=float(rng.uniform(0.20, 0.50)),
        core_scale=float(rng.uniform(3.5, 7.0)),
        shear_phase=float(rng.uniform(0.0, 2.0 * math.pi)),
    )


def holland_b_1980(
    max_wind_m_s: float,
    *,
    central_pressure_hpa: float,
    environment_pressure_hpa: float,
    air_density_kg_m3: float = _AIR_DENSITY_KG_M3,
) -> float:
    """Holland (1980) profile shape ``B`` from the maximum wind and pressure drop.

    Inserting the wind-profile equation at ``r = Rmax`` gives
    ``B = Vmax² · e · ρ / (p_env − p_c)`` (Holland 1980, eqs. 5–6), clipped to
    the published 1.0–2.5 range.  The same formula is used by CLIMADA's
    ``_B_holland_1980``; only the formula is shared, no code.
    """
    dp_pa = max(environment_pressure_hpa - central_pressure_hpa, 0.0) * 100.0
    if dp_pa <= 0.0:
        return 1.0
    b = max_wind_m_s**2 * math.e * air_density_kg_m3 / dp_pa
    return float(np.clip(b, 1.0, 2.5))


def holland_wind_m_s(
    r_km: np.ndarray | float,
    *,
    rmax_km: float,
    central_pressure_hpa: float,
    environment_pressure_hpa: float,
    lat_deg: float,
    b: float = 1.5,
) -> np.ndarray:
    """Holland (1980) gradient-wind speed at radius ``r_km`` (m/s).

    ``b`` is Holland's profile shape parameter (1.0–2.5; 1.5 is the common
    default).  The Coriolis term is kept for inner-core realism; the result is
    clipped at zero on the axis.
    """
    r = np.maximum(np.asarray(r_km, dtype=np.float64), 1.0e-6) * 1000.0
    rmax_m = max(rmax_km, 1.0e-6) * 1000.0
    dp_pa = max(environment_pressure_hpa - central_pressure_hpa, 0.0) * 100.0
    x = (rmax_m / r) ** b
    f = 2.0 * _OMEGA * math.sin(math.radians(lat_deg))
    v = np.sqrt((b / _AIR_DENSITY_KG_M3) * x * dp_pa * np.exp(-x) + (r * f / 2.0) ** 2)
    v = v - r * f / 2.0
    return np.maximum(v, 0.0)


def _latlon_grid(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    lat = 90.0 - (np.arange(height, dtype=np.float64) + 0.5) / height * 180.0
    lon = (np.arange(width, dtype=np.float64) + 0.5) / width * 360.0 - 180.0
    return np.broadcast_to(lat[:, None], (height, width)), np.broadcast_to(
        lon[None, :], (height, width)
    )


def _sphere_xyz(lat_deg: np.ndarray, lon_deg: np.ndarray) -> tuple[np.ndarray, ...]:
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    cos_lat = np.cos(lat)
    return (
        np.ascontiguousarray(cos_lat * np.cos(lon)),
        np.ascontiguousarray(np.sin(lat)),
        np.ascontiguousarray(cos_lat * np.sin(lon)),
    )


def _distance_bearing_km(
    lat0_deg: float, lon0_deg: float, lat_deg: np.ndarray, lon_deg: np.ndarray, radius_km: float
) -> tuple[np.ndarray, np.ndarray]:
    """Great-circle distance (km) and initial bearing (rad) from the centre."""
    lat0 = math.radians(lat0_deg)
    lon0 = math.radians(lon0_deg)
    lat = np.radians(lat_deg)
    dlon = np.radians(lon_deg) - lon0
    a = np.sin((lat - lat0) / 2.0) ** 2 + math.cos(lat0) * np.cos(lat) * np.sin(dlon / 2.0) ** 2
    dist = 2.0 * radius_km * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    bearing = np.arctan2(
        np.sin(dlon) * np.cos(lat),
        math.cos(lat0) * np.sin(lat) - math.sin(lat0) * np.cos(lat) * np.cos(dlon),
    )
    return dist, bearing


def _smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _tropical_template(
    cyc: Cyclone,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    radius_km: float,
    noise: np.ndarray,
    texture: np.ndarray,
    fine: np.ndarray,
    mid: np.ndarray,
) -> np.ndarray:
    dist, bearing = _distance_bearing_km(cyc.lat_deg, cyc.lon_deg, lat_deg, lon_deg, radius_km)
    rmax = max(cyc.rmax_km, 1.0)
    r = dist / rmax
    outer = max(cyc.outer_radius_km, cyc.rmax_km)
    motion_bearing = math.atan2(cyc.motion_east_m_s, cyc.motion_north_m_s)
    rel = bearing - motion_bearing
    shape = _shape_of(cyc)

    # Eye: clear inside the per-storm eye fraction, eyewall ring at Rmax.
    eye_clear = _smoothstep(0.60 * shape.eye_fraction, 1.60 * shape.eye_fraction, r)
    eyewall = np.exp(-(((r - 1.0) / 0.24) ** 2)) * 0.98
    grain = (0.55 + 0.45 * (0.5 + 0.5 * fine)) * (0.70 + 0.30 * (0.5 + 0.5 * mid))
    core = np.exp(-((r / shape.core_scale) ** 2)) * 0.50 * grain

    # Cirrus shield and logarithmic spiral rainbands, bounded by the outer scale.
    # Real storms show one dominant band (wavenumber 1) or a pair (wavenumber 2),
    # strongly asymmetric; three symmetric arms are not observed.  The phase
    # noise warps the bands so they read as ragged cloud streets, not arcs.
    # No circular rim: an elongated, noise-perturbed shield that dissolves into
    # patchy cirrus filaments instead of a smooth radial glow.
    along = dist * np.cos(rel)
    cross = dist * np.sin(rel)
    edge = np.sqrt((along / (1.12 * outer)) ** 2 + (cross / (0.84 * outer)) ** 2)
    edge = edge / (1.0 + 0.18 * noise + 0.10 * np.cos(rel - shape.shear_phase))
    shield_env = 1.0 - _smoothstep(0.98, 1.04, edge)
    phase = (
        float(shape.band_count) * rel + shape.band_pitch * np.log(np.maximum(r, 0.2)) + 2.2 * noise
    )
    bands = (0.5 + 0.5 * np.cos(phase)) ** 1.5 * (0.55 + 0.45 * (0.5 + 0.5 * texture))
    band_env = np.exp(-(((np.log(np.maximum(r, 0.2) / 2.5)) / 1.4) ** 2))
    # One side of the storm carries the organised bands (shear/asymmetry).
    side = 0.5 + 0.5 * np.cos(rel - shape.shear_phase)
    band_weight = 0.60 + 0.40 * side
    # The central overcast/eyewall stays nearly symmetric; the asymmetry lives
    # in the rainbands.  Applying the full asymmetry to the core opened a dark
    # bite beside the eye (user QA 2026-10-21).
    core_asym = 1.0 + 0.03 * np.cos(rel - shape.shear_phase)
    band_asym = 1.0 + 0.40 * shape.asymmetry * np.cos(rel - shape.shear_phase)
    # Dense shield with band gaps: the storm should read as a bright disk
    # carved by dark spiral troughs, not as a faint additive spiral.
    # Spiral gaps carve the shield outside the eyewall but leave the central
    # dense overcast intact; a uniform gap pattern opened a false 400 km hole
    # around the eye (user QA 2026-10-21).
    gap = _smoothstep(0.6, 2.2, r)
    band_pattern = 1.0 - gap * (0.35 * (1.0 - bands * band_weight))
    shield = 1.20 * grain * band_pattern * band_asym
    core_sheet = (core + 0.60 * grain) * band_pattern * shield_env * core_asym
    band_sheet = 0.75 * shield * band_env * shield_env
    sheet = core_sheet + band_sheet

    alpha = np.maximum(eyewall, sheet) * eye_clear
    out: np.ndarray = np.clip(alpha * cyc.strength, 0.0, 1.0)
    return out


def _tangent_coords(
    cyc: Cyclone, lat_deg: np.ndarray, lon_deg: np.ndarray, radius_km: float
) -> tuple[np.ndarray, np.ndarray]:
    """Displacement (km) along and across the translation vector."""
    x, y, z = _sphere_xyz(lat_deg, lon_deg)
    lat0 = math.radians(cyc.lat_deg)
    lon0 = math.radians(cyc.lon_deg)
    cx = math.cos(lat0) * math.cos(lon0)
    cy = math.sin(lat0)
    cz = math.cos(lat0) * math.sin(lon0)
    east = np.array([-math.sin(lon0), 0.0, math.cos(lon0)])
    north = np.array(
        [-math.sin(lat0) * math.cos(lon0), math.cos(lat0), -math.sin(lat0) * math.sin(lon0)]
    )
    dp_x = (x - cx) * radius_km
    dp_y = (y - cy) * radius_km
    dp_z = (z - cz) * radius_km
    dx = dp_x * east[0] + dp_y * east[1] + dp_z * east[2]
    dy = dp_x * north[0] + dp_y * north[1] + dp_z * north[2]

    speed = math.hypot(cyc.motion_east_m_s, cyc.motion_north_m_s)
    if speed > 1.0e-6:
        me = cyc.motion_east_m_s / speed
        mn = cyc.motion_north_m_s / speed
    else:
        me, mn = 1.0, 0.0
    return dx * me + dy * mn, -dx * mn + dy * me


def _extratropical_template(
    cyc: Cyclone,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    radius_km: float,
    noise: np.ndarray,
    texture: np.ndarray,
    fine: np.ndarray,
    mid: np.ndarray,
) -> np.ndarray:
    along, cross = _tangent_coords(cyc, lat_deg, lon_deg, radius_km)

    scale = max(cyc.outer_radius_km, 1.0)
    a = along / scale
    c = cross / scale
    # Main comma head plus a curved trailing tail on the cold side.
    head = np.exp(-((a / 1.1) ** 2 + (c / 0.7) ** 2))
    tail_line = 0.35 * a
    tail = np.exp(-(((c - tail_line) / 0.20) ** 2)) * np.exp(-((a / 1.8) ** 2))
    tail = np.where(a < 0.0, tail, 0.0)  # the tail trails behind the comma head
    comma = np.maximum(head, 0.85 * tail) * (1.0 + 0.3 * np.tanh(c / 0.6))
    # Frontal band along the translation direction.
    front = np.exp(-((c / 0.10) ** 2)) * np.exp(-(((a - 0.15) / 0.9) ** 2))
    # Dry slot: the dark wedge between the cloud head and the trailing cold
    # front is what makes a comma read as a comma (GOES/MODIS references).
    slot_line = -0.55 - 0.20 * a
    slot = (
        np.exp(-(((c - slot_line) / 0.26) ** 2))
        * np.exp(-((a / 1.1) ** 2))
        * (1.0 - _smoothstep(0.10, 0.45, a))
    )
    # Tangent-plane coordinates degenerate at the antipode (the chord vanishes
    # against the local east/north basis), so gate the template by the true
    # great-circle distance before compositing.
    dist, _bearing = _distance_bearing_km(cyc.lat_deg, cyc.lon_deg, lat_deg, lon_deg, radius_km)
    envelope = np.exp(-((dist / (2.2 * scale)) ** 2))
    edge = np.clip(1.0 - 0.75 * slot, 0.0, 1.0)
    grain = (0.50 + 0.50 * (0.5 + 0.5 * fine)) * (0.60 + 0.40 * (0.5 + 0.5 * mid))
    alpha = (0.85 * comma + 0.15 * front) * grain * edge * envelope
    out: np.ndarray = np.clip(alpha * cyc.strength, 0.0, 1.0)
    return out


def cyclone_alpha(
    cyclones: list[Cyclone],
    *,
    height: int,
    width: int,
    radius_km: float,
    seed: int = 41,
) -> np.ndarray:
    """Composite cloud-opacity template for a set of cyclone tracks."""
    if not cyclones:
        return np.zeros((height, width), dtype=np.float64)
    lat_deg, lon_deg = _latlon_grid(height, width)
    x, y, z = _sphere_xyz(lat_deg, lon_deg)
    noise = fbm_on_points(x.ravel(), y.ravel(), z.ravel(), seed=seed, octaves=2).reshape(
        height, width
    )
    texture = fbm_on_points(
        x.ravel(), y.ravel(), z.ravel(), seed=seed + 7, octaves=3, base_freq=32.0
    ).reshape(height, width)
    fine = fbm_on_points(
        x.ravel(),
        y.ravel(),
        z.ravel(),
        seed=seed + 13,
        octaves=4,
        base_freq=64.0,
        persistence=0.6,
    ).reshape(height, width)
    mid = fbm_on_points(
        x.ravel(),
        y.ravel(),
        z.ravel(),
        seed=seed + 19,
        octaves=4,
        base_freq=16.0,
        persistence=0.6,
    ).reshape(height, width)
    total = np.zeros((height, width), dtype=np.float64)
    for cyc in cyclones:
        if cyc.kind == "tropical":
            template = _tropical_template(
                cyc, lat_deg, lon_deg, radius_km, noise, texture, fine, mid
            )
        else:
            template = _extratropical_template(
                cyc, lat_deg, lon_deg, radius_km, noise, texture, fine, mid
            )
        total = 1.0 - (1.0 - total) * (1.0 - template)
    return np.clip(total, 0.0, 1.0)


def cyclone_envelope(
    cyclones: list[Cyclone],
    *,
    height: int,
    width: int,
    radius_km: float,
    seed: int = 41,
) -> np.ndarray:
    """Storm-influence envelope ∈ [0, 1] for compositing.

    Inside this envelope the L2 cloud deck is blended toward the L3 template
    instead of merely adding cloud on top: screening a template over an
    already overcast field leaves only the eye visible (user QA 2026-10-21).
    The envelope is the broad shield/comma footprint, not the bright core.
    """
    if not cyclones:
        return np.zeros((height, width), dtype=np.float64)
    lat_deg, lon_deg = _latlon_grid(height, width)
    x, y, z = _sphere_xyz(lat_deg, lon_deg)
    noise = fbm_on_points(x.ravel(), y.ravel(), z.ravel(), seed=seed, octaves=2).reshape(
        height, width
    )
    env = np.zeros((height, width), dtype=np.float64)
    for cyc in cyclones:
        dist, bearing = _distance_bearing_km(cyc.lat_deg, cyc.lon_deg, lat_deg, lon_deg, radius_km)
        if cyc.kind == "tropical":
            scale = max(cyc.outer_radius_km, cyc.rmax_km)
            shape = _shape_of(cyc)
            rel = bearing - math.atan2(cyc.motion_east_m_s, cyc.motion_north_m_s)
            along = dist * np.cos(rel)
            cross = dist * np.sin(rel)
            edge = np.sqrt((along / (1.12 * scale)) ** 2 + (cross / (0.84 * scale)) ** 2)
            edge = edge / (1.0 + 0.18 * noise + 0.10 * np.cos(rel - shape.shear_phase))
            one = 1.0 - _smoothstep(0.75, 1.08, edge)
        else:
            scale = max(cyc.outer_radius_km, 1.0)
            one = np.exp(-((dist / (1.8 * scale)) ** 2))
        env = np.maximum(env, one)
    return np.clip(env, 0.0, 1.0)


def cyclone_clear(
    cyclones: list[Cyclone],
    *,
    height: int,
    width: int,
    radius_km: float,
) -> np.ndarray:
    """Clear mask: tropical eye plus the extratropical dry slot.

    Screening a template over the L2 deck can only add cloud, so the eye and
    the dry slot have to actively remove the underlying deck; otherwise a
    storm over a cloudy field has no visible eye or comma notch.
    """
    if not cyclones:
        return np.zeros((height, width), dtype=np.float64)
    lat_deg, lon_deg = _latlon_grid(height, width)
    clear = np.zeros((height, width), dtype=np.float64)
    for cyc in cyclones:
        if cyc.kind == "tropical":
            dist, _bearing = _distance_bearing_km(
                cyc.lat_deg, cyc.lon_deg, lat_deg, lon_deg, radius_km
            )
            r = dist / max(cyc.rmax_km, 1.0)
            shape = _shape_of(cyc)
            eye = 1.0 - _smoothstep(0.60 * shape.eye_fraction, 1.60 * shape.eye_fraction, r)
            clear = np.maximum(clear, eye * cyc.strength)
        else:
            along, cross = _tangent_coords(cyc, lat_deg, lon_deg, radius_km)
            a = along / max(cyc.outer_radius_km, 1.0)
            c = cross / max(cyc.outer_radius_km, 1.0)
            slot_line = -0.55 - 0.20 * a
            slot = (
                np.exp(-(((c - slot_line) / 0.26) ** 2))
                * np.exp(-((a / 1.1) ** 2))
                * (1.0 - _smoothstep(0.10, 0.45, a))
            )
            clear = np.maximum(clear, 0.75 * slot * cyc.strength)
    return np.clip(clear, 0.0, 1.0)


def composite_alpha(base: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Screen-composite the L3 template over the L2 opacity.

    The template is weighted by the local L2 opacity so the cyclone inherits
    the texture instead of reading as a flat white brush stroke; over clear
    pixels it still adds 40% of its amplitude.
    """
    textured = template * (0.55 + 0.45 * base)
    return np.clip(1.0 - (1.0 - base) * (1.0 - textured), 0.0, 1.0)


def _sample_equirect(field: np.ndarray, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    """Bilinear sample of an equirectangular field at (lat, lon) degrees."""
    h, w = field.shape
    r = (90.0 - lat_deg) / 180.0 * h - 0.5
    c = (lon_deg + 180.0) / 360.0 * w - 0.5
    r0 = np.floor(r).astype(np.int64)
    c0 = np.floor(c).astype(np.int64)
    fr = r - r0
    fc = c - c0
    r0c = np.clip(r0, 0, h - 1)
    r1c = np.clip(r0 + 1, 0, h - 1)
    c0w = np.mod(c0, w)
    c1w = np.mod(c0 + 1, w)
    sampled: np.ndarray = (
        field[r0c, c0w] * (1 - fr) * (1 - fc)
        + field[r1c, c0w] * fr * (1 - fc)
        + field[r0c, c1w] * (1 - fr) * fc
        + field[r1c, c1w] * fr * fc
    )
    return sampled


def warp_cyclone_texture(
    alpha: np.ndarray,
    cyclones: list[Cyclone],
    *,
    radius_km: float,
) -> np.ndarray:
    """Twist the L2 cloud texture into spirals around each tropical cyclone.

    The storm shield is then grown from the same procedural cloud field as the
    rest of the planet (domain warp), instead of being a separate smooth
    template; the L3 template only supplies the eye, eyewall and band
    modulation on top.
    """
    if not cyclones:
        return alpha
    height, width = alpha.shape
    lat_deg, lon_deg = _latlon_grid(height, width)
    x, y, z = _sphere_xyz(lat_deg, lon_deg)
    out = alpha.copy()
    for cyc in cyclones:
        if cyc.kind != "tropical":
            continue
        dist, _bearing = _distance_bearing_km(cyc.lat_deg, cyc.lon_deg, lat_deg, lon_deg, radius_km)
        scale = max(cyc.outer_radius_km, cyc.rmax_km, 1.0)
        w = np.exp(-((dist / (1.45 * scale)) ** 2))
        if float(w.max()) < 0.01:
            continue
        # Cyclonic twist, stronger toward the centre; sign flips by hemisphere.
        sign = 1.0 if cyc.lat_deg >= 0.0 else -1.0
        twist = (
            0.85
            * sign
            * np.clip(np.log(scale / np.maximum(dist, 0.15 * max(cyc.rmax_km, 1.0))), 0.0, 2.5)
        )
        lat0 = math.radians(cyc.lat_deg)
        lon0 = math.radians(cyc.lon_deg)
        c = np.array(
            [math.cos(lat0) * math.cos(lon0), math.sin(lat0), math.cos(lat0) * math.sin(lon0)]
        )
        p = np.stack([x, y, z], axis=-1)
        dot = p @ c
        cross = np.cross(c, p)
        cos_t = np.cos(twist)[..., None]
        sin_t = np.sin(twist)[..., None]
        pr = p * cos_t + cross * sin_t + c * (dot[..., None] * (1.0 - cos_t))
        lat_r = np.degrees(np.arcsin(np.clip(pr[..., 1], -1.0, 1.0)))
        lon_r = np.degrees(np.arctan2(pr[..., 2], pr[..., 0]))
        sampled = _sample_equirect(out, lat_r, lon_r)
        out = out * (1.0 - w) + sampled * w
    result: np.ndarray = np.clip(out, 0.0, 1.0)
    return result


def _spread_lons(rng: np.random.Generator, n: int) -> list[float]:
    """Evenly spaced longitudes with a random offset and ±quarter-step jitter."""
    step = 360.0 / max(n, 1)
    offset = float(rng.uniform(-180.0, 180.0))
    jitter = rng.uniform(-0.25 * step, 0.25 * step, size=n)
    return [float(v) for v in (offset + np.arange(n) * step + jitter + 180.0) % 360.0 - 180.0]


def synthetic_cyclones(
    seed: int = 31,
    *,
    tropical_per_hemisphere: int = 1,
    extratropical_per_hemisphere: int = 2,
    tropical_scale: float = 1.0,
    extratropical_scale: float = 1.0,
) -> list[Cyclone]:
    """Climatological placeholder tracks for visual QA, not model output.

    Latitude bands follow the GCM scaling note: tropical genesis at 10–25°,
    extratropical storm track at 52–58°.  The extratropical comma scale is
    larger than Earth's because the deformation radius at 55° is about 3×
    Earth's at 45° (``docs/knowledge/climatology/day_length_effects.md``).
    Counts follow the canon: 4–5 tropical storms per local year (a snapshot
    holds about one per hemisphere) and 2–3 extratropical systems per
    hemisphere.  Positions, phases, sizes and intensities are random draws —
    L1 replaces this function with real tracks.
    """
    rng = np.random.default_rng(seed)
    out: list[Cyclone] = []
    for hemi in (1.0, -1.0):
        # Spread the placeholder tracks around each latitude circle; random
        # longitudes clump by chance and turn the storm track into a ring.
        trop_lons = _spread_lons(rng, tropical_per_hemisphere)
        extra_lons = _spread_lons(rng, extratropical_per_hemisphere)
        for lon in trop_lons:
            out.append(
                Cyclone(
                    lat_deg=hemi * float(rng.uniform(10.0, 25.0)),
                    lon_deg=lon,
                    kind="tropical",
                    central_pressure_hpa=float(rng.uniform(950.0, 985.0)),
                    environment_pressure_hpa=1010.0,
                    rmax_km=float(rng.uniform(90.0, 180.0)) * tropical_scale,
                    outer_radius_km=float(rng.uniform(1500.0, 2500.0)) * tropical_scale,
                    motion_east_m_s=float(rng.uniform(2.0, 7.0)) * hemi,
                    motion_north_m_s=float(rng.uniform(-1.0, 1.0)),
                    shape_seed=int(rng.integers(1, 2**31 - 1)),
                )
            )
        for lon in extra_lons:
            out.append(
                Cyclone(
                    lat_deg=hemi * float(rng.uniform(52.0, 58.0)),
                    lon_deg=lon,
                    kind="extratropical",
                    central_pressure_hpa=float(rng.uniform(960.0, 995.0)),
                    environment_pressure_hpa=1010.0,
                    rmax_km=float(rng.uniform(300.0, 600.0)) * extratropical_scale,
                    outer_radius_km=float(rng.uniform(2500.0, 4000.0)) * extratropical_scale,
                    motion_east_m_s=float(rng.uniform(5.0, 12.0)),
                    motion_north_m_s=float(rng.uniform(-2.0, 2.0)) * hemi,
                    shape_seed=int(rng.integers(1, 2**31 - 1)),
                )
            )
    return out
