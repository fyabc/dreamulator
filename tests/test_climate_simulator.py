"""Integration tests for climate simulation on a small CVT mesh.

Verifies end-to-end pipeline: CVT mesh → temperature → precipitation → Köppen.
Uses a small synthetic mesh (100 cells) for fast execution.
"""

import numpy as np
import pytest

from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import TerrainPipelineConfig


def _build_test_mesh(
    num_bands: int = 10,
    cells_per_band: int = 10,
) -> CVTMesh:
    """Build a small synthetic CVT mesh with realistic latitude/longitude layout.

    Cells are arranged in latitude bands (like a simplified Fibonacci sphere).
    Elevation is set to produce a simple Earth-like continent pattern:
      - Low latitudes: more land (tropical)
      - Mid latitudes: mixed
      - High latitudes: mostly ocean with a polar continent at ~-80°

    Returns:
        CVTMesh with elevation and adjacency set.
    """
    import math

    n = num_bands * cells_per_band
    cells: list[VoronoiCell] = []
    adjacency: dict[str, list[int]] = {}

    for band in range(num_bands):
        # Latitude: from +80° (north) to -80° (south)
        lat = 80.0 - band * 160.0 / (num_bands - 1) if num_bands > 1 else 0.0
        lat_rad = math.radians(lat)

        for j in range(cells_per_band):
            idx = band * cells_per_band + j
            lon = j * 360.0 / cells_per_band - 180.0
            lon_rad = math.radians(lon)

            # 3D coordinates on unit sphere
            cos_lat = math.cos(lat_rad)
            x = cos_lat * math.cos(lon_rad)
            y = math.sin(lat_rad)
            z = cos_lat * math.sin(lon_rad)

            # Simple continent pattern: land near equator and mid-latitudes
            abs_lat = abs(lat)
            if abs_lat < 20.0 and -80 < lon < 30:
                # Tropical continent (Africa-like)
                base_elev = 400.0
                crust = "continental"
            elif 30.0 < abs_lat < 55.0 and 0 < lon < 120:
                # Mid-latitude continent (Eurasia-like)
                base_elev = 300.0
                crust = "continental"
            elif abs_lat > 70.0 and -60 < lon < 60:
                # Polar continent (Antarctica-like)
                base_elev = 2000.0
                crust = "continental"
            elif abs_lat < 30.0 and -160 < lon < -100:
                # Island chain
                base_elev = 50.0
                crust = "continental"
            else:
                # Ocean
                base_elev = -3000.0
                crust = "oceanic"

            # Add some noise
            base_elev += (hash((band, j)) % 500) - 250

            # Neighbours in adjacent bands and same band
            neighbors: list[int] = []
            # Same band: east and west
            neighbors.append(band * cells_per_band + (j + 1) % cells_per_band)
            neighbors.append(band * cells_per_band + (j - 1) % cells_per_band)
            # North and south bands (if they exist)
            if band > 0:
                neighbors.append((band - 1) * cells_per_band + j)
            if band < num_bands - 1:
                neighbors.append((band + 1) * cells_per_band + j)

            cell = VoronoiCell(
                id=idx,
                lon=lon,
                lat=lat,
                x=x,
                y=y,
                z=z,
                area_km2=510_000_000 / n,  # ~Earth surface area / n
                elevation=base_elev,
                crust_type=crust,
                neighbors=neighbors,
                plate_id=f"plate_{band % 3}",
            )
            cells.append(cell)
            adjacency[str(idx)] = neighbors

    return CVTMesh(
        seed=42,
        num_cells=n,
        cells=cells,
        adjacency=adjacency,
    )


class TestClimateSimulatorEndToEnd:
    """End-to-end climate simulation on a synthetic 100-cell mesh."""

    @pytest.fixture
    def config(self) -> TerrainPipelineConfig:
        """Earth-like climate configuration."""
        return TerrainPipelineConfig(
            seed=42,
            radius_km=6371.0,
            rotation_period_days=1.0,
            stellar_luminosity_sol=1.0,
            orbital_distance_au=1.0,
            axial_tilt_deg=23.44,
            greenhouse_warming_K=33.0,
            lat_gradient_c=45.0,
            lapse_rate_c_km=6.5,
            evaporation_base_mm=2000.0,
            orographic_efficiency=0.5,
            wind_blocking_height_m=3000.0,
            itcz_lag_days=30,
            num_nodes=100,
        )

    @pytest.fixture
    def mesh(self) -> CVTMesh:
        """Synthetic 100-cell CVT mesh."""
        return _build_test_mesh(num_bands=10, cells_per_band=10)

    def test_simulate_populates_cells(self, mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
        """Climate simulation should populate temperature, precipitation, Köppen."""
        from dreamulator.map.climate_simulator import simulate_climate

        simulate_climate(mesh, config)

        n_populated = 0
        for c in mesh.cells:
            if c.temperature_C is not None:
                n_populated += 1
                assert isinstance(c.temperature_C, float)
                assert isinstance(c.precipitation_mm, float)
                assert isinstance(c.koppen_class, str)
                assert len(c.koppen_class) >= 2  # at least 2-char code

        assert n_populated == mesh.num_cells, (
            f"Expected all {mesh.num_cells} cells populated, got {n_populated}"
        )

    def test_temperature_physically_plausible(
        self, mesh: CVTMesh, config: TerrainPipelineConfig
    ) -> None:
        """Temperature range should be physically plausible for Earth-like planet."""
        from dreamulator.map.climate_simulator import simulate_climate

        simulate_climate(mesh, config)

        temps = [c.temperature_C for c in mesh.cells if c.temperature_C is not None]
        assert len(temps) == mesh.num_cells

        # Earth range: roughly -50 to +40 °C
        t_min, t_max = min(temps), max(temps)
        assert t_min > -80.0, f"Temperatures implausibly cold: min {t_min:.1f} °C"
        assert t_max < 55.0, f"Temperatures implausibly hot: max {t_max:.1f} °C"

    def test_equator_warmer_than_poles(self, mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
        """Equatorial cells should be warmer than polar cells."""
        from dreamulator.map.climate_simulator import simulate_climate

        simulate_climate(mesh, config)

        equatorial = [c for c in mesh.cells if abs(c.lat) < 15.0]
        polar = [c for c in mesh.cells if abs(c.lat) > 60.0]

        eq_mean = np.mean([c.temperature_C for c in equatorial if c.temperature_C is not None])  # type: ignore[arg-type]
        pol_mean = np.mean([c.temperature_C for c in polar if c.temperature_C is not None])  # type: ignore[arg-type]

        assert eq_mean > pol_mean, (
            f"Expected equator ({eq_mean:.1f} °C) warmer than poles ({pol_mean:.1f} °C)"
        )

    def test_high_altitude_colder(self, mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
        """High-elevation cells should be colder than nearby low-elevation cells."""
        from dreamulator.map.climate_simulator import simulate_climate

        simulate_climate(mesh, config)

        # Compare each cell with its neighbors
        colder_count = 0
        total_comparisons = 0
        for c in mesh.cells:
            if c.temperature_C is None:
                continue
            for n_id in c.neighbors:
                if n_id < 0 or n_id >= mesh.num_cells:
                    continue
                n_cell = mesh.cells[n_id]
                if n_cell.temperature_C is None:
                    continue
                # Higher elevation should be colder (within ±5° latitude to control for lat gradient)
                if abs(c.lat - n_cell.lat) < 5.0:
                    total_comparisons += 1
                    elev_diff = c.elevation - n_cell.elevation
                    temp_diff = n_cell.temperature_C - c.temperature_C  # type: ignore[operator]
                    if (
                        elev_diff > 200.0
                        and temp_diff > 0.3
                        or elev_diff < -200.0
                        and temp_diff < -0.3
                    ):
                        colder_count += 1

        # With a small synthetic mesh (100 cells, ±250m elevation noise),
        # the altitude signal is weak relative to latitude. Use a lenient threshold.
        if total_comparisons > 0:
            ratio = colder_count / total_comparisons
            assert ratio > 0.15, (
                f"Altitude gradient inconsistent: {colder_count}/{total_comparisons} ({ratio:.1%})"
            )

    def test_precipitation_non_negative(self, mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
        """Precipitation should be non-negative everywhere."""
        from dreamulator.map.climate_simulator import simulate_climate

        simulate_climate(mesh, config)

        for c in mesh.cells:
            assert c.precipitation_mm is not None
            assert c.precipitation_mm >= 0.0, (
                f"Negative precipitation at cell {c.id}: {c.precipitation_mm}"
            )

    def test_koppen_classes_include_ocean(
        self, mesh: CVTMesh, config: TerrainPipelineConfig
    ) -> None:
        """Ocean cells should be classified as 'Ocean'."""
        from dreamulator.map.climate_simulator import simulate_climate

        simulate_climate(mesh, config)

        for c in mesh.cells:
            if c.elevation < 0.0:
                assert c.koppen_class == "Ocean", (
                    f"Ocean cell {c.id} got Köppen class '{c.koppen_class}'"
                )

    def test_koppen_classes_on_land(self, mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
        """All land cells should have a valid Köppen code."""
        from dreamulator.map.climate_simulator import simulate_climate

        simulate_climate(mesh, config)

        valid_prefixes = {"A", "B", "C", "D", "E"}
        land_with_class = 0
        for c in mesh.cells:
            if c.elevation >= 0.0 and c.koppen_class:
                land_with_class += 1
                assert c.koppen_class[0] in valid_prefixes, (
                    f"Invalid Köppen code '{c.koppen_class}' at cell {c.id}"
                )

        # At least some land cells should have classifications
        assert land_with_class > 0, "No land cells received Köppen classification"

    def test_deterministic_output(self, mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
        """Same input → same output (no RNG dependence)."""
        from dreamulator.map.climate_simulator import simulate_climate

        # Run twice on identical inputs
        mesh1 = _build_test_mesh(num_bands=10, cells_per_band=10)
        mesh2 = _build_test_mesh(num_bands=10, cells_per_band=10)

        simulate_climate(mesh1, config)
        simulate_climate(mesh2, config)

        for i in range(mesh1.num_cells):
            assert mesh1.cells[i].temperature_C == pytest.approx(
                mesh2.cells[i].temperature_C, abs=1e-6
            ), (  # type: ignore[arg-type]
                f"Non-deterministic temperature at cell {i}"
            )
            assert mesh1.cells[i].precipitation_mm == pytest.approx(
                mesh2.cells[i].precipitation_mm, abs=1e-6
            ), (  # type: ignore[arg-type]
                f"Non-deterministic precipitation at cell {i}"
            )

    def test_export_equirectangular_climate_fields(
        self, mesh: CVTMesh, config: TerrainPipelineConfig, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Climate raster export should produce valid PNG files."""
        from dreamulator.map.climate_simulator import simulate_climate
        from dreamulator.map.export import (
            _climate_data_available,
            export_climate_layers,
            export_equirectangular,
        )

        simulate_climate(mesh, config)
        assert _climate_data_available(mesh)

        output_dir = tmp_path_factory.mktemp("climate_output")

        # Set export resolution
        config.export_width = 180
        config.export_height = 90

        export_climate_layers(mesh, output_dir, config)

        # Check files exist
        assert (output_dir / "temperature.png").exists()
        assert (output_dir / "precipitation.png").exists()
        assert (output_dir / "koppen.json").exists()
        assert (output_dir / "climate_metadata.json").exists()

        # Check temperature PNG is valid
        from PIL import Image

        temp_img = Image.open(output_dir / "temperature.png")
        assert temp_img.size == (180, 90)
        assert temp_img.mode == "I;16"

        # Verify the grids have plausible data
        temp_grid = export_equirectangular(mesh, 180, 90, field="temperature_C")
        assert temp_grid.shape == (90, 180)
        assert np.all(np.isfinite(temp_grid))

        # No NaN in output
        assert not np.any(np.isnan(temp_grid))
