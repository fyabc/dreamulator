"""World CRUD API routes."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from re import fullmatch
from shutil import rmtree
from tempfile import TemporaryDirectory, mkdtemp
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from ruamel.yaml.error import YAMLError as RoundTripYAMLError
from starlette.background import BackgroundTask

from dreamulator import doc_render
from dreamulator.browser_creation import (
    MAX_CREATION_BYTES,
    browser_creation_files,
    validate_browser_creation,
)
from dreamulator.build_jobs import (
    BuildBusyError,
    BuildJob,
    BuildSummary,
    build_jobs,
    local_compute_slot,
)
from dreamulator.engine.ephemeris import sky_ephemeris
from dreamulator.models.catalog import load_entities
from dreamulator.world_manager import STARTER_TEMPLATES, WorldManager
from dreamulator.world_parameters import (
    WorldGridUpdate,
    WorldParameters,
    WorldPlanetUpdate,
    grid_engine,
    grid_inherited,
    read_world_parameters,
    write_world_grid,
    write_world_planet,
)
from dreamulator.world_snapshot import export_snapshot, restore_snapshot, snapshot_world_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from dreamulator.engine.base import BaseEngine
    from dreamulator.engine.progress import PipelineEvent
    from dreamulator.models.layers import Layer
    from dreamulator.models.world import WorldConfig
    from dreamulator.resolver import LayerResolver

router = APIRouter(prefix="/api/worlds", tags=["worlds"])

# Shared world manager instance
_manager = WorldManager()


def _load_yaml(path: Path) -> Any:
    """Load a YAML file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class WorldCreateRequest(BaseModel):
    """Request body for creating a world."""

    name: str = Field(description="World name (used as directory name)")
    seed: int | None = Field(default=None, description="RNG seed (random if omitted)")
    template: str = Field(default="minimal", description="Template to use")
    title: str | None = Field(default=None, min_length=1, max_length=120)


class WorldListResponse(BaseModel):
    """Response for listing worlds."""

    ok: bool = True
    data: list[str]


class WorldInfoResponse(BaseModel):
    """Response for world info."""

    ok: bool = True
    data: dict[str, Any]


class ErrorResponse(BaseModel):
    """Standard error response."""

    ok: bool = False
    error: str
    code: str = "UNKNOWN"


@router.get("", response_model=WorldListResponse)
def list_worlds() -> WorldListResponse:
    """List all available worlds."""
    worlds = _manager.list_worlds()
    return WorldListResponse(data=worlds)


@router.post("", response_model=WorldInfoResponse, status_code=201)
def create_world(req: WorldCreateRequest) -> WorldInfoResponse:
    """Create a new world from a template."""
    try:
        snapshot_world_id(req.name)
        snapshot_world_id(req.template)
        title = req.title.strip() if req.title is not None else None
        if title is not None and (
            not title
            or not fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", req.name)
            or req.name == "earth"
            or req.template not in STARTER_TEMPLATES
            or (req.seed is not None and not 0 <= req.seed <= 0x7FFFFFFF)
        ):
            raise ValueError("Invalid starter world settings")
        _manager.create_world(req.name, seed=req.seed, template=req.template, title=title)
        config = _manager.load_world(req.name)
        return WorldInfoResponse(data=config.model_dump(mode="json"))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/{world_name}", response_model=WorldInfoResponse)
def get_world(world_name: str) -> WorldInfoResponse:
    """Get world root data.

    Layer summaries are enriched with on-disk build status (input source,
    document count, derived freshness, last build time) so the UI shows the
    actual data state instead of the hand-maintained ``configured`` flag.
    """
    from dreamulator.world_layer_status import enrich_layer_summaries

    try:
        config = _manager.load_world(world_name)
        data = config.model_dump(mode="json")
        layers = data.get("layers")
        if isinstance(layers, dict) and layers:
            data["layers"] = enrich_layer_summaries(
                _manager.world_dir(world_name), layers, seed=config.seed.seed
            )
        return WorldInfoResponse(data=data)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/from-heightmap", status_code=201)
def create_world_from_heightmap(file: UploadFile = File(...)) -> dict[str, str]:
    """Restore the browser's initial world without running a build."""
    if file.size is None or file.size > MAX_CREATION_BYTES:
        raise HTTPException(413, "World creation archive is too large")
    with TemporaryDirectory(prefix="dreamulator-creation-") as temporary:
        archive = Path(temporary) / "world.tar.gz"
        try:
            with archive.open("xb") as output:
                remaining = MAX_CREATION_BYTES
                while chunk := file.file.read(1024 * 1024):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise HTTPException(413, "World creation archive is too large")
                    output.write(chunk)
            world = restore_snapshot(
                archive,
                _manager.worlds_dir,
                max_bytes=MAX_CREATION_BYTES,
                max_files=10,
                validate=validate_browser_creation,
            )
        except FileExistsError as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, OSError, yaml.YAMLError) as error:
            raise HTTPException(422, str(error)) from error
    return {"id": world.name}


@router.get("/{world_name}/heightmap-creation/{artifact}", response_class=FileResponse)
def read_world_creation_artifact(world_name: str, artifact: str) -> FileResponse:
    try:
        artifacts = browser_creation_files(_manager.world_dir(snapshot_world_id(world_name)))
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(404, "World creation data not found") from error
    path = artifacts.get(artifact)
    if path is None:
        raise HTTPException(404, "World creation data not found")
    media_type = "image/png" if artifact == "heightmap.png" else "application/json"
    return FileResponse(path, media_type=media_type)


@router.delete("/{world_name}", status_code=204)
def delete_world(world_name: str) -> None:
    """Delete a world."""
    try:
        _manager.delete_world(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{world_name}/validate")
def validate_world(world_name: str) -> dict[str, Any]:
    """Validate a world's files."""
    try:
        errors = _manager.validate_world(world_name)
        return {"ok": len(errors) == 0, "errors": errors}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{world_name}/snapshot", response_class=FileResponse)
def download_world_snapshot(world_name: str) -> FileResponse:
    """Download a local world's files without rebuilding or changing the world."""
    try:
        world = _manager.world_dir(snapshot_world_id(world_name))
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if not local_compute_slot.acquire(blocking=False):
        raise HTTPException(409, "Wait for local computation to finish before exporting a snapshot")
    filename = f"{world.name}.dreamulator.tar.gz"
    try:
        directory = Path(mkdtemp(prefix="dreamulator-snapshot-"))
        archive = directory / "snapshot.tar.gz"
        try:
            export_snapshot(world, archive)
        except BaseException:
            rmtree(directory, ignore_errors=True)
            raise
    except FileNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, yaml.YAMLError) as error:
        raise HTTPException(422, str(error)) from error
    finally:
        local_compute_slot.release()
    return FileResponse(
        archive,
        filename=filename,
        media_type="application/gzip",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(rmtree, directory, ignore_errors=True),
    )


@router.get("/{world_name}/branches")
def list_branches(world_name: str) -> dict[str, Any]:
    """List all branches for a world."""
    from dreamulator.branch_manager import BranchManager

    try:
        world_dir = _manager.world_dir(world_name)
        branch_mgr = BranchManager(world_dir)
        branches = branch_mgr.list_branches()
        return {
            "ok": True,
            "data": [b.model_dump(mode="json") for b in branches],
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Layer data endpoints — stellar, planets, habitable zones
# ---------------------------------------------------------------------------


def _resolve_layer_dir(
    world_dir: Path, layer: str, subdir: str, branch: str | None = None
) -> Path | None:
    """Resolve the effective input or derived directory for a layer.

    Walks the branch inheritance chain if branch is specified.
    """
    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)
    if subdir == "input":
        return resolver.get_input_dir(layer)
    elif subdir == "derived":
        return resolver.get_derived_dir(layer)
    return None


def _load_layer_yaml(
    world_dir: Path, layer: str, filename: str, branch: str | None = None
) -> dict[str, Any] | list[Any] | None:
    """Load a layer YAML file with _inherit: true merge support."""
    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)
    return resolver.load_layer_yaml(layer, filename)


_KM_PER_EARTH_RADIUS = 6371.0


def _normalize_body(
    body: dict[str, Any], orbit_lookup: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Normalize an OrbitingBody dict to PlanetData-compatible format.

    Converts units and field names so the frontend can render bodies
    (moons, asteroids) using the same PlanetMesh component as planets.
    """
    orbit = orbit_lookup.get(body.get("id", ""), {})
    normalized: dict[str, Any] = {
        "id": body.get("id"),
        "name": body.get("name"),
        "planet_type": body.get("body_type", "natural_satellite"),
        "mass": body.get("mass_earth", 0),
        "radius": body.get("radius_km", 0) / _KM_PER_EARTH_RADIUS,
        "orbits": orbit.get("parent_id", ""),
    }
    # Pass through optional fields
    for key in ("rotation_period_days", "axial_tilt_deg", "albedo"):
        if key in body and body[key] is not None:
            normalized[key] = body[key]
    if "surface" in body:
        normalized["surface"] = body["surface"]
    if "description" in body:
        normalized["description"] = body["description"]
    return normalized


@router.get("/{world_name}/stellar")
def get_stellar_system(world_name: str, branch: str | None = None) -> dict[str, Any]:
    """Get stellar system data (input + derived merged).

    Returns the stellar.yaml input data with derived star parameters
    merged in, matching the format used by the static export.
    Non-star bodies (moons, asteroids) are normalized to planet-compatible
    units and included under the 'bodies' key.
    """
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Load stellar input data (with _inherit: true merge support)
    stellar_input = _load_layer_yaml(world_dir, "astronomy", "stellar.yaml", branch)
    if stellar_input is None:
        raise HTTPException(status_code=404, detail="stellar.yaml not found")
    if not isinstance(stellar_input, dict):
        raise HTTPException(status_code=500, detail="stellar.yaml must be a mapping")

    # Merge derived data if available
    derived_dir = _resolve_layer_dir(world_dir, "astronomy", "derived", branch)
    if derived_dir is not None:
        stellar_derived: dict[str, Any] | None = _load_yaml(derived_dir / "stellar_derived.yaml")
        if stellar_derived and "stars" in stellar_derived:
            derived_by_id: dict[str, dict[str, Any]] = {
                s["id"]: s for s in stellar_derived["stars"] if "id" in s
            }
            if "stars" in stellar_input:
                for star in stellar_input["stars"]:
                    star_id = star.get("id")
                    if star_id and star_id in derived_by_id:
                        star["derived"] = derived_by_id[star_id]

    # Normalize bodies (moons, asteroids) to planet-compatible format
    bodies = stellar_input.get("bodies", [])
    if bodies:
        from dreamulator.models.stellar import overlay_planet_physicals

        planets_data = _load_layer_yaml(world_dir, "geological", "planets.yaml", branch)
        if isinstance(planets_data, dict) and isinstance(planets_data.get("planets"), list):
            overlay_planet_physicals(bodies, planets_data["planets"])
        orbit_lookup = {o["body_id"]: o for o in stellar_input.get("orbits", []) if "body_id" in o}
        stellar_input["bodies"] = [_normalize_body(b, orbit_lookup) for b in bodies]

    return stellar_input


@router.get("/{world_name}/planets")
def get_planets(world_name: str, branch: str | None = None) -> list[dict[str, Any]]:
    """Get planet definitions from the geological layer."""
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    planets_data = _load_layer_yaml(world_dir, "geological", "planets.yaml", branch)
    if planets_data is None:
        raise HTTPException(status_code=404, detail="planets.yaml not found")

    # Return the planets list (matching static export format)
    if isinstance(planets_data, dict) and "planets" in planets_data:
        result: list[dict[str, Any]] = planets_data["planets"]
        return result
    return planets_data if isinstance(planets_data, list) else []


@router.get("/{world_name}/system-catalog")
def get_system_catalog(world_name: str, branch: str | None = None) -> dict[str, Any]:
    """Get the merged system catalog (stellar.yaml + planets.yaml, derived).

    Single per-body data source for the 3D viewer and body-encyclopedia UI;
    see ``engine/physical_inputs.py::build_system_catalog``.
    """
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    derived_dir = _resolve_layer_dir(world_dir, "astronomy", "derived", branch)
    if derived_dir is None:
        raise HTTPException(status_code=404, detail="astronomy derived layer not found")
    catalog = _load_yaml(derived_dir / "system_catalog.yaml")
    if not isinstance(catalog, dict):
        raise HTTPException(
            status_code=404, detail="system_catalog.yaml not found — run dreamulator build"
        )
    return catalog


#: Sky-entities cache cap — one entry per (world, branch), stat-validated.
_SKY_CACHE_CAP = 8
_SKY_ENTITIES: OrderedDict[tuple[str, str | None], tuple[int, int, dict[str, Any], str | None]] = (
    OrderedDict()
)


def _sky_entities(
    world_name: str, world_dir: Path, branch: str | None
) -> tuple[dict[str, Any], str | None]:
    """Entities (+ default observer) for the sky query, cached per (world, branch).

    Re-parsing the catalog costs ~135 ms per call — fatal under a time slider
    polling the fast path — so the parsed table is kept until the yaml's
    (mtime_ns, size) changes; same always-fresh posture as the packs npy cache.
    """
    derived_dir = _resolve_layer_dir(world_dir, "astronomy", "derived", branch)
    if derived_dir is None:
        raise HTTPException(status_code=404, detail="astronomy derived layer not found")
    catalog_path = derived_dir / "system_catalog.yaml"
    if not catalog_path.exists():
        raise HTTPException(
            status_code=404, detail="system_catalog.yaml not found — run dreamulator build"
        )
    stat = catalog_path.stat()
    fingerprint = (stat.st_mtime_ns, stat.st_size)
    key = (world_name, branch)
    cached = _SKY_ENTITIES.get(key)
    if cached is not None and cached[0] == fingerprint[0] and cached[1] == fingerprint[1]:
        _SKY_ENTITIES.move_to_end(key)
        return cached[2], cached[3]
    catalog = _load_yaml(catalog_path)
    if not isinstance(catalog, dict):
        raise HTTPException(status_code=404, detail="system_catalog.yaml is unreadable")
    entities = load_entities(catalog)
    target = catalog.get("target_body_id")
    target_id = str(target) if target else None
    _SKY_ENTITIES[key] = (*fingerprint, entities, target_id)
    _SKY_ENTITIES.move_to_end(key)
    while len(_SKY_ENTITIES) > _SKY_CACHE_CAP:
        _SKY_ENTITIES.popitem(last=False)
    return entities, target_id


@router.get("/{world_name}/sky")
def get_sky(
    world_name: str,
    from_: str | None = Query(default=None, alias="from"),
    lat: float = 0.0,
    lon: float = 0.0,
    at: float = 0.0,
    targets: str | None = None,
    include_events: bool = True,
    branch: str | None = None,
) -> dict[str, Any]:
    """The observer's sky above one surface point (``docs/design/pipelines/sky-ephemeris.md`` §3).

    Serves ``engine.ephemeris.sky_ephemeris`` (its result verbatim, no
    envelope).  ``include_events=false`` is the slider fast path (~1 ms vs
    ~1 s); see the engine module for the frame conventions.  API-only by
    design: the output is parameterized, so it has no static mirror (packs
    precedent).
    """
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    entities, default_observer = _sky_entities(world_name, world_dir, branch)
    observer = from_ if from_ is not None else default_observer
    if observer is None:
        raise HTTPException(
            status_code=422,
            detail="no observer given and the catalog has no target_body_id — pass ?from=",
        )
    target_ids = None
    if targets is not None:
        target_ids = [t.strip() for t in targets.split(",") if t.strip()] or None
    try:
        result = sky_ephemeris(
            entities,
            observer,
            lat,
            lon,
            at,
            targets=target_ids,
            include_events=include_events,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"unknown body: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return dict[str, Any](result.model_dump())


_SKY_BACKGROUND: OrderedDict[tuple[str, str | None], tuple[int, int, dict[str, Any]]] = (
    OrderedDict()
)


@router.get("/{world_name}/sky/background")
def get_sky_background(world_name: str, branch: str | None = None) -> dict[str, Any]:
    """The static universe setting around the system (sky-background framework).

    Neighbour stars, deep-sky objects, the galactic band and transient-event
    hooks, directions frozen as ecliptic-frame unit vectors by the astronomy
    engine.  Time- and observer-independent, so it is served once (cached per
    (world, branch), stat-validated like the sky-entities cache) and rotated
    into the observer frame client-side — keeping look-around fetch-free.
    """
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    derived_dir = _resolve_layer_dir(world_dir, "astronomy", "derived", branch)
    if derived_dir is None:
        raise HTTPException(status_code=404, detail="astronomy derived layer not found")
    bg_path = derived_dir / "sky_background.yaml"
    if not bg_path.exists():
        raise HTTPException(
            status_code=404, detail="sky_background.yaml not found — run dreamulator build"
        )
    stat = bg_path.stat()
    key = (world_name, branch)
    cached = _SKY_BACKGROUND.get(key)
    if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        _SKY_BACKGROUND.move_to_end(key)
        return cached[2]
    data = _load_yaml(bg_path)
    if not isinstance(data, dict):
        raise HTTPException(status_code=404, detail="sky_background.yaml is unreadable")
    _SKY_BACKGROUND[key] = (stat.st_mtime_ns, stat.st_size, data)
    _SKY_BACKGROUND.move_to_end(key)
    while len(_SKY_BACKGROUND) > _SKY_CACHE_CAP:
        _SKY_BACKGROUND.popitem(last=False)
    return data


_SKY_CULTURE: OrderedDict[tuple[str, str | None], tuple[int, int, dict[str, Any]]] = OrderedDict()


@router.get("/{world_name}/sky/culture")
def get_sky_culture(world_name: str, branch: str | None = None) -> dict[str, Any]:
    """The world's authored star lore (the civilization-layer sky-culture hook).

    Cultures name and connect background objects strictly by id — positions
    stay in the sky-background catalogue and the client joins the two, so a
    star can move without breaking any culture.  Validated against the
    astronomy catalogue at build time (unknown ids fail the build).  Static
    per (world, branch): served with the same stat-validated cache posture
    as the sky background.
    """
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    derived_dir = _resolve_layer_dir(world_dir, "civilization", "derived", branch)
    if derived_dir is None:
        raise HTTPException(status_code=404, detail="civilization derived layer not found")
    culture_path = derived_dir / "sky_culture.yaml"
    if not culture_path.exists():
        raise HTTPException(
            status_code=404, detail="sky_culture.yaml not found — run dreamulator build"
        )
    stat = culture_path.stat()
    key = (world_name, branch)
    cached = _SKY_CULTURE.get(key)
    if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        _SKY_CULTURE.move_to_end(key)
        return cached[2]
    data = _load_yaml(culture_path)
    if not isinstance(data, dict):
        raise HTTPException(status_code=404, detail="sky_culture.yaml is unreadable")
    _SKY_CULTURE[key] = (stat.st_mtime_ns, stat.st_size, data)
    _SKY_CULTURE.move_to_end(key)
    while len(_SKY_CULTURE) > _SKY_CACHE_CAP:
        _SKY_CULTURE.popitem(last=False)
    return data


@router.get("/{world_name}/habitable-zones")
def get_habitable_zones(world_name: str, branch: str | None = None) -> dict[str, Any]:
    """Get habitable zone data from the astronomy derived layer."""
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    derived_dir = _resolve_layer_dir(world_dir, "astronomy", "derived", branch)
    if derived_dir is None:
        raise HTTPException(status_code=404, detail="No astronomy derived data found")

    hz_data: dict[str, Any] | None = _load_yaml(derived_dir / "habitable_zones.yaml")
    if hz_data is None:
        raise HTTPException(status_code=404, detail="habitable_zones.yaml not found")

    # Return first star's HZ data (matching static export format)
    if isinstance(hz_data, dict) and "stars" in hz_data:
        stars: list[dict[str, Any]] = hz_data["stars"]
        if stars and len(stars) > 0:
            return stars[0]

    return hz_data


# ---------------------------------------------------------------------------
# Layer document endpoints — serve .md files from any layer's input directory
# ---------------------------------------------------------------------------


def _resolve_design_notes_dir(world_dir: Path, branch: str | None) -> Path | None:
    """Resolve the design-notes directory, walking branch chain."""
    if branch:
        from dreamulator.branch_manager import BranchManager

        bm = BranchManager(world_dir)
        try:
            branch_info = bm.get_branch(branch)
            branch_dir = world_dir / "branches" / branch_info.name
            dn_dir = branch_dir / "design-notes"
            if dn_dir.exists():
                return dn_dir
        except (FileNotFoundError, KeyError):
            pass
    dn_dir = world_dir / "design-notes"
    return dn_dir if dn_dir.exists() else None


def _list_md_documents(directory: Path | None) -> list[dict[str, Any]]:
    """List .md files in a directory, returning frontmatter metadata."""
    if directory is None or not directory.exists():
        return []

    documents = []
    for fp in sorted(directory.glob("*.md")):
        with fp.open("r", encoding="utf-8") as f:
            content = f.read()
        fm, _body = doc_render.parse_frontmatter(content)
        documents.append(
            {
                "filename": fp.name,
                "title": fm.get("title", fp.stem),
                "type": fm.get("type", ""),
                "period": fm.get("period", ""),
                "tags": fm.get("tags", []),
                "status": str(fm.get("status", "") or ""),
                "date": str(fm.get("date", "") or ""),
            }
        )
    return documents


def _get_md_document(
    directory: Path | None, filename: str, world_dir: Path, branch: str | None
) -> dict[str, Any]:
    """Read a specific .md file from a directory and render its template body.

    The body is rendered against the entity-addressed fact context
    (``system_catalog.yaml`` + per-layer summaries, resolved along the branch
    chain); when the context is unavailable the raw template is returned with
    ``rendered: false``. See ``dreamulator.doc_render``.
    """
    if directory is None or not directory.exists():
        raise HTTPException(status_code=404, detail=f"Document '{filename}' not found")

    target = None
    for fp in directory.glob("*.md"):
        if fp.name == filename:
            target = fp
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"Document '{filename}' not found")

    with target.open("r", encoding="utf-8") as f:
        content = f.read()

    fm, body = doc_render.parse_frontmatter(content)
    context = doc_render.load_render_context(world_dir, branch)
    body, rendered = doc_render.render_body(body, context)
    return {
        "filename": target.name,
        "title": fm.get("title", target.stem),
        "frontmatter": fm,
        "content": body,
        "rendered": rendered,
    }


# --- Valid layer names for the generalized endpoint ---
_VALID_LAYERS = frozenset(
    [
        "physics",
        "chemistry",
        "astronomy",
        "geological",
        "climate",
        "ecology",
        "civilization",
        "design-notes",
    ]
)


@router.get("/{world_name}/layer-documents/{layer}")
def list_layer_documents(
    world_name: str, layer: str, branch: str | None = None
) -> list[dict[str, Any]]:
    """List .md files in any layer's input directory.

    Returns metadata extracted from YAML frontmatter for each file.
    Also accepts 'design-notes' to read from the design-notes/ directory.
    """
    if layer not in _VALID_LAYERS:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}")

    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    if layer == "design-notes":
        doc_dir = _resolve_design_notes_dir(world_dir, branch)
    else:
        doc_dir = _resolve_layer_dir(world_dir, layer, "input", branch)
    return _list_md_documents(doc_dir)


@router.get("/{world_name}/layer-documents/{layer}/{filename}")
def get_layer_document(
    world_name: str, layer: str, filename: str, branch: str | None = None
) -> dict[str, Any]:
    """Read a specific .md file from any layer's input directory."""
    if layer not in _VALID_LAYERS:
        raise HTTPException(status_code=400, detail=f"Invalid layer: {layer}")

    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    if layer == "design-notes":
        doc_dir = _resolve_design_notes_dir(world_dir, branch)
    else:
        doc_dir = _resolve_layer_dir(world_dir, layer, "input", branch)
    return _get_md_document(doc_dir, filename, world_dir, branch)


# --- Design notes endpoints (non-layer, cross-cutting design documents) ---


@router.get("/{world_name}/design-documents")
def list_design_documents(world_name: str, branch: str | None = None) -> list[dict[str, Any]]:
    """List .md files in the design-notes directory."""
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    dn_dir = _resolve_design_notes_dir(world_dir, branch)
    return _list_md_documents(dn_dir)


@router.get("/{world_name}/design-documents/{filename}")
def get_design_document(
    world_name: str, filename: str, branch: str | None = None
) -> dict[str, Any]:
    """Read a specific .md file from the design-notes directory."""
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    dn_dir = _resolve_design_notes_dir(world_dir, branch)
    return _get_md_document(dn_dir, filename, world_dir, branch)


# --- Legacy civilization-documents endpoints (backward compatibility) ---


@router.get("/{world_name}/civilization-documents")
def list_civilization_documents(world_name: str, branch: str | None = None) -> list[dict[str, Any]]:
    """List .md files in the civilization layer input directory. (Legacy endpoint.)"""
    return list_layer_documents(world_name, "civilization", branch)


@router.get("/{world_name}/civilization-documents/{filename}")
def get_civilization_document(
    world_name: str, filename: str, branch: str | None = None
) -> dict[str, Any]:
    """Read a specific .md file from the civilization layer input directory. (Legacy.)"""
    return get_layer_document(world_name, "civilization", filename, branch)


@router.get("/{world_name}/climate")
def get_climate(world_name: str, branch: str | None = None) -> dict[str, Any] | None:
    """Get climate data from the climate layer input.

    Returns null when no climate.yaml exists yet (layer not populated).
    """
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    data = _load_layer_yaml(world_dir, "climate", "climate.yaml", branch)
    return data if isinstance(data, dict) else None


@router.get("/{world_name}/ecology")
def get_ecology(world_name: str, branch: str | None = None) -> dict[str, Any] | None:
    """Get ecology data from the ecology layer input.

    Returns null when no ecology.yaml exists yet (layer not populated).
    """
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    data = _load_layer_yaml(world_dir, "ecology", "ecology.yaml", branch)
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Build endpoint — run the engine pipeline
# ---------------------------------------------------------------------------


class BuildRequest(BaseModel):
    """Request body for building a world."""

    engine: str | None = Field(default=None, description="Run only this engine")
    branch: str | None = Field(default=None, description="Branch to build")
    start_layer: str | None = Field(
        default=None, description="Start from this layer (engine layers only)"
    )
    force: bool = Field(default=False, description="Re-run even if outputs exist")


class LayerBuildState(BaseModel):
    """One engine layer's freshness for the build plan."""

    name: str
    derived_fresh: str
    input_source: str | None = None
    last_build_time: str | None = None


class BuildPlan(BaseModel):
    """Which engine layers are out of date, and where a build should start."""

    branch: str | None
    fork_layer: str | None
    read_only: bool
    layers: list[LayerBuildState]
    start_layer: str | None
    recompute: list[str]


class LabParameter(BaseModel):
    """One registry parameter value for the selected planet."""

    id: str
    group: str
    value: float | None
    unit: str | None = None
    range: dict[str, float] | None = None
    consumers: list[str]
    source: str | None = None
    editable: bool
    reason: str | None = None


class ParameterLabState(BaseModel):
    """Editable parameter state for one planet."""

    planet: str | None
    branch: str | None
    fork_layer: str | None
    read_only: bool
    revision: str
    parameters: list[LabParameter]
    affected: list[str] = Field(default_factory=list)
    start_layer: str | None = None


class ParameterLabSave(BaseModel):
    """Save values against the revision the lab opened."""

    revision: str | None = None
    values: dict[str, float]


class ParameterLabBranchSave(BaseModel):
    """Save values into a newly created branch."""

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    values: dict[str, float]


@router.get("/{world_name}/build-plan", response_model=BuildPlan)
def get_build_plan(world_name: str, branch: str | None = None) -> BuildPlan:
    """Describe the out-of-date engine layers in build order.

    Freshness compares each layer's recorded input projection when available
    (registered shared parameters are attributed to their consumers; other
    fields are conservative). Older builds without a record fall back to the
    mtime heuristic (input YAML newer than derived products; geological
    products include ``maps/<planet>/``). The plan starts from the earliest
    layer that is not fresh and lists that layer plus everything downstream; a
    reference root is marked read-only.
    """
    from dreamulator.engine import get_all_engines
    from dreamulator.models.layers import get_layer_index
    from dreamulator.world_layer_status import compute_layer_status

    config, resolver, fork = _resolve_build_target(world_name, branch)
    read_only = branch is None and (config.reference_anchor or world_name == "earth")
    engine_layers = sorted({engine.layer for engine in get_all_engines()}, key=get_layer_index)
    if fork is not None:
        fork_index = get_layer_index(fork)
        engine_layers = [layer for layer in engine_layers if get_layer_index(layer) >= fork_index]
    states: list[LayerBuildState] = []
    for layer in engine_layers:
        # Compute per engine layer, not from world.yaml's ``layers`` dict: the
        # dict only lists layers the template configured, while an engine can
        # build a layer with defaults and produce derived data for it.
        try:
            status = compute_layer_status(
                resolver.world_dir, layer, branch=branch, seed=config.seed.seed
            )
        except ValueError:
            status = {}
        states.append(
            LayerBuildState(
                name=layer.value,
                derived_fresh=str(status.get("derived_fresh") or "absent"),
                input_source=status.get("input_source"),
                last_build_time=status.get("last_build_time"),
            )
        )
    start_layer = (
        None
        if read_only
        else next((state.name for state in states if state.derived_fresh != "fresh"), None)
    )
    recompute: list[str] = []
    if start_layer is not None:
        start_index = next(index for index, state in enumerate(states) if state.name == start_layer)
        recompute = [state.name for state in states[start_index:]]
    return BuildPlan(
        branch=branch,
        fork_layer=fork.value if fork is not None else None,
        read_only=read_only,
        layers=states,
        start_layer=start_layer,
        recompute=recompute,
    )


def _parameter_lab_read_only(world_name: str, branch: str | None) -> bool:
    config = _manager.load_world(world_name)
    return branch is None and (config.reference_anchor or world_name == "earth")


@router.get("/{world_name}/parameter-lab", response_model=ParameterLabState)
def get_parameter_lab(
    world_name: str, planet: str | None = None, branch: str | None = None
) -> ParameterLabState:
    """Read the editable registry parameters for one planet."""
    from dreamulator.parameter_lab import ParameterLabUnavailableError, read_lab

    try:
        world_dir = _manager.world_dir(world_name)
        state = read_lab(
            world_dir,
            branch,
            planet,
            read_only=_parameter_lab_read_only(world_name, branch),
        )
        return ParameterLabState.model_validate(state)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ParameterLabUnavailableError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.put("/{world_name}/parameter-lab", response_model=ParameterLabState)
def save_parameter_lab(
    world_name: str,
    update: ParameterLabSave,
    planet: str | None = None,
    branch: str | None = None,
) -> ParameterLabState:
    """Save registry parameter values into the selected world or branch."""
    from dreamulator.parameter_lab import (
        ParameterLabConflictError,
        ParameterLabReadOnlyError,
        ParameterLabUnavailableError,
        save_lab,
    )

    try:
        world_dir = _manager.world_dir(world_name)
        state = save_lab(
            world_dir,
            branch,
            planet,
            update.values,
            update.revision,
            read_only=_parameter_lab_read_only(world_name, branch),
        )
        return ParameterLabState.model_validate(state)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ParameterLabConflictError as error:
        raise HTTPException(
            status_code=409, detail="The parameter files changed since the lab opened"
        ) from error
    except ParameterLabReadOnlyError as error:
        raise HTTPException(status_code=409, detail=f"Parameter is read-only: {error}") from error
    except (ParameterLabUnavailableError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{world_name}/parameter-lab/branch", response_model=ParameterLabState)
def save_parameter_lab_branch(
    world_name: str,
    update: ParameterLabBranchSave,
    planet: str | None = None,
    branch: str | None = None,
) -> ParameterLabState:
    """Create a branch at the earliest consumer layer and save the values."""
    from dreamulator.parameter_lab import (
        ParameterLabReadOnlyError,
        ParameterLabUnavailableError,
        save_as_branch,
    )

    if _parameter_lab_read_only(world_name, branch):
        raise HTTPException(status_code=409, detail="This world is read-only")
    try:
        world_dir = _manager.world_dir(world_name)
        state = save_as_branch(world_dir, branch, update.name, planet, update.values)
        return ParameterLabState.model_validate(state)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ParameterLabReadOnlyError as error:
        raise HTTPException(status_code=409, detail=f"Parameter is read-only: {error}") from error
    except (ParameterLabUnavailableError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _resolve_build_target(
    world_name: str, branch: str | None
) -> tuple[WorldConfig, LayerResolver, Layer | None]:
    from dreamulator.resolver import LayerResolver

    try:
        world_dir = _manager.world_dir(world_name)
        config = _manager.load_world(world_name)
        if branch and (branch in {".", ".."} or "/" in branch or "\\" in branch):
            raise HTTPException(status_code=422, detail="Invalid branch name")
        resolver = LayerResolver(world_dir, branch)
        return config, resolver, resolver.get_fork_layer()
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


class BuildGrid(BaseModel):
    num_cells: int | None = Field(default=None, gt=0, strict=True)
    reuses_mesh: bool


@router.get("/{world_name}/build-grid", response_model=BuildGrid)
def get_build_grid(world_name: str, branch: str | None = None) -> BuildGrid:
    """Describe a full build's grid without constructing or reading the mesh."""
    config, resolver, _ = _resolve_build_target(world_name, branch)
    try:
        engine = grid_engine(resolver, config.seed.seed)
        num_cells, reuses_mesh = engine.preview_mesh_cells(inherited=grid_inherited(resolver))
        return BuildGrid(num_cells=num_cells, reuses_mesh=reuses_mesh)
    except (ValueError, yaml.YAMLError) as error:
        raise HTTPException(
            status_code=422, detail="Cannot determine the build grid size"
        ) from error


@router.get("/{world_name}/world-parameters", response_model=WorldParameters)
def get_world_parameters(world_name: str, branch: str | None = None) -> WorldParameters:
    config, resolver, _ = _resolve_build_target(world_name, branch)
    try:
        return read_world_parameters(
            resolver,
            config.seed.seed,
            reference=branch is None and (config.reference_anchor or world_name == "earth"),
        )
    except (ValueError, yaml.YAMLError) as error:
        raise HTTPException(status_code=422, detail="Cannot read the world settings") from error


@router.put("/{world_name}/world-parameters", response_model=WorldParameters)
def save_world_parameters(
    world_name: str, update: WorldGridUpdate | WorldPlanetUpdate, branch: str | None = None
) -> WorldParameters:
    if not local_compute_slot.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Another local compute job is already active")
    try:
        settings = get_world_parameters(world_name, branch)
        planet = settings.planet
        selected = planet if isinstance(update, WorldPlanetUpdate) else settings
        if selected is None or selected.read_only:
            raise HTTPException(status_code=409, detail="These settings are read-only")
        if selected.revision != update.revision:
            raise HTTPException(
                status_code=409, detail="These settings changed since they were opened"
            )
        _, resolver, _ = _resolve_build_target(world_name, branch)
        if isinstance(update, WorldPlanetUpdate) and planet is not None:
            write_world_planet(resolver, planet, update.planet)
        elif isinstance(update, WorldGridUpdate) and settings.num_cells != update.num_cells:
            write_world_grid(resolver, settings, update.num_cells)
        return get_world_parameters(world_name, branch)
    except (ValueError, RoundTripYAMLError) as error:
        raise HTTPException(status_code=422, detail="Cannot update the world settings") from error
    finally:
        local_compute_slot.release()


def _prepare_build(
    world_name: str, req: BuildRequest
) -> tuple[Path, Callable[[Callable[[PipelineEvent], None]], BuildSummary]]:
    """Validate requests before reserving a background writer."""
    from dreamulator.engine import get_all_engines
    from dreamulator.engine.pipeline import run_pipeline
    from dreamulator.models.layers import Layer, get_layer_index

    config, resolver, fork = _resolve_build_target(world_name, req.branch)
    world_dir = resolver.world_dir
    if req.branch is None and (config.reference_anchor or world_name == "earth"):
        raise HTTPException(
            status_code=409, detail="Reference world roots are read-only; build a branch"
        )
    engines: list[type[BaseEngine]] = get_all_engines()
    buildable = [
        engine
        for engine in engines
        if fork is None or get_layer_index(engine.layer) >= get_layer_index(fork)
    ]
    available = {engine.name for engine in buildable}
    if req.engine is not None and req.engine not in available:
        raise HTTPException(status_code=422, detail=f"Engine '{req.engine}' is unavailable")
    start_layer: Layer | None = None
    if req.start_layer is not None:
        try:
            start_layer = Layer(req.start_layer)
        except ValueError as error:
            raise HTTPException(
                status_code=422, detail=f"Unknown layer '{req.start_layer}'"
            ) from error
        if start_layer not in {engine.layer for engine in buildable}:
            raise HTTPException(status_code=422, detail=f"Layer '{req.start_layer}' is unavailable")
        if req.engine is not None:
            target = next(engine for engine in buildable if engine.name == req.engine)
            if get_layer_index(target.layer) < get_layer_index(start_layer):
                raise HTTPException(
                    status_code=422, detail="Engine is before the requested start layer"
                )

    def run(on_progress: Callable[[PipelineEvent], None]) -> BuildSummary:
        if not engines:
            return BuildSummary(status="no_engines")
        results = run_pipeline(
            engines,
            world_dir,
            config.seed.seed,
            force=req.force,
            only_engine=req.engine,
            branch=req.branch,
            start_layer=start_layer,
            on_progress=on_progress,
        )
        failed = [result for result in results if not result.success]
        return BuildSummary(
            status="failed" if failed else "success",
            engines_run=len(results),
            success=len(results) - len(failed),
            failed=len(failed),
            errors=[warning for result in failed for warning in result.warnings],
        )

    return world_dir, run


def _reserve_build(world_dir: Path, req: BuildRequest) -> BuildJob:
    try:
        return build_jobs.reserve(
            world_dir,
            branch=req.branch,
            engine=req.engine,
            force=req.force,
            start_layer=req.start_layer,
        )
    except BuildBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{world_name}/build")
def build_world(world_name: str, req: BuildRequest | None = None) -> dict[str, Any]:
    """Run synchronously, sharing the writer reservation with background builds."""
    req = req or BuildRequest()
    world_dir, run = _prepare_build(world_name, req)
    job = _reserve_build(world_dir, req)
    finished = build_jobs.execute(job.id, run)
    if finished.error is not None:
        raise HTTPException(status_code=500, detail=f"Build failed: {finished.error}")
    assert finished.result is not None
    if finished.result.status == "no_engines":
        return {"status": "no_engines", "message": "No engines registered"}
    return finished.result.model_dump(mode="json")


@router.post("/{world_name}/build-jobs", response_model=BuildJob, status_code=202)
def start_build_job(
    world_name: str, background_tasks: BackgroundTasks, req: BuildRequest | None = None
) -> BuildJob:
    """Accept a build; the client polls its real stage boundaries."""
    req = req or BuildRequest()
    world_dir, run = _prepare_build(world_name, req)
    job = _reserve_build(world_dir, req)
    background_tasks.add_task(build_jobs.execute, job.id, run)
    return job


@router.get("/{world_name}/build-jobs/{job_id}", response_model=BuildJob)
def get_build_job(world_name: str, job_id: str) -> BuildJob:
    """Read a recent job, scoped to this world and server process."""
    try:
        world_dir = _manager.world_dir(world_name)
        return build_jobs.get(world_dir, job_id)
    except (FileNotFoundError, KeyError) as error:
        raise HTTPException(status_code=404, detail="Build job not found") from error


@router.post("/{world_name}/geography-raster")
async def upload_geography_raster(
    world_name: str,
    file: UploadFile = File(...),
    branch: str | None = None,
) -> dict[str, Any]:
    """Upload a dense land-bias raster (Gleba-style probability map).

    The grayscale is normalised to [0, 1] and re-encoded as 16-bit PNG at
    ``layers/geological/input/geography_raster.png``; the terrain pipeline
    maps it to a [-1, 1] bias (mid-grey neutral) and superposes it onto the
    geography.yaml feature field (weight ``raster_weight``).
    """
    from dreamulator.map.elevation_codec import encode_elevation
    from dreamulator.map.importer import import_heightmap
    from dreamulator.resolver import LayerResolver

    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    resolver = LayerResolver(world_dir, branch)
    geo_input_dir = resolver.get_input_dir("geological")
    if geo_input_dir is None:
        geo_input_dir = world_dir / "layers" / "geological" / "input"
        geo_input_dir.mkdir(parents=True, exist_ok=True)

    data = await file.read()
    try:
        result = import_heightmap(data, filename=file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    target = geo_input_dir / "geography_raster.png"
    target.write_bytes(encode_elevation(result.elevation, 0.0, 1.0))

    return {
        "ok": True,
        "source_format": result.source_format,
        "source_resolution": [result.source_width, result.source_height],
        "saved": str(target.relative_to(world_dir)),
    }
