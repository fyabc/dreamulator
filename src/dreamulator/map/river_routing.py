"""Two-ring single receivers with conservative terrain, water and crossing checks.

Only the eight primitive (2, 1) directions extend the prepared D8 graph.
New edges must descend everywhere on the piecewise-bilinear nodal DEM and
avoid water pixel interiors. Crossing edges retain their original D8 receiver.
The direction set follows expanded single-flow routing; the constraints
are original numerical rules, not a reproduction of the published D16.
"""

from __future__ import annotations

import numpy as np
from numba import njit

HEIGHT_TOL_M = 1e-9
KNIGHT_OFFSETS = np.array(
    [(r, c) for r in range(-2, 3) for c in range(-2, 3) if abs(r) + abs(c) == 3],
    dtype=np.int64,
)


def two_ring_receivers(
    height: np.ndarray,
    land: np.ndarray,
    receiver: np.ndarray,
    protected_water: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Extend a resolved D8 graph, preserving flats and all protected lake links.

    ``height`` is the zero-epsilon filled routing surface. A downstream-first
    Priority-Flood order remains valid: new targets have strictly lower
    height, and unchanged flat links retain their discovery predecessor.
    This in-memory implementation preserves the receiver's integer dtype.
    """
    if height.ndim != 2 or min(height.shape) < 2 or not np.isfinite(height).all():
        raise ValueError("routing height must be a finite two-dimensional grid")
    if land.shape != height.shape or receiver.size != height.size:
        raise ValueError("land and receivers must match the routing grid")
    if protected_water is not None and protected_water.shape != height.shape:
        raise ValueError("protected water must match the routing grid")
    stop = ~np.asarray(land, dtype=bool)
    if protected_water is not None:
        stop |= protected_water
    stop[0, :] = stop[-1, :] = stop[:, 0] = stop[:, -1] = True
    proposed = candidates(height, stop, receiver)
    order = np.argsort(-height.ravel(), kind="stable")
    result, rejected = prune_crossings(receiver, proposed, order, height.shape[1])
    changed = int(np.count_nonzero(proposed != receiver.ravel()))
    return result, {
        "proposed_extensions": changed,
        "crossing_rejected": rejected,
        "accepted_extensions": changed - rejected,
    }


@njit(cache=True)
def bilinear(height: np.ndarray, row: float, col: float) -> float:
    r = min(int(np.floor(row)), height.shape[0] - 2)
    c = min(int(np.floor(col)), height.shape[1] - 2)
    u, v = row - r, col - c
    return float(
        (1 - u) * (1 - v) * height[r, c]
        + (1 - u) * v * height[r, c + 1]
        + u * (1 - v) * height[r + 1, c]
        + u * v * height[r + 1, c + 1]
    )


@njit(cache=True)
def clear_descent(height: np.ndarray, stop: np.ndarray, r: int, c: int, dr: int, dc: int) -> bool:
    """Check exact derivative signs in both bilinear intervals, plus water entry."""
    if not (0 <= r + dr < height.shape[0] and 0 <= c + dc < height.shape[1]):
        return False
    # A primitive two-ring edge crosses pixel boundaries at t=1/4, 1/2, 3/4.
    for t in (0.125, 0.375, 0.625, 0.875):
        rr, cc = int(np.floor(r + dr * t + 0.5)), int(np.floor(c + dc * t + 0.5))
        if stop[rr, cc]:
            return False
    # Restricting a bilinear patch to a straight line gives a quadratic.
    # Its derivative is linear; both endpoint signs bound the entire interval.
    for t0 in (0.0, 0.5):
        h0 = bilinear(height, r + dr * t0, c + dc * t0)
        hm = bilinear(height, r + dr * (t0 + 0.25), c + dc * (t0 + 0.25))
        h1 = bilinear(height, r + dr * (t0 + 0.5), c + dc * (t0 + 0.5))
        a = 2 * (h0 + h1 - 2 * hm)
        b = h1 - h0 - a
        if not np.isfinite(a + b) or max(b, b + 2 * a) > HEIGHT_TOL_M:
            return False
    return True


@njit(cache=True)
def candidates(height: np.ndarray, stop: np.ndarray, base: np.ndarray) -> np.ndarray:
    """Keep the steepest eligible extension; baseline D8 supplies every fallback."""
    nr, nc = height.shape
    result = base.ravel().copy()
    for cell in range(height.size):
        r, c = divmod(cell, nc)
        target = result[cell]
        if stop[r, c] or target < 0:
            continue
        tr, tc = divmod(target, nc)
        best = (height[r, c] - height[tr, tc]) / np.hypot(r - tr, c - tc)
        # Equal-height cells keep the prepared D8 flat graph exactly.
        if best <= 0:
            continue
        for k in range(len(KNIGHT_OFFSETS)):
            dr, dc = KNIGHT_OFFSETS[k]
            if not (0 <= r + dr < nr and 0 <= c + dc < nc):
                continue
            slope = (height[r, c] - height[r + dr, c + dc]) / np.sqrt(5.0)
            if slope > best and clear_descent(height, stop, r, c, dr, dc):
                best = slope
                result[cell] = (r + dr) * nc + c + dc
    return result


@njit(cache=True)
def crosses(a: int, b: int, c: int, d: int, columns: int) -> bool:
    """Proper interior intersection; a shared grid-center endpoint is a junction."""
    ar, ac = divmod(a, columns)
    br, bc = divmod(b, columns)
    cr, cc = divmod(c, columns)
    dr, dc = divmod(d, columns)
    vr, vc, wr, wc = br - ar, bc - ac, dr - cr, dc - cc
    denominator = vr * wc - vc * wr
    if denominator == 0:
        return False
    t = ((cr - ar) * wc - (cc - ac) * wr) / denominator
    u = ((cr - ar) * vc - (cc - ac) * vr) / denominator
    return 0 < t < 1 and 0 < u < 1


@njit(cache=True)
def prune_crossings(
    base: np.ndarray, proposed: np.ndarray, order: np.ndarray, columns: int
) -> tuple[np.ndarray, int]:
    """Accept extensions in stable elevation order against the current entire graph."""
    result = base.ravel().copy()
    rows = len(result) // columns
    rejected = 0
    for cell in order:
        target = proposed[cell]
        if target == result[cell] or target < 0:
            continue
        r, c = divmod(cell, columns)
        conflict = False
        # Both edges have coordinate extent <= 2, so all intersections are local.
        for rr in range(max(0, r - 4), min(rows, r + 5)):
            for cc in range(max(0, c - 4), min(columns, c + 5)):
                other = rr * columns + cc
                down = result[other]
                if other != cell and down >= 0 and crosses(cell, target, other, down, columns):
                    conflict = True
                    break
            if conflict:
                break
        if conflict:
            rejected += 1
        else:
            result[cell] = target
    return result, rejected


@njit(cache=True)
def accumulate(receiver: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Topologically accumulate each source once, rejecting cycles or invalid targets."""
    n = len(receiver)
    indegree = np.zeros(n, dtype=np.int64)
    queue = np.empty(n, dtype=np.int64)
    total = source.ravel().copy()
    for target in receiver:
        if target < -1 or target >= n:
            raise ValueError("receiver index outside graph")
        if target >= 0:
            indegree[target] += 1
    head, tail = 0, 0
    for cell in range(n):
        if indegree[cell] == 0:
            queue[tail] = cell
            tail += 1
    while head < tail:
        cell = queue[head]
        head += 1
        target = receiver[cell]
        if target >= 0:
            total[target] += total[cell]
            indegree[target] -= 1
            if indegree[target] == 0:
                queue[tail] = target
                tail += 1
    if tail != n:
        raise ValueError("flow graph contains a cycle")
    return total.reshape(source.shape)
