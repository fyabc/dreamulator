"""Retain authored elevation images as inputs and sample them onto build meshes."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from uuid import uuid4

import yaml
from pydantic import TypeAdapter

from dreamulator.models.branch import BranchMetadata
from dreamulator.models.layers import Layer, get_layer_index
from dreamulator.resolver import LayerResolver

from .models import ElevationImportSource

if TYPE_CHECKING:
    from pathlib import Path

    from .importer import MetricImport
    from .models import CVTMesh, ElevationImportProvenance

SOURCE_MANIFEST = "elevation_imports.yaml"
_SOURCES = TypeAdapter(dict[str, ElevationImportSource])


def load_elevation_sources(path: Path | None) -> dict[str, ElevationImportSource]:
    if path is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"invalid elevation import manifest: {path.name}") from e
    return _SOURCES.validate_python(data)


def validate_elevation_input_target(world_dir: Path, branch: str | None) -> None:
    """An elevation change must belong to a writable geological layer."""
    world_yaml = world_dir / "world.yaml"
    world = yaml.safe_load(world_yaml.read_text(encoding="utf-8")) if world_yaml.exists() else {}
    if branch is None and (world_dir.name == "earth" or (world or {}).get("reference_anchor")):
        raise ValueError("reference world root is read-only; import into a geological branch")
    if branch is not None:
        path = world_dir / "branches" / branch / "branch.yaml"
        if not path.exists():
            raise ValueError(f"branch '{branch}' does not exist")
        metadata = BranchMetadata.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if metadata.fork_layer is None or get_layer_index(metadata.fork_layer) > get_layer_index(
            Layer.GEOLOGICAL
        ):
            raise ValueError("elevation imports require a branch that owns the geological layer")


def save_elevation_source(
    world_dir: Path,
    branch: str | None,
    planet_id: str,
    data: bytes,
    provenance: ElevationImportProvenance,
) -> None:
    """Write immutable image bytes first, then atomically publish the import contract."""
    validate_elevation_input_target(world_dir, branch)
    resolver = LayerResolver(world_dir, branch)
    sources = load_elevation_sources(resolver.find_input_file(Layer.GEOLOGICAL, SOURCE_MANIFEST))
    source = ElevationImportSource(sha256=hashlib.sha256(data).hexdigest(), provenance=provenance)
    base = world_dir if branch is None else world_dir / "branches" / branch
    input_dir = base / "layers" / "geological" / "input"
    blob = input_dir / source.relative_path
    blob.parent.mkdir(parents=True, exist_ok=True)
    # Content addressing keeps the previous manifest valid until the replacement is published.
    if not blob.exists() or blob.read_bytes() != data:
        temp = blob.with_name(f".{uuid4().hex}.tmp")
        temp.write_bytes(data)
        temp.replace(blob)
    sources[planet_id] = source
    manifest = input_dir / SOURCE_MANIFEST
    temp = manifest.with_name(f".{uuid4().hex}.tmp")
    temp.write_text(
        yaml.safe_dump(_SOURCES.dump_python(sources, mode="json"), allow_unicode=True),
        encoding="utf-8",
    )
    temp.replace(manifest)


def read_elevation_source(source: ElevationImportSource, blob: Path | None) -> MetricImport:
    """Decode the retained original, refusing missing or corrupted input even if a mesh exists."""
    from .importer import import_heightmap_metres

    if blob is None or not blob.is_file():
        raise ValueError(
            f"retained elevation image is missing: {source.relative_path}; re-import it"
        )
    data = blob.read_bytes()
    if hashlib.sha256(data).hexdigest() != source.sha256:
        raise ValueError(f"retained elevation image checksum mismatch: {source.relative_path}")
    provenance = source.provenance
    assert provenance.mapping is not None
    width, height = provenance.output_resolution
    return import_heightmap_metres(
        data,
        provenance.mapping,
        filename=provenance.source_filename,
        target_width=width,
        target_height=height,
    )


def sample_elevation_import(mesh: CVTMesh, imported: MetricImport) -> None:
    """Use the containing raster pixel for both height and class, without mixing across coasts.

    This matches the map viewer's equirectangular pixel convention. The input declares every
    non-land pixel as water; separate inland-water masks and geology are not inferred here.
    """
    from .elevation_codec import lon_lat_to_pixel
    from .export import _truncate_float_precision

    height, width = imported.metres.shape
    # Sample at the coordinates consumers will read. Mesh serialization truncates decimal
    # places; a few metres can cross a raster pixel boundary even on a coarse mesh.
    coordinates = json.loads(
        _truncate_float_precision(json.dumps([[c.lon, c.lat] for c in mesh.cells]).encode())
    )
    for cell, (lon, lat) in zip(mesh.cells, coordinates, strict=True):
        x, y = lon_lat_to_pixel(lon, lat, width, height)
        cell.elevation = float(imported.metres[y, x])
        cell.water_class = "land" if imported.land[y, x] else "ocean"
    # The unassigned tectonic fields remain at mesh defaults. Only the climate water mask
    # is authoritative; the heightmap does not supply a tectonic history.
