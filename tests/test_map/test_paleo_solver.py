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
    conjugate_fit,
    crust_field,
    left_jacobian,
    ridge_record,
    rotation_vector,
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


def _setup(config: SolverConfig, sea_deg: float = 30.0):  # type: ignore[no-untyped-def]
    """Seafloor within ``sea_deg`` of a ridge on the lon-90 boundary.

    With ``sea_deg`` above 8 the seafloor at high latitude is older than the gap
    between the equatorial continents allows (they meet after about 7 Myr).
    """
    kin = _kin()
    blocks = build_blocks(kin)
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    ridge = np.unique(rows[kin.plate[rows] != kin.plate[kin.nbr_idx]])
    lon = np.degrees(np.arctan2(kin.xyz[:, 2], kin.xyz[:, 0]))
    ridge = ridge[np.abs(lon[ridge] - 90.0) < 30.0]
    age = np.full(kin.n, np.nan)
    source = np.full(kin.n, -1)
    sea = np.flatnonzero(~kin.continental & (np.abs(lon - 90.0) < sea_deg))
    for p in (0, 1):
        own = ridge[kin.plate[ridge] == p]
        cells = sea[kin.plate[sea] == p]
        d = np.arccos(np.clip(kin.xyz[cells] @ kin.xyz[own].T, -1, 1))
        source[cells] = own[np.argmin(d, axis=1)]
        # each plate turns about the axis at OMEGA: age = longitude from the ridge / OMEGA
        age[cells] = np.radians(np.abs(lon[cells] - 90.0)) / OMEGA / 1.0e6
    # half-rate (cm/yr) at the equator
    half = np.full(kin.n, np.nan)
    half[ridge] = OMEGA * RADIUS_KM * 1.0e5
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
    kin, blocks, setup = _setup(config, sea_deg=8.0)
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


def test_continent_next_to_a_ridge_is_a_soft_margin() -> None:
    # both flanks carry seafloor: neither continent sits on the ridge
    config = SolverConfig(n_particles=800, n_ocean_particles=800, margin_km=1500.0)
    kin, blocks, setup = _setup(config)
    assert not setup.cell_soft.any()
    # without ridge cells on plate 0's side (no seafloor there), plate 0's continent
    # near the ridge is a stretched margin; plate 1's is not
    lon = np.degrees(np.arctan2(kin.xyz[:, 2], kin.xyz[:, 0]))
    half = np.full(kin.n, np.nan)
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    ridge = np.unique(rows[kin.plate[rows] != kin.plate[kin.nbr_idx]])
    ridge = ridge[(kin.plate[ridge] == 1) & (np.abs(lon[ridge] - 90.0) < 30.0)]
    half[ridge] = OMEGA * RADIUS_KM * 1.0e5
    nan = np.full(kin.n, np.nan)
    soft = build_setup(kin, blocks, kin.omega, kin.omega, nan, np.full(kin.n, -1), half, config)
    near = kin.continental & (np.abs(lon - 90.0) < 12.0)  # within 1500 km
    assert soft.cell_soft[near & (kin.plate == 0)].all()
    assert not soft.cell_soft[kin.plate == 1].any()
    assert not soft.cell_soft[kin.continental & (np.abs(lon - 90.0) > 25.0)].any()
    inside = crust_field(soft, config, 0.0).sdf > 0
    assert not inside[:, near & (kin.plate == 0)].any()


def test_contact_is_not_welded_across_older_seafloor() -> None:
    # the seafloor says the two continents moved apart for about 26 Myr
    config = SolverConfig(
        n_particles=800, n_ocean_particles=800, end_myr=20.0, contact_km=200.0, max_iter=60
    )
    kin, blocks, setup = _setup(config)
    assert ridge_record(setup)[(0, 1)] > 20.0
    res = solve(blocks, setup, config)
    assert not res.contact_welds
    assert sum(st.get("refused_contacts", 0.0) for st in res.stats) > 0


def test_rotation_vector_inverts_the_exponential() -> None:
    theta = np.array([0.3, -0.5, 0.2])
    np.testing.assert_allclose(rotation_vector(expm(skew(theta))), theta, atol=1e-12)
    np.testing.assert_allclose(rotation_vector(np.eye(3)), 0.0, atol=1e-15)


def test_conjugate_fit_recovers_a_known_offset() -> None:
    # a round continent cut in two by the lon-90 boundary; turn one half by 3° and fit it back
    config = SolverConfig(n_particles=2500, n_ocean_particles=100, fit_window_km=800.0)
    kin, blocks, setup = _setup(config)
    centre = np.array([0.0, 0.0, 1.0])  # lon 90, lat 0
    disc = kin.xyz @ centre > np.cos(np.radians(30.0))
    touching = replace(kin, continental=disc)
    blocks = build_blocks(touching)
    nan = np.full(kin.n, np.nan)
    setup = build_setup(
        touching, blocks, kin.omega, kin.omega, nan, np.full(kin.n, -1), nan, config
    )
    frame = np.repeat(np.eye(3)[None], blocks.n, axis=0)
    # on this coarse mesh (spacing ~3.6°) the fit already pulls the facing edges
    # together; the nudge must come back on top of that
    rot0 = conjugate_fit(setup, config, frame, np.array([0]), np.array([1]))[0]
    nudge = expm(skew(np.radians(6.0) * np.array([0.0, 1.0, 0.0])))
    frame[0] = nudge
    rot, before, after, pairs = conjugate_fit(setup, config, frame, np.array([0]), np.array([1]))
    assert pairs > 0 and after < 0.5 * before
    left = rot @ nudge @ rot0.T
    angle = np.degrees(np.arccos(np.clip((np.trace(left) - 1) / 2, -1, 1)))
    assert angle < 1.5  # the 6° nudge is undone to well within a mesh spacing
