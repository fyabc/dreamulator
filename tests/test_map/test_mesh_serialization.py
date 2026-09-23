"""Unit tests for the canonical mesh serialization (gzip-framed MessagePack).

Covers: model and dict roundtrips, float-precision truncation semantics,
legacy plain-JSON / gzip-JSON reads (the zero-rebuild migration path), the
legacy-twin cleanup on save, and the find/iter helpers' generation
preference.
"""

from __future__ import annotations

import gzip
import json
from typing import TYPE_CHECKING

from dreamulator.map.export import (
    LEGACY_MESH_FILENAME,
    MESH_FILENAME,
    decode_mesh_bytes,
    find_mesh_file,
    iter_mesh_files,
    load_cvt_mesh,
    load_cvt_mesh_model,
    save_cvt_mesh,
)
from dreamulator.map.models import CVTMesh, VoronoiCell

if TYPE_CHECKING:
    from pathlib import Path


def _mesh(seed: int = 7, lon: float = 1.25) -> CVTMesh:
    return CVTMesh(seed=seed, num_cells=1, cells=[VoronoiCell(id=0, lon=lon, lat=2.0)])


def test_save_load_roundtrip_model(tmp_path: Path) -> None:
    path = tmp_path / MESH_FILENAME
    save_cvt_mesh(path, _mesh(lon=1.23456789))

    raw = path.read_bytes()
    assert raw[:2] == b"\x1f\x8b"  # gzip framing

    data = load_cvt_mesh(path)
    assert data["seed"] == 7
    # Float truncation semantics survive the format change (4 decimal
    # places, truncation not rounding — same as the legacy JSON regex).
    assert data["cells"][0]["lon"] == 1.2345

    mesh = load_cvt_mesh_model(path)
    assert mesh.seed == 7
    assert mesh.cells[0].lon == 1.2345


def test_save_accepts_plain_dict(tmp_path: Path) -> None:
    path = tmp_path / MESH_FILENAME
    obj = {"seed": 3, "num_cells": 1, "cells": [{"id": 0, "lon": 0.5, "lat": -0.5}]}
    save_cvt_mesh(path, obj)
    assert load_cvt_mesh(path) == obj


def test_save_removes_legacy_twin(tmp_path: Path) -> None:
    legacy = tmp_path / LEGACY_MESH_FILENAME
    legacy.write_text(_mesh().model_dump_json(), encoding="utf-8")

    save_cvt_mesh(tmp_path / MESH_FILENAME, _mesh(seed=9))

    assert not legacy.exists()
    assert find_mesh_file(tmp_path) == tmp_path / MESH_FILENAME
    assert load_cvt_mesh(tmp_path / MESH_FILENAME)["seed"] == 9


def test_decode_legacy_plain_and_gzip_json() -> None:
    plain = _mesh().model_dump_json().encode("utf-8")
    assert decode_mesh_bytes(plain)["seed"] == 7

    gzipped = gzip.compress(plain)
    assert decode_mesh_bytes(gzipped)["seed"] == 7


def test_load_model_legacy_json(tmp_path: Path) -> None:
    path = tmp_path / LEGACY_MESH_FILENAME
    path.write_text(_mesh(lon=3.5).model_dump_json(), encoding="utf-8")
    mesh = load_cvt_mesh_model(path)
    assert mesh.cells[0].lon == 3.5


def test_find_and_iter_generation_preference(tmp_path: Path) -> None:
    maps = tmp_path / "maps"
    # Both generations present → canonical wins; legacy-only planet → legacy.
    both = maps / "alpha"
    both.mkdir(parents=True)
    (both / MESH_FILENAME).write_bytes(b"")
    (both / LEGACY_MESH_FILENAME).write_bytes(b"")
    legacy_only = maps / "beta"
    legacy_only.mkdir()
    (legacy_only / LEGACY_MESH_FILENAME).write_bytes(b"")
    # Scratch dirs are skipped.
    scratch = maps / "_baseline_alpha"
    scratch.mkdir()
    (scratch / MESH_FILENAME).write_bytes(b"")

    assert find_mesh_file(both) == both / MESH_FILENAME
    assert find_mesh_file(legacy_only) == legacy_only / LEGACY_MESH_FILENAME
    assert find_mesh_file(maps / "missing") is None

    found = iter_mesh_files(maps)
    assert both / MESH_FILENAME in found
    assert legacy_only / LEGACY_MESH_FILENAME in found
    assert len(found) == 2  # scratch excluded, one file per planet


def test_msgpack_payload_is_valid_msgpack(tmp_path: Path) -> None:
    """The gzip envelope unpacks to msgpack (not legacy JSON text)."""
    import msgpack

    path = tmp_path / MESH_FILENAME
    save_cvt_mesh(path, _mesh())
    inner = gzip.decompress(path.read_bytes())
    assert inner.lstrip()[:1] != b"{"
    assert msgpack.unpackb(inner, raw=False)["seed"] == 7


def test_load_cvt_mesh_json_passthrough(tmp_path: Path) -> None:
    """A hand-written pretty-printed JSON mesh still loads (whitespace sniff)."""
    path = tmp_path / LEGACY_MESH_FILENAME
    pretty = json.dumps({"seed": 1, "num_cells": 0, "cells": []}, indent=2)
    path.write_text(pretty, encoding="utf-8")
    assert load_cvt_mesh(path)["seed"] == 1
