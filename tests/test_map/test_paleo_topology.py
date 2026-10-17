"""Tests for the plate-boundary graph (plate topology layer, T1)."""

from __future__ import annotations

import numpy as np
from scipy.spatial import SphericalVoronoi

from dreamulator.map import paleo_topology as pt
from dreamulator.map.cvt_mesh import build_adjacency_graph, fibonacci_sphere
from dreamulator.map.paleo_kinematics import PlateKinematics, adjacency_csr

RADIUS_KM = 1000.0


def _mesh(n: int = 3000) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    pts = fibonacci_sphere(n)
    sv = SphericalVoronoi(pts, radius=1.0)
    sv.sort_vertices_of_regions()
    adj = build_adjacency_graph(sv)
    ptr, idx = adjacency_csr([adj[i] for i in range(n)])
    return pts, ptr, idx, sv.calculate_areas() * RADIUS_KM**2


def _kin(plate: np.ndarray, omega: np.ndarray) -> PlateKinematics:
    pts, ptr, idx, area = _mesh(len(plate))
    return PlateKinematics(
        xyz=pts,
        nbr_ptr=ptr,
        nbr_idx=idx,
        plate=plate,
        omega=omega,
        continental=np.zeros(len(plate), dtype=bool),
        area_km2=area,
        radius_km=RADIUS_KM,
    )


def _three_plates() -> PlateKinematics:
    pts = fibonacci_sphere(3000)
    lon = np.arctan2(pts[:, 2], pts[:, 0])
    plate = np.digitize(lon, [-np.pi / 3, np.pi / 3])  # three lunes meeting at the poles
    return _kin(plate.astype(np.int64), np.zeros((3, 3)))


def test_thresholds_follow_euler() -> None:
    assert pt.thresholds(52) == (5, 0.62)
    n_min, s_max = pt.thresholds(4)
    assert n_min == 3 and s_max == 0.9


def test_extract_finds_two_triple_junctions_and_three_segments() -> None:
    kin = _three_plates()
    topo = pt.extract(kin.xyz, kin.plate)
    assert len(topo.nodes) == 2
    assert len(topo.segments) == 3
    assert {abs(n[1]) > 0.95 for n in topo.nodes} == {True}  # at the poles
    for seg in topo.segments:
        assert seg.left != seg.right
        assert seg.start >= 0 and seg.end >= 0


def test_rasterize_reproduces_the_labels() -> None:
    kin = _three_plates()
    sp = kin.spacing_km / kin.radius_km
    topo = pt.prepare(pt.extract(kin.xyz, kin.plate), 0.5 * sp)
    lab = pt.rasterize(topo, kin, sp / 3.0)
    assert np.mean(lab == kin.plate) > 0.98
    chk = pt.check(kin, lab)
    assert chk.pieces_outside_largest < 0.01


def test_junction_velocity_satisfies_normal_constraints() -> None:
    node = np.array([0.0, 1.0, 0.0])
    normals = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [np.sqrt(0.5), 0.0, np.sqrt(0.5)]])
    target = np.array([2.0, 0.0, -1.0])
    vels = np.array([target, target, target])  # all boundaries move the same way
    v = pt.junction_velocity(node, normals, vels)
    np.testing.assert_allclose(v, target, atol=1e-12)


def test_attach_end_cuts_overshoot() -> None:
    lon = np.radians(np.linspace(0, 40, 41))
    pts = np.column_stack([np.cos(lon), np.zeros_like(lon), np.sin(lon)])
    node = pts[10]  # the junction slid 10 points inward
    out = pt.attach_end(pts, node, at_start=True)
    np.testing.assert_allclose(out[0], node)
    assert len(out) == len(pts) - 10


def test_rigid_common_rotation_moves_graph_rigidly() -> None:
    """If every plate rotates the same way, the graph rotates rigidly."""
    kin = _three_plates()
    w = np.array([0.0, 1.0e-8, 0.0])
    kin = PlateKinematics(**{**kin.__dict__, "omega": np.tile(w, (3, 1))})
    sp = kin.spacing_km / kin.radius_km
    topo = pt.prepare(pt.extract(kin.xyz, kin.plate), 0.5 * sp)
    pt.classify(topo, kin.omega, kin.radius_km)
    moved = pt.step(topo, kin.omega, 5.0, 0.5 * sp)
    rot = pt._rotate_points(topo.nodes, np.tile(w, (len(topo.nodes), 1)), -5.0e6)
    # junctions move by their linearized velocity: second-order difference only
    np.testing.assert_allclose(moved.nodes, rot, atol=1e-4)
    for before, after in zip(topo.segments, moved.segments, strict=True):
        expected = pt._rotate_points(before.points, np.tile(w, (len(before.points), 1)), -5.0e6)
        # light per-step smoothing and resampling move points only slightly
        d = np.arccos(np.clip(np.max(after.points @ expected.T, axis=1), -1, 1))
        assert d.max() < 0.5 * sp


def test_collision_is_detected_and_resolved_by_reclosing() -> None:
    kin = _three_plates()
    sp = kin.spacing_km / kin.radius_km
    topo = pt.prepare(pt.extract(kin.xyz, kin.plate), 0.5 * sp)
    for seg in topo.segments:
        seg.kind = pt.RIDGE
    assert not pt.find_crossings(topo, 2.0 * sp)
    # swing one pole-to-pole boundary about the polar axis until it crosses another
    seg = topo.segments[0]
    w = np.tile([0.0, np.radians(125.0), 0.0], (len(seg.points), 1))
    seg.points = pt._rotate_points(seg.points, w, 1.0)
    seg.points[0], seg.points[-1] = topo.nodes[seg.start], topo.nodes[seg.end]
    assert pt.find_crossings(topo, 2.0 * sp)
    grid = pt.event_grid(6000, kin.radius_km)
    side = (kin.xyz, kin.continental, np.full(kin.n, 10.0), pt.cKDTree(kin.xyz))
    new, stats = pt.reclose(topo, grid, sp, side, kin.omega, kin.radius_km)
    assert not pt.find_crossings(new, 2.0 * sp)
    assert all(s.kind == pt.RIDGE for s in new.segments if s.kind)  # types carried by plate pair
    # the plate squeezed between the crossed boundaries is split away as a thin part
    assert stats["segments"] >= 1


def test_topology_walk_is_identity_without_motion() -> None:
    from dreamulator.map.paleo_history import OceanDepth, Orogens
    from dreamulator.map.paleo_walk import WalkConfig, run_topology_walk

    kin = _three_plates()
    cont = kin.xyz[:, 1] > 0.6
    kin = PlateKinematics(**{**kin.__dict__, "continental": cont})
    sp = kin.spacing_km / kin.radius_km
    topo = pt.prepare(pt.extract(kin.xyz, kin.plate), 0.5 * sp)
    pt.classify(topo, kin.omega, kin.radius_km)
    age = np.where(cont, np.nan, 20.0)
    elev = np.where(cont, 500.0, -4000.0)
    orogens = Orogens(relief_m=np.zeros(kin.n), build_myr=np.ones(kin.n))
    depth = OceanDepth(ridge_depth_m=2500.0, subsidence_coeff=350.0, max_depth_m=5500.0)
    side = (kin.xyz, cont, age, pt.cKDTree(kin.xyz))
    cfg = WalkConfig(event_grid=0)
    snaps, log = run_topology_walk(kin, topo, age, elev, orogens, depth, [0.0, 3.0], cfg, side)
    s0, s3 = snaps
    np.testing.assert_array_equal(s0.continental, cont)
    assert np.mean(s3.continental == cont) > 0.99
    assert log.steps[-1]["continental_parcels_ratio"] == 1.0
    # oceanic parcels age with time: 20 Myr crust is 17 Myr old at −3 Myr and shallower
    ocean = ~s3.continental & np.isfinite(s3.age_myr)
    np.testing.assert_allclose(np.median(s3.age_myr[ocean]), 17.0, atol=0.5)
    assert np.median(s3.elevation_m[ocean]) > -4000.0


def test_continental_rifts_registers_only_opening_pairs() -> None:
    from dreamulator.map.paleo_walk import continental_rifts

    kin = _three_plates()
    omega = np.zeros((3, 3))
    omega[1] = [
        0.0,
        2.0e-8,
        0.0,
    ]  # plate 1 turns about the polar axis: opens one side, closes the other
    cont = np.ones(kin.n, dtype=bool)
    kin = PlateKinematics(**{**kin.__dict__, "omega": omega, "continental": cont})
    budget, onset = continental_rifts(kin, 300.0)
    assert len(budget) == 1  # one of its two boundaries opens, the other closes
    (pair,) = budget
    assert 1 in pair
    assert onset[pair] > 0


def test_rename_pairs_after_merge() -> None:
    from dreamulator.map.paleo_walk import _rename_pairs

    budget = {(0, 1): 10.0, (1, 2): 5.0, (0, 2): 7.0}
    onset = {(0, 1): 3.0, (1, 2): 4.0, (0, 2): 2.0}
    nb, no = _rename_pairs(budget, onset, {1: 0})
    assert nb == {(0, 2): 12.0}
    assert no == {(0, 2): 2.0}


def test_split_thin_parts_divides_a_ribbon_along_its_midline() -> None:
    grid = pt.event_grid(8000, RADIUS_KM)
    lon = np.degrees(np.arctan2(grid.xyz[:, 2], grid.xyz[:, 0]))
    lab = np.where(lon < 0, 0, 1)
    ribbon = (lon > -3) & (lon < 3) & (np.abs(grid.xyz[:, 1]) < 0.8)  # ~6 deg wide strip
    lab = np.where(ribbon, 2, lab)
    out = pt.split_thin_parts(grid, lab, 3)
    assert not np.any(out == 2)  # the ribbon is gone
    west = ribbon & (lon < -1)
    east = ribbon & (lon > 1)
    assert np.mean(out[west] == 0) > 0.9 and np.mean(out[east] == 1) > 0.9


def test_net_rotation_is_one_for_a_rigid_planet_and_zero_for_opposite_halves() -> None:
    from dreamulator.map.paleo_walk import _net_rotation

    pts, ptr, idx, area = _mesh(4000)
    half = (pts[:, 1] > 0).astype(np.int64)
    kin = PlateKinematics(pts, ptr, idx, half, np.zeros((2, 3)), half > 0, area, RADIUS_KM)
    same = np.array([[0.0, 1e-8, 0.0], [0.0, 1e-8, 0.0]])
    assert abs(_net_rotation(same, half, kin) - 1.0) < 0.02
    opposite = np.array([[0.0, 1e-8, 0.0], [0.0, -1e-8, 0.0]])
    assert _net_rotation(opposite, half, kin) < 0.02


def test_segment_probes_and_opening_fraction_follow_the_poles() -> None:
    from dreamulator.map.paleo_walk import _opening_fraction, _segment_probes

    kin = _three_plates()
    sp = kin.spacing_km / kin.radius_km
    topo = pt.prepare(pt.extract(kin.xyz, kin.plate), 0.5 * sp)
    omega = np.zeros((3, 3))
    omega[1] = [0.0, 2.0e-8, 0.0]
    pt.classify(topo, omega, kin.radius_km)
    cont = np.ones(kin.n, dtype=bool)
    side = (kin.xyz, cont, np.full(kin.n, np.nan), pt.cKDTree(kin.xyz))
    ridge = _segment_probes(topo, side, sp, want="ridge")
    both = _segment_probes(topo, side, sp, want="continental")
    assert len(ridge[0]) > 0 and len(both[0]) > len(ridge[0])
    assert _opening_fraction(omega, ridge, opening=False) < 0.05  # ridges open
    reversed_ = -omega
    assert _opening_fraction(reversed_, ridge, opening=False) > 0.95
    # one of plate 1's two boundaries opens: about half of all boundary points
    assert 0.2 < _opening_fraction(omega, both, opening=True) < 0.8


def test_perturb_poles_respects_the_speed_cap_and_idle_plates() -> None:
    from dreamulator.map.paleo_walk import WalkConfig, _perturb_poles

    omega = np.array([[0.0, 1e-8, 0.0], [0.0, 0.0, 0.0], [3e-8, 0.0, 0.0]])
    cap_cm_yr = 1e-8 * RADIUS_KM * 1e5
    rng = np.random.default_rng(1)
    for _ in range(20):
        out = _perturb_poles(omega, np.array([0, 1, 2]), rng, WalkConfig(), cap_cm_yr, RADIUS_KM)
        assert np.all(np.linalg.norm(out, axis=1) <= 1e-8 * (1 + 1e-9))
        np.testing.assert_array_equal(out[1], 0.0)


def test_airy_thickness_round_trips_and_follows_isostasy() -> None:
    from dreamulator.map.paleo_walk import crust_thickness_km, elevation_from_thickness_m

    z = np.array([-3000.0, -200.0, 0.0, 500.0, 5000.0])
    h = crust_thickness_km(z)
    np.testing.assert_allclose(h[2], 35.0)
    np.testing.assert_allclose(h[4], 35.0 + 5.0 * 3300 / 500, rtol=1e-12)  # 5 km plateau: 68 km
    np.testing.assert_allclose(elevation_from_thickness_m(h), z, atol=1e-9)


def test_unstretch_conserves_volume_and_caps_thickness() -> None:
    from dreamulator.map.paleo_walk import _unstretch

    pos = np.array([[1.0, 0.0, 0.0], [1.0, 0.001, 0.0], [1.0, -0.001, 0.0], [0.0, 1.0, 0.0]])
    pos /= np.linalg.norm(pos, axis=1, keepdims=True)
    plate = np.array([1, 0, 0, 0])
    thick = np.array([20.0, 20.0, 25.0, 10.0])  # parcel 0 overlaps plate 0's thinned crust
    total = thick.sum()
    receivers = np.array([False, True, True, True])
    done, moved = _unstretch(pos, plate, thick, np.array([0]), np.array([0]), receivers, 35.0, 0.01)
    assert done[0] and moved == 20.0  # room 15 + 10 km
    np.testing.assert_allclose(thick.sum(), total)
    assert thick[1] <= 35.0 and thick[2] <= 35.0
    assert thick[3] == 10.0  # out of reach
    # more than the room left (5 + 0 km): the parcel stays, thinner
    thick2 = np.array([30.0, 35.0, 30.0, 10.0])
    done2, moved2 = _unstretch(
        pos, plate, thick2, np.array([0]), np.array([0]), receivers, 35.0, 0.01
    )
    assert not done2[0] and moved2 == 5.0 and thick2[0] == 25.0


def test_rate_thresholds_are_scale_invariant() -> None:
    from dreamulator.map.paleo_walk import continental_rifts

    kin = _three_plates()
    omega = np.array([[0.0, 0.0, 0.0], [0.0, 2.0e-8, 0.0], [1.0e-9, 0.0, 3.0e-10]])
    cont = np.ones(kin.n, dtype=bool)
    sp = kin.spacing_km / kin.radius_km
    kinds = []
    rifts = []
    for k in (1.0, 0.01):
        kk = PlateKinematics(**{**kin.__dict__, "omega": omega * k, "continental": cont})
        topo = pt.prepare(pt.extract(kk.xyz, kk.plate), 0.5 * sp)
        pt.classify(topo, kk.omega, kk.radius_km)
        kinds.append([s.kind for s in topo.segments])
        budget, onset = continental_rifts(kk, 300.0)
        rifts.append((sorted(budget), {p: v * k for p, v in onset.items()}))
    assert kinds[0] == kinds[1]
    assert rifts[0][0] == rifts[1][0]
    for p in rifts[0][1]:
        np.testing.assert_allclose(rifts[0][1][p], rifts[1][1][p], rtol=1e-9)
