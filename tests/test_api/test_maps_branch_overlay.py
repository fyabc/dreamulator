"""API tests for per-file branch → root fallback on map endpoints.

A branch that forks at the climate layer legitimately ships only climate
products in its own ``maps/`` dir; terrain products (map.yaml, elevation.png,
plates/features…) live only in the root world's ``maps/``.  Directory-level
resolution alone 404s those files for such branches (the branch dir exists,
so it wins).  These tests pin the per-file overlay semantics: files present
in the branch overlay win, missing files fall back to the root world.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import maps as maps_module
from dreamulator.world_manager import WorldManager
from tests.test_api.test_world_documents import _write, _write_yaml

if TYPE_CHECKING:
    from pathlib import Path

PLANET = "planet_x"
ROOT_MONTHLY = b"root-monthly-climate"
BRANCH_MONTHLY = b"branch-gcm-monthly-climate"
ROOT_YEARLY = b"root-yearly-climate"
ROOT_ELEVATION = b"\x89PNG-root-elevation"

BASE = f"/api/worlds/test-world/maps/{PLANET}"
BRANCH_Q = "?branch=gcm-branch"


def _write_bin(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _build_world(world: Path) -> None:
    # Root world: full terrain + climate products.
    root_maps = world / "maps" / PLANET
    _write_yaml(root_maps / "map.yaml", {"planet_id": PLANET, "width": 8, "height": 4})
    _write_bin(root_maps / "elevation.png", ROOT_ELEVATION)
    _write_bin(root_maps / "climate_monthly.msgpack", ROOT_MONTHLY)
    _write_bin(root_maps / "climate_yearly.msgpack", ROOT_YEARLY)
    _write(
        root_maps / "plates.json",
        '{"plates": [{"id": "p1", "name": "Plate One", '
        '"euler_pole": {"x": 0.0, "y": 0.0, "z": 1.0, "omega_rad_yr": 1e-8}}]}',
    )
    _write(
        root_maps / "features.json",
        '{"features": [{"id": "f1", "type": "river", "coordinates": [[0.0, 1.0]]}]}',
    )
    # Climate-fork branch: only its own climate product, no terrain products.
    branch = world / "branches" / "gcm-branch"
    _write_bin(branch / "maps" / PLANET / "climate_monthly.msgpack", BRANCH_MONTHLY)
    _write_yaml(branch / "branch.yaml", {"name": "gcm-branch", "fork_layer": "climate"})


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    worlds_dir = tmp_path / "worlds"
    _build_world(worlds_dir / "test-world")
    monkeypatch.setattr(maps_module, "_manager", WorldManager(worlds_dir))
    app = FastAPI()
    app.include_router(maps_module.router)
    return TestClient(app)


def test_branch_meta_falls_back_to_root(client: TestClient) -> None:
    r = client.get(f"{BASE}/meta{BRANCH_Q}")
    assert r.status_code == 200
    assert r.json()["planet_id"] == PLANET


def test_branch_elevation_falls_back_to_root(client: TestClient) -> None:
    r = client.get(f"{BASE}/elevation{BRANCH_Q}")
    assert r.status_code == 200
    assert r.content == ROOT_ELEVATION


def test_branch_climate_monthly_prefers_overlay(client: TestClient) -> None:
    """The branch's own climate product wins over root's — no fallback."""
    r = client.get(f"{BASE}/climate-monthly{BRANCH_Q}")
    assert r.status_code == 200
    assert r.content == BRANCH_MONTHLY


def test_branch_climate_yearly_falls_back_to_root(client: TestClient) -> None:
    r = client.get(f"{BASE}/climate-yearly{BRANCH_Q}")
    assert r.status_code == 200
    assert r.content == ROOT_YEARLY


def test_branch_climate_missing_everywhere_still_404(client: TestClient) -> None:
    """Fallback does not mask genuinely missing data (no such planet anywhere)."""
    r = client.get("/api/worlds/test-world/maps/planet_y/climate-yearly" + BRANCH_Q)
    assert r.status_code == 404


def test_branch_plates_falls_back_to_root(client: TestClient) -> None:
    r = client.get(f"{BASE}/plates{BRANCH_Q}")
    assert r.status_code == 200
    assert [p["id"] for p in r.json()] == ["p1"]


def test_branch_features_falls_back_to_root(client: TestClient) -> None:
    r = client.get(f"{BASE}/features{BRANCH_Q}")
    assert r.status_code == 200
    assert [f["id"] for f in r.json()] == ["f1"]


def test_root_endpoints_unaffected(client: TestClient) -> None:
    """Without ?branch the root world's own data is served (no regression)."""
    assert client.get(f"{BASE}/meta").status_code == 200
    assert client.get(f"{BASE}/elevation").content == ROOT_ELEVATION
    assert client.get(f"{BASE}/climate-monthly").content == ROOT_MONTHLY
