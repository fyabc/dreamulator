"""Geological engine — wraps the terrain generation pipeline as a DAG engine.

This enables ``dreamulator build --only geological`` to run the full terrain
pipeline (CVT mesh → plates → boundaries → terrain synthesis → export)
through the standard BaseEngine interface.

For fine-grained stage control during development, use
``dreamulator terrain generate --stages ...`` instead.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.models.layers import Layer

logger = logging.getLogger(__name__)


class GeologicalEngine(BaseEngine):
    """Run the terrain generation pipeline as a DAG engine.

    Reads terrain_config.yaml from the geological input layer,
    runs the full pipeline, and writes outputs to geological derived.
    """

    name = "geological"
    version = "0.1.0"
    layer = Layer.GEOLOGICAL
    requires: list[str] = ["astronomy"]
    input_files = ["terrain_config.yaml"]
    output_files = [
        "maps/{planet_id}/elevation.png",
        "maps/{planet_id}/cvt_mesh.json",
        "maps/{planet_id}/plates.json",
        "maps/{planet_id}/metadata.json",
    ]

    def run(self, parameters: dict[str, object] | None = None) -> EngineResult:
        """Execute the terrain generation pipeline.

        Args:
            parameters: Optional overrides (num_nodes, num_plates, seed, stages).

        Returns:
            EngineResult describing the outcome.
        """
        from dreamulator.map.pipeline_types import TerrainPipelineConfig
        from dreamulator.map.terrain_pipeline import run_terrain_pipeline

        warnings: list[str] = []
        pars = parameters or {}

        # ---- Load configuration ----
        config = self._load_config(pars)
        if config is None:
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=["terrain_config.yaml not found in any layer input directory"],
            )

        # ---- Determine planet ID and output directory ----
        planet_id = str(pars.get("planet_id", "earth"))
        output_dir = self.layer_output_dir / "maps" / planet_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # ---- Parse optional stage list ----
        stage_list: list[str] | None = None
        if "stages" in pars:
            stages_val = pars["stages"]
            if isinstance(stages_val, str):
                stage_list = [s.strip() for s in stages_val.split(",")]
            elif isinstance(stages_val, list):
                stage_list = [str(s) for s in stages_val]

        # ---- Run pipeline ----
        logger.info(
            "Running terrain pipeline: %d nodes, %d plates, seed=%d",
            config.num_nodes,
            config.num_plates,
            config.seed,
        )

        try:
            result = run_terrain_pipeline(config, output_dir, stages=stage_list)
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
            f"maps/{planet_id}/metadata.json",
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
                "elapsed_seconds": result.elapsed_seconds,
            },
        )

    def _load_config(self, pars: dict[str, object]) -> "object | None":
        """Load TerrainPipelineConfig from terrain_config.yaml or defaults.

        Args:
            pars: Optional parameter overrides.

        Returns:
            TerrainPipelineConfig or None if not found.
        """
        from dreamulator.map.pipeline_types import TerrainPipelineConfig

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

        # Apply parameter overrides
        for key in ("num_nodes", "num_plates", "seed", "tectonic_steps"):
            if key in pars:
                setattr(cfg, key, pars[key])

        return cfg
