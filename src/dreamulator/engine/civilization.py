"""Civilization engine — habitability & agriculture derived layers.

Reads the CVT mesh with climate data (temperature, precipitation, distance-to-coast)
already populated by the ClimateEngine, and computes per-cell civilization inputs:

    - ``habitable_coast`` (宜居海岸) — settleable coastal land.
    - ``agricultural_core`` (农业核心区) — farmable land (Köppen C/D tree-line).

This is the first derived engine of the civilization layer: a thin bridge between
climate/ecology and the Phase 3C semi-structured civilisation model.  It is NOT
the 3C event-sourcing/state-machine engine — it only produces the two per-cell
land-suitability layers that ``civilizations.yaml`` anchors on (roadmap §七
"文明宜居/农业图层").  See ``docs/design/civilization-layer.md`` for 3C.

Output files (written to ``layers/civilization/derived/``):
    - habitability_summary.yaml — per-cell habitable/agricultural counts + overlap
    - civilization_seed_candidates.yaml — derived seed-candidate regions (ranked
      by carrying capacity, features inherited from climate/ecology/geography)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.habitability import (
    agriculture_score,
    classify_agricultural_core,
    classify_habitable_coast,
    habitability_score,
)
from dreamulator.engine.physical_inputs import load_planet_for_engine
from dreamulator.engine.seed_discovery import discover_seed_candidates
from dreamulator.map.models import CVTMesh
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.models.layers import Layer

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class CivilizationEngine(BaseEngine):
    """Compute the two habitability/agriculture derived layers per cell.

    Requires climate data (temperature, precipitation, hottest-month temperature,
    distance-to-coast) already computed on the CVT mesh by the ClimateEngine, and
    runs after the EcologyEngine so its fields are also present downstream.
    """

    name = "civilization"
    layer = Layer.CIVILIZATION
    requires = ["ecology", "climate", "geological"]
    input_files: list[str] = []
    optional_input_files: list[str] = []
    output_files = [
        "habitability_summary.yaml",
        "civilization_seed_candidates.yaml",
    ]

    def run(
        self, parameters: dict[str, object] | None = None, *, force: bool = False
    ) -> EngineResult:  # noqa: ARG002
        """Run habitability/agriculture classification on the CVT mesh.

        Steps:
            1. Load CVT mesh from geological derived data.
            2. Verify climate fields (temperature_C, precipitation_mm,
               temperature_hottest_month_C, distance_to_coast_km) exist.
            3. Resolve planet id/name for the summary.
            4. Per cell: habitable_coast / agricultural_core booleans.
            5. Write fields back to cvt_mesh.json + habitability_summary.yaml.

        Returns
        -------
        EngineResult
        """
        warnings: list[str] = []

        # ---- 1. Load CVT mesh ----
        mesh, mwarnings = _load_cvt_mesh(self)
        warnings.extend(mwarnings)
        if mesh is None:
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=warnings + ["No CVT mesh found"],
            )

        # ---- 2. Verify climate data present ----
        n_cells = mesh.num_cells
        cells_with_temp = sum(1 for c in mesh.cells if c.temperature_C is not None)
        cells_with_precip = sum(1 for c in mesh.cells if c.precipitation_mm is not None)
        cells_with_t_hot = sum(1 for c in mesh.cells if c.temperature_hottest_month_C is not None)
        cells_with_dist = sum(1 for c in mesh.cells if c.distance_to_coast_km is not None)
        if not (cells_with_temp and cells_with_precip and cells_with_t_hot and cells_with_dist):
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=warnings
                + [
                    f"Climate data incomplete: T={cells_with_temp}, P={cells_with_precip}, "
                    f"t_hot={cells_with_t_hot}, dist_to_coast={cells_with_dist} / {n_cells}. "
                    "Run the climate engine first.",
                ],
            )

        # ---- 3. Resolve planet + config (sub-planet longitude drives the zone) ----
        planet, pwarnings = load_planet_for_engine(self)
        warnings.extend(pwarnings)
        planet_id = planet.id if planet is not None else None
        planet_name = planet.name if planet is not None else None

        terrain_config_path = self.find_input("terrain_config.yaml")
        config = (
            TerrainPipelineConfig.from_yaml(terrain_config_path)
            if terrain_config_path is not None
            else TerrainPipelineConfig()
        )
        sub_planet_longitude_deg = config.sub_planet_longitude_deg

        # ---- 4. Classify every cell ----
        counts: dict[str, int] = {
            "habitable_coast": 0,
            "agricultural_core": 0,
            "overlap": 0,
            "habitable_not_agricultural": 0,
            "agricultural_not_habitable": 0,
            "neither": 0,
        }
        n_land = 0
        for cell in mesh.cells:
            is_ocean = cell.elevation < 0.0
            if not is_ocean:
                n_land += 1

            habitable = classify_habitable_coast(
                temperature_c=cell.temperature_C,
                precipitation_mm=cell.precipitation_mm,
                distance_to_coast_km=cell.distance_to_coast_km,
                is_ocean=is_ocean,
            )
            agricultural = classify_agricultural_core(
                temperature_hottest_month_c=cell.temperature_hottest_month_C,
                is_ocean=is_ocean,
            )
            cell.habitable_coast = habitable
            cell.agricultural_core = agricultural
            cell.habitability_score = habitability_score(
                temperature_c=cell.temperature_C,
                precipitation_mm=cell.precipitation_mm,
                is_ocean=is_ocean,
            )
            cell.agriculture_score = agriculture_score(
                temperature_hottest_month_c=cell.temperature_hottest_month_C,
                precipitation_mm=cell.precipitation_mm,
                soil_fertility=cell.soil_fertility,
                is_ocean=is_ocean,
            )

            if is_ocean:
                continue  # summary counts cover land cells only
            if habitable and agricultural:
                counts["overlap"] += 1
                counts["habitable_coast"] += 1
                counts["agricultural_core"] += 1
            elif habitable:
                counts["habitable_coast"] += 1
                counts["habitable_not_agricultural"] += 1
            elif agricultural:
                counts["agricultural_core"] += 1
                counts["agricultural_not_habitable"] += 1
            else:
                counts["neither"] += 1

        # ---- 4.5 Discover seed candidate regions (derived, deterministic) ----
        candidates = discover_seed_candidates(
            mesh, sub_planet_longitude_deg=sub_planet_longitude_deg
        )

        # ---- 5. Write habitability data back to the source mesh ----
        _write_mesh_with_habitability(mesh, self.maps_output_dir, planet_id)

        # ---- 6. Write summary + seed-candidate YAML ----
        summary = _build_habitability_summary(mesh, counts, n_land, planet_id, planet_name)
        candidates_doc = _build_seed_candidates_doc(candidates, planet_id, planet_name)
        import yaml

        yaml_path = self.output_path("habitability_summary.yaml")
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(
            yaml.dump(summary, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        candidates_path = self.output_path("civilization_seed_candidates.yaml")
        candidates_path.write_text(
            yaml.dump(
                candidates_doc, allow_unicode=True, default_flow_style=False, sort_keys=False
            ),
            encoding="utf-8",
        )

        return EngineResult(
            engine_name=self.name,
            success=True,
            warnings=warnings,
            output_files=[str(yaml_path), str(candidates_path)],
            metadata={
                "n_cells": n_cells,
                "n_land": n_land,
                "habitability_counts": counts,
                "n_seed_candidates": len(candidates),
            },
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_mesh_with_habitability(
    mesh: CVTMesh, maps_output_dir: Path, planet_id: str | None
) -> None:
    """Write the habitability-populated mesh back to cvt_mesh.json.

    Overwrites the existing mesh file in place (matching the climate and ecology
    engines) so the frontend and downstream engines see the new fields.
    """
    from pydantic import TypeAdapter

    mesh_bytes = TypeAdapter(CVTMesh).dump_json(mesh)
    from ..map.export import _truncate_float_precision, compress_mesh_bytes

    mesh_bytes = _truncate_float_precision(mesh_bytes)
    mesh_bytes = compress_mesh_bytes(mesh_bytes)

    if planet_id is not None:
        target = maps_output_dir / planet_id / "cvt_mesh.json"
        if target.exists():
            target.write_bytes(mesh_bytes)
            logger.info("Updated mesh with habitability data: %s", target)
            return

    for mesh_path in maps_output_dir.glob("*/cvt_mesh.json"):
        mesh_path.write_bytes(mesh_bytes)
        logger.info("Updated mesh with habitability data: %s", mesh_path)


def _load_cvt_mesh(engine: CivilizationEngine) -> tuple[CVTMesh | None, list[str]]:
    """Load the CVT mesh, reusing the same logic as the climate engine."""
    from dreamulator.engine.climate import _load_cvt_mesh_from_geological

    return _load_cvt_mesh_from_geological(
        engine.layer_derived_dirs,
        engine.layer_input_dirs,
        maps_dir=engine.maps_output_dir,
    )


def _build_habitability_summary(
    mesh: CVTMesh,
    counts: dict[str, int],
    n_land: int,
    planet_id: str | None,
    planet_name: str | None,
) -> dict[str, object]:
    """Build a YAML-safe summary of the habitability/agriculture layers."""

    def land_frac(count: int) -> float | None:
        return round(count / n_land, 4) if n_land else None

    return {
        "planet": {
            "id": planet_id or "unknown",
            "name": planet_name or "unknown",
        },
        "n_cells": mesh.num_cells,
        "n_land": n_land,
        "habitable_coast": {
            "n_cells": counts["habitable_coast"],
            "land_fraction": land_frac(counts["habitable_coast"]),
        },
        "agricultural_core": {
            "n_cells": counts["agricultural_core"],
            "land_fraction": land_frac(counts["agricultural_core"]),
        },
        "overlap": {
            "n_cells": counts["overlap"],
            "land_fraction": land_frac(counts["overlap"]),
            "note": "habitable AND agricultural — coastal civilisation 'cradle'",
        },
        "habitable_not_agricultural": {
            "n_cells": counts["habitable_not_agricultural"],
            "land_fraction": land_frac(counts["habitable_not_agricultural"]),
            "note": "cool-wet oceanic ET (Faroese/Inuit-type) — settleable, not farmable",
        },
        "agricultural_not_habitable": {
            "n_cells": counts["agricultural_not_habitable"],
            "land_fraction": land_frac(counts["agricultural_not_habitable"]),
            "note": "inland warm land — farmable but outside the coastal threshold",
        },
        "neither": {
            "n_cells": counts["neither"],
            "land_fraction": land_frac(counts["neither"]),
        },
    }


def _build_seed_candidates_doc(
    candidates: list[dict[str, object]],
    planet_id: str | None,
    planet_name: str | None,
) -> dict[str, object]:
    """Build the YAML-safe seed-candidate document."""
    return {
        "planet": {
            "id": planet_id or "unknown",
            "name": planet_name or "unknown",
        },
        "n_candidates": len(candidates),
        "candidates": candidates,
    }
