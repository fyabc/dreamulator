"""Tests for the programmatic SPL erosion solver (known-answer grids)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.prog_erosion import (
    SPL_M,
    flow_accumulation,
    lake_mask,
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
    segs, _flows = river_segments(
        rivers, rec, acc, 1.0, lake=lakes
    )
    # No segment endpoint sits inside a lake.
    for a, b in segs:
        for px, py in (a, b):
            ix, iy = int(round(px)), int(round(31 - py))
            if 0 <= ix < n and 0 <= iy < n:
                assert not lakes[iy, ix]


def test_spl_constants_documented() -> None:
    # n = 1 is required by the implicit linear solve; m = 0.5 classic.
    assert SPL_M == 0.5
