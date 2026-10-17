"""Tests for the programmatic SPL erosion solver (known-answer grids)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.ndimage import binary_erosion

from dreamulator.map.prog_erosion import (
    SPL_M,
    flow_accumulation,
    heal_inland_water,
    keep_large_lakes,
    lake_mask,
    lake_mmu_cells,
    priority_flood,
    river_mask,
    river_segments,
    spl_erode,
)


def _slope_east(n: int = 32) -> tuple[np.ndarray, np.ndarray]:
    """Uniform eastward slope (sea at the east edge)."""
    y, x = np.mgrid[0:n, 0:n]
    dem = (n - 1 - x).astype(np.float64) * 10.0
    land = x < n - 1
    return dem, land


def test_priority_flood_order_downstream_first() -> None:
    dem, land = _slope_east()
    filled, order, receiver = priority_flood(dem, land)
    w = dem.shape[1]
    # Interior cells' receiver is the eastern neighbour (steepest descent).
    # Cells within 2 of the frame edge may legally route to the boundary
    # outlet instead — the window edge truncates the world.
    for cell in order:
        y, x = cell // w, cell % w
        if 2 <= y < w - 2 and 2 <= x < w - 3 and land[y, x]:
            assert receiver[cell] == y * w + (x + 1)
    # Drainage order: receivers appear before the cells they drain; a
    # receiver on the frame edge (outlet) is exempt — outlets are not
    # themselves drained.
    eff = land.copy()
    eff[0, :] = eff[-1, :] = eff[:, 0] = eff[:, -1] = False
    seen = set()
    for cell in order:
        r = receiver[cell]
        if r >= 0 and eff.reshape(-1)[r]:
            assert r in seen
        seen.add(cell)
    # No fill needed on an already-draining slope (interior; the frame-edge
    # band legally fills up to its outlet neighbour).
    interior = np.zeros_like(land)
    interior[2:-2, 2:-2] = land[2:-2, 2:-2]
    assert np.allclose(filled[interior], dem[interior], atol=1e-3)


def test_priority_flood_fills_pit_to_spill() -> None:
    # V-valley draining west to the sea, with a pit in the middle.  Frame
    # edges act as outlets too (rivers may leave the window), so the pit
    # drains either west to the sea or east out of frame — the guarantees
    # are: the flood reaches every interior land cell, filling never lowers
    # terrain, and every such cell has a receiver.
    n = 16
    _y, x = np.mgrid[0:n, 0:n]
    dem = 100.0 - 10.0 * np.abs(x - n // 2)  # valley along x
    dem[n // 2, n // 2 - 2 : n // 2 + 3] -= 40.0  # pit at row centre
    dem[:, :2] = -50.0  # western sea (base level)
    land = dem > 0.0
    interior = land.copy()
    interior[0, :] = interior[-1, :] = interior[:, 0] = interior[:, -1] = False
    filled, order, rec = priority_flood(dem, land)
    assert (order >= 0).sum() == int(interior.sum())
    assert (filled[interior] >= dem[interior] - 1e-9).all()
    assert (rec[order[order >= 0]] >= 0).all()


def test_accumulation_grows_downstream() -> None:
    dem, land = _slope_east()
    _filled, order, _rec = priority_flood(dem, land)
    weight = np.where(land, 1.0, 0.0)
    acc = flow_accumulation(order, _rec, weight)
    w = dem.shape[1]
    # Along the middle row the accumulation increases eastward.
    row = acc[n_row := dem.shape[0] // 2]
    assert (np.diff(row[:-1]) >= 0).all()
    # The last land cell of the row carries the whole upstream row; the
    # frame edge itself is an outlet and does not count as producing land.
    assert row[w - 2] == pytest.approx(land[n_row][1:-1].sum())


def test_spl_erode_cuts_channels_keeps_sea() -> None:
    dem, land = _slope_east(64)
    rain = np.where(land, 1.0, 0.0)
    h, acc = spl_erode(dem.copy(), land, rain, steps=5, dt_yr=1e5, k_spl=1e-5)
    # Sea cells untouched (base level), land only lowered (uplift = 0).
    sea = ~land
    assert np.allclose(h[sea], dem[sea])
    assert (h[land] <= dem[land] + 1e-9).all()
    # Net erosion is positive somewhere and bounded by initial relief.
    assert (dem - h)[land].max() > 0.0
    assert h.min() >= dem.min() - 1e-9
    # Accumulation is a forest: each land cell drains somewhere.
    assert (acc[land] >= rain[land]).all()


def test_river_mask_threshold() -> None:
    n = 16
    acc = np.zeros((n, n))
    acc[:, 5] = 500.0
    land = np.ones((n, n), dtype=bool)
    mask = river_mask(acc, land, threshold_cells=200)
    assert mask[:, 5].all()
    assert not mask[:, 6].any()


def test_lake_mask_and_river_chain_stops_at_lake() -> None:
    # Basin in the middle of a draining slope: the fill raises it to the
    # spill saddle → it is a lake; river chains must not cross it.
    n = 32
    _y, x = np.mgrid[0:n, 0:n]
    dem = (n - 1 - x).astype(np.float64) * 5.0  # slope to the east sea
    dem[12:20, 18:26] -= 60.0  # deep basin (below its surroundings)
    land = dem > 0.0
    dem[land & (dem < 0)] = 5.0  # keep basin floor positive
    filled, order, rec = priority_flood(dem, land)
    lakes = lake_mask(filled, dem)
    assert lakes.any()
    assert (filled[lakes] > dem[lakes] + 5.0).all()

    weight = np.where(land, 1.0, 0.0)
    acc = flow_accumulation(order, rec, weight)
    rivers = river_mask(acc, land, 10)
    segs, _flows = river_segments(rivers, rec, acc, 1.0, lake=lakes)
    # Chains END at the lake but touch the water: endpoints may sit on the
    # shore ring (one cell in), never in the eroded core — and no endpoint
    # appears beyond the lake on its far side.
    core = binary_erosion(lakes)
    for a, b in segs:
        for px, py in (a, b):
            ix, iy = int(round(px)), int(round(31 - py))
            if 0 <= ix < n and 0 <= iy < n:
                assert not core[iy, ix]


def test_lake_mmu_cells_scales_with_resolution() -> None:
    # 256 cells is the calibration on the refined 4096/550 km grid.
    assert lake_mmu_cells(550.0 / 4096) == 256
    # The pack grid (2048) resolves the same MMU in 4x fewer cells.
    assert lake_mmu_cells(550.0 / 2048) == 64


def test_heal_inland_water_small_filled_big_kept() -> None:
    # Ocean strip in the west, a 1-cell sub-sea pit and a large inland
    # below-sea-level depression: the pit is healed to land (rivers flow
    # through), the depression stays water as an endorheic terminal lake.
    n = 64
    dem = np.full((n, n), 5.0)
    dem[:, :4] = -10.0  # ocean (touches the frame edge)
    dem[30, 40] = -1.0  # single-cell inland pit
    dem[10:26, 30:46] = -5.0  # 16x16 = 256-cell inland depression
    land = dem > 0.0
    h2, land2, inland_big = heal_inland_water(dem, land, min_cells=64)
    assert land2[30, 40] and h2[30, 40] == 0.0  # pit healed to sea-level land
    assert not land2[10, 38] and inland_big[10, 38]  # depression kept as water
    assert not inland_big[:, :4].any()  # the ocean is not "inland"
    assert (land2 & ~land).sum() == 1  # exactly the one pit cell added


def test_heal_inland_water_width_and_ocean_merge() -> None:
    # At km_per_px=0.5 (min_cells=8, width gate 1.5 km = 3 px): a compact
    # depression is an endorheic lake; a same-area sliver is a river valley
    # (healed); a near-ocean compact depression merges back into the sea
    # while a far one stays; a border speck heals like any sub-MMU noise.
    n = 128
    dem = np.full((n, n), 5.0)
    dem[:, :6] = -10.0  # ocean strip (frame edge)
    dem[10:30, 90:110] = -5.0  # far compact lake (42 km causeway)
    dem[40:80, 45:47] = -5.0  # 40x2 sliver: 20 km long, 1.0 km wide
    dem[90:110, 8:28] = -5.0  # compact lake, 1.0 km causeway (merges)
    dem[0, 60:62] = -1.0  # 2-cell border speck
    land = dem > 0.0
    _h2, land2, inland_big = heal_inland_water(dem, land, 8, km_per_px=0.5, min_width_km=1.5)
    assert inland_big[20, 100]  # far compact depression stays a lake
    assert not inland_big[100, 18]  # 1-km-causeway depression merges to ocean
    assert land2[60, 46]  # sliver healed to land
    assert land2[0, 61]  # border speck healed
    assert (land2 & ~land).sum() == 2 + 80  # speck + sliver only


def test_keep_large_lakes_width_gate() -> None:
    # Two lakes of equal area (400 cells): the compact one passes, the
    # 2-km-wide sliver fails the minimum-extent gate and leaves the set.
    lake = np.zeros((128, 128), dtype=bool)
    lake[10:30, 10:30] = True  # 20x20 compact, 400 cells
    lake[40:80, 10:12] = True  # 40x2 contiguous sliver, 80 cells
    kept = keep_large_lakes(lake, 50, min_width_km=3.0, km_per_px=1.0)
    assert kept[20, 20]  # compact lake kept
    assert not kept[60, 11]  # 2-km-wide sliver dropped despite passing area


def test_river_segments_keeps_short_final_reach() -> None:
    # A trunk whose last river cell sits directly on the coast: the final
    # reach is two cells (channel + sea outlet) and must still be drawn —
    # the <3-cell drop erased whole trunks (visited cells, never redrawn).
    n = 8
    rivers = np.zeros((n, n), dtype=bool)
    rivers[3, 6] = True  # one channel cell adjacent to the eastern sea
    land = np.zeros((n, n), dtype=bool)
    land[:, :7] = True
    rec = np.full(n * n, -1, dtype=np.int64)
    rec[3 * n + 6] = 3 * n + 7  # drains into the sea
    acc = np.where(rivers, 100.0, 0.0)
    segs, flows = river_segments(rivers, rec, acc, 1.0, lake=None)
    assert len(segs) >= 1
    assert flows[0] == pytest.approx(100.0)  # mouth width not sagged to 0


def test_river_segments_flows_grow_downstream() -> None:
    # Known-answer: a bent 5-cell channel with accumulation 10..50 draining
    # into the sea.  Per-segment flows interpolate the cell accumulation
    # (sea mouth clamped to the last channel cell), so the width grading
    # grows downstream within the chain instead of one constant per chain.
    n = 8
    rivers = np.zeros((n, n), dtype=bool)
    rivers[2, 1:4] = True
    rivers[3, 4:6] = True
    land = np.zeros((n, n), dtype=bool)
    land[:, :6] = True
    rec = np.full(n * n, -1, dtype=np.int64)
    rec[2 * n + 1] = 2 * n + 2
    rec[2 * n + 2] = 2 * n + 3
    rec[2 * n + 3] = 3 * n + 4
    rec[3 * n + 4] = 3 * n + 5
    rec[3 * n + 5] = 3 * n + 6  # into the sea
    acc = np.zeros((n, n))
    acc[2, 1:4] = [10.0, 20.0, 30.0]
    acc[3, 4:6] = [40.0, 50.0]
    segs, flows = river_segments(rivers, rec, acc, 1.0)
    assert len(flows) > 5  # bent path keeps multiple segments after merge
    assert (np.diff(flows) >= -1e-9).all()  # monotone along the chain
    # Chaikin keeps the endpoint but blends the penultimate point, so the
    # final segment lands a hair under the clamped cell flow.
    assert flows[-1] == pytest.approx(50.0, abs=0.5)  # mouth not sagged to 0
    assert flows[-1] - flows[0] > 25.0  # visibly graded


def test_river_segments_crosses_submmu_lake_stops_at_big() -> None:
    # Same slope with two basins: a sub-MMU lake (between LAKE_MIN_CELLS and
    # the MMU) is crossed invisible; an MMU lake stops the chain at its shore.
    n = 128
    _y, x = np.mgrid[0:n, 0:n]
    kmpp = 0.1
    mmu = lake_mmu_cells(kmpp)
    dem = (n - 1 - x).astype(np.float64) * 5.0  # slope to the eastern sea
    dem[18:28, 48:58] -= 60.0  # 10x10 basin — sub-MMU lake
    dem[55:115, 50:110] -= 60.0  # 60x60 basin — MMU lake
    land = dem > 0.0
    filled, order, rec = priority_flood(dem, land)
    lakes = lake_mask(filled, dem)
    small = lakes[10:40, 40:60]
    big = lakes[50:120, 45:115]
    assert 64 <= small.sum() < mmu, "small basin must be a sub-MMU lake"
    assert big.sum() >= mmu, "big basin must be an MMU lake"
    acc = flow_accumulation(order, rec, np.where(land, 1.0, 0.0))
    rivers = river_mask(acc, land, 10)
    segs, _flows = river_segments(rivers, rec, acc, kmpp, lake=lakes)
    # Sub-MMU basin: the network crosses — some segment past the basin's
    # east rim (x=58) within its y band (the claiming chain may thread the
    # basin on any row of the band).
    beyond_small = any(a[0] > 60.0 * kmpp for a, _b in segs if 12 < (n - 1 - a[1] / kmpp) < 34)
    assert beyond_small, "sub-MMU lake must not break the channel"
    # MMU basin (x 50..110, y 55..115): no chain crosses the interior of
    # its MMU-scale lake.  (Fringe fragments below the MMU inside the box
    # are legitimately crossed, so restrict the interior to big components.)
    from dreamulator.map.prog_erosion import keep_large_lakes

    lakes_big = keep_large_lakes(lakes, mmu)
    core = binary_erosion(lakes_big, iterations=1)
    for a, b in segs:
        for px, py in (a, b):
            ix, iy = int(round(px / kmpp)), int(round((n - 1) - py / kmpp))
            if 0 <= ix < n and 0 <= iy < n and 50 < ix < 110 and 55 < iy < 115:
                assert not core[iy, ix], "channel crossed the MMU lake"


def test_spl_constants_documented() -> None:
    # n = 1 is required by the implicit linear solve; m = 0.5 classic.
    assert SPL_M == 0.5
