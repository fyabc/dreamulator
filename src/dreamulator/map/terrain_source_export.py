"""Frozen numerical sources of a terrain synthesis, with explicit stage units."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, cast

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path


_FIELD_BASIS = {
    "land_crust_mask": (
        "effective orogen source eligibility after terrain-stage crust preparation: "
        "crust_type differs from oceanic; source-stage crust and surface land are distinct"
    ),
    "shelf_continental_crust_mask": (
        "actual continental crust at shelf-stage input after terrain geography and "
        "crust relabelling; independent of elevation land/ocean and earlier tectonic labels"
    ),
    "cell_area_km2": (
        "actual area of each source CVT cell; native finite-volume measure tied to xyz"
    ),
    "combined_elevation_m": (
        "combined base, boundary, mountain, trench, catalogue and noise surface before "
        "the initial sea-level calibration"
    ),
    "after_initial_sea_level_m": (
        "actual surface after the initial uniform sea-level shift; subsequent native "
        "terrain stages consume this datum"
    ),
    "orogen_cap_m": (
        "active mountain owner's mean-elevation cap above the sea-level reference; "
        "infinity where no active profile owns the cell"
    ),
    "interior_lowland_clamped_mask": (
        "actual interior lowland floor activation supplied to deposition fill"
    ),
    "final_forearc_surface_m": (
        "original forearc bound shifted by the actual initial sea-level calibration "
        "and configured sea-level offset, as consumed after the coastal stage"
    ),
    "after_final_sea_level_m": (
        "actual surface after the final uniform sea-level trim; overlay texture and "
        "author elevation constraints are applied subsequently"
    ),
    "shelf_coast_drowned_width_m": (
        "geometric reach of coast-connected submerged continental cells, including their "
        "projected footprint radius; source-mesh precision, without a thinned-crust class"
    ),
    "shelf_coast_type_width_m": (
        "observational approximation: Harris et al. (2014) global means of 88 km for "
        "passive margins and 31 km for active margins; local widths remain unresolved"
    ),
    "shelf_coast_type_active_mask": (
        "current coast-source classifier: within boundary influence and either positive "
        "convergence or tangential fraction above 0.5; propagated by shelf_coast_cell_id"
    ),
    "shelf_coast_width_m": (
        "maximum of drowned-crust geometric reach and margin-type mean width; "
        "shelf_coast_cell_id below zero marks unavailable coast sources"
    ),
}


def capture_source_field(
    fields: dict[str, np.ndarray] | None, name: str, value: np.ndarray
) -> None:
    """Copy an opt-in source value at its actual stage, independently of later mutation."""
    if fields is not None:
        stored = np.array(value, copy=True)
        stored.setflags(write=False)
        fields[name] = stored


def save_terrain_source_fields(
    path: Path,
    fields: dict[str, np.ndarray],
    *,
    radius_km: float,
    source: dict[str, Any],
) -> None:
    """Save an opt-in NPZ source archive and its checksummed schema sidecar."""
    if not np.isfinite(radius_km) or radius_km <= 0:
        raise ValueError("source radius must be finite and positive")
    if path.suffix != ".npz":
        raise ValueError("terrain source archive must use the .npz suffix")
    if "xyz" not in fields or fields["xyz"].ndim != 2 or fields["xyz"].shape[1] != 3:
        raise ValueError("source archive needs its source-mesh coordinates")
    n = len(fields["xyz"])
    if n == 0:
        raise ValueError("source mesh must contain coordinates")
    if not np.allclose(np.linalg.norm(fields["xyz"], axis=1), 1, rtol=0, atol=1e-7):
        raise ValueError("source coordinates must be unit vectors")
    descriptions = {}
    for name, value in fields.items():
        if (
            not name
            or "/" in name
            or "\\" in name
            or value.ndim < 1
            or value.shape[0] != n
            or value.dtype.hasobject
        ):
            raise ValueError("source fields must be named non-object arrays on the source mesh")
        units = "m"
        if name == "xyz":
            units = "unit vector; y north"
        elif name.endswith("_km2"):
            units = "km²"
        elif name.endswith("_mask"):
            units = "boolean"
        elif name == "plate_id":
            units = "stable plate id"
        elif name.endswith("_cell_id"):
            units = "source cell index; -1 is unavailable"
        elif name.endswith("_fraction"):
            units = "dimensionless"
        descriptions[name] = {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "units": units,
            "missing": "NaN is unavailable; infinity is an unbounded surface"
            if value.dtype.kind == "f"
            else None,
        }
        if name in _FIELD_BASIS:
            descriptions[name]["basis"] = _FIELD_BASIS[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, allow_pickle=False, **cast("Any", fields))
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = {
        "format": "terrain-source-fields-v1",
        "sha256": digest,
        "radius_km": radius_km,
        "cell_count": n,
        "nominal_spacing_km": float(np.sqrt(4 * np.pi * radius_km**2 / n)),
        "source": source,
        "fields": descriptions,
        "scope": "original geological-stage sources; source-mesh precision",
    }
    path.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load_terrain_source_fields(
    path: Path, *, expected_terrain_fingerprint: str | None = None
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Read a verified source archive with immutable arrays and its stage provenance."""
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if meta.get("format") != "terrain-source-fields-v1" or meta.get("sha256") != digest:
        raise ValueError("terrain source archive format or checksum mismatch")
    if (
        expected_terrain_fingerprint is not None
        and meta.get("source", {}).get("terrain_fingerprint") != expected_terrain_fingerprint
    ):
        raise ValueError("terrain source archive belongs to a different terrain fingerprint")
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != set(meta["fields"]):
            raise ValueError("terrain source archive field list mismatch")
        fields = {name: archive[name] for name in archive.files}
    for name, value in fields.items():
        desc = meta["fields"][name]
        if list(value.shape) != desc["shape"] or str(value.dtype) != desc["dtype"]:
            raise ValueError("terrain source archive field shape or dtype mismatch")
        value.setflags(write=False)
    return fields, meta
