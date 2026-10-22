"""Heat-pipe provinces (map/heat_pipe.py, proposals/island-catalog.md §3.2)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from dreamulator.map.heat_pipe import (
    KM_PER_MY_PER_W_M2,
    TidalHeatHistory,
    heat_pipe_rate_km_my,
    heat_segments,
    heating_pattern,
    load_tidal_heat_history,
    province_index,
)

NACREA = Path("data/worlds/nacrea/layers/geological/input/tidal_heat_history.yaml")


def _history(recent: list[float], **kw: object) -> TidalHeatHistory:
    data: dict[str, object] = {
        "recent": {"step_kyr": 10, "heat_flow_w_m2": recent},
        "ensemble": {
            "quiet_median_kyr": 250,
            "quiet_sigma_ln": 0.6,
            "quiet_heat_flow_w_m2": [0.2, 0.6],
            "active_median_kyr": 50,
            "active_sigma_ln": 1.2,
            "active_max_kyr": 1050,
            "active_heat_flow_w_m2": [1.22, 1.85],
        },
        "active_threshold_w_m2": 1.2,
    }
    data.update(kw)
    return TidalHeatHistory.model_validate(data)


def test_heating_pattern_mean_and_extrema() -> None:
    rng = np.random.default_rng(0)
    v = rng.standard_normal((400_000, 3))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    assert heating_pattern(v).mean() == pytest.approx(1.0, abs=0.01)
    pts = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1.0]])
    np.testing.assert_allclose(heating_pattern(pts), [2.5, 2.5, 2.5, 2.5, 0.0])
    assert list(province_index(pts[:4])) == [0, 1, 2, 3]


def test_magma_rate_unit_and_plate_share() -> None:
    assert abs(KM_PER_MY_PER_W_M2 - 5.26) < 0.01  # 0017 §4: about 5 mm/yr per W/m²
    sub = np.array([[1.0, 0.0, 0.0]])
    rate = heat_pipe_rate_km_my(sub, 1.0, np.ones(4), 0.5)
    assert rate[0] == pytest.approx((2.5 - 0.5) * KM_PER_MY_PER_W_M2)
    node = np.array([[0.0, 0.0, 1.0]])  # zero heating: the plates carry it all
    assert heat_pipe_rate_km_my(node, 1.0, np.ones(4), 0.1)[0] == 0.0
    half = heat_pipe_rate_km_my(sub, 1.0, np.array([0.5, 1, 1, 1]), 0.0)
    assert half[0] == pytest.approx(0.5 * 2.5 * KM_PER_MY_PER_W_M2)


def test_segments_from_recent_and_ensemble() -> None:
    hist = _history([0.2] * 30 + [1.5] * 5 + [0.3] * 20, latest_phase_activity={"anti": 0.5})
    segs = heat_segments(hist, 5.0, np.random.default_rng(1))
    assert segs[0].young_myr == 0.0 and not segs[0].active
    assert segs[1].active and segs[1].heat_w_m2 == pytest.approx(1.5)
    assert segs[1].activity == (1.0, 0.5, 1.0, 1.0)  # the latest tidal phase: author activity
    assert segs[-1].old_myr == pytest.approx(5.0)
    for a, b in zip(segs, segs[1:], strict=False):
        assert a.old_myr == pytest.approx(b.young_myr)
        assert a.active != b.active
    again = heat_segments(hist, 5.0, np.random.default_rng(1))
    assert [s.old_myr for s in again] == [s.old_myr for s in segs]


def test_history_validation_and_nacrea_file() -> None:
    with pytest.raises(ValidationError):
        _history([0.2], latest_phase_activity={"east": 1.0})
    with pytest.raises(ValidationError):
        _history([0.2], unknown_key=1)
    assert load_tidal_heat_history(None) is None
    hist = load_tidal_heat_history(NACREA)
    assert hist is not None and len(hist.recent.heat_flow_w_m2) == 201
    assert hist.recent.heat_flow_w_m2[0] == pytest.approx(0.18, abs=0.02)  # 0014: ~0.19 W/m²


def test_catalogue_heat_pipe_volcanoes() -> None:
    from dreamulator.map.island_catalog import build_island_catalog
    from dreamulator.map.pipeline_types import TerrainPipelineConfig
    from dreamulator.map.terrain_pipeline import run_terrain_pipeline

    cfg = TerrainPipelineConfig(
        num_nodes=6000, lloyd_iterations=1, num_plates=8, seed=7, tectonic_duration_my=20.0
    )
    res = run_terrain_pipeline(
        cfg, stages=["mesh", "plates", "tectonics", "boundaries", "terrain"], cache=None
    )
    assert not [
        v for v in build_island_catalog(res.mesh, res.plates, cfg).volcanoes if v.kind == "heatpipe"
    ]
    hot = replace(cfg, tidal_heat_history=_history([0.4] * 50 + [1.6] * 10 + [0.4] * 100))
    hp = [
        v for v in build_island_catalog(res.mesh, res.plates, hot).volcanoes if v.kind == "heatpipe"
    ]
    assert hp and all(v.relief_m > 0.0 for v in hp)
    assert {v.source for v in hp} <= {"hp_sub", "hp_anti", "hp_north", "hp_south"}
    slopes = [np.degrees(np.arctan(v.relief_m / 1000.0 / v.base_radius_km)) for v in hp]
    assert np.allclose(slopes, 0.4, atol=0.01)  # Io-like low shields
