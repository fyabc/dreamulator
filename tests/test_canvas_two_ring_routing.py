"""Independent graph, seam, flat and formal-chain checks for canvas routing."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import numpy as np
import pytest

from dreamulator.map.river_routing import accumulate
from dreamulator.media import canvas_flow_tiled as flow
from dreamulator.media.canvas_pipeline import CanvasStore
from dreamulator.media.canvas_routing import (
    downstream_order,
    flat_ranks,
    prune_code_rows,
    tiled_two_ring_routing,
    whole_grid_routing,
)

if TYPE_CHECKING:
    from pathlib import Path


def _store(root: Path, height: np.ndarray, tile: int) -> CanvasStore:
    rows, cols = height.shape
    keys = [
        (r, c)
        for r in range(rows // tile)
        for c in range(cols // tile)
        if np.isfinite(height[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile]).any()
    ]
    st = cast("CanvasStore", SimpleNamespace(root=root, work=root / "work", tile=tile, chunks=keys))
    for r, c in keys:
        p = st.work / "final" / f"r{r:03d}_c{c:03d}.i16.npy"
        p.parent.mkdir(parents=True, exist_ok=True)
        np.save(p, height[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile])
    return st


def _assembled(st: CanvasStore, kind: str, fill: float = 0) -> np.ndarray:
    first = flow.load_chunk(st, kind, st.chunks[0])
    out = np.full(flow.ChunkLayout.of(st).shape, fill, dtype=first.dtype)
    for r, c in st.chunks:
        out[r * st.tile : (r + 1) * st.tile, c * st.tile : (c + 1) * st.tile] = flow.load_chunk(
            st, kind, (r, c)
        )
    return out


@pytest.mark.parametrize(("tile", "band", "workers"), [(16, 1, 1), (16, 13, 2), (32, 32, 1)])
@pytest.mark.parametrize("missing", [False, True])
def test_generated_directions_are_independent_of_tiles_bands_and_workers(
    tmp_path: Path, tile: int, band: int, workers: int, missing: bool
) -> None:
    rr, cc = np.indices((96, 96))
    height = np.round(800 - 2 * rr - 3 * cc + 12 * np.sin(rr / 3) * np.cos(cc / 4)).astype(
        np.float32
    )
    # An open flat crosses multiple chunks; its routing must use integer ranks.
    height[20:44, 8:88] = 620
    height[44:48, 8:88] = 600
    if missing:
        height[64:96, 32:64] = np.nan
    land = np.isfinite(height)
    water = np.zeros(height.shape, bool)
    water[50:56, 34:42] = True
    ranks = flat_ranks(height, 0)
    expected_rec, expected_stats = whole_grid_routing(height, ranks, land, water)
    st = _store(tmp_path, height, tile)
    flow.tiled_graded(st, eps=0, keep_dist=True, open_edges=True, workers=workers)
    flow.tiled_directions(st, workers=workers)
    for r, c in st.chunks:
        part = np.s_[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile]
        flow.save_chunk(st, "lakes0", (r, c), water[part].astype(np.uint8))
        # A prior generation's sort cache must be invalidated.
        flow._atomic_save(flow.flow_path(st, "order", (r, c)), np.zeros(tile * tile, np.int32))
    stats = tiled_two_ring_routing(st, workers=workers, band_rows=band)
    assert stats == expected_stats
    assert stats["accepted_extensions"] > 100
    np.testing.assert_array_equal(_assembled(st, "graded", np.nan), height)
    np.testing.assert_array_equal(_assembled(st, "flat_rank", 2**31 - 1), ranks)
    code = _assembled(st, "dir", 255)
    has = code != 255
    offsets = flow.FLOW_OFFSETS[np.where(has, code, 0)]
    actual_rec = np.where(
        has, (rr + offsets[..., 0]) * height.shape[1] + cc + offsets[..., 1], -1
    ).ravel()
    np.testing.assert_array_equal(actual_rec, expected_rec)
    source = land.astype(np.float64)
    for r, c in st.chunks:
        flow.save_chunk(
            st, "source", (r, c), source[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile]
        )
    flow.tiled_accumulation(st, "source", workers=workers, float64=True)
    total = _assembled(st, "acc_source")
    np.testing.assert_array_equal(total, accumulate(actual_rec, source))
    assert total.ravel()[actual_rec < 0].sum() == source.sum()
    # Every link decreases physical height or, on a flat, the integer distance.
    donors = np.flatnonzero(actual_rec >= 0)
    targets = actual_rec[donors]
    z = height.ravel()
    d = ranks.ravel()
    assert np.all((z[targets] < z[donors]) | ((z[targets] == z[donors]) & (d[targets] < d[donors])))


def test_high_flat_does_not_depend_on_floating_point_micro_slopes() -> None:
    height = np.full((12, 60), 1e8, np.float32)
    before = height.copy()
    ranks = flat_ranks(height, 0)
    rec, stats = whole_grid_routing(
        height, ranks, np.ones(height.shape, bool), np.zeros_like(height, bool)
    )
    assert ranks[6, 30] > 0
    assert stats["accepted_extensions"] == 0
    total = accumulate(rec, np.ones(height.shape, np.float64))
    assert total.ravel()[rec < 0].sum() == height.size
    np.testing.assert_array_equal(height, before)


def test_generated_directions_with_spawn_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DREAMULATOR_START_METHOD", "spawn")
    test_generated_directions_are_independent_of_tiles_bands_and_workers(
        tmp_path, tile=32, band=7, workers=2, missing=True
    )


def test_cross_chunk_link_graph_rejects_cycles() -> None:
    with pytest.raises(ValueError, match="cycle"):
        downstream_order(np.array([1, 0], np.int64))


def test_arbitration_rejects_an_interior_crossing_but_keeps_a_junction() -> None:
    base = np.full((7, 7), 255, np.uint8)
    base[2, 2], base[3, 1] = 6, 4  # both baseline edges meet (3, 2)

    def code(dy: int, dx: int) -> int:
        return int(np.flatnonzero(((dy, dx) == flow.FLOW_OFFSETS).all(axis=1))[0])

    proposed = base.copy()
    proposed[2, 2], proposed[3, 1] = code(2, 1), code(-1, 2)
    current = base.copy()
    assert prune_code_rows(current, proposed, 0, 7) == 1
    assert current[2, 2] == proposed[2, 2]
    assert current[3, 1] == base[3, 1]
    # A shared endpoint is a confluence, so both long edges remain eligible.
    proposed[3, 1] = code(1, 2)
    current = base.copy()
    assert prune_code_rows(current, proposed, 0, 7) == 0
    np.testing.assert_array_equal(current, proposed)


def test_cli_refreshes_old_routing_without_repeating_the_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dreamulator.cli_export_canvas import _run_hydrology
    from dreamulator.media import canvas_pipeline, canvas_rivers_tiled
    from dreamulator.media.canvas_surface_process import write_surface_tag

    st = _store(tmp_path, np.full((16, 16), 30, np.float32), 16)
    st.surface = "td"
    (tmp_path / "hydro").mkdir()
    np.save(tmp_path / "hydro/rivers.line.npy", np.zeros((0, 2, 2)))
    write_surface_tag(tmp_path / "hydro", st.surface)
    meta = tmp_path / "hydro/rivers.meta.json"
    meta.write_text('{"threshold_cells": 64}', encoding="utf-8")
    monkeypatch.setattr(CanvasStore, "load", lambda *a, **k: st)
    monkeypatch.setattr(canvas_rivers_tiled, "prefer_out_of_core", lambda s: False)
    calls = []

    def fill(*args: object, **kwargs: object) -> None:
        pytest.fail("Existing fill must be reused when only river routing changes")

    def rivers(store: CanvasStore, *, threshold_cells: int) -> None:
        calls.append(threshold_cells)
        meta.write_text(
            json.dumps({"routing": "constrained-two-ring-v1", "threshold_cells": threshold_cells}),
            encoding="utf-8",
        )

    monkeypatch.setattr(canvas_pipeline, "run_canvas_fill", fill)
    monkeypatch.setattr(canvas_pipeline, "run_canvas_rivers", rivers)
    for threshold in (64, 64, 96):
        _run_hydrology(tmp_path, resume=True, force=False, threshold_cells=threshold)
    assert calls == [64, 96]


@pytest.mark.parametrize(("runoff", "evap"), [(200, 2500), (100, 4000), (25, 2500)])
def test_formal_two_ring_chains_agree_on_monthly_lake_cascades(
    tmp_path: Path, runoff: float, evap: float
) -> None:
    from dreamulator.media.canvas_pipeline import run_canvas_fill, run_canvas_rivers
    from dreamulator.media.canvas_rivers_tiled import run_canvas_rivers_tiled
    from tests.test_canvas_flow_tiled import _make_lakes_canvas

    root = tmp_path / "canvas"
    root.mkdir()
    _make_lakes_canvas(root, runoff, evap)
    st = CanvasStore.load(root)
    monthly = np.full((12, 4, 4), runoff, np.float32)
    monthly[3:8] = 0
    np.save(root / "climate/runoff_monthly.mm.npy", monthly)
    np.save(root / "climate/lake_evaporation.mm.npy", np.full((4, 4), evap, np.float32))
    np.save(
        root / "climate/lake_evaporation_monthly.mm.npy", np.full((12, 4, 4), evap / 12, np.float32)
    )
    np.save(
        root / "climate/precipitation_monthly.mm.npy", np.full((12, 4, 4), 100 / 12, np.float32)
    )
    run_canvas_fill(st, workers=1, verbose=False)
    run_canvas_rivers(st, threshold_cells=8, verbose=False)
    expected = {
        kind: np.load(root / "hydro" / f"rivers.{kind}.npy") for kind in ("line", "flow", "regime")
    }
    expected_lakes = json.loads((root / "hydro/terminal_lakes.json").read_text(encoding="utf-8"))
    run_canvas_rivers_tiled(st, workers=1, threshold_cells=8, verbose=False, keep_work=True)
    meta = json.loads((root / "hydro/rivers.meta.json").read_text(encoding="utf-8"))
    assert meta["routing"] == "constrained-two-ring-v1"
    assert meta["river_geometry"] == "receiver-vertices"
    for kind, array in expected.items():
        np.testing.assert_array_equal(np.load(root / "hydro" / f"rivers.{kind}.npy"), array)
    actual_lakes = json.loads((root / "hydro/terminal_lakes.json").read_text(encoding="utf-8"))
    assert actual_lakes == expected_lakes
