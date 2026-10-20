"""Tests for the programmatic SPL erosion solver (known-answer grids)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.ndimage import binary_erosion

from dreamulator.map.prog_erosion import (
    SPL_M,
    apply_terminal_equilibrium,
    flow_accumulation,
    heal_inland_water,
    hydrology_weight,
    keep_large_lakes,
    lake_mask,
    lake_mmu_cells,
    month_active_counts,
    priority_flood,
    regime_active_cells,
    river_mask,
    river_segments,
    spl_erode,
    terminal_equilibrium_routing,
    terminal_lakes,
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
    segs, _flows, _regimes = river_segments(rivers, rec, acc, 1.0, lake=lakes)
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
    segs, flows, _regimes = river_segments(rivers, rec, acc, 1.0, lake=None)
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
    segs, flows, _regimes = river_segments(rivers, rec, acc, 1.0)
    assert len(flows) > 5  # bent path keeps multiple segments after merge
    assert (np.diff(flows) >= -1e-9).all()  # monotone along the chain
    # Chaikin keeps the endpoint but blends the penultimate point, so the
    # final segment lands a hair under the clamped cell flow.
    assert flows[-1] == pytest.approx(50.0, abs=0.5)  # mouth not sagged to 0
    assert flows[-1] - flows[0] > 25.0  # visibly graded


def test_river_segments_crosses_submmu_lake_stops_at_big() -> None:
    # Same slope with two basins: a sub-MMU lake (between LAKE_MIN_CELLS and
    # the MMU) is crossed invisible; a wide flat-floored basin makes an
    # MMU + min-width lake that stops the chain at its shore.  The big
    # basin is a flat floor set deep below the surrounding slope so the
    # fill covers the whole box (river_segments gates its stop-lakes by
    # MMU AND min width — a fixture whose fill stays narrow is a
    # crossable valley, which order-derived receivers rightly cross).
    n = 128
    _y, x = np.mgrid[0:n, 0:n]
    kmpp = 0.1
    mmu = lake_mmu_cells(kmpp)
    dem = (n - 1 - x).astype(np.float64) * 5.0  # slope draining to the east frame
    dem[18:28, 48:58] -= 60.0  # 10x10 basin — sub-MMU lake
    dem[55:115, 30:80] = 10.0  # wide flat-floored bowl, rim > 200 m on all sides
    land = dem > 0.0
    filled, order, rec = priority_flood(dem, land)
    lakes = lake_mask(filled, dem)
    small = lakes[10:40, 40:60]
    big = lakes[50:120, 25:85]
    assert 64 <= small.sum() < mmu, "small basin must be a sub-MMU lake"
    assert big.sum() >= mmu, "big basin must be an MMU lake"
    acc = flow_accumulation(order, rec, np.where(land, 1.0, 0.0))
    rivers = river_mask(acc, land, 10)
    segs, _flows, _regimes = river_segments(rivers, rec, acc, kmpp, lake=lakes)
    # Sub-MMU basin: the network crosses — some segment past the basin's
    # east rim (x=58) within its y band (the claiming chain may thread the
    # basin on any row of the band).
    beyond_small = any(a[0] > 60.0 * kmpp for a, _b in segs if 12 < (n - 1 - a[1] / kmpp) < 34)
    assert beyond_small, "sub-MMU lake must not break the channel"
    # Wide basin (x 30..80, y 55..115): no chain crosses the interior of
    # its lake — gated the way river_segments gates it (MMU AND min
    # width); narrower fills are legitimately crossed as valleys.
    from dreamulator.map.prog_erosion import LAKE_MIN_WIDTH_KM, keep_large_lakes

    lakes_big = keep_large_lakes(lakes, mmu, LAKE_MIN_WIDTH_KM, kmpp)
    assert lakes_big.any(), "fixture lake must pass the width gate"
    core = binary_erosion(lakes_big, iterations=1)
    for a, b in segs:
        for px, py in (a, b):
            ix, iy = int(round(px / kmpp)), int(round((n - 1) - py / kmpp))
            if 0 <= ix < n and 0 <= iy < n and 30 < ix < 80 and 55 < iy < 115:
                assert not core[iy, ix], "channel crossed the MMU lake"


def test_spl_constants_documented() -> None:
    # n = 1 is required by the implicit linear solve; m = 0.5 classic.
    assert SPL_M == 0.5


def test_hydrology_weight_runoff_and_fallback(tmp_path) -> None:
    # Source chain: runoff channel → precipitation (legacy packs) → uniform
    # land; the land-mean normalisation keeps the threshold in "upstream
    # cells" units whatever the source (here exercised through the kron
    # upsample 8² → 16²).
    inp = tmp_path / "input"
    inp.mkdir()
    n, res = 8, 16
    land = np.ones((res, res), dtype=bool)
    from dreamulator.map.prog_erosion import RUNOFF_REFERENCE_MM

    np.save(inp / "runoff.mm.npy", np.full((n, n), 100.0, dtype=np.float32))
    weight, mean_mm, source = hydrology_weight(inp, res, land)
    assert source == "runoff"
    # The runoff source normalises by the FIXED reference (absolute
    # discharge threshold), not the window mean: 100 mm/yr land reads as
    # weight 1/3 per cell, normaliser 300.
    assert mean_mm == pytest.approx(RUNOFF_REFERENCE_MM)
    assert weight.shape == (res, res)
    assert weight[land].mean() == pytest.approx(100.0 / RUNOFF_REFERENCE_MM)
    # Legacy pack without the runoff channel falls back to precipitation.
    (inp / "runoff.mm.npy").unlink()
    np.save(inp / "precipitation.mm.npy", np.full((n, n), 200.0, dtype=np.float32))
    _w, mean_mm, source = hydrology_weight(inp, res, land)
    assert source == "precipitation"
    assert mean_mm == pytest.approx(200.0)
    # Zero runoff is an honest zero-river world under the fixed reference
    # (no division hazard) — the weight is zero everywhere.
    np.save(inp / "runoff.mm.npy", np.zeros((n, n), dtype=np.float32))
    weight, mean_mm, source = hydrology_weight(inp, res, land)
    assert source == "runoff"
    assert mean_mm == pytest.approx(RUNOFF_REFERENCE_MM)
    assert not weight.any()
    # Nothing usable: uniform land weight, normaliser 0 (balance disabled).
    (inp / "runoff.mm.npy").unlink()
    (inp / "precipitation.mm.npy").unlink()
    weight, mean_mm, source = hydrology_weight(inp, res, land)
    assert source == "uniform-land"
    assert mean_mm == 0.0
    assert (weight[land] == 1.0).all()


def test_terminal_lakes_arid_vs_humid_balance() -> None:
    # Mountain-fed trunk crossing an arid plain into a closed basin (the
    # exotic-river geometry): under a humid lake forcing the demand is
    # negative — the lake passes through and the trunk resumes past the
    # spill; under an arid forcing the equilibrium rewrite dries the basin
    # to a playa (1-cell sink), the drainage re-routes into the sink, and
    # no trunk survives below the basin.
    n = 64
    _y, x = np.mgrid[0:n, 0:n]
    dem = (n - 1 - x).astype(np.float64) * 5.0  # slope to the eastern sea
    dem[24:40, 36:52] -= 50.0  # closed basin (floor stays above sea level)
    land = dem > 0.0
    assert land[24:40, 36:52].all()
    # Runoff weight: humid headwaters in the west, dead plain elsewhere —
    # the trunk keeps its mountain water across the plain (exotic river).
    runoff = np.where(x < 22, 1.0, 0.0)
    rbar = float(runoff[land].mean())
    weight = runoff / rbar
    filled, order, rec = priority_flood(dem, land)
    lakes_draw = keep_large_lakes(lake_mask(filled, dem), lake_mmu_cells(1.0))
    assert lakes_draw.any()
    acc = flow_accumulation(order, rec, weight)

    humid = terminal_lakes(
        lakes_draw,
        rec,
        acc,
        land=land,
        precip_mm=np.full((n, n), 2100.0),
        temp_c=np.full((n, n), 10.0),
        runoff_land_mean_mm=rbar,
    )
    assert not humid.any()  # demand = PET − P < 0: pass-through by definition
    arid = terminal_lakes(
        lakes_draw,
        rec,
        acc,
        land=land,
        precip_mm=np.full((n, n), 50.0),
        temp_c=np.full((n, n), 30.0),
        runoff_land_mean_mm=rbar,
    )
    assert arid.any()

    def east_trunk_flow(segs: np.ndarray, flows: np.ndarray) -> float:
        # Largest flow among segments drawn east of the basin rim
        # (columns 36..52) within its row band.
        best = 0.0
        for (a, b), f in zip(segs, flows, strict=True):
            if any(23 < n - 1 - py < 41 and px > 52.5 for px, py in (a, b)):
                best = max(best, float(f))
        return best

    # Humid scenario: full production sequence minus the (empty) verdict.
    segs_humid, flows_humid, _regimes_humid = river_segments(
        river_mask(acc, land, 10), rec, acc, 1.0, lake=lakes_draw
    )
    # Arid scenario: verdict → equilibrium rewrite → re-route → re-accumulate.
    h2, land2, water, stats = apply_terminal_equilibrium(
        dem,
        land,
        arid,
        rec,
        acc,
        precip_mm=np.full((n, n), 50.0),
        temp_c=np.full((n, n), 30.0),
        runoff_land_mean_mm=rbar,
        mmu_cells=lake_mmu_cells(1.0),
        sea_level_m=0.0,
    )
    assert stats["shrunk"] == 0
    # Every dry playa keeps exactly its 1-cell sink (the frame-edge fill
    # fringe may register extra arid components).
    assert int(water.sum()) == stats["dry_playas"] >= 1
    _f2, order2, rec2 = priority_flood(h2, land2)
    acc2 = flow_accumulation(order2, rec2, weight)
    segs_arid, flows_arid, _regimes_arid = river_segments(
        river_mask(acc2, land2, 10), rec2, acc2, 1.0, lake=water
    )
    assert east_trunk_flow(segs_humid, flows_humid) > 15.0, "pass-through lake resumes the trunk"
    assert east_trunk_flow(segs_arid, flows_arid) == 0.0, "dry playa ends the trunk"


def test_terminal_lake_at_frame_edge_stays_passthrough() -> None:
    # A lake component touching the frame edge has its catchment truncated
    # by the window — the verdict is forced pass-through regardless of the
    # balance (here arid enough to be terminal were it interior).
    n = 16
    lake = np.zeros((n, n), dtype=bool)
    lake[5:9, 0:4] = True  # touches the west frame edge
    land = np.ones((n, n), dtype=bool)
    land[lake] = False
    rec = np.full(n * n, -1, dtype=np.int64)
    for y in range(5, 9):  # land east of the lake drains into it
        rec[y * n + 4] = y * n + 3
    acc = np.zeros((n, n))
    acc[5:9, 4] = 100.0
    term = terminal_lakes(
        lake,
        rec,
        acc,
        land=land,
        precip_mm=np.zeros((n, n)),
        temp_c=np.full((n, n), 30.0),
        runoff_land_mean_mm=1.0,
    )
    assert not term.any()


def test_apply_terminal_equilibrium_dry_and_shrunk() -> None:
    # Hand-built 16x16 with two lakes: a poorly fed one (A* < MMU → dry
    # playa; the deepest cell stays a 1-cell non-land sink) and a well-fed
    # one (A* rounds to 3 cells of equilibrium water; the exposed floor
    # becomes land, below-sea floors raised to sea level).
    n = 16
    h = np.full((n, n), 10.0)
    land = np.ones((n, n), dtype=bool)
    lake = np.zeros((n, n), dtype=bool)
    lake[2:6, 2:6] = True  # 16 cells, flat floor at 5 m
    h[2:6, 2:6] = 5.0
    lake[8:12, 8:12] = True  # 16 cells; three deepest at −5 m, rest at −3 m
    h[8, 8] = h[8, 9] = h[9, 8] = -5.0
    rest = lake[8:12, 8:12] & (h[8:12, 8:12] == 10.0)
    h[8:12, 8:12][rest] = -3.0
    rec = np.full(n * n, -1, dtype=np.int64)
    rec[2 * n + 1] = 2 * n + 2  # one feeder into lake A
    rec[8 * n + 7] = 8 * n + 8  # one feeder into lake B
    acc = np.zeros((n, n))
    acc[2, 1] = 10.0
    acc[8, 7] = 4000.0
    h2, land2, water, stats = apply_terminal_equilibrium(
        h,
        land,
        lake,
        rec,
        acc,
        precip_mm=np.zeros((n, n)),
        temp_c=np.full((n, n), 30.0),  # PET ≈ 1828 mm/yr
        runoff_land_mean_mm=1.0,
        mmu_cells=2,
        sea_level_m=0.0,
    )
    assert stats == {"terminal": 2, "dry_playas": 1, "shrunk": 1}
    # Lake A: dry playa — one sink cell (stable argsort picks the first,
    # (2, 2), on the flat floor), everything else stays land at its floor.
    assert water[2:6, 2:6].sum() == 1 and water[2, 2]
    assert land2[2:6, 2:6].sum() == 15 and h2[3, 3] == 5.0
    # Lake B: A* = 4000/1828 ≈ 2.19 → 3 deepest cells of water; the exposed
    # below-sea floor raised to sea level, becoming land.
    assert water[8, 8] and water[8, 9] and water[9, 8] and water[8:12, 8:12].sum() == 3
    assert not land2[8, 8]
    exposed = lake[8:12, 8:12] & ~water[8:12, 8:12]
    assert land2[8:12, 8:12][exposed].all()
    assert (h2[8:12, 8:12][exposed] == 0.0).all()  # raised from −3 m to sea level
    assert h2[8, 8] == -5.0  # the water cells keep their floor


def test_terminal_lakes_counts_lake_chain_inflow() -> None:
    # Regression (2026-10-17): a pass-through lake spilling DIRECTLY into a
    # smaller basin delivers its whole upstream accumulation via its spill
    # cell — the spill cell is itself a lake cell, so counting only land
    # donors starved the downstream basin (a 164 m³/s trunk once "ended" at
    # an invisible playa this way on the 21.5N/95.5E sheet).
    n = 16
    lake = np.zeros((n, n), dtype=bool)
    lake[5:8, 3:6] = True  # lake A (upstream, pass-through)
    lake[5:8, 7:10] = True  # lake B (downstream, would dry without chain inflow)
    land = np.ones((n, n), dtype=bool)
    rec = np.full(n * n, -1, dtype=np.int64)
    rec[5 * n + 1] = 5 * n + 3  # land feeder → lake A
    rec[6 * n + 5] = 6 * n + 7  # lake A spills east into lake B (adjacent)
    acc = np.zeros((n, n))
    acc[5, 1] = 1000.0
    acc[6, 5] = 1000.0  # A's spill cell carries the whole trunk
    temp = np.full((n, n), 20.0)  # PET ≈ 1045 mm/yr
    precip = np.zeros((n, n))
    term = terminal_lakes(
        lake,
        rec,
        acc,
        land=land,
        precip_mm=precip,
        temp_c=temp,
        runoff_land_mean_mm=1.0,
    )
    # demand ≈ 1045 × 9 cells ≈ 9.4k mm·cells < inflow 1000 mm·cells? No:
    # 1000 × 1.0 = 1000 < 9405 → BOTH would be terminal by that margin.
    # Give the chain more water: the assertion below pins the accounting —
    # B's inflow must include A's spill, i.e. B's verdict follows the chain.
    acc2 = np.zeros((n, n))
    acc2[5, 1] = 20000.0
    acc2[6, 5] = 20000.0
    term2 = terminal_lakes(
        lake,
        rec,
        acc2,
        land=land,
        precip_mm=precip,
        temp_c=temp,
        runoff_land_mean_mm=1.0,
    )
    assert not term2[5:8, 3:6].any(), "A stays pass-through"
    # Without the chain inflow B would dry (inflow 0 < demand 9.4k); with it
    # (20k > 9.4k) B overflows — the spill cell's acc must have been counted.
    assert not term2[5:8, 7:10].any(), "lake-chain inflow keeps B pass-through"
    assert term[5:8, 7:10].all() or not term[5:8, 7:10].any()  # first variant sanity


def test_lake_fringe_descend_walks_to_water() -> None:
    # A cone-shaped basin (pit at the centre): the descent tree inside a
    # water-bearing footprint must strictly descend to the kept water and
    # self-loop there; a dry footprint (no visible water) descends nowhere.
    from dreamulator.map.prog_erosion import lake_fringe_descend

    n = 13
    yy, xx = np.mgrid[0:n, 0:n]
    h = 2.0 * np.hypot(yy - 6, xx - 6)
    footprint = h <= 6.0  # one connected basin around the pit
    water = h <= 2.0  # the equilibrium surface (deepest cells)
    desc = lake_fringe_descend(h, footprint, water)
    w = n
    c = 6 * w + 9  # eastern fringe cell (distance 3, inside the footprint)
    assert desc[c] >= 0
    path_h = [h.reshape(-1)[c]]
    while True:
        d = int(desc[c])
        if d < 0 or d == c:
            break
        path_h.append(h.reshape(-1)[d])
        c = d
    assert (np.diff(path_h) < 0).all()  # strict descent, no cycles
    assert water.reshape(-1)[c]  # the walk ends one cell into the water
    assert desc[c] == c  # water cells self-loop
    # Dry playa: the same basin with no kept water has no descent at all.
    dry = lake_fringe_descend(h, footprint, np.zeros_like(water))
    assert (dry < 0).all()


def test_river_segments_extends_shrunk_fringe_to_water() -> None:
    # Regression (2026-10-17, 21.5N/95.5E sheet): a river meeting a shrunk
    # lake's footprint at the basin edge stopped there, leaving a ~2.5 km
    # gap to the visible water inside.  With the fringe descent tree the
    # chain crosses the dried fringe and ends one cell into the water;
    # without it (legacy) the chain still stops at the outer edge.
    n = 8
    rivers = np.zeros((n, n), dtype=bool)
    rivers[3, 1:4] = True
    rec = np.full(n * n, -1, dtype=np.int64)
    rec[3 * n + 1] = 3 * n + 2
    rec[3 * n + 2] = 3 * n + 3
    rec[3 * n + 3] = 3 * n + 4  # drains into the footprint's edge cell
    acc = np.zeros((n, n))
    acc[3, 1:4] = [10.0, 20.0, 30.0]
    footprint = np.zeros((n, n), dtype=bool)
    footprint[1:7, 4:7] = True  # compact terminal basin (passes MMU gates)
    # Fringe descent: edge cell → dried fringe → water (self-loop at col 6).
    desc = np.full(n * n, -1, dtype=np.int64)
    desc[3 * n + 4] = 3 * n + 5
    desc[3 * n + 5] = 3 * n + 6
    desc[3 * n + 6] = 3 * n + 6
    segs_new, flows_new, _regimes_new = river_segments(
        rivers, rec, acc, 1.0, lake=footprint, lake_descend=desc
    )
    xmax_new = max(max(a[0], b[0]) for a, b in segs_new)
    assert xmax_new == pytest.approx(6.0)  # reaches the water cell
    # The merged straight reach interpolates its endpoint flows (10 → 30,
    # clamped at the mouth) — the check is that it never sags to zero.
    assert flows_new[-1] >= 10.0
    segs_old, _, _regimes_old = river_segments(rivers, rec, acc, 1.0, lake=footprint)
    xmax_old = max(max(a[0], b[0]) for a, b in segs_old)
    assert xmax_old == pytest.approx(4.0)  # legacy: stops at the basin edge


def test_month_active_counts_independent_active_rule() -> None:
    # Two cells draining 0 → 1.  With reference 1 mm and active rule 1,
    # uniform 1 mm/month is active at both cells all year; the same annual
    # water in two months gives two active months.  This rule is independent
    # of the annual cartographic threshold.
    land = np.ones((1, 2), dtype=bool)
    rec = np.array([1, -1], dtype=np.int64)
    order = np.array([1, 0], dtype=np.int64)  # downstream first
    uniform = np.ones((1, 2, 12), dtype=np.float64)
    counts = month_active_counts(order, rec, uniform, land, 1.0, reference_mm=1.0)
    assert counts.tolist() == [[12, 12]]
    # At active rule 2 the head (accumulation 1) is inactive while the mouth
    # (accumulation 2) remains active.
    counts_high = month_active_counts(order, rec, uniform, land, 2.0, reference_mm=1.0)
    assert counts_high.tolist() == [[0, 12]]
    seasonal = np.zeros((1, 2, 12), dtype=np.float64)
    seasonal[..., 3:5] = 6.0
    counts_seasonal = month_active_counts(order, rec, seasonal, land, 1.0, reference_mm=1.0)
    assert counts_seasonal.tolist() == [[2, 2]]
    zeros = month_active_counts(order, rec, np.zeros_like(uniform), land, 1.0)
    assert not zeros.any()


def test_regime_active_cells_roundtrip_discharge() -> None:
    # The accumulation-unit conversion must recover the same monthly-mean
    # discharge at every grid resolution.
    for km_pp in (0.1, 0.2):
        cells = regime_active_cells(km_pp)
        seconds_per_month = 365.25 * 86400.0 / 12.0
        discharge = cells * 0.3 * (km_pp * 1000.0) ** 2 / seconds_per_month
        assert discharge == pytest.approx(0.001)


def test_river_segments_regime_is_reach_based() -> None:
    # Contiguous cells form independent perennial/non-perennial reaches; one
    # dry headwater cell no longer downgrades the whole chain.  The appended
    # downstream outlet does not create an extra reach.
    n = 8
    rivers = np.zeros((n, n), dtype=bool)
    rivers[3, 1:4] = True
    rec = np.full(n * n, -1, dtype=np.int64)
    rec[3 * n + 1] = 3 * n + 2
    rec[3 * n + 2] = 3 * n + 3
    rec[3 * n + 3] = 3 * n + 4
    acc = np.zeros((n, n))
    acc[3, 1:4] = [10.0, 20.0, 30.0]
    month_active = np.zeros((n, n), dtype=np.uint8)
    month_active[3, 1:4] = 12
    _s, _f, perennial = river_segments(rivers, rec, acc, 1.0, month_active=month_active)
    assert len(perennial) and (perennial == 0).all()
    month_active[3, 2] = 3
    _s, _f, reaches = river_segments(rivers, rec, acc, 1.0, month_active=month_active)
    assert reaches.tolist() == [0, 1, 0]
    _s, _f, legacy = river_segments(rivers, rec, acc, 1.0)
    assert (legacy == 0).all()


def _bowl_dem(n: int = 96) -> tuple[np.ndarray, np.ndarray]:
    """East slope with a wide deep flat-floored bowl mid-west."""
    _y, x = np.mgrid[0:n, 0:n]
    dem = (n - 1 - x).astype(np.float64) * 5.0
    dem[30:60, 30:60] = 5.0  # flat floor far below the >150 m rim
    return dem, dem > 0.0


def test_fill_receiver_routes_to_spill() -> None:
    # Order-derived receivers (todo ⑤): the chain entering a fill must cut
    # across the interior to the spill — the discovery chain — instead of
    # hugging the shoreline.  Bowl mid-west, entry at mid-row on the west
    # rim: the receiver walk stays near that row and exits on the east
    # (spill) side; a rim walk would detour along the north/south shore.
    n = 96
    dem, land = _bowl_dem(n)
    filled, order, rec = priority_flood(dem, land)
    lakes = lake_mask(filled, dem)
    assert lakes[30:60, 30:60].all()
    r2 = rec.reshape(n, n)
    assert r2[45, 29] == 45 * n + 30  # descends into the fill
    rows, cols = [], []
    c = 45 * n + 30
    for _ in range(400):
        y, x = c // n, c % n
        rows.append(y)
        cols.append(x)
        c = int(rec[c])
        if c < 0 or not lakes[c // n, c % n]:
            break
    assert max(cols) >= 58, "path must reach the east (spill) side of the fill"
    # Discovery chains weave (diagonal merges): +/-8 on a 30-row fill is a
    # crossing; a rim walk rides the boundary at +/-15.
    assert max(abs(np.asarray(rows) - 45)) <= 8, "path must cut across, not hug the rim"


def test_receiver_order_topological() -> None:
    # The discovery-predecessor tie-break keeps the receiver forest acyclic
    # and consistent with the pop order (flow_accumulation's contract).
    n = 96
    dem, land = _bowl_dem(n)
    dem[10:20, 10:20] -= 30.0  # a second, smaller depression
    _f, order, rec = priority_flood(dem, land)
    pos = np.full(n * n, -1, dtype=np.int64)
    for a, c in enumerate(order):
        if c >= 0:
            pos[c] = a
    for a in np.nonzero(order >= 0)[0]:
        cell = int(order[a])
        r = int(rec[cell])
        if r >= 0:
            assert pos[r] < pos[cell], "receiver must pop before the cell it drains"


def test_ordinary_terrain_receiver_unchanged() -> None:
    # Zero-regression: on a depressionless slope the predecessor never ties
    # the true gradient, and the receiver equals plain steepest descent on
    # the filled surface (the pre-change behaviour).
    dem, land = _slope_east(48)
    filled, _order, rec = priority_flood(dem, land)
    h, w = dem.shape
    ref = np.full(h * w, -1, dtype=np.int64)
    dist_card, dist_diag = 1.0, np.sqrt(2.0)
    for y in range(h):
        for x in range(w):
            if not land[y, x]:
                continue
            f0 = filled[y, x]
            best, best_slope = -1, 0.0
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w:
                        fj = filled[ny, nx]
                        if land[ny, nx] and fj >= f0:
                            continue
                        dist = dist_diag if (dx != 0 and dy != 0) else dist_card
                        slope = (f0 - fj) / dist
                        if slope > best_slope:
                            best_slope, best = slope, ny * w + nx
            ref[y * w + x] = best
    mask = land.reshape(-1) & (rec >= 0)
    assert (rec[mask] == ref[mask]).all()


def test_hydrology_weight_precip_gated_by_pet(tmp_path) -> None:
    # Todo ⑤ headwater gate: on the precipitation fallback, cells without a
    # water surplus (P <= PET_hamon) carry zero weight — rivers cannot
    # start in the arid east.
    n = 64
    half = n // 2
    _y, x = np.mgrid[0:half, 0:half]
    land = np.ones((n, n), dtype=bool)
    precip = np.where(x < half // 2, 2500.0, 50.0)
    temp = np.where(x < half // 2, 10.0, 30.0)
    np.save(tmp_path / "precipitation.mm.npy", precip)
    np.save(tmp_path / "temperature.C.npy", temp)
    weight, norm_mm, source = hydrology_weight(tmp_path, n, land)
    assert source == "precipitation"
    assert norm_mm > 0.0
    # Kron-upsampled arid east: zero weight; wet west: positive.
    assert (weight[:, half + 2 :] == 0.0).all()
    assert (weight[:, : half // 2 - 1] > 0.0).all()


def test_terminal_routing_emits_lake_records() -> None:
    # The spill/verdict record closes the "rim/spill 不落盘" gap: every
    # drawn lake gets a verdict, and pass-through lakes carry their spill.
    n = 64
    _y, x = np.mgrid[0:n, 0:n]
    dem = (n - 1 - x).astype(np.float64) * 5.0
    dem[24:40, 36:52] -= 50.0
    land = dem > 0.0
    runoff = np.where(x < 22, 1.0, 0.0)
    rbar = float(runoff[land].mean())
    filled, order, rec = priority_flood(dem, land)
    lakes_draw = keep_large_lakes(lake_mask(filled, dem), lake_mmu_cells(1.0))
    assert lakes_draw.any()
    common = dict(
        weight=runoff / rbar,
        precip_mm=np.full((n, n), 2100.0),
        temp_c=np.full((n, n), 10.0),
        runoff_land_mean_mm=rbar,
        mmu_cells=lake_mmu_cells(1.0),
        km_per_px=1.0,
        sea_level_m=0.0,
    )
    _h, _l, _lr, _cs, _fd, _rr, _acc, _tw, _st, records = terminal_equilibrium_routing(
        dem, land, lakes_draw, order, rec, **common
    )
    assert len(records) >= 1
    # The bowl is the component spilling on its east rim (rows 24..40);
    # frame-corner fill fringes may appear as extra small components.
    bowl = [r for r in records if r["spill_cell"] and 24 <= r["spill_cell"][0] <= 40]
    assert bowl, "fixture bowl must be recorded"
    assert bowl[0]["verdict"] == "passthrough"  # humid forcing: demand < 0
    assert bowl[0]["spill_elev_m"] > 0.0
    assert bowl[0]["inflow_mm"] > 0.0
    # Arid forcing: the same geometry dries to a terminal verdict.
    arid = dict(common, precip_mm=np.full((n, n), 50.0), temp_c=np.full((n, n), 30.0))
    _h2, _l2, _lr2, _cs2, _fd2, _rr2, _acc2, _tw2, _st2, records2 = terminal_equilibrium_routing(
        dem, land, lakes_draw, order, rec, **arid
    )
    assert any(r["verdict"] in ("terminal", "dry_playa", "shrunk") for r in records2)
    # A* consistency invariant (label-remap regression, 2026-10-18): every
    # terminal-class lake keeps at most ceil(inflow/demand × draw) cells —
    # the pre-fix label mismatch kept whole lakes at ~8% of their balance.
    for r in records2:
        if r["verdict"] in ("terminal", "dry_playa", "shrunk"):
            cap = math.ceil(r["inflow_mm"] / r["demand_mm"] * r["draw_cells"]) + 1
            assert r["kept_water_cells"] <= cap, (r["label"], r["kept_water_cells"], cap)
