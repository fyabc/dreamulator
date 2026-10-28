"""Declared slab sides, temporal scope and agreement between terrain consumers."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.island_catalog import _arc_geometry
from dreamulator.map.models import CVTMesh, EulerPole, TectonicPlate, VoronoiCell
from dreamulator.map.orogen_contract import (
    build_orogen_contract,
    contact_polarity,
    contract_contact_polarity,
    load_orogen_contract,
    resolve_contract_polarities,
    save_orogen_contract,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.subduction_polarity import (
    SubductionPolarity,
    load_subduction_polarities,
    polarity_at_age,
)
from dreamulator.map.tectonic_simulator import _relax_segment
from dreamulator.map.terrain_cache import build_stage_fingerprint
from dreamulator.map.terrain_pipeline import run_terrain_pipeline
from dreamulator.map.trench_flexure import trench_sources

if TYPE_CHECKING:
    from pathlib import Path


def test_time_scopes_distinguish_present_data_and_polarity_reversal() -> None:
    present = SubductionPolarity("present", ("a", "b"), "a")
    assert polarity_at_age([present], 0)[("a", "b")].down_going == "a"
    assert polarity_at_age([present], 1) == {}
    old = replace(present, id="old", valid_from_age_myr=20, valid_until_age_myr=10)
    recent = replace(present, id="recent", down_going="b", valid_from_age_myr=10)
    assert polarity_at_age([old, recent], 15)[("a", "b")].down_going == "a"
    assert polarity_at_age([old, recent], 10)[("a", "b")].down_going == "b"
    assert polarity_at_age([old, recent], 0)[("a", "b")].down_going == "b"


def test_loader_rejects_conflicting_historical_sources(tmp_path: Path) -> None:
    path = tmp_path / "plate_history.yaml"
    path.write_text(
        """subduction_polarities:
  - {id: older, plates: [a, b], down_going: a, valid_from_age_myr: 30, valid_until_age_myr: 10}
  - {id: younger, plates: [b, a], down_going: b, valid_from_age_myr: 20}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicting"):
        load_subduction_polarities(path)
    with pytest.raises(ValueError, match="evidence"):
        SubductionPolarity("obs", ("a", "b"), "a", source_kind="observation")


@pytest.fixture(scope="module")
def built():
    cfg = TerrainPipelineConfig(
        num_nodes=3000,
        radius_km=1500,
        seed=7,
        lloyd_iterations=1,
        num_plates=8,
        tectonic_duration_my=20,
    )
    result = run_terrain_pipeline(cfg, stages=["mesh", "plates", "tectonics", "boundaries"])
    return cfg, result


def test_contract_keeps_declared_sides_and_shares_them_with_trench_and_arc(
    built, tmp_path: Path
) -> None:
    cfg, result = built
    legacy = contact_polarity(result.mesh, result.plates, cfg.radius_km)
    pair = next((a, b) for kind, a, b in legacy.values() if kind == "ocean")
    source = SubductionPolarity(
        "observed-pair",
        pair,
        pair[1],
        source_kind="observation",
        evidence="independent slab-side reference",
    )
    contract = build_orogen_contract(
        result.mesh, result.plates, cfg.radius_km, subduction_polarities=[source]
    )
    selected = {
        k: value
        for k, value in contract.contact_polarities.items()
        if value[0] == "ocean" and set(value[1:]) == set(pair)
    }
    assert selected and all(v[1] == source.down_going for v in selected.values())
    assert all(contract.polarity_sources[k]["id"] == source.id for k in selected)
    path = tmp_path / "orogen_contract.json"
    save_orogen_contract(path, contract, mesh=result.mesh, radius_km=cfg.radius_km)
    restored = load_orogen_contract(path, mesh=result.mesh)
    assert restored.contact_polarities == contract.contact_polarities
    assert restored.subduction_polarities == [source]
    # A common angular velocity changes absolute speeds and leaves relative
    # kinematics unchanged. Frozen sides and explicit source identities persist.
    shifted = copy.deepcopy(result.plates)
    for plate in shifted:
        ep = plate.euler_pole
        omega = np.array([ep.x, ep.y, ep.z]) * ep.omega_rad_yr + np.array([2e-6, 0.0, 0.0])
        w = np.linalg.norm(omega)
        plate.euler_pole = EulerPole(x=omega[0] / w, y=omega[1] / w, z=omega[2] / w, omega_rad_yr=w)
    assert (
        contract_contact_polarity(result.mesh, shifted, restored, cfg.radius_km)
        == contract.contact_polarities
    )
    fresh = contact_polarity(result.mesh, shifted, cfg.radius_km, subduction_polarities=[source])
    assert all(fresh[k][1:] == v[1:] for k, v in selected.items())
    trench = trench_sources(result.mesh, shifted, restored, cfg.radius_km)
    _, _, arc_over = _arc_geometry(result.mesh, shifted, cfg.radius_km, orogen_contract=restored)
    down_ids = [
        k
        for k in selected
        if result.mesh.cells[k].plate_id == source.down_going
        and result.mesh.cells[k].crust_type == "oceanic"
    ]
    upper_ids = [k for k in selected if result.mesh.cells[k].plate_id != source.down_going]
    assert down_ids and upper_ids
    assert all(trench[k] == source.down_going and not arc_over[k] for k in down_ids)
    assert all(arc_over[k] and k not in trench for k in upper_ids)
    mismatched = copy.deepcopy(result.mesh)
    mismatched.cells[down_ids[0]].plate_id = "unrelated-plate"
    with pytest.raises(ValueError, match="plate assignment"):
        load_orogen_contract(path, mesh=mismatched)


def test_terrain_crust_preparation_reclassifies_contacts_without_rebuilding_history(built) -> None:
    cfg, result = built
    mesh = copy.deepcopy(result.mesh)
    contract = build_orogen_contract(mesh, result.plates, cfg.radius_km)
    ocean_ids = {k for k, v in contract.contact_polarities.items() if v[0] == "ocean"}
    assert ocean_ids
    history = copy.deepcopy((contract.segments, contract.escape, contract.retained_km))
    # Terrain preparation can restore authored continental fragments. Its
    # resulting crust must define the ocean-contact type for both consumers.
    for cell in mesh.cells:
        cell.crust_type = "continental"
    resolve_contract_polarities(mesh, result.plates, contract, cfg.radius_km, stage="terrain-crust")
    assert contract.polarity_stage == "terrain-crust"
    assert all(contract.contact_polarities[k][0] != "ocean" for k in ocean_ids)
    assert (contract.segments, contract.escape, contract.retained_km) == history
    trench = trench_sources(mesh, result.plates, contract, cfg.radius_km)
    _, _, over = _arc_geometry(mesh, result.plates, cfg.radius_km, orogen_contract=contract)
    assert not trench and not over.any()


def test_declared_tectonic_arc_side_is_independent_of_common_rotation() -> None:
    cells = []
    for side in (-1, 1):
        for lo in np.linspace(-30, 30, 20):
            lat, lon = np.radians(side * 4), np.radians(lo)
            i = len(cells)
            cells.append(
                VoronoiCell(
                    id=i,
                    lat=side * 4,
                    lon=lo,
                    crust_type="oceanic",
                    x=np.cos(lat) * np.cos(lon),
                    y=np.sin(lat),
                    z=np.cos(lat) * np.sin(lon),
                    neighbors=[j for j in (i - 1, i + 1) if 0 <= j < 40],
                )
            )
    mesh = CVTMesh(seed=7, num_cells=40, cells=cells)
    mapping = {k: "a" if k < 20 else "b" for k in range(40)}
    source = SubductionPolarity("slab", ("a", "b"), "b", valid_from_age_myr=20)
    states = []
    for common in (-2e-6, 2e-6):
        plates = [
            TectonicPlate(
                id=p,
                name=p,
                cell_ids=list(range(i * 20, (i + 1) * 20)),
                euler_pole=EulerPole(x=0, y=0, z=1, omega_rad_yr=common + w),
            )
            for i, (p, w) in enumerate((("a", 1e-8), ("b", -1e-8)))
        ]
        state = {}
        _relax_segment(
            mesh,
            mapping.copy(),
            list(range(40)),
            *plates,
            6371,
            54,
            1,
            state,
            mapping,
            {"a": 1000, "b": 1000},
            subduction_polarities=[source],
            age_myr=5,
        )
        assert set(state) == {("b", "a")}
        states.append(state[("b", "a")])
    assert states[0] == pytest.approx(states[1], abs=1e-12)


def test_polarity_input_invalidates_tectonics_and_terrain_only() -> None:
    cfg = TerrainPipelineConfig()
    changed = replace(cfg, subduction_polarities=[SubductionPolarity("s", ("a", "b"), "a")])
    for stage in ("mesh", "plates", "boundaries"):
        assert build_stage_fingerprint(stage, cfg) == build_stage_fingerprint(stage, changed)
    for stage in ("tectonics", "terrain"):
        assert build_stage_fingerprint(stage, cfg) != build_stage_fingerprint(stage, changed)
