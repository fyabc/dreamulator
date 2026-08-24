"""Climate engine — EBM temperature, geostrophic wind, precipitation, ocean currents.

Reads planet parameters from the geological layer and stellar parameters from the
astronomy layer, then computes gridded climate data using the spherical CVT mesh.

Output files (written to ``layers/climate/derived/``):
    - climate_summary.yaml  — per-cell temperature, precipitation, Köppen codes
    - maps/{planet_id}/temperature.png  — equirectangular temperature raster
    - maps/{planet_id}/precipitation.png — equirectangular precipitation raster
    - maps/{planet_id}/koppen.json       — Köppen classification per cell
    - maps/{planet_id}/climate_metadata.json — export metadata
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import yaml
from pydantic import TypeAdapter

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.physical_inputs import (
    load_planets,
    resolve_and_apply_physical_parameters,
)
from dreamulator.map.models import CVTMesh
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.models.layers import Layer
from dreamulator.models.planet import Planet  # noqa: TCH001 — used at runtime

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class ClimateEngine(BaseEngine):
    """Compute temperature, precipitation, wind, and ocean currents.

    Requires astronomy-derived stellar parameters and geological terrain
    data (elevation raster + CVT mesh) as inputs.
    """

    name = "climate"
    layer = Layer.CLIMATE
    requires = ["astronomy", "geological"]  # geological data is loaded via maps, not DAG
    input_files = [
        "stellar.yaml",  # → astronomy input (star luminosity, orbits)
        "stellar_derived.yaml",  # → astronomy derived (computed stellar params)
        "planets.yaml",  # → geological input (planet physical parameters)
    ]
    optional_input_files = [
        "terrain_config.yaml",  # → geological input (climate tuning knobs; defaults ok)
    ]
    output_files = [
        "climate_summary.yaml",
        "maps/{planet_id}/temperature.png",
        "maps/{planet_id}/precipitation.png",
        "maps/{planet_id}/koppen.json",
        "maps/{planet_id}/climate_metadata.json",
    ]

    def run(
        self, parameters: dict[str, object] | None = None, *, force: bool = False
    ) -> EngineResult:
        """Execute climate simulation.

        Steps:
            1. Load planet parameters (planets.yaml).
            2. Load stellar parameters (stellar_derived.yaml or stellar.yaml).
            3. Load CVT mesh + elevation from geological derived directory.
            4. Compute temperature, precipitation, Köppen classes.
            5. Export raster + JSON outputs.
            6. Write climate_summary.yaml.

        Args:
            parameters: Optional overrides for climate constants.

        Returns:
            EngineResult describing the outcome.
        """
        warnings: list[str] = []

        # ---- 1. Load planet data ----
        planet_path = self.find_input("planets.yaml")
        if planet_path is None:
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=["planets.yaml not found"],
            )

        planets, pwarnings = load_planets(planet_path)
        warnings.extend(pwarnings)

        if not planets:
            return EngineResult(engine_name=self.name, success=False, warnings=warnings)

        # Use the first terrestrial planet
        planet = planets[0]

        # ---- 2-3. Resolve physical parameters (shared with geological engine) ----
        # Stellar luminosity and heliocentric distance come from the astronomy
        # layer (satellite-aware: moons resolve against their host star);
        # planet physics (tilt/rotation/radius/greenhouse) from planets.yaml.
        # Climate tuning knobs (lat_gradient_c, circulation cell boundaries,
        # precipitation efficiencies, ...) live in terrain_config.yaml — the
        # same file the geological engine's in-pipeline climate pass reads,
        # so the standalone climate build and the terrain pipeline cannot
        # diverge.  Canonical physical forcing (luminosity, distance, tilt,
        # rotation, greenhouse) is still resolved from planets.yaml/stellar
        # below and overrides anything in terrain_config.yaml.
        terrain_config_path = self.find_input("terrain_config.yaml")
        if terrain_config_path is not None:
            config = TerrainPipelineConfig.from_yaml(terrain_config_path)
        else:
            config = TerrainPipelineConfig()
        warnings.extend(resolve_and_apply_physical_parameters(self, config, planet=planet))

        # ---- 4. Load CVT mesh with elevation ----
        mesh, mwarnings = _load_cvt_mesh_from_geological(
            self.layer_derived_dirs,
            self.layer_input_dirs,
            maps_dir=self.maps_output_dir,
        )
        warnings.extend(mwarnings)
        if mesh is None:
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=warnings + ["No CVT mesh found in geological derived data"],
            )

        # ---- 5. Run climate simulation ----
        from dreamulator.map.climate_simulator import simulate_climate

        # Override from parameters dict
        pars = parameters or {}
        for key in (
            "lapse_rate_c_km",
            "lat_gradient_c",
            "hadley_extent_deg",
            "polar_cell_start_deg",
            "greenhouse_warming_K",
            "evaporation_base_mm",
            "wind_blocking_height_m",
            "itcz_lag_days",
        ):
            if key in pars:
                setattr(config, key, pars[key])

        # simulate_climate returns per-phase wall-clock timings (M0)
        phase_timings = simulate_climate(mesh, config)

        # ---- 5b. Write climate data back to source cvt_mesh.json ----
        # The frontend reads cvt_mesh.json (geological layer) and expects
        # koppen_class / temperature_C / precipitation_mm to be populated.
        self._update_source_mesh(mesh, planet.id)

        # ---- 6. Export outputs ----
        export_dir = self.maps_output_dir / planet.id
        export_dir.mkdir(parents=True, exist_ok=True)

        from dreamulator.map.export import export_climate_layers

        export_climate_layers(mesh, export_dir, config)

        # ---- 7. Write summary YAML ----
        summary = _build_climate_summary(mesh, planet, config)
        self._write_yaml("climate_summary.yaml", summary)

        n_cells = mesh.num_cells
        n_land = sum(1 for c in mesh.cells if c.elevation >= 0.0)
        koppen_counts: dict[str, int] = {}
        for c in mesh.cells:
            if c.koppen_class:
                koppen_counts[c.koppen_class] = koppen_counts.get(c.koppen_class, 0) + 1

        logger.info(
            "Climate engine complete: %d cells, %d land, %d Köppen classes",
            n_cells,
            n_land,
            len(koppen_counts),
        )

        return EngineResult(
            engine_name=self.name,
            success=True,
            output_files=[
                f"maps/{planet.id}/temperature.png",
                f"maps/{planet.id}/precipitation.png",
                f"maps/{planet.id}/koppen.json",
                f"maps/{planet.id}/climate_metadata.json",
                "climate_summary.yaml",
            ],
            warnings=warnings,
            metadata={
                "planet_id": planet.id,
                "planet_name": planet.name,
                "num_cells": mesh.num_cells,
                "num_land_cells": n_land,
                "koppen_class_counts": koppen_counts,
                "phase_timings": phase_timings,
            },
        )

    def outputs_exist(self) -> bool:
        """Climate outputs span two directories: maps/ and layers/climate/derived/."""
        # climate_summary.yaml lives in layer_output_dir
        if not self.output_path("climate_summary.yaml").exists():
            return False
        # raster + JSON outputs live in maps/{planet_id}/
        if not self.maps_output_dir.exists():
            return False
        return any(self.maps_output_dir.glob("*/temperature.png"))

    def output_paths(self) -> list[Path]:
        """Resolved climate outputs across derived/ and maps/ (for dirty check)."""
        paths: list[Path] = [self.output_path("climate_summary.yaml")]
        if self.maps_output_dir.exists():
            paths.extend(self.maps_output_dir.glob("*/temperature.png"))
        return paths

    def _write_yaml(self, filename: str, data: dict[str, object]) -> None:
        """Write data as YAML to the output directory."""
        path = self.output_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _update_source_mesh(self, mesh: CVTMesh, planet_id: str) -> None:
        """Write climate-populated mesh back to the source cvt_mesh.json.

        Writes to the specific planet's unified maps/ directory (new structure),
        with a fallback to old layer-based locations for backward compatibility.

        Uses the pydantic-core serializer (Rust, ~5x faster than
        model_dump() + json.dump()); non-finite floats serialize as null.
        """
        # model_dump_json() returns str; write_bytes needs bytes.
        mesh_bytes = mesh.model_dump_json().encode("utf-8")
        from ..map.export import _truncate_float_precision, compress_mesh_bytes

        mesh_bytes = _truncate_float_precision(mesh_bytes)
        mesh_bytes = compress_mesh_bytes(mesh_bytes)
        # Write to the specific planet directory (new unified maps/ structure)
        target = self.maps_output_dir / planet_id / "cvt_mesh.json"
        if target.exists():
            try:
                target.write_bytes(mesh_bytes)
                logger.info("Updated source mesh with climate data: %s", target)
                return
            except Exception as e:
                logger.warning("Failed to update %s: %s", target, e)

        # Fallback: old layer-based locations
        search_dirs: list[Path] = []
        for layer_dirs in (self.layer_derived_dirs, self.layer_input_dirs):
            geo_dir = layer_dirs.get("geological")
            if geo_dir:
                search_dirs.append(geo_dir)

        for d in search_dirs:
            for mesh_path in d.glob("maps/*/cvt_mesh.json"):
                try:
                    mesh_path.write_bytes(mesh_bytes)
                    logger.info("Updated source mesh with climate data: %s", mesh_path)
                    return
                except Exception as e:
                    logger.warning("Failed to update %s: %s", mesh_path, e)

        logger.warning("No source cvt_mesh.json found to update with climate data")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_cvt_mesh_from_geological(
    layer_derived_dirs: dict[str, Path],
    layer_input_dirs: dict[str, Path] | None = None,
    maps_dir: Path | None = None,
) -> tuple[CVTMesh | None, list[str]]:
    """Load the CVT mesh from the unified maps/ directory or old layer locations.

    Searches for ``cvt_mesh.json`` in:
    1. Unified maps/{planet_id}/ directory (new structure)
    2. Old layer-based directories (backward compatibility)

    Args:
        layer_derived_dirs: Map of layer name → derived directory.
        layer_input_dirs: Map of layer name → input directory.
        maps_dir: Unified maps output directory (new structure).

    Returns:
        (CVTMesh | None, warnings).
    """
    from ..map.export import decompress_mesh_bytes

    # 1. Search unified maps/ directory first
    if maps_dir is not None and maps_dir.exists():
        mesh_paths = list(maps_dir.glob("*/cvt_mesh.json"))
        if mesh_paths:
            mesh_path = mesh_paths[0]
            try:
                # pydantic-core JSON parser (Rust) — faster than
                # json.load() + CVTMesh(**data) for the 80+ MB mesh.
                mesh = TypeAdapter(CVTMesh).validate_json(
                    decompress_mesh_bytes(mesh_path.read_bytes())
                )
                return mesh, []
            except Exception as e:
                return None, [f"Failed to load CVT mesh from {mesh_path}: {e}"]

    # 2. Fallback: old layer-based locations
    search_dirs: list[Path] = []

    geo_derived = layer_derived_dirs.get("geological")
    if geo_derived is not None:
        search_dirs.append(geo_derived)

    if layer_input_dirs:
        geo_input = layer_input_dirs.get("geological")
        if geo_input is not None:
            search_dirs.append(geo_input)

    if not search_dirs:
        return None, ["No maps directory or geological layer directories found"]

    # Search for cvt_mesh.json in maps/<planet_id>/
    mesh_paths = []
    for d in search_dirs:
        mesh_paths.extend(d.glob("maps/*/cvt_mesh.json"))

    if not mesh_paths:
        return None, [f"No cvt_mesh.json found in: {[str(d) for d in search_dirs]}"]

    # Use the first one found
    mesh_path = mesh_paths[0]
    try:
        mesh = TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(mesh_path.read_bytes()))
        return mesh, []
    except Exception as e:
        return None, [f"Failed to load CVT mesh from {mesh_path}: {e}"]


def _build_climate_summary(
    mesh: CVTMesh,
    planet: Planet,
    config: TerrainPipelineConfig,
) -> dict[str, object]:
    """Build a structured summary of the climate simulation.

    Args:
        mesh: CVTMesh with populated climate fields.
        planet: Planet object.
        config: TerrainPipelineConfig used for the simulation.

    Returns:
        Dict suitable for YAML serialization.
    """
    cells = mesh.cells
    len(cells)

    # Extract arrays
    elev = np.array([c.elevation for c in cells], dtype=np.float64)
    temp = np.array(
        [(c.temperature_C if c.temperature_C is not None else np.nan) for c in cells],
        dtype=np.float64,
    )
    precip = np.array(
        [(c.precipitation_mm if c.precipitation_mm is not None else np.nan) for c in cells],
        dtype=np.float64,
    )

    land_mask = elev >= 0.0
    ocean_mask = ~land_mask

    # Seasonal temperature range (hottest − coldest month) — the statistic the
    # harness interrogation cites (e.g. "季节温差中位数 ~0.8°C" for a 9°-obliquity
    # / 67-day-year world). See harness.md §5.2.
    hot = np.array(
        [
            (c.temperature_hottest_month_C if c.temperature_hottest_month_C is not None else np.nan)
            for c in cells
        ],
        dtype=np.float64,
    )
    cold = np.array(
        [
            (c.temperature_coldest_month_C if c.temperature_coldest_month_C is not None else np.nan)
            for c in cells
        ],
        dtype=np.float64,
    )
    seasonal_range = hot - cold
    land_range = seasonal_range[land_mask]
    land_range = land_range[~np.isnan(land_range)]

    def _median_stats(arr: np.ndarray) -> dict[str, float]:
        if arr.size == 0:
            return {
                "median": float("nan"),
                "mean": float("nan"),
                "min": float("nan"),
                "max": float("nan"),
            }
        return {
            "median": float(np.median(arr)),
            "mean": float(np.mean(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
        }

    seasonal_land_stats = _median_stats(land_range)

    # Global statistics
    def safe_stats(arr: np.ndarray, mask: np.ndarray | None = None) -> dict[str, float]:
        if mask is not None:
            arr = arr[mask]
        valid = arr[~np.isnan(arr)]
        if len(valid) == 0:
            return {"mean": float("nan"), "min": float("nan"), "max": float("nan")}
        return {
            "mean": float(np.mean(valid)),
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
        }

    # Köppen class distribution
    from collections import Counter

    koppen_counts = Counter(
        c.koppen_class for c in cells if c.koppen_class and c.koppen_class != "Ocean"
    )

    return {
        "planet": {
            "id": planet.id,
            "name": planet.name,
        },
        "temperature_C": {
            "global": safe_stats(temp),
            "land": safe_stats(temp, land_mask),
            "ocean": safe_stats(temp, ocean_mask),
        },
        "precipitation_mm": {
            "global": safe_stats(precip),
            "land": safe_stats(precip, land_mask),
            "ocean": safe_stats(precip, ocean_mask),
        },
        "koppen_classes": dict(koppen_counts),
        "seasonal_range_C": {
            "land": seasonal_land_stats,
        },
        "simulation_parameters": {
            "axial_tilt_deg": float(getattr(config, "axial_tilt_deg", 23.44)),
            "stellar_luminosity_sol": float(getattr(config, "stellar_luminosity_sol", 1.0)),
            "orbital_distance_au": float(getattr(config, "orbital_distance_au", 1.0)),
            "greenhouse_warming_K": float(getattr(config, "greenhouse_warming_K", 33.0)),
        },
    }
