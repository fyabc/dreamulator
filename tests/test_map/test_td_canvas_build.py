"""Tests for the S1 canvas IO layer: layout config, inputs, worker bookkeeping and the mosaic."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map import td_canvas as tc
from dreamulator.map import td_canvas_build as tb
from dreamulator.map import td_canvas_mosaic as tm
from dreamulator.map import td_canvas_worker as tw

if TYPE_CHECKING:
    from pathlib import Path


def _grid_mesh(n: int = 24, step: float = 0.5) -> SimpleNamespace:
    """An n x n lat/lon grid around (0, 0): a square island in the middle, ocean around."""
    cells = []
    for a in range(n):
        for b in range(n):
            lat, lon = (a - n / 2) * step, (b - n / 2) * step
            land = abs(a - n / 2) < n / 4 and abs(b - n / 2) < n / 4
            nb = [
                (a + da) * n + (b + db)
                for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= a + da < n and 0 <= b + db < n
            ]
            cells.append(
                SimpleNamespace(
                    lat=lat, lon=lon, area_km2=3000.0, neighbors=nb,
                    water_class="land" if land else "ocean",
                    elevation=400.0 if land else -1000.0,
                    koppen_class="Af" if land else None,
                    biome="tropical_rainforest" if land else None,
                    ice_thickness_m=None, npp_gc_m2_yr=2000.0 if land else None,
                )
            )  # fmt: skip
    return SimpleNamespace(cells=cells)


def test_layout_config_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "canvas_layout.yaml"
    f.write_text(
        "branch: b1\ncuts:\n  - {lat: 1.0, lon: 2.0, radius_km: 50.0}\n"
        "names:\n  isle: [0.0, 0.0]\njoins:\n  - {point: [1, 1], into: [0, 0]}\n"
        "generation: {seed: 7}\n",
        encoding="utf-8",
    )
    cfg = tb.CanvasLayoutConfig.load(f)
    assert cfg.branch == "b1" and cfg.land_cuts() == (tc.LandCut(1.0, 2.0, 50.0),)
    assert cfg.names["isle"] == (0.0, 0.0) and cfg.joins[0].into == (0.0, 0.0)
    gen = cfg.generation_params()
    assert gen["seed"] == 7 and gen["model"] == tb.DEFAULT_GENERATION["model"]


def test_plan_and_write_inputs(tmp_path: Path) -> None:
    mesh = _grid_mesh()
    cfg = tb.CanvasLayoutConfig(names={"isle": (0.0, 0.0)})
    layout = tb.plan_world_layout(mesh, 6371.0, cfg)  # type: ignore[arg-type]
    assert [p.canvas_id for p in layout.plans] == ["isle"]
    tb.write_layout(tmp_path, layout, cfg, {"world": "toy"})
    doc = json.loads((tmp_path / "layout.json").read_text(encoding="utf-8"))
    assert doc["format"] == tb.LAYOUT_FORMAT and doc["canvases"][0]["id"] == "isle"
    owner = np.load(tmp_path / "owner_canvas.npy")
    assert len(owner) == sum(c.water_class == "land" for c in mesh.cells) and (owner == 0).all()

    n = len(mesh.cells)
    t = np.full((n, 12), 25.0) + np.linspace(-1, 1, 12)
    p = np.full((n, 12), 200.0)
    cols = tb.MeshColumns.from_mesh(mesh, t, p)  # type: ignore[arg-type]
    out = tb.write_canvas_inputs(tmp_path, layout.plans[0], cols, cfg.generation_params(), {})
    meta = json.loads((out / "canvas.json").read_text(encoding="utf-8"))
    ncell = meta["geometry"]["ncell"]
    hm = np.load(out / "conditioning" / "heightmap.npy")
    assert hm.shape == (ncell, ncell) and hm.max() == pytest.approx(400.0)
    for name, d in meta["climate"].items():
        arr = np.load(out / "climate" / f"{name}.npy")
        assert list(arr.shape) == d["shape"]
    runoff = np.load(out / "climate" / "runoff.mm.npy")
    assert np.isnan(runoff[hm <= 0]).all() and np.isfinite(runoff[hm >= 399.9]).any()
    assert np.nanmin(runoff) > 0
    assert meta["legends"]["koppen.codes"] == {"1": "Af"}
    sha = hashlib.sha256((out / "conditioning" / "heightmap.npy").read_bytes()).hexdigest()
    assert meta["conditioning_sha256"]["heightmap"] == sha


def _fake_canvas(tmp_path: Path, chunks: list[list[int]], ncell: int = 16) -> Path:
    geom = tc.CanvasGeometry(0.0, 0.0, 6371.0, ncell)
    c = tmp_path / "cv"
    (c / "chunks").mkdir(parents=True)
    meta = {"id": "cv", "geometry": geom.to_dict(), "chunks": chunks}
    (c / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
    return c


def test_worker_bookkeeping_and_status(tmp_path: Path) -> None:
    chunks = [[0, 0], [0, 1], [1, 0], [1, 1], [2, 2]]
    assert tw.worker_slice(chunks, 0, 2) == (chunks[:3], [1, 1])
    assert tw.worker_slice(chunks, 1, 2) == (chunks[3:], None)
    c = _fake_canvas(tmp_path, chunks)
    good = c / "chunks" / tw.chunk_name(0, 0)
    np.save(good, np.zeros((4, 4), np.int16))
    tw.append_checksum(
        c / "chunks.sha256", hashlib.sha256(good.read_bytes()).hexdigest(), good.name
    )
    bad = c / "chunks" / tw.chunk_name(0, 1)
    np.save(bad, np.ones((4, 4), np.int16))
    tw.append_checksum(c / "chunks.sha256", "0" * 64, bad.name)
    assert tw.pending(c, chunks[:3]) == [(0, 1), (1, 0)]
    assert tb.chunk_name(3, 12) == tw.chunk_name(3, 12) == "r003_c012.npy"
    assert tb.canvas_status(c) == {"chunks": 5, "done": 2, "missing": 3, "corrupt": 0}
    assert tb.canvas_status(c, verify=True) == {"chunks": 5, "done": 1, "missing": 3, "corrupt": 1}


def test_mosaic_crops_to_generated_chunks(tmp_path: Path) -> None:
    c = _fake_canvas(tmp_path, [[0, 0], [0, 1], [1, 1]])
    y, x = np.mgrid[0:2048, 0:2048]
    for i, j in [(0, 0), (0, 1), (1, 1)]:
        h = (np.sin(x / 150.0) * 300 + (j - 0.5) * 800).astype(np.int16)
        np.save(c / "chunks" / tw.chunk_name(i, j), h)
    out = tmp_path / "m.png"
    side = tm.render_mosaic(c, out, step=16, workers=1)
    assert (side["width_px"], side["height_px"]) == (256, 256)
    from PIL import Image

    img = np.asarray(Image.open(out))
    paper = np.rint(np.array(tm.PAPER_RGB) * 255).astype(np.uint8)
    assert (img[200, 50] == paper).all()  # chunk (1, 0) not generated
    assert not (img[50, 50] == paper).all()
    with pytest.raises(ValueError, match="step must divide"):
        tm.render_mosaic(c, out, step=3)


def test_export_canvas_cli_status_and_mosaic(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from dreamulator.cli import app
    from dreamulator.cli_export_canvas import _parse_gpus

    assert _parse_gpus("0-2,5") == ["0", "1", "2", "5"]
    c = _fake_canvas(tmp_path, [[0, 0]])
    np.save(c / "chunks" / tw.chunk_name(0, 0), np.full((2048, 2048), 300, np.int16))
    layout = {"canvases": [{"id": "cv"}]}
    (tmp_path / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    runner = CliRunner()
    res = runner.invoke(app, ["export", "canvas", "status", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "cv" in res.output
    out = tmp_path / "m.jpg"
    res = runner.invoke(
        app,
        ["export", "canvas", "mosaic", str(c), "-o", str(out), "--step", "16", "--workers", "1"],
    )
    assert res.exit_code == 0, res.output
    assert out.exists() and (tmp_path / "m.jpg.json").exists()
