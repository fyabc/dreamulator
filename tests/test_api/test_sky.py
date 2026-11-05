"""API integration tests for the sky-ephemeris endpoint.

Pins the dedicated ``GET /api/worlds/{world}/sky`` route: default observer
from ``target_body_id``, parameter handling, the ``include_events`` fast
path, error mapping (404 world/body, 422 spin-axis/latitude), and the
stat-validated entities cache that keeps the slider fast path off the
~135 ms-per-call YAML re-parse.

Minimal FastAPI app mounting only the worlds router (test_world_documents
pattern); the module-level sky cache is cleared per test.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import worlds as worlds_module
from dreamulator.world_manager import WorldManager

if TYPE_CHECKING:
    from pathlib import Path


def _orbit(body_id: str, parent_id: str, a: float, e: float, i: float) -> dict[str, Any]:
    return {
        "body_id": body_id,
        "parent_id": parent_id,
        "semi_major_axis_au": a,
        "eccentricity": e,
        "inclination_deg": i,
        "longitude_ascending_node_deg": 0.0,
        "argument_of_periapsis_deg": 0.0,
        "mean_anomaly_epoch_deg": 0.0,
        "epoch_year": 0.0,
    }


def _body(
    body_id: str,
    parent_id: str,
    *,
    radius_km: float,
    rotation_days: float,
    tilt: float,
    derived: dict[str, Any] | None = None,
    body_type: str = "natural_satellite",
) -> dict[str, Any]:
    return {
        "id": body_id,
        "name": body_id,
        "body_type": body_type,
        "parent_id": parent_id,
        "orbit": {"period_days": rotation_days},
        "physical": {
            "radius_km": radius_km,
            "rotation_period_days": rotation_days,
            "axial_tilt_deg": tilt,
        },
        "derived": derived or {},
    }


#: A three-rung catalog: a locked satellite (target), a planet with the spin
#: azimuth (observable), and a planet without one (spin-axis 422 case).
CATALOG: dict[str, Any] = {
    "stars": [
        {
            "id": "star_sol",
            "name": "Sol",
            "luminosity_sol": 1.0,
            "radius_sol": 1.0,
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        }
    ],
    "orbits": [
        _orbit("planet_terra", "star_sol", 1.0, 0.0167, 0.0),
        _orbit("satellite_luna", "planet_terra", 0.00257, 0.0549, 5.145),
        _orbit("planet_reject", "star_sol", 2.0, 0.05, 1.0),
    ],
    "bodies": [
        _body(
            "planet_terra",
            "star_sol",
            radius_km=6371.0,
            rotation_days=365.25,
            tilt=23.4,
            derived={"tidally_locked": False, "spin_axis_ecliptic_longitude_deg": 0.0},
            body_type="planet",
        ),
        _body(
            "satellite_luna",
            "planet_terra",
            radius_km=1737.0,
            rotation_days=27.3,
            tilt=0.0,
            derived={"tidally_locked": True, "solar_day_days": 29.5},
        ),
        _body(
            "planet_reject",
            "star_sol",
            radius_km=5000.0,
            rotation_days=500.0,
            tilt=11.0,
            derived={"tidally_locked": False},
            body_type="planet",
        ),
    ],
    "target_body_id": "satellite_luna",
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    worlds = tmp_path / "worlds"
    catalog_path = worlds / "test-world" / "layers" / "astronomy" / "derived"
    catalog_path.mkdir(parents=True)
    with (catalog_path / "system_catalog.yaml").open("w", encoding="utf-8") as fh:
        yaml.safe_dump(CATALOG, fh, allow_unicode=True)
    input_dir = worlds / "test-world" / "layers" / "astronomy" / "input"
    input_dir.mkdir(parents=True)
    # The resolver only exposes a layer once its input side has a file
    # (test_guard_facts' marker-file precedent); an empty dir does not count.
    (input_dir / "stellar.yaml").write_text("stars: []\n", encoding="utf-8")
    monkeypatch.setattr(worlds_module, "_manager", WorldManager(worlds))
    worlds_module._SKY_ENTITIES.clear()
    app = FastAPI()
    app.include_router(worlds_module.router)
    return TestClient(app)


def test_sky_default_observer_and_shape(client: TestClient) -> None:
    resp = client.get("/api/worlds/test-world/sky", params={"at": 10.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["observer_id"] == "satellite_luna"  # catalog target_body_id
    assert data["at_days"] == 10.0
    ids = {row["body_id"] for row in data["targets"]}
    assert {"star_sol", "planet_terra", "planet_reject"} <= ids
    row = next(r for r in data["targets"] if r["body_id"] == "planet_terra")
    assert -90.0 <= row["altitude_deg"] <= 90.0
    assert 0.0 <= row["azimuth_deg"] < 360.0
    assert row["rise_state"] is not None  # events on by default


def test_sky_params_and_targets_filter(client: TestClient) -> None:
    resp = client.get(
        "/api/worlds/test-world/sky",
        params={"from": "planet_terra", "lat": 10, "lon": 20, "at": 5, "targets": "star_sol"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["observer_id"] == "planet_terra"
    assert data["lat_deg"] == 10.0
    assert [r["body_id"] for r in data["targets"]] == ["star_sol"]


def test_sky_fast_path_nulls_events(client: TestClient) -> None:
    resp = client.get("/api/worlds/test-world/sky", params={"include_events": "false"})
    assert resp.status_code == 200
    for row in resp.json()["targets"]:
        assert row["rise_state"] is None
        assert row["next_rise_days"] is None
        assert row["next_set_days"] is None
        assert isinstance(row["altitude_deg"], float)


def test_sky_error_mapping(client: TestClient) -> None:
    assert client.get("/api/worlds/no-such/sky").status_code == 404
    assert (
        client.get("/api/worlds/test-world/sky", params={"targets": "satellite_ghost"}).status_code
        == 404
    )
    assert client.get("/api/worlds/test-world/sky", params={"lat": 91}).status_code == 422
    # A planet without the spin-axis azimuth is rejected with the engine's
    # actionable message, not silently guessed.
    resp = client.get("/api/worlds/test-world/sky", params={"from": "planet_reject"})
    assert resp.status_code == 422
    assert "spin-axis" in resp.json()["detail"]


def test_sky_entities_cache_stat_validated(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = {"count": 0}
    real_load = worlds_module._load_yaml

    def counting_load(path: Any) -> Any:
        if str(path).endswith("system_catalog.yaml"):
            loads["count"] += 1
        return real_load(path)

    monkeypatch.setattr(worlds_module, "_load_yaml", counting_load)

    assert client.get("/api/worlds/test-world/sky").status_code == 200
    assert loads["count"] == 1
    # Same fingerprint → cached, no re-parse.
    assert client.get("/api/worlds/test-world/sky", params={"at": 3}).status_code == 200
    assert loads["count"] == 1

    # Rewrite the catalog (different content ⇒ different size/mtime) → reload.
    catalog = dict(CATALOG)
    catalog["bodies"] = [b for b in CATALOG["bodies"] if b["id"] != "planet_reject"]
    path = (
        tmp_path
        / "worlds"
        / "test-world"
        / "layers"
        / "astronomy"
        / "derived"
        / "system_catalog.yaml"
    )
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(catalog, fh, allow_unicode=True)
    os.utime(path)  # ensure mtime moves even with coarse filesystem granularity

    resp = client.get("/api/worlds/test-world/sky")
    assert resp.status_code == 200
    assert loads["count"] == 2
    ids = {row["body_id"] for row in resp.json()["targets"]}
    assert "planet_reject" not in ids


def test_sky_background_missing_is_404(client: TestClient) -> None:
    worlds_module._SKY_BACKGROUND.clear()
    resp = client.get("/api/worlds/test-world/sky/background")
    assert resp.status_code == 404


def test_sky_background_serves_and_caches(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worlds_module._SKY_BACKGROUND.clear()
    bg = {
        "frame": "ecliptic",
        "starfield": {"seed": 1, "count": 2, "magnitude_limit": 6.0},
        "stars": [
            {
                "id": "bg_star_00000",
                "name": None,
                "magnitude": 3.0,
                "temperature_k": 5000.0,
                "unit": [0.0, 0.0, 1.0],
                "source": "starfield",
            }
        ],
        "deep_sky": [],
        "galactic_band": None,
        "transient_events": [],
    }
    path = (
        tmp_path
        / "worlds"
        / "test-world"
        / "layers"
        / "astronomy"
        / "derived"
        / "sky_background.yaml"
    )
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(bg, fh, allow_unicode=True)

    loads = {"count": 0}
    real_load = worlds_module._load_yaml

    def counting_load(p: Any) -> Any:
        if str(p).endswith("sky_background.yaml"):
            loads["count"] += 1
        return real_load(p)

    monkeypatch.setattr(worlds_module, "_load_yaml", counting_load)

    resp = client.get("/api/worlds/test-world/sky/background")
    assert resp.status_code == 200
    assert resp.json()["stars"][0]["id"] == "bg_star_00000"
    assert loads["count"] == 1
    # Stat-validated cache: second call reuses the parsed table.
    assert client.get("/api/worlds/test-world/sky/background").status_code == 200
    assert loads["count"] == 1


def test_sky_culture_missing_is_404(client: TestClient) -> None:
    worlds_module._SKY_CULTURE.clear()
    resp = client.get("/api/worlds/test-world/sky/culture")
    assert resp.status_code == 404


def test_sky_culture_serves_and_caches(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worlds_module._SKY_CULTURE.clear()
    civ = tmp_path / "worlds" / "test-world" / "layers" / "civilization"
    (civ / "input").mkdir(parents=True)
    # The resolver only exposes a layer once its input side has a file
    # (the fixture's stellar.yaml marker precedent).
    (civ / "input" / "civilizations.yaml").write_text("civilizations: []\n", encoding="utf-8")
    (civ / "derived").mkdir(parents=True)
    culture = {
        "cultures": [
            {
                "id": "culture_test",
                "name": "Test Culture",
                "description": None,
                "star_names": {"star_a": "the Nail"},
                "asterisms": [
                    {
                        "id": "asterism_test",
                        "name": "Figure",
                        "meaning": None,
                        "lines": [["star_a", "dso_x"]],
                    }
                ],
            }
        ]
    }
    path = civ / "derived" / "sky_culture.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(culture, fh, allow_unicode=True)

    loads = {"count": 0}
    real_load = worlds_module._load_yaml

    def counting_load(p: Any) -> Any:
        if str(p).endswith("sky_culture.yaml"):
            loads["count"] += 1
        return real_load(p)

    monkeypatch.setattr(worlds_module, "_load_yaml", counting_load)

    resp = client.get("/api/worlds/test-world/sky/culture")
    assert resp.status_code == 200
    assert resp.json()["cultures"][0]["asterisms"][0]["id"] == "asterism_test"
    assert loads["count"] == 1
    # Stat-validated cache: second call reuses the parsed table.
    assert client.get("/api/worlds/test-world/sky/culture").status_code == 200
    assert loads["count"] == 1
