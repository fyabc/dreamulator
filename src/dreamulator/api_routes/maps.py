"""Map API routes — REST endpoints for planet map data."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from dreamulator.world_manager import WorldManager

from ..map.manager import MapManager
from ..map.models import MapLayerType

router = APIRouter(prefix="/api/worlds", tags=["maps"])
_manager = WorldManager()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    """Request body for procedural terrain generation (CVT pipeline)."""

    seed: int | None = Field(default=None, description="RNG seed (world seed if omitted)")
    num_nodes: int = Field(default=100_000, ge=100, le=1_000_000)
    num_plates: int = Field(default=20, ge=1, le=100)
    jitter_sigma: float = Field(default=0.3, ge=0, le=2.0)
    lloyd_iterations: int = Field(default=8, ge=0, le=30)
    export_width: int = Field(default=4096, ge=256, le=8192)
    export_height: int = Field(default=2048, ge=128, le=4096)
    # Legacy fields (ignored by new pipeline)
    num_continents: int | None = Field(default=None, description="Legacy — ignored")
    mountaininess: float | None = Field(default=None, description="Legacy — ignored")
    voronoi_num_cells: int | None = Field(default=None, description="Legacy — ignored")


class MapListResponse(BaseModel):
    ok: bool = True
    data: list[str]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_map_manager(world_name: str, branch: str | None = None) -> MapManager:
    """Create a MapManager for the given world/branch."""
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return MapManager(world_dir, branch)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{world_name}/maps", response_model=MapListResponse)
def list_map_planets(
    world_name: str,
    branch: str | None = None,
) -> MapListResponse:
    """List planet IDs that have map data."""
    mgr = _get_map_manager(world_name, branch)
    return MapListResponse(data=mgr.list_planets_with_maps())


@router.get("/{world_name}/maps/{planet_id}/meta")
def get_map_meta(
    world_name: str,
    planet_id: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """Get map metadata for a planet."""
    mgr = _get_map_manager(world_name, branch)
    meta = mgr.get_map_metadata(planet_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"No map metadata for '{planet_id}'")
    return meta.model_dump(mode="json")


@router.get("/{world_name}/maps/{planet_id}/elevation")
def get_elevation(
    world_name: str,
    planet_id: str,
    branch: str | None = None,
) -> Response:
    """Get elevation heightmap as 16-bit PNG."""
    mgr = _get_map_manager(world_name, branch)
    map_dir = mgr._map_input_dir(planet_id)  # noqa: SLF001
    if map_dir is None:
        raise HTTPException(status_code=404, detail=f"No map data for '{planet_id}'")
    png_path = map_dir / "elevation.png"
    if not png_path.exists():
        raise HTTPException(status_code=404, detail=f"No elevation data for '{planet_id}'")
    data = png_path.read_bytes()
    return Response(content=data, media_type="image/png")


@router.get("/{world_name}/maps/{planet_id}/layer/{layer_type}")
def get_map_layer(
    world_name: str,
    planet_id: str,
    layer_type: str,
    branch: str | None = None,
) -> Response:
    """Get a derived raster layer as PNG."""
    mgr = _get_map_manager(world_name, branch)
    try:
        lt = MapLayerType(layer_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown layer type: {layer_type}")

    # Determine which engine layer to look in
    layer_map = {
        MapLayerType.TERRAIN: "geological",
        MapLayerType.TEMPERATURE: "climate",
        MapLayerType.PRECIPITATION: "climate",
        MapLayerType.BIOMES: "ecology",
    }
    engine_layer = layer_map.get(lt, "geological")

    data = mgr.get_layer_image(planet_id, lt, engine_layer)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No {layer_type} layer data for '{planet_id}'",
        )
    return Response(content=data, media_type="image/png")


@router.get("/{world_name}/maps/{planet_id}/voronoi")
def get_voronoi(
    world_name: str,
    planet_id: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """Get the Voronoi network for a planet."""
    mgr = _get_map_manager(world_name, branch)
    network = mgr.get_voronoi(planet_id)
    if network is None:
        raise HTTPException(status_code=404, detail=f"No Voronoi data for '{planet_id}'")
    return network.model_dump(mode="json")


@router.get("/{world_name}/maps/{planet_id}/plates")
def get_plates(
    world_name: str,
    planet_id: str,
    branch: str | None = None,
) -> list[dict[str, Any]]:
    """Get tectonic plate definitions for a planet."""
    mgr = _get_map_manager(world_name, branch)
    plates = mgr.get_plates(planet_id)
    return [p.model_dump(mode="json") for p in plates]


@router.get("/{world_name}/maps/{planet_id}/features")
def get_features(
    world_name: str,
    planet_id: str,
    branch: str | None = None,
) -> list[dict[str, Any]]:
    """Get map features (rivers, ridges, etc.) for a planet."""
    mgr = _get_map_manager(world_name, branch)
    features = mgr.get_features(planet_id)
    return [f.model_dump(mode="json") for f in features]


@router.get("/{world_name}/maps/{planet_id}/cvt-mesh")
def get_cvt_mesh(
    world_name: str,
    planet_id: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """Get the CVT mesh data (cells, adjacency, vertices, regions)."""
    import json

    mgr = _get_map_manager(world_name, branch)
    map_dir = mgr._map_input_dir(planet_id)  # noqa: SLF001
    if map_dir is None:
        raise HTTPException(status_code=404, detail=f"No map data for '{planet_id}'")

    mesh_file = map_dir / "cvt_mesh.json"
    if not mesh_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No CVT mesh data for '{planet_id}'. Run terrain generation first.",
        )

    with open(mesh_file, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------


@router.post("/{world_name}/maps/{planet_id}/elevation")
async def save_elevation(
    world_name: str,
    planet_id: str,
    file: UploadFile = File(...),
    branch: str | None = None,
) -> dict[str, Any]:
    """Upload a new elevation heightmap (16-bit PNG)."""
    mgr = _get_map_manager(world_name, branch)
    from ..map.elevation_codec import decode_elevation

    data = await file.read()
    elevation = decode_elevation(data)
    mgr.save_elevation(planet_id, elevation)

    # Sync Voronoi if it exists
    mgr.sync_voronoi_from_elevation(planet_id)

    return {
        "ok": True,
        "shape": list(elevation.shape),
        "range": [float(elevation.min()), float(elevation.max())],
    }


@router.post("/{world_name}/maps/{planet_id}/import-elevation")
async def import_elevation(
    world_name: str,
    planet_id: str,
    file: UploadFile = File(...),
    branch: str | None = None,
) -> dict[str, Any]:
    """Import a heightmap from an external tool (PNG/TIFF).

    Auto-detects format, normalises to [0, 1], and optionally resamples to
    match the project's target resolution.  After import the Voronoi network
    is automatically re-sampled from the new elevation data.

    Supported formats: 16-bit PNG, 16-bit TIFF, 32-bit float TIFF.
    """
    from ..map.importer import import_heightmap

    mgr = _get_map_manager(world_name, branch)
    meta = mgr.get_map_metadata(planet_id)

    data = await file.read()
    filename = file.filename or ""

    # Determine target resolution
    target_w = meta.width if meta else None
    target_h = meta.height if meta else None

    result = import_heightmap(
        data,
        filename=filename,
        target_width=target_w,
        target_height=target_h,
    )

    mgr.save_elevation(planet_id, result.elevation)
    mgr.sync_voronoi_from_elevation(planet_id)

    # Update layer registry and mark downstream layers as stale
    registry = mgr.update_registry_on_elevation_change(planet_id)
    stale_layers = [
        name
        for name, meta in {**registry.raster_layers, **registry.vector_layers}.items()
        if meta.stale
    ]

    return {
        "ok": True,
        "source_format": result.source_format,
        "source_resolution": [result.source_width, result.source_height],
        "output_resolution": list(result.elevation.shape[::-1]),
        "was_resampled": result.was_resampled,
        "range": [float(result.elevation.min()), float(result.elevation.max())],
        "stale_layers": stale_layers,
    }


@router.post("/{world_name}/maps/{planet_id}/voronoi")
def save_voronoi(
    world_name: str,
    planet_id: str,
    body: dict[str, Any],
    branch: str | None = None,
) -> dict[str, Any]:
    """Update the Voronoi network for a planet."""
    from ..map.models import VoronoiNetwork

    mgr = _get_map_manager(world_name, branch)
    network = VoronoiNetwork.model_validate(body)
    mgr.save_voronoi(planet_id, network)
    return {"ok": True, "num_cells": network.num_cells}


@router.post("/{world_name}/maps/{planet_id}/plates")
def save_plates(
    world_name: str,
    planet_id: str,
    body: list[dict[str, Any]],
    branch: str | None = None,
) -> dict[str, Any]:
    """Update tectonic plate definitions for a planet."""
    from ..map.models import TectonicPlate

    mgr = _get_map_manager(world_name, branch)
    plates = [TectonicPlate.model_validate(p) for p in body]
    mgr.save_plates(planet_id, plates)
    return {"ok": True, "num_plates": len(plates)}


@router.post("/{world_name}/maps/{planet_id}/generate")
def generate_map(
    world_name: str,
    planet_id: str,
    req: GenerateRequest | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Procedurally generate terrain using the CVT pipeline.

    Runs: CVT mesh -> plates -> boundaries -> terrain synthesis -> export.
    Climate, rivers, and erosion stages are skipped (not yet implemented).
    """
    import logging

    logging.basicConfig(level=logging.WARNING)

    from ..map.pipeline_types import TerrainPipelineConfig
    from ..map.terrain_pipeline import run_terrain_pipeline

    params = req or GenerateRequest()

    # Resolve world seed if not provided
    if params.seed is None:
        try:
            config = _manager.load_world(world_name)
            effective_seed = config.seed.seed
        except Exception:
            effective_seed = 42
    else:
        effective_seed = params.seed

    cfg = TerrainPipelineConfig(
        seed=effective_seed,
        num_nodes=params.num_nodes,
        num_plates=params.num_plates,
        jitter_sigma=params.jitter_sigma,
        lloyd_iterations=params.lloyd_iterations,
        export_width=params.export_width,
        export_height=params.export_height,
    )

    # Determine output directory (input/maps/ for persistent storage)
    mgr = _get_map_manager(world_name, branch)
    output_dir = mgr._ensure_input_dir(planet_id)  # noqa: SLF001

    # Skip export stage in API mode (we save via manager instead)
    result = run_terrain_pipeline(
        cfg, output_dir,
        stages=["mesh", "plates", "boundaries", "terrain", "export"],
    )

    # Build response
    elev_range = [0.0, 0.0]
    if result.elevation_grid is not None:
        elev_range = [
            float(result.elevation_grid.min()),
            float(result.elevation_grid.max()),
        ]

    return {
        "ok": True,
        "planet_id": planet_id,
        "seed": effective_seed,
        "num_nodes": cfg.num_nodes,
        "num_plates": cfg.num_plates,
        "num_cells": result.mesh.num_cells if result.mesh else 0,
        "num_boundary_cells": len(result.boundary_cell_ids),
        "elevation_range_m": elev_range,
        "stages_completed": result.stages_completed,
        "elapsed_seconds": round(result.elapsed_seconds, 1),
    }


@router.delete("/{world_name}/maps/{planet_id}")
def delete_map(
    world_name: str,
    planet_id: str,
    branch: str | None = None,
) -> None:
    """Delete all map data for a planet."""
    import shutil

    mgr = _get_map_manager(world_name, branch)
    map_dir = mgr._map_input_dir(planet_id)  # noqa: SLF001
    if map_dir is not None:
        shutil.rmtree(map_dir)
    derived_dir = mgr._map_derived_dir(planet_id)  # noqa: SLF001
    if derived_dir is not None:
        shutil.rmtree(derived_dir)
