"""Export CVT mesh data to equirectangular raster grids.

Converts scattered CVT cell data (on the sphere) to regular lat/lon grids
suitable for PNG export, map visualization, and Gaea import.

See ``docs/design/terrain-pipeline.md`` §11 for algorithm details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from .models import CVTMesh, TectonicPlate
from .pipeline_types import TerrainPipelineConfig, make_equirect_grid

if TYPE_CHECKING:
    from scipy.spatial import cKDTree  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Equirectangular interpolation
# ---------------------------------------------------------------------------


def build_export_tree(mesh: CVTMesh) -> "cKDTree":
    """Build the unit-sphere KD-tree for equirectangular export.

    Callers exporting multiple fields for the same mesh should build this
    once and pass it to ``export_equirectangular`` (Stage 0.3: avoids
    rebuilding the tree per field).
    """
    from scipy.spatial import cKDTree  # type: ignore[import-untyped]

    cell_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells])
    return cKDTree(cell_xyz)


def export_equirectangular(
    mesh: CVTMesh,
    width: int = 4096,
    height: int = 2048,
    field: str = "elevation",
    tree: "cKDTree | None" = None,
) -> np.ndarray:
    """Interpolate CVT cell data onto a regular equirectangular grid.

    Uses scipy's nearest-neighbor interpolation on the sphere (via
    SphericalVoronoi-based lookup or angular distance).

    Args:
        mesh: The CVT mesh.
        width: Output grid width in pixels.
        height: Output grid height in pixels.
        field: Cell attribute to export (e.g. "elevation", "temperature_C").

    Returns:
        2D array of shape (height, width).
    """
    logger.info(
        "Exporting '%s' to equirectangular grid (%d×%d)",
        field,
        width,
        height,
    )

    # KD-tree on unit sphere for fast nearest-neighbor lookup (reused
    # across fields when the caller passes a pre-built tree)
    if tree is None:
        tree = build_export_tree(mesh)

    # Create output grid
    lat_grid, lon_grid = make_equirect_grid(width, height)

    # Convert grid to Cartesian on unit sphere
    cos_lat = np.cos(lat_grid)
    grid_x = cos_lat * np.cos(lon_grid)
    grid_y = np.sin(lat_grid)
    grid_z = cos_lat * np.sin(lon_grid)

    # Flatten for KD-tree query
    grid_flat = np.column_stack([
        grid_x.ravel(),
        grid_y.ravel(),
        grid_z.ravel(),
    ])

    # Query nearest cell for each grid point
    _, indices = tree.query(grid_flat)

    # Extract field values
    cell_values = np.array(
        [getattr(mesh.cells[i], field, 0.0) for i in range(mesh.num_cells)],
        dtype=np.float64,
    )
    result = cell_values[indices].reshape(height, width)

    logger.info(
        "  Export complete: range [%.2f, %.2f]",
        np.min(result),
        np.max(result),
    )
    return result


def export_multiple_fields(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    fields: list[str] | None = None,
) -> dict[str, np.ndarray]:
    """Export multiple cell fields to equirectangular grids.

    Args:
        mesh: The CVT mesh.
        config: Pipeline configuration.
        fields: List of field names. Defaults to ["elevation"].

    Returns:
        Dict of field_name → 2D grid.
    """
    if fields is None:
        fields = ["elevation"]

    tree = build_export_tree(mesh)
    results = {}
    for field_name in fields:
        results[field_name] = export_equirectangular(
            mesh,
            config.export_width,
            config.export_height,
            field=field_name,
            tree=tree,
        )
    return results


# ---------------------------------------------------------------------------
# PNG export
# ---------------------------------------------------------------------------


def export_elevation_png(
    elevation: np.ndarray,
    path: Path,
    min_m: float = -11_000.0,
    max_m: float = 9_000.0,
) -> None:
    """Export elevation grid as 16-bit PNG.

    Elevation is normalized to [0, 65535] using the given range.

    Args:
        elevation: 2D elevation grid in metres.
        path: Output file path.
        min_m: Minimum elevation for normalization.
        max_m: Maximum elevation for normalization.
    """
    # Normalize to [0, 1]
    normalized = np.clip((elevation - min_m) / (max_m - min_m), 0, 1)

    # Convert to 16-bit
    data_16 = (normalized * 65535).astype(np.uint16)

    img = Image.fromarray(data_16, mode="I;16")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    logger.info("  Saved elevation PNG: %s", path)


def export_layer_png(
    data: np.ndarray,
    path: Path,
    min_val: float = 0.0,
    max_val: float = 1.0,
) -> None:
    """Export a generic layer as 16-bit PNG.

    Args:
        data: 2D data grid.
        path: Output file path.
        min_val: Minimum value for normalization.
        max_val: Maximum value for normalization.
    """
    if max_val - min_val < 1e-12:
        normalized = np.zeros_like(data)
    else:
        normalized = np.clip((data - min_val) / (max_val - min_val), 0, 1)

    data_16 = (normalized * 65535).astype(np.uint16)
    img = Image.fromarray(data_16, mode="I;16")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    logger.info("  Saved layer PNG: %s", path)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def save_outputs(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    elevation_grid: np.ndarray,
    output_dir: Path,
    config: TerrainPipelineConfig,
) -> None:
    """Save all pipeline outputs to the given directory.

    Output files:
        - elevation.png (16-bit PNG)
        - cvt_mesh.json (full CVT mesh)
        - plates.json (tectonic plates)
        - metadata.json (generation parameters)

    Args:
        mesh: The CVT mesh.
        plates: List of TectonicPlate.
        elevation_grid: 2D elevation grid.
        output_dir: Output directory.
        config: Pipeline configuration.
    """
    import json

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Elevation PNG
    elev_min = float(np.min(elevation_grid))
    elev_max = float(np.max(elevation_grid))
    # Round to nice values for PNG encoding
    png_min = min(-11_000, elev_min)
    png_max = max(9_000, elev_max)
    export_elevation_png(elevation_grid, output_dir / "elevation.png", png_min, png_max)

    # 2. CVT Mesh JSON — pydantic-core serializer (Rust, ~5x faster than
    #    model_dump() + json.dump()); non-finite floats serialize as null,
    #    same semantics as the previous sanitize_nonfinite pass.
    from pydantic import TypeAdapter

    from .models import CVTMesh

    mesh_bytes = TypeAdapter(CVTMesh).dump_json(mesh, indent=2)
    (output_dir / "cvt_mesh.json").write_bytes(mesh_bytes)
    logger.info("  Saved CVT mesh: %s", output_dir / "cvt_mesh.json")

    # 3. Plates JSON
    from .models import sanitize_nonfinite

    plates_data = sanitize_nonfinite([p.model_dump() for p in plates])
    with open(output_dir / "plates.json", "w", encoding="utf-8") as f:
        json.dump(plates_data, f, indent=2, default=str)
    logger.info("  Saved plates: %s", output_dir / "plates.json")

    # 4. Write map.yaml with full generation metadata (replaces metadata.json).
    #    All identity/provenance fields are (re)written on every export:
    #    regenerating a world from scratch must produce a map.yaml that
    #    satisfies MapMetadata on its own (the old "update-only" behaviour
    #    left out planet_id etc. when no prior map.yaml existed, crashing
    #    the API with a pydantic ValidationError).
    import yaml as _yaml

    map_yaml_path = output_dir / "map.yaml"
    map_data: dict = {}
    if map_yaml_path.exists():
        with map_yaml_path.open("r", encoding="utf-8") as _f:
            map_data = _yaml.safe_load(_f) or {}

    # Identity + generation provenance (output_dir is maps/<planet_id>/)
    map_data["planet_id"] = output_dir.name
    map_data["projection"] = "equirectangular"
    map_data["width"] = config.export_width
    map_data["height"] = config.export_height
    map_data["voronoi_seed"] = config.seed
    map_data["voronoi_num_cells"] = config.num_nodes
    map_data["cvt_jitter_sigma"] = config.jitter_sigma
    map_data["cvt_lloyd_iterations"] = config.lloyd_iterations
    # Sync PNG encoding range (frontend uses these to decode elevation.png)
    map_data["elevation_min_m"] = png_min
    map_data["elevation_max_m"] = png_max
    map_data["sea_level_m"] = 0.0
    # Generation provenance (formerly metadata.json)
    map_data["num_plates"] = config.num_plates
    map_data["radius_km"] = config.radius_km
    map_data["elevation_range_m"] = [round(elev_min, 1), round(elev_max, 1)]
    map_data["pipeline_version"] = "2.0-cvt"

    with map_yaml_path.open("w", encoding="utf-8") as _f:
        _yaml.dump(map_data, _f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    logger.info("  Updated map.yaml (elevation range + metadata)")

    # 5. Climate layers (if available)
    if _climate_data_available(mesh):
        export_climate_layers(mesh, output_dir, config)


# ---------------------------------------------------------------------------
# Climate layer export (Phase 3A)
# ---------------------------------------------------------------------------


def _climate_data_available(mesh: CVTMesh) -> bool:
    """Check if climate simulation has populated the mesh cells."""
    if mesh.num_cells == 0:
        return False
    return mesh.cells[0].temperature_C is not None


def export_climate_layers(
    mesh: CVTMesh,
    output_dir: Path,
    config: TerrainPipelineConfig,
) -> None:
    """Export climate raster and vector layers.

    Produces:
        - temperature.png (16-bit PNG, range [-40, +50] °C)
        - precipitation.png (16-bit PNG, range [0, 6000] mm/yr)
        - koppen.json (per-cell Köppen class codes)
        - climate_metadata.json

    Args:
        mesh: CVT mesh with climate fields populated.
        output_dir: Output directory.
        config: Pipeline configuration.
    """
    import json

    width = config.export_width
    height = config.export_height
    tree = build_export_tree(mesh)  # Stage 0.3: shared across both rasters

    # 1. Temperature raster
    temp_grid = export_equirectangular(mesh, width, height, field="temperature_C", tree=tree)
    t_min, t_max = _nice_range(float(np.nanmin(temp_grid)), float(np.nanmax(temp_grid)), -40.0, 50.0)
    export_layer_png(temp_grid, output_dir / "temperature.png", t_min, t_max)
    logger.info("  Exported temperature.png [%.0f, %.0f] °C", t_min, t_max)

    # 2. Precipitation raster
    precip_grid = export_equirectangular(mesh, width, height, field="precipitation_mm", tree=tree)
    p_min, p_max = _nice_range(float(np.nanmin(precip_grid)), float(np.nanmax(precip_grid)), 0.0, 6000.0)
    export_layer_png(precip_grid, output_dir / "precipitation.png", p_min, p_max)
    logger.info("  Exported precipitation.png [%.0f, %.0f] mm/yr", p_min, p_max)

    # 3. Köppen classification vector data (per cell)
    koppen_by_cell = {}
    for c in mesh.cells:
        if c.koppen_class is not None:
            koppen_by_cell[str(c.id)] = c.koppen_class

    # Aggregate Köppen class counts for climate summary
    from collections import Counter

    koppen_counter = Counter(koppen_by_cell.values())

    koppen_data = {
        "cells": koppen_by_cell,
        "summary": dict(koppen_counter),
        "num_cells": mesh.num_cells,
    }
    koppen_path = output_dir / "koppen.json"
    with koppen_path.open("w", encoding="utf-8") as _f:
        json.dump(koppen_data, _f, indent=2)
    logger.info("  Exported koppen.json (%d classes)", len(koppen_counter))

    # 4. Climate metadata
    climate_meta = {
        "temperature_range_c": [t_min, t_max],
        "precipitation_range_mm": [p_min, p_max],
        "koppen_classes": sorted(koppen_counter.keys()),
        "export_resolution": [width, height],
        "stellar_luminosity_sol": config.stellar_luminosity_sol,
        "orbital_distance_au": config.orbital_distance_au,
        "axial_tilt_deg": config.axial_tilt_deg,
        "greenhouse_warming_K": config.greenhouse_warming_K,
    }
    meta_path = output_dir / "climate_metadata.json"
    with meta_path.open("w", encoding="utf-8") as _f:
        json.dump(climate_meta, _f, indent=2)
    logger.info("  Exported climate_metadata.json")


def _nice_range(
    data_min: float,
    data_max: float,
    fallback_min: float,
    fallback_max: float,
) -> tuple[float, float]:
    """Round a data range to nice round numbers for PNG encoding.

    Args:
        data_min: Actual minimum value.
        data_max: Actual maximum value.
        fallback_min: Floor if data is within this range.
        fallback_max: Ceiling if data is within this range.

    Returns:
        (nice_min, nice_max) rounded to the nearest 10.
    """
    import math

    rmin = math.floor(min(data_min, fallback_min) / 10.0) * 10.0
    rmax = math.ceil(max(data_max, fallback_max) / 10.0) * 10.0
    return rmin, rmax
