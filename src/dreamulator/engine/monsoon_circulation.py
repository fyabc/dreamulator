"""Monsoon circulation — seasonal thermal-low pressure anomalies and boundary-layer winds.

Pure functions (no IO, no RNG, no mesh dependency), parallel to
``climate_physics.py``.  The orchestration on the CVT mesh (gradients,
coupling into the moisture budget) lives in ``map/climate_simulator.py``.

Physical chain (tech debt 23, roadmap):

1. **Zonal-mean reference** — the monthly zonal-mean temperature per
   latitude band is the "no land-sea contrast" reference state.
2. **Pressure anomaly** — a column warmer than the zonal mean expands
   (hydrostatic), lowering surface pressure: a thermal low over summer
   continents, a relative high over winter continents and cool oceans.
   The response is derived, not tuned:

       ΔP = −P_sfc · (d/H) · ΔT / T̄

   with d/H = ``depth_fraction`` the fraction of the atmospheric column
   whose temperature anomaly projects onto surface pressure (monsoon
   thermal anomalies occupy the lowest ~2 km of an ~8.5 km scale height,
   hence the default 0.25), and T̄ the zonal-mean absolute temperature.
   Earth check: ΔT = +5 K over 293 K mean gives −4.3 hPa, the right
   order for the Asian summer thermal low (~5 hPa below the surrounding
   ocean).
3. **Boundary-layer momentum balance** — the surface wind answers the
   pressure-gradient force against Coriolis and turbulent drag:

       0 = G − f k̂×v − k_d·v ,   G = −∇(ΔP)/ρ

   In local east/north components this is a 2×2 linear system with the
   closed-form solution

       v_e = (k_d·G_e + f·G_n) / (k_d² + f²)
       v_n = (k_d·G_n − f·G_e) / (k_d² + f²)

   Two limits with the right physics: f → 0 (equator) gives v = G/k_d,
   a direct down-gradient flow — this is what allows the cross-equatorial
   monsoon current (the Somali-jet analogue); k_d → 0 gives geostrophic
   flow along the isobars.  The drag rate k_d ≈ C_D·|U|/h_BL ≈
   1.3e-3·8/1000 ≈ 1e-5 s⁻¹ is the inverse boundary-layer drag timescale
   (~1 day), derived from bulk aerodynamic surface drag, not calibrated.

**Sign convention.**  The east/north basis used here is the same as
``hadley_cell_wind`` in ``climate_physics.py``: north_t = (0,1,0)
projected onto the tangent plane, east_t = north_t × r̂.  This basis is a
right-handed ENU frame (east × north = up), which with f = +2Ω·sin(φ)
(rotation vector +y, northern hemisphere at y > 0) gives rightward
Coriolis deflection — the physical convention.  Note that
``map/ocean_circulation.east_north_basis`` currently points the *other*
way (it returns the direction of increasing longitude, which on this
mesh's lon = atan2(z, x) labeling is physical west); see the convention
audit note in today.md before mixing components from the two bases.
"""

from __future__ import annotations

import numpy as np

# Fraction of the atmospheric column whose temperature anomaly projects
# onto surface pressure (hydrostatic).  Monsoon thermal anomalies are
# tropospheric but bottom-heavy: the boundary layer plus the lower free
# troposphere, ~2 km of an ~8.5 km scale height.
_MONSOON_DEPTH_FRACTION: float = 0.25

# Boundary-layer drag rate k_d = C_D·|U|/h_BL (s⁻¹): bulk drag coefficient
# C_D ≈ 1.3e-3 (open water and smooth terrain; the rough-vegetated value
# ~2.5e-3 would halve the anomaly again), surface wind |U| ≈ 8 m/s,
# boundary-layer depth h_BL ≈ 1 km → k_d ≈ 1e-5 s⁻¹, a momentum dissipation
# timescale of ~1 day.  Near the equator the balance degenerates to v = G/k_d,
# so this rate directly sets the strength of the cross-equatorial monsoon
# current; the plausible range (C_D 1.3–2.5e-3, |U| 6–10 m/s, h_BL 0.8–1.5 km)
# spans k_d ≈ 0.9–3e-5 s⁻¹.
_DRAG_RATE_S: float = 1.0e-5

# Sea-level air density (kg/m³), same reference as _geostrophic_wind.
_AIR_DENSITY_KG_M3: float = 1.225


def _tangent_basis(nodes_xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Local (east, north) unit basis, same convention as ``hadley_cell_wind``.

    north = (0,1,0) projected to the tangent plane; east = north × r̂.
    Right-handed ENU (east × north = r̂).  At the poles north is degenerate;
    those cells get world +x as east, zero north — the monsoon pressure
    gradient is weak at the poles, so the choice there is immaterial.

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

    east = np.cross(north, nodes_xyz)
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

    Returns:
        Zonal-mean temperature per cell and month (°C), shape (N, 12).
    """
    edges = np.arange(-90.0, 90.0 + band_deg, band_deg)
    n_bins = len(edges) - 1
    idx = np.clip(((lat_deg - edges[0]) / band_deg).astype(np.int64), 0, n_bins - 1)

    sums = np.zeros((n_bins, 12), dtype=np.float64)
    counts = np.zeros(n_bins, dtype=np.float64)
    np.add.at(sums, idx, t_monthly_c)
    np.add.at(counts, idx, 1.0)

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
    depth_fraction: float = _MONSOON_DEPTH_FRACTION,
) -> np.ndarray:
    """Monthly surface-pressure anomaly from seasonal heating contrasts (hPa).

    ΔT is the cell's departure from the zonal mean at its latitude and
    month — the land-sea / surface-type heating contrast.  Its annual
    mean is then subtracted: the annual-mean pressure pattern already
    drives the annual geostrophic wind upstream, so only the *seasonal*
    anomaly belongs here (no double counting).

    The hydrostatic surface response to warming the lowest
    ``depth_fraction`` of the column by ΔT is

        ΔP = −P_sfc · depth_fraction · ΔT / T̄_zonal

    (fractional column expansion ΔT/T̄ applied to the fraction of the
    column that couples to surface pressure; T̄_zonal is the *annual-mean*
    zonal temperature, so the 12 monthly anomalies sum to exactly zero
    per cell).  Warmer → lower pressure (thermal low); colder → higher
    pressure.

    Args:
        t_monthly_c: Monthly temperature field (°C), shape (N, 12).
        lat_deg: Latitude in degrees, shape (N,).
        band_deg: Latitude bin width for the zonal mean.
        surface_pressure_hpa: Sea-level pressure P_sfc.  Scales the
            response linearly, so denser/thinner atmospheres respond
            proportionally.
        depth_fraction: Fraction of the column coupling to surface
            pressure (see module docstring).

    Returns:
        Monthly pressure anomaly ΔP (hPa), shape (N, 12).  The 12 months
        sum to ≈ 0 at every cell.
    """
    t_zonal = zonal_mean_monthly(t_monthly_c, lat_deg, band_deg)
    dt = t_monthly_c - t_zonal
    # Seasonal anomaly only: remove the annual mean of the land-sea contrast.
    dt = dt - dt.mean(axis=1, keepdims=True)

    # Sensitivity factor from the annual-mean zonal temperature: the monthly
    # ΔT already averages to zero per cell, and a fixed T̄ keeps ΔP exactly
    # anomaly-only (12 months sum to zero).  Using the monthly T̄ would leak a
    # ~0.5 hPa annual residual through the 1/T̄ modulation.
    t_zonal_k = np.maximum(t_zonal.mean(axis=1, keepdims=True) + 273.15, 200.0)
    dp = -surface_pressure_hpa * depth_fraction * dt / t_zonal_k
    return np.asarray(dp)


def monsoon_boundary_layer_wind(
    grad_dp_pa_m: np.ndarray,
    f_coriolis: np.ndarray,
    nodes_xyz: np.ndarray,
    drag_rate_s: float = _DRAG_RATE_S,
    air_density_kg_m3: float = _AIR_DENSITY_KG_M3,
    max_speed_m_s: float = 30.0,
) -> np.ndarray:
    """Monthly monsoon wind anomaly from the boundary-layer momentum balance.

    Solves  0 = G − f k̂×v − k_d·v  with G = −∇(ΔP)/ρ in closed form per
    month and cell (see module docstring for the two physical limits).
    The input pressure gradient is already the gradient of the *seasonal
    anomaly* field (``pressure_anomaly_monthly``), so the output is a wind
    anomaly to be added onto the annual background wind.

    Args:
        grad_dp_pa_m: Gradient of the monthly pressure anomaly, tangent
            vectors in Pa/m, shape (12, N, 3).
        f_coriolis: Coriolis parameter (rad/s), shape (N,).
        nodes_xyz: Unit sphere node positions, shape (N, 3).
        drag_rate_s: Boundary-layer drag rate k_d (s⁻¹).
        air_density_kg_m3: Surface air density ρ (kg/m³).
        max_speed_m_s: Speed clamp for the anomaly (m/s).

    Returns:
        Monthly wind anomaly vectors (m/s), tangent to the sphere,
        shape (12, N, 3).  Sum over months ≈ 0 (anomaly field).
    """
    east, north = _tangent_basis(nodes_xyz)

    # G = −∇(ΔP)/ρ per month, decomposed into local components.
    g = -grad_dp_pa_m / air_density_kg_m3  # (12, N, 3)
    g_e = np.einsum("mij,ij->mi", g, east)  # (12, N)
    g_n = np.einsum("mij,ij->mi", g, north)

    k_d = drag_rate_s
    f = f_coriolis[None, :]  # (1, N)
    denom = k_d * k_d + f * f  # (1, N), strictly > 0

    v_e = (k_d * g_e + f * g_n) / denom
    v_n = (k_d * g_n - f * g_e) / denom

    wind = v_e[:, :, None] * east[None, :, :] + v_n[:, :, None] * north[None, :, :]

    speed = np.linalg.norm(wind, axis=2)
    scale = np.where(speed > max_speed_m_s, max_speed_m_s / np.maximum(speed, 1e-12), 1.0)
    wind *= scale[:, :, None]
    return np.asarray(wind)
