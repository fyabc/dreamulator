"""Depression hierarchy and Fill-Spill-Merge cascade tests."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.media.canvas_lakes import (
    build_hierarchy,
    fill_spill_merge,
    water_level,
)


def _receivers(dem: np.ndarray) -> np.ndarray:
    """Flat D8 receivers on the raw DEM (strict descent; -1 at pits/ocean)."""
    h, w = dem.shape
    rec = -np.ones(h * w, dtype=np.int64)
    for r in range(h):
        for c in range(w):
            best, best_s = -1, 0.0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    nr, nc = r + dy, c + dx
                    if 0 <= nr < h and 0 <= nc < w:
                        s = (dem[r, c] - dem[nr, nc]) / (2**0.5 if dy and dx else 1.0)
                        if s > best_s:
                            best_s, best = s, nr * w + nc
            rec[r * w + c] = best
    return rec


def _two_pits() -> np.ndarray:
    """Two parabolic bowls joined by a saddle (the lower envelope of two bowls)."""
    y, x = np.mgrid[0:9, 0:11]
    left = (x - 3.0) ** 2 + (y - 4.0) ** 2
    right = (x - 7.0) ** 2 + (y - 4.0) ** 2
    dem = 100.0 + 4.0 * np.minimum(left, right)
    dem += 0.001 * (y * 11 + x)  # unique heights, no flats
    return dem


def test_water_level_analytic() -> None:
    assert water_level(np.array([0.0, 0.0, 0.0, 0.0]), 2.0) == pytest.approx(0.5)
    # Capacity from 0 to 1 is 1 (three cells at 0..2): volume 0.5 -> level 0.5.
    z = np.array([0.0, 0.0, 1.0, 2.0])
    lvl = water_level(z, 0.5)
    assert float(np.maximum(0.0, lvl - z).sum()) == pytest.approx(0.5)


def test_hierarchy_two_pits_nested() -> None:
    dem = _two_pits()
    rec = _receivers(dem)
    hier = build_hierarchy(dem, rec, sea_level=-1e9)
    # Two leaves (the two pits) plus a parent; the parent is a closed basin.
    leaves = [n for n in hier.nodes if n.children is None]
    assert len(leaves) == 2
    parent = leaves[0].parent
    assert parent is not None and leaves[0].parent == leaves[1].parent
    # The spill is the saddle elevation; capacity is the volume below it.
    assert hier.nodes[parent].spill_m > leaves[0].pit_m


def test_fill_spill_merge_separate_then_spill_then_merge() -> None:
    dem = _two_pits()
    rec = _receivers(dem)
    hier = build_hierarchy(dem, rec, sea_level=-1e9)
    leaves = [n for n in hier.nodes if n.children is None]
    left, right = leaves
    cap_l, cap_r = left.capacity_m3, right.capacity_m3
    assert cap_l > 0 and cap_r > 0

    # Water only into the left pit; below its capacity -> left lake only.
    inflow = np.zeros(dem.size)
    inflow[left.cells] = 1.0
    total = float(inflow.sum())
    assert total < cap_l
    levels = fill_spill_merge(hier, inflow)
    assert left.id in levels and right.id not in levels
    ref = water_level(dem.ravel()[np.asarray(left.cells)], total)
    assert levels[left.id] == pytest.approx(ref)

    # More water than the left capacity -> left fills to the spill, the
    # surplus fills the right pit (geolink spill).
    inflow = np.zeros(dem.size)
    inflow[left.cells] = cap_l / len(left.cells) * 1.5
    levels = fill_spill_merge(hier, inflow)
    assert left.id in levels and right.id in levels
    assert levels[left.id] == pytest.approx(left.spill_m)
    surplus = float(inflow.sum()) - cap_l
    ref_r = water_level(dem.ravel()[np.asarray(right.cells)], surplus)
    assert levels[right.id] == pytest.approx(ref_r)

    # More than both capacities -> both full, the parent merges them.
    inflow = np.zeros(dem.size)
    inflow[left.cells] = cap_l / len(left.cells) * 3.0
    inflow[right.cells] = cap_r / len(right.cells) * 3.0
    levels = fill_spill_merge(hier, inflow)
    parent = left.parent
    assert parent is not None and parent in levels
    total = float(inflow.sum())
    body = min(total, hier.nodes[parent].capacity_m3)
    ref = water_level(dem.ravel()[np.asarray(hier.nodes[parent].cells)], body)
    assert levels[parent] == pytest.approx(ref)
    # Merged: both pits share the parent's level.
    assert levels[left.id] == pytest.approx(levels[parent])


def test_ocean_linked_pit_spills_to_sea() -> None:
    # A bowl next to a sea column; filling beyond capacity keeps the level at
    # the spill and discards the surplus.
    y, x = np.mgrid[0:9, 0:9]
    dem = 100.0 + ((y - 4.0) ** 2 + (x - 6.0) ** 2) * 5.0
    dem[:, :2] = -50.0  # sea
    rec = _receivers(dem)
    hier = build_hierarchy(dem, rec, sea_level=0.0)
    leaves = [n for n in hier.nodes if n.children is None]
    assert leaves
    # Feed 10x the deepest bowl's capacity: the level must stop at the spill.
    leaf = leaves[0]
    inflow = np.zeros(dem.size)
    inflow[leaf.cells] = leaf.capacity_m3 / max(1, len(leaf.cells)) * 10.0
    levels = fill_spill_merge(hier, inflow)
    assert leaf.id in levels
    assert levels[leaf.id] == pytest.approx(leaf.spill_m, abs=1e-6)
