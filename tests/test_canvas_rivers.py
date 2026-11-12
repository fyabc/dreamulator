"""S2 vector river extraction tests (disk pipeline, synthetic canvas)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_pipeline import (
    CanvasStore,
    run_canvas_fill,
    run_canvas_rivers,
)

if TYPE_CHECKING:
    from pathlib import Path

T = 256


def _make_canvas(root: Path) -> CanvasGeometry:
    """A 4x4-chunk canvas: tilted slope + a wide pit + a sea band."""
    geom = CanvasGeometry(10.0, 20.0, 6816.97, 4)
    (root / "chunks").mkdir(parents=True)
    (root / "climate").mkdir()
    (root / "canvas.json").write_text(
        json.dumps(
            {"geometry": geom.to_dict(), "chunks": [[i, j] for i in range(4) for j in range(4)]}
        ),
        encoding="utf-8",
    )
    px = geom.px_km
    for ci in range(4):
        for cj in range(4):
            r = np.arange(T, dtype=np.float64)[:, None]
            c = np.arange(T, dtype=np.float64)[None, :]
            x = -geom.half_km + (cj * T + c + 0.5) * px
            y = geom.half_km - (ci * T + r + 0.5) * px
            dem = 300.0 + 0.35 * x + 0.20 * y
            dem -= 90.0 * np.exp(-((x**2 + y**2) / (2 * 30.0**2)))
            dem = np.where(y < -30.0, -40.0, dem)
            np.save(root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy", dem.astype(np.int16))
    n = geom.ncell
    np.save(root / "climate" / "runoff.mm.npy", np.full((n, n), 200.0, dtype=np.float32))
    np.save(root / "climate" / "precipitation.mm.npy", np.full((n, n), 900.0, dtype=np.float32))
    np.save(root / "climate" / "temperature.C.npy", np.full((n, n), 22.0, dtype=np.float32))
    return geom


def test_canvas_rivers(tmp_path: Path) -> None:
    root = tmp_path / "canvas"
    root.mkdir()
    geom = _make_canvas(root)
    store = CanvasStore.load(root)
    run_canvas_fill(store, verbose=False)
    run_canvas_rivers(store, threshold_cells=60, verbose=False)

    hydro = root / "hydro"
    segs = np.load(hydro / "rivers.line.npy")
    flows = np.load(hydro / "rivers.flow.npy")
    regimes = np.load(hydro / "rivers.regime.npy")
    assert segs.ndim == 3 and segs.shape[1:] == (2, 2)
    assert segs.shape[0] == flows.shape[0] == regimes.shape[0] > 0
    assert regimes.dtype == np.uint8
    assert set(np.unique(regimes).tolist()) <= {0, 1}
    assert float(flows.max()) > 60.0
    size_km = geom.size_px * geom.px_km
    assert float(segs.min()) >= -1e-3
    assert float(segs.max()) <= size_km + 1e-3
    assert (hydro / "rivers.png").exists()
    meta = json.loads((hydro / "rivers.meta.json").read_text(encoding="utf-8"))
    assert meta["segments"] == int(segs.shape[0])
    # Lake tables (S3 consumes these instead of re-deriving) + the heal
    # delta driving the fill generation.
    lakes = json.loads((hydro / "lakes.json").read_text(encoding="utf-8"))
    assert lakes["schema"] == "canvas-lakes-v1" and isinstance(lakes["lakes"], list)
    term = json.loads((hydro / "terminal_lakes.json").read_text(encoding="utf-8"))
    assert term["schema"] == "canvas-terminal-lakes-v1"
    assert set(term["stats"]) == {"terminal", "dry_playas", "shrunk"}
    assert meta["healed_pit_cells"] >= 0  # heal.npz exists and was counted
    assert (root / "hydro-work" / "heal.npz").exists()
    # The pit on the tilted slope is a lake with a verdict.
    assert len(lakes["lakes"]) > 0 and all("verdict" in lk for lk in lakes["lakes"])


@pytest.mark.parametrize("start_method", ["fork", "spawn"])
def test_fill_is_independent_of_the_worker_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, start_method: str
) -> None:
    # Stages 1 and 3 run per chunk in a process pool (fork on Linux, spawn on
    # Windows); the files and the checksum ledger must match the serial run
    # byte for byte.
    monkeypatch.setenv("DREAMULATOR_START_METHOD", start_method)
    outputs = []
    for workers in (1, 3):
        root = tmp_path / f"canvas{workers}"
        root.mkdir()
        _make_canvas(root)
        store = CanvasStore.load(root)
        stats = run_canvas_fill(store, verbose=False, workers=workers)
        files = {
            p.relative_to(store.work).as_posix(): p.read_bytes()
            for sub in ("fill", "labels", "final", "summary")
            for p in sorted((store.work / sub).glob("*"))
        }
        ledger = sorted((store.work / "chunks.sha256").read_text(encoding="utf-8").splitlines())
        outputs.append((stats["watersheds"], files, ledger))
    (w1, f1, l1), (w3, f3, l3) = outputs
    assert w1 == w3
    assert len(f1) == 4 * 16
    assert f1.keys() == f3.keys()
    assert all(f1[k] == f3[k] for k in f1 if not k.startswith("summary/"))
    assert l1 == l3


@pytest.mark.parametrize("missing", [None, (1, 2), (0, 0)])
def test_watershed_levels_match_the_reference(
    tmp_path: Path, missing: tuple[int, int] | None
) -> None:
    # Stage 2 (numpy seams + numba minimax) against the dict-and-heapq oracle,
    # on a full canvas and on canvases with a missing chunk.
    from dreamulator.media.canvas_pipeline import _watershed_levels, _watershed_levels_reference

    root = tmp_path / "canvas"
    root.mkdir()
    _make_canvas(root)
    if missing is not None:
        meta = json.loads((root / "canvas.json").read_text(encoding="utf-8"))
        meta["chunks"] = [c for c in meta["chunks"] if tuple(c) != missing]
        (root / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
        (root / "chunks" / f"r{missing[0]:03d}_c{missing[1]:03d}.npy").unlink()
    store = CanvasStore.load(root)
    run_canvas_fill(store, verbose=False, workers=1)
    keys = list(store.chunks)
    summaries = {}
    for ci, cj in keys:
        with np.load(store.path("summary", ci, cj, "npz")) as data:
            summaries[(ci, cj)] = {name: data[name] for name in data.files}
    new, n_new = _watershed_levels(keys, summaries, T)
    ref, n_ref = _watershed_levels_reference(keys, summaries, T)
    assert n_new == n_ref > 0
    assert new.keys() == ref.keys()
    for key in keys:
        assert np.array_equal(new[key], ref[key]), key
