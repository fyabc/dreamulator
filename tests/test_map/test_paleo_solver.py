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
    stage_diagnostics,
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
    """Seafloor between the two continents made by a ridge on the lon-90 boundary."""
    kin = _kin()
    blocks = build_blocks(kin)
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    ridge = np.unique(rows[kin.plate[rows] != kin.plate[kin.nbr_idx]])
    lon = np.degrees(np.arctan2(kin.xyz[:, 2], kin.xyz[:, 0]))
    ridge = ridge[np.abs(lon[ridge] - 90.0) < 30.0]
    age = np.full(kin.n, np.nan)
    source = np.full(kin.n, -1)
    sea = np.flatnonzero(~kin.continental & (np.abs(lon - 90.0) < 30.0))
    for p in (0, 1):
        own = ridge[kin.plate[ridge] == p]
        cells = sea[kin.plate[sea] == p]
        d = np.arccos(np.clip(kin.xyz[cells] @ kin.xyz[own].T, -1, 1))
        source[cells] = own[np.argmin(d, axis=1)]
        # each plate turns about the axis at OMEGA: age = longitude from the ridge / OMEGA
        age[cells] = np.radians(np.abs(lon[cells] - 90.0)) / OMEGA / 1.0e6
    # half-rate (cm/yr) at the equator
    half = np.full(kin.n, OMEGA * RADIUS_KM * 1.0e5)
    setup = build_setup(kin, blocks, kin.omega, kin.omega, age, source, half, config)
    return kin, blocks, setup


def test_left_jacobian_matches_matrix_exponential() -> None:
    rng = np.random.default_rng(1)
    theta = rng.normal(size=3) * 0.4
    d = rng.normal(size=3) * 1e-6
    lhs = expm(skew(theta + d)) - expm(skew(theta))
    rhs = skew(left_jacobian(theta[None])[0] @ d) @ expm(skew(theta))
    np.testing.assert_allclose(lhs, rhs, atol=1e-11)


def test_window_gradient_matches_finite_differences() -> None:
    config = SolverConfig(
        n_particles=1200, n_ocean_particles=1200, overlap_tol_km=0.0, contact_km=400.0
    )
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
    assert terms["overlap"] > 0 and terms["isochron"] > 0
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
    config = SolverConfig(
        n_particles=800, n_ocean_particles=800, end_myr=20.0, contact_km=200.0, max_iter=60
    )
    kin, blocks, setup = _setup(config)
    res = solve(blocks, setup, config)
    assert res.stage_omega.shape == (4, 2, 3)
    # the present poles would push the continents through each other within 20 Myr;
    # the solve keeps the penetration near the tolerance
    assert res.stats[-1]["worst_depth_km"] < 3.0 * config.overlap_tol_km
    # poles are deterministic
    again = solve(blocks, replace(setup, cache={}), config)
    np.testing.assert_array_equal(res.stage_omega, again.stage_omega)


def test_isochrons_meet_under_the_poles_that_made_the_seafloor() -> None:
    config = SolverConfig(n_particles=800, n_ocean_particles=2000, contact_km=400.0)
    kin, blocks, setup = _setup(config)
    group = np.array([0, 1])
    none = np.zeros((2, 2), dtype=bool)
    pole = kin.omega[blocks.plate]
    good = stage_diagnostics(setup, config, rotation_matrices(pole, -10.0e6), group, none, 10.0)
    bad = stage_diagnostics(setup, config, rotation_matrices(-pole, -10.0e6), group, none, 10.0)
    spacing = np.sqrt(np.median(kin.area_km2))
    assert good["isochron_misfit_km"] < spacing
    assert bad["isochron_misfit_km"] > 5.0 * spacing
