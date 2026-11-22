"""Tests for scripts/release/export_static.py markdown document rendering.

The script is not a package, so it is loaded via ``importlib``. Verifies that
``_export_dir_documents`` and ``_export_layer_data`` render template bodies
against the entity-addressed fact context (``system_catalog.yaml`` + summaries)
and emit the ``rendered`` flag, and degrade to the raw template when the
context is unavailable.
"""

from __future__ import annotations

import importlib.util
import json
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from dreamulator.civmap.manager import CivMapManager
from dreamulator.climate_trial import BROWSER_TRIAL_MAX_CELLS, TrialSource
from dreamulator.map.export import MESH_FILENAME, save_cvt_mesh
from dreamulator.map.koppen_product import OBSERVED_KOPPEN_FILE
from dreamulator.map.pipeline_types import TerrainPipelineConfig

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


def test_browser_trial_exports_resolved_grid_and_respects_budget(
    export_static: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mesh = tmp_path / "cvt_mesh.msgpack.gz"
    config = TerrainPipelineConfig(axial_tilt_deg=63.44, greenhouse_warming_K=30.0)

    def resolve(world: Path, planet: str, branch: str | None) -> TrialSource:
        assert (world, planet, branch) == (tmp_path, "planet_test", "model")
        return TrialSource(config, mesh)

    monkeypatch.setattr(export_static, "resolve_trial_source", resolve)
    export_static._export_browser_trial(tmp_path, "planet_test", "model", tmp_path, mesh, 18032)
    manifest = tmp_path / "climate_trial.json"
    trial = json.loads(manifest.read_text(encoding="utf-8"))
    assert trial["mesh"] == mesh.name
    assert trial["cells"] == 18032
    assert trial["forcing"]["axial_tilt_deg"] == 63.44
    assert trial["config"]["greenhouse_warming_K"] == 30.0
    assert not (tmp_path / "climate_trial_mesh.bin").exists()

    export_static._export_browser_trial(
        tmp_path, "planet_test", "model", tmp_path, mesh, BROWSER_TRIAL_MAX_CELLS + 1
    )
    assert json.loads(manifest.read_text(encoding="utf-8")) == {
        "version": 1,
        "reason": "browser_grid_limit",
    }


def test_browser_trial_uses_distinct_source_grid_when_needed(
    export_static: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_mesh = tmp_path / "parent" / "cvt_mesh.json"
    _write(source_mesh, '{"num_cells": 1200}')
    displayed_mesh = tmp_path / "branch" / "cvt_mesh.msgpack.gz"
    source = TrialSource(TerrainPipelineConfig(), source_mesh)
    monkeypatch.setattr(export_static, "resolve_trial_source", lambda *_args: source)

    export_static._export_browser_trial(
        tmp_path, "planet_test", "model", tmp_path, displayed_mesh, 600
    )
    manifest = json.loads((tmp_path / "climate_trial.json").read_text(encoding="utf-8"))
    assert manifest["cells"] == 1200
    assert manifest["mesh"] == "climate_trial_mesh.bin"
    assert (tmp_path / manifest["mesh"]).read_bytes() == source_mesh.read_bytes()


def test_browser_trial_does_not_enable_reference_anchor(export_static: Any, tmp_path: Path) -> None:
    _write_yaml(tmp_path / "world.yaml", {"reference_anchor": True})
    export_static._export_browser_trial(tmp_path, "planet_earth", None, tmp_path, None, None)
    assert json.loads((tmp_path / "climate_trial.json").read_text(encoding="utf-8")) == {
        "version": 1,
        "reason": "reference_anchor",
    }


@pytest.mark.parametrize("legacy", [False, True])
def test_export_civmap_reference_matches_api(
    export_static: Any, tmp_path: Path, legacy: bool
) -> None:
    world = tmp_path / "earth"
    root_reference = world / "maps" / "earth_reference"
    legacy_reference = world / "layers" / "geological" / "input" / "maps" / "earth_reference"
    root_reference.mkdir(parents=True)
    reference = legacy_reference if legacy else root_reference
    boundary = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "id": "GRC-2884", "properties": {"iso_a2": "GR"}}],
    }
    _write(reference / "adm1.geojson", json.dumps(boundary))
    if not legacy:
        _write(legacy_reference / "adm0.geojson", "{}")
        _write(reference / "metadata.json", '{"levels":{"adm0":{},"adm1":{"features":1}}}')

    manager = CivMapManager(world)
    assert manager.list_available_levels() == ["adm1"]
    assert manager.get_boundary_geojson("adm1") == boundary
    output = tmp_path / "out"
    export_static._export_civmap_reference(world, output)
    civmap = output / "civmap"
    metadata = json.loads((civmap / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["levels"] == {"adm1": {} if legacy else {"features": 1}}
    mapping = json.loads((civmap / "mapping.json").read_text(encoding="utf-8"))
    assert mapping == manager.get_country_province_mapping() == {"GR": ["GRC-2884"]}
    assert (civmap / "adm1.geojson").read_bytes() == (reference / "adm1.geojson").read_bytes()


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


def test_export_layer_data_keeps_the_resolved_catalog_epoch(
    export_static: Any, tmp_path: Path
) -> None:
    world = tmp_path / "test-world"
    _build_world(world)
    branch = world / "branches" / "new-epoch"
    _write_yaml(branch / "branch.yaml", {"name": "new-epoch", "fork_layer": "astronomy"})
    branch_epoch = {"label": "J0"}
    _write_yaml(
        branch / "layers" / "astronomy" / "input" / "stellar.yaml",
        {"stars": [], "reference_epoch": branch_epoch},
    )
    _write_yaml(
        branch / "layers" / "astronomy" / "derived" / "system_catalog.yaml",
        {**SAMPLE_CATALOG, "reference_epoch": branch_epoch},
    )
    background = {"frame": "ecliptic", "stars": []}
    _write_yaml(world / "layers" / "astronomy" / "derived" / "sky_background.yaml", background)

    base = export_static._export_layer_data(world)
    assert "reference_epoch" not in base["system_catalog"]
    assert base["sky_background"] == background
    assert base["sky_culture"] is None
    resolved = export_static._export_layer_data(world, "new-epoch")
    assert resolved["system_catalog"]["reference_epoch"] == branch_epoch
    assert resolved["sky_background"] is None


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


def test_export_map_data_branch_omits_files_identical_to_root(
    export_static: Any, tmp_path: Path
) -> None:
    """Branch map output keeps only files that differ from the root export.

    The static client resolves a missing branch file by fetching the root
    path, which serves the identical bytes; copying every root file into
    each branch doubled the Pages payload.  The combined mesh and the
    browser-trial manifest stay in the branch directory because the browser
    climate trial loads the mesh straight from it.
    """
    world = tmp_path / "test-world"
    _build_world(world)
    root_maps = world / "maps" / "planet_x"
    _write_yaml(root_maps / "map.yaml", {"planet_id": "planet_x"})
    (root_maps / "elevation.png").write_bytes(b"root-png")
    (root_maps / "climate_monthly.msgpack").write_bytes(b"root-monthly")
    (root_maps / "climate_yearly.msgpack").write_bytes(b"root-yearly")
    _write(root_maps / "plates.json", '{"plates": [{"id": "root-plate"}]}')
    mesh = {"num_cells": 0, "cells": [], "vertices": [], "regions": [], "seed": 0}
    save_cvt_mesh(root_maps / MESH_FILENAME, mesh)
    branch_maps = world / "branches" / "gcm" / "maps" / "planet_x"
    _write_yaml(world / "branches" / "gcm" / "branch.yaml", {"name": "gcm"})
    branch_maps.mkdir(parents=True)
    (branch_maps / "climate_monthly.msgpack").write_bytes(b"gcm-monthly")
    # The build copies the inherited mesh into the branch directory, so the
    # branch's map metadata matches root and its split pair is identical.
    save_cvt_mesh(branch_maps / MESH_FILENAME, mesh)

    root_out = tmp_path / "out" / "maps"
    assert export_static._export_map_data(world, root_out, branch=None) == ["planet_x"]
    branch_out = tmp_path / "out" / "branches" / "gcm" / "maps"
    assert export_static._export_map_data(
        world, branch_out, branch="gcm", root_maps_out=root_out
    ) == ["planet_x"]

    planet_out = branch_out / "planet_x"
    # The branch's own climate wins and is written.
    assert (planet_out / "climate_monthly.msgpack").read_bytes() == b"gcm-monthly"
    # Identical-to-root files are omitted in favour of the client's fallback.
    for name in (
        "elevation.png",
        "climate_yearly.msgpack",
        "plates.json",
        "meta.json",
        "mesh_geometry.msgpack.gz",
        "mesh_fields.msgpack.gz",
    ):
        assert not (planet_out / name).exists(), name
    # The combined mesh and trial manifest stay for the browser climate trial.
    assert (planet_out / MESH_FILENAME).is_file()
    assert (planet_out / "climate_trial.json").is_file()
    import json as _json

    assert _json.loads((branch_out / "maps.json").read_text(encoding="utf-8")) == ["planet_x"]
    # The omitted paths are declared so the client reads root without a 404.
    shared = _json.loads((branch_out / "shared.json").read_text(encoding="utf-8"))
    assert "planet_x/elevation.png" in shared
    assert "planet_x/climate_yearly.msgpack" in shared
    assert "planet_x/mesh_geometry.msgpack.gz" in shared
    assert "planet_x/climate_monthly.msgpack" not in shared
    assert "planet_x/cvt_mesh.msgpack.gz" not in shared
    assert "planet_x/climate_trial.json" not in shared


def test_export_preserves_observed_koppen_only_with_its_mesh(
    export_static: Any, tmp_path: Path
) -> None:
    world = tmp_path / "test-world"
    _build_world(world)
    root_maps = world / "maps" / "planet_x"
    branch_maps = world / "branches" / "model" / "maps" / "planet_x"
    _write_yaml(root_maps / "map.yaml", {"planet_id": "planet_x"})
    _write(root_maps / "climate_metadata.json", '{"koppen_source":"observed"}')
    (root_maps / "elevation.png").write_bytes(b"root-png")
    (root_maps / OBSERVED_KOPPEN_FILE).write_bytes(b"observed-class-pixels")
    _write_yaml(world / "branches" / "model" / "branch.yaml", {"name": "model"})
    mesh = {"num_cells": 0, "cells": [], "vertices": [], "regions": [], "seed": 0}
    save_cvt_mesh(root_maps / MESH_FILENAME, mesh)

    out = tmp_path / "out" / "maps"
    planet_out = out / "planet_x"
    export_static._export_map_data(world, out, branch="model")
    assert (planet_out / OBSERVED_KOPPEN_FILE).read_bytes() == b"observed-class-pixels"
    assert json.loads((planet_out / "meta.json").read_text(encoding="utf-8"))["koppen"] == {
        "source": "observed",
        "raster": True,
    }

    branch_maps.mkdir(parents=True)
    save_cvt_mesh(branch_maps / MESH_FILENAME, mesh)
    (branch_maps / "climate_monthly.msgpack").write_bytes(b"model-monthly")
    export_static._export_map_data(world, out, branch="model")
    assert not (planet_out / OBSERVED_KOPPEN_FILE).exists()
    assert json.loads((planet_out / "meta.json").read_text(encoding="utf-8"))["koppen"] == {
        "source": "model",
        "same_grid_monthly": True,
    }


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
