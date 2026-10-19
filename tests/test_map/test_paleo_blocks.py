"""Tests for continental blocks and weld relations (paleo_blocks)."""

from __future__ import annotations

import numpy as np
from scipy.spatial import SphericalVoronoi

from dreamulator.map.cvt_mesh import build_adjacency_graph, fibonacci_sphere
from dreamulator.map.paleo_blocks import (
    Blocks,
    Weld,
    block_snapshot,
    build_blocks,
    finite_rotations,
)
from dreamulator.map.paleo_kinematics import (
    PlateKinematics,
    adjacency_csr,
    rewind,
    rotation_matrices,
)
from dreamulator.map.paleo_sutures import AuthorSuture

RADIUS_KM = 6371.0
OMEGA = 1.0e-8


def _kin() -> PlateKinematics:
    pts = fibonacci_sphere(4000)
    sv = SphericalVoronoi(pts, radius=1.0)
    sv.sort_vertices_of_regions()
    adj = build_adjacency_graph(sv)
    ptr, idx = adjacency_csr([adj[i] for i in range(len(pts))])
    plate = (pts[:, 0] < 0).astype(np.int64)
    return PlateKinematics(
        xyz=pts,
        nbr_ptr=ptr,
        nbr_idx=idx,
        plate=plate,
        omega=np.array([[0.0, OMEGA, 0.0], [0.0, -OMEGA, 0.0]]),
        continental=np.abs(pts[:, 1]) < 0.5,  # an equatorial ring split by the plates
        area_km2=sv.calculate_areas() * RADIUS_KM**2,
        radius_km=RADIUS_KM,
    )


def test_weld_intervals_and_groups() -> None:
    welds = [
        Weld(0, 1, "suture", until_myr=50.0),
        Weld(1, 2, "rift", since_myr=10.0),
    ]
    b = Blocks(block=np.zeros(1), plate=np.array([0, 0, 1]), welds=welds)
    assert b.groups(5.0).tolist() == [0, 0, 2]  # rift still open
    assert b.groups(20.0).tolist() == [0, 0, 0]  # rift closed, suture holds
    assert b.groups(60.0).tolist() == [0, 1, 1]  # before the collision


def test_finite_rotations_compose_stages() -> None:
    w = np.array([[[0.0, OMEGA, 0.0]]] * 3)  # constant pole over three stages
    r = finite_rotations(w, 5.0, 12.0)
    np.testing.assert_allclose(r[0], rotation_matrices(w[0], -12.0e6)[0], atol=1e-12)


def test_block_snapshot_with_fixed_poles_matches_rewind() -> None:
    kin = _kin()
    blocks = build_blocks(kin)
    assert blocks.n == 2 and blocks.plate.tolist() == [0, 1]
    age = np.where(kin.continental, np.nan, 30.0)
    stage = np.repeat(kin.omega[blocks.plate][None], 4, axis=0)
    rb = finite_rotations(stage, 5.0, 17.0)
    ro = rotation_matrices(kin.omega, -17.0e6)
    a = rewind(kin, age, 17.0)
    b = block_snapshot(kin, age, blocks, rb, ro, 17.0)
    np.testing.assert_array_equal(a.src, b.src)
    np.testing.assert_array_equal(a.gap, b.gap)


def test_sutures_cut_blocks_and_rifts_weld_them() -> None:
    kin = _kin()
    lon = np.degrees(np.arctan2(kin.xyz[:, 2], kin.xyz[:, 0]))
    # a north-south suture through plate 0's continent at lon 30
    s = AuthorSuture(
        id="s",
        name="s",
        collision_age_myr=40.0,
        path=np.array([[30.0, -40.0], [30.0, 40.0]]),
        width_km=500.0,  # wider than the coarse test mesh's spacing (~360 km)
        moving_side="east",
    )
    blocks = build_blocks(kin, [s], rift_onsets={(0, 1): 8.0})
    assert blocks.n == 3
    east = blocks.block[(lon > 40) & (lon < 80) & kin.continental]
    assert len(set(east.tolist())) == 1 and "+s" in blocks.names[int(east[0])]
    g0, g20 = blocks.groups(0.0), blocks.groups(20.0)
    assert len(set(g0.tolist())) == 2  # plate 0 (both blocks) and plate 1
    assert len(set(g20.tolist())) == 1  # the rift between the plates has closed
    suture_welds = [w for w in blocks.welds if w.kind == "suture"]
    assert len(suture_welds) == 1 and suture_welds[0].active(30.0)
    assert not suture_welds[0].active(50.0)  # before the collision the two sides are apart
