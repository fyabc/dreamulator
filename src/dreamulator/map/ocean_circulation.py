"""Pure ocean circulation module — no I/O, no RNG.

Solves the Stommel barotropic streamfunction equation on the CVT spherical
mesh to produce steady-state wind-driven surface currents, then corrects SST
via along-current advection relaxation.

All functions are deterministic and take only numpy arrays + geometry extracted
from ``VoronoiCell`` lists — they never touch the filesystem or RNG.

References
----------
- Stommel (1948): β ψ_x + R ∇²ψ = curl_z(τ) / (ρ₀ H)
- MPAS-Ocean / TRiSK: SCVT grids are the standard for global ocean modelling
  (we only need the barotropic streamfunction, not the full C-grid scheme).
- ``docs/knowledge/climatology/ocean_currents.md`` §1–3 (physical basis).
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import gmres

if TYPE_CHECKING:
    from dreamulator.map.models import VoronoiCell

# ---------------------------------------------------------------------------
# Default physical parameters (overridable via TerrainPipelineConfig.ocean)
# ---------------------------------------------------------------------------

RHO_AIR: float = 1.225  # kg / m³
RHO_WATER: float = 1025.0  # kg / m³
C_D: float = 1.2e-3  # surface drag coefficient (dimensionless)
DEFAULT_H_ML: float = 50.0  # mixed-layer depth (m)
DEFAULT_BOTTOM_FRICTION: float = 1e-6  # Stommel R (s⁻¹), tuned for WBC ratio
DEFAULT_SST_PASSES: int = 8
DEFAULT_SST_RELAXATION: float = 0.1
#: Surface SST adjustment time τ (days) for semi-Lagrangian advection.  A warm
#: anomaly carried by a current of speed |u| is damped by air–sea heat exchange
#: over a distance L = |u|·τ.  τ = ρ_w·c_p·H_ml / λ, where λ is the air–sea
#: damping coefficient (Haney 1971, ~15–35 W/m²/K).  With ρ_w=1025 kg/m³,
#: c_p=4000 J/kg/K, H_ml=50 m and λ≈34 W/m²/K (Haney's 70 ly day⁻¹ °C⁻¹) this
#: gives τ ≈ 70 days (~2.3 months; Frankignoul & Hasselmann 1977 give ~40 days
#: for a 46 m layer).
DEFAULT_SST_TAU_DAYS: float = 70.0
#: Wind-biased graph-diffusion coefficient for advecting ocean SST anomalies onto
#: land (signed: warm WBCs warm their lee coasts, cold EBCs cool theirs).  Matches
#: the BFS moisture-diffusivity scale; a wind-aligned graph Laplacian + GMRES
#: spreads the anomaly downwind — fast and vectorised, no per-cell tracing.
DEFAULT_TEMP_DIFFUSIVITY: float = 5.0
DEFAULT_COASTAL_INFLUENCE_KM: float = 500.0
UPWELLING_ANOMALY_C: float = -3.0  # cold anomaly cap (°C) at upwelling sites


# ===================================================================
# Mesh geometry helpers (extract numpy arrays from VoronoiCell list)
# ===================================================================


def _extract_nodes_xyz(cells: list[VoronoiCell]) -> np.ndarray:
    """Cell-centre positions on unit sphere, shape (N, 3)."""
    n = len(cells)
    xyz = np.zeros((n, 3), dtype=np.float64)
    for i in range(n):
        c = cells[i]
        xyz[i, 0] = c.x
        xyz[i, 1] = c.y
        xyz[i, 2] = c.z
    return xyz


def _extract_areas_km2(cells: list[VoronoiCell]) -> np.ndarray:
    """Cell areas in km², shape (N,)."""
    return np.array([c.area_km2 for c in cells], dtype=np.float64)


def _extract_lat_rad(cells: list[VoronoiCell]) -> np.ndarray:
    """Cell-centre latitudes in radians, shape (N,)."""
    return np.radians(np.array([c.lat for c in cells], dtype=np.float64))


def _build_directed_edge_table(cells: list[VoronoiCell]) -> tuple[np.ndarray, np.ndarray]:
    """Flat (src, dst) arrays for every directed edge in the CVT adjacency graph.

    Returns:
        src: int64 array of source cell ids.
        dst: int64 array of destination cell ids.
    """
    n = len(cells)
    _src: list[int] = []
    _dst: list[int] = []
    for i in range(n):
        for j in cells[i].neighbors:
            if 0 <= j < n:
                _src.append(i)
                _dst.append(j)
    return np.asarray(_src, dtype=np.int64), np.asarray(_dst, dtype=np.int64)


# ===================================================================
# Local tangent-frame basis vectors
# ===================================================================


def east_north_basis(nodes_xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Local east and north unit vectors at each cell (tangent to sphere).

    Convention (same as ``_geostrophic_wind`` in climate_simulator.py):
        y = +north pole  →  east = k̂ × r̂ / |k̂ × r̂|,  north = r̂ × east.

    Args:
        nodes_xyz: Unit sphere positions, shape (N, 3).

    Returns:
        (east, north) — each shape (N, 3), dtype float64.
    """
    k_hat = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    # east = r̂ × k̂  (points in direction of increasing longitude)
    east_raw = np.cross(nodes_xyz, k_hat)  # (N, 3)
    cos_lat = np.linalg.norm(east_raw, axis=1)  # = cos(lat)
    # Guard against pole singularities (cos_lat → 0)
    safe = cos_lat > 1e-9

    east = np.zeros_like(nodes_xyz)
    east[safe] = east_raw[safe] / cos_lat[safe, None]
    # At poles any direction works; default to world +x
    east[~safe, 0] = 1.0

    # north = east × r̂  (right-handed {east, north} in tangent plane)
    north = np.cross(east, nodes_xyz)
    return east, north


def decompose_tangent(
    vec: np.ndarray,
    east: np.ndarray,
    north: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Project a 3-D tangent vector field into (east, north) scalar components.

    Args:
        vec: Tangent vectors, shape (N, 3).
        east: Local east unit vectors, shape (N, 3).
        north: Local north unit vectors, shape (N, 3).

    Returns:
        (vec_east, vec_north) — each shape (N,), dtype float64.
    """
    return np.einsum("ij,ij->i", vec, east), np.einsum("ij,ij->i", vec, north)


def recompose_tangent(
    comp_east: np.ndarray,
    comp_north: np.ndarray,
    east: np.ndarray,
    north: np.ndarray,
) -> np.ndarray:
    """Reconstruct 3-D tangent vectors from (east, north) scalar components."""
    return comp_east[:, None] * east + comp_north[:, None] * north  # type: ignore[no-any-return]


# ===================================================================
# Graph gradient (reproduced from climate_simulator._compute_graph_gradient
# to keep this module self-contained and avoid circular imports).
# ===================================================================


def _graph_gradient(
    scalar: np.ndarray,
    nodes_xyz: np.ndarray,
    src: np.ndarray,
    dst: np.ndarray,
    n: int,
) -> np.ndarray:
    """Finite-difference gradient of a scalar field on the directed edge table.

    For each cell *i*, the gradient is the weighted average of
    (scalar[j] − scalar[i]) / distance_ij × direction_ij over all neighbours *j*.

    Args:
        scalar: Field values, shape (N,).
        nodes_xyz: Unit sphere positions, shape (N, 3).
        src, dst: Directed edge tables, shape (E,).
        n: Number of cells.

    Returns:
        Gradient vectors tangent to sphere, shape (N, 3).
    """
    node_i = nodes_xyz[src]
    node_j = nodes_xyz[dst]

    dot = np.clip(np.einsum("ij,ij->i", node_i, node_j), -1.0, 1.0)
    dist = np.arccos(dot)

    direction = node_j - node_i
    radial = np.einsum("ij,ij->i", direction, node_i)
    direction = direction - radial[:, None] * node_i
    dir_norm = np.linalg.norm(direction, axis=1)
    valid = (dist >= 1e-9) & (dir_norm >= 1e-9)

    weight = np.zeros_like(dist)
    weight[valid] = 1.0 / dist[valid]

    diff = scalar[dst] - scalar[src]
    contrib = (weight * diff)[:, None] * direction

    grad = np.zeros((n, 3), dtype=np.float64)
    np.add.at(grad, src, contrib)
    weight_sum = np.zeros(n, dtype=np.float64)
    np.add.at(weight_sum, src, weight)
    mask = weight_sum > 1e-9
    grad[mask] /= weight_sum[mask, None]
    return grad


# ===================================================================
# Wind stress
# ===================================================================


def compute_wind_stress(
    wind: np.ndarray,
    rho_air: float = RHO_AIR,
    c_d: float = C_D,
) -> np.ndarray:
    """Bulk aerodynamic wind stress.

    τ = ρ_air · C_D · |u| · u

    Args:
        wind: 10-m wind vectors (m/s), shape (N, 3), tangent to sphere.
        rho_air: Air density (kg/m³).
        c_d: Drag coefficient.

    Returns:
        Wind stress vectors (Pa), shape (N, 3).
    """
    speed = np.linalg.norm(wind, axis=1)
    return rho_air * c_d * speed[:, None] * wind  # type: ignore[no-any-return]


# ===================================================================
# Curl of a tangent vector field (via gradient-of-components)
# ===================================================================


def compute_curl_z(
    tau: np.ndarray,
    nodes_xyz: np.ndarray,
    src: np.ndarray,
    dst: np.ndarray,
    east: np.ndarray,
    north: np.ndarray,
) -> np.ndarray:
    """Vertical component of the curl of a tangent vector field.

    Uses the identity  curl_z(v) = ∂v_north/∂x_east − ∂v_east/∂x_north,
    computing each partial derivative via the graph gradient.

    Args:
        tau: Tangent vector field, shape (N, 3).
        nodes_xyz: Unit sphere positions, shape (N, 3).
        src, dst: Directed edge tables.
        east: Local east unit vectors, shape (N, 3).
        north: Local north unit vectors, shape (N, 3).

    Returns:
        curl_z at each cell, shape (N,).
    """
    n = len(tau)
    tau_e, tau_n = decompose_tangent(tau, east, north)
    grad_te = _graph_gradient(tau_e, nodes_xyz, src, dst, n)
    grad_tn = _graph_gradient(tau_n, nodes_xyz, src, dst, n)
    # ∂τ_n/∂x_e (change of north component in the east direction)
    dtn_de = np.einsum("ij,ij->i", grad_tn, east)
    # ∂τ_e/∂x_n (change of east component in the north direction)
    dte_dn = np.einsum("ij,ij->i", grad_te, north)
    return dtn_de - dte_dn  # type: ignore[no-any-return]


# ===================================================================
# Ocean basin detection (connected components on the graph)
# ===================================================================


def detect_ocean_basins(
    cells: list[VoronoiCell],
    sea_level_m: float = 0.0,
) -> tuple[np.ndarray, list[np.ndarray]]:
    """Partition ocean cells into connected basins via BFS.

    A cell is "ocean" when  elevation <= sea_level  AND  crust_type is
    'oceanic' or 'transitional' (continental shelf cells that are submerged
    still participate in the basin circulation).

    Args:
        cells: All VoronoiCell objects.
        sea_level_m: Sea-level offset (from TerrainPipelineConfig).

    Returns:
        basin_id:  int array, shape (N,).  Land cells = -1.
        basins:    list of int arrays, one per basin, containing the *global*
                   cell indices of that basin's members.
    """
    n = len(cells)
    is_ocean = np.zeros(n, dtype=bool)
    for i in range(n):
        c = cells[i]
        if c.elevation <= sea_level_m and c.crust_type in ("oceanic", "transitional"):
            is_ocean[i] = True

    basin_id = np.full(n, -1, dtype=np.int64)
    basins: list[np.ndarray] = []

    for seed in range(n):
        if not is_ocean[seed] or basin_id[seed] >= 0:
            continue
        # BFS over ocean neighbours
        queue: deque[int] = deque([seed])
        basin_id[seed] = len(basins)
        members: list[int] = [seed]
        while queue:
            i = queue.popleft()
            for j in cells[i].neighbors:
                if 0 <= j < n and is_ocean[j] and basin_id[j] < 0:
                    basin_id[j] = len(basins)
                    queue.append(j)
                    members.append(j)
        basins.append(np.array(members, dtype=np.int64))

    return basin_id, basins


def compute_land_mask(
    cells: list[VoronoiCell],
    sea_level_m: float = 0.0,
) -> np.ndarray:
    """Land mask via ocean connectivity (flood-fill from the global ocean).

    The climate engine's land/ocean split cannot be a bare ``elevation >= 0``
    test: endorheic basins below sea level (Turpan −154 m, Qattara, Afar, Death
    Valley) are dry LAND, not ocean.  This helper marks a cell as "ocean" only
    when it is part of a water body connected to the *global ocean* (the largest
    connected water basin); closed below-sea-level basins fall out as land.

    The continental shelf stays ocean (it is connected to the world ocean),
    which a crust-type test alone would get wrong — hence the pure elevation +
    connectivity criterion, independent of ``crust_type``.

    Args:
        cells: All VoronoiCell objects (needs ``neighbors``).
        sea_level_m: Sea-level offset (from TerrainPipelineConfig).

    Returns:
        Boolean land mask, shape (N,).  True = land, False = ocean.
    """
    n = len(cells)
    is_water = np.array([c.elevation <= sea_level_m for c in cells], dtype=bool)

    basin_id = np.full(n, -1, dtype=np.int64)
    basins: list[np.ndarray] = []
    for seed in range(n):
        if not is_water[seed] or basin_id[seed] >= 0:
            continue
        queue: deque[int] = deque([seed])
        basin_id[seed] = len(basins)
        members: list[int] = [seed]
        while queue:
            i = queue.popleft()
            for j in cells[i].neighbors:
                if 0 <= j < n and is_water[j] and basin_id[j] < 0:
                    basin_id[j] = len(basins)
                    queue.append(j)
                    members.append(j)
        basins.append(np.array(members, dtype=np.int64))

    if not basins:
        # No water anywhere → the whole surface is land.
        return np.ones(n, dtype=bool)

    # Global ocean = largest connected water basin.  Everything else is land
    # (emergent land AND closed below-sea-level basins / inland lakes).
    ocean = np.zeros(n, dtype=bool)
    ocean[max(basins, key=len)] = True
    return ~ocean


# ===================================================================
# Sparse operator assembly (per basin)
# ===================================================================


def _global_to_local(basin_cells: np.ndarray, n_global: int) -> np.ndarray:
    """Map global cell id → local index within basin (or −1 if not in basin)."""
    local_map = np.full(n_global, -1, dtype=np.int64)
    local_map[basin_cells] = np.arange(len(basin_cells), dtype=np.int64)
    return local_map


def assemble_graph_laplacian(
    basin_cells: np.ndarray,
    areas_km2: np.ndarray,
    cells: list[VoronoiCell],
) -> sparse.csr_matrix:
    """Uniform-weighted graph Laplacian on a single ocean basin.

    L[i,j] = 1/A_i   for j ∈ N(i)
    L[i,i] = −k_i / A_i   where k_i = |N(i)|

    Parameters for coastal cells (Dirichlet ψ=0) are set later by
    ``apply_dirichlet_bc``.

    Args:
        basin_cells: Global cell indices of this basin.
        areas_km2:   Cell areas (km²), shape (N_global,).
        cells:       All VoronoiCell objects.

    Returns:
        Sparse (N_basin × N_basin) CSR matrix.
    """
    n_global = len(cells)
    n_local = len(basin_cells)
    local_map = _global_to_local(basin_cells, n_global)

    row: list[int] = []
    col: list[int] = []
    data: list[float] = []

    for gi in basin_cells:
        li = local_map[gi]
        ki = len(cells[gi].neighbors)
        inv_area = 1.0 / areas_km2[gi]
        # Off-diagonal: +1/A_i per neighbour in basin
        for gj in cells[gi].neighbors:
            if 0 <= gj < n_global:
                lj = local_map[gj]
                if lj >= 0:
                    row.append(li)
                    col.append(lj)
                    data.append(inv_area)
        # Diagonal: −k_i / A_i
        row.append(li)
        col.append(li)
        data.append(-ki * inv_area)

    return sparse.csr_matrix((data, (row, col)), shape=(n_local, n_local), dtype=np.float64)


def assemble_east_gradient(
    basin_cells: np.ndarray,
    cells: list[VoronoiCell],
    nodes_xyz: np.ndarray,
    east: np.ndarray,
) -> sparse.csr_matrix:
    """East-component of the graph gradient on a single ocean basin.

    ∂ψ/∂x|_i = (1/W_i) · Σ_{j∈N(i)} (ψ_j − ψ_i) / d_ij × (n̂_ij · ê_i)

    where  W_i = Σ_{j∈N(i)} 1/d_ij,  d_ij is the great-circle distance,
    n̂_ij is the unit direction from i to j tangent to the sphere,
    and ê_i is the local east direction.

    Args:
        basin_cells: Global cell indices of this basin.
        cells:       All VoronoiCell objects.
        nodes_xyz:   Unit sphere positions, shape (N_global, 3).
        east:        East unit vectors, shape (N_global, 3).

    Returns:
        Sparse (N_basin × N_basin) CSR matrix.
    """
    n_global = len(cells)
    n_local = len(basin_cells)
    local_map = _global_to_local(basin_cells, n_global)

    row: list[int] = []
    col: list[int] = []
    data: list[float] = []
    diag_accum = np.zeros(n_local, dtype=np.float64)

    for gi in basin_cells:
        li = local_map[gi]
        neighbors = [j for j in cells[gi].neighbors if 0 <= j < n_global]
        if not neighbors:
            continue

        xyz_i = nodes_xyz[gi]
        e_i = east[gi]

        # Weight = 1 / great-circle distance
        weights: list[float] = []
        directions: list[np.ndarray] = []
        for gj in neighbors:
            xyz_j = nodes_xyz[gj]
            dot = max(-1.0, min(1.0, float(np.dot(xyz_i, xyz_j))))
            d = np.arccos(dot)
            if d < 1e-9:
                weights.append(0.0)
                directions.append(np.zeros(3, dtype=np.float64))
                continue
            w = 1.0 / d
            weights.append(w)
            # Direction from i to j (tangent)
            n_ij = xyz_j - xyz_i
            radial = float(np.dot(n_ij, xyz_i))
            n_ij = n_ij - radial * xyz_i
            n_norm = np.linalg.norm(n_ij)
            if n_norm > 1e-9:
                n_ij = n_ij / n_norm
            directions.append(n_ij)

        w_sum = sum(weights)
        if w_sum < 1e-9:
            continue

        for gj, w, n_ij in zip(neighbors, weights, directions, strict=True):
            lj = local_map[gj]
            if lj < 0:
                continue
            coeff = (w / w_sum) * float(np.dot(n_ij, e_i))
            if abs(coeff) < 1e-15:
                continue
            row.append(li)
            col.append(lj)
            data.append(coeff)
            diag_accum[li] -= coeff

    # Add diagonal entries
    for li in range(n_local):
        if diag_accum[li] != 0.0:
            row.append(li)
            col.append(li)
            data.append(diag_accum[li])

    return sparse.csr_matrix((data, (row, col)), shape=(n_local, n_local), dtype=np.float64)


def assemble_stommel_operator(
    basin_cells: np.ndarray,
    cells: list[VoronoiCell],
    nodes_xyz: np.ndarray,
    areas_km2: np.ndarray,
    beta: np.ndarray,
    bottom_friction: float,
    east: np.ndarray,
) -> sparse.csr_matrix:
    """Assemble Stommel operator  A = diag(β) @ G_east + R × L.

    Args:
        basin_cells:     Global indices of this basin.
        cells:           All VoronoiCell objects.
        nodes_xyz:       Unit sphere positions, shape (N_global, 3).
        areas_km2:       Cell areas (km²), shape (N_global,).
        beta:            Planetary vorticity gradient per cell (m⁻¹ s⁻¹), shape (N_global,).
        bottom_friction: Stommel R (s⁻¹).
        east:            East unit vectors, shape (N_global, 3).

    Returns:
        Sparse (N_basin × N_basin) CSR matrix.
    """
    L = assemble_graph_laplacian(basin_cells, areas_km2, cells)
    G_east = assemble_east_gradient(basin_cells, cells, nodes_xyz, east)

    # Extract basin β values
    beta_basin = beta[basin_cells]
    # diag(β) @ G_east — scale each row of G_east by β_i
    D_beta = sparse.diags(beta_basin, dtype=np.float64)
    A = D_beta @ G_east + bottom_friction * L
    return A


# ===================================================================
# Dirichlet BC helper
# ===================================================================


def apply_dirichlet_coastal(
    A: sparse.csr_matrix,
    rhs: np.ndarray,
    basin_cells: np.ndarray,
    cells: list[VoronoiCell],
    sea_level_m: float = 0.0,
) -> tuple[sparse.csr_matrix, np.ndarray]:
    """Apply ψ=0 Dirichlet BC at coastal cells (ocean cells with land neighbours).

    A coastal cell is an ocean cell that has at least one neighbour with
    elevation > sea_level and non-oceanic crust.

    We zero its row, set the diagonal to 1, and set rhs = 0.
    Uses LIL format for efficient row-level editing of the sparse matrix.

    Returns:
        (A_csr_modified, rhs_modified).
    """
    n_global = len(cells)
    rhs_mod = rhs.copy()

    # Identify coastal local indices (pre-compute to avoid neighbour traversal
    # inside the LIL row-editing loop).
    coastal_local: list[int] = []
    for li, gi in enumerate(basin_cells):
        for nj in cells[gi].neighbors:
            if 0 <= nj < n_global:
                nc = cells[nj]
                if nc.elevation > sea_level_m and nc.crust_type == "continental":
                    coastal_local.append(li)
                    rhs_mod[li] = 0.0
                    break

    if not coastal_local:
        return A, rhs_mod

    # Convert to LIL once, edit coastal rows, convert back.
    A_lil = A.tolil()
    for li in coastal_local:
        A_lil[li, :] = 0.0
        A_lil[li, li] = 1.0

    return A_lil.tocsr(), rhs_mod


# ===================================================================
# Solve
# ===================================================================


def solve_ocean_gyre(
    basin_cells: np.ndarray,
    cells: list[VoronoiCell],
    nodes_xyz: np.ndarray,
    areas_km2: np.ndarray,
    curl_z: np.ndarray,
    beta: np.ndarray,
    bottom_friction: float = DEFAULT_BOTTOM_FRICTION,
    h_ml: float = DEFAULT_H_ML,
    east: np.ndarray | None = None,
    sea_level_m: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Solve the Stommel streamfunction and derive current velocity for one basin.

    Equation:  β ∂ψ/∂x + R ∇²ψ = curl_z(τ) / (ρ_w H_ml)

    ψ = 0 at coastal cells (Dirichlet BC).  The system is solved via
    conjugate gradient (CG).

    Args:
        basin_cells:     Global indices of basin members.
        cells:           All VoronoiCell objects.
        nodes_xyz:       Unit sphere positions, shape (N_global, 3).
        areas_km2:       Cell areas (km²), shape (N_global,).
        curl_z:          Wind-stress curl at every cell, shape (N_global,).
        beta:            Planetary β at every cell (m⁻¹ s⁻¹), shape (N_global,).
        bottom_friction: Stommel R (s⁻¹).
        h_ml:            Mixed-layer depth (m).
        east:            East unit vectors (computed once, optional).
        sea_level_m:     Sea-level offset.

    Returns:
        (psi, velocity) —
        psi:      Streamfunction (m²/s), shape (N_basin,).
        velocity: 3-D tangent current vectors, shape (N_basin, 3).
    """
    n_global = len(cells)
    n_local = len(basin_cells)

    if east is None:
        east, _ = east_north_basis(nodes_xyz)

    # ---- assemble operator ----
    A = assemble_stommel_operator(
        basin_cells,
        cells,
        nodes_xyz,
        areas_km2,
        beta,
        bottom_friction,
        east,
    )

    # ---- RHS ----
    rhs = curl_z[basin_cells] / (RHO_WATER * h_ml)

    # ---- Dirichlet BC at coastal cells ----
    A, rhs = apply_dirichlet_coastal(A, rhs, basin_cells, cells, sea_level_m)

    # ---- solve (GMRES — Stommel op is non-symmetric) ----
    # Relaxed tolerance (1e-6 → 1e-4): ocean currents are for visualisation
    # and qualitative climate coupling, not centimetre-precision science.
    # 10× looser tolerance gives 3–5× fewer GMRES iterations on large basins.
    #
    # Jacobi (diagonal) preconditioner: Stommel operator has strong diagonal
    # from the graph Laplacian (R * L, with L_diag ∝ -k_i/A_i).  Diagonal
    # scaling costs O(N) and typically halves the iteration count.
    diag = np.abs(A.diagonal())
    diag_inv = np.where(diag > 1e-15, 1.0 / diag, 1.0)
    M = sparse.diags(diag_inv, format="csr")
    psi, info = gmres(
        A,
        rhs,
        M=M,
        rtol=1e-4,
        atol=1e-10,
        maxiter=min(n_local * 2, 20000),
    )
    if info != 0:
        import logging as _logging  # noqa: F811

        _logging.getLogger(__name__).warning(
            "GMRES did not converge for basin of %d cells (info=%d); result may be approximate.",
            n_local,
            info,
        )

    # ---- velocity from ψ (u = k̂ × ∇ψ on sphere) ----
    # Compute graph gradient of ψ on the global mesh (ψ=0 for non-basin cells).
    psi_global = np.zeros(n_global, dtype=np.float64)
    psi_global[basin_cells] = psi

    src, dst = _build_directed_edge_table(cells)
    grad_psi = _graph_gradient(psi_global, nodes_xyz, src, dst, n_global)
    # Only return basin cells
    grad_basin = grad_psi[basin_cells]
    # u = k̂ × ∇ψ  (cross product with radial unit vector, giving tangent vector)
    velocity = np.cross(nodes_xyz[basin_cells], grad_basin)

    # u = k̂ × ∇ψ is already in m/s: the RHS was divided by ρ_w·H_ml, so ψ has
    # units m²/s and its gradient ∇ψ has units m/s directly — no further
    # scaling by H_ml (that shrank speeds ~50×, leaving nacrea currents at
    # ~0.9 cm/s instead of the physically expected ~50 cm/s surface flow).
    return psi, velocity


def _is_coastal(
    gi: int,
    cells: list[VoronoiCell],
    n_global: int,
    basin_id: np.ndarray,
) -> bool:
    """True if cell *gi* has a land neighbour (elevation > 0, continental crust)."""
    for nj in cells[gi].neighbors:
        if 0 <= nj < n_global:
            nc = cells[nj]
            if nc.elevation > 0.0 and nc.crust_type == "continental":
                return True
    return False


# ===================================================================
# Ekman upwelling index
# ===================================================================


def compute_upwelling_index(
    wind: np.ndarray,
    cells: list[VoronoiCell],
    nodes_xyz: np.ndarray,
    east: np.ndarray,
    north: np.ndarray,
    lat_rad: np.ndarray,
) -> np.ndarray:
    """Ekman upwelling index from wind-driven divergence.

    Positive = upwelling (divergence of Ekman transport).
    Significant only near eastern ocean boundaries where trade winds
    drive offshore Ekman transport.

    For each ocean cell with an eastern-boundary character (wind blows
    equatorward along the coast, pushing surface water offshore), we
    set a positive upwelling index proportional to the along-shore
    wind component.

    Args:
        wind:     Wind vectors (m/s), shape (N, 3).
        cells:    All VoronoiCell objects.
        nodes_xyz, east, north: geometry arrays.
        lat_rad:  Latitude in radians, shape (N,).

    Returns:
        Upwelling index (dimensionless proxy), shape (N,).
        Land cells = 0.  Only coastal ocean cells with favourable wind
        direction get non-zero values.
    """
    n = len(cells)
    upwelling = np.zeros(n, dtype=np.float64)

    for i in range(n):
        c = cells[i]
        if c.crust_type not in ("oceanic", "transitional"):
            continue
        if c.elevation > 0.0:
            continue
        if not _is_coastal(i, cells, n, np.array([])):
            continue

        # Determine whether cell is near an eastern boundary.
        # Eastern boundary cells have a majority of land neighbours to the east.
        east_neighbor_land = False
        for j in c.neighbors:
            if 0 <= j < n:
                nc = cells[j]
                if nc.elevation > 0.0 and nc.crust_type == "continental":
                    # Check if this land neighbour lies roughly east of cell i
                    d_lon = nc.lon - c.lon
                    # Normalise to [-180, 180]
                    if d_lon > 180:
                        d_lon -= 360
                    elif d_lon < -180:
                        d_lon += 360
                    if abs(d_lon) < 90 and d_lon > 0:
                        east_neighbor_land = True
                        break

        if not east_neighbor_land:
            continue

        # Wind at this cell
        _w_east, w_north = decompose_tangent(wind[i : i + 1], east[i : i + 1], north[i : i + 1])
        w_north_val = float(w_north[0])

        # Offshore Ekman transport: equatorward along-shore wind drives
        # westward Ekman transport offshore → upwelling at east coast.
        equatorward_wind = -np.sign(lat_rad[i]) * w_north_val
        if equatorward_wind > 0:
            upwelling[i] = equatorward_wind  # proxy index (m/s)

    return upwelling


def apply_upwelling_sst_correction(
    upwelling_index: np.ndarray,
    sst_c: np.ndarray,
    *,
    cooling_coeff_c_per_ms: float = 0.8,
    max_cooling_c: float = 6.0,
) -> np.ndarray:
    """Cool SST in upwelling regions — Ekman suction brings cold deep water up.

    Coastal upwelling (eastern ocean boundaries where winds drive offshore
    Ekman transport) is the primary process behind cold eastern-boundary
    currents (Humboldt, California, Canary, Benguela on Earth) and the
    associated cold coastal deserts (Atacama, Namib).

    The cooling is proportional to the upwelling index computed by
    ``compute_upwelling_index()`` (units of m/s-equivalent equatorward
    wind) and the coefficient ``cooling_coeff_c_per_ms``:

        ΔSST = −min( coeff × upw_index,  max_cooling )

    The coefficient is **not** a free Earth-tuned parameter — it arises
    from Ekman-layer physics (ρ_a C_d |U| / (ρ f H_ml) × ΔT_thermocline ≈
    0.5–1.0 °C per m/s for Earth-like parameters) and is kept planet-generic
    because the wind-speed dependence is already encoded in the upwelling
    index itself.

    Args:
        upwelling_index: ``compute_upwelling_index()`` output (m/s-equiv).
        sst_c: Current sea-surface temperature (°C), shape (N,).
        cooling_coeff_c_per_ms: SST cooling per unit upwelling index.
        max_cooling_c: Hard ceiling on cooling to prevent unphysical SST.

    Returns:
        Corrected SST (°C), shape (N,).
    """
    cooling = np.minimum(cooling_coeff_c_per_ms * upwelling_index, max_cooling_c)
    result = sst_c - cooling
    # Only clip upwelled cells to sea-water freezing point (−2 °C);
    # land cells and non-upwelling ocean are left alone.
    mask = upwelling_index > 0
    result[mask] = np.maximum(result[mask], -2.0)
    return np.asarray(result)


# ===================================================================
# SST correction via along-current advection relaxation
# ===================================================================


def advect_sst_relaxation(
    sst_ref: np.ndarray,
    current_velocity: np.ndarray,
    basin_cells: np.ndarray,
    cells: list[VoronoiCell],
    nodes_xyz: np.ndarray,
    coastal_distance_km: np.ndarray | None = None,
    n_passes: int = DEFAULT_SST_PASSES,
    relaxation_rate: float = DEFAULT_SST_RELAXATION,
    coastal_influence_km: float = DEFAULT_COASTAL_INFLUENCE_KM,
) -> tuple[np.ndarray, np.ndarray]:
    """Correct SST by relaxing each cell toward the average of its upstream neighbours.

    Iterates over the ocean cells of one basin, each pass moving SST toward
    the weighted mean of upstream (where current flows FROM) cells.

    Args:
        sst_ref:              Reference SST (latitude profile), shape (N_global,).
        current_velocity:     Surface current vectors, shape (N_basin, 3).
        basin_cells:          Global cell indices of this basin.
        cells:                All VoronoiCell objects.
        nodes_xyz:            Unit sphere positions, shape (N_global, 3).
        coastal_distance_km:  Distance from coast per cell (optional, shape (N_global,)).
        n_passes:             Number of relaxation sweeps.
        relaxation_rate:      λ per sweep.
        coastal_influence_km: Radius for maritime influence on land cells.

    Returns:
        (sst_final, anomaly) —
        sst_final: SST after advection, shape (N_global,).  Non-basin/land = sst_ref.
        anomaly:   sst_final − sst_ref (only meaningful in ocean), shape (N_global,).
    """
    n_global = len(cells)
    n_local = len(basin_cells)
    local_map = _global_to_local(basin_cells, n_global)

    sst = sst_ref.copy()

    # Precompute per-cell "incoming" neighbour weights once: for cell i,
    # upstream neighbours are those where current flows toward i.
    upstream_neighbors: list[list[int]] = [[] for _ in range(n_local)]
    upstream_weights: list[list[float]] = [[] for _ in range(n_local)]

    for li, gi in enumerate(basin_cells):
        vel_i = current_velocity[li]
        for gj in cells[gi].neighbors:
            if 0 <= gj < n_global:
                lj = local_map[gj]
                if lj < 0:
                    continue
                # Direction from i to j
                d_ij = nodes_xyz[gj] - nodes_xyz[gi]
                radial = float(np.dot(d_ij, nodes_xyz[gi]))
                d_ij = d_ij - radial * nodes_xyz[gi]
                # Dot product with current: positive → j is downstream of i
                # For upstream neighbours we want flow FROM j TO i, so reverse:
                # u_i · (−d_ij) = −u_i · d_ij > 0  means j is upstream
                alignment = -float(np.dot(vel_i, d_ij))
                if alignment > 1e-9:
                    upstream_neighbors[li].append(lj)
                    upstream_weights[li].append(alignment)

    # Relaxation sweeps (Jacobi-style: update from previous iteration's values)
    for _ in range(n_passes):
        sst_new = sst.copy()
        for li, gi in enumerate(basin_cells):
            if not upstream_neighbors[li]:
                continue
            w_local = upstream_weights[li]
            w_total = sum(w_local)
            if w_total < 1e-9:
                continue
            upstream_mean = (
                sum(
                    w_local[k] * sst[basin_cells[lj]] for k, lj in enumerate(upstream_neighbors[li])
                )
                / w_total
            )
            sst_new[gi] = (1.0 - relaxation_rate) * sst[gi] + relaxation_rate * upstream_mean
        sst = sst_new

    anomaly = sst - sst_ref

    # Maritime influence: coastal land cells get a fraction of nearby ocean anomaly
    if coastal_influence_km > 0 and coastal_distance_km is not None:
        for i in range(n_global):
            c = cells[i]
            if c.crust_type == "continental" and c.elevation > 0.0:
                d = coastal_distance_km[i] if coastal_distance_km[i] > 0 else 1e9
                if d < coastal_influence_km:
                    # Nearest ocean anomaly (approximate from neighbours)
                    ocean_anomalies: list[float] = []
                    for j in c.neighbors:
                        if 0 <= j < n_global:
                            nc = cells[j]
                            if nc.crust_type in ("oceanic", "transitional") and nc.elevation <= 0.0:
                                ocean_anomalies.append(anomaly[j])
                    if ocean_anomalies:
                        mean_anom = float(np.mean(ocean_anomalies))
                        weight = max(0.0, 1.0 - d / coastal_influence_km)
                        sst[i] += mean_anom * weight
                        anomaly[i] = mean_anom * weight

    return sst, anomaly


# ===================================================================
# SST advection — semi-Lagrangian upstream tracing (replaces diffusive relaxation)
# ===================================================================


def _trace_upstream(
    start_gi: int,
    vel_global: np.ndarray,
    cells: list[VoronoiCell],
    nodes_xyz: np.ndarray,
    radius_m: float,
    max_dist_m: float,
    ocean_only: bool = True,
) -> int:
    """Trace a streamline upstream from ``start_gi`` for ``max_dist_m`` metres.

    Walks cell-to-cell along the −u direction (steepest upstream neighbour),
    accumulating great-circle distance.  Returns the global id of the cell
    reached when the distance exceeds ``max_dist_m``, or the last cell before
    a coast / zero-flow dead end.

    When ``ocean_only`` is True (SST advection), tracing is restricted to ocean
    cells — land blocks the current and its temperature is an air temp, not an
    SST.  Set False to trace across land (temperature-anomaly advection by wind).
    """
    gi = start_gi
    dist = 0.0
    # At ~76 km/cell and max_dist ≲ 1500 km this is < ~20 hops; cap generously.
    for _ in range(64):
        u = vel_global[gi]
        u_norm = float(np.linalg.norm(u))
        if u_norm < 1e-12:
            break
        best_j = -1
        best_cos = -1.0  # require cos > 0 → a genuine upstream neighbour
        for j in cells[gi].neighbors:
            if not 0 <= j < len(cells):
                continue
            if ocean_only:
                # Land blocks the current, and a land cell's temperature is a
                # surface air temp, not an SST.
                c_j = cells[j]
                if not (c_j.crust_type in ("oceanic", "transitional") and c_j.elevation <= 0.0):
                    continue
            d = nodes_xyz[j] - nodes_xyz[gi]
            radial = float(np.dot(d, nodes_xyz[gi]))
            d = d - radial * nodes_xyz[gi]
            d_norm = float(np.linalg.norm(d))
            if d_norm < 1e-12:
                continue
            cos = float(np.dot(-u, d) / (u_norm * d_norm))
            if cos > best_cos:
                best_cos = cos
                best_j = j
        if best_j < 0:
            break
        step_rad = float(
            np.arccos(np.clip(float(np.dot(nodes_xyz[gi], nodes_xyz[best_j])), -1.0, 1.0))
        )
        dist += step_rad * radius_m
        gi = best_j
        if dist >= max_dist_m:
            break
    return gi


def advect_sst_semilagrangian(
    sst_ref: np.ndarray,
    current_velocity: np.ndarray,
    basin_cells: np.ndarray,
    cells: list[VoronoiCell],
    nodes_xyz: np.ndarray,
    radius_m: float,
    tau_days: float = DEFAULT_SST_TAU_DAYS,
    coastal_distance_km: np.ndarray | None = None,
    coastal_influence_km: float = DEFAULT_COASTAL_INFLUENCE_KM,
) -> tuple[np.ndarray, np.ndarray]:
    """Advect SST along currents via semi-Lagrangian upstream tracing.

    Each ocean cell takes the SST of the cell reached by tracing upstream a
    distance L = |u|·τ (τ = surface SST adjustment time).  Unlike the old
    diffusive relaxation, warm water is transported downstream without per-hop
    attenuation, so a strong western boundary current produces a several-degree
    anomaly instead of a fraction of a degree.

    Args:
        sst_ref:           Reference SST (latitude profile), shape (N_global,).
        current_velocity:  Surface current vectors, shape (N_basin, 3).
        basin_cells:       Global cell indices of this basin.
        cells:             All VoronoiCell objects.
        nodes_xyz:         Unit sphere positions, shape (N_global, 3).
        radius_m:          Planet radius (m) for distance accumulation.
        tau_days:          SST adjustment time (days) — L = |u|·τ.
        coastal_distance_km: Distance from coast per cell (optional).
        coastal_influence_km: Radius for maritime influence on land cells.

    Returns:
        (sst_final, anomaly) — sst_final shape (N_global,), non-basin/land = sst_ref.
    """
    n_global = len(cells)

    vel_global = np.zeros((n_global, 3), dtype=np.float64)
    vel_global[basin_cells] = current_velocity

    tau_s = tau_days * 86400.0

    sst = sst_ref.copy()
    for li, gi in enumerate(basin_cells):
        u_norm = float(np.linalg.norm(current_velocity[li]))
        max_dist = u_norm * tau_s
        if max_dist < 1e-6:
            continue
        gi_up = _trace_upstream(gi, vel_global, cells, nodes_xyz, radius_m, max_dist)
        if gi_up != gi:
            sst[gi] = sst_ref[gi_up]

    anomaly = sst - sst_ref

    # Maritime influence: coastal land cells get a fraction of nearby ocean anomaly
    if coastal_influence_km > 0 and coastal_distance_km is not None:
        for i in range(n_global):
            c = cells[i]
            if c.crust_type == "continental" and c.elevation > 0.0:
                d = coastal_distance_km[i] if coastal_distance_km[i] > 0 else 1e9
                if d < coastal_influence_km:
                    ocean_anomalies: list[float] = []
                    for j in c.neighbors:
                        if 0 <= j < n_global:
                            nc = cells[j]
                            if nc.crust_type in ("oceanic", "transitional") and nc.elevation <= 0.0:
                                ocean_anomalies.append(anomaly[j])
                    if ocean_anomalies:
                        mean_anom = float(np.mean(ocean_anomalies))
                        weight = max(0.0, 1.0 - d / coastal_influence_km)
                        sst[i] += mean_anom * weight
                        anomaly[i] = mean_anom * weight

    return sst, anomaly


# ===================================================================
# Temperature-anomaly advection onto land (ocean → land coupling via wind)
# ===================================================================


def advect_temperature_anomaly(
    sst_anomaly: np.ndarray,
    wind: np.ndarray,
    is_ocean: np.ndarray,
    cells: list[VoronoiCell],
    nodes_xyz: np.ndarray,
    radius_m: float,
    diffusivity: float = DEFAULT_TEMP_DIFFUSIVITY,
) -> np.ndarray:
    """Advect ocean SST anomalies onto land along the prevailing wind.

    Same wind-biased graph-Laplacian + GMRES steady-state diffusion as the BFS
    moisture transport: ocean cells hold the SST anomaly (source), and a
    wind-aligned diffusion spreads it downwind onto land.  Signed, so warm
    western-boundary currents warm their lee coasts and cold eastern-boundary
    currents (Humboldt-type) cool theirs.

    Args:
        sst_anomaly:  Ocean SST anomaly (signed °C), shape (N_global,) — land ignored.
        wind:         Surface wind vectors, shape (N_global, 3).
        is_ocean:     Boolean ocean mask, shape (N_global,).
        cells:        All VoronoiCell objects.
        nodes_xyz:    Unit sphere positions, shape (N_global, 3).
        radius_m:     Planet radius (m).
        diffusivity:  Wind-biased graph-diffusion coefficient D₀.

    Returns:
        Temperature anomaly for every cell (°C), shape (N_global,).
    """
    n = len(cells)

    # Wind-biased edge alignment (same construction as BFS moisture transport).
    wind_speed = np.linalg.norm(wind, axis=1)
    wind_unit = wind / np.maximum(wind_speed, 1e-9)[:, None]

    src_list: list[int] = []
    dst_list: list[int] = []
    for i, cell in enumerate(cells):
        for j in cell.neighbors:
            if 0 <= j < n:
                src_list.append(i)
                dst_list.append(j)
    src = np.asarray(src_list, dtype=np.int64)
    dst = np.asarray(dst_list, dtype=np.int64)
    edge_vec = nodes_xyz[dst] - nodes_xyz[src]
    radial = np.einsum("ij,ij->i", edge_vec, nodes_xyz[src])
    edge_vec = edge_vec - radial[:, None] * nodes_xyz[src]
    edge_norm = np.linalg.norm(edge_vec, axis=1)
    valid = edge_norm >= 1e-9
    edge_dir = np.zeros_like(edge_vec)
    edge_dir[valid] = edge_vec[valid] / edge_norm[valid, None]
    align = np.where(valid, np.einsum("ij,ij->i", edge_dir, wind_unit[src]), -1.0)
    align_pos = np.maximum(align, 0.0)

    # Symmetric graph Laplacian (CG/GMRES-compatible).
    w = sparse.coo_matrix(
        (
            np.concatenate([align_pos, align_pos]) * 0.5,
            (np.concatenate([src, dst]), np.concatenate([dst, src])),
        ),
        shape=(n, n),
    ).tocsr()
    degree = np.asarray(w.sum(axis=1)).ravel()
    laplacian = sparse.diags(degree) - w

    # Diffusion strength α = D₀ · |wind| / cell_radius (per-cell, wind-scaled).
    cell_radius_km = (radius_m / 1000.0) * np.sqrt(4.0 * np.pi / n)
    alpha = diffusivity * np.maximum(wind_speed, 1e-9) / cell_radius_km
    alpha_avg = float(np.mean(alpha))

    source = np.where(is_ocean, sst_anomaly, 0.0).astype(np.float64)

    # Steady-state diffusion: (I + α·L) T = source.
    a = sparse.eye(n, format="csr") + alpha_avg * laplacian
    t_anom = np.asarray(gmres(a, source, rtol=1e-3, atol=1e-6, maxiter=200)[0])

    return t_anom


# ===================================================================
# Strait detection and hydraulic flux
# ===================================================================


def detect_straits(
    cells: list[VoronoiCell],
    basin_id: np.ndarray,
    sea_level_m: float = 0.0,
    max_width_km: float = 300.0,
) -> list[dict[str, Any]]:
    """Detect potential strait cells between ocean basins.

    A strait cell is an ocean cell whose neighbours include cells from a
    *different* ocean basin AND land on both sides, indicating a narrow
    passage.

    Args:
        cells:        All VoronoiCell objects.
        basin_id:     Basin assignment per cell (−1 = land).
        sea_level_m:  Sea-level offset.
        max_width_km: Maximum strait width to consider (km).

    Returns:
        List of strait info dicts with keys:
        (i, j, basin_a, basin_b, width_km, depth_m, cross_section_m2).
    """
    n = len(cells)
    straits: list[dict[str, Any]] = []

    for i in range(n):
        if basin_id[i] < 0:
            continue
        c = cells[i]
        if c.elevation > sea_level_m:
            continue

        neighbor_basins: set[int] = set()
        for nj in c.neighbors:
            if 0 <= nj < n and basin_id[nj] >= 0 and basin_id[nj] != basin_id[i]:
                neighbor_basins.add(int(basin_id[nj]))

        if not neighbor_basins:
            continue

        # Approximate strait width from cell geometry
        cell_width_km = np.sqrt(c.area_km2)
        if cell_width_km > max_width_km:
            continue

        # Straits need coastal constraint: at least one cell on each side is land
        # (already implicit since basin boundary implies land barrier)

        depth_m = sea_level_m - c.elevation
        if depth_m <= 0:
            continue

        for nb in neighbor_basins:
            straits.append(
                {
                    "cell_i": i,
                    "basin_a": int(basin_id[i]),
                    "basin_b": nb,
                    "width_km": cell_width_km,
                    "depth_m": float(depth_m),
                    "cross_section_m2": cell_width_km * 1000.0 * depth_m,
                }
            )

    return straits


def compute_strait_flux(
    straits: list[dict[str, Any]],
    psi_by_basin: dict[int, np.ndarray],
    basin_cells_list: list[np.ndarray],
    cells: list[VoronoiCell],
    sea_level_m: float = 0.0,
    c_d: float = 1.0,
    g_prime: float = 0.02,
) -> list[dict[str, Any]]:
    """Estimate transport through each strait using a hydraulic constraint.

    T_strait ≈ C_d × A × √(2 g' Δh)

    where Δh is the water-level difference inferred from the streamfunction
    difference across the strait, g' is reduced gravity, and A is the
    cross-sectional area of the channel.

    Args:
        straits:          Output of ``detect_straits``.
        psi_by_basin:     {basin_id: psi_array} where psi is the local (N_basin,) solution.
        basin_cells_list: Global cell indices per basin.
        cells:            All VoronoiCell objects.
        sea_level_m:      Sea-level offset.
        c_d:              Discharge coefficient.
        g_prime:          Reduced gravity (m/s²), default ≈ 0.02 for baroclinic.

    Returns:
        straits list augmented with 'flux_sv' (Sverdrup = 10⁶ m³/s).
    """
    # Build global psi array for quick lookup
    n_global = len(cells)
    psi_global = np.zeros(n_global, dtype=np.float64)
    for bid, psi_local in psi_by_basin.items():
        psi_global[basin_cells_list[bid]] = psi_local

    for s in straits:
        ci = s["cell_i"]

        # Δh from streamfunction difference (ψ in m²/s; divide by strait width
        # and depth to get velocity, but we use hydraulic formula directly)
        psi_diff = abs(psi_global[ci])
        # Approximate sea-level difference from ψ difference
        # (geostrophic: f × u = g × ∂η/∂x; η ~ ψ / (g × width))
        dh = psi_diff / (9.81 * s["width_km"] * 1000.0) if s["width_km"] > 0 else 0.0

        A = s["cross_section_m2"]
        flux_m3s = c_d * A * np.sqrt(2.0 * g_prime * max(dh, 0.0))
        s["flux_sv"] = flux_m3s / 1e6  # convert to Sverdrup
        s["dh_m"] = dh

    return straits


# ===================================================================
# Ekman surface current (vectorised replacement for the orphan
# ekman_current_direction in climate_physics.py)
# ===================================================================


def ekman_surface_current(
    wind: np.ndarray,
    nodes_xyz: np.ndarray,
    lat_rad: np.ndarray,
    speed_ratio: float = 0.02,
) -> np.ndarray:
    """Vectorised Ekman surface current: 45° deflection, ~2% of wind speed.

    Uses spherical cross products instead of the old east-north plane
    rotation, so it is correct everywhere on the sphere.

    Args:
        wind:        Wind vectors (m/s), shape (N, 3).
        nodes_xyz:   Unit sphere positions, shape (N, 3).
        lat_rad:     Latitude in radians, shape (N,).
        speed_ratio: Current speed as fraction of wind speed.

    Returns:
        Ekman current vectors (m/s), shape (N, 3).
    """
    wind_speed = np.linalg.norm(wind, axis=1)
    mask = wind_speed < 1e-9

    # Deflection: rotate wind vector around the local radial axis by ±45°
    # Rotation around r̂ by angle α:  v' = cos(α)·v + sin(α)·(r̂ × v)
    angle = np.sign(lat_rad) * np.radians(45.0)
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)

    r_cross_w = np.cross(nodes_xyz, wind)
    current = cos_a[:, None] * wind + sin_a[:, None] * r_cross_w
    current *= speed_ratio
    current[mask] = 0.0
    return current  # type: ignore[no-any-return]
