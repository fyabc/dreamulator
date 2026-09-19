"""Integration tests for climate simulation on a small CVT mesh.

Verifies end-to-end pipeline: CVT mesh → temperature → precipitation → Köppen.
Uses a small synthetic mesh (100 cells) for fast execution.
"""

import numpy as np
import pytest

from dreamulator.engine.climate_physics import _PICKUP_GATE_F_MIN
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


def test_upwind_distance_traces_west_ocean_for_westerly_wind() -> None:
    """A physical westerly wind traces a land cell's upwind ocean to its WEST.

    Regression test for the 4.1-B wind sign convention: since the tech-debt-24
    root unification (2026-09-13) ``hadley_cell_wind`` composes on the
    physical east basis (``east_north_basis``, = direction of increasing
    longitude); ``_upwind_distance_to_coast`` consumes it directly — a
    mirrored feed would trace to the downwind ocean instead.
    """
    from dreamulator.map.climate_simulator import _upwind_distance_to_coast
    from dreamulator.map.ocean_circulation import east_north_basis

    # A single latitude band at the equator, 8 cells spanning 360° lon.
    mesh = _build_test_mesh(num_bands=1, cells_per_band=8)
    n = mesh.num_cells
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    east, _ = east_north_basis(nodes_xyz)

    # Land only at lon ≈ 0°; ocean everywhere else on the band.
    is_land = np.array([abs(c.lon) < 1.0 for c in mesh.cells], dtype=bool)
    # Physical westerly wind: blow toward increasing longitude (east).
    wind = east * 5.0

    dist, src = _upwind_distance_to_coast(mesh.cells, n, is_land, wind, nodes_xyz, radius_km=6371.0)
    land_i = int(np.flatnonzero(is_land)[0])
    assert src[land_i] >= 0 and np.isfinite(dist[land_i])
    # The source is the ocean to the west (lon < 0), not the east.
    assert mesh.cells[src[land_i]].lon < 0.0


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
            evaporation_base_mm=1000.0,
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
                # Annual pressure anomaly (M2-A0③): every built world carries
                # it — the frontend's annual pressure layer reads this field.
                assert c.pressure_anomaly_annual_hpa is not None
                assert -60.0 < c.pressure_anomaly_annual_hpa < 60.0

        assert n_populated == mesh.num_cells, (
            f"Expected all {mesh.num_cells} cells populated, got {n_populated}"
        )

    def test_hadley_derive_path_does_not_crash(self, mesh: CVTMesh) -> None:
        """``hadley_extent_deg=0`` (derive) with subsidence warming must not crash.

        Regression for the ZeroDivisionError where the subsidence-warming block
        read the raw ``config.hadley_extent_deg`` (0.0) instead of the resolved
        (derived) extent, producing an empty cell mask and an empty ``np.average``.
        """
        from dreamulator.map.climate_simulator import simulate_climate

        config = TerrainPipelineConfig(
            seed=42,
            radius_km=6371.0,
            rotation_period_days=1.0,
            stellar_luminosity_sol=1.0,
            orbital_distance_au=1.0,
            axial_tilt_deg=23.44,
            greenhouse_warming_K=33.0,
            ebm_1d=True,  # the subsidence-warming block lives on the EBM branch
            hadley_extent_deg=0.0,  # derive via Held-Hou instead of a pin
            subsidence_warming_c=1.0,
            num_nodes=100,
        )
        simulate_climate(mesh, config)
        assert all(c.temperature_C is not None for c in mesh.cells)

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

        # Compare each cell with its neighbors: over pairs with a real
        # elevation contrast (> 200 m, within ±5° latitude to control for
        # the lat gradient) the regression of ΔT on Δelevation must have a
        # negative slope — higher is colder on average.  (A pair-count
        # ratio was used before; on this 100-cell synthetic mesh it
        # measured noise around a near-zero slope and sat at the threshold.)
        elev_diffs: list[float] = []
        temp_diffs: list[float] = []
        for c in mesh.cells:
            if c.temperature_C is None:
                continue
            for n_id in c.neighbors:
                if n_id < 0 or n_id >= mesh.num_cells:
                    continue
                n_cell = mesh.cells[n_id]
                if n_cell.temperature_C is None:
                    continue
                if abs(c.lat - n_cell.lat) < 5.0 and abs(c.elevation - n_cell.elevation) > 200.0:
                    elev_diffs.append(c.elevation - n_cell.elevation)
                    temp_diffs.append(n_cell.temperature_C - c.temperature_C)  # type: ignore[operator]
        assert len(elev_diffs) >= 20
        slope = np.polyfit(np.array(elev_diffs), np.array(temp_diffs), 1)[0]
        assert slope < -3.0e-4, f"Altitude gradient inconsistent: slope {slope * 1000:.2f} K/km"

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


class TestColdTrap:
    """The cold-trap saturation cap W ≤ W_sat with upwind routing (CLIM-02 slice 2)."""

    @staticmethod
    def _no_edges(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Degenerate edge set (no inflow) for pure-cap behaviour."""
        return (
            np.zeros(0, dtype=bool),
            np.zeros(0, dtype=np.int64),
            np.zeros(0, dtype=np.int64),
            np.zeros(0, dtype=np.float64),
        )

    def test_caps_column_water(self) -> None:
        """Column water above W_sat is capped; warm columns are untouched."""
        from dreamulator.map.climate_simulator import _apply_cold_trap

        w = np.array([25.0, 3.0, 0.2])
        w_sat = np.array([1e9, 1.0, 0.5])
        k_rain_field = np.array([40.6, 40.6, 40.6])
        neg, src, dst, c_in = self._no_edges(3)
        w_capped, p = _apply_cold_trap(w, w_sat, k_rain_field, neg, src, dst, c_in)

        assert np.all(w_capped <= w_sat + 1e-9)
        assert w_capped[0] == pytest.approx(25.0)  # warm → untouched
        assert w_capped[1] == pytest.approx(1.0)  # cold → capped
        assert w_capped[2] == pytest.approx(0.2)  # already below → untouched
        # No inflow edges: the capped cell keeps its own excess rain.
        assert p[1] == pytest.approx(3.0 * 40.6)

    def test_no_op_when_unsaturated(self) -> None:
        """No cells near saturation → identical to the input."""
        from dreamulator.map.climate_simulator import _apply_cold_trap

        w = np.array([20.0, 15.0, 10.0, 5.0])
        w_sat = np.full(4, 1e9)
        k_rain_field = np.full(4, 40.6)
        neg, src, dst, c_in = self._no_edges(4)
        w_capped, p = _apply_cold_trap(w, w_sat, k_rain_field, neg, src, dst, c_in)

        assert np.allclose(w_capped, w)
        assert np.allclose(p, w * k_rain_field)

    def test_excess_rains_upwind(self) -> None:
        """The capped rainout rains at the (warm) inflow source, not the cold cell.

        Two cells: warm source 0 → cold overshooting cell 1 (one inflow edge,
        directed 1→0 with c<0).  Cell 1's column is capped at W_sat and its
        excess rainout k·(W−W_sat) appears as cell 0's precipitation —
        ΣP is exactly the unconstrained Σ k·W (conservation survives the cap).
        """
        from dreamulator.map.climate_simulator import _apply_cold_trap

        k = 40.6
        w = np.array([10.0, 6.0])
        w_sat = np.array([1e9, 2.0])
        k_rain_field = np.full(2, k)
        # One directed edge (src=1 → dst=0) with c<0: air flows 0 → 1.
        neg = np.array([True])
        src = np.array([1])
        dst = np.array([0])
        c_in = np.array([-5.0])

        w_capped, p = _apply_cold_trap(w, w_sat, k_rain_field, neg, src, dst, c_in)

        assert w_capped[1] == pytest.approx(2.0)  # capped
        assert p[1] == pytest.approx(2.0 * k)  # cold cell rains only its capped column
        excess = (6.0 - 2.0) * k
        assert p[0] == pytest.approx(10.0 * k + excess)  # excess rained upwind
        # Global conservation: ΣP == Σ k·W_unconstrained.
        assert p.sum() == pytest.approx(k * w.sum(), rel=1e-12)

    def test_excess_split_by_inflow_share(self) -> None:
        """Two inflow edges split the routed excess ∝ their arriving *flux*
        (|c|·W_source — the edge with 3× |c| from a wetter source carries
        30 vs 8 of flux, so shares are 30/38 and 8/38)."""
        from dreamulator.map.climate_simulator import _apply_cold_trap

        k = 40.6
        w = np.array([10.0, 8.0, 6.0])
        w_sat = np.array([1e9, 1e9, 2.0])  # only cell 2 overshoots
        k_rain_field = np.full(3, k)
        # Two inflow edges into cell 2 (directed 2→0 and 2→1, c<0).
        neg = np.array([True, True])
        src = np.array([2, 2])
        dst = np.array([0, 1])
        c_in = np.array([-3.0, -1.0])

        _, p = _apply_cold_trap(w, w_sat, k_rain_field, neg, src, dst, c_in)

        excess = (6.0 - 2.0) * k
        f0, f1 = 3.0 * 10.0, 1.0 * 8.0  # arriving fluxes |c|·W_source
        assert p[0] == pytest.approx(10.0 * k + excess * f0 / (f0 + f1))
        assert p[1] == pytest.approx(8.0 * k + excess * f1 / (f0 + f1))
        assert p.sum() == pytest.approx(k * w.sum(), rel=1e-12)


# ---------------------------------------------------------------------------
# Wind convention: mirror → physical flip in the precipitation stage
# (2026-09-12 mirror-bug fix; tech debt 24)
# ---------------------------------------------------------------------------


def _build_lat_band_mesh(lat_deg: float, n_cells: int = 24) -> CVTMesh:
    """Single latitude band of cells around the globe (1-D ring adjacency)."""
    import math

    cells: list[VoronoiCell] = []
    adjacency: dict[str, list[int]] = {}
    lat_rad = math.radians(lat_deg)
    for j in range(n_cells):
        lon = j * 360.0 / n_cells - 180.0
        lon_rad = math.radians(lon)
        neighbors = [(j + 1) % n_cells, (j - 1) % n_cells]
        cells.append(
            VoronoiCell(
                id=j,
                lon=lon,
                lat=lat_deg,
                x=math.cos(lat_rad) * math.cos(lon_rad),
                y=math.sin(lat_rad),
                z=math.cos(lat_rad) * math.sin(lon_rad),
                area_km2=510_000_000 / n_cells,
                elevation=-3000.0,
                crust_type="oceanic",
                neighbors=neighbors,
                plate_id="plate_0",
            )
        )
        adjacency[str(j)] = neighbors
    return CVTMesh(seed=42, num_cells=n_cells, cells=cells, adjacency=adjacency)


def test_annual_wind_is_vector_mean_of_monthly() -> None:
    """B0a data contract: the stored annual wind is the vector mean of the
    monthly fields (observational definition — NCEP annual climatology).

    The identity must hold *by construction*, also with a non-zero monsoon
    anomaly: the annual field is derived from the monthly one, not stored
    from an independent composition path.
    """
    from dreamulator.map.climate_simulator import simulate_climate

    mesh = _build_lat_band_mesh(30.0, 24)
    # Every 3rd cell becomes low land → land-sea heating contrast drives a
    # non-zero monsoon anomaly in the monthly fields.
    for j, c in enumerate(mesh.cells):
        if j % 3 == 0:
            c.elevation = 50.0
            c.crust_type = "continental"
            c.water_class = "land"
        else:
            c.water_class = "ocean"
    simulate_climate(mesh, TerrainPipelineConfig())

    we_ann = np.array([c.wind_east_m_s for c in mesh.cells])
    wn_ann = np.array([c.wind_north_m_s for c in mesh.cells])
    we_m = np.asarray(mesh._wind_east_monthly, dtype=np.float64)  # (N, 12) float32
    wn_m = np.asarray(mesh._wind_north_monthly, dtype=np.float64)
    # A non-trivial anomaly actually exercised the identity:
    assert np.abs(we_m - we_m.mean(axis=1, keepdims=True)).max() > 1e-6
    np.testing.assert_allclose(we_ann, we_m.mean(axis=1), atol=2e-4)
    np.testing.assert_allclose(wn_ann, wn_m.mean(axis=1), atol=2e-4)


def test_annual_temperature_is_mean_of_monthly() -> None:
    """Single-authority contract (slice 6): temperature_C is *derived* as
    ⟨t_monthly⟩, and t_hot/t_cold are the monthly extremes.

    The seasonal EBM alone has no elevation dimension — before the B0c
    handoff, highland cells' monthly series sat ~19 °C above the
    lapse-corrected annual field (Andes 4 km), poisoning Köppen via t_hot.
    """
    from dreamulator.map.climate_simulator import simulate_climate

    mesh = _build_lat_band_mesh(45.0, 24)
    highland = np.zeros(len(mesh.cells), dtype=bool)
    for j, c in enumerate(mesh.cells):
        if j % 3 == 0:
            c.elevation = 2500.0  # highland: exercises the lapse vs EBM gap
            c.crust_type = "continental"
            c.water_class = "land"
            highland[j] = True
        else:
            c.water_class = "ocean"
    simulate_climate(mesh, TerrainPipelineConfig())

    t_m = np.asarray(mesh._t_monthly_c, dtype=np.float64)  # (N, 12) float32
    t_ann = np.array([c.temperature_C for c in mesh.cells])
    t_hot = np.array([c.temperature_hottest_month_C for c in mesh.cells])
    t_cold = np.array([c.temperature_coldest_month_C for c in mesh.cells])
    np.testing.assert_allclose(t_ann, t_m.mean(axis=1), atol=1e-3)
    np.testing.assert_allclose(t_hot, t_m.max(axis=1), atol=1e-3)
    np.testing.assert_allclose(t_cold, t_m.min(axis=1), atol=1e-3)
    # Highland cells actually carry the lapse-corrected (much colder) level.
    assert t_ann[highland].mean() < t_ann[~highland].mean() - 8.0


class TestWindConventionPrecipitation:
    """Sign anchors for the physical wind convention in the precipitation stage.

    Since the tech-debt-24 root unification (2026-09-13) ``hadley_cell_wind``
    and the monsoon module compose on the *physical* east basis
    (``east_north_basis`` = direction of increasing longitude, NCEP-verified)
    and the precipitation stage consumes it directly — the 2026-09-12 entry
    flip is retired (``_to_physical_wind`` survives only to feed the
    mirror-calibrated ocean chain).  These tests fail if the convention
    regresses — the mirror bug advected moisture E-W reversed (Earth's top-3
    per-cell P biases + nacrea east-coast deserts).
    """

    def test_to_physical_wind_flips_east_keeps_north(self) -> None:
        from dreamulator.map.climate_simulator import _to_physical_wind
        from dreamulator.map.ocean_circulation import east_north_basis

        mesh = _build_lat_band_mesh(45.0, 8)
        nodes = np.array([[c.x, c.y, c.z] for c in mesh.cells])
        east, north = east_north_basis(nodes)
        # Internal mirror encoding of a physical (5 m/s east, 2 m/s north) wind.
        internal = 5.0 * (-east) + 2.0 * north
        phys = _to_physical_wind(internal, east)
        np.testing.assert_allclose(np.einsum("ij,ij->i", phys, east), 5.0, atol=1e-12)
        np.testing.assert_allclose(np.einsum("ij,ij->i", phys, north), 2.0, atol=1e-12)
        # (M, N, 3) monthly stacking must broadcast.
        phys_m = _to_physical_wind(np.stack([internal] * 3), east)
        np.testing.assert_allclose(phys_m, np.stack([phys] * 3), atol=1e-12)

    def test_solver_advects_moisture_downwind(self) -> None:
        """Solver contract: a physical eastward wind carries W eastward."""
        from dreamulator.map.climate_simulator import _solve_moisture_budget
        from dreamulator.map.ocean_circulation import east_north_basis

        mesh = _build_lat_band_mesh(0.0, 24)
        n = mesh.num_cells
        nodes = np.array([[c.x, c.y, c.z] for c in mesh.cells])
        east, _ = east_north_basis(nodes)
        # Ocean (the only moisture source) at lon ∈ [-75, -15]; land elsewhere
        # with zero ET → any W there is advected or diffused.
        is_ocean = np.array([-75.0 <= c.lon <= -15.0 for c in mesh.cells])
        wind = east * 5.0  # physical eastward (westerly)
        w, _p = _solve_moisture_budget(
            mesh,
            wind,
            is_ocean,
            np.full(n, 20.0),
            nodes,
            TerrainPipelineConfig(),
            land_evapotranspiration=np.zeros(n),
        )
        lons = np.array([c.lon for c in mesh.cells])
        east_plume = w[(lons >= 0.0) & (lons <= 45.0)].mean()  # downwind of source
        west_side = w[(lons >= -165.0) & (lons <= -90.0)].mean()  # upwind, no source
        assert east_plume > 2.0 * max(west_side, 1e-9), (east_plume, west_side)

    def test_west_coast_wetter_than_east_coast_under_westerlies(self) -> None:
        """Stage-level Patagonia anchor, fed exactly what the pipeline feeds.

        A mid-latitude continent (lon 0–75°) under the Ferrel-cell westerlies:
        the west coast is windward (long ocean fetch) and must be wetter than
        the east coast (downwind of the whole continent).  Pre-fix, the mirrored
        advection + inverted coast-asymmetry step made the EAST coast wetter.
        """
        from dreamulator.map.climate_simulator import (
            _compute_precipitation_monthly_budget,
            _seasonal_mean_cell_wind,
        )

        mesh = _build_lat_band_mesh(45.0, 24)
        n = mesh.num_cells
        nodes = np.array([[c.x, c.y, c.z] for c in mesh.cells])
        lat_rad = np.radians(np.array([c.lat for c in mesh.cells]))
        is_land = np.array([0.0 <= c.lon <= 75.0 for c in mesh.cells])
        is_ocean = ~is_land
        config = TerrainPipelineConfig()
        # Exactly what simulate_climate passes: the physical-convention
        # annual background (Ferrel westerlies at 45°N), no monsoon anomaly.
        wind = _seasonal_mean_cell_wind(
            lat_rad,
            nodes,
            config,
            None,
            hadley_extent_deg=30.0,
            polar_cell_start_deg=60.0,
        )
        wind_monthly = np.stack([wind] * 12)
        t = np.full(n, 15.0)
        p_ann, _p_m = _compute_precipitation_monthly_budget(
            mesh,
            wind,
            wind_monthly,
            is_land,
            is_ocean,
            t,
            np.stack([t] * 12, axis=1),
            nodes,
            config,
        )
        lons = np.array([c.lon for c in mesh.cells])
        west_coast = p_ann[(lons >= -1.0) & (lons <= 16.0)].mean()
        east_coast = p_ann[(lons >= 59.0) & (lons <= 76.0)].mean()
        assert west_coast > 1.2 * east_coast, (
            f"west coast {west_coast:.0f} mm vs east coast {east_coast:.0f} mm — "
            "moisture advection likely mirrored"
        )


class TestConvectivePickupGateWiring:
    """§5-β wiring: iterate-once pickup gate in the monthly moisture budget.

    The gate multiplies k_rain by f(W/W_sat) — a mass-conserving
    redistribution (sums are untouched up to the Budyko feedback), so the
    flag-on run must move precipitation from dry columns to moist ones
    instead of removing it.
    """

    @pytest.fixture
    def mesh(self) -> CVTMesh:
        """Synthetic 100-cell CVT mesh (same geometry as the end-to-end class)."""
        return _build_test_mesh(num_bands=10, cells_per_band=10)

    def _run(self, mesh: CVTMesh, gate: bool) -> dict[str, np.ndarray]:
        from dreamulator.map.climate_simulator import simulate_climate

        cfg = TerrainPipelineConfig(
            seed=42,
            radius_km=6371.0,
            rotation_period_days=1.0,
            stellar_luminosity_sol=1.0,
            orbital_distance_au=1.0,
            axial_tilt_deg=23.44,
            greenhouse_warming_K=33.0,
            lat_gradient_c=45.0,
            evaporation_base_mm=1000.0,
            num_nodes=100,
            convective_pickup_gate_enabled=gate,
        )
        debug: dict[str, np.ndarray] = {}
        simulate_climate(mesh, cfg, debug=debug)
        return debug

    def test_flag_off_deterministic_and_ungated(self, mesh: CVTMesh) -> None:
        """Two flag-off runs are bit-identical and store the calibration field."""
        d1 = self._run(mesh, False)
        d2 = self._run(mesh, False)
        assert np.array_equal(d1["moisture_budget"], d2["moisture_budget"])
        assert "w_column_annual" in d1
        assert "pickup_gate_annual" not in d1

    def test_gate_redistributes_rather_than_removes(self, mesh: CVTMesh) -> None:
        """Flag-on: bounded gate field, dry cells lose, global mean survives."""
        d_off = self._run(mesh, False)
        d_on = self._run(mesh, True)
        p_off = d_off["moisture_budget"]
        p_on = d_on["moisture_budget"]
        gate = d_on["pickup_gate_annual"]
        assert gate.min() >= _PICKUP_GATE_F_MIN - 1e-12
        assert gate.max() <= 1.0 + 1e-12
        assert "pickup_gate_monthly_mean" in d_on
        # Mass-conserving redistribution: the global mean survives (the Budyko
        # feedback shifts it only second-order).
        assert abs(p_on.mean() - p_off.mean()) < 0.15 * p_off.mean()
        # Wherever the gate bites, the local precipitation falls.
        bitten = gate < 0.95
        if bitten.any():
            assert p_on[bitten].mean() < p_off[bitten].mean()

    def test_gate_uses_monthly_columns(self, mesh: CVTMesh) -> None:
        """The monthly gate is not the annual gate pasted twelve times.

        The annual factor multiplies the twelve monthly factors element-wise;
        equality everywhere would mean the monthly solve ignored its own
        column water (the lagged/degenerate failure mode)."""
        d_on = self._run(mesh, True)
        g_ann = d_on["pickup_gate_annual"]
        g_mon = d_on["pickup_gate_monthly_mean"]
        if (g_ann < 0.99).any():
            assert not np.allclose(g_ann, g_mon)


class TestMonthlyAnnualConsistency:
    """CLIM-01 (2026-09-18) + slice 6: the monthly series is the single
    temperature authority — every Stage-2.5 ocean correction keeps
    ⟨t_monthly⟩ ≡ t_mean_C, and the exported annual field is the terminal
    aggregation of the monthly one (no re-centring)."""

    def test_monthly_mean_matches_annual(self) -> None:
        import numpy as np

        from dreamulator.map.climate_simulator import simulate_climate

        mesh = _build_test_mesh(num_bands=10, cells_per_band=10)
        config = TerrainPipelineConfig(
            seed=42,
            radius_km=6371.0,
            rotation_period_days=1.0,
            stellar_luminosity_sol=1.0,
            orbital_distance_au=1.0,
            axial_tilt_deg=23.44,
            greenhouse_warming_K=33.0,
            lat_gradient_c=45.0,
            lapse_rate_c_km=6.5,
            evaporation_base_mm=1000.0,
            wind_blocking_height_m=3000.0,
            itcz_lag_days=30,
            num_nodes=100,
            ocean_currents_enabled=True,
            ocean_upwelling_enabled=True,
        )
        simulate_climate(mesh, config)

        t_monthly = getattr(mesh, "_t_monthly_c", None)
        assert t_monthly is not None, "monthly temperature array not attached"
        t_annual = np.array([c.temperature_C for c in mesh.cells], dtype=np.float64)
        mean_monthly = np.asarray(t_monthly, dtype=np.float64).mean(axis=1)
        assert np.allclose(mean_monthly, t_annual, atol=0.05), (
            f"monthly mean drifted from annual by up to "
            f"{np.abs(mean_monthly - t_annual).max():.3f} °C"
        )

    def test_seasonal_lake_freeze_clamp_keeps_identity(self) -> None:
        """Slice 6: the lake 0 °C freeze clamp is applied *before* the
        terminal aggregation, so lake cells satisfy ⟨t_monthly⟩ ≡
        temperature_C exactly — the old re-centre-then-clamp order broke the
        identity on every lake cell whose winter engaged the clamp."""
        from dreamulator.map.climate_simulator import simulate_climate

        mesh = _build_lat_band_mesh(55.0, 24)
        lakes = np.zeros(len(mesh.cells), dtype=bool)
        for j, c in enumerate(mesh.cells):
            if j % 3 == 0:
                c.elevation = -50.0
                c.crust_type = "oceanic"
                c.water_class = "ocean"
                c.is_lake = True
                lakes[j] = True
            else:
                c.elevation = 200.0
                c.crust_type = "continental"
                c.water_class = "land"
        simulate_climate(mesh, TerrainPipelineConfig())

        t_m = np.asarray(mesh._t_monthly_c, dtype=np.float64)  # (N, 12) float32
        t_ann = np.array([c.temperature_C for c in mesh.cells])
        t_cold = np.array([c.temperature_coldest_month_C for c in mesh.cells])
        # The clamp actually engaged somewhere — otherwise the clamp-before-
        # aggregate ordering is not exercised.
        assert (t_m[lakes].min(axis=1) == 0.0).any(), "freeze clamp never engaged"
        # Identity holds on *all* cells, lakes included.
        np.testing.assert_allclose(t_ann, t_m.mean(axis=1), atol=1e-3)
        assert (t_cold[lakes] >= 0.0).all()


class TestConvergenceSentinel:
    """CLIM-02 slice 5: α·k_rain·W_sat(T) per-cell sentinel replaces the
    fixed 11000 mm/yr Earth-station clip."""

    def test_sentinel_values_and_monotonicity(self):
        from dreamulator.map.climate_simulator import _convergence_sentinel

        k = np.full(4, 40.58)  # base rainout rate, 1/yr (τ = 9 d)
        t = np.array([-20.0, 0.0, 15.0, 28.0])  # polar / freezing / mid / tropical
        s = _convergence_sentinel(t, k)
        # Warm tropics: W_sat(28 °C) ~ 66 mm → sentinel ~ 8×40.6×66 ≈ 21,000
        # mm/yr — real orographic extremes (Cherrapunji 11,871) pass.
        assert 12_000.0 < s[3] < 30_000.0
        # Freezing floor: below 0 °C the sentinel is flat (advective-supply
        # proxy — Antarctic coasts get 200-800 mm/yr at tiny local W_sat).
        assert s[0] == pytest.approx(s[1])
        assert 2_000.0 < s[0] < 4_000.0  # W_sat(0 °C) ≈ 9.5 mm → ~3.1 m/yr
        # Monotone above the floor (a warmer column holds more water).
        assert s[1] < s[2] < s[3]
        # Linear in the rainout rate.
        s2 = _convergence_sentinel(t, 2.0 * k)
        assert np.allclose(s2, 2.0 * s)

    def test_sentinel_does_not_bite_gentle_terrain(self):
        """On the gentle 100-cell fixture the budget stays far below the
        sentinel — pre_cap == final (no clipping in the physical regime)."""
        from dreamulator.map.climate_simulator import simulate_climate

        mesh = _build_test_mesh(num_bands=10, cells_per_band=10)
        config = TerrainPipelineConfig(
            seed=42,
            radius_km=6371.0,
            rotation_period_days=1.0,
            stellar_luminosity_sol=1.0,
            orbital_distance_au=1.0,
            axial_tilt_deg=23.44,
            greenhouse_warming_K=33.0,
            lat_gradient_c=45.0,
            lapse_rate_c_km=6.5,
            evaporation_base_mm=1000.0,
            wind_blocking_height_m=3000.0,
            itcz_lag_days=30,
            num_nodes=100,
        )
        debug = {}
        simulate_climate(mesh, config, debug=debug)
        assert "pre_cap" in debug and "final" in debug
        assert np.allclose(debug["pre_cap"], debug["final"]), (
            "convergence sentinel bit on gentle terrain — threshold too tight"
        )
