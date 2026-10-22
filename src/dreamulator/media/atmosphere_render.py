"""L5 atmosphere rendering for the orbital weather-globe chain.

This module replaces the preview's hand-drawn limb glow with a physically
grounded atmosphere: a spherical shell of Rayleigh-scattering molecules,
Mie-scattering aerosols and absorbing ozone, lit by the world's own star.  It
covers the first L5 increment from the orbital weather-globe requirement
notes (the layer stack there is surface sphere + translucent cloud shell +
atmosphere shell), plus ocean sun glint, a Hillaire-style multiple-scattering
lookup table, two cloud shells with a high-cirrus shadow, and a generic
eclipse-shadow interface; cloud-top height and city lights remain later
increments.

Model and references
--------------------
The radiative transfer follows the single-scattering formulation used by

* Bruneton & Neyret (2008), *Precomputed Atmospheric Scattering*, Computer
  Graphics Forum 27(4) — ray/shell geometry, exponential density profiles,
  transmittance lookup table, single-scattering integral;
* Hillaire (2020), *A Scalable and Production Ready Sky and Atmosphere
  Rendering Technique*, Computer Graphics Forum 39(4) — the RGB coefficient
  set (Rayleigh 5.802/13.558/33.1e-6 m^-1 at 680/550/440 nm, Mie scattering
  3.996e-6 m^-1, Mie absorption 0.444e-6 m^-1, ozone absorption
  0.650/1.881/0.085e-6 m^-1 in a 25 km tent of half-width 15 km), the Mie
  asymmetry g = 0.8, and the isotropic multiple-scattering LUT
  ``L1_mean / (1 - f_ms)``.

The star spectrum enters through the CIE 1931 colour-matching functions
(analytic multi-lobe fit of Wyman, Sloan & Shirley 2013, JCGT 2(2)).  The
Rayleigh coefficient at every wavelength is ``beta(550) * (550/lambda)^4``;
integrating the Planck spectrum against the CMFs yields the RGB coefficients
of the star-referenced display frame.  Since the scattering is linear in the
incident spectrum, these effective coefficients reproduce the exact
optically-thin scattered colour.  The star's colour is kept as one explicit
constant, ``light_color``: the default ``white_balance`` exposure divides out
the scene's direct daylight (the surface palette is authored for neutral
daylight), while ``exposure == "physical"`` keeps the K-star's warm cast and
the paler sky that follows.

Colour management is explicit: the surface PNG and cloud colour are sRGB,
so they are decoded to linear radiance before the radiative transfer and
encoded back to sRGB at the end.  Treating sRGB values as linear (as the
legacy preview did) crushes the midtones.

Epistemic status
----------------
The geometry, density profiles and coefficients are derived or taken from the
cited literature.  The vertical aerosol and ozone profiles are Earth-analogue
inputs (``mie_scale`` / ``ozone_scale`` expose them); they are not derived from
Nacrea's photochemistry.  Multiple scattering uses Hillaire's local isotropic
LUT, which roughly doubles the day-side in-scatter but cannot transport light
from the day side into the deep night-side atmosphere; polarisation and
spectral correlation between extinction and scattering are neglected.  The
cloud shell is a thin surface at a fixed altitude (L1 will supply cloud-top
height).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

# ---------------------------------------------------------------------------
# Physical constants and Earth-calibrated reference values
# ---------------------------------------------------------------------------

EARTH_RADIUS_KM = 6371.0
EARTH_GRAVITY = 9.80665

#: Rayleigh scattering at 550 nm for a 1 atm Earth-gravity column (m^-1).
RAYLEIGH_BETA_550 = 13.558e-6
#: Rayleigh scale height of the Earth standard atmosphere (km).
RAYLEIGH_SCALE_HEIGHT_EARTH_KM = 8.0
#: Mie (aerosol) scattering and absorption at sea level (m^-1).
MIE_SCATTER = 3.996e-6
MIE_ABSORB = 0.444e-6
#: Mie scale height of the Earth standard atmosphere (km).
MIE_SCALE_HEIGHT_KM = 1.2
#: Mie asymmetry parameter (Hillaire 2020; Cornette-Shanks/Heneyey-Greenstein).
MIE_ASYMMETRY = 0.8
#: Ozone absorption coefficients (m^-1), Earth column, R/G/B channels.
OZONE_ABSORB_RGB = (0.650e-6, 1.881e-6, 0.085e-6)
#: Ozone tent profile (Hillaire 2020): peak at 25 km, zero at 10 and 40 km.
OZONE_CENTER_KM = 25.0
OZONE_HALF_WIDTH_KM = 15.0

#: The atmosphere is truncated where the density has fallen by e^-12.
ATMOSPHERE_TOP_SCALE_HEIGHTS = 12.0

#: Default shell altitude of the L2 cloud deck; L1 cloud-top height replaces it.
CLOUD_ALTITUDE_KM = 4.0

#: sRGB primaries for the XYZ→linear-RGB conversion (IEC 61966-2-1).
_XYZ_TO_RGB = np.array(
    [
        [3.2406, -1.5372, -0.4986],
        [-0.9689, 1.8758, 0.0415],
        [0.0557, -0.2040, 1.0570],
    ]
)

_MOLAR_MASS_KG = {
    "N2": 0.0280134,
    "O2": 0.0319988,
    "AR": 0.039948,
    "CO2": 0.0440095,
    "CH4": 0.0160425,
}


# ---------------------------------------------------------------------------
# Star spectrum → display coefficients
# ---------------------------------------------------------------------------


def _gauss_lobe(
    wavelength_nm: np.ndarray, mu: float, sigma_lo: float, sigma_hi: float
) -> np.ndarray:
    """Asymmetric Gaussian lobe used by the Wyman et al. CMF fit."""
    sigma = np.where(wavelength_nm < mu, sigma_lo, sigma_hi)
    return np.asarray(np.exp(-0.5 * ((wavelength_nm - mu) / sigma) ** 2))


def cie_xyz_cmf(wavelength_nm: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """CIE 1931 x̄, ȳ, z̄ from the Wyman-Sloan-Shirley multi-lobe fit.

    Valid over 380–780 nm.  The fit is a fit, not the tabulated standard;
    the authors quantify the error as below the variance between human
    observer datasets.  It is used here so the star spectrum can enter the
    coefficients analytically rather than through a hand-picked colour.
    """
    x_bar = (
        1.056 * _gauss_lobe(wavelength_nm, 599.8, 37.9, 31.0)
        + 0.362 * _gauss_lobe(wavelength_nm, 442.0, 16.0, 26.7)
        - 0.065 * _gauss_lobe(wavelength_nm, 501.1, 20.4, 26.2)
    )
    y_bar = 0.821 * _gauss_lobe(wavelength_nm, 568.8, 46.9, 40.5) + 0.286 * _gauss_lobe(
        wavelength_nm, 530.9, 16.3, 31.1
    )
    z_bar = 1.217 * _gauss_lobe(wavelength_nm, 437.0, 11.8, 36.0) + 0.681 * _gauss_lobe(
        wavelength_nm, 459.0, 26.0, 13.8
    )
    return x_bar, y_bar, z_bar


def planck_spectral_radiance(wavelength_nm: np.ndarray, temperature_k: float) -> np.ndarray:
    """Planck spectral radiance (arbitrary scale) at the given wavelengths."""
    if temperature_k <= 0.0:
        raise ValueError("temperature_k must be positive")
    lam = np.asarray(wavelength_nm, dtype=np.float64) * 1e-9
    h = 6.62607015e-34
    c = 2.99792458e8
    k = 1.380649e-23
    exponent = h * c / (lam * k * temperature_k)
    return np.asarray((2.0 * h * c * c / lam**5) / np.expm1(exponent))


@dataclass(frozen=True)
class StarOptics:
    """Display-frame optical properties of a blackbody star.

    ``rayleigh_rgb`` is the Rayleigh coefficient per unit of the 550 nm
    reference, expressed in the star's sRGB display frame.  ``white_rgb`` is
    the star's sRGB white point (an unlit white Lambertian surface under this
    star); it converts between white-balanced and physical colour.
    """

    temperature_k: float
    rayleigh_rgb: tuple[float, float, float]
    white_rgb: tuple[float, float, float]


@lru_cache(maxsize=32)
def star_optics(temperature_k: float) -> StarOptics:
    """Derive the star's RGB Rayleigh weights and white point from its Planck spectrum."""
    wavelengths = np.arange(380.0, 781.0, 1.0)
    x_bar, y_bar, z_bar = cie_xyz_cmf(wavelengths)
    spectrum = planck_spectral_radiance(wavelengths, temperature_k)

    xyz = np.array(
        [
            float(np.trapezoid(spectrum * x_bar, wavelengths)),
            float(np.trapezoid(spectrum * y_bar, wavelengths)),
            float(np.trapezoid(spectrum * z_bar, wavelengths)),
        ]
    )
    white = np.clip(_XYZ_TO_RGB @ xyz, 0.0, None)
    if not np.any(white > 0.0):
        raise ValueError("star spectrum has no visible response")

    beta_lambda = (550.0 / wavelengths) ** 4
    beta_xyz = np.array(
        [
            float(np.trapezoid(spectrum * beta_lambda * x_bar, wavelengths)),
            float(np.trapezoid(spectrum * beta_lambda * y_bar, wavelengths)),
            float(np.trapezoid(spectrum * beta_lambda * z_bar, wavelengths)),
        ]
    )
    # White-balancing divides each display channel by the star's own white,
    # so an unlit white surface reads (1, 1, 1).
    beta_rgb = (_XYZ_TO_RGB @ beta_xyz) / white
    return StarOptics(
        temperature_k=float(temperature_k),
        rayleigh_rgb=(float(beta_rgb[0]), float(beta_rgb[1]), float(beta_rgb[2])),
        white_rgb=(float(white[0]), float(white[1]), float(white[2])),
    )


def mean_molar_mass_kg_mol(composition: dict[str, float] | None) -> float:
    """Mean molar mass (kg/mol) of a mole-fraction composition; Earth air if unknown."""
    if not composition:
        return 0.0289652
    total = 0.0
    mass = 0.0
    for species, fraction in composition.items():
        molar = _MOLAR_MASS_KG.get(species.upper())
        if molar is None:
            continue
        total += float(fraction)
        mass += float(fraction) * molar
    if total <= 0.0:
        return 0.0289652
    return mass / total


# ---------------------------------------------------------------------------
# Atmosphere model and transmittance lookup table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AtmosphereModel:
    """Physical description of an Earth-like scattering atmosphere.

    ``gravity_m_s2`` and ``surface_pressure_atm`` set the optical column
    relative to Earth; the scale height follows from hydrostatic equilibrium
    ``H = R_specific * T / g``.  ``atmosphere_temperature_k`` is a reference
    temperature for the scattering layer (273.15 K, the standard-atmosphere
    sea-level value), not the planet's surface temperature.  ``ground_albedo``
    is the Bond albedo used by the multiple-scattering LUT's ground-reflected
    term; the CLI fills it from ``planets.yaml``.
    """

    planet_radius_km: float = EARTH_RADIUS_KM
    gravity_m_s2: float = EARTH_GRAVITY
    surface_pressure_atm: float = 1.0
    atmosphere_temperature_k: float = 273.15
    mean_molar_mass_kg_mol: float = 0.0289652
    star_temperature_k: float = 5772.0
    mie_scale: float = 1.0
    ozone_scale: float = 1.0
    ground_albedo: float = 0.3

    @property
    def scale_height_km(self) -> float:
        specific_gas = 8.314462618 / max(self.mean_molar_mass_kg_mol, 1e-9)
        return specific_gas * self.atmosphere_temperature_k / self.gravity_m_s2 / 1000.0

    @property
    def top_altitude_km(self) -> float:
        return ATMOSPHERE_TOP_SCALE_HEIGHTS * self.scale_height_km

    @property
    def column_factor(self) -> float:
        """Optical column relative to Earth: p/p0 * g0/g."""
        return self.surface_pressure_atm * EARTH_GRAVITY / self.gravity_m_s2

    @property
    def star(self) -> StarOptics:
        return star_optics(self.star_temperature_k)

    @property
    def rayleigh_rgb(self) -> np.ndarray:
        """Effective Rayleigh coefficient per RGB channel (m^-1)."""
        scale = RAYLEIGH_BETA_550 * self.column_factor
        return np.asarray(np.array(self.star.rayleigh_rgb) * scale, dtype=np.float64)

    @property
    def mie_scatter(self) -> float:
        return MIE_SCATTER * self.column_factor * self.mie_scale

    @property
    def mie_absorb(self) -> float:
        return MIE_ABSORB * self.column_factor * self.mie_scale

    @property
    def ozone_absorb_rgb(self) -> np.ndarray:
        return np.asarray(np.array(OZONE_ABSORB_RGB) * self.ozone_scale, dtype=np.float64)

    def light_color(self, exposure: str = "white_balance") -> np.ndarray:
        """Star colour applied to the final image.

        ``white_balance`` returns (1, 1, 1): the camera neutralises the star,
        which matches the surface palette's visual intent.  ``physical``
        returns the star's own sRGB white divided by its luminance, so the
        scene keeps the star's warm cast.
        """
        if exposure == "white_balance":
            return np.ones(3, dtype=np.float64)
        if exposure != "physical":
            raise ValueError("exposure must be 'white_balance' or 'physical'")
        white = np.asarray(self.star.white_rgb, dtype=np.float64)
        luminance = float(0.2126 * white[0] + 0.7152 * white[1] + 0.0722 * white[2])
        return np.asarray(white / max(luminance, 1e-9), dtype=np.float64)


def _sample_lut_table(
    table: np.ndarray, top_altitude_km: float, altitude_km: np.ndarray, cos_zenith: np.ndarray
) -> np.ndarray:
    """Bilinear lookup in an (altitude, cos zenith) RGB table."""
    n_alt, n_mu, _ = table.shape
    a = np.clip(altitude_km / top_altitude_km, 0.0, 1.0) * (n_alt - 1)
    m = (np.clip(cos_zenith, -1.0, 1.0) + 1.0) * 0.5 * (n_mu - 1)
    a0 = np.clip(np.floor(a).astype(np.int64), 0, n_alt - 2)
    m0 = np.clip(np.floor(m).astype(np.int64), 0, n_mu - 2)
    fa = np.clip(a - a0, 0.0, 1.0)[..., None]
    fm = np.clip(m - m0, 0.0, 1.0)[..., None]
    t00 = table[a0, m0]
    t01 = table[a0, m0 + 1]
    t10 = table[a0 + 1, m0]
    t11 = table[a0 + 1, m0 + 1]
    result: np.ndarray = (
        t00 * (1.0 - fa) * (1.0 - fm)
        + t01 * (1.0 - fa) * fm
        + t10 * fa * (1.0 - fm)
        + t11 * fa * fm
    )
    return result


@dataclass(frozen=True)
class EclipseShadow:
    """A circular eclipse shadow on the planet surface.

    This is the rendering-side hand-off for satellite/planet eclipses: the
    astronomy layer computes the sub-shadow point, the umbra/penumbra angular
    radii on the sphere (``arcsin(shadow radius / planet radius)`` while the
    boundary intersects the surface) and the maximum darkening; the renderer
    only applies the profile.  The shadow
    attenuates direct sunlight on the surface and cloud shells; the
    atmosphere's in-scatter is not shadowed in this prototype.

    ``depth`` is the fractional darkening at the umbra centre (1 = fully
    black); the penumbra blends smoothly to zero at ``penumbra_radius_deg``.
    ``umbra_radius_deg = 0`` describes an annular/partial event (the occulter
    is smaller than the star): a smooth penumbra-only dimming.  When the
    shadow is wider than the planet, the umbra boundary lies off the surface;
    pass 90° (the whole visible hemisphere) and the profile saturates there.
    """

    center_lon_deg: float
    center_lat_deg: float
    umbra_radius_deg: float
    penumbra_radius_deg: float
    depth: float = 0.8

    def __post_init__(self) -> None:
        if self.umbra_radius_deg < 0.0:
            raise ValueError("umbra_radius_deg must be >= 0")
        if self.penumbra_radius_deg <= 0.0:
            raise ValueError("penumbra_radius_deg must be positive")
        if self.penumbra_radius_deg < self.umbra_radius_deg:
            raise ValueError("penumbra_radius_deg must be >= umbra_radius_deg")
        if not 0.0 <= self.depth <= 1.0:
            raise ValueError("eclipse depth must be in [0, 1]")

    def factor(self, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
        """Sunlight transmission factor (1 outside, ``1-depth`` in the umbra)."""
        lat0 = math.radians(self.center_lat_deg)
        lon0 = math.radians(self.center_lon_deg)
        lat = np.radians(lat_deg)
        dlon = np.radians(lon_deg) - lon0
        cosine = np.sin(lat) * math.sin(lat0) + np.cos(lat) * math.cos(lat0) * np.cos(dlon)
        distance = np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))
        span = max(self.penumbra_radius_deg - self.umbra_radius_deg, 1e-9)
        t = np.clip((distance - self.umbra_radius_deg) / span, 0.0, 1.0)
        blend = t * t * (3.0 - 2.0 * t)
        return np.asarray(1.0 - self.depth * (1.0 - blend), dtype=np.float64)


@dataclass(frozen=True)
class TransmittanceLUT:
    """Tabulated atmospheric transmittance to the star over (altitude, cos zenith)."""

    top_altitude_km: float
    table: np.ndarray  # (n_alt, n_mu, 3)

    def sample(self, altitude_km: np.ndarray, cos_zenith: np.ndarray) -> np.ndarray:
        """Bilinear lookup; returns shape ``altitude.shape + (3,)``."""
        return _sample_lut_table(self.table, self.top_altitude_km, altitude_km, cos_zenith)


def build_transmittance_lut(
    model: AtmosphereModel,
    *,
    n_alt: int = 64,
    n_mu: int = 128,
    n_steps: int = 32,
) -> TransmittanceLUT:
    """Integrate the optical depth from a point in the shell toward the star.

    A ray that intersects the planet is blocked (transmittance zero); the
    geometric cutoff plus the growing grazing path give the smooth terminator.
    """
    planet = model.planet_radius_km
    top = planet + model.top_altitude_km
    # Coefficients are per metre; the geometry below is in kilometres.
    beta_r = model.rayleigh_rgb * 1000.0
    beta_m_ext = (model.mie_scatter + model.mie_absorb) * 1000.0
    beta_o = model.ozone_absorb_rgb * 1000.0
    h_r = model.scale_height_km

    altitudes = np.linspace(0.0, model.top_altitude_km, n_alt)
    mus = np.linspace(-1.0, 1.0, n_mu)
    radius = planet + altitudes[:, None]
    radius2 = radius * radius
    along = radius * mus[None, :]
    perp2 = np.maximum(radius2 - along * along, 0.0)
    blocked = (along < 0.0) & (perp2 < planet * planet)

    t_end = -along + np.sqrt(np.maximum(along * along + top * top - radius2, 0.0))
    fractions = np.linspace(0.0, 1.0, n_steps)
    path = t_end[..., None] * fractions
    sample_radius = np.sqrt(perp2[..., None] + (along[..., None] + path) ** 2)
    height = np.maximum(sample_radius - planet, 0.0)

    rho_r = np.exp(-height / h_r)
    rho_m = np.exp(-height / MIE_SCALE_HEIGHT_KM)
    rho_o = np.clip(1.0 - np.abs(height - OZONE_CENTER_KM) / OZONE_HALF_WIDTH_KM, 0.0, None)

    extinction = (
        beta_r[None, None, None, :] * rho_r[..., None]
        + beta_m_ext * rho_m[..., None]
        + beta_o[None, None, None, :] * rho_o[..., None]
    )
    tau = np.sum(
        0.5
        * (extinction[..., 1:, :] + extinction[..., :-1, :])
        * np.diff(path, axis=-1)[..., None],
        axis=-2,
    )
    transmittance = np.exp(-tau)
    transmittance[blocked] = 0.0
    return TransmittanceLUT(top_altitude_km=model.top_altitude_km, table=transmittance)


@dataclass(frozen=True)
class MultiscatteringLUT:
    """Mean singly-scattered radiance plus the geometric multiple-scattering factor.

    The table stores ``L1_mean / (1 - f_ms)`` over (altitude, sun zenith
    cosine), following Hillaire (2020): ``L1_mean`` is the average of the
    singly-scattered radiance over all directions and ``f_ms`` is the fraction
    of light that scatters again.  The main march adds ``phi * sigma_s`` at
    every sample, which approximates all scattering orders past the first.
    """

    top_altitude_km: float
    table: np.ndarray  # (n_alt, n_mu, 3)

    def sample(self, altitude_km: np.ndarray, cos_zenith: np.ndarray) -> np.ndarray:
        return _sample_lut_table(self.table, self.top_altitude_km, altitude_km, cos_zenith)


#: Quasi-random sphere directions (R2 sequence; Roberts 2018) used by the
#: multiple-scattering LUT.  Deterministic and well distributed at n = 16–64.
_PHI2 = (1.32471795724474602596, 1.75487766624669276005)


def _sphere_directions(count: int) -> np.ndarray:
    """Return ``count`` roughly uniform unit vectors via the R2 sequence."""
    indices = np.arange(1, count + 1, dtype=np.float64)
    u = np.mod(0.5 + indices * _PHI2[0], 1.0)
    v = np.mod(0.5 + indices * _PHI2[1], 1.0)
    phi = 2.0 * math.pi * v
    sin_lambda = 2.0 * u - 1.0
    cos_lambda = np.sqrt(np.maximum(1.0 - sin_lambda * sin_lambda, 0.0))
    return np.stack([cos_lambda * np.cos(phi), cos_lambda * np.sin(phi), sin_lambda], axis=-1)


def build_multiscattering_lut(
    model: AtmosphereModel,
    transmittance: TransmittanceLUT,
    *,
    n_alt: int = 32,
    n_mu: int = 32,
    n_dirs: int = 16,
    n_steps: int = 16,
) -> MultiscatteringLUT:
    """Precompute the Hillaire (2020) multiple-scattering table.

    For every (altitude, sun zenith) grid point the routine marches a bundle
    of uniform directions through the shell.  Along each direction it
    accumulates the singly-scattered radiance (second scattering order) and
    the fraction of light that scatters again; the geometric series of higher
    orders collapses to ``1 / (1 - f_ms)``.  A ground-reflected term closes
    the bundle for rays that hit the surface.
    """
    planet = model.planet_radius_km
    top = planet + model.top_altitude_km
    beta_r = model.rayleigh_rgb * 1000.0
    beta_m_scat = float(model.mie_scatter * 1000.0)
    beta_m_ext = float((model.mie_scatter + model.mie_absorb) * 1000.0)
    beta_o = model.ozone_absorb_rgb * 1000.0
    h_r = model.scale_height_km
    g = MIE_ASYMMETRY

    altitudes = np.linspace(0.0, model.top_altitude_km, n_alt)
    mus = np.linspace(-1.0, 1.0, n_mu)
    radius = np.broadcast_to(planet + altitudes[:, None], (n_alt, n_mu)).ravel()
    mu_flat = np.broadcast_to(mus[None, :], (n_alt, n_mu)).ravel()
    # Local frame: z is up, the star lies in the x–z plane.
    light = np.stack(
        [np.sqrt(np.maximum(1.0 - mu_flat * mu_flat, 0.0)), np.zeros_like(mu_flat), mu_flat],
        axis=-1,
    )
    origin = np.stack([np.zeros_like(radius), np.zeros_like(radius), radius], axis=-1)
    radius2 = radius * radius

    l2_sum = np.zeros((radius.size, 3), dtype=np.float64)
    f_sum = np.zeros((radius.size, 3), dtype=np.float64)
    directions = _sphere_directions(n_dirs)

    for ray_dir in directions:
        along = radius * ray_dir[2]
        perp2 = np.maximum(radius2 - along * along, 0.0)
        hits_ground = perp2 < planet * planet
        t_ground = -along + np.sqrt(np.maximum(along * along + planet * planet - radius2, 0.0))
        t_top = -along + np.sqrt(np.maximum(along * along + top * top - radius2, 0.0))
        t_end = np.where(hits_ground, t_ground, t_top)
        step = t_end / max(n_steps, 1)
        optical_depth = np.zeros((radius.size, 3), dtype=np.float64)
        l2_dir = np.zeros((radius.size, 3), dtype=np.float64)
        f_dir = np.zeros((radius.size, 3), dtype=np.float64)

        cos_theta = light @ ray_dir

        for k in range(n_steps):
            t = step * (k + 0.5)
            point = origin + t[:, None] * ray_dir
            local_r = np.sqrt(np.maximum(np.sum(point * point, axis=-1), 1e-12))
            up = point / local_r[:, None]
            altitude = np.maximum(local_r - planet, 0.0)
            rho_r = np.exp(-altitude / h_r)
            rho_m = np.exp(-altitude / MIE_SCALE_HEIGHT_KM)
            rho_o = np.clip(
                1.0 - np.abs(altitude - OZONE_CENTER_KM) / OZONE_HALF_WIDTH_KM, 0.0, None
            )
            extinction = (
                beta_r[None, :] * rho_r[:, None]
                + beta_o[None, :] * rho_o[:, None]
                + beta_m_ext * rho_m[:, None]
            )
            optical_depth += extinction * step[:, None]
            transmittance_to_sample = np.exp(-optical_depth)

            mu_light = np.sum(up * light, axis=-1)
            sun_transmittance = transmittance.sample(altitude, mu_light)
            phase_r = 3.0 / (16.0 * math.pi) * (1.0 + cos_theta * cos_theta)
            phase_m = (1.0 - g * g) / (4.0 * math.pi * (1.0 + g * g - 2.0 * g * cos_theta) ** 1.5)
            scattering = (
                beta_r[None, :] * rho_r[:, None] * phase_r[:, None]
                + beta_m_scat * rho_m[:, None] * phase_m[:, None]
            )
            l2_dir += transmittance_to_sample * sun_transmittance * scattering * step[:, None]
            f_dir += (
                transmittance_to_sample
                * (beta_r[None, :] * rho_r[:, None] + beta_m_scat * rho_m[:, None])
                * step[:, None]
            )

        # Ground-reflected light closes the bundle where the ray hits the planet.
        ground_point = origin + t_end[:, None] * ray_dir
        ground_r = np.sqrt(np.maximum(np.sum(ground_point * ground_point, axis=-1), 1e-12))
        ground_up = ground_point / ground_r[:, None]
        mu_ground = np.sum(ground_up * light, axis=-1)
        ground_sun = transmittance.sample(np.zeros_like(ground_r), mu_ground)
        ground = (
            ground_sun
            * np.exp(-optical_depth)
            * np.clip(mu_ground, 0.0, None)[:, None]
            * model.ground_albedo
        )
        l2_dir += np.where(hits_ground[:, None], ground, 0.0)

        l2_sum += l2_dir
        f_sum += f_dir

    l2_mean = l2_sum / max(n_dirs, 1)
    f_mean = f_sum / max(n_dirs, 1)
    phi = np.clip(l2_mean / np.clip(1.0 - f_mean, 0.05, None), 0.0, None)
    return MultiscatteringLUT(
        top_altitude_km=model.top_altitude_km,
        table=np.asarray(phi.reshape(n_alt, n_mu, 3), dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# Ray marching and globe compositing
# ---------------------------------------------------------------------------


def _srgb_to_linear(value: np.ndarray) -> np.ndarray:
    """Decode an sRGB-encoded 0–1 array (IEC 61966-2-1) to linear radiance."""
    value = np.clip(value, 0.0, 1.0)
    return np.asarray(
        np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4),
        dtype=np.float64,
    )


def _linear_to_srgb(value: np.ndarray) -> np.ndarray:
    """Encode linear radiance to sRGB 0–1 for display."""
    value = np.clip(value, 0.0, 1.0)
    return np.asarray(
        np.where(value <= 0.0031308, value * 12.92, 1.055 * value ** (1.0 / 2.4) - 0.055),
        dtype=np.float64,
    )


def _sample_equirect(field: np.ndarray, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    """Bilinear equirectangular sample at (lat, lon) degrees; shape ``lat.shape``."""
    height, width = field.shape
    row = (90.0 - lat_deg) / 180.0 * height - 0.5
    col = (lon_deg + 180.0) / 360.0 * width - 0.5
    r0 = np.floor(row).astype(np.int64)
    c0 = np.floor(col).astype(np.int64)
    fr = row - r0
    fc = col - c0
    r0c = np.clip(r0, 0, height - 1)
    r1c = np.clip(r0 + 1, 0, height - 1)
    c0w = np.mod(c0, width)
    c1w = np.mod(c0 + 1, width)
    sampled: np.ndarray = (
        field[r0c, c0w] * (1.0 - fr) * (1.0 - fc)
        + field[r1c, c0w] * fr * (1.0 - fc)
        + field[r0c, c1w] * (1.0 - fr) * fc
        + field[r1c, c1w] * fr * fc
    )
    return sampled


def _sample_equirect_rgb(image: np.ndarray, lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    return np.stack(
        [_sample_equirect(image[..., c], lat_deg, lon_deg) for c in range(image.shape[2])],
        axis=-1,
    )


def _march_segment(
    *,
    origin_xy: tuple[np.ndarray, np.ndarray],
    origin_z: np.ndarray,
    b2: np.ndarray,
    f: np.ndarray,
    sun: np.ndarray,
    sigma_start: np.ndarray,
    sigma_end: np.ndarray,
    model: AtmosphereModel,
    lut: TransmittanceLUT,
    n_steps: int,
    ms_lut: MultiscatteringLUT | None = None,
    eclipse: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Single-scattering radiance and view transmittance over one ray segment.

    ``origin`` is the view-plane foot point ``b_vec``; a ray point is
    ``b_vec + sigma * f``.  The view direction toward the camera is ``+f``,
    so the scattering angle cosine is ``-sun·f``.
    """
    rows, cols = origin_z.shape
    beta_r = (model.rayleigh_rgb * 1000.0).astype(np.float32)
    beta_m_scat = float(model.mie_scatter * 1000.0)
    beta_m_ext = float((model.mie_scatter + model.mie_absorb) * 1000.0)
    beta_o = (model.ozone_absorb_rgb * 1000.0).astype(np.float32)
    h_r = model.scale_height_km
    planet = model.planet_radius_km

    cos_scatter = float(np.clip(-np.dot(sun, f), -1.0, 1.0))
    phase_r = 3.0 / (16.0 * math.pi) * (1.0 + cos_scatter * cos_scatter)
    g = MIE_ASYMMETRY
    phase_m = (1.0 - g * g) / (4.0 * math.pi * (1.0 + g * g - 2.0 * g * cos_scatter) ** 1.5)

    f_dot_sun = float(np.dot(f, sun))
    bx, by = origin_xy
    b_dot_sun = bx * float(sun[0]) + by * float(sun[1]) + origin_z * float(sun[2])
    step = np.abs(sigma_end - sigma_start) / max(n_steps, 1)
    radiance = np.zeros((rows, cols, 3), dtype=np.float32)
    transmittance = np.ones((rows, cols, 3), dtype=np.float32)

    for i in range(n_steps):
        frac = (i + 0.5) / n_steps
        sigma = sigma_start + (sigma_end - sigma_start) * frac
        radius = np.sqrt(np.maximum(b2 + sigma * sigma, 0.0))
        altitude = np.maximum(radius - planet, 0.0)
        mu = np.clip((b_dot_sun + sigma * f_dot_sun) / np.maximum(radius, 1e-6), -1.0, 1.0)

        sun_t = lut.sample(altitude, mu).astype(np.float32)
        rho_r = np.exp(-altitude / h_r)[..., None]
        rho_m = np.exp(-altitude / MIE_SCALE_HEIGHT_KM)[..., None]
        rho_o = np.clip(1.0 - np.abs(altitude - OZONE_CENTER_KM) / OZONE_HALF_WIDTH_KM, 0.0, None)[
            ..., None
        ]

        source = beta_r * rho_r * phase_r + beta_m_scat * rho_m * phase_m
        if ms_lut is not None:
            # Higher scattering orders: the LUT already contains the sun
            # transmittance and the directional average, so it must NOT be
            # multiplied by the direct sun transmittance again.
            multi = ms_lut.sample(altitude, mu).astype(np.float32)
            source = source * sun_t + multi * (beta_r * rho_r + beta_m_scat * rho_m)
            radiance += transmittance * source * step[..., None]
        else:
            radiance += transmittance * source * sun_t * step[..., None]

        extinction = beta_r * rho_r + beta_o * rho_o + beta_m_ext * rho_m
        transmittance *= np.exp(-extinction * step[..., None])

    if eclipse is not None:
        # Local approximation: the shadow is sampled at the column's surface
        # sub-point.  Aegis' umbra (9.8 planet radii) is far wider than the
        # atmosphere's 91 km depth, so a column is essentially uniformly lit
        # or shadowed; the approximation breaks down only for small shadows.
        radiance = radiance * np.asarray(eclipse, dtype=np.float32)[..., None]

    return radiance, transmittance


def render_globe_atmosphere(
    surface_rgb: np.ndarray,
    cloud_alpha: np.ndarray,
    cloud_alpha_high: np.ndarray | None = None,
    *,
    res: int = 1600,
    center_lon_deg: float = 90.0,
    center_lat_deg: float = 15.0,
    sun_lon_deg: float | None = None,
    sun_lat_deg: float = 20.0,
    model: AtmosphereModel | None = None,
    cloud_rgb: tuple[int, int, int] = (252, 250, 245),
    cloud_altitude_km: float = CLOUD_ALTITUDE_KM,
    cirrus_altitude_km: float = 9.0,
    cirrus_shadow_strength: float = 0.6,
    eclipse_shadow: EclipseShadow | None = None,
    eclipse_field: np.ndarray | None = None,
    cloud_shadows: bool = True,
    ocean_mask: np.ndarray | None = None,
    sun_glint: bool = True,
    water_roughness: float = 0.08,
    multiple_scattering: bool = True,
    exposure: str = "white_balance",
    auto_exposure: bool = True,
    view_samples: int = 14,
) -> np.ndarray:
    """Orthographic globe with a physical atmosphere shell.

    Layers, back to front: surface sphere, translucent cloud shell at
    ``cloud_altitude_km``, atmosphere shell.  The ray is split at the cloud
    shell so a partial cloud correctly shows the atmosphere behind it.  The
    atmosphere's in-scatter is integrated twice (above and below the cloud),
    and the cloud casts a shadow by sampling the deck where the surface's sun
    ray crosses it.

    Returns an ``(res, res, 3)`` uint8 image.  The view uses the same
    convention as :func:`dreamulator.media.cloud_render.render_globe_preview`:
    92% of the frame, orthographic, x = cos φ cos λ, y = sin φ,
    z = cos φ sin λ.
    """
    if model is None:
        model = AtmosphereModel(planet_radius_km=EARTH_RADIUS_KM)
    if exposure not in ("white_balance", "physical"):
        raise ValueError("exposure must be 'white_balance' or 'physical'")
    surface_rgb = _srgb_to_linear(np.asarray(surface_rgb, dtype=np.float64))
    cloud_alpha = np.asarray(cloud_alpha, dtype=np.float64)
    if surface_rgb.ndim != 3 or surface_rgb.shape[2] != 3:
        raise ValueError("surface_rgb must have shape (h, w, 3)")
    if cloud_alpha.shape != surface_rgb.shape[:2]:
        raise ValueError("cloud_alpha must match the surface grid")
    if cloud_alpha_high is not None:
        cloud_alpha_high = np.asarray(cloud_alpha_high, dtype=np.float64)
        if cloud_alpha_high.shape != surface_rgb.shape[:2]:
            raise ValueError("cloud_alpha_high must match the surface grid")
    if not 0.0 <= cirrus_shadow_strength <= 1.0:
        raise ValueError("cirrus_shadow_strength must be in [0, 1]")
    if ocean_mask is not None:
        ocean_mask = np.asarray(ocean_mask, dtype=np.float64)
        if ocean_mask.shape != surface_rgb.shape[:2]:
            raise ValueError("ocean_mask must match the surface grid")

    planet = model.planet_radius_km
    top = planet + model.top_altitude_km
    cloud_radius = planet + cloud_altitude_km
    high_active = cloud_alpha_high is not None
    if high_active and cirrus_altitude_km <= cloud_altitude_km:
        raise ValueError("cirrus_altitude_km must be above cloud_altitude_km")
    cloud_radius_high = planet + cirrus_altitude_km if high_active else cloud_radius

    lam_c = math.radians(center_lon_deg)
    phi_c = math.radians(center_lat_deg)
    if sun_lon_deg is None:
        sun_lon_deg = center_lon_deg - 25.0
    lam_s = math.radians(sun_lon_deg)
    phi_s = math.radians(sun_lat_deg)

    f = np.array(
        [math.cos(phi_c) * math.cos(lam_c), math.sin(phi_c), math.cos(phi_c) * math.sin(lam_c)]
    )
    right = np.array([-math.sin(lam_c), 0.0, math.cos(lam_c)])
    up = np.cross(right, f)
    sun = np.array(
        [math.cos(phi_s) * math.cos(lam_s), math.sin(phi_s), math.cos(phi_s) * math.sin(lam_s)]
    )

    half = res / 2.0
    py, px = np.mgrid[0:res, 0:res].astype(np.float64)
    vx = (px + 0.5 - half) / (half * 0.92)
    vy = (half - py - 0.5) / (half * 0.92)
    b2 = (vx * vx + vy * vy) * planet * planet
    b = np.sqrt(b2)

    origin = (vx * right[0] + vy * up[0]) * planet
    origin_y = (vx * right[1] + vy * up[1]) * planet
    origin_z = (vx * right[2] + vy * up[2]) * planet

    has_atmosphere = b < top
    hits_surface = b < planet
    hits_cloud = b < cloud_radius
    hits_cloud_high = b < cloud_radius_high if high_active else np.zeros_like(hits_cloud)

    sigma_entry = np.sqrt(np.maximum(top * top - b2, 0.0))
    sigma_surface = np.sqrt(np.maximum(planet * planet - b2, 0.0))
    sigma_cloud = np.sqrt(np.maximum(cloud_radius * cloud_radius - b2, 0.0))
    sigma_cloud_high = np.sqrt(np.maximum(cloud_radius_high * cloud_radius_high - b2, 0.0))
    sigma_end = np.where(hits_surface, sigma_surface, -sigma_entry)
    sigma_split_low = np.where(hits_cloud, sigma_cloud, sigma_end)
    sigma_split_high = (
        np.where(hits_cloud_high, sigma_cloud_high, sigma_end) if high_active else sigma_split_low
    )

    # Surface sub-point (also the local shadow sample for the atmosphere).
    s_lat = np.degrees(
        np.arcsin(np.clip((origin_y + sigma_surface * f[1]) / np.maximum(planet, 1e-9), -1, 1))
    )
    s_lon = np.degrees(np.arctan2(origin_z + sigma_surface * f[2], origin + sigma_surface * f[0]))
    if eclipse_field is not None:
        eclipse_field = np.asarray(eclipse_field, dtype=np.float64)
        if eclipse_field.shape != (res, res):
            raise ValueError("eclipse_field must have shape (res, res)")
    elif eclipse_shadow is not None:
        eclipse_field = np.asarray(eclipse_shadow.factor(s_lat, s_lon), dtype=np.float64)

    lut = build_transmittance_lut(model)
    ms_lut = build_multiscattering_lut(model, lut) if multiple_scattering else None
    radiance_upper, trans_upper = _march_segment(
        origin_xy=(origin, origin_y),
        origin_z=origin_z,
        b2=b2,
        f=f,
        sun=sun,
        sigma_start=sigma_entry,
        sigma_end=sigma_split_high,
        model=model,
        lut=lut,
        n_steps=view_samples,
        ms_lut=ms_lut,
        eclipse=eclipse_field,
    )
    radiance_middle, trans_middle = _march_segment(
        origin_xy=(origin, origin_y),
        origin_z=origin_z,
        b2=b2,
        f=f,
        sun=sun,
        sigma_start=sigma_split_high,
        sigma_end=sigma_split_low,
        model=model,
        lut=lut,
        n_steps=view_samples,
        ms_lut=ms_lut,
        eclipse=eclipse_field,
    )
    radiance_lower, trans_lower = _march_segment(
        origin_xy=(origin, origin_y),
        origin_z=origin_z,
        b2=b2,
        f=f,
        sun=sun,
        sigma_start=sigma_split_low,
        sigma_end=sigma_end,
        model=model,
        lut=lut,
        n_steps=view_samples,
        ms_lut=ms_lut,
        eclipse=eclipse_field,
    )

    # ---- Cloud shells: coverage, sun transmittance and pseudo-3D shading ----
    from scipy.ndimage import gaussian_filter

    emboss_sigma = 3.0
    emboss_relief = 8.0
    thick_base = 0.80
    thick_amp = 0.40
    sun_screen = np.array([np.dot(sun, right), np.dot(sun, up), np.dot(sun, f)])
    sun_screen = sun_screen / max(np.linalg.norm(sun_screen), 1e-9)
    tint = _srgb_to_linear(np.asarray(cloud_rgb, dtype=np.float64) / 255.0)

    def _cloud_layer(
        alpha_field: np.ndarray,
        sigma_shell: np.ndarray,
        altitude_km: float,
        hit_mask: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        coverage = np.zeros((res, res), dtype=np.float64)
        light = np.zeros((res, res, 3), dtype=np.float64)
        if not np.any(hit_mask):
            return coverage, light
        cx = origin + sigma_shell * f[0]
        cy = origin_y + sigma_shell * f[1]
        cz = origin_z + sigma_shell * f[2]
        c_radius = np.sqrt(np.maximum(cx * cx + cy * cy + cz * cz, 1e-9))
        c_lat = np.degrees(np.arcsin(np.clip(cy / c_radius, -1.0, 1.0)))
        c_lon = np.degrees(np.arctan2(cz, cx))
        coverage = np.clip(_sample_equirect(alpha_field, c_lat, c_lon), 0.0, 1.0) * hit_mask
        cos_cloud = np.clip((cx * sun[0] + cy * sun[1] + cz * sun[2]) / c_radius, -1.0, 1.0)
        sun_cloud = lut.sample(np.full_like(c_lat, altitude_km), cos_cloud)
        h_tex = gaussian_filter(alpha_field, emboss_sigma)
        h0 = _sample_equirect(h_tex, c_lat, c_lon)
        hx = _sample_equirect(h_tex, c_lat, c_lon + 360.0 / h_tex.shape[1])
        hy = _sample_equirect(h_tex, c_lat - 180.0 / h_tex.shape[0], c_lon)
        nx = -(hx - h0) * emboss_relief
        ny = -(hy - h0) * emboss_relief
        nlen = np.sqrt(nx * nx + ny * ny + 1.0)
        shade = np.clip((nx * sun_screen[0] + ny * sun_screen[1] + sun_screen[2]) / nlen, 0.0, 1.0)
        term = 0.45 + 0.95 * np.power(shade, 0.9)
        gate = np.clip(coverage / 0.15, 0.0, 1.0)
        thickness = thick_base + thick_amp * coverage
        light_mod = 1.0 + gate * (term * thickness - 1.0)
        light = tint * (sun_cloud * np.clip(cos_cloud, 0.0, None)[..., None] * light_mod[..., None])
        return coverage, light

    cloud_coverage, cloud_light = _cloud_layer(
        cloud_alpha, sigma_cloud, cloud_altitude_km, hits_cloud
    )
    if high_active:
        assert cloud_alpha_high is not None
        cloud_coverage_high, cloud_light_high = _cloud_layer(
            cloud_alpha_high, sigma_cloud_high, cirrus_altitude_km, hits_cloud_high
        )
    else:
        cloud_coverage_high = np.zeros((res, res), dtype=np.float64)
        cloud_light_high = np.zeros((res, res, 3), dtype=np.float64)

    # ---- Surface: sun transmittance, cloud shadow, Lambert ----
    surface = _sample_equirect_rgb(surface_rgb, s_lat, s_lon)
    n_x = (origin + sigma_surface * f[0]) / planet
    n_y = (origin_y + sigma_surface * f[1]) / planet
    n_z = (origin_z + sigma_surface * f[2]) / planet
    cos_surface = np.clip(n_x * sun[0] + n_y * sun[1] + n_z * sun[2], -1.0, 1.0)
    sun_surface = lut.sample(np.zeros_like(cos_surface), cos_surface)

    # ---- High cirrus shadow on the low cloud and surface ----
    # The cirrus is optically thin, so this is a subtle attenuation of the
    # direct sunlight where the sun ray from the low shell / surface crosses
    # the high shell.  The high cloud itself is not self-shadowed.
    if high_active and cirrus_shadow_strength > 0.0:
        assert cloud_alpha_high is not None

        def _shadow_alpha(
            px: np.ndarray, py: np.ndarray, pz: np.ndarray, radius2: float
        ) -> np.ndarray:
            along = px * sun[0] + py * sun[1] + pz * sun[2]
            disc = along * along + cloud_radius_high * cloud_radius_high - radius2
            t = -along + np.sqrt(np.maximum(disc, 0.0))
            qx = px + t * sun[0]
            qy = py + t * sun[1]
            qz = pz + t * sun[2]
            q_radius = np.sqrt(np.maximum(qx * qx + qy * qy + qz * qz, 1e-9))
            q_lat = np.degrees(np.arcsin(np.clip(qy / q_radius, -1.0, 1.0)))
            q_lon = np.degrees(np.arctan2(qz, qx))
            return np.asarray(
                np.clip(_sample_equirect(cloud_alpha_high, q_lat, q_lon), 0.0, 1.0),
                dtype=np.float64,
            )

        surface_alpha = _shadow_alpha(n_x * planet, n_y * planet, n_z * planet, planet * planet)
        surface_shadow = np.clip(1.0 - cirrus_shadow_strength * surface_alpha, 0.0, 1.0)
        sun_surface = sun_surface * surface_shadow[..., None]

        low_x = origin + sigma_cloud * f[0]
        low_y = origin_y + sigma_cloud * f[1]
        low_z = origin_z + sigma_cloud * f[2]
        low_alpha = _shadow_alpha(low_x, low_y, low_z, cloud_radius * cloud_radius)
        low_shadow = np.clip(1.0 - cirrus_shadow_strength * low_alpha, 0.0, 1.0)
        cloud_light = cloud_light * low_shadow[..., None]

    # ---- Eclipse shadow: direct sunlight on the surface and cloud shells ----
    # The atmosphere's in-scatter is attenuated by the same factor in
    # _march_segment, sampled at the surface sub-point.  That local
    # approximation is good for Aegis' umbra (9.8 planet radii wide, far
    # deeper than the atmosphere) but not a full 3-D shadowed transport.
    # The astronomy interface supplies the sub-shadow point and angular
    # radii via EclipseShadow.
    if eclipse_field is not None:
        sun_surface = sun_surface * eclipse_field[..., None]
        cloud_light = cloud_light * eclipse_field[..., None]
        cloud_light_high = cloud_light_high * eclipse_field[..., None]

    shadow = np.ones((res, res), dtype=np.float64)
    if cloud_shadows and np.any(hits_surface):
        # Where does the surface's sun ray cross the cloud shell?
        along = n_x * sun[0] + n_y * sun[1] + n_z * sun[2]
        # |P + t S|^2 = Rc^2 with |P| = R: t = -c + sqrt(c^2 + Rc^2 - R^2)
        t_shadow = -along * planet + np.sqrt(
            np.maximum((along * planet) ** 2 + cloud_radius * cloud_radius - planet * planet, 0.0)
        )
        sh_x = n_x * planet + t_shadow * sun[0]
        sh_y = n_y * planet + t_shadow * sun[1]
        sh_z = n_z * planet + t_shadow * sun[2]
        sh_radius = np.sqrt(np.maximum(sh_x * sh_x + sh_y * sh_y + sh_z * sh_z, 1e-9))
        sh_lat = np.degrees(np.arcsin(np.clip(sh_y / sh_radius, -1.0, 1.0)))
        sh_lon = np.degrees(np.arctan2(sh_z, sh_x))
        shadow = 1.0 - np.clip(_sample_equirect(cloud_alpha, sh_lat, sh_lon), 0.0, 1.0)
        shadow = np.where(hits_surface & (cos_surface > 0.0), shadow, 1.0)

    surface_radiance = (
        surface
        * sun_surface
        * np.clip(cos_surface, 0.0, None)[..., None]
        * shadow[..., None]
        * hits_surface[..., None]
    )

    # ---- Ocean sun glint (GGX microfacet lobe, water Fresnel) ----
    # The glint is the specular reflection of the star on wave facets.  GGX
    # with ``water_roughness`` as the slope parameter reproduces the broad,
    # slightly elongated highlight of a real full-disk ocean shot.  It is
    # additive to the diffuse ocean term and is occluded by clouds through the
    # regular layer composite (and by the cloud shadow term).
    if sun_glint and ocean_mask is not None:
        half = sun + f
        half = half / max(float(np.linalg.norm(half)), 1e-9)
        cos_half = np.clip(n_x * half[0] + n_y * half[1] + n_z * half[2], 0.0, 1.0)
        cos_view = np.clip(n_x * f[0] + n_y * f[1] + n_z * f[2], 0.0, 1.0)
        alpha = max(float(water_roughness), 1e-3)
        denom = cos_half * cos_half * (alpha * alpha - 1.0) + 1.0
        distribution = alpha * alpha / (math.pi * np.maximum(denom * denom, 1e-8))
        fresnel = 0.02 + 0.98 * (1.0 - cos_half) ** 5
        specular = np.minimum(
            distribution * fresnel / (4.0 * np.maximum(cos_view * cos_surface, 1e-4)),
            20.0,
        )
        ocean = _sample_equirect(ocean_mask, s_lat, s_lon).clip(0.0, 1.0)
        glint = specular * ocean * np.clip(cos_surface, 0.0, None) * shadow * hits_surface
        surface_radiance = surface_radiance + glint[..., None] * sun_surface

    # ---- Composite: upper atmosphere, cirrus shell, middle atmosphere,
    # low cloud shell, lower atmosphere, surface ----
    bottom = radiance_lower + trans_lower * surface_radiance
    low_image = radiance_middle + trans_middle * (
        cloud_coverage[..., None] * cloud_light + (1.0 - cloud_coverage[..., None]) * bottom
    )
    rgb = radiance_upper + trans_upper * (
        cloud_coverage_high[..., None] * cloud_light_high
        + (1.0 - cloud_coverage_high[..., None]) * low_image
    )
    rgb = np.where(has_atmosphere[..., None], rgb, 0.0)
    # Exposure.  ``white_balance`` behaves like a camera balanced on a white
    # card in the scene's daylight: the sub-solar surface transmittance is
    # divided out per channel, so the authored surface palette stays neutral
    # and the atmosphere's *relative* colour (blue halo, warm terminator)
    # remains visible.  ``physical`` keeps the star's sRGB white instead, so
    # the whole scene carries the K star's warm cast.
    overhead = lut.sample(np.zeros(1), np.ones(1))[0]
    if exposure == "white_balance":
        rgb = rgb / np.maximum(overhead, 1e-3)
    elif exposure == "physical":
        rgb = rgb * model.light_color("physical")

    # Normalise overall brightness to a white Lambertian surface at the
    # sub-solar point (the old preview used a 16% night floor, which the
    # physical model deliberately drops).  White balance already normalises
    # per channel; physical mode needs a scalar luminance gain.
    if auto_exposure and exposure == "physical":
        overhead_luminance = float(
            0.2126 * overhead[0] + 0.7152 * overhead[1] + 0.0722 * overhead[2]
        )
        rgb = rgb * max(min(1.0 / max(overhead_luminance, 1e-6), 2.0), 0.5)

    return np.asarray(np.clip(_linear_to_srgb(rgb), 0.0, 1.0) * 255.0, dtype=np.uint8)


def atmosphere_summary(
    model: AtmosphereModel,
    *,
    exposure: str = "white_balance",
    sun_glint: bool = True,
    water_roughness: float = 0.08,
    multiple_scattering: bool = True,
) -> dict[str, object]:
    """Small JSON-ready summary for ``meta.json``."""
    return {
        "model": "single-scattering Rayleigh/Mie/ozone (Bruneton 2008; Hillaire 2020)",
        "planet_radius_km": model.planet_radius_km,
        "gravity_m_s2": model.gravity_m_s2,
        "surface_pressure_atm": model.surface_pressure_atm,
        "atmosphere_temperature_k": model.atmosphere_temperature_k,
        "mean_molar_mass_kg_mol": model.mean_molar_mass_kg_mol,
        "scale_height_km": model.scale_height_km,
        "top_altitude_km": model.top_altitude_km,
        "star_temperature_k": model.star_temperature_k,
        "rayleigh_beta_rgb_per_m": [float(v) for v in model.rayleigh_rgb],
        "mie_scattering_per_m": model.mie_scatter,
        "mie_absorption_per_m": model.mie_absorb,
        "ozone_absorption_rgb_per_m": [float(v) for v in model.ozone_absorb_rgb],
        "mie_scale": model.mie_scale,
        "ozone_scale": model.ozone_scale,
        "sun_glint": sun_glint,
        "water_roughness": water_roughness,
        "multiple_scattering": multiple_scattering,
        "ground_albedo": model.ground_albedo,
        "exposure": exposure,
    }
