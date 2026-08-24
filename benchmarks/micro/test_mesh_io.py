"""Mesh JSON serialization round-trip on the nacrea 88 MB mesh
(pydantic-core path, Stage 0.2)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from benchmarks.conftest import NACREAESH_JSON
from dreamulator.map.models import CVTMesh

pytestmark = pytest.mark.benchmark

if not NACREAESH_JSON.exists():
    pytest.skip(f"missing {NACREAESH_JSON}", allow_module_level=True)

_DATA = NACREAESH_JSON.read_bytes()
if _DATA.startswith(b"version https://git-lfs"):
    # Git LFS pointer (e.g. CI checkout without lfs: true) — not the real mesh.
    pytest.skip(f"{NACREAESH_JSON} is an LFS pointer", allow_module_level=True)

_ADAPTER = TypeAdapter(CVTMesh)


def test_mesh_json_roundtrip(benchmark):
    def run():
        mesh = _ADAPTER.validate_json(_DATA)
        return mesh.model_dump_json()

    benchmark.pedantic(run, rounds=3, iterations=1)
