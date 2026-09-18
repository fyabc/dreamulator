"""Fingerprinting for the dev-data package compatibility key."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.map.pipeline_types import TerrainImportRecipe

# The base-terrain mesh/grid serialization format version.  Bump when the CVT
# mesh schema or grid encoding changes in a byte-incompatible way; a bumped
# version makes older published packages incompatible (audit
# github-data-bootstrap-evaluation §版本与可信度的最低要求).
MESH_FORMAT_VERSION = 1


def sha256_hex(data: bytes) -> str:
    """SHA-256 of bytes, hex-encoded."""
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes, or ``""`` if the file is missing."""
    if not path.exists():
        return ""
    return sha256_hex(path.read_bytes())


def recipe_fingerprint(
    recipe: TerrainImportRecipe, mesh_format_version: int = MESH_FORMAT_VERSION
) -> str:
    """Compatibility fingerprint: hash of the import recipe + mesh format version.

    Deliberately excludes the code revision — editing climate (or any) code must
    NOT invalidate the base terrain.  ``code_revision`` is recorded in the
    manifest for provenance only.
    """
    payload: dict[str, Any] = {
        "recipe": recipe.to_dict(),
        "mesh_format_version": mesh_format_version,
    }
    return sha256_hex(json.dumps(payload, sort_keys=True).encode("utf-8"))
