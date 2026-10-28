"""History contract, orogen part (map/orogen_contract.py, history-contract.md §3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.orogen_contract import (
    MARGIN_CONSUMED_KM,
    MAX_POST_COLLISION_CONVERGENCE_KM,
    CollisionOverride,
    _contact_histories,
    build_orogen_contract,
    load_collision_overrides,
    load_orogen_contract,
    save_orogen_contract,
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
    assert got.cell_history == seg.cell_history
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


def test_export_preserves_exact_contract_and_binds_mesh(built, tmp_path: Path) -> None:
    """A consumer can reproduce relief from the exported contract without rebuilding history."""
    import json
    from dataclasses import asdict

    from dreamulator.map.orogen_profile import orogen_relief

    cfg, res = built
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    path = tmp_path / "contract.json"
    save_orogen_contract(path, contract, mesh=res.mesh, radius_km=cfg.radius_km)
    restored = load_orogen_contract(path, mesh=res.mesh)
    assert asdict(restored) == asdict(contract)
    before = orogen_relief(res.mesh, contract, cfg.radius_km, cfg.gravity_m_s2, 850)
    after = orogen_relief(res.mesh, restored, cfg.radius_km, cfg.gravity_m_s2, 850)
    for a, b in zip(before, after, strict=True):
        np.testing.assert_array_equal(a, b)
    payload = json.loads(path.read_text())
    assert payload["segments"][0]["retained_km_median"] is not None
    assert payload["geometry"]["contacts"][0]["xyz"]
    other = res.mesh.model_copy(deep=True)
    other.cells[0].lat += 0.001
    with pytest.raises(ValueError, match="geometry"):
        load_orogen_contract(path, mesh=other)
    path.write_text(json.dumps({"segments": payload["segments"]}))
    with pytest.raises(ValueError, match="per-contact"):
        load_orogen_contract(path)


def test_contact_history_matches_nearest_evolution_cell(built) -> None:
    cfg, res = built
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    xyz = res.mesh.cell_xyz
    xyz = xyz / np.linalg.norm(xyz, axis=1, keepdims=True)
    had = np.array([i for i, c in enumerate(res.mesh.cells) if c.convergent_duration_my > 0])
    for segment in contract.segments:
        assert set(segment.cell_history) == set(segment.cell_ids)
        for k, history in segment.cell_history.items():
            distances = np.linalg.norm(xyz[had] - xyz[k], axis=1) * cfg.radius_km
            nearest = int(had[distances.argmin()])
            if distances.min() >= 400:
                assert history.status == "unavailable"
                assert history.source_cell_id is None and history.transfer_chord_km is None
            else:
                cell = res.mesh.cells[nearest]
                assert history.source_cell_id == nearest
                assert history.transfer_chord_km == pytest.approx(distances.min())
                assert history.continuous_duration_myr == cell.convergent_duration_my
                assert history.continuous_convergence_km == cell.convergent_run_km
                assert history.cumulative_convergence_km == cell.cumulative_convergence_km
            assert history.continuous_convergence_km == segment.cell_convergence_km[k]


def test_contact_history_marks_unavailable_transfer(built) -> None:
    cfg, res = built
    mesh = res.mesh.model_copy(deep=True)
    for cell in mesh.cells:
        cell.convergent_duration_my = 0
    xyz = mesh.cell_xyz
    far = int(np.argmin(xyz @ xyz[0]))
    empty = _contact_histories(mesh, [0, far], cfg.radius_km)
    assert all(h.status == "unavailable" for h in empty.values())
    mesh.cells[0].convergent_duration_my = 5
    mesh.cells[0].convergent_run_km = 18
    mesh.cells[0].cumulative_convergence_km = 25
    history = _contact_histories(mesh, [0, far], cfg.radius_km)
    assert history[0].source_cell_id == 0
    assert history[0].continuous_duration_myr == 5
    assert history[0].transfer_chord_km == 0
    assert history[far].status == "unavailable"
    assert history[far].source_cell_id is None


def test_export_full_interface_keeps_zero_contribution_and_polarity(built, tmp_path: Path) -> None:
    import json

    cfg, res = built
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    path = tmp_path / "contract.json"
    save_orogen_contract(path, contract, mesh=res.mesh)
    original = json.loads(path.read_text())["geometry"]
    for k in contract.retained_km:
        contract.retained_km[k] = 0
    save_orogen_contract(path, contract, mesh=res.mesh)
    geometry = json.loads(path.read_text())["geometry"]
    assert geometry["vertices"] == original["vertices"]
    assert geometry["interfaces"]
    vertices = {v["vertex_id"]: np.array(v["xyz"]) for v in geometry["vertices"]}
    segments = {s.id: s for s in contract.segments}
    expected = {
        (s.id, tuple(sorted((i, j))))
        for s in contract.segments
        for i in s.cell_ids
        for j in res.mesh.cells[i].neighbors
        if {res.mesh.cells[i].plate_id, res.mesh.cells[j].plate_id} == {s.pro_plate, s.retro_plate}
    }
    actual = set()
    for edge, previous in zip(geometry["interfaces"], original["interfaces"], strict=True):
        assert not edge["positive_retained_contact_cell_ids"]
        assert edge["vertex_ids"] == previous["vertex_ids"]
        actual.add((edge["segment_id"], tuple(edge["cell_ids"])))
        s = segments[edge["segment_id"]]
        a, b = [vertices[k] for k in edge["vertex_ids"]]
        np.testing.assert_allclose([np.linalg.norm(a), np.linalg.norm(b)], 1)
        pro = next(k for k in edge["cell_ids"] if res.mesh.cells[k].plate_id == s.pro_plate)
        assert np.cross(a, b) @ res.mesh.cell_xyz[pro] > 0
    assert actual == expected


def test_old_v2_contract_loads_without_history(built, tmp_path: Path) -> None:
    import json

    from dreamulator.map.orogen_profile import orogen_relief

    cfg, res = built
    contract = build_orogen_contract(res.mesh, res.plates, cfg.radius_km)
    path = tmp_path / "contract.json"
    save_orogen_contract(path, contract, mesh=res.mesh)
    payload = json.loads(path.read_text())
    assert all("cell_history" not in s for s in payload["detail"]["segments"])
    del payload["contact_history"]
    path.write_text(json.dumps(payload))
    restored = load_orogen_contract(path, mesh=res.mesh)
    assert all(not s.cell_history for s in restored.segments)
    for a, b in zip(
        orogen_relief(res.mesh, contract, cfg.radius_km, cfg.gravity_m_s2, 850),
        orogen_relief(res.mesh, restored, cfg.radius_km, cfg.gravity_m_s2, 850),
        strict=True,
    ):
        np.testing.assert_array_equal(a, b)


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
