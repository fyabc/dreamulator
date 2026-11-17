"""Submetre heights survive cross-tile fills and cache format changes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.prog_erosion import priority_flood
from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_pipeline import (
    FILL_FORMAT,
    SEA_MASK_VERSION,
    CanvasStore,
    run_canvas_fill,
)

if TYPE_CHECKING:
    from pathlib import Path


def _canvas(root: Path, dem: np.ndarray, tile: int) -> CanvasStore:
    (root / "chunks").mkdir(parents=True)
    geometry = CanvasGeometry(10.0, 20.0, 6816.97, 1)
    keys = [(r, c) for r in range(len(dem) // tile) for c in range(len(dem) // tile)]
    (root / "canvas.json").write_text(
        json.dumps(
            {
                "geometry": geometry.to_dict(),
                "chunks": keys,
                "sea_mask": {"version": SEA_MASK_VERSION},
            }
        ),
        encoding="utf-8",
    )
    (root / "conditioning").mkdir()
    np.save(root / "conditioning" / "heightmap.npy", np.full((1, 1), 100.0))
    for r, c in keys:
        np.save(
            root / "chunks" / f"r{r:03d}_c{c:03d}.npy",
            dem[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile],
        )
    return CanvasStore.load(root)


def _filled(store: CanvasStore, shape: tuple[int, ...]) -> np.ndarray:
    out = np.empty(shape, np.float32)
    for r, c in store.chunks:
        out[r * store.tile : (r + 1) * store.tile, c * store.tile : (c + 1) * store.tile] = np.load(
            store.path("final", r, c, "f32.npy")
        )
    return out


@pytest.mark.parametrize("base_m", [100.0, 5000.0, 40000.0])
def test_fractional_saddle_matches_serial_flood_across_tiles(tmp_path: Path, base_m: float) -> None:
    rr, cc = np.indices((64, 64))
    dem = base_m + 0.031 * rr + 0.017 * cc
    # The sub-metre depression straddles four chunks and drains over a fractional sill.
    dem -= 0.73 * np.exp(-((rr - 32) ** 2 + (cc - 32) ** 2) / 50)
    dem = dem.astype(np.float32)
    land = np.ones(dem.shape, bool)
    land[[0, -1], :] = False
    land[:, [0, -1]] = False
    expected, _order, _receiver = priority_flood(dem, land, eps=0)
    assert np.any(expected > dem)
    for tile in (16, 32):
        store = _canvas(tmp_path / str(tile), dem, tile)
        run_canvas_fill(store, verbose=False, workers=1)
        np.testing.assert_array_equal(_filled(store, dem.shape), expected.astype(np.float32))
        for r, c in store.chunks:
            with np.load(store.path("summary", r, c, "npz")) as summary:
                raw = store.raw(r, c)
                for name, edge in [
                    ("top", raw[0]),
                    ("bottom", raw[-1]),
                    ("left", raw[:, 0]),
                    ("right", raw[:, -1]),
                ]:
                    assert summary[name + "_z"].dtype == np.float32
                    np.testing.assert_array_equal(summary[name + "_z"], edge)
        # A genuine resume reuses the new caches and preserves their values.
        stats = run_canvas_fill(store, verbose=False, workers=1)
        assert stats["cells"] == 0
        np.testing.assert_array_equal(_filled(store, dem.shape), expected.astype(np.float32))


@pytest.mark.parametrize("legacy_header", [False, True])
def test_legacy_cache_requires_force_and_clears_dependent_flow(
    tmp_path: Path, legacy_header: bool
) -> None:
    rr, cc = np.indices((32, 32))
    dem = (300.25 - 0.025 * rr - 0.011 * cc).astype(np.float32)
    store = _canvas(tmp_path / "canvas", dem, 16)
    np.save(store.path("fill", 0, 0, "i16.npy"), np.rint(dem[:16, :16]).astype(np.int16))
    np.save(store.path("final", 0, 0, "i16.npy"), np.rint(dem[:16, :16]).astype(np.int16))
    marker = store.work / "flow" / "graded" / "stale.npy"
    marker.parent.mkdir(parents=True)
    np.save(marker, np.array([999]))
    if legacy_header:
        (store.work / "fill-format.json").write_text(
            json.dumps({"format": "canvas-fill-i16-v0"}), encoding="utf-8"
        )
    with pytest.raises(RuntimeError, match="canvas hydrology --force"):
        run_canvas_fill(store, verbose=False, workers=1)
    run_canvas_fill(store, resume=False, verbose=False, workers=1)
    assert not marker.exists()
    assert not list((store.work / "fill").glob("*.i16.npy"))
    assert not list((store.work / "final").glob("*.i16.npy"))
    np.testing.assert_array_equal(_filled(store, dem.shape), dem)
    format_ = json.loads((store.work / "fill-format.json").read_text(encoding="utf-8"))
    assert format_["format"] == FILL_FORMAT


def test_window_preserves_fractional_surface_and_prefers_float_fill(tmp_path: Path) -> None:
    from dreamulator.media.canvas_window import CanvasSource, _fill_raster

    rr, cc = np.indices((32, 32))
    dem = (300.25 - 0.025 * rr - 0.011 * cc).astype(np.float32)
    store = _canvas(tmp_path / "canvas", dem, 16)
    run_canvas_fill(store, verbose=False, workers=1)
    source = CanvasSource.load(store.root)
    # A stale read-only legacy file must not take priority over the fractional product.
    np.save(store.path("final", 0, 0, "i16.npy"), np.full((16, 16), 999, np.int16))
    np.testing.assert_array_equal(_fill_raster(source, 0, 0, 32, 32), dem)
    (store.root / "increments").mkdir()
    np.save(store.root / "increments" / "r000_c000.npy", np.ones((16, 16), np.int16))
    source.increments = store.root / "increments"
    np.testing.assert_array_equal(source.chunk(0, 0), dem[:16, :16] + 1)


def test_cli_force_rebuilds_legacy_fill_instead_of_resuming_it(tmp_path: Path) -> None:
    from dreamulator.cli_export_canvas import _run_hydrology

    rr, cc = np.indices((32, 32))
    dem = (300.25 - 0.025 * rr - 0.011 * cc).astype(np.float32)
    store = _canvas(tmp_path / "canvas", dem, 16)
    for r, c in store.chunks:
        np.save(store.path("final", r, c, "i16.npy"), np.full((16, 16), 300, np.int16))
    with pytest.raises(RuntimeError, match="canvas hydrology --force"):
        _run_hydrology(store.root, resume=True, force=False, threshold_cells=64)
    _run_hydrology(store.root, resume=True, force=True, threshold_cells=64, out_of_core=False)
    np.testing.assert_array_equal(_filled(store, dem.shape), dem)
    meta = json.loads((store.root / "hydro" / "rivers.meta.json").read_text(encoding="utf-8"))
    assert meta["fill_format"] == FILL_FORMAT
