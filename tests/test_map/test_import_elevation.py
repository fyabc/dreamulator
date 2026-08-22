"""Tests for external heightmap import (importer + provenance recording)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from dreamulator.map.elevation_codec import encode_elevation
from dreamulator.map.importer import import_heightmap
from dreamulator.map.manager import MapManager
from dreamulator.map.models import ElevationImportProvenance

if TYPE_CHECKING:
    from pathlib import Path


def _png_bytes() -> bytes:
    grid = np.linspace(0.0, 1.0, 64 * 32).reshape(32, 64)
    return encode_elevation(grid, -1000.0, 1000.0)


def test_import_heightmap_png16_shape_range() -> None:
    result = import_heightmap(_png_bytes(), filename="test.png")
    assert result.source_format == "png-16bit"
    assert (result.source_width, result.source_height) == (64, 32)
    assert not result.was_resampled
    assert result.elevation.min() >= 0.0 and result.elevation.max() <= 1.0


def test_import_heightmap_resamples() -> None:
    result = import_heightmap(_png_bytes(), target_width=16, target_height=8)
    assert result.was_resampled
    assert result.elevation.shape == (8, 16)


def test_record_elevation_import_writes_map_yaml(tmp_path: Path) -> None:
    world_dir = tmp_path / "w"
    (world_dir / "maps" / "p").mkdir(parents=True)
    (world_dir / "maps" / "p" / "elevation.png").write_bytes(_png_bytes())
    mgr = MapManager(world_dir)

    result = import_heightmap(_png_bytes(), filename="gaea.png")
    mgr.record_elevation_import(
        "p",
        ElevationImportProvenance(
            source_format=result.source_format,
            source_filename="gaea.png",
            source_resolution=[result.source_width, result.source_height],
            was_resampled=result.was_resampled,
            notes="Gaea export",
        ),
    )

    meta = mgr.get_map_metadata("p")
    assert meta is not None and meta.elevation_import is not None
    assert meta.elevation_import.source_format == "png-16bit"
    assert meta.elevation_import.source_filename == "gaea.png"
    assert meta.elevation_import.notes == "Gaea export"
