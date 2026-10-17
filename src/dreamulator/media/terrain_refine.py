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
import subprocess
from pathlib import Path

import numpy as np

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
    py = td_repo / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise FileNotFoundError(
            f"terrain-diffusion venv not found at {py} — see the manual's "
            "setup section (uv venv + CUDA wheels, external to this project)"
        )
    return py


def _export_conditioning(pack_dir: Path, tmp: Path, *, coast_warp: bool = False) -> int:
    """Stage 1 (main env): window the mesh + monthly climate → .npy fields."""
    from dreamulator.map.export import export_cell_index_grid, find_mesh_file, load_cvt_mesh_model
    from dreamulator.map.region_export import read_radius_km, region_window

    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    src = meta["source"]
    world_dir = Path("data") / "worlds" / src["world"]
    map_dir = world_dir / "maps" / src["planet"]

    mesh_file = find_mesh_file(map_dir)
    if mesh_file is None:
        raise FileNotFoundError(f"no cvt mesh under {map_dir}")
    mesh = load_cvt_mesh_model(mesh_file)
    radius_km = read_radius_km(map_dir)
    grid_w, grid_h = 4096, 2048
    window = region_window(
        meta["center_lat"], meta["center_lon"], meta["span_km"], radius_km, grid_w, grid_h
    )
    indices_full = export_cell_index_grid(mesh, grid_w, grid_h)
    indices = indices_full[window.y0 : window.y1, window.x0 : window.x1]

    import msgpack

    monthly = map_dir / "climate_monthly.msgpack"
    if not monthly.exists():
        raise FileNotFoundError(f"monthly climate series missing: {monthly}")
    with monthly.open("rb") as f:
        d = msgpack.unpackb(f.read())
    n, m = int(d["num_cells"]), int(d["months"])

    def deq(prefix: str) -> np.ndarray:
        q = np.frombuffer(d[f"{prefix}_monthly"], dtype="<i2").astype(np.float64)
        return (q * float(d[f"{prefix}_scale"]) + float(d[f"{prefix}_offset"])).reshape(n, m)

    t_m, p_m = deq("t"), deq("p")
    t_mean, p_mean = t_m.mean(axis=1), p_m.mean(axis=1)
    fields = {
        "elevation_m": np.fromiter((c.elevation for c in mesh.cells), dtype=np.float64, count=n),
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

        cell_px = float(meta["cell_pitch_km"]) / (float(meta["extent_km"]["x"]) / window.grid_w)
        out_fields = {
            name: apply_boundary_warp(arr, cell_px, order=0 if name == "elevation_m" else 1)
            for name, arr in out_fields.items()
        }
    for name, arr in out_fields.items():
        np.save(tmp / f"{name}.npy", arr.astype(np.float32))
    return window.grid_w


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
        LAKE_MIN_WIDTH_KM,
        flow_accumulation,
        heal_inland_water,
        keep_large_lakes,
        lake_mask,
        lake_mmu_cells,
        priority_flood,
        river_mask,
        river_segments,
    )

    pack_dir = pack_dir.resolve()  # td subprocess runs with cwd=repo —
    # every path handed to it must be absolute or it resolves under the repo
    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    pack_res = int(meta["grid"]["w"])
    res = pack_res * REFINE_FACTOR
    tmp = pack_dir / "refine-tmp"

    cached = pack_dir / "refined-out" / "height.meters.npy"
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

    rain = np.nan_to_num(
        np.load(pack_dir / "input" / "precipitation.mm.npy").astype(np.float64), nan=0.0
    )
    factor = res // rain.shape[0]
    rain_r = np.kron(rain, np.ones((factor, factor)))[:res, :res]
    weight = rain_r / rain_r[land].mean() if rain_r[land].any() else np.where(land, 1.0, 0.0)

    filled, order, rec = priority_flood(h, land)
    lakes = lake_mask(filled, h)
    mmu = lake_mmu_cells(km_pp)
    lakes_draw = keep_large_lakes(lakes, mmu, LAKE_MIN_WIDTH_KM, km_pp) | inland_big
    acc = flow_accumulation(order, rec, weight)
    thr = river_threshold if river_threshold is not None else 3000 * factor * factor
    rivers = river_mask(acc, land, thr)

    out = pack_dir / "refined-out"
    out.mkdir(exist_ok=True)
    lo, hi = float(h.min()), float(h.max())
    span = hi - lo or 1.0
    np.save(out / "height.meters.npy", h.astype(np.float32))
    export_elevation_png(h, out / "height.gaea.png", min_m=lo, max_m=hi)
    segs, flows = river_segments(rivers, rec, acc, km_pp, lake=lakes_draw)
    np.save(out / "rivers.line.npy", segs)
    np.save(out / "rivers.flow.npy", flows)
    rivers &= ~lakes_draw
    Image.fromarray((rivers * 255).astype(np.uint8)).save(out / "rivers.png")
    Image.fromarray((lakes_draw * 255).astype(np.uint8)).save(out / "lake.png")
    Image.fromarray(((~land & ~inland_big) * 255).astype(np.uint8)).save(out / "sea-water.png")
    sea_depth = np.clip(float(meta["sea_level_m"]) - h, 0, None) / span
    sea_depth[inland_big] = 0.0
    Image.fromarray(np.clip(sea_depth * 65535, 0, 65535).astype(np.uint16)).save(
        out / "sea-depth.png"
    )
    Image.fromarray(np.clip(acc / max(acc.max(), 1.0) * 65535.0).astype(np.uint16)).save(
        out / "flow-accum.png"
    )
    (out / "meta.json").write_text(
        json.dumps(
            {
                "height_gaea_png_range_m": [lo, hi],
                "sea_level_m": meta["sea_level_m"],
                "source": "terrain-diffusion 90m refined",
                "td_snr": TD_SNR,
                "td_seed": TD_SEED,
                "river_threshold": thr,
                "lake_mmu_cells": mmu,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    # The intermediates are reproducible from the pack — remove the scratch.
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
    return {
        "res": res,
        "lakes_pct": round(float(lakes_draw.sum() / max(land.sum(), 1) * 100), 1),
        "river_segments": int(len(segs)),
        "height_range_m": [round(lo, 1), round(hi, 1)],
    }
