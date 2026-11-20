"""Portable conditioning and monthly runoff carried by a region pack.

The files are sampled and calculated once at export. Refinement consumes
them without reopening the source world's mesh or climate archive.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.result_contract import REFERENCE_MONTH_DAYS

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.map.models import CVTMesh
    from dreamulator.map.region_export import RegionWindow

REFINEMENT_INPUT_VERSION = "region-refinement-inputs-v1"
CONDITIONING_UNITS = {
    "elevation_m": "m",
    "temperature_mean_c": "degC at surface",
    "temperature_std_c": "degC",
    "precipitation_total_mm": "mm per reference year",
    "precipitation_cv_pct": "%",
}
REFINEMENT_GEOMETRY_KEYS = (
    "projection",
    "center_lat",
    "center_lon",
    "span_km",
    "radius_km",
    "grid",
    "sea_level_m",
)


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def monthly_runoff_shape(
    temperature: np.ndarray,
    precipitation: np.ndarray,
    *,
    recharge_fraction: float | None = None,
    residence_time_days: float | None = None,
) -> np.ndarray:
    """Twelve shares from the existing bucket/baseflow and surplus fallbacks."""
    from dreamulator.engine.climate_physics import (
        BASEFLOW_RECHARGE_FRACTION,
        BASEFLOW_RESIDENCE_TIME_DAYS,
        SOIL_WATER_CAPACITY_MM,
        potential_evapotranspiration_hamon_monthly,
        route_runoff_with_baseflow,
        soil_bucket_monthly,
    )

    t = np.asarray(temperature, dtype=np.float64)
    p = np.asarray(precipitation, dtype=np.float64)
    if t.shape != p.shape or t.ndim != 2 or t.shape[1] != 12:
        raise ValueError("monthly climate must contain matching (cells, 12) arrays")
    if not np.isfinite(t).all() or not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("monthly climate must be finite with nonnegative precipitation")
    pet = potential_evapotranspiration_hamon_monthly(t, REFERENCE_MONTH_DAYS)
    _e, runoff, _cycles, _resid = soil_bucket_monthly(p, pet, SOIL_WATER_CAPACITY_MM)
    runoff = route_runoff_with_baseflow(
        runoff,
        days_per_month=REFERENCE_MONTH_DAYS,
        recharge_fraction=(
            BASEFLOW_RECHARGE_FRACTION if recharge_fraction is None else recharge_fraction
        ),
        residence_time_days=(
            BASEFLOW_RESIDENCE_TIME_DAYS if residence_time_days is None else residence_time_days
        ),
    )
    shares = np.zeros_like(runoff)
    total = runoff.sum(axis=1)
    has_bucket = total > 1e-6
    shares[has_bucket] = runoff[has_bucket] / total[has_bucket, None]
    surplus = np.maximum(p - pet, 0.0)
    surplus_total = surplus.sum(axis=1)
    has_surplus = ~has_bucket & (surplus_total > 1e-6)
    shares[has_surplus] = surplus[has_surplus] / surplus_total[has_surplus, None]
    shares[~has_bucket & ~has_surplus] = 1.0 / 12.0
    return shares


def conditioning_fields(heights: np.ndarray, t: np.ndarray, p: np.ndarray) -> dict[str, np.ndarray]:
    """TD's five fields, from co-registered surface height and monthly climate."""
    if t.shape != p.shape or t.shape[:-1] != heights.shape or t.shape[-1] != 12:
        raise ValueError("conditioning climate must share the elevation grid and have 12 months")
    mean_p = p.mean(axis=-1)
    return {
        "elevation_m": heights,
        "temperature_mean_c": t.mean(axis=-1),
        "temperature_std_c": t.std(axis=-1),
        "precipitation_total_mm": p.sum(axis=-1),
        "precipitation_cv_pct": np.where(
            mean_p > 1e-9, p.std(axis=-1) / np.maximum(mean_p, 1e-9) * 100.0, 0.0
        ),
    }


def td_temperature_lapse_c_per_m(annual_precipitation_mm: np.ndarray) -> np.ndarray:
    """The existing precipitation-dependent terrain-conditioning convention."""
    return np.clip(-6.5 + 0.0015 * annual_precipitation_mm, -9.8, -4.0) / 1000.0


def write_refinement_inputs(
    input_dir: Path,
    fields: dict[str, np.ndarray],
    monthly_runoff: np.ndarray,
    *,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Write a validated, hashed input snapshot, keeping the existing pack grid."""
    if set(fields) != set(CONDITIONING_UNITS):
        raise ValueError("refinement inputs need all five conditioning fields")
    shape = fields["elevation_m"].shape
    if len(shape) != 2 or shape[0] != shape[1] or shape[0] < 2:
        raise ValueError("conditioning grid must be square with at least two pixels per side")
    for name, values in fields.items():
        if values.ndim != 2 or values.shape != shape or not np.isfinite(values).all():
            raise ValueError(f"invalid conditioning field {name}: expected finite {shape}")
    annual = annual_runoff(input_dir)
    monthly = np.asarray(monthly_runoff, dtype=np.float32)
    if monthly.shape != (*annual.shape, 12) or not np.isfinite(monthly).all():
        raise ValueError("monthly runoff must be a finite (pack height, pack width, 12) array")
    if (monthly < 0).any() or not np.allclose(monthly.sum(axis=-1), annual, rtol=2e-6, atol=1e-4):
        raise ValueError("monthly runoff must be nonnegative and sum to the pack's annual runoff")
    for name in ("temperature_std_c", "precipitation_total_mm", "precipitation_cv_pct"):
        if (fields[name] < 0).any():
            raise ValueError(f"conditioning field {name} must be nonnegative")
    records: dict[str, Any] = {}
    values_to_save = {**fields, "runoff_monthly_mm": monthly}
    for name, values in values_to_save.items():
        relative = f"refinement/{name}.npy"
        target = input_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".partial")
        with temporary.open("wb") as stream:
            np.save(stream, np.asarray(values, dtype=np.float32))
        temporary.replace(target)
        records[name] = {
            "path": relative,
            "sha256": file_sha256(target),
            "shape": list(values.shape),
            "units": CONDITIONING_UNITS.get(name, "mm per reference month"),
        }
    descriptor = {
        "version": REFINEMENT_INPUT_VERSION,
        "temperature_basis": "surface",
        "days_per_month": REFERENCE_MONTH_DAYS,
        "source": provenance,
        "height_sha256": file_sha256(input_dir / "height.meters.npy"),
        "annual_runoff_sha256": file_sha256(input_dir / "runoff.mm.npy"),
        "fields": records,
    }
    local_months = ("climate_monthly_T.npy", "climate_monthly_P.npy")
    if all((input_dir / name).exists() for name in local_months):
        descriptor["local_climate_sha256"] = {
            name: file_sha256(input_dir / name) for name in local_months
        }
    return descriptor


def read_refinement_inputs(input_dir: Path, descriptor: dict[str, Any]) -> dict[str, np.ndarray]:
    """Read the declared snapshot; incomplete or changed input never falls back."""
    if descriptor.get("version") != REFINEMENT_INPUT_VERSION:
        raise ValueError("unsupported region refinement input version")
    if descriptor.get("temperature_basis") != "surface":
        raise ValueError("refinement inputs must declare surface temperature")
    if descriptor.get("days_per_month") != REFERENCE_MONTH_DAYS:
        raise ValueError("refinement inputs must use the reference-month time basis")
    if "geometry" in descriptor:
        meta = json.loads((input_dir / "meta.json").read_text(encoding="utf-8"))
        if descriptor["geometry"] != {key: meta.get(key) for key in REFINEMENT_GEOMETRY_KEYS}:
            raise ValueError("refinement inputs no longer match the pack window; export again")
    for name, checksum in descriptor.get("local_climate_sha256", {}).items():
        if name not in ("climate_monthly_T.npy", "climate_monthly_P.npy"):
            raise ValueError("unexpected local climate input in refinement manifest")
        if file_sha256(input_dir / name) != checksum:
            raise ValueError("refinement inputs no longer match the local monthly climate")
    for stem, key in (("height.meters", "height_sha256"), ("runoff.mm", "annual_runoff_sha256")):
        path = input_dir / f"{stem}.npy"
        if file_sha256(path) != descriptor.get(key):
            raise ValueError(
                f"refinement input no longer matches {path.name}; export the pack again"
            )
    records = descriptor.get("fields", {})
    expected = {*CONDITIONING_UNITS, "runoff_monthly_mm"}
    if set(records) != expected:
        raise ValueError(
            "refinement input manifest must contain all conditioning and runoff fields"
        )
    result = {}
    for name, record in records.items():
        path = (input_dir / record["path"]).resolve()
        if not path.is_relative_to(input_dir.resolve()):
            raise ValueError("refinement input paths must stay inside the pack")
        if file_sha256(path) != record["sha256"]:
            raise ValueError(f"refinement input checksum mismatch: {name}")
        units = CONDITIONING_UNITS.get(name, "mm per reference month")
        if record.get("units") != units:
            raise ValueError(f"invalid refinement input units: {name}")
        values = np.load(path, allow_pickle=False, mmap_mode="r")
        if (
            values.dtype != np.float32
            or list(values.shape) != record["shape"]
            or not np.isfinite(values).all()
        ):
            raise ValueError(f"invalid refinement input array: {name}")
        result[name] = values
    shape = result["elevation_m"].shape
    if len(shape) != 2 or shape[0] != shape[1] or shape[0] < 2:
        raise ValueError("conditioning grid must be square with at least two pixels per side")
    for name in CONDITIONING_UNITS:
        if result[name].shape != shape:
            raise ValueError(f"conditioning grids do not match: {name}")
    for name in ("temperature_std_c", "precipitation_total_mm", "precipitation_cv_pct"):
        if (result[name] < 0).any():
            raise ValueError(f"conditioning field {name} must be nonnegative")
    annual = annual_runoff(input_dir)
    monthly = result["runoff_monthly_mm"]
    if monthly.shape != (*annual.shape, 12):
        raise ValueError("monthly runoff grid does not match the annual channel")
    for start in range(0, annual.shape[0], 64):
        block = monthly[start : start + 64]
        if (block < 0).any() or not np.allclose(
            block.sum(axis=-1), annual[start : start + 64], rtol=2e-6, atol=1e-4
        ):
            raise ValueError("monthly runoff must be nonnegative and sum to annual runoff")
    return result


def write_world_refinement_inputs(
    input_dir: Path,
    mesh: CVTMesh,
    window: RegionWindow,
    t: np.ndarray,
    p: np.ndarray,
    indices: np.ndarray,
    *,
    provenance: dict[str, Any],
    native_elevation_m: np.ndarray | None = None,
) -> dict[str, Any]:
    """Snapshot mesh climate and evaluate TD's temperature at the source surface."""
    import math

    from dreamulator.map.export import build_export_tree
    from dreamulator.map.region_export import _nearest_indices_on_grid, sample_native_elevation

    n = max(2, round(window.span_km / (math.pi * window.radius_km / 2047.0)))
    lon, lat = window.out_latlon(n)
    coarse_indices = _nearest_indices_on_grid(build_export_tree(mesh), lon, lat)
    height = np.fromiter((c.elevation for c in mesh.cells), dtype=np.float64, count=len(mesh.cells))
    fields = conditioning_fields(height[coarse_indices], t[coarse_indices], p[coarse_indices])
    if native_elevation_m is not None:
        native_height = sample_native_elevation(native_elevation_m, lon, lat)
        height_delta = np.maximum(0, native_height) - np.maximum(0, fields["elevation_m"])
        fields["temperature_mean_c"] += (
            td_temperature_lapse_c_per_m(fields["precipitation_total_mm"]) * height_delta
        )
        fields["elevation_m"] = native_height
    annual = annual_runoff(input_dir)
    monthly = runoff_on_grid(monthly_runoff_shape(t, p), indices, annual)
    return write_refinement_inputs(input_dir, fields, monthly, provenance=provenance)


def annual_runoff(input_dir: Path) -> np.ndarray:
    """Missing annual pixels contribute zero; invalid physical values fail."""
    annual = np.load(input_dir / "runoff.mm.npy", allow_pickle=False, mmap_mode="r")
    height = np.load(input_dir / "height.meters.npy", allow_pickle=False, mmap_mode="r")
    if annual.ndim != 2 or annual.shape != height.shape or annual.shape[0] != annual.shape[1]:
        raise ValueError("annual runoff must share the square pack elevation grid")
    if np.isinf(annual).any() or (annual < 0).any():
        raise ValueError("annual runoff must be nonnegative; missing pixels may be NaN")
    return np.asarray(np.nan_to_num(annual, nan=0.0))


def runoff_on_grid(shares: np.ndarray, indices: np.ndarray, annual: np.ndarray) -> np.ndarray:
    """Expand monthly shares in row blocks, without a full float64 monthly copy."""
    monthly = np.empty((*annual.shape, 12), dtype=np.float32)
    for start in range(0, annual.shape[0], 64):
        rows = slice(start, start + 64)
        monthly[rows] = shares[indices[rows]] * annual[rows, :, None]
    return monthly


def local_climate(input_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read co-registered surface climate on the local pack's coarse grid."""
    t = np.load(input_dir / "climate_monthly_T.npy", allow_pickle=False)
    p = np.load(input_dir / "climate_monthly_P.npy", allow_pickle=False)
    if t.ndim != 3 or t.shape != p.shape or t.shape[0] != t.shape[1] or t.shape[0] < 2:
        raise ValueError("local monthly climate must have matching square (N, N, 12) grids")
    if t.shape[-1] != 12 or not np.isfinite(t).all() or not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("local climate needs twelve finite months and nonnegative precipitation")
    return t, p


def local_conditioning(input_dir: Path) -> dict[str, np.ndarray]:
    """Use the prototype's bilinear height alignment and surface-month statistics."""
    t, p = local_climate(input_dir)
    height = np.load(input_dir / "height.meters.npy", allow_pickle=False)
    h = resize_local_field(height, t.shape[0])
    return conditioning_fields(h, t, p)


def local_runoff(input_dir: Path, **overrides: float | None) -> np.ndarray:
    """Nearest coarse-grid monthly shares, also for noninteger grid ratios."""
    t, p = local_climate(input_dir)
    annual = annual_runoff(input_dir)
    n, res = t.shape[0], annual.shape[0]
    nearest = np.minimum(((np.arange(res) + 0.5) * n / res).astype(int), n - 1)
    indices = nearest[:, None] * n + nearest[None, :]
    shares = monthly_runoff_shape(t.reshape(-1, 12), p.reshape(-1, 12), **overrides)
    return runoff_on_grid(shares, indices, annual)


def resize_local_field(values: np.ndarray, out_res: int) -> np.ndarray:
    """Bilinear local-grid resize with nearest boundary values, never zero padding.

    Endpoint-coordinate roundoff can place the last sample just beyond the
    source extent. Constant padding would turn deep sea into zero-metre shore.
    """
    from scipy.ndimage import zoom

    return np.asarray(
        zoom(
            values, (out_res / values.shape[0], out_res / values.shape[1]), order=1, mode="nearest"
        )
    )
