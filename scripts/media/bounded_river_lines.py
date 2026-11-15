"""Research-only bounded smoothing; the accepted receiver graph stays unsmoothed."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dreamulator.map.prog_erosion import (
    RIVER_REGIME_NON_PERENNIAL,
    RIVER_REGIME_PERENNIAL,
    ChannelGraph,
    _chaikin,
)


@dataclass
class SmoothedLine:
    points: np.ndarray
    source_station: np.ndarray
    reference: np.ndarray
    maximum_offset: float


def _interpolate(points: np.ndarray, station: np.ndarray, query: np.ndarray) -> np.ndarray:
    return np.column_stack([np.interp(query, station, points[:, axis]) for axis in range(2)])


def _reach(points: np.ndarray, sample_spacing: float, maximum_offset: float) -> SmoothedLine:
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    keep = np.r_[True, lengths > 1e-12]
    clean = points[keep]
    station = np.r_[0.0, np.cumsum(lengths[keep[1:]])]
    if len(clean) < 2:
        return SmoothedLine(clean, station, clean.copy(), 0)
    # Straight reaches need no new drawing vertices. Keep the existing
    # two-endpoint representation of long D8 runs at canvas scale.
    if station[-1] <= np.linalg.norm(clean[-1] - clean[0]) + 1e-10:
        return SmoothedLine(clean[[0, -1]], station[[0, -1]], clean[[0, -1]].copy(), 0)
    samples = np.unique(np.r_[np.arange(0, station[-1], sample_spacing), station[-1]])
    controls = np.column_stack((_interpolate(clean, station, samples), samples))
    smooth = _chaikin(controls)
    # Include every knot of both linear maps. Between knots their difference
    # is linear, and its norm is bounded by the maximum at the two endpoints.
    query = np.union1d(station, smooth[:, 2])
    # Coincident knots computed through two arithmetic paths can differ by a
    # few ulps. Merge them before emitting meaningless near-zero line segments.
    query = query[np.r_[True, np.diff(query) > 1e-10]]
    query[-1] = station[-1]
    reference = _interpolate(clean, station, query)
    candidate = _interpolate(smooth[:, :2], smooth[:, 2], query)
    delta = candidate - reference
    largest = float(np.linalg.norm(delta, axis=1).max())
    scale = min(1.0, maximum_offset / largest) if largest > 0 else 1.0
    result = reference + scale * delta
    result[0], result[-1] = points[0], points[-1]
    actual = float(np.linalg.norm(result - reference, axis=1).max())
    return SmoothedLine(result, query, reference, actual)


def smooth_line(
    points: np.ndarray,
    *,
    sample_spacing: float,
    maximum_offset: float = 0.5,
    anchors: tuple[int, ...] = (),
) -> SmoothedLine:
    """Preserve endpoints/junctions and bound displacement in input-coordinate units."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not len(points) or not np.isfinite(points).all():
        raise ValueError("points must be finite and have shape (N, 2)")
    if not np.isfinite(sample_spacing) or sample_spacing <= 0:
        raise ValueError("sample spacing must be finite and positive")
    if not np.isfinite(maximum_offset) or maximum_offset < 0:
        raise ValueError("maximum offset must be finite and nonnegative")
    if any(index < 0 or index >= len(points) for index in anchors):
        raise ValueError("anchor index is outside the line")
    if len(points) == 1:
        return SmoothedLine(points.copy(), np.zeros(1), points.copy(), 0)
    boundaries = sorted({0, len(points) - 1, *anchors})
    pieces: list[np.ndarray] = []
    references: list[np.ndarray] = []
    stations: list[np.ndarray] = []
    start_station = 0.0
    maximum = 0.0
    for begin, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        part = _reach(points[begin : end + 1], sample_spacing, maximum_offset)
        selection = slice(None) if not pieces else slice(1, None)
        pieces.append(part.points[selection])
        references.append(part.reference[selection])
        stations.append(part.source_station[selection] + start_station)
        start_station += part.source_station[-1]
        maximum = max(maximum, part.maximum_offset)
    return SmoothedLine(
        np.concatenate(pieces), np.concatenate(stations), np.concatenate(references), maximum
    )


def bounded_segments_from_graph(
    graph: ChannelGraph,
    *,
    smooth: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The chain walk of :func:`river_segments` on a :class:`ChannelGraph`.

    Chains are walked in compact table indices, so the cost is the channel cells and the lake
    cells, not the grid.  See :func:`river_segments` for the lake and regime semantics.
    """
    rec = graph.index_of(graph.receiver)
    desc = graph.index_of(graph.descend)
    is_river, is_lake, acc, month = graph.is_river, graph.is_lake, graph.acc, graph.month
    w, rows, km_per_px = graph.width, graph.rows, graph.km_per_px
    riv_idx = np.flatnonzero(is_river)
    # Spill points: a lake cell draining into a non-lake cell — the outlet chain resumes just
    # downstream of it, PREPENDED with the spill lake cell itself so the line starts one cell
    # INTO the water (the twin of the end-of-chain shore append: without it the resumed reach
    # began a cell or two off the rendered shore and read as a river starting from bare
    # ground).  Terminal lakes carry no spill cell: their equilibrium water is non-land and
    # receiver-less, so nothing resumes below them by construction.
    spill_pre: dict[int, int] = {}
    for c in np.flatnonzero(is_lake).tolist():
        r = int(rec[c])
        if r >= 0 and not is_lake[r]:
            spill_pre.setdefault(r, c)
    # Channel heads: no other channel cell drains into them.
    down = rec[riv_idx]
    incoming = np.bincount(down[down >= 0], minlength=graph.cells.size)
    has_upstream = np.zeros(graph.cells.size, dtype=bool)
    has_upstream[down[(down >= 0) & is_river[np.maximum(down, 0)]]] = True
    heads = [int(c) for c in riv_idx if not has_upstream[c]]
    heads += [c for c in spill_pre if is_river[c]]

    def cell_xyz_km(c: int) -> tuple[float, float, float]:
        # Row 0 is the NORTH edge of the canvas.  The array may be shorter than the canvas
        # square (only the chunks near land exist), so the y origin is the canvas's bottom
        # edge, not the array's: using the array height shifted every reach south by the empty
        # rows (184 km on a 104x96-cell box of a 112-cell canvas).
        g = int(graph.cells[c])
        y, x = g // w, g % w
        return (x * km_per_px, (rows - 1 - y) * km_per_px, float(acc[c]))

    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    flows: list[float] = []
    regimes: list[int] = []
    visited = np.zeros(graph.cells.size, dtype=bool)
    for head in heads:
        chain = []
        c = head
        while c >= 0 and is_river[c] and not visited[c] and not is_lake[c]:
            visited[c] = True
            chain.append(c)
            c = int(rec[c])
        n_channel = len(chain)  # channel cells only — appended cells never gate
        if head in spill_pre:
            # Resumed reach: start one cell into the lake (shore symmetry).
            chain.insert(0, spill_pre[head])
            n_channel += 1  # the spill cell is a channel-side cell, not appended
        # Always connect the chain's end to its downstream cell: the junction when a tributary
        # meets an already-traced trunk (missing this link left every tributary one segment
        # short: "broken rivers"), the sea/frame outlet, or the shore cell of the lake it ends
        # in (drawn one cell into the water so the line touches it).
        if c >= 0 and len(chain) >= 1:
            chain.append(c)
        # Terminal footprint entered: descend the pre-rewrite bathymetry across a shrunk lake's
        # dried fringe to the visible water (the cut receiver ends the walk at the basin's
        # outer edge, which read as a broken river when the water sits kilometres inside).  Dry
        # playas descend nowhere (-1) and keep the outer-edge semantics.
        if chain and is_lake[chain[-1]]:
            c = chain[-1]
            while True:
                dn = int(desc[c])
                if dn < 0 or dn == c:
                    break
                chain.append(dn)
                c = dn
        # Two cells = a legal short reach (e.g. a trunk's final step into the sea); only a
        # genuinely empty chain is dropped.
        if len(chain) < 2:
            continue
        active_chain = np.empty(len(chain), dtype=np.uint8)
        for i, cell in enumerate(chain):
            # Appended outlet/fringe cells are not new channel reaches; inherit the last real
            # channel cell's active-month count.
            active_chain[i] = month[cell] if i < n_channel else active_chain[i - 1]
        pts = np.asarray([cell_xyz_km(c) for c in chain], dtype=np.float64)
        # The appended outlet can be a sea cell (accumulation ~ 0) or a lake shore — its flow
        # coordinate must not sag at the mouth, or the final reach renders thinner than the
        # channel above it.
        np.maximum.accumulate(pts[:, 2], out=pts[:, 2])
        # One regime per inter-point reach, labelled by its upstream cell.  Adjacent runs share
        # exactly one boundary point, never a segment.
        labels = np.where(
            active_chain[:-1] >= 12,
            RIVER_REGIME_PERENNIAL,
            RIVER_REGIME_NON_PERENNIAL,
        )
        run_start = 0
        for run_end in range(1, len(labels) + 1):
            if run_end < len(labels) and labels[run_end] == labels[run_start]:
                continue
            reach = pts[run_start : run_end + 1]
            regime = int(labels[run_start])
            # Keep every original receiver vertex for constrained routing:
            # removing a node can lose a junction or a flow/regime station.
            if not smooth:
                for a, b in zip(reach[:-1], reach[1:], strict=True):
                    segs.append(((a[0], a[1]), (b[0], b[1])))
                    flows.append(float(0.5 * (a[2] + b[2])))
                    regimes.append(regime)
                run_start = run_end
                continue
            fixed = tuple(
                i
                for i in range(1, len(reach) - 1)
                if incoming[chain[run_start + i]] > 1 or is_lake[chain[run_start + i]]
            )
            if run_start == 0 and is_lake[chain[0]]:
                fixed += (1,)
            if run_end == len(labels) and (is_lake[chain[-1]] or not is_river[chain[-1]]):
                fixed += (len(reach) - 2,)
            geometry = smooth_line(
                reach[:, :2],
                sample_spacing=2.0 * km_per_px,
                maximum_offset=0.5 * km_per_px,
                anchors=fixed,
            )
            station = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(reach[:, :2], axis=0), axis=1))]
            drawn = np.column_stack(
                (geometry.points, np.interp(geometry.source_station, station, reach[:, 2]))
            )
            for a, b in zip(drawn[:-1], drawn[1:], strict=True):
                segs.append(((a[0], a[1]), (b[0], b[1])))
                flows.append(float(0.5 * (a[2] + b[2])))
                regimes.append(regime)
            run_start = run_end

    return (
        np.asarray(segs, dtype=np.float64).reshape(-1, 2, 2),
        np.asarray(flows, dtype=np.float64),
        np.asarray(regimes, dtype=np.uint8),
    )
