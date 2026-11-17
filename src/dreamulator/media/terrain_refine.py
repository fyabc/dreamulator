"""Build a region from redrawn terrain, source detail blend or source hydrology.

TD inference uses its own environment. All modes write one adopted height
and the shared drainage/render vocabulary; intermediate fields are retained
with hashes so terrain edits and cache reuse can be inspected.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.media.lake_masks import lake_footprint
from dreamulator.media.terrain_blend import (
    RefinementMode,
    blend_height,
    cap_depression_depth,
    detail_difference,
)

if TYPE_CHECKING:
    from pathlib import Path

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
        coarse = zoom(arr, (rows / arr.shape[0], rows / arr.shape[1]), order=1, mode="nearest")
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
    from dreamulator.world_manager import _data_dir

    src = meta["source"]
    map_dir = MapManager(_data_dir() / src["world"], src.get("branch"))._maps_dir(src["planet"])
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
    from dreamulator.map.export import build_export_tree, find_mesh_file, load_climate_monthly
    from dreamulator.map.region_export import _nearest_indices_on_grid
    from dreamulator.map.region_inputs import (
        local_runoff,
        monthly_runoff_shape,
        read_refinement_inputs,
    )

    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    overrides = {"recharge_fraction": recharge_fraction, "residence_time_days": residence_time_days}
    if "refinement_inputs" in meta:
        if recharge_fraction is not None or residence_time_days is not None:
            raise ValueError("runoff overrides need a newly exported input snapshot")
        return read_refinement_inputs(pack_dir / "input", meta["refinement_inputs"])[
            "runoff_monthly_mm"
        ]
    if meta.get("source", {}).get("world") == "external":
        return local_runoff(pack_dir / "input", **overrides)

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
    shape = monthly_runoff_shape(t_m, p_m, **overrides)

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
    from dreamulator.map.region_inputs import (
        CONDITIONING_UNITS,
        local_conditioning,
        read_refinement_inputs,
    )

    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    if "refinement_inputs" in meta:
        snapshot = read_refinement_inputs(pack_dir / "input", meta["refinement_inputs"])
        out_fields = {name: snapshot[name] for name in CONDITIONING_UNITS}
        n = out_fields["elevation_m"].shape[0]
    elif meta.get("source", {}).get("world") == "external":
        out_fields = local_conditioning(pack_dir / "input")
        n = out_fields["elevation_m"].shape[0]
    else:
        mesh, window = _mesh_and_window(pack_dir)
        n = max(2, round(window.span_km / (math.pi * window.radius_km / 2047.0)))
        indices = _nearest_indices_on_grid(build_export_tree(mesh), *window.out_latlon(n))
        t_m, p_m = load_climate_monthly(_pack_map_dir(meta))
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
        out_fields = {name: arr[indices].astype(np.float32) for name, arr in fields.items()}
    tmp.mkdir(parents=True, exist_ok=True)
    if coast_warp:
        from dreamulator.media.satellite_color import apply_boundary_warp

        cell_px = float(meta["cell_pitch_km"]) / (float(meta["extent_km"]["x"]) / n)
        out_fields = {
            name: apply_boundary_warp(arr, cell_px, order=0 if name == "elevation_m" else 1)
            for name, arr in out_fields.items()
        }
    for name, arr in out_fields.items():
        np.save(tmp / f"{name}.npy", arr.astype(np.float32))
    return int(n)


def _run_td(py: Path, td_repo: Path, tmp: Path, span_km: float, n: int, out_tif: Path) -> None:
    """Stages 2 (td venv): conditioning tiffs → diffusion inference → tif→npy.

    ``tmp`` is the refinement scratch root (holds the driver, the exported
    ``fields/`` and the ``cond/`` tiffs); the conditioning source dir is
    ``tmp/fields``.
    """
    driver = tmp / "_td_driver.py"
    driver.write_text(_TD_DRIVER, encoding="utf-8")
    tiff_dir = tmp / "cond"
    # The subprocess owns a different torch installation. Allocator settings
    # from the host's torch can be unsupported by that installation.
    env = os.environ.copy()
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)
    env.pop("PYTORCH_ALLOC_CONF", None)
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
        env=env,
    )
    subprocess.run(
        [str(py), str(driver), "infer", str(td_repo), str(tiff_dir), str(out_tif)],
        check=True,
        env=env,
    )


def _cache_contract(
    pack_dir: Path,
    meta: dict[str, Any],
    mode: RefinementMode,
    native_km: float | None,
    preserve_km: float | None,
    coast_warp: bool,
    depth_cap: bool,
) -> dict[str, Any]:
    from dreamulator.map.region_inputs import file_sha256

    # Hash actual portable files, including legacy monthly forcing. Paths are
    # relative so moving a pack does not invalidate the cache.
    files = sorted((pack_dir / "input").rglob("*.npy"))
    return {
        "version": "region-refinement-modes-v1",
        "input_meta_sha256": file_sha256(pack_dir / "input/meta.json"),
        "inputs": {str(p.relative_to(pack_dir)): file_sha256(p) for p in files},
        "mode": mode.value,
        "native_resolution_km": native_km,
        "preserve_wavelength_km": preserve_km,
        "coast_warp": coast_warp,
        "cap_depression_depth": depth_cap,
        "res": int(meta["grid"]["w"]) * REFINE_FACTOR,
        "driver_sha256": hashlib.sha256(_TD_DRIVER.encode("utf-8")).hexdigest(),
    }


def _td_revision(td_repo: Path) -> str:
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=td_repo,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise ValueError("--td must point to a terrain-diffusion git checkout") from exc
    changes = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "terrain_diffusion"], cwd=td_repo
    )
    return revision if not changes else revision + ":" + hashlib.sha256(changes).hexdigest()


def refine_region_pack(
    pack_dir: Path,
    td_repo: Path | None,
    *,
    river_threshold: int | None = None,
    coast_warp: bool = False,
    reuse_height: bool = False,
    debug: bool = False,
    mode: RefinementMode = RefinementMode.REDRAW,
    native_resolution_km: float | None = None,
    preserve_wavelength_km: float | None = None,
    depth_cap: bool = False,
) -> dict[str, object]:
    """CLI entry: refine a region pack's terrain, write ``refined-out/``.

    ``reuse_height=True`` validates the input/mode/scale contract and donor
    checksum, then rebuilds from the saved donor without TD inference.
    Blend and hydrology preserve the original bed; depth_cap is an explicit
    blend edit saved separately before hydrology.
    ``debug=True`` adds ``flow-accum.png``, the accumulation field nothing downstream reads
    (20-35 MB of high-entropy 16-bit noise a pack) but which is worth looking at when the
    drainage is being tuned.
    """
    from PIL import Image

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

    if td_repo is not None:
        td_repo = td_repo.resolve()
    pack_dir = pack_dir.resolve()  # td subprocess runs with cwd=repo —
    # every path handed to it must be absolute or it resolves under the repo
    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    pack_res = int(meta["grid"]["w"])
    res = pack_res * REFINE_FACTOR
    tmp = pack_dir / "refine-tmp"

    from scipy.ndimage import label

    from dreamulator.map.importer import _resample_by_class
    from dreamulator.map.region_inputs import file_sha256, read_refinement_inputs
    from dreamulator.map.river_routing import two_ring_receivers

    mode = RefinementMode(mode)
    sea_level = float(meta["sea_level_m"])
    km_pp = float(meta["extent_km"]["x"]) / res
    if meta["grid"]["h"] != pack_res:
        raise ValueError("region build requires a square input grid")
    if mode != RefinementMode.BLEND and (
        native_resolution_km is not None or preserve_wavelength_km is not None or depth_cap
    ):
        raise ValueError("native scale, preserve wavelength and depth cap require --mode blend")
    if mode != RefinementMode.REDRAW and coast_warp:
        raise ValueError("coast warp requires --mode redraw")
    if mode == RefinementMode.HYDROLOGY and reuse_height:
        raise ValueError("hydrology reads the original input; omit --reuse-height")
    # Reject broken forcing even when no diffusion inference is requested.
    if "refinement_inputs" in meta:
        read_refinement_inputs(pack_dir / "input", meta["refinement_inputs"])
    raw_source = np.load(pack_dir / "input/height.meters.npy")
    if raw_source.shape != (pack_res, pack_res) or not np.isfinite(raw_source).all():
        raise ValueError("input height must be finite and match the declared grid")
    source, _ = _resample_by_class(raw_source, raw_source > sea_level, res, res)
    source = source.astype(np.float32)
    native_km: float | None = None
    preserve_km: float | None = None
    if mode == RefinementMode.BLEND:
        native_km = native_resolution_km
        if native_km is None:
            native_km = float(meta["source"].get("px_km", meta["cell_pitch_km"]))
        if not math.isfinite(native_km) or native_km <= 0:
            raise ValueError("native resolution must be positive")
        preserve_km = (
            preserve_wavelength_km if preserve_wavelength_km is not None else 4 * native_km
        )
        if not math.isfinite(preserve_km) or preserve_km < 4 * km_pp:
            raise ValueError("preserve wavelength must be at least four output pixels")
    contract = _cache_contract(pack_dir, meta, mode, native_km, preserve_km, coast_warp, depth_cap)
    previous = pack_dir / "refined-out"
    td_revision: str | None = None
    donor: np.ndarray | None = None
    if mode != RefinementMode.HYDROLOGY:
        if reuse_height:
            old_meta_path = previous / "meta.json"
            if not old_meta_path.exists():
                raise FileNotFoundError("--reuse-height needs a previous region build")
            old_meta = json.loads(old_meta_path.read_text(encoding="utf-8"))
            if old_meta.get("cache_contract") != contract:
                raise ValueError("cached mode, input or scale changed; run without --reuse-height")
            cached = previous / "height.donor.npy"
            if not cached.exists() or file_sha256(cached) != old_meta.get("stage_sha256", {}).get(
                cached.name
            ):
                raise ValueError("cached donor is missing or damaged; run without --reuse-height")
            td_revision = old_meta.get("td_revision")
            if td_repo is not None and _td_revision(td_repo) != td_revision:
                raise ValueError("terrain-diffusion revision changed; run without --reuse-height")
            donor = np.load(cached).astype(np.float32)
            print(f"[refine] reusing {cached} (TD inference skipped)")
        else:
            if td_repo is None:
                raise ValueError("--td is required for redraw or blend (or pass --reuse-height)")
            td_revision = _td_revision(td_repo)
            n = _export_conditioning(pack_dir, tmp / "fields", coast_warp=coast_warp)
            py = _td_python(td_repo)
            raw_tif = tmp / "refined.tif"
            _run_td(py, td_repo, tmp, float(meta["extent_km"]["x"]), n, raw_tif)
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
            donor = np.load(tmp / "refined.npy").astype(np.float32)
        if donor.shape != (res, res) or not np.isfinite(donor).all():
            raise ValueError("donor height must be finite and match the refined grid")
    # Assemble a complete product separately; a rejected build leaves the
    # previous adopted height and cache intact.
    out = tmp / "product"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    np.save(out / "height.source.npy", source)
    if donor is not None:
        np.save(out / "height.donor.npy", donor)
    if mode == RefinementMode.BLEND:
        assert donor is not None and preserve_km is not None
        delta = detail_difference(source, donor, km_pp, preserve_km)
        np.save(out / "height.frequency-delta.npy", delta)
        blended = blend_height(source, delta, km_pp, preserve_km / 2, sea_level)
        np.save(out / "height.blended.npy", blended)
        h = cap_depression_depth(blended, source, sea_level) if depth_cap else blended
        if depth_cap:
            np.save(out / "height.depth-capped.npy", h)
    else:
        if mode == RefinementMode.HYDROLOGY:
            h = source
        else:
            assert donor is not None
            h = donor
    h = h.astype(np.float64)
    geographic_land = h > sea_level
    land = geographic_land.copy()
    if mode == RefinementMode.REDRAW:
        h, land, inland_big = heal_inland_water(
            h,
            land,
            lake_mmu_cells(km_pp),
            sea_level,
            km_per_px=km_pp,
            min_width_km=LAKE_MIN_WIDTH_KM,
        )
    else:
        # Preserve all original elevations. Inland non-land components are
        # water sinks, while boundary-connected components remain marine.
        labels, _ = label(~land)
        edge = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
        inland_big = (~land) & ~np.isin(labels, edge)

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
    # Lake-surface demand: the pack's energy-based open-water channel; packs
    # exported before it fall back to the Hamon demand (low on cold plateaus).
    lake_path = pack_dir / "input" / "lake_evaporation.mm.npy"
    open_water_r: np.ndarray | None = None
    if temp_r is not None and lake_path.exists():
        lake_p = np.nan_to_num(np.load(lake_path).astype(np.float64), nan=0.0)
        open_water_r = np.kron(lake_p, np.ones((factor, factor)))[:res, :res]
    if temp_r is not None:
        print(
            "[refine] lake evaporation: "
            + (
                "open-water energy balance"
                if open_water_r is not None
                else "Hamon fallback (no lake_evaporation.mm.npy; re-export the pack)"
            )
        )

    filled, order, rec = priority_flood(h, land, eps=0.0)
    lakes = lake_footprint(lake_mask(filled, h), filled, h)
    mmu = lake_mmu_cells(km_pp)
    lakes_draw0 = keep_large_lakes(lakes, mmu, LAKE_MIN_WIDTH_KM, km_pp) | inland_big
    rec, routing_stats = two_ring_receivers(filled, land, rec, lakes_draw0)
    # Save the geometry used for routing before the terminal-lake verdict.
    np.save(out / "height.pre-equilibrium.npy", h.astype(np.float32))
    # Terminal-lake equilibrium with through-flow depletion (the shared
    # helper): pass-through lakes deduct their net evaporation from the
    # through-flow; routing stays on the pre-rewrite tree.
    (
        h_rw,
        land,
        lakes_draw,
        chain_stop,
        fringe_desc,
        rec,
        acc,
        term_water,
        lake_stats,
        lake_records,
    ) = terminal_equilibrium_routing(
        h,
        land,
        lakes_draw0,
        order,
        rec,
        weight,
        precip_mm=precip_r if temp_r is not None else np.zeros_like(land),
        temp_c=temp_r if temp_r is not None else np.full_like(h, 0.0),
        runoff_land_mean_mm=run_norm_mm if (temp_r is not None and weight_src == "runoff") else 0.0,
        mmu_cells=mmu,
        km_per_px=km_pp,
        sea_level_m=float(meta["sea_level_m"]),
        open_water_mm=open_water_r,
        keep_rewritten_h=mode == RefinementMode.REDRAW,
    )
    if h_rw is not None:
        h = h_rw
    # Route from the saved pre-equilibrium geometry, then cut terminal sinks.
    # Source-preserving modes leave the physical bed untouched.
    h = h.astype(np.float32).astype(np.float64)
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
    Image.fromarray((geographic_land * 255).astype(np.uint8)).save(out / "land.png")
    segs, flows, regimes = river_segments(
        rivers,
        rec,
        acc,
        km_pp,
        lake=chain_stop,
        lake_descend=fringe_desc,
        month_active=month_act,
        smooth=False,
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
    if debug:
        Image.fromarray(np.clip(acc / max(acc.max(), 1.0) * 65535.0).astype(np.uint16)).save(
            out / "flow-accum.png"
        )
    sheet_meta: dict[str, object] = {
        "sea_level_m": meta["sea_level_m"],
        "source": {
            RefinementMode.REDRAW: "terrain-diffusion redrawn terrain",
            RefinementMode.BLEND: "source terrain with terrain-diffusion detail",
            RefinementMode.HYDROLOGY: "source terrain with hydrology",
        }[mode],
        "mode": mode.value,
        "cache_contract": contract,
        "td_revision": td_revision,
        "adopted_height": "height.meters.npy",
        "routing_height": "height.pre-equilibrium.npy",
        "geographic_land": "land.png",
        "height_encoding": "float32 metres; land.png preserves classification under quantisation",
        "stage_sha256": {p.name: file_sha256(p) for p in sorted(out.glob("height.*.npy"))},
        "seam_scope": "crop a fixed parent grid; independent DCT windows are not equivalent",
        "terrain_edit": {
            "depth_cap": depth_cap,
            "inland_heal": mode == RefinementMode.REDRAW,
            "terminal_floor_rewrite": mode == RefinementMode.REDRAW,
            "max_adopted_change_from_source_m": float(np.max(np.abs(h - source))),
        },
        "td_snr": TD_SNR if donor is not None else None,
        "td_seed": TD_SEED if donor is not None else None,
        "river_threshold": thr,
        "hydrology_routing": {
            "scheme": "two-ring-constrained-v1",
            "flat_preparation": "zero-epsilon Priority-Flood with equal-height D8 predecessors",
            "geometry": "receiver links without additional smoothing",
            **routing_stats,
        },
        "lake_mmu_cells": mmu,
        "hydrology_weight": weight_src,
        "runoff_normalizer_mm": round(run_norm_mm, 3),
        "terminal_lakes": lake_stats["terminal"],
        "dry_playas": lake_stats["dry_playas"],
        "shrunk_lakes": lake_stats["shrunk"],
        "lakes": lake_records,
        "lake_balance": (
            {"evaporation": "open-water energy balance (input/lake_evaporation.mm.npy)"}
            if open_water_r is not None
            else {"pet": "hamon-annual", "evaporation_factor": LAKE_EVAPORATION_FACTOR}
        ),
    }
    if mode == RefinementMode.BLEND:
        adopted_delta = h - blended
        sheet_meta["terrain_edit"] = {
            "depth_cap": depth_cap,
            "inland_heal": False,
            "terminal_floor_rewrite": False,
            "edited_pixels": int(np.count_nonzero(adopted_delta)),
            "max_raise_m": float(adopted_delta.max()),
            "rms_change_from_blended_m": float(np.sqrt(np.mean(adopted_delta**2))),
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
    # Install only after the product and manifest are complete.
    backup = tmp / "previous"
    shutil.rmtree(backup, ignore_errors=True)
    if previous.exists():
        os.replace(previous, backup)
    try:
        os.replace(out, previous)
    except OSError:
        if backup.exists():
            os.replace(backup, previous)
        raise
    shutil.rmtree(tmp, ignore_errors=True)
    result: dict[str, object] = {
        "res": res,
        "mode": mode.value,
        "lakes_pct": round(float(lakes_draw.sum() / max(land.sum(), 1) * 100), 1),
        "river_segments": int(len(segs)),
        "height_range_m": [round(lo, 1), round(hi, 1)],
    }
    if month_act is not None:
        result["regime_segments"] = [
            int((regimes == r).sum()) for r in (RIVER_REGIME_PERENNIAL, RIVER_REGIME_NON_PERENNIAL)
        ]
    return result
