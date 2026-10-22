"""canvas_lakes — depression hierarchy and Fill-Spill-Merge cascade (S2).

Implements the lake routing structure of Barnes, Callaghan & Wickert 2021,
"Computing water flow through complex landscapes - Part 3: Fill-Spill-Merge:
flow routing in depression hierarchies" (Earth Surface Dynamics 9:105-121):

* :func:`build_hierarchy` sweeps cells by descending elevation with a
  union-find.  A cell with no processed land neighbour opens a **leaf**
  (a simple pit); a cell that joins two distinct depressions creates an
  internal **node** whose spill elevation is the cell's elevation.  A
  component that touches the sea is marked as *ocean-linked* (its overflow
  leaves the system, the paper's oceanlink).  Every node stores the
  capacity below its spill, ``spill * n_cells - sum(dem)``.
* :func:`fill_spill_merge` routes water bottom-up in increasing spill order.
  Water that exceeds a depression's capacity first fills its sibling
  (geolink spill — captured by the pair rule below); once both siblings are
  full their parent becomes water-bearing and the two bodies **merge**.
  Surplus continues to the parent and finally to the ocean.  Each
  water-bearing node's surface level solves the paper's lake-level equation
  ``sum_i max(0, z_w - z_i) * a_i = W`` over its cells.

The skeleton keeps per-node cell lists (the production path floods each
node with the paper's priority queue instead); the geometry and routing
rules are the paper's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "DepressionHierarchy",
    "DepressionNode",
    "build_hierarchy",
    "fill_spill_merge",
    "water_level",
]


@dataclass
class DepressionNode:
    """One depression of the hierarchy (leaf = simple pit, else merged)."""

    id: int
    spill_m: float
    pit_m: float
    parent: int | None = None
    children: tuple[int, int] | None = None
    n_cells: int = 0
    dem_sum: float = 0.0
    capacity_m3: float = 0.0  # volume below spill_m
    oceanlink: bool = False  # overflow leaves the system (the sea)
    cells: list[int] = field(default_factory=list)
    water_m3: float = 0.0  # water held in this node's own body (children excluded)
    level_m: float | None = None


@dataclass
class DepressionHierarchy:
    dem: np.ndarray
    sea_level: float
    nodes: list[DepressionNode]
    root_ids: list[int]  # nodes whose overflow leaves the system
    leaf_of_cell: np.ndarray  # -1 = ocean, else the draining leaf node id


def _find(uf: list[int], a: int) -> int:
    root = a
    while uf[root] != root:
        root = uf[root]
    while uf[a] != a:
        uf[a], a = root, uf[a]
    return root


def build_hierarchy(
    dem: np.ndarray,
    receiver: np.ndarray,
    *,
    sea_level: float = 0.0,
) -> DepressionHierarchy:
    """Build the binary depression hierarchy (Barnes et al. 2021).

    ``receiver`` is the flat D8 receiver array (-1 = no receiver / ocean);
    it defines which pit each cell drains to, hence the leaf that receives
    the cell's runoff.  Use a fill with a small eps (or unique elevations)
    so flats have a deterministic descent.
    """
    h, w = dem.shape
    n = h * w
    flat = np.asarray(dem, dtype=np.float64).ravel()
    rec = np.asarray(receiver, dtype=np.int64).ravel()
    ocean = flat <= sea_level

    # Leaf of every cell: follow receivers to the terminal cell.
    leaf_of_cell = np.full(n, -1, dtype=np.int64)
    terminal_of = np.full(n, -1, dtype=np.int64)
    for c in range(n):
        if ocean[c] or terminal_of[c] >= 0:
            continue
        path = []
        cur = c
        term = cur
        for _ in range(n + 1):
            if ocean[cur] or int(rec[cur]) < 0 or int(rec[cur]) == cur:
                term = cur
                break
            path.append(cur)
            cur = int(rec[cur])
        path.append(term)
        for q in path:
            terminal_of[q] = term

    uf = list(range(n))
    comp_node: dict[int, int] = {}
    agg_n: dict[int, int] = {}
    agg_sum: dict[int, float] = {}
    active = np.zeros(n, dtype=bool)
    nodes: list[DepressionNode] = []
    pit_node_of_cell: dict[int, int] = {}
    root_ids: list[int] = []
    comp_cells: dict[int, list[int]] = {}

    def new_node(
        spill: float, pit: float, children: tuple[int, int] | None, oceanlink: bool
    ) -> int:
        node = DepressionNode(
            id=len(nodes), spill_m=spill, pit_m=pit, children=children, oceanlink=oceanlink
        )
        nodes.append(node)
        return node.id

    # Ascending elevation: low cells open pits; a higher cell that
    # joins two distinct components is their spill saddle.
    order = np.argsort(flat, kind="stable")
    for c in order:
        c = int(c)
        if ocean[c]:
            active[c] = True
            continue
        active[c] = True
        ci, cj = divmod(c, w)
        land_roots: list[int] = []
        touches_ocean = False
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < h and 0 <= nj < w):
                    continue
                nb = ni * w + nj
                if not active[nb]:
                    continue
                if ocean[nb]:
                    touches_ocean = True
                else:
                    r = _find(uf, nb)
                    if r not in land_roots:
                        land_roots.append(r)
        if not land_roots:
            # Local pit: a leaf depression.  A pit touching the sea drains
            # straight to it (zero capacity, oceanlink).
            leaf = new_node(
                spill=float(flat[c]),
                pit=float(flat[c]),
                children=None,
                oceanlink=touches_ocean,
            )
            comp_node[c] = leaf
            agg_n[c] = 1
            agg_sum[c] = float(flat[c])
            comp_cells[c] = [c]
            nodes[leaf].cells = [c]
            nodes[leaf].n_cells = 1
            nodes[leaf].dem_sum = float(flat[c])
            pit_node_of_cell[c] = leaf
            if touches_ocean:
                root_ids.append(leaf)
            continue
        main = land_roots[0]
        uf[c] = main
        agg_n[main] = agg_n.get(main, 0) + 1
        agg_sum[main] = agg_sum.get(main, 0.0) + float(flat[c])
        comp_cells.setdefault(main, []).append(c)
        for other in land_roots[1:]:
            ra, rb = _find(uf, main), _find(uf, other)
            if ra == rb:
                continue
            child_a, child_b = comp_node[ra], comp_node[rb]
            # The children's geometry is the component built so far.
            nodes[child_a].n_cells = agg_n[ra]
            nodes[child_a].dem_sum = agg_sum[ra]
            nodes[child_a].cells = list(comp_cells.get(ra, nodes[child_a].cells))
            nodes[child_b].n_cells = agg_n[rb]
            nodes[child_b].dem_sum = agg_sum[rb]
            nodes[child_b].cells = list(comp_cells.get(rb, nodes[child_b].cells))
            spill = float(flat[c])
            parent = new_node(
                spill=spill,
                pit=min(nodes[child_a].pit_m, nodes[child_b].pit_m),
                children=(child_a, child_b),
                oceanlink=False,
            )
            nodes[child_a].parent = parent
            nodes[child_b].parent = parent
            # Each merge redefines the child's spill: its final overflow is
            # the elevation of the last parent it joined.
            nodes[child_a].spill_m = spill
            nodes[child_b].spill_m = spill
            nodes[child_a].capacity_m3 = spill * nodes[child_a].n_cells - nodes[child_a].dem_sum
            nodes[child_b].capacity_m3 = spill * nodes[child_b].n_cells - nodes[child_b].dem_sum
            uf[rb] = ra
            agg_n[ra] = agg_n[ra] + agg_n[rb]
            agg_sum[ra] = agg_sum[ra] + agg_sum[rb]
            comp_cells[ra] = comp_cells.get(ra, []) + comp_cells.get(rb, [])
            nodes[parent].n_cells = agg_n[ra]
            nodes[parent].dem_sum = agg_sum[ra]
            nodes[parent].capacity_m3 = spill * agg_n[ra] - agg_sum[ra]
            nodes[parent].cells = list(comp_cells[ra])
            comp_node[ra] = parent
            main = ra
        # Propagate the ocean link: the component now drains to the sea at
        # this cell's elevation.
        root = _find(uf, main)
        node_id = comp_node[root]
        if touches_ocean:
            node = nodes[node_id]
            node.oceanlink = True
            node.spill_m = float(flat[c])
            node.n_cells = agg_n[root]
            node.dem_sum = agg_sum[root]
            node.capacity_m3 = flat[c] * node.n_cells - node.dem_sum
            if node_id not in root_ids:
                root_ids.append(node_id)
        else:
            nodes[node_id].n_cells = agg_n[root]
            nodes[node_id].dem_sum = agg_sum[root]

    # Finalise component sizes and root capacities.  A root that never spills
    # (a closed basin) has infinite capacity; an ocean-linked root spills at
    # the elevation where it met the sea.
    for root in {_find(uf, i) for i in range(n) if not ocean[i]}:
        root_node = comp_node.get(root)
        if root_node is None:
            continue
        node = nodes[root_node]
        node.n_cells = agg_n.get(root, node.n_cells)
        node.dem_sum = agg_sum.get(root, node.dem_sum)
        node.cells = list(comp_cells.get(root, node.cells))
        if node.parent is None:
            if node.oceanlink:
                node.capacity_m3 = node.spill_m * node.n_cells - node.dem_sum
            else:
                node.capacity_m3 = float("inf")
            if root_node not in root_ids:
                root_ids.append(root_node)

    # Water-routing leaf of every cell (from the receivers); the node cell
    # lists themselves come from the union-find components above.
    for c in range(n):
        if ocean[c]:
            continue
        term = int(terminal_of[c])
        leaf_id = pit_node_of_cell.get(term)
        if leaf_id is not None:
            leaf_of_cell[c] = leaf_id

    return DepressionHierarchy(
        dem=dem,
        sea_level=sea_level,
        nodes=nodes,
        root_ids=root_ids,
        leaf_of_cell=leaf_of_cell,
    )


def water_level(z: np.ndarray, volume: float, area: float = 1.0) -> float:
    """Solve ``sum(max(0, level - z_i)) * area = volume`` (paper's equation)."""
    if volume <= 0.0 or z.size == 0:
        return float(z.min()) if z.size else 0.0
    zs = np.sort(np.asarray(z, dtype=np.float64))
    acc = 0.0
    for i in range(zs.size - 1):
        v = (zs[i + 1] - zs[i]) * (i + 1) * area
        if acc + v >= volume:
            return float(zs[i] + (volume - acc) / ((i + 1) * area))
        acc += v
    return float(zs[-1] + (volume - acc) / (zs.size * area))


def fill_spill_merge(
    hierarchy: DepressionHierarchy,
    inflow: np.ndarray,
    *,
    area: float = 1.0,
) -> dict[int, float]:
    """Route water through the hierarchy (fill - spill - merge).

    ``inflow`` is the per-cell water volume.  Returns {node_id: level_m} for
    every water-bearing node.  Filling is bottom-up by spill elevation; a
    parent becomes water-bearing (its children merge into one lake) only
    when the pair's combined water reaches the pair's combined capacity.
    Surplus at an ocean-linked node leaves the system.
    """
    nodes = hierarchy.nodes
    dem_flat = np.asarray(hierarchy.dem, dtype=np.float64).ravel()
    flat = np.asarray(inflow, dtype=np.float64).ravel()

    leaf_water: dict[int, float] = {}
    for c in range(flat.size):
        leaf = int(hierarchy.leaf_of_cell[c])
        if leaf >= 0:
            leaf_water[leaf] = leaf_water.get(leaf, 0.0) + float(flat[c])

    for node in nodes:
        node.water_m3 = 0.0
        node.level_m = None

    ext: dict[int, float] = {}
    levels: dict[int, float] = {}
    order = sorted(range(len(nodes)), key=lambda i: (nodes[i].spill_m, nodes[i].id))
    for nid in order:
        node = nodes[nid]
        if node.children is None:
            total = leaf_water.get(nid, 0.0) + ext.pop(nid, 0.0)
            held = total if node.capacity_m3 <= 0 else min(total, node.capacity_m3)
            surplus = total - held
            _hold(node, held, dem_flat, area, levels)
            if surplus > 0 and node.parent is not None:
                ext[node.parent] = ext.get(node.parent, 0.0) + surplus
            # else: ocean-linked root; the surplus leaves the system
            continue
        a, b = node.children
        na, nb = nodes[a], nodes[b]
        extra_in = ext.pop(nid, 0.0)
        total = na.water_m3 + nb.water_m3 + extra_in
        pair_cap = na.capacity_m3 + nb.capacity_m3
        if total >= pair_cap:
            # Both depressions are full: the parent floods and the bodies merge.
            ring_cap = max(0.0, node.capacity_m3 - pair_cap)
            body = total
            surplus = 0.0
            if ring_cap > 0 and body > node.capacity_m3:
                surplus = body - node.capacity_m3
                body = node.capacity_m3
            _hold(node, body, dem_flat, area, levels)
            if surplus > 0 and node.parent is not None:
                ext[node.parent] = ext.get(node.parent, 0.0) + surplus
            continue
        # Separate bodies; an overflowing child fills its sibling first.
        wa = min(na.water_m3, na.capacity_m3)
        wb = min(nb.water_m3, nb.capacity_m3)
        extra = extra_in
        if extra > 0:
            if wa >= na.capacity_m3 and wb < nb.capacity_m3:
                wb = min(nb.capacity_m3, wb + extra)
            elif wb >= nb.capacity_m3 and wa < na.capacity_m3:
                wa = min(na.capacity_m3, wa + extra)
            else:
                wa = min(na.capacity_m3, wa + extra)
        _hold(na, wa, dem_flat, area, levels)
        _hold(nb, wb, dem_flat, area, levels)
        node.water_m3 = 0.0
    return levels


def _hold(
    node: DepressionNode,
    volume: float,
    dem_flat: np.ndarray,
    area: float,
    levels: dict[int, float],
) -> None:
    if volume <= 0.0:
        return
    node.water_m3 = float(volume)
    if node.cells:
        node.level_m = water_level(dem_flat[np.asarray(node.cells)], volume, area=area)
        levels[node.id] = node.level_m
        if node.children is not None:
            # A merged parent is one water body: its children share the level.
            for child in node.children:
                levels[child] = node.level_m
