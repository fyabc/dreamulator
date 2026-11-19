"""Tests for external heightmap import (importer + provenance recording)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.elevation_codec import encode_elevation
from dreamulator.map.importer import import_heightmap
from dreamulator.map.manager import MapManager
from dreamulator.map.models import ElevationImportProvenance

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI


def _png_bytes() -> bytes:
    grid = np.linspace(0.0, 1.0, 64 * 32).reshape(32, 64)
    return encode_elevation(grid, -1000.0, 1000.0)


def test_import_heightmap_png16_shape_range() -> None:
    result = import_heightmap(_png_bytes(), filename="test.png")
    assert result.source_format == "png-16bit"
    assert (result.source_width, result.source_height) == (64, 32)
    assert not result.was_resampled
    assert result.elevation.min() >= 0.0 and result.elevation.max() <= 1.0


def test_import_heightmap_resamples() -> None:
    result = import_heightmap(_png_bytes(), target_width=16, target_height=8)
    assert result.was_resampled
    assert result.elevation.shape == (8, 16)


def test_record_elevation_import_writes_map_yaml(tmp_path: Path) -> None:
    world_dir = tmp_path / "w"
    (world_dir / "maps" / "p").mkdir(parents=True)
    (world_dir / "maps" / "p" / "elevation.png").write_bytes(_png_bytes())
    mgr = MapManager(world_dir)

    result = import_heightmap(_png_bytes(), filename="gaea.png")
    mgr.record_elevation_import(
        "p",
        ElevationImportProvenance(
            source_format=result.source_format,
            source_filename="gaea.png",
            source_resolution=[result.source_width, result.source_height],
            was_resampled=result.was_resampled,
            notes="Gaea export",
        ),
    )

    meta = mgr.get_map_metadata("p")
    assert meta is not None and meta.elevation_import is not None
    assert meta.elevation_import.source_format == "png-16bit"
    assert meta.elevation_import.source_filename == "gaea.png"
    assert meta.elevation_import.notes == "Gaea export"


# ---------------------------------------------------------------------------
# The metric import contract (nonspecialist-entry stage A)
# ---------------------------------------------------------------------------


def _png8(grey: np.ndarray) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(grey.astype(np.uint8), mode="L").save(buf, format="PNG")
    return buf.getvalue()


def _tiff_float(values: np.ndarray) -> bytes:
    import io

    import tifffile

    buf = io.BytesIO()
    tifffile.imwrite(buf, values.astype(np.float32))
    return buf.getvalue()


def test_range_mapping_round_trips_the_maps_own_export() -> None:
    """A map's elevation.png plus its map.yaml scale comes back in metres unchanged."""
    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import ElevationMapping

    rng = np.random.default_rng(3)
    metres = rng.uniform(-7743.0, 5360.0, (32, 64))
    lo, hi = -7743.0, 5360.0
    data = encode_elevation((metres - lo) / (hi - lo), lo, hi)
    res = import_heightmap_metres(data, ElevationMapping(mode="range", min_m=lo, max_m=hi))
    one_level = (hi - lo) / 65535.0
    assert np.abs(res.metres - metres).max() <= one_level
    assert res.land_fraction == pytest.approx(float((metres > 0).mean()), abs=1.0 / metres.size)
    assert not res.seafloor_assumed
    assert res.level_step_m == pytest.approx({"coast": one_level, "max": one_level})


def test_threshold_mapping_declares_the_sea_floor_and_the_grey_step() -> None:
    """A land-only 8-bit map: land from 0 m at the threshold, sea at the declared depth."""
    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import ElevationMapping

    grey = np.tile(np.arange(256, dtype=np.uint8), (128, 1))  # 256 wide, 128 tall: 2:1
    m = ElevationMapping(mode="threshold", sea_level=20 / 255, max_m=8000.0, seafloor_m=-3000.0)
    res = import_heightmap_metres(_png8(grey), m)
    assert res.seafloor_assumed
    assert np.all(res.metres[:, :21] == -3000.0)  # grey 0..20 is sea
    assert np.all(res.metres[:, 21:] > 0.0)
    assert res.metres[0, 255] == pytest.approx(8000.0)
    step = 8000.0 / 235.0  # linear: max_m over the 235 land levels
    assert res.level_step_m == pytest.approx({"coast": step, "max": step})
    assert any("8-bit" in w for w in res.warnings)
    # a gamma curve concentrates levels near the coast: finer steps there, coarser on top
    g = import_heightmap_metres(_png8(grey), m.model_copy(update={"curve": "gamma", "gamma": 2.0}))
    assert g.level_step_m is not None
    assert g.level_step_m["coast"] < step < g.level_step_m["max"]


def test_land_and_sea_are_decided_on_the_source_pixels() -> None:
    """Downsampling keeps each class's own heights: a coast is not dragged toward the sea floor."""
    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import ElevationMapping

    grey = np.zeros((64, 128), dtype=np.uint8)
    grey[:, :48] = 200  # land on the west 48 columns
    m = ElevationMapping(mode="threshold", sea_level=10 / 255, max_m=5000.0, seafloor_m=-4000.0)
    full = import_heightmap_metres(_png8(grey), m)
    land_h = float(full.metres[0, 0])
    res = import_heightmap_metres(_png8(grey), m, target_width=32, target_height=16)
    assert res.was_resampled and res.metres.shape == (16, 32)
    # each output cell covers 4 source columns; column 12 covers source 48..51: all sea
    assert res.land[:, :12].all() and not res.land[:, 12:].any()
    assert np.allclose(res.metres[:, :12], land_h)  # land cells average land samples only
    assert np.all(res.metres[:, 12:] == -4000.0)
    assert res.land_fraction == pytest.approx(12 / 32)


def test_metres_mapping_reads_float_tiff_as_is() -> None:
    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import ElevationMapping

    metres = np.linspace(-500.0, 1500.0, 32 * 64).reshape(32, 64)
    res = import_heightmap_metres(_tiff_float(metres), ElevationMapping(mode="metres"))
    assert np.allclose(res.metres, metres.astype(np.float32))
    assert res.land_fraction == pytest.approx(float((metres > 0).mean()), abs=1 / metres.size)
    assert res.level_step_m is None and not res.warnings
    with pytest.raises(ValueError, match="float TIFF"):
        import_heightmap_metres(_png8(np.zeros((8, 16))), ElevationMapping(mode="metres"))


def test_a_non_global_aspect_is_warned_about() -> None:
    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import ElevationMapping

    res = import_heightmap_metres(
        _png8(np.full((50, 60), 128)), ElevationMapping(mode="threshold", max_m=1000.0)
    )
    assert any("not 2:1" in w for w in res.warnings)


@pytest.mark.parametrize("gamma", [0.4, 1.0, 2.0])
def test_threshold_uint32_reports_steps_without_enumerating_levels(gamma: float) -> None:
    import io

    import tifffile

    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import ElevationMapping

    levels = 2**32 - 1
    buf = io.BytesIO()
    tifffile.imwrite(buf, np.array([[0, levels // 2, levels - 1, levels]], dtype=np.uint32))
    mapping = ElevationMapping(mode="threshold", max_m=8000, curve="gamma", gamma=gamma)
    result = import_heightmap_metres(buf.getvalue(), mapping)
    coast = 8000 * (1 / levels) ** gamma
    last_step = 8000 * (1 - ((levels - 1) / levels) ** gamma)
    assert result.level_step_m == pytest.approx({"coast": coast, "max": max(coast, last_step)})
    assert result.metres[0, -1] == 8000


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("mode", ["range", "metres"])
def test_float_import_rejects_missing_or_infinite_pixels(bad_value: float, mode: str) -> None:
    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import ElevationMapping

    data = _tiff_float(np.array([[0.0, 1.0], [bad_value, 0.5]]))
    with pytest.raises(ValueError, match="finite"):
        import_heightmap_metres(data, ElevationMapping.model_validate({"mode": mode}))


@pytest.mark.parametrize(
    "fields",
    [
        {"mode": "range", "min_m": 1000, "max_m": 500},
        {"mode": "threshold", "max_m": 0},
        {"max_m": float("inf")},
        {"min_m": float("nan")},
    ],
)
def test_mapping_rejects_invalid_scales(fields: dict[str, object]) -> None:
    from dreamulator.map.models import ElevationMapping

    with pytest.raises(ValueError):
        ElevationMapping.model_validate(fields)


def test_sample_heightmap_writes_metres() -> None:
    """The two scale parameters take effect: Voronoi cells get metres like the CVT mesh."""
    from dreamulator.map.models import VoronoiCell, VoronoiNetwork
    from dreamulator.map.voronoi_generator import sample_heightmap

    net = VoronoiNetwork(
        seed=1,
        num_cells=2,
        cells=[VoronoiCell(id=0, lon=-170.0, lat=0.0), VoronoiCell(id=1, lon=170.0, lat=0.0)],
    )
    raster = np.zeros((8, 16))
    raster[:, 8:] = 1.0  # east half at full scale
    out = sample_heightmap(net, raster, -2000.0, 3000.0)
    assert [c.elevation for c in out.cells] == [-2000.0, 3000.0]


def test_import_endpoint_applies_the_mapping(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dreamulator.api_routes import maps as maps_module
    from dreamulator.world_manager import WorldManager
    from tests.test_api.test_world_documents import _write_yaml

    worlds = tmp_path / "worlds"
    _write_yaml(
        worlds / "w" / "maps" / "p" / "map.yaml", {"planet_id": "p", "width": 32, "height": 16}
    )
    app = FastAPI()
    app.include_router(maps_module.router)
    old = maps_module._manager
    maps_module._manager = WorldManager(worlds)
    try:
        client = TestClient(app)
        grey = np.zeros((32, 64), dtype=np.uint8)
        grey[:, :32] = 255
        r = client.post(
            "/api/worlds/w/maps/p/import-elevation",
            files={"file": ("map.png", _png8(grey), "image/png")},
            data={"mode": "threshold", "sea_level": "0.05", "max_m": "4000", "seafloor_m": "-2500"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["seafloor_assumed"] is True
        assert body["land_fraction"] == pytest.approx(0.5)
        assert body["range_m"] == pytest.approx([-2500.0, 4000.0])
        assert any("8-bit" in w for w in body["warnings"])
        mgr = MapManager(worlds / "w")
        meta = mgr.get_map_metadata("p")
        assert meta is not None and meta.elevation_import is not None
        assert meta.elevation_import.mapping is not None
        assert meta.elevation_import.mapping.mode == "threshold"
        assert (meta.elevation_min_m, meta.elevation_max_m) == (-2500.0, 4000.0)
        stored = mgr.get_elevation("p")
        assert stored is not None and stored.shape == (16, 32)
        # the stored raster reads back as the imported metres through map.yaml's scale
        back = meta.elevation_min_m + stored * (meta.elevation_max_m - meta.elevation_min_m)
        assert back[:, :16].min() == pytest.approx(4000.0, abs=0.2)
        assert back[:, 16:].max() == pytest.approx(-2500.0, abs=0.2)
        bad = client.post(
            "/api/worlds/w/maps/p/import-elevation",
            files={"file": ("map.png", _png8(grey), "image/png")},
            data={"mode": "threshold", "sea_level": "1.5"},
        )
        assert bad.status_code == 400
    finally:
        maps_module._manager = old


# ---------------------------------------------------------------------------
# Read-only preview (frontend entry stage B)
# ---------------------------------------------------------------------------


def test_land_area_fraction_weights_rows_by_sphere_area() -> None:
    from dreamulator.map.importer import land_area_fraction

    land = np.zeros((4, 8), dtype=bool)
    land[0] = True  # the polar band 90..45 N: (1 - sin 45°) / 2 of the sphere
    assert land.mean() == pytest.approx(0.25)
    assert land_area_fraction(land) == pytest.approx((1 - np.sqrt(0.5)) / 2)
    assert land_area_fraction(np.ones((5, 10), dtype=bool)) == pytest.approx(1.0)


def test_preview_grid_keeps_small_maps_and_resamples_large_ones_by_class() -> None:
    from dreamulator.map.importer import preview_grid

    metres = np.full((40, 80), -3000.0)
    land = np.zeros((40, 80), dtype=bool)
    metres[:, :40], land[:, :40] = 2000.0, True
    same, same_land = preview_grid(metres, land, max_width=80)
    assert same is metres and same_land is land
    small, small_land = preview_grid(metres, land, max_width=20)
    assert small.shape == small_land.shape == (10, 20)
    assert small_land[:, :10].all() and not small_land[:, 10:].any()
    # per-class means: the coast column is not dragged toward the other side
    assert small[small_land].min() == pytest.approx(2000.0)
    assert small[~small_land].max() == pytest.approx(-3000.0)


def _preview_app() -> FastAPI:
    from fastapi import FastAPI

    from dreamulator.api_routes import maps as maps_module

    app = FastAPI()
    app.include_router(maps_module.router)
    app.include_router(maps_module.preview_router)
    return app


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_preview_matches_the_import_and_writes_nothing(tmp_path: Path) -> None:
    import base64

    from fastapi.testclient import TestClient

    from dreamulator.api_routes import maps as maps_module
    from dreamulator.world_manager import WorldManager
    from tests.test_api.test_world_documents import _write_yaml

    worlds = tmp_path / "worlds"
    _write_yaml(
        worlds / "w" / "maps" / "p" / "map.yaml", {"planet_id": "p", "width": 32, "height": 16}
    )
    old = maps_module._manager
    maps_module._manager = WorldManager(worlds)
    try:
        client = TestClient(_preview_app())
        grey = np.zeros((32, 64), dtype=np.uint8)
        grey[:, :32] = 255
        form = {"mode": "threshold", "sea_level": "0.05", "max_m": "4000", "seafloor_m": "-2500"}
        before = _tree(worlds)
        preview = client.post(
            "/api/elevation-preview?world=w&planet_id=p",
            files={"file": ("map.png", _png8(grey), "image/png")},
            data=form,
        )
        assert preview.status_code == 200, preview.text
        assert _tree(worlds) == before  # a preview never writes
        body = preview.json()
        assert body["resolution_from"] == "map" and body["output_resolution"] == [32, 16]
        assert body["mapping_source"] == "request"
        grid = body["preview"]
        metres = np.frombuffer(base64.b64decode(grid["metres_f32"]), "<f4")
        land = np.frombuffer(base64.b64decode(grid["land_u8"]), np.uint8)
        assert metres.size == land.size == grid["width"] * grid["height"] == 32 * 16
        assert set(np.unique(metres)) == {-2500.0, 4000.0}
        assert body["land_area_fraction"] == pytest.approx(0.5)

        imported = client.post(
            "/api/worlds/w/maps/p/import-elevation",
            files={"file": ("map.png", _png8(grey), "image/png")},
            data=form,
        ).json()
        shared = ("mapping", "range_m", "land_fraction", "land_area_fraction")
        shared += ("seafloor_assumed", "level_step_m", "warnings", "output_resolution")
        for key in shared:
            assert body[key] == imported[key], key
    finally:
        maps_module._manager = old


def test_preview_without_a_world_uses_source_size_and_contract_defaults(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from dreamulator.api_routes import maps as maps_module
    from dreamulator.map.models import ElevationMapping
    from dreamulator.world_manager import WorldManager

    worlds = tmp_path / "worlds"
    worlds.mkdir()
    old = maps_module._manager
    maps_module._manager = WorldManager(worlds)
    try:
        client = TestClient(_preview_app())
        r = client.post(
            "/api/elevation-preview", files={"file": ("map.png", _png_bytes(), "image/png")}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["resolution_from"] == "source" and body["output_resolution"] == [64, 32]
        assert body["mapping_source"] == "contract"
        assert body["mapping"] == ElevationMapping().model_dump()
        assert list(worlds.iterdir()) == []
        bad = client.post(
            "/api/elevation-preview",
            files={"file": ("map.png", b"not an image", "image/png")},
        )
        assert bad.status_code == 400
        missing = client.post(
            "/api/elevation-preview?world=nope&planet_id=p",
            files={"file": ("map.png", _png_bytes(), "image/png")},
        )
        assert missing.status_code == 404
    finally:
        maps_module._manager = old


@pytest.mark.parametrize(
    ("kind", "status_code", "detail"),
    [
        ("regional", 400, "Global heightmap must be 2:1 (received 64x48)"),
        ("oversized", 400, "Global heightmap dimensions exceed 4096x2048"),
        ("oversized_tiff", 400, "Global heightmap dimensions exceed 4096x2048"),
        ("too_many_bytes", 413, "Global heightmap file exceeds 1 MiB"),
    ],
)
def test_global_upload_limits_apply_before_decoding_or_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, status_code: int, detail: str
) -> None:
    from io import BytesIO

    from fastapi.testclient import TestClient
    from PIL import Image

    from dreamulator.api_routes import maps as maps_module
    from dreamulator.world_manager import WorldManager
    from tests.test_api.test_world_documents import _write_yaml

    worlds = tmp_path / "worlds"
    _write_yaml(
        worlds / "w" / "maps" / "p" / "map.yaml", {"planet_id": "p", "width": 32, "height": 16}
    )
    monkeypatch.setattr(maps_module, "_manager", WorldManager(worlds))
    filename = "map.png"
    if kind == "regional":
        payload = _png8(np.zeros((48, 64), dtype=np.uint8))
    elif kind == "oversized":
        payload = _png8(np.zeros((2049, 4098), dtype=np.uint8))
    elif kind == "oversized_tiff":
        filename = "map.tiff"
        output = BytesIO()
        Image.new("F", (64, 2049)).save(output, format="TIFF")
        payload = output.getvalue()
    else:
        monkeypatch.setattr(maps_module, "GLOBAL_HEIGHTMAP_MAX_MIB", 1)
        payload = _png_bytes().ljust(1024**2 + 1, b"\0")

    def unexpected_decode(*args: object) -> None:
        pytest.fail("rejected uploads must not reach the metric decoder")

    monkeypatch.setattr(maps_module, "_run_metric_import", unexpected_decode)
    before = _tree(worlds)
    with TestClient(_preview_app()) as client:
        for path in ("/api/elevation-preview", "/api/worlds/w/maps/p/import-elevation"):
            response = client.post(path, files={"file": (filename, payload)})
            assert response.status_code == status_code, response.text
            assert response.json()["detail"] == detail
    assert _tree(worlds) == before


def test_oversized_png_is_a_clear_input_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image

    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import ElevationMapping

    # Pillow raises above twice MAX_IMAGE_PIXELS; shrink the limit instead of building a huge PNG.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ValueError, match=r"PNG has 2048 pixels, above the import limit of 200 "):
        import_heightmap_metres(_png_bytes(), ElevationMapping())
