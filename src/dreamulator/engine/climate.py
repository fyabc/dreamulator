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
import yaml  # type: ignore[import-untyped]

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.physical_inputs import (
    load_planets,
    resolve_and_apply_physical_parameters,
)
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
    output_files = [
        "climate_summary.yaml",
        "maps/{planet_id}/temperature.png",
        "maps/{planet_id}/precipitation.png",
        "maps/{planet_id}/koppen.json",
        "maps/{planet_id}/climate_metadata.json",
    ]

    # ------------------------------------------------------------------
    # Default climate parameters (Earth-like)
    # ------------------------------------------------------------------
    _DEFAULT_LAPSE_RATE: float = 6.5  # °C/km
    _DEFAULT_LAT_GRADIENT: float = 45.0  # °C equator-pole
    _DEFAULT_GREENHOUSE: float = 33.0  # K
    _DEFAULT_EVAP_BASE: float = 2000.0  # mm/yr
    _DEFAULT_OROGRAPHIC_EFF: float = 0.5
    _DEFAULT_WIND_BLOCK: float = 3000.0  # m
    _DEFAULT_ITCZ_LAG: int = 30  # days

    def run(self, parameters: dict[str, object] | None = None) -> EngineResult:
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
        from dreamulator.map.pipeline_types import TerrainPipelineConfig

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
            "greenhouse_warming_K",
            "evaporation_base_mm",
            "orographic_efficiency",
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
        self._update_source_mesh(mesh)

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
        koppen_counts = {}
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

    def _write_yaml(self, filename: str, data: dict[str, object]) -> None:
        """Write data as YAML to the output directory."""
        path = self.output_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _update_source_mesh(self, mesh: object) -> None:
        """Write climate-populated mesh back to the source cvt_mesh.json.

        Searches the unified maps/ directory first, then falls back to
        old layer-based locations for backward compatibility.

        Uses the pydantic-core serializer (Rust, ~5x faster than
        model_dump() + json.dump()); non-finite floats serialize as null.
        """
        # model_dump_json() returns str; write_bytes needs bytes.
        mesh_bytes = mesh.model_dump_json().encode("utf-8")  # type: ignore[union-attr]
        # Search in unified maps/ directory (new structure)
        for mesh_path in self.maps_output_dir.glob("*/cvt_mesh.json"):
            try:
                mesh_path.write_bytes(mesh_bytes)
                logger.info("Updated source mesh with climate data: %s", mesh_path)
                return
            except Exception as e:
                logger.warning("Failed to update %s: %s", mesh_path, e)

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
) -> tuple[object | None, list[str]]:
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
    # 1. Search unified maps/ directory first
    if maps_dir is not None and maps_dir.exists():
        mesh_paths = list(maps_dir.glob("*/cvt_mesh.json"))
        if mesh_paths:
            mesh_path = mesh_paths[0]
            try:
                from pydantic import TypeAdapter

                from dreamulator.map.models import CVTMesh

                # pydantic-core JSON parser (Rust) — faster than
                # json.load() + CVTMesh(**data) for the 80+ MB mesh.
                mesh = TypeAdapter(CVTMesh).validate_json(mesh_path.read_bytes())
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
    mesh_paths: list[Path] = []
    for d in search_dirs:
        mesh_paths.extend(d.glob("maps/*/cvt_mesh.json"))

    if not mesh_paths:
        return None, [f"No cvt_mesh.json found in: {[str(d) for d in search_dirs]}"]

    # Use the first one found
    mesh_path = mesh_paths[0]
    try:
        from pydantic import TypeAdapter

        from dreamulator.map.models import CVTMesh

        mesh = TypeAdapter(CVTMesh).validate_json(mesh_path.read_bytes())
        return mesh, []
    except Exception as e:
        return None, [f"Failed to load CVT mesh from {mesh_path}: {e}"]


def _build_climate_summary(
    mesh: object,
    planet: Planet,
    config: object,
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
        "simulation_parameters": {
            "axial_tilt_deg": float(getattr(config, "axial_tilt_deg", 23.44)),
            "stellar_luminosity_sol": float(getattr(config, "stellar_luminosity_sol", 1.0)),
            "orbital_distance_au": float(getattr(config, "orbital_distance_au", 1.0)),
            "greenhouse_warming_K": float(getattr(config, "greenhouse_warming_K", 33.0)),
        },
    }
