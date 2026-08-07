"""Geological engine — wraps the terrain generation pipeline as a DAG engine.

This enables ``dreamulator build --only geological`` to run the full terrain
pipeline (CVT mesh → plates → boundaries → terrain synthesis → export)
through the standard BaseEngine interface.

For fine-grained stage control during development, use
``dreamulator terrain generate --stages ...`` instead.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.models.layers import Layer

if TYPE_CHECKING:
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)


class GeologicalEngine(BaseEngine):
    """Run the terrain generation pipeline as a DAG engine.

    Reads terrain_config.yaml from the geological input layer,
    runs the full pipeline, and writes outputs to geological derived.
    """

    name = "geological"
    layer = Layer.GEOLOGICAL
    requires: list[str] = ["astronomy"]
    # Both optional: absent terrain_config falls back to planet-derived
    # defaults; absent geography.yaml = unauthored (random) continents.
    input_files: list[str] = []
    optional_input_files = ["terrain_config.yaml", "geography.yaml"]
    output_files = [
        "maps/{planet_id}/elevation.png",
        "maps/{planet_id}/cvt_mesh.json",
        "maps/{planet_id}/plates.json",
        "maps/{planet_id}/map.yaml",
    ]

    def run(self, parameters: dict[str, object] | None = None) -> EngineResult:
        """Execute the terrain generation pipeline.

        Args:
            parameters: Optional overrides (num_nodes, num_plates, seed, stages).

        Returns:
            EngineResult describing the outcome.
        """
        from dreamulator.map.terrain_pipeline import run_terrain_pipeline

        warnings: list[str] = []
        pars = parameters or {}

        # ---- Load configuration ----
        config, config_warnings = self._load_config(pars)
        warnings.extend(config_warnings)
        if config is None:
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=warnings + ["terrain_config.yaml not found in any layer input directory"],
            )

        # ---- Determine planet ID and output directory ----
        planet_id = str(pars.get("planet_id", "")) or self._detect_planet_id()
        output_dir = self.maps_output_dir / planet_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # ---- Parse optional stage list ----
        stage_list: list[str] | None = None
        if "stages" in pars:
            stages_val = pars["stages"]
            if isinstance(stages_val, str):
                stage_list = [s.strip() for s in stages_val.split(",")]
            elif isinstance(stages_val, list):
                stage_list = [str(s) for s in stages_val]

        if stage_list is None:
            # Stage 0.0a: the climate engine is authoritative for climate
            # fields; skip the terrain pipeline's in-line climate pass
            # (~123 s at 100k cells + duplicated climate raster export).
            # Rivers/erosion stay listed (they skip until implemented); when
            # they land and need climate forcing, re-add "climate" here.
            stage_list = [
                "mesh",
                "plates",
                "tectonics",
                "boundaries",
                "terrain",
                "rivers",
                "erosion",
                "export",
            ]

        # ---- Run pipeline ----
        logger.info(
            "Running terrain pipeline: %d nodes, %d plates, seed=%d",
            config.num_nodes,
            config.num_plates,
            config.seed,
        )

        try:
            raster_path = self.find_input("geography_raster.png")
            raster = None
            if raster_path is not None:
                from dreamulator.map.geography import load_geography_raster

                raster = load_geography_raster(raster_path)
            result = run_terrain_pipeline(
                config, output_dir, stages=stage_list, geography_raster=raster
            )
        except RuntimeError as e:
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=[f"Pipeline error: {e}"],
            )

        # ---- Report ----
        logger.info(
            "Terrain pipeline complete in %.1fs: %s",
            result.elapsed_seconds,
            " -> ".join(result.stages_completed),
        )

        output_files = [
            f"maps/{planet_id}/elevation.png",
            f"maps/{planet_id}/cvt_mesh.json",
            f"maps/{planet_id}/plates.json",
            f"maps/{planet_id}/map.yaml",
        ]

        return EngineResult(
            engine_name=self.name,
            success=True,
            output_files=output_files,
            warnings=warnings,
            metadata={
                "planet_id": planet_id,
                "num_nodes": config.num_nodes,
                "num_plates": config.num_plates,
                "seed": config.seed,
                "stages_completed": result.stages_completed,
                "stage_timings": result.stage_timings,
                "elapsed_seconds": result.elapsed_seconds,
            },
        )

    def outputs_exist(self) -> bool:
        """Check if geological outputs already exist in maps/ directory."""
        if not self.maps_output_dir.exists():
            return False
        # Any planet directory with cvt_mesh.json counts as "done"
        return any(self.maps_output_dir.glob("*/cvt_mesh.json"))

    def _load_config(
        self, pars: dict[str, object]
    ) -> tuple[TerrainPipelineConfig | None, list[str]]:
        """Load TerrainPipelineConfig and canonical physical parameters.

        Terrain-generation knobs come from ``terrain_config.yaml`` (or planet
        defaults); physical forcing parameters (stellar luminosity, orbital
        distance, tilt, rotation, radius, greenhouse) are resolved exactly as
        the climate engine does (shared ``physical_inputs`` module), so the
        in-pipeline climate pass and the climate engine can never diverge.

        Args:
            pars: Optional parameter overrides.

        Returns:
            (config, warnings).
        """
        from dreamulator.engine.physical_inputs import (
            PHYSICAL_CONFIG_FIELDS,
            resolve_and_apply_physical_parameters,
        )
        from dreamulator.map.pipeline_types import TerrainPipelineConfig

        warnings: list[str] = []

        # Try to find terrain_config.yaml
        config_path = self.find_input("terrain_config.yaml")
        if config_path is not None:
            cfg = TerrainPipelineConfig.from_yaml(config_path)
        else:
            # Fall back to planets.yaml for basic parameters
            planets_path = self.find_input("planets.yaml")
            if planets_path is not None:
                import yaml

                with planets_path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                planets = data.get("planets", [])
                if planets:
                    cfg = TerrainPipelineConfig.from_planet_config(planets[0])
                else:
                    cfg = TerrainPipelineConfig()
            else:
                cfg = TerrainPipelineConfig()

        # Apply parameter overrides (terrain knobs from CLI/API)
        for key in ("num_nodes", "num_plates", "seed", "tectonic_steps"):
            if key in pars:
                setattr(cfg, key, pars[key])

        # Authored geography (continent anchoring). Optional: absent → pure
        # procedural crust assignment. See map/geography.py.
        from dreamulator.map.geography import load_geography_spec

        cfg.geography = load_geography_spec(self.find_input("geography.yaml"))

        # Canonical physical parameters from planets.yaml + stellar data
        # (satellite-aware stellar lookup — see physical_inputs docstring).
        planet_id = str(pars.get("planet_id") or "") or None
        before = {key: getattr(cfg, key) for key in PHYSICAL_CONFIG_FIELDS}
        warnings.extend(resolve_and_apply_physical_parameters(self, cfg, planet_id=planet_id))

        # Flag terrain_config physical values overridden by canonical inputs
        # (consistency-check pattern: warn only beyond a 20% divergence).
        defaults = TerrainPipelineConfig()
        for key in PHYSICAL_CONFIG_FIELDS:
            old = before[key]
            new = getattr(cfg, key)
            if old != new and old != getattr(defaults, key):
                rel = abs(old - new) / max(abs(new), 1e-9)
                if rel > 0.2:
                    warnings.append(
                        f"terrain_config {key}={old} differs from canonical "
                        f"planets/stellar value {new} ({rel:.0%}); using canonical value"
                    )

        return cfg, warnings

    def _detect_planet_id(self) -> str:
        """Auto-detect planet ID from planets.yaml or existing map directories.

        Returns:
            Planet ID string (e.g. 'satellite_gaiam', 'earth').
        """
        import yaml

        # Try planets.yaml first
        planets_path = self.find_input("planets.yaml")
        if planets_path is not None:
            with planets_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            planets = data.get("planets", [])
            if planets and isinstance(planets[0], dict) and "id" in planets[0]:
                return str(planets[0]["id"])

        # Fallback: check existing maps directories
        for layer_dirs in (self.layer_input_dirs, self.layer_derived_dirs):
            geo_dir = layer_dirs.get("geological")
            if geo_dir:
                maps_dir = geo_dir / "maps"
                if maps_dir.exists():
                    for d in maps_dir.iterdir():
                        if d.is_dir() and (d / "cvt_mesh.json").exists():
                            return d.name

        return "earth"
