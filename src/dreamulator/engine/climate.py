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
import shutil
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

        # Model-state vs obs-state separation (CLAUDE.md「核心设计原则」): the
        # earth root is a real-data reference anchor — the climate engine never
        # writes model fields to it.  Model output lives on branches; the root's
        # climate fields come from import_earth_climate (real observation).
        if self._branch_name() is None and _is_reference_anchor(self.world_dir):
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=[
                    f"'{self.world_dir.name}' 是真实数据参照世界（reference_anchor=true）："
                    f"root 永不 build 模型层。temperature/precipitation/koppen 只写在分支上——"
                    f"用 `dreamulator build {self.world_dir.name} --branch <名>` 构建模型层；"
                    f"root 的真实观测由 import_earth_climate 写入。"
                ],
            )

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
        mesh, mesh_source, mwarnings = _load_cvt_mesh_from_geological(
            self.layer_derived_dirs,
            self.layer_input_dirs,
            maps_dir=self.maps_output_dir,
            planet_id=planet.id,
            world_dir=self.world_dir,
        )
        warnings.extend(mwarnings)
        if mesh is None:
            recovery = self._dev_data_recovery_hint(config, planet.id)
            return EngineResult(
                engine_name=self.name,
                success=False,
                warnings=warnings + ["No CVT mesh found in geological derived data", recovery],
            )

        # ---- 4b. Materialize a branch-local mesh copy ----
        # Climate writes its fields back into cvt_mesh.json.  When the mesh was
        # inherited from outside this build's maps directory (typically the
        # root world's mesh, via a branch that forked before climate), writing
        # in place would leak branch climate fields into the shared parent
        # baseline — copy first, then all writes stay inside the branch
        # (M1-P0: 分支不回写父世界 / base-mesh isolation).
        mesh_target = _materialize_writable_mesh(mesh_source, self.maps_output_dir, planet.id)

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
        self._update_source_mesh(mesh, mesh_target)

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

    def _update_source_mesh(self, mesh: CVTMesh, target: Path) -> None:
        """Write climate-populated mesh back to cvt_mesh.json.

        ``target`` is the mesh's writable location — for branch builds this is
        the branch-local copy materialized before the simulation (step 4b), so
        branch climate fields never leak into the parent world's baseline
        mesh.  For root builds the target is the canonical
        ``maps/{planet_id}/cvt_mesh.json``; the legacy layer-based fallback is
        root-build compat only and is never reached from a branch.

        Uses the pydantic-core serializer (Rust, ~5x faster than
        model_dump() + json.dump()); non-finite floats serialize as null.
        """
        # model_dump_json() returns str; write_bytes needs bytes.
        mesh_bytes = mesh.model_dump_json().encode("utf-8")
        from ..map.export import _truncate_float_precision, compress_mesh_bytes

        mesh_bytes = _truncate_float_precision(mesh_bytes)
        mesh_bytes = compress_mesh_bytes(mesh_bytes)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(mesh_bytes)
            logger.info("Updated source mesh with climate data: %s", target)
            return
        except Exception as e:
            logger.warning("Failed to update %s: %s", target, e)

        if self.maps_output_dir == self.world_dir / "maps":
            # Root build with a legacy layout (maps under layers/geological/
            # derived/maps/): keep the old write location working.
            for layer_dirs in (self.layer_derived_dirs, self.layer_input_dirs):
                geo_dir = layer_dirs.get("geological")
                if not geo_dir:
                    continue
                for mesh_path in geo_dir.glob("maps/*/cvt_mesh.json"):
                    try:
                        mesh_path.write_bytes(mesh_bytes)
                        logger.info("Updated source mesh with climate data: %s", mesh_path)
                        return
                    except Exception as e:
                        logger.warning("Failed to update %s: %s", mesh_path, e)

        logger.warning("No source cvt_mesh.json found to update with climate data")

    def _branch_name(self) -> str | None:
        """Branch this engine writes into (None for root-world builds)."""
        try:
            rel = self.maps_output_dir.relative_to(self.world_dir)
        except ValueError:
            return None
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == "branches":
            return parts[1]
        return None

    def _dev_data_recovery_hint(self, config: TerrainPipelineConfig, planet_id: str) -> str:
        """Recovery message for a missing mesh: prefer ``data fetch`` when indexed."""
        if config.elevation_source == "imported":
            from dreamulator.datapkg import fetch_hint

            hint = fetch_hint(
                self.world_dir.name, self._branch_name(), planet_id, config.terrain_import
            )
            if hint is not None:
                return hint
            return (
                "Restore imported terrain first (docs/usage/climate-validation-"
                "workflow.md), e.g.:\n"
                "  uv sync --extra validation\n"
                f"  uv run python scripts/earth/import_earth_elevation.py "
                f"--output-dir {self.maps_output_dir / planet_id} "
                "--mesh-nodes 200000 --seed 42"
            )
        return (
            "Generate terrain first: uv run dreamulator build <world> "
            "[--branch <branch>] (geological stage), or import real data "
            "(Earth) via scripts/earth/."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _mesh_candidates(base: Path, planet_id: str | None) -> list[Path]:
    """Mesh paths under a ``maps/`` root, exact planet match first.

    Excludes ``_``-prefixed scratch directories (_baseline_*/_cache_* …) —
    the climate engine must load the real planet mesh, not a stale baseline.
    """
    if not base.exists():
        return []
    out: list[Path] = []
    if planet_id:
        exact = base / planet_id / "cvt_mesh.json"
        if exact.exists():
            out.append(exact)
    for p in sorted(base.glob("*/cvt_mesh.json")):
        if p.parent.name.startswith("_"):
            continue
        if p not in out:
            out.append(p)
    return out


def _is_reference_anchor(world_dir: Path) -> bool:
    """True when the world is a real-data reference anchor (earth root).

    Such worlds are never built through the simulation pipeline for the model
    (climate + downstream) layers — their fields come from real observation
    (``import_earth_climate``), and model output lives on branches only.
    (CLAUDE.md「模型态 vs obs 态分离」)
    """
    try:
        data = yaml.safe_load((world_dir / "world.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    return bool((data or {}).get("reference_anchor", False))


def _materialize_writable_mesh(
    mesh_source: Path | None, maps_output_dir: Path, planet_id: str
) -> Path:
    """Return a writable mesh path inside this build's maps directory.

    When the loaded mesh already lives under ``maps_output_dir`` (same build
    context), it is returned as-is.  When it was inherited from outside — the
    root world's mesh consumed by a branch build — a copy is materialized at
    ``maps_output_dir/<planet_id>/cvt_mesh.json`` so that subsequent field
    write-backs (climate/ecology/civilization) never modify the parent
    baseline mesh (M1-P0).
    """
    target = maps_output_dir / planet_id / "cvt_mesh.json"
    if mesh_source is None or mesh_source == target:
        return target
    try:
        mesh_source.relative_to(maps_output_dir)
        return mesh_source  # already inside this build's maps directory
    except ValueError:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(mesh_source, target)
        logger.info(
            "Materialized branch mesh copy: %s (source: %s — parent mesh stays untouched)",
            target,
            mesh_source,
        )
    return target


def _load_cvt_mesh_from_geological(
    layer_derived_dirs: dict[str, Path],
    layer_input_dirs: dict[str, Path] | None = None,
    maps_dir: Path | None = None,
    *,
    planet_id: str | None = None,
    world_dir: Path | None = None,
) -> tuple[CVTMesh | None, Path | None, list[str]]:
    """Load the CVT mesh, planet-scoped, with parent-world inheritance.

    Candidate locations, most specific first:

    1. this build's unified ``maps/`` — exact ``maps/{planet_id}/`` match
       before any non-scratch planet directory
    2. the root world's ``maps/`` (same rule) — branch builds inherit the
       parent's mesh when the branch has none of its own
    3. legacy layer-based ``maps/`` locations under the geological layer

    Args:
        layer_derived_dirs: Map of layer name → derived directory.
        layer_input_dirs: Map of layer name → input directory.
        maps_dir: Unified maps output directory for this build (branch or root).
        planet_id: Target planet — selects the exact mesh instead of the
            first glob hit.
        world_dir: Root world directory, enabling parent-map inheritance.

    Returns:
        (mesh, source path, warnings).  Source path is None iff mesh is None.
    """
    from ..map.export import decompress_mesh_bytes

    candidates: list[Path] = []
    if maps_dir is not None:
        candidates.extend(_mesh_candidates(maps_dir, planet_id))
    if world_dir is not None and (world_dir / "maps") != maps_dir:
        candidates.extend(_mesh_candidates(world_dir / "maps", planet_id))

    # Legacy layer-based locations (pre-migration layouts).
    legacy_dirs: list[Path] = []
    geo_derived = layer_derived_dirs.get("geological")
    if geo_derived is not None:
        legacy_dirs.append(geo_derived)
    if layer_input_dirs:
        geo_input = layer_input_dirs.get("geological")
        if geo_input is not None:
            legacy_dirs.append(geo_input)
    for d in legacy_dirs:
        for p in sorted(d.glob("maps/*/cvt_mesh.json")):
            if not p.parent.name.startswith("_") and p not in candidates:
                candidates.append(p)

    if not candidates:
        searched = [
            str(maps_dir) if maps_dir is not None else "(no maps dir)",
            *([str(world_dir / "maps")] if world_dir is not None else []),
            *[str(d / "maps") for d in legacy_dirs],
        ]
        return None, None, [f"No cvt_mesh.json found in: {searched}"]

    for mesh_path in candidates:
        try:
            # pydantic-core JSON parser (Rust) — faster than
            # json.load() + CVTMesh(**data) for the 80+ MB mesh.
            mesh = TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(mesh_path.read_bytes()))
            return mesh, mesh_path, []
        except Exception as e:
            return None, None, [f"Failed to load CVT mesh from {mesh_path}: {e}"]

    return None, None, ["No loadable cvt_mesh.json found"]


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
