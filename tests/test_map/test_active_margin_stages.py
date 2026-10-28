"""Incoming-plate flexure and shelf ownership in complete terrain synthesis."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from dreamulator.map import terrain_synthesizer, trench_flexure
from dreamulator.map.orogen_contract import build_orogen_contract
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline


@pytest.mark.parametrize("gravity", [9.81, 19.62])
def test_synthesis_preserves_the_computed_incoming_plate_at_shelf_stage(
    monkeypatch: pytest.MonkeyPatch, gravity: float
) -> None:
    cfg = TerrainPipelineConfig(
        num_nodes=2000,
        radius_km=1500.0,
        gravity_m_s2=gravity,
        num_plates=8,
        seed=7,
        lloyd_iterations=1,
        tectonic_duration_my=20.0,
    )
    result = run_terrain_pipeline(cfg, stages=["mesh", "plates", "tectonics", "boundaries"])
    contract = build_orogen_contract(result.mesh, result.plates, cfg.radius_km)
    original_flexure = trench_flexure.trench_relief
    original_shelf = terrain_synthesizer._apply_continental_shelf
    footprints = []
    conflicts = []

    def record_flexure(*args, **kwargs):
        values = original_flexure(*args, **kwargs)
        footprints.append(values[2].copy())
        return values

    def inspect_shelf(mesh, elevation, config, rng, *, active_flexure=None):
        assert active_flexure is not None
        np.testing.assert_array_equal(active_flexure, footprints[-1])
        assert active_flexure.any(), "fixture must have a down-going plate"
        assert all(mesh.cells[k].crust_type == "oceanic" for k in np.flatnonzero(active_flexure))
        before = elevation.copy()
        old_rng = np.random.default_rng()
        old_rng.bit_generator.state = copy.deepcopy(rng.bit_generator.state)
        legacy = original_shelf(mesh, before.copy(), config, old_rng)
        out = original_shelf(mesh, elevation, config, rng, active_flexure=active_flexure)
        np.testing.assert_array_equal(out[active_flexure], before[active_flexure])
        np.testing.assert_array_equal(out[~active_flexure], legacy[~active_flexure])
        assert rng.bit_generator.state == old_rng.bit_generator.state
        np.testing.assert_array_equal(
            out > config.sea_level_offset_m, before > config.sea_level_offset_m
        )
        conflicts.append(int(np.count_nonzero(legacy[active_flexure] != before[active_flexure])))
        return out

    monkeypatch.setattr(trench_flexure, "trench_relief", record_flexure)
    monkeypatch.setattr(terrain_synthesizer, "_apply_continental_shelf", inspect_shelf)
    terrain_synthesizer.synthesize_terrain(
        result.mesh, result.plates, cfg, orogen_contract=contract
    )
    assert len(conflicts) == 1 and conflicts[0] > 0, (
        "fixture must exercise a shelf/flexure conflict"
    )
    assert np.isfinite([c.elevation for c in result.mesh.cells]).all()
