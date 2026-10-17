"""API tests for the /api/packs region-pack endpoints (the /packs QA page).

A tiny synthetic pack (8×8 input grid, 16×16 refined grid, 10 km/px both
axes) with self-consistent window geometry exercises the whole surface:
listing/legs, meta documents, PNG serving with ETag revalidation, traversal
rejection, and the multi-resolution probe (refined height, input-resolution
codes, masks, nearest-segment river lookup, 422 outside the window).
"""

from __future__ import annotations

import io
import json
import math
from typing import TYPE_CHECKING

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from dreamulator.api_routes import packs as packs_module

if TYPE_CHECKING:
    from pathlib import Path

PACK = "w-test_10_-20_80km"
GRID = 8  # input grid; refined grid is 2× (16)
KM_PER_PX = 10.0
EXTENT = GRID * KM_PER_PX  # 80 km on both axes
R_KM = 6371.0
C_LAT, C_LON = 10.0, -20.0
DEG_PER_KM = 180.0 / (math.pi * R_KM)
COS_C = math.cos(math.radians(C_LAT))

PNG_BYTES = b"\x89PNG-fake-bytes"  # only round-tripped, never decoded


def _lon_at(u: float) -> float:
    return C_LON + (u - 0.5) * EXTENT * DEG_PER_KM / COS_C


def _lat_at(v: float) -> float:
    return C_LAT + (0.5 - v) * EXTENT * DEG_PER_KM


def _write_meta(root: Path) -> None:
    meta = {
        "center_lat": C_LAT,
        "center_lon": C_LON,
        "span_km": EXTENT,
        "radius_km": R_KM,
        "grid": {"w": GRID, "h": GRID},
        "extent_km": {"x": EXTENT, "y": EXTENT},
        "km_per_px": {"x": KM_PER_PX, "y": KM_PER_PX},
        "cell_pitch_km": KM_PER_PX,
        "sea_level_m": 0.0,
        "elevation_m_global": [-200.0, 900.0],
        "height_png_range_m": [-100.0, 800.0],
        "height_gaea_png_range_m": [-100.0, 800.0],
        "climate": {"biome": {"legend": {"7": "tundra"}}},
        "source": {"world": "w-test", "planet": "planet_x", "branch": None},
    }
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_mask(path: Path, lit: list[tuple[int, int]]) -> None:
    arr = np.zeros((GRID * 2, GRID * 2), dtype=np.uint8)
    for row, col in lit:
        arr[row, col] = 255
    Image.fromarray(arr, mode="L").save(path)


def _build_pack(root: Path, name: str = PACK) -> None:
    inp = root / name / "input"
    inp.mkdir(parents=True)
    _write_meta(inp)
    np.save(
        inp / "height.meters.npy",
        np.arange(GRID * GRID, dtype=np.float32).reshape(GRID, GRID),
    )
    biome = np.zeros((GRID, GRID), dtype=np.uint8)
    biome[4, 4] = 7  # input cell under the window centre
    np.save(inp / "biome.codes.npy", biome)
    koppen = np.zeros((GRID, GRID), dtype=np.uint8)
    koppen[4, 4] = 3
    np.save(inp / "koppen.codes.npy", koppen)
    np.save(inp / "ice.m.npy", np.zeros((GRID, GRID), dtype=np.float32))
    np.save(inp / "npp.gc_m2_yr.npy", np.zeros((GRID, GRID), dtype=np.float32))
    (inp / "color.png").write_bytes(PNG_BYTES)

    refined = root / name / "refined-out"
    refined.mkdir()
    (refined / "meta.json").write_text(json.dumps({"river_threshold": 1}), encoding="utf-8")
    np.save(
        refined / "height.meters.npy",
        np.arange(GRID * 2 * GRID * 2, dtype=np.float32).reshape(GRID * 2, GRID * 2),
    )
    # 3×3 block so the centre cell is lake FILL, not the shore ring
    # (single-cell lakes erode to nothing and read as all-shore).
    _write_mask(refined / "lake.png", [(r, c) for r in (7, 8, 9) for c in (7, 8, 9)])
    _write_mask(refined / "rivers.png", [(12, 12)])
    _write_mask(refined / "sea-water.png", [])
    # One river segment passing exactly through the window centre in the
    # SW-origin km frame (x east, y north from the south-west corner).
    np.save(refined / "rivers.line.npy", np.array([[[40.0, 40.0], [40.5, 40.0]]], dtype=np.float32))
    np.save(refined / "rivers.flow.npy", np.array([123.0], dtype=np.float32))
    np.save(refined / "rivers.regime.npy", np.array([1], dtype=np.uint8))


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _build_pack(tmp_path)
    (tmp_path / "not-a-pack").mkdir()  # no input/meta.json → skipped by listing
    monkeypatch.setenv("DREAMULATOR_PACKS_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(packs_module.router)
    return TestClient(app)


def test_list_packs_filters_and_reports_legs(client: TestClient) -> None:
    r = client.get("/api/packs")
    assert r.status_code == 200
    data = r.json()["data"]
    assert [p["name"] for p in data] == [PACK]
    pack = data[0]
    assert pack["world"] == "w-test"
    assert pack["legs"] == {
        "color": False,
        "refined": True,
        "carto": False,
        "renders": False,
        "prog": False,
        "gaea": False,
    }


def test_list_packs_missing_root_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DREAMULATOR_PACKS_DIR", str(tmp_path / "nope"))
    app = FastAPI()
    app.include_router(packs_module.router)
    r = TestClient(app).get("/api/packs")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_meta_returns_both_documents(client: TestClient) -> None:
    r = client.get(f"/api/packs/{PACK}/meta")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["input"]["span_km"] == EXTENT
    assert data["refined"]["river_threshold"] == 1
    assert client.get("/api/packs/no-such-pack/meta").status_code == 404


def test_image_serves_with_etag_and_304(client: TestClient) -> None:
    url = f"/api/packs/{PACK}/image/input/color.png"
    r1 = client.get(url)
    assert r1.status_code == 200
    assert r1.content == PNG_BYTES
    assert "ETag" in r1.headers
    r2 = client.get(url, headers={"If-None-Match": r1.headers["ETag"]})
    assert r2.status_code == 304


def test_image_rejects_non_png_whitelist_and_traversal(client: TestClient) -> None:
    base = f"/api/packs/{PACK}/image"
    for path in (
        "input/meta.json",  # not a PNG
        "carto/topo.png",  # top dir not whitelisted (furniture sheets)
        "secrets/color.png",  # unknown top dir
        "../other/input/color.png",  # escapes the pack
    ):
        assert client.get(f"{base}/{path}").status_code == 404, path
    assert client.get(f"{base}/..%2Fother%2Finput%2Fcolor.png").status_code == 404


def test_probe_centre_hits_refined_height_and_input_codes(client: TestClient) -> None:
    r = client.get(f"/api/packs/{PACK}/probe", params={"lat": C_LAT, "lon": C_LON})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["res"] == {"w": GRID * 2, "h": GRID * 2}
    assert (d["row"], d["col"]) == (8, 8)  # refined grid under the centre
    assert d["height_source"] == "refined"
    assert d["height_m"] == 8 * 16 + 8  # arange value at [8, 8]
    assert d["biome_code"] == 7  # input cell [4, 4]
    assert d["koppen_code"] == 3
    assert d["lake"] is True
    assert d["river_flow_accum"] == 123.0  # segment passes through the centre
    assert d["river_regime"] == 1
    assert d["offset_km"] == {"x": 0.0, "y": 0.0}


def test_probe_quadrant_maps_each_raster_at_its_own_resolution(client: TestClient) -> None:
    # Probe the centre of refined cell [4, 12] — cell centres keep the
    # degree round-trip off the int() cell boundaries.
    v, u = 4.5 / (GRID * 2), 12.5 / (GRID * 2)
    r = client.get(f"/api/packs/{PACK}/probe", params={"lat": _lat_at(v), "lon": _lon_at(u)})
    d = r.json()["data"]
    assert (d["row"], d["col"]) == (4, 12)
    assert d["biome_code"] == 0  # input cell [2, 6] — zeros region
    assert d["offset_km"] == {"x": 22.5, "y": 17.5}


def test_probe_river_mask_cell(client: TestClient) -> None:
    v = 12.5 / (GRID * 2)  # centre of refined cell [12, 12]
    r = client.get(f"/api/packs/{PACK}/probe", params={"lat": _lat_at(v), "lon": _lon_at(v)})
    assert r.json()["data"]["river"] is True


def test_probe_outside_window_is_422(client: TestClient) -> None:
    r = client.get(
        f"/api/packs/{PACK}/probe",
        params={"lat": C_LAT + 50.0 * DEG_PER_KM, "lon": C_LON},
    )
    assert r.status_code == 422
    missing = client.get("/api/packs/no-such-pack/probe", params={"lat": 0, "lon": 0})
    assert missing.status_code == 404


def test_probe_river_far_from_any_segment_is_null(client: TestClient) -> None:
    v = 1.5 / (GRID * 2)  # near the NW corner, ~49 km from the segment
    r = client.get(f"/api/packs/{PACK}/probe", params={"lat": _lat_at(v), "lon": _lon_at(v)})
    d = r.json()["data"]
    assert d["river_flow_accum"] is None
    assert d["river_regime"] is None


def test_ll_to_frac_wraps_and_roundtrips() -> None:
    win = packs_module._window(
        {
            "center_lat": C_LAT,
            "center_lon": C_LON,
            "radius_km": R_KM,
            "extent_km": {"x": EXTENT, "y": EXTENT},
        }
    )
    for lat, lon in ((C_LAT, C_LON), (12.3, -21.7), (8.9, -18.2)):
        u, v = packs_module._ll_to_frac(win, lat, lon)
        assert packs_module._frac_to_ll(win, u, v) == pytest.approx((lat, lon), abs=1e-12)
    # +180° and −180° of the centre land on the same meridian after the wrap.
    assert packs_module._ll_to_frac(win, C_LAT, 340.0) == pytest.approx(
        packs_module._ll_to_frac(win, C_LAT, -20.0)
    )


def test_list_packs_scans_world_packs_dirs_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default resolution: every world's packs/ dir under the data dir."""
    monkeypatch.delenv("DREAMULATOR_PACKS_DIR", raising=False)
    monkeypatch.setenv("DREAMULATOR_DATA_DIR", str(tmp_path))
    _build_pack(tmp_path / "world-a" / "packs")
    app = FastAPI()
    app.include_router(packs_module.router)
    r = TestClient(app).get("/api/packs")
    assert [p["name"] for p in r.json()["data"]] == [PACK]


def test_topo_png_renders_composite_with_water_ink(client: TestClient) -> None:
    r1 = client.get(f"/api/packs/{PACK}/topo.png")
    assert r1.status_code == 200
    assert r1.headers["content-type"] == "image/png"
    assert r1.content[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(r1.content))
    assert img.size == (GRID * 2, GRID * 2)
    # The lake cell under the window centre is filled with the flat water ink
    # (carto RIVER_COLOR — lakes go in after every multiply).
    assert img.getpixel((8, 8)) == (44, 92, 130)
    # ETag revalidation on the unchanged pack.
    r2 = client.get(f"/api/packs/{PACK}/topo.png", headers={"If-None-Match": r1.headers["ETag"]})
    assert r2.status_code == 304


def test_rivers_json_shifts_to_centre_origin(client: TestClient) -> None:
    r = client.get(f"/api/packs/{PACK}/rivers.json")
    assert r.status_code == 200
    d = r.json()["data"]
    # The one segment passes through the window centre: SW-origin (40, 40) with
    # extent 80 km → centre-origin (x=0, y=0); returned as [y, x] pairs.
    assert d["segs"] == [[[0.0, 0.0], [0.0, 0.5]]]
    assert d["flows"] == [123.0]
    assert d["regimes"] == [1]
    assert d["flow_max"] == 123.0
