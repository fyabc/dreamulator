"""Out-of-core S2 flow fields against the in-memory oracle (canvas_flow_fields)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_hydrology import _NEIGHBOURS
from dreamulator.media.canvas_pipeline import CanvasStore, canvas_flow_fields, run_canvas_fill

if TYPE_CHECKING:
    from pathlib import Path

T = 128


def _make_canvas(root: Path, missing: tuple[int, int] | None) -> None:
    """4x4 chunks: tilted slope, a wide pit across the central seams (a flat lake), a sea band."""
    geom = CanvasGeometry(10.0, 20.0, 6816.97, 4)
    keys = [(i, j) for i in range(4) for j in range(4) if (i, j) != missing]
    (root / "chunks").mkdir(parents=True)
    (root / "climate").mkdir()
    g = geom.to_dict()
    g["chunk_px"] = T
    (root / "canvas.json").write_text(
        json.dumps({"geometry": g, "chunks": [list(k) for k in keys]}), encoding="utf-8"
    )
    px = geom.px_km
    for ci, cj in keys:
        r = np.arange(T, dtype=np.float64)[:, None]
        c = np.arange(T, dtype=np.float64)[None, :]
        x = -geom.half_km + (cj * T + c + 0.5) * px
        y = geom.half_km - (ci * T + r + 0.5) * px
        x0 = -geom.half_km + 2 * T * px  # the middle of the 4 x 4 chunks: the pit spans four
        y0 = geom.half_km - 2 * T * px
        dem = 300.0 + 0.35 * (x - x0) + 0.20 * (y - y0)
        dem -= 120.0 * np.exp(-(((x - x0) ** 2 + (y - y0) ** 2) / (2 * 6.0**2)))
        dem = np.where(y - y0 < -14.0, -40.0, dem)
        np.save(root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy", dem.astype(np.int16))
    n = geom.ncell
    yy, xx = np.mgrid[0:n, 0:n]
    np.save(root / "climate" / "runoff.mm.npy", (100.0 + 20.0 * xx + 7.0 * yy).astype(np.float32))
    np.save(root / "climate" / "precipitation.mm.npy", np.full((n, n), 900.0, dtype=np.float32))
    np.save(root / "climate" / "temperature.C.npy", np.full((n, n), 22.0, dtype=np.float32))


@pytest.mark.parametrize(
    ("missing", "workers", "start"),
    [(None, 1, "fork"), ((1, 2), 1, "fork"), ((1, 2), 3, "fork"), (None, 3, "spawn")],
)
def test_tiled_flow_fields_match_the_in_memory_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: tuple[int, int] | None,
    workers: int,
    start: str,
) -> None:
    from dreamulator.map.prog_erosion import flow_accumulation
    from dreamulator.media.canvas_flow_tiled import (
        load_chunk,
        tiled_accumulation,
        tiled_directions,
        tiled_graded,
    )

    monkeypatch.setenv("DREAMULATOR_START_METHOD", start)
    root = tmp_path / "canvas"
    root.mkdir()
    _make_canvas(root, missing)
    store = CanvasStore.load(root)
    run_canvas_fill(store, verbose=False, workers=1)
    graded, _dem, rec, _acc, land, order, weight, _inland = canvas_flow_fields(store)
    h, w = graded.shape

    def part(a: np.ndarray, key: tuple[int, int]) -> np.ndarray:
        return a[key[0] * T : (key[0] + 1) * T, key[1] * T : (key[1] + 1) * T]

    # a flat crossing the seams exists (the filled pit): grading changes cells there
    final = np.full((h, w), np.nan, np.float32)
    for ci, cj in store.chunks:
        part(final, (ci, cj))[:] = np.load(store.path("final", ci, cj, "i16.npy"))
    assert (graded != final)[np.isfinite(final)].any()

    rounds = tiled_graded(store, workers=workers)
    assert rounds >= 2  # the seam exchange took part
    tiled_directions(store, workers=workers)
    tiled_accumulation(store, "w_runoff", workers=workers)
    oracle = flow_accumulation(order, rec, weight.astype(np.float64).ravel()).reshape(h, w)
    rr, cc = np.mgrid[0:T, 0:T]
    for key in store.chunks:
        assert np.array_equal(load_chunk(store, "graded", key), part(graded, key))
        assert np.array_equal(load_chunk(store, "land", key).astype(bool), part(land, key))
        assert np.array_equal(load_chunk(store, "w_runoff", key), part(weight, key))
        code = load_chunk(store, "dir", key)
        got = np.full((T, T), -1, dtype=np.int64)
        for k, (dy, dx) in enumerate(_NEIGHBOURS):
            m = code == k
            got[m] = (key[0] * T + rr[m] + dy) * w + (key[1] * T + cc[m] + dx)
        assert np.array_equal(got, part(rec.reshape(h, w), key))
        a = load_chunk(store, "acc_w_runoff", key).astype(np.float64)
        assert np.allclose(a, part(oracle, key).astype(np.float32), rtol=1e-6, atol=0)
    assert oracle.max() > 50 * weight.max()  # rivers do cross chunks


@pytest.mark.parametrize(("missing", "workers"), [(None, 1), ((0, 3), 3)])
def test_tiled_lakes_match_the_in_memory_oracle(
    tmp_path: Path, missing: tuple[int, int] | None, workers: int
) -> None:
    from scipy import ndimage

    from dreamulator.map.prog_erosion import lake_mmu_cells, renderable_lakes
    from dreamulator.media.canvas_flow_tiled import load_chunk, tiled_graded
    from dreamulator.media.canvas_lakes_tiled import tiled_geometry_lakes

    root = tmp_path / "canvas"
    root.mkdir()
    _make_canvas(root, missing)
    store = CanvasStore.load(root)
    run_canvas_fill(store, verbose=False, workers=1)
    graded, dem, _rec, _acc, _land, _order, _w, inland = canvas_flow_fields(store)
    km = store.geometry.px_km
    mmu = lake_mmu_cells(km)
    lakes = renderable_lakes(graded, dem, inland, mmu, km)
    lbl, n = ndimage.label(lakes)
    assert n >= 1 and lbl.max() == n

    tiled_graded(store, workers=workers)
    comps = tiled_geometry_lakes(store, mmu, km, workers=workers)
    assert comps.count == n
    sizes = np.bincount(lbl.ravel(), minlength=n + 1)
    assert np.array_equal(comps.size[1:], sizes[1:])
    for ci, cj in store.chunks:
        sl = np.s_[ci * T : (ci + 1) * T, cj * T : (cj + 1) * T]
        assert np.array_equal(load_chunk(store, "lakes0", (ci, cj)).astype(bool), lakes[sl])
        assert np.array_equal(load_chunk(store, "lbl_lakes0", (ci, cj)), lbl[sl])


def _terminal_oracle(  # type: ignore[no-untyped-def]
    store: CanvasStore, precip: np.ndarray, temp: np.ndarray, ow: np.ndarray
):
    from dreamulator.map.prog_erosion import (
        RUNOFF_REFERENCE_MM,
        lake_mmu_cells,
        renderable_lakes,
        terminal_equilibrium_routing,
    )
    from dreamulator.map.td_canvas import PX_PER_CELL

    graded, dem, rec, _acc, land, order, weight, inland = canvas_flow_fields(store)
    km = store.geometry.px_km
    mmu = lake_mmu_cells(km)
    lakes0 = renderable_lakes(graded, dem, inland, mmu, km)
    w = weight.ravel().copy()
    out = terminal_equilibrium_routing(
        dem, land, lakes0, order, rec.copy(), w,
        precip_mm=precip, temp_c=temp, runoff_land_mean_mm=RUNOFF_REFERENCE_MM,
        mmu_cells=mmu, km_per_px=km, sea_level_m=0.0, climate_block=PX_PER_CELL,
        open_water_mm=ow, keep_rewritten_h=False,
    )  # fmt: skip
    return out, w.reshape(graded.shape), lakes0, mmu, km


def _make_lakes_canvas(
    root: Path, runoff_west: float, evaporation_east: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Three pits on an eastward slope to the sea; the middle pit spans four chunks.

    Runoff is high in the west climate column, lake evaporation high in the east one, so the
    lakes cascade west to east and the eastern ones can go terminal.
    """
    geom = CanvasGeometry(10.0, 20.0, 6816.97, 4)
    keys = [(i, j) for i in range(4) for j in range(4)]
    (root / "chunks").mkdir(parents=True)
    (root / "climate").mkdir()
    g = geom.to_dict()
    g["chunk_px"] = T
    (root / "canvas.json").write_text(
        json.dumps({"geometry": g, "chunks": [list(k) for k in keys]}), encoding="utf-8"
    )
    px = geom.px_km
    width = 4 * T * px
    for ci, cj in keys:
        r = np.arange(T, dtype=float)[:, None]
        c = np.arange(T, dtype=float)[None, :]
        x = (cj * T + c + 0.5) * px
        y = (ci * T + r + 0.5) * px
        dem = 600.0 - 12.0 * x + 3.0 * np.abs(y - width / 2)
        for xc in (0.24 * width, 0.5 * width, 0.74 * width):
            dem -= 70.0 * np.exp(-((x - xc) ** 2 + (y - width / 2) ** 2) / (2 * 2.5**2))
        dem = np.where(x > 0.92 * width, -40.0, dem)
        np.save(root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy", dem.astype(np.int16))
    n = 4
    runoff = np.full((n, n), 2.0, dtype=np.float32)
    runoff[:, 0] = runoff_west
    precip = np.full((n, n), 100.0)
    precip[:, 0] = 900.0
    ow = np.full((n, n), evaporation_east)
    ow[:, 0] = 1000.0
    temp = np.full((n, n), 24.0)
    np.save(root / "climate" / "runoff.mm.npy", runoff)
    np.save(root / "climate" / "precipitation.mm.npy", precip.astype(np.float32))
    np.save(root / "climate" / "temperature.C.npy", temp.astype(np.float32))
    return precip, temp, ow


@pytest.mark.parametrize(
    ("case", "runoff_west", "evaporation_east"),
    [("cascade", 200.0, 2500.0), ("shrunk", 100.0, 4000.0), ("playa", 25.0, 2500.0)],
)
def test_tiled_terminal_routing_matches_the_in_memory_oracle(
    tmp_path: Path, case: str, runoff_west: float, evaporation_east: float
) -> None:
    from dreamulator.map.prog_erosion import RUNOFF_REFERENCE_MM
    from dreamulator.map.td_canvas import PX_PER_CELL
    from dreamulator.media.canvas_flow_tiled import (
        load_chunk,
        tiled_accumulation,
        tiled_directions,
        tiled_graded,
    )
    from dreamulator.media.canvas_lakes_tiled import tiled_geometry_lakes
    from dreamulator.media.canvas_terminal_tiled import tiled_terminal_routing

    root = tmp_path / "canvas"
    root.mkdir()
    precip, temp, ow = _make_lakes_canvas(root, runoff_west, evaporation_east)
    store = CanvasStore.load(root)
    run_canvas_fill(store, verbose=False, workers=1)
    oracle, w_dep, lakes0, mmu, km = _terminal_oracle(store, precip, temp, ow)
    h_rw, land2, render, chain, desc, rec_route, _acc, water, stats, records = oracle
    assert len(records) == 3 and sum(r["downstream_label"] > 0 for r in records) >= 1
    expect = {"cascade": "passthrough", "shrunk": "shrunk", "playa": "dry_playa"}[case]
    assert any(r["verdict"] == expect for r in records)
    if case == "shrunk":  # the fringe descent has work to do
        assert desc is not None and ((desc >= 0) & ~render.ravel()).sum() > 50

    tiled_graded(store, workers=1)
    tiled_directions(store, workers=1)
    comps = tiled_geometry_lakes(store, mmu, km, workers=1)
    res = tiled_terminal_routing(
        store, comps, precip_mm=precip, temp_c=temp, open_water_mm=ow,
        runoff_land_mean_mm=RUNOFF_REFERENCE_MM, mmu_cells=mmu, km_per_px=km,
        climate_block=PX_PER_CELL, workers=1,
    )  # fmt: skip
    assert res.stats == stats
    assert len(res.lake_records) == len(records)
    for a, b in zip(res.lake_records, records, strict=True):
        for k in ("label", "verdict", "draw_cells", "kept_water_cells", "spill_cell",
                  "spill_elev_m", "downstream_label"):  # fmt: skip
            assert a[k] == b[k], (k, a, b)
        for k in ("inflow_mm", "demand_mm"):
            assert a[k] == pytest.approx(b[k], rel=1e-5, abs=1e-3)
    h, w = lakes0.shape
    rr, cc = np.mgrid[0:T, 0:T]
    from dreamulator.media.canvas_hydrology import _NEIGHBOURS

    for key in store.chunks:
        sl = np.s_[key[0] * T : (key[0] + 1) * T, key[1] * T : (key[1] + 1) * T]
        assert np.array_equal(load_chunk(store, "lakes_render", key).astype(bool), render[sl])
        assert np.array_equal(load_chunk(store, "term_water", key).astype(bool), water[sl])
        assert np.array_equal(load_chunk(store, "land2", key).astype(bool), land2[sl])
        code = load_chunk(store, "dir_route", key)
        got = np.full((T, T), -1, dtype=np.int64)
        for k, (dy, dx) in enumerate(_NEIGHBOURS):
            m = code == k
            got[m] = (key[0] * T + rr[m] + dy) * w + (key[1] * T + cc[m] + dx)
        assert np.array_equal(got, rec_route.reshape(h, w)[sl])
        if desc is not None:
            assert np.array_equal(load_chunk(store, "desc", key), desc.reshape(h, w)[sl])
        assert np.array_equal(load_chunk(store, "w_depleted", key), w_dep[sl])
    tiled_accumulation(store, "w_depleted", dir_kind="dir_route", workers=1)
    del h_rw, chain


def test_tiled_month_active_matches_the_in_memory_oracle(tmp_path: Path) -> None:
    """Twenty-four monthly accumulations with the pass-through lakes' own monthly balance."""
    from dreamulator.map.prog_erosion import (
        RUNOFF_REFERENCE_MM,
        PassThroughLakes,
        lake_monthly_demand,
        month_active_counts,
        regime_active_cells,
    )
    from dreamulator.map.td_canvas import PX_PER_CELL
    from dreamulator.media.canvas_flow_tiled import (
        load_chunk,
        tiled_directions,
        tiled_graded,
    )
    from dreamulator.media.canvas_lakes_tiled import tiled_geometry_lakes
    from dreamulator.media.canvas_month_tiled import tiled_month_active
    from dreamulator.media.canvas_terminal_tiled import tiled_terminal_routing

    root = tmp_path / "canvas"
    root.mkdir()
    precip, temp, ow = _make_lakes_canvas(root, 200.0, 2500.0)
    store = CanvasStore.load(root)
    run_canvas_fill(store, verbose=False, workers=1)
    # a wet half-year in the west, a dry one everywhere: the lakes draw down and spill seasonally
    n = 4
    season = np.array([0.1, 0.1, 0.4, 1.4, 2.6, 3.0, 2.4, 1.2, 0.4, 0.1, 0.1, 0.1])
    monthly = np.full((n, n, 12), 2.0 / 12.0, dtype=np.float32) * season
    monthly[:, 0, :] = 200.0 / 12.0 * season
    evap_m = np.repeat((ow / 12.0)[None, :, :], 12, axis=0).astype(np.float32)
    evap_m *= (2.0 - 0.5 * season)[:, None, None]
    precip_m = (
        np.repeat((precip / 12.0)[None, :, :], 12, axis=0).astype(np.float32)
        * season[:, None, None]
    )

    pt_out: list[PassThroughLakes] = []
    graded, dem, rec, _acc, land, order, weight, inland = canvas_flow_fields(store)
    from dreamulator.map.prog_erosion import lake_mmu_cells, renderable_lakes

    km = store.geometry.px_km
    mmu = lake_mmu_cells(km)
    lakes0 = renderable_lakes(graded, dem, inland, mmu, km)
    from dreamulator.map.prog_erosion import terminal_equilibrium_routing

    out = terminal_equilibrium_routing(
        dem, land, lakes0, order, rec.copy(), weight.ravel().copy(),
        precip_mm=precip, temp_c=temp, runoff_land_mean_mm=RUNOFF_REFERENCE_MM,
        mmu_cells=mmu, km_per_px=km, sea_level_m=0.0, climate_block=PX_PER_CELL,
        open_water_mm=ow, keep_rewritten_h=False, pass_through_out=pt_out,
    )  # fmt: skip
    rec_route = out[5]
    pt = pt_out[0]
    assert pt.count >= 1
    demand = lake_monthly_demand(pt, evap_m, precip_m, land.shape[1], climate_block=PX_PER_CELL)
    active = regime_active_cells(km)
    stats_oracle: dict[str, int] = {}
    expect = month_active_counts(
        order, rec_route, monthly, land, active, factor=PX_PER_CELL,
        lakes=(pt, demand), lake_stats_out=stats_oracle,
    )  # fmt: skip
    assert 0 < int(expect.max()) <= 12 and stats_oracle["lakes"] == pt.count

    tiled_graded(store, workers=1)
    tiled_directions(store, workers=1)
    comps = tiled_geometry_lakes(store, mmu, km, workers=1)
    term = tiled_terminal_routing(
        store, comps, precip_mm=precip, temp_c=temp, open_water_mm=ow,
        runoff_land_mean_mm=RUNOFF_REFERENCE_MM, mmu_cells=mmu, km_per_px=km,
        climate_block=PX_PER_CELL, workers=1,
    )  # fmt: skip
    res = tiled_month_active(
        store, comps, term, runoff_monthly_pack=monthly, evaporation_monthly_mm=evap_m,
        precip_monthly_mm=precip_m, active_cells=active, factor=PX_PER_CELL,
        climate_block=PX_PER_CELL, workers=1,
    )  # fmt: skip
    assert res.pass_through == pt.count and res.stats == stats_oracle
    assert stats_oracle["seasonal_outflow"] >= 1  # the dry season empties a lake below its sill
    for key in store.chunks:
        sl = np.s_[key[0] * T : (key[0] + 1) * T, key[1] * T : (key[1] + 1) * T]
        assert np.array_equal(load_chunk(store, "month_active", key), expect[sl])
    assert not (store.work / "flow" / "w_month").exists()

    # without the monthly lake channels no lake loses water month by month
    plain = month_active_counts(order, rec_route, monthly, land, active, factor=PX_PER_CELL)
    res2 = tiled_month_active(
        store, comps, term, runoff_monthly_pack=monthly, evaporation_monthly_mm=None,
        precip_monthly_mm=None, active_cells=active, factor=PX_PER_CELL,
        climate_block=PX_PER_CELL, workers=1,
    )  # fmt: skip
    assert res2.pass_through == 0 and not res2.stats
    assert (plain != expect).any()  # the lake balance does change the regime
    for key in store.chunks:
        sl = np.s_[key[0] * T : (key[0] + 1) * T, key[1] * T : (key[1] + 1) * T]
        assert np.array_equal(load_chunk(store, "month_active", key), plain[sl])
