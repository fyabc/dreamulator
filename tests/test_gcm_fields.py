"""Pinned GCM climate (climate_source: gcm branches): field sets, guards, engine hook."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
import yaml

from dreamulator.branch_manager import BranchManager
from dreamulator.engine.climate import ClimateEngine
from dreamulator.gcm.fields import (
    ANNUAL_FIELDS,
    GCM_FIELDS_FILENAME,
    GcmFieldSet,
    StaleFieldSetError,
    apply_field_set,
    load_field_set,
    mesh_fingerprint,
    provenance_path,
    save_field_set,
)
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.models.branch import BranchMetadata, ClimateSource
from dreamulator.models.layers import Layer

if TYPE_CHECKING:
    from pathlib import Path


def _mesh(elev0: float = 100.0) -> CVTMesh:
    cells = [
        VoronoiCell(id=i, lon=10.0 * i, lat=5.0 * i, elevation=[elev0, -50.0, 300.0][i])
        for i in range(3)
    ]
    for c in cells:
        c.biome = "grassland"
        c.sst_anomaly_c = 1.0
    return CVTMesh(seed=1, num_cells=3, cells=cells, adjacency={"0": [], "1": [], "2": []})


def _field_set(mesh: CVTMesh) -> GcmFieldSet:
    n = mesh.num_cells
    return GcmFieldSet(
        num_cells=n,
        mesh_fingerprint=mesh_fingerprint(mesh),
        annual={k: np.arange(n, dtype=float) + j for j, k in enumerate(ANNUAL_FIELDS)},
        monthly={
            "t_monthly_c": np.tile(np.arange(12.0), (n, 1)),
            "p_monthly_mm": np.full((n, 12), 50.0),
        },
        koppen=["Cfb", None, "BSk"],
        slp_reduction_unreliable=np.array([False, False, True]),
        provenance={"source_nc": "MOST.00000.nc", "pco2_ppm": 712},
    )


def test_fingerprint_ignores_climate_fields_but_tracks_terrain() -> None:
    mesh = _mesh()
    before = mesh_fingerprint(mesh)
    mesh.cells[0].temperature_C = 12.0
    mesh.cells[0].koppen_class = "Cfb"
    assert mesh_fingerprint(mesh) == before
    assert mesh_fingerprint(_mesh(elev0=101.0)) != before


def test_save_load_round_trip_with_provenance(tmp_path: Path) -> None:
    mesh = _mesh()
    path = save_field_set(tmp_path / GCM_FIELDS_FILENAME, _field_set(mesh))
    assert provenance_path(path).exists()
    fs = load_field_set(path)
    assert fs.koppen == ["Cfb", None, "BSk"]
    assert np.allclose(fs.monthly["t_monthly_c"][2], np.arange(12.0))
    assert fs.provenance["pco2_ppm"] == 712
    # deterministic bytes: saving the same content again gives the same digest
    sha = provenance_path(path).read_text(encoding="utf-8")
    save_field_set(path, _field_set(mesh))
    assert provenance_path(path).read_text(encoding="utf-8") == sha


def test_load_refuses_binary_not_matching_provenance(tmp_path: Path) -> None:
    mesh = _mesh()
    path = save_field_set(tmp_path / GCM_FIELDS_FILENAME, _field_set(mesh))
    other = _field_set(mesh)
    other.provenance["pco2_ppm"] = 1400
    prov = provenance_path(path).read_text(encoding="utf-8")
    save_field_set(path, other)  # binary changes …
    provenance_path(path).write_text(prov, encoding="utf-8")  # … provenance stays old
    with pytest.raises(StaleFieldSetError, match="does not match"):
        load_field_set(path)


def test_apply_writes_fields_clears_engine_derived_and_attaches_monthly() -> None:
    mesh = _mesh()
    apply_field_set(mesh, _field_set(mesh))
    c0, c2 = mesh.cells[0], mesh.cells[2]
    assert c0.temperature_C == 0.0 and c2.precipitation_mm == 5.0  # precipitation is index 3
    assert c0.koppen_class == "Cfb" and mesh.cells[1].koppen_class is None
    assert c2.slp_reduction_unreliable is True
    assert c0.biome is None and c0.sst_anomaly_c is None
    assert mesh._t_monthly_c.shape == (3, 12)  # type: ignore[attr-defined]


def test_apply_refuses_field_set_from_another_terrain() -> None:
    fs = _field_set(_mesh())
    with pytest.raises(StaleFieldSetError, match="stale"):
        apply_field_set(_mesh(elev0=250.0), fs)


def test_gcm_climate_source_requires_climate_fork() -> None:
    ok = BranchMetadata(name="g", fork_layer=Layer.CLIMATE, climate_source=ClimateSource.GCM)
    assert ok.climate_source is ClimateSource.GCM
    with pytest.raises(ValueError, match="requires fork_layer"):
        BranchMetadata(name="g", fork_layer=Layer.GEOLOGICAL, climate_source="gcm")
    assert BranchMetadata(name="e", fork_layer=Layer.ECOLOGY).climate_source is ClimateSource.ENGINE


def test_create_branch_validates_before_writing(tmp_path: Path) -> None:
    mgr = BranchManager(tmp_path)
    with pytest.raises(ValueError):
        mgr.create_branch("bad", "geological", climate_source="gcm")
    assert not (tmp_path / "branches" / "bad").exists()
    branch_dir = mgr.create_branch("gcm-t42", "climate", climate_source="gcm")
    data = yaml.safe_load((branch_dir / "branch.yaml").read_text(encoding="utf-8"))
    assert data["climate_source"] == "gcm"


def _engine(world: Path, branch: str | None) -> ClimateEngine:
    maps = world / "maps" if branch is None else world / "branches" / branch / "maps"
    layer_inputs = {}
    if branch is not None:
        layer_inputs["climate"] = world / "branches" / branch / "layers" / "climate" / "input"
    return ClimateEngine(world, seed=42, maps_output_dir=maps, layer_input_dirs=layer_inputs)


def test_engine_resolves_climate_source(tmp_path: Path) -> None:
    BranchManager(tmp_path).create_branch("gcm-t42", "climate", climate_source="gcm")
    BranchManager(tmp_path).create_branch("plain", "climate")
    assert _engine(tmp_path, "gcm-t42")._climate_source() is ClimateSource.GCM
    assert _engine(tmp_path, "plain")._climate_source() is ClimateSource.ENGINE
    assert _engine(tmp_path, None)._climate_source() is ClimateSource.ENGINE


def test_engine_applies_pinned_climate_or_explains_why_not(tmp_path: Path) -> None:
    branch_dir = BranchManager(tmp_path).create_branch("gcm-t42", "climate", climate_source="gcm")
    engine = _engine(tmp_path, "gcm-t42")
    missing = engine._apply_pinned_gcm_climate(_mesh())
    assert isinstance(missing, str) and "worlds-data" in missing

    mesh = _mesh()
    save_field_set(
        branch_dir / "layers" / "climate" / "input" / GCM_FIELDS_FILENAME, _field_set(mesh)
    )
    stale = engine._apply_pinned_gcm_climate(_mesh(elev0=999.0))
    assert isinstance(stale, str) and "refused" in stale

    provenance = engine._apply_pinned_gcm_climate(mesh)
    assert provenance == {"source_nc": "MOST.00000.nc", "pco2_ppm": 712}
    assert mesh.cells[0].koppen_class == "Cfb"
