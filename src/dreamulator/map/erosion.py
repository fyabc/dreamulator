"""Fluvial erosion (surface evolution) on the spherical CVT mesh — Phase 3B.

Stream-power incision ``E = K·Q^m·S^n`` (Howard 1994) + hillslope diffusion
``∂h/∂t = D ∇²h``, time-driven by ``surface_evolution_time_myr``.

Time integration is the **Fastscape-style implicit scheme** (Braun & Willett
2013): for n=1 the stream power is linear and *triangular* (each cell has exactly
one downstream neighbour), so it is solved exactly in reverse topological order;
the hillslope diffusion is a small term handled with a few Jacobi iterations.
Unconditionally stable — a large, uniform ``dt = time / stream_power_steps`` is
used, so the step count is small (~20) and independent of mesh resolution.

Resolution independence: the time is a fixed physical duration, and the
erodibility is auto-scaled by the fractal law
``K_eff = K₀ · (Δx/reference_cell_km)^(n(1-H))`` to compensate coarse-grid slope
smoothing (S ∝ Δx^(H-1)).  Metre-scale detail is deferred to Gaea local
refinement (terrain-pipeline §13).

Deterministic: no RNG — a pure function of the input elevation + config.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from .hydrology import (
    build_adjacency,
    compute_flow_accumulation,
    compute_flow_directions,
    priority_flood_fill,
    route_flat_cells,
)
from .precip_proxy import geomorphic_precipitation

if TYPE_CHECKING:
    from collections.abc import Callable

    from .models import CVTMesh
    from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

# Jacobi iterations for the implicit hillslope diffusion (small term — converges
# in a few passes since D·dt/d² ≪ 1).
_DIFF_JACOBI_ITERS = 5


def apply_erosion(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    progress_callback: Callable[[float, float], None] | None = None,
) -> None:
    """Dispatch on ``config.erosion_algorithm``, modifying ``cell.elevation`` in place."""
    if mesh.num_cells == 0:
        return
    mode = config.erosion_algorithm
    if mode == "none":
        return
    if mode == "stream_power":
        _apply_stream_power_erosion(mesh, config, progress_callback=progress_callback)
        return
    raise ValueError(f"Unknown erosion_algorithm: {mode!r}")


def _apply_stream_power_erosion(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    progress_callback: Callable[[float, float], None] | None = None,
) -> None:
    """Implicit stream power (triangular solve) + Jacobi hillslope diffusion."""
    n = mesh.num_cells
    target_time_yr = config.surface_evolution_time_myr * 1e6
    if target_time_yr <= 0:
        return
    n_steps = max(config.stream_power_steps, 1)
    dt = target_time_yr / n_steps

    elevation = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    area_km2 = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    xyz = mesh.cell_xyz
    sea_level = config.sea_level_offset_m
    is_land = elevation >= sea_level

    neighbors, dists_km = build_adjacency(mesh.cells, config.radius_km, xyz)
    dists_m = [[d * 1000.0 for d in ds] for ds in dists_km]

    precip_mm = geomorphic_precipitation(
        elevation, lat_deg, xyz, is_land, neighbors, dists_m, config
    )

    cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)
    k_eff = _effective_erodibility(config, cell_km)
    d_eff = _effective_diffusivity(config, cell_km)

    h0 = elevation.copy()
    h = elevation.copy()
    for step in range(n_steps):
        h = _implicit_step(
            h,
            is_land,
            neighbors,
            dists_km,
            dists_m,
            area_km2,
            precip_mm,
            sea_level,
            k_eff,
            d_eff,
            dt,
            config,
        )
        if progress_callback is not None:
            progress_callback((step + 1) * dt / 1e6, config.surface_evolution_time_myr)

    for i, c in enumerate(mesh.cells):
        if is_land[i]:
            c.elevation = float(h[i])
            c.net_erosion_m = float(h[i] - h0[i])


def _implicit_step(
    h: np.ndarray,
    is_land: np.ndarray,
    neighbors: list[list[int]],
    dists_km: list[list[float]],
    dists_m: list[list[float]],
    area_km2: np.ndarray,
    precip_mm: np.ndarray,
    sea_level: float,
    k_eff: float,
    d_eff: float,
    dt: float,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """One unconditionally-stable implicit step (stream power + hillslope diffusion)."""
    n = len(h)

    # 1. Drainage.
    filled, connected = priority_flood_fill(h, is_land, neighbors)
    flow_dir = compute_flow_directions(filled, is_land, neighbors, dists_km)
    flow_dir = route_flat_cells(filled, is_land, connected, neighbors, flow_dir)
    accum = compute_flow_accumulation(flow_dir, is_land, area_km2)

    # 2. Discharge.
    q_ref = config.precip_proxy_base_mm * 1e6
    q = np.where(is_land, precip_mm * np.maximum(accum, area_km2), 0.0) / q_ref

    # 3. Stream-power implicit solve (n=1 → linear triangular system).
    #    c_i = dt · K_eff · q_i^m / d_ij;  h_new_i = (h_i + c_i·h_new_j) / (1 + c_i).
    downstream = np.full(n, -1, dtype=np.int32)
    c = np.zeros(n)
    for i in range(n):
        if not is_land[i]:
            continue
        j = flow_dir[i]
        if j < 0 or not is_land[j]:
            continue
        downstream[i] = j
        for k, nbr in enumerate(neighbors[i]):
            if nbr == j:
                d = max(dists_m[i][k], 1e-6)
                c[i] = dt * k_eff * (q[i] ** config.stream_power_m) / d
                break

    h_new = h.copy()
    for i in _reverse_topological_order(flow_dir, is_land):
        j = downstream[i]
        if j >= 0:
            h_new[i] = (h[i] + c[i] * h_new[j]) / (1.0 + c[i])

    # 4. Hillslope diffusion implicit (Jacobi, few iterations).
    d_coeff = d_eff * dt
    for _ in range(_DIFF_JACOBI_ITERS):
        h_next = h_new.copy()
        for i in range(n):
            if not is_land[i]:
                continue
            num = h_new[i]
            den = 1.0
            for k, j in enumerate(neighbors[i]):
                if not is_land[j]:
                    continue
                d = dists_m[i][k]
                if d <= 0:
                    continue
                w = d_coeff / (d * d)
                num += w * h_new[j]
                den += w
            h_next[i] = num / den
        h_new = h_next

    # 5. Overshoot guard + sea-level clamp.
    for i in range(n):
        if not is_land[i]:
            continue
        j = downstream[i]
        if j >= 0 and h_new[i] < h_new[j]:
            h_new[i] = h_new[j]
    h_new[is_land] = np.maximum(h_new[is_land], sea_level + 1.0)
    return h_new


def _reverse_topological_order(flow_dir: np.ndarray, is_land: np.ndarray) -> list[int]:
    """Land cells in reverse topological order (sink/mouth → source).

    Each cell has at most one downstream neighbour (D8), so the flow graph is a
    forest; a Kahn sort gives source→mouth, reversed gives downstream-first —
    the order required by the implicit stream-power triangular solve.
    """
    n = len(flow_dir)
    in_degree = np.zeros(n, dtype=np.int32)
    for i in range(n):
        t = flow_dir[i]
        if t >= 0 and is_land[i] and is_land[t]:
            in_degree[t] += 1
    q: deque[int] = deque(i for i in range(n) if is_land[i] and in_degree[i] == 0)
    order: list[int] = []
    while q:
        i = q.popleft()
        order.append(i)
        t = flow_dir[i]
        if t >= 0 and is_land[t]:
            in_degree[t] -= 1
            if in_degree[t] == 0:
                q.append(t)
    return order[::-1]


def _effective_erodibility(config: TerrainPipelineConfig, cell_km: float) -> float:
    """K_eff = K₀ · (Δx/reference_cell_km)^(n(1-H)) — fractal resolution scaling."""
    ref = max(config.reference_cell_km, 1e-3)
    exponent = config.stream_power_n * (1.0 - config.terrain_hurst_exponent)
    return float(config.fluvial_erodibility * (cell_km / ref) ** exponent)


def _effective_diffusivity(config: TerrainPipelineConfig, cell_km: float) -> float:
    """D_eff = D₀ · (Δx/reference_cell_km)^(2-H) — fractal curvature scaling."""
    ref = max(config.reference_cell_km, 1e-3)
    exponent = 2.0 - config.terrain_hurst_exponent
    return float(config.hillslope_diffusivity * (cell_km / ref) ** exponent)


def _graph_laplacian(
    h: np.ndarray,
    is_land: np.ndarray,
    neighbors: list[list[int]],
    dists_m: list[list[float]],
) -> np.ndarray:
    """Discrete graph Laplacian Σ_j (h_j − h_i) / d_ij² over land cells (1/m).

    Only diffuses across land edges so ocean depth does not drag into the
    coastal cells.
    """
    n = len(h)
    lap = np.zeros(n)
    for i in range(n):
        if not is_land[i]:
            continue
        s = 0.0
        for k, j in enumerate(neighbors[i]):
            if not is_land[j]:
                continue
            d = dists_m[i][k]
            if d <= 0:
                continue
            s += (h[j] - h[i]) / (d * d)
        lap[i] = s
    return lap
