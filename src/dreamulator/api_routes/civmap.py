"""CivMap API routes — civilization-layer map on real Earth admin boundaries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dreamulator.world_manager import WorldManager

from ..civmap.manager import CivMapManager
from ..civmap.models import CivCountry, CivSnapshot, CivTerritory, TerritoryAssignment

router = APIRouter(prefix="/api/worlds", tags=["civmap"])

_manager = WorldManager()


def _civ_manager(world_name: str, branch: str | None) -> CivMapManager:
    """Create a CivMapManager for the given world/branch."""
    try:
        world_dir = _manager.world_dir(world_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return CivMapManager(world_dir, branch)


# ---------------------------------------------------------------------------
# Reference GeoJSON (read-only, not branch-scoped)
# ---------------------------------------------------------------------------


@router.get("/{world_name}/civmap/boundaries/{level}")
def get_boundaries(
    world_name: str,
    level: str,
    region: str | None = Query(default=None),
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Get admin boundary GeoJSON.

    Args:
        level: Admin level — ``adm0``, ``adm1``, or ``adm2``.
        region: Optional region filter (e.g. ``europe``, ``asia``).
        branch: Branch name (for resolver inheritance).
    """
    if level not in ("adm0", "adm1", "adm2"):
        raise HTTPException(status_code=400, detail=f"Invalid level: {level}")

    mgr = _civ_manager(world_name, branch)
    geojson = mgr.get_boundary_geojson(level, region)
    if geojson is None:
        raise HTTPException(
            status_code=404,
            detail=f"Boundary data for '{level}' not found. "
            "Run scripts/prepare_civmap_data.py to download reference data.",
        )
    return geojson


@router.get("/{world_name}/civmap/boundaries-meta")
def get_boundaries_meta(
    world_name: str,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Get reference data metadata (source, version, feature counts)."""
    mgr = _civ_manager(world_name, branch)
    meta = mgr.get_reference_metadata()
    if meta is None:
        raise HTTPException(status_code=404, detail="Reference metadata not found")
    return meta


@router.get("/{world_name}/civmap/available-levels")
def get_available_levels(
    world_name: str,
    branch: str | None = Query(default=None),
) -> list[str]:
    """List available admin boundary levels."""
    mgr = _civ_manager(world_name, branch)
    return mgr.list_available_levels()


@router.get("/{world_name}/civmap/boundaries-mapping")
def get_country_province_mapping(
    world_name: str,
    branch: str | None = Query(default=None),
) -> dict[str, list[str]]:
    """Get country (ISO_A2) → province (adm1_code) mapping.

    Lightweight endpoint (~100KB) that returns just the ID mapping
    without geometry, used by the frontend for ADM0↔ADM1 level bridging.
    """
    mgr = _civ_manager(world_name, branch)
    return mgr.get_country_province_mapping()


# ---------------------------------------------------------------------------
# Territory data (branch-scoped)
# ---------------------------------------------------------------------------


@router.get("/{world_name}/civmap/territory")
def get_territory(
    world_name: str,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Get complete territory data (countries, snapshots, assignments)."""
    mgr = _civ_manager(world_name, branch)
    territory = mgr.get_territory()
    return territory.model_dump(mode="json")


class TerritoryUpdateRequest(BaseModel):
    """Request body for replacing all territory data."""

    territory: dict[str, Any] = Field(description="Complete CivTerritory data")


@router.post("/{world_name}/civmap/territory")
def save_territory(
    world_name: str,
    req: TerritoryUpdateRequest,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Replace all territory data."""
    mgr = _civ_manager(world_name, branch)
    territory = CivTerritory.model_validate(req.territory)
    mgr.save_territory(territory)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Country CRUD
# ---------------------------------------------------------------------------


@router.get("/{world_name}/civmap/countries")
def get_countries(
    world_name: str,
    branch: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Get all fictional countries."""
    mgr = _civ_manager(world_name, branch)
    return [c.model_dump(mode="json") for c in mgr.get_countries()]


class CountryCreateRequest(BaseModel):
    """Request body for creating/updating a country."""

    country: dict[str, Any]


@router.post("/{world_name}/civmap/countries")
def upsert_country(
    world_name: str,
    req: CountryCreateRequest,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Create or update a fictional country."""
    mgr = _civ_manager(world_name, branch)
    country = CivCountry.model_validate(req.country)
    territory = mgr.upsert_country(country)
    return {"ok": True, "territory": territory.model_dump(mode="json")}


@router.delete("/{world_name}/civmap/countries/{country_id}")
def delete_country(
    world_name: str,
    country_id: str,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Delete a country and all its territory assignments."""
    mgr = _civ_manager(world_name, branch)
    territory = mgr.delete_country(country_id)
    return {"ok": True, "territory": territory.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# Snapshot CRUD
# ---------------------------------------------------------------------------


@router.get("/{world_name}/civmap/snapshots")
def get_snapshots(
    world_name: str,
    branch: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Get all timeline snapshots."""
    mgr = _civ_manager(world_name, branch)
    return [s.model_dump(mode="json") for s in mgr.get_snapshots()]


class SnapshotCreateRequest(BaseModel):
    """Request body for creating a snapshot."""

    snapshot: dict[str, Any]


@router.post("/{world_name}/civmap/snapshots")
def create_snapshot(
    world_name: str,
    req: SnapshotCreateRequest,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Create a new timeline snapshot."""
    mgr = _civ_manager(world_name, branch)
    snapshot = CivSnapshot.model_validate(req.snapshot)
    territory = mgr.create_snapshot(snapshot)
    return {"ok": True, "territory": territory.model_dump(mode="json")}


@router.delete("/{world_name}/civmap/snapshots/{snapshot_id}")
def delete_snapshot(
    world_name: str,
    snapshot_id: str,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Delete a snapshot and its assignments."""
    mgr = _civ_manager(world_name, branch)
    territory = mgr.delete_snapshot(snapshot_id)
    return {"ok": True, "territory": territory.model_dump(mode="json")}


@router.patch("/{world_name}/civmap/snapshots/{snapshot_id}")
def update_snapshot(
    world_name: str,
    snapshot_id: str,
    req: SnapshotCreateRequest,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Update a snapshot's metadata (year, description)."""
    mgr = _civ_manager(world_name, branch)
    snapshot = CivSnapshot.model_validate(req.snapshot)
    territory = mgr.update_snapshot(snapshot_id, snapshot)
    return {"ok": True, "territory": territory.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# Assignment CRUD (within a snapshot)
# ---------------------------------------------------------------------------


@router.get("/{world_name}/civmap/snapshots/{snapshot_id}/assignments")
def get_assignments(
    world_name: str,
    snapshot_id: str,
    branch: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Get territory assignments for a specific snapshot."""
    mgr = _civ_manager(world_name, branch)
    return [a.model_dump(mode="json") for a in mgr.get_assignments(snapshot_id)]


class AssignmentUpdateRequest(BaseModel):
    """Request body for batch-updating assignments."""

    updates: list[dict[str, Any]] = Field(
        description="List of TerritoryAssignment dicts (province_id, country_id). "
        "Set country_id to '' to unassign.",
    )


@router.patch("/{world_name}/civmap/snapshots/{snapshot_id}/assignments")
def patch_assignments(
    world_name: str,
    snapshot_id: str,
    req: AssignmentUpdateRequest,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Partially update assignments for a snapshot.

    For each update:
    - If province_id exists, replace its country_id
    - If country_id is empty, unassign the province
    - Otherwise, add a new assignment
    """
    mgr = _civ_manager(world_name, branch)
    updates = [TerritoryAssignment.model_validate(u) for u in req.updates]
    territory = mgr.patch_assignments(snapshot_id, updates)
    return {"ok": True, "territory": territory.model_dump(mode="json")}


@router.put("/{world_name}/civmap/snapshots/{snapshot_id}/assignments")
def set_assignments(
    world_name: str,
    snapshot_id: str,
    req: AssignmentUpdateRequest,
    branch: str | None = Query(default=None),
) -> dict[str, Any]:
    """Replace all assignments for a snapshot."""
    mgr = _civ_manager(world_name, branch)
    assignments = [TerritoryAssignment.model_validate(u) for u in req.updates]
    territory = mgr.set_assignments(snapshot_id, assignments)
    return {"ok": True, "territory": territory.model_dump(mode="json")}
