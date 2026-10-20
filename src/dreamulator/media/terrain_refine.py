"""terrain_refine — terrain-diffusion refinement as an export command.

The main terrain source of the terrain chain (docs/usage/terrain-chain.md
step ②): the engine's coarse conditioning fields drive the terrain-
diffusion model to regenerate the landscape at 90 m; the programmatic
hydrology layer (Priority-Flood + lakes + vector channels) then extracts
the drainage semantics.  The heavy inference runs in the terrain-diffusion
venv as a subprocess — its CUDA torch stack stays out of this project's
dependencies.

    <pack> + world data  →  <pack>/refined-out/  (shared file vocabulary)
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.media.lake_masks import lake_footprint

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh
    from dreamulator.map.region_export import RegionWindow

#: Coarse conditioning pixel size (km) of the 90 m model — fixed upstream.
TD_COARSE_KM = 23.0
#: Inference defaults carried over from the 2026-10 trial (see the manual).
TD_SNR = "0.2,0.2,1.0,0.2,1.0"
TD_SEED = 42
#: Target refined grid resolution: pack grid × this factor.
REFINE_FACTOR = 2

_TD_DRIVER = (
    r"""
import sys
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

mode, *args = sys.argv[1:]
if mode == "condition":
    src, out, span_km, n = Path(args[0]), Path(args[1]), float(args[2]), int(args[3])
    out.mkdir(parents=True, exist_ok=True)
    # Channel filenames/units follow TD's CHANNEL_FILES table (heightmap m,
    # temperature °C at SEA LEVEL, t_std °C, precipitation mm/yr, p_cv %);
    # internal ×100 scaling is TD's own job, not ours.
    chans = {
        "heightmap": "elevation_m.npy",
        "temperature": "temperature_mean_c.npy",
        "temperature_std": "temperature_std_c.npy",
        "precipitation": "precipitation_total_mm.npy",
        "precipitation_cv": "precipitation_cv_pct.npy",
    }
    loaded = {name: np.load(src / fname).astype(np.float64) for name, fname in chans.items()}
    elev = loaded["heightmap"]
    precip = loaded["precipitation"]
    if "temperature" in loaded:
        # Upstream convention: the model's temperature is SEA-LEVEL
        # temperature — engine t_mean is surface, add the orographic
        # lapse back (wet adiabat flattening with precipitation).
        lapse = np.clip(-6.5 + 0.0015 * precip, -9.8, -4.0) / 1000.0
        loaded["temperature"] = loaded["temperature"] - lapse * np.maximum(0.0, elev)
    # Coarse grid sizing + bilinear resample follow the validated research
    # pipeline (make_conditioning_tiffs.py): rows = round(extent/coarse-km),
    # scipy zoom order=1.  The conditioning must be bit-identical for the
    # same seed to reproduce the same terrain — nearest-stride or a ±1 cell
    # count yields a different field and a wholly different generation.
    from scipy.ndimage import zoom

    rows = max(2, round(span_km / {km}))
    for name, arr in loaded.items():
        coarse = zoom(arr, (rows / arr.shape[0], rows / arr.shape[1]), order=1)
        tifffile.imwrite(out / f"{name}.tif", coarse.astype(np.float32))
elif mode == "infer":
    import subprocess as sp
    repo, tiff_dir, out_tif = Path(args[0]), Path(args[1]), Path(args[2])
    py = Path(sys.executable)
    sp.run([str(py), "-m", "terrain_diffusion.inference.tiff_export",
            "xandergos/terrain-diffusion-90m", str(tiff_dir), str(out_tif),
            "--snr", "{snr}", "--seed", "{seed}"], check=True, cwd=str(repo))
elif mode == "tonpy":
    tif, npy, size = Path(args[0]), Path(args[1]), int(args[2])
    a = tifffile.imread(str(tif)).astype(np.float64)
    im = Image.fromarray((a + 32768).astype(np.int32))
    im = im.resize((size, size), Image.LANCZOS)
    np.save(npy, (np.asarray(im).astype(np.float64) - 32768).astype(np.float32))
""".replace("{km}", str(TD_COARSE_KM))
    .replace("{snr}", TD_SNR)
    .replace("{seed}", str(TD_SEED))
)


def _td_python(td_repo: Path) -> Path:
    # venv layouts differ by platform: Scripts/python.exe on Windows,
    # bin/python on Linux (the server refines there too; before this it
    # symlinked bin/python → Scripts/python.exe to be found, handoff 2026-10-16).
    for rel in ((".venv", "Scripts", "python.exe"), (".venv", "bin", "python")):
        py = td_repo.joinpath(*rel)
        if py.exists():
            return py
    raise FileNotFoundError(
        f"terrain-diffusion venv not found under {td_repo / '.venv'} — see the manual's "
        "setup section (uv venv + CUDA wheels, external to this project)"
    )


def _pack_map_dir(meta: dict[str, Any]) -> Path:
    """Branch-aware maps directory of the pack's source world/planet.

    A pack exported with ``--branch`` must refine against that branch's mesh
    and monthly climate (e.g. ``gcm-t42-712``), not the root world's engine
    climate; MapManager applies the branch → root → legacy resolution order.
    """
    from dreamulator.map.manager import MapManager

    src = meta["source"]
    map_dir = MapManager(Path("data") / "worlds" / src["world"], src.get("branch"))._maps_dir(
        src["planet"]
    )
    if map_dir is None:
        raise FileNotFoundError(
            f"no maps for {src['world']}/{src['planet']} (branch {src.get('branch')})"
        )
    return map_dir


def _mesh_and_window(pack_dir: Path) -> tuple[CVTMesh, RegionWindow]:
    """The pack's source mesh and its azimuthal-equidistant window.

    Shared by the conditioning export and the monthly-regime loader.  Both
    sample the window's AEQ plane: conditioning on the coarse TD grid, the
    regime on the pack's own 2048-class grid.
    """
    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model
    from dreamulator.map.region_export import read_radius_km, region_window

    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    map_dir = _pack_map_dir(meta)
    mesh_file = find_mesh_file(map_dir)
    if mesh_file is None:
        raise FileNotFoundError(f"no cvt mesh under {map_dir}")
    mesh = load_cvt_mesh_model(mesh_file)
    radius_km = read_radius_km(map_dir)
    window = region_window(meta["center_lat"], meta["center_lon"], meta["span_km"], radius_km)
    return mesh, window


def _pack_monthly_runoff(
    pack_dir: Path,
    *,
    recharge_fraction: float | None = None,
    residence_time_days: float | None = None,
) -> np.ndarray | None:
    """Monthly runoff on the PACK grid (pack_res, pack_res, 12), mm/month.

    The monthly shape comes from the Manabe bucket at periodic steady state
    followed by one linear groundwater store (WBM-inspired quickflow plus
    baseflow); the annual total is the pack's Turc–Pike channel itself, so
    the twelve fields sum EXACTLY to the annual extraction weight.  The
    un-routed bucket alone zeroes yield in strongly seasonal climates (its
    documented blind spot) and would grade Mediterranean-slope rivers
    non-perennial by artefact.  Where the bucket yields nothing the shape falls
    back to the monthly moisture surplus (P − PET)+; where that is empty
    too (hyperarid interiors) the total spreads uniformly over twelve
    months — no seasonal information reads as perennial, the same
    degradation as missing monthly data.  Sampling is nearest-CVT: the
    regime is classification input, not a rendered surface, and the C1
    smoothness the render channels pay for buys nothing here.  Returns None
    when the world carries no monthly series or the pack has no annual
    runoff channel (regime off, all rivers solid — the documented fallback).
    The two optional parameters are sensitivity-experiment overrides;
    production uses the documented WBM-default constants.
    """
    from dreamulator.engine.climate_physics import (
        BASEFLOW_RECHARGE_FRACTION,
        BASEFLOW_RESIDENCE_TIME_DAYS,
        SOIL_WATER_CAPACITY_MM,
        potential_evapotranspiration_hamon_monthly,
        route_runoff_with_baseflow,
        soil_bucket_monthly,
    )
    from dreamulator.map.export import build_export_tree, find_mesh_file, load_climate_monthly
    from dreamulator.map.region_export import _nearest_indices_on_grid
    from dreamulator.result_contract import REFERENCE_MONTH_DAYS

    annual_path = pack_dir / "input" / "runoff.mm.npy"
    if not annual_path.exists():
        print(f"[refine] no {annual_path}; river regime off (all solid)")
        return None
    annual = np.nan_to_num(np.load(annual_path).astype(np.float64), nan=0.0)

    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    map_dir = _pack_map_dir(meta)
    if find_mesh_file(map_dir) is None:
        print(f"[refine] no cvt mesh under {map_dir}; river regime off (all solid)")
        return None
    try:
        t_m, p_m = load_climate_monthly(map_dir)
    except FileNotFoundError:
        print(f"[refine] no climate_monthly under {map_dir}; river regime off (all solid)")
        return None
    pet_m = potential_evapotranspiration_hamon_monthly(t_m, REFERENCE_MONTH_DAYS)
    _e, r_m, _cycles, _resid = soil_bucket_monthly(p_m, pet_m, SOIL_WATER_CAPACITY_MM)
    r_m = route_runoff_with_baseflow(
        r_m,
        days_per_month=REFERENCE_MONTH_DAYS,
        recharge_fraction=(
            BASEFLOW_RECHARGE_FRACTION if recharge_fraction is None else recharge_fraction
        ),
        residence_time_days=(
            BASEFLOW_RESIDENCE_TIME_DAYS if residence_time_days is None else residence_time_days
        ),
    )

    # Normalised monthly shape: every cell's twelve shares sum to one, so
    # multiplying by the pack's annual channel preserves that channel
    # exactly (including its C1 interpolation, which nearest-CVT sampling
    # of a mesh-annual field would not reproduce).
    shape = np.zeros_like(r_m)
    bucket_total = r_m.sum(axis=1)
    has_bucket = bucket_total > 1e-6
    shape[has_bucket] = r_m[has_bucket] / bucket_total[has_bucket, None]
    surplus = np.maximum(p_m - pet_m, 0.0)
    surplus_total = surplus.sum(axis=1)
    has_surplus = ~has_bucket & (surplus_total > 1e-6)
    shape[has_surplus] = surplus[has_surplus] / surplus_total[has_surplus, None]
    shape[~has_bucket & ~has_surplus] = 1.0 / 12.0

    mesh, window = _mesh_and_window(pack_dir)
    tree = build_export_tree(mesh)
    lon_grid, lat_grid = window.out_latlon(annual.shape[0])
    indices = _nearest_indices_on_grid(tree, lon_grid, lat_grid)
    monthly = shape[indices] * annual[..., None]
    return np.asarray(monthly, dtype=np.float32)


def _export_conditioning(pack_dir: Path, tmp: Path, *, coast_warp: bool = False) -> int:
    """Stage 1 (main env): sample the mesh + monthly climate on the AEQ window."""
    from dreamulator.map.export import build_export_tree, load_climate_monthly
    from dreamulator.map.region_export import _nearest_indices_on_grid

    mesh, window = _mesh_and_window(pack_dir)
    # Conditioning pitch = the legacy equirect export grid's meridional pitch
    # (2048 rows), the resolution the TD chain was tuned on.  AEQ sampling
    # holds that ground pitch at every latitude; the TD driver resamples the
    # fields to round(span / 23 km) coarse cells either way.
    n = max(2, round(window.span_km / (math.pi * window.radius_km / 2047.0)))
    tree = build_export_tree(mesh)
    indices = _nearest_indices_on_grid(tree, *window.out_latlon(n))
    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    map_dir = _pack_map_dir(meta)

    t_m, p_m = load_climate_monthly(map_dir)
    t_mean, p_mean = t_m.mean(axis=1), p_m.mean(axis=1)
    fields = {
        "elevation_m": np.fromiter(
            (c.elevation for c in mesh.cells), dtype=np.float64, count=t_m.shape[0]
        ),
        "temperature_mean_c": t_mean,
        "temperature_std_c": t_m.std(axis=1),
        "precipitation_total_mm": p_m.sum(axis=1),
        "precipitation_cv_pct": np.where(
            p_mean > 1e-9, p_m.std(axis=1) / np.maximum(p_mean, 1e-9) * 100.0, 0.0
        ),
    }
    tmp.mkdir(parents=True, exist_ok=True)
    # Optional coast-domain warp before coarse conditioning (off by default):
    # the engine's sea-land edges are straight Voronoi boundaries and TD
    # anchors its coastline to the conditioning elevation — warped, straight
    # runs bend into organic shorelines (measured 9.1→14.6 roughness), at
    # the cost of ~35 km of coordinate drift on the conditioning.
    out_fields = {name: arr[indices].astype(np.float32) for name, arr in fields.items()}
    if coast_warp:
        from dreamulator.media.satellite_color import apply_boundary_warp

        cell_px = float(meta["cell_pitch_km"]) / (float(meta["extent_km"]["x"]) / n)
        out_fields = {
            name: apply_boundary_warp(arr, cell_px, order=0 if name == "elevation_m" else 1)
            for name, arr in out_fields.items()
        }
    for name, arr in out_fields.items():
        np.save(tmp / f"{name}.npy", arr.astype(np.float32))
    return n


def _run_td(py: Path, td_repo: Path, tmp: Path, span_km: float, n: int, out_tif: Path) -> None:
    """Stages 2 (td venv): conditioning tiffs → diffusion inference → tif→npy.

    ``tmp`` is the refinement scratch root (holds the driver, the exported
    ``fields/`` and the ``cond/`` tiffs); the conditioning source dir is
    ``tmp/fields``.
    """
    driver = tmp / "_td_driver.py"
    driver.write_text(_TD_DRIVER, encoding="utf-8")
    tiff_dir = tmp / "cond"
    subprocess.run(
        [
            str(py),
            str(driver),
            "condition",
            str(tmp / "fields"),
            str(tiff_dir),
            str(span_km),
            str(n),
        ],
        check=True,
    )
    subprocess.run(
        [str(py), str(driver), "infer", str(td_repo), str(tiff_dir), str(out_tif)],
        check=True,
    )


def refine_region_pack(
    pack_dir: Path,
    td_repo: Path | None,
    *,
    river_threshold: int | None = None,
    coast_warp: bool = False,
    reuse_height: bool = False,
) -> dict[str, object]:
    """CLI entry: refine a region pack's terrain, write ``refined-out/``.

    ``reuse_height=True`` skips the TD inference and re-extracts the
    hydrology from the previous ``refined-out/height.meters.npy`` — the
    iteration loop for drainage/lake semantics changes (a full re-run is
    deterministic for the same seed but pays the whole inference again).
    """
    from PIL import Image

    from dreamulator.map.export import export_elevation_png
    from dreamulator.map.prog_erosion import (
        LAKE_EVAPORATION_FACTOR,
        LAKE_MIN_WIDTH_KM,
        REGIME_ACTIVE_DISCHARGE_M3S,
        RIVER_REGIME_NON_PERENNIAL,
        RIVER_REGIME_PERENNIAL,
        RIVER_THRESHOLD_CELLS,
        heal_inland_water,
        hydrology_weight,
        keep_large_lakes,
        lake_mask,
        lake_mmu_cells,
        month_active_counts,
        priority_flood,
        regime_active_cells,
        river_mask,
        river_segments,
        terminal_equilibrium_routing,
    )

    pack_dir = pack_dir.resolve()  # td subprocess runs with cwd=repo —
    # every path handed to it must be absolute or it resolves under the repo
    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    pack_res = int(meta["grid"]["w"])
    res = pack_res * REFINE_FACTOR
    tmp = pack_dir / "refine-tmp"

    # Reuse cache: prefer the PRE-equilibrium field (post-heal, before the
    # terminal-lake rewrite) so the equilibrium verdict re-derives from the
    # true depression geometry on every reuse — the product height flattens
    # dried playa floors, which would erase the evidence.
    cached_pre = pack_dir / "refined-out" / "height.pre-equilibrium.npy"
    cached = cached_pre if cached_pre.exists() else pack_dir / "refined-out" / "height.meters.npy"
    if reuse_height:
        if not cached.exists():
            raise FileNotFoundError(
                f"--reuse-height needs a previous full refine — {cached} is missing"
            )
        h = np.load(cached).astype(np.float64)
        if h.shape[0] != res:
            raise ValueError(f"cached height is {h.shape[0]}², expected {res}² — run a full refine")
        print(f"[refine] reusing {cached} (TD inference skipped)")
    else:
        if td_repo is None:
            raise ValueError("td_repo is required for a full refine (or pass reuse_height)")
        n = _export_conditioning(pack_dir, tmp / "fields", coast_warp=coast_warp)
        extent_km = float(meta["extent_km"]["x"])
        py = _td_python(td_repo)
        raw_tif = tmp / "refined.tif"
        _run_td(py, td_repo, tmp, extent_km, n, raw_tif)
        subprocess.run(
            [
                str(py),
                str(tmp / "_td_driver.py"),
                "tonpy",
                str(raw_tif),
                str(tmp / "refined.npy"),
                str(res),
            ],
            check=True,
        )
        h = np.load(tmp / "refined.npy").astype(np.float64)

    land = h > float(meta["sea_level_m"])
    km_pp = float(meta["extent_km"]["x"]) / res
    # Sub-MMU inland water bodies (h≤0, not connected to the ocean) are TD
    # quantisation noise — heal to land so rivers continue through them to
    # the real sea or sink; larger ones stay water as endorheic lakes.
    h, land, inland_big = heal_inland_water(
        h,
        land,
        lake_mmu_cells(km_pp),
        float(meta["sea_level_m"]),
        km_per_px=km_pp,
        min_width_km=LAKE_MIN_WIDTH_KM,
    )

    # Extraction weight: the annual runoff channel (Manabe-bucket water
    # balance) when the pack carries it, precipitation for legacy packs —
    # hydrology_weight prints which.  The P/T annual channels ride along
    # (kron-upsampled to the refined grid) for the terminal-lake balance.
    weight, run_norm_mm, weight_src = hydrology_weight(pack_dir / "input", res, land)
    precip_p = np.nan_to_num(
        np.load(pack_dir / "input" / "precipitation.mm.npy").astype(np.float64), nan=0.0
    )
    factor = res // precip_p.shape[0]
    precip_r = np.kron(precip_p, np.ones((factor, factor)))[:res, :res]
    t_path = pack_dir / "input" / "temperature.C.npy"
    temp_r: np.ndarray | None = None
    if t_path.exists():
        temp_p = np.nan_to_num(np.load(t_path).astype(np.float64), nan=0.0)
        temp_r = np.kron(temp_p, np.ones((factor, factor)))[:res, :res]
    else:
        print(f"[refine] no temperature.C.npy in {pack_dir / 'input'}; terminal-lake balance off")

    filled, order, rec = priority_flood(h, land)
    lakes = lake_footprint(lake_mask(filled, h), filled, h)
    mmu = lake_mmu_cells(km_pp)
    lakes_draw0 = keep_large_lakes(lakes, mmu, LAKE_MIN_WIDTH_KM, km_pp) | inland_big
    out = pack_dir / "refined-out"
    out.mkdir(exist_ok=True)
    # Reuse cache: the field BEFORE the terminal-lake rewrite (see the
    # loader) — written whenever a rewrite may happen.
    np.save(out / "height.pre-equilibrium.npy", h.astype(np.float32))
    # Terminal-lake equilibrium with through-flow depletion (the shared
    # helper): pass-through lakes deduct their net evaporation from the
    # through-flow; routing stays on the pre-rewrite tree.
    h, land, lakes_draw, chain_stop, fringe_desc, rec, acc, term_water, lake_stats, lake_records = (
        terminal_equilibrium_routing(
            h,
            land,
            lakes_draw0,
            order,
            rec,
            weight,
            precip_mm=precip_r if temp_r is not None else np.zeros_like(land),
            temp_c=temp_r if temp_r is not None else np.full_like(h, 0.0),
            runoff_land_mean_mm=run_norm_mm
            if (temp_r is not None and weight_src == "runoff")
            else 0.0,
            mmu_cells=mmu,
            km_per_px=km_pp,
            sea_level_m=float(meta["sea_level_m"]),
        )
    )
    thr = (
        river_threshold if river_threshold is not None else RIVER_THRESHOLD_CELLS * factor * factor
    )
    rivers = river_mask(acc, land, thr)
    # Monthly flow regime (12 accumulations on the final routing, R₀ shared
    # with the annual family — see month_active_counts).  None on legacy
    # worlds: every river renders solid, the documented degradation.
    monthly_pack = _pack_monthly_runoff(pack_dir)
    month_act = (
        None
        if monthly_pack is None
        else month_active_counts(
            order, rec, monthly_pack, land, regime_active_cells(km_pp), factor=factor
        )
    )

    lo, hi = float(h.min()), float(h.max())
    span = hi - lo or 1.0
    np.save(out / "height.meters.npy", h.astype(np.float32))
    export_elevation_png(h, out / "height.gaea.png", min_m=lo, max_m=hi)
    segs, flows, regimes = river_segments(
        rivers, rec, acc, km_pp, lake=chain_stop, lake_descend=fringe_desc, month_active=month_act
    )
    np.save(out / "rivers.line.npy", segs)
    np.save(out / "rivers.flow.npy", flows)
    if month_act is not None:
        np.save(out / "rivers.regime.npy", regimes)
    rivers &= ~lakes_draw
    Image.fromarray((rivers * 255).astype(np.uint8)).save(out / "rivers.png")
    Image.fromarray((lakes_draw * 255).astype(np.uint8)).save(out / "lake.png")
    not_sea = term_water  # equilibrium water (kept surfaces + playa sinks)
    Image.fromarray(((~land & ~not_sea & ~lakes_draw) * 255).astype(np.uint8)).save(
        out / "sea-water.png"
    )
    sea_depth = np.clip(float(meta["sea_level_m"]) - h, 0, None) / span
    sea_depth[not_sea] = 0.0
    Image.fromarray(np.clip(sea_depth * 65535, 0, 65535).astype(np.uint16)).save(
        out / "sea-depth.png"
    )
    Image.fromarray(np.clip(acc / max(acc.max(), 1.0) * 65535.0).astype(np.uint16)).save(
        out / "flow-accum.png"
    )
    sheet_meta: dict[str, object] = {
        "height_gaea_png_range_m": [lo, hi],
        "sea_level_m": meta["sea_level_m"],
        "source": "terrain-diffusion 90m refined",
        "td_snr": TD_SNR,
        "td_seed": TD_SEED,
        "river_threshold": thr,
        "lake_mmu_cells": mmu,
        "hydrology_weight": weight_src,
        "runoff_normalizer_mm": round(run_norm_mm, 3),
        "terminal_lakes": lake_stats["terminal"],
        "dry_playas": lake_stats["dry_playas"],
        "shrunk_lakes": lake_stats["shrunk"],
        "lakes": lake_records,
        "lake_balance": {
            "pet": "hamon-annual",
            "evaporation_factor": LAKE_EVAPORATION_FACTOR,
        },
    }
    if month_act is not None:
        sheet_meta["regime"] = {
            "encoding": "0 perennial / 1 non-perennial",
            "shape": "manabe-bucket + linear-baseflow monthly, anchored to turc-pike annual",
            "active_rule": "12 active months = perennial; otherwise non-perennial, by reach",
            "active_discharge_m3s": REGIME_ACTIVE_DISCHARGE_M3S,
            "active_cells": regime_active_cells(km_pp),
        }
    (out / "meta.json").write_text(
        json.dumps(sheet_meta, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    # The intermediates are reproducible from the pack — remove the scratch.
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
    result: dict[str, object] = {
        "res": res,
        "lakes_pct": round(float(lakes_draw.sum() / max(land.sum(), 1) * 100), 1),
        "river_segments": int(len(segs)),
        "height_range_m": [round(lo, 1), round(hi, 1)],
    }
    if month_act is not None:
        result["regime_segments"] = [
            int((regimes == r).sum()) for r in (RIVER_REGIME_PERENNIAL, RIVER_REGIME_NON_PERENNIAL)
        ]
    return result
