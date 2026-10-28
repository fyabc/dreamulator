"""Linear hillslope transport on a uniform physical grid.

Pairwise finite-volume fluxes solve dh/dt = D laplacian(h). Land faces
exchange equal opposite volumes; sea faces use the water level as a fixed
base level and record the exported volume. The frame has zero flux.
Diffusivity and elapsed time are explicit inputs with physical units.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TransportBudget:
    initial_land_volume_m3: float
    final_land_volume_m3: float
    exported_volume_m3: float
    residual_m3: float
    substeps: int


def hillslope_transport(
    elevation_m: np.ndarray,
    land_mask: np.ndarray,
    *,
    spacing_m: float,
    diffusivity_m2_yr: float,
    elapsed_yr: float,
    sea_level_m: float = 0.0,
) -> tuple[np.ndarray, TransportBudget]:
    """Move slope material with closed frame and an explicitly counted sea sink.

    The model assumes a mobile/weathered surface with linear slope transport.
    Each stable forward step is a positive neighbour average. Substeps enforce
    D dt / dx² <= 1/4, preserving the input range relative to the base level.
    Original submerged elevations remain unchanged.
    """
    h = np.array(elevation_m, dtype=np.float64, copy=True)
    land = np.asarray(land_mask, dtype=bool)
    if h.ndim != 2 or h.shape != land.shape or not h.size or not np.isfinite(h).all():
        raise ValueError("terrain and land mask must share a finite, nonempty two-dimensional grid")
    if not np.isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("physical spacing must be finite and positive")
    if not np.isfinite(diffusivity_m2_yr) or diffusivity_m2_yr < 0:
        raise ValueError("diffusivity must be finite and nonnegative")
    if not np.isfinite(elapsed_yr) or elapsed_yr < 0 or not np.isfinite(sea_level_m):
        raise ValueError("elapsed time and sea datum must be finite; time is nonnegative")
    initial = float(np.sum(h[land] - sea_level_m) * spacing_m**2)
    number = max(1, int(np.ceil(4 * diffusivity_m2_yr * elapsed_yr / spacing_m**2)))
    alpha = diffusivity_m2_yr * elapsed_yr / (number * spacing_m**2)
    exported = 0.0
    for _ in range(number):
        delta = np.zeros(h.shape)
        for a, b in [(np.s_[:, :-1], np.s_[:, 1:]), (np.s_[:-1, :], np.s_[1:, :])]:
            la, lb = land[a], land[b]
            ha, hb = np.where(la, h[a], sea_level_m), np.where(lb, h[b], sea_level_m)
            flux = alpha * (ha - hb)
            delta[a] -= np.where(la, flux, 0)
            delta[b] += np.where(lb, flux, 0)
            exported += (
                float(np.sum(np.where(la & ~lb, flux, np.where(lb & ~la, -flux, 0)))) * spacing_m**2
            )
        h += delta
    final = float(np.sum(h[land] - sea_level_m) * spacing_m**2)
    residual = final - initial + exported
    if abs(residual) > 5e-12 * max(abs(initial), abs(final), abs(exported), 1.0):
        raise ArithmeticError("hillslope transport failed its volume budget")
    return h, TransportBudget(initial, final, exported, residual, number)
