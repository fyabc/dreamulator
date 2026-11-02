"""Fill-reducing elimination order for operators on the spherical CVT mesh.

The moisture budget factorises one sparse operator per solve, about a hundred
times per build, and every one of them has the same sparsity pattern — the
mesh's edge graph — so the elimination order can be computed once and reused.
SuperLU's own minimum-degree ordering recomputes it on every call, which was
measured at about a fifth of each factorisation.

The order here is nested dissection with geometric separators.  A Voronoi mesh
of a sphere is close to a planar graph, for which nested dissection is the
asymptotically good ordering (George 1973; Lipton, Rose and Tarjan 1979): each
region is split at the median of its widest Cartesian coordinate, the cells on
one side that touch the other side form a separator, and the separator is
numbered after both halves, so eliminating either half creates no fill in the
other.  Measured on nacrea's 200k-cell budget operator (2026-11-02), it gives
7% more factor nonzeros than minimum degree but factorises 35% faster, because
the elimination falls into large dense supernodes that the dense kernels handle
well.

Pure numpy, deterministic, no dependency, so it runs in the browser build too.
"""

from __future__ import annotations

import numpy as np

#: Regions of at most this many cells are not split further.  Small enough that
#: the leaves' own fill is negligible, large enough that the recursion stays
#: shallow (twelve levels for 200k cells).
NESTED_DISSECTION_LEAF_CELLS = 64


def nested_dissection_order(
    xyz: np.ndarray,
    src: np.ndarray,
    dst: np.ndarray,
    *,
    leaf_cells: int = NESTED_DISSECTION_LEAF_CELLS,
) -> np.ndarray:
    """Elimination order of the mesh's cells, separators after the halves they split.

    Args:
        xyz: Cell centres as Cartesian coordinates, shape (n, 3).
        src: Source cell of each edge.
        dst: Destination cell of each edge.  Edges may be listed in one or both
            directions; the adjacency is symmetrised here.
        leaf_cells: Regions this small are numbered as they stand.

    Returns:
        Permutation ``order`` with ``order[k]`` the original index of the cell
        eliminated k-th, i.e. new position to original index.  The symmetric
        pre-permutation of a matrix ``A`` is ``A[order][:, order]``.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"xyz must have shape (n, 3), got {xyz.shape}")
    if leaf_cells < 1:
        raise ValueError("leaf_cells must be positive")
    n = xyz.shape[0]
    src = np.asarray(src, dtype=np.int64)
    dst = np.asarray(dst, dtype=np.int64)
    if src.shape != dst.shape:
        raise ValueError("src and dst must have the same shape")

    rows = np.concatenate([src, dst])
    cols = np.concatenate([dst, src])
    keep = rows != cols
    rows, cols = rows[keep], cols[keep]
    by_row = np.lexsort((cols, rows))
    rows, cols = rows[by_row], cols[by_row]
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.add.at(indptr, rows + 1, 1)
    indptr = np.cumsum(indptr)

    in_high = np.zeros(n, dtype=bool)
    order: list[np.ndarray] = []

    def touches_high(cells: np.ndarray) -> np.ndarray:
        """Which of ``cells`` have a neighbour currently marked in ``in_high``."""
        starts = indptr[cells]
        counts = indptr[cells + 1] - starts
        total = int(counts.sum())
        if total == 0:
            return np.zeros(cells.size, dtype=bool)
        offsets = np.cumsum(counts) - counts
        slots = np.arange(total) - np.repeat(offsets, counts) + np.repeat(starts, counts)
        owner = np.repeat(np.arange(cells.size), counts)
        hits = np.bincount(owner, weights=in_high[cols[slots]], minlength=cells.size)
        return np.asarray(hits > 0.0)

    def split(cells: np.ndarray) -> None:
        if cells.size <= leaf_cells:
            order.append(cells)
            return
        coords = xyz[cells]
        axis = int(np.argmax(coords.max(axis=0) - coords.min(axis=0)))
        median = float(np.median(coords[:, axis]))
        low_side = coords[:, axis] <= median
        low, high = cells[low_side], cells[~low_side]
        if low.size == 0 or high.size == 0:
            order.append(cells)
            return
        in_high[high] = True
        separating = touches_high(low)
        in_high[high] = False
        split(low[~separating])
        split(high)
        order.append(low[separating])

    split(np.arange(n, dtype=np.int64))
    result = np.concatenate(order)
    if result.size != n:  # pragma: no cover - a bisection either keeps or splits every cell
        raise AssertionError("nested dissection lost cells")
    return result
