"""History contract, orogen part (map/orogen_contract.py, history-contract.md §3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.orogen_contract import (
    MARGIN_CONSUMED_KM,
    MAX_POST_COLLISION_CONVERGENCE_KM,
    CollisionOverride,
    build_orogen_contract,
    load_collision_overrides,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline

if TYPE_CHECKING:
    from pathlib import Path

TINY = dict(num_nodes=1500, lloyd_iterations=1, num_plates=8, seed=7, tectonic_duration_my=20.0)


@pytest.fixture(scope="module")
def built():
    cfg = TerrainPipelineConfig(**TINY)
    res = run_terrain_pipeline(
        cfg, stages=["mesh", "plates", "tectonics", "boundaries"], cache=None
    )
    return cfg, res


def test_continuous_run_fields_bounded(built) -> None:
    cfg, res = built
    dur = np.array([c.convergent_duration_my for c in res.mesh.cells])
    run = np.array([c.convergent_run_km for c in res.mesh.cells])
    tot = np.array([c.cumulative_convergence_km for c in res.mesh.cells])
    # evolution runs whole steps, so its length is ceil(duration / dt) * dt
    from dreamulator.map.tectonic_simulator import _auto_compute_dt

    dt = _auto_compute_dt(res.mesh, cfg, res.plates)
    assert (dur >= 0).all() and dur.max() <= cfg.tectonic_duration_my + 1.5 * dt
    assert (run <= tot + 1e-9).all()
    assert (run[dur == 0.0] == 0.0).all()
    assert (dur > 0).any()


def test_segments_are_convergent_contacts(built) -> None:
    cfg, res = built
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    assert contract.segments, "tiny world should have convergent segments"
    size = {p.id: len(p.cell_ids) for p in res.plates}
    cells = res.mesh.cells
    for s in contract.segments:
        assert s.kind in ("collision", "andean")
        for k in s.cell_ids:
            c = cells[k]
            assert c.boundary_type == "convergent"
            assert any(cells[j].plate_id != c.plate_id for j in c.neighbors)
        if s.kind == "collision":
            assert size[s.pro_plate] <= size[s.retro_plate]
        assert s.sources["onset_age_myr"] == "derived"


def test_retained_shortening_formula(built) -> None:
    cfg, res = built
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    for s in contract.segments:
        for k in s.cell_ids:
            got = contract.retained_km[k]
            conv = s.cell_convergence_km[k]
            if s.kind == "collision":
                conv = min(conv, MAX_POST_COLLISION_CONVERGENCE_KM)
            if s.kind == "andean":
                assert got == pytest.approx(s.upper_plate_ratio * conv)
            else:
                entering = conv - MARGIN_CONSUMED_KM - s.cell_rate_cm_yr[k] * s.breakoff_my * 10
                e = contract.escape.get(k, 0.0)
                assert 0.0 <= e <= 1.0
                pre = s.upper_plate_ratio * s.cell_pre_collision_km[k]
                assert got == pytest.approx(max(0.0, entering) * (1.0 - e) + pre)


def test_author_override_by_plates(built) -> None:
    cfg, res = built
    base = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    seg = base.segments[0]
    ov = CollisionOverride(
        id="test",
        kind=seg.kind,
        plates=(seg.pro_plate, seg.retro_plate),
        onset_age_myr=30.0,
        breakoff_my=5.0,
        upper_plate_ratio=0.07,
    )
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km, [ov], max_onset_myr=20.0)
    got = next(s for s in contract.segments if s.cell_ids == seg.cell_ids)
    assert got.onset_age_myr == 30.0
    assert got.convergence_km == pytest.approx(got.rate_cm_yr * 30.0 * 10.0)
    k = got.cell_ids[0]
    assert got.cell_convergence_km[k] == pytest.approx(got.cell_rate_cm_yr[k] * 300.0)
    assert got.breakoff_my == 5.0 and got.upper_plate_ratio == 0.07
    assert got.sources["onset_age_myr"] == "author"
    assert any("older than the tectonic history" in w for w in contract.warnings)


def test_load_collision_overrides(tmp_path: Path) -> None:
    p = tmp_path / "plate_history.yaml"
    p.write_text(
        "collisions:\n"
        "  - id: c1\n    path: [[0, 0], [10, 5]]\n"
        "    onset_age_myr: 35\n    down_going: plate_001\n"
        "andean_margins:\n"
        "  - id: m1\n    plates: [plate_002, plate_003]\n    upper_plate_ratio: 0.06\n",
        encoding="utf-8",
    )
    ovs = load_collision_overrides(p)
    assert [o.kind for o in ovs] == ["collision", "andean"]
    assert ovs[0].path is not None and ovs[0].onset_age_myr == 35.0
    assert ovs[1].plates == ("plate_002", "plate_003") and ovs[1].upper_plate_ratio == 0.06
    p.write_text("collisions:\n  - id: bad\n    onset_age_myr: 3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_collision_overrides(p)
    assert load_collision_overrides(tmp_path / "missing.yaml") == []


def test_orogen_relief_cap_and_widening(built) -> None:
    """Relief stays under the type cap; more retained crust widens rather than raises."""
    from dreamulator.map.orogen_profile import orogen_relief

    cfg, res = built
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    contact = [k for s in contract.segments for k in s.cell_ids]
    assert contact
    base = 850.0
    from dreamulator.map.orogen_profile import collision_cap_m

    cap = collision_cap_m(cfg.gravity_m_s2) - base
    widths = []
    for retained in (50.0, 400.0, 4000.0):
        for k in contact:
            contract.retained_km[k] = retained
        relief, _cap = orogen_relief(res.mesh, contract, cfg.radius_km, cfg.gravity_m_s2, base)
        assert relief.max() <= cap + 1e-6
        for i, c in enumerate(res.mesh.cells):
            if c.crust_type != "continental":
                assert relief[i] == 0.0
        widths.append(int((relief > 0).sum()))
    assert widths[0] < widths[1] < widths[2]


def test_collision_cap_force_balance() -> None:
    """Earth reproduces the Tibetan calibration; higher g lowers it (about 1/g); weaker lower."""
    from dreamulator.map.orogen_profile import collision_cap_m

    assert collision_cap_m(9.80665) == pytest.approx(5000.0, rel=1e-9)
    nacrea = collision_cap_m(10.28)
    assert 4700.0 < nacrea < 5000.0
    # Iran-like warm lithosphere: about one third of the force gives about a 2 km plateau
    assert collision_cap_m(9.80665, strength_factor=2.3 / 7.1) == pytest.approx(2000.0, rel=0.08)


def test_apply_orogen_cap_soft() -> None:
    """Excess over the cap is compressed to at most the softness; others untouched."""
    from dreamulator.map.orogen_profile import apply_orogen_cap

    elev = np.array([1000.0, 4900.0, 6000.0, 9000.0, 7000.0])
    cap = np.array([4800.0, 4800.0, 4800.0, 4800.0, np.inf])
    out = apply_orogen_cap(elev, cap, 0.0)
    assert out[0] == 1000.0 and out[4] == 7000.0
    assert 4800.0 < out[1] < 4900.0 and out[2] < out[3] <= 4800.0 + 300.0


def test_contract_independent_of_hash_seed(tmp_path: Path) -> None:
    """Plate-id ties must not follow the per-process string hash seed (technical debt 48)."""
    import os
    import subprocess
    import sys

    script = tmp_path / "contract.py"
    script.write_text(
        "from dreamulator.map.orogen_contract import build_orogen_contract\n"
        "from dreamulator.map.pipeline_types import TerrainPipelineConfig\n"
        "from dreamulator.map.terrain_pipeline import run_terrain_pipeline\n"
        f"cfg = TerrainPipelineConfig(**{TINY!r})\n"
        "res = run_terrain_pipeline(cfg, stages=['mesh', 'plates', 'tectonics', 'boundaries'],"
        " cache=None)\n"
        "c = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)\n"
        "print(sorted((s.kind, s.pro_plate, s.retro_plate, tuple(s.cell_ids))"
        " for s in c.segments), sorted(c.retained_km.items()))\n",
        encoding="utf-8",
    )
    outs = []
    for seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        r = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, env=env, check=True
        )
        outs.append(r.stdout.strip().splitlines()[-1])  # last line: the contract
    assert outs[0] == outs[1] == outs[2]
