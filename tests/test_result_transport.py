"""Real map files must have the same meaning through API and static export."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from typing import Any

import msgpack
import numpy as np
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import maps as maps_module
from dreamulator.map.export import save_cvt_mesh, write_engine_climate_yearly
from dreamulator.map.models import CVTMesh, VoronoiCell, map_metadata_result
from dreamulator.result_contract import FORMAT_VERSION, REFERENCE_YEAR_DAYS
from dreamulator.world_manager import WorldManager


@pytest.fixture(scope="module")
def exporter() -> Any:
    path = Path(__file__).resolve().parents[1] / "scripts/release/export_static.py"
    spec = importlib.util.spec_from_file_location("contract_export_static", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def mesh() -> CVTMesh:
    return CVTMesh(
        seed=7,
        num_cells=3,
        cells=[
            VoronoiCell(id=0, lon=0, lat=10, elevation=120, water_class="land"),
            VoronoiCell(id=1, lon=120, lat=-20, elevation=-1000, water_class="ocean"),
            VoronoiCell(id=2, lon=-120, lat=70, elevation=1500, water_class="land"),
        ],
    )


def monthly_arrays() -> tuple[np.ndarray, np.ndarray]:
    t = np.array([[25.0] * 12, [10.0] * 12, [-30.0] * 12], dtype=np.float32)
    p = np.array([[100.0] * 12, [80.0] * 12, [10.0] * 12], dtype=np.float32)
    return t, p


@pytest.mark.parametrize("branch", [None, "gcm"])
@pytest.mark.parametrize("own_yearly", [False, True])
def test_real_climate_files_match_api_and_static(
    exporter: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch: str | None,
    own_yearly: bool,
) -> None:
    worlds = tmp_path / "worlds"
    world = worlds / "probe"
    planet = "planet_probe"
    root_map = world / "maps" / planet
    write_yaml(
        root_map / "map.yaml",
        {
            "planet_id": planet,
            "width": 6,
            "height": 3,
            "num_plates": 2,
            "radius_km": 6371.0,
            "pipeline_version": "2.0-cvt",
            "generation_date": date(2026, 1, 1),
        },
    )
    # Tiny valid elevation image, not an opaque fake transport payload.
    from PIL import Image

    Image.fromarray(np.full((3, 6), 33000, dtype=np.uint16)).save(root_map / "elevation.png")
    m = mesh()
    save_cvt_mesh(root_map / "cvt_mesh.msgpack.gz", m)
    t, p = monthly_arrays()
    write_engine_climate_yearly(m, root_map, t_monthly=t, p_monthly=p)
    monthly = {
        "num_cells": 3,
        "months": 12,
        "bin_days": REFERENCE_YEAR_DAYS / 12,
        "temperature": t.astype("<f4").tobytes(),
        "precipitation": p.astype("<f4").tobytes(),
    }
    (root_map / "climate_monthly.msgpack").write_bytes(msgpack.packb(monthly))
    if branch:
        write_yaml(
            world / "branches" / branch / "branch.yaml", {"name": branch, "fork_layer": "climate"}
        )
        overlay = world / "branches" / branch / "maps" / planet
        overlay.mkdir(parents=True)
        (overlay / "climate_monthly.msgpack").write_bytes(
            msgpack.packb({**monthly, "source": "branch"})
        )
        if own_yearly:
            write_engine_climate_yearly(
                m,
                overlay,
                t_monthly=t + 1,
                p_monthly=p * 2,
                climate_source="controlled branch input",
            )
    monkeypatch.setattr(maps_module, "_manager", WorldManager(worlds))
    app = FastAPI()
    app.include_router(maps_module.router)
    client = TestClient(app)
    output = tmp_path / "static"
    assert exporter._export_map_data(world, output, branch) == [planet]
    query = f"?branch={branch}" if branch else ""
    base = f"/api/worlds/probe/maps/{planet}"
    api_meta = client.get(base + "/meta" + query)
    assert api_meta.status_code == 200
    static_meta = json.loads((output / planet / "meta.json").read_text(encoding="utf-8"))
    assert api_meta.json() == static_meta
    assert static_meta["format_version"] == FORMAT_VERSION
    assert static_meta["projection"] == "equirectangular"
    assert static_meta["generation_date"] == "2026-01-01"
    assert static_meta["time"]["reference_year_days"] == 365.25
    assert static_meta["num_plates"] == 2
    assert static_meta["radius_km"] == 6371
    for endpoint, filename in [
        ("elevation", "elevation.png"),
        ("climate-monthly", "climate_monthly.msgpack"),
        ("climate-yearly", "climate_yearly.msgpack"),
    ]:
        response = client.get(base + "/" + endpoint + query)
        assert response.status_code == 200
        assert response.content == (output / planet / filename).read_bytes()
        assert (
            client.get(
                base + "/" + endpoint + query, headers={"If-None-Match": response.headers["etag"]}
            ).status_code
            == 304
        )
    yearly = msgpack.unpackb((output / planet / "climate_yearly.msgpack").read_bytes(), raw=False)
    assert yearly["profile"].startswith("ucc-v2")
    assert yearly["data_source"] == "model"
    assert yearly["p_total_basis"] == "reference_year"
    assert yearly["p_total_mm"] == yearly["p_total_ref365_mm"]
    multiplier = 2 if branch and own_yearly else 1
    np.testing.assert_allclose(
        np.frombuffer(yearly["p_total_mm"], dtype="<f4"),
        [1200 * multiplier, 960 * multiplier, 120 * multiplier],
    )
    # Ocean supply is not applicable; frozen land lies outside the demand domain.
    assert list(yearly["ucc_supply"])[1:] == [255, 255]
    assert np.isnan(np.frombuffer(yearly["ai"], dtype="<f4")[2])


def test_metadata_serialization_uses_defaults_and_keeps_provenance() -> None:
    result = map_metadata_result(
        {
            "planet_id": "x",
            "width": "64",
            "radius_km": 5000,
            "format_version": "stale",
            "time": {"reference_year_days": 1},
        }
    )
    assert result["width"] == 64
    assert result["height"] == 2048
    assert result["format_version"] == FORMAT_VERSION
    assert result["time"]["reference_year_days"] == 365.25
    assert result["radius_km"] == 5000


def test_metadata_extra_nonfinite_is_strict_json() -> None:
    result = map_metadata_result({"planet_id": "x", "diagnostic": [float("nan"), float("inf")]})
    assert json.loads(json.dumps(result, allow_nan=False))["diagnostic"] == [None, None]


@pytest.mark.parametrize("branch", [None, "gcm"])
def test_static_export_excludes_internal_map_snapshots(
    exporter: Any, tmp_path: Path, branch: str | None
) -> None:
    world = tmp_path / "world"
    scope = world if branch is None else world / "branches" / branch
    for name in ["planet_x", "_baseline", ".scratch"]:
        write_yaml(scope / "maps" / name / "map.yaml", {"planet_id": name})
        (scope / "maps" / name / "elevation.png").write_bytes(b"png")
    output = tmp_path / "static"
    assert exporter._export_map_data(world, output, branch) == ["planet_x"]
    assert not (output / "_baseline").exists()
    assert not (output / ".scratch").exists()
