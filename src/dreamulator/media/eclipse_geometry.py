"""Occultation geometry for rendering an eclipse on the planet's day side.

A moon-sized occluder (Aegis for nacrea) between the star and the planet
casts an eclipse whose local depth varies across the visible disk: for each
surface normal the angular separation between the occluder centre and the
star decides the fraction of the stellar disk still visible.  The geometry is
exact for circular disks — no circular-spot approximation of the shadow.

The occluder's sky position is parameterised by the impact parameter ``b``:
the perpendicular offset (km) of the occluder centre from the star-planet
axis.  ``b = 0`` is mid-eclipse; the eclipse band sweeps across the disk as
``b`` runs from positive through zero to negative.
"""

from __future__ import annotations

import math

import numpy as np


def disk_coverage(
    sep: np.ndarray | float, radius_big: float, radius_small: float
) -> np.ndarray | float:
    """Fraction of the small disk (the star) hidden behind the big disk.

    Exact circular-lens overlap area divided by the small disk's area:
    full coverage at zero separation, zero once the disks separate, and the
    lens formula in between.
    """
    sep_arr = np.asarray(sep, dtype=np.float64)
    full = sep_arr <= radius_big - radius_small
    none = sep_arr >= radius_big + radius_small
    partial = ~(full | none)
    cov = np.zeros_like(sep_arr)
    cov[full] = 1.0
    if np.any(partial):
        s = sep_arr[partial]
        big, small = radius_big, radius_small
        a1 = big * big * np.arccos((s * s + big * big - small * small) / (2 * s * big))
        a2 = small * small * np.arccos((s * s + small * small - big * big) / (2 * s * small))
        a3 = 0.5 * np.sqrt(
            np.clip(
                (-s + big + small) * (s + big - small) * (s - big + small) * (s + big + small),
                0.0,
                None,
            )
        )
        cov[partial] = (a1 + a2 - a3) / (math.pi * small * small)
    return cov if cov.shape else float(cov)


def _unit(lon_deg: float, lat_deg: float) -> np.ndarray:
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    return np.array([math.cos(lat) * math.cos(lon), math.sin(lat), math.cos(lat) * math.sin(lon)])


def eclipse_mask(
    res: int,
    *,
    planet_km: float,
    b_km: float,
    center_lon_deg: float,
    center_lat_deg: float,
    sun_lon_deg: float,
    sun_lat_deg: float,
    shadow_lon_deg: float,
    shadow_lat_deg: float,
    occluder_radius_km: float,
    occluder_distance_km: float,
    star_radius_km: float,
    star_distance_km: float,
) -> np.ndarray:
    """Per-pixel stellar transmission (1 = unobscured, 0 = total eclipse).

    The shadow centre is offset from the sub-stellar point by the impact
    parameter ``b_km`` toward ``shadow_lon_deg``/``shadow_lat_deg`` — the
    occluder's zenith direction on the surface (the sub-Aegis point for a
    tidally locked moon), so the eclipse band advances toward the occluder
    as the star approaches it in the sky.  Only the day side can be
    eclipsed; the night side keeps its normal lighting.
    """
    view = _unit(center_lon_deg, center_lat_deg)
    sun = _unit(sun_lon_deg, sun_lat_deg)
    lam = math.radians(center_lon_deg)
    right = np.array([-math.sin(lam), 0.0, math.cos(lam)])
    up = np.cross(right, view)
    # Offset direction: toward the shadow target, projected perpendicular to
    # the star direction (a surface great-circle direction as seen on the sky).
    shadow = _unit(shadow_lon_deg, shadow_lat_deg)
    u = shadow - np.dot(shadow, sun) * sun
    norm = float(np.linalg.norm(u))
    if norm > 1.0e-9:
        u = u / norm
    else:
        # Mid-eclipse: the offset direction is undefined but b is zero there,
        # so any in-plane direction is numerically fine.
        u = right - np.dot(right, sun) * sun
        u = u / float(np.linalg.norm(u))

    half = res / 2.0
    py, px = np.mgrid[0:res, 0:res].astype(np.float64)
    x = (px + 0.5 - half) / (half * 0.92)
    y = (half - py - 0.5) / (half * 0.92)
    r2 = x * x + y * y
    inside = r2 <= 1.0
    z = np.sqrt(np.clip(1.0 - r2, 0.0, None))
    n_x = x * right[0] + y * up[0] + z * view[0]
    n_y = x * right[1] + y * up[1] + z * view[1]
    n_z = x * right[2] + y * up[2] + z * view[2]
    cos_sun = n_x * sun[0] + n_y * sun[1] + n_z * sun[2]
    cos_u = n_x * u[0] + n_y * u[1] + n_z * u[2]

    alpha_big = math.asin(occluder_radius_km / occluder_distance_km)
    alpha_small = math.asin(star_radius_km / star_distance_km)
    rho2 = planet_km**2 + b_km**2 - 2.0 * b_km * planet_km * cos_u - (planet_km * cos_sun) ** 2
    rho = np.sqrt(np.clip(rho2, 0.0, None))
    sep = np.arctan2(rho, occluder_distance_km)

    cov = np.asarray(disk_coverage(sep, alpha_big, alpha_small), dtype=np.float64)
    cov = np.clip(cov, 0.0, 1.0)
    cov = np.where(inside & (cos_sun > 0.0), cov, 0.0)
    return np.asarray(1.0 - cov, dtype=np.float64)


__all__ = ["disk_coverage", "eclipse_mask"]
