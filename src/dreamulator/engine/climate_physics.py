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
    return (absorbed / SIGMA_SB) ** 0.25


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
    pole ≈ -15 °C when T_mean = 15 °C and ΔT = 45 °C — matching Earth.

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
    return t_equator - lat_gradient_c * np.sin(lat_rad) ** 2


def altitude_lapse_rate(
    temperature_c: np.ndarray,
    elevation_m: np.ndarray,
    lapse_rate_c_km: float = 6.5,
) -> np.ndarray:
    """Correct temperature for altitude using the moist adiabatic lapse rate.

    T(h) = T_surface - Γ × h
    Γ ≈ 6.5 °C/km (moist), 9.8 °C/km (dry)

    Args:
        temperature_c: Surface-level temperature (°C), shape (N,).
        elevation_m: Elevation in metres, shape (N,).
        lapse_rate_c_km: Lapse rate in °C per km.  Earth: 6.5 (moist), 9.8 (dry).

    Returns:
        Altitude-corrected temperature (°C), shape (N,).
    """
    return temperature_c - lapse_rate_c_km * (elevation_m / 1000.0)


def seasonal_temperature(
    t_mean_c: np.ndarray,
    lat_rad: np.ndarray,
    axial_tilt_deg: float = 23.44,
    orbital_period_days: float = 365.25,
    day_of_year: float = 0.0,
    seasonal_amplitude_c: float = 35.0,
) -> dict[str, np.ndarray]:
    """Compute seasonal temperature at a given day of year.

    The seasonal cycle is driven by the planet's axial tilt (obliquity ε).
    The solar declination varies between -ε and +ε over the orbital period.

    The effective seasonal deviation from mean is:
        deviation = seasonal_amplitude_c * sin²(lat) * √sin(ε)

    Earth calibration (seasonal_amplitude_c=30):
        60°N: deviation ≈ 14.2°C (T_hot ≈ 10-12°C → D climate)
        45°N: deviation ≈ 9.5°C
        30°N: deviation ≈ 4.7°C

    Args:
        t_mean_c: Mean annual temperature (°C), shape (N,).
        lat_rad: Latitude in radians, shape (N,).
        axial_tilt_deg: Axial obliquity in degrees.
        orbital_period_days: Length of year in days.
        day_of_year: Day of year (0 = northern winter solstice).
        seasonal_amplitude_c: Base amplitude scaling factor (°C).
            Earth: 30. Higher values → larger seasonal swings.

    Returns:
        dict with keys:
            'today': Temperature on given day (°C).
            'jan': Northern winter (day 0) temperature.
            'jul': Northern summer (day 182) temperature.
            'annual_range': Annual temperature range (°C).
    """
    epsilon = np.radians(axial_tilt_deg)

    # Solar declination on the given day
    solar_dec = epsilon * np.sin(2.0 * np.pi * day_of_year / orbital_period_days)

    # Seasonal temperature amplitude at each latitude.
    # Effective deviation = amplitude * sin(lat) = A * sin²(lat) * √sin(ε)
    # This gives ~14°C at 60°N, ~9.5°C at 45°N for Earth (A=30).
    amplitude = seasonal_amplitude_c * np.abs(np.sin(lat_rad)) * (np.sin(epsilon) ** 0.5)

    # Temperature today = mean + amplitude * sin(solar_dec) * sin(lat)
    #  sin(solar_dec) * sin(lat) > 0 → summer, < 0 → winter
    t_today = t_mean_c + amplitude * np.sign(solar_dec) * np.sin(lat_rad)

    # Jan (northern winter): solar_dec ≈ -ε
    t_jan = t_mean_c - amplitude * np.sign(epsilon) * np.sin(lat_rad)

    # Jul (northern summer): solar_dec ≈ +ε
    t_jul = t_mean_c + amplitude * np.sign(epsilon) * np.sin(lat_rad)

    annual_range = 2.0 * amplitude

    return {
        "today": t_today,
        "jan": t_jan,
        "jul": t_jul,
        "annual_range": annual_range,
    }


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
    return 2.0 * omega * np.sin(lat_rad)


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

    return np.clip(p_thermal, 0.5 * surface_pressure_hpa, 1.07 * surface_pressure_hpa)


def hadley_cell_wind(
    lat_rad: np.ndarray,
    mesh_nodes_xyz: np.ndarray,
    hadley_extent_deg: float = 30.0,
    polar_cell_start_deg: float = 60.0,
) -> np.ndarray:
    """Simplified Hadley / Ferrel / Polar cell wind circulation.

    Produces zonally-averaged meridional (N-S) and zonal (E-W) wind
    components from the three-cell model of atmospheric circulation.

    Cell boundaries (parameterized, 3A.3a):
        0°–H: Hadley cell  → surface trade winds (E→W in tropics)
        H°–P°: Ferrel cell → surface westerlies (W→E in mid-latitudes)
        P°–90°: Polar cell  → surface easterlies (E→W near poles)

    Earth defaults H=30°, P=60°.  Slow rotators (weak Coriolis) have an
    expanded Hadley cell (~Ω^-1/2 scaling); gaia-m uses H=55°, P=75°.

    Args:
        lat_rad: Latitude in radians, shape (N,).
        mesh_nodes_xyz: Unit sphere coordinates, shape (N, 3).
        hadley_extent_deg: Hadley cell poleward boundary H (°).
        polar_cell_start_deg: Polar cell equatorward boundary P (°).

    Returns:
        Wind velocity vectors (m/s) tangent to sphere, shape (N, 3).
    """
    n = len(lat_rad)
    lat_deg = np.degrees(lat_rad)
    h = float(hadley_extent_deg)
    p = float(polar_cell_start_deg)

    # Zonal (E-W) wind speed: positive = eastward (westerly), negative = westward (easterly)
    zonal_speed = np.zeros(n, dtype=np.float64)

    # Hadley cell: equator → H: trade winds (easterly), peak at equator
    hadley_mask = np.abs(lat_deg) < h
    zonal_speed[hadley_mask] = -5.0 * np.cos(np.pi * lat_deg[hadley_mask] / (2.0 * h))

    # Ferrel cell: H → P: westerlies, peak at cell centre
    ferrel_mask = (np.abs(lat_deg) >= h) & (np.abs(lat_deg) < p)
    zonal_speed[ferrel_mask] = 8.0 * np.cos(
        np.pi * (np.abs(lat_deg[ferrel_mask]) - (h + p) / 2.0) / (p - h)
    )

    # Polar cell: P → 90°: polar easterlies, peak at pole
    polar_mask = np.abs(lat_deg) >= p
    zonal_speed[polar_mask] = -3.0 * np.cos(
        np.pi * (90.0 - np.abs(lat_deg[polar_mask])) / (2.0 * (90.0 - p))
    )

    # Convert zonal wind to 3D tangent vectors
    wind = np.zeros((n, 3), dtype=np.float64)
    for i in range(n):
        if abs(zonal_speed[i]) < 1e-9:
            continue
        # East direction at this point: tangent to the latitude circle
        node = mesh_nodes_xyz[i]
        # Local north: (0, 1, 0) projected to tangent plane
        north = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        north_tangent = north - np.dot(north, node) * node
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
        wind[i] = east * zonal_speed[i]

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
    base_mm: float = 2000.0,
) -> np.ndarray:
    """Surface evaporation rate based on temperature and water availability.

    Clausius-Clapeyron: evaporation increases ~7% per °C warming.

    Args:
        temperature_c: Temperature in °C, shape (N,).
        is_ocean: Boolean mask, True for ocean cells.
        base_mm: Base annual evaporation at 15 °C tropical ocean (mm/yr).

    Returns:
        Annual evaporation in mm, shape (N,).
    """
    evap = np.zeros(len(temperature_c), dtype=np.float64)
    # Only ocean cells evaporate
    ocean_mask = np.asarray(is_ocean, dtype=bool)
    # 7% per °C above 15 °C reference
    evap[ocean_mask] = base_mm * (1.0 + 0.07 * (temperature_c[ocean_mask] - 15.0))
    return np.maximum(evap, 0.0)


def orographic_precipitation(
    moisture_in: np.ndarray,
    elev_diff_m: float,
    efficiency: float = 0.5,
) -> tuple[float, float]:
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
        return 0.0, moisture_in

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
    return np.degrees(itcz) + 5.0  # mean NH offset


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

    Args:
        t_mean_c: Mean annual temperature (°C), shape (N,).
        t_cold_c: Coldest month mean temperature (°C), shape (N,).
        t_hot_c: Hottest month mean temperature (°C), shape (N,).
        p_annual_mm: Annual precipitation (mm), shape (N,).
        p_dry_mm: Driest month precipitation (mm), shape (N,).
        p_wet_mm: Wettest month precipitation (mm), shape (N,).
        is_land: Boolean mask, True for land cells.

    Returns:
        List of Köppen codes (e.g. 'Cfa', 'BWh', 'ET', 'Am').  Ocean → 'Ocean'.
    """
    n = len(t_mean_c)
    classes: list[str] = []

    for i in range(n):
        if not is_land[i]:
            classes.append("Ocean")
            continue

        tc, th, ta = t_cold_c[i], t_hot_c[i], t_mean_c[i]
        pa, pd, pw = p_annual_mm[i], p_dry_mm[i], p_wet_mm[i]

        # Group E: Polar
        if th < 10.0:
            if th > 0.0:
                classes.append("ET")  # Tundra
            elif th > -10.0:
                classes.append("EF")  # Ice cap
            else:
                classes.append("EF")
            continue

        # Group B: Arid — dryness threshold
        # Simple formula: annual precip < 20 × T_annual + (offset based on seasonality)
        if pw > 2.0 * pd:
            dry_offset = 280.0  # summer-dry
        elif pd > 2.0 * pw:
            dry_offset = 140.0  # winter-dry
        else:
            dry_offset = 0.0

        dryness_threshold = 20.0 * ta + dry_offset

        if pa < dryness_threshold:
            if ta > 18.0:
                if pa < 10.0 * ta:
                    classes.append("BWh")  # Hot desert
                else:
                    classes.append("BSh")  # Hot steppe
            else:
                if pa < 10.0 * ta:
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
            if pw > 3.0 * pd and pd < 40.0:
                # Dry summer (Mediterranean)
                if th > 22.0:
                    classes.append("Csa")
                elif th > 10.0 and tc > 0.0:
                    classes.append("Csb")
                else:
                    classes.append("Csc")
            elif pd < 30.0 and pw < 10.0 * pd:
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
        if pw > 3.0 * pd and pd < 40.0:
            # Dry summer
            if th > 22.0:
                classes.append("Dsa")
            elif th > 10.0:
                classes.append("Dsb")
            else:
                classes.append("Dsc")
        elif pd < 30.0 and pw < 10.0 * pd:
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
