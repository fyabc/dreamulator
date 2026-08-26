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
    t_scale_c: float = 10.0,
) -> np.ndarray:
    """Temperature-dependent moist-adiabatic lapse rate (°C / km).

    Warm air holds more moisture → more latent heat release during ascent →
    lower effective lapse rate.  The parametrisation is a simple exponential
    interpolation between the warm (moist) and cold (dry) limits:

        Γ(T) = Γ_max − (Γ_max − Γ_min) × exp(−T / T_scale)

    At T =  0 °C    →  Γ ≈ Γ_max (cold, dry — little latent heating)
    At T ≫ T_scale  →  Γ → Γ_min (warm, moist — strong latent heating)

    Typical values at Earth's surface gravity:
        Γ_min = 4.5 °C/km  (tropical ocean, T ≈ 27 °C)
        Γ_max = 6.5 °C/km  (polar / high-altitude, T ≪ 0 °C)

    For planets with different gravity the limits scale with g/g⊕ because
    the dry adiabatic lapse rate Γ_d = g / cp.  Pass ``gamma_max`` and
    ``gamma_min`` scaled accordingly.

    Args:
        temperature_c: Surface air temperature (°C), shape (N,).
        gamma_max: Lapse rate in the cold (dry) limit (°C / km).
        gamma_min: Lapse rate in the warm (moist) limit (°C / km).
        t_scale_c: e-folding temperature scale (°C).

    Returns:
        Moist adiabatic lapse rate for each cell (°C / km), shape (N,).
    """
    delta = gamma_max - gamma_min
    return gamma_max - delta * np.exp(-np.maximum(temperature_c, -50.0) / t_scale_c)  # type: ignore[no-any-return]


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

    P(h) = P₀ exp(-h / H) - δP_T(T)

    where H ≈ 8500 m × (9.81/g) is the scale height (isothermal,
    Earth-composition air; H ∝ 1/g) and δP_T is the thermal pressure
    reduction (warmer air → lower pressure).

    Args:
        temperature_c: Temperature in °C, shape (N,).
        elevation_m: Elevation in metres, shape (N,).
        gravity_m_s2: Surface gravity (m/s²).  Sets the scale height.
        surface_pressure_hpa: Sea-level pressure P₀ (hPa).

    Returns:
        Approximate surface pressure in hPa, shape (N,).
    """
    # Barometric formula
    scale_height_m = 8500.0 * (9.81 / gravity_m_s2)
    p_barometric = surface_pressure_hpa * np.exp(-elevation_m / scale_height_m)

    # Normalise temperature for thermal pressure correction
    t_min, t_max = temperature_c.min(), temperature_c.max()
    if t_max - t_min < 1e-6:
        return p_barometric

    t_normalized = (temperature_c - t_min) / (t_max - t_min)
    # Thermal low: warm air expands → lower pressure
    p_thermal = p_barometric - 20.0 * t_normalized

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
    wind = np.zeros((n, 3), dtype=np.float64)
    for i in range(n):
        if abs(zonal_speed[i]) < 1e-9 and abs(merid_speed[i]) < 1e-9:
            continue
        node = mesh_nodes_xyz[i]
        # Local north: (0, 1, 0) projected to tangent plane
        north_vec = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        north_tangent = north_vec - np.dot(north_vec, node) * node
        north_norm = np.linalg.norm(north_tangent)
        if north_norm < 1e-9:
            continue
        north_tangent /= north_norm
        # Local east = north × radial (right-hand rule)
        east = np.cross(north_tangent, node)
        east_norm = np.linalg.norm(east)
        if east_norm < 1e-9:
            continue
        east /= east_norm
        wind[i] = east * zonal_speed[i] + north_tangent * merid_speed[i]

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

        # Group B: Arid — dryness threshold (Köppen 1936 / Kottek et al. 2006).
        #   P_threshold = 20·T + offset, offset ∈ {280 (warm-season wet),
        #   140 (even), 0 (cold-season wet)}.
        # When monthly precipitation is available, pick the offset by the
        # warm/cold-season concentration; otherwise fall back to "even" (140).
        # The threshold is clamped to a positive floor (1 mm): for T ≤ −7 °C the
        # empirical 20·T + offset goes ≤ 0, which would otherwise classify a
        # polar desert (P≈0, from BFS numerical noise ~1e-5 mm) as "humid" (D)
        # instead of arid — a latent bug exposed when warming pushes polar t_hot
        # above the E-group threshold.  ``<=`` + the 1 mm floor make P≈0 arid.
        if p_warm_mm is not None and p_cold_mm is not None:
            p_warm = p_warm_mm[i]
            p_cold = p_cold_mm[i]
            if p_warm > 0.7 * pa:
                offset = 280.0
            elif p_cold > 0.7 * pa:
                offset = 0.0
            else:
                offset = 140.0
        else:
            offset = 140.0
        dryness_threshold = max(20.0 * ta + offset, 1.0)

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

        # Group C: Temperate
        if tc > -3.0:
            if dry_summer_c[i]:
                # Dry summer (Mediterranean)
                if th > 22.0:
                    classes.append("Csa")
                elif th > 10.0 and tc > 0.0:
                    classes.append("Csb")
                else:
                    classes.append("Csc")
            elif dry_winter[i]:
                # Dry winter
                if th > 22.0:
                    classes.append("Cwa")
                elif th > 10.0:
                    classes.append("Cwb")
                else:
                    classes.append("Cwc")
            else:
                # Fully humid
                if th > 22.0:
                    classes.append("Cfa")
                elif th > 10.0:
                    classes.append("Cfb")
                else:
                    classes.append("Cfc")
            continue

        # Group D: Continental
        if dry_summer_d[i]:
            # Dry summer
            if th > 22.0:
                classes.append("Dsa")
            elif th > 10.0:
                classes.append("Dsb")
            else:
                classes.append("Dsc")
        elif dry_winter[i]:
            # Dry winter
            if th > 22.0:
                classes.append("Dwa")
            elif th > 10.0:
                classes.append("Dwb")
            else:
                classes.append("Dwc")
        else:
            # Fully humid
            if th > 22.0:
                classes.append("Dfa")
            elif th > 10.0:
                classes.append("Dfb")
            else:
                classes.append("Dfc")

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
