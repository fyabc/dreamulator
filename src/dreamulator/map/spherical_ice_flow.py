"""Conservative shallow-ice flow on a shared spherical Voronoi domain.

The fixed-coast trial exports land ice through absorbing ocean faces. This
is a grounded terrestrial inventory; floating shelves and front stresses
require their own dynamics. Face widths, centre distances and cell areas
have physical units. Canvas ownership never enters the flow calculation.

References: Bueler (2016), doi:10.1017/jog.2015.3; PISM marine calving docs.
The donor-thickness discretization is a finite-volume trial, rather than an
implementation of Bueler's finite-volume-element scheme.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numba import njit

from .canvas_ice_surface import SECONDS_PER_YEAR, TEMPERATE_RATE_FACTOR_PA3_S
from .ice_mass_balance import ICE_MELT_MM_PER_K_DAY, SNOW_MELT_MM_PER_K_DAY
from .ice_sheets import RHO_ICE_KG_M3


@dataclass(frozen=True)
class SphericalIceMesh:
    cell_indices: np.ndarray
    area_m2: np.ndarray
    face_cells: np.ndarray
    distance_m: np.ndarray
    width_m: np.ndarray
    tangents: np.ndarray
    transverse: np.ndarray
    gradient_inverse: np.ndarray


@dataclass(frozen=True)
class SphericalIceBudget:
    initial_volume_m3: float
    final_volume_m3: float
    ocean_export_m3: float
    residual_m3: float
    substeps: int


@dataclass(frozen=True)
class SphericalIceEvolutionBudget:
    initial_volume_m3: float
    final_volume_m3: float
    snowfall_volume_m3: float
    runoff_volume_m3: float
    ocean_export_m3: float
    residual_m3: float
    substeps: int


def spherical_ice_mesh(
    centres: np.ndarray,
    area_m2: np.ndarray,
    face_cells: np.ndarray,
    face_vertices: np.ndarray,
    land_mask: np.ndarray,
    ocean_mask: np.ndarray,
    *,
    radius_m: float,
) -> SphericalIceMesh:
    """Prepare shared ice geometry from a complete spherical Voronoi mesh.

    Each face occurs once; face_vertices has two endpoint vectors per face.
    Ocean faces use the coast halfway between the two centres. Lake faces
    are closed in this trial. Cell centres and vertices are normalized before
    measuring great-circle lengths, including rounded exported coordinates.
    """
    xyz = np.asarray(centres, dtype=float)
    area = np.asarray(area_m2, dtype=float)
    faces = np.asarray(face_cells, dtype=np.int64)
    vertices = np.asarray(face_vertices, dtype=float)
    land, ocean = np.asarray(land_mask, dtype=bool), np.asarray(ocean_mask, dtype=bool)
    if (
        xyz.shape != (len(area), 3)
        or faces.ndim != 2
        or faces.shape[1] != 2
        or vertices.shape != (len(faces), 2, 3)
        or land.shape != area.shape
        or ocean.shape != area.shape
        or np.any(land & ocean)
        or np.any(area <= 0)
        or not all(np.isfinite(a).all() for a in (xyz, area, vertices))
        or not np.isfinite(radius_m)
        or radius_m <= 0
        or np.any((faces < 0) | (faces >= len(area)))
        or np.any(np.linalg.norm(xyz, axis=1) == 0)
        or np.any(np.linalg.norm(vertices, axis=2) == 0)
    ):
        raise ValueError("ice geometry needs finite spherical cells, areas and unique faces")
    xyz = xyz / np.linalg.norm(xyz, axis=1)[:, None]
    vertices = vertices / np.linalg.norm(vertices, axis=2)[..., None]
    select = (land[faces[:, 0]] & (land | ocean)[faces[:, 1]]) | (
        land[faces[:, 1]] & (land | ocean)[faces[:, 0]]
    )
    faces, vertices = faces[select].copy(), vertices[select]
    swap = ~land[faces[:, 0]]
    faces[swap] = faces[swap, ::-1]
    a, b = xyz[faces[:, 0]], xyz[faces[:, 1]]
    cross = np.cross(a, b)
    sine = np.linalg.norm(cross, axis=1)
    cosine = np.sum(a * b, axis=1)
    angle = np.arctan2(sine, cosine)
    va, vb = vertices[:, 0], vertices[:, 1]
    width = radius_m * np.arctan2(np.linalg.norm(np.cross(va, vb), axis=1), (va * vb).sum(1))
    if np.any(sine <= 0) or np.any(width <= 0):
        raise ValueError("ice faces need distinct neighbours and nonzero widths")
    # The right tangent points back toward the left cell. The common cross
    # axis is perpendicular to both great-circle directions.
    tangents = np.stack(
        [(b - cosine[:, None] * a) / sine[:, None], (a - cosine[:, None] * b) / sine[:, None]],
        axis=1,
    )
    transverse = cross / sine[:, None]
    indices = np.flatnonzero(land)
    local = np.full(len(area), -1, dtype=np.int64)
    local[indices] = np.arange(len(indices))
    pairs = local[faces]
    marine = pairs[:, 1] == -1
    distance = radius_m * angle * np.where(marine, 0.5, 1.0)
    normal_matrix = np.zeros((len(indices), 3, 3))
    for side in range(2):
        valid = pairs[:, side] >= 0
        directions = tangents[valid, side]
        np.add.at(
            normal_matrix, pairs[valid, side], directions[:, :, None] * directions[:, None, :]
        )
    inverse = np.linalg.pinv(normal_matrix, rcond=1e-12, hermitian=True)
    return SphericalIceMesh(
        indices, area[indices], pairs, distance, width, tangents, transverse, inverse
    )


@njit(cache=True, nogil=True)
def _flow(
    bed: np.ndarray,
    ice: np.ndarray,
    area: np.ndarray,
    pairs: np.ndarray,
    distance: np.ndarray,
    width: np.ndarray,
    tangents: np.ndarray,
    transverse: np.ndarray,
    inverse: np.ndarray,
    duration: float,
    coefficient: float,
    open_ocean: bool,
    max_substeps: int,
) -> tuple[np.ndarray, float, int]:
    h = ice.copy()
    n, nf = len(h), len(pairs)
    rhs, gradient = np.zeros((n, 3)), np.empty((n, 3))
    slopes, flux = np.empty(nf), np.empty(nf)
    outgoing, diffusion = np.empty(n), np.empty(n)
    elapsed, export, steps = 0.0, 0.0, 0
    while elapsed < duration:
        if steps >= max_substeps:
            raise RuntimeError("shared ice flow exceeded its substep budget")
        rhs[:] = 0
        outgoing[:] = diffusion[:] = 0
        for f in range(nf):
            i, j = pairs[f]
            slope = 0.0
            if j >= 0:
                slope = (bed[i] + h[i] - bed[j] - h[j]) / distance[f]
            elif open_ocean:
                slope = (bed[i] + h[i]) / distance[f]
            slopes[f] = slope
            for k in range(3):
                rhs[i, k] -= slope * tangents[f, 0, k]
                if j >= 0:
                    rhs[j, k] += slope * tangents[f, 1, k]
        for i in range(n):
            for k in range(3):
                gradient[i, k] = 0
                for component in range(3):
                    gradient[i, k] += inverse[i, k, component] * rhs[i, component]
        for f in range(nf):
            i, j = pairs[f]
            slope = slopes[f]
            across = 0.0
            if j >= 0:
                for k in range(3):
                    across += 0.5 * (gradient[i, k] + gradient[j, k]) * transverse[f, k]
            donor = h[i] if slope > 0 else (h[j] if j >= 0 else 0.0)
            diffusivity = coefficient * donor**5 * (slope**2 + across**2)
            flux[f] = diffusivity * slope * width[f]
            diffusion[i] += diffusivity * width[f] / distance[f]
            outgoing[i] += max(flux[f], 0.0)
            if j >= 0:
                diffusion[j] += diffusivity * width[f] / distance[f]
                outgoing[j] += max(-flux[f], 0.0)
        dt = duration - elapsed
        for i in range(n):
            if diffusion[i] > 0:
                dt = min(dt, 0.1 * area[i] / diffusion[i])
            if outgoing[i] > 0:
                dt = min(dt, 0.9 * h[i] * area[i] / outgoing[i])
        for f in range(nf):
            i, j = pairs[f]
            exchange = dt * flux[f]
            h[i] -= exchange / area[i]
            if j >= 0:
                h[j] += exchange / area[j]
            else:
                export += exchange
        elapsed += dt
        steps += 1
    return h, export, steps


def flow_spherical_ice(
    mesh: SphericalIceMesh,
    bed_m: np.ndarray,
    ice_m: np.ndarray,
    *,
    elapsed_yr: float,
    gravity_m_s2: float,
    open_ocean: bool = True,
    rate_factor_pa3_s: float = TEMPERATE_RATE_FACTOR_PA3_S,
    max_substeps: int = 500_000,
) -> tuple[np.ndarray, SphericalIceBudget]:
    """Move land ice, counting marine discharge in the same volume budget.

    Fields follow mesh.cell_indices. Internal face fluxes cancel by volume,
    including unequal cell areas. Ocean surface is fixed at zero metres;
    exported solid ice leaves the terrestrial inventory immediately. Closing
    these faces provides a paired control with identical geometry and flow.
    """
    bed, h = np.asarray(bed_m, dtype=float), np.asarray(ice_m, dtype=float)
    if (
        bed.shape != mesh.area_m2.shape
        or h.shape != bed.shape
        or not np.isfinite(bed).all()
        or not np.isfinite(h).all()
        or np.any(h < 0)
        or not np.isfinite([elapsed_yr, gravity_m_s2, rate_factor_pa3_s]).all()
        or elapsed_yr < 0
        or min(gravity_m_s2, rate_factor_pa3_s) <= 0
        or max_substeps < 1
    ):
        raise ValueError(
            "shared ice flow needs finite bed, nonnegative ice and physical parameters"
        )
    initial = float(h @ mesh.area_m2)
    coefficient = 2.0 / 5.0 * rate_factor_pa3_s * (RHO_ICE_KG_M3 * gravity_m_s2) ** 3
    final, export, steps = _flow(
        bed,
        h,
        mesh.area_m2,
        mesh.face_cells,
        mesh.distance_m,
        mesh.width_m,
        mesh.tangents,
        mesh.transverse,
        mesh.gradient_inverse,
        elapsed_yr * SECONDS_PER_YEAR,
        coefficient,
        open_ocean,
        max_substeps,
    )
    volume = float(final @ mesh.area_m2)
    residual = volume - initial + export
    if np.any(final < 0) or abs(residual) > 5e-12 * max(initial, volume, export, 1.0):
        raise ArithmeticError("shared ice flow failed its nonnegative volume budget")
    return final, SphericalIceBudget(initial, volume, export, residual, steps)


@njit(cache=True, nogil=True)
def _evolve(
    mesh_area: np.ndarray,
    pairs: np.ndarray,
    distance: np.ndarray,
    width: np.ndarray,
    tangents: np.ndarray,
    transverse: np.ndarray,
    inverse: np.ndarray,
    bed: np.ndarray,
    initial: np.ndarray,
    snow: np.ndarray,
    pdd: np.ndarray,
    forcing_time: np.ndarray,
    duration_yr: int,
    flow_interval_yr: int,
    coefficient: float,
    open_ocean: bool,
) -> tuple[np.ndarray, float, float, float, int]:
    h = initial.copy()
    source_by_cell, runoff_by_cell = np.zeros(len(h)), np.zeros(len(h))
    export, steps = 0.0, 0
    knot = 0
    for start in range(0, duration_yr, flow_interval_yr):
        end = min(start + flow_interval_yr, duration_yr)
        for year in range(start, end):
            time = year + 0.5
            while knot < len(forcing_time) - 2 and time > forcing_time[knot + 1]:
                knot += 1
            w = (time - forcing_time[knot]) / (forcing_time[knot + 1] - forcing_time[knot])
            for i in range(len(h)):
                ice = h[i] * RHO_ICE_KG_M3
                retained = 0.0
                for month in range(12):
                    incoming = (1 - w) * snow[knot, month, i] + w * snow[knot + 1, month, i]
                    capacity = (1 - w) * pdd[knot, month, i] + w * pdd[knot + 1, month, i]
                    retained += incoming
                    melt_snow = min(retained, capacity * SNOW_MELT_MM_PER_K_DAY)
                    retained -= melt_snow
                    capacity = max(capacity - melt_snow / SNOW_MELT_MM_PER_K_DAY, 0.0)
                    melt_ice = min(ice, capacity * ICE_MELT_MM_PER_K_DAY)
                    ice -= melt_ice
                    source_by_cell[i] += incoming
                    runoff_by_cell[i] += melt_snow + melt_ice
                h[i] = (ice + retained) / RHO_ICE_KG_M3
        h, discharge, number = _flow(
            bed,
            h,
            mesh_area,
            pairs,
            distance,
            width,
            tangents,
            transverse,
            inverse,
            (end - start) * SECONDS_PER_YEAR,
            coefficient,
            open_ocean,
            500_000,
        )
        export += discharge
        steps += number
    accumulation = np.dot(source_by_cell / RHO_ICE_KG_M3, mesh_area)
    runoff = np.dot(runoff_by_cell / RHO_ICE_KG_M3, mesh_area)
    return h, accumulation, runoff, export, steps


def evolve_spherical_ice(
    mesh: SphericalIceMesh,
    bed_m: np.ndarray,
    initial_ice_m: np.ndarray,
    snowfall_mm: np.ndarray,
    positive_degree_days: np.ndarray,
    forcing_time_yr: np.ndarray,
    *,
    elapsed_yr: int,
    gravity_m_s2: float,
    open_ocean: bool = True,
    flow_interval_yr: int = 1,
    rate_factor_pa3_s: float = TEMPERATE_RATE_FACTOR_PA3_S,
) -> tuple[np.ndarray, SphericalIceEvolutionBudget]:
    """Integrate annual seasonal snow, ice melt and shared spherical flow.

    Month-first forcing snapshots have shape (time, 12, land_cell) and are
    linearly mixed at the middle of each year. Each year's retained snow
    enters ice-equivalent storage. A flow_interval_yr of two batches annual
    balances before flow, providing a temporal splitting check. Atmospheric
    and bed-height feedback belong to the supplied forcing preparation.
    """
    bed, h = np.asarray(bed_m, dtype=float), np.asarray(initial_ice_m, dtype=float)
    snow, pdd = np.asarray(snowfall_mm, dtype=float), np.asarray(positive_degree_days, dtype=float)
    time = np.asarray(forcing_time_yr, dtype=float)
    if (
        time.ndim != 1
        or len(time) < 2
        or np.any(np.diff(time) <= 0)
        or snow.shape != (len(time), 12, len(mesh.area_m2))
        or pdd.shape != snow.shape
        or bed.shape != mesh.area_m2.shape
        or h.shape != bed.shape
        or not all(np.isfinite(a).all() for a in (time, snow, pdd, bed, h))
        or any(np.any(a < 0) for a in (snow, pdd, h))
        or elapsed_yr < 0
        or flow_interval_yr < 1
        or time[0] > 0
        or time[-1] < elapsed_yr
        or not np.isfinite([gravity_m_s2, rate_factor_pa3_s]).all()
        or min(gravity_m_s2, rate_factor_pa3_s) <= 0
    ):
        raise ValueError(
            "ice evolution needs aligned annual climate history and physical parameters"
        )
    volume = float(h @ mesh.area_m2)
    coefficient = 2.0 / 5.0 * rate_factor_pa3_s * (RHO_ICE_KG_M3 * gravity_m_s2) ** 3
    final, accumulation, runoff, export, steps = _evolve(
        mesh.area_m2,
        mesh.face_cells,
        mesh.distance_m,
        mesh.width_m,
        mesh.tangents,
        mesh.transverse,
        mesh.gradient_inverse,
        bed,
        h,
        snow,
        pdd,
        time,
        elapsed_yr,
        flow_interval_yr,
        coefficient,
        open_ocean,
    )
    final_volume = float(final @ mesh.area_m2)
    residual = final_volume - volume - accumulation + runoff + export
    if np.any(final < 0) or abs(residual) > 2e-10 * max(volume, accumulation, runoff, export, 1.0):
        raise ArithmeticError("ice history failed its nonnegative source/runoff/export budget")
    return final, SphericalIceEvolutionBudget(
        volume,
        final_volume,
        accumulation,
        runoff,
        export,
        residual,
        steps,
    )
