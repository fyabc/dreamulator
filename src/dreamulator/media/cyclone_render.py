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

``cyclone_wind_field`` exposes the same Holland profile as an east/north
vortex wind on an equirectangular grid, for the L4 cloud-advection prototype:
adding it to the environment wind lets a storm's cloud bands rotate around the
centre while the storm translates with the steering flow.

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
from typing import TYPE_CHECKING, Literal

import numpy as np

from dreamulator.map.noise_kernels import fbm_on_points

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "Cyclone",
    "composite_alpha",
    "cyclone_alpha",
    "cyclone_clear",
    "cyclone_envelope",
    "cyclone_wind_field",
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

#: Extratropical cyclones are front-driven comma clouds; the track's Rmax is a
#: tropical-core scale, so a closed-core vortex would spin the comma like a
#: disc.  The L4 advection therefore suppresses their vortex by default and
#: lets the environment wind shear the front.
_EXTRATROPICAL_VORTEX_SCALE = 0.0


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


def cyclone_wind_field(
    cyclones: Sequence[Cyclone],
    *,
    height: int,
    width: int,
    radius_km: float,
    centers: Sequence[tuple[float, float]] | None = None,
    taper: float = 1.25,
) -> tuple[np.ndarray, np.ndarray]:
    """East/north vortex wind of the storm tracks on an equirectangular grid.

    Each cyclone contributes its Holland (1980) tangential wind around its
    current centre, tapered smoothly to zero between ``0.9 × outer`` and
    ``taper × outer``.  The circulation is counter-clockwise in the northern
    hemisphere and clockwise in the southern hemisphere.  Adding this field to
    the environment wind lets an advected cloud texture rotate around the storm
    while the storm itself translates with the steering flow.

    Extratropical comma clouds are front-driven; their track's ``rmax`` is not
    a closed-core scale, so their vortex is suppressed by default
    (``_EXTRATROPICAL_VORTEX_SCALE = 0``) and the environment wind shears the
    front instead.

    ``centers`` optionally overrides the track positions (for a Lagrangian
    centre that moves during the animation); otherwise each cyclone's
    ``lat_deg``/``lon_deg`` is used.  The profile shape is fixed at Holland's
    common ``B = 1.5``; the cloud template's strength still comes from the
    pressure deficit.
    """
    lat, lon = _latlon_grid(height, width)
    east = np.zeros((height, width), dtype=np.float64)
    north = np.zeros((height, width), dtype=np.float64)
    for index, cyc in enumerate(cyclones):
        if cyc.deficit_hpa <= 0.0:
            continue
        centre = centers[index] if centers is not None else (cyc.lat_deg, cyc.lon_deg)
        centre_lat, centre_lon = float(centre[0]), float(centre[1])
        distance, bearing = _distance_bearing_km(centre_lat, centre_lon, lat, lon, radius_km)
        speed = holland_wind_m_s(
            distance,
            rmax_km=cyc.rmax_km,
            central_pressure_hpa=cyc.central_pressure_hpa,
            environment_pressure_hpa=cyc.environment_pressure_hpa,
            lat_deg=centre_lat,
            b=1.5,
        )
        if cyc.kind == "extratropical":
            speed = speed * _EXTRATROPICAL_VORTEX_SCALE
        weight = 1.0 - _smoothstep(0.9 * cyc.outer_radius_km, taper * cyc.outer_radius_km, distance)
        speed = speed * weight
        sign = 1.0 if centre_lat >= 0.0 else -1.0
        east += -sign * speed * np.cos(bearing)
        north += sign * speed * np.sin(bearing)
    return east, north


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
    eye_r = r / (
        1.0
        + 0.18 * np.cos(2.0 * rel + shape.shear_phase)
        + 0.12 * np.cos(rel - shape.shear_phase)
        + 0.15 * fine
    )
    eye_clear = _smoothstep(0.60 * shape.eye_fraction, 1.60 * shape.eye_fraction, eye_r)
    grain = (0.55 + 0.45 * (0.5 + 0.5 * fine)) * (0.70 + 0.30 * (0.5 + 0.5 * mid))

    # Compact central dense overcast, no filled disk around it.
    core = np.exp(-((r / 2.6) ** 2)) * 1.05 * grain
    r_ew = r + 0.15 * mid + 0.10 * fine
    eyewall = np.exp(-(((r_ew - 1.0) / 0.32) ** 2)) * 0.65
    # Ragged, broken ring: no continuous white circle.
    eyewall = np.clip(
        eyewall
        * (0.40 + 0.60 * (0.5 + 0.5 * fine))
        * (0.55 + 0.45 * (0.5 + 0.5 * np.cos(2.0 * rel + 1.5 * noise))),
        0.0,
        1.0,
    )

    # Band-dominated structure: one dominant log-spiral arm (wavenumber 1 or 2)
    # plus a weaker secondary arm and a ragged outer fade.  The storm is mostly
    # bands with ambient cloud between them, not a bright disk.
    log_r = np.log(np.maximum(r, 0.3))
    phase1 = float(shape.band_count) * rel + shape.band_pitch * log_r + 2.2 * noise + 1.0 * fine
    phase2 = (
        float(shape.band_count + 1) * rel
        + (0.75 * shape.band_pitch + 0.8) * log_r
        + 1.9 * noise
        + 0.9 * fine
        + 2.1
    )
    primary = np.exp(-((1.0 - np.cos(phase1)) / (2.0 * 0.52**2)))
    secondary = np.exp(-((1.0 - np.cos(phase2)) / (2.0 * 0.44**2)))
    # A soft threshold sharpens the band edges; the phase already carries
    # noise, so this does not create a hard geometric contour.
    primary = _smoothstep(0.06, 0.58, primary)
    secondary = _smoothstep(0.06, 0.52, secondary)
    side = 0.5 + 0.5 * np.cos(rel - shape.shear_phase)
    band_weight = 0.55 + 0.45 * side
    band_fade = np.exp(-((dist / (1.20 * outer)) ** 2))
    bands_total = 1.45 * primary * band_weight + 0.95 * secondary * band_weight**1.5
    bands_total *= band_fade * (0.75 + 0.25 * (0.5 + 0.5 * texture)) * grain

    # Thin cirrus veil between bands raises the cloud amount without a disk.
    veil = 0.45 * np.exp(-((dist / (1.00 * outer)) ** 2)) * grain
    # Explicit cirrus filaments: high-azimuthal-wavenumber streaks, broken by
    # noise and elongated tangentially around the storm.
    phase_c = (50.0 + 25.0 * (0.5 + 0.5 * mid)) * rel + 2.0 * log_r + 10.0 * noise + 8.0 * fine
    cirrus = (0.5 + 0.5 * np.cos(phase_c)) ** 4
    cirrus *= 0.40 + 0.60 * (0.5 + 0.5 * mid)
    cirrus_env = (
        np.exp(-((dist / (1.10 * outer)) ** 2)) * _smoothstep(1.2, 2.5, r) * (0.6 + 0.4 * grain)
    )
    cirrus_alpha = 0.18 * cirrus * cirrus_env
    sheet = np.clip(
        np.maximum(np.maximum(core, eyewall), bands_total) + veil + cirrus_alpha,
        0.0,
        1.0,
    )
    alpha = sheet * eye_clear
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


def _comma_geometry(
    cyc: Cyclone,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    radius_km: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Along/across-motion coordinates and great-circle distance for a comma.

    ``a`` is positive in the direction of motion, ``c`` is positive to the left
    of the motion vector; both are normalised by the comma scale.  The true
    distance is returned separately because the tangent-plane coordinates
    degenerate at the antipode.
    """
    along, cross = _tangent_coords(cyc, lat_deg, lon_deg, radius_km)
    scale = max(cyc.outer_radius_km, 1.0)
    a = along / scale
    c = cross / scale
    dist, _bearing = _distance_bearing_km(cyc.lat_deg, cyc.lon_deg, lat_deg, lon_deg, radius_km)
    return a, c, dist, scale


def _comma_twist(
    a: np.ndarray,
    c: np.ndarray,
    noise: np.ndarray,
    texture: np.ndarray | None = None,
    mid: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Differential-rotation domain warp for the comma cloud.

    Rotating the local coordinates by an angle that grows logarithmically with
    radius is the classic twist/domain-warp construction (Terragen-style
    procedural hurricanes; Lygia's spiral SDFs use the same differential
    rotation idea).  A filled cloud head and a cold-front tail are then
    evaluated in the *twisted* frame, so the shield curls into a comma without
    drawing explicit spiral stripes.  Low-frequency noise perturbs the twist
    and the sampling point, which keeps the edges irregular.
    """
    r = np.hypot(a - 0.05, c - 0.08)
    theta = np.arctan2(c - 0.08, a - 0.05)
    alpha = 1.10 * np.log(np.maximum(r, 0.25)) + 0.35 * (noise - 0.5)
    cos_a = np.cos(alpha)
    sin_a = np.sin(alpha)
    at = a * cos_a - c * sin_a
    ct = a * sin_a + c * cos_a
    if texture is not None:
        at = at + 0.12 * (texture - 0.5)
    if mid is not None:
        ct = ct + 0.12 * (mid - 0.5)
    return at, ct, r, theta


def _comma_slot(r: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Curved dry-slot wedge south-east of the low centre."""
    slot = np.exp(-(((theta + 0.55) / 0.52) ** 2))
    slot = slot * _smoothstep(0.10, 0.30, r) * (1.0 - _smoothstep(1.05, 1.35, r))
    return np.asarray(slot, dtype=np.float64)


def _extratropical_template(
    cyc: Cyclone,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    radius_km: float,
    noise: np.ndarray,
    texture: np.ndarray,
    fine: np.ndarray,
    mid: np.ndarray,
    erosion: np.ndarray | None = None,
) -> np.ndarray:
    a, c, dist, scale = _comma_geometry(cyc, lat_deg, lon_deg, radius_km)
    at, ct, r, theta = _comma_twist(a, c, noise, texture, mid)

    # Cloud head evaluated in the twisted frame: a filled shield that curls
    # around the low instead of an ellipse in the unwarped plane.
    head_rho = np.sqrt(((at - 0.10) / 1.10) ** 2 + ((ct - 0.38) / 0.55) ** 2)
    head_rho = head_rho / (1.0 + 0.075 * noise + 0.040 * fine)
    head = 1.0 - _smoothstep(0.86, 1.01, head_rho)

    # Dry slot in the *unwarped* angular coordinate: a sharp wedge south-east
    # of the low, the cloud-free notch that makes the comma read.
    slot = _comma_slot(r, theta)
    comma = head * (1.0 - 0.95 * slot)

    # Cold-front tail in the twisted frame; it curls with the head and leaves
    # the south-west edge as one continuous cloud band.
    tail_axis = -0.28 + 0.45 * at + 0.10 * at * at
    tail = np.exp(-(np.abs((ct - tail_axis) / 0.24) ** 4))
    tail = tail * np.exp(-(((at + 0.85) / 1.15) ** 2)) * (at < 0.25)
    tail = tail * (0.85 + 0.15 * (0.5 + 0.5 * texture))
    comma = np.maximum(comma, 0.95 * tail)

    # Cloud streets parallel to the twisted front, broken by the texture.
    street_phase = 95.0 * ct + 8.0 * at + 4.0 * noise + 2.0 * fine
    streets = (0.5 + 0.5 * np.cos(street_phase)) ** 8
    streets = streets * (0.50 + 0.50 * (0.5 + 0.5 * texture))
    comma = comma + 0.12 * streets * (0.35 * head + 0.65 * tail)
    # Mesoscale holes: break the shield into cloud masses rather than a
    # uniformly filled wash.
    holes = _smoothstep(0.30, 0.62, 0.5 + 0.5 * texture + 0.15 * (noise - 0.5))
    comma = comma * (0.50 + 0.50 * holes) * (0.88 + 0.12 * (0.5 + 0.5 * fine))
    if erosion is not None:
        # L2 carries the erosion/grain/MCC texture; use it to break the shield
        # with the same holes as the surrounding cloud deck.
        comma = comma * (0.50 + 0.50 * erosion)

    # Broad comma footprint for the outer envelope; evaluate it in the same
    # twisted frame so the brightening follows the curl.
    env_at, env_ct, _env_r, _env_theta = _comma_twist(a, c, noise)
    head_env_rho = np.sqrt(((env_at - 0.10) / 1.28) ** 2 + ((env_ct - 0.38) / 0.68) ** 2)
    envelope = 1.0 - _smoothstep(0.86, 1.04, head_env_rho)
    env_axis = -0.28 + 0.45 * env_at + 0.10 * env_at * env_at
    env_tail = np.exp(-(np.abs((env_ct - env_axis) / 0.36) ** 4))
    env_tail = env_tail * np.exp(-(((env_at + 0.85) / 1.35) ** 2)) * (env_at < 0.25)
    envelope = np.maximum(envelope, 0.88 * env_tail)
    envelope = envelope * (1.0 - 0.55 * slot)
    # Antipode gate; the tangent-plane coordinates are meaningless there.
    envelope = envelope * np.exp(-((dist / (2.0 * scale)) ** 4))

    grain = (0.60 + 0.40 * (0.5 + 0.5 * fine)) * (0.75 + 0.25 * (0.5 + 0.5 * mid))
    alpha = (0.98 * comma + 0.06 * streets) * grain * envelope
    # Light unsharp mask: semi-Lagrangian/composite pipelines soften the
    # template edges; a small 3×3 high-pass restores the comma's edge contrast
    # without an explicit contour line.
    blur = (
        alpha
        + np.roll(alpha, 1, axis=0)
        + np.roll(alpha, -1, axis=0)
        + np.roll(alpha, 1, axis=1)
        + np.roll(alpha, -1, axis=1)
    ) / 5.0
    alpha = np.clip(alpha + 0.35 * (alpha - blur), 0.0, 1.0)
    out: np.ndarray = np.clip(alpha * cyc.strength, 0.0, 1.0)
    return out


def cyclone_alpha(
    cyclones: list[Cyclone],
    *,
    height: int,
    width: int,
    radius_km: float,
    seed: int = 41,
    erosion: np.ndarray | None = None,
) -> np.ndarray:
    """Composite cloud-opacity template for a set of cyclone tracks.

    ``erosion`` is an optional 0–1 local-contrast field from the L2 cloud
    texture (``cloud_erosion_field``).  Extratropical templates multiply
    their shield by it so the comma inherits the ambient cloud's holes and
    grain instead of being a separate smooth white brush stroke.
    """
    if erosion is not None and erosion.shape != (height, width):
        raise ValueError("erosion must match the (height, width) template grid")
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
                cyc, lat_deg, lon_deg, radius_km, noise, texture, fine, mid, erosion
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
            a, c, dist, scale = _comma_geometry(cyc, lat_deg, lon_deg, radius_km)
            at, ct, r, theta = _comma_twist(a, c, noise)
            head_env_rho = np.sqrt(((at - 0.10) / 1.28) ** 2 + ((ct - 0.38) / 0.68) ** 2)
            one = 1.0 - _smoothstep(0.86, 1.04, head_env_rho / (1.0 + 0.04 * noise))
            axis = -0.28 + 0.45 * at + 0.10 * at * at
            tail_env = np.exp(-(np.abs((ct - axis) / 0.36) ** 4))
            tail_env = tail_env * np.exp(-(((at + 0.85) / 1.35) ** 2)) * (at < 0.25)
            one = np.maximum(one, 0.88 * tail_env)
            one = one * (1.0 - 0.55 * _comma_slot(r, theta))
            one = one * np.exp(-((dist / (2.0 * scale)) ** 4))
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
            dist, bearing = _distance_bearing_km(
                cyc.lat_deg, cyc.lon_deg, lat_deg, lon_deg, radius_km
            )
            r = dist / max(cyc.rmax_km, 1.0)
            shape = _shape_of(cyc)
            rel = bearing - math.atan2(cyc.motion_east_m_s, cyc.motion_north_m_s)
            eye_r = r / (
                1.0
                + 0.18 * np.cos(2.0 * rel + shape.shear_phase)
                + 0.12 * np.cos(rel - shape.shear_phase)
            )
            eye = 1.0 - _smoothstep(0.60 * shape.eye_fraction, 1.60 * shape.eye_fraction, eye_r)
            clear = np.maximum(clear, 0.90 * eye * cyc.strength)
        else:
            a, c, _dist, _scale = _comma_geometry(cyc, lat_deg, lon_deg, radius_km)
            r = np.hypot(a - 0.05, c - 0.08)
            theta = np.arctan2(c - 0.08, a - 0.05)
            clear = np.maximum(clear, 0.90 * _comma_slot(r, theta) * cyc.strength)
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
