"""Publish the scientific inputs used by the world-to-region TD exporter."""

from __future__ import annotations

import gzip
import hashlib
import struct
from typing import TYPE_CHECKING, BinaryIO

import msgpack
import numpy as np

from .elevation_input import read_elevation_source, world_elevation_source
from .export import find_mesh_file, load_climate_monthly, load_cvt_mesh_model
from .region_inputs import conditioning_fields

if TYPE_CHECKING:
    from pathlib import Path

    from .manager import MapManager
    from .models import ElevationImportSource

MAX_NATIVE_PIXELS = 4096 * 2048


def native_terrain_key(source: ElevationImportSource) -> str:
    return hashlib.sha256(f"v1:{source.model_dump_json()}".encode()).hexdigest()


def terrain_source(
    manager: MapManager, planet: str
) -> tuple[bytes, tuple[ElevationImportSource, Path] | None]:
    """Keep mesh and monthly climate together, using the same directory as the CLI."""
    map_dir = manager._maps_dir(planet)
    mesh_path = find_mesh_file(map_dir) if map_dir is not None else None
    if map_dir is None or mesh_path is None:
        return msgpack.packb(None), None
    try:
        temperature, precipitation = load_climate_monthly(map_dir)
    except FileNotFoundError:
        return msgpack.packb(None), None
    except (KeyError, TypeError) as error:
        raise ValueError("Invalid TD monthly climate file") from error
    mesh = load_cvt_mesh_model(mesh_path)
    if (
        not mesh.cells
        or temperature.shape != (len(mesh.cells), 12)
        or precipitation.shape != temperature.shape
        or not np.isfinite(temperature).all()
        or not np.isfinite(precipitation).all()
        or (precipitation < 0).any()
    ):
        raise ValueError("TD climate must match the selected mesh and contain twelve valid months")
    positions = np.asarray([(cell.x, cell.y, cell.z) for cell in mesh.cells], dtype="<f8")
    heights = np.fromiter(
        (cell.elevation for cell in mesh.cells), dtype="<f8", count=len(mesh.cells)
    )
    fields = conditioning_fields(heights, temperature, precipitation)
    retained = world_elevation_source(manager.world_dir, manager.branch, planet)
    packet = msgpack.packb(
        {
            "version": 1,
            "cells": len(mesh.cells),
            "positions": positions.tobytes(),
            "fields": {
                name: values.astype("<f8", copy=False).tobytes() for name, values in fields.items()
            },
            "native": native_terrain_key(retained[0]) if retained is not None else None,
        }
    )
    return packet, retained


def write_native_terrain(stream: BinaryIO, retained: tuple[ElevationImportSource, Path]) -> None:
    """Write the retained source in metres without the display PNG's requantization."""
    source, path = retained
    width, height = source.provenance.source_resolution
    if width * height > MAX_NATIVE_PIXELS:
        raise ValueError("Native TD source exceeds the browser's 8,388,608-pixel limit")
    values = read_elevation_source(source, path, native=True).metres
    if values.shape != (height, width) or not np.isfinite(values).all():
        raise ValueError("Native TD elevation does not match the retained source metadata")
    with gzip.GzipFile(
        fileobj=stream, mode="wb", compresslevel=1, mtime=0, filename=""
    ) as compressed:
        compressed.write(struct.pack("<II", width, height))
        for start in range(0, height, 32):
            compressed.write(values[start : start + 32].astype("<f8", copy=False).tobytes())
