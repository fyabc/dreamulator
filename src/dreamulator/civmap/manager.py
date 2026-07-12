"""CivMap manager — CRUD for civilization map data with branch inheritance.

Handles two types of data:
1. **Reference GeoJSON** — real-world admin boundaries (shared across branches,
   stored under geological/input/maps/earth_reference/)
2. **Territory data** — fictional countries + assignments (per-branch,
   stored under civilization/input/)
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 — used at runtime
from typing import Any

import yaml  # type: ignore[import-untyped]

from dreamulator.resolver import LayerResolver

from .models import CivCountry, CivSnapshot, CivTerritory, TerritoryAssignment


class CivMapManager:
    """Manages civilization map data for a world/branch.

    Args:
        world_dir: Path to the world root directory.
        branch: Branch name (None for root world).
    """

    def __init__(self, world_dir: Path, branch: str | None = None) -> None:
        self.world_dir = world_dir
        self.branch = branch
        self._resolver = LayerResolver(world_dir, branch)

    # -------------------------------------------------------------------
    # Reference GeoJSON (read-only, shared across branches)
    # -------------------------------------------------------------------

    def _reference_dir(self) -> Path | None:
        """Resolve the reference GeoJSON directory.

        Looks in geological/input/maps/earth_reference/ via the resolver
        (supports branch inheritance — a civilization-fork branch inherits
        the geological layer from the parent).
        """
        input_dir = self._resolver.get_input_dir("geological")
        if input_dir is None:
            return None
        ref_dir = input_dir / "maps" / "earth_reference"
        if ref_dir.exists():
            return ref_dir
        return None

    def get_boundary_geojson(
        self,
        level: str,
        region: str | None = None,
    ) -> dict[str, Any] | None:
        """Load admin boundary GeoJSON.

        Args:
            level: Admin level — ``"adm0"``, ``"adm1"``, or ``"adm2"``.
            region: Optional region filter (e.g. ``"europe"``). If provided,
                loads from a region-split file; otherwise loads the global file.

        Returns:
            GeoJSON FeatureCollection dict, or None if not found.
        """
        ref_dir = self._reference_dir()
        if ref_dir is None:
            return None

        filename = f"{level}_{region}.geojson" if region else f"{level}.geojson"

        geojson_path = ref_dir / filename
        if not geojson_path.exists():
            return None

        with geojson_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)
        return data

    def get_reference_metadata(self) -> dict[str, Any] | None:
        """Load reference data metadata (source, version, feature counts)."""
        ref_dir = self._reference_dir()
        if ref_dir is None:
            return None
        meta_path = ref_dir / "metadata.json"
        if not meta_path.exists():
            return None
        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)
        return data

    def list_available_levels(self) -> list[str]:
        """List available admin boundary levels (e.g. ['adm0', 'adm1'])."""
        ref_dir = self._reference_dir()
        if ref_dir is None:
            return []
        levels = []
        for name in ("adm0", "adm1", "adm2"):
            if (ref_dir / f"{name}.geojson").exists():
                levels.append(name)
        return levels

    def get_country_province_mapping(self) -> dict[str, list[str]]:
        """Build a mapping from country ISO_A2 code to list of ADM1 province IDs.

        Reads the ADM1 GeoJSON and groups feature IDs by their ``iso_a2``
        property.  Used by the frontend to translate ADM0-level painting
        (click a country) into ADM1-level assignments (all provinces).

        Returns:
            Dict of ``{iso_a2: [adm1_code, ...]}``, e.g. ``{"GR": ["GRC-2884", ...]}``.
            Empty dict if ADM1 data is not available.
        """
        ref_dir = self._reference_dir()
        if ref_dir is None:
            return {}
        adm1_path = ref_dir / "adm1.geojson"
        if not adm1_path.exists():
            return {}

        with adm1_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        mapping: dict[str, list[str]] = {}
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            iso_a2 = props.get("iso_a2")
            adm1_code = feature.get("id")
            if iso_a2 and adm1_code:
                mapping.setdefault(iso_a2, []).append(adm1_code)
        return mapping

    # -------------------------------------------------------------------
    # Territory data (per-branch, civilization layer)
    # -------------------------------------------------------------------

    def _civ_input_dir(self) -> Path | None:
        """Resolve the civilization input directory for reading."""
        return self._resolver.get_input_dir("civilization")

    def _ensure_civ_input_dir(self) -> Path:
        """Create and return the civilization input directory for writing.

        Always writes to the branch's own directory (not inherited).
        """
        if self.branch is not None:
            base = self.world_dir / "branches" / self.branch / "layers"
        else:
            base = self.world_dir / "layers"
        civ_dir = base / "civilization" / "input"
        civ_dir.mkdir(parents=True, exist_ok=True)
        return civ_dir

    def get_territory(self) -> CivTerritory:
        """Load territory data (with branch inheritance via ``_inherit: true``).

        Returns:
            CivTerritory model. Returns empty model if no data exists.
        """
        data = self._resolver.load_layer_yaml("civilization", "civ_territory.yaml")
        if data is None:
            return CivTerritory()
        if isinstance(data, dict):
            return CivTerritory.model_validate(data)
        return CivTerritory()

    def save_territory(self, territory: CivTerritory) -> None:
        """Save territory data to the branch's civilization input directory."""
        civ_dir = self._ensure_civ_input_dir()
        yaml_path = civ_dir / "civ_territory.yaml"
        with yaml_path.open("w", encoding="utf-8") as f:
            yaml.dump(
                territory.model_dump(mode="json"),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    # -------------------------------------------------------------------
    # Country CRUD helpers
    # -------------------------------------------------------------------

    def get_countries(self) -> list[CivCountry]:
        """Get all fictional countries."""
        return self.get_territory().countries

    def upsert_country(self, country: CivCountry) -> CivTerritory:
        """Create or update a country.

        If a country with the same ID exists, it is replaced.
        Otherwise, the country is appended.
        """
        territory = self.get_territory()
        # Replace existing or append
        found = False
        for i, existing in enumerate(territory.countries):
            if existing.id == country.id:
                territory.countries[i] = country
                found = True
                break
        if not found:
            territory.countries.append(country)
        self.save_territory(territory)
        return territory

    def delete_country(self, country_id: str) -> CivTerritory:
        """Delete a country and remove all its territory assignments."""
        territory = self.get_territory()
        territory.countries = [c for c in territory.countries if c.id != country_id]
        # Remove assignments referencing this country
        for snap_id, assignments in territory.assignments.items():
            territory.assignments[snap_id] = [
                a for a in assignments if a.country_id != country_id
            ]
        self.save_territory(territory)
        return territory

    # -------------------------------------------------------------------
    # Snapshot CRUD helpers
    # -------------------------------------------------------------------

    def get_snapshots(self) -> list[CivSnapshot]:
        """Get all timeline snapshots."""
        return self.get_territory().snapshots

    def create_snapshot(self, snapshot: CivSnapshot) -> CivTerritory:
        """Create a new snapshot (with empty assignments)."""
        territory = self.get_territory()
        territory.snapshots.append(snapshot)
        territory.assignments.setdefault(snapshot.id, [])
        if territory.active_snapshot is None:
            territory.active_snapshot = snapshot.id
        self.save_territory(territory)
        return territory

    def delete_snapshot(self, snapshot_id: str) -> CivTerritory:
        """Delete a snapshot and its assignments."""
        territory = self.get_territory()
        territory.snapshots = [s for s in territory.snapshots if s.id != snapshot_id]
        territory.assignments.pop(snapshot_id, None)
        if territory.active_snapshot == snapshot_id:
            territory.active_snapshot = (
                territory.snapshots[0].id if territory.snapshots else None
            )
        self.save_territory(territory)
        return territory

    def update_snapshot(self, snapshot_id: str, updates: CivSnapshot) -> CivTerritory:
        """Update a snapshot's metadata (year, description).

        The snapshot ID must match; only year and description are changed.
        """
        territory = self.get_territory()
        for i, existing in enumerate(territory.snapshots):
            if existing.id == snapshot_id:
                territory.snapshots[i] = existing.model_copy(
                    update={"year": updates.year, "description": updates.description},
                )
                break
        self.save_territory(territory)
        return territory

    # -------------------------------------------------------------------
    # Territory assignment helpers
    # -------------------------------------------------------------------

    def get_assignments(self, snapshot_id: str) -> list[TerritoryAssignment]:
        """Get territory assignments for a specific snapshot."""
        territory = self.get_territory()
        return territory.assignments.get(snapshot_id, [])

    def set_assignments(
        self,
        snapshot_id: str,
        assignments: list[TerritoryAssignment],
    ) -> CivTerritory:
        """Replace all assignments for a snapshot."""
        territory = self.get_territory()
        territory.assignments[snapshot_id] = assignments
        self.save_territory(territory)
        return territory

    def patch_assignments(
        self,
        snapshot_id: str,
        updates: list[TerritoryAssignment],
    ) -> CivTerritory:
        """Partially update assignments for a snapshot.

        For each update:
        - If province_id already exists, replace its country_id.
        - Otherwise, append the new assignment.

        To unassign a province, set country_id to empty string "".
        """
        territory = self.get_territory()
        existing = {a.province_id: a for a in territory.assignments.get(snapshot_id, [])}

        for update in updates:
            if update.country_id == "":
                # Unassign
                existing.pop(update.province_id, None)
            else:
                existing[update.province_id] = update

        territory.assignments[snapshot_id] = list(existing.values())
        self.save_territory(territory)
        return territory
