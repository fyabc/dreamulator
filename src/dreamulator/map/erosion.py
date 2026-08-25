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

Sub-grid channel width dilution: stream power incises the channel bed, whose
width follows the downstream hydraulic geometry ``w = 5·Q^0.5`` (Leopold &
Maddock 1953; compilations give coeff 3–10).  The cell-averaged lowering is
``E_channel × min(1, w/d)`` — without the ``w/d`` factor, D8 single-flow
concentrates all discharge into one-cell-wide threads and cuts grid-scale
canyons ~d/w times too deep (up to ~1–2 km at 51 km cells).  Barrier cells
on a dammed-basin sill are exempt (concentrated notch incision — see below).

Sediment routing (mass conservation, ``sediment_routing="bagnold"``): each
substep's erosion product is routed downstream along the flow graph and
deposited where the load exceeds the Bagnold (1966) stream-power transport
capacity ``ε·(ρw/ρs)·Q·S``; sediment reaching water bodies deposits there
(deltas, shelf building, lake fill).  Without routing, incised mass would be
lost at the coastline and basins would never fill.

Land cells are clamped at ``sea_level + 1 m`` during incision (no general
marine transgression), and cells draining to the **open ocean** stay static
(marine base-level incision there over-planates lowlands — nacrea regression
2026-08-25: mean denudation 97→155 m and Cfb −1069 cells when open-coast
base level was admitted, because the detachment-limited law has no
transport-limited slowdown; marine processes are future work).

One targeted exception — **dammed inland seas**: land cells draining into a
below-sea-level water body that is *not* connected to the open ocean incise
toward sea level as base level, so sills separating the basin from the ocean
can be worn down.  When such a sill reaches the clamp, the end-of-run **sill
breach** pass lowers it to ``sea_level − 5 m`` so the basin connects to the
ocean (roadmap §7 #7 capability requirement: erosion must be able to cut
open a blocked shallow strait; Barnes et al. 2014-style fill/route + a
minimal marine-transgression step, deepening left to future marine
processes).

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

# Depth (m below sea level) assigned to breached sills.  A newly opened
# strait is shallow; deepening is the job of marine processes (not yet
# modelled).  Any small negative value establishes water-body connectivity,
# which is what downstream consumers (ocean BFS, climate moisture) need.
_BREACH_DEPTH_M = 5.0

# Tolerance (m) for recognising a cell as "at the sea-level clamp".
_SILL_TOL_M = 1e-3

# Channel-width allometry w = coeff · Q^0.5 (Q in m³/s).  Leopold & Maddock
# (1953) downstream hydraulic geometry; compilations give coeff ≈ 3–10.
# Used for sub-grid width dilution: stream power incises only the channel
# bed, so the cell-averaged lowering is E_channel × (w / cell width).
_CHANNEL_WIDTH_COEFF_M = 5.0

# (mm/yr · km²) → m³/s conversion: 1 mm/yr over 1 km² = 1e-3 m × 1e6 m² /
# 3.156e7 s ≈ 3.17e-5 m³/s.
_MM_KM2_PER_YR_TO_M3S = 1.0e3 / 3.156e7  # ≈ 3.17e-5

# Bagnold (1966) sediment-transport capacity: capacity ∝ ε·(ρw/ρs)·Q·S.
_RHO_WATER_KG_M3 = 1000.0
_RHO_SEDIMENT_KG_M3 = 2650.0
_SECONDS_PER_YEAR = 3.156e7


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
    water_comp, ocean_comp = _water_components(h, sea_level, neighbors)
    barrier_mask = _dammed_barrier_mask(
        h, sea_level, is_land, neighbors, water_comp, ocean_comp
    )
    for step in range(n_steps):
        h_prev = h
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
            water_comp,
            ocean_comp,
            barrier_mask,
        )
        if config.sediment_routing == "bagnold":
            h = _route_sediment(
                h,
                h_prev,
                is_land,
                neighbors,
                dists_km,
                dists_m,
                area_km2,
                precip_mm,
                sea_level,
                config,
                barrier_mask,
            )
        if progress_callback is not None:
            progress_callback((step + 1) * dt / 1e6, config.surface_evolution_time_myr)

    h = _breach_sills(h, is_land, neighbors, sea_level)

    for i, c in enumerate(mesh.cells):
        if is_land[i]:
            c.elevation = float(h[i])
            c.net_erosion_m = float(h[i] - h0[i])
        elif h[i] != h0[i]:
            # Sediment deposited into water bodies (deltas, lake fill).
            c.elevation = float(h[i])


def _water_components(
    h: np.ndarray, sea_level: float, neighbors: list[list[int]]
) -> tuple[np.ndarray, int]:
    """Label connected water bodies (cells below sea level).

    Returns:
        ``(comp, ocean_comp)`` where ``comp[i]`` is the component label of
        water cell ``i`` (−1 for land) and ``ocean_comp`` the label of the
        largest component (the open ocean; −1 if there is no water).
    """
    n = len(h)
    comp = np.full(n, -1, dtype=np.int32)
    sizes: list[int] = []
    for seed in range(n):
        if h[seed] >= sea_level or comp[seed] >= 0:
            continue
        label = len(sizes)
        comp[seed] = label
        size = 1
        q: deque[int] = deque([seed])
        while q:
            u = q.popleft()
            for v in neighbors[u]:
                if h[v] < sea_level and comp[v] < 0:
                    comp[v] = label
                    size += 1
                    q.append(v)
        sizes.append(size)
    ocean_comp = int(np.argmax(sizes)) if sizes else -1
    return comp, ocean_comp


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
    water_comp: np.ndarray,
    ocean_comp: int,
    barrier_mask: np.ndarray,
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
    #    c_i = dt · K_eff · q_i^m / d_ij · width_frac;
    #    h_new_i = (h_i + c_i·h_down) / (1 + c_i).
    #    Downstream water bodies act as a base level at *sea level* (not their
    #    depth — a river mouth's base level is the water surface), so cells
    #    draining into a dammed inland sea incise toward sea level and sills
    #    can be worn down to the clamp.  Cells draining to the *open* ocean
    #    stay static instead (see skip below): admitting sea-level base level
    #    there over-planates lowlands because the detachment-limited law has
    #    no transport-limited slowdown (nacrea regression 2026-08-25).
    downstream = np.full(n, -1, dtype=np.int32)
    c = np.zeros(n)
    for i in range(n):
        if not is_land[i]:
            continue
        j = flow_dir[i]
        if j < 0:
            continue
        if not is_land[j] and water_comp[j] == ocean_comp and not barrier_mask[i]:
            continue  # open-ocean coastline: static in v1 (marine processes P2);
            # barrier cells damming an inland sea are the exception — they must
            # incise toward sea level so the strait can open
        downstream[i] = j
        for k, nbr in enumerate(neighbors[i]):
            if nbr == j:
                d = max(dists_m[i][k], 1e-6)
                # Sub-grid channel width dilution: stream power incises the
                # channel bed (width w ∝ Q^0.5), not the whole cell — the
                # cell-averaged lowering is scaled by w/d.  Without this, D8
                # single-flow concentrates all discharge into one-cell-wide
                # threads and over-incises them by ~d/w (grid-canyon artefact).
                # Barrier cells are exempt: strait cutting IS a concentrated
                # notch incising along the saddle path (the barrier mask
                # already selects that path); diluting it there would demand
                # the whole cell average reach sea level ~d/w times slower
                # than the physical notch-breaching time.
                if barrier_mask[i]:
                    width_frac = 1.0
                else:
                    q_m3s = q[i] * q_ref * _MM_KM2_PER_YR_TO_M3S
                    width_frac = min(1.0, _CHANNEL_WIDTH_COEFF_M * float(np.sqrt(q_m3s)) / d)
                c[i] = dt * k_eff * (q[i] ** config.stream_power_m) / d * width_frac
                break

    def _down_level(i: int) -> float:
        """Effective downstream elevation for the solve (water → sea level)."""
        j = downstream[i]
        if is_land[j]:
            return float(h_new[j])
        return max(float(h[j]), sea_level)

    h_new = h.copy()
    for i in _reverse_topological_order(flow_dir, is_land):
        j = downstream[i]
        if j >= 0:
            h_new[i] = (h[i] + c[i] * _down_level(i)) / (1.0 + c[i])
            if h_new[i] > h[i]:
                h_new[i] = h[i]  # stream power incises only; no deposition (v1)

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

    # 5. Overshoot guard + sea-level clamp.  The guard keeps a cell from being
    # incised below its downstream neighbour, but must never raise it above its
    # own starting elevation (flat-routed cells can have an *uphill* downstream
    # parent — raising them would fabricate deposition).
    for i in range(n):
        if not is_land[i]:
            continue
        j = downstream[i]
        if j >= 0 and h_new[i] < _down_level(i):
            h_new[i] = min(_down_level(i), h[i])
    h_new[is_land] = np.maximum(h_new[is_land], sea_level + 1.0)
    return h_new


def _route_sediment(
    h: np.ndarray,
    h_prev: np.ndarray,
    is_land: np.ndarray,
    neighbors: list[list[int]],
    dists_km: list[list[float]],
    dists_m: list[list[float]],
    area_km2: np.ndarray,
    precip_mm: np.ndarray,
    sea_level: float,
    config: TerrainPipelineConfig,
    barrier_mask: np.ndarray,
) -> np.ndarray:
    """Route this step's erosion product downstream and deposit it.

    Mass-conserving source-to-sink pass (Bagnold 1966 transport capacity):

    - **Supply**: cells that dropped during the incision/diffusion substep
      (``h_prev − h``, clipped at 0) become sediment volume.
    - **Capacity**: ``cap = ε·(ρw/ρs)·Q·S·dt`` — the stream power available
      to move sediment (Bagnold 1966; ε ≈ 0.01–0.1).  Load exceeding capacity
      deposits in place; the remainder is passed downstream.  No extra bed
      entrainment (detachment is already handled by the stream-power step).
    - **Water bodies are sinks**: sediment reaching an ocean cell deposits
      there (delta progradation / shelf building); endorheic sinks deposit in
      the terminal cell (lake fill).
    - **Barrier cells are exempt** (same reason they are exempt from width
      dilution): the sill notch is sub-grid; the spill flow through it exports
      sediment to the ocean rather than depositing it, otherwise the sill
      would be buried by its own catchment's supply and never breach.

    Args:
        h: (n,) elevation after the incision/diffusion substep.
        h_prev: (n,) elevation before that substep.
        barrier_mask: (n,) bool dammed-basin barrier cells (no deposition).
        (remaining args as in :func:`_implicit_step`).

    Returns:
        Elevation array with deposition applied (land and water cells).
    """
    n = len(h)
    filled, connected = priority_flood_fill(h, is_land, neighbors)
    flow_dir = compute_flow_directions(filled, is_land, neighbors, dists_km)
    flow_dir = route_flat_cells(filled, is_land, connected, neighbors, flow_dir)
    accum = compute_flow_accumulation(flow_dir, is_land, area_km2)

    q_ref = config.precip_proxy_base_mm * 1e6
    q = np.where(is_land, precip_mm * np.maximum(accum, area_km2), 0.0) / q_ref

    n_steps = max(config.stream_power_steps, 1)
    dt_s = config.surface_evolution_time_myr * 1e6 / n_steps * _SECONDS_PER_YEAR
    coeff = config.sediment_transport_efficiency * (_RHO_WATER_KG_M3 / _RHO_SEDIMENT_KG_M3)

    supply_m3 = np.maximum(0.0, h_prev - h) * area_km2
    load = supply_m3.copy()
    dep = np.zeros(n)

    # Source → sink (reverse of the downstream-first solve order).
    order = _reverse_topological_order(flow_dir, is_land)[::-1]
    for i in order:
        if load[i] <= 0.0:
            continue
        j = int(flow_dir[i])
        if j < 0:
            dep[i] += load[i]  # unrouted sink: deposit in place
            load[i] = 0.0
            continue
        if not is_land[j]:
            dep[j] += load[i]  # water body: delta / lake-fill deposition
            load[i] = 0.0
            continue
        if barrier_mask[i]:
            load[j] += load[i]  # sill notch: spill flow exports the load
            continue
        d = 1.0
        for k, nbr in enumerate(neighbors[i]):
            if nbr == j:
                d = max(dists_m[i][k], 1.0)
                break
        # Local slope toward the downstream cell.  Zero on uphill flat routes
        # (filled-basin spill paths) → zero capacity → deposition, which is
        # exactly the basin-fill behaviour.
        slope = max(0.0, (h[i] - h[j]) / d)
        q_m3s = q[i] * q_ref * _MM_KM2_PER_YR_TO_M3S
        cap = coeff * q_m3s * slope * dt_s
        if load[i] > cap:
            dep[i] += load[i] - cap
            load[i] = cap
        load[j] += load[i]

    if not dep.any():
        return h
    out = h + dep / np.maximum(area_km2, 1e-9)
    return np.asarray(out)


def _minimax_from_ocean(
    h: np.ndarray,
    sea_level: float,
    neighbors: list[list[int]],
    water_comp: np.ndarray,
    ocean_comp: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Minimax "cost" of reaching each cell from the open ocean.

    ``cost[i]`` is the lowest achievable maximum elevation along any path from
    an ocean cell to ``i`` (water cells contribute ``sea_level``, land cells
    their elevation) — i.e. the level water would have to rise to before it
    could reach cell ``i``.  This is the priority-flood spill level viewed
    from the ocean; the cheapest entry into a dammed inland sea is the lowest
    saddle (sill) on its enclosing barrier.

    Args:
        h: (n,) elevation (m).
        sea_level: sea level (m).
        neighbors: per-cell neighbour index lists.
        water_comp: water-body component labels (−1 for land).
        ocean_comp: label of the open-ocean component (−1 if none).

    Returns:
        ``(cost, prev)`` — minimax cost (inf where unreachable) and the
        predecessor index along the witness path (−1 for sources).
    """
    import heapq

    n = len(h)
    cost = np.full(n, np.inf)
    prev = np.full(n, -1, dtype=np.int32)
    heap: list[tuple[float, int]] = []
    for i in range(n):
        if water_comp[i] == ocean_comp:
            cost[i] = sea_level
            heapq.heappush(heap, (sea_level, i))
    while heap:
        c, i = heapq.heappop(heap)
        if c > cost[i]:
            continue
        for j in neighbors[i]:
            step = max(c, sea_level if water_comp[j] >= 0 else float(h[j]))
            if step < cost[j]:
                cost[j] = step
                prev[j] = i
                heapq.heappush(heap, (step, j))
    return cost, prev


def _dammed_barrier_mask(
    h: np.ndarray,
    sea_level: float,
    is_land: np.ndarray,
    neighbors: list[list[int]],
    water_comp: np.ndarray,
    ocean_comp: int,
) -> np.ndarray:
    """Land cells on the lowest barrier between a dammed inland sea and the ocean.

    For every below-sea-level water body that is not the open ocean, the
    minimax path to the ocean crosses the barrier's lowest saddle; all land
    cells on that path form the barrier.  Barrier cells are the ones fluvial
    incision (at sea-level base level) must wear down before the basin can
    open — including ocean-side cells that drain directly to the ocean and
    would otherwise stay static.

    Args:
        h: (n,) elevation (m).
        sea_level: sea level (m).
        is_land: (n,) bool land mask.
        neighbors: per-cell neighbour index lists.
        water_comp: water-body component labels (−1 for land).
        ocean_comp: label of the open-ocean component (−1 if none).

    Returns:
        (n,) bool mask of barrier land cells.
    """
    n = len(h)
    mask = np.zeros(n, dtype=bool)
    if ocean_comp < 0:
        return mask
    cost, prev = _minimax_from_ocean(h, sea_level, neighbors, water_comp, ocean_comp)

    comps = sorted({int(water_comp[i]) for i in range(n) if water_comp[i] >= 0})
    for label in comps:
        if label == ocean_comp:
            continue
        members = [i for i in range(n) if water_comp[i] == label]
        entry = min(members, key=lambda i: cost[i])
        if not np.isfinite(cost[entry]):
            continue
        j = int(entry)
        while j >= 0:
            if is_land[j]:
                mask[j] = True
            j = int(prev[j])
    return mask


def _breach_sills(
    h: np.ndarray,
    is_land: np.ndarray,
    neighbors: list[list[int]],
    sea_level: float,
) -> np.ndarray:
    """Breach barriers whose lowest saddle erosion has worn down to sea level.

    During incision land cells are clamped at ``sea_level + 1 m``, so a sill
    between a dammed inland sea and the ocean is worn down to +1 m but never
    opens on its own.  This end-of-run pass detects such sills (minimax cost
    from the ocean ≤ sea level + clamp) and lowers every remaining land cell
    on the barrier path below sea level — a minimal marine-transgression step:
    a barrier whose lowest crest has reached sea level cannot hold back the
    sea; waves and throughflow take the rest (marine processes themselves are
    future work).  Roadmap §7 #7 capability requirement: erosion must be able
    to cut open a blocked shallow strait.

    Args:
        h: (n,) current elevation (m).
        is_land: (n,) bool land mask (initial, pre-erosion).
        neighbors: per-cell neighbour index lists.
        sea_level: sea level (m).

    Returns:
        Updated elevation array (breached barrier cells at
        ``sea_level − _BREACH_DEPTH_M``).
    """
    n = len(h)
    comp, ocean_comp = _water_components(h, sea_level, neighbors)
    if ocean_comp < 0 or comp.max() < 1:
        return h  # single (or no) water body — nothing dammed

    cost, prev = _minimax_from_ocean(h, sea_level, neighbors, comp, ocean_comp)

    h_new = h.copy()
    breached = 0
    comps = sorted({int(comp[i]) for i in range(n) if comp[i] >= 0})
    for label in comps:
        if label == ocean_comp:
            continue
        members = [i for i in range(n) if comp[i] == label]
        entry = min(members, key=lambda i: cost[i])
        if cost[entry] > sea_level + 1.0 + _SILL_TOL_M:
            continue  # sill not yet worn down to sea level
        j = int(entry)
        while j >= 0:
            if is_land[j] and h_new[j] >= sea_level:
                h_new[j] = sea_level - _BREACH_DEPTH_M
                breached += 1
            j = int(prev[j])
    if breached:
        logger.info(
            "Sill breach: %d barrier cell(s) opened to connect dammed basin(s)", breached
        )
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
