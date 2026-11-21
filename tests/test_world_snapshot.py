"""Snapshot portability, integrity, and the local download and CLI contract."""

from __future__ import annotations

import tarfile
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from dreamulator.api_routes import worlds as worlds_route
from dreamulator.build_jobs import local_compute_slot
from dreamulator.cli import app
from dreamulator.world_manager import WorldManager
from dreamulator.world_snapshot import export_snapshot, restore_snapshot

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def world(tmp_path: Path) -> Path:
    world = WorldManager(tmp_path / "original").create_world("snapshot-test", seed=42)
    files = {
        "layers/geological/input/elevation_sources/original.bin": b"original elevation",
        "layers/geological/input/elevation_mapping.yaml": b"meters_per_unit: 0.5\n",
        "layers/climate/derived/climate_summary.json": b'{"mean": 15}',
        "maps/planet_test/climate_monthly.npz": b"monthly climate",
        "branches/wet/branch.yaml": b"name: wet\n",
        "branches/wet/layers/climate/derived/climate_summary.json": b'{"mean": 16}',
        "packs/saved/refined-out/height.npy": b"saved region",
        "canvases/canvas/height.npy": b"saved canvas",
        "design-notes/地图说明.md": b"notes",
        "layers/astronomy/input/.scratch": b"temporary file",
    }
    for name, data in files.items():
        path = world / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return world


def _contents(world: Path) -> dict[str, bytes]:
    return {
        path.relative_to(world).as_posix(): path.read_bytes()
        for path in world.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }


def test_cli_round_trip(world: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DREAMULATOR_DATA_DIR", raising=False)
    runner = CliRunner()
    archive = tmp_path / "snapshot.tar.gz"
    export_args = [
        "snapshot",
        "export",
        world.name,
        "-o",
        str(archive),
        "--data-dir",
        str(world.parent),
    ]
    result = runner.invoke(app, export_args)
    assert result.exit_code == 0, result.output
    original_archive = archive.read_bytes()
    assert runner.invoke(app, export_args).exit_code == 1
    assert archive.read_bytes() == original_archive

    worlds = tmp_path / "restored"
    restore_args = ["snapshot", "restore", str(archive), "--data-dir", str(worlds)]
    result = runner.invoke(app, restore_args)
    assert result.exit_code == 0, result.output
    contents = _contents(worlds / world.name)
    assert contents == _contents(world)
    assert not (worlds / world.name / "layers/astronomy/input/.scratch").exists()
    result = runner.invoke(app, restore_args)
    assert result.exit_code == 1
    assert "already exists" in result.output
    assert _contents(worlds / world.name) == contents
    assert list(worlds.iterdir()) == [worlds / world.name]


@pytest.mark.parametrize("kind", ["checksum", "truncated", "traversal", "link", "sparse"])
def test_restore_rejects_bad_archives(world: Path, tmp_path: Path, kind: str) -> None:
    archive = tmp_path / "snapshot.tar.gz"
    if kind in {"checksum", "truncated"}:
        export_snapshot(world, archive)
        original = tmp_path / "original.tar.gz"
        archive.rename(original)
        if kind == "truncated":
            archive.write_bytes(original.read_bytes()[:-8])
        else:
            with tarfile.open(original) as source, tarfile.open(archive, "w:gz") as target:
                for entry in source:
                    if entry.name.endswith("height.npy"):
                        target.addfile(entry, BytesIO(b"!" * entry.size))
                    else:
                        target.addfile(entry, source.extractfile(entry))
    else:
        with tarfile.open(archive, "w:gz") as target:
            entry = tarfile.TarInfo(f"{world.name}/layers/geological/input/world.yaml")
            if kind == "traversal":
                entry.name = f"{world.name}/layers/../../escape.yaml"
            elif kind == "link":
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/tmp"
            else:
                entry.pax_headers = {"GNU.sparse.major": "1", "GNU.sparse.minor": "0"}
            target.addfile(entry)
    worlds = tmp_path / "restored"
    with pytest.raises(ValueError):
        restore_snapshot(archive, worlds)
    assert not list(worlds.iterdir())
    assert not (tmp_path / "escape.yaml").exists()


def test_local_download(world: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worlds_route, "_manager", WorldManager(world.parent))
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    def temp_directory(*, prefix: str) -> str:
        directory = downloads / (prefix + "test")
        directory.mkdir()
        return str(directory)

    monkeypatch.setattr(worlds_route, "mkdtemp", temp_directory)
    api = FastAPI()
    api.include_router(worlds_route.router)
    client = TestClient(api)
    url = f"/api/worlds/{world.name}/snapshot"
    with local_compute_slot:
        assert client.get(url).status_code == 409
    assert client.get("/api/worlds/missing/snapshot").status_code == 404
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
    assert response.headers["cache-control"] == "no-store"
    assert f"{world.name}.dreamulator.tar.gz" in response.headers["content-disposition"]
    assert not list(downloads.iterdir())
    archive = tmp_path / "download.tar.gz"
    archive.write_bytes(response.content)
    restored = restore_snapshot(archive, tmp_path / "restored")
    assert _contents(restored) == _contents(world)


def test_non_ascii_world_id(world: Path, tmp_path: Path) -> None:
    renamed = world.rename(world.with_name("海岸世界"))
    archive = tmp_path / "snapshot.tar.gz"
    export_snapshot(renamed, archive)
    restored = restore_snapshot(archive, tmp_path / "restored")
    assert restored.name == renamed.name
    assert _contents(restored) == _contents(renamed)


def test_create_heightmap_endpoint_does_not_restore_arbitrary_world_snapshots(
    world: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "snapshot.tar.gz"
    export_snapshot(world, archive)
    destination = tmp_path / "new-worlds"
    monkeypatch.setattr(worlds_route, "_manager", WorldManager(destination))
    api = FastAPI()
    api.include_router(worlds_route.router)
    response = TestClient(api).post(
        "/api/worlds/from-heightmap", files={"file": (archive.name, archive.read_bytes())}
    )
    assert response.status_code == 422
    assert not list(destination.iterdir())
