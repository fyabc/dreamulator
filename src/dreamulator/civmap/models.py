"""CivMap data models — fictional countries, territory assignments, timeline snapshots."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CivCountry(BaseModel):
    """A fictional country / political entity for the civilization map."""

    id: str = Field(description="Stable identifier, e.g. 'ere_byzantine'")
    name: str = Field(description="Display name, e.g. '东罗马帝国'")
    color: str = Field(
        description="Hex color for map fill, e.g. '#8B4513'",
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )
    description: str = Field(default="", description="Brief description")


class CivSnapshot(BaseModel):
    """A point-in-time snapshot of territorial assignments."""

    id: str = Field(description="Snapshot identifier, e.g. 'snap_500'")
    year: int | None = Field(default=None, description="Historical year (optional)")
    description: str = Field(default="", description="e.g. '查士丁尼一世收复意大利'")


class TerritoryAssignment(BaseModel):
    """Assignment of a real-world admin region to a fictional country."""

    province_id: str = Field(
        description="GeoJSON feature ID (e.g. GID_1 from geoBoundaries, or ISO_A3 for ADM0)",
    )
    country_id: str = Field(description="References CivCountry.id")


class CivTerritory(BaseModel):
    """Complete territory data for a civilization-layer branch.

    Stored as ``civ_territory.yaml`` in the civilization input directory.
    """

    countries: list[CivCountry] = Field(default_factory=list)
    snapshots: list[CivSnapshot] = Field(default_factory=list)
    active_snapshot: str | None = Field(
        default=None,
        description="Currently active snapshot ID",
    )
    assignments: dict[str, list[TerritoryAssignment]] = Field(
        default_factory=dict,
        description="Mapping of snapshot_id → list of territory assignments",
    )
