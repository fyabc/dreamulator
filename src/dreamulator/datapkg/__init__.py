"""Versioned development data packages (M1-P1).

A dev-data package publishes the *base terrain* of an imported-terrain world
(earth: ETOPO1 elevation + PB2002 plates + GSHHG water class — four files under
``maps/<planet>/``) together with a manifest (per-file SHA-256 + import recipe
fingerprint).  A small, git-committed index pins the immutable asset address +
package digest; the ``data fetch`` CLI command resolves the effective recipe,
finds the matching index entry, verifies and atomically installs it.

See docs/design/roadmap.md §六 M1-P1 and
private/reviews/github-data-bootstrap-evaluation-2026-09-17.md.
"""

from dreamulator.datapkg.fingerprint import (
    MESH_FORMAT_VERSION,
    file_sha256,
    recipe_fingerprint,
    sha256_hex,
)
from dreamulator.datapkg.index import (
    DevDataIndex,
    IndexEntry,
    default_index_path,
    fetch_hint,
    find_matching_entry,
)
from dreamulator.datapkg.install import InstallError
from dreamulator.datapkg.manifest import (
    ROLE_TERRAIN_BASE,
    SCHEMA_VERSION,
    TERRAIN_BASE_FILES,
    DevDataManifest,
    PackageFile,
)

__all__ = [
    "MESH_FORMAT_VERSION",
    "ROLE_TERRAIN_BASE",
    "SCHEMA_VERSION",
    "TERRAIN_BASE_FILES",
    "DevDataIndex",
    "DevDataManifest",
    "IndexEntry",
    "InstallError",
    "PackageFile",
    "default_index_path",
    "fetch_hint",
    "file_sha256",
    "find_matching_entry",
    "recipe_fingerprint",
    "sha256_hex",
]
