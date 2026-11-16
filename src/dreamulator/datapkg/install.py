"""Verify a dev-data package tarball and atomically install it.

The install is safe by construction (audit §版本与可信度的最低要求):
- the tarball digest and the manifest's per-file SHA-256 are verified first,
- archive members are checked for path traversal / absolute paths / links and
  unpacked to a temporary directory before any write to the target,
- only the expected ``maps/<planet>/`` base-terrain files are installed (never
  YAML source config),
- an existing base terrain whose mesh parameters differ from the recipe is
  refused with an explicit diff (never silently replaced).
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from dreamulator.datapkg.fingerprint import MESH_FORMAT_VERSION, file_sha256, recipe_fingerprint
from dreamulator.datapkg.manifest import (
    MESH_FILE_NAMES,
    ROLE_TERRAIN_BASE,
    SCHEMA_VERSION,
    TERRAIN_BASE_FILES,
    DevDataManifest,
)
from dreamulator.datapkg.terrain_base import populated_climate_fields

if TYPE_CHECKING:
    from dreamulator.map.pipeline_types import TerrainImportRecipe

_MANIFEST_NAME = "manifest.json"
_INSTALL_MANIFEST_NAME = "dev-data-manifest.json"


class InstallError(Exception):
    """A package failed verification or could not be installed safely."""


def _check_member(member: tarfile.TarInfo) -> None:
    name = member.name.replace("\\", "/")
    if name.startswith("/") or ".." in name.split("/"):
        raise InstallError(f"unsafe path in package: {member.name!r}")
    if member.issym() or member.islnk():
        raise InstallError(f"unsupported link in package: {member.name!r}")


def _extract_safely(tar_path: Path, extract_dir: Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    root = extract_dir.resolve()
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            _check_member(member)
            if member.isfile():
                target = (extract_dir / member.name).resolve()
                if not target.is_relative_to(root):
                    raise InstallError(f"path escapes install dir: {member.name!r}")
                tar.extract(member, extract_dir, filter="data")


def verify_package(
    tar_path: Path,
    extract_dir: Path,
    *,
    package_sha256: str | None = None,
    manifest_sha256: str | None = None,
    fingerprint: str | None = None,
    world: str | None = None,
    planet_id: str | None = None,
) -> DevDataManifest:
    """Verify a package and extract it to ``extract_dir``; return its manifest.

    Checks the package digest, the manifest's identity/role/fingerprint, and
    every file's SHA-256 and size.  Raises ``InstallError`` on any mismatch.
    """
    if package_sha256:
        actual = file_sha256(tar_path)
        if actual != package_sha256:
            raise InstallError(
                f"package SHA-256 mismatch: expected {package_sha256[:16]}…, got {actual[:16]}…"
            )

    _extract_safely(tar_path, extract_dir)

    manifest_path = extract_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        raise InstallError("package has no manifest.json")
    if manifest_sha256 is not None and file_sha256(manifest_path) != manifest_sha256:
        raise InstallError("manifest SHA-256 mismatch")
    manifest = DevDataManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))

    if manifest.schema_version != SCHEMA_VERSION:
        raise InstallError(f"unsupported manifest schema version: {manifest.schema_version}")
    if manifest.mesh_format_version != MESH_FORMAT_VERSION:
        raise InstallError(f"unsupported mesh format version: {manifest.mesh_format_version}")
    if manifest.role != ROLE_TERRAIN_BASE:
        raise InstallError(f"unexpected package role: {manifest.role!r}")
    if world is not None and manifest.world != world:
        raise InstallError(f"package world {manifest.world!r} != requested {world!r}")
    if planet_id is not None and manifest.planet_id != planet_id:
        raise InstallError(f"package planet {manifest.planet_id!r} != requested {planet_id!r}")
    if fingerprint is not None and manifest.input_fingerprint != fingerprint:
        raise InstallError("package recipe fingerprint does not match the resolved recipe")

    from dreamulator.map.pipeline_types import TerrainImportRecipe

    recipe = TerrainImportRecipe.from_dict(manifest.recipe)
    if (
        manifest.recipe != recipe.to_dict()
        or recipe_fingerprint(recipe, manifest.mesh_format_version) != manifest.input_fingerprint
    ):
        raise InstallError("manifest recipe does not match its fingerprint")

    _verify_files(extract_dir, manifest)
    return manifest


def _verify_files(extract_dir: Path, manifest: DevDataManifest) -> None:
    present = {f.path for f in manifest.files}
    prefix = f"maps/{manifest.planet_id}/"
    meshes = present & {prefix + name for name in MESH_FILE_NAMES}
    expected = {prefix + name for name in TERRAIN_BASE_FILES} | meshes
    if len(meshes) != 1 or present != expected or len(manifest.files) != 4:
        raise InstallError("manifest must contain exactly four base-terrain files for its planet")
    for f in manifest.files:
        p = extract_dir / f.path
        if not p.is_file():
            raise InstallError(f"missing file: {f.path}")
        if file_sha256(p) != f.sha256:
            raise InstallError(f"SHA-256 mismatch: {f.path}")
        if p.stat().st_size != f.size_bytes:
            raise InstallError(f"size mismatch: {f.path}")

    from dreamulator.map.export import load_cvt_mesh

    data = load_cvt_mesh(extract_dir / next(iter(meshes)))
    climate = populated_climate_fields(data)
    if climate:
        raise InstallError(
            f"base-terrain package contains climate fields: {', '.join(sorted(climate))}"
        )
    if (data.get("seed"), data.get("num_cells")) != (
        manifest.recipe["seed"],
        manifest.recipe["mesh_nodes"],
    ):
        raise InstallError("package mesh parameters do not match its recipe")


def _mesh_params(mesh_path: Path) -> tuple[int, int] | None:
    """(seed, num_cells) of an installed mesh, or ``None`` if unreadable."""
    try:
        from dreamulator.map.export import load_cvt_mesh

        if not mesh_path.is_file():
            return None
        data = load_cvt_mesh(mesh_path)
        climate = populated_climate_fields(data)
        if climate:
            raise InstallError(
                "existing mesh contains climate data; base-terrain installation would erase it. "
                "Keep this reference mesh and install into a separate data directory."
            )
        return int(data.get("seed", -1)), int(data.get("num_cells", -1))
    except InstallError:
        raise
    except Exception:
        return None


def install_files(
    extract_dir: Path,
    manifest: DevDataManifest,
    target_maps_dir: Path,
    recipe: TerrainImportRecipe,
) -> None:
    """Atomically install the base-terrain files into ``target_maps_dir``.

    Refuses to overwrite an existing product whose mesh (seed, num_cells) differs
    from the recipe.  Writes the manifest into the target as provenance.
    """
    target_maps_dir.mkdir(parents=True, exist_ok=True)

    for name in MESH_FILE_NAMES:
        mesh_target = target_maps_dir / name
        if not mesh_target.exists():
            continue
        existing = _mesh_params(mesh_target)
        if existing is None:
            raise InstallError("existing mesh file could not be parsed; refusing to overwrite")
        if existing != (recipe.seed, recipe.mesh_nodes):
            raise InstallError(
                f"existing base terrain has different parameters "
                f"(seed={existing[0]}, nodes={existing[1]}) than the recipe "
                f"(seed={recipe.seed}, nodes={recipe.mesh_nodes}); "
                "refusing to overwrite — re-fetch with a matching recipe, or "
                "remove the existing maps directory first"
            )

    for f in manifest.files:
        src = extract_dir / f.path
        name = Path(f.path).name
        dst = target_maps_dir / name
        tmp_dst = target_maps_dir / (name + ".tmp")
        shutil.copy2(src, tmp_dst)
        os.replace(tmp_dst, dst)

    installed_names = {Path(f.path).name for f in manifest.files}
    for name in MESH_FILE_NAMES:
        if name not in installed_names:
            (target_maps_dir / name).unlink(missing_ok=True)

    (target_maps_dir / _INSTALL_MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
