"""Manifest model for a dev-data package."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

SCHEMA_VERSION = 1
ROLE_TERRAIN_BASE = "terrain-base"

# The four base-terrain artifacts produced by the elevation + tectonics +
# watermask importers — deliberately EXCLUDES import_earth_climate (obs climate)
# and the climate build's write-back (simulated climate fields).  See audit
# github-data-bootstrap-evaluation §推荐的包边界.
TERRAIN_BASE_FILES = ("elevation.png", "plates.json", "map.yaml")
# The mesh may be either generation: canonical msgpack.gz or legacy gzip JSON.
MESH_FILE_NAMES = ("cvt_mesh.msgpack.gz", "cvt_mesh.json")


class PackageFile(BaseModel):
    """One file inside the package: its repo-relative path, SHA-256 and size."""

    path: str
    sha256: str
    size_bytes: int


class DevDataManifest(BaseModel):
    """The manifest written alongside a dev-data package.

    ``input_fingerprint`` is the compatibility key (recipe + mesh format
    version); ``code_revision`` is provenance only.
    """

    schema_version: int = SCHEMA_VERSION
    role: str = ROLE_TERRAIN_BASE
    world: str
    planet_id: str
    recipe: dict[str, Any]
    mesh_format_version: int
    input_fingerprint: str
    code_revision: str
    files: list[PackageFile]
