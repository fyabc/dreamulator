"""Build a standalone region pack from a local heightmap and declared climate."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from dreamulator.engine.climate_physics import (
    annual_runoff_turc_pike,
    potential_evapotranspiration_hamon,
)
from dreamulator.map.export import export_elevation_png, save_rgba_png
from dreamulator.map.importer import import_heightmap_metres
from dreamulator.map.palettes import build_adaptive_terrain_lut
from dreamulator.map.region_export import (
    PACK_VERSION,
    _export_headwaters,
    _export_scalar_channel,
    region_window,
)
from dreamulator.map.region_inputs import (
    conditioning_fields,
    file_sha256,
    local_runoff,
    resize_local_field,
    write_refinement_inputs,
)
from dreamulator.result_contract import REFERENCE_MONTH_DAYS

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.map.models import ElevationMapping


class LocalMonthlyClimate(BaseModel):
    """Twelve surface-temperature means and precipitation totals, or local NPY grids."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    temperature_basis: Literal["surface"]
    days_per_month: float = REFERENCE_MONTH_DAYS
    temperature_c: list[float] | str = Field(alias="temperature_C")
    precipitation_mm: list[float] | str
    description: str


def load_local_climate(path: Path, n: int) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """A pair of uniform twelve-month series, or matching square spatial arrays."""
    spec = LocalMonthlyClimate.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if spec.days_per_month != REFERENCE_MONTH_DAYS:
        raise ValueError("local climate must use 365.25 / 12 days per reference month")

    def read(value: list[float] | str) -> np.ndarray:
        if isinstance(value, str):
            return np.asarray(np.load(path.parent / value, allow_pickle=False), dtype=np.float64)
        return np.asarray(value, dtype=np.float64)

    t, p = read(spec.temperature_c), read(spec.precipitation_mm)
    if t.shape != p.shape:
        raise ValueError("temperature and precipitation must have matching monthly grids")
    if t.shape == (12,):
        t, p = (np.broadcast_to(a, (n, n, 12)).copy() for a in (t, p))
    if t.ndim != 3 or t.shape[0] != t.shape[1] or t.shape[0] < 2 or t.shape[-1] != 12:
        raise ValueError("climate needs twelve values or square (N, N, 12) NPY arrays")
    if not np.isfinite(t).all() or not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("climate must be finite with nonnegative monthly precipitation")
    source: dict[str, Any] = {
        "description": spec.description,
        "temperature_basis": spec.temperature_basis,
        "days_per_month": spec.days_per_month,
        "sha256": file_sha256(path),
        "grid": list(t.shape),
    }
    for key in ("temperature_C", "precipitation_mm"):
        value = spec.temperature_c if key == "temperature_C" else spec.precipitation_mm
        if isinstance(value, str):
            source[f"{key}_sha256"] = file_sha256(path.parent / value)
    return t, p, source


def import_region_pack(
    image: Path,
    climate_file: Path,
    mapping: ElevationMapping,
    *,
    px_km: float,
    out_dir: Path,
    out_res: int = 2048,
    center_lat: float = 0.0,
    center_lon: float = 0.0,
    radius_km: float = 6371.0,
    seafloor_clamp_m: float = -400.0,
) -> dict[str, Any]:
    """Import a north-up square image. Location is an explicit AEQ placement assumption."""
    if not math.isfinite(px_km) or px_km <= 0 or out_res < 2:
        raise ValueError("source px_km must be positive and out_res must be at least two")
    if not all(math.isfinite(x) for x in (center_lat, center_lon, radius_km, seafloor_clamp_m)):
        raise ValueError("placement and height limits must be finite")
    if radius_km <= 0 or abs(center_lat) > 90 or abs(center_lon) > 180:
        raise ValueError("placement needs a positive radius and valid latitude/longitude")
    if mapping.sea_level_m != 0.0:
        raise ValueError("local refinement currently requires sea_level_m = 0")
    if seafloor_clamp_m >= 0:
        raise ValueError("seafloor clamp must be below sea level")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("output input directory must be empty; use a new pack for new forcing")
    imported = import_heightmap_metres(
        image.read_bytes(),
        mapping,
        filename=image.name,
        target_width=out_res,
        target_height=out_res,
        global_map=False,
    )
    if imported.source_width != imported.source_height:
        raise ValueError("standalone region heightmap must be square; crop it before import")
    span = imported.source_width * px_km
    region_window(center_lat, center_lon, span, radius_km)
    n = max(2, round(span / (math.pi * radius_km / 2047.0)))
    t, p, climate_source = load_local_climate(climate_file, n)
    height = imported.metres.astype(np.float32)
    coarse_height = resize_local_field(height, t.shape[0])
    fields = conditioning_fields(coarse_height, t, p)
    pet = potential_evapotranspiration_hamon(t.reshape(-1, 12), REFERENCE_MONTH_DAYS)
    annual = annual_runoff_turc_pike(p.sum(axis=-1).ravel(), pet).reshape(t.shape[:2])
    scalars = {
        "temperature_C": ("temperature.C", fields["temperature_mean_c"]),
        "precipitation_mm": ("precipitation.mm", fields["precipitation_total_mm"]),
        "runoff_mm": ("runoff.mm", annual),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "height.meters.npy", height)
    np.save(out_dir / "climate_monthly_T.npy", t)
    np.save(out_dir / "climate_monthly_P.npy", p)
    climate_meta: dict[str, Any] = {}
    sampled: dict[str, np.ndarray] = {}
    for name, (stem, values) in scalars.items():
        values = resize_local_field(values, out_res)
        sampled[name] = values
        climate_meta[name] = _export_scalar_channel(
            values,
            out_dir,
            stem,
            png_min=0.0,
            png_max=float(values.max()),
            png=name == "precipitation_mm",
        )
    climate_meta["runoff_mm"].update(
        units="mm per reference year", criterion="Turc-Pike annual P vs Hamon annual PET"
    )
    climate_meta["headwaters"] = _export_headwaters(
        height, sampled["precipitation_mm"], sampled["temperature_C"], 0.0, out_dir
    )
    nearest = np.minimum(
        ((np.arange(out_res) + 0.5) * t.shape[0] / out_res).astype(int), t.shape[0] - 1
    )
    freeze = (t < 0).sum(axis=-1).astype(np.uint8)
    np.save(out_dir / "lake_ice.months.npy", freeze[nearest[:, None], nearest[None, :]])
    climate_meta["lake_ice_months"] = {"units": "months with mean surface temperature < 0 degC"}
    h_min, h_max = float(height.min()), float(height.max())
    gaea = np.maximum(height, seafloor_clamp_m)
    gaea_min, gaea_max = float(gaea.min()), float(gaea.max())
    export_elevation_png(height, out_dir / "height.png", min_m=h_min, max_m=h_max)
    export_elevation_png(gaea, out_dir / "height.gaea.png", min_m=gaea_min, max_m=gaea_max)
    lut = build_adaptive_terrain_lut(h_min, h_max, 0.0)
    ix = np.clip(
        np.rint((height - h_min) / (h_max - h_min or 1.0) * (len(lut) - 1)), 0, len(lut) - 1
    ).astype(int)
    rgba = np.full((*height.shape, 4), 255, dtype=np.uint8)
    rgba[..., :3] = lut[ix]
    save_rgba_png(rgba, out_dir / "color.png")
    source = {
        "kind": "external-heightmap",
        "world": "external",
        "planet": "external",
        "image": image.name,
        "image_sha256": file_sha256(image),
        "source_resolution": [imported.source_width, imported.source_height],
        "px_km": px_km,
        "elevation_mapping": mapping.model_dump(),
        "seafloor_assumed": imported.seafloor_assumed,
        "level_step_m": imported.level_step_m,
        "warnings": imported.warnings,
        "climate": climate_source,
        "placement": "north-up local image placed on an assumed azimuthal-equidistant plane",
    }
    meta = {
        "pack_version": PACK_VERSION,
        "projection": "azimuthal_equidistant",
        "center_lat": center_lat,
        "center_lon": center_lon,
        "radius_km": radius_km,
        "span_km": span,
        "grid": {"w": out_res, "h": out_res},
        "extent_km": {"x": span, "y": span},
        "km_per_px": {"x": span / out_res, "y": span / out_res},
        "cell_pitch_km": span / t.shape[0],
        "sampling": "source-class-aware elevation; bilinear annual fields; nearest monthly shares",
        "elevation_m": {"min": h_min, "max": h_max},
        "elevation_m_global": [h_min, h_max],
        "height_png_range_m": [h_min, h_max],
        "height_gaea_png_range_m": [gaea_min, gaea_max],
        "seafloor_clamp_m": seafloor_clamp_m,
        "sea_level_m": 0.0,
        "ocean_fraction": float((~imported.land).mean()),
        "source": source,
        "climate": climate_meta,
        "refinement_inputs": write_refinement_inputs(
            out_dir, fields, local_runoff(out_dir), provenance=source
        ),
    }
    if "refinement_inputs" in meta:
        from dreamulator.map.region_inputs import REFINEMENT_GEOMETRY_KEYS

        meta["refinement_inputs"]["geometry"] = {key: meta[key] for key in REFINEMENT_GEOMETRY_KEYS}
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return meta
