"""Map API routes — REST endpoints for planet map data."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from dreamulator.world_manager import WorldManager

from ..map.manager import MapManager

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.map.importer import MetricImport
    from dreamulator.map.models import (
        ElevationMapping,
        MapMetadata,
        RasterLayerMeta,
        VectorLayerMeta,
    )

router = APIRouter(prefix="/api/worlds", tags=["maps"])
#: Routes that do not belong to one world (the import preview runs before a world exists).
preview_router = APIRouter(prefix="/api", tags=["maps"])
_manager = WorldManager()
GLOBAL_HEIGHTMAP_MAX_WIDTH = 4096
GLOBAL_HEIGHTMAP_MAX_HEIGHT = GLOBAL_HEIGHTMAP_MAX_WIDTH // 2
GLOBAL_HEIGHTMAP_MAX_MIB = 64


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
        raise HTTPException(status_code=404, detail=str(e)) from e
    return MapManager(world_dir, branch)


def _map_dirs_overlay_first(mgr: MapManager, planet_id: str) -> list[Path]:
    """Candidate map dirs for *planet_id*, most specific first.

    Branch ``maps/`` dirs are overlays on the root world's: a branch that
    forks at the climate layer legitimately ships only climate products,
    while terrain products (map.yaml, elevation.png, plates/features…)
    live only in the root's ``maps/``.  Directory-level resolution alone
    (``MapManager._map_input_dir``) 404s those files for such branches —
    the branch dir exists, so it wins — hence per-file fallback here,
    mirroring the static frontend's branch→root fetch fallback.
    """
    dirs: list[Path] = []
    if mgr.branch is not None:
        overlay = mgr.world_dir / "branches" / mgr.branch / "maps" / planet_id
        if overlay.is_dir():
            dirs.append(overlay)
        root_dir = MapManager(mgr.world_dir, None)._map_input_dir(planet_id)  # noqa: SLF001
    else:
        root_dir = mgr._map_input_dir(planet_id)  # noqa: SLF001
    if root_dir is not None:
        dirs.append(root_dir)
    return dirs


def _map_file_overlay_first(mgr: MapManager, planet_id: str, filename: str) -> Path | None:
    """First existing *filename* across the overlay-first candidate dirs."""
    for d in _map_dirs_overlay_first(mgr, planet_id):
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None


def _mgr_reading(mgr: MapManager, planet_id: str, filename: str) -> MapManager:
    """The manager (branch overlay or root) whose map dir provides *filename*."""
    if mgr.branch is not None:
        overlay = mgr.world_dir / "branches" / mgr.branch / "maps" / planet_id / filename
        if not overlay.exists():
            return MapManager(mgr.world_dir, None)
    return mgr


def _weak_etag(path: Path) -> str:
    """Weak ETag from size + mtime.

    The large map artifacts are deterministic build outputs — a stat-based
    validator is exact for them and avoids hashing tens of MB per request.
    """
    stat = path.stat()
    return f'W/"{stat.st_size:x}-{stat.st_mtime_ns:x}"'


def _file_response(
    request: Request,
    path: Path,
    media_type: str,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    """Stream *path* with ETag revalidation (``If-None-Match`` → 304).

    ``Cache-Control: no-cache`` makes the browser revalidate once per load —
    unchanged files answer 304 with zero body, so page revisits stop
    re-transferring ~60 MB of mesh/elevation/climate data. The 304 check
    runs before the file is read, short-circuiting disk I/O as well.
    """
    etag = _weak_etag(path)
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if extra_headers:
        headers.update(extra_headers)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=path.read_bytes(), media_type=media_type, headers=headers)


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
    mgr = _mgr_reading(_get_map_manager(world_name, branch), planet_id, "map.yaml")
    meta = mgr.get_map_metadata_result(planet_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"No map metadata for '{planet_id}'")
    return meta


@router.get("/{world_name}/maps/{planet_id}/elevation")
def get_elevation(
    world_name: str,
    planet_id: str,
    request: Request,
    branch: str | None = None,
) -> Response:
    """Get elevation heightmap as 16-bit PNG."""
    mgr = _get_map_manager(world_name, branch)
    png_path = _map_file_overlay_first(mgr, planet_id, "elevation.png")
    if png_path is None:
        raise HTTPException(status_code=404, detail=f"No elevation data for '{planet_id}'")
    return _file_response(request, png_path, "image/png")


@router.get("/{world_name}/maps/{planet_id}/voronoi")
def get_voronoi(
    world_name: str,
    planet_id: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """Get the Voronoi network for a planet."""
    mgr = _get_map_manager(world_name, branch)
    network = mgr.get_voronoi(planet_id)
    if network is None and mgr.branch is not None:
        # Branch overlay lacks voronoi data — inherit from the root world.
        network = MapManager(mgr.world_dir, None).get_voronoi(planet_id)
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
    mgr = _mgr_reading(_get_map_manager(world_name, branch), planet_id, "plates.json")
    plates = mgr.get_plates(planet_id)
    return [p.model_dump(mode="json") for p in plates]


@router.get("/{world_name}/maps/{planet_id}/cvt-mesh/geometry")
def get_cvt_mesh_geometry(
    world_name: str,
    planet_id: str,
    request: Request,
    branch: str | None = None,
) -> Response:
    """Static half of the geometry/fields split (P1 分离存储, 2026-09-29).

    Mesh topology + geological identity — byte-stable across climate/ecology/
    civilization rebuilds, so the ETag serves 304s and downstream-layer
    rebuilds only re-fetch the fields half.  ``application/gzip``: the worker
    gunzips client-side (a declared ``Content-Encoding`` would block browser
    cache reuse — same convention as the combined mesh).  404 when the world
    predates the split; the client falls back to the combined mesh.
    """
    from dreamulator.map.export import GEOMETRY_FILENAME

    mgr = _get_map_manager(world_name, branch)
    geo_file = _map_file_overlay_first(mgr, planet_id, GEOMETRY_FILENAME)
    if geo_file is None:
        raise HTTPException(
            status_code=404,
            detail=f"No split geometry for '{planet_id}' (rebuild the world)",
        )
    return _file_response(request, geo_file, "application/gzip")


@router.get("/{world_name}/maps/{planet_id}/cvt-mesh/fields")
def get_cvt_mesh_fields(
    world_name: str,
    planet_id: str,
    request: Request,
    branch: str | None = None,
) -> Response:
    """Dynamic half of the split: per-cell climate/ecology/civ fields.

    Columnar (one f32/u8/interned-string column per field) — no 200k object
    graph to decode or clone; the worker hands the column buffers to the main
    thread as transferables.  Same ETag/304 + application/gzip conventions.
    """
    from dreamulator.map.export import FIELDS_FILENAME

    mgr = _get_map_manager(world_name, branch)
    fields_file = _map_file_overlay_first(mgr, planet_id, FIELDS_FILENAME)
    if fields_file is None:
        raise HTTPException(
            status_code=404,
            detail=f"No split fields for '{planet_id}' (rebuild the world)",
        )
    return _file_response(request, fields_file, "application/gzip")


@router.get("/{world_name}/maps/{planet_id}/cvt-mesh")
def get_cvt_mesh(
    world_name: str,
    planet_id: str,
    request: Request,
    branch: str | None = None,
    fmt: str = "json",
) -> Any:
    """Get the CVT mesh data (cells, adjacency, vertices, regions).

    Query params:
        fmt: ``"json"`` (default) or ``"msgpack"`` — response encoding.

    The canonical on-disk format is gzip-framed MessagePack, streamed back
    byte-for-byte as ``application/gzip`` (the MessagePack worker gunzips
    client-side, same as the static site's mesh blobs) — zero server-side
    parse.  Legacy gzip-JSON / plain-JSON files are decoded and re-encoded;
    raw JSON text is never shipped as msgpack.
    """
    mgr = _get_map_manager(world_name, branch)

    from dreamulator.map.export import decode_mesh_bytes, find_mesh_file

    mesh_file = None
    for candidate_dir in _map_dirs_overlay_first(mgr, planet_id):
        mesh_file = find_mesh_file(candidate_dir)
        if mesh_file is not None:
            break
    if mesh_file is None:
        raise HTTPException(
            status_code=404,
            detail=f"No CVT mesh data for '{planet_id}'. Run terrain generation first.",
        )

    # Revalidation check runs before the file is read, so revisits skip the
    # disk read AND the format sniff below (which decompresses the entire
    # gzip payload just to peek at one byte).
    etag = _weak_etag(mesh_file)
    cache_headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if fmt == "msgpack" and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cache_headers)

    raw = mesh_file.read_bytes()
    import gzip

    inner_is_json = False
    if raw[:2] == b"\x1f\x8b":  # gzip framing — JSON (legacy) or msgpack (canonical)
        inner = gzip.decompress(raw)
        inner_is_json = inner.lstrip()[:1] == b"{"
    else:
        inner = raw
        inner_is_json = raw.lstrip()[:1] == b"{"

    if fmt == "msgpack":
        import msgpack

        if inner_is_json:
            # Legacy file: decode once and re-encode as msgpack.
            return Response(
                content=msgpack.packb(decode_mesh_bytes(raw)),
                media_type="application/x-msgpack",
            )
        # Canonical file: stream the stored gzip bytes untouched, declared as
        # application/gzip WITHOUT Content-Encoding.  A hand-declared
        # Content-Encoding makes Chrome refuse to reuse the cache entry
        # (measured 2026-09-29: ETag revalidation never hits), so the worker
        # gunzips via DecompressionStream instead — same path the static
        # site already uses for its cvt_mesh.msgpack.gz blobs.
        if raw[:2] == b"\x1f\x8b":
            return Response(
                content=raw,
                media_type="application/gzip",
                headers=cache_headers,
            )
        return Response(content=raw, media_type="application/x-msgpack", headers=cache_headers)

    return decode_mesh_bytes(raw)


@router.get("/{world_name}/maps/{planet_id}/climate-monthly")
def get_climate_monthly(
    world_name: str,
    planet_id: str,
    request: Request,
    branch: str | None = None,
) -> Response:
    """Get the monthly climate data (Phase 4) as MessagePack.

    The file is written by ``export_climate_layers`` (already MessagePack), so
    this endpoint streams the raw bytes.
    """
    mgr = _get_map_manager(world_name, branch)
    monthly_file = _map_file_overlay_first(mgr, planet_id, "climate_monthly.msgpack")
    if monthly_file is None:
        raise HTTPException(
            status_code=404,
            detail=f"No monthly climate data for '{planet_id}'. Run the climate engine first.",
        )

    return _file_response(request, monthly_file, "application/x-msgpack")


@router.get("/{world_name}/maps/{planet_id}/climate-yearly")
def get_climate_yearly(
    world_name: str,
    planet_id: str,
    request: Request,
    branch: str | None = None,
) -> Response:
    """Get the yearly climate descriptors (UCC-01) as MessagePack.

    The file is written by ``export_climate_layers`` (already MessagePack), so
    this endpoint streams the raw bytes.
    """
    mgr = _get_map_manager(world_name, branch)
    yearly_file = _map_file_overlay_first(mgr, planet_id, "climate_yearly.msgpack")
    if yearly_file is None:
        raise HTTPException(
            status_code=404,
            detail=f"No yearly climate data for '{planet_id}'. Run the climate engine first.",
        )

    return _file_response(request, yearly_file, "application/x-msgpack")


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
    notes: str | None = Form(None),
    mode: str | None = Form(None),
    min_m: float | None = Form(None),
    max_m: float | None = Form(None),
    sea_level: float | None = Form(None),
    sea_level_m: float | None = Form(None),
    curve: str | None = Form(None),
    gamma: float | None = Form(None),
    seafloor_m: float | None = Form(None),
) -> dict[str, Any]:
    """Import a heightmap from an external tool (PNG/TIFF) under an explicit mapping to metres.

    The mapping is the import contract (``ElevationMapping``): ``range`` (the image carries
    the sea floor; ``min_m``/``max_m`` at its ends), ``threshold`` (a land-only map; ``sea_level``
    as a fraction of full scale, ``max_m`` at white, ``curve``/``gamma``, and the assumed
    ``seafloor_m`` for every sea cell) or ``metres`` (a float TIFF already in metres).  With no
    mapping fields it is ``range`` over the map's own ``elevation_min_m``/``elevation_max_m``,
    which is what the endpoint has always implied.  Land and sea are decided on the source
    pixels and the heights resampled per class to the map's resolution.

    The response reports the land fraction, the height of one grey level, whether the sea floor
    is an assumption and any warnings about the image. The original image and contract are
    retained in geological input; the next build samples them onto a CVT mesh for climate.
    """
    from ..map.elevation_input import save_elevation_source
    from ..map.importer import land_area_fraction
    from ..map.models import ElevationImportProvenance

    mgr = _get_map_manager(world_name, branch)
    meta, mapping, _ = _import_target_and_mapping(
        mgr, branch, planet_id, _mapping_fields(
            mode, min_m, max_m, sea_level, sea_level_m, curve, gamma, seafloor_m
        )
    )  # fmt: skip
    data = await _read_global_heightmap(file)
    filename = file.filename or ""
    result = _run_metric_import(data, filename, mapping, meta)

    provenance = ElevationImportProvenance(
        source_format=result.source_format,
        source_filename=filename,
        source_resolution=[result.source_width, result.source_height],
        output_resolution=list(result.metres.shape[::-1]),
        was_resampled=result.was_resampled,
        mapping=mapping,
        range_m=[float(result.metres.min()), float(result.metres.max())],
        land_fraction=result.land_fraction,
        seafloor_assumed=result.seafloor_assumed,
        level_step_m=result.level_step_m,
        notes=notes,
    )
    try:
        save_elevation_source(mgr.world_dir, branch, planet_id, data, provenance)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    lo, hi = mgr.save_elevation_metres(planet_id, result.metres)
    # The declared sea level is part of the display contract as well as the water mask.
    updated_meta = mgr.get_map_metadata(planet_id)
    assert updated_meta is not None
    updated_meta.width, updated_meta.height = result.metres.shape[::-1]
    updated_meta.sea_level_m = 0.0 if mapping.mode == "threshold" else mapping.sea_level_m
    updated_meta.elevation_import = provenance
    mgr.save_map_metadata(planet_id, updated_meta)
    mgr.sync_voronoi_from_elevation(planet_id)

    # Update layer registry and mark downstream layers as stale
    registry = mgr.update_registry_on_elevation_change(planet_id)
    metas: dict[str, RasterLayerMeta | VectorLayerMeta] = {
        **registry.raster_layers,
        **registry.vector_layers,
    }
    stale_layers = [name for name, meta in metas.items() if meta.stale]

    return {
        "ok": True,
        "source_format": result.source_format,
        "source_resolution": [result.source_width, result.source_height],
        "output_resolution": list(result.metres.shape[::-1]),
        "was_resampled": result.was_resampled,
        "mapping": mapping.model_dump(),
        "range_m": [float(result.metres.min()), float(result.metres.max())],
        "stored_scale_m": [lo, hi],
        "land_fraction": result.land_fraction,
        "land_area_fraction": land_area_fraction(result.land),
        "seafloor_assumed": result.seafloor_assumed,
        "level_step_m": result.level_step_m,
        "warnings": result.warnings,
        "stale_layers": stale_layers,
    }


# ---------------------------------------------------------------------------
# Elevation import: shared mapping resolution and the read-only preview
# ---------------------------------------------------------------------------


def _mapping_fields(
    mode: str | None,
    min_m: float | None,
    max_m: float | None,
    sea_level: float | None,
    sea_level_m: float | None,
    curve: str | None,
    gamma: float | None,
    seafloor_m: float | None,
) -> dict[str, Any]:
    """The mapping fields a request actually sent."""
    return {
        k: v
        for k, v in {
            "mode": mode, "min_m": min_m, "max_m": max_m, "sea_level": sea_level,
            "sea_level_m": sea_level_m, "curve": curve, "gamma": gamma, "seafloor_m": seafloor_m,
        }.items()
        if v is not None
    }  # fmt: skip


def _import_target_and_mapping(
    mgr: MapManager | None, branch: str | None, planet_id: str | None, fields: dict[str, Any]
) -> tuple[MapMetadata | None, ElevationMapping, str]:
    """Validate the import target and resolve the mapping the import will use.

    With no mapping fields, an existing map keeps its own scale (``range`` over its
    ``elevation_min_m``/``elevation_max_m``); without a map the contract defaults apply.
    Returns the target's map metadata, the mapping and where the mapping came from
    (``request``, ``map`` or ``contract``).
    """
    from ..map.elevation_input import validate_elevation_input_target
    from ..map.models import ElevationMapping

    meta = None
    if mgr is not None:
        try:
            validate_elevation_input_target(mgr.world_dir, branch)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if planet_id is not None:
            meta = mgr.get_map_metadata(planet_id)
    source = "request" if fields else "contract"
    if not fields and meta is not None:
        fields = {
            "mode": "range",
            "min_m": meta.elevation_min_m,
            "max_m": meta.elevation_max_m,
            "sea_level_m": meta.sea_level_m,
        }
        source = "map"
    try:
        mapping = ElevationMapping.model_validate(fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return meta, mapping, source


async def _read_global_heightmap(file: UploadFile) -> bytes:
    """Reject unsupported global uploads before decoding pixel arrays."""
    max_bytes = GLOBAL_HEIGHTMAP_MAX_MIB * 1024**2
    too_large = f"Global heightmap file exceeds {GLOBAL_HEIGHTMAP_MAX_MIB} MiB"
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=413, detail=too_large)
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=too_large)
    dimension_limit = (
        f"Global heightmap dimensions exceed "
        f"{GLOBAL_HEIGHTMAP_MAX_WIDTH}x{GLOBAL_HEIGHTMAP_MAX_HEIGHT}"
    )
    try:
        with Image.open(BytesIO(data), formats=["PNG", "TIFF"]) as image:
            width, height = image.size
    except Image.DecompressionBombError as e:
        raise HTTPException(status_code=400, detail=dimension_limit) from e
    except (OSError, ValueError, SyntaxError) as e:
        raise HTTPException(status_code=400, detail="Cannot read a PNG or TIFF heightmap") from e
    if width > GLOBAL_HEIGHTMAP_MAX_WIDTH or height > GLOBAL_HEIGHTMAP_MAX_HEIGHT:
        raise HTTPException(status_code=400, detail=dimension_limit)
    if width != 2 * height:
        raise HTTPException(
            status_code=400, detail=f"Global heightmap must be 2:1 (received {width}x{height})"
        )
    return data


def _run_metric_import(
    data: bytes, filename: str, mapping: ElevationMapping, meta: MapMetadata | None
) -> MetricImport:
    """Decode and map an uploaded image at the target map's resolution (400 on bad input)."""
    from ..map.importer import import_heightmap_metres

    try:
        return import_heightmap_metres(
            data,
            mapping,
            filename=filename,
            target_width=meta.width if meta else None,
            target_height=meta.height if meta else None,
        )
    except (OSError, ValueError, SyntaxError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


#: Width of the preview grid returned by the elevation preview.
PREVIEW_MAX_WIDTH = 720


@preview_router.post("/elevation-preview")
async def preview_elevation_import(
    file: UploadFile = File(...),
    world: str | None = None,
    planet_id: str | None = None,
    branch: str | None = None,
    mode: str | None = Form(None),
    min_m: float | None = Form(None),
    max_m: float | None = Form(None),
    sea_level: float | None = Form(None),
    sea_level_m: float | None = Form(None),
    curve: str | None = Form(None),
    gamma: float | None = Form(None),
    seafloor_m: float | None = Form(None),
) -> dict[str, Any]:
    """Preview an elevation import without writing anything.

    The image goes through the same decoding, mapping and per-class resampling as
    ``import-elevation``.  With ``world`` and ``planet_id`` the target is validated and the
    output takes that map's resolution and, when no mapping fields are sent, its scale; without
    them (a world that does not exist yet) the output keeps the source size and the contract
    defaults.  The response carries the import summary plus a display grid of at most
    ``PREVIEW_MAX_WIDTH`` pixels: heights in metres as little-endian float32 and the land mask
    as uint8, both base64 encoded, row-major from the north-west corner.
    """
    import base64

    import numpy as np

    from ..map.importer import land_area_fraction, preview_grid

    mgr = _get_map_manager(world, branch) if world else None
    meta, mapping, mapping_source = _import_target_and_mapping(
        mgr, branch, planet_id if world else None, _mapping_fields(
            mode, min_m, max_m, sea_level, sea_level_m, curve, gamma, seafloor_m
        )
    )  # fmt: skip
    data = await _read_global_heightmap(file)
    result = _run_metric_import(data, file.filename or "", mapping, meta)
    grid, grid_land = preview_grid(result.metres, result.land, PREVIEW_MAX_WIDTH)
    metres_f32 = np.ascontiguousarray(grid, "<f4").tobytes()
    land_u8 = np.ascontiguousarray(grid_land, np.uint8).tobytes()
    return {
        "ok": True,
        "source_format": result.source_format,
        "source_resolution": [result.source_width, result.source_height],
        "output_resolution": list(result.metres.shape[::-1]),
        "resolution_from": "map" if meta is not None else "source",
        "was_resampled": result.was_resampled,
        "mapping": mapping.model_dump(),
        "mapping_source": mapping_source,
        "range_m": [float(result.metres.min()), float(result.metres.max())],
        "land_fraction": result.land_fraction,
        "land_area_fraction": land_area_fraction(result.land),
        "seafloor_assumed": result.seafloor_assumed,
        "level_step_m": result.level_step_m,
        "warnings": result.warnings,
        "preview": {
            "width": int(grid.shape[1]),
            "height": int(grid.shape[0]),
            "metres_f32": base64.b64encode(metres_f32).decode(),
            "land_u8": base64.b64encode(land_u8).decode(),
        },
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
    The climate stage is skipped (handled by other endpoints).
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
        cfg,
        output_dir,
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
