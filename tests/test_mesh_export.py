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


def _mesh_with_elev(elev: float) -> CVTMesh:
    cells = [
        VoronoiCell(id=i, lon=float(i), lat=0.0, elevation=elev - 200.0 * i, neighbors=[])
        for i in range(2)
    ]
    return CVTMesh(seed=42, num_cells=2, cells=cells, adjacency={"0": [], "1": []})


def test_backup_existing_rotates_previous(tmp_path: Path) -> None:
    # backup_existing=True keeps the displaced generation as .prev (root mesh
    # recovery point: real-data roots are expensive to re-import, and one was
    # lost to a self-destruct overwrite 2026-09-25).
    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh_with_elev(100.0))
    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh_with_elev(555.0), backup_existing=True)

    prev = tmp_path / (MESH_FILENAME + ".prev")
    assert prev.exists()
    assert load_cvt_mesh_model(prev).cells[0].elevation == 100.0
    assert load_cvt_mesh_model(tmp_path / MESH_FILENAME).cells[0].elevation == 555.0


def test_backup_existing_keeps_one_generation(tmp_path: Path) -> None:
    # Depth-1 rotation: each backup-save replaces .prev — no unbounded
    # accumulation across repeated re-imports.
    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh_with_elev(100.0))
    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh_with_elev(555.0), backup_existing=True)
    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh_with_elev(777.0), backup_existing=True)

    prev = tmp_path / (MESH_FILENAME + ".prev")
    assert load_cvt_mesh_model(prev).cells[0].elevation == 555.0


def test_backup_existing_first_save_is_noop(tmp_path: Path) -> None:
    # Nothing to displace on a fresh planet: no .prev, no error.
    save_cvt_mesh(tmp_path / MESH_FILENAME, _tiny_mesh(), backup_existing=True)

    assert not (tmp_path / (MESH_FILENAME + ".prev")).exists()
    assert load_cvt_mesh_model(tmp_path / MESH_FILENAME).num_cells == 2


def test_backup_existing_from_legacy_json(tmp_path: Path) -> None:
    # A legacy-only planet: the legacy bytes become .prev (content-sniffed by
    # the loaders, so the name does not matter), then cleanup unlinks legacy.
    legacy_path = tmp_path / LEGACY_MESH_FILENAME
    legacy_path.write_text(_mesh_with_elev(100.0).model_dump_json(), encoding="utf-8")

    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh_with_elev(555.0), backup_existing=True)

    prev = tmp_path / (MESH_FILENAME + ".prev")
    assert not legacy_path.exists()
    assert load_cvt_mesh_model(prev).cells[0].elevation == 100.0
    assert load_cvt_mesh_model(tmp_path / MESH_FILENAME).cells[0].elevation == 555.0


def test_default_save_creates_no_prev(tmp_path: Path) -> None:
    # Engine/branch builds keep the default: reproducible-from-seed meshes
    # must not pay a full-size copy per build.
    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh_with_elev(100.0))
    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh_with_elev(555.0))

    assert not (tmp_path / (MESH_FILENAME + ".prev")).exists()
