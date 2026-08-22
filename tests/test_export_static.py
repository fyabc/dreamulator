"""Tests for scripts/export_static.py markdown document rendering.

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
        "export_static_under_test", _ROOT / "scripts" / "export_static.py"
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
