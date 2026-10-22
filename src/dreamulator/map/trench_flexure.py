"""Trench cell-mean depth from the flexure of the subducting plate (technical debt 43, phase D).

Physics and calibration: ``docs/knowledge/geology/orogen_topography.md`` §5–6.  A trench is
the flexural moat of the down-going plate, broken at the axis and bent by the slab
(Caldwell et al. 1976; Turcotte & Schubert, *Geodynamics*, eq. 3.159).  With an end load only,
the deflection at distance x from the axis on the subducting plate is

    w(x) = −W0 · e^(−x/α) · cos(x/α),     α = [4D / ((ρm − ρw)·g)]^¼,  D = E·Te³ / (12(1 − ν²)),

which gives the outer rise (≈ 0.04 W0 at π·α) without a separate term.  It is added to the
age–depth seafloor of the subducting plate's oceanic cells only; the overriding plate gets
no trench.  Cell values are the mean of w over the cell's span [d, d + Δx] measured from
the axis (the cell-mean semantics of §1.1); the axis point depth is a sub-grid quantity.

Closures:

* Te = 25 km for every plate age — observation fit: trench Te shows almost no age trend
  because bending faults and yielding weaken the plate (Craig & Copley 2014;
  Contreras-Reyes & Osses 2010); Earth α ≈ 65 km, scaling with g as g^(−¼).
* W0 = 2.0 km — observation fit on Earth: on the 200k grid the ETOPO axis cell lies a median
  1.17 km below the same-plate seafloor 250–450 km away, i.e. W0 ≈ 1.9 km with the
  contact-cell factor 0.62 (literature range 0.5–2.5 km, Craig & Copley 2014).  No age or
  convergence-rate dependence (neither verified); no sediment fill.  Author ruling
  2026-10-21: the same W0 on every world.

Forearc (§6): on ocean–continent margins the overriding plate's leading edge is a
critically tapered wedge riding on the slab (Davis et al. 1983).  Its surface rises from the
trench axis at the slope α, so the coast sits where the wedge reaches sea level, and the
Andean orogen stands behind the forearc.  α = 1.55° — observation fit: on Earth's
ocean–continent margins (200k grid, ETOPO cell means) the overriding-side profile rises from
the axis cell (median −4.2 km) to sea level at ~150 km; regional values range from ~0.9°
(accretionary, Cascadia) to ~2.4° (erosive, central Andes), the controlling basal friction
and sediment supply are not derivable here.  Ocean–ocean arcs are left to the island
catalogue (debt 44).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from dreamulator.map.orogen_contract import contact_polarity

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh, TectonicPlate
    from dreamulator.map.orogen_contract import OrogenContract

_YOUNG_MODULUS_PA = 70.0e9
_POISSON = 0.25
_ELASTIC_THICKNESS_KM = 25.0
_RHO_MANTLE = 3300.0
_RHO_WATER = 1030.0
AXIS_DEFLECTION_M = 2000.0
FOREARC_SLOPE_DEG = 1.55
# The wedge surface is followed up to this height (m), above any orogen's mean-elevation cap.
_WEDGE_TOP_M = 6000.0


def flexural_parameter_km(gravity_m_s2: float) -> float:
    """α (km) of the trench plate."""
    te = _ELASTIC_THICKNESS_KM * 1000.0
    d = _YOUNG_MODULUS_PA * te**3 / (12.0 * (1.0 - _POISSON**2))
    return float((4.0 * d / ((_RHO_MANTLE - _RHO_WATER) * gravity_m_s2)) ** 0.25 / 1000.0)


def _primitive(x: np.ndarray, alpha: float) -> np.ndarray:
    """∫ e^(−x/α)·cos(x/α) dx, truncated at the profile end 3π/2·α."""
    x = np.minimum(x, 1.5 * np.pi * alpha)
    out: np.ndarray = 0.5 * alpha * np.exp(-x / alpha) * (np.sin(x / alpha) - np.cos(x / alpha))
    return out


def cell_mean_factor(d_km: np.ndarray, dx_km: float, alpha_km: float) -> np.ndarray:
    """Mean of e^(−x/α)·cos(x/α) over [d, d + Δx] (w = −W0 × this)."""
    d = np.asarray(d_km, dtype=np.float64)
    out: np.ndarray = (_primitive(d + dx_km, alpha_km) - _primitive(d, alpha_km)) / dx_km
    return out


def _graph(mesh: CVTMesh, radius_km: float) -> csr_matrix:
    cells = mesh.cells
    n = len(cells)
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    rows = np.repeat(np.arange(n), [len(c.neighbors) for c in cells])
    cols = np.array([j for c in cells for j in c.neighbors], dtype=np.int64)
    w = np.arccos(np.clip(np.einsum("ij,ij->i", xyz[rows], xyz[cols]), -1.0, 1.0)) * radius_km
    return csr_matrix((w, (rows, cols)), shape=(n, n))


def trench_sources(
    mesh: CVTMesh, plates: list[TectonicPlate], contract: OrogenContract, radius_km: float
) -> dict[int, str]:
    """Axis cells: convergent contact cells on the down-going plate, ``cell -> plate``.

    Andean margins take the down-going plate from the history contract (author overrides
    included); ocean–ocean contacts from ``contact_polarity``.  Only oceanic cells.
    """
    cells = mesh.cells
    out: dict[int, str] = {}
    for seg in contract.segments:
        if seg.kind != "andean":
            continue
        for k in seg.cell_ids:
            if cells[k].plate_id == seg.pro_plate and cells[k].crust_type == "oceanic":
                out[k] = seg.pro_plate
    for k, (kind, down, _over) in contact_polarity(mesh, plates, radius_km).items():
        if kind == "ocean" and cells[k].plate_id == down and cells[k].crust_type == "oceanic":
            out[k] = down
    return out


def trench_relief(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    contract: OrogenContract,
    radius_km: float,
    gravity_m_s2: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cell-mean flexure (m, negative in the moat), axis offsets and the subducting side.

    Returns ``(relief, axis_offset, subducting)``: ``axis_offset`` is the axis point depth
    minus the cell mean (m, negative) on axis cells and NaN elsewhere; ``subducting``
    marks the cells inside a profile (the down-going plate within 3π/2·α of its axis),
    where no arc stands.  Each oceanic cell of a
    down-going plate takes the profile of its nearest axis cell of the same plate (graph
    distance through that plate's oceanic cells).
    """
    cells = mesh.cells
    n = len(cells)
    relief = np.zeros(n, dtype=np.float64)
    axis_offset = np.full(n, np.nan)
    subducting = np.zeros(n, dtype=bool)
    sources = trench_sources(mesh, plates, contract, radius_km)
    if not sources:
        return relief, axis_offset, subducting
    alpha = flexural_parameter_km(gravity_m_s2)
    dx = float(np.sqrt(4.0 * np.pi * radius_km**2 / n))
    graph = _graph(mesh, radius_km)
    plate_arr = np.array([c.plate_id or "" for c in cells])
    oceanic = np.array([c.crust_type == "oceanic" for c in cells])
    for pid in sorted(set(sources.values())):
        src = np.array(sorted(k for k, p in sources.items() if p == pid), dtype=np.int64)
        nodes = np.flatnonzero(oceanic & (plate_arr == pid))
        d = dijkstra(
            graph[nodes][:, nodes],
            indices=np.searchsorted(nodes, src),
            min_only=True,
            limit=1.5 * np.pi * alpha,
        )
        ok = np.isfinite(d)
        subducting[nodes[ok]] = True
        relief[nodes[ok]] = -AXIS_DEFLECTION_M * cell_mean_factor(d[ok], dx, alpha)
    axis_ids = np.array(sorted(sources), dtype=np.int64)
    axis_offset[axis_ids] = -AXIS_DEFLECTION_M - relief[axis_ids]
    return relief, axis_offset, subducting


def forearc(
    mesh: CVTMesh,
    contract: OrogenContract,
    axis_mean_m: np.ndarray,
    radius_km: float,
) -> tuple[np.ndarray, dict[int, float]]:
    """Forearc wedge surface of ocean–continent margins and the forearc width per contact cell.

    ``axis_mean_m`` is the cell-mean elevation of each axis cell (seafloor plus the axis-cell
    flexure).  Returns ``(surface, width)``: ``surface`` is the wedge surface (m) on cells of
    the overriding side up to where it reaches the highest mean elevation any orogen can
    have (``inf`` elsewhere), an upper bound on their cell mean — below sea level it is the
    submerged forearc, above it a ramp that keeps any upper-plate relief (a neighbouring
    collision plateau included) from standing as a cliff over the forearc; ``width`` maps
    every Andean contact cell to the forearc width (km) of its nearest axis cell, the
    distance at which the wedge reaches sea level and the Andean flank starts.
    """
    cells = mesh.cells
    n = len(cells)
    surface = np.full(n, np.inf)
    width: dict[int, float] = {}
    slope = float(np.tan(np.radians(FOREARC_SLOPE_DEG))) * 1000.0  # m per km
    andean = [s for s in contract.segments if s.kind == "andean"]
    axis_of: dict[str, list[int]] = {}
    for seg in andean:
        for k in seg.cell_ids:
            if cells[k].plate_id == seg.pro_plate and cells[k].crust_type == "oceanic":
                axis_of.setdefault(seg.pro_plate, []).append(k)
    if not axis_of:
        return surface, width
    graph = _graph(mesh, radius_km)
    plate_arr = np.array([c.plate_id or "" for c in cells])
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    for pid, ax in sorted(axis_of.items()):
        src = np.array(sorted(set(ax)), dtype=np.int64)
        reach = (float(np.max(np.maximum(-axis_mean_m[src], 0.0))) + _WEDGE_TOP_M) / slope
        nodes = np.union1d(np.flatnonzero(plate_arr != pid), src)
        d, _, near = dijkstra(
            graph[nodes][:, nodes],
            indices=np.searchsorted(nodes, src),
            min_only=True,
            limit=reach,
            return_predecessors=True,
        )
        ok = np.isfinite(d) & (plate_arr[nodes] != pid)
        cid = nodes[ok]
        s_m = axis_mean_m[nodes[near[ok]]] + slope * d[ok]
        surface[cid] = np.minimum(surface[cid], s_m)
    all_ax = np.array(sorted({k for v in axis_of.values() for k in v}), dtype=np.int64)
    w_ax = np.maximum(-axis_mean_m[all_ax], 0.0) / slope
    tree = cKDTree(xyz[all_ax])
    for seg in andean:
        _, j = tree.query(xyz[np.array(seg.cell_ids)])
        for k, jj in zip(seg.cell_ids, np.atleast_1d(j), strict=True):
            width[int(k)] = float(w_ax[int(jj)])
    return surface, width
