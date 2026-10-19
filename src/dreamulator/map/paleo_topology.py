"""Explicit plate-boundary graph for the backward walk (plate topology layer, T1).

Design: ``docs/design/proposals/geological-timeline.md`` appendix A.  Plates are not whatever
cells their crust parcels happen to cover; they are closed by an explicit graph
of boundary segments on the sphere:

* **nodes** are triple junctions;
* **segments** are polylines between two nodes (or closed loops without a node),
  each with a left and a right plate and a type (ridge, trench, transform,
  diffuse continental boundary);
* a plate is the region bounded by the segments that carry it.

The geometry is continuous (unit vectors on the sphere).  The mesh is used only
to extract the starting graph from present plate labels and to rasterize the
graph back to cell labels.

Extraction uses the Voronoi–Delaunay duality: the circumcentres of the mesh's
Delaunay triangles are the Voronoi vertices, a Voronoi edge between cells of two
plates is a piece of plate boundary, and a triangle whose three cells belong to
three plates is a triple junction.

Each step moves every segment with its own kinematic rule — a ridge with the
mean rotation of its two plates (half-stage rotation, symmetric spreading), a
trench with its overriding plate, a transform or diffuse boundary with the mean
— and then puts every node at the mean of the segment ends that meet there
(McKenzie & Morgan 1969 treat junction motion as set jointly by its three
boundaries).  Pure functions on numpy arrays: no IO, no RNG.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

from dreamulator.map.paleo_kinematics import MIN_MOTION_FRAC

if TYPE_CHECKING:
    from dreamulator.map.paleo_kinematics import PlateKinematics

_CM_PER_KM = 1.0e5

RIDGE = "ridge"
TRENCH = "trench"
TRANSFORM = "transform"
DIFFUSE = "diffuse"


@dataclass
class Segment:
    """A boundary polyline between two plates.

    Attributes:
        points: (m, 3) unit vectors, first and last at the nodes (equal for a loop).
        start, end: node indices (−1 for a closed loop without a node).
        left, right: plate indices on the left and right when walking start → end
            (left is the side of q × t for outward normal q and tangent t).
        kind: ridge, trench, transform or diffuse.
        over: overriding plate of a trench (−1 otherwise).
    """

    points: np.ndarray
    start: int
    end: int
    left: int
    right: int
    kind: str = TRANSFORM
    over: int = -1


@dataclass
class Topology:
    """Nodes and segments of the plate-boundary graph."""

    nodes: np.ndarray  # (K, 3)
    segments: list[Segment] = field(default_factory=list)

    def node_segments(self) -> list[list[tuple[int, bool]]]:
        """For each node, the (segment, at_start) ends that meet there."""
        out: list[list[tuple[int, bool]]] = [[] for _ in range(len(self.nodes))]
        for s, seg in enumerate(self.segments):
            if seg.start >= 0:
                out[seg.start].append((s, True))
            if seg.end >= 0:
                out[seg.end].append((s, False))
        return out


def _normalize(v: np.ndarray) -> np.ndarray:
    out: np.ndarray = v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-15)
    return out


def delaunay(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Delaunay triangles of points on the unit sphere and their circumcentres.

    On a sphere the Delaunay triangulation is the convex hull; the outward unit
    normal of a facet is its circumcentre, i.e. a Voronoi vertex.
    """
    tri = ConvexHull(xyz).simplices
    a, b, c = xyz[tri[:, 0]], xyz[tri[:, 1]], xyz[tri[:, 2]]
    n = np.cross(b - a, c - a)
    flip = np.einsum("ij,ij->i", n, a) < 0
    n[flip] *= -1.0
    tri[flip] = tri[flip][:, [0, 2, 1]]
    return tri, _normalize(n)


def extract(xyz: np.ndarray, plate: np.ndarray) -> Topology:
    """Boundary graph of a labelled mesh (cells at ``xyz`` with labels ``plate``).

    Voronoi edges between cells of different plates are chained between triple
    junctions into segments; a boundary with no junction becomes a closed loop.
    """
    tri, centre = delaunay(xyz)
    t_count = len(tri)
    # edge (sorted cell pair) -> the two triangles sharing it
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    owner = np.tile(np.arange(t_count), 3)
    e_sorted = np.sort(e, axis=1)
    key = e_sorted[:, 0].astype(np.int64) * len(xyz) + e_sorted[:, 1]
    order = np.argsort(key, kind="stable")
    key, owner, e_sorted = key[order], owner[order], e_sorted[order]
    first = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    t1, t2 = owner[first], owner[first + 1]
    ci, cj = e_sorted[first, 0], e_sorted[first, 1]
    bnd = plate[ci] != plate[cj]
    t1, t2, ci, cj = t1[bnd], t2[bnd], ci[bnd], cj[bnd]

    # boundary adjacency of triangle vertices: each boundary Voronoi edge links t1-t2
    adj: dict[int, list[tuple[int, int, int]]] = {}
    for a, b, i, j in zip(t1.tolist(), t2.tolist(), ci.tolist(), cj.tolist(), strict=True):
        adj.setdefault(a, []).append((b, i, j))
        adj.setdefault(b, []).append((a, i, j))
    junction = sorted(v for v, lst in adj.items() if len(lst) >= 3)
    node_of = {v: k for k, v in enumerate(junction)}
    used: set[tuple[int, int]] = set()
    topo = Topology(nodes=centre[junction] if junction else np.zeros((0, 3)))

    def walk(start: int, first_step: tuple[int, int, int]) -> None:
        path = [start]
        prev, (cur, i, j) = start, first_step
        used.add((min(prev, cur), max(prev, cur)))
        pair = (plate[i], plate[j])
        path.append(cur)
        while cur not in node_of and cur != start:
            nxt = [s for s in adj[cur] if (min(cur, s[0]), max(cur, s[0])) not in used]
            if not nxt:
                break
            prev, (cur, _, _) = cur, nxt[0]
            used.add((min(prev, cur), max(prev, cur)))
            path.append(cur)
        pts = centre[path]
        # left plate: the cell of the first edge on the left of the first step
        m = _normalize(pts[0] + pts[1])
        left_vec = np.cross(m, pts[1] - pts[0])
        i_left = left_vec @ (xyz[i] - m) > 0
        left, right = (pair[0], pair[1]) if i_left else (pair[1], pair[0])
        s_node = node_of.get(path[0], -1)
        e_node = node_of.get(path[-1], -1)
        topo.segments.append(Segment(pts, s_node, e_node, int(left), int(right)))

    for v in junction:
        for step in adj[v]:
            if (min(v, step[0]), max(v, step[0])) not in used:
                walk(v, step)
    for v, lst in adj.items():  # loops without junctions
        for step in lst:
            if (min(v, step[0]), max(v, step[0])) not in used:
                walk(v, step)
    return topo


def clean_labels(kin: PlateKinematics, label: np.ndarray) -> np.ndarray:
    """Absorb plate enclaves before extraction (terrain engine's rule).

    As ``tectonic_simulator._merge_plate_enclaves``: each plate keeps its largest
    connected piece; other pieces smaller than ``max(50, 0.3 %)`` cells take the
    most common neighbouring plate.  Repeated until stable.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    lab = label.copy()
    min_keep = max(50, int(0.003 * kin.n))
    for _ in range(10):
        same = lab[rows] == lab[cols]
        g = csr_matrix((np.ones(int(same.sum())), (rows[same], cols[same])), shape=(kin.n, kin.n))
        _, comp = connected_components(g, directed=False)
        size = np.bincount(comp)
        comp_plate = np.zeros(size.size, dtype=lab.dtype)
        comp_plate[comp] = lab
        largest = np.zeros(size.size, dtype=bool)
        for q in np.unique(lab):
            ids = np.flatnonzero(comp_plate == q)
            largest[ids[np.argmax(size[ids])]] = True
        enclave = ~largest & (size < min_keep)
        if not enclave.any():
            break
        border = ~same & enclave[comp[rows]]
        b_comp, b_nb = comp[rows[border]], lab[cols[border]]
        for c in np.unique(b_comp):
            vals, counts = np.unique(b_nb[b_comp == c], return_counts=True)
            lab[comp == c] = vals[np.argmax(counts)]
    return lab


def resample(points: np.ndarray, spacing: float) -> np.ndarray:
    """Polyline resampled to roughly uniform ``spacing`` (radians), ends kept."""
    if len(points) < 2:
        return points
    seg = np.arccos(np.clip(np.einsum("ij,ij->i", points[:-1], points[1:]), -1.0, 1.0))
    s = np.r_[0.0, np.cumsum(seg)]
    n = max(2, int(np.ceil(s[-1] / spacing)) + 1)
    targets = np.linspace(0.0, s[-1], n)
    k = np.clip(np.searchsorted(s, targets, side="right") - 1, 0, len(points) - 2)
    frac = np.where(seg[k] > 0, (targets - s[k]) / np.maximum(seg[k], 1e-15), 0.0)
    out = _normalize(points[k] * (1.0 - frac)[:, None] + points[k + 1] * frac[:, None])
    out[0], out[-1] = points[0], points[-1]
    return out


def smooth(points: np.ndarray, iterations: int, weight: float = 0.5) -> np.ndarray:
    """Laplacian smoothing of the interior points (ends fixed; loops wrap)."""
    p = points.copy()
    loop = len(p) > 2 and np.allclose(p[0], p[-1])
    for _ in range(iterations):
        if loop:
            core = p[:-1]
            avg = 0.5 * (np.roll(core, 1, axis=0) + np.roll(core, -1, axis=0))
            core = _normalize((1.0 - weight) * core + weight * avg)
            p = np.vstack([core, core[:1]])
        elif len(p) > 2:
            avg = 0.5 * (p[:-2] + p[2:])
            p[1:-1] = _normalize((1.0 - weight) * p[1:-1] + weight * avg)
    return p


def prepare(topo: Topology, spacing_rad: float, iterations: int = 8) -> Topology:
    """Resample every segment to ``spacing_rad`` and smooth away the mesh staircase."""
    segs = []
    for seg in topo.segments:
        pts = resample(seg.points, spacing_rad)
        pts = resample(smooth(pts, iterations), spacing_rad)
        segs.append(replace(seg, points=pts))
    return Topology(nodes=topo.nodes.copy(), segments=segs)


def tangents(points: np.ndarray) -> np.ndarray:
    """Unit tangents of a polyline (central differences, one-sided at the ends)."""
    t = np.gradient(points, axis=0)
    t -= np.einsum("ij,ij->i", t, points)[:, None] * points
    return _normalize(t)


def classify(
    topo: Topology,
    omega: np.ndarray,
    radius_km: float,
    side_info: tuple[np.ndarray, np.ndarray, np.ndarray, cKDTree] | None = None,
    threshold_frac: float = MIN_MOTION_FRAC,
) -> None:
    """Set each segment's type from the relative motion of its plates (in place).

    The forward opening rate is the velocity of the left plate relative to the
    right projected on the left normal.  Ridge: median opening above the
    threshold and larger than the shear; trench: median closing above it;
    otherwise transform.  The threshold is ``threshold_frac`` of the median
    relative speed over all boundary points, so the types depend on the
    motion's geometry, not its overall speed.  A trench's overriding plate is the side with
    continental crust, else the side with younger ocean (older ocean is denser
    and subducts), read from ``side_info`` = (cell_xyz, continental, age, tree).
    """
    rel = [np.cross(omega[s.left] - omega[s.right], s.points) for s in topo.segments]
    if not rel:
        return
    scale = float(np.median(np.linalg.norm(np.vstack(rel), axis=1))) * radius_km * _CM_PER_KM
    threshold = threshold_frac * scale
    for seg, v in zip(topo.segments, rel, strict=True):
        q = seg.points
        t = tangents(q)
        left_n = np.cross(q, t)
        v = v * radius_km * _CM_PER_KM
        opening = float(np.median(np.einsum("ij,ij->i", v, left_n)))
        shear = float(np.median(np.abs(np.einsum("ij,ij->i", v, t))))
        if opening > threshold and opening >= 0.5 * shear:
            seg.kind, seg.over = RIDGE, -1
        elif opening < -threshold and -opening >= 0.5 * shear:
            seg.kind = TRENCH
            seg.over = _overriding(seg, left_n, side_info)
        else:
            seg.kind, seg.over = TRANSFORM, -1


def _overriding(
    seg: Segment,
    left_n: np.ndarray,
    side_info: tuple[np.ndarray, np.ndarray, np.ndarray, cKDTree] | None,
) -> int:
    if side_info is None:
        return seg.left
    _, continental, age, tree = side_info
    probe = 0.01  # ~60 km on Earth-sized planets
    scores = []
    for sign in (1.0, -1.0):
        x = _normalize(seg.points + sign * probe * left_n)
        _, idx = tree.query(x)
        cont = float(np.mean(continental[idx]))
        a = age[idx]
        young = -float(np.nanmedian(a)) if np.isfinite(a).any() else 0.0
        scores.append((cont, young))
    return seg.left if scores[0] >= scores[1] else seg.right


def classify_from_cells(
    topo: Topology,
    xyz: np.ndarray,
    boundary_type: np.ndarray,
    side_info: tuple[np.ndarray, np.ndarray, np.ndarray, cKDTree],
    fallback: tuple[np.ndarray, float] | None = None,
) -> int:
    """Set segment types from the terrain engine's per-cell boundary types.

    ``boundary_type`` holds "convergent", "divergent", "transform" or "" per
    cell.  A segment takes the most common non-empty type of the cells nearest
    its points (convergent → trench, divergent → ridge, transform → transform);
    a trench's overriding side follows the same rule as ``classify``.  Segments
    the engine never classified (boundaries that only the reconstruction model
    created, e.g. around a reassigned continental block) fall back to
    ``classify`` with ``fallback`` = (omega, radius_km).  Returns the number of
    segments typed from the engine.
    """
    tree = side_info[3]
    mapped = 0
    rest: list[Segment] = []
    for seg in topo.segments:
        _, idx = tree.query(seg.points)
        kinds = boundary_type[idx]
        kinds = kinds[kinds != ""]
        if kinds.size == 0:
            rest.append(seg)
            continue
        vals, counts = np.unique(kinds, return_counts=True)
        top = str(vals[np.argmax(counts)])
        if top == "divergent":
            seg.kind, seg.over = RIDGE, -1
        elif top == "convergent":
            seg.kind = TRENCH
            seg.over = _overriding(seg, np.cross(seg.points, tangents(seg.points)), side_info)
        else:
            seg.kind, seg.over = TRANSFORM, -1
        mapped += 1
    if rest and fallback is not None:
        classify(Topology(nodes=topo.nodes, segments=rest), fallback[0], fallback[1], side_info)
    return mapped


def segment_rotation(seg: Segment, omega: np.ndarray) -> np.ndarray:
    """Rotation vector that carries a segment: ridge/transform/diffuse use the
    mean of the two plates (half-stage), a trench uses its overriding plate."""
    if seg.kind == TRENCH and seg.over >= 0:
        w: np.ndarray = omega[seg.over]
        return w
    mean: np.ndarray = 0.5 * (omega[seg.left] + omega[seg.right])
    return mean


def point_rotations(
    seg: Segment,
    omega: np.ndarray,
    continents: tuple[np.ndarray, np.ndarray, cKDTree] | None,
    probe_rad: float,
) -> np.ndarray:
    """(m, 3) rotation vector carrying a segment: one rotation for the whole segment.

    Continental lithosphere does not subduct, so a boundary with continent along
    most of one side is attached to that continent and moves with its plate
    (active margins, continental transforms); with continent along most of both
    sides it moves with the mean.  Otherwise the segment follows its type rule
    (``segment_rotation``); a ridge, oceanic on both flanks by definition, always
    does.  Choosing per point instead lets parts of one segment ride different
    plates, which shears it into folds within a few Myr at Nacrea's plate speeds.
    ``continents`` = (positions, plates, tree) of the continental crust now.
    """
    w = segment_rotation(seg, omega)
    if continents is not None and seg.kind != RIDGE:
        _, cplate, tree = continents
        left_n = np.cross(seg.points, tangents(seg.points))
        share = []
        for sign, side_plate in ((1.0, seg.left), (-1.0, seg.right)):
            x = _normalize(seg.points + sign * probe_rad * left_n)
            d, idx = tree.query(x)
            share.append(float(np.mean((d < probe_rad) & (cplate[idx] == side_plate))))
        if share[0] > 0.5 and share[1] > 0.5:
            w = 0.5 * (omega[seg.left] + omega[seg.right])
        elif share[0] > 0.5:
            w = omega[seg.left]
        elif share[1] > 0.5:
            w = omega[seg.right]
    out: np.ndarray = np.broadcast_to(w, seg.points.shape).copy()
    return out


def _smooth_series(x: np.ndarray, window: int) -> np.ndarray:
    """Moving average with edge padding (window in points, odd)."""
    if window <= 1 or len(x) < 3:
        return x
    k = np.ones(window) / window
    pad = window // 2
    out: np.ndarray = np.convolve(np.pad(x, pad, mode="edge"), k, mode="valid")
    return out


def junction_velocity(node: np.ndarray, normals: np.ndarray, velocities: np.ndarray) -> np.ndarray:
    """Velocity of a triple junction from the segments meeting there.

    Velocity-triangle construction (McKenzie & Morgan 1969): the junction may
    slide freely along each boundary, but its velocity component normal to each
    boundary must equal that boundary's normal velocity.  Three boundaries give
    three equations for the two tangent-plane components, solved by least
    squares.  ``normals`` are the boundaries' unit normals at the junction and
    ``velocities`` the boundaries' own velocities there (3-vectors).
    """
    e1 = np.cross(node, [0.0, 1.0, 0.0] if abs(node[1]) < 0.9 else [1.0, 0.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(node, e1)
    a = np.column_stack([normals @ e1, normals @ e2])
    b = np.einsum("ij,ij->i", velocities, normals)
    sol = np.linalg.lstsq(a, b, rcond=None)[0]
    v: np.ndarray = sol[0] * e1 + sol[1] * e2
    return v


def _rotate_points(p: np.ndarray, w: np.ndarray, t_yr: float) -> np.ndarray:
    """Rotate each point by its own rotation vector ``w`` (rad/yr) over ``t_yr``."""
    rate = np.linalg.norm(w, axis=1)
    axis = w / np.maximum(rate, 1e-30)[:, None]
    theta = rate * t_yr
    c, s = np.cos(theta)[:, None], np.sin(theta)[:, None]
    moved = (
        p * c + np.cross(axis, p) * s + axis * np.einsum("ij,ij->i", axis, p)[:, None] * (1.0 - c)
    )
    return _normalize(moved)


def attach_end(points: np.ndarray, node: np.ndarray, *, at_start: bool) -> np.ndarray:
    """Join a segment end to its (moved) junction without leaving an overshoot.

    The junction slides along the segment: if it slid inward, the stretch beyond
    it is cut off; if outward, the segment is extended to it.  The cut is at the
    segment point nearest the junction within the segment's first (or last)
    half.
    """
    p = points if at_start else points[::-1]
    half = max(2, len(p) // 2)
    k = int(np.argmax(p[:half] @ node))
    out = np.vstack([node[None, :], p[k + 1 :]]) if k + 1 < len(p) else np.vstack([node, p[-1]])
    result: np.ndarray = out if at_start else out[::-1]
    return result


def _end_ray(points: np.ndarray, at_start: bool, frac: float, extend_rad: float) -> np.ndarray:
    """The end portion of a segment (``frac`` of its points, at least 3) seen from
    the junction end outward, extended beyond the end along its tangent."""
    p = points if at_start else points[::-1]
    m = max(3, int(len(p) * frac))
    part = p[:m]
    tan = _normalize(part[0] - part[1] + 1e-15)
    ext = _normalize(part[0] + tan * extend_rad)
    return np.vstack([ext[None, :], part])


def _first_crossing(a: np.ndarray, b: np.ndarray, centre: np.ndarray) -> np.ndarray | None:
    """First intersection of polylines ``a`` and ``b`` (gnomonic about ``centre``)."""
    e1 = np.cross(centre, [0.0, 1.0, 0.0] if abs(centre[1]) < 0.9 else [1.0, 0.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(centre, e1)

    def proj(p: np.ndarray) -> np.ndarray:
        d = np.maximum(p @ centre, 1e-6)
        out: np.ndarray = np.column_stack([(p @ e1) / d, (p @ e2) / d])
        return out

    ga, gb = proj(a), proj(b)
    b1, b2 = gb[:-1], gb[1:]
    for i in range(len(ga) - 1):
        p, r = ga[i], ga[i + 1] - ga[i]
        s = b2 - b1
        den = r[0] * s[:, 1] - r[1] * s[:, 0]
        ok = np.abs(den) > 1e-15
        qp = b1 - p
        tt = np.where(ok, (qp[:, 0] * s[:, 1] - qp[:, 1] * s[:, 0]) / np.where(ok, den, 1), -1)
        uu = np.where(ok, (qp[:, 0] * r[1] - qp[:, 1] * r[0]) / np.where(ok, den, 1), -1)
        hit = ok & (tt >= 0) & (tt <= 1) & (uu >= 0) & (uu <= 1)
        if hit.any():
            j = int(np.flatnonzero(hit)[0])
            g = p + tt[j] * r
            x = centre + g[0] * e1 + g[1] * e2
            res: np.ndarray = x / np.linalg.norm(x)
            return res
    return None


def step(
    topo: Topology,
    omega: np.ndarray,
    dt_myr: float,
    spacing_rad: float,
    continents: tuple[np.ndarray, np.ndarray, cKDTree] | None = None,
) -> Topology:
    """Move the graph back by ``dt_myr``.

    Each segment moves rigidly with its rotation (``point_rotations``).  A
    junction is where its boundaries meet: after the move it is put at the mean
    of the pairwise intersections of the moved segment ends (each extended a
    little along its tangent), and every segment end is cut back to it, so no
    end overshoots past a neighbouring boundary — the closure of continuously
    closing plates (Gurnis et al. 2012).  If the ends no longer intersect, the
    junction moves with its velocity-triangle velocity (``junction_velocity``,
    McKenzie & Morgan 1969).  Segments are then lightly smoothed and resampled.
    """
    t_yr = -dt_myr * 1.0e6
    rotations = [point_rotations(seg, omega, continents, spacing_rad) for seg in topo.segments]
    moved = [
        _rotate_points(seg.points, w, t_yr) for seg, w in zip(topo.segments, rotations, strict=True)
    ]
    nodes = topo.nodes.copy()
    for k, lst in enumerate(topo.node_segments()):
        if not lst:
            continue
        node = topo.nodes[k]
        # how far a junction can travel in one step: the fastest boundary here
        speed = max(float(np.linalg.norm(rotations[s][0])) for s, _ in lst) * abs(t_yr)
        extend = max(3.0 * spacing_rad, 2.0 * speed)
        rays = [_end_ray(moved[s], at_start, 0.3, extend) for s, at_start in lst]
        hits = []
        for i in range(len(rays)):
            for j in range(i + 1, len(rays)):
                x = _first_crossing(rays[i], rays[j], node)
                if x is not None:
                    hits.append(x)
        if hits:
            nodes[k] = _normalize(np.mean(hits, axis=0))
        else:
            normals, vels = [], []
            for s, at_start in lst:
                pts = topo.segments[s].points
                end = 0 if at_start else -1
                normals.append(np.cross(node, tangents(pts)[end]))
                vels.append(np.cross(rotations[s][end], node))
            v = junction_velocity(node, np.array(normals), np.array(vels))
            nodes[k] = _normalize(node + v * t_yr)
    segs = []
    for seg, pts in zip(topo.segments, moved, strict=True):
        if seg.start >= 0:
            pts = attach_end(pts, nodes[seg.start], at_start=True)
        if seg.end >= 0:
            pts = attach_end(pts, nodes[seg.end], at_start=False)
        # light smoothing keeps per-step noise from accumulating (numerical stabilization)
        segs.append(replace(seg, points=resample(smooth(pts, 1, 0.3), spacing_rad)))
    return Topology(nodes=nodes, segments=segs)


def rasterize(
    topo: Topology,
    kin: PlateKinematics,
    densify_rad: float,
    band_rad: float | None = None,
    k: int = 8,
) -> np.ndarray:
    """Plate label of every cell from the boundary graph.

    Side test: for a cell, the ``k`` nearest densified boundary points each vote
    for the plate on the cell's side of the local tangent, weighted by inverse
    distance (a single nearest point misjudges cells near segment ends and
    corners).  Cells farther than ``band_rad`` from every boundary are grouped
    into connected components, and each component takes the majority of its
    cells' votes, so a plate interior is one label even where a vote is noisy.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    if band_rad is None:
        band_rad = kin.spacing_km / kin.radius_km
    pts, tan, left, right = [], [], [], []
    for seg in topo.segments:
        p = resample(seg.points, densify_rad)
        pts.append(p)
        tan.append(tangents(p))
        left.append(np.full(len(p), seg.left))
        right.append(np.full(len(p), seg.right))
    allp, allt = np.vstack(pts), np.vstack(tan)
    lab_l, lab_r = np.concatenate(left), np.concatenate(right)
    kk = min(k, len(allp))
    dist, idx = cKDTree(allp).query(kin.xyz, k=kk)
    dist, idx = dist.reshape(kin.n, kk), idx.reshape(kin.n, kk)
    q = allp[idx]
    side = np.einsum("nkj,nkj->nk", np.cross(q, allt[idx]), kin.xyz[:, None, :] - q) > 0
    vote_plate = np.where(side, lab_l[idx], lab_r[idx])
    weight = 1.0 / np.maximum(dist, 1e-9)
    n_lab = int(max(lab_l.max(), lab_r.max())) + 1
    tally = np.zeros((kin.n, n_lab))
    np.add.at(tally, (np.repeat(np.arange(kin.n), kk), vote_plate.ravel()), weight.ravel())
    label: np.ndarray = np.argmax(tally, axis=1)

    interior = dist[:, 0] > band_rad
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    keep = interior[rows] & interior[cols]
    g = csr_matrix((np.ones(int(keep.sum())), (rows[keep], cols[keep])), shape=(kin.n, kin.n))
    _, comp = connected_components(g, directed=False)
    ci = np.flatnonzero(interior)
    comp_tally = np.zeros((comp.max() + 1, n_lab))
    np.add.at(
        comp_tally, comp[ci], tally[ci] / np.maximum(tally[ci].sum(axis=1, keepdims=True), 1e-12)
    )
    label[ci] = np.argmax(comp_tally[comp[ci]], axis=1)
    return label


def event_grid(n: int, radius_km: float) -> PlateKinematics:
    """Fixed sampling sphere for boundary-collision events.

    ``n`` Fibonacci points with Delaunay adjacency and equal areas.  Re-closing
    the graph on this grid instead of the world's mesh keeps event handling the
    same whatever the world's cell count (geological-timeline.md §12).
    """
    from dreamulator.map.cvt_mesh import fibonacci_sphere
    from dreamulator.map.paleo_kinematics import PlateKinematics, adjacency_csr

    xyz = fibonacci_sphere(n)
    tri, _ = delaunay(xyz)
    nbrs: list[set[int]] = [set() for _ in range(n)]
    for a, b, c in tri.tolist():
        nbrs[a].update((b, c))
        nbrs[b].update((a, c))
        nbrs[c].update((a, b))
    ptr, idx = adjacency_csr([sorted(s) for s in nbrs])
    return PlateKinematics(
        xyz=xyz,
        nbr_ptr=ptr,
        nbr_idx=idx,
        plate=np.zeros(n, dtype=np.int64),
        omega=np.zeros((1, 3)),
        continental=np.zeros(n, dtype=bool),
        area_km2=np.full(n, 4.0 * np.pi * radius_km**2 / n),
        radius_km=radius_km,
    )


def _chunks(points: np.ndarray, max_rad: float) -> list[tuple[int, np.ndarray]]:
    """Split a polyline into overlapping pieces no longer than ``max_rad``; each
    piece comes with the index of its first point in the full polyline."""
    seg = np.arccos(np.clip(np.einsum("ij,ij->i", points[:-1], points[1:]), -1.0, 1.0))
    s = np.r_[0.0, np.cumsum(seg)]
    out: list[tuple[int, np.ndarray]] = []
    i = 0
    while i < len(points) - 1:
        j = int(np.searchsorted(s, s[i] + max_rad, side="right"))
        j = min(max(j, i + 2), len(points))
        out.append((i, points[i:j]))
        i = j - 1
    return out


def find_crossings(
    topo: Topology, near_rad: float, chunk_rad: float = 0.5
) -> list[tuple[int, int, np.ndarray]]:
    """Crossings between boundary segments away from their shared junctions.

    Returns (segment a, segment b, crossing point) for every pair of polyline
    pieces that properly intersect (a segment with itself included), skipping
    contacts within ``near_rad`` of a junction they share.  Segments are tested
    in pieces of at most ``chunk_rad`` so that each pair fits one gnomonic chart.
    """
    out: list[tuple[int, int, np.ndarray]] = []
    segs = topo.segments
    pieces = [
        (k, off, p) for k, seg in enumerate(segs) for off, p in _chunks(seg.points, chunk_rad)
    ]
    centres = np.array([_normalize(p.mean(axis=0)) for _, _, p in pieces])
    reach = np.cos(chunk_rad + 2.0 * near_rad)
    for u in range(len(pieces)):
        a, off_a, pa = pieces[u]
        for v in range(u, len(pieces)):
            b, off_b, pb = pieces[v]
            if centres[u] @ centres[v] < reach:
                continue
            shared = [
                topo.nodes[n]
                for n in {segs[a].start, segs[a].end} & {segs[b].start, segs[b].end}
                if n >= 0
            ]
            centre = _normalize(centres[u] + centres[v])
            e1 = np.cross(centre, [0.0, 1.0, 0.0] if abs(centre[1]) < 0.9 else [1.0, 0.0, 0.0])
            e1 /= np.linalg.norm(e1)
            e2 = np.cross(centre, e1)
            ga = np.column_stack([(pa @ e1) / (pa @ centre), (pa @ e2) / (pa @ centre)])
            gb = np.column_stack([(pb @ e1) / (pb @ centre), (pb @ e2) / (pb @ centre)])
            b1, s = gb[:-1], gb[1:] - gb[:-1]
            for i in range(len(ga) - 1):
                p, r = ga[i], ga[i + 1] - ga[i]
                den = r[0] * s[:, 1] - r[1] * s[:, 0]
                ok = np.abs(den) > 1e-15
                qp = b1 - p
                safe = np.where(ok, den, 1.0)
                tt = np.where(ok, (qp[:, 0] * s[:, 1] - qp[:, 1] * s[:, 0]) / safe, -1.0)
                uu = np.where(ok, (qp[:, 0] * r[1] - qp[:, 1] * r[0]) / safe, -1.0)
                hit = ok & (tt > 1e-9) & (tt < 1 - 1e-9) & (uu > 1e-9) & (uu < 1 - 1e-9)
                if a == b:
                    hit &= np.abs((off_b + np.arange(len(b1))) - (off_a + i)) > 1
                for j in np.flatnonzero(hit):
                    g = p + tt[j] * r
                    x = _normalize(centre + g[0] * e1 + g[1] * e2)
                    if any(float(x @ n) > np.cos(near_rad) for n in shared):
                        continue
                    out.append((a, b, x))
    # pieces overlap by one point, so a crossing at a shared piece end can repeat
    unique: list[tuple[int, int, np.ndarray]] = []
    for a, b, x in out:
        if not any(a == a2 and b == b2 and float(x @ x2) > np.cos(1e-6) for a2, b2, x2 in unique):
            unique.append((a, b, x))
    return unique


def _hop_distance(
    ptr: np.ndarray, idx: np.ndarray, sources: np.ndarray, allowed: np.ndarray, max_hops: int
) -> np.ndarray:
    """Graph hop distance from ``sources`` through ``allowed`` cells (−1 beyond
    ``max_hops`` or unreachable)."""
    dist = np.full(len(ptr) - 1, -1, dtype=np.int64)
    frontier = np.flatnonzero(sources & allowed)
    dist[frontier] = 0
    for h in range(1, max_hops + 1):
        if frontier.size == 0:
            break
        starts, ends = ptr[frontier], ptr[frontier + 1]
        nbr = np.concatenate([idx[s:e] for s, e in zip(starts, ends, strict=True)])
        nbr = np.unique(nbr)
        nbr = nbr[allowed[nbr] & (dist[nbr] < 0)]
        dist[nbr] = h
        frontier = nbr
    return dist


def split_thin_parts(grid: PlateKinematics, lab: np.ndarray, r_hops: int) -> np.ndarray:
    """Split plate parts narrower than about 2 · r_hops cells along their midline.

    Morphological opening per plate: cells at least ``r_hops`` from any other
    plate are its core; cells within ``r_hops`` of its core survive; the rest are
    thin parts (ribbons, fingers) that cannot be rigid plates.  Every thin cell
    goes to the nearest surviving cell's plate, so a ribbon between two plates is
    divided along its midline and its neighbours meet there in a new boundary.
    """
    ptr, idx = grid.nbr_ptr, grid.nbr_idx
    rows = np.repeat(np.arange(grid.n), np.diff(ptr))
    on_edge = np.zeros(grid.n, dtype=bool)
    on_edge[rows[lab[rows] != lab[idx]]] = True
    everywhere = np.ones(grid.n, dtype=bool)
    d_edge = _hop_distance(ptr, idx, on_edge, everywhere, r_hops)
    core = (d_edge < 0) | (d_edge >= r_hops)
    keep = np.zeros(grid.n, dtype=bool)
    for p in np.unique(lab):
        own = lab == p
        d = _hop_distance(ptr, idx, core & own, own, r_hops)
        keep |= own & (d >= 0)
    thin = ~keep
    if not thin.any():
        return lab
    out = lab.copy()
    # nearest surviving cell: grow the surviving labels into the thin cells
    frontier_label = np.where(keep, lab, -1)
    for _ in range(4 * r_hops + 4):
        todo = np.flatnonzero(frontier_label < 0)
        if todo.size == 0:
            break
        nb_rows = np.repeat(todo, np.diff(ptr)[todo])
        nb = np.concatenate([idx[ptr[c] : ptr[c + 1]] for c in todo])
        cand = frontier_label[nb]
        ok = cand >= 0
        if not ok.any():
            break
        first: dict[int, int] = {}
        for cell, lab_c in zip(nb_rows[ok].tolist(), cand[ok].tolist(), strict=True):
            first.setdefault(cell, lab_c)
        cells = np.fromiter(first.keys(), dtype=np.int64)
        frontier_label[cells] = np.fromiter(first.values(), dtype=np.int64)
    filled = frontier_label >= 0
    out[filled] = frontier_label[filled]
    return out


def reclose(
    topo: Topology,
    grid: PlateKinematics,
    spacing_rad: float,
    side_info: tuple[np.ndarray, np.ndarray, np.ndarray, cKDTree],
    omega: np.ndarray,
    radius_km: float,
    smooth_iterations: int = 3,
    relabel: dict[int, int] | None = None,
    transfers: list[tuple[np.ndarray, int]] | None = None,
    thin_hops: int = 2,
) -> tuple[Topology, dict[str, int]]:
    """Resolve boundary collisions by closing the plates again.

    ``relabel`` merges plates while closing (merged → kept): a merged plate's
    cells take the kept plate's label before extraction, so the boundary between
    them disappears and the merged plate's other boundaries carry over to the
    kept plate.  ``transfers`` moves regions to another plate while closing: each
    (points, plate) pair gives the event-grid cells nearest to ``points`` (within
    about one spacing of them) to ``plate`` (a boundary jump).  Plate parts
    narrower than about 2 · ``thin_hops`` event-grid cells are split along their
    midline between the neighbouring plates (``split_thin_parts``).

    The graph is rasterized on the fixed event grid (``event_grid``), enclaves
    are absorbed (terrain engine's rule), and the graph is extracted again: a
    plate whose width went to zero disappears or leaves a fragment that is
    absorbed, and new junctions and new plate pairs appear where boundaries met.
    Segment types and trench polarities carry over by plate pair; a plate pair
    that did not exist before is typed from its relative motion.
    """
    grid_spacing = float(np.sqrt(4.0 * np.pi / grid.n))
    lab = rasterize(topo, grid, grid_spacing / 3.0)
    if relabel:
        for old, new_label in relabel.items():
            lab[lab == old] = new_label
    for pts, new_plate in transfers or []:
        if len(pts):
            d, _ = cKDTree(pts).query(grid.xyz, distance_upper_bound=1.5 * spacing_rad)
            lab[np.isfinite(d)] = new_plate
    lab = clean_labels(grid, lab)
    if thin_hops > 0:
        lab = clean_labels(grid, split_thin_parts(grid, lab, thin_hops))
    before = {s.left for s in topo.segments} | {s.right for s in topo.segments}
    new = prepare(extract(grid.xyz, lab), 0.5 * spacing_rad, smooth_iterations)
    kinds: dict[tuple[int, int], tuple[str, int]] = {}
    remap = relabel or {}
    for seg in topo.segments:
        left, right = remap.get(seg.left, seg.left), remap.get(seg.right, seg.right)
        over = remap.get(seg.over, seg.over)
        kinds.setdefault((left, right), (seg.kind, over))
        kinds.setdefault((right, left), (seg.kind, over))
    untyped: list[Segment] = []
    for seg in new.segments:
        if (seg.left, seg.right) in kinds:
            seg.kind, seg.over = kinds[(seg.left, seg.right)]
        else:
            untyped.append(seg)
    if untyped:
        classify(Topology(nodes=new.nodes, segments=untyped), omega, radius_km, side_info)
    after = {s.left for s in new.segments} | {s.right for s in new.segments}
    stats = {
        "plates_removed": len(before - after),
        "new_plate_pairs": len(untyped),
        "segments": len(new.segments),
        "junctions": len(new.nodes),
    }
    return new, stats


@dataclass(frozen=True)
class TopologyCheck:
    """Topology rules of geological-timeline.md appendix A.3 on rasterized labels.

    Attributes:
        plates: number of plates.
        n_min, s_max: thresholds for that plate count (Euler: mean neighbours 6 − 12/N).
        min_neighbours: fewest neighbours among plates above 1 % of the surface.
        max_share: largest boundary share with a single neighbour among them.
        pieces_outside_largest: area share of plates' disconnected pieces.
        passed: all rules hold.
    """

    plates: int
    n_min: int
    s_max: float
    min_neighbours: int
    max_share: float
    pieces_outside_largest: float
    passed: bool


def thresholds(n_plates: int) -> tuple[int, float]:
    """(n_min, s_max) for ``n_plates``: mean neighbours of a trivalent spherical
    tessellation are 6 − 12/N; PB2002 (N = 52) gives 5 and 0.62."""
    mean_nb = 6.0 - 12.0 / max(n_plates, 3)
    return max(3, int(np.floor(mean_nb))), min(0.9, 0.62 * (6.0 - 12.0 / 52.0) / mean_nb)


def check(kin: PlateKinematics, label: np.ndarray) -> TopologyCheck:
    """Evaluate the topology rules on cell labels."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    a = kin.area_km2
    total = float(a.sum())
    plates = np.unique(label)
    n_min, s_max = thresholds(len(plates))
    min_nb, max_share = 10**6, 0.0
    for q in plates:
        if a[label == q].sum() < 0.01 * total:
            continue
        edge = (label[rows] == q) & (label[cols] != q)
        nb, cnt = np.unique(label[cols[edge]], return_counts=True)
        if cnt.size:
            min_nb = min(min_nb, int(nb.size))
            max_share = max(max_share, float(cnt.max() / cnt.sum()))
    same = label[rows] == label[cols]
    g = csr_matrix((np.ones(int(same.sum())), (rows[same], cols[same])), shape=(kin.n, kin.n))
    _, comp = connected_components(g, directed=False)
    comp_area = np.bincount(comp, weights=a)
    comp_plate = np.zeros(comp_area.size, dtype=label.dtype)
    comp_plate[comp] = label
    outside = 0.0
    for q in plates:
        ca = comp_area[comp_plate == q]
        outside += float(ca.sum() - ca.max())
    min_nb = min_nb if min_nb < 10**6 else 0
    return TopologyCheck(
        plates=len(plates),
        n_min=n_min,
        s_max=round(s_max, 3),
        min_neighbours=min_nb,
        max_share=round(max_share, 3),
        pieces_outside_largest=round(outside / total, 4),
        passed=min_nb >= n_min and max_share <= s_max and outside / total < 0.01,
    )
