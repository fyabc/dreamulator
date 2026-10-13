"""Pinned GCM climate field sets: the per-cell climate of a GCM run, frozen for a branch.

A branch with ``climate_source: gcm`` (:class:`~dreamulator.models.branch.ClimateSource`)
does not simulate its climate.  Its ``layers/climate/input/`` holds a field set
produced from an ExoPlaSim run by :func:`dreamulator.gcm.to_mesh.compute_field_set`,
and the climate engine only writes those fields onto the inherited mesh
(:func:`apply_field_set`).  This module has no netCDF dependency, so applying a
field set works without the ``[gcm]`` extra.

The field set is tied to the exact mesh the GCM was run on through
:func:`mesh_fingerprint` (cell geometry, elevation and the land mask).  When the
parent world's terrain changes, the GCM run itself is invalid (it saw the old
continents), so a stale field set is refused rather than re-projected.

The binary file is large (tens of MB) and is distributed with the ``worlds-data``
release, not git; the small ``<name>.provenance.json`` next to it is tracked and
records the source run and the SHA-256 of the binary.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import msgpack
import numpy as np

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh

GCM_FIELDS_FILENAME = "gcm_fields.msgpack.gz"
PROVENANCE_SUFFIX = ".provenance.json"
FORMAT_VERSION = 1

#: Per-cell float fields written onto ``VoronoiCell`` (attribute names).
ANNUAL_FIELDS = (
    "temperature_C",
    "temperature_hottest_month_C",
    "temperature_coldest_month_C",
    "precipitation_mm",
    "pressure_anomaly_annual_hpa",
    "slp_annual_hpa",
    "wind_east_m_s",
    "wind_north_m_s",
)

#: Per-cell monthly fields (shape ``(N, 12)``), stored on the mesh object under
#: the private names :func:`dreamulator.map.export.export_climate_layers` reads.
#: Month 0 starts at the northern vernal equinox, as in the engine.
MONTHLY_FIELDS = {
    "t_monthly_c": "_t_monthly_c",
    "p_monthly_mm": "_p_monthly_mm",
    "wind_east_monthly": "_wind_east_monthly",
    "wind_north_monthly": "_wind_north_monthly",
    "pressure_monthly": "_pressure_monthly",
}

#: Engine-derived fields that would be inconsistent with GCM climate (the slab
#: ocean has no currents; biome and the scores are rebuilt downstream).
CLEARED_FIELDS = (
    "ocean_current_east_m_s",
    "ocean_current_north_m_s",
    "sst_anomaly_c",
    "biome",
    "npp_gc_m2_yr",
    "agriculture_score",
    "habitability_score",
)


class StaleFieldSetError(ValueError):
    """The field set was computed on a different mesh than the one it is applied to."""


@dataclass
class GcmFieldSet:
    """Per-cell GCM climate for one mesh (cell order = mesh order)."""

    num_cells: int
    mesh_fingerprint: str
    annual: dict[str, np.ndarray]
    monthly: dict[str, np.ndarray]
    koppen: list[str | None]
    slp_reduction_unreliable: np.ndarray
    provenance: dict[str, Any] = field(default_factory=dict)


def mesh_fingerprint(mesh: CVTMesh) -> str:
    """SHA-256 of the cell ids, positions (1e-4°), elevation (1 m) and land mask (pure).

    Climate fields are excluded, so the fingerprint is the same before and after
    a climate build and changes only when the terrain does.
    """
    cells = mesh.cells
    ids = np.array([c.id for c in cells], dtype=np.int64)
    pos = np.round(np.array([(c.lat, c.lon) for c in cells], dtype=np.float64), 4)
    elev = np.round(np.array([c.elevation for c in cells], dtype=np.float64))
    h = hashlib.sha256()
    for arr in (ids, pos, elev, elev >= 0.0):
        h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()


def _pack_array(a: np.ndarray) -> dict[str, Any]:
    a = np.ascontiguousarray(a)
    return {"dtype": a.dtype.str, "shape": list(a.shape), "data": a.tobytes()}


def _unpack_array(d: dict[str, Any]) -> np.ndarray:
    return np.frombuffer(d["data"], dtype=np.dtype(d["dtype"])).reshape(d["shape"]).copy()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def provenance_path(path: Path) -> Path:
    return path.with_name(path.name + PROVENANCE_SUFFIX)


def save_field_set(path: str | Path, fs: GcmFieldSet) -> Path:
    """Write the field set plus its tracked ``.provenance.json`` (with the file's SHA-256)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": FORMAT_VERSION,
        "num_cells": fs.num_cells,
        "mesh_fingerprint": fs.mesh_fingerprint,
        "annual": {k: _pack_array(v.astype(np.float32)) for k, v in fs.annual.items()},
        "monthly": {k: _pack_array(v.astype(np.float32)) for k, v in fs.monthly.items()},
        "koppen": list(fs.koppen),
        "slp_reduction_unreliable": _pack_array(fs.slp_reduction_unreliable.astype(np.bool_)),
        "provenance": fs.provenance,
    }
    # mtime=0 keeps the gzip bytes (and so the SHA-256) a pure function of the content.
    with gzip.GzipFile(path, "wb", compresslevel=6, mtime=0) as f:
        f.write(msgpack.packb(payload, use_bin_type=True))
    prov = {
        **fs.provenance,
        "file": path.name,
        "sha256": file_sha256(path),
        "num_cells": fs.num_cells,
        "mesh_fingerprint": fs.mesh_fingerprint,
        "format_version": FORMAT_VERSION,
    }
    provenance_path(path).write_text(
        json.dumps(prov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def load_field_set(path: str | Path, *, verify_provenance: bool = True) -> GcmFieldSet:
    """Read a field set; with ``verify_provenance`` the tracked SHA-256 must match the file.

    The check catches a binary that does not belong to the committed provenance
    (an older release download, or a field set regenerated without committing).
    """
    path = Path(path)
    if verify_provenance:
        prov_file = provenance_path(path)
        if not prov_file.exists():
            raise StaleFieldSetError(f"missing {prov_file.name} next to {path}")
        expected = json.loads(prov_file.read_text(encoding="utf-8")).get("sha256")
        actual = file_sha256(path)
        if expected != actual:
            raise StaleFieldSetError(
                f"{path.name} does not match {prov_file.name} (sha256 {actual[:12]}… vs "
                f"{str(expected)[:12]}…); fetch the worlds-data release that matches this "
                "commit, or regenerate the field set and commit its provenance"
            )
    with gzip.open(path, "rb") as f:
        payload = msgpack.unpackb(f.read(), raw=False)
    if payload.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported field-set format {payload.get('format_version')}")
    return GcmFieldSet(
        num_cells=int(payload["num_cells"]),
        mesh_fingerprint=str(payload["mesh_fingerprint"]),
        annual={k: _unpack_array(v) for k, v in payload["annual"].items()},
        monthly={k: _unpack_array(v) for k, v in payload["monthly"].items()},
        koppen=list(payload["koppen"]),
        slp_reduction_unreliable=_unpack_array(payload["slp_reduction_unreliable"]),
        provenance=dict(payload.get("provenance", {})),
    )


def apply_field_set(mesh: CVTMesh, fs: GcmFieldSet) -> None:
    """Write the pinned GCM climate onto ``mesh`` in place.

    Raises :class:`StaleFieldSetError` when the mesh is not the one the field set
    was computed on.  Sets the per-cell annual fields and Köppen class, clears
    :data:`CLEARED_FIELDS`, and attaches the monthly arrays under the private
    names the climate exporter reads.
    """
    if mesh.num_cells != fs.num_cells:
        raise StaleFieldSetError(
            f"field set has {fs.num_cells} cells, mesh has {mesh.num_cells}; the parent "
            "terrain changed since the GCM run — rerun the GCM on the new mesh"
        )
    fingerprint = mesh_fingerprint(mesh)
    if fingerprint != fs.mesh_fingerprint:
        raise StaleFieldSetError(
            "mesh fingerprint differs from the one the GCM field set was computed on "
            "(cell geometry, elevation or land mask changed); the GCM run is stale — "
            "rerun the GCM on the new mesh"
        )
    annual = {k: fs.annual[k].astype(np.float64) for k in ANNUAL_FIELDS}
    unreliable = fs.slp_reduction_unreliable
    for i, cell in enumerate(mesh.cells):
        for name, values in annual.items():
            setattr(cell, name, float(values[i]))
        cell.koppen_class = fs.koppen[i]
        cell.slp_reduction_unreliable = bool(unreliable[i])
        for name in CLEARED_FIELDS:
            setattr(cell, name, None)
    for key, attr in MONTHLY_FIELDS.items():
        if key in fs.monthly:
            object.__setattr__(mesh, attr, fs.monthly[key].astype(np.float32))


__all__ = [
    "ANNUAL_FIELDS",
    "CLEARED_FIELDS",
    "GCM_FIELDS_FILENAME",
    "MONTHLY_FIELDS",
    "GcmFieldSet",
    "StaleFieldSetError",
    "apply_field_set",
    "file_sha256",
    "load_field_set",
    "mesh_fingerprint",
    "provenance_path",
    "save_field_set",
]
