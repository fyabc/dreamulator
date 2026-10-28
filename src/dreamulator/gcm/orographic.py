"""Linear theory of orographic precipitation (Smith & Barstad 2004) — pure functions.

Used to downscale GCM precipitation over terrain the GCM grid does not resolve
(``docs/design/proposals/canvas-conditioning-structure.md`` §4.1).  For a uniform, saturated
upstream flow (U, V) over terrain ``h(x, y)`` on a regular grid, the orographic precipitation
transfer function in Fourier space is

    P̂(k, l) = C_w · i σ ĥ / [(1 − i m H_w)(1 + i σ τ_c)(1 + i σ τ_f)],   σ = U k + V l,

    m = sign(σ) · sqrt((N_m² − σ²) / σ² · (k² + l²))   if N_m² > σ²  (vertically propagating),
    m = i · sqrt((σ² − N_m²) / σ² · (k² + l²))         otherwise     (evanescent),

where C_w = ρ_s Γ_m / γ is the thermodynamic uplift sensitivity (kg m⁻³), H_w the water-vapour
scale height, N_m the moist buoyancy frequency, τ_c and τ_f the condensation and fallout times.
The physical precipitation is max(P_background + P_orographic, 0).  The source uses radian
wavenumbers (k = 2π/λ) and a non-rotating hydrostatic atmosphere; this module follows it.

Epistemic class: approximate derivation (linearised, steady, saturated flow).  τ_c = τ_f =
1000 s are the source's typical values (observation-informed, uncertainty a factor of two).
"""

from __future__ import annotations

import math

import numpy as np

#: Condensation and fallout time scales (s), Smith & Barstad (2004) typical values.
TAU_C_S = 1000.0
TAU_F_S = 1000.0
#: Water vapour gas constant (J kg⁻¹ K⁻¹) and latent heat of condensation (J kg⁻¹).
R_V = 461.5
R_D = 287.04
L_V = 2.5e6
CP_D = 1004.0


def saturation_vapour_pressure_pa(t_k: np.ndarray) -> np.ndarray:
    """Bolton (1980) saturation vapour pressure over water (Pa)."""
    t_c = np.asarray(t_k) - 273.15
    return np.asarray(611.2 * np.exp(17.67 * t_c / (t_c + 243.5)))


def moist_adiabatic_lapse_k_per_m(t_k: np.ndarray, p_pa: np.ndarray, g: float) -> np.ndarray:
    """Saturated adiabatic lapse rate Γ_m (K m⁻¹) at temperature and pressure."""
    es = saturation_vapour_pressure_pa(t_k)
    rs = 0.622 * es / np.maximum(np.asarray(p_pa) - es, 1.0)
    num = 1.0 + L_V * rs / (R_D * t_k)
    den = 1.0 + L_V**2 * rs * 0.622 / (CP_D * R_D * t_k**2)
    return np.asarray(g / CP_D * num / den)


def lt_parameters(
    t_surface_k: float, p_surface_pa: float, lapse_k_per_m: float, g: float
) -> tuple[float, float, float]:
    """(C_w kg m⁻³, H_w m, N_m s⁻¹) from the low-level state (Smith & Barstad 2004 §2).

    ``lapse_k_per_m`` is the environmental lapse rate γ (positive when temperature falls with
    height).  N_m² = (g / T)(Γ_m − γ) is clipped at a small positive value so the response stays
    in the propagating regime for nearly neutral profiles.
    """
    gamma_m = float(moist_adiabatic_lapse_k_per_m(np.array(t_surface_k), np.array(p_surface_pa), g))
    gamma = max(lapse_k_per_m, 1e-4)
    rho_s = float(saturation_vapour_pressure_pa(np.array(t_surface_k))) / (R_V * t_surface_k)
    c_w = rho_s * gamma_m / gamma
    h_w = R_V * t_surface_k**2 / (L_V * gamma)
    n_m2 = g / t_surface_k * (gamma_m - gamma)
    return c_w, h_w, math.sqrt(max(n_m2, 1e-8))


def orographic_precipitation(
    h_m: np.ndarray,
    dx_m: float,
    u_m_s: float,
    v_m_s: float,
    c_w: float,
    h_w_m: float,
    n_m_s: float,
    *,
    tau_c_s: float = TAU_C_S,
    tau_f_s: float = TAU_F_S,
    pad: int | None = None,
) -> np.ndarray:
    """Orographic precipitation anomaly (kg m⁻² s⁻¹, i.e. mm s⁻¹) on the grid of ``h_m``.

    Row index increases southward is NOT assumed: ``h_m[i, j]`` is at y = i·dx, x = j·dx with
    v along +i.  Zero-padding (default half the grid on each side) suppresses wrap-around.
    The result can be negative (lee-side drying); callers add it to a background and truncate.
    """
    h = np.asarray(h_m, dtype=np.float64)
    ny, nx = h.shape
    p = pad if pad is not None else max(ny, nx) // 2
    hp = np.pad(h, p, mode="constant")
    my, mx = hp.shape
    k = 2 * np.pi * np.fft.fftfreq(mx, d=dx_m)[None, :]
    l_ = 2 * np.pi * np.fft.fftfreq(my, d=dx_m)[:, None]
    sigma = u_m_s * k + v_m_s * l_
    kh2 = k**2 + l_**2
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = (n_m_s**2 - sigma**2) / sigma**2
        m = np.where(
            ratio > 0,
            np.sign(sigma) * np.sqrt(np.abs(ratio * kh2)),
            1j * np.sqrt(np.abs(ratio * kh2)),
        )
    m = np.where(np.isfinite(m), m, 0.0)
    hhat = np.fft.fft2(hp)
    trans = (
        c_w
        * 1j
        * sigma
        / ((1 - 1j * m * h_w_m) * (1 + 1j * sigma * tau_c_s) * (1 + 1j * sigma * tau_f_s))
    )
    trans[0, 0] = 0.0
    out = np.real(np.fft.ifft2(trans * hhat))
    return np.asarray(out[p : p + ny, p : p + nx])


def orographic_precipitation_buffered(
    h_buffer_m: np.ndarray,
    dx_m: float,
    u_m_s: float,
    v_m_s: float,
    c_w: float,
    h_w_m: float,
    n_m_s: float,
    *,
    core: tuple[slice, slice],
    tau_c_s: float = TAU_C_S,
    tau_f_s: float = TAU_F_S,
    pad: int | None = None,
) -> np.ndarray:
    """Evaluate a core within a supplied real-terrain buffer (mm s⁻¹).

    Remove the core's constant datum, then taper the surrounding buffer to
    zero with a half cosine on each side. Terrain and slopes inside the core
    stay unchanged. The buffer must contain actual surrounding terrain;
    zero padding is only the outer numerical extension. Callers establish
    buffer and overlap convergence for their terrain and atmosphere.

    This is an explicit numerical-boundary candidate. Thermodynamic state,
    saturation applicability and precipitation-budget closure are unchanged.
    """
    h = np.asarray(h_buffer_m, dtype=np.float64)
    if h.ndim != 2 or not np.isfinite(h).all():
        raise ValueError("h_buffer_m must be a finite two-dimensional terrain")
    if not np.isfinite(dx_m) or dx_m <= 0:
        raise ValueError("dx_m must be finite and positive")
    indices = []
    windows = []
    for selection, size in zip(core, h.shape, strict=True):
        start, stop, step = selection.indices(size)
        if step != 1 or not 0 < start < stop < size:
            raise ValueError("core requires a nonempty contiguous interior and a real buffer")
        window = np.ones(size)
        window[:start] = 0.5 * (1 - np.cos(np.pi * np.arange(start) / start))
        tail = size - stop
        window[stop:] = 0.5 * (1 + np.cos(np.pi * np.arange(1, tail + 1) / tail))
        indices.append(slice(start, stop))
        windows.append(window)
    core_indices = (indices[0], indices[1])
    relative = (h - np.mean(h[core_indices])) * windows[0][:, None] * windows[1][None, :]
    response = orographic_precipitation(
        relative,
        dx_m,
        u_m_s,
        v_m_s,
        c_w,
        h_w_m,
        n_m_s,
        tau_c_s=tau_c_s,
        tau_f_s=tau_f_s,
        pad=pad,
    )
    return np.asarray(response[core_indices])
