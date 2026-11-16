"""Tests for the versioned dev-data package system (M1-P1)."""

from __future__ import annotations

import gzip
import io
import json
import tarfile

import pytest
from typer.testing import CliRunner

from dreamulator.datapkg import (
    MESH_FORMAT_VERSION,
    DevDataIndex,
    DevDataManifest,
    IndexEntry,
    PackageFile,
    file_sha256,
    recipe_fingerprint,
)
from dreamulator.datapkg.install import InstallError, install_files, verify_package
from dreamulator.map.pipeline_types import TerrainImportRecipe, TerrainPipelineConfig

_BASE = ("elevation.png", "cvt_mesh.json", "plates.json", "map.yaml")


def _gzip_mesh(seed: int, num_cells: int) -> bytes:
    return gzip.compress(json.dumps({"seed": seed, "num_cells": num_cells, "cells": []}).encode())


def _build_package(tmp_path, *, planet_id="planet_earth", seed=42, nodes=200_000):
    """Write a minimal valid base-terrain package; return (tar_path, manifest, recipe)."""
    staging_maps = tmp_path / "staging" / "maps" / planet_id
    staging_maps.mkdir(parents=True)
    contents = {
        "elevation.png": b"elev",
        "cvt_mesh.json": _gzip_mesh(seed, nodes),
        "plates.json": b"{}",
        "map.yaml": b"planet_id: x\n",
    }
    for name, data in contents.items():
        (staging_maps / name).write_bytes(data)

    recipe = TerrainImportRecipe(seed=seed, mesh_nodes=nodes)
    fingerprint = recipe_fingerprint(recipe, MESH_FORMAT_VERSION)
    files = [
        PackageFile(
            path=f"maps/{planet_id}/{name}",
            sha256=file_sha256(staging_maps / name),
            size_bytes=(staging_maps / name).stat().st_size,
        )
        for name in _BASE
    ]
    manifest = DevDataManifest(
        world="earth",
        planet_id=planet_id,
        recipe=recipe.to_dict(),
        mesh_format_version=MESH_FORMAT_VERSION,
        input_fingerprint=fingerprint,
        code_revision="test",
        files=files,
    )
    (tmp_path / "staging" / "manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )

    tar_path = tmp_path / "package.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for name in _BASE:
            tar.add(staging_maps / name, arcname=f"maps/{planet_id}/{name}")
        tar.add(tmp_path / "staging" / "manifest.json", arcname="manifest.json")
    return tar_path, manifest, recipe


# --- fingerprint --------------------------------------------------------


def test_fingerprint_stable_and_recipe_sensitive():
    a = TerrainImportRecipe(seed=42, mesh_nodes=200_000)
    b = TerrainImportRecipe(seed=42, mesh_nodes=200_000)
    c = TerrainImportRecipe(seed=43, mesh_nodes=200_000)
    assert recipe_fingerprint(a) == recipe_fingerprint(b)
    assert recipe_fingerprint(a) != recipe_fingerprint(c)
    # mesh format version participates
    assert recipe_fingerprint(a, 1) != recipe_fingerprint(a, 2)


def test_fingerprint_excludes_code_revision():
    # recipe_fingerprint takes no code_revision argument — the same recipe must
    # hash identically regardless of any external provenance.
    recipe = TerrainImportRecipe()
    assert recipe_fingerprint(recipe) == recipe_fingerprint(recipe)


# --- recipe parsing -----------------------------------------------------


def test_terrain_import_parsed_from_dict():
    cfg = TerrainPipelineConfig.from_dict(
        {
            "elevation_source": "imported",
            "terrain_import": {
                "provider": "etopo1",
                "dataset": "etopo1_ice_surface_grid_registered",
                "resolution": [4096, 2048],
                "mesh_nodes": 200000,
                "seed": 42,
                "importer_version": 1,
            },
        }
    )
    assert cfg.elevation_source == "imported"
    assert cfg.terrain_import is not None
    assert cfg.terrain_import.resolution_w == 4096
    assert cfg.terrain_import.resolution_h == 2048
    assert cfg.terrain_import.resolution == "4096x2048"
    assert cfg.terrain_import.mesh_nodes == 200000


def test_terrain_import_default_none():
    cfg = TerrainPipelineConfig.from_dict({"elevation_source": "generated"})
    assert cfg.terrain_import is None


# --- manifest round-trip -------------------------------------------------


def test_manifest_roundtrip(tmp_path):
    _, manifest, _ = _build_package(tmp_path)
    data = json.loads(manifest.model_dump_json())
    loaded = DevDataManifest.model_validate(data)
    assert loaded == manifest
    assert {f.path.split("/")[-1] for f in loaded.files} == set(_BASE)


# --- index ---------------------------------------------------------------


def test_index_save_load_find(tmp_path):
    recipe = TerrainImportRecipe(seed=42)
    fp = recipe_fingerprint(recipe)
    entry = IndexEntry(
        world="earth",
        planet_id="planet_earth",
        input_fingerprint=fp,
        mesh_format_version=MESH_FORMAT_VERSION,
        tag="dev-data",
        asset_name="earth-terrain-base-abc.tar.gz",
        package_sha256="a" * 64,
        manifest_sha256="b" * 64,
        size_bytes=123,
        recipe=recipe.to_dict(),
    )
    index = DevDataIndex(entries=[entry])
    path = tmp_path / "index.json"
    index.save(path)
    loaded = DevDataIndex.load(path)
    assert loaded.find(world="earth", planet_id="planet_earth", input_fingerprint=fp) == entry
    assert loaded.find(world="earth", planet_id="planet_earth", input_fingerprint="x") is None


def test_index_load_missing_is_empty(tmp_path):
    assert DevDataIndex.load(tmp_path / "nope.json").entries == []


# --- verification --------------------------------------------------------


def test_verify_package_ok(tmp_path):
    tar, manifest, recipe = _build_package(tmp_path)
    extract = tmp_path / "extract"
    got = verify_package(
        tar,
        extract,
        package_sha256=file_sha256(tar),
        fingerprint=recipe_fingerprint(recipe),
        world="earth",
        planet_id="planet_earth",
    )
    assert got == manifest


def test_verify_package_digest_mismatch(tmp_path):
    tar, _, recipe = _build_package(tmp_path)
    with pytest.raises(InstallError):
        verify_package(tar, tmp_path / "e", package_sha256="f" * 64)


def _repack(tar_path, staging, manifest):
    (staging / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    with tarfile.open(tar_path, "w:gz") as tar:
        for path in staging.rglob("*"):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(staging)))


def test_verify_manifest_digest_mismatch(tmp_path):
    tar, _, _ = _build_package(tmp_path)
    with pytest.raises(InstallError, match="manifest SHA-256"):
        verify_package(tar, tmp_path / "e", manifest_sha256="0" * 64)


@pytest.mark.parametrize("field", ["schema_version", "mesh_format_version"])
def test_verify_rejects_unknown_versions(tmp_path, field):
    tar, manifest, _ = _build_package(tmp_path)
    setattr(manifest, field, 999)
    _repack(tar, tmp_path / "staging", manifest)
    with pytest.raises(InstallError, match="unsupported"):
        verify_package(tar, tmp_path / "e")


def test_verify_rejects_recipe_inconsistent_with_fingerprint(tmp_path):
    tar, manifest, _ = _build_package(tmp_path)
    manifest.recipe["seed"] = 99
    _repack(tar, tmp_path / "staging", manifest)
    with pytest.raises(InstallError, match="recipe does not match"):
        verify_package(tar, tmp_path / "e")


@pytest.mark.parametrize("change", ["extra_config", "duplicate", "wrong_planet"])
def test_verify_rejects_files_outside_four_artifact_contract(tmp_path, change):
    tar, manifest, _ = _build_package(tmp_path)
    if change == "extra_config":
        path = tmp_path / "staging/layers/geological/input/planets.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("planets: []\n", encoding="utf-8")
        manifest.files.append(
            PackageFile(
                path="layers/geological/input/planets.yaml",
                sha256=file_sha256(path),
                size_bytes=path.stat().st_size,
            )
        )
    elif change == "duplicate":
        manifest.files.append(manifest.files[0].model_copy())
    else:
        manifest.files[0].path = "maps/planet_other/elevation.png"
    _repack(tar, tmp_path / "staging", manifest)
    with pytest.raises(InstallError, match="exactly four"):
        verify_package(tar, tmp_path / "e")


@pytest.mark.parametrize(
    "field,value",
    [("precipitation_mm", 0.0), ("cloud_total_frac", 0.0), ("wind_east_m_s", 1.0)],
)
def test_verify_rejects_climate_in_base_package(tmp_path, field, value):
    tar, manifest, _ = _build_package(tmp_path)
    path = tmp_path / "staging/maps/planet_earth/cvt_mesh.json"
    mesh = {"seed": 42, "num_cells": 200_000, "cells": [{field: value}]}
    path.write_bytes(gzip.compress(json.dumps(mesh).encode("utf-8")))
    mesh_file = next(f for f in manifest.files if f.path.endswith("cvt_mesh.json"))
    mesh_file.sha256 = file_sha256(path)
    mesh_file.size_bytes = path.stat().st_size
    _repack(tar, tmp_path / "staging", manifest)
    with pytest.raises(InstallError, match="contains climate fields"):
        verify_package(tar, tmp_path / "e")


def test_verify_package_fingerprint_mismatch(tmp_path):
    tar, _, recipe = _build_package(tmp_path)
    with pytest.raises(InstallError):
        verify_package(
            tar, tmp_path / "e", fingerprint="0" * 64, world="earth", planet_id="planet_earth"
        )


def test_verify_rejects_traversal(tmp_path):
    tar_path = tmp_path / "evil.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        info = tarfile.TarInfo("../evil.txt")
        data = b"evil"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(InstallError):
        verify_package(tar_path, tmp_path / "e")


def test_verify_rejects_symlink(tmp_path):
    tar_path = tmp_path / "link.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(InstallError):
        verify_package(tar_path, tmp_path / "e")


# --- install -------------------------------------------------------------


def test_install_writes_files_and_provenance(tmp_path):
    tar, manifest, recipe = _build_package(tmp_path)
    extract = tmp_path / "extract"
    verify_package(tar, extract, fingerprint=recipe_fingerprint(recipe))
    target = tmp_path / "target"
    install_files(extract, manifest, target, recipe)
    for name in _BASE:
        assert (target / name).exists()
    assert (target / "dev-data-manifest.json").exists()


def test_install_refuses_mismatched_mesh(tmp_path):
    tar, manifest, recipe = _build_package(tmp_path, seed=42, nodes=200_000)
    extract = tmp_path / "extract"
    verify_package(tar, extract, fingerprint=recipe_fingerprint(recipe))
    target = tmp_path / "target"
    target.mkdir()
    (target / "cvt_mesh.json").write_bytes(_gzip_mesh(seed=99, num_cells=32768))
    with pytest.raises(InstallError, match="different parameters"):
        install_files(extract, manifest, target, recipe)


def test_install_idempotent_on_matching_mesh(tmp_path):
    tar, manifest, recipe = _build_package(tmp_path, seed=42, nodes=200_000)
    extract = tmp_path / "extract"
    verify_package(tar, extract, fingerprint=recipe_fingerprint(recipe))
    target = tmp_path / "target"
    target.mkdir()
    (target / "cvt_mesh.json").write_bytes(_gzip_mesh(seed=42, num_cells=200_000))
    # matching params → proceeds (refreshes) rather than raising
    install_files(extract, manifest, target, recipe)
    assert (target / "elevation.png").exists()


def test_install_preserves_existing_observation_mesh_and_source_config(tmp_path):
    tar, manifest, recipe = _build_package(tmp_path)
    extract = tmp_path / "extract"
    verify_package(tar, extract)
    target = tmp_path / "world/maps/planet_earth"
    target.mkdir(parents=True)
    reference = gzip.compress(
        json.dumps({"seed": 42, "num_cells": 200_000, "cells": [{"precipitation_mm": 0.0}]}).encode(
            "utf-8"
        )
    )
    (target / "cvt_mesh.json").write_bytes(reference)
    (target / "elevation.png").write_bytes(b"existing elevation")
    config = tmp_path / "world/layers/geological/input/planets.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("planets: [{id: planet_earth}]\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in (tmp_path / "world").rglob("*") if p.is_file()}
    with pytest.raises(InstallError, match="would erase"):
        install_files(extract, manifest, target, recipe)
    assert before == {p: p.read_bytes() for p in before}
    assert not (target / "dev-data-manifest.json").exists()


def test_install_legacy_package_removes_stale_modern_base_mesh(tmp_path):
    from dreamulator.map.export import MESH_FILENAME, find_mesh_file, save_cvt_mesh

    tar, manifest, recipe = _build_package(tmp_path)
    extract = tmp_path / "extract"
    verify_package(tar, extract)
    target = tmp_path / "target"
    target.mkdir()
    save_cvt_mesh(target / MESH_FILENAME, {"seed": 42, "num_cells": 200_000, "cells": []})
    install_files(extract, manifest, target, recipe)
    assert not (target / MESH_FILENAME).exists()
    assert find_mesh_file(target).name == "cvt_mesh.json"


def _fetch_fixture(tmp_path, monkeypatch):
    from dreamulator.datapkg import IndexEntry

    tar, manifest, recipe = _build_package(tmp_path)
    world = tmp_path / "worlds/earth/layers/geological/input"
    world.mkdir(parents=True)
    import yaml

    (world / "terrain_config.yaml").write_text(
        yaml.safe_dump({"elevation_source": "imported", "terrain_import": recipe.to_dict()}),
        encoding="utf-8",
    )
    entry = IndexEntry(
        world="earth",
        planet_id="planet_earth",
        input_fingerprint=manifest.input_fingerprint,
        mesh_format_version=MESH_FORMAT_VERSION,
        tag="dev-data",
        asset_name=tar.name,
        package_sha256=file_sha256(tar),
        manifest_sha256=file_sha256(tmp_path / "staging/manifest.json"),
        size_bytes=tar.stat().st_size,
        recipe=recipe.to_dict(),
    )
    index_path = tmp_path / "index.json"
    DevDataIndex(entries=[entry]).save(index_path)
    monkeypatch.setattr("dreamulator.cli_data.default_index_path", lambda: index_path)
    monkeypatch.setenv("DREAMULATOR_DATA_DIR", str(tmp_path / "worlds"))
    return tar


def test_fetch_local_package_points_earth_to_branch(tmp_path, monkeypatch):
    from dreamulator.cli import app

    tar = _fetch_fixture(tmp_path, monkeypatch)
    worlds = tmp_path / "worlds"
    result = CliRunner().invoke(
        app, ["data", "fetch", "earth", "--from", str(tar), "--data-dir", str(worlds)]
    )
    assert result.exit_code == 0, result.output
    assert "build earth --branch climate-dev" in result.output
    assert "--data-dir" in result.output
    assert (tmp_path / "worlds/earth/maps/planet_earth/elevation.png").exists()


def test_fetch_missing_gh_offers_local_install(tmp_path, monkeypatch):
    from dreamulator.cli import app

    _fetch_fixture(tmp_path, monkeypatch)

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr("dreamulator.cli_data.subprocess.run", unavailable)
    result = CliRunner().invoke(app, ["data", "fetch", "earth"])
    assert result.exit_code == 1
    assert "use --from" in result.output
    assert not (tmp_path / "worlds/earth/maps").exists()
