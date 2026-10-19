"""Tests for the receding-horizon block solver (paleo_solver)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy.linalg import expm
from scipy.spatial import SphericalVoronoi

from dreamulator.map.cvt_mesh import build_adjacency_graph, fibonacci_sphere
from dreamulator.map.paleo_blocks import build_blocks
from dreamulator.map.paleo_kinematics import PlateKinematics, adjacency_csr, rotation_matrices
from dreamulator.map.paleo_solver import (
    SolverConfig,
    _exempt,
    _window_objective,
    build_setup,
    left_jacobian,
    skew,
    solve,
)

RADIUS_KM = 6371.0
OMEGA = 2.0e-8


def _kin() -> PlateKinematics:
    """Two plates split at x = 0, a continent on each side of the lon-90 boundary.

    Going back, the poles drive the two continents into each other.
    """
    pts = fibonacci_sphere(3000)
    sv = SphericalVoronoi(pts, radius=1.0)
    sv.sort_vertices_of_regions()
    adj = build_adjacency_graph(sv)
    ptr, idx = adjacency_csr([adj[i] for i in range(len(pts))])
    plate = (pts[:, 0] < 0).astype(np.int64)
    lon = np.degrees(np.arctan2(pts[:, 2], pts[:, 0]))
    cont = (np.abs(pts[:, 1]) < 0.4) & (np.abs(lon - 90.0) > 8.0) & (np.abs(lon - 90.0) < 50.0)
    # plate 0 (x > 0, lon < 90) moves west, plate 1 east: apart forward, together going back
    return PlateKinematics(
        xyz=pts,
        nbr_ptr=ptr,
        nbr_idx=idx,
        plate=plate,
        omega=np.array([[0.0, OMEGA, 0.0], [0.0, -OMEGA, 0.0]]),
        continental=cont,
        area_km2=sv.calculate_areas() * RADIUS_KM**2,
        radius_km=RADIUS_KM,
    )


def _setup(config: SolverConfig):  # type: ignore[no-untyped-def]
    kin = _kin()
    blocks = build_blocks(kin)
    nan = np.full(kin.n, np.nan)
    setup = build_setup(kin, blocks, kin.omega, nan, np.full(kin.n, -1), config)
    return kin, blocks, replace(setup, ridge_pairs=[(0, 1, 100.0)])


def test_left_jacobian_matches_matrix_exponential() -> None:
    rng = np.random.default_rng(1)
    theta = rng.normal(size=3) * 0.4
    d = rng.normal(size=3) * 1e-6
    lhs = expm(skew(theta + d)) - expm(skew(theta))
    rhs = skew(left_jacobian(theta[None])[0] @ d) @ expm(skew(theta))
    np.testing.assert_allclose(lhs, rhs, atol=1e-11)


def test_window_gradient_matches_finite_differences() -> None:
    config = SolverConfig(n_particles=1200, overlap_tol_km=0.0, contact_km=400.0)
    kin, blocks, setup = _setup(config)
    frame0 = rotation_matrices(kin.omega[blocks.plate], -10.0e6)  # already overlapping
    glists = [np.array([0, 1]), np.array([0, 1])]
    exempts = [_exempt(blocks, 15.0), _exempt(blocks, 20.0)]
    rng = np.random.default_rng(2)
    pole = kin.omega[blocks.plate]  # blocks are not numbered like plates
    u = (np.vstack([pole, pole]) / setup.rate_ref).ravel() + rng.normal(size=12) * 0.1
    prev = pole * 0.9
    args = (setup, config, frame0, prev, glists, exempts, [15.0, 20.0])
    value, grad, terms = _window_objective(u, *args)
    assert terms["overlap"] > 0 and terms["seafloor"] > 0
    h = 1e-6
    fd = np.array(
        [
            (_window_objective(u + h * e, *args)[0] - _window_objective(u - h * e, *args)[0])
            / (2 * h)
            for e in np.eye(u.size)
        ]
    )
    np.testing.assert_allclose(grad, fd, rtol=2e-3, atol=1e-6 * abs(value))


def test_solve_keeps_converging_continents_apart() -> None:
    config = SolverConfig(n_particles=800, end_myr=20.0, contact_km=200.0, max_iter=60)
    kin, blocks, setup = _setup(config)
    res = solve(blocks, setup, config, kin.omega[blocks.plate])
    assert res.stage_omega.shape == (4, 2, 3)
    # the present poles would push the continents through each other within 20 Myr;
    # the solve keeps the penetration near the tolerance
    assert res.stats[-1]["worst_depth_km"] < 3.0 * config.overlap_tol_km
    # poles are deterministic
    again = solve(blocks, setup, config, kin.omega[blocks.plate])
    np.testing.assert_array_equal(res.stage_omega, again.stage_omega)
