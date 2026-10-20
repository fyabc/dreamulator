"""Tests for the L2 procedural cloud texture prototype."""

from __future__ import annotations

import math

import numpy as np

from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.media import cloud_render as cr


def test_fbm3_deterministic_and_seed_sensitive() -> None:
    from dreamulator.map.noise_kernels import fbm_on_points

    rng = np.random.default_rng(0)
    pts = rng.normal(size=(500, 3))
    x, y, z = pts[:, 0].copy(), pts[:, 1].copy(), pts[:, 2].copy()
    a1 = fbm_on_points(x, y, z, seed=7, octaves=3)
    a2 = fbm_on_points(x.copy(), y.copy(), z.copy(), seed=7, octaves=3)
    b = fbm_on_points(x, y, z, seed=8, octaves=3)
    np.testing.assert_array_equal(a1, a2)
    assert not np.allclose(a1, b)
    assert np.abs(a1).max() < 1.0  # amplitude-normalised fBm stays well inside ±1


def test_sphere_sampling_seamless_at_antimeridian() -> None:
    """Noise is a function of sphere position: the two grid edges of the
    equirect map (λ = −180° and +180°) sample the same 3D points."""
    width = 64
    lat = np.array([0.3])
    x, y, z = cr._band_xyz(width, lat)
    # Column 0 sits at λ = −180° + Δ/2, column −1 at +180° − Δ/2: not the same
    # point, but their noise values must be close (continuous across the seam).
    from dreamulator.map.noise_kernels import fbm_on_points

    eps = 1e-3
    a = fbm_on_points(x[:1] + eps, y[:1], z[:1], seed=3, octaves=2)
    b = fbm_on_points(x[:1] - eps, y[:1], z[:1], seed=3, octaves=2)
    assert abs(a[0] - b[0]) < 5e-3  # continuous, not bitwise-equal


def test_large_scale_cover_end_members() -> None:
    # Saturated ITCZ cell: heavy precip + deep low → near-overcast.
    wet = cr.large_scale_cover(np.array([8000.0]), np.array([-12.0]))
    assert wet[0] > 0.9
    # Subtropical high desert: no precip + strong high → clear.
    dry = cr.large_scale_cover(np.array([20.0]), np.array([10.0]))
    assert dry[0] == 0.0
    # Monotonic in both legs (below saturation).
    p = np.array([50.0, 300.0, 1500.0])
    c = cr.large_scale_cover(p, np.zeros(3))
    assert np.all(np.diff(c) > 0)


def _toy_mesh(n: int = 400) -> CVTMesh:
    """Fibonacci-sphere toy mesh with latitude-banded conditioning fields."""
    from scipy.spatial import cKDTree

    cells = []
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n):
        y = 1.0 - 2.0 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - y * y))
        theta = golden * i
        x, z = r * math.cos(theta), r * math.sin(theta)
        lat = math.degrees(math.asin(y))
        lon = math.degrees(math.atan2(z, x))
        cells.append(
            VoronoiCell(
                id=i,
                lon=lon,
                lat=lat,
                x=x,
                y=y,
                z=z,
                area_km2=1.0,
                elevation=-4000.0,  # all ocean: surface base is bathy blue
                # Wet, low-pressure equator; dry, high-pressure subtropics.
                precipitation_mm=3000.0 if abs(lat) < 15 else 100.0,
                pressure_anomaly_annual_hpa=-10.0 if abs(lat) < 15 else 10.0,
                wind_east_m_s=5.0 if lat > 0 else -5.0,
                wind_north_m_s=0.0,
            )
        )
    xyz = np.array([[c.x, c.y, c.z] for c in cells])
    tree = cKDTree(xyz)
    adjacency: dict[str, list[int]] = {}
    for i in range(n):
        _, idx = tree.query(xyz[i], k=7)
        adjacency[str(i)] = [int(j) for j in idx[1:]]
    return CVTMesh(seed=0, num_cells=n, cells=cells, adjacency=adjacency)


def test_cloud_texture_bands_and_determinism() -> None:
    mesh = _toy_mesh()
    from dreamulator.map.export import export_cell_index_grid

    indices = export_cell_index_grid(mesh, 256, 128)
    cover, u, v, _oce, _dp = cr.conditioning_grids(mesh, indices)
    assert cover.shape == (128, 256)
    assert np.all((cover >= 0.0) & (cover <= 1.0))
    # Equatorial rows cloudier than subtropical rows on average.
    lat_rows = 90.0 - (np.arange(128) + 0.5) / 128 * 180.0
    eq = cover[np.abs(lat_rows) < 10].mean()
    subtrop = cover[(np.abs(lat_rows) > 20) & (np.abs(lat_rows) < 35)].mean()
    assert eq > subtrop

    p1 = cr.cloud_texture_equirect(cover, u, v, radius_km=6800.0, seed=7)
    p2 = cr.cloud_texture_equirect(cover, u, v, radius_km=6800.0, seed=7)
    np.testing.assert_array_equal(p1.alpha, p2.alpha)
    assert np.all((p1.alpha >= 0.0) & (p1.alpha <= 1.0))
    # The wet band must carry more cloud opacity than the dry band.
    a_eq = p1.alpha[np.abs(lat_rows) < 10].mean()
    a_sub = p1.alpha[(np.abs(lat_rows) > 20) & (np.abs(lat_rows) < 35)].mean()
    assert a_eq > a_sub


def test_globe_preview_day_night() -> None:
    h, w = 64, 128
    surface = np.full((h, w, 3), 0.4)
    clouds = np.full((h, w), 0.5)
    img = cr.render_globe_preview(
        surface,
        clouds,
        res=200,
        center_lon_deg=0.0,
        center_lat_deg=0.0,
        sun_lon_deg=0.0,
        sun_lat_deg=0.0,
    )
    assert img.shape == (200, 200, 3)
    assert img.dtype == np.uint8
    centre = img[100, 100].astype(float).mean()
    # Disk centre is sub-solar → bright; corners are space → black.
    corner = img[5, 5].astype(float).mean()
    assert centre > 80.0
    assert corner == 0.0
