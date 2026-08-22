"""API integration tests for the layer/design document endpoints.

Verifies Jinja2 template rendering wired into ``_get_md_document``: successful
render, graceful degradation when ``system_catalog.yaml`` is missing, branch
context selection, and the metadata-only list endpoints.

Uses ``monkeypatch`` to swap the module-level ``WorldManager`` singleton with
one pointed at a temp worlds dir, and a minimal FastAPI app mounting only the
worlds router (avoids importing the full ``dreamulator.api`` app and its
map/civmap/narrate routes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import worlds as worlds_module
from dreamulator.world_manager import WorldManager

if TYPE_CHECKING:
    from pathlib import Path

SAMPLE_CATALOG: dict[str, object] = {
    "stars": [],
    "bodies": [
        {
            "id": "planet_test",
            "name": "Test",
            "body_type": "planet",
            "physical": {"mass_earth": 1.2},
            "derived": {"solar_day_days": 3.4157},
        }
    ],
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(text)


def _write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


TEMPLATE_DOC = (
    '---\ntitle: "Sample"\ntype: stellar\ntags: [t]\n---\n'
    "太阳日 {{ entities.planet_test.solar_day_days | round2 }} 天\n"
)
PLAIN_DOC = '---\ntitle: "Plain"\ntype: overview\n---\nno placeholders here\n'


def _build_world(world: Path) -> None:
    _write(world / "layers" / "astronomy" / "input" / "sample.md", TEMPLATE_DOC)
    _write(world / "layers" / "astronomy" / "input" / "plain.md", PLAIN_DOC)
    _write_yaml(world / "layers" / "astronomy" / "derived" / "system_catalog.yaml", SAMPLE_CATALOG)
    _write(world / "design-notes" / "note.md", TEMPLATE_DOC)


def _add_branch(world: Path, name: str, *, with_derived: bool) -> None:
    branch = world / "branches" / name
    _write_yaml(branch / "branch.yaml", {"name": name, "fork_layer": "astronomy"})
    _write(branch / "layers" / "astronomy" / "input" / "sample.md", TEMPLATE_DOC)
    if with_derived:
        _write_yaml(
            branch / "layers" / "astronomy" / "derived" / "system_catalog.yaml",
            {
                "stars": [],
                "bodies": [
                    {
                        "id": "planet_test",
                        "body_type": "planet",
                        "derived": {"solar_day_days": 9.999},
                    }
                ],
            },
        )


@pytest.fixture
def worlds_dir(tmp_path: Path) -> Path:
    worlds = tmp_path / "worlds"
    _build_world(worlds / "test-world")
    return worlds


@pytest.fixture
def client(worlds_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(worlds_module, "_manager", WorldManager(worlds_dir))
    app = FastAPI()
    app.include_router(worlds_module.router)
    return TestClient(app)


def _catalog_file(worlds_dir: Path) -> Path:
    return worlds_dir / "test-world" / "layers" / "astronomy" / "derived" / "system_catalog.yaml"


def test_renders_template_with_context(client: TestClient) -> None:
    resp = client.get("/api/worlds/test-world/layer-documents/astronomy/sample.md")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rendered"] is True
    assert data["content"] == "太阳日 3.42 天\n"
    assert "{{" not in data["content"]


def test_degrades_when_system_catalog_missing(client: TestClient, worlds_dir: Path) -> None:
    _catalog_file(worlds_dir).unlink()

    resp = client.get("/api/worlds/test-world/layer-documents/astronomy/sample.md")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rendered"] is False
    assert "{{ entities.planet_test.solar_day_days | round2 }}" in data["content"]


def test_design_documents_render(client: TestClient) -> None:
    resp = client.get("/api/worlds/test-world/design-documents/note.md")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rendered"] is True
    assert data["content"] == "太阳日 3.42 天\n"


def test_plain_doc_renders_true_even_without_context(client: TestClient, worlds_dir: Path) -> None:
    _catalog_file(worlds_dir).unlink()

    resp = client.get("/api/worlds/test-world/layer-documents/astronomy/plain.md")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rendered"] is True
    assert data["content"] == "no placeholders here\n"


def test_list_endpoint_returns_metadata_only(client: TestClient) -> None:
    resp = client.get("/api/worlds/test-world/layer-documents/astronomy")
    assert resp.status_code == 200
    docs = resp.json()
    assert {d["filename"] for d in docs} == {"sample.md", "plain.md"}
    for d in docs:
        assert set(d) == {"filename", "title", "type", "period", "tags"}


def test_invalid_layer_returns_400(client: TestClient) -> None:
    resp = client.get("/api/worlds/test-world/layer-documents/bogus")
    assert resp.status_code == 400


def test_missing_document_returns_404(client: TestClient) -> None:
    resp = client.get("/api/worlds/test-world/layer-documents/astronomy/nope.md")
    assert resp.status_code == 404


def test_missing_world_returns_404(client: TestClient) -> None:
    resp = client.get("/api/worlds/ghost/layer-documents/astronomy")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Branch context selection
# ---------------------------------------------------------------------------


@pytest.fixture
def branch_client(worlds_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    world = worlds_dir / "test-world"
    _add_branch(world, "built", with_derived=True)
    _add_branch(world, "unbuilt", with_derived=False)

    monkeypatch.setattr(worlds_module, "_manager", WorldManager(worlds_dir))
    app = FastAPI()
    app.include_router(worlds_module.router)
    return TestClient(app)


def test_branch_with_derived_uses_own_params(branch_client: TestClient) -> None:
    resp = branch_client.get(
        "/api/worlds/test-world/layer-documents/astronomy/sample.md?branch=built"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rendered"] is True
    assert data["content"] == "太阳日 10.0 天\n"


def test_branch_input_without_derived_degrades(branch_client: TestClient) -> None:
    resp = branch_client.get(
        "/api/worlds/test-world/layer-documents/astronomy/sample.md?branch=unbuilt"
    )
    assert resp.status_code == 200
    data = resp.json()
    # Must NOT fall back to root params; raw template is returned.
    assert data["rendered"] is False
    assert "{{ entities.planet_test.solar_day_days | round2 }}" in data["content"]


def test_root_world_unaffected_by_branches(branch_client: TestClient) -> None:
    resp = branch_client.get("/api/worlds/test-world/layer-documents/astronomy/sample.md")
    assert resp.json()["content"] == "太阳日 3.42 天\n"
