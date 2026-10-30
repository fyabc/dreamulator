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


def test_native_rain_refresh_preserves_terrain_and_recomputes_runoff(tmp_path: Path) -> None:
    from dreamulator.gcm.native_partition import NativePrecipitationField, gaussian_parent_partition

    mesh = _grid_mesh()
    cfg = tb.CanvasLayoutConfig(names={"isle": (0.0, 0.0)})
    plan = tb.plan_world_layout(mesh, 6371.0, cfg).plans[0]  # type: ignore[arg-type]
    n = len(mesh.cells)
    t = np.full((n, 12), 25.0)
    cols = tb.MeshColumns.from_mesh(mesh, t, np.full((n, 12), 1.0))  # type: ignore[arg-type]
    cols.npp[:] = np.nan  # GCM supplies no ecosystem estimate.
    out = tb.write_canvas_inputs(tmp_path, plan, cols, cfg.generation_params(), {})
    (out / "chunks").mkdir()
    chunk = out / "chunks/r000_c000.npy"
    chunk.write_bytes(b"accepted-terrain")
    before = {f.name: f.read_bytes() for f in (out / "conditioning").iterdir()}
    mu, _ = np.polynomial.legendre.leggauss(8)
    part = gaussian_parent_partition(
        np.degrees(np.arcsin(mu)), np.arange(16) * 22.5, radius_km=6371.0, spacing_km=500
    )
    native = np.full((2, 12, len(part.parent_area_km2)), 100.0)
    field = NativePrecipitationField(part, native, part.conservative_depths(native), {})
    tb.refresh_canvas_climate(out, cols, {"run": "new"}, precipitation_field=field)
    assert chunk.read_bytes() == b"accepted-terrain"
    assert before == {f.name: f.read_bytes() for f in (out / "conditioning").iterdir()}
    monthly = np.load(out / "climate/precipitation_monthly.mm.npy")
    annual = np.load(out / "climate/precipitation.mm.npy")
    np.testing.assert_array_equal(annual, monthly.sum(axis=0))
    np.testing.assert_allclose(monthly, 200.0, rtol=1e-7)
    _pet, runoff, runoff_m = tb._runoff_arrays(t, np.full_like(t, 200.0))
    actual = np.load(out / "climate/runoff.mm.npy")
    np.testing.assert_allclose(actual[np.isfinite(actual)], runoff[0], rtol=1e-7)
    actual_m = np.load(out / "climate/runoff_monthly.mm.npy")
    np.testing.assert_allclose(
        actual_m[:, np.isfinite(actual)],
        np.broadcast_to(runoff_m[0, :, None], (12, np.isfinite(actual).sum())),
        rtol=1e-7,
    )
    assert np.isnan(np.load(out / "climate/pet_hamon.mm.npy")[~np.isfinite(actual)]).all()
    assert np.isnan(np.load(out / "climate/npp.gc_m2_yr.npy")).all()
    meta = json.loads((out / "canvas.json").read_text(encoding="utf-8"))
    assert meta["climate_source"] == {"run": "new"}
    assert "Gaussian" in meta["precipitation_source"]["area_ledger"]
    assert "area mean" in meta["precipitation_source"]["sampling"]
    area = np.load(out / "precipitation/area_km2.npy")
    from scipy.sparse import load_npz

    weights = load_npz(out / "precipitation/overlap_km2.npz")
    np.testing.assert_allclose(np.asarray(weights.sum(axis=1)).reshape(area.shape), area)
    np.testing.assert_allclose(
        np.asarray(meta["precipitation_source"]["coverage"]["component_month_volume_mm_km2"]),
        np.full((2, 12), area.sum() * 100),
    )

    from dreamulator.map.canvas_precipitation import canvas_precipitation_coverage

    wrong_footprint = canvas_precipitation_coverage(
        part, tc.CanvasGeometry(10.0, 0.0, 6371.0, plan.geometry.ncell)
    )
    with pytest.raises(ValueError, match="footprint differs"):
        tb.refresh_canvas_climate(
            out,
            cols,
            {"run": "new"},
            precipitation_field=field,
            precipitation_coverage=wrong_footprint,
        )


def test_native_rain_water_channels_reproduce_exported_months(tmp_path: Path) -> None:
    from dreamulator.gcm.native_partition import NativePrecipitationField, gaussian_parent_partition

    mesh = _grid_mesh()
    cfg = tb.CanvasLayoutConfig(names={"isle": (0.0, 0.0)})
    plan = tb.plan_world_layout(mesh, 6371.0, cfg).plans[0]  # type: ignore[arg-type]
    t = np.broadcast_to(12.34567891 + np.sin(np.arange(12)) * 6, (len(mesh.cells), 12)).copy()
    cols = tb.MeshColumns.from_mesh(mesh, t, np.full_like(t, 200.0))  # type: ignore[arg-type]
    mu, _ = np.polynomial.legendre.leggauss(8)
    part = gaussian_parent_partition(
        np.degrees(np.arcsin(mu)), np.arange(16) * 22.5, radius_km=6371.0, spacing_km=500
    )
    rng = np.random.default_rng(85)
    native = rng.uniform(10.123456789, 120.123456789, (2, 12, len(part.parent_area_km2)))
    field = NativePrecipitationField(part, native, part.conservative_depths(native), {})
    out = tb.write_canvas_inputs(
        tmp_path, plan, cols, cfg.generation_params(), {}, precipitation_field=field
    )
    tm = np.load(out / "climate/temperature_monthly.C.npy").astype(np.float64)
    pm = np.load(out / "climate/precipitation_monthly.mm.npy").astype(np.float64)
    pet, runoff, runoff_m = tb._runoff_arrays(
        np.moveaxis(tm, 0, -1).reshape(-1, 12), np.moveaxis(pm, 0, -1).reshape(-1, 12)
    )
    land = np.load(out / "conditioning/heightmap.npy").ravel() > 0
    for name, expected in (("pet_hamon.mm", pet), ("runoff.mm", runoff)):
        observed = np.load(out / f"climate/{name}.npy").ravel()
        np.testing.assert_array_equal(observed[land], expected[land].astype(np.float32))
    observed = np.load(out / "climate/runoff_monthly.mm.npy").reshape(12, -1).T
    np.testing.assert_array_equal(observed[land], runoff_m[land].astype(np.float32))


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


@pytest.mark.parametrize("resumed", [False, True])
def test_history_targets_use_their_recorded_results_before_cache_rebuild(resumed: bool) -> None:
    # A is queried during warmup and again during historical generation. B
    # subsequently leaves the simulated cache. Its accepted result is the
    # value at that historical call, rather than a later recomputation.
    a, b, c, new = (0, 0), (0, 1), (1, 0), (1, 1)
    history = [a, b, a, c]
    accepted = {chunk: number for number, chunk in enumerate(history, 1)}
    todo = [a, new] if resumed else [a, b, new]
    queried, written = [], {}
    for i, j, emit in tw.generation_queries([list(chunk) for chunk in history], todo):
        queried.append((i, j))
        # A cache rebuild can change a chunk's value, represented here by
        # the absolute query number. Saving the historical result is exact.
        value = len(queried)
        if emit:
            written[(i, j)] = value
    assert queried == history + [new]
    assert written[a] == accepted[a]
    assert written[new] == len(history) + 1
    if resumed:
        assert b not in written
    else:
        assert written[b] == accepted[b]


def test_no_history_preserves_worker_generation_order() -> None:
    todo = [(0, 0), (0, 1), (1, 0)]
    assert list(tw.generation_queries([], todo)) == [(i, j, True) for i, j in todo]


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


def test_mosaic_relief_style_palettes_and_seas(tmp_path: Path) -> None:
    from PIL import Image

    c = _fake_canvas(tmp_path, [[0, 0], [1, 1]])
    y, x = np.mgrid[0:2048, 0:2048]
    for i, j in [(0, 0), (1, 1)]:
        h = (np.sin(x / 150.0) * 300 + (y - 1024) * 0.5).astype(np.int16)
        np.save(c / "chunks" / tw.chunk_name(i, j), h)
    clim = c / "climate"
    clim.mkdir()
    n = 16
    np.save(clim / "precipitation.mm.npy", np.full((n, n), 100.0, np.float32))
    np.save(clim / "pet_hamon.mm.npy", np.full((n, n), 1200.0, np.float32))  # arid
    np.save(clim / "temperature.C.npy", np.full((n, n), 25.0, np.float32))
    np.save(clim / "temperature_monthly.C.npy", np.full((12, n, n), 25.0, np.float32))
    np.save(clim / "ice.m.npy", np.zeros((n, n), np.float32))
    w = tm.cross_blend_weights(c)
    assert np.allclose(w["arid"], 1.0) and np.allclose(w["polar"], 0.0)
    paper = np.rint(np.array(tm.PAPER_RGB) * 255).astype(np.uint8)
    grey = np.rint(np.array(tm.SEA_GREY_RGB) * 255).astype(np.uint8)
    for palette in tm.palette_names():
        out = tmp_path / f"{palette}.png"
        side = tm.render_mosaic(c, out, step=16, style="relief", palette=palette, workers=1)
        assert side["palette"] == palette and side["exaggeration"] == pytest.approx(16.0)
        assert (np.asarray(Image.open(out))[200, 50] == paper).all()  # outside the manifest
    tm.render_mosaic(c, tmp_path / "g.png", step=16, style="relief", sea="grey", workers=1)
    assert (np.asarray(Image.open(tmp_path / "g.png"))[200, 50] == grey).all()
    depths = np.array([[-10.0, -500.0, -6000.0]])
    assert np.all(tm.sea_rgb(depths, "flat", "pastel") == tm.SEA_FLAT_RGB)
    with pytest.raises(ValueError, match="unknown style"):
        tm.render_mosaic(c, out, step=16, style="oil")
    with pytest.raises(ValueError, match="unknown palette"):
        tm.render_mosaic(c, out, step=16, palette="nope")


def test_structure_anomaly_keeps_cell_means_and_land() -> None:
    from scipy.spatial import cKDTree

    from dreamulator.map.td_canvas_structure import structure_anomaly

    # a 1.5-degree mesh over a 30 x 30 degree box: a ridge belt across the middle of an island
    la, lo = np.meshgrid(np.arange(-15, 15.01, 1.5), np.arange(-15, 15.01, 1.5), indexing="ij")
    la, lo = la.ravel(), lo.ravel()
    xyz = tc.unit_vectors(la, lo)
    elev = np.where(np.abs(lo) < 12, 400 + 2500 * np.exp(-((la / 4) ** 2)), -2000.0)
    mu = np.where(elev > 0, 50 + 700 * np.exp(-((la / 4) ** 2)), np.nan)
    geom = tc.CanvasGeometry(0.0, 0.0, 6371.0, 128)
    anom, stats = structure_anomaly(geom, "toy", xyz, elev, mu)
    again, _ = structure_anomaly(geom, "toy", xyz, elev, mu)
    assert np.array_equal(anom, again)  # deterministic per canvas id
    assert stats["anomaly_std_land_m"] > 50
    # cell means on the 4x grid are kept (to a few % of the relief) and land stays land
    la4, lo4 = geom.coarse_centres_latlon(tc.OVERSAMPLE)
    _, idx = cKDTree(xyz).query(tc.unit_vectors(la4, lo4).reshape(-1, 3))
    base = tc.sample_mesh_field(geom, elev, xyz)
    assert np.all((base + anom)[base > 1] > 0)
    assert stats["resid_over_mu_p95"] < 0.05


def test_mosaic_intertidal_band(tmp_path: Path) -> None:
    from PIL import Image

    c = _fake_canvas(tmp_path, [[0, 0]])
    y, x = np.mgrid[0:2048, 0:2048]
    np.save(c / "chunks" / tw.chunk_name(0, 0), ((x - 1024) // 64).astype(np.int16))  # -16..15 m
    out = tmp_path / "t.png"
    tm.render_mosaic(c, out, step=16, style="relief", workers=1)
    img = np.asarray(Image.open(out)).astype(int)
    tide = np.rint(np.array(tm.INTERTIDAL_RGB) * 255).astype(int)
    assert np.abs(img[64, 64] - tide).max() <= 1  # h = 0 m: intertidal
    assert np.abs(img[64, 4] - tide).max() > 10  # h = -16 m: sea
    tm.render_mosaic(c, out, step=16, style="relief", intertidal_m=None, workers=1)
    assert np.abs(np.asarray(Image.open(out)).astype(int)[64, 64] - tide).max() > 10


def _fib_island(n: int = 40000, radius_km: float = 500.0) -> tuple[np.ndarray, ...]:
    """Irregular global mesh points (Fibonacci) with a round island of ``radius_km`` at (0, 0)."""
    i = np.arange(n) + 0.5
    lat = np.degrees(np.arcsin(1 - 2 * i / n))
    lon = (np.degrees(np.pi * (1 + 5**0.5) * i) + 180.0) % 360.0 - 180.0
    xyz = tc.unit_vectors(lat, lon)
    dist_km = 6371.0 * np.arccos(np.clip(xyz @ tc.unit_vectors(0.0, 0.0).reshape(3), -1, 1))
    elev = np.where(dist_km < radius_km, 300.0 + 0.5 * (radius_km - dist_km), -2000.0)
    return lat, lon, xyz, elev


def _coast_radius_spread(geom: tc.CanvasGeometry, h: np.ndarray) -> float:
    """Std of the coast pixels' distance from the canvas centre (km): roundness of the island."""
    from scipy import ndimage as ndi

    land = h > 0
    edge = land & ~ndi.binary_erosion(land)
    s = (np.arange(geom.ncell) + 0.5) * tc.TD_COARSE_KM - geom.half_km
    gx, gy = np.meshgrid(s, s[::-1])
    return float(np.hypot(gx, gy)[edge].std())


def test_antialiased_height_rounds_the_mesh_coast_and_keeps_inland_signs() -> None:
    lat, lon, xyz, elev = _fib_island()
    geom = tc.CanvasGeometry(0.0, 0.0, 6371.0, 64)
    base = tb.antialiased_height(geom, elev, lat, lon, xyz)
    again = tb.antialiased_height(geom, elev, lat, lon, xyz)
    assert np.array_equal(base, again)
    nearest = tc.sample_mesh_field(geom, elev, xyz)
    assert base.max() <= elev.max() and base.min() >= elev.min()
    # the coast is rounder than the nearest-cell staircase of the ~110 km mesh
    assert _coast_radius_spread(geom, base) < 0.7 * _coast_radius_spread(geom, nearest)
    # cells more than one mesh spacing from the coast keep their land/sea sign
    s = (np.arange(geom.ncell) + 0.5) * tc.TD_COARSE_KM - geom.half_km
    gx, gy = np.meshgrid(s, s[::-1])
    r = np.hypot(gx, gy)
    assert np.all(base[r < 380] > 0) and np.all(base[r > 620] < 0)


def test_structure_keeps_the_base_coast_and_canvas_records_sampling(tmp_path: Path) -> None:
    mesh = _grid_mesh()
    for c in mesh.cells:
        c.relief_std_m = 600.0 if c.water_class == "land" else None
    cfg = tb.CanvasLayoutConfig(names={"isle": (0.0, 0.0)})
    layout = tb.plan_world_layout(mesh, 6371.0, cfg)  # type: ignore[arg-type]
    n = len(mesh.cells)
    t = np.full((n, 12), 25.0)
    p = np.full((n, 12), 200.0)
    cols = tb.MeshColumns.from_mesh(mesh, t, p)  # type: ignore[arg-type]
    plan = layout.plans[0]
    out = tb.write_canvas_inputs(tmp_path, plan, cols, cfg.generation_params(), {}, structure=True)
    hm = np.load(out / "conditioning" / "heightmap.npy")
    base = tb.antialiased_height(plan.geometry, cols.elevation_m, cols.lat, cols.lon, cols.xyz)
    assert np.array_equal(hm > 0, base > 0)
    meta = json.loads((out / "canvas.json").read_text(encoding="utf-8"))
    assert meta["height_sampling"] == tb.HEIGHT_SAMPLING


def test_antialiased_height_keeps_single_cell_islands() -> None:
    lat, lon, xyz, elev = _fib_island()
    i0 = int(np.argmin(np.abs(lat - 0.0) + np.abs(lon - 8.0)))  # one land cell ~890 km east
    elev = elev.copy()
    elev[i0] = 150.0
    geom = tc.CanvasGeometry(0.0, 0.0, 6371.0, 96)
    base = tb.antialiased_height(geom, elev, lat, lon, xyz)
    x, y = geom.latlon_to_xy(lat[i0], lon[i0])
    r = int((geom.half_km - y) / tc.TD_COARSE_KM)
    c = int((x + geom.half_km) / tc.TD_COARSE_KM)
    assert base[r, c] > 0  # the low-pass alone would drown a single-cell island


def test_continuous_height_source_records_geometry_and_preserves_climate_inputs(
    tmp_path: Path,
) -> None:
    from dreamulator.map.terrain_source import SOURCE_SAMPLING, ProjectedTerrainSource

    mesh = _grid_mesh()
    geom = tc.CanvasGeometry(0, 0, 6371, 8)
    plan = tc.CanvasPlan("c", geom, [], 0, 1, [(0, 0)])
    n = len(mesh.cells)
    cols = tb.MeshColumns.from_mesh(  # type: ignore[arg-type]
        mesh, np.full((n, 12), 20.0), np.full((n, 12), 80.0)
    )
    baseline = tb.write_canvas_inputs(tmp_path / "old", plan, cols, tb.DEFAULT_GENERATION, {})
    source = ProjectedTerrainSource(geom, lambda x, y: 100 + 3 * x, {"source_id": "fixed"})
    out = tb.write_canvas_inputs(
        tmp_path / "new", plan, cols, tb.DEFAULT_GENERATION, {}, height_source=source
    )
    meta = json.loads((out / "canvas.json").read_text(encoding="utf-8"))
    assert meta["height_sampling"] == SOURCE_SAMPLING
    assert meta["height_source"]["source_id"] == "fixed"
    frac = np.load(out / "geometry_fields/land_fraction.npy")
    assert ((frac > 0) & (frac < 1)).any()
    assert (
        tb.sha256_file(out / "geometry_fields/land_fraction.npy")
        == (meta["height_source"]["land_fraction"]["sha256"])
    )
    for name in ["temperature", "temperature_std", "precipitation", "precipitation_cv"]:
        np.testing.assert_array_equal(
            np.load(out / "conditioning" / f"{name}.npy"),
            np.load(baseline / "conditioning" / f"{name}.npy"),
        )
