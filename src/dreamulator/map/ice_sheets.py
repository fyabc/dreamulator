"""Polar ice sheets — appended post-pass over the calibrated terrain.

Runs as the final terrain-modifying stage (after sea-level calibration,
geography pins, isostatic compression, smoothing and rivers), so the
coastline configuration is untouched: ice is added on top of land cells
only, the sea level stays where the calibration put it, and bedrock is
reconstructible as ``elevation - ice_thickness_m``.

Physics
-------
Thermal gate (symmetric, dimensionless):
    Annual-mean TOA insolation below a fraction of the world's own
    equatorial value (``ice_sheet_insolation_fraction``) makes a land cell
    ice-eligible — the crossing latitude follows obliquity and stellar flux
    (0.50 → ~67° on Earth, ~62° on nacrea whose ε = 14.9° darkens poles).
    This is the classical insolation control on ice-sheet survival
    (Milankovitch).  Annual mean is obtained by averaging the daily-mean
    insolation (Hartmann 2016 eq. 3.7, ``climate_seasonality``) over a
    circular orbit's declination cycle.

Geographic mode split (where the N/S asymmetry comes from):
    Earth's northern polar lands stay tundra while Antarctica carries a
    continental dome because the Arctic Ocean heats its surroundings; the
    asymmetry is geographic, not astronomical.  We reproduce the same
    mechanism with the geodesic distance to the nearest sea: land farther
    than ``ice_maritime_distance_km`` from any ocean builds a full dome;
    nearer in-gate land gets local caps only above a snow line
    (Canadian-Arctic / Svalbard style; Earth: tundra coasts < ~500 km
    from sea, Dome A ~1200 km inland).

Dome profile (perfect-plastic Vialov):
    h(x) = sqrt(2·τ_d·x / (ρ_i·g)),  x = distance from the ice margin.
    With driving stress τ_d ≈ 50–100 kPa (observed ice-sheet range,
    Cuffey & Paterson 2010) this reproduces Earth's polar caps: τ = 50 kPa
    at a 1800 km half-width gives a ~4.4 km dome (Dome A: 4093 m).  The
    world's gravity enters directly — a heavier world carries thinner ice.

Calibration references
----------------------
* Fretwell, P. et al. (2013). "Bedmap2". *The Cryosphere* 7, 375–393 —
  Antarctic grounded-ice mean surface ~2048 m, mean thickness ~2.1 km.
* Cuffey, K.M. & Paterson, W.S.B. (2010). *The Physics of Glaciers*,
  4th ed., ch. 8 — perfect-plastic profiles, driving stress range.
* Hartmann, D.L. (2016). *Global Physical Climatology* eq. 3.7 —
  daily-mean insolation.

Epistemic class: thermal gate + dome profile = approximate derivation;
snow line / cap ceiling / maritime threshold = observational fit
(Earth Arctic-coast analogs).  Known limitation (documented): the gate is
thermal-only — accumulation is assumed sufficient (cold poles accumulate
over Myr even at low precipitation, cf. Antarctica) and ocean-heat
transport enters only through the maritime proxy, so a world with extreme
poleward heat transport could be over-iced; cross-check in the climate
layer (ice cells should stay below freezing annually).
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

if TYPE_CHECKING:
    from .models import CVTMesh, VoronoiCell
    from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

RHO_ICE_KG_M3 = 917.0
SOLAR_CONSTANT_WM2 = 1361.0


def annual_mean_insolation(
    lat_rad: np.ndarray,
    obliquity_deg: float,
    solar_constant: float,
    samples: int = 32,
) -> np.ndarray:
    """Annual-mean TOA insolation (W/m²) per latitude, circular orbit.

    Averages ``daily_mean_insolation`` over ``samples`` declinations
    δ = ε·sin(L), L uniformly in [0, 2π) (zero eccentricity — the annual
    mean's eccentricity correction is second order for the gate).
    """
    from dreamulator.engine.climate_seasonality import daily_mean_insolation

    eps = math.radians(obliquity_deg)
    total = np.zeros_like(lat_rad)
    for k in range(samples):
        decl = eps * math.sin(2.0 * math.pi * (k + 0.5) / samples)
        total += daily_mean_insolation(lat_rad, decl, solar_constant)
    return total / samples


def _adjacency_graph(mesh: CVTMesh) -> tuple[csr_matrix, np.ndarray]:
    """Symmetric adjacency CSR + per-cell mean neighbour distance (km)."""
    rows: list[int] = []
    cols: list[int] = []
    dists: list[float] = []
    radius = 1.0  # unit sphere positions; scaled by config radius at call site
    xyz = mesh.cell_xyz
    seen: set[tuple[int, int]] = set()
    for i, cell in enumerate(mesh.cells):
        xi = xyz[i]
        for j in cell.neighbors:
            if (i, j) in seen:
                continue
            seen.add((i, j))
            seen.add((j, i))
            rows.append(i)
            cols.append(j)
            rows.append(j)
            cols.append(i)
            d = float(np.arccos(np.clip(np.dot(xi, xyz[j]), -1.0, 1.0))) * radius
            dists.append(d)
            dists.append(d)
    n = len(mesh.cells)
    graph = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n)).tocsr()
    edge_dist = coo_matrix((dists, (rows, cols)), shape=(n, n)).tocsr()
    deg = np.asarray(graph.sum(axis=1)).ravel()
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_dist = np.asarray(edge_dist.sum(axis=1)).ravel() / np.maximum(deg, 1.0)
    return graph, mean_dist


def _weighted_graph(mesh: CVTMesh, graph: csr_matrix) -> csr_matrix:
    """Adjacency weighted by unit-sphere geodesic edge lengths (radians)."""
    unit_xyz = mesh.cell_xyz
    coo = graph.tocoo()
    w = np.arccos(np.clip((unit_xyz[coo.row] * unit_xyz[coo.col]).sum(axis=1), -1.0, 1.0))
    return coo_matrix((w, (coo.row, coo.col)), shape=graph.shape).tocsr()


def _distance_to_sea(wgraph: csr_matrix, is_ocean: np.ndarray) -> np.ndarray:
    """Geodesic distance (radians) from each cell to the nearest ocean cell.

    The maritime proxy: Earth's Arctic-coast tundra lands sit within ~500 km
    of the Arctic Ocean, while Dome A is ~1200 km inland — the distance to a
    warm coast, not any smoothed share, is what separates cap country from
    continental-sheet interiors.
    """
    seeds = np.where(is_ocean)[0].astype(np.int64)
    if len(seeds) == 0:
        return np.full(wgraph.shape[0], np.inf)
    return np.asarray(dijkstra(wgraph, directed=False, indices=seeds, min_only=True))


def apply_polar_ice_sheets(mesh: CVTMesh, config: TerrainPipelineConfig) -> dict[str, float]:
    """Add polar ice on top of the calibrated terrain (in-place).

    Idempotent: existing ``ice_thickness_m`` is stripped before the surface
    is rebuilt, so re-running over an already-iced mesh recomputes rather
    than double-counts.  Returns summary stats for logging.
    """
    stats: dict[str, float] = {
        "dome_cells": 0.0,
        "cap_cells": 0.0,
        "dome_peak_m": 0.0,
        "dome_mean_surface_m": 0.0,
    }
    if not config.ice_sheet_enabled:
        return stats

    n = len(mesh.cells)
    radius_km = config.radius_km

    # ---- Bed reconstruction (idempotency) ----
    # getattr guard: stage-cache pickles predate model fields (mesh.pkl from
    # before 2026-09-29 lacks ice_thickness_m on the unpickled cells) — stale
    # cache + model evolution must not crash the phase.
    def _old_ice(c: VoronoiCell) -> float:
        return getattr(c, "ice_thickness_m", None) or 0.0

    bed = np.array([c.elevation - _old_ice(c) for c in mesh.cells], dtype=np.float64)
    old_ice = np.array([_old_ice(c) for c in mesh.cells], dtype=np.float64)
    land = bed > 0.0

    # ---- Thermal gate: annual-mean insolation ----
    solar_constant = (
        SOLAR_CONSTANT_WM2
        * config.stellar_luminosity_sol
        / max(config.orbital_distance_au, 1e-6) ** 2
    )
    lat_rad = np.radians(np.array([c.lat for c in mesh.cells]))
    qbar = annual_mean_insolation(lat_rad, config.axial_tilt_deg, solar_constant)
    qbar_eq = float(qbar[np.argmin(np.abs(lat_rad))])
    cold = qbar < config.ice_sheet_insolation_fraction * qbar_eq
    eligible = land & cold
    if not np.any(eligible):
        for c in mesh.cells:
            c.ice_thickness_m = None
        if old_ice.any():
            for c, b in zip(mesh.cells, bed, strict=True):
                c.elevation = float(b)
        return stats

    # ---- Maritime proxy: distance to the nearest sea (dome/cap split) ----
    graph, _mean_dist = _adjacency_graph(mesh)
    wgraph = _weighted_graph(mesh, graph)
    dist_sea_km = _distance_to_sea(wgraph, (~land).astype(bool)) * radius_km
    dome_zone = eligible & (dist_sea_km > config.ice_maritime_distance_km)
    cap_zone = eligible & ~dome_zone

    ice = np.zeros(n, dtype=np.float64)

    # ---- Dome: perfect-plastic profile from the ice margin ----
    if np.any(dome_zone):
        dome_ids = np.where(dome_zone)[0]
        # Restrict everything to the dome subgraph: components, the ice
        # margin (dome cells adjacent to non-dome or another dome component)
        # and the geodesic distance — ice flows over land, never through sea.
        sub = graph[dome_ids][:, dome_ids].tocoo()
        nsub, sub_labels = connected_components(
            coo_matrix((np.ones(len(sub.row)), (sub.row, sub.col)), shape=(len(dome_ids),) * 2),
            directed=False,
        )
        # Global boundary detection: dome cell i has neighbour j outside i's dome component
        global_coo = graph.tocoo()
        dome_pos = {int(k): p for p, k in enumerate(dome_ids)}
        boundary_sub: set[int] = set()
        for a, b in zip(global_coo.row, global_coo.col, strict=True):
            pa = dome_pos.get(int(a))
            if pa is None:
                continue
            pb = dome_pos.get(int(b))
            if pb is None or sub_labels[pb] != sub_labels[pa]:
                boundary_sub.add(pa)
        if boundary_sub:
            wsub = wgraph[dome_ids][:, dome_ids]
            bnd = np.array(sorted(boundary_sub), dtype=np.int64)
            dist_margin = dijkstra(wsub, directed=False, indices=bnd, min_only=True)
            x_km = np.where(np.isfinite(dist_margin), dist_margin, 0.0) * radius_km
            tau = config.ice_sheet_driving_stress_kpa * 1000.0  # Pa
            coeff = 2.0 * tau / (RHO_ICE_KG_M3 * config.gravity_m_s2)
            ice[dome_ids] = np.sqrt(coeff * np.maximum(x_km, 0.0) * 1000.0)
            stats["dome_cells"] = float(dome_zone.sum())
            stats["dome_peak_m"] = float(ice.max())

    # ---- Maritime caps: snow-line gated, ceiling-clamped ----
    if np.any(cap_zone):
        cap_bed = bed[cap_zone]
        cap_h = np.clip((cap_bed - config.ice_cap_snowline_m) * 0.5, 0.0, config.ice_cap_max_m)
        ice[cap_zone] = cap_h
        stats["cap_cells"] = float((cap_h > 0.0).sum())

    # ---- Write back: surface = bed + ice ----
    dome_mask = dome_zone & (ice > 0.0)
    if dome_mask.any():
        stats["dome_mean_surface_m"] = float((bed[dome_mask] + ice[dome_mask]).mean())
    for i, c in enumerate(mesh.cells):
        if ice[i] > 0.0:
            c.ice_thickness_m = float(ice[i])
            c.elevation = float(bed[i] + ice[i])
        else:
            c.ice_thickness_m = None
            c.elevation = float(bed[i])

    logger.info(
        "  Polar ice: %d dome cells (peak %.0f m, mean surface %.0f m), %d cap cells "
        "(gate q̄/q̄eq < %.2f; S₀=%.0f W/m² = 1361·%.3f/%.3f², tilt %.1f°, "
        "q̄eq=%.0f W/m², maritime >%.0f km)",
        int(stats["dome_cells"]),
        stats["dome_peak_m"],
        stats["dome_mean_surface_m"],
        int(stats["cap_cells"]),
        config.ice_sheet_insolation_fraction,
        solar_constant,
        config.stellar_luminosity_sol,
        config.orbital_distance_au,
        config.axial_tilt_deg,
        qbar_eq,
        config.ice_maritime_distance_km,
    )
    return stats
