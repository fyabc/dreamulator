"""Tests for the CVT terrain generation pipeline."""

from __future__ import annotations

import math

import numpy as np
import pytest

from dreamulator.map.cvt_mesh import (
    build_adjacency_graph,
    fibonacci_sphere,
    generate_cvt_mesh,
    jitter_points,
    lloyd_relaxation,
)
from dreamulator.map.models import CVTMesh, EulerPole, VoronoiCell
from dreamulator.map.pipeline_types import (
    TerrainPipelineConfig,
    lonlat_to_xyz,
    smooth_step,
    xyz_to_lonlat,
)
from dreamulator.map.plate_generator import (
    assign_crust_types,
    flood_fill_plates,
    generate_plates,
    select_plate_seeds,
)


# ---------------------------------------------------------------------------
# Coordinate utilities
# ---------------------------------------------------------------------------


class TestCoordinateConversion:
    def test_lonlat_to_xyz_origin(self):
        """(0°, 0°) should map to (1, 0, 0)."""
        x, y, z = lonlat_to_xyz(0.0, 0.0)
        assert abs(x - 1.0) < 1e-10
        assert abs(y) < 1e-10
        assert abs(z) < 1e-10

    def test_lonlat_to_xyz_north_pole(self):
        """(any, 90°) should map to (0, 1, 0)."""
        x, y, z = lonlat_to_xyz(42.0, 90.0)
        assert abs(x) < 1e-10
        assert abs(y - 1.0) < 1e-10
        assert abs(z) < 1e-10

    def test_xyz_roundtrip(self):
        """lonlat → xyz → lonlat should be identity."""
        for lon in [-180, -90, 0, 45, 90, 135, 180]:
            for lat in [-90, -45, 0, 30, 60, 90]:
                x, y, z = lonlat_to_xyz(float(lon), float(lat))
                lon2, lat2 = xyz_to_lonlat(x, y, z)
                assert abs(lon2 - lon) < 0.01, f"lon mismatch at ({lon}, {lat})"
                assert abs(lat2 - lat) < 0.01, f"lat mismatch at ({lon}, {lat})"

    def test_smooth_step(self):
        """smooth_step should be 0 at edge0 and 1 at edge1."""
        assert abs(smooth_step(np.array([0.0]))[0]) < 1e-10
        assert abs(smooth_step(np.array([1.0]))[0] - 1.0) < 1e-10
        assert abs(smooth_step(np.array([0.5]))[0] - 0.5) < 1e-10


# ---------------------------------------------------------------------------
# CVT mesh generation
# ---------------------------------------------------------------------------


class TestFibonacciSphere:
    def test_correct_count(self):
        """Should generate exactly N points."""
        for n in [10, 100, 1000]:
            pts = fibonacci_sphere(n)
            assert pts.shape == (n, 3)

    def test_unit_sphere(self):
        """All points should be on the unit sphere."""
        pts = fibonacci_sphere(500)
        norms = np.linalg.norm(pts, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-10)

    def test_uniformity(self):
        """Points should be approximately uniformly distributed."""
        pts = fibonacci_sphere(1000)
        # Check that y-coordinates span [-1, 1] evenly
        y_sorted = np.sort(pts[:, 1])
        expected = np.linspace(-1, 1, 1000)
        # Max deviation should be small
        max_dev = np.max(np.abs(y_sorted - expected))
        assert max_dev < 0.05, f"y-distribution max deviation: {max_dev}"


class TestJitter:
    def test_no_jitter(self):
        """sigma=0 should return unchanged points."""
        pts = fibonacci_sphere(100)
        rng = np.random.default_rng(42)
        jittered = jitter_points(pts, 0.0, rng)
        np.testing.assert_array_equal(pts, jittered)

    def test_stays_on_sphere(self):
        """Jittered points should remain on unit sphere."""
        pts = fibonacci_sphere(100)
        rng = np.random.default_rng(42)
        jittered = jitter_points(pts, 0.5, rng)
        norms = np.linalg.norm(jittered, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-10)


class TestLloydRelaxation:
    def test_stays_on_sphere(self):
        """Relaxed points should remain on unit sphere."""
        pts = fibonacci_sphere(100)
        relaxed = lloyd_relaxation(pts, 2)
        norms = np.linalg.norm(relaxed, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-10)

    def test_converges(self):
        """Multiple iterations should converge (points change less)."""
        pts = fibonacci_sphere(100)
        rng = np.random.default_rng(42)
        pts = jitter_points(pts, 0.5, rng)

        relaxed_1 = lloyd_relaxation(pts, 1)
        relaxed_5 = lloyd_relaxation(pts, 5)

        # After 5 iterations, points should be more uniform
        # (measured by variance of nearest-neighbor distances)
        from scipy.spatial import SphericalVoronoi

        sv_1 = SphericalVoronoi(relaxed_1, radius=1.0, center=np.zeros(3))
        sv_5 = SphericalVoronoi(relaxed_5, radius=1.0, center=np.zeros(3))

        # Area variance should decrease with more relaxation
        def area_variance(sv):
            areas = []
            for region in sv.regions:
                if region and -1 not in region:
                    verts = sv.vertices[region]
                    # Solid angle approximation
                    centroid = verts.mean(axis=0)
                    centroid /= np.linalg.norm(centroid)
                    dists = [np.linalg.norm(v - centroid) for v in verts]
                    areas.append(np.mean(dists))
            return np.var(areas)

        var_1 = area_variance(sv_1)
        var_5 = area_variance(sv_5)
        assert var_5 <= var_1, f"Relaxation didn't improve uniformity: {var_5} > {var_1}"


class TestGenerateCvtMesh:
    def test_basic_generation(self):
        """Full mesh generation should work."""
        cfg = TerrainPipelineConfig(num_nodes=200, seed=42, lloyd_iterations=2)
        mesh = generate_cvt_mesh(cfg)

        assert mesh.num_cells == 200
        assert len(mesh.cells) == 200
        assert len(mesh.vertices) > 0
        assert len(mesh.regions) == 200
        assert len(mesh.adjacency) == 200

    def test_euler_formula(self):
        """V - E + F = 2 for a sphere (Euler characteristic)."""
        cfg = TerrainPipelineConfig(num_nodes=500, seed=42, lloyd_iterations=2)
        mesh = generate_cvt_mesh(cfg)

        V = len(mesh.vertices)
        F = mesh.num_cells  # faces = cells
        E = sum(len(v) for v in mesh.adjacency.values()) // 2  # edges from adjacency

        euler = V - E + F
        assert euler == 2, f"Euler characteristic: V={V} - E={E} + F={F} = {euler} (expected 2)"

    def test_area_conservation(self):
        """Total cell area should equal sphere surface area."""
        cfg = TerrainPipelineConfig(num_nodes=500, seed=42, lloyd_iterations=2)
        mesh = generate_cvt_mesh(cfg)

        total_area = sum(c.area_km2 for c in mesh.cells)
        expected = 4 * math.pi * cfg.radius_km**2
        error_pct = abs(total_area - expected) / expected * 100
        assert error_pct < 1.0, f"Area error: {error_pct:.2f}%"

    def test_deterministic(self):
        """Same seed should produce same output."""
        cfg = TerrainPipelineConfig(num_nodes=100, seed=42, lloyd_iterations=2)
        mesh1 = generate_cvt_mesh(cfg)
        mesh2 = generate_cvt_mesh(cfg)

        for c1, c2 in zip(mesh1.cells, mesh2.cells):
            assert c1.lon == c2.lon
            assert c1.lat == c2.lat
            assert c1.x == c2.x


# ---------------------------------------------------------------------------
# Plate generation
# ---------------------------------------------------------------------------


class TestPlateGeneration:
    @pytest.fixture
    def small_mesh(self):
        cfg = TerrainPipelineConfig(num_nodes=200, seed=42, lloyd_iterations=2)
        return generate_cvt_mesh(cfg)

    def test_seed_selection(self, small_mesh):
        """Should select the requested number of seeds."""
        rng = np.random.default_rng(42)
        seeds = select_plate_seeds(small_mesh, 8, rng)
        assert len(seeds) == 8
        assert len(set(seeds)) == 8  # all unique

    def test_flood_fill_completeness(self, small_mesh):
        """All cells should be assigned to a plate."""
        rng = np.random.default_rng(42)
        seeds = select_plate_seeds(small_mesh, 8, rng)
        cell_plate_map = flood_fill_plates(small_mesh, seeds, rng)
        assert len(cell_plate_map) == small_mesh.num_cells

    def test_generate_plates(self, small_mesh):
        """Full plate generation should work."""
        cfg = TerrainPipelineConfig(num_nodes=200, seed=42, num_plates=8)
        plates, cell_plate_map = generate_plates(small_mesh, cfg)

        assert len(plates) == 8
        assert len(cell_plate_map) == 200

        # All cells should have a plate_id
        for cell in small_mesh.cells:
            assert cell.plate_id is not None

        # All plates should have Euler poles
        for plate in plates:
            assert plate.euler_pole is not None
            norm = math.sqrt(
                plate.euler_pole.x**2
                + plate.euler_pole.y**2
                + plate.euler_pole.z**2
            )
            assert abs(norm - 1.0) < 0.01, f"Euler pole not unit vector: norm={norm}"


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestTerrainPipeline:
    def test_full_pipeline(self):
        """End-to-end pipeline should produce valid output."""
        from dreamulator.map.terrain_pipeline import run_terrain_pipeline

        cfg = TerrainPipelineConfig(
            num_nodes=300,
            seed=42,
            lloyd_iterations=2,
            num_plates=6,
            export_width=128,
            export_height=64,
        )

        result = run_terrain_pipeline(cfg)

        # Mesh
        assert result.mesh is not None
        assert result.mesh.num_cells == 300

        # Plates
        assert len(result.plates) == 6

        # Boundaries
        assert len(result.boundary_cell_ids) > 0

        # Elevation grid
        assert result.elevation_grid is not None
        assert result.elevation_grid.shape == (64, 128)

        # Elevation range should be reasonable
        assert result.elevation_grid.min() < 0  # has ocean
        assert result.elevation_grid.max() > 0  # has land

        # Stages
        assert "mesh" in result.stages_completed
        assert "plates" in result.stages_completed
        assert "terrain" in result.stages_completed
        assert "export" in result.stages_completed
        # climate, rivers, erosion should be skipped
        assert "climate" not in result.stages_completed

    def test_partial_stages(self):
        """Should be able to run only specific stages."""
        from dreamulator.map.terrain_pipeline import run_terrain_pipeline

        cfg = TerrainPipelineConfig(num_nodes=100, seed=42, lloyd_iterations=1)

        # Only mesh
        result = run_terrain_pipeline(cfg, stages=["mesh"])
        assert result.mesh is not None
        assert result.stages_completed == ["mesh"]
        assert result.plates == []

    def test_determinism(self):
        """Same config should produce identical results."""
        from dreamulator.map.terrain_pipeline import run_terrain_pipeline

        cfg = TerrainPipelineConfig(
            num_nodes=100, seed=99, lloyd_iterations=1, num_plates=4,
            export_width=64, export_height=32,
        )

        r1 = run_terrain_pipeline(cfg)
        r2 = run_terrain_pipeline(cfg)

        np.testing.assert_array_equal(r1.elevation_grid, r2.elevation_grid)
