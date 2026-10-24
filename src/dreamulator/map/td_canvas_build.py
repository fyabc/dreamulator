"""td_canvas_build — S1 layout and per-canvas inputs of the global terrain-diffusion canvases.

The IO layer above ``td_canvas`` (which holds the geometry, layout and sampling maths):

* ``CanvasLayoutConfig`` — the author's layout choices for one world, read from YAML: the source
  branch, ``LandCut`` discs, fixed canvas ids (a land seed point per id), forced joins, per-canvas
  anisotropy-cap overrides and the generation parameters.
* ``plan_world_layout`` — land components, layout and ownership tables for a mesh.
* ``write_layout`` — ``layout.json``, ``owner_points.npy`` and ``owner_canvas.npy``.
* ``write_canvas_inputs`` — one canvas's ``canvas.json``, the five TD conditioning rasters and the
  coarse climate channels.

Conditioning is bit-reproducible: nearest CVT cell on a 4x grid then the block mean
(``sample_mesh_field``), temperature reduced to sea level with the region chain's lapse rate.
Climate channels: continuous fields by Clough–Tocher interpolation in the canvas plane, clipped
to each point's triangle-vertex range; land-only quantities are NaN on ocean coarse cells
(block-mean height <= 0); monthly runoff and the class codes use ``sample_mesh_field``.  Derived
channels (runoff, PET) are computed per CVT cell first, then sampled.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml
from pydantic import BaseModel, Field

from . import td_canvas as tc

if TYPE_CHECKING:
    from pathlib import Path

    from .models import CVTMesh

#: Default generation parameters: the 90 m model, the region chain's seed and condition SNRs,
#: fp32, upstream tiff_export's 64-cell edge padding.  A layout records them; any change makes
#: a different world.
DEFAULT_GENERATION: dict[str, Any] = {
    "model": "xandergos/terrain-diffusion-90m",
    "model_revision": "2bb1a93141140040091d44f0770d4ba22c8cf145",
    "td_commit": "e8dcb4b1a834ab2f6b1a6f5256ed7c9f2f3e8230",
    "seed": 42,
    "cond_snr": [0.2, 0.2, 1.0, 0.2, 1.0],
    "dtype": "fp32",
    "torch_compile": True,
    "edge_padding_cells": 64,
}
LAYOUT_FORMAT = "td-canvas-layout-v1"
CANVAS_FORMAT = "td-canvas-v1"
#: Climate channels whose values exist on land only (NaN on ocean coarse cells).
LAND_ONLY = ("runoff.mm", "pet_hamon.mm", "npp.gc_m2_yr", "runoff_monthly.mm")
UNITS = {
    "temperature.C": "degC",
    "precipitation.mm": "mm/yr",
    "runoff.mm": "mm/yr",
    "pet_hamon.mm": "mm/yr",
    "temperature_monthly.C": "degC",
    "precipitation_monthly.mm": "mm/month",
    "runoff_monthly.mm": "mm/month",
    "ice.m": "m",
    "npp.gc_m2_yr": "gC/m2/yr",
    "koppen.codes": "code",
    "biome.codes": "code",
}


class CutSpec(BaseModel):
    lat: float
    lon: float
    radius_km: float
    reattach: bool = False


class JoinSpec(BaseModel):
    """A land seed point whose component must join the canvas of another seed point."""

    point: tuple[float, float]
    into: tuple[float, float]


class CanvasLayoutConfig(BaseModel):
    """Author layout choices for one world (``canvas_layout.yaml``)."""

    branch: str | None = None
    planet: str | None = None
    cuts: list[CutSpec] = Field(default_factory=list)
    #: canvas id -> a (lat, lon) seed point on its land
    names: dict[str, tuple[float, float]] = Field(default_factory=dict)
    joins: list[JoinSpec] = Field(default_factory=list)
    #: canvas id -> anisotropy cap allowed for it (above the layout cap)
    max_anisotropy_overrides: dict[str, float] = Field(default_factory=dict)
    generation: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> CanvasLayoutConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def land_cuts(self) -> tuple[tc.LandCut, ...]:
        return tuple(tc.LandCut(c.lat, c.lon, c.radius_km, c.reattach) for c in self.cuts)

    def generation_params(self) -> dict[str, Any]:
        return {**DEFAULT_GENERATION, **self.generation}


@dataclass
class WorldLayout:
    land: tc.LandModel
    plans: list[tc.CanvasPlan]


def _component_at(land: tc.LandModel, lat: float, lon: float) -> int:
    """Component of the land cell nearest to (lat, lon)."""
    v = tc.unit_vectors(np.array(lat), np.array(lon))
    k = int(np.argmax(np.where(land.labels >= 0, land.xyz @ v, -2)))
    return int(land.labels[k])


def plan_world_layout(mesh: CVTMesh, radius_km: float, cfg: CanvasLayoutConfig) -> WorldLayout:
    """Land components and canvas layout; raises when a canvas exceeds its anisotropy cap."""
    land = tc.land_components(mesh, radius_km, cfg.land_cuts())
    names = {_component_at(land, *p): cid for cid, p in cfg.names.items()}
    joins = {_component_at(land, *j.point): _component_at(land, *j.into) for j in cfg.joins}
    plans, over = tc.plan_layout(land, names=names, joins=joins)
    for p in plans:
        cap = cfg.max_anisotropy_overrides.get(p.canvas_id)
        if cap is not None and p.max_anisotropy <= cap:
            over = [c for c in over if c not in p.components]
    if over:
        raise ValueError(f"components over the anisotropy cap without an override: {over}")
    return WorldLayout(land, plans)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_layout(
    root: Path, layout: WorldLayout, cfg: CanvasLayoutConfig, source: dict[str, Any]
) -> None:
    """``layout.json`` and the ownership tables (``owner_of`` inputs) under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    pts, owner = [], []
    for k, p in enumerate(layout.plans):
        m = np.isin(layout.land.labels, p.components)
        pts.append(layout.land.xyz[m])
        owner.append(np.full(int(m.sum()), k, dtype=np.int16))
    np.save(root / "owner_points.npy", np.concatenate(pts).astype(np.float64))
    np.save(root / "owner_canvas.npy", np.concatenate(owner))
    doc = {
        "format": LAYOUT_FORMAT,
        "buffer_km": tc.BUFFER_KM,
        "max_anisotropy": tc.MAX_ANISOTROPY,
        "shelf_reach_km": tc.SHELF_REACH_KM,
        "shelf_floor_m": tc.SHELF_FLOOR_M,
        "max_anisotropy_overrides": cfg.max_anisotropy_overrides,
        "joins": [{"from": list(j.point), "into": list(j.into)} for j in cfg.joins],
        "cuts": [c.model_dump() for c in cfg.cuts],
        "generation": cfg.generation_params(),
        "source": source,
        "canvases": [
            {
                "id": p.canvas_id,
                "geometry": p.geometry.to_dict(),
                "components": p.components,
                "land_km2": round(p.land_km2, 1),
                "max_anisotropy": round(p.max_anisotropy, 4),
                "chunks": len(p.chunks),
            }
            for p in layout.plans
        ],
    }
    (root / "layout.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")


def clough_tocher(
    geom: tc.CanvasGeometry, values: np.ndarray, cell_lat: np.ndarray, cell_lon: np.ndarray
) -> np.ndarray:
    """C1 interpolation of a per-cell column onto the coarse-cell centres, vertex-range clipped."""
    from scipy.interpolate import CloughTocher2DInterpolator

    x, y = geom.latlon_to_xy(cell_lat, cell_lon)
    lim = geom.half_km + 3 * tc.TD_COARSE_KM * tc.OVERSAMPLE * 4
    rho = np.hypot(x, y)
    sel = (np.abs(x) <= lim) & (np.abs(y) <= lim) & (rho < 0.9 * np.pi * geom.radius_km)
    sel &= ~np.isnan(values)
    pts, v = np.column_stack([x[sel], y[sel]]), values[sel]
    s = (np.arange(geom.ncell) + 0.5) / geom.ncell * 2 * geom.half_km - geom.half_km
    gx, gy = np.meshgrid(s, s[::-1])
    interp = CloughTocher2DInterpolator(pts, v)
    q = np.column_stack([gx.ravel(), gy.ravel()])
    out = interp(q)
    simplex = interp.tri.find_simplex(q)
    inside = (simplex >= 0) & ~np.isnan(out)
    verts = v[interp.tri.simplices[simplex[inside]]]
    out[inside] = np.clip(out[inside], verts.min(axis=1), verts.max(axis=1))
    return np.asarray(np.clip(out, v.min(), v.max()).reshape(geom.ncell, geom.ncell))


@dataclass
class MeshColumns:
    """Per-cell columns the inputs are built from (mesh-cell order)."""

    lat: np.ndarray
    lon: np.ndarray
    xyz: np.ndarray
    elevation_m: np.ndarray
    is_ocean: np.ndarray
    ice_m: np.ndarray
    npp: np.ndarray
    koppen: list[str | None]
    biome: list[str | None]
    t_monthly_c: np.ndarray  # (n, 12)
    p_monthly_mm: np.ndarray  # (n, 12)

    @classmethod
    def from_mesh(
        cls, mesh: CVTMesh, t_monthly_c: np.ndarray, p_monthly_mm: np.ndarray
    ) -> MeshColumns:
        cells = mesh.cells
        lat = np.array([c.lat for c in cells])
        lon = np.array([c.lon for c in cells])

        def col(field: str, none_as: float = np.nan) -> np.ndarray:
            vals = [getattr(c, field) for c in cells]
            return np.array([none_as if v is None else float(v) for v in vals])

        return cls(
            lat=lat,
            lon=lon,
            xyz=tc.unit_vectors(lat, lon),
            elevation_m=np.array([c.elevation for c in cells], dtype=np.float64),
            is_ocean=np.array([c.water_class == "ocean" for c in cells]),
            ice_m=col("ice_thickness_m", 0.0),
            npp=col("npp_gc_m2_yr"),
            koppen=[c.koppen_class for c in cells],
            biome=[c.biome for c in cells],
            t_monthly_c=t_monthly_c,
            p_monthly_mm=p_monthly_mm,
        )


def _runoff_cells(cols: MeshColumns) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-cell annual Hamon PET, annual Turc–Pike runoff and monthly runoff (region chain)."""
    from dreamulator.engine.climate_physics import (
        BASEFLOW_RECHARGE_FRACTION,
        BASEFLOW_RESIDENCE_TIME_DAYS,
        SOIL_WATER_CAPACITY_MM,
        annual_runoff_turc_pike,
        potential_evapotranspiration_hamon,
        potential_evapotranspiration_hamon_monthly,
        route_runoff_with_baseflow,
        soil_bucket_monthly,
    )
    from dreamulator.result_contract import REFERENCE_MONTH_DAYS

    t_m, p_m = cols.t_monthly_c, cols.p_monthly_mm
    pet_annual = potential_evapotranspiration_hamon(t_m, REFERENCE_MONTH_DAYS)
    runoff_annual = annual_runoff_turc_pike(p_m.sum(1), pet_annual)
    pet_m = potential_evapotranspiration_hamon_monthly(t_m, REFERENCE_MONTH_DAYS)
    _e, r_m, _cy, _res = soil_bucket_monthly(p_m, pet_m, SOIL_WATER_CAPACITY_MM)
    r_m = route_runoff_with_baseflow(
        r_m,
        days_per_month=REFERENCE_MONTH_DAYS,
        recharge_fraction=BASEFLOW_RECHARGE_FRACTION,
        residence_time_days=BASEFLOW_RESIDENCE_TIME_DAYS,
    )
    # monthly shape: bucket runoff, else the P - PET surplus, else uniform; times the annual runoff
    shape = np.zeros_like(r_m)
    tot = r_m.sum(1)
    hb = tot > 1e-6
    shape[hb] = r_m[hb] / tot[hb, None]
    surplus = np.maximum(p_m - pet_m, 0.0)
    st = surplus.sum(1)
    hs = ~hb & (st > 1e-6)
    shape[hs] = surplus[hs] / st[hs, None]
    shape[~hb & ~hs] = 1.0 / 12.0
    return pet_annual, runoff_annual, shape * runoff_annual[:, None]


def write_canvas_inputs(
    root: Path,
    plan: tc.CanvasPlan,
    cols: MeshColumns,
    generation: dict[str, Any],
    source: dict[str, Any],
) -> Path:
    """Write ``<root>/<canvas_id>/`` (canvas.json, conditioning/, climate/); returns the dir."""
    geom = plan.geometry
    out = root / plan.canvas_id
    (out / "conditioning").mkdir(parents=True, exist_ok=True)
    (out / "climate").mkdir(parents=True, exist_ok=True)
    t_m, p_m, xyz = cols.t_monthly_c, cols.p_monthly_mm, cols.xyz
    p_mean = p_m.mean(1)

    cond = {
        "heightmap": tc.sample_mesh_field(geom, cols.elevation_m, xyz),
        "temperature": tc.sample_mesh_field(geom, t_m.mean(1), xyz),
        "temperature_std": tc.sample_mesh_field(geom, t_m.std(1), xyz),
        "precipitation": tc.sample_mesh_field(geom, p_m.sum(1), xyz),
        "precipitation_cv": tc.sample_mesh_field(
            geom, np.where(p_mean > 1e-9, p_m.std(1) / np.maximum(p_mean, 1e-9) * 100, 0.0), xyz
        ),
    }
    # sea-level temperature, lapse rate from precipitation as in the region chain's refine
    lapse = np.clip(-6.5 + 0.0015 * cond["precipitation"], -9.8, -4.0) / 1000.0
    cond["temperature"] = cond["temperature"] - lapse * np.maximum(0.0, cond["heightmap"])
    cond_sha = {}
    for name, arr in cond.items():
        f = out / "conditioning" / f"{name}.npy"
        np.save(f, arr.astype(np.float32))
        cond_sha[name] = sha256_file(f)
    ocean_cell = cond["heightmap"] <= 0.0

    pet_annual, runoff_annual, runoff_monthly = _runoff_cells(cols)
    lat, lon = cols.lat, cols.lon

    def land_only(v: np.ndarray) -> np.ndarray:
        return np.where(cols.is_ocean.reshape(-1, *([1] * (np.ndim(v) - 1))), np.nan, v)

    climate: dict[str, np.ndarray] = {
        "temperature.C": clough_tocher(geom, t_m.mean(1), lat, lon),
        "precipitation.mm": clough_tocher(geom, p_m.sum(1), lat, lon),
        "runoff.mm": clough_tocher(geom, land_only(runoff_annual), lat, lon),
        "pet_hamon.mm": clough_tocher(geom, land_only(pet_annual), lat, lon),
        "temperature_monthly.C": np.stack(
            [clough_tocher(geom, t_m[:, k], lat, lon) for k in range(12)]
        ),
        "precipitation_monthly.mm": np.stack(
            [clough_tocher(geom, p_m[:, k], lat, lon) for k in range(12)]
        ),
        "runoff_monthly.mm": tc.sample_mesh_field(geom, land_only(runoff_monthly), xyz),
        "ice.m": clough_tocher(geom, cols.ice_m, lat, lon),
        "npp.gc_m2_yr": clough_tocher(geom, land_only(cols.npp), lat, lon),
    }
    for name in LAND_ONLY:
        climate[name] = np.where(ocean_cell, np.nan, climate[name])
    climate["ice.m"] = np.where(ocean_cell, 0.0, np.maximum(climate["ice.m"], 0.0))
    for name in ("precipitation.mm", "precipitation_monthly.mm"):
        climate[name] = np.maximum(climate[name], 0.0)
    legends = {}
    for chan, labels in (("koppen.codes", cols.koppen), ("biome.codes", cols.biome)):
        uniq = sorted({v for v in labels if v})
        code = {v: i + 1 for i, v in enumerate(uniq)}
        codes = np.array([code.get(v, 0) if v else 0 for v in labels], dtype=np.uint8)
        climate[chan] = tc.sample_mesh_field(geom, codes, xyz, categorical=True).astype(np.uint8)
        legends[chan] = {str(i): v for v, i in code.items()}
    climate_meta = {}
    for name, arr in climate.items():
        f = out / "climate" / f"{name}.npy"
        np.save(f, arr if arr.dtype == np.uint8 else arr.astype(np.float32))
        categorical = arr.dtype == np.uint8
        if categorical:
            missing, sampling = "0 = missing", "nearest at coarse centre"
        else:
            missing = "NaN on ocean coarse cells" if name in LAND_ONLY else "none"
            sampling = (
                "nearest on 4x grid, block mean"
                if name == "runoff_monthly.mm"
                else "Clough-Tocher, vertex-range clipped"
            )
        climate_meta[name] = {
            "units": UNITS[name],
            "shape": list(arr.shape),
            "missing": missing,
            "sampling": sampling,
        }

    canvas = {
        "format": CANVAS_FORMAT,
        "id": plan.canvas_id,
        "geometry": geom.to_dict(),
        "components": plan.components,
        "land_km2": round(plan.land_km2, 1),
        "max_anisotropy": round(plan.max_anisotropy, 4),
        "chunks": [list(c) for c in plan.chunks],
        "elevation": {"dtype": "int16", "units": "m", "sea_level_m": 0.0, "row0": "north"},
        "conditioning_sha256": cond_sha,
        "climate": climate_meta,
        "legends": legends,
        "generation": generation,
        "source": source,
    }
    (out / "canvas.json").write_text(
        json.dumps(canvas, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    return out


def read_chunk_checksums(canvas_dir: Path) -> dict[str, str]:
    """``chunks.sha256`` as {file name: digest} (empty when absent)."""
    f = canvas_dir / "chunks.sha256"
    if not f.exists():
        return {}
    out = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            out[name.strip()] = digest
    return out


def chunk_name(ci: int, cj: int) -> str:
    return f"r{ci:03d}_c{cj:03d}.npy"


def canvas_status(canvas_dir: Path, *, verify: bool = False) -> dict[str, int]:
    """Counts of a canvas's manifest: done (file + listed checksum), missing, and — with
    ``verify`` — corrupt (file present but its checksum differs or is unlisted)."""
    meta = json.loads((canvas_dir / "canvas.json").read_text(encoding="utf-8"))
    listed = read_chunk_checksums(canvas_dir)
    done = missing = corrupt = 0
    for ci, cj in meta["chunks"]:
        name = chunk_name(ci, cj)
        p = canvas_dir / "chunks" / name
        if not p.exists():
            missing += 1
        elif name not in listed or (verify and sha256_file(p) != listed[name]):
            corrupt += 1
        else:
            done += 1
    return {"chunks": len(meta["chunks"]), "done": done, "missing": missing, "corrupt": corrupt}
