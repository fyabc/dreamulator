"""Pinned GCM climate field sets: the per-cell climate of a GCM run, frozen for a branch.

A branch with ``climate_source: gcm`` (:class:`~dreamulator.models.branch.ClimateSource`)
does not simulate its climate.  Its ``layers/climate/input/`` holds a field set
produced from an ExoPlaSim run by :func:`dreamulator.gcm.to_mesh.compute_field_set`,
and the climate engine only writes those fields onto the inherited mesh
(:func:`apply_field_set`).  This module has no netCDF dependency, so applying a
field set works without the ``[gcm]`` extra.

The field set is tied to the mesh the GCM was projected onto.  It stores
:func:`mesh_fingerprint` (cell geometry, elevation and the land mask) and, from
format 2 on, a copy of that reference geometry.  A mesh with the same fingerprint
is accepted directly.  Otherwise the meshes are compared cell by cell
(:func:`compare_mesh`): builds of the same inputs on different CPUs may differ in
a few coastline cells, which is accepted within :data:`MESH_TOLERANCES`, while a
changed terrain (the GCM run saw other continents) is refused.

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
FORMAT_VERSION = 2
SUPPORTED_FORMATS = (1, 2)

#: Tolerances for accepting a mesh whose fingerprint differs from the reference.
#: Numerical-stabilisation constants (not physics): they absorb platform float
#: noise that moves a handful of coastline cells across sea level, and are far
#: below what any authored terrain change produces (thousands of cells).
MESH_TOLERANCES = {
    "position_deg": 1e-3,  # max |Δlat|, |Δlon| per cell
    "elevation_m": 5.0,  # a cell counts as changed above this |Δelevation|
    "changed_fraction": 1e-3,  # max share of cells changed by more than elevation_m
    "land_flip_fraction": 1e-3,  # max share of cells whose land mask differs
}

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

#: Per-cell float fields that only some field sets carry (absent from sets written
#: before the field existed); applied when present, otherwise left empty.
OPTIONAL_ANNUAL_FIELDS = (
    "cloud_total_frac",
    "cloud_low_frac",
    "cloud_mid_frac",
    "cloud_high_frac",
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
    #: lat/lon/elevation/land of the mesh the fields were projected onto (format 2+).
    reference_geometry: dict[str, np.ndarray] | None = None


@dataclass
class MeshMatch:
    """Cell-by-cell comparison of a mesh against a field set's reference geometry."""

    num_cells: int
    max_position_diff_deg: float
    max_elevation_diff_m: float
    changed_cells: int
    land_flips: int

    def within_tolerance(self) -> bool:
        tol = MESH_TOLERANCES
        return (
            self.max_position_diff_deg <= tol["position_deg"]
            and self.changed_cells <= tol["changed_fraction"] * self.num_cells
            and self.land_flips <= tol["land_flip_fraction"] * self.num_cells
        )

    def describe(self) -> str:
        return (
            f"max position difference {self.max_position_diff_deg:.2e}°, "
            f"{self.changed_cells} cells differ by more than "
            f"{MESH_TOLERANCES['elevation_m']:g} m (max {self.max_elevation_diff_m:.1f} m), "
            f"{self.land_flips} land-mask flips, of {self.num_cells} cells"
        )


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


def mesh_reference_geometry(mesh: CVTMesh) -> dict[str, np.ndarray]:
    """Per-cell lat, lon, elevation and land mask, as stored in a format-2 field set."""
    cells = mesh.cells
    elev = np.array([c.elevation for c in cells], dtype=np.float64)
    return {
        "lat": np.array([c.lat for c in cells], dtype=np.float64),
        "lon": np.array([c.lon for c in cells], dtype=np.float64),
        "elevation": elev.astype(np.float32),
        "land": elev >= 0.0,
    }


def compare_mesh(mesh: CVTMesh, reference: dict[str, np.ndarray]) -> MeshMatch:
    """Compare ``mesh`` cell by cell against a stored reference geometry."""
    cur = mesh_reference_geometry(mesh)
    dlon = np.abs(cur["lon"] - reference["lon"])
    dlon = np.minimum(dlon, 360.0 - dlon)
    dpos = np.maximum(np.abs(cur["lat"] - reference["lat"]), dlon)
    delev = np.abs(cur["elevation"].astype(np.float64) - reference["elevation"])
    return MeshMatch(
        num_cells=len(delev),
        max_position_diff_deg=float(dpos.max()) if dpos.size else 0.0,
        max_elevation_diff_m=float(delev.max()) if delev.size else 0.0,
        changed_cells=int((delev > MESH_TOLERANCES["elevation_m"]).sum()),
        land_flips=int((cur["land"] != reference["land"]).sum()),
    )


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
    if fs.reference_geometry is not None:
        payload["reference_geometry"] = {
            k: _pack_array(v) for k, v in fs.reference_geometry.items()
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
    if payload.get("format_version") not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported field-set format {payload.get('format_version')}")
    ref = payload.get("reference_geometry")
    return GcmFieldSet(
        num_cells=int(payload["num_cells"]),
        mesh_fingerprint=str(payload["mesh_fingerprint"]),
        annual={k: _unpack_array(v) for k, v in payload["annual"].items()},
        monthly={k: _unpack_array(v) for k, v in payload["monthly"].items()},
        koppen=list(payload["koppen"]),
        slp_reduction_unreliable=_unpack_array(payload["slp_reduction_unreliable"]),
        provenance=dict(payload.get("provenance", {})),
        reference_geometry={k: _unpack_array(v) for k, v in ref.items()} if ref else None,
    )


def apply_field_set(mesh: CVTMesh, fs: GcmFieldSet) -> MeshMatch | None:
    """Write the pinned GCM climate onto ``mesh`` in place.

    Returns ``None`` when the mesh fingerprint matches exactly, or the
    :class:`MeshMatch` when a differing mesh was accepted within
    :data:`MESH_TOLERANCES`.  Raises :class:`StaleFieldSetError` when the mesh is
    not the one the field set was computed on.  Sets the per-cell annual fields
    (plus any :data:`OPTIONAL_ANNUAL_FIELDS` the set carries) and Köppen class,
    clears :data:`CLEARED_FIELDS`, and attaches the monthly
    arrays under the private names the climate exporter reads.
    """
    if mesh.num_cells != fs.num_cells:
        raise StaleFieldSetError(
            f"field set has {fs.num_cells} cells, mesh has {mesh.num_cells}; the parent "
            "terrain changed since the GCM run — rerun the GCM on the new mesh"
        )
    match: MeshMatch | None = None
    if mesh_fingerprint(mesh) != fs.mesh_fingerprint:
        if fs.reference_geometry is None:
            raise StaleFieldSetError(
                "mesh fingerprint differs from the one the GCM field set was computed on "
                "(cell geometry, elevation or land mask changed), and this format-1 field "
                "set has no reference geometry to compare against; regenerate it with "
                "scripts/climate/gcm/gcm_to_mesh.py --emit-fields"
            )
        match = compare_mesh(mesh, fs.reference_geometry)
        if not match.within_tolerance():
            raise StaleFieldSetError(
                "the mesh differs from the one the GCM field set was computed on beyond the "
                f"platform tolerance ({match.describe()}); the parent terrain changed, so "
                "the GCM run is stale — rerun the GCM on the new mesh"
            )
    annual = {k: fs.annual[k].astype(np.float64) for k in ANNUAL_FIELDS}
    annual.update(
        {k: fs.annual[k].astype(np.float64) for k in OPTIONAL_ANNUAL_FIELDS if k in fs.annual}
    )
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
    return match


__all__ = [
    "ANNUAL_FIELDS",
    "CLEARED_FIELDS",
    "GCM_FIELDS_FILENAME",
    "MONTHLY_FIELDS",
    "MESH_TOLERANCES",
    "OPTIONAL_ANNUAL_FIELDS",
    "GcmFieldSet",
    "MeshMatch",
    "StaleFieldSetError",
    "apply_field_set",
    "compare_mesh",
    "file_sha256",
    "load_field_set",
    "mesh_fingerprint",
    "mesh_reference_geometry",
    "provenance_path",
    "save_field_set",
]
