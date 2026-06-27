"""World CRUD API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dreamulator.world_manager import WorldManager

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
        world_dir = _manager.create_world(req.name, seed=req.seed, template=req.template)
        config = _manager.load_world(req.name)
        return WorldInfoResponse(data=config.model_dump(mode="json"))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{world_name}", response_model=WorldInfoResponse)
def get_world(world_name: str) -> WorldInfoResponse:
    """Get world root data."""
    try:
        config = _manager.load_world(world_name)
        return WorldInfoResponse(data=config.model_dump(mode="json"))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{world_name}", status_code=204)
def delete_world(world_name: str) -> None:
    """Delete a world."""
    try:
        _manager.delete_world(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{world_name}/validate")
def validate_world(world_name: str) -> dict[str, Any]:
    """Validate a world's files."""
    try:
        errors = _manager.validate_world(world_name)
        return {"ok": len(errors) == 0, "errors": errors}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
        raise HTTPException(status_code=404, detail=str(e))


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
        raise HTTPException(status_code=404, detail=str(e))

    # Load stellar input data
    input_dir = _resolve_layer_dir(world_dir, "astronomy", "input", branch)
    if input_dir is None:
        raise HTTPException(status_code=404, detail="No astronomy data found")

    stellar_input: dict[str, Any] = _load_yaml(input_dir / "stellar.yaml")
    if stellar_input is None:
        raise HTTPException(status_code=404, detail="stellar.yaml not found")

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
        orbit_lookup = {o["body_id"]: o for o in stellar_input.get("orbits", []) if "body_id" in o}
        stellar_input["bodies"] = [_normalize_body(b, orbit_lookup) for b in bodies]

    return stellar_input


@router.get("/{world_name}/planets")
def get_planets(world_name: str, branch: str | None = None) -> list[dict[str, Any]]:
    """Get planet definitions from the geological layer."""
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    input_dir = _resolve_layer_dir(world_dir, "geological", "input", branch)
    if input_dir is None:
        raise HTTPException(status_code=404, detail="No geological data found")

    planets_data: dict[str, Any] | None = _load_yaml(input_dir / "planets.yaml")
    if planets_data is None:
        raise HTTPException(status_code=404, detail="planets.yaml not found")

    # Return the planets list (matching static export format)
    if isinstance(planets_data, dict) and "planets" in planets_data:
        result: list[dict[str, Any]] = planets_data["planets"]
        return result
    return planets_data if isinstance(planets_data, list) else []


@router.get("/{world_name}/habitable-zones")
def get_habitable_zones(world_name: str, branch: str | None = None) -> dict[str, Any]:
    """Get habitable zone data from the astronomy derived layer."""
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

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
# Build endpoint — run the engine pipeline
# ---------------------------------------------------------------------------


class BuildRequest(BaseModel):
    """Request body for building a world."""

    engine: str | None = Field(default=None, description="Run only this engine")
    branch: str | None = Field(default=None, description="Branch to build")
    force: bool = Field(default=False, description="Re-run even if outputs exist")


@router.post("/{world_name}/build")
def build_world(world_name: str, req: BuildRequest | None = None) -> dict[str, Any]:
    """Run the simulation pipeline for a world."""
    from dreamulator.engine import get_all_engines
    from dreamulator.engine.pipeline import run_pipeline

    try:
        world_dir = _manager.world_dir(world_name)
        config = _manager.load_world(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    engines = get_all_engines()
    if not engines:
        return {"status": "no_engines", "message": "No engines registered"}

    branch = req.branch if req else None
    only_engine = req.engine if req else None
    force = req.force if req else False

    try:
        results = run_pipeline(
            engines,
            world_dir,
            config.seed.seed,
            force=force,
            only_engine=only_engine,
            branch=branch,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Build failed: {e}")

    success_count = sum(1 for r in results if r.success)
    fail_count = sum(1 for r in results if not r.success)

    errors: list[str] = []
    for r in results:
        if not r.success:
            errors.extend(r.warnings)

    return {
        "status": "success" if fail_count == 0 else "failed",
        "engines_run": len(results),
        "success": success_count,
        "failed": fail_count,
        "errors": errors,
    }
