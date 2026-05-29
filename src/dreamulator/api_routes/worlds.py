"""World CRUD API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dreamulator.world_manager import WorldManager

router = APIRouter(prefix="/api/worlds", tags=["worlds"])

# Shared world manager instance
_manager = WorldManager()


class WorldCreateRequest(BaseModel):
    """Request body for creating a new world."""

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
    data: dict


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
def validate_world(world_name: str) -> dict:
    """Validate a world's files."""
    try:
        errors = _manager.validate_world(world_name)
        return {"ok": len(errors) == 0, "errors": errors}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{world_name}/branches")
def list_branches(world_name: str) -> dict:
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
