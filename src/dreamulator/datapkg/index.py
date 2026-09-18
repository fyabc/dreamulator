"""Fixed, git-committed index of published dev-data packages.

The index is a small committed file (``data/dev-data/index.json``) that pins the
immutable asset address + package digest for each published package.  It is the
single source of truth for "a matching package exists" — ``data fetch`` only
claims availability when an entry here matches the resolved recipe fingerprint
(audit §版本与可信度的最低要求 / §用户体验建议).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from dreamulator.datapkg.fingerprint import recipe_fingerprint
from dreamulator.datapkg.manifest import ROLE_TERRAIN_BASE, SCHEMA_VERSION

if TYPE_CHECKING:
    from dreamulator.map.pipeline_types import TerrainImportRecipe


def default_index_path() -> Path:
    """The git-committed index file (``data/dev-data/index.json``), from project root."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current / "data" / "dev-data" / "index.json"
        current = current.parent
    raise RuntimeError("Could not find project root (no pyproject.toml found)")


class IndexEntry(BaseModel):
    """One published package, addressed by its recipe fingerprint."""

    schema_version: int = SCHEMA_VERSION
    role: str = ROLE_TERRAIN_BASE
    world: str
    planet_id: str
    input_fingerprint: str
    mesh_format_version: int
    tag: str  # GitHub Release tag the asset lives on
    asset_name: str  # immutable, content-addressed asset filename
    package_sha256: str
    manifest_sha256: str
    size_bytes: int
    recipe: dict[str, Any]


class DevDataIndex(BaseModel):
    """The whole index file."""

    entries: list[IndexEntry] = []

    @classmethod
    def load(cls, path: Path) -> DevDataIndex:
        """Load the index; a missing file is treated as an empty index."""
        if not path.exists():
            return cls(entries=[])
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    def find(self, *, world: str, planet_id: str, input_fingerprint: str) -> IndexEntry | None:
        """Return the entry matching a resolved recipe, or ``None``."""
        for entry in self.entries:
            if (
                entry.world == world
                and entry.planet_id == planet_id
                and entry.input_fingerprint == input_fingerprint
            ):
                return entry
        return None

    def upsert(self, entry: IndexEntry) -> None:
        """Add or replace the entry for the same (world, planet, fingerprint)."""
        for i, existing in enumerate(self.entries):
            if (
                existing.world == entry.world
                and existing.planet_id == entry.planet_id
                and existing.input_fingerprint == entry.input_fingerprint
            ):
                self.entries[i] = entry
                return
        self.entries.append(entry)


def find_matching_entry(
    world: str, planet_id: str, recipe: TerrainImportRecipe | None
) -> IndexEntry | None:
    """Index entry matching a recipe fingerprint, or ``None`` (never raises)."""
    if recipe is None:
        return None
    try:
        fingerprint = recipe_fingerprint(recipe)
        return DevDataIndex.load(default_index_path()).find(
            world=world, planet_id=planet_id, input_fingerprint=fingerprint
        )
    except Exception:  # noqa: BLE001 — a broken index must not break the caller
        return None


def fetch_hint(
    world: str, branch: str | None, planet_id: str, recipe: TerrainImportRecipe | None
) -> str | None:
    """A ``data fetch`` command (with version/size) if a package is indexed, else None."""
    entry = find_matching_entry(world, planet_id, recipe)
    if entry is None:
        return None
    cmd = f"  uv run dreamulator data fetch {world}"
    if branch:
        cmd += f" --branch {branch}"
    size_mb = entry.size_bytes / (1024 * 1024)
    return f"{cmd}\n  (matching package {entry.asset_name}, {size_mb:.1f} MB)"
