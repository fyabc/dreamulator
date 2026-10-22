"""History contract, orogen part: convergent boundary segments and their shortening history.

Design: ``docs/design/proposals/history-contract.md`` §3 (contract) and
``docs/knowledge/geology/orogen_topography.md`` §2 (retained shortening).  For every
convergent boundary segment the contract gives the collision onset age, the
convergence integrated since onset, the post-collision continental subduction time and,
for Andean margins, the upper-plate shortening ratio.  Onset and convergence are derived
from the tectonic evolution's continuous convergent stretch per cell
(``convergent_duration_my`` / ``convergent_run_km``); ``plate_history.yaml`` can override
them per collision.  The lateral escape ratio is not part of the contract: it is derived
here from exit geometry and plate motion (Houseman & England 1993).

The retained shortening of a collision cell is
``(min(L, L_max) − W_m − U·τ_b) × (1 − e) + φ·L_pre`` (``L_max`` = 3000 km, Earth's
largest collision) (the second term is the Andean-type phase before
the collision, ``L_pre`` = cumulative convergence − convergence since onset); of an
Andean cell ``φ·L``.  Pure functions apart from
``load_collision_overrides``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from dreamulator.map.paleo_sutures import polyline_geometry

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.map.models import CVTMesh, TectonicPlate

# Contact cells slower than this are not treated as convergent (cm/yr; boundary
# classifier threshold 0.5, numerical convention).
_MIN_RATE_CM_YR = 0.3
# Crust of each side: continental share of that plate's cells within this radius;
# a 4-ring window reads the transitional crust behind a trench as oceanic
# (numerical convention, checked on Earth: Nazca–South America).
_CRUST_WINDOW_KM = 500.0
# Contact cells of the same plate pair closer than this belong to one segment.
_SEGMENT_LINK_KM = 150.0
# Width of the thinned down-going margin consumed before the collision locks (km).
# Observation fit: Arabian margin ~180 km (McQuarrie & van Hinsbergen 2013);
# passive-margin necking zones are 150–200 km.
MARGIN_CONSUMED_KM = 180.0
# Upper bound on the convergence a collision absorbs after onset (km).  Collision
# resistance decelerates the plates (India–Asia slowed from ~15 to ~5 cm/yr after
# contact) and Earth's largest collision has absorbed ~2500–3000 km since ~50 Ma.  In the
# "specified present" mode continents do not move, so a synthetic boundary can keep
# converging inside a continent for most of the evolution (nacrea: up to ~8000 km).
# Observation fit, calibration domain = Cenozoic collisions.
MAX_POST_COLLISION_CONVERGENCE_KM = 3000.0
# Default post-collision continental subduction time before slab breakoff (My).
# Observation fit: Iran ~10 My; Tibet ~25 My (inverted from volume, Ingalls et al. 2016).
DEFAULT_BREAKOFF_MY = 10.0
# Default Andean upper-plate shortening ratio φ.  Observation fit: on Earth's ocean–continent
# margins (ETOPO bedrock volume over 50 My of Müller 2019 convergence, Cascadia excluded) the
# convergence-weighted ratio is 0.026, median 0.015, central Andes ~0.07.  No kinematic
# criterion tested (upper-plate trenchward velocity, the Lallemand 2008 neutral-arc law,
# slab-edge distance) predicts the per-margin ratio better than this constant
# (docs/design/proposals/orogen-topography.md §4); the central Andes excess needs interface
# friction, which a fictional world cannot derive.
DEFAULT_UPPER_PLATE_RATIO = 0.026
# The boundary reshaping after tectonic evolution (segment shaping, noise warping,
# smoothing) moves the final boundary off the cells that converged during evolution:
# on nacrea the distance from a final contact cell to the nearest evolution-convergent
# cell has median ~100 km and 90th percentile ~400 km.  Each contact cell reads the
# continuous convergent stretch of the nearest evolution-convergent cell within this
# radius (numerical convention, set by the reshaping displacement).
_RUN_TRANSFER_KM = 400.0
# A neighbouring plate counts as an escape exit when it moves away from the orogen
# faster than this (cm/yr; numerical convention).
_ESCAPE_MIN_AWAY_CM_YR = 0.5


@dataclass(frozen=True)
class CollisionOverride:
    """One ``collisions`` or ``andean_margins`` entry of ``plate_history.yaml``."""

    id: str
    kind: str  # "collision" or "andean"
    plates: tuple[str, str] | None = None
    path: np.ndarray | None = None  # (m, 2) [lon, lat] degrees
    width_km: float = 150.0
    onset_age_myr: float | None = None
    breakoff_my: float | None = None
    down_going: str | None = None
    upper_plate_ratio: float | None = None


@dataclass
class OrogenSegment:
    """One convergent boundary segment and its contract quantities."""

    id: str
    kind: str  # "collision" or "andean"
    pro_plate: str  # down-going side
    retro_plate: str  # overriding side
    cell_ids: list[int]
    rate_cm_yr: float  # median present convergence rate
    onset_age_myr: float
    convergence_km: float
    breakoff_my: float
    upper_plate_ratio: float
    # Convergence before the collision (km): the cumulative convergence of the tectonic
    # evolution minus the convergence since onset — the Andean-type subduction phase
    # that preceded the collision (orogen_topography.md §2).
    pre_collision_km: float = 0.0
    sources: dict[str, str] = field(default_factory=dict)  # quantity -> derived/author/default
    # Per contact cell (the segment values above are their medians, kept as summaries):
    # convergence since onset, convergence before the collision, present rate.  A
    # boundary bends and its obliquity changes along strike, so one segment median
    # would give an oblique stretch the convergence of the frontal one.
    cell_convergence_km: dict[int, float] = field(default_factory=dict)
    cell_pre_collision_km: dict[int, float] = field(default_factory=dict)
    cell_rate_cm_yr: dict[int, float] = field(default_factory=dict)


@dataclass
class OrogenContract:
    """Segments plus per-cell escape ratio and retained shortening (contact cells only)."""

    segments: list[OrogenSegment]
    escape: dict[int, float]
    retained_km: dict[int, float]
    warnings: list[str]


def load_collision_overrides(path: Path) -> list[CollisionOverride]:
    """Read ``collisions`` and ``andean_margins`` of a ``plate_history.yaml`` (empty if absent)."""
    import yaml

    if not path.exists():
        return []
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[CollisionOverride] = []
    for kind, key in (("collision", "collisions"), ("andean", "andean_margins")):
        for item in data.get(key) or []:
            plates = item.get("plates")
            if plates is None and item.get("path") is None:
                raise ValueError(f"{key} {item.get('id')}: needs plates or path")

            def num(name: str, entry: dict[str, Any] = item) -> float | None:
                v = entry.get(name)
                return None if v is None else float(v)

            out.append(
                CollisionOverride(
                    id=str(item["id"]),
                    kind=kind,
                    plates=None if plates is None else (str(plates[0]), str(plates[1])),
                    path=None if item.get("path") is None else np.asarray(item["path"], float),
                    width_km=float(item.get("width_km", 150.0)),
                    onset_age_myr=num("onset_age_myr"),
                    breakoff_my=num("breakoff_my"),
                    down_going=item.get("down_going"),
                    upper_plate_ratio=num("upper_plate_ratio"),
                )
            )
    return out


def _union_find_groups(n: int, pairs: np.ndarray) -> list[list[int]]:
    parent = np.arange(n)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i

    for i, j in pairs:
        ri, rj = find(int(i)), find(int(j))
        if ri != rj:
            parent[ri] = rj
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _plate_velocity(plate: TectonicPlate, pos: np.ndarray, radius_cm: float) -> np.ndarray:
    ep = plate.euler_pole
    return np.cross(np.array([ep.x, ep.y, ep.z]), pos) * ep.omega_rad_yr * radius_cm


def contact_polarity(
    mesh: CVTMesh, plates: list[TectonicPlate], radius_km: float
) -> dict[int, tuple[str, str, str]]:
    """Kind and polarity of every convergent contact cell: ``cell -> (kind, down, over)``.

    Contact cells are convergent boundary cells (rate above ``_MIN_RATE_CM_YR``) that touch
    another plate.  Each side's crust is the continental share of that plate within
    ``_CRUST_WINDOW_KM``: both continental → ``collision`` (the smaller plate goes down),
    one → ``andean`` (the oceanic side goes down), none → ``ocean`` (the faster plate of
    the pair goes down, mean speed over the pair's ocean contact cells — the same rule as
    the trench-arc shaping of the tectonic evolution).
    """
    cells = mesh.cells
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    plate_of = np.array([c.plate_id or "" for c in cells])
    cont = np.array([c.crust_type == "continental" for c in cells])
    size = {p.id: len(p.cell_ids) for p in plates}
    by_id = {p.id: p for p in plates}
    tree = cKDTree(xyz)
    radius_cm = radius_km * 1.0e5

    out: dict[int, tuple[str, str, str]] = {}
    ocean_pairs: dict[tuple[str, str], list[float]] = {}  # (a, b), a < b -> |v_a| − |v_b|
    ocean_cells: list[tuple[int, str, str]] = []
    for i, c in enumerate(cells):
        if c.boundary_type != "convergent" or c.convergence_rate_cm_yr <= _MIN_RATE_CM_YR:
            continue
        others = [plate_of[j] for j in c.neighbors if plate_of[j] != plate_of[i]]
        if not others:
            continue
        # ties go to the smallest id: iterating a set of strings follows the per-process
        # hash seed, which made the contract differ between runs
        p, q = plate_of[i], max(sorted(set(others)), key=others.count)
        win = np.array(tree.query_ball_point(xyz[i], _CRUST_WINDOW_KM / radius_km))
        ccp = float(cont[win][plate_of[win] == p].mean()) if np.any(plate_of[win] == p) else 0.0
        ccq = float(cont[win][plate_of[win] == q].mean()) if np.any(plate_of[win] == q) else 0.0
        if ccp >= 0.5 and ccq >= 0.5:
            pro, retro = (p, q) if size.get(p, 0) < size.get(q, 0) else (q, p)
            out[i] = ("collision", pro, retro)
        elif ccp >= 0.5 or ccq >= 0.5:
            out[i] = ("andean", q, p) if ccp >= 0.5 else ("andean", p, q)
        elif p in by_id and q in by_id:
            a, b = sorted((p, q))
            va = float(np.linalg.norm(_plate_velocity(by_id[a], xyz[i], radius_cm)))
            vb = float(np.linalg.norm(_plate_velocity(by_id[b], xyz[i], radius_cm)))
            ocean_pairs.setdefault((a, b), []).append(va - vb)
            ocean_cells.append((i, a, b))
    for i, a, b in ocean_cells:
        down, over = (a, b) if np.mean(ocean_pairs[(a, b)]) > 0.0 else (b, a)
        out[i] = ("ocean", down, over)
    return out


def convergent_segments(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    radius_km: float,
    overrides: list[CollisionOverride] | None = None,
) -> tuple[list[OrogenSegment], list[str]]:
    """Group contact cells of convergent boundaries into segments with contract quantities.

    Contact cells and their polarity come from ``contact_polarity``; ocean–ocean contacts
    carry no orogen and are left out (their trenches are ``trench_flexure``'s).  Onset
    and convergence are the segment medians of the evolution's
    continuous convergent stretch, each contact cell reading the nearest
    evolution-convergent cell within ``_RUN_TRANSFER_KM`` (the post-evolution boundary
    reshaping moves boundaries); author overrides replace them (§3.4).
    """
    warnings: list[str] = []
    cells = mesh.cells
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    polarity = contact_polarity(mesh, plates, radius_km)
    pair_of = {k: v for k, v in polarity.items() if v[0] != "ocean"}

    # continuous convergent stretch carried over from the evolution's boundary cells
    run_dur = np.array([c.convergent_duration_my for c in cells])
    run_km = np.array([c.convergent_run_km for c in cells])
    total_km = np.array([c.cumulative_convergence_km for c in cells])
    had = np.flatnonzero(run_dur > 0.0)
    contact_dur: dict[int, float] = {}
    contact_km: dict[int, float] = {}
    contact_total: dict[int, float] = {}
    if had.size:
        run_tree = cKDTree(xyz[had])
        keys = np.array(sorted(pair_of))
        if keys.size:
            dist, idx = run_tree.query(xyz[keys], distance_upper_bound=_RUN_TRANSFER_KM / radius_km)
            for k, d, j in zip(keys, dist, idx, strict=True):
                found = np.isfinite(d)
                contact_dur[int(k)] = float(run_dur[had[j]]) if found else 0.0
                contact_km[int(k)] = float(run_km[had[j]]) if found else 0.0
                contact_total[int(k)] = float(total_km[had[j]]) if found else 0.0

    segments: list[OrogenSegment] = []
    by_pair: dict[tuple[str, str, str], list[int]] = {}
    for i, key in pair_of.items():
        by_pair.setdefault(key, []).append(i)
    for (kind, pro, retro), members in sorted(by_pair.items()):
        mem = np.array(sorted(members))
        sub = cKDTree(xyz[mem])
        pairs = np.array(sorted(sub.query_pairs(_SEGMENT_LINK_KM / radius_km)), dtype=np.int64)
        for group in _union_find_groups(len(mem), pairs.reshape(-1, 2)):
            ids = [int(mem[g]) for g in group]
            dur = np.array([contact_dur.get(k, 0.0) for k in ids])
            run = np.array([contact_km.get(k, 0.0) for k in ids])
            rate = float(np.median([cells[k].convergence_rate_cm_yr for k in ids]))
            total = np.array([contact_total.get(k, 0.0) for k in ids])
            segments.append(
                OrogenSegment(
                    id=f"seg_{len(segments):03d}",
                    kind=kind,
                    pro_plate=pro,
                    retro_plate=retro,
                    cell_ids=ids,
                    rate_cm_yr=rate,
                    onset_age_myr=float(np.median(dur)),
                    convergence_km=float(np.median(run)),
                    breakoff_my=DEFAULT_BREAKOFF_MY,
                    upper_plate_ratio=DEFAULT_UPPER_PLATE_RATIO,
                    pre_collision_km=float(max(0.0, np.median(total) - np.median(run))),
                    cell_convergence_km={k: float(r) for k, r in zip(ids, run, strict=True)},
                    cell_pre_collision_km={
                        k: float(max(0.0, t - r)) for k, t, r in zip(ids, total, run, strict=True)
                    },
                    cell_rate_cm_yr={k: float(cells[k].convergence_rate_cm_yr) for k in ids},
                    sources={
                        "onset_age_myr": "derived",
                        "convergence_km": "derived",
                        "breakoff_my": "default",
                        "upper_plate_ratio": "default",
                    },
                )
            )

    for ov in overrides or []:
        claimed = [s for s in segments if s.kind == ov.kind and _claims(ov, s, xyz, radius_km)]
        if not claimed:
            warnings.append(f"plate_history {ov.id}: claims no {ov.kind} segment")
        for s in claimed:
            _apply_override(ov, s, warnings)
    return segments, warnings


def _claims(ov: CollisionOverride, seg: OrogenSegment, xyz: np.ndarray, radius_km: float) -> bool:
    if ov.plates is not None:
        return {seg.pro_plate, seg.retro_plate} == set(ov.plates)
    assert ov.path is not None
    d, _ = polyline_geometry(xyz[seg.cell_ids], ov.path)
    return bool(np.mean(d * radius_km <= 2.0 * ov.width_km) >= 0.5)


def _apply_override(ov: CollisionOverride, seg: OrogenSegment, warnings: list[str]) -> None:
    if ov.down_going is not None:
        if ov.down_going not in (seg.pro_plate, seg.retro_plate):
            warnings.append(f"plate_history {ov.id}: down_going {ov.down_going} not in {seg.id}")
        elif ov.down_going != seg.pro_plate:
            seg.pro_plate, seg.retro_plate = seg.retro_plate, seg.pro_plate
    if ov.onset_age_myr is not None:
        seg.onset_age_myr = ov.onset_age_myr
        seg.convergence_km = seg.rate_cm_yr * ov.onset_age_myr * 10.0  # cm/yr × My → km
        seg.cell_convergence_km = {
            k: r * ov.onset_age_myr * 10.0 for k, r in seg.cell_rate_cm_yr.items()
        }
        seg.sources["onset_age_myr"] = "author"
        seg.sources["convergence_km"] = "author onset × present rate"
    if ov.breakoff_my is not None:
        seg.breakoff_my = ov.breakoff_my
        seg.sources["breakoff_my"] = "author"
    if ov.upper_plate_ratio is not None:
        seg.upper_plate_ratio = ov.upper_plate_ratio
        seg.sources["upper_plate_ratio"] = "author"


def escape_ratios(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    segments: list[OrogenSegment],
    radius_km: float,
) -> dict[int, float]:
    """Lateral escape ratio per collision contact cell (orogen_topography.md §2).

    Collision cells within ``_SEGMENT_LINK_KM`` form one orogen front of along-strike
    length W (largest geodesic distance between its cells).  Exits are edge cells of the
    overriding plate within 2W of the front: trenches facing subducting oceanic crust,
    whose side boundary moves out at a quarter of the indentation rate U (Houseman &
    England 1993), and non-convergent boundaries with a plate moving away from the
    orogen, at that outward speed (not less than U/4).  A cell's ratio is
    Σ u_out · spacing · exp(−D/W) / (U · W) over exits, D its great-circle distance to
    the exit, capped at 1.
    """
    cells = mesh.cells
    n = len(cells)
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    plate_of = np.array([c.plate_id or "" for c in cells])
    cont = np.array([c.crust_type == "continental" for c in cells])
    by_id = {p.id: p for p in plates}
    radius_cm = radius_km * 1e5
    spacing = float(np.sqrt(4.0 * np.pi * radius_km**2 / n))

    coll = [s for s in segments if s.kind == "collision"]
    if not coll:
        return {}
    cell_seg: dict[int, OrogenSegment] = {k: s for s in coll for k in s.cell_ids}
    members_all = np.array(sorted(cell_seg))
    pairs = np.array(
        sorted(cKDTree(xyz[members_all]).query_pairs(_SEGMENT_LINK_KM / radius_km)),
        dtype=np.int64,
    )
    rows = np.repeat(np.arange(n), [len(c.neighbors) for c in cells])
    cols = np.array([j for c in cells for j in c.neighbors], dtype=np.int64)
    w = np.arccos(np.clip(np.einsum("ij,ij->i", xyz[rows], xyz[cols]), -1.0, 1.0)) * radius_km
    graph = csr_matrix((w, (rows, cols)), shape=(n, n))
    edge = np.array(
        [any(plate_of[j] != plate_of[i] for j in c.neighbors) for i, c in enumerate(cells)]
    )

    out: dict[int, float] = {}
    for group in _union_find_groups(len(members_all), pairs.reshape(-1, 2)):
        front = members_all[group]
        fp = xyz[front]
        w_ind = max(float(np.arccos(np.clip(fp @ fp.T, -1.0, 1.0)).max()) * radius_km, spacing)
        retros = [cell_seg[int(k)].retro_plate for k in front]
        retro = max(sorted(set(retros)), key=retros.count)  # deterministic ties
        pros = {cell_seg[int(k)].pro_plate for k in front}
        u = float(np.median([cells[int(k)].convergence_rate_cm_yr for k in front]))
        if u <= 0.0 or retro not in by_id:
            continue
        dist, _, nearest = dijkstra(
            graph, indices=front, min_only=True, limit=2.0 * w_ind, return_predecessors=True
        )
        exits: list[tuple[int, float]] = []
        for c in np.flatnonzero(edge & (plate_of == retro) & np.isfinite(dist)):
            u_out = 0.0
            for j in cells[c].neighbors:
                q = plate_of[j]
                if q == retro or q in pros or q not in by_id:
                    continue
                if cells[c].boundary_type == "convergent":
                    if not cont[j]:
                        u_out = max(u_out, u / 4.0)  # trench: lithostatic side boundary
                    continue  # a collision front elsewhere is not an exit
                v_rel = _plate_velocity(by_id[q], xyz[c], radius_cm) - _plate_velocity(
                    by_id[retro], xyz[c], radius_cm
                )
                out_dir = xyz[c] - xyz[nearest[c]]
                out_dir -= out_dir.dot(xyz[c]) * xyz[c]
                norm = float(np.linalg.norm(out_dir))
                if norm > 1e-12:
                    away = float(v_rel @ (out_dir / norm))
                    if away > _ESCAPE_MIN_AWAY_CM_YR:
                        u_out = max(u_out, u / 4.0, away)
            if u_out > 0.0:
                exits.append((int(c), u_out))
        if not exits:
            for k in front:
                out[int(k)] = 0.0
            continue
        ex = np.array([c for c, _ in exits])
        uo = np.array([v for _, v in exits])
        for k in front:
            d = np.arccos(np.clip(xyz[ex] @ xyz[int(k)], -1.0, 1.0)) * radius_km
            out[int(k)] = min(1.0, float((uo * np.exp(-d / w_ind)).sum()) * spacing / (u * w_ind))
    return out


def save_orogen_contract(path: Path, contract: OrogenContract) -> None:
    """Write the contract as JSON: segments with their quantities and sources, warnings.

    Per-cell escape and retained shortening are summarised per segment (median, range);
    the cell arrays are recomputed at build time rather than stored.
    """
    import json

    rows = []
    for s in contract.segments:
        esc = [contract.escape.get(k, 0.0) for k in s.cell_ids]
        ret = [contract.retained_km.get(k, 0.0) for k in s.cell_ids]
        rows.append(
            {
                "id": s.id,
                "kind": s.kind,
                "pro_plate": s.pro_plate,
                "retro_plate": s.retro_plate,
                "cells": len(s.cell_ids),
                "rate_cm_yr": round(s.rate_cm_yr, 2),
                "onset_age_myr": round(s.onset_age_myr, 1),
                "convergence_km": round(s.convergence_km, 0),
                "breakoff_my": s.breakoff_my,
                "upper_plate_ratio": s.upper_plate_ratio,
                "escape_median": round(float(np.median(esc)), 3) if s.kind == "collision" else None,
                "pre_collision_km": round(s.pre_collision_km, 0),
                "retained_km_median": round(float(np.median(ret)), 0),
                "retained_km_max": round(float(np.max(ret)), 0),
                "sources": s.sources,
            }
        )
    payload = {"segments": rows, "warnings": contract.warnings}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def build_orogen_contract(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    radius_km: float,
    overrides: list[CollisionOverride] | None = None,
    *,
    max_onset_myr: float | None = None,
) -> OrogenContract:
    """Segments, escape ratios and the retained shortening of every contact cell.

    ``max_onset_myr`` (the tectonic evolution length) bounds author onset ages: an
    onset older than the history the world has is flagged (§3.5).
    """
    segments, warnings = convergent_segments(mesh, plates, radius_km, overrides)
    escape = escape_ratios(mesh, plates, segments, radius_km)
    retained: dict[int, float] = {}
    n_zero = 0
    capped = 0
    for s in segments:
        if max_onset_myr is not None and s.onset_age_myr > max_onset_myr:
            warnings.append(
                f"{s.id}: onset {s.onset_age_myr:.0f} Myr older than the tectonic history "
                f"({max_onset_myr:.0f} Myr)"
            )
        young = 0
        for k in s.cell_ids:
            conv = s.cell_convergence_km.get(k, s.convergence_km)
            if s.kind == "collision" and conv > MAX_POST_COLLISION_CONVERGENCE_KM:
                conv = MAX_POST_COLLISION_CONVERGENCE_KM
                capped += 1
            if s.kind == "andean":
                retained[k] = s.upper_plate_ratio * conv
                continue
            rate = s.cell_rate_cm_yr.get(k, s.rate_cm_yr)
            entering = conv - MARGIN_CONSUMED_KM - rate * s.breakoff_my * 10.0
            retained[k] = max(0.0, entering) * (1.0 - escape.get(k, 0.0))
            if retained[k] == 0.0:
                young += 1
            # the margin was Andean-type before the collision: its upper-plate shortening
            # stays in the orogen (orogen_topography.md §2)
            retained[k] += s.upper_plate_ratio * s.cell_pre_collision_km.get(k, s.pre_collision_km)
        if s.kind == "collision" and young == len(s.cell_ids):
            n_zero += 1
    if capped:
        warnings.append(
            f"{capped} collision contact cell(s) capped at "
            f"{MAX_POST_COLLISION_CONVERGENCE_KM:.0f} km of post-collision convergence"
        )
    if n_zero:
        warnings.append(
            f"{n_zero} collision segment(s) too young to thicken since onset (margin and "
            "pre-breakoff subduction exceed the convergence); only their pre-collision "
            "Andean-type thickening remains"
        )
    return OrogenContract(segments=segments, escape=escape, retained_km=retained, warnings=warnings)
