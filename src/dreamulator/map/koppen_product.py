"""Resolve Köppen provenance from the directory that supplied the displayed mesh."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict

from .export import find_mesh_file

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

OBSERVED_KOPPEN_FILE = "koppen-observed.msgpack.gz"


class KoppenProduct(TypedDict, total=False):
    source: str
    raster: bool
    same_grid_monthly: bool


def has_observed_koppen(directory: Path) -> bool:
    try:
        metadata = json.loads((directory / "climate_metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(metadata, dict):
        return False
    source = metadata.get("koppen_source")
    return source == "observed" or (
        source is None
        and metadata.get("source") == "NCEP/NCAR Reanalysis 1 + GPCP v2.3 + Beck et al. (2018)"
    )


def resolve_koppen_product(directories: Sequence[Path]) -> tuple[KoppenProduct, Path | None]:
    mesh = next((directory for directory in directories if find_mesh_file(directory)), None)
    if mesh is None:
        return {"source": "model", "same_grid_monthly": False}, None
    if has_observed_koppen(mesh):
        candidate = mesh / OBSERVED_KOPPEN_FILE
        raster = candidate if candidate.is_file() else None
        return {"source": "observed", "raster": raster is not None}, raster
    monthly_name = "climate_monthly.msgpack"
    monthly = next((path for path in directories if (path / monthly_name).is_file()), None)
    return {"source": "model", "same_grid_monthly": mesh == monthly}, None
