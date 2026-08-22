"""Ecology engine — Whittaker biome classification, Miami NPP, domestication tags.

Reads the CVT mesh with climate data (temperature, precipitation, elevation)
already populated, and computes per-cell ecology properties.

Output files (written to ``layers/ecology/derived/``):
    - ecology_summary.yaml — per-cell biome, NPP, and domesticable tags summary
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.ecology_physics import (
    classify_cell_ecology,
    classify_soil,
)
from dreamulator.engine.physical_inputs import (
    load_planet_for_engine,
    resolve_stellar_forcing,
)
from dreamulator.map.biogeography import partition_biogeographic_provinces
from dreamulator.map.models import CVTMesh
from dreamulator.models.layers import Layer

logger = logging.getLogger(__name__)


class EcologyEngine(BaseEngine):
    """Compute per-cell ecology: biome, NPP, domestication, soil, province.

    Requires climate data (temperature, precipitation) already computed on the
    CVT mesh by the ClimateEngine.
    """

    name = "ecology"
    layer = Layer.ECOLOGY
    requires = ["climate", "geological"]  # geological for mesh, climate for T/P
    input_files: list[str] = []
    optional_input_files: list[str] = []
    output_files = [
        "ecology_summary.yaml",
    ]

    # Miami NPP assumes Earth-like sunshine.  The PAR ratio corrects for a
    # star's flux at the planet's orbit (S/S_earth = luminosity / distance²);
    # it is derived in run() from resolve_stellar_forcing and defaults to 1.0
    # when stellar data is unavailable.

    def run(
        self, parameters: dict[str, object] | None = None, *, force: bool = False
    ) -> EngineResult:  # noqa: ARG002
        """Run ecology classification on the CVT mesh.

        Steps:
            1. Load CVT mesh from geological derived data.
            2. Verify climate fields (temperature_C, precipitation_mm) exist.
            3. Resolve planet + PAR ratio from stellar forcing.
            4. Per cell: biome / NPP / domesticable tags + soil order/fertility.
            5. Partition land cells into biogeographic realms → provinces.
            6. Write ecology_summary.yaml and update cvt_mesh.json.

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
        if cells_with_temp == 0 or cells_with_precip == 0:
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=warnings
                + [
                    f"Climate data missing: {cells_with_temp}/{n_cells} cells have "
                    f"temperature, {cells_with_precip}/{n_cells} have precipitation. "
                    "Run the climate engine first.",
                ],
            )

        # ---- 3. Resolve planet + PAR ratio (needed before classification) ----
        planet, pwarnings = load_planet_for_engine(self)
        warnings.extend(pwarnings)
        planet_id = planet.id if planet is not None else None
        par_ratio = 1.0  # Earth-normal default
        if planet is not None:
            luminosity, distance, _, swarnings = resolve_stellar_forcing(self, planet)
            warnings.extend(swarnings)
            if luminosity is not None and distance is not None:
                par_ratio = luminosity / distance**2

        # ---- 4. Classify every cell (biome / NPP / domesticable / soil) ----
        biome_counts: dict[str, int] = {}
        for cell in mesh.cells:
            is_ocean = cell.elevation < 0.0
            eco = classify_cell_ecology(
                temperature_c=cell.temperature_C,
                precipitation_mm=cell.precipitation_mm,
                elevation_m=cell.elevation,
                is_ocean=is_ocean,
                par_ratio=par_ratio,
            )
            cell.biome = eco.biome.value
            cell.npp_gc_m2_yr = eco.npp_gc_m2_yr
            cell.domesticable_tags = eco.domesticable_tags

            soil_type, soil_fertility = classify_soil(
                temperature_c=cell.temperature_C,
                precipitation_mm=cell.precipitation_mm,
                elevation_m=cell.elevation,
                crust_type=cell.crust_type,
                is_ocean=is_ocean,
            )
            cell.soil_type = soil_type
            cell.soil_fertility = soil_fertility

            biome_counts[eco.biome.value] = biome_counts.get(eco.biome.value, 0) + 1

        # ---- 5. Biogeographic partition (realm → province) ----
        province_ids, province_meta = partition_biogeographic_provinces(mesh)
        for cell, pid in zip(mesh.cells, province_ids, strict=True):
            cell.biogeographic_province = pid

        # ---- 6. Write ecology data back to source mesh ----
        _write_mesh_with_ecology(mesh, self.maps_output_dir, planet_id)

        # ---- 7. Write summary YAML ----
        summary = _build_ecology_summary(
            mesh, biome_counts, planet_id, planet.name if planet else None, province_meta
        )
        import yaml

        eco_derived = self.layer_derived_dirs.get("ecology")
        if eco_derived is None:
            eco_derived = self.maps_output_dir / "ecology"
        yaml_path = eco_derived / "ecology_summary.yaml"
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(
            yaml.dump(summary, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        return EngineResult(
            engine_name=self.name,
            success=True,
            warnings=warnings,
            output_files=[
                str(yaml_path),
            ],
            metadata={
                "n_cells": n_cells,
                "biome_counts": biome_counts,
            },
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_mesh_with_ecology(mesh: CVTMesh, maps_output_dir: Path, planet_id: str | None) -> None:
    """Write the ecology-populated mesh back to cvt_mesh.json.

    Overwrites the existing mesh file in place so the frontend and downstream
    engines see the ecology fields. Targets the specific planet directory
    (matching the climate engine's ``_update_source_mesh``), falling back to a
    glob only when the planet id is unknown.
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
            logger.info("Updated mesh with ecology data: %s", target)
            return

    for mesh_path in maps_output_dir.glob("*/cvt_mesh.json"):
        mesh_path.write_bytes(mesh_bytes)
        logger.info("Updated mesh with ecology data: %s", mesh_path)


def _load_cvt_mesh(engine: EcologyEngine) -> tuple[CVTMesh | None, list[str]]:
    """Load the CVT mesh, reusing the same logic as the climate engine."""
    from dreamulator.engine.climate import _load_cvt_mesh_from_geological

    return _load_cvt_mesh_from_geological(
        engine.layer_derived_dirs,
        engine.layer_input_dirs,
        maps_dir=engine.maps_output_dir,
    )


def _build_ecology_summary(
    mesh: CVTMesh,
    biome_counts: dict[str, int],
    planet_id: str | None,
    planet_name: str | None,
    province_meta: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Build a YAML-safe summary of ecology outputs."""
    from collections import Counter

    n_cells = mesh.num_cells
    land_cells = [c for c in mesh.cells if c.crust_type == "continental"]
    ocean_cells = [c for c in mesh.cells if c.crust_type in ("oceanic", "transitional")]

    # Land NPP stats
    land_npp = [c.npp_gc_m2_yr for c in land_cells if c.npp_gc_m2_yr is not None]
    ocean_npp = [c.npp_gc_m2_yr for c in ocean_cells if c.npp_gc_m2_yr is not None]

    # Soil + biogeography stats
    soil_orders = Counter(c.soil_type for c in land_cells if c.soil_type is not None)
    soil_fertility = Counter(c.soil_fertility for c in land_cells if c.soil_fertility is not None)
    realms = {p["realm"] for p in province_meta.values()}

    return {
        "planet": {
            "id": planet_id or "unknown",
            "name": planet_name or "unknown",
        },
        "n_cells": n_cells,
        "n_land": len(land_cells),
        "n_ocean": len(ocean_cells),
        "biome_counts": biome_counts,
        "npp_gc_m2_yr": {
            "land": {
                "mean": sum(land_npp) / len(land_npp) if land_npp else None,
                "min": min(land_npp) if land_npp else None,
                "max": max(land_npp) if land_npp else None,
            },
            "ocean": {
                "mean": sum(ocean_npp) / len(ocean_npp) if ocean_npp else None,
            },
        },
        "soil": {
            "orders": dict(soil_orders),
            "fertility": dict(soil_fertility),
        },
        "biogeography": {
            "n_realms": len(realms),
            "n_provinces": len(province_meta),
        },
        "domesticable_highlights": {
            "high_large_herbivores": sum(
                1 for c in land_cells if "large_herbivores_high" in c.domesticable_tags
            ),
            "high_staple_crops": sum(
                1 for c in land_cells if "staple_crops_high" in c.domesticable_tags
            ),
            "high_draft_animals": sum(
                1 for c in land_cells if "draft_animals_high" in c.domesticable_tags
            ),
        },
    }
