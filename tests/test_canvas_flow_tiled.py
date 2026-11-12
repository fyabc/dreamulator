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
