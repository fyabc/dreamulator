"""Steady, one-dimensional thermal diagnostic for an accumulating ice divide.

Robin (1955) uses vertical velocity w(z) = -a*z/H, with z measured from
the bed, and constant conductivity and heat capacity. This cold-column
approximation omits horizontal advection, strain/friction heating and the
advection due to basal melting. Its melt output is an energy-limited potential,
not an enthalpy solution or a prescribed sliding velocity.

Material properties follow PISM's ice configuration reference.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import erf

from .canvas_ice_surface import SECONDS_PER_YEAR
from .ice_sheets import RHO_ICE_KG_M3

ICE_CONDUCTIVITY_W_M_K = 2.1
ICE_HEAT_CAPACITY_J_KG_K = 2009.0
ICE_LATENT_HEAT_J_KG = 3.34e5
PRESSURE_MELTING_K_PA = 7.9e-8
ICE_DIFFUSIVITY_M2_S = ICE_CONDUCTIVITY_W_M_K / (RHO_ICE_KG_M3 * ICE_HEAT_CAPACITY_J_KG_K)


@dataclass(frozen=True)
class IceThermalColumn:
    basal_temperature_c: np.ndarray
    pressure_melting_temperature_c: np.ndarray
    conductive_flux_w_m2: np.ndarray
    basal_melt_potential_m_yr: np.ndarray
    diffusion_time_yr: np.ndarray


def steady_ice_column(
    surface_temperature_c: np.ndarray,
    ice_thickness_m: np.ndarray,
    accumulation_ice_m_yr: np.ndarray,
    basal_heat_flux_w_m2: np.ndarray,
    *,
    gravity_m_s2: float,
) -> IceThermalColumn:
    """Return a cold-column temperature and excess basal-energy diagnostic.

    Positive accumulation transports cold ice downward. Effective conductive
    length is H*integral(exp(-Pe*u**2/2), u=0..1), Pe=a*H/kappa. At a=0 this
    recovers the exact conductive column. Basal temperature is bounded by
    pressure melting; excess heat is expressed as potential melt. Ice-free
    columns have no basal ice melt. Heat flux is an explicit basal input,
    distinct from a planet's total internal or volcanic heat-release budget.
    """
    ts, h, a, q = np.broadcast_arrays(
        *[
            np.asarray(v, dtype=float)
            for v in (
                surface_temperature_c,
                ice_thickness_m,
                accumulation_ice_m_yr,
                basal_heat_flux_w_m2,
            )
        ]
    )
    if (
        not all(np.isfinite(v).all() for v in (ts, h, a, q))
        or any(np.any(v < 0) for v in (h, a, q))
        or not np.isfinite(gravity_m_s2)
        or gravity_m_s2 <= 0
    ):
        raise ValueError(
            "thermal columns need finite fields, nonnegative storage/forcing and gravity"
        )
    pe = a / SECONDS_PER_YEAR * h / ICE_DIFFUSIVITY_M2_S
    root = np.sqrt(pe / 2)
    factor = np.divide(np.sqrt(np.pi) * erf(root), 2 * root, out=np.ones_like(h), where=pe > 0)
    length = h * factor
    melting = -PRESSURE_MELTING_K_PA * RHO_ICE_KG_M3 * gravity_m_s2 * h
    required = np.divide(
        ICE_CONDUCTIVITY_W_M_K * np.maximum(melting - ts, 0),
        length,
        out=np.zeros_like(h),
        where=h > 0,
    )
    conducted = np.minimum(q, required)
    excess = np.where(h > 0, q - conducted, 0)
    temperature = np.where(h > 0, np.minimum(ts + q * length / ICE_CONDUCTIVITY_W_M_K, melting), ts)
    return IceThermalColumn(
        temperature,
        melting,
        conducted,
        excess * SECONDS_PER_YEAR / (RHO_ICE_KG_M3 * ICE_LATENT_HEAT_J_KG),
        h**2 / ICE_DIFFUSIVITY_M2_S / SECONDS_PER_YEAR,
    )
