"""Planetary dynamo estimates — gas-giant magnetic fields and dipole moments.

Pure physics module for the magnetic-field estimate side of the
``magnetic_field_strength`` consistency contract: the astronomy layer's
system catalog records an authored value (planets.yaml, authoritative) plus a
formula estimate in ``derived`` and warns when the two disagree by more than
the engine consistency threshold (same epistemic pattern as the star
mass–luminosity check in ``astronomy.py``).

Estimates use the energy-flux dynamo scaling of Christensen, Holzwarth &
Reiners (2009) in a Jupiter-anchored ratio form. In the rapidly rotating
(dipole-dominated, saturated) regime the scaling is

    <B>^2 / (2 mu_0) = c * f_ohm * <rho>^(1/3) * (F q_0)^(2/3)

with c = 0.63 fitted from dynamo simulations; field strength is *independent*
of rotation rate and diffusivity. With <rho> approximated by the bulk mean
density 3M/(4 pi R^3) and the convective flux q_0 ~ L / R^2 at the dynamo
top, the surface equatorial dipole field relative to Jupiter is

    B / B_J = (M/M_J)^(1/6) * (L/L_J)^(1/3) * (R_J/R)^(7/6)

Anchoring the prefactor to Jupiter's observed field cancels the structural
efficiency factor F and the internal-to-surface conversion (B/B_dip ~ 7,
dynamo top at 0.84 R) into a single calibration point, so only *ratios* of
the COND03 luminosity table enter — its known over-luminosity zero-point
(table Jupiter vs observed Jupiter) cancels exactly.

Domain and limits (documented, not silently applied):

- Applicable to rapidly rotating fluid dynamos — giant planets in practice.
  Terrestrial-core dynamos (Earth, Nacrea) are outside the domain and stay
  authored-only.
- Saturn-like stably stratified conducting layers and Uranus/Neptune thin
  shell dynamos are excluded by the source paper; no such bodies are
  estimated here (single-point anchor cannot express those structures).
- The anchor does not capture the dynamo-depth variation the source paper
  folds in for the most massive young giants, so estimates at 5-10 M_J run
  low by roughly a factor 1.5 (cross-check below); acceptable for a
  consistency-check estimate, epistemic class "approximate derivation,
  single-point calibrated".

References:
    Christensen, U. R., Holzwarth, V., & Reiners, A. (2009). Energy flux
        determines magnetic field strength of planets and stars.
        Nature, 457, 167-169. doi:10.1038/nature07626
    Baraffe, I., Chabrier, G., Barman, T. S., Allard, F., & Hauschildt, P. H.
        (2003). Evolutionary models for cool brown dwarfs and extrasolar
        giant planets. A&A, 402, 701-712. COND isochrones; log L digitized
        from https://perso.ens-lyon.fr/isabelle.baraffe/COND03_models
    Connerney, J. E. P. (1993). Magnetic fields of the outer planets.
        J. Geophys. Res., 98, 18659-18679. (Jupiter surface dipole anchor)
"""

from __future__ import annotations

import bisect
import math

from dreamulator.engine.stellar_physics import L_SUN_W

# ==== Jupiter anchor ====

#: Jupiter surface equatorial dipole field (microtesla), Connerney (1993).
JUPITER_EQ_DIPOLE_UT: float = 428.0

#: IAU nominal mean Jupiter radius (km).
JUPITER_RADIUS_KM: float = 69911.0

#: Jupiter mass in Earth masses (IAU nominal ratio).
JUPITER_MASS_EARTH: float = 317.8

#: Vacuum permeability (SI).
MU_0: float = 4.0 * math.pi * 1e-7

# ==== COND03 intrinsic-luminosity grid (Baraffe et al. 2003) ====
# log10(L/L_sun) for solar-composition COND cooling tracks, digitized at
# five ages (rows, Gyr) x five masses (columns, M_Jup). Domain 0.5-10 M_Jup
# and 0.1-10 Gyr; outside the grid the nearest edge is used (no extrapolation).
_COND_AGES_GYR: tuple[float, ...] = (0.1, 0.5, 1.0, 5.0, 10.0)
_COND_MASSES_MJ: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0, 10.0)
_COND_LOG_L: tuple[tuple[float, ...], ...] = (
    (-7.45, -6.99, -6.42, -5.73, -5.03),
    (-8.46, -7.80, -7.25, -6.53, -5.91),
    (-8.90, -8.23, -7.60, -6.87, -6.27),
    (-10.00, -9.31, -8.62, -7.69, -7.06),
    (-10.57, -9.84, -9.11, -8.14, -7.41),
)


_COND_LOG_MASSES: tuple[float, ...] = tuple(math.log(m) for m in _COND_MASSES_MJ)
_COND_LOG_AGES: tuple[float, ...] = tuple(math.log(a) for a in _COND_AGES_GYR)


def _cond_log_luminosity(mass_mj: float, age_gyr: float) -> float:
    """Bilinear (log mass x log age) interpolation of the COND03 grid.

    Nearest-edge clamping outside the digitized domain — the dynamo scaling
    only uses luminosity *ratios* at one age, so an edge-clamped mass or age
    degrades gracefully instead of extrapolating.
    """
    x = math.log(min(max(mass_mj, _COND_MASSES_MJ[0]), _COND_MASSES_MJ[-1]))
    y = math.log(min(max(age_gyr, _COND_AGES_GYR[0]), _COND_AGES_GYR[-1]))
    j = max(1, min(bisect.bisect_left(_COND_LOG_MASSES, x), len(_COND_MASSES_MJ) - 1))
    i = max(1, min(bisect.bisect_left(_COND_LOG_AGES, y), len(_COND_AGES_GYR) - 1))
    x0, x1 = _COND_LOG_MASSES[j - 1], _COND_LOG_MASSES[j]
    y0, y1 = _COND_LOG_AGES[i - 1], _COND_LOG_AGES[i]
    tx = (x - x0) / (x1 - x0)
    ty = (y - y0) / (y1 - y0)
    z00, z01 = _COND_LOG_L[i - 1][j - 1], _COND_LOG_L[i - 1][j]
    z10, z11 = _COND_LOG_L[i][j - 1], _COND_LOG_L[i][j]
    return (z00 * (1 - tx) + z01 * tx) * (1 - ty) + (z10 * (1 - tx) + z11 * tx) * ty


def estimate_intrinsic_luminosity_w(mass_mj: float, age_gyr: float) -> float:
    """Intrinsic (residual-heat) luminosity of a giant planet in watts.

    COND03 grid interpolation; accuracy is roughly a factor of two across the
    domain (hot-start models, no clouds). The dynamo estimate consumes
    L^(1/3), so this propagates as about +-25% on the field.
    """
    return float(10.0 ** _cond_log_luminosity(mass_mj, age_gyr) * L_SUN_W)


def estimate_magnetic_field_ut(
    mass_earth: float,
    radius_km: float,
    age_gyr: float,
    luminosity_w: float | None = None,
) -> float:
    """Estimated surface equatorial dipole field of a gas giant (microtesla).

    Args:
        mass_earth: body mass in Earth masses.
        radius_km: body radius in km.
        age_gyr: system age in Gyr (planets share the star's age).
        luminosity_w: authored intrinsic luminosity in watts; when None the
            COND03 table provides it. Either way the ratio is taken against
            the table's own 1 M_Jup track at the same age, so the table's
            luminosity zero-point cancels.

    Returns:
        Estimated field in microtesla (Jupiter-anchored ratio form above).
    """
    mass_mj = mass_earth / JUPITER_MASS_EARTH
    if luminosity_w is not None:
        lum_ratio = luminosity_w / (10.0 ** _cond_log_luminosity(1.0, age_gyr) * L_SUN_W)
    else:
        lum_ratio = 10.0 ** (
            _cond_log_luminosity(mass_mj, age_gyr) - _cond_log_luminosity(1.0, age_gyr)
        )
    radius_ratio = JUPITER_RADIUS_KM / radius_km
    return float(
        JUPITER_EQ_DIPOLE_UT
        * ((mass_mj ** (1.0 / 6.0)) * (lum_ratio ** (1.0 / 3.0)) * (radius_ratio ** (7.0 / 6.0)))
    )


def dipole_moment_am2(field_ut: float, radius_km: float) -> float:
    """Magnetic dipole moment (A m^2) from a surface equatorial field.

    B_eq = mu_0 m / (4 pi R^3) inverted; matches the hand derivation in
    nacrea's ``layers/astronomy/input/coupled_magnetic.md`` (400 uT at
    71,355 km -> 1.453e27 A m^2).
    """
    r_m = radius_km * 1000.0
    return field_ut * 1e-6 * (4.0 * math.pi * r_m**3) / MU_0


def dipole_field_at_distance_ut(field_ut: float, radius_km: float, distance_km: float) -> float:
    """Equatorial dipole field (microtesla) at ``distance_km`` from the centre.

    Pure geometric falloff B ~ r^-3 of a dipole: the parent planet's field at
    a satellite's orbit (nacrea canon: 400 uT x (71,355/723,300)^3 ~ 0.38 uT).
    """
    return field_ut * (radius_km / distance_km) ** 3
