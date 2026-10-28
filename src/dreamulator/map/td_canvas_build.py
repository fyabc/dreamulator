"""td_canvas_build — S1 layout and per-canvas inputs of the global terrain-diffusion canvases.

The IO layer above ``td_canvas`` (which holds the geometry, layout and sampling maths):

* ``CanvasLayoutConfig`` — the author's layout choices for one world, read from YAML: the source
  branch, ``LandCut`` discs, fixed canvas ids (a land seed point per id), forced joins, per-canvas
  anisotropy-cap overrides and the generation parameters.
* ``plan_world_layout`` — land components, layout and ownership tables for a mesh.
* ``write_layout`` — ``layout.json``, ``owner_points.npy`` and ``owner_canvas.npy``.
* ``write_canvas_inputs`` — one canvas's ``canvas.json``, the five TD conditioning rasters and the
  coarse climate channels.

Conditioning is bit-reproducible.  The height base is anti-aliased (``antialiased_height``):
Clough–Tocher values on the 4x grid with the land/sea sign of the signed distance to the mesh coast
low-passed at half the mesh spacing, then the block mean; the structure field (when enabled) is
added without changing that land/sea sign.  The other channels take the nearest CVT cell on the
4x grid then the block mean (``sample_mesh_field``); temperature is reduced to sea level with the
region chain's lapse rate, referred to the cell-mean height.
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

    from dreamulator.gcm.native_partition import NativePrecipitationField

    from .canvas_precipitation import CanvasPrecipitationCoverage
    from .models import CVTMesh
    from .terrain_source import TerrainSource

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
#: Recorded in canvas.json: how the height conditioning base was sampled (``antialiased_height``).
HEIGHT_SAMPLING = "antialias-v1"
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
    #: add the zero-mean tectonic structure field to the height conditioning (td_canvas_structure)
    structure: bool = False

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


def install_planned_inputs(staged: Path, root: Path) -> None:
    """Install verified input files, retaining existing chunks and unrelated assets.

    The caller prepares and validates the whole selected batch first. File
    replacement keeps an existing input symlink's source unchanged. Directory
    symlinks inside the output root are rejected before any files are installed.
    IO errors during installation can leave an already installed subset.
    """
    files = sorted(
        (path for path in staged.rglob("*") if path.is_file()),
        key=lambda path: (
            path.name in ("canvas.json", "layout.json"),
            path.name == "layout.json",
            str(path.relative_to(staged)),
        ),
    )
    if root.exists() and not root.is_dir():
        raise ValueError(f"canvas root is not a directory: {root}")
    for path in files:
        relative = path.relative_to(staged)
        target = root / relative
        if target.is_dir():
            raise ValueError(f"planned input file is an existing directory: {target}")
        for i in range(1, len(relative.parts)):
            folder = root.joinpath(*relative.parts[:i])
            if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
                raise ValueError(f"planned input directory must be a regular directory: {folder}")
    for path in files:
        target = root / path.relative_to(staged)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)


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
        "structure": cfg.structure,
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
    geom: tc.CanvasGeometry,
    values: np.ndarray,
    cell_lat: np.ndarray,
    cell_lon: np.ndarray,
    *,
    oversample: int = 1,
) -> np.ndarray:
    """C1 interpolation of a per-cell column onto the coarse-cell centres, vertex-range clipped.

    ``oversample`` > 1 evaluates on the ``oversample``-times finer grid instead (row 0 north).
    """
    from scipy.interpolate import CloughTocher2DInterpolator

    x, y = geom.latlon_to_xy(cell_lat, cell_lon)
    lim = geom.half_km + 3 * tc.TD_COARSE_KM * tc.OVERSAMPLE * 4
    rho = np.hypot(x, y)
    sel = (np.abs(x) <= lim) & (np.abs(y) <= lim) & (rho < 0.9 * np.pi * geom.radius_km)
    sel &= ~np.isnan(values)
    nf = geom.ncell * oversample
    if not sel.any():
        return np.full((nf, nf), np.nan)
    pts, v = np.column_stack([x[sel], y[sel]]), values[sel]
    s = (np.arange(nf) + 0.5) / nf * 2 * geom.half_km - geom.half_km
    gx, gy = np.meshgrid(s, s[::-1])
    interp = CloughTocher2DInterpolator(pts, v)
    q = np.column_stack([gx.ravel(), gy.ravel()])
    out = interp(q)
    simplex = interp.tri.find_simplex(q)
    inside = (simplex >= 0) & ~np.isnan(out)
    verts = v[interp.tri.simplices[simplex[inside]]]
    out[inside] = np.clip(out[inside], verts.min(axis=1), verts.max(axis=1))
    return np.asarray(np.clip(out, v.min(), v.max()).reshape(nf, nf))


def antialiased_height(
    geom: tc.CanvasGeometry,
    elevation_m: np.ndarray,
    cell_lat: np.ndarray,
    cell_lon: np.ndarray,
    cell_xyz: np.ndarray,
    *,
    oversample: int = tc.OVERSAMPLE,
) -> np.ndarray:
    """Height conditioning base (ncell, ncell) that carries only the scales the mesh resolves.

    Nearest-cell sampling turns every CVT cell into a flat step and puts the coast on Voronoi
    polygon edges; under the strong height condition TD reproduces both (proposal
    canvas-conditioning-structure §4.2).  On the ``oversample`` grid the values come from
    ``clough_tocher`` (no cell plateaus) and the land/sea sign from the signed distance to the
    mesh coast (elevation > 0 m), Gaussian low-passed with sigma = half the mesh spacing (median
    nearest-neighbour distance of the cell centres), which
    removes the mesh-scale saw-tooth of the coast; within a quarter spacing of each cell centre the
    cell's own sign is kept, so no mesh land or sea cell disappears (single-cell islands survive);
    pixels where sign and value disagree get +-1 m.  The
    land labels are taken on a grid padded by three sigma so the low-pass sees coasts beyond the
    canvas edge; outside the interpolation hull (partial meshes only) values fall back to the
    nearest cell.  The block mean gives the coarse grid.  The only scale is the mesh spacing.
    """
    from scipy import ndimage as ndi
    from scipy.spatial import cKDTree

    px_km = tc.TD_COARSE_KM / oversample
    tree = cKDTree(cell_xyz)
    nn_chord = tree.query(cell_xyz, k=2)[0][:, 1]
    spacing_km = float(np.median(2 * np.arcsin(nn_chord / 2)) * geom.radius_km)
    sigma_px = 0.5 * spacing_km / px_km
    pad = int(np.ceil(3 * sigma_px / oversample)) + 1  # coarse cells
    big = tc.CanvasGeometry(geom.center_lat, geom.center_lon, geom.radius_km, geom.ncell + 2 * pad)
    la, lo = big.coarse_centres_latlon(oversample)
    chord, idx = tree.query(tc.unit_vectors(la, lo).reshape(-1, 3))
    land = (np.asarray(elevation_m)[idx] > 0).reshape(la.shape)
    sdf = ndi.distance_transform_edt(land) - ndi.distance_transform_edt(~land)
    crop = slice(pad * oversample, (pad + geom.ncell) * oversample)
    is_land = ndi.gaussian_filter(sdf, sigma_px)[crop, crop] > 0
    # every cell keeps its own land/sea sign near its centre (single-cell islands survive)
    near_km = (2 * np.arcsin(chord / 2) * geom.radius_km).reshape(la.shape)[crop, crop]
    centre = near_km < 0.25 * spacing_km
    is_land = np.where(centre, land[crop, crop], is_land)
    value = clough_tocher(geom, elevation_m, cell_lat, cell_lon, oversample=oversample)
    # outside the interpolation hull (only on partial meshes) fall back to the nearest cell
    nearest = np.asarray(elevation_m, dtype=np.float64)[idx].reshape(la.shape)[crop, crop]
    value = np.where(np.isnan(value), nearest, value)
    fine = np.where(is_land, np.maximum(value, 1.0), np.minimum(value, -1.0))
    n = geom.ncell
    return np.asarray(fine.reshape(n, oversample, n, oversample).mean(axis=(1, 3)))


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
    relief_std_m: np.ndarray | None = None  # sub-grid relief (NaN off land)

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
            relief_std_m=np.array(
                [
                    np.nan if getattr(c, "relief_std_m", None) is None else c.relief_std_m
                    for c in cells
                ],
                dtype=np.float64,
            ),
        )


def _runoff_cells(cols: MeshColumns) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return _runoff_arrays(cols.t_monthly_c, cols.p_monthly_mm)


def _runoff_arrays(t_m: np.ndarray, p_m: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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
    *,
    structure: bool = False,
    height_source: TerrainSource | None = None,
    height_quadrature: int = 8,
    precipitation_field: NativePrecipitationField | None = None,
) -> Path:
    """Write ``<root>/<canvas_id>/`` (canvas.json, conditioning/, climate/); returns the dir.

    With ``structure`` the height conditioning gets the zero-mean tectonic structure field
    (``td_canvas_structure.structure_anomaly``); the sea-level temperature reduction keeps using
    the cell-mean height, the height the mesh temperature refers to.
    ``height_source`` supplies an independently queryable surface. Its spherical footprint
    averages replace the height base; fractional land coverage is saved as source geometry.
    """
    geom = plan.geometry
    precipitation_coverage = None
    if precipitation_field is not None:
        from .canvas_precipitation import canvas_precipitation_coverage

        _check_precipitation_radius(geom, precipitation_field)
        precipitation_coverage = canvas_precipitation_coverage(precipitation_field.partition, geom)
    out = root / plan.canvas_id
    (out / "conditioning").mkdir(parents=True, exist_ok=True)
    (out / "climate").mkdir(parents=True, exist_ok=True)
    t_m, p_m, xyz = cols.t_monthly_c, cols.p_monthly_mm, cols.xyz
    p_mean = p_m.mean(1)

    cell_mean_height = tc.sample_mesh_field(geom, cols.elevation_m, xyz)
    source_averages = None
    if height_source is not None:
        from .terrain_source import sample_canvas

        source_averages = sample_canvas(height_source, geom, quadrature=height_quadrature)
    height_base = (
        source_averages.height_m
        if source_averages is not None
        else antialiased_height(geom, cols.elevation_m, cols.lat, cols.lon, xyz)
    )
    cond = {
        "heightmap": height_base,
        "temperature": tc.sample_mesh_field(geom, t_m.mean(1), xyz),
        "temperature_std": tc.sample_mesh_field(geom, t_m.std(1), xyz),
        "precipitation": tc.sample_mesh_field(geom, p_m.sum(1), xyz),
        "precipitation_cv": tc.sample_mesh_field(
            geom, np.where(p_mean > 1e-9, p_m.std(1) / np.maximum(p_mean, 1e-9) * 100, 0.0), xyz
        ),
    }
    if precipitation_field is not None and precipitation_coverage is not None:
        monthly = precipitation_coverage.cells.means(precipitation_field.component_monthly_mm).sum(
            axis=0
        )
        mean = monthly.mean(axis=0)
        cond["precipitation"] = monthly.sum(axis=0)
        cond["precipitation_cv"] = np.divide(
            monthly.std(axis=0) * 100, mean, out=np.zeros_like(mean), where=mean > 1e-9
        )
    # sea-level temperature, lapse rate from precipitation as in the region chain's refine
    lapse = np.clip(-6.5 + 0.0015 * cond["precipitation"], -9.8, -4.0) / 1000.0
    cond["temperature"] = cond["temperature"] - lapse * np.maximum(0.0, cell_mean_height)
    structure_stats: dict[str, Any] | None = None
    if structure:
        from .td_canvas_structure import structure_anomaly

        if cols.relief_std_m is None:
            raise ValueError("structure needs the mesh's relief_std_m")
        anom, st = structure_anomaly(geom, plan.canvas_id, xyz, cols.elevation_m, cols.relief_std_m)
        base = cond["heightmap"]
        # the structure field never moves the base's coast
        cond["heightmap"] = np.where(
            base > 0, np.maximum(base + anom, 1.0), np.minimum(base + anom, -1.0)
        )
        structure_stats = {k: round(v, 4) for k, v in st.items()}
    cond_sha = {}
    for name, arr in cond.items():
        f = out / "conditioning" / f"{name}.npy"
        np.save(f, arr.astype(np.float32))
        cond_sha[name] = sha256_file(f)
    ocean_cell = cond["heightmap"] <= 0.0

    climate_meta, legends = _write_canvas_climate(
        out, geom, cols, ocean_cell, precipitation_field, precipitation_coverage
    )

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
        "structure": structure_stats,
        "height_sampling": HEIGHT_SAMPLING,
        "source": source,
    }
    if precipitation_field is not None and precipitation_coverage is not None:
        canvas["precipitation_source"] = _save_precipitation_coverage(
            out, precipitation_field, precipitation_coverage
        )
    if height_source is not None and source_averages is not None:
        from .terrain_source import SOURCE_SAMPLING

        folder = out / "geometry_fields"
        folder.mkdir(exist_ok=True)
        fraction_path = folder / "land_fraction.npy"
        np.save(fraction_path, source_averages.land_fraction.astype(np.float32))
        canvas["height_sampling"] = SOURCE_SAMPLING
        canvas["height_source"] = {
            **height_source.metadata,
            "quadrature": height_quadrature,
            "land_fraction": {
                "path": "geometry_fields/land_fraction.npy",
                "sha256": sha256_file(fraction_path),
                "meaning": "source land coverage before the structure increment",
            },
        }
    (out / "canvas.json").write_text(
        json.dumps(canvas, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    return out


def _check_precipitation_radius(geom: tc.CanvasGeometry, field: NativePrecipitationField) -> None:
    if not np.isclose(geom.radius_km, field.partition.radius_km, rtol=1e-10, atol=0):
        raise ValueError("native precipitation and canvas must use the same planetary radius")


def _save_precipitation_coverage(
    out: Path,
    field: NativePrecipitationField,
    coverage: CanvasPrecipitationCoverage,
) -> dict[str, Any]:
    """Archive the target footprint so its component/month water ledger is reviewable."""
    from scipy.sparse import save_npz

    folder = out / "precipitation"
    folder.mkdir(exist_ok=True)
    matrix_path = folder / "overlap_km2.npz"
    area_path = folder / "area_km2.npy"
    save_npz(matrix_path, coverage.cells.overlap_km2)
    np.save(area_path, coverage.cells.area_km2)
    volume = coverage.cells.integrals(field.component_monthly_mm).sum(axis=(-2, -1))
    return {
        **field.metadata,
        "sampling": "spherical area mean over projected coarse-cell footprint",
        "coverage": {
            "overlap_asset": "precipitation/overlap_km2.npz",
            "overlap_sha256": sha256_file(matrix_path),
            "area_asset": "precipitation/area_km2.npy",
            "area_sha256": sha256_file(area_path),
            "row0": "north",
            "geometry": coverage.geometry.to_dict(),
            "native_geometry": list(coverage.native_geometry),
            "component_month_volume_mm_km2": volume.tolist(),
            "max_area_relative_error": coverage.max_area_relative_error,
            "max_overlap_change_relative": coverage.max_overlap_change_relative,
            "max_edge_subdivisions": coverage.max_edge_subdivisions,
            "footprint": "complete coarse cells of this canvas; ownership overlaps are separate",
        },
    }


def _write_canvas_climate(
    out: Path,
    geom: tc.CanvasGeometry,
    cols: MeshColumns,
    ocean_cell: np.ndarray,
    precipitation_field: NativePrecipitationField | None,
    precipitation_coverage: CanvasPrecipitationCoverage | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    t_m, p_m, xyz = cols.t_monthly_c, cols.p_monthly_mm, cols.xyz
    lat, lon = cols.lat, cols.lon

    def land_only(v: np.ndarray) -> np.ndarray:
        return np.where(cols.is_ocean.reshape(-1, *([1] * (np.ndim(v) - 1))), np.nan, v)

    climate: dict[str, np.ndarray] = {
        "temperature.C": clough_tocher(geom, t_m.mean(1), lat, lon),
        "temperature_monthly.C": np.stack(
            [clough_tocher(geom, t_m[:, k], lat, lon) for k in range(12)]
        ),
        "ice.m": clough_tocher(geom, cols.ice_m, lat, lon),
        "npp.gc_m2_yr": clough_tocher(geom, land_only(cols.npp), lat, lon),
    }
    if precipitation_field is None:
        pet_annual, runoff_annual, runoff_monthly = _runoff_cells(cols)
        climate.update(
            {
                "precipitation.mm": clough_tocher(geom, p_m.sum(1), lat, lon),
                "runoff.mm": clough_tocher(geom, land_only(runoff_annual), lat, lon),
                "pet_hamon.mm": clough_tocher(geom, land_only(pet_annual), lat, lon),
                "precipitation_monthly.mm": np.stack(
                    [clough_tocher(geom, p_m[:, k], lat, lon) for k in range(12)]
                ),
                "runoff_monthly.mm": tc.sample_mesh_field(geom, land_only(runoff_monthly), xyz),
            }
        )
    else:
        _check_precipitation_radius(geom, precipitation_field)
        if precipitation_coverage is None:
            raise ValueError("native canvas precipitation requires finite-area coverage")
        monthly = precipitation_coverage.cells.means(precipitation_field.component_monthly_mm).sum(
            axis=0
        )
        climate["precipitation_monthly.mm"] = monthly
        climate["precipitation.mm"] = monthly.sum(axis=0)
        # Derive water channels from precisely the months downstream readers get.
        # Calculate in float64 after the explicit float32 export quantization.
        t = np.moveaxis(
            climate["temperature_monthly.C"].astype(np.float32).astype(np.float64), 0, -1
        ).reshape(-1, 12)
        p = np.moveaxis(monthly.astype(np.float32).astype(np.float64), 0, -1).reshape(-1, 12)
        pet, runoff, runoff_m = _runoff_arrays(t, p)
        climate["pet_hamon.mm"] = pet.reshape(geom.ncell, geom.ncell)
        climate["runoff.mm"] = runoff.reshape(geom.ncell, geom.ncell)
        climate["runoff_monthly.mm"] = np.moveaxis(
            runoff_m.reshape(geom.ncell, geom.ncell, 12), -1, 0
        )
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
        if precipitation_field is not None:
            if name.startswith("precipitation"):
                sampling = "spherical area mean over projected coarse-cell footprint"
            elif name in ("pet_hamon.mm", "runoff.mm", "runoff_monthly.mm"):
                sampling = "derived from the same monthly temperature and area-mean precipitation"
        climate_meta[name] = {
            "units": UNITS[name],
            "shape": list(arr.shape),
            "missing": missing,
            "sampling": sampling,
        }
        if precipitation_field is not None and name in (
            "pet_hamon.mm",
            "runoff.mm",
            "runoff_monthly.mm",
        ):
            climate_meta[name]["input_encoding"] = (
                "exported float32 monthly T/P, calculations in float64"
            )

    return climate_meta, legends


def refresh_canvas_climate(
    canvas_dir: Path,
    cols: MeshColumns,
    source: dict[str, Any],
    *,
    precipitation_field: NativePrecipitationField,
    precipitation_coverage: CanvasPrecipitationCoverage | None = None,
    refresh_conditioning: bool = False,
) -> None:
    """Refresh staged climate, optionally replacing TD's climate conditioning.

    The caller stages the batch separately before adopting it. Precipitation
    uses finite spherical footprints; downstream hydrology must be rerun.
    """
    meta_path = canvas_dir / "canvas.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if refresh_conditioning and any((canvas_dir / "chunks").glob("*.npy")):
        raise ValueError("new TD climate conditioning needs a separate ungenerated canvas batch")
    g = meta["geometry"]
    geom = tc.CanvasGeometry(g["center_lat"], g["center_lon"], g["radius_km"], g["ncell"])
    _check_precipitation_radius(geom, precipitation_field)
    if precipitation_coverage is None:
        from .canvas_precipitation import canvas_precipitation_coverage

        precipitation_coverage = canvas_precipitation_coverage(precipitation_field.partition, geom)
    native_geometry = (
        *precipitation_field.partition.shape,
        precipitation_field.partition.radius_km,
        precipitation_field.partition.spacing_km,
    )
    if (
        precipitation_coverage.geometry != geom
        or precipitation_coverage.native_geometry != native_geometry
        or precipitation_coverage.cells.shape != (geom.ncell, geom.ncell)
    ):
        raise ValueError("precipitation footprint differs from canvas or native geometry")
    height = np.load(canvas_dir / "conditioning/heightmap.npy", allow_pickle=False)
    if height.shape != (geom.ncell, geom.ncell):
        raise ValueError("accepted height conditioning shape differs from canvas geometry")
    climate_meta, legends = _write_canvas_climate(
        canvas_dir, geom, cols, height <= 0, precipitation_field, precipitation_coverage
    )
    if refresh_conditioning:
        monthly = precipitation_coverage.cells.means(precipitation_field.component_monthly_mm).sum(
            axis=0
        )
        mean = monthly.mean(axis=0)
        annual = monthly.sum(axis=0)
        cell_height = tc.sample_mesh_field(geom, cols.elevation_m, cols.xyz)
        lapse = np.clip(-6.5 + 0.0015 * annual, -9.8, -4.0) / 1000.0
        conditions = {
            "temperature": tc.sample_mesh_field(geom, cols.t_monthly_c.mean(1), cols.xyz)
            - lapse * np.maximum(0.0, cell_height),
            "temperature_std": tc.sample_mesh_field(geom, cols.t_monthly_c.std(1), cols.xyz),
            "precipitation": annual,
            "precipitation_cv": np.divide(
                monthly.std(axis=0) * 100, mean, out=np.zeros_like(mean), where=mean > 1e-9
            ),
        }
        for name, values in conditions.items():
            path = canvas_dir / "conditioning" / f"{name}.npy"
            np.save(path, values.astype(np.float32))
            meta["conditioning_sha256"][name] = sha256_file(path)
    meta.update(
        climate=climate_meta,
        legends=legends,
        climate_source=source,
        precipitation_source=_save_precipitation_coverage(
            canvas_dir, precipitation_field, precipitation_coverage
        ),
        climate_refresh={
            "terrain_conditioning": (
                "new climate; accepted height source"
                if refresh_conditioning
                else "retained from accepted terrain generation"
            ),
            "downstream_hydrology": "requires recomputation from refreshed climate",
            "water_input_encoding": "exported float32 monthly T/P, calculations in float64",
        },
    )
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")


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
