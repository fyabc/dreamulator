"""save/load round-trip regressions for the canonical mesh file format."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dreamulator.map.export import (
    LEGACY_MESH_FILENAME,
    MESH_FILENAME,
    find_mesh_file,
    load_cvt_mesh_model,
    save_cvt_mesh,
)
from dreamulator.map.models import CVTMesh, VoronoiCell

if TYPE_CHECKING:
    from pathlib import Path


def _tiny_mesh() -> CVTMesh:
    cells = [
        VoronoiCell(id=i, lon=float(i), lat=0.0, elevation=100.0 - 200.0 * i, neighbors=[])
        for i in range(2)
    ]
    return CVTMesh(seed=42, num_cells=2, cells=cells, adjacency={"0": [], "1": []})


def test_save_to_legacy_json_path_canonicalizes(tmp_path: Path) -> None:
    # Regression (2026-09-25 root earth re-import): save_cvt_mesh called with
    # the legacy ``cvt_mesh.json`` path used to write the msgpack.gz bytes
    # INTO that path and then unlink it as its own "legacy sibling" — the mesh
    # vanished entirely.  The legacy target must canonicalize to the
    # msgpack.gz filename, and the round-trip must survive.
    legacy_path = tmp_path / LEGACY_MESH_FILENAME
    save_cvt_mesh(legacy_path, _tiny_mesh())

    assert not legacy_path.exists()  # never left under the legacy name
    canonical = tmp_path / MESH_FILENAME
    assert canonical.exists()
    assert find_mesh_file(tmp_path) == canonical

    mesh = load_cvt_mesh_model(canonical)
    assert mesh.num_cells == 2
    assert mesh.cells[1].elevation == -100.0


def test_save_over_legacy_sibling_replaces_it(tmp_path: Path) -> None:
    # A stale legacy json next to the canonical target is removed so a planet
    # never carries two divergent meshes.
    legacy_path = tmp_path / LEGACY_MESH_FILENAME
    legacy_path.write_text("{}", encoding="utf-8")
    save_cvt_mesh(tmp_path / MESH_FILENAME, _tiny_mesh())

    assert not legacy_path.exists()
    assert (tmp_path / MESH_FILENAME).exists()
