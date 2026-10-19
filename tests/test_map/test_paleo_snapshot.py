"""Tests for snapshots derived from solved block motions (paleo_snapshot)."""

from __future__ import annotations

import numpy as np
from scipy.spatial import SphericalVoronoi

from dreamulator.map.cvt_mesh import build_adjacency_graph, fibonacci_sphere
from dreamulator.map.paleo_blocks import build_blocks
from dreamulator.map.paleo_history import Orogens
from dreamulator.map.paleo_kinematics import PlateKinematics, adjacency_csr
from dreamulator.map.paleo_snapshot import DepthLaw, land_mask, ocean_hosts, snapshot

RADIUS_KM = 6371.0
OMEGA = 2.0e-8
DEPTH = DepthLaw(ridge_depth_m=2500.0, subsidence_coeff=350.0, max_depth_m=6000.0)


def _world() -> tuple[PlateKinematics, np.ndarray, np.ndarray]:
    """Two plates split at x = 0 separating at a ridge on the lon-90 boundary.

    Each plate carries an equatorial continent 8–50° from the ridge; the seafloor
    age is the longitude from the ridge over the angular speed.
    """
    pts = fibonacci_sphere(3000)
    sv = SphericalVoronoi(pts, radius=1.0)
    sv.sort_vertices_of_regions()
    adj = build_adjacency_graph(sv)
    ptr, idx = adjacency_csr([adj[i] for i in range(len(pts))])
    lon = np.degrees(np.arctan2(pts[:, 2], pts[:, 0]))
    off = np.abs(lon - 90.0)
    cont = (np.abs(pts[:, 1]) < 0.4) & (off > 8.0) & (off < 50.0)
    kin = PlateKinematics(
        xyz=pts,
        nbr_ptr=ptr,
        nbr_idx=idx,
        plate=(pts[:, 0] < 0).astype(np.int64),
        omega=np.array([[0.0, OMEGA, 0.0], [0.0, -OMEGA, 0.0]]),
        continental=cont,
        area_km2=sv.calculate_areas() * RADIUS_KM**2,
        radius_km=RADIUS_KM,
    )
    age = np.where(~cont & (off < 60.0), np.radians(off) / OMEGA / 1.0e6, np.nan)
    elev = np.where(cont, 500.0, -DEPTH(np.nan_to_num(age, nan=200.0)))
    return kin, age, elev


def _poles(kin: PlateKinematics, n_stages: int) -> tuple[np.ndarray, np.ndarray, object]:
    blocks = build_blocks(kin)
    stage = np.repeat(kin.omega[blocks.plate][None], n_stages, axis=0)
    groups = np.repeat(np.arange(blocks.n)[None], n_stages, axis=0)
    return stage, groups, blocks


def test_snapshot_at_present_is_the_present() -> None:
    kin, age, elev = _world()
    stage, groups, blocks = _poles(kin, 2)
    snap = snapshot(kin, blocks, age, stage, groups, 5.0, 0.0, kin.omega, elev, DEPTH)
    np.testing.assert_array_equal(snap.src, np.arange(kin.n))
    np.testing.assert_allclose(snap.elevation_m, elev)
    assert snap.check.plates == 2
    # one closed boundary loop: it opens on one side and closes on the other
    assert len(snap.topology.segments) == 1


def test_seafloor_younger_than_t_is_gone_and_the_rest_is_shallower() -> None:
    kin, age, elev = _world()
    stage, groups, blocks = _poles(kin, 4)
    t = 5.0
    snap = snapshot(kin, blocks, age, stage, groups, 5.0, t, kin.omega, elev, DEPTH)
    kept = snap.src >= 0
    assert not np.any(age[snap.src[kept]] < t)  # no crust younger than t survives
    sea = kept & ~snap.continental & np.isfinite(age[snap.src])
    np.testing.assert_allclose(snap.age_myr[sea], age[snap.src[sea]] - t)
    assert np.all(snap.elevation_m[sea] >= elev[snap.src[sea]] - 1e-6)
    # the ridge closes going back: the gap stays small and the plates still meet there
    assert (snap.src < 0).mean() < 0.05


def test_orogens_younger_than_t_are_cut_down() -> None:
    kin, age, elev = _world()
    stage, groups, blocks = _poles(kin, 4)
    relief = np.where(kin.continental, 1000.0, 0.0)
    orog = Orogens(relief_m=relief, build_myr=np.full(kin.n, 20.0))
    plain = snapshot(kin, blocks, age, stage, groups, 5.0, 10.0, kin.omega, elev, DEPTH)
    cut = snapshot(kin, blocks, age, stage, groups, 5.0, 10.0, kin.omega, elev, DEPTH, orog)
    land = cut.continental
    np.testing.assert_allclose(cut.elevation_m[land], plain.elevation_m[land] - 500.0)


def test_ocean_hosts_follow_their_plate() -> None:
    kin, _, _ = _world()
    blocks = build_blocks(kin)
    host = ocean_hosts(kin, blocks)
    sea = ~kin.continental
    assert np.all(host[sea] >= 0)
    assert np.all(blocks.plate[host[sea]] == kin.plate[sea])
    assert np.all(host[kin.continental] == -1)


def test_land_mask_keeps_closed_basins_as_land() -> None:
    kin, _, _ = _world()
    elev = np.full(kin.n, -3000.0)
    lon = np.degrees(np.arctan2(kin.xyz[:, 2], kin.xyz[:, 0]))
    lat = np.degrees(np.arcsin(kin.xyz[:, 1]))
    ring = (np.abs(lat) < 20) & (np.abs(lon) < 20)
    elev[ring] = 500.0
    basin = (np.abs(lat) < 8) & (np.abs(lon) < 8)
    elev[basin] = -100.0  # below sea level but enclosed
    land = land_mask(kin, elev, 0.0)
    assert land[basin].all() and land[ring].all() and not land[~ring].any()


def test_no_net_rotation_keeps_relative_motion() -> None:
    from dataclasses import replace

    from dreamulator.map.paleo_kinematics import no_net_rotation

    kin, _, _ = _world()
    spin = np.array([0.3, -0.2, 0.5]) * OMEGA
    shifted = replace(kin, omega=kin.omega + spin)  # same relative motion, other frame
    a, b = no_net_rotation(kin), no_net_rotation(shifted)
    np.testing.assert_allclose(a, b, atol=1e-22)
    np.testing.assert_allclose(a[0] - a[1], kin.omega[0] - kin.omega[1], atol=1e-22)
    # one rigid rotation of the whole surface has no motion left
    solid = replace(kin, omega=np.repeat(spin[None], 2, axis=0))
    np.testing.assert_allclose(no_net_rotation(solid), 0.0, atol=1e-22)
