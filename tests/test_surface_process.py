"""Surface-process solver and canvas driver: ledgers, incision pattern, infill, S2 consumption."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.surface_process import SurfaceProcessParams, run_surface_process

if TYPE_CHECKING:
    from pathlib import Path

PX_M = 720.0


def _plateau(n: int = 96, *, pit: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """A 2 km plateau dropping to a sea on the west edge; optionally a closed pit on top."""
    y, x = np.mgrid[0:n, 0:n].astype(float)
    z = np.minimum(2000.0, 40.0 * x) + 3.0 * np.sin(y / 3.0)
    if pit:
        z -= 300.0 * np.exp(-((x - 60) ** 2 + (y - 48) ** 2) / (2 * 6.0**2))
    z[:, :2] = -100.0
    land = z > 0
    return z, land


def _climate(shape: tuple[int, int], runoff: float = 600.0) -> dict[str, np.ndarray]:
    return {
        "runoff_mm": np.full(shape, runoff),
        "precip_mm": np.full(shape, 1200.0),
        "temp_c": np.full(shape, 15.0),
    }


def _run(z, land, t_yr, **kw):
    c = _climate(z.shape)
    return run_surface_process(
        z, land, c["runoff_mm"], c["precip_mm"], c["temp_c"], PX_M, t_yr, **kw
    )


def test_ledgers_close() -> None:
    z, land = _plateau()
    r = _run(z, land, 2e6, anchor=z)
    assert r.steps > 1
    assert r.ledger["eroded_km3"] > 0
    assert r.ledger["sediment_residual_rel"] < 1e-9
    assert r.ledger["topography_residual_rel"] < 1e-9


def test_incision_starts_at_the_outlet() -> None:
    z, land = _plateau()
    r = _run(z, land, 2e6)
    cut = z - r.h
    near = cut[:, 52:60][land[:, 52:60]]  # the escarpment foot rows meet the plateau edge at x = 50
    far = cut[:, 85:94][land[:, 85:94]]
    assert np.median(near) > np.median(far) + 1.0


def test_sediment_fills_a_closed_pit() -> None:
    from dreamulator.map import prog_erosion as pe

    z, land = _plateau(pit=True)

    def fill_depth(h: np.ndarray) -> float:
        f, _o, _r = pe.priority_flood(h, land)
        return float((f.reshape(h.shape) - h)[land].max())

    r = _run(z, land, 2e6, anchor=z)
    assert fill_depth(r.h) < fill_depth(z) - 1.0


def test_ice_cells_take_no_lake_sediment() -> None:
    """Non-erodible (ice-surface) cells inside a filling lake neither erode nor aggrade."""
    z, land = _plateau(pit=True)
    ice = np.zeros(z.shape, bool)
    ice[44:52, 56:64] = True  # the pit floor is ice
    r = _run(z, land, 2e6, anchor=z, erodible=~ice)
    assert np.array_equal(r.h[ice], z[ice])
    assert r.ledger["sediment_residual_rel"] < 1e-9
    assert r.ledger["topography_residual_rel"] < 1e-9
    free = _run(z, land, 2e6, anchor=z)
    assert (free.h[ice] > z[ice]).any()  # without ice the same floor fills


def test_open_water_evaporation_keeps_a_terminal_lake() -> None:
    z, land = _plateau(pit=True)
    c = _climate(z.shape, runoff=20.0)
    p = SurfaceProcessParams(fixed_steps=1)
    hamon = run_surface_process(
        z, land, c["runoff_mm"], np.full(z.shape, 300.0), np.full(z.shape, -5.0), PX_M, 1e4, p
    )
    energy = run_surface_process(
        z,
        land,
        c["runoff_mm"],
        np.full(z.shape, 300.0),
        np.full(z.shape, -5.0),
        PX_M,
        1e4,
        p,
        open_water_mm=np.full(z.shape, 1500.0),
    )
    assert not hamon.terminal.any()
    assert energy.terminal.any()


# ---------------------------------------------------------------------------
# canvas driver
# ---------------------------------------------------------------------------

T = 256


def _make_canvas(root: Path, *, missing: tuple[int, int] | None = None) -> None:
    from dreamulator.map.td_canvas import CanvasGeometry

    geom = CanvasGeometry(10.0, 20.0, 6816.97, 4)
    keys = [(i, j) for i in range(4) for j in range(4) if (i, j) != missing]
    (root / "chunks").mkdir(parents=True)
    (root / "climate").mkdir()
    (root / "conditioning").mkdir()
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
        dem = 600.0 + 0.6 * x + 0.3 * y
        dem -= 150.0 * np.exp(-((x**2 + y**2) / (2 * 15.0**2)))
        dem = np.where(y < -40.0, -40.0, dem)
        np.save(root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy", dem.astype(np.int16))
    n = geom.ncell
    cond = np.full((n, n), 300.0, dtype=np.float32)
    cond[-1, :] = -40.0  # the southern sea row is geological ocean
    np.save(root / "conditioning" / "heightmap.npy", cond)
    for name, v in (("runoff.mm", 400.0), ("precipitation.mm", 1000.0), ("temperature.C", 18.0)):
        np.save(root / "climate" / f"{name}.npy", np.full((n, n), v, dtype=np.float32))
    for name, v in (("lake_evaporation.mm", 1200.0), ("ice.m", 0.0)):
        np.save(root / "climate" / f"{name}.npy", np.full((n, n), v, dtype=np.float32))


@pytest.mark.parametrize("by_basin", [True, False])
@pytest.mark.parametrize("missing", [None, (0, 3)])
def test_canvas_driver_writes_a_consumable_product(
    tmp_path: Path, missing: tuple[int, int] | None, by_basin: bool
) -> None:
    from dreamulator.map import prog_erosion as pe
    from dreamulator.media.canvas_pipeline import CanvasStore
    from dreamulator.media.canvas_surface_process import (
        CanvasSurfaceConfig,
        run_canvas_surface_process,
        surface_process_complete,
    )

    root = tmp_path / "canvas"
    root.mkdir()
    _make_canvas(root, missing=missing)
    cfg = CanvasSurfaceConfig(
        t_max_myr=0.4, t_min_myr=0.4, native_time_myr=0.16, halo_px=32, by_basin=by_basin
    )
    teff = np.array([np.nan])  # one platform cell: every pixel takes the cap
    xyz = np.array([[1.0, 0.0, 0.0]])
    manifest = run_canvas_surface_process(root, teff, xyz, cfg, workers=1, log=lambda m: None)
    assert surface_process_complete(root)
    assert manifest["coarse"]["ledger"]["sediment_residual_rel"] < 1e-9
    assert manifest["native"]["worst_ledger_residual"] < 1e-9
    assert not (root / "surface_process" / "work").exists()
    keys = [tuple(c) for c in json.loads((root / "canvas.json").read_text())["chunks"]]
    before, after = [], []
    for ci, cj in keys:
        name = f"r{ci:03d}_c{cj:03d}.npy"
        native = np.load(root / "chunks" / name).astype(np.int32)
        inc = np.load(root / "surface_process" / "increments" / name)
        assert inc.dtype == np.int16 and inc.shape == native.shape
        final = native + inc
        assert (final[native > 0] >= 1).all()  # land keeps its sign
        assert (inc[native <= 0] == 0).all()  # sea untouched
        before.append(native)
        after.append(final)
    assert any(np.count_nonzero(a - b) for a, b in zip(after, before, strict=True))

    store = CanvasStore.load(root)
    assert store.increments is not None
    assert store.work.name == "hydro-work"
    assert store.surface.startswith("surface-process:")
    ci, cj = keys[0]
    expect = np.load(root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy").astype(np.float64)
    expect += np.load(root / "surface_process" / "increments" / f"r{ci:03d}_c{cj:03d}.npy")
    assert np.array_equal(store.raw(ci, cj), expect)
    td = CanvasStore.load(root, surface="td")
    assert td.increments is None and td.surface == "td"
    # the window crop reads the same surface as S2
    from dreamulator.media.canvas_window import CanvasSource

    src = CanvasSource.load(root)
    window_chunk = src.chunk(ci, cj)
    assert window_chunk is not None
    assert np.array_equal(window_chunk.astype(np.float64), expect)
    td_chunk = CanvasSource.load(root, surface="td").chunk(ci, cj)
    assert td_chunk is not None
    assert np.array_equal(td_chunk, np.load(root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy"))

    # the central pit got shallower (single grid: the regression the margin was set on; the
    # basin run steps once more under its step bound and lands within the same few per mille)
    if missing is None and not by_basin:

        def mosaic(chunks: list[np.ndarray]) -> np.ndarray:
            return np.block([[chunks[i * 4 + j] for j in range(4)] for i in range(4)]).astype(float)

        z0, z1 = mosaic(before), mosaic(after)
        land = z0 > 0

        def pit(h: np.ndarray) -> float:
            f, _o, _r = pe.priority_flood(h, land)
            return float((f.reshape(h.shape) - h)[land].sum())

        assert pit(z1) < pit(z0)


def test_surface_option_rejects_a_missing_product(tmp_path: Path) -> None:
    from dreamulator.media.canvas_pipeline import CanvasStore

    root = tmp_path / "canvas"
    root.mkdir()
    _make_canvas(root)
    assert CanvasStore.load(root).increments is None  # auto without a product: TD
    with pytest.raises(FileNotFoundError, match="no complete product"):
        CanvasStore.load(root, surface="surface-process")
    with pytest.raises(ValueError, match="unknown surface"):
        CanvasStore.load(root, surface="eroded")


@pytest.mark.parametrize("start_method", ["fork", "spawn"])
def test_native_pass_is_independent_of_the_worker_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, start_method: str
) -> None:
    from dreamulator.media.canvas_surface_process import (
        CanvasSurfaceConfig,
        run_canvas_surface_process,
    )

    monkeypatch.setenv("DREAMULATOR_START_METHOD", start_method)
    cfg = CanvasSurfaceConfig(t_max_myr=0.4, t_min_myr=0.4, native_time_myr=0.16, halo_px=32)
    outs = []
    for workers in (1, 3):
        root = tmp_path / f"canvas{workers}"
        root.mkdir()
        _make_canvas(root)
        run_canvas_surface_process(
            root, np.array([np.nan]), np.array([[1.0, 0.0, 0.0]]), cfg, workers=workers,
            log=lambda m: None,
        )  # fmt: skip
        outs.append(
            {
                p.name: p.read_bytes()
                for p in sorted((root / "surface_process" / "increments").glob("*.npy"))
            }
        )
    assert outs[0].keys() == outs[1].keys() and len(outs[0]) == 16
    assert all(outs[0][k] == outs[1][k] for k in outs[0])


def test_fill_refuses_to_resume_on_another_surface(tmp_path: Path) -> None:
    from dreamulator.media.canvas_pipeline import CanvasStore, run_canvas_fill
    from dreamulator.media.canvas_surface_process import (
        CanvasSurfaceConfig,
        read_surface_tag,
        run_canvas_surface_process,
    )

    root = tmp_path / "canvas"
    root.mkdir()
    _make_canvas(root)
    run_canvas_fill(CanvasStore.load(root), verbose=False, workers=1)
    assert read_surface_tag(root / "hydro-work") == "td"
    cfg = CanvasSurfaceConfig(t_max_myr=0.4, t_min_myr=0.4, native=False)
    run_canvas_surface_process(
        root, np.array([np.nan]), np.array([[1.0, 0.0, 0.0]]), cfg, log=lambda m: None
    )
    eroded = CanvasStore.load(root)
    with pytest.raises(RuntimeError, match="was filled on surface"):
        run_canvas_fill(eroded, verbose=False, workers=1)
    run_canvas_fill(eroded, resume=False, verbose=False, workers=1)
    assert read_surface_tag(root / "hydro-work") == eroded.surface
    final = np.load(root / "hydro-work" / "final" / "r000_c000.i16.npy").astype(np.int32)
    assert (final >= np.rint(eroded.raw(0, 0)).astype(np.int32) - 1).all()


# ---------------------------------------------------------------------------
# basin-by-basin coarse level
# ---------------------------------------------------------------------------


def _valley(n: int = 64, x0: int = 0, w: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """One drainage basin: a tilted valley inside high walls, draining to one sea cell."""
    w = n if w is None else w
    y, x = np.mgrid[0:n, 0:w].astype(float)
    z = 20.0 * y + 3.0 * np.abs(x - w / 2) + 2.0 * np.sin(x / 2.0)
    z[0, :] = z[-1, :] = 5000.0
    z[:, 0] = z[:, -1] = 5000.0
    z[0, w // 2] = -100.0  # the outlet
    land = (z > 0) & (z < 5000.0)
    full = np.full((n, x0 + w + 8), 5000.0)
    full_land = np.zeros(full.shape, bool)
    full[:, x0 : x0 + w] = z
    full_land[:, x0 : x0 + w] = land
    return full, full_land


def test_one_basin_reproduces_the_single_grid_run() -> None:
    from dreamulator.map.surface_process_basins import run_surface_process_by_basin

    z, land = _valley()
    c = _climate(z.shape)
    p = SurfaceProcessParams(parallel_flood=False, max_dt_yr=80_000.0)  # same bound both ways
    age = np.full(z.shape, 1e6)
    for anchor in (None, z):
        single = run_surface_process(
            z, land, c["runoff_mm"], c["precip_mm"], c["temp_c"], PX_M, 1e6, p, anchor=anchor
        )
        basin, info = run_surface_process_by_basin(
            z, land, c["runoff_mm"], c["precip_mm"], c["temp_c"], PX_M, p, age_yr=age,
            anchor=anchor,
        )  # fmt: skip
        assert info["basins"] == 1 and info["tasks"] == 1
        assert basin.steps == single.steps
        assert basin.ledger["sediment_residual_rel"] < 1e-9
        if anchor is None:
            assert np.array_equal(basin.h, single.h)
        else:  # the masked low-pass sees the crop's edge where the full grid has its own
            assert np.abs(basin.h - single.h).max() < 1e-3 * np.ptp(z[land])


def test_basins_take_their_own_time_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two separate basins: each matches its own single-grid run, the smaller takes fewer steps."""
    from dreamulator.map import surface_process_basins as spb
    from dreamulator.map.surface_process_basins import run_surface_process_by_basin

    monkeypatch.setattr(spb, "BIG_BASIN_CELLS", 100)  # both basins get crops of their own

    big_z, big_land = _valley(96, 0, 64)
    small_z, small_land = _valley(32, 0, 24)
    z = np.full((96, 72 + 32 + 8), 5000.0)
    land = np.zeros(z.shape, bool)
    z[:, :72] = big_z
    land[:, :72] = big_land
    z[:32, 72:104] = small_z
    land[:32, 72:104] = small_land
    c = _climate(z.shape)
    p = SurfaceProcessParams(parallel_flood=False, max_dt_yr=80_000.0)  # same bound both ways
    age = np.full(z.shape, 1e6)
    res, info = run_surface_process_by_basin(
        z, land, c["runoff_mm"], c["precip_mm"], c["temp_c"], PX_M, p, age_yr=age
    )
    assert info["basins"] == 2
    for keep in (big_land, None):
        mask = np.zeros(z.shape, bool)
        if keep is not None:
            mask[:, :72] = big_land
        else:
            mask[:32, 72:104] = small_land
        alone = run_surface_process(
            np.where(land & ~mask, -100.0, z), mask, c["runoff_mm"], c["precip_mm"], c["temp_c"],
            PX_M, 1e6, p,
        )  # fmt: skip
        assert np.allclose(res.h[mask], alone.h[mask], atol=1e-9)
    assert info["max_steps"] < info["total_steps"]  # the two basins stepped differently
    assert np.array_equal(res.h[~land], z[~land])
    assert res.ledger["sediment_residual_rel"] < 1e-9
