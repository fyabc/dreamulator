"""Biogeographic partitioning — realm (continent) → province (biome region).

Pure mesh-level functions, no IO and no RNG.  Partitions land cells into a
two-level nested hierarchy mirroring Wallace / Udvardy realms and provinces:

- **realm**    = continental landmass (connected land cells above sea level).
- **province** = connected same-biome region within a realm.

The returned province ids use the stable ``"realm.province"`` form (1-based
within each realm), so a future civmap extension can reference them directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh


def partition_biogeographic_provinces(
    mesh: CVTMesh,
    target_provinces_per_realm: int = 1,
    min_province_cells: int = 20,
) -> tuple[list[str | None], dict[str, dict[str, object]]]:
    """Partition land cells into nested realms → biogeographic provinces.

    Parameters
    ----------
    mesh:
        CVT mesh with per-cell ``elevation``, ``biome`` and ``neighbors``
        already populated.
    target_provinces_per_realm:
        Desired province count per realm.  Same-biome connected components are
        merged (smallest → largest same-realm neighbour) until each realm holds
        at most this many provinces.
    min_province_cells:
        Provinces smaller than this (isolated islets) are folded into the
        nearest province of at least this size.  A one-cell islet ~51 km across
        is too small to be a meaningful biogeographic province — Udvardy /
        Wallace treat island chains, not individual islets, as provinces.

    Returns
    -------
    (province_ids, metadata):
        - ``province_ids``: per-cell province id (``"realm.province"``) or
          ``None`` for ocean cells.
        - ``metadata``: province id → ``{"realm": int, "biome": str,
          "cell_count": int}``.
    """
    n = mesh.num_cells
    cells = mesh.cells

    id_to_index = {c.id: i for i, c in enumerate(cells)}
    is_land = [c.elevation >= 0.0 for c in cells]

    # ---- adjacency (id → index, keep only in-range) ----
    adj: list[list[int]] = [[] for _ in range(n)]
    for i, c in enumerate(cells):
        for nid in c.neighbors:
            j = id_to_index.get(nid)
            if j is not None:
                adj[i].append(j)

    # ---- realm = connected land components ----
    realm = [-1] * n
    n_realms = 0
    for i in range(n):
        if is_land[i] and realm[i] == -1:
            realm[i] = n_realms
            stack = [i]
            while stack:
                u = stack.pop()
                for v in adj[u]:
                    if is_land[v] and realm[v] == -1:
                        realm[v] = n_realms
                        stack.append(v)
            n_realms += 1

    # ---- province = connected same-biome region within a realm ----
    prov = [-1] * n
    n_prov = 0
    for i in range(n):
        if is_land[i] and prov[i] == -1:
            biome = cells[i].biome
            prov[i] = n_prov
            stack = [i]
            while stack:
                u = stack.pop()
                for v in adj[u]:
                    if (
                        is_land[v]
                        and prov[v] == -1
                        and realm[v] == realm[i]
                        and cells[v].biome == biome
                    ):
                        prov[v] = n_prov
                        stack.append(v)
            n_prov += 1

    # ---- merge same-biome components within each realm ----
    prov_cells: list[list[int]] = [[] for _ in range(n_prov)]
    for i in range(n):
        if prov[i] != -1:
            prov_cells[prov[i]].append(i)

    # Province adjacency (same-realm boundary cell counts).  Cross-realm pairs
    # are never neighbours by construction (realms are ocean-separated).
    prov_adj: dict[int, dict[int, int]] = {}
    for i in range(n):
        pi = prov[i]
        if pi == -1:
            continue
        for v in adj[i]:
            pv = prov[v]
            if pv != -1 and pv != pi and realm[v] == realm[i]:
                prov_adj.setdefault(pi, {})[pv] = prov_adj.setdefault(pi, {}).get(pv, 0) + 1

    alive = [p for p in range(n_prov) if prov_cells[p]]
    realm_prov_count: dict[int, int] = {}
    for p in alive:
        r = realm[prov_cells[p][0]]
        realm_prov_count[r] = realm_prov_count.get(r, 0) + 1

    while True:
        # Smallest province in an over-full realm that still has a neighbour.
        candidates = [
            p
            for p in alive
            if realm_prov_count[realm[prov_cells[p][0]]] > target_provinces_per_realm
            and prov_adj.get(p)
        ]
        if not candidates:
            break
        smallest = min(candidates, key=lambda p: len(prov_cells[p]))
        target_p = max(prov_adj[smallest], key=lambda q: prov_adj[smallest][q])
        r_smallest = realm[prov_cells[smallest][0]]

        # Merge smallest → target_p.
        for u in prov_cells[smallest]:
            prov[u] = target_p
        prov_cells[target_p].extend(prov_cells[smallest])
        prov_cells[smallest] = []
        realm_prov_count[r_smallest] -= 1
        alive.remove(smallest)

        # Fold smallest's adjacency into target_p, updating both endpoints so
        # the province graph stays symmetric (a neighbour of smallest becomes a
        # neighbour of target_p on both sides).
        for q, cnt in prov_adj.pop(smallest, {}).items():
            if q == target_p:
                continue
            prov_adj.setdefault(target_p, {})[q] = prov_adj.setdefault(target_p, {}).get(q, 0) + cnt
            prov_adj.setdefault(q, {})[target_p] = prov_adj.setdefault(q, {}).get(target_p, 0) + cnt
        for q in prov_adj:
            prov_adj[q].pop(smallest, None)

    # ---- fold tiny provinces (isolated islets) into the nearest large one ----
    # Province centroids on the unit sphere.
    prov_centroid: dict[int, tuple[float, float, float]] = {}
    for p in alive:
        m = len(prov_cells[p])
        prov_centroid[p] = (
            sum(cells[u].x for u in prov_cells[p]) / m,
            sum(cells[u].y for u in prov_cells[p]) / m,
            sum(cells[u].z for u in prov_cells[p]) / m,
        )

    large = [p for p in alive if len(prov_cells[p]) >= min_province_cells]
    if large:
        for p in alive:
            if len(prov_cells[p]) >= min_province_cells:
                continue
            cx, cy, cz = prov_centroid[p]
            nearest = min(
                large,
                key=lambda q: (
                    (prov_centroid[q][0] - cx) ** 2
                    + (prov_centroid[q][1] - cy) ** 2
                    + (prov_centroid[q][2] - cz) ** 2
                ),
            )
            for u in prov_cells[p]:
                prov[u] = nearest
            prov_cells[nearest].extend(prov_cells[p])
            prov_cells[p] = []
        alive = [p for p in alive if prov_cells[p]]

    # ---- assign stable "realm.province" ids (1-based, per realm) ----
    province_ids: list[str | None] = [None] * n
    metadata: dict[str, dict[str, object]] = {}
    per_realm_counter: dict[int, int] = {}
    for p in alive:
        # Representative biome = most common biome across the province's cells.
        biome_counts: dict[str, int] = {}
        for u in prov_cells[p]:
            b = cells[u].biome
            if b is not None:
                biome_counts[b] = biome_counts.get(b, 0) + 1
        rep_biome = max(biome_counts, key=lambda b: biome_counts[b]) if biome_counts else "unknown"
        r = realm[prov_cells[p][0]]
        per_realm_counter[r] = per_realm_counter.get(r, 0) + 1
        pid = f"{r + 1}.{per_realm_counter[r]}"
        for u in prov_cells[p]:
            province_ids[u] = pid
        metadata[pid] = {
            "realm": r + 1,
            "biome": rep_biome,
            "cell_count": len(prov_cells[p]),
        }

    return province_ids, metadata
