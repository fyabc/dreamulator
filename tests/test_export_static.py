"""Tests for scripts/release/export_static.py markdown document rendering.

The script is not a package, so it is loaded via ``importlib``. Verifies that
``_export_dir_documents`` and ``_export_layer_data`` render template bodies
against the entity-addressed fact context (``system_catalog.yaml`` + summaries)
and emit the ``rendered`` flag, and degrade to the raw template when the
context is unavailable.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def export_static() -> Any:
    spec = importlib.util.spec_from_file_location(
        "export_static_under_test", _ROOT / "scripts" / "release" / "export_static.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
# Render context (entity-addressed) passed directly to _export_dir_documents.
CONTEXT: dict[str, object] = {"entities": {"planet_test": {"solar_day_days": 3.4157}}}
# system_catalog.yaml written by _build_world — build_fact_context flattens it
# to the same entity shape as CONTEXT.
SAMPLE_CATALOG: dict[str, object] = {
    "stars": [],
    "bodies": [
        {
            "id": "planet_test",
            "name": "Test",
            "body_type": "planet",
            "derived": {"solar_day_days": 3.4157},
        }
    ],
}


@pytest.fixture
def doc_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    _write(d / "sample.md", TEMPLATE_DOC)
    return d


def test_export_dir_documents_renders(export_static: Any, doc_dir: Path) -> None:
    docs = export_static._export_dir_documents(doc_dir, CONTEXT)
    assert docs is not None
    assert len(docs) == 1
    doc = docs[0]
    assert doc["rendered"] is True
    assert doc["content"] == "太阳日 3.42 天\n"
    assert doc["title"] == "Sample"
    assert doc["frontmatter"]["type"] == "stellar"


def test_export_dir_documents_degrades_without_context(export_static: Any, doc_dir: Path) -> None:
    docs = export_static._export_dir_documents(doc_dir, None)
    assert docs is not None
    doc = docs[0]
    assert doc["rendered"] is False
    assert "{{ entities.planet_test.solar_day_days | round2 }}" in doc["content"]


def test_export_dir_documents_empty_returns_none(export_static: Any, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert export_static._export_dir_documents(empty, CONTEXT) is None
    assert export_static._export_dir_documents(tmp_path / "missing", CONTEXT) is None


def _build_world(world: Path) -> None:
    _write(world / "world.yaml", "name: test-world\n")
    _write(world / "layers" / "astronomy" / "input" / "stellar.yaml", "stars: []\n")
    _write(world / "layers" / "astronomy" / "input" / "sample.md", TEMPLATE_DOC)
    _write_yaml(world / "layers" / "astronomy" / "derived" / "system_catalog.yaml", SAMPLE_CATALOG)
    _write(world / "design-notes" / "note.md", TEMPLATE_DOC)


def test_export_layer_data_renders_documents(export_static: Any, tmp_path: Path) -> None:
    world = tmp_path / "test-world"
    _build_world(world)

    result = export_static._export_layer_data(world)
    assert "astronomy_documents" in result
    astro = result["astronomy_documents"]
    sample = next(d for d in astro if d["filename"] == "sample.md")
    assert sample["rendered"] is True
    assert sample["content"] == "太阳日 3.42 天\n"

    assert "design-notes_documents" in result
    note = result["design-notes_documents"][0]
    assert note["rendered"] is True
    assert note["content"] == "太阳日 3.42 天\n"


def test_export_layer_data_branch_without_derived_degrades(
    export_static: Any, tmp_path: Path
) -> None:
    world = tmp_path / "test-world"
    _build_world(world)
    branch = world / "branches" / "unbuilt"
    _write_yaml(branch / "branch.yaml", {"name": "unbuilt", "fork_layer": "astronomy"})
    _write(branch / "layers" / "astronomy" / "input" / "stellar.yaml", "stars: []\n")
    _write(branch / "layers" / "astronomy" / "input" / "sample.md", TEMPLATE_DOC)

    result = export_static._export_layer_data(world, "unbuilt")
    astro = result["astronomy_documents"]
    sample = next(d for d in astro if d["filename"] == "sample.md")
    assert sample["rendered"] is False
    assert "{{ entities.planet_test.solar_day_days | round2 }}" in sample["content"]


def test_export_map_data_branch_overlay_without_elevation(
    export_static: Any, tmp_path: Path
) -> None:
    """Branch-only planet (no root maps): a climate-fork branch maps dir
    lacking terrain products must still be exported (the static frontend
    would otherwise fall back to root climate), and must NOT get empty
    plates placeholders (those would shadow root's real files)."""
    world = tmp_path / "test-world"
    _build_world(world)
    branch_maps = world / "branches" / "gcm" / "maps" / "planet_x"
    _write_yaml(world / "branches" / "gcm" / "branch.yaml", {"name": "gcm"})
    branch_maps.mkdir(parents=True)
    (branch_maps / "climate_monthly.msgpack").write_bytes(b"gcm-monthly")

    out = tmp_path / "out" / "maps"
    planets = export_static._export_map_data(world, out, branch="gcm")

    assert planets == ["planet_x"]
    assert (out / "planet_x" / "climate_monthly.msgpack").read_bytes() == b"gcm-monthly"
    assert not (out / "planet_x" / "elevation.png").exists()
    assert not (out / "planet_x" / "plates.json").exists()
    import json as _json

    assert _json.loads((out / "maps.json").read_text(encoding="utf-8")) == ["planet_x"]


def test_export_map_data_branch_overlay_inherits_root_files(
    export_static: Any, tmp_path: Path
) -> None:
    """Per-file branch inheritance: files the overlay lacks are filled from
    the root world's maps dir so the static export is self-contained (host
    404 semantics are not reliable — vite preview answers missing files
    with 200 HTML).  The branch's own files always win."""
    world = tmp_path / "test-world"
    _build_world(world)
    root_maps = world / "maps" / "planet_x"
    _write_yaml(root_maps / "map.yaml", {"planet_id": "planet_x"})
    (root_maps / "elevation.png").write_bytes(b"root-png")
    (root_maps / "climate_monthly.msgpack").write_bytes(b"root-monthly")
    (root_maps / "climate_yearly.msgpack").write_bytes(b"root-yearly")
    _write(root_maps / "plates.json", '{"plates": [{"id": "root-plate"}]}')
    branch_maps = world / "branches" / "gcm" / "maps" / "planet_x"
    _write_yaml(world / "branches" / "gcm" / "branch.yaml", {"name": "gcm"})
    branch_maps.mkdir(parents=True)
    (branch_maps / "climate_monthly.msgpack").write_bytes(b"gcm-monthly")

    out = tmp_path / "out" / "maps"
    planets = export_static._export_map_data(world, out, branch="gcm")

    assert planets == ["planet_x"]
    planet_out = out / "planet_x"
    # Branch's own climate wins; everything else is filled from root.
    assert (planet_out / "climate_monthly.msgpack").read_bytes() == b"gcm-monthly"
    assert (planet_out / "climate_yearly.msgpack").read_bytes() == b"root-yearly"
    assert (planet_out / "elevation.png").read_bytes() == b"root-png"
    import json as _json

    meta = _json.loads((planet_out / "meta.json").read_text(encoding="utf-8"))
    assert meta["planet_id"] == "planet_x"
    plates = _json.loads((planet_out / "plates.json").read_text(encoding="utf-8"))
    assert plates == {"plates": [{"id": "root-plate"}]}


def test_export_map_data_root_writes_placeholders(export_static: Any, tmp_path: Path) -> None:
    """Root export keeps the elevation gate and empty plates
    placeholders (404-noise avoidance) — unchanged by the branch fix."""
    world = tmp_path / "test-world"
    _build_world(world)
    root_maps = world / "maps" / "planet_x"
    root_maps.mkdir(parents=True)
    (root_maps / "elevation.png").write_bytes(b"png")

    out = tmp_path / "out" / "maps"
    planets = export_static._export_map_data(world, out, branch=None)

    assert planets == ["planet_x"]
    import json as _json

    assert _json.loads((out / "planet_x" / "plates.json").read_text(encoding="utf-8")) == {
        "plates": []
    }
