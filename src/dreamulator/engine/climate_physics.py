"""Climate physics — pure functions for EBM, wind, precipitation, and ocean currents.

All functions are deterministic (no RNG, no I/O).  They operate on numpy arrays
and are designed to be applied to the CVT mesh node fields (elevation, latitude,
longitude, land/ocean mask).

References:
    - Energy Balance Model: https://en.wikipedia.org/wiki/Energy_balance_model
    - Atmospheric Circulation: https://en.wikipedia.org/wiki/Atmospheric_circulation
    - Orographic Lift: https://en.wikipedia.org/wiki/Orographic_lift
    - Köppen Climate Classification: https://en.wikipedia.org/wiki/K%C3%B6ppen_climate_classification
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

# Stefan-Boltzmann constant (W / m² / K⁴)
SIGMA_SB: float = 5.670374419e-8

# Solar constant at 1 AU (W / m²)
SOLAR_CONSTANT: float = 1361.0

# Earth's equilibrium blackbody temperature without atmosphere (K)
EARTH_BLACKBODY_TEMP_K: float = 255.0

# Earth mean surface temperature with greenhouse (K) → 288 K = 15 °C
EARTH_SURFACE_TEMP_K: float = 288.0

# Air density at sea level (kg / m³)
AIR_DENSITY: float = 1.225

# Specific heat capacity of air (J / kg / K)
CP_AIR: float = 1005.0


# ---------------------------------------------------------------------------
# 1. Temperature — Energy Balance Model (EBM)
# ---------------------------------------------------------------------------


def equilibrium_temperature(
    stellar_luminosity_sol: float = 1.0,
    orbital_distance_au: float = 1.0,
    albedo: float = 0.3,
) -> float:
    """Planet equilibrium blackbody temperature (K) from stellar irradiance.

    T_eq = (L_* / (16 π σ d²))^(1/4)

    Args:
        stellar_luminosity_sol: Stellar luminosity in solar units (1.0 = Sun).
        orbital_distance_au: Semi-major axis in AU.
        albedo: Bond albedo (0–1).  Earth ≈ 0.306.

    Returns:
        Equilibrium temperature in Kelvin.
    """
    # Stellar flux at planet distance
    flux = SOLAR_CONSTANT * stellar_luminosity_sol / (orbital_distance_au**2)
    # Absorbed flux (after albedo)
    absorbed = flux * (1.0 - albedo) / 4.0  # factor 1/4 for sphere vs disk
    return float((absorbed / SIGMA_SB) ** 0.25)


def surface_temperature(
    teq_kelvin: float,
    greenhouse_warming_K: float = 33.0,
) -> float:
    """Surface temperature with greenhouse effect.

    T_surface = T_eq + greenhouse_warming

    Args:
        teq_kelvin: Equilibrium (blackbody) temperature in K.
        greenhouse_warming_K: Additional greenhouse warming in K.  Earth ≈ 33 K.

    Returns:
        Mean surface temperature in Kelvin.
    """
    return teq_kelvin + greenhouse_warming_K


def latitude_temperature(
    t_surface_mean_c: np.ndarray | float,
    lat_rad: np.ndarray,
    lat_gradient_c: float = 40.0,
) -> np.ndarray:
    """Apply latitude-dependent temperature gradient.

    T(lat) = T_eq - ΔT_lat × sin²(lat)

    where T_eq = T_mean + ΔT_lat / 3 (because the area-weighted mean of
    sin²(φ) over the sphere is 1/3).  This gives equator ≈ 30 °C and
    pole ≈ -15 °C when T_mean = 15 °C and ΔT = 45 °C.  Earth's actual
    equator-to-pole ΔT is ~40–50 °C; the default 40 is a calibration value.

    The sin²(φ) dependence comes from the latitudinal distribution of
    annual-mean insolation.

    Args:
        t_surface_mean_c: **Global mean** surface temperature (°C).
        lat_rad: Latitude in radians, shape (N,).
        lat_gradient_c: Equator-to-pole temperature difference (°C).
            Earth ≈ 45 °C.

    Returns:
        Temperature at each latitude (°C), shape (N,).
    """
    t_surface = np.asarray(t_surface_mean_c, dtype=np.float64)
    # Convert global mean to equatorial baseline
    t_equator = t_surface + lat_gradient_c / 3.0
    return np.asarray(t_equator - lat_gradient_c * np.sin(lat_rad) ** 2)


def moist_lapse_rate(
    temperature_c: np.ndarray,
    *,
    gamma_max: float = 6.5,
    gamma_min: float = 4.5,
    t_mid_c: float = 10.0,
    t_width_c: float = 8.0,
) -> np.ndarray:
    """Temperature-dependent moist-adiabatic lapse rate (°C / km).

    Warm air holds more moisture → more latent heat release during ascent →
    lower effective lapse rate.  A logistic between the warm (moist) and
    cold (dry) limits, bounded to [Γ_min, Γ_max] by construction:

        Γ(T) = Γ_min + (Γ_max − Γ_min) · σ((T_mid − T) / T_width)

        T =  27 °C → 4.7 °C/km  (tropical sea-level reference)
        T =  10 °C → 5.5 °C/km
        T =   0 °C → 6.1 °C/km
        T = −20 °C → 6.5 °C/km  (polar / ice sheet — standard value)

    The station-implied effective surface lapse splits along temperature,
    not latitude (2026-09-11 highland diagnostic, earth climate-dev):
    tropical highlands ~4.2–5.2 °C/km (Quito/Cusco/Addis/Altiplano), mid
    and high latitude ~6+ — matching this curve.  This replaces both the
    constant 6.5 and the former hard [15°, 35°] subtropical band (whose
    edges printed artificial step lines across Tibet/Andes/Rockies).  The
    former exponential interpolation was inverted (warm → steep) and went
    unphysical (Γ < 0 below ~−12 °C), forcing callers to clip.

    For planets with different gravity the limits scale with g/g⊕ because
    the dry adiabatic lapse rate Γ_d = g / cp.  Pass ``gamma_max`` and
    ``gamma_min`` scaled accordingly.

    Args:
        temperature_c: Surface air temperature (°C), shape (N,).
        gamma_max: Lapse rate in the cold (dry) limit (°C/km).
        gamma_min: Lapse rate in the warm (moist) limit (°C/km).
        t_mid_c: Mid-transition temperature (°C): Γ = (Γ_min+Γ_max)/2 here.
        t_width_c: Logistic transition width (°C).

    Returns:
        Moist adiabatic lapse rate for each cell (°C/km), shape (N,).
    """
    delta = gamma_max - gamma_min
    _z = np.clip((t_mid_c - temperature_c) / t_width_c, -50.0, 50.0)
    _sig = 1.0 / (1.0 + np.exp(-_z))
    return np.asarray(gamma_min + delta * _sig)


def altitude_lapse_rate(
    temperature_c: np.ndarray,
    elevation_m: np.ndarray,
    lapse_rate_c_km: float | np.ndarray = 6.5,
) -> np.ndarray:
    """Correct temperature for altitude using the (moist) adiabatic lapse rate.

    T(h) = T_surface − Γ × h

    When ``lapse_rate_c_km`` is a scalar the conventional constant-Γ
    correction is applied.  Pass the output of ``moist_lapse_rate()`` to
    use a temperature-dependent lapse rate (tropical highlands stay warmer,
    polar mountains get the standard dry-adiabatic correction).

    Args:
        temperature_c: Surface-level temperature (°C), shape (N,).
        elevation_m: Elevation in metres, shape (N,).
        lapse_rate_c_km: Lapse rate in °C per km — scalar or per-cell array.

    Returns:
        Altitude-corrected temperature (°C), shape (N,).
    """
    return temperature_c - lapse_rate_c_km * (elevation_m / 1000.0)


# ---------------------------------------------------------------------------
# 1b. Slow-rotation meridional transport (3A.3a)
# ---------------------------------------------------------------------------


def lat_gradient_from_omega(
    rotation_period_days: float = 1.0,
    earth_gradient_c: float = 45.0,
) -> float:
    """Equator-to-pole temperature gradient scaled by rotation rate.

    On slower-rotating planets the Hadley cell widens and strengthens,
    transporting more heat poleward — the equator-to-pole ΔT shrinks.
    Fitted to Kaspi & Showman (2015, *ApJ* 804:60) Fig. 8a:

        ΔT(Ω) = ΔT⊕ × Ω^0.3

    where Ω = 1 / rotation_period_days (Ω⊕ = 1).

    Args:
        rotation_period_days: Rotation period in Earth days (1.0 = Earth,
            P = 24 h).  Larger values = slower rotation.
        earth_gradient_c: Earth reference equator-to-pole ΔT (°C).
            Default 45.0 (observed Earth ΔT ~45–50 °C).

    Returns:
        Equator-to-pole temperature difference in °C.

    Examples:
        Earth  (P=1.0):  45.0 × 1.0^0.3     = 45.0 °C
        nacrea (P=3.23): 45.0 × 3.23^(-0.3) ≈ 31.6 °C
        Venus  (P=243):  45.0 × 243^(-0.3)  ≈  8.7 °C
    """
    omega_ratio = 1.0 / rotation_period_days  # Ω / Ω⊕
    return float(earth_gradient_c * omega_ratio**0.3)


def hadley_extent_from_rotation(
    delta_theta_fraction: float,
    *,
    radius_km: float = 6371.0,
    gravity_m_s2: float = 9.81,
    rotation_period_days: float = 1.0,
    troposphere_height_m: float = 1.0e4,
) -> float:
    """Hadley-cell half-width from the Held-Hou thermal-Rossby-number scaling.

    The axisymmetric (eddy-free) equinox solution (Held & Hou 1980; Lindzen &
    Hou 1988; see also Guendelman & Kaspi 2019, GRL, "An axisymmetric limit
    for the width of the Hadley cell on planets") closes as

        R_t = 2 g H Δ_H / (Ω² a²) ,      φ_H ≈ R_t^(1/2)

    where Δ_H is the *fractional* meridional contrast of the radiative-
    equilibrium temperature (Δθ_eq/θ₀) and the O(1) proportionality constant
    is 1 (edge-matching closure; the full equal-area solution shifts it by
    O(20%)).  The cap at 90° is the global-cell regime — for R_t ≳ 2.5 the
    axisymmetric cell fills the hemisphere.

    Known limitation (why nacrea keeps an explicit override): the solstitial
    winter cell goes global far more readily than the equinox scaling
    predicts (Faulk et al. 2017: global cross-equatorial cell at Ω ≤ Ω⊕/8),
    and nacrea's weak obliquity (9°) shrinks Δ_H — the axisymmetric formula
    gives ~60° where the GCM evidence (ExoPlaSim PoC mass streamfunction,
    single-signed to the pole at Ω = 0.318) shows a global cell.  Worlds in
    that regime set ``hadley_extent_deg: 90`` explicitly (escape hatch).

    Args:
        delta_theta_fraction: Fractional radiative-equilibrium contrast
            Δθ_eq/θ₀ (dimensionless, ~0.13–0.25 for terrestrial forcings).
        radius_km: Planet radius (km).
        gravity_m_s2: Surface gravity (m/s²).
        rotation_period_days: Sidereal rotation period (days).
        troposphere_height_m: Hadley-cell depth (troposphere height, m).

    Returns:
        Hadley-cell half-width in degrees, capped at 90.
    """
    omega = 2.0 * np.pi / (rotation_period_days * 86400.0)  # rad/s
    a = radius_km * 1000.0  # m
    r_t = 2.0 * gravity_m_s2 * troposphere_height_m * delta_theta_fraction / (omega**2 * a**2)
    phi = min(0.5 * np.pi, np.sqrt(r_t))
    return float(np.degrees(phi))


def diffuse_heat_graph(
    temperature_c: np.ndarray,
    neighbors: list[list[int]],
    *,
    diffusion_passes: int = 3,
    diffusion_strength: float | np.ndarray = 0.15,
    land_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Graph-Laplacian heat diffusion — emulates atmospheric heat transport.

    Smooths temperature gradients across the CVT neighbour graph.  Each pass
    nudges every cell toward the mean of its neighbours:

        T_i ← (1 − α_i) T_i + α_i · mean(T_neighbors)

    When ``diffusion_strength`` is an array, α varies per cell.  A natural
    choice is α ∝ wind_speed: faster winds → stronger eddy heat transport.
    This peaks at mid-latitudes (storm tracks), where baroclinic instability
    drives the strongest poleward heat flux — zero additional free parameters.

    Args:
        temperature_c: Surface air temperature (°C), shape (N,).
        neighbors: Per-cell neighbour lists (cell indices not IDs).
        diffusion_passes: Number of Laplacian smoothing iterations.
        diffusion_strength: Per-pass blend factor α in [0, 1].
            Scalar → same everywhere; array → per-cell (e.g. ∝ wind speed).
        land_mask: Optional boolean mask, shape (N,).

    Returns:
        Temperature after diffusion (°C), shape (N,).
    """
    t = temperature_c.astype(np.float64, copy=True)
    n = len(t)
    alpha = np.broadcast_to(np.asarray(diffusion_strength, dtype=np.float64), n)

    for _pass in range(diffusion_passes):
        t_new = t.copy()
        for i in range(n):
            nbrs = neighbors[i]
            if not nbrs:
                continue
            nbr_mean = np.mean(t[nbrs])
            a = float(alpha[i])
            t_new[i] = (1.0 - a) * t[i] + a * nbr_mean
        t = t_new

    # Maritime moderation: ocean cells warm adjacent coastal land.
    if land_mask is not None:
        ocean_mask = ~land_mask
        for i in range(n):
            if not land_mask[i]:
                continue
            nbrs = neighbors[i]
            ocean_nbrs = [j for j in nbrs if ocean_mask[j]]
            if not ocean_nbrs:
                continue
            ocean_mean = np.mean(t[ocean_nbrs])
            t[i] = 0.7 * t[i] + 0.3 * ocean_mean

    return t


# ---------------------------------------------------------------------------
# 1c. Ice-albedo feedback (3A.3)
# ---------------------------------------------------------------------------


def ice_albedo_feedback(
    temperature_c: np.ndarray,
    *,
    base_albedo: float = 0.306,
    ice_albedo: float = 0.7,
    ice_threshold_c: float = -10.0,
    max_cooling_c: float = 8.0,
    transition_width_c: float = 4.0,
    n_iterations: int = 3,
) -> np.ndarray:
    """Ice-albedo positive feedback — ice reflects more sunlight → colder → more ice.

    Ice- and snow-covered surfaces have a much higher albedo (≈ 0.6–0.8) than
    bare land or ocean (≈ 0.1–0.3).  The reduced absorption of shortwave
    radiation cools the surface, which can expand the ice cover and close a
    positive feedback loop.

    The per-cell cooling is **limited** to ``max_cooling_c`` because
    atmospheric heat transport from lower latitudes partially compensates
    for the local radiative deficit.  (Applying the pure Stefan–Boltzmann
    scaling T ∝ (1–α)^(1/4) to individual cells would give 20–50 K of
    cooling — far exceeding observed ice-sheet effects of 2–8 K.)

    Algorithm (2–3 iterations):

        ice_frac = sigmoid((T_thresh − T) / transition_width)
        T        = T − max_cooling × ice_frac  (if T dropped below threshold)

    The cooling is applied cumulatively across iterations so cells that
    cross the threshold mid-way continue to cool, mimicking runaway
    ice-albedo feedback with a bounded ceiling.

    Args:
        temperature_c: Surface air temperature (°C), shape (N,).
        base_albedo: Planet base Bond albedo.  Unused; reserved for future
            global-mean feedback coupling.
        ice_albedo: Reference ice/snow albedo.  Unused; reserved.
        ice_threshold_c: Temperature below which ice cover begins.
        max_cooling_c: Maximum additional cooling from full ice cover (°C).
            Typical 3–8 °C per GCM studies of LGM vs pre-industrial.
        transition_width_c: Sigmoid transition width (°C).
        n_iterations: Feedback iterations.

    Returns:
        Temperature after ice-albedo feedback (°C), shape (N,).
    """
    del base_albedo, ice_albedo  # reserved for global-mean coupling
    t = temperature_c.astype(np.float64, copy=True)

    for _ in range(n_iterations):
        # Sigmoid: 0 in warm cells, 1 in cold (ice-covered) cells
        ice_frac = 1.0 / (1.0 + np.exp((t - ice_threshold_c) / transition_width_c))
        # Apply cooling proportional to ice fraction, bounded by max_cooling
        t -= max_cooling_c * ice_frac

    return t


def _blackbody_fraction_below(temp_k: float, wavelength_um: float) -> float:
    """Fraction of blackbody (Planck) energy emitted below ``wavelength_um``.

    The fraction is the incomplete Planck integral, a universal function of the
    dimensionless variable ``x = hc/(λkT)``:

        f(λ,T) = 1 − (15/π⁴) ∫₀ˣ t³/(eᵗ − 1) dt

    (15/π⁴ normalises by ∫₀^∞ t³/(eᵗ−1) dt = π⁴/15.)  Evaluated by trapezoidal
    quadrature over t ∈ [0, x].

    Args:
        temp_k: Blackbody temperature (K).
        wavelength_um: Wavelength (µm).

    Returns:
        Fraction of energy emitted below the wavelength, in [0, 1].
    """
    x = 0.01438777 / (wavelength_um * 1e-6 * temp_k)  # h·c/k (m·K)
    if x <= 0.0:
        return 1.0
    t = np.linspace(0.0, x, 256)
    with np.errstate(divide="ignore", invalid="ignore"):
        integrand = t**3 / np.expm1(t)
    integrand[0] = 0.0  # t³/(eᵗ−1) → 0 as t → 0
    integral = float(np.trapezoid(integrand, t))
    return float(max(0.0, min(1.0, 1.0 - 15.0 / np.pi**4 * integral)))


# Spectral ice-albedo model constants (two-band approximation, see
# ``spectral_ice_albedo``).  Ice/snow reflect strongly below ~1.1 µm and absorb
# in the near-IR; these are physically-motivated reference values, not a
# verbatim Shields et al. (2012) data table.
_ICE_BREAK_WAVELENGTH_UM: float = 1.1  # ice albedo transitions high→low near 1.1 µm
_ICE_NIR_ALBEDO: float = 0.2  # snow/ice albedo in the near-IR (λ > 1.1 µm)


def spectral_ice_albedo(
    stellar_temp_k: float,
    *,
    ice_albedo_visible: float = 0.7,
) -> float:
    """Effective snow/ice albedo under a stellar spectrum (Shields et al. 2012).

    Snow/ice reflect strongly in the visible (λ ≲ 1.1 µm) but absorb in the
    near-IR, so the effective ice albedo depends on the host star's spectral
    energy distribution: a Sun-like star (5772 K) emits ~76% of energy below
    1.1 µm and sees the full visible albedo; an M dwarf (3300–3900 K) emits much
    of its energy in the IR and sees a lower albedo.  This suppresses the
    ice-albedo feedback around M dwarfs (Shields et al. 2012, *Astrobiology*
    12:1023 — snow 0.8→0.6, ice 0.5→0.3 from solar to a 3300 K blackbody).

    Two-band model — a **project simplification**, not a verbatim Shields
    formula (which uses resolved spectral albedo curves and non-Planckian M
    dwarf spectra):

        α_eff = α_vis · f_vis + α_nir · (1 − f_vis)

    with α_vis = ``ice_albedo_visible``, α_nir = ``_ICE_NIR_ALBEDO``, and f_vis
    = ``_blackbody_fraction_below`` below ``_ICE_BREAK_WAVELENGTH_UM``.  The
    result is normalised so the Sun (5772 K) returns ``ice_albedo_visible``
    exactly, preserving Earth's behaviour.

    Args:
        stellar_temp_k: Host star effective temperature (K).
        ice_albedo_visible: Snow/ice albedo under a Sun-like spectrum
            (broadband visible-band value, default 0.7).

    Returns:
        Effective snow/ice albedo under the stellar spectrum.
    """
    ratio = _ICE_NIR_ALBEDO / ice_albedo_visible
    f_vis = _blackbody_fraction_below(stellar_temp_k, _ICE_BREAK_WAVELENGTH_UM)
    f_vis_sun = _blackbody_fraction_below(5772.0, _ICE_BREAK_WAVELENGTH_UM)
    weight = f_vis * (1.0 - ratio) + ratio
    weight_sun = f_vis_sun * (1.0 - ratio) + ratio
    return float(ice_albedo_visible * weight / weight_sun)


# ---------------------------------------------------------------------------
# 2. Wind — geostrophic wind + Hadley/Ferrel/Polar cells
# ---------------------------------------------------------------------------


def coriolis_parameter(
    lat_rad: np.ndarray,
    rotation_period_days: float = 1.0,
) -> np.ndarray:
    """Coriolis parameter f = 2Ω sin(φ).

    Args:
        lat_rad: Latitude in radians, shape (N,).
        rotation_period_days: Sidereal rotation period in days.

    Returns:
        Coriolis parameter f (rad/s), shape (N,).
    """
    omega = 2.0 * np.pi / (rotation_period_days * 86400.0)  # rad/s
    return np.asarray(2.0 * omega * np.sin(lat_rad))


def pressure_from_temperature(
    temperature_c: np.ndarray,
    elevation_m: np.ndarray,
    gravity_m_s2: float = 9.81,
    surface_pressure_hpa: float = 1013.25,
) -> np.ndarray:
    """Approximate surface pressure from temperature and elevation.

    Uses the barometric formula (hydrostatic equilibrium, isothermal
    approximation) plus a thermal-low contribution.

    P(h) = P₀ exp(-h / H) - δP_T(θ)

    where H ≈ 8500 m × (9.81/g) is the scale height (isothermal,
    Earth-composition air; H ∝ 1/g) and δP_T is the thermal pressure
    reduction (warmer air → lower pressure).

    The thermal-low term is keyed to the surface **potential temperature**
    θ = T + Γ_d·z (dry adiabatic lapse rate Γ_d = g/c_p), not the raw surface
    temperature.  An elevated surface (Tibetan plateau, Andes, Ethiopia) has a
    cold surface but a warm column — the elevated heat source — which raw T
    misreads as a cold anomaly.  θ reduces every surface to a common reference
    level, so the plateau's warm θ correctly lowers the pressure.

    Args:
        temperature_c: Surface temperature in °C, shape (N,).
        elevation_m: Elevation in metres, shape (N,).
        gravity_m_s2: Surface gravity (m/s²).  Sets the scale height and the
            dry adiabatic lapse rate Γ_d = g/c_p.
        surface_pressure_hpa: Sea-level pressure P₀ (hPa).

    Returns:
        Approximate surface pressure in hPa, shape (N,).
    """
    # Barometric formula
    scale_height_m = 8500.0 * (9.81 / gravity_m_s2)
    p_barometric = surface_pressure_hpa * np.exp(-elevation_m / scale_height_m)

    # Thermal low: warm air (potential temperature θ = T + Γ_d·z) expands →
    # lower pressure.  Γ_d = g/c_p is derived (not tuned), ~9.76 K/km on Earth.
    theta_c = temperature_c + (gravity_m_s2 / CP_AIR) * elevation_m
    theta_min, theta_max = theta_c.min(), theta_c.max()
    if theta_max - theta_min < 1e-6:
        return p_barometric

    theta_normalized = (theta_c - theta_min) / (theta_max - theta_min)
    p_thermal = p_barometric - 20.0 * theta_normalized

    return np.asarray(np.clip(p_thermal, 0.5 * surface_pressure_hpa, 1.07 * surface_pressure_hpa))


def hadley_cell_wind(
    lat_rad: np.ndarray,
    mesh_nodes_xyz: np.ndarray,
    hadley_extent_deg: float = 30.0,
    polar_cell_start_deg: float = 60.0,
    rotation_period_days: float = 1.0,
    itcz_lat_deg: float = 0.0,
) -> np.ndarray:
    """Three-cell atmospheric circulation: zonal + meridional surface winds.

    Cell boundaries (parameterized, roadmap 3A.3a):
        0°–H: Hadley cell  → surface equatorward + easterly (trade winds)
        H°–P°: Ferrel cell → surface poleward + westerly
        P°–90°: Polar cell  → surface equatorward + easterly

    Earth reference: H=30°, P=60°.  Slow rotators (weak Coriolis) have an
    expanded Hadley cell.

    Wind speeds scale with rotation rate as Ω^(-1/3) (Hill et al. 2019,
    J. Atmos. Sci. 76, doi:10.1175/JAS-D-18-0180.1 — both Hadley cell
    width and strength scale identically with Ω).  The scaling factor is
    (P_planet / P_earth)^(1/3).

    Meridional (N-S) surface wind direction follows the three-cell model:
    Hadley and Polar cells transport air equatorward at the surface; the
    Ferrel cell transports air poleward.  This is the primary source of
    ∂τ_north/∂x_east in the wind-stress curl that drives ocean gyres.

    References:
        Hill, S. A., S. Bordoni, and J. L. Mitchell (2019). "Constraints
        from invariant subtropical vertical velocities on the scalings of
        Hadley cell strength and downdraft width with rotation rate."
        J. Atmos. Sci., 76, doi:10.1175/JAS-D-18-0180.1.
        Held, I. M., and A. Y. Hou (1980). "Nonlinear axially symmetric
        circulations in a nearly inviscid atmosphere." J. Atmos. Sci.,
        37, 515–533.

    Args:
        lat_rad: Latitude in radians, shape (N,).
        mesh_nodes_xyz: Unit sphere coordinates, shape (N, 3).
        hadley_extent_deg: Hadley cell poleward boundary H (°).
        polar_cell_start_deg: Polar cell equatorward boundary P (°).
        rotation_period_days: Rotation period in Earth days (1.0 = Earth).
            Used for Ω^(-1/3) wind-speed scaling.
        itcz_lat_deg: Latitude of the ITCZ (thermal equator) in degrees.  The
            cell structure is symmetric about this latitude rather than the
            geographic equator, so a nonzero ITCZ shifts the circulation and
            reverses the meridional surface wind across it (seasonal monsoon).

    Returns:
        Wind velocity vectors (m/s) tangent to sphere, shape (N, 3).
    """
    n = len(lat_rad)
    # Effective latitude relative to the ITCZ.  Shifting the ITCZ north/south
    # (e.g. ±14° with the seasonal thermal equator) drags the whole circulation
    # with it — the seasonal wind reversal that drives monsoons.
    lat_deg = np.degrees(lat_rad) - itcz_lat_deg
    h = float(hadley_extent_deg)
    p = float(polar_cell_start_deg)

    # ── Ω^(-1/3) wind-speed scaling (Hill et al. 2019) ──
    omega_scale = rotation_period_days ** (1.0 / 3.0)  # (P/P⊕)^(1/3)

    # ── Zonal (E-W) wind ──
    # positive = eastward (westerly), negative = westward (easterly)
    zonal_speed = np.zeros(n, dtype=np.float64)
    # Base speeds (Earth, Ω=Ω⊕); scaled by omega_scale for other rotators.
    Z_HADLEY = -5.0 * omega_scale  # peak easterly (trade winds) at equator
    Z_FERREL = 8.0 * omega_scale  # peak westerly at cell centre
    Z_POLAR = -3.0 * omega_scale  # peak easterly at pole

    # Hadley: equator → H — easterly, peak at equator
    hadley_mask = np.abs(lat_deg) < h
    zonal_speed[hadley_mask] = Z_HADLEY * np.cos(np.pi * lat_deg[hadley_mask] / (2.0 * h))

    # Ferrel: H → P — westerly, peak at cell centre.  Degenerate (zero-width)
    # when P ≤ H (single-Hadley-cell slow rotators): skipped rather than
    # dividing by (P − H) = 0.
    ferrel_mask = (
        (np.abs(lat_deg) >= h) & (np.abs(lat_deg) < p) if p > h else np.zeros(n, dtype=bool)
    )
    if p > h:
        zonal_speed[ferrel_mask] = Z_FERREL * np.cos(
            np.pi * (np.abs(lat_deg[ferrel_mask]) - (h + p) / 2.0) / (p - h)
        )

    # Polar: P → 90° — easterly, peak at pole.  Degenerate when P ≥ 90 (no
    # polar cap — the single cell runs to the pole): skipped to avoid dividing
    # by (90 − P) = 0.  (The ITCZ shift lat_deg = lat − itcz can push the
    # opposite-pole cells past |lat_deg| = 90, which would otherwise hit this.)
    polar_mask = np.abs(lat_deg) >= p if p < 90.0 else np.zeros(n, dtype=bool)
    if p < 90.0:
        zonal_speed[polar_mask] = Z_POLAR * np.cos(
            np.pi * (90.0 - np.abs(lat_deg[polar_mask])) / (2.0 * (90.0 - p))
        )

    # ── Meridional (N-S) wind ──
    # positive = northward, negative = southward
    # Base magnitude (Earth); scaled by omega_scale.
    M = 1.5 * omega_scale  # m/s, peak meridional surface wind

    merid_speed = np.zeros(n, dtype=np.float64)

    # Hadley: surface branch flows equatorward
    #   NH (lat>0): equatorward = south → negative (−M)
    #   SH (lat<0): equatorward = north → positive (+M)
    #   Profile: soft-shouldered sine, peaks at h/2.
    # The plain sin(π·|lat|/h) reverses over ~2 cells at the equator; the coarse
    # CVT mesh amplifies that reversal's finite-volume divergence ~100× into a
    # spurious ITCZ spike.  A soft shoulder u = M·sin(πt)·(s + (1−s)·sin(πt))
    # (t = |lat|/h) has slope s·π at the equator instead of π, so s < 1 widens the
    # convergence band without a hard dead zone (which would split the ITCZ).
    _shoulder = 0.2  # meridional wind factor at the equator (1.0 = plain sine)
    _t = np.abs(lat_deg[hadley_mask]) / h
    _sin_t = np.sin(np.pi * _t)
    merid_speed[hadley_mask] = (
        -np.sign(lat_deg[hadley_mask]) * M * _sin_t * (_shoulder + (1.0 - _shoulder) * _sin_t)
    )

    # Ferrel: surface branch flows poleward (opposite of Hadley)
    #   NH: poleward = north → positive (+M)
    #   SH: poleward = south → negative (−M)
    if p > h:
        merid_speed[ferrel_mask] = (
            np.sign(lat_deg[ferrel_mask])
            * M
            * 0.6  # Ferrel meridional is weaker than Hadley
            * np.sin(np.pi * (np.abs(lat_deg[ferrel_mask]) - h) / (p - h))
        )

    # Polar: surface branch flows equatorward (same direction as Hadley)
    #   NH: south → negative; SH: north → positive
    if p < 90.0:
        merid_speed[polar_mask] = (
            -np.sign(lat_deg[polar_mask])
            * M
            * 0.5  # polar meridional is weaker still
            * np.sin(np.pi * (90.0 - np.abs(lat_deg[polar_mask])) / (90.0 - p))
        )

    # ── Combine zonal + meridional into 3D tangent vectors ──
    # Vectorized basis (was a per-cell Python loop — the seasonal-mean
    # circulation evaluates this 12 times, so it must be cheap):
    # local north = (0,1,0) projected to the tangent plane, local east =
    # r̂ × north — the *physical* east (direction of increasing longitude),
    # identical to ``map/ocean_circulation.east_north_basis``.  (Tech debt 24
    # root unification, 2026-09-13: this used to compose on ``north × r̂`` =
    # physical WEST — the mirrored convention whose storage/consumer flips are
    # now removed.  ``zonal_speed`` > 0 = eastward (westerly) is literal.)
    wind = np.zeros((n, 3), dtype=np.float64)
    nonzero = (np.abs(zonal_speed) >= 1e-9) | (np.abs(merid_speed) >= 1e-9)
    if nonzero.any():
        node = mesh_nodes_xyz[nonzero]
        north_tangent = np.array([0.0, 1.0, 0.0]) - node[:, 1:2] * node
        north_norm = np.linalg.norm(north_tangent, axis=1)
        pole = north_norm < 1e-9
        north_tangent[~pole] /= north_norm[~pole, None]
        east = np.cross(node, north_tangent)
        east_norm = np.linalg.norm(east, axis=1)
        valid = ~pole & (east_norm >= 1e-9)
        east[valid] /= east_norm[valid, None]
        idx = np.flatnonzero(nonzero)[valid]
        wind[idx] = (
            east[valid] * zonal_speed[idx, None] + north_tangent[valid] * merid_speed[idx, None]
        )

    return wind


def terrain_wind_blocking(
    wind: np.ndarray,
    elevation_m: np.ndarray,
    blocking_height_m: float = 3000.0,
) -> np.ndarray:
    """Reduce wind speed over high-elevation terrain.

    Mountains above blocking_height_m reduce wind by up to 50%.

    Args:
        wind: Wind vectors (m/s), shape (N, 3).
        elevation_m: Elevation in metres, shape (N,).
        blocking_height_m: Height at which blocking reaches 50% reduction.

    Returns:
        Blocked wind vectors (m/s), shape (N, 3).
    """
    # Blocking factor: 1.0 at sea level → 0.5 above blocking_height_m
    blocking = 0.5 + 0.5 * np.exp(-np.maximum(elevation_m, 0.0) / blocking_height_m)
    # Only apply blocking to positive elevations
    mask = elevation_m > 0.0
    result = wind.copy()
    result[mask] = wind[mask] * blocking[mask, np.newaxis]
    return result


# ---------------------------------------------------------------------------
# 3. Precipitation — moisture transport + orographic rainfall
# ---------------------------------------------------------------------------


def saturation_specific_humidity(temperature_c: np.ndarray) -> np.ndarray:
    """Saturation specific humidity q_sat (kg/kg) — Bolton (1980).

    Clausius–Clapeyron saturation vapour pressure over liquid water, converted
    to a specific-humidity mixing ratio at ~1000 hPa.  Shared by the cold-trap
    saturation clamp (``column_water_saturation``) and the coastal
    moisture-flux estimate.
    """
    t_k = np.maximum(np.asarray(temperature_c, dtype=np.float64) + 273.15, 180.0)
    e_sat = 611.2 * np.exp(17.67 * (t_k - 273.15) / (t_k - 29.65))  # Pa
    return 0.622 * e_sat / 101325.0


def column_water_saturation(
    temperature_c: np.ndarray,
    *,
    vapor_scale_height_m: float = 2100.0,
    rho_air_kg_m3: float = 1.2,
    rho_water_kg_m3: float = 1000.0,
) -> np.ndarray:
    """Saturated column water vapour W_sat (mm) at the given temperature.

    ``W_sat = q_sat(T) · H_v · ρ_air / ρ_w`` with the water-vapour scale height
    ``H_v ≈ 2.1 km``.  The cold-trap clamp caps the moisture budget's column
    water at this value, so a cold air column cannot rain out more water than
    it can hold (Clausius–Clapeyron saturation × column height).  Warm columns
    have a large W_sat and are effectively unconstrained.
    """
    q_sat = saturation_specific_humidity(temperature_c)
    return q_sat * vapor_scale_height_m * rho_air_kg_m3 / rho_water_kg_m3 * 1000.0


def evaporation_rate(
    temperature_c: np.ndarray,
    is_ocean: np.ndarray,
    base_mm: float = 1000.0,
) -> np.ndarray:
    """Surface evaporation rate based on temperature and water availability.

    Ocean evaporation is *energy-limited*, not set by the Clausius–Clapeyron
    saturation curve: the latent heat flux cannot exceed the available net
    surface radiation, so evaporation rises only ~2–3% per °C of warming
    (Trenberth et al. 2009; Held & Soden 2006) — not the ~7%/°C C–C rate,
    which applies to the *saturation vapour pressure*, a different quantity.

    Args:
        temperature_c: Temperature in °C, shape (N,).
        is_ocean: Boolean mask, True for ocean cells.
        base_mm: Base annual evaporation at 15 °C reference ocean (mm/yr).
            Calibrated so the global ocean-mean evaporation matches Earth's
            observed ~1143 mm/yr (Trenberth 2009; 1000 mm at ~18.7 °C mean SST).

    Returns:
        Annual evaporation in mm, shape (N,).
    """
    evap = np.zeros(len(temperature_c), dtype=np.float64)
    # Only ocean cells evaporate
    ocean_mask = np.asarray(is_ocean, dtype=bool)
    # ~3% per °C above 15 °C reference (energy-limited, not C–C)
    evap[ocean_mask] = base_mm * (1.0 + 0.03 * (temperature_c[ocean_mask] - 15.0))
    return np.maximum(evap, 0.0)


def orographic_precipitation(
    moisture_in: np.ndarray,
    elev_diff_m: float,
    efficiency: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute precipitation from orographic uplift.

    When moisture-laden air is forced to rise over terrain, it cools
    adiabatically and water vapour condenses.  The amount of precipitation
    is proportional to the elevation gain and available moisture.

    Args:
        moisture_in: Available moisture in the incoming air mass (mm).
        elev_diff_m: Elevation gain the air must traverse (m).  Positive = rising.
        efficiency: Fraction of moisture converted to rain per 1000 m of uplift.
            0.5 = 50% of moisture rains out per km of ascent.

    Returns:
        (precipitation_mm, moisture_out):
            precipitation_mm — rain/snow deposited at this location.
            moisture_out — remaining moisture in the air mass.
    """
    if elev_diff_m <= 0.0:
        # Descending or flat: no orographic precipitation, moisture conserved
        return np.zeros_like(moisture_in), moisture_in

    # Fraction of moisture that condenses
    rain_fraction = min(efficiency * (elev_diff_m / 1000.0), 0.9)
    rain = moisture_in * rain_fraction
    return rain, moisture_in - rain


def itcz_latitude(
    day_of_year: float,
    axial_tilt_deg: float = 23.44,
    lag_days: float = 30.0,
    orbital_period_days: float = 365.25,
) -> float:
    """Approximate ITCZ latitude for a given day of year.

    The ITCZ (Intertropical Convergence Zone) migrates with the thermal
    equator, which lags the subsolar point by 1–2 months due to ocean
    thermal inertia.

    Args:
        day_of_year: Day of year (0–365).
        axial_tilt_deg: Axial obliquity in degrees.
        lag_days: ITCZ lag behind subsolar point (days).
        orbital_period_days: Length of year in days.

    Returns:
        ITCZ latitude in degrees.
    """
    epsilon = np.radians(axial_tilt_deg)
    # Subsolar point
    solar_declination = epsilon * np.sin(2.0 * np.pi * (day_of_year - 80.0) / orbital_period_days)
    # ITCZ lags and is damped; +5.0° mean NH bias (more land → warmer) below
    itcz = (
        0.7 * solar_declination
        + np.sin(2.0 * np.pi * (day_of_year - 80.0 - lag_days) / orbital_period_days)
        * epsilon
        * 0.7
    )
    return float(np.degrees(itcz) + 5.0)  # mean NH offset


# ---------------------------------------------------------------------------
# 4. Ocean currents
# ---------------------------------------------------------------------------


def ekman_current_direction(
    wind: np.ndarray,
    lat_rad: np.ndarray,
) -> np.ndarray:
    """Compute surface ocean current direction from Ekman transport.

    Surface currents are deflected ~45° from the wind direction:
    - NH: right of wind
    - SH: left of wind

    Current speed ≈ 2% of wind speed.

    Args:
        wind: Wind vectors (m/s), shape (N, 3).
        lat_rad: Latitude in radians, shape (N,).

    Returns:
        Ocean current vectors (m/s), shape (N, 3).
    """
    n = len(wind)
    currents = np.zeros_like(wind)

    for i in range(n):
        wind_speed = np.linalg.norm(wind[i])
        if wind_speed < 1e-9:
            continue

        # Deflection angle: ±45° depending on hemisphere
        angle = np.sign(lat_rad[i]) * np.radians(45.0)

        # Rotate wind vector by deflection angle — simplified: rotate in the
        # east-north plane (a proper implementation would use the local normal)
        w_east = wind[i, 0]  # x → lon direction at given point
        w_north = -wind[i, 2]  # z → lat direction (subtle: depends on mesh convention)

        cos_a, sin_a = np.cos(angle), np.sin(angle)
        c_east = cos_a * w_east - sin_a * w_north
        c_north = sin_a * w_east + cos_a * w_north

        # Current speed ≈ 2% of wind speed
        speed_ratio = 0.02
        currents[i, 0] = c_east * speed_ratio
        currents[i, 2] = -c_north * speed_ratio

    return currents


# ---------------------------------------------------------------------------
# 5. Köppen climate classification
# ---------------------------------------------------------------------------


def dryness_offset_mm(
    p_warm_mm: float | np.ndarray,
    p_cold_mm: float | np.ndarray,
    p_annual_mm: float | np.ndarray,
) -> np.ndarray:
    """Köppen B-group dryness-threshold seasonal offset (Kottek et al. 2006).

    280 mm when >70% of the annual precipitation falls in the warm half of the
    year, 0 mm when >70% falls in the cold half, 140 mm otherwise (even
    distribution).  Vectorised single source for ``koppen_classify`` and the
    subsidence aridity gate (``subsidence_aridity_gate``).

    Args:
        p_warm_mm: Warm-half (6 warmest months) precipitation total, mm.
        p_cold_mm: Cold-half (6 coldest months) precipitation total, mm.
        p_annual_mm: Annual precipitation total, mm.

    Returns:
        Offset in mm, same broadcast shape as the inputs (0-d array for
        scalar inputs).
    """
    return np.asarray(
        np.where(
            np.asarray(p_warm_mm) > 0.7 * np.asarray(p_annual_mm),
            280.0,
            np.where(np.asarray(p_cold_mm) > 0.7 * np.asarray(p_annual_mm), 0.0, 140.0),
        )
    )


def dryness_threshold_mm(
    t_mean_c: float | np.ndarray,
    offset_mm: float | np.ndarray,
) -> np.ndarray:
    """Köppen B-group aridity threshold: ``max(20·T + offset, 1)`` mm/yr.

    The 1 mm floor keeps polar deserts (T ≤ −7 °C drives the empirical
    formula ≤ 0, while P ≈ 0 from numerical noise) classified as arid.

    Args:
        t_mean_c: Mean annual temperature, °C.
        offset_mm: Seasonal offset from ``dryness_offset_mm``, mm.

    Returns:
        Threshold in mm/yr, same broadcast shape as the inputs.
    """
    return np.asarray(np.maximum(20.0 * np.asarray(t_mean_c) + np.asarray(offset_mm), 1.0))


def potential_evapotranspiration_hamon(
    t_monthly_c: np.ndarray,
    days_per_month: float,
) -> np.ndarray:
    """Annual Hamon (1961) potential evapotranspiration, mm/yr.

    Daily form ``PET = 29.8 · N_h · e_s(T) / T_K`` mm/day (Hamon 1961;
    identical to the HEC-HMS ``ETo = c·(N/12)·ρ_sat`` with c = 0.165 mm per
    g/m³ and ρ_sat = 216.7·e_s[hPa]/T_K), Magnus saturation vapour pressure
    ``e_s = 0.6108·exp(17.27·T/(T+237.3))`` kPa.

    Daylength is taken as N = 12 h: the annual-mean daylength is 12 h at
    every latitude, and the consumer (``subsidence_aridity_gate``) acts only
    inside the Hadley band (|lat| ≲ 38°), where the seasonal N×T covariance
    contributes < 5% to the annual sum.  Below 0 °C the formula stays
    positive and small (T_K > 0 always), so no cold-side pathology.

    Args:
        t_monthly_c: Monthly-mean temperature, °C, shape (N, 12).
        days_per_month: Mean days per calendar month (orbital_period / 12).

    Returns:
        Annual potential evapotranspiration, mm/yr, shape (N,).
    """
    t = np.asarray(t_monthly_c, dtype=np.float64)
    es_kpa = 0.6108 * np.exp(17.27 * t / (t + 237.3))
    pet_day = 29.8 * 12.0 * es_kpa / (t + 273.15)  # mm/day at N = 12 h
    return np.asarray(pet_day.sum(axis=-1) * days_per_month)


def aridity_index_keep(
    p_annual_mm: np.ndarray,
    pet_annual_mm: np.ndarray,
) -> np.ndarray:
    """UNEP (1992) aridity-index keep-fraction for the subsidence gate.

    ``AI = P / PET``; UNEP classes: hyper-arid < 0.05, arid 0.05-0.2,
    semi-arid 0.2-0.5, dry sub-humid 0.5-0.65, humid > 0.65.  Subsidence
    warming is kept through the semi-arid class (AI ≤ 0.5), released through
    the humid class (AI ≥ 0.65), linear across the dry sub-humid transition.
    Both knots are UNEP class boundaries — no tunable parameters.

    The exponential (Clausius-Clapeyron) PET makes AI robust where the
    linear Köppen threshold is not: over hot subsidence coasts the engine's
    precipitation is biased wet (no subsidence drying parameterisation yet),
    but a 3× wet bias at 27 °C still lands in the semi-arid class because
    PET there is ~1500 mm/yr.

    Args:
        p_annual_mm: Annual precipitation, mm, shape (N,).
        pet_annual_mm: Annual potential evapotranspiration, mm, shape (N,).

    Returns:
        Keep-fraction in [0, 1], shape (N,): 1 = arid, keep the warming;
        0 = humid, release it.
    """
    ai = np.asarray(p_annual_mm) / np.maximum(np.asarray(pet_annual_mm), 1e-9)
    return np.asarray(np.clip((0.65 - ai) / 0.15, 0.0, 1.0))


# Highland exemption for the subsidence gate (m).  The Stage-1 increment is
# defined on the sea-level-reduced temperature and physically belongs to the
# descent-branch boundary layer, which tops out near 850 hPa over the
# subtropics — ≈ 1.5 km in the standard atmosphere.  Surfaces above it
# (Tibet, Altiplano, Rockies) are decoupled from that layer and their
# temperature treatment is a separate registered open item (highland cold
# bias family), so the gate must not silently re-tune them.
_SUBSIDENCE_GATE_ELEV_MAX_M = 1500.0


def subsidence_aridity_gate(
    dt_subsidence_c: np.ndarray,
    p_annual_mm: np.ndarray,
    t_mean_c: np.ndarray,
    p_warm_mm: np.ndarray,
    p_cold_mm: np.ndarray,
    pet_annual_mm: np.ndarray,
    elevation_m: np.ndarray,
) -> np.ndarray:
    """Aridity-gated release of the Held-Hou subsidence warming (4.2-①).

    The subsidence homogenisation warms every land cell inside the Hadley
    cell, but physically the warming belongs to the *dry* descending branch:
    over humid subtropical margins (monsoon coasts) it is offset by moist
    convection and evaporative cooling, and the annual-mean surface sits at
    its local radiative-advection balance instead.  Since precipitation is
    only known after the temperature pass, the increment is archived at
    Stage 1 and *released* here: dry cells keep it, humid cells give it
    back.

    Only the **warming** (positive) component is gated.  Near the equator the
    archived increment is negative — there the homogenisation represents the
    ascent branch's moist-convective pull toward the cell mean, not subsidence
    warming — so it is kept everywhere regardless of aridity.

    Release requires **both** aridity indicators to say humid (keep = max of
    the two keep-fractions): the Köppen ratio ``r = P / threshold(T)`` (knots
    r = 0.5 BW/BS and r = 1 arid/humid) and the UNEP aridity index
    ``AI = P / PET_Hamon`` (knots 0.5 / 0.65, ``aridity_index_keep``).  The
    conjunction absorbs the engine's wet bias over hot subsidence coasts
    (Persian Gulf / Sahara Atlantic coast), where model P alone would
    misclassify true desert as humid and release the warming.  Cells above
    ``_SUBSIDENCE_GATE_ELEV_MAX_M`` always keep (highland exemption).
    All knots are existing Köppen / UNEP class boundaries — no new tunable
    parameters.

    Args:
        dt_subsidence_c: Archived Stage-1 subsidence increment, °C, shape
            (N,) — zero over ocean and outside the Hadley band.
        p_annual_mm: Annual precipitation, mm, shape (N,).
        t_mean_c: Mean annual temperature (pre-release), °C, shape (N,).
        p_warm_mm: Warm-half precipitation, mm, shape (N,).
        p_cold_mm: Cold-half precipitation, mm, shape (N,).
        pet_annual_mm: Annual Hamon potential evapotranspiration, mm, (N,).
        elevation_m: Cell elevation, m, shape (N,).

    Returns:
        Increment to *subtract* from the temperature fields, °C, shape (N,) —
        non-negative (never adds warming back).
    """
    offset = dryness_offset_mm(p_warm_mm, p_cold_mm, p_annual_mm)
    threshold = dryness_threshold_mm(t_mean_c, offset)
    r = np.asarray(p_annual_mm) / threshold
    keep_k = np.asarray(np.clip((1.0 - r) / 0.5, 0.0, 1.0))  # 1 dry … 0 humid
    keep_ai = aridity_index_keep(p_annual_mm, pet_annual_mm)
    keep = np.maximum(keep_k, keep_ai)
    keep = np.where(np.asarray(elevation_m) >= _SUBSIDENCE_GATE_ELEV_MAX_M, 1.0, keep)
    dt_warm = np.maximum(np.asarray(dt_subsidence_c), 0.0)
    return np.asarray((1.0 - keep) * dt_warm)


# §5-α SST convection gate knots.  Calibration: GPCP ocean cells, rainout
# efficiency e_rel = P_local / P_band-mean, binned by the SST anomaly
# ΔSST = SST − 5°-band mean (scripts/climate/diagnose_desert_wetness.py,
# archive mode, 2026-09-13).  The gate factor is e_rel normalised by its
# zero-anomaly value so the calibrated baseline (ΔSST = 0) is untouched:
#   tropical (|lat| ≤ 15°):   e_rel 0.94 @ 0 → 0.84 @ −1 → 0.60 @ −2  (WTG —
#     the free troposphere is horizontally uniform, so convective instability
#     follows the *local* anomaly; much more sensitive than mid-latitudes)
#   extratropical (|lat| ≥ 25°): 1.00 @ 0 → 0.82 @ −3 → 0.65 @ −5 → 0.24 @ −7
_SST_GATE_KNOTS_TROP_DSST: tuple[float, ...] = (0.0, -1.0, -2.0)
_SST_GATE_KNOTS_TROP_F: tuple[float, ...] = (1.0, 0.894, 0.638)
_SST_GATE_KNOTS_EXTR_DSST: tuple[float, ...] = (0.0, -3.0, -5.0, -7.0)
_SST_GATE_KNOTS_EXTR_F: tuple[float, ...] = (1.0, 0.82, 0.65, 0.24)
# Floor: the stratocumulus-drizzle residual — marine Sc decks over cold water
# still drizzle ~20% of what a warm pool rains per unit column water (the
# 0.1-0.3 tail range of the calibration; take 0.2).
_SST_GATE_F_MIN: float = 0.2


def sst_convection_gate(
    t_c: np.ndarray,
    lat_deg: np.ndarray,
    is_ocean: np.ndarray,
) -> np.ndarray:
    """Weak-temperature-gradient SST convection gate (§5-α): k_rain × f(ΔSST).

    Under WTG (Sobel et al. 2001) the tropical free troposphere is horizontally
    uniform, so ocean convective instability follows the *local* SST anomaly
    relative to its latitude band: warm-anomaly water deep-conveys (threshold
    family 26-28 °C, Johnson & Xie 2010), cold-anomaly water (upwelling /
    eastern boundary currents / the equatorial cold tongue) is stabilised from
    below (trade inversion, coastal fog deserts — Namib/Atacama type, Garreaud
    et al. 2002; cold tongue-ITCZ coupling, Xie & Philander 1994).  Rainout
    efficiency collapses over the cold anomaly and the moisture is exported
    horizontally to the warm pool / ITCZ where it rains out — a mass-conserving
    redistribution (the gate multiplies k_rain, so ΣP = ΣE holds for any gate
    field), not a sink.

    The returned factor is a piecewise-linear ramp through the calibrated
    knots (see the module constants above), clipped to [0.2, 1].  Positive
    anomalies give f = 1 exactly (structural safety: warm pools and western
    boundary currents — Bay of Bengal, South China Sea, Kuroshio, Gulf Stream
    — are never suppressed; only the *cold* side of the double-ITCZ bias
    family is addressed).  Land cells get f = 1 (v1: ocean-only gate; coastal
    land converges indirectly through the moisture-supply cutoff).  The
    tropical/extratropical branches blend linearly over 15-25°.

    Args:
        t_c: Sea-surface temperature field, °C, shape (N,) or (N, 12).  The
            anomaly is computed against the 5°-band, cos-weighted mean of the
            ocean cells in the same column (monthly fields are banded per
            month).
        lat_deg: Latitude in degrees, shape (N,).
        is_ocean: Ocean mask, shape (N,) — the band mean and the gate apply
            to ocean cells only.

    Returns:
        Gate factor in [0.2, 1.0], same shape as *t_c*.
    """
    t_arr = np.asarray(t_c, dtype=np.float64)
    monthly = t_arr.ndim == 2
    n_months = t_arr.shape[1] if monthly else 1
    flat = t_arr.reshape(t_arr.shape[0], n_months) if monthly else t_arr[:, None]

    abs_lat = np.abs(np.asarray(lat_deg, dtype=np.float64))
    lat_signed = np.asarray(lat_deg, dtype=np.float64)
    # Signed 5° latitude bands (36 bands, hemispheres NOT merged — a uniform
    # interhemispheric offset must not register as a zonal anomaly).
    band_idx = np.clip(((lat_signed + 90.0) / 5.0).astype(np.int64), 0, 35)

    dsst = np.zeros_like(flat)
    for b in range(36):
        m = (band_idx == b) & is_ocean
        if m.sum() < 3:
            continue  # band with no ocean (polar cap) — no anomaly defined
        w = np.cos(np.radians(lat_signed[m]))
        for j in range(n_months):
            dsst[m, j] = flat[m, j] - float(np.average(flat[m, j], weights=w))

    # Branch interpolation + latitudinal blend (tropical |lat|≤15, extratrop ≥25).
    # np.interp with increasing x: positive anomalies clamp to f(0)=1 (the
    # structural zero-suppression for warm pools); below the last knot the
    # measured slope is linearly extrapolated (the tropical calibration stops
    # at −2 °C — upwelling cores reach −4).
    def _ramp(x: np.ndarray, xs: tuple[float, ...], fs: tuple[float, ...]) -> np.ndarray:
        f = np.asarray(np.interp(x, xs[::-1], fs[::-1]))
        below = x < xs[-1]
        if below.any():
            slope = (fs[-1] - fs[-2]) / (xs[-1] - xs[-2])
            f = np.asarray(np.where(below, fs[-1] + (x - xs[-1]) * slope, f))
        return f

    w_trop = 1.0 - np.clip((abs_lat - 15.0) / 10.0, 0.0, 1.0)
    f_trop = _ramp(dsst, _SST_GATE_KNOTS_TROP_DSST, _SST_GATE_KNOTS_TROP_F)
    f_extr = _ramp(dsst, _SST_GATE_KNOTS_EXTR_DSST, _SST_GATE_KNOTS_EXTR_F)
    f = w_trop[:, None] * f_trop + (1.0 - w_trop[:, None]) * f_extr
    f = np.where(np.asarray(is_ocean)[:, None], f, 1.0)
    out = np.clip(f, _SST_GATE_F_MIN, 1.0)
    if monthly:
        return np.asarray(out)
    return np.asarray(out[:, 0])


def koppen_classify(
    t_mean_c: np.ndarray,
    t_cold_c: np.ndarray,
    t_hot_c: np.ndarray,
    p_annual_mm: np.ndarray,
    p_dry_mm: np.ndarray,
    p_wet_mm: np.ndarray,
    is_land: np.ndarray,
    p_warm_mm: np.ndarray | None = None,
    p_cold_mm: np.ndarray | None = None,
    p_dry_summer_mm: np.ndarray | None = None,
    p_wet_winter_mm: np.ndarray | None = None,
    p_dry_winter_mm: np.ndarray | None = None,
    p_wet_summer_mm: np.ndarray | None = None,
    t_months_ge10: np.ndarray | None = None,
) -> list[str]:
    """Köppen climate classification for each cell.

    Five main groups:
        A: Tropical   — t_cold > 18 °C
        B: Arid       — precipitation below dryness threshold
        C: Temperate  — t_cold ∈ [-3, 18) °C, t_hot > 10 °C
        D: Continental — t_cold < -3 °C, t_hot > 10 °C
        E: Polar      — t_hot < 10 °C

    Sub-classification based on precipitation seasonality:
        f: fully humid (no dry season)
        s: dry summer (Mediterranean pattern)
        w: dry winter (monsoon pattern)
        m: monsoonal (tropical, short dry season)

    The C/D third letter (s/w/f) is season-aware when the four per-half
    extremes (``*_summer_*`` / ``*_winter_*``) are supplied: the year is split
    into the 6 warmest and 6 coldest months, and "s" is a dry *warm* half while
    "w" is a dry *cold* half (Kottek et al. 2006).  Without them it falls back
    to a season-blind wettest/driest-month heuristic.

    Args:
        t_mean_c: Mean annual temperature (°C), shape (N,).
        t_cold_c: Coldest month mean temperature (°C), shape (N,).
        t_hot_c: Hottest month mean temperature (°C), shape (N,).
        p_annual_mm: Annual precipitation (mm), shape (N,).
        p_dry_mm: Driest month precipitation (mm), shape (N,).
        p_wet_mm: Wettest month precipitation (mm), shape (N,).
        is_land: Boolean mask, True for land cells.
        p_warm_mm: Warm-half (6 warmest months) precipitation (mm), shape (N,).
            Optional; with ``p_cold_mm`` selects the B-group dryness-threshold
            offset (warm/cold-season wet).  None → "even" offset.
        p_cold_mm: Cold-half (6 coldest months) precipitation (mm), shape (N,).
        p_dry_summer_mm: Driest warm-half month (mm), shape (N,).  Optional;
            with the other three ``*_summer_*``/``*_winter_*`` args enables the
            season-aware s/w/f discrimination.
        p_wet_winter_mm: Wettest cold-half month (mm), shape (N,).
        p_dry_winter_mm: Driest cold-half month (mm), shape (N,).
        p_wet_summer_mm: Wettest warm-half month (mm), shape (N,).
        t_months_ge10: Count of months with mean temperature ≥ 10 °C, shape
            (N,) — the Kottek et al. (2006) criterion for the b/c third
            letter (b = ≥ 4 such months, c = 1–3).  Optional; without it the
            third letter falls back to warmest-month thresholds, under which
            'c' is structurally unreachable (the E-group gate has already
            caught t_hot < 10).  D-group 'd' (coldest month < −38 °C) also
            requires the monthly count to be meaningful and is skipped
            without it.

    Returns:
        List of Köppen codes (e.g. 'Cfa', 'BWh', 'ET', 'Am').  Ocean → 'Ocean'.
    """
    n = len(t_mean_c)
    classes: list[str] = []

    # Season-aware dry-summer / dry-winter flags (Kottek et al. 2006):
    #   s: driest warm-half month < wettest cold-half month / 3, and (C only)
    #      < 40 mm;   w: driest cold-half month < wettest warm-half month / 10.
    if (
        p_dry_summer_mm is not None
        and p_wet_winter_mm is not None
        and p_dry_winter_mm is not None
        and p_wet_summer_mm is not None
    ):
        dry_summer_d = np.asarray(p_dry_summer_mm < p_wet_winter_mm / 3.0)  # D group
        dry_summer_c = dry_summer_d & np.asarray(p_dry_summer_mm < 40.0)  # C group
        dry_winter = np.asarray(p_dry_winter_mm < p_wet_summer_mm / 10.0)
    else:
        # Season-blind heuristic: a strong wettest/driest-month contrast.
        dry_summer_c = np.asarray((p_wet_mm > 3.0 * p_dry_mm) & (p_dry_mm < 40.0))
        dry_summer_d = dry_summer_c
        dry_winter = np.asarray((p_dry_mm < 30.0) & (p_wet_mm < 10.0 * p_dry_mm))

    # Warm-month count for the b/c third letter (Kottek et al. 2006: b = ≥ 4
    # months at ≥ 10 °C, c = 1–3).  The former `elif t_hot > 10: b else: c`
    # made 'c' structurally unreachable (the E-group gate above has already
    # caught t_hot < 10), so observed Dfc/Dwc/Cfc cells (≈ 7300 on Earth)
    # could never be produced.
    warm4_b = np.asarray(t_months_ge10) >= 4 if t_months_ge10 is not None else None

    for i in range(n):
        if not is_land[i]:
            classes.append("Ocean")
            continue

        tc, th, ta = t_cold_c[i], t_hot_c[i], t_mean_c[i]
        pa, pd = p_annual_mm[i], p_dry_mm[i]

        # Group E: Polar
        if th < 10.0:
            if th > 0.0:
                classes.append("ET")  # Tundra
            elif th > -10.0:
                classes.append("EF")  # Ice cap
            else:
                classes.append("EF")
            continue

        # Group B: Arid — dryness threshold (Köppen 1936 / Kottek et al. 2006),
        # shared with the subsidence aridity gate: ``dryness_offset_mm`` picks
        # the seasonal offset from the warm/cold-half concentration (fallback
        # "even" 140 without monthly data), ``dryness_threshold_mm`` applies
        # 20·T + offset with the 1 mm polar-desert floor (see their docstrings).
        # ``<=`` + the floor make P≈0 polar desert arid, not "humid" (D).
        if p_warm_mm is not None and p_cold_mm is not None:
            offset = float(dryness_offset_mm(p_warm_mm[i], p_cold_mm[i], pa))
        else:
            offset = 140.0
        dryness_threshold = float(dryness_threshold_mm(ta, offset))

        if pa <= dryness_threshold:
            if ta > 18.0:
                if pa <= dryness_threshold / 2.0:
                    classes.append("BWh")  # Hot desert
                else:
                    classes.append("BSh")  # Hot steppe
            else:
                if pa <= dryness_threshold / 2.0:
                    classes.append("BWk")  # Cold desert
                else:
                    classes.append("BSk")  # Cold steppe
            continue

        # Group A: Tropical
        if tc > 18.0:
            if pd > 60.0:
                classes.append("Af")  # Tropical rainforest
            elif pd >= 100.0 - pa / 25.0:
                classes.append("Am")  # Tropical monsoon
            else:
                classes.append("Aw")  # Tropical savanna
            continue

        # Third-letter seasonality (s/w/f), shared by C and D.
        # Group C: Temperate
        if tc > -3.0:
            if dry_summer_c[i]:
                s = "s"  # dry summer (Mediterranean)
            elif dry_winter[i]:
                s = "w"  # dry winter
            else:
                s = "f"  # fully humid
            # Temperature letter (Kottek et al. 2006): a = warmest > 22 °C;
            # b = ≥ 4 months at ≥ 10 °C; c = 1–3 such months.  (The former
            # Csb extra `tc > 0` condition is dropped — non-standard, and 'c'
            # is now reachable by the proper month-count criterion.)
            if th > 22.0:
                t3 = "a"
            elif warm4_b is None:
                t3 = "b" if th > 10.0 else "c"  # legacy fallback
            elif warm4_b[i]:
                t3 = "b"
            else:
                t3 = "c"
            classes.append(f"C{s}{t3}")
            continue

        # Group D: Continental (tc ≤ −3, th ≥ 10 — the E gate caught th < 10)
        if dry_summer_d[i]:
            s = "s"
        elif dry_winter[i]:
            s = "w"
        else:
            s = "f"
        # 'd' (coldest month < −38 °C, e.g. Verkhoyansk) takes precedence —
        # it replaces the warm-summer letter entirely (Kottek et al. 2006;
        # requires monthly data, skipped in the legacy fallback).
        if warm4_b is not None and tc < -38.0:
            t3 = "d"
        elif th > 22.0:
            t3 = "a"
        elif warm4_b is None:
            t3 = "b" if th > 10.0 else "c"  # legacy fallback
        elif warm4_b[i]:
            t3 = "b"
        else:
            t3 = "c"
        classes.append(f"D{s}{t3}")

    return classes


# ---------------------------------------------------------------------------
# 6. Composite functions — convenience wrappers for common pipelines
# ---------------------------------------------------------------------------


def compute_mean_annual_temperature(
    elevation_m: np.ndarray,
    lat_rad: np.ndarray,
    *,
    stellar_luminosity_sol: float = 1.0,
    orbital_distance_au: float = 1.0,
    albedo: float = 0.306,
    greenhouse_warming_K: float = 33.0,
    lat_gradient_c: float = 40.0,
    lapse_rate_c_km: float = 6.5,
) -> np.ndarray:
    """End-to-end mean annual temperature computation.

    Combines EBM equilibrium temperature → latitude gradient →
    altitude correction into a single call.

    Args:
        elevation_m: Elevation in metres, shape (N,).
        lat_rad: Latitude in radians, shape (N,).
        stellar_luminosity_sol: Star luminosity (solar units).
        orbital_distance_au: Orbital distance in AU.
        albedo: Bond albedo (0–1).
        greenhouse_warming_K: Additional greenhouse warming (K).
        lat_gradient_c: Equator-to-pole temperature difference (°C).
        lapse_rate_c_km: Altitude lapse rate (°C/km).

    Returns:
        Mean annual temperature in °C, shape (N,).
    """
    teq = equilibrium_temperature(stellar_luminosity_sol, orbital_distance_au, albedo)
    t_surf_k = surface_temperature(teq, greenhouse_warming_K)
    t_surf_c = t_surf_k - 273.15  # K → °C
    t_lat = latitude_temperature(t_surf_c, lat_rad, lat_gradient_c)
    t_with_elev = altitude_lapse_rate(t_lat, elevation_m, lapse_rate_c_km)
    return t_with_elev
