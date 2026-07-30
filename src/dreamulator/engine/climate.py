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

import json
import logging
from typing import TYPE_CHECKING

import numpy as np
import yaml  # type: ignore[import-untyped]

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.models.layers import Layer
from dreamulator.models.planet import Planet  # noqa: TCH001 — used at runtime

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.map.pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)


def _build_terrain_config(
    planet: Planet,
    stellar_luminosity: float,
    orbital_distance_au: float,
) -> TerrainPipelineConfig:
    """Build the simulation config from planet + stellar data.

    Planet values pass through unchanged.  The ``is not None`` guards only
    cover Optional model variants — an explicit ``0.0`` (e.g. a tidally
    locked body's axial tilt) must NOT be replaced with Earth-like
    fallbacks (a previous truthiness check silently gave every zero-tilt
    world Earth's 23.44° obliquity and thus fictitious seasons).
    """
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

    config = TerrainPipelineConfig()
    config.stellar_luminosity_sol = stellar_luminosity
    config.orbital_distance_au = orbital_distance_au
    config.axial_tilt_deg = planet.axial_tilt_deg if planet.axial_tilt_deg is not None else 23.44
    config.rotation_period_days = (
        planet.rotation_period_days if planet.rotation_period_days is not None else 1.0
    )
    config.radius_km = float(planet.radius) * 6371.0

    if planet.atmosphere is not None:
        config.greenhouse_warming_K = planet.atmosphere.greenhouse_factor
    return config


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

        planets, pwarnings = _load_planets(planet_path)
        warnings.extend(pwarnings)

        if not planets:
            return EngineResult(engine_name=self.name, success=False, warnings=warnings)

        # Use the first terrestrial planet
        planet = planets[0]

        # ---- 2. Load stellar data ----
        stellar_luminosity = 1.0  # default Sun
        stellar_path = self.find_input("stellar_derived.yaml")
        if stellar_path is None:
            stellar_path = self.find_input("stellar.yaml")

        if stellar_path is not None:
            stellar_luminosity = _load_stellar_luminosity(stellar_path, planet.orbits)

        # ---- 3. Determine orbital distance ----
        orbital_distance_au = _load_orbital_distance(planet_path, planet)

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

        config = _build_terrain_config(planet, stellar_luminosity, orbital_distance_au)

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

        simulate_climate(mesh, config)

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
        """
        # Search in unified maps/ directory (new structure)
        for mesh_path in self.maps_output_dir.glob("*/cvt_mesh.json"):
            try:
                with mesh_path.open("w", encoding="utf-8") as f:
                    json.dump(mesh.model_dump(), f, default=str)
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
                    with mesh_path.open("w", encoding="utf-8") as f:
                        json.dump(mesh.model_dump(), f, default=str)
                    logger.info("Updated source mesh with climate data: %s", mesh_path)
                    return
                except Exception as e:
                    logger.warning("Failed to update %s: %s", mesh_path, e)

        logger.warning("No source cvt_mesh.json found to update with climate data")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_planets(path: Path) -> tuple[list[Planet], list[str]]:
    """Load planets from planets.yaml."""
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    planets_raw = data.get("planets", []) if isinstance(data, dict) else []
    planets: list[Planet] = []
    warnings: list[str] = []

    for pdata in planets_raw:
        if not isinstance(pdata, dict):
            continue
        try:
            planets.append(Planet(**pdata))
        except Exception as e:
            warnings.append(f"Failed to parse planet {pdata.get('id', '?')}: {e}")

    return planets, warnings


def _load_stellar_luminosity(stellar_path: Path, star_id: str) -> float:
    """Extract stellar luminosity from stellar_derived.yaml or stellar.yaml.

    Args:
        stellar_path: Path to stellar YAML file.
        star_id: ID of the star the planet orbits.

    Returns:
        Stellar luminosity in solar units (default 1.0 if not found).
    """
    with stellar_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    stars = data.get("stars", [])
    for star in stars:
        if not isinstance(star, dict):
            continue
        if star.get("id") == star_id:
            # Prefer computed luminosity, then authored, then default
            lum = star.get("computed_luminosity") or star.get("luminosity")
            if lum is not None:
                return float(lum)

    return 1.0


def _load_orbital_distance(planet_path: Path, planet: Planet) -> float:
    """Extract orbital distance for the planet from the same file that defines it.

    Currently returns 1.0 AU as default.  In Phase 3B+ this should read orbital
    elements from stellar.yaml.

    Args:
        planet_path: Path to the YAML file containing planet definitions.
        planet: The planet object.

    Returns:
        Orbital semi-major axis in AU.
    """
    # For now, Earth-like default.  Orbital data lives in astronomy layer;
    # full integration requires cross-referencing StellarSystem.orbits.
    return 1.0


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
                from dreamulator.map.models import CVTMesh

                with mesh_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                return CVTMesh(**data), []
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
        from dreamulator.map.models import CVTMesh

        with mesh_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        mesh = CVTMesh(**data)
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
