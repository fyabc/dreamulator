"""Monsoon circulation — seasonal thermal-low pressure anomalies and boundary-layer winds.

Pure functions (no IO, no RNG, no mesh dependency), parallel to
``climate_physics.py``.  The orchestration on the CVT mesh (gradients,
coupling into the moisture budget) lives in ``map/climate_simulator.py``.

Physical chain (tech debt 23, roadmap):

1. **Zonal-mean reference** — the monthly zonal-mean temperature per
   latitude band is the "no land-sea contrast" reference state.
2. **Pressure anomaly** — a column warmer than its same-latitude ocean
   reference expands (hydrostatic), lowering surface pressure: a thermal
   low over summer continents, a relative high over winter continents.
   The monthly field carries the *full* land-sea contrast (annual mean
   included — B0b), so the derived annual wind (vector mean of the
   monthly winds) keeps its stationary structure.  The response is
   derived, not tuned:

       ΔP = −P_sfc · E · ΔT / T̄

   with E ≈ 0.104 the boundary-layer projection factor (BL-mean
   amplitude × linear-decay profile over the heat-low depth; see the
   module constants) and T̄ the monthly zonal reference temperature.
   Earth anchor (2026-09-14 Stage-C probe, full-contrast target): Sahara
   July 0.93×, Siberia January 1.08×, Mongolia January 0.80× of the
   observed NCEP land-sea SLP contrast.  Known limitation: wet
   deep-convective systems (India/South-China summer lows, whose latent
   heating projects through the whole column) need E ≈ 0.37-0.40 and are
   undershot ~4× by this dry-BL factor — no Stage-2-available,
   non-circular discriminator separates them (δMCD/δTH decomposition
   2026-09-14), so the monsoon-land amplitude moves to the moisture-
   routing line (D) rather than a per-region ΔP retune.
3. **Boundary-layer momentum balance** — the surface wind answers the
   pressure-gradient force against Coriolis and turbulent drag.  The
   Coriolis acceleration in the right-handed ENU frame is −f k̂×v
   (rightward of the motion for f > 0), so the steady balance is

       0 = G − f k̂×v − k_d·v ,   G = −∇(ΔP)/ρ

   In local east/north components this is a 2×2 linear system with the
   closed-form solution

       v_e = (k_d·G_e + f·G_n) / (k_d² + f²)
       v_n = (k_d·G_n − f·G_e) / (k_d² + f²)

   Two limits with the right physics: f → 0 (equator) gives v = G/k_d,
   a direct down-gradient flow — this is what allows the cross-equatorial
   monsoon current (the Somali-jet analogue); k_d → 0 gives geostrophic
   flow along the isobars, low pressure to the left of the wind in the
   northern hemisphere (Buys-Ballot) — the same convention as
   ``_geostrophic_wind`` in ``map/climate_simulator.py``.  The drag rate
   k_d ≈ C_D·|U|/h_BL ≈ 1.3e-3·8/1000 ≈ 1e-5 s⁻¹ is the inverse
   boundary-layer drag timescale (~1 day), derived from bulk aerodynamic
   surface drag, not calibrated.

**Sign convention.**  The east/north basis used here is the *physical*
one, identical to ``map/ocean_circulation.east_north_basis`` (verified
against NCEP, 2026-09-12) and to ``hadley_cell_wind``: north_t = (0,1,0)
projected onto the tangent plane, east_t = r̂ × north_t = direction of
increasing longitude.  With f = +2Ω·sin(φ) (rotation vector +y, northern
hemisphere at y > 0) the boundary-layer solution below deflects rightward
in the NH — the physical convention.  (Tech debt 24 root unification,
2026-09-13: the basis used to be ``north_t × r̂`` = physical west, which
made the closed-form solution equivalent to f → −f in true geography;
the former claim that ``east_north_basis`` points west was wrong — the
NCEP storage anchor is the authority.)
"""

from __future__ import annotations

import numpy as np

from dreamulator.engine.climate_physics import coriolis_parameter

# Fraction of the atmospheric column whose temperature anomaly projects onto
# surface pressure (hydrostatic), derived from the observed structure of the
# thermal systems (M4, 2026-09-14):
#
#   E = r · [1 − (H/h)·(1 − e^(−h/H))]
#
# * r = ΔT̄_BL / ΔT_sfc — the boundary-layer-mean (virtual) temperature
#   anomaly over the surface land-sea contrast: the surface superadiabatic
#   layer over hot dry ground and the in-layer decay (Lindzen & Nigam 1987,
#   JAS 44:2418: BL anomaly decays to ~70 % of the surface value by 3 km,
#   γ = 0.30, H₀ = 3000 m; ERA5 BL profiles put the layer-mean ratio at
#   0.4-0.6).
# * h = the depth over which the anomaly converges to zero — the heat-low
#   vertical cap at ≤ ~700 hPa (Lavaysse et al. 2009, Climate Dyn. 33:313;
#   observed 1.5-4 km, the circulation closes within the boundary layer,
#   Rácz & Smith 1999, QJRMS 125:225).
#
# With r = 0.6 and h = 3200 m this gives E ≈ 0.104 — the uniform-full-amplitude
# 0.25 (pre-M4) overstated the Sahara July thermal low by ~4-5× (two factors
# of ~2: the uniform in-layer profile, and the surface ΔT standing in for the
# BL mean; lit review 2026-09-14 report 2 §B).  Stage-C anchor check
# (2026-09-14, full land-sea contrast target): Sahara 0.93×, Siberia 1.08×,
# Mongolia 0.80× of the observed NCEP contrast at this value.
_BL_AMPLITUDE_RATIO: float = 0.6
_HEAT_LOW_DEPTH_M: float = 3200.0

# B1 elevation derating scales (m):
# Barometric pressure scale height (standard atmosphere) — an elevated
# cell's surface pressure represents a smaller mass column.
_PRESSURE_SCALE_HEIGHT_M: float = 8500.0
# Moisture scale height: 85% of the atmospheric water vapour resides below
# 3 km (Wu et al. 2012, Sci Rep 2:404, p.3) — heating above the moisture
# ceiling acts on dry air and projects only weakly onto surface pressure
# (Boos & Kuang 2010/2013: the monsoon heat source is the lowland
# non-orographic heating, not the elevated plateau surface).
_MOISTURE_SCALE_HEIGHT_M: float = 3000.0


def _monsoon_projection_fraction() -> float:
    """Lowland column projection factor E (see the M4 constants block)."""
    ratio = 1.0 - (_PRESSURE_SCALE_HEIGHT_M / _HEAT_LOW_DEPTH_M) * (
        1.0 - float(np.exp(-_HEAT_LOW_DEPTH_M / _PRESSURE_SCALE_HEIGHT_M))
    )
    return _BL_AMPLITUDE_RATIO * ratio


_MONSOON_PROJECTION_FRACTION: float = _monsoon_projection_fraction()

# Boundary-layer drag rate k_d = C_D·|U|/h_BL (s⁻¹): bulk drag coefficient
# C_D ≈ 1.3e-3 over open water (smooth surface), |U| ≈ 8 m/s, h_BL ≈ 1 km →
# k_d ≈ 1e-5 s⁻¹, a momentum dissipation timescale of ~1 day.  Over rough
# vegetation C_D is ~20× larger (forest canopy ~0.03), so k_d ≈ 2e-4 s⁻¹.
# Near the equator the balance degenerates to v = G/k_d, so this rate directly
# sets the strength of the cross-equatorial monsoon current — and with a uniform
# open-water rate it over-amplifies the equatorial LAND wind (Amazon) to ~20 m/s
# vs the observed ~1–2 m/s.  Hence the per-cell land/ocean split (see
# docs/knowledge/climatology/atmospheric_circulation.md §4.5).
_DRAG_RATE_S: float = 1.0e-5  # open water (C_D ≈ 1.3e-3)
_DRAG_RATE_LAND_S: float = 2.0e-4  # rough vegetation (C_D ≈ 0.03), ~20× water

# Cross-equatorial westerly drag rate (s⁻¹).  The cross-equatorial monsoon
# current (winter hemisphere → summer ITCZ) is a *deep* tropospheric flow that
# approaches angular-momentum conservation — its effective damping is much
# weaker than the surface boundary layer, with a timescale set by the
# equator→ITCZ crossing (~7 days) rather than the surface drag (~1 day).  The
# value below calibrates the westerly belt so the cross-equatorial belt's
# surface wind reverses from the symmetric Hadley easterly to the observed
# westerly (~+2 m/s over Guinea/India in July, NCEP sig995).  Shared by all
# worlds: on a slow rotator the Coriolis parameter f and the ITCZ excursion
# both shrink, so the belt weakens correspondingly (see the module tests).
_CROSS_EQUATORIAL_DRAG_RATE_S: float = 1.6e-6

# Sea-level air density (kg/m³), same reference as _geostrophic_wind.
_AIR_DENSITY_KG_M3: float = 1.225


def _tangent_basis(nodes_xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Local (east, north) unit basis, same convention as ``hadley_cell_wind``.

    north = (0,1,0) projected to the tangent plane; east = r̂ × north — the
    *physical* east (direction of increasing longitude), matching
    ``map/ocean_circulation.east_north_basis``.  At the poles north is
    degenerate; those cells get world +x as east, zero north — the monsoon
    pressure gradient is weak at the poles, so the choice there is immaterial.

    Args:
        nodes_xyz: Unit sphere positions, shape (N, 3).

    Returns:
        (east, north), each shape (N, 3).
    """
    north = np.array([0.0, 1.0, 0.0]) - nodes_xyz[:, 1:2] * nodes_xyz
    north_norm = np.linalg.norm(north, axis=1)
    pole = north_norm < 1e-9
    north[~pole] /= north_norm[~pole, None]
    north[pole] = 0.0

    east = np.cross(nodes_xyz, north)
    east_norm = np.linalg.norm(east, axis=1)
    ok = east_norm >= 1e-9
    east[ok] /= east_norm[ok, None]
    east[~ok] = 0.0
    east[~ok, 0] = 1.0  # poles: arbitrary but finite
    return east, north


def zonal_mean_monthly(
    t_monthly_c: np.ndarray,
    lat_deg: np.ndarray,
    band_deg: float = 5.0,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Monthly zonal-mean temperature per cell (latitude-band average).

    Bins cells by signed latitude (the hemispheres are averaged
    separately — their land fractions and seasons differ), then assigns
    each cell its band's monthly mean.  Bands without cells are filled
    from the nearest non-empty band.

    Args:
        t_monthly_c: Monthly temperature field (°C), shape (N, 12).
        lat_deg: Latitude in degrees, shape (N,).
        band_deg: Latitude bin width (degrees).
        mask: Optional boolean (N,) — only these cells contribute to the
            band average (e.g. ocean-only, giving each cell its same-
            latitude *ocean* temperature as the land-sea contrast
            reference).  A band with no masked cells falls back to the
            nearest band that has one.

    Returns:
        Zonal-mean temperature per cell and month (°C), shape (N, 12).
    """
    edges = np.arange(-90.0, 90.0 + band_deg, band_deg)
    n_bins = len(edges) - 1
    idx = np.clip(((lat_deg - edges[0]) / band_deg).astype(np.int64), 0, n_bins - 1)

    m = None if mask is None else np.asarray(mask, dtype=bool)
    if m is None or not m.any():
        # No mask (or an all-land world with no reference ocean at all):
        # fall back to the all-cell zonal mean.
        idx_sel = idx
        t_sel = t_monthly_c
    else:
        idx_sel = idx[m]
        t_sel = t_monthly_c[m]
    sums = np.zeros((n_bins, 12), dtype=np.float64)
    counts = np.zeros(n_bins, dtype=np.float64)
    np.add.at(sums, idx_sel, t_sel)
    np.add.at(counts, idx_sel, 1.0)

    filled = counts >= 1
    means = np.zeros((n_bins, 12), dtype=np.float64)
    means[filled] = sums[filled] / counts[filled, None]

    if not filled.all():
        # Fill empty bands from the nearest non-empty one (forward scan,
        # then backward for the leading gap).
        filled_idx = np.flatnonzero(filled)
        for b in np.flatnonzero(~filled):
            nearest = filled_idx[np.argmin(np.abs(filled_idx - b))]
            means[b] = means[nearest]

    return np.asarray(means[idx])


def pressure_anomaly_monthly(
    t_monthly_c: np.ndarray,
    lat_deg: np.ndarray,
    band_deg: float = 5.0,
    surface_pressure_hpa: float = 1013.25,
    elevation_m: np.ndarray | None = None,
    ocean_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Monthly surface pressure from the land-sea heating contrast (hPa).

    ΔT is the cell's departure from the same-latitude ocean zonal mean at
    its month — the *full* land-sea contrast, annual mean included (B0b,
    2026-09-14: the correct algorithm is monthly pressure (full contrast)
    → monthly wind → vector average = annual wind; the former "seasonal
    anomaly only" subtraction zero-meaned the monthly ΔP and made the
    annual vector average collapse onto the pure three-cell background —
    the "annual wind is a textbook three-cell pattern" artifact and the
    wind R² −0.81 metric).  A winter Siberian high now drives its
    north-easterly outflow, and its asymmetric collocation with the summer
    thermal lows gives the annual mean its stationary structure.

    The hydrostatic response to warming the boundary layer by ΔT (M4,
    2026-09-14 — BL-mean amplitude × linear-decay profile, see module
    constants), structured by elevation (B1, 2026-09-13):

        ΔP = −P(z) · f(z) · ΔT / T̄_zonal(m)
        P(z) = P_sfc · exp(−z/H)                    # H = 8.5 km
        f(z) = E · exp(−z/z_moist)                  # E ≈ 0.104, z_moist = 3 km

    with z = max(elevation, 0) and T̄_zonal(m) the zonal reference
    temperature of the same month (the actual column temperature that
    sets the hydrostatic sensitivity).

    The two elevation deratings, both physical:
    * P(z): the surface pressure of an elevated cell already represents a
      smaller mass column — the same fractional expansion moves less mass
      (barometric).
    * f(z)'s exp(−z/z_moist): the monsoon's heat source is the *lowland
      non-orographic* heating — deep convection anchors on the lowland θeb
      maximum and removing the plateau's elevated heating barely weakens
      the South Asian monsoon (Boos & Kuang 2010 Nature / 2013 Sci Rep),
      while 85% of the atmospheric water vapour sits below 3 km (Wu et al.
      2012).  Without it the 4844 m Tibetan surface anomaly dominates ΔP.
      Combined with P(z), a 4.8 km plateau cell responds at ~11% of a
      lowland cell.

    Args:
        t_monthly_c: Monthly temperature field (°C), shape (N, 12).
        lat_deg: Latitude in degrees, shape (N,).
        band_deg: Latitude bin width for the zonal mean.
        surface_pressure_hpa: Sea-level pressure P_sfc.  Scales the
            response linearly, so denser/thinner atmospheres respond
            proportionally.
        elevation_m: Cell elevation (m), shape (N,), clamped at 0 for the
            derating factors.  None → all cells at sea level.
        ocean_mask: Boolean (N,).  When given, the zonal reference is the
            *ocean-only* latitude-band mean (B2): ΔT becomes the land-vs-
            same-latitude-ocean contrast.  The all-cell zonal mean
            self-dilutes in the subtropical desert belt (every 25-35°N
            cell is hot → small departure), which pushed the July
            thermal-low centre to the 40-50°N interior (Karakum) instead
            of the observed Iran/Thar ~30°N lowlands anchored on the
            land-ocean θeb contrast (Boos & Kuang 2010; Geen et al. 2020).

    Returns:
        Monthly pressure ΔP (hPa), shape (N, 12).  Ocean cells are 0 by
        construction (they are their own reference); the 12 months do not
        sum to zero — the annual mean is the stationary land-sea pattern.
    """
    t_zonal = zonal_mean_monthly(t_monthly_c, lat_deg, band_deg, mask=ocean_mask)
    dt = t_monthly_c - t_zonal

    # Hydrostatic sensitivity from the monthly zonal reference temperature.
    t_zonal_k = np.maximum(t_zonal + 273.15, 200.0)
    if elevation_m is None:
        dp = -surface_pressure_hpa * _MONSOON_PROJECTION_FRACTION * dt / t_zonal_k
    else:
        z = np.maximum(np.asarray(elevation_m, dtype=np.float64), 0.0)[:, None]
        p_z = surface_pressure_hpa * np.exp(-z / _PRESSURE_SCALE_HEIGHT_M)
        f_z = _MONSOON_PROJECTION_FRACTION * np.exp(-z / _MOISTURE_SCALE_HEIGHT_M)
        dp = -p_z * f_z * dt / t_zonal_k
    return np.asarray(dp)


def monsoon_boundary_layer_wind(
    grad_dp_pa_m: np.ndarray,
    f_coriolis: np.ndarray,
    nodes_xyz: np.ndarray,
    drag_rate_s: float | np.ndarray = _DRAG_RATE_S,
    air_density_kg_m3: float = _AIR_DENSITY_KG_M3,
    max_speed_m_s: float = 30.0,
) -> np.ndarray:
    """Monthly monsoon wind from the boundary-layer momentum balance.

    Solves  0 = G − f k̂×v − k_d·v  with G = −∇(ΔP)/ρ in closed form per
    month and cell (see module docstring for the two physical limits).
    The input pressure gradient is that of the *full* monthly land-sea
    contrast field (``pressure_anomaly_monthly``, B0b), so the output is
    the monthly thermal-wind component to be added onto the three-cell
    background — their vector average over the 12 months is the annual
    wind (which therefore carries the stationary land-sea structure).

    Args:
        grad_dp_pa_m: Gradient of the monthly pressure anomaly, tangent
            vectors in Pa/m, shape (12, N, 3).
        f_coriolis: Coriolis parameter (rad/s), shape (N,).
        nodes_xyz: Unit sphere node positions, shape (N, 3).
        drag_rate_s: Boundary-layer drag rate k_d (s⁻¹) — a scalar for a
            uniform rate, or a per-cell array shape (N,) to split land
            (rough, high drag) from ocean (smooth, low drag).  The f→0
            degeneracy v = G/k_d makes the equatorial wind ∝ 1/k_d, so a
            land/ocean split is what keeps the Amazon (~1 m/s) below the
            cross-equatorial jet (~10 m/s).
        air_density_kg_m3: Surface air density ρ (kg/m³).
        max_speed_m_s: Speed clamp for the anomaly (m/s).

    Returns:
        Monthly wind vectors (m/s), tangent to the sphere, shape (12, N, 3).
        Sum over months ≠ 0 — the residual is the stationary annual
        component the full-value ΔP is meant to carry.
    """
    east, north = _tangent_basis(nodes_xyz)

    # G = −∇(ΔP)/ρ per month, decomposed into local components.
    g = -grad_dp_pa_m / air_density_kg_m3  # (12, N, 3)
    g_e = np.einsum("mij,ij->mi", g, east)  # (12, N)
    g_n = np.einsum("mij,ij->mi", g, north)

    # Per-cell drag rate: scalar → uniform, array → surface-type dependent.
    if isinstance(drag_rate_s, (int, float)):
        k_d = np.full(f_coriolis.shape, float(drag_rate_s))
    else:
        k_d = np.asarray(drag_rate_s, dtype=np.float64)
    k_d = k_d[None, :]  # (1, N)
    f = f_coriolis[None, :]  # (1, N)
    denom = k_d * k_d + f * f  # (1, N), strictly > 0

    v_e = (k_d * g_e + f * g_n) / denom
    v_n = (k_d * g_n - f * g_e) / denom

    wind = v_e[:, :, None] * east[None, :, :] + v_n[:, :, None] * north[None, :, :]

    speed = np.linalg.norm(wind, axis=2)
    scale = np.where(speed > max_speed_m_s, max_speed_m_s / np.maximum(speed, 1e-12), 1.0)
    wind *= scale[:, :, None]
    return np.asarray(wind)


def cross_equatorial_monsoon_westerly(
    lat_rad: np.ndarray,
    nodes_xyz: np.ndarray,
    itcz_lat_deg: float,
    hadley_extent_deg: float = 30.0,
    rotation_period_days: float = 1.0,
    drag_rate_s: float = _CROSS_EQUATORIAL_DRAG_RATE_S,
) -> np.ndarray:
    """Cross-equatorial monsoon westerlies (seasonal Hadley branch).

    The three-cell circulation's zonal wind (``hadley_cell_wind``) is a
    symmetric easterly in the Hadley belt, so it misses the monsoon's
    signature feature: the low-level cross-equatorial flow from the winter
    hemisphere toward the summer ITCZ is deflected *westward* once it crosses
    the equator — the Somali-jet / Guinea-westerly belt.  This function
    reconstructs that belt from the boundary-layer momentum balance in the
    pure-meridional-gradient limit (G_e = 0):

        u_cross = f · v_n / k_d

    f = 2Ω sin(φ) is the Coriolis parameter at the *absolute* latitude, v_n
    the cross-equatorial meridional wind (the Hadley surface branch toward the
    ITCZ, the same soft-shouldered sine as ``hadley_cell_wind``), and k_d the
    cross-equatorial drag rate (see ``_CROSS_EQUATORIAL_DRAG_RATE_S``).  The
    sign is westerly in both hemispheres — NH: f > 0 and v_n > 0; SH: f < 0
    and v_n < 0 — and it vanishes at the equator (f = 0) and outside the
    cross-equatorial belt (|φ| < |ITCZ| with φ on the ITCZ's side of the
    equator), leaving the trades and the mid-latitude Ferrel cell untouched.
    (The tech-debt-24 "sweeping rain belt" falsification came from moving the
    *whole* circulation with the ITCZ; this is the local reversal only.)

    Args:
        lat_rad: Latitude in radians, shape (N,).
        nodes_xyz: Unit sphere positions, shape (N, 3).
        itcz_lat_deg: ITCZ latitude in degrees (seasonal thermal equator).
        hadley_extent_deg: Hadley cell poleward boundary (°).
        rotation_period_days: Rotation period in Earth days (for f and Ω^⅓).
        drag_rate_s: Cross-equatorial drag rate k_d (s⁻¹).

    Returns:
        Westerly wind vectors (m/s) tangent to the sphere, shape (N, 3);
        non-zero only within the cross-equatorial belt.
    """
    n = len(lat_rad)
    itcz = float(itcz_lat_deg)
    if abs(itcz) < 1e-9:
        return np.zeros((n, 3), dtype=np.float64)

    lat_deg = np.degrees(lat_rad)
    # Cross-equatorial belt: same side of the equator as the ITCZ, equatorward
    # of it (0 < |φ| < |ITCZ|).
    cross = (np.sign(lat_deg) == np.sign(itcz)) & (np.abs(lat_deg) < np.abs(itcz))

    # Cross-equatorial meridional wind v_n — the Hadley surface branch toward
    # the ITCZ, the same soft-shouldered sine as ``hadley_cell_wind``, evaluated
    # on the ITCZ-relative latitude rel = φ − ITCZ.  Within the belt rel has the
    # opposite sign to the ITCZ, so −sign(rel) points toward the ITCZ
    # (northward in NH summer).
    h = float(hadley_extent_deg)
    omega_scale = rotation_period_days ** (1.0 / 3.0)
    m = 1.5 * omega_scale
    shoulder = 0.2

    rel_deg = lat_deg - itcz
    v_n = np.zeros(n, dtype=np.float64)
    sel = cross & (np.abs(rel_deg) < h)
    t = np.abs(rel_deg[sel]) / h
    sin_t = np.sin(np.pi * t)
    v_n[sel] = -np.sign(rel_deg[sel]) * m * sin_t * (shoulder + (1.0 - shoulder) * sin_t)

    f = coriolis_parameter(lat_rad, rotation_period_days)
    u_cross = f * v_n / drag_rate_s  # westerly (eastward) > 0 in both hemispheres

    east, _ = _tangent_basis(nodes_xyz)
    return np.asarray(u_cross[:, None] * east)
