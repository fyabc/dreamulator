"""Terrain generation pipeline orchestrator.

Runs the complete CVT terrain generation pipeline:
    1. CVT mesh generation (Fibonacci + Lloyd + SphericalVoronoi)
    2. Plate tectonics (Poisson-disc + Voronoi partition)
    3. Tectonic time evolution (Cortial et al. 2019: centroid rotation +
       subduction + collision)
    4. Boundary detection (velocity decomposition + classification)
    5. Terrain synthesis (bimodal base + boundary effects + fBm noise)
    6. Climate simulation (see climate_simulator + pipelines/climate-pipeline.md)
    7. Polar ice sheets (appended post-pass; coastline untouched)
    8. Export (equirectangular raster + PNG + JSON)

Rivers are not routed on the global mesh; the canvas chain computes drainage at high
resolution.  Closed below-sea-level basins are marked as lakes before the ice sheets.

See ``docs/design/pipelines/geological-pipeline.md`` for the algorithm
reference of stages 1-5/7-8 and ``climate-pipeline.md`` for stage 6.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import time
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
from rich.console import Console

from .boundary_detector import detect_boundaries
from .cvt_mesh import generate_cvt_mesh
from .export import export_equirectangular, save_outputs
from .geography import sample_raster_at_cells
from .plate_generator import generate_plates
from .terrain_cache import (
    CacheConfig,
    TerrainCache,
    build_stage_fingerprint,
)
from .terrain_synthesizer import synthesize_terrain

if TYPE_CHECKING:
    from pathlib import Path

    from .island_catalog import IslandCatalog
    from .models import CVTMesh, TectonicPlate
    from .orogen_contract import OrogenContract
    from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)
_console = Console(highlight=False)

# Valid stage names for partial pipeline execution
VALID_STAGES = frozenset(
    {
        "mesh",
        "plates",
        "tectonics",
        "boundaries",
        "terrain",
        "climate",
        "ice",
        "export",
    }
)

# Stage display names for stdout
_STAGE_NAMES: dict[str, str] = {
    "mesh": "1/8  CVT Mesh",
    "plates": "2/8  Plate Tectonics",
    "tectonics": "3/8  Tectonic Evolution",
    "boundaries": "4/8  Boundary Detection",
    "terrain": "5/8  Terrain Synthesis",
    "climate": "6/8  Climate Simulation",
    "ice": "7/8  Polar Ice Sheets",
    "export": "8/8  Export",
}


def _stage_begin(stage: str) -> None:
    """Print a user-facing stage header."""
    name = _STAGE_NAMES.get(stage, stage)
    _console.print(f"[bold bright_cyan]>>[/] [bold]{name}[/]")


def _stage_end(elapsed: float) -> None:
    """Print elapsed time for the just-completed stage."""
    if elapsed < 1.0:
        timing = f"{elapsed * 1000:.0f}ms"
    elif elapsed < 60:
        timing = f"{elapsed:.1f}s"
    else:
        mins = int(elapsed // 60)
        secs = elapsed % 60
        timing = f"{mins}m {secs:.0f}s"
    _console.print(f"  [bold green]done[/] [dim italic]({timing})[/]")


@dataclass
class TerrainPipelineResult:
    """Result of a terrain pipeline run."""

    mesh: CVTMesh | None = None
    plates: list[TectonicPlate] = field(default_factory=list)
    boundary_cell_ids: list[int] = field(default_factory=list)
    elevation_grid: np.ndarray | None = None
    stages_completed: list[str] = field(default_factory=list)
    stage_timings: dict[str, float] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    output_dir: Path | None = None
    orogen_contract: OrogenContract | None = None
    island_catalog: IslandCatalog | None = None


def _resolve_stages(requested: list[str] | None) -> list[str]:
    """Resolve requested stages to an ordered list.

    If ``requested`` is None, returns all stages in order.
    Otherwise validates and returns the requested stages in pipeline order.
    """
    all_stages = [
        "mesh",
        "plates",
        "tectonics",
        "boundaries",
        "terrain",
        "climate",
        "ice",
        "export",
    ]

    if requested is None:
        return all_stages

    # Validate
    for s in requested:
        if s not in VALID_STAGES:
            raise ValueError(f"Unknown stage '{s}'. Valid stages: {sorted(VALID_STAGES)}")

    # Return in pipeline order, only including requested
    return [s for s in all_stages if s in requested]


# Per-cell fields each cached stage writes in place (2026-09-17 nacrea
# landform-layer loss): stage pickles must capture these alongside their
# regular outputs, and cache hits must replay them onto the cells — otherwise
# an all-cache-hit rebuild exports a mesh with these fields empty.  When a
# stage gains a new in-place cell field, add it to the stage's save/replay
# payload here AND bump its _STAGE_SCHEMA_VERSIONS entry in terrain_cache.
_TECTONICS_CELL_FIELDS = (
    "cumulative_convergence_km",
    "cumulative_divergence_km",
    "convergent_duration_my",
    "convergent_run_km",
    "elevation",
    "crust_type",
)
_BOUNDARIES_CELL_FIELDS = (
    "distance_to_boundary_km",
    "convergence_rate_cm_yr",
    "tangential_fraction",
    "boundary_type",
)
# 2026-09-30 (user-reported all-cache-hit corruption): the plate path writes
# more in-place cell fields than the stage payloads captured — crust_type
# (base partition + geography re-anchor) and the tectonic-stage elevation
# baseline were silently lost on cache hits, so a plates/tectonics-hit +
# terrain-rerun build (first made reachable by terrain_only overlays, latent
# since the cache existed) synthesized terrain from crust-less cells and
# every authored continent vanished.  Payloads now capture + replay all
# in-place fields of their stage (schema versions bumped to invalidate the
# old pickles).
_PLATES_CELL_FIELDS = ("crust_type",)


def _cell_field_arrays(mesh: CVTMesh, fields: tuple[str, ...]) -> dict[str, np.ndarray]:
    """Snapshot per-cell field values for the stage cache (pickle-safe arrays)."""
    return {f: np.array([getattr(c, f) for c in mesh.cells]) for f in fields}


def _replay_cell_fields(mesh: CVTMesh, arrays: dict[str, np.ndarray]) -> None:
    """Re-apply cached per-cell field values onto the live mesh cells."""
    for f, arr in arrays.items():
        for cell, value in zip(mesh.cells, arr, strict=False):
            setattr(cell, f, value)


def run_terrain_pipeline(
    config: TerrainPipelineConfig,
    output_dir: Path | None = None,
    *,
    stages: list[str] | None = None,
    geography_raster: np.ndarray | None = None,
    cache: CacheConfig | None = None,
    geography_hash: str = "",
    source_fields: dict[str, np.ndarray] | None = None,
    tectonic_state: TerrainPipelineResult | None = None,
) -> TerrainPipelineResult:
    """Run the terrain generation pipeline.

    Args:
        config: Pipeline configuration.
        output_dir: Directory for output files. If None, no files are saved.
        stages: Optional list of stages to run. If None, runs all stages.
            Valid stages: mesh, plates, tectonics, boundaries, terrain,
            climate, ice, export.
        cache: Optional caching configuration. When enabled, intermediate
            results are saved to ``_cache/`` and re-used on subsequent runs
            when inputs haven't changed.
        geography_hash: SHA-256 of geography.yaml (optional). When provided
            and caching is enabled, geography-dependent stages are invalidated
            when the geography file changes.
        source_fields: Optional output mapping for frozen source-stage arrays.
            Capture reruns only terrain, while retaining valid upstream caches.
        tectonic_state: Explicit pre-terrain mesh, plates, boundaries and optional
            history contract. A private copy is consumed by the requested downstream
            stages. Callers retain and verify the source artifact's provenance.
            Requires an explicit downstream stage list and disabled stage caching.

    Returns:
        TerrainPipelineResult with generated data.
    """
    t_start = time.time()
    result = TerrainPipelineResult()

    ordered = _resolve_stages(stages)
    frozen_fingerprint = ""
    if tectonic_state is not None:
        if stages is None or any(
            s in ordered for s in ("mesh", "plates", "tectonics", "boundaries")
        ):
            raise ValueError("tectonic_state requires explicit downstream stages")
        if cache is not None and cache.enabled:
            raise ValueError("tectonic_state requires disabled stage caching")
        if tectonic_state.mesh is None or not tectonic_state.plates:
            raise ValueError("tectonic_state requires a mesh and plates")
        mesh = tectonic_state.mesh
        plate_ids = {p.id for p in tectonic_state.plates}
        if len(mesh.cells) != config.num_nodes or any(
            c.id != i or c.plate_id not in plate_ids for i, c in enumerate(mesh.cells)
        ):
            raise ValueError("tectonic_state cell count, ordering or plate assignment mismatch")
        area = sum(c.area_km2 for c in mesh.cells)
        if not np.isclose(area, 4 * np.pi * config.radius_km**2, rtol=1e-3):
            raise ValueError("tectonic_state radius differs from the requested terrain")
        frozen_fingerprint = hashlib.sha256(pickle.dumps(tectonic_state, protocol=5)).hexdigest()
        result = deepcopy(tectonic_state)
        result.stages_completed = []
        result.stage_timings = {}
        result.elapsed_seconds = 0.0
        result.output_dir = None
        result.elevation_grid = None
        if "terrain" in ordered:
            result.island_catalog = None
    logger.info(
        "Starting terrain pipeline: %s (seed=%d, nodes=%d)",
        " → ".join(ordered),
        config.seed,
        config.num_nodes,
    )

    # ---- Initialise per-stage cache ----
    tc: TerrainCache | None = None
    use_cache = cache is not None and cache.enabled
    upstream_fps: dict[str, str] = {}  # upstream stage → fingerprint
    if frozen_fingerprint:
        upstream_fps["boundaries"] = frozen_fingerprint
    if use_cache and output_dir is not None:
        tc = TerrainCache(output_dir)
        _console.print(f"  [dim]Cache: {tc.cache_dir}[/dim]")

    # ---- Stage 1: CVT Mesh ----
    if "mesh" in ordered:
        mesh_fp = build_stage_fingerprint("mesh", config)
        upstream_fps["mesh"] = mesh_fp
        if tc is not None and tc.has_valid("mesh", mesh_fp):
            _console.print("  [dim]mesh: cache hit, loading…[/dim]")
            t = time.time()
            result.mesh = tc.load("mesh")
            if result.mesh is not None:
                result.stages_completed.append("mesh")
                result.stage_timings["mesh"] = time.time() - t
                _stage_end(result.stage_timings["mesh"])
        if result.mesh is None:
            _stage_begin("mesh")
            t = time.time()
            result.mesh = generate_cvt_mesh(config)
            result.stages_completed.append("mesh")
            result.stage_timings["mesh"] = time.time() - t
            _stage_end(result.stage_timings["mesh"])
            if tc is not None:
                tc.save("mesh", result.mesh, mesh_fp)

    if result.mesh is None:
        raise RuntimeError("CVT mesh is required for subsequent stages. Run 'mesh' stage first.")

    # Dense authored raster bias (Gleba-style probability map), sampled once
    # per mesh and shared by crust anchoring, uplift suppression and pins.
    raster_bias = (
        sample_raster_at_cells(result.mesh, geography_raster)
        if geography_raster is not None and config.geography is not None
        else None
    )

    # Plate-stage view of the authored geography (2026-09-30): terrain-only
    # overlays are invisible to plate seeds / crust partition / coast cost and
    # excluded from these stages' fingerprints, so editing them cannot
    # reshuffle the global plate realization (new ridges, islets, coasts).
    # The terrain stage below still consumes the full spec + full-file hash.
    if config.geography is not None:
        _plates_geo_hash = config.geography.plates_fingerprint()
        _config_plates = replace(config, geography=config.geography.plate_view())
    else:
        _plates_geo_hash = geography_hash
        _config_plates = config

    # ---- Stage 2: Plate Tectonics ----
    if "plates" in ordered:
        plates_fp = build_stage_fingerprint(
            "plates",
            config,
            geography_hash=_plates_geo_hash,
            upstream_fingerprints=upstream_fps,
        )
        upstream_fps["plates"] = plates_fp
        if tc is not None and tc.has_valid("plates", plates_fp):
            _console.print("  [dim]plates: cache hit, loading…[/dim]")
            t = time.time()
            cached = tc.load("plates")
            if cached is not None:
                result.plates, cell_plate_map, plate_cell_fields = cached
                _replay_cell_fields(result.mesh, plate_cell_fields)
                result.stages_completed.append("plates")
                result.stage_timings["plates"] = time.time() - t
                _stage_end(result.stage_timings["plates"])
        if not result.plates:
            _stage_begin("plates")
            t = time.time()
            result.plates, cell_plate_map = generate_plates(
                result.mesh, _config_plates, raster_bias=raster_bias
            )
            result.stages_completed.append("plates")
            result.stage_timings["plates"] = time.time() - t
            _stage_end(result.stage_timings["plates"])
            if tc is not None:
                tc.save(
                    "plates",
                    (
                        result.plates,
                        cell_plate_map,
                        _cell_field_arrays(result.mesh, _PLATES_CELL_FIELDS),
                    ),
                    plates_fp,
                )
    else:
        # Reconstruct cell_plate_map from existing plate data
        cell_plate_map = {}
        for cell in result.mesh.cells:
            if cell.plate_id:
                cell_plate_map[cell.id] = cell.plate_id

    # ---- Stage 3: Tectonic Time Evolution (Cortial 2019) ----
    if "tectonics" in ordered:
        if not result.plates:
            raise RuntimeError(
                "Plates are required for tectonic evolution. Run 'plates' stage first."
            )
        tectonics_fp = build_stage_fingerprint(
            "tectonics",
            config,
            geography_hash=_plates_geo_hash,
            upstream_fingerprints=upstream_fps,
        )
        upstream_fps["tectonics"] = tectonics_fp
        if tc is not None and tc.has_valid("tectonics", tectonics_fp):
            _console.print("  [dim]tectonics: cache hit, loading…[/dim]")
            t = time.time()
            cached = tc.load("tectonics")
            if cached is not None:
                result.plates, cell_plate_map, cumulative_fields = cached
                _replay_cell_fields(result.mesh, cumulative_fields)
                result.stages_completed.append("tectonics")
                result.stage_timings["tectonics"] = time.time() - t
                _stage_end(result.stage_timings["tectonics"])
        if "tectonics" not in result.stages_completed:
            _stage_begin("tectonics")
            t = time.time()
            from .tectonic_simulator import run_tectonic_evolution

            # Rich progress bar for long-running tectonic steps
            progress_cb = None
            _progress = None
            try:
                from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

                _progress = Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[dim]{task.percentage:>3.0f}%[/]"),
                    TimeRemainingColumn(),
                    transient=True,
                )
                task_id = _progress.add_task(
                    "  Tectonic steps",
                    total=config.tectonic_steps,
                )
                _progress.start()

                def _cb(step: int, total: int) -> None:
                    if _progress is not None:
                        # duration mode derives the step count inside the evolution
                        _progress.update(task_id, completed=step, total=total)

                progress_cb = _cb
            except ImportError:
                pass

            result.plates, cell_plate_map = run_tectonic_evolution(
                result.mesh,
                result.plates,
                _config_plates,
                progress_callback=progress_cb,
                raster_bias=raster_bias,
            )
            if _progress is not None:
                _progress.stop()

            # Re-anchor crust to authored geography (plate view — terrain-only
            # overlays must not restamp crust here; they act at terrain stage)
            if config.geography is not None and config.geography.reapply_after_tectonics:
                from .geography import apply_geography_crust

                apply_geography_crust(result.mesh, _config_plates, raster_bias=raster_bias)

            result.stages_completed.append("tectonics")
            result.stage_timings["tectonics"] = time.time() - t
            _stage_end(result.stage_timings["tectonics"])
            if tc is not None:
                tc.save(
                    "tectonics",
                    (
                        result.plates,
                        cell_plate_map,
                        _cell_field_arrays(result.mesh, _TECTONICS_CELL_FIELDS),
                    ),
                    tectonics_fp,
                )

    # Re-apply the plate assignment onto the mesh cells.  On cache hits the
    # (plates, cell_plate_map) pair is restored from the pickle, but the
    # in-place ``cell.plate_id = ...`` side effects of generate_plates /
    # run_tectonic_evolution are NOT replayed — and the mesh cache was saved
    # before the plates stage, so its cells carry plate_id=None.  Without this
    # the exported mesh file loses all per-cell plate assignments while
    # plates.json (written from result.plates) stays intact.  Idempotent on
    # fresh runs (the map matches the in-place values).
    if cell_plate_map:
        for _cid, _pid in cell_plate_map.items():
            result.mesh.cells[_cid].plate_id = _pid

    # ---- Stage 4: Boundary Detection ----
    if "boundaries" in ordered:
        if not result.plates:
            raise RuntimeError(
                "Plates are required for boundary detection. Run 'plates' stage first."
            )
        boundaries_fp = build_stage_fingerprint(
            "boundaries",
            config,
            upstream_fingerprints=upstream_fps,
        )
        upstream_fps["boundaries"] = boundaries_fp
        if tc is not None and tc.has_valid("boundaries", boundaries_fp):
            _console.print("  [dim]boundaries: cache hit, loading…[/dim]")
            t = time.time()
            cached = tc.load("boundaries")
            if cached is not None:
                result.boundary_cell_ids, boundary_fields = cached
                _replay_cell_fields(result.mesh, boundary_fields)
                result.stages_completed.append("boundaries")
                result.stage_timings["boundaries"] = time.time() - t
                _stage_end(result.stage_timings["boundaries"])
        if "boundaries" not in result.stages_completed:
            _stage_begin("boundaries")
            t = time.time()
            result.boundary_cell_ids = detect_boundaries(
                result.mesh, result.plates, cell_plate_map, config
            )
            result.stages_completed.append("boundaries")
            result.stage_timings["boundaries"] = time.time() - t
            _stage_end(result.stage_timings["boundaries"])
            if tc is not None:
                tc.save(
                    "boundaries",
                    (
                        result.boundary_cell_ids,
                        _cell_field_arrays(result.mesh, _BOUNDARIES_CELL_FIELDS),
                    ),
                    boundaries_fp,
                )

    # ---- Stage 5: Terrain Synthesis ----
    if "terrain" in ordered:
        if not result.plates:
            raise RuntimeError(
                "Plates are required for terrain synthesis. Run 'plates' stage first."
            )
        # History contract, orogen part (history-contract.md §3): convergent segments
        # and their shortening history, read from the tectonic-stage fields.
        from .orogen_contract import build_orogen_contract

        if result.orogen_contract is None:
            result.orogen_contract = build_orogen_contract(
                result.mesh,
                result.plates,
                config.radius_km,
                config.collision_overrides,
                max_onset_myr=config.tectonic_duration_my or None,
                subduction_polarities=config.subduction_polarities,
            )
        for _w in result.orogen_contract.warnings:
            logger.warning("  Collision history: %s", _w)
        for _w in result.orogen_contract.notes:
            logger.info("  Collision history: %s", _w)
        terrain_fp = build_stage_fingerprint(
            "terrain",
            config,
            geography_hash=geography_hash,
            upstream_fingerprints=upstream_fps,
        )
        upstream_fps["terrain"] = terrain_fp
        if tc is not None and tc.has_valid("terrain", terrain_fp) and source_fields is None:
            _console.print("  [dim]terrain: cache hit, loading…[/dim]")
            t = time.time()
            cached_arrays = tc.load("terrain")
            if cached_arrays is not None:
                _el, _cr, _bt, _lf, _hs, _lk, _cat = cached_arrays
                from .island_catalog import remember_synthesis_catalog

                remember_synthesis_catalog(_cat)
                for _i in range(len(result.mesh.cells)):
                    result.mesh.cells[_i].elevation = float(_el[_i])
                    result.mesh.cells[_i].crust_type = str(_cr[_i])
                    result.mesh.cells[_i].boundary_type = str(_bt[_i]) if _bt[_i] else None
                    result.mesh.cells[_i].landform = str(_lf[_i]) if _lf[_i] else None
                    result.mesh.cells[_i].hotspot_id = str(_hs[_i]) if _hs[_i] else None
                    result.mesh.cells[_i].is_lake = bool(_lk[_i])
                from .orogen_contract import resolve_contract_polarities

                resolve_contract_polarities(
                    result.mesh,
                    result.plates,
                    result.orogen_contract,
                    config.radius_km,
                    stage="terrain-crust",
                )
                result.stages_completed.append("terrain")
                result.stage_timings["terrain"] = time.time() - t
                _stage_end(result.stage_timings["terrain"])
        if "terrain" not in result.stages_completed:
            _stage_begin("terrain")
            t = time.time()
            synthesize_terrain(
                result.mesh,
                result.plates,
                config,
                raster_bias=raster_bias,
                orogen_contract=result.orogen_contract,
                source_fields=source_fields,
            )
            result.stages_completed.append("terrain")
            result.stage_timings["terrain"] = time.time() - t
            _stage_end(result.stage_timings["terrain"])
            if tc is not None:
                # Only cache the fields that terrain synthesis modifies
                # (not the full CVTMesh with 200k Pydantic cells).
                _n = len(result.mesh.cells)
                _elev = np.array([c.elevation for c in result.mesh.cells], dtype=np.float64)
                _crust = np.array([c.crust_type for c in result.mesh.cells], dtype=object)
                _btype = np.array([c.boundary_type or "" for c in result.mesh.cells], dtype=object)
                _landform = np.array([c.landform or "" for c in result.mesh.cells], dtype=object)
                _hotspot = np.array([c.hotspot_id or "" for c in result.mesh.cells], dtype=object)
                # deposition fill leaves some closed basins as lakes
                _lake = np.array([c.is_lake for c in result.mesh.cells], dtype=bool)
                from .island_catalog import peek_synthesis_catalog

                tc.save(
                    "terrain",
                    (_elev, _crust, _btype, _landform, _hotspot, _lake, peek_synthesis_catalog()),
                    terrain_fp,
                )

        # water_class (land/ocean split) is geological — elevation + sea level +
        # ocean connectivity — not a climate field.  Write it here so the climate
        # engine and frontend read it directly, and a `--only geological` rebuild
        # no longer leaves it at the "ocean" default (coastline disappearance).
        from .water_bodies import compute_land_mask

        _is_land = compute_land_mask(result.mesh.cells, config.sea_level_offset_m)
        for _i, _c in enumerate(result.mesh.cells):
            _c.water_class = "land" if bool(_is_land[_i]) else "ocean"

        # Sub-grid relief and peak elevation of land cells (knowledge/geology/
        # orogen_topography.md §1): a deterministic function of the cell-mean field,
        # recomputed after a cache hit.
        from .subgrid_relief import subgrid_relief

        _std, _peak = subgrid_relief(result.mesh, config.radius_km, config.sea_level_offset_m)
        for _i, _c in enumerate(result.mesh.cells):
            _c.relief_std_m = None if np.isnan(_std[_i]) else float(_std[_i])
            _c.peak_elevation_m = None if np.isnan(_peak[_i]) else float(_peak[_i])

        # Trench axis point depth (knowledge/geology/orogen_topography.md §5): the axis
        # offset of the flexure profile below the final cell mean, ocean axis cells only.
        if (
            result.orogen_contract is not None
            and result.plates
            and config.terrain_algorithm == "cortial2019_asymmetric"
        ):
            from .trench_flexure import trench_relief

            _, _axis, _ = trench_relief(
                result.mesh,
                result.plates,
                result.orogen_contract,
                config.radius_km,
                config.gravity_m_s2,
            )
            for _i, _c in enumerate(result.mesh.cells):
                _ok = not np.isnan(_axis[_i]) and _c.elevation <= config.sea_level_offset_m
                _c.trench_axis_elevation_m = _c.elevation + float(_axis[_i]) if _ok else None

        # Sub-grid island catalogue (island-catalog.md): the catalogue of terrain synthesis (kept
        # in the terrain cache), summits and emergent areas on the final surface, summaries.
        if config.terrain_algorithm == "cortial2019_asymmetric" and result.plates:
            from .island_catalog import (
                build_island_catalog,
                summarise_islands,
                take_synthesis_catalog,
                volcano_cell_mean,
            )

            # the volcanoes whose volume terrain synthesis put into the cell means
            result.island_catalog = take_synthesis_catalog() or build_island_catalog(
                result.mesh, result.plates, config, orogen_contract=result.orogen_contract
            )
            _contrib = volcano_cell_mean(result.mesh, result.island_catalog, config.radius_km)
            _isl = summarise_islands(
                result.mesh, result.island_catalog, _contrib, config.sea_level_offset_m
            )
            for _i, _c in enumerate(result.mesh.cells):
                _c.island_count = int(_isl["island_count"][_i])
                _c.island_area_frac = float(_isl["island_area_frac"][_i])
                _pk = _isl["island_peak_m"][_i]
                _c.island_peak_m = None if np.isnan(_pk) else float(_pk)
                if _contrib[_i] > 0.0 and _c.peak_elevation_m is not None:
                    # on a volcanic edifice the highest point is the catalogue summit, not the
                    # slope statistics calibrated on continental relief
                    _c.peak_elevation_m = max(
                        _c.elevation, _c.island_peak_m if _c.island_peak_m is not None else -1e9
                    )
                _c.hotspot_id = None
            for _v in result.island_catalog.volcanoes:
                if _v.kind == "hotspot":
                    result.mesh.cells[_v.cell].hotspot_id = _v.source

    # ---- Stage 6: Climate ----
    if "climate" in ordered:
        _stage_begin("climate")
        try:
            from .climate_simulator import simulate_climate

            t = time.time()
            simulate_climate(result.mesh, config)
            result.stages_completed.append("climate")
            result.stage_timings["climate"] = time.time() - t
            _stage_end(result.stage_timings["climate"])
        except NotImplementedError as e:
            _console.print(f"  [dim]skipped: {type(e).__name__}[/]")
            logger.info("  skipped: %s", str(e).split("\n")[0])

    # ---- Closed-basin lakes: below-sea-level basins cut off from the global ocean are
    #      lakes (climate, ecology, civilization and the land/ocean split read is_lake).
    #      Marked on the terrain surface, before the ice sheets stack onto land. ----
    if result.mesh is not None and ("ice" in ordered or "export" in ordered):
        from .hydrology import mark_closed_basin_lakes

        mark_closed_basin_lakes(result.mesh, config.sea_level_offset_m)

    # ---- Stage 7: Polar ice sheets (the calibrated coastline is untouched, ice only
    #      stacks onto land cells) ----
    if "ice" in ordered:
        _stage_begin("ice")
        t = time.time()
        from .ice_sheets import apply_polar_ice_sheets

        apply_polar_ice_sheets(result.mesh, config)
        result.stages_completed.append("ice")
        result.stage_timings["ice"] = time.time() - t
        _stage_end(result.stage_timings["ice"])

    # ---- Stage 8: Export ----
    if "export" in ordered:
        _stage_begin("export")
        t = time.time()

        # Large endorheic lakes (Caspian analogues) are ocean-like for climate —
        # the same size split the GSHHG import applies on the real Earth.  Runs
        # after the closed-basin lakes are marked (is_lake): those are the
        # climate-relevant inland seas — terrain-stage deposition lakes alone
        # undercount them.
        from .water_bodies import upgrade_large_endorheic_lakes

        _n_upgraded = upgrade_large_endorheic_lakes(result.mesh.cells, config.sea_level_offset_m)
        if _n_upgraded:
            _console.print(f"  [dim]large endorheic lakes → ocean-like: {_n_upgraded} cells[/dim]")

        result.elevation_grid = export_equirectangular(
            result.mesh,
            config.export_width,
            config.export_height,
            field="elevation",
        )

        if output_dir is not None:
            save_outputs(
                result.mesh,
                result.plates,
                result.elevation_grid,
                output_dir,
                config,
            )
            if result.orogen_contract is not None:
                from .orogen_contract import save_orogen_contract

                save_orogen_contract(
                    output_dir / "orogen_contract.json",
                    result.orogen_contract,
                    mesh=result.mesh,
                    radius_km=config.radius_km,
                )
            if result.island_catalog is not None:
                import json as _json

                from .island_catalog import catalog_to_json

                (output_dir / "island_catalog.json").write_text(
                    _json.dumps(catalog_to_json(result.island_catalog), ensure_ascii=False),
                    encoding="utf-8",
                )
            if source_fields:
                from .island_source import catalogue_geometry
                from .terrain_source_export import save_terrain_source_fields

                save_terrain_source_fields(
                    output_dir / "terrain_sources.npz",
                    source_fields,
                    radius_km=config.radius_km,
                    source={
                        "terrain_fingerprint": upstream_fps.get("terrain"),
                        "seed": config.seed,
                        "sea_level_m": config.sea_level_offset_m,
                        "island_geometry": (
                            catalogue_geometry(result.island_catalog)
                            if result.island_catalog is not None
                            else None
                        ),
                        "polarity_stage": (
                            result.orogen_contract.polarity_stage
                            if result.orogen_contract is not None
                            else None
                        ),
                    },
                )
            elif (output_dir / "terrain_sources.json").exists():
                import json as _source_json

                source_path = output_dir / "terrain_sources.json"
                previous = _source_json.loads(source_path.read_text(encoding="utf-8"))
                if previous.get("source", {}).get("terrain_fingerprint") != upstream_fps.get(
                    "terrain"
                ):
                    (output_dir / "terrain_sources.npz").unlink(missing_ok=True)
                    source_path.unlink()
            result.output_dir = output_dir

        result.stages_completed.append("export")
        result.stage_timings["export"] = time.time() - t
        _stage_end(result.stage_timings["export"])

    result.elapsed_seconds = time.time() - t_start
    if result.elapsed_seconds < 60:
        total_timing = f"{result.elapsed_seconds:.1f}s"
    else:
        mins = int(result.elapsed_seconds // 60)
        secs = result.elapsed_seconds % 60
        total_timing = f"{mins}m {secs:.0f}s"
    _console.print(
        f"[bold green]Pipeline complete[/] "
        f"({' -> '.join(result.stages_completed)}) "
        f"[dim italic](total {total_timing})[/]",
    )

    return result
