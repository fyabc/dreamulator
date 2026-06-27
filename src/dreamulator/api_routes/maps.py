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
    """Request body for procedural terrain generation."""

    seed: int | None = Field(default=None, description="RNG seed (world seed if omitted)")
    num_continents: int = Field(default=3, ge=1, le=10)
    mountaininess: float = Field(default=0.5, ge=0, le=1)
    num_plates: int = Field(default=10, ge=1, le=50)
    width: int = Field(default=2048, ge=256, le=8192)
    height: int = Field(default=1024, ge=128, le=4096)
    voronoi_num_cells: int = Field(default=5000, ge=100, le=50000)


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
    """Procedurally generate terrain, Voronoi network, and plates."""
    mgr = _get_map_manager(world_name, branch)
    params = req or GenerateRequest()

    meta = mgr.generate_map(
        planet_id,
        seed=params.seed,
        num_continents=params.num_continents,
        mountaininess=params.mountaininess,
        num_plates=params.num_plates,
        width=params.width,
        height=params.height,
        voronoi_num_cells=params.voronoi_num_cells,
    )
    return {"ok": True, **meta.model_dump(mode="json")}


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
