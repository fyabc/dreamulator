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
