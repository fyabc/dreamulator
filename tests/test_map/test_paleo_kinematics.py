"""Tests for the paleogeographic rewind (geological timeline M1)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from scipy.spatial import SphericalVoronoi

from dreamulator.map.cvt_mesh import build_adjacency_graph, fibonacci_sphere
from dreamulator.map.paleo_kinematics import (
    PlateKinematics,
    adjacency_csr,
    boundary_cells,
    fit_rotation,
    paleo_fields,
    reconstruction_plates,
    rewind,
    ridge_half_rates,
    rotation_matrices,
    synthesize_seafloor_age,
)

RADIUS_KM = 1000.0
#: 5 cm/yr at the rotation equator: ω = v / R.
OMEGA = 5.0e-5 / RADIUS_KM
DEPTH = {"ridge_depth_m": 2500.0, "subsidence_coeff": 350.0, "max_depth_m": 5500.0}


def _frozen(a: np.ndarray) -> np.ndarray:
    a = np.array(a)
    a.setflags(write=False)
    return a


@pytest.fixture(scope="module")
def two_plates() -> tuple[PlateKinematics, np.ndarray, np.ndarray]:
    """Two hemispheres (x > 0, x < 0) spinning in opposite senses about the y axis.

    Plate 0 turns about +y and plate 1 about −y, so along the y–z boundary circle
    they separate on the z > 0 half (a ridge) and converge on the z < 0 half (a
    trench).  Polar caps |x| > 0.8 are continental.  Returns the kinematics, a
    divergent-boundary mask and an elevation field; every array is read-only, so
    any in-place write by the code under test raises.
    """
    pts = fibonacci_sphere(4000)
    sv = SphericalVoronoi(pts, radius=1.0)
    sv.sort_vertices_of_regions()
    adj = build_adjacency_graph(sv)
    ptr, idx = adjacency_csr([adj[i] for i in range(len(pts))])
    plate = (pts[:, 0] < 0).astype(np.int64)
    kin = PlateKinematics(
        xyz=_frozen(pts),
        nbr_ptr=_frozen(ptr),
        nbr_idx=_frozen(idx),
        plate=_frozen(plate),
        omega=_frozen(np.array([[0.0, OMEGA, 0.0], [0.0, -OMEGA, 0.0]])),
        continental=_frozen(np.abs(pts[:, 0]) > 0.8),
        area_km2=_frozen(sv.calculate_areas() * RADIUS_KM**2),
        radius_km=RADIUS_KM,
    )
    rows = np.repeat(np.arange(kin.n), np.diff(ptr))
    on_boundary = np.zeros(kin.n, dtype=bool)
    on_boundary[rows[plate[rows] != plate[idx]]] = True
    elevation = np.where(kin.continental, 500.0, -4000.0) + 10.0 * pts[:, 1]
    return kin, _frozen(on_boundary), _frozen(elevation)


def test_rotation_is_reversible() -> None:
    omega = np.array([[0.0, 0.0, 2.0e-8], [3.0e-9, -1.0e-8, 4.0e-9]])
    back = rotation_matrices(omega, -5.0e6)
    fwd = rotation_matrices(omega, 5.0e6)
    np.testing.assert_allclose(fwd @ back, np.broadcast_to(np.eye(3), (2, 3, 3)), atol=1e-12)


def test_ridges_only_where_plates_separate(two_plates) -> None:
    kin, boundary, _ = two_plates
    half, _ = ridge_half_rates(kin, boundary)
    ridge = np.isfinite(half)
    assert ridge.any()
    assert np.all(kin.xyz[ridge, 2] > 0)  # the z < 0 half converges
    # Opening at the rotation equator (y = 0) is 2 × 5 cm/yr, so the half-rate is 5.
    eq = ridge & (np.abs(kin.xyz[:, 1]) < 0.1)
    np.testing.assert_allclose(np.median(half[eq]), 5.0, rtol=0.1)


def test_seafloor_age_is_symmetric_and_scales_with_distance(two_plates) -> None:
    kin, boundary, _ = two_plates
    half, offset = ridge_half_rates(kin, boundary)
    age, _ = synthesize_seafloor_age(kin, half, offset)
    assert np.all(np.isnan(age[kin.continental]))
    band = (np.abs(kin.xyz[:, 1]) < 0.1) & (kin.xyz[:, 2] > 0.3) & ~kin.continental
    dist_km = RADIUS_KM * np.arcsin(np.abs(kin.xyz[:, 0]))
    ok = band & np.isfinite(age)
    # age ≈ distance / half-rate, 5 cm/yr = 50 km/Myr
    np.testing.assert_allclose(age[ok], dist_km[ok] / 50.0, atol=1.5, rtol=0.15)
    # the two flanks have the same age distribution
    a0 = np.median(age[ok & (kin.plate == 0)])
    a1 = np.median(age[ok & (kin.plate == 1)])
    assert abs(a0 - a1) < 0.1 * max(a0, a1)


def test_zero_time_is_identity(two_plates) -> None:
    kin, boundary, elevation = two_plates
    half, offset = ridge_half_rates(kin, boundary)
    age, _ = synthesize_seafloor_age(kin, half, offset)
    state = rewind(kin, age, 0.0)
    np.testing.assert_array_equal(state.src, np.arange(kin.n))
    assert not state.gap.any() and not state.overlap.any() and not state.dropped.any()
    f = paleo_fields(kin, state, elevation, age, **DEPTH)
    np.testing.assert_array_equal(f.elevation_m, elevation)
    np.testing.assert_array_equal(f.continental, kin.continental)
    np.testing.assert_array_equal(f.plate, kin.plate)


def test_rewind_closes_ridge_and_opens_trench_gap(two_plates) -> None:
    kin, boundary, elevation = two_plates
    half, offset = ridge_half_rates(kin, boundary)
    age, _ = synthesize_seafloor_age(kin, half, offset)
    t = 4.0  # 5 cm/yr × 4 Myr = 200 km ≈ 3.5 cell spacings per plate
    state = rewind(kin, age, t)
    assert state.dropped.any()
    near_ridge = (np.abs(kin.xyz[:, 0]) < 0.15) & (kin.xyz[:, 2] > 0.5)
    near_trench = (np.abs(kin.xyz[:, 0]) < 0.15) & (kin.xyz[:, 2] < -0.5)
    # Crust younger than t is gone and the t-isochrons meet: no hole at the ridge.
    assert state.gap[near_ridge].mean() < 0.05
    # Behind the trench the crust consumed since t is missing.
    assert state.gap[near_trench].mean() > 0.3

    f = paleo_fields(kin, state, elevation, age, **DEPTH)
    ocean = (f.plate >= 0) & ~f.continental & np.isfinite(f.age_myr)
    assert np.all(f.age_myr[ocean] >= 0)
    # Younger ocean is shallower: the past floor sits above the present one.
    src = state.src[ocean]
    assert np.all(f.elevation_m[ocean] >= elevation[src] - 1e-9)
    # Rigid rotation keeps continental area (up to resampling noise).
    a = kin.area_km2
    ratio = a[f.continental].sum() / a[kin.continental].sum()
    assert 0.95 < ratio < 1.05


def test_fit_rotation_recovers_rigid_motion() -> None:
    rng = np.random.default_rng(0)
    xyz = rng.normal(size=(200, 3))
    xyz /= np.linalg.norm(xyz, axis=1, keepdims=True)
    omega = np.array([1.0e-8, -2.0e-8, 0.5e-8])
    fitted = fit_rotation(xyz, np.cross(omega, xyz), np.ones(200))
    np.testing.assert_allclose(fitted, omega, rtol=1e-9)


def test_reconstruction_plates_keep_a_straddling_continent_rigid(two_plates) -> None:
    kin, _, _ = two_plates
    # A continent around the +z pole straddles the plate boundary.
    straddle = replace(kin, continental=_frozen(kin.xyz[:, 2] > 0.8))
    rp = reconstruction_plates(straddle, np.zeros(kin.n, dtype=bool))
    block = straddle.continental
    assert np.unique(rp.block[block]).size == 1
    assert np.unique(rp.plate[block]).size == 1  # the whole block rides one plate
    np.testing.assert_array_equal(rp.plate[~block], kin.plate[~block])  # ocean unchanged
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    inside = block[rows] & block[cols]
    assert np.all(rp.plate[rows[inside]] == rp.plate[cols[inside]])  # no boundary inside

    # Flagging the boundary as a suture splits the continent back along it, and
    # unchanged plates get their present poles back.
    rp2 = reconstruction_plates(straddle, boundary_cells(kin))
    np.testing.assert_array_equal(rp2.plate, kin.plate)
    np.testing.assert_allclose(rp2.omega, kin.omega, rtol=1e-9, atol=1e-20)
    assert rp2.misfit_cm_yr.max() < 1e-6
