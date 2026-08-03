"""Mesh JSON serialization round-trip on the gaia-m 88 MB mesh
(pydantic-core path, Stage 0.2)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from benchmarks.conftest import GAIA_MESH_JSON
from dreamulator.map.models import CVTMesh

pytestmark = pytest.mark.benchmark

if not GAIA_MESH_JSON.exists():
    pytest.skip(f"missing {GAIA_MESH_JSON}", allow_module_level=True)

_DATA = GAIA_MESH_JSON.read_bytes()
_ADAPTER = TypeAdapter(CVTMesh)


def test_mesh_json_roundtrip(benchmark):
    def run():
        mesh = _ADAPTER.validate_json(_DATA)
        return mesh.model_dump_json()

    benchmark.pedantic(run, rounds=3, iterations=1)
