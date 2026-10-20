"""S3 canvas window crop tests (synthetic canvas, pack vocabulary)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_window import CanvasSource, crop_canvas_window

if TYPE_CHECKING:
    from pathlib import Path

T = 2048  # canvas chunk edge (contract)


def _make_canvas(root: Path) -> CanvasGeometry:
    geom = CanvasGeometry(10.0, 20.0, 6816.97, 16)
    (root / "chunks").mkdir(parents=True)
    (root / "climate").mkdir()
    (root / "hydro" / "lakes.sparse").mkdir(parents=True)
    (root / "canvas.json").write_text(
        json.dumps(
            {
                "geometry": geom.to_dict(),
                "chunks": [[0, 0], [0, 1], [1, 0], [1, 1]],
                "koppen_legend": {"1": "Af", "2": "BWh"},
                "biome_legend": {"1": "tropical_rainforest"},
            }
        ),
        encoding="utf-8",
    )
    px = geom.px_km
    for ci in range(2):
        for cj in range(2):
            r = np.arange(T, dtype=np.float64)[:, None]
            c = np.arange(T, dtype=np.float64)[None, :]
            x = -geom.half_km + (cj * T + c + 0.5) * px
            y = geom.half_km - (ci * T + r + 0.5) * px
            dem = 200.0 + 0.01 * x + 0.005 * y
            dem = np.where(y < -150.0, -50.0, dem)
            np.save(root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy", dem.astype(np.int16))

    n = geom.ncell
    ii, jj = np.mgrid[0:n, 0:n]
    np.save(root / "climate" / "temperature.C.npy", (20.0 + 0.1 * (ii + jj)).astype(np.float32))
    np.save(root / "climate" / "precipitation.mm.npy", (800.0 + ii * 10.0).astype(np.float32))
    np.save(root / "climate" / "koppen.codes.npy", ((ii % 2) + 1).astype(np.uint8))
    np.save(root / "climate" / "biome.codes.npy", np.ones((n, n), dtype=np.uint8))

    # A lake disk (lake id 1) around the canvas centre (pixel 2048, 2048).
    rr, cc = np.mgrid[0:T, 0:T]
    for ci in range(2):
        for cj in range(2):
            gr = ci * T + rr
            gc = cj * T + cc
            near = (gr - 2048) ** 2 + (gc - 2048) ** 2 <= 200**2
            if not near.any():
                continue
            idx = np.flatnonzero(near.ravel())
            np.savez(
                root / "hydro" / "lakes.sparse" / f"lake.r{ci:03d}_c{cj:03d}.npz",
                idx=idx.astype(np.uint32),
                lake_id=np.full(idx.size, 1, dtype=np.uint16),
            )
    np.save(
        root / "hydro" / "rivers.line.npy",
        np.array([[[-50.0, -50.0], [50.0, 50.0]]], dtype=np.float32),
    )
    np.save(root / "hydro" / "rivers.flow.npy", np.array([10.0], dtype=np.float32))
    np.save(root / "hydro" / "rivers.regime.npy", np.array([0], dtype=np.uint8))
    return geom


def test_crop_canvas_window(tmp_path: Path) -> None:
    root = tmp_path / "canvas"
    root.mkdir()
    _make_canvas(root)
    source = CanvasSource.load(root)
    assert len(source.chunks) == 4

    out = tmp_path / "window"
    meta = crop_canvas_window(
        source,
        center_lat=10.0,
        center_lon=20.0,
        span_km=550.0,
        out_res=128,
        out_dir=out,
    )
    assert meta["grid"] == {"w": 128, "h": 128}
    assert meta["projection"] == "azimuthal_equidistant"

    height = np.load(out / "refined-out" / "height.meters.npy")
    assert height.shape == (128, 128)
    assert height.dtype == np.float32
    # Linear terrain: the window centre maps to the canvas centre (h = 200).
    assert float(height[64, 64]) == 200.0 or abs(float(height[64, 64]) - 200.0) < 1.0

    from PIL import Image

    def mask(name: str) -> np.ndarray:
        return np.asarray(Image.open(out / "refined-out" / name).convert("L")) > 127

    # Sea band (y < -150 km) covers part of a 550 km window.
    sea = mask("sea-water.png")
    assert sea.shape == (128, 128)
    assert 0.0 < float(sea.mean()) < 0.5
    lake = mask("lake.png")
    assert bool(lake[64, 64])
    rivers = mask("rivers.png")
    assert rivers.any()

    line = np.load(out / "refined-out" / "rivers.line.npy")
    assert line.shape == (1, 2, 2)
    # SW-origin km: the segment spans the window centre (half = 275).
    assert np.allclose(line[0, 0], [225.0, 225.0], atol=2.0)
    assert np.allclose(line[0, 1], [325.0, 325.0], atol=2.0)

    temp = np.load(out / "input" / "temperature.C.npy")
    assert temp.shape == (128, 128)
    koppen = np.load(out / "input" / "koppen.codes.npy")
    assert set(np.unique(koppen).tolist()) <= {1, 2}
    written = json.loads((out / "input" / "meta.json").read_text(encoding="utf-8"))
    assert written["climate"]["koppen"]["legend"]["1"] == "Af"
    assert written["climate"]["biome"]["legend"]["1"] == "tropical_rainforest"
    (out / "refined-out" / "meta.json").read_text(encoding="utf-8")
