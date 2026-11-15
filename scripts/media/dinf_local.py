"""Local square-grid D-infinity reference, independent of production routing.

Tarboton (1997), doi:10.1029/96WR03137: select the steepest of eight
triangular facets, then partition by angle between its two downslope nodes.
Angles are counterclockwise from east; array rows run south. Missing nodes
are closed. Explicit absorbing cells receive water but have no outgoing edges.
Boundary facets with missing vertices are excluded; valid individual links
remain available. Flat/pit cells are sinks unless prepared by Priority-Flood.
This in-memory pilot does not implement the external-memory river/lake solver.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numba import njit

# Axis vertex, diagonal vertex, axis azimuth, facet orientation.
FACETS = (
    ((0, 1), (-1, 1), 0, 1),
    ((-1, 0), (-1, 1), 1, -1),
    ((-1, 0), (-1, -1), 1, 1),
    ((0, -1), (-1, -1), 2, -1),
    ((0, -1), (1, -1), 2, 1),
    ((1, 0), (1, -1), 3, -1),
    ((1, 0), (1, 1), 3, 1),
    ((0, 1), (1, 1), 4, -1),
)


@dataclass
class Routing:
    """Two global flattened receivers per cell; -1 denotes an unused edge."""

    receiver: np.ndarray
    proportion: np.ndarray
    angle_rad: np.ndarray
    slope: np.ndarray


def _neighbor(array: np.ndarray, offset: tuple[int, int], fill: float) -> np.ndarray:
    dr, dc = offset
    nr, nc = array.shape
    out = np.full_like(array, fill)
    r0, r1, c0, c1 = max(0, -dr), min(nr, nr - dr), max(0, -dc), min(nc, nc - dc)
    out[r0:r1, c0:c1] = array[r0 + dr : r1 + dr, c0 + dc : c1 + dc]
    return out


def directions(
    height_m: np.ndarray,
    spacing_m: float,
    absorbing: np.ndarray | None = None,
    *,
    method: str = "dinf",
) -> Routing:
    """Calculate D8 or D-infinity on the same prepared height and sink masks."""
    h = np.asarray(height_m, dtype=np.float64)
    if h.ndim != 2 or not h.size or min(h.shape) < 2:
        raise ValueError("height must be a nonempty 2-D grid with at least two rows/columns")
    if not np.isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("spacing_m must be finite and positive")
    if method not in {"d8", "dinf"}:
        raise ValueError("method must be d8 or dinf")
    stop = ~np.isfinite(h)
    if absorbing is not None:
        if absorbing.shape != h.shape:
            raise ValueError("absorbing mask shape differs from height")
        stop |= absorbing
    ids = np.arange(h.size).reshape(h.shape)
    receiver = np.full((*h.shape, 2), -1, dtype=np.int64)
    proportion = np.zeros((*h.shape, 2), dtype=np.float64)
    best = np.zeros(h.shape)
    angle = np.full(h.shape, np.nan)
    neighbors = {offset for a, d, _, _ in FACETS for offset in (a, d)}
    # Single links cover both D8 and missing-vertex boundary degeneration.
    for offset in sorted(neighbors):
        e = _neighbor(h, offset, np.nan)
        target = _neighbor(ids, offset, -1)
        s = (h - e) / (spacing_m * np.hypot(*offset))
        take = np.isfinite(s) & ~stop & (s > best)
        best[take] = s[take]
        angle[take] = np.arctan2(-offset[0], offset[1]) % (2 * np.pi)
        receiver[take, 0] = target[take]
        proportion[take, 0] = 1
    if method == "dinf":
        for axis, diagonal, quarter, sign in FACETS:
            e1, e2 = _neighbor(h, axis, np.nan), _neighbor(h, diagonal, np.nan)
            s1, s2 = (h - e1) / spacing_m, (e1 - e2) / spacing_m
            raw = np.arctan2(s2, s1)
            r = np.clip(raw, 0, np.pi / 4)
            s = np.where(
                raw < 0,
                s1,
                np.where(raw > np.pi / 4, (h - e2) / (spacing_m * np.sqrt(2)), np.hypot(s1, s2)),
            )
            take = np.isfinite(e1) & np.isfinite(e2) & ~stop & (s > best)
            best[take] = s[take]
            angle[take] = (quarter * np.pi / 2 + sign * r[take]) % (2 * np.pi)
            receiver[take, 0] = _neighbor(ids, axis, -1)[take]
            receiver[take, 1] = _neighbor(ids, diagonal, -1)[take]
            fraction = r[take] / (np.pi / 4)
            proportion[take, 0], proportion[take, 1] = 1 - fraction, fraction
    receiver[proportion == 0] = -1
    return Routing(receiver, proportion, angle, best)


def tiled_directions(
    height_m: np.ndarray, spacing_m: float, absorbing: np.ndarray, tile_size: int
) -> Routing:
    """Use a real one-cell halo; remap both tile receivers to whole-grid IDs."""
    if tile_size < 1:
        raise ValueError("tile_size must be positive")
    nr, nc = height_m.shape
    result = Routing(
        np.full((nr, nc, 2), -1, dtype=np.int64),
        np.zeros((nr, nc, 2)),
        np.full((nr, nc), np.nan),
        np.zeros((nr, nc)),
    )
    for row in range(0, nr, tile_size):
        for col in range(0, nc, tile_size):
            endr, endc = min(nr, row + tile_size), min(nc, col + tile_size)
            r0, c0 = max(0, row - 1), max(0, col - 1)
            r1, c1 = min(nr, endr + 1), min(nc, endc + 1)
            halo = np.s_[r0:r1, c0:c1]
            core = np.s_[row - r0 : endr - r0, col - c0 : endc - c0]
            dst = np.s_[row:endr, col:endc]
            local = directions(height_m[halo], spacing_m, absorbing[halo])
            rec = local.receiver[core]
            mapped = (rec // (c1 - c0) + r0) * nc + rec % (c1 - c0) + c0
            result.receiver[dst] = np.where(rec >= 0, mapped, -1)
            result.proportion[dst] = local.proportion[core]
            result.angle_rad[dst], result.slope[dst] = local.angle_rad[core], local.slope[core]
    return result


def check_routing(height_m: np.ndarray, route: Routing) -> None:
    """Require an acyclic descending graph and a closed per-cell flow budget."""
    h = np.asarray(height_m).ravel()
    if route.receiver.shape != (*height_m.shape, 2):
        raise ValueError("receiver shape differs from height")
    if route.proportion.shape != route.receiver.shape:
        raise ValueError("proportion shape differs from receiver")
    rec, p = route.receiver.reshape(-1, 2), route.proportion.reshape(-1, 2)
    if not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("proportions must be finite and nonnegative")
    positive = p > 0
    if (rec[~positive] != -1).any() or (rec[positive] < 0).any() or (rec[positive] >= h.size).any():
        raise ValueError("positive edges must have valid receivers; unused edges must be -1")
    source = np.broadcast_to(np.arange(h.size)[:, None], rec.shape)[positive]
    target = rec[positive]
    if not (h[source] > h[target]).all():
        raise ValueError("every positive edge must strictly descend")
    sr, sc = np.divmod(source, height_m.shape[1])
    tr, tc = np.divmod(target, height_m.shape[1])
    if (np.maximum(abs(sr - tr), abs(sc - tc)) != 1).any():
        raise ValueError("receivers must be neighboring cells")
    if not np.allclose(p.sum(axis=1), positive.any(axis=1), atol=1e-14, rtol=0):
        raise ValueError("outgoing proportions must sum to one")


@njit(cache=True)
def _accumulate(
    order: np.ndarray, receiver: np.ndarray, proportion: np.ndarray, source: np.ndarray
) -> np.ndarray:
    accumulated = source.copy()
    for cell in order:
        for edge in range(2):
            target = receiver[cell, edge]
            if target >= 0:
                accumulated[target] += accumulated[cell] * proportion[cell, edge]
    return accumulated


def accumulate(height_m: np.ndarray, route: Routing, source: np.ndarray) -> np.ndarray:
    """Route both fractions once, in descending elevation order, including sinks."""
    check_routing(height_m, route)
    if source.shape != height_m.shape or not np.isfinite(source).all() or (source < 0).any():
        raise ValueError("source must be finite, nonnegative and have the height shape")
    if (source[~np.isfinite(height_m)] != 0).any():
        raise ValueError("missing height cells cannot produce water")
    order = np.argsort(np.nan_to_num(height_m.ravel(), nan=-np.inf), kind="stable")[::-1]
    return _accumulate(
        order,
        route.receiver.reshape(-1, 2),
        route.proportion.reshape(-1, 2),
        np.asarray(source, dtype=np.float64).ravel(),
    ).reshape(height_m.shape)


def displacement_angle(route: Routing) -> np.ndarray:
    """Azimuth of the water-weighted one-step displacement, including link length."""
    nr, nc = route.angle_rad.shape
    row, col = np.indices((nr, nc))
    rec, p = route.receiver, route.proportion
    dx = np.sum(p * (rec % nc - col[..., None]), axis=2)
    dy = np.sum(p * (row[..., None] - rec // nc), axis=2)
    return np.where(p.sum(axis=2) > 0, np.arctan2(dy, dx) % (2 * np.pi), np.nan)
