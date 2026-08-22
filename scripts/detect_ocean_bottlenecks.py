#!/usr/bin/env python3
"""Detect ocean current bottlenecks (narrow straits) on the CVT mesh.

Algorithm
---------
1. Identify the largest connected ocean basin.
2. Compute the graph diameter (farthest pair of ocean cells via BFS).
3. Walk the shortest path between the diameter endpoints; for each cell
   on the path, compute the *cross-section width* — the minimum number
   of ocean cells that must be traversed to go from one side of the
   strait to the other, perpendicular to the path direction.
4. Rank bottlenecks by cross-section width (fewer cells = narrower).

Usage
-----
    uv run python scripts/detect_ocean_bottlenecks.py [--top 10]
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np


def load_mesh(path: str) -> list[dict[str, Any]]:
    from dreamulator.map.export import decompress_mesh_bytes

    with open(path, "rb") as f:
        data = json.loads(decompress_mesh_bytes(f.read()))
    return data["cells"]


def find_largest_ocean_basin(cells: list[dict]) -> tuple[list[int], set[int]]:
    """Return (cell_indices, set) for the largest connected ocean component."""
    n = len(cells)
    visited = np.zeros(n, dtype=bool)
    largest: list[int] = []
    largest_set: set[int] = set()

    for seed in range(n):
        if visited[seed]:
            continue
        if cells[seed]["elevation"] > 0:
            visited[seed] = True
            continue

        # BFS this basin
        basin: list[int] = []
        q: deque[int] = deque([seed])
        visited[seed] = True
        while q:
            cur = q.popleft()
            basin.append(cur)
            for nid in cells[cur].get("neighbors", []):
                if 0 <= nid < n and not visited[nid] and cells[nid]["elevation"] <= 0:
                    visited[nid] = True
                    q.append(nid)

        if len(basin) > len(largest):
            largest = basin
            largest_set = set(basin)

    return largest, largest_set


def bfs_farthest(
    cells: list[dict],
    basin_set: set[int],
    start: int,
) -> tuple[int, list[int], np.ndarray]:
    """BFS from *start*; return (farthest_node, path_to_it, distances)."""
    n = len(cells)
    dist = np.full(n, -1, dtype=np.int32)
    parent = np.full(n, -1, dtype=np.int32)
    q: deque[int] = deque([start])
    dist[start] = 0

    while q:
        cur = q.popleft()
        for nid in cells[cur].get("neighbors", []):
            if 0 <= nid < n and nid in basin_set and dist[nid] == -1:
                dist[nid] = dist[cur] + 1
                parent[nid] = cur
                q.append(nid)

    farthest = int(np.argmax(dist))
    # Reconstruct path
    path = [farthest]
    while path[-1] != start and parent[path[-1]] != -1:
        path.append(int(parent[path[-1]]))
    path.reverse()
    return farthest, path, dist


def cross_section_width(
    cells: list[dict],
    basin_set: set[int],
    center: int,
    forward: int,
    max_radius: int = 20,
) -> int:
    """Width (cell count) of the strait cross-section near *center*.

    Heuristic: do a constrained BFS that only expands perpendicular to the
    forward direction.  The number of cells reachable within *max_radius*
    hops that stay within the basin is the cross-section area; the *minimum*
    width along the path is the bottleneck.
    """
    # Approximate "perpendicular" by using all neighbors except the two
    # that are roughly along the path.  Since we don't know the exact path
    # direction, just count unique cells reached in a radius-limited BFS
    # that does NOT cross land.
    n = len(cells)
    visited = np.zeros(n, dtype=bool)
    q: deque[int] = deque([center])
    visited[center] = True
    depth = {center: 0}
    count = 0

    while q:
        cur = q.popleft()
        d = depth[cur]
        if d >= max_radius:
            continue
        for nid in cells[cur].get("neighbors", []):
            if 0 <= nid < n and nid in basin_set and not visited[nid]:
                visited[nid] = True
                depth[nid] = d + 1
                q.append(nid)
                count += 1

    return count


def find_bottlenecks(
    cells: list[dict],
    basin: list[int],
    basin_set: set[int],
    top: int = 15,
) -> list[dict]:
    """Find narrowest straits in the ocean basin.

    Strategy: compute K diameter paths (via random starts), find the
    narrowest cross-section along each path, and rank by width.
    """
    # Compute K diameter pairs for better coverage
    rng = np.random.default_rng(42)
    starts = list(basin)
    rng.shuffle(starts)
    K = min(10, len(starts))
    bottlenecks: list[dict] = []

    for k in range(K):
        # First BFS: from random start to one end
        end_a, _, _ = bfs_farthest(cells, basin_set, starts[k])
        # Second BFS: from end_a to opposite end (true diameter for this pair)
        end_b, path, _ = bfs_farthest(cells, basin_set, end_a)

        # Sample the path and find narrowest cross-section
        step = max(1, len(path) // 50)
        min_width = 10**9
        best_cell = -1
        for i in range(0, len(path), step):
            w = cross_section_width(cells, basin_set, path[i], path[min(i + 1, len(path) - 1)])
            if w < min_width:
                min_width = w
                best_cell = path[i]

        # Avoid duplicates
        if best_cell >= 0:
            bottlenecks.append(
                {
                    "cell_id": cells[best_cell]["id"],
                    "lon": cells[best_cell]["lon"],
                    "lat": cells[best_cell]["lat"],
                    "elevation_m": cells[best_cell]["elevation"],
                    "cross_section_cells": min_width,
                    "path_length_hops": len(path),
                }
            )

    # Deduplicate by proximity (< 3 deg)
    bottlenecks.sort(key=lambda b: b["cross_section_cells"])
    unique: list[dict] = []
    for b in bottlenecks:
        too_close = any(
            abs(b["lon"] - u["lon"]) < 3 and abs(b["lat"] - u["lat"]) < 3
            for u in unique
        )
        if not too_close:
            unique.append(b)

    return unique[:top]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Detect ocean bottlenecks")
    parser.add_argument("mesh", nargs="?", default="data/worlds/gaia-m/maps/satellite_gaiam/cvt_mesh.json")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    print("Loading mesh...")
    cells = load_mesh(args.mesh)
    print(f"  {len(cells)} cells")

    print("Finding largest ocean basin...")
    basin, basin_set = find_largest_ocean_basin(cells)
    print(f"  {len(basin)} ocean cells in main basin")

    print("Detecting bottlenecks...")
    bottlenecks = find_bottlenecks(cells, basin, basin_set, top=args.top)

    print(f"\n{'ID':>6}  {'Lon':>8} {'Lat':>8} {'Elev(m)':>8} {'Width':>6} {'Path':>6}")
    print("-" * 55)
    for b in bottlenecks:
        print(
            f"#{b['cell_id']:>5}  {b['lon']:>8.1f} {b['lat']:>8.1f} "
            f"{b['elevation_m']:>8.0f} {b['cross_section_cells']:>6} "
            f"{b['path_length_hops']:>6}"
        )


if __name__ == "__main__":
    main()
