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
   Elevated terrain splits by anomaly sign (B1 warm derating / B4 cold
   airmass decomposition — see ``pressure_anomaly_monthly``).  Earth
   anchors (``scripts/climate/diagnose_monsoon_dp_shape.py``,
   full-contrast target, post-B4 2026-09-25): Sahara July 1.13×,
   Siberia January 1.14× of the observed NCEP land-sea SLP contrast
   (target band 0.8-1.25); Mongolia January 0.58× — below band,
   declared: its obs target is itself a 1.4 km-plateau SLP reduction and
   the Γ·z decomposition removes part of what the reduction convention
   adds back (calibration line, deferred).  Known limitation: wet
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
# BL mean; lit review 2026-09-14 report 2 §B).  Anchor check
# (diagnose_monsoon_dp_shape, full land-sea contrast target, post-B4):
# Sahara 1.13×, Siberia 1.14× of the observed NCEP contrast at this
# value (target band 0.8-1.25); Mongolia 0.58× below band — declared
# (obs target is a plateau-reduction value; calibration line, deferred).
_BL_AMPLITUDE_RATIO: float = 0.6
_HEAT_LOW_DEPTH_M: float = 3200.0

# Standard-atmosphere lapse rate (°C/km) — fallback only when the caller does
# not pass the per-cell lapse field (ICAO standard; equals the default of
# config.lapse_rate_c_km and the cold limit of moist_lapse_rate).  Not a
# tuning parameter: the B4 airmass decomposition consumes the SAME per-cell
# Γ(T) (moist_lapse_rate) the engine's temperature stage applied, so adding
# Γ·z back to ΔT exactly inverts the engine's own altitude cooling.
_STANDARD_LAPSE_C_PER_KM: float = 6.5

# B1 elevation derating scales (m) — warm (convective) anomalies only; the
# cold branch answers through its AIRMASS component with no elevation derating
# (B4, 2026-09-25, see pressure_anomaly_monthly: both scales derive their
# rationale from deep convective heating and do not apply to cold stable
# columns).
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

# Cross-equatorial monsoon southwesterly amplitude (D/F 子项 2, 2026-09-14).
# The cross-equatorial current (winter hemisphere → summer ITCZ) is a deep
# tropospheric flow whose surface wind is a small fraction ε of the angular-
# momentum scale Ω·a at the ITCZ's maximum excursion:
#
#   u_scale = ε_u · Ω a · sin(φ_itcz_max)   # westerly (Coriolis-deflected)
#
# ε ≈ 0.015 is the boundary-layer frictional attenuation (the current is ~2 % of
# the rotational-speed scale), a physical constant shared by every world — Ω and
# the ITCZ excursion carry the world-dependence, so a slow rotator (small Ω,
# small obliquity) gets a proportionally weak current (nacrea ≈ 0.21 m/s, Earth
# ≈ 1.7 m/s).  The amplitude is *not* a function of the local latitude φ, only
# of the ITCZ latitude — this fixes sub-item 1's `f·v_n/k_d`, which grew with
# local f and over-amplified ~6× once the monsoon trough moved poleward.  The
# cross-equatorial belt's zonal wind therefore reverses from the symmetric
# Hadley easterly to the observed westerly (~+2 m/s Guinea/India July, NCEP
# sig995).  (The meridional branch ε_v was falsified this round — the northward
# v lacked the "southward north-of-ITCZ" convergence limb and over-dried Guinea;
# see proposal §5.)
_EPS_U: float = 0.015

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
    lapse_rate_c_per_km: np.ndarray | float | None = None,
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
    constants), structured by elevation with a sign-conditional split
    (B1 2026-09-13 warm branch; B4 2026-09-25 cold branch):

        ΔP = −P_sfc · E · ΔT_eff / T̄_zonal(m) · A(z, ΔT)
        ΔT ≥ 0:  ΔT_eff = ΔT,                 A = exp(−z/H)·exp(−z/z_moist)
        ΔT < 0:  ΔT_eff = min(ΔT + Γ·z, 0),   A = 1
                                            # H = 8.5 km, z_moist = 3 km

    with z = max(elevation, 0), E ≈ 0.104, Γ the per-cell lapse rate the
    engine's temperature stage used (°C/km), and T̄_zonal(m) the zonal
    reference temperature of the same month (the actual column
    temperature that sets the hydrostatic sensitivity).

    The two elevation deratings of the warm branch, both physical:
    * exp(−z/H): the surface pressure of an elevated cell already
      represents a smaller mass column — the same fractional expansion
      moves less mass (barometric).
    * exp(−z/z_moist): the monsoon's heat source is the *lowland
      non-orographic* heating — deep convection anchors on the lowland θeb
      maximum and removing the plateau's elevated heating barely weakens
      the South Asian monsoon (Boos & Kuang 2010 Nature / 2013 Sci Rep),
      while 85% of the atmospheric water vapour sits below 3 km (Wu et al.
      2012).  Without it the 4844 m Tibetan surface anomaly dominates ΔP.
      Combined, a 4.8 km plateau cell responds at ~11% of a lowland cell.

    The cold branch answers through its AIRMASS component only (B4
    2026-09-25): surface cold comes in two kinds — lapse-rate cold
    (elevated terrain / tropical islands: the surface is cold because it
    is high, the column above is ambient, the SLP anomaly ≈ 0) and true
    airmass cold (inversions / polar air: the whole column is colder than
    the environmental lapse profile — the East Antarctic Plateau carries
    Earth's strongest positive SLP anomaly, +28 hPa in July, and the
    winter Siberian high sits at near sea level).  ΔT_airmass = ΔT + Γ·z
    inverts the engine's own altitude cooling *exactly* (the caller
    passes the same per-cell moist_lapse_rate field the temperature stage
    applied — zero new parameters), separating the two: pure lapse cold
    → ΔP = 0; airmass cold → the undiminished sea-level response (under
    SLP semantics a cold column amplifies its anomaly — the warm
    deratings are convective-heating parameterizations, and applying them
    to cold anomalies reversed the E/W Antarctic asymmetry, B3
    diagnostic 2026-09-25; applying no correction at all gave tropical
    elevated terrain spurious permanent highs — nacrea's 7.8 km range
    read +10.6 hPa and drained its equatorial islands, 永耀岛 P
    436→148 mm/yr).  Epistemology: approximate derivation — the airmass
    component is projected through M4's E (whose derivation domain is
    warm BL heating; inheritance declared), and the standard-lapse
    assumption over-corrects deep-inversion plateaux (winter Tibet, the
    Antarctic interior read weak; refinement = the reduction-difference
    term exp(z/H_cold) − exp(z/H_std), registered stage-2 candidate);
    cold-side overshoot where subpolar-low climatology is absent (W
    Antarctic / Greenland) belongs to the missing storm-track stationary
    waves (④ family).  ΔP is continuous everywhere (both branches → 0
    at ΔT_eff = 0); slope kinks are piecewise physics, cf. the land/
    ocean drag-rate split.

    Args:
        t_monthly_c: Monthly temperature field (°C), shape (N, 12).
        lat_deg: Latitude in degrees, shape (N,).
        band_deg: Latitude bin width for the zonal mean.
        surface_pressure_hpa: Sea-level pressure P_sfc.  Scales the
            response linearly, so denser/thinner atmospheres respond
            proportionally.
        elevation_m: Cell elevation (m), shape (N,), clamped at 0 for the
            warm-branch derating factors.  None → all cells at sea level.
        lapse_rate_c_per_km: Per-cell lapse rate (°C/km) the engine's
            temperature stage applied (``moist_lapse_rate``), shape (N,)
            or scalar — the B4 cold-branch airmass decomposition adds
            Γ·z back onto ΔT.  None → the 6.5 °C/km standard atmosphere.
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
        # B4 airmass decomposition (cold branch): undo the engine's own
        # altitude cooling Γ·z — lapse-explained surface cold leaves the
        # column ambient (no SLP anomaly); only genuine airmass cold drives
        # the high.  Γ is the caller's per-cell moist_lapse_rate field (the
        # exact one the temperature stage used), so this inverts it exactly.
        if lapse_rate_c_per_km is None:
            lapse_c_km = np.full(dt.shape[0], _STANDARD_LAPSE_C_PER_KM)
        else:
            lapse_c_km = np.asarray(lapse_rate_c_per_km, dtype=np.float64) * np.ones(dt.shape[0])
        dt_airmass = dt + lapse_c_km[:, None] * z / 1000.0
        dt_eff = np.where(dt >= 0.0, dt, np.minimum(dt_airmass, 0.0))
        # Warm anomalies keep the calibrated convective derating (B1).
        atten = np.where(
            dt >= 0.0,
            np.exp(-z / _PRESSURE_SCALE_HEIGHT_M) * np.exp(-z / _MOISTURE_SCALE_HEIGHT_M),
            1.0,
        )
        dp = -surface_pressure_hpa * _MONSOON_PROJECTION_FRACTION * dt_eff / t_zonal_k * atten
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


def monsoon_trough_latitude(
    t_c: np.ndarray,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    ocean_mask: np.ndarray,
    itcz_ocean_deg: float,
    band_deg: float = 10.0,
    damping: float = 0.9,
    sh_ocean_thresh: float = 0.5,
    nh_land_thresh: float = 0.3,
    eq_ocean_thresh: float = 0.7,
) -> np.ndarray:
    """Monsoon-trough latitude (the ITCZ's land northward shift), per cell.

    The monsoon trough is the ITCZ shifted poleward over land by the stronger
    summer surface heating of low-heat-capacity ground — India's July land
    temperature peaks at 24–28°N vs the ocean ITCZ at ~14°N.  This function
    derives the trough latitude per longitude band from the engine's own
    temperature field (first-principles, no tuning per world): within each
    longitude band, if (and only if) it is a **cross-equatorial monsoon**
    sector — southern-hemisphere ocean (the trade-wind moisture source) *and*
    northern-hemisphere land (the heated sink) — the trough latitude is the
    temperature-weighted latitude of the warm northern land, else it falls back
    to the ocean ITCZ.  This is the discriminator that keeps India/West Africa/
    Southeast Asia (cross-equatorial) shifting poleward while South China /
    East Asia (subtropical-high south-easterlies, no SH ocean source) do not.

    Args:
        t_c: Monthly temperature field (°C), shape (N,) — one month.
        lat_deg: Latitude in degrees, shape (N,).
        lon_deg: Longitude in degrees, shape (N,) (any sign convention).
        ocean_mask: Boolean ocean mask, shape (N,).
        itcz_ocean_deg: Ocean ITCZ latitude for this month (°).
        band_deg: Longitude band width (°).
        damping: Fraction of the land-temperature-peak latitude the trough
            reaches (convective heating lags the surface maximum).
        sh_ocean_thresh: Minimum southern-hemisphere ocean fraction for a band
            to count as having a cross-equatorial trade-wind source.
        nh_land_thresh: Minimum northern-hemisphere land fraction for a band to
            count as having a heated land sink.
        eq_ocean_thresh: Minimum equatorial (−5°…5°) ocean fraction — an
            unblocked cross-equatorial corridor.  South China / East Asia sit
            behind the Indonesian archipelago (equatorial land ~50 %), so their
            equatorial-ocean fraction is low and the belt does not shift there.

    Returns:
        Monsoon-trough latitude per cell (°), shape (N,) — ≥ ``itcz_ocean_deg``.
    """
    lon = np.where(lon_deg < 0.0, lon_deg + 360.0, lon_deg)
    n_bands = int(round(360.0 / band_deg))
    band_idx = np.clip((lon / band_deg).astype(np.int64), 0, n_bands - 1)
    is_land = ~np.asarray(ocean_mask, dtype=bool)
    t = np.asarray(t_c, dtype=np.float64)

    # Cross-equatorial monsoon sector: SH ocean (source) + NH land (sink) +
    # an unblocked equatorial ocean corridor (no land damming the flow).
    sh = lat_deg < -5.0
    eq = (lat_deg > -5.0) & (lat_deg < 5.0)
    nh = lat_deg > 5.0
    sh_ocean = sh & ~is_land
    nh_land = nh & is_land
    eq_ocean = eq & ~is_land
    sh_count = np.bincount(band_idx, weights=sh.astype(np.float64), minlength=n_bands)
    sh_oc = np.bincount(band_idx, weights=sh_ocean.astype(np.float64), minlength=n_bands)
    eq_count = np.bincount(band_idx, weights=eq.astype(np.float64), minlength=n_bands)
    eq_oc = np.bincount(band_idx, weights=eq_ocean.astype(np.float64), minlength=n_bands)
    nh_count = np.bincount(band_idx, weights=nh.astype(np.float64), minlength=n_bands)
    nh_ld = np.bincount(band_idx, weights=nh_land.astype(np.float64), minlength=n_bands)
    sh_ocean_frac = sh_oc / np.maximum(sh_count, 1e-9)
    eq_ocean_frac = eq_oc / np.maximum(eq_count, 1e-9)
    nh_land_frac = nh_ld / np.maximum(nh_count, 1e-9)
    cross_eq = (
        (sh_ocean_frac > sh_ocean_thresh)
        & (eq_ocean_frac > eq_ocean_thresh)
        & (nh_land_frac > nh_land_thresh)
    )

    # Land temperature-peak latitude: warm (T > 20 °C) northern land, weighted
    # by T² so the hottest cells dominate the mean (India July → ~24°N).
    w = np.where(nh_land, np.maximum(t - 20.0, 0.0) ** 2, 0.0)
    sum_w = np.bincount(band_idx, weights=w, minlength=n_bands)
    sum_wlat = np.bincount(band_idx, weights=w * lat_deg, minlength=n_bands)
    land_peak = sum_wlat / np.maximum(sum_w, 1e-9)

    trough_band = np.where(
        cross_eq,
        np.maximum(itcz_ocean_deg, land_peak * damping),
        itcz_ocean_deg,
    )
    # One pass of neighbour smoothing, but only *within* cross-equatorial bands:
    # a non-cross-equatorial band (e.g. South China, behind the Indonesian
    # archipelago) stays at the ocean ITCZ and is not pulled poleward by an
    # adjacent cross-equatorial band (the Philippines / SE Asia).
    nbr = 0.5 * (np.roll(trough_band, 1) + np.roll(trough_band, -1))
    trough_band = np.where(cross_eq, 0.5 * trough_band + 0.5 * nbr, itcz_ocean_deg)
    return np.asarray(trough_band[band_idx])


def cross_equatorial_monsoon_wind(
    lat_rad: np.ndarray,
    nodes_xyz: np.ndarray,
    itcz_lat_deg: float,
    radius_km: float,
    rotation_period_days: float,
    itcz_max_deg: float,
    background_wind: np.ndarray,
) -> np.ndarray:
    """Cross-equatorial monsoon westerlies (seasonal Hadley branch).

    The three-cell circulation's zonal wind (``hadley_cell_wind``) is a
    symmetric easterly in the Hadley belt, so it misses the monsoon's
    signature feature: the low-level cross-equatorial flow from the winter
    hemisphere toward the summer ITCZ, deflected *westward* once it crosses the
    equator — the Somali-jet / Guinea-westerly belt.  This function returns the
    belt's net westerly **with the background zonal wind replaced** within the
    belt (``background_wind`` is subtracted there, so adding the result to the
    background yields exactly the westerly).

    The amplitude is a scale shared by every world (see ``_EPS_U``):

        u_scale = ε_u · Ω a · sin(φ_itcz_max)

    with the bell `g = sin(π·|φ|/|φ_trough|)` (0 at the equator and the trough,
    peak mid-belt).  The amplitude depends only on the *maximum ITCZ excursion*
    (Ω and obliquity), not on the local latitude — sub-item 1's `f·v_n/k_d`
    grew with local f and over-amplified once the trough moved poleward.

    (2026-09-14 否证记录：跨赤道流的**经向支**（v toward the ITCZ）与**季风槽
    北移**（陆地温度峰值）已否证——v 向北缺「ITCZ 北侧向南」的辐合结构导致几内亚
    辐散，季风槽用温度峰值无法区分湿润对流 vs 干热沙漠；两者属「稳态耦合」大工程，
    见 proposal §5。本函数只保留纬向 u 反转，经向辐合仍由背景三圈环流承担。）

    Args:
        lat_rad: Latitude in radians, shape (N,).
        nodes_xyz: Unit sphere positions, shape (N, 3).
        itcz_lat_deg: Ocean ITCZ latitude in degrees (scalar, one month).
        radius_km: Planet radius (km) for the rotational-speed scale Ω a.
        rotation_period_days: Rotation period in Earth days.
        itcz_max_deg: Maximum ITCZ excursion (°, the ocean ITCZ's seasonal
            amplitude) for the amplitude scale.
        background_wind: Background (annual three-cell) wind, shape (N, 3) —
            subtracted within the belt so the result *replaces* it there.

    Returns:
        Wind vectors (m/s) tangent to the sphere, shape (N, 3); non-zero only
        within the cross-equatorial belt, where adding them to
        ``background_wind`` yields the net westerly.
    """
    n = len(lat_rad)
    itcz = float(itcz_lat_deg)
    lat_deg = np.degrees(lat_rad)

    # Cross-equatorial belt: same side of the equator as the ITCZ, equatorward
    # of it (0 < |φ| < |ITCZ|).
    belt = (
        (np.sign(lat_deg) == np.sign(itcz)) & (np.abs(lat_deg) < np.abs(itcz)) & (abs(itcz) > 1e-9)
    )

    # Bell g = sin(π·|φ|/|ITCZ|), 0 at equator and ITCZ, peak mid-belt.
    g = np.zeros(n, dtype=np.float64)
    ratio = np.abs(lat_deg[belt]) / abs(itcz)
    g[belt] = np.sin(np.pi * ratio)

    omega_a = 2.0 * np.pi * radius_km * 1000.0 / (rotation_period_days * 86400.0)
    sin_max = float(np.sin(np.radians(abs(itcz_max_deg))))
    u_scale = _EPS_U * omega_a * sin_max  # westerly (eastward)

    east, _ = _tangent_basis(nodes_xyz)
    u_cross = u_scale * g
    # Replace only the *zonal* component (keep the background meridional branch,
    # which carries the Hadley convergence structure): west = (u_cross − bg_e)·east.
    bg_east = np.einsum("ij,ij->i", background_wind, east)
    west = (u_cross - bg_east)[:, None] * east
    return np.asarray(np.where(belt[:, None], west, 0.0))
