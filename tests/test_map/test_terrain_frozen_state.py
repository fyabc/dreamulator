"""Replay terrain from an owned, fixed tectonic realization."""

from __future__ import annotations

import pickle
from dataclasses import replace

import numpy as np
import pytest

from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline


@pytest.fixture(scope="module")
def fixed_tectonics():
    cfg = TerrainPipelineConfig(num_nodes=128, num_plates=6, lloyd_iterations=1)
    state = run_terrain_pipeline(cfg, stages=["mesh", "plates", "boundaries"])
    return cfg, state


def test_fixed_state_replays_and_terrain_edits_preserve_source(fixed_tectonics, monkeypatch):
    cfg, state = fixed_tectonics
    before = pickle.dumps(state)

    def forbidden(*args, **kwargs):
        pytest.fail("Fixed tectonics must not be regenerated")

    monkeypatch.setattr("dreamulator.map.terrain_pipeline.generate_cvt_mesh", forbidden)
    monkeypatch.setattr("dreamulator.map.terrain_pipeline.generate_plates", forbidden)
    monkeypatch.setattr("dreamulator.map.terrain_pipeline.detect_boundaries", forbidden)
    a = run_terrain_pipeline(cfg, stages=["terrain"], tectonic_state=state)
    b = run_terrain_pipeline(cfg, stages=["terrain"], tectonic_state=state)
    edited = run_terrain_pipeline(
        replace(cfg, noise_amplitude_land_m=2 * cfg.noise_amplitude_land_m),
        stages=["terrain"],
        tectonic_state=state,
    )
    np.testing.assert_array_equal(
        [c.elevation for c in a.mesh.cells], [c.elevation for c in b.mesh.cells]
    )
    assert a.stages_completed == ["terrain"]
    assert any(
        x.elevation != y.elevation for x, y in zip(a.mesh.cells, edited.mesh.cells, strict=True)
    )
    assert [c.plate_id for c in a.mesh.cells] == [c.plate_id for c in edited.mesh.cells]
    assert before == pickle.dumps(state)
