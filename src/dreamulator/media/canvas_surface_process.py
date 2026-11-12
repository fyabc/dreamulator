"""Canvas surface process: erosion and deposition between TD generation and S2 hydrology.

Two-level solve (canvas-erosion-deposition proposal §3.7):

1. **Coarse level.**  The native chunks block-averaged by ``block`` (8 → about
   720 m) evolve under the round-2 solver (:mod:`dreamulator.map.surface_process`)
   for each cell's effective incision time.  The sea is S2's rule on the coarse
   grid: water at or below 0 m that reaches the open boundary inside
   geological-ocean cells, or lies inside a closed water body the mesh upgraded
   to sea class.  Inside the mesh's other closed basins the anchor is two-sided
   (their depth is canon); elsewhere one-sided.  Ice-covered cells (coarse ice
   over 1 m) do not take part.  The coarse increment is upsampled bilinearly to
   the native pixels.
2. **Native level.**  Each 2048² chunk with a halo from its neighbours is solved
   at 90 m for ``native_time_myr`` with fixed 80 kyr steps, no hillslope
   collapse (hillslopes were set on the coarse grid) and an anchor to its own
   low-pass at twice the coarse spacing, so it only clears the sub-grid pits the
   coarse level cannot see.  Overlapping windows are blended with linear weights.

The product is ``surface_process/``: per-chunk integer-metre increments
(``increments/rXXX_cYYY.npy``, final surface minus the TD chunk) and
``manifest.json``.  TD chunks are never modified; S2 reads chunk + increment when
the manifest says the product is complete (``CanvasStore.load(surface=...)``).
Land keeps its sign (at least 1 m above sea level) and sea pixels are untouched.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.map.surface_process import SurfaceProcessParams, run_surface_process
from dreamulator.map.td_canvas import PX_PER_CELL, CanvasGeometry

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

SURFACE_PROCESS_DIR = "surface_process"
MANIFEST = "manifest.json"
PRODUCT_FORMAT = "canvas-surface-process-v1"
#: Coarse ice thickness above which a cell is under ice and has no fluvial process (m).
ICE_FREE_MAX_M = 1.0
#: Peak memory of one solver process per grid cell of its window (measured: 8.6 GB for a
#: 2560 x 2560 native window, 1.3 kB per cell; rounded up).  Sizes the process pools.
SOLVER_BYTES_PER_CELL = 1400


@dataclass(frozen=True)
class CanvasSurfaceConfig:
    """Driver settings.  ``t_max_myr`` caps old platforms at a steady-state run;
    ``t_min_myr`` keeps an orogen whose onset is near zero from having no surface
    time at all; the native level runs ``native_time_myr`` in ``native_step_kyr``
    steps (convergence: 2, 4 and 8 Myr gave lake shares within 15 %)."""

    block: int = 8
    t_max_myr: float = 50.0
    t_min_myr: float = 0.5
    native: bool = True
    native_time_myr: float = 4.0
    native_step_kyr: float = 80.0
    halo_px: int = 256
    #: coarse level basin by basin (own time step per drainage basin, fixed divides, parallel);
    #: False runs the single-grid solver (one time step for the whole canvas)
    by_basin: bool = True
    params: SurfaceProcessParams = field(default_factory=SurfaceProcessParams)


@dataclass
class _Canvas:
    root: Path
    geometry: CanvasGeometry
    tile: int
    chunks: list[tuple[int, int]]

    @classmethod
    def load(cls, root: Path) -> _Canvas:
        meta = json.loads((root / "canvas.json").read_text(encoding="utf-8"))
        g = meta["geometry"]
        geom = CanvasGeometry(
            float(g["center_lat"]), float(g["center_lon"]), float(g["radius_km"]), int(g["ncell"])
        )
        chunks = [(int(c[0]), int(c[1])) for c in meta["chunks"]]
        tile = int(g.get("chunk_px", 2048))
        return cls(root=root, geometry=geom, tile=tile, chunks=chunks)

    def chunk(self, ci: int, cj: int) -> np.ndarray:
        return np.asarray(np.load(self.root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy"))

    @property
    def shape_px(self) -> tuple[int, int]:
        nr = max(c[0] for c in self.chunks) + 1
        nc = max(c[1] for c in self.chunks) + 1
        return nr * self.tile, nc * self.tile


def _block_surface(canvas: _Canvas, b: int) -> np.ndarray:
    """Native chunks block-averaged by ``b`` (NaN where chunks are missing)."""
    hpx, wpx = canvas.shape_px
    nb = canvas.tile // b
    z = np.full((hpx // b, wpx // b), np.nan, dtype=np.float32)
    for ci, cj in canvas.chunks:
        a = canvas.chunk(ci, cj).astype(np.float32)
        z[ci * nb : (ci + 1) * nb, cj * nb : (cj + 1) * nb] = a.reshape(nb, b, nb, b).mean(
            axis=(1, 3)
        )
    return z


def _coarse_to_grid(arr: np.ndarray, shape: tuple[int, int], per_cell: int) -> np.ndarray:
    r = np.minimum(np.arange(shape[0]) // per_cell, arr.shape[0] - 1)
    c = np.minimum(np.arange(shape[1]) // per_cell, arr.shape[1] - 1)
    return np.asarray(arr[np.ix_(r, c)], dtype=np.float64)


def coarse_sea(
    z: np.ndarray, geo_ocean: np.ndarray, mesh_sea_lake: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray]:
    """S2's sea rule on a coarse grid; returns (sea, mesh_basin).

    ``geo_ocean`` and ``mesh_sea_lake`` are already on the grid of ``z``.  A water
    body (≤ 0 m, 8-connected, missing pixels joined to it) is sea when it reaches
    the open boundary (frame or missing chunks) and holds a geological-ocean
    pixel, or when it holds a pixel inside a mesh sea-class lake.
    ``mesh_basin`` marks geological-ocean pixels that are not sea: the closed
    basins the mesh itself has, where the anchor is two-sided.
    """
    from scipy import ndimage

    valid = np.isfinite(z)
    water = valid & (z <= 0.0)
    open_ = ~valid
    open_[[0, -1], :] = True
    open_[:, [0, -1]] = True
    lbl, n = ndimage.label(water | ~valid, structure=np.ones((3, 3), bool))
    touch = np.zeros(n + 1, bool)
    touch[np.unique(lbl[open_])] = True
    geoc = np.zeros(n + 1, bool)
    geoc[np.unique(lbl[water & geo_ocean])] = True
    ok = touch & geoc
    if mesh_sea_lake is not None:
        meshc = np.zeros(n + 1, bool)
        meshc[np.unique(lbl[water & mesh_sea_lake])] = True
        ok |= meshc
    ok[0] = False
    sea = water & ok[lbl]
    return sea, valid & geo_ocean & ~sea


def _cache_key(*parts: bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
    return h.hexdigest()[:16]


def coarse_incision_age_myr(
    canvas: _Canvas,
    shape: tuple[int, int],
    b: int,
    teff_cells_myr: np.ndarray,
    cell_xyz: np.ndarray,
    config: CanvasSurfaceConfig,
) -> np.ndarray:
    """Incision time per coarse pixel (Myr): nearest mesh cell's T_eff, platform at the cap."""
    from scipy.spatial import cKDTree

    from dreamulator.map.td_canvas import unit_vectors

    rr = (np.arange(shape[0]) + 0.5) * b
    cc = (np.arange(shape[1]) + 0.5) * b
    out = np.empty(shape)
    tree = cKDTree(cell_xyz)
    for r0 in range(0, shape[0], 512):  # row bands bound the query memory
        rows = rr[r0 : r0 + 512]
        la, lo = canvas.geometry.pixel_to_latlon(
            rows[:, None] * np.ones((1, cc.size)), np.ones((rows.size, 1)) * cc[None, :]
        )
        _, idx = tree.query(unit_vectors(la, lo).reshape(-1, 3))
        te = teff_cells_myr[idx].reshape(rows.size, cc.size)
        out[r0 : r0 + rows.size] = np.where(np.isfinite(te), te, config.t_max_myr)
    return np.clip(out, config.t_min_myr, config.t_max_myr)


@dataclass
class CoarseInputs:
    """Everything the coarse level needs, on the coarse grid."""

    z: np.ndarray
    land: np.ndarray
    erodible: np.ndarray
    mesh_basin: np.ndarray
    runoff: np.ndarray
    precip: np.ndarray
    temp: np.ndarray
    open_water: np.ndarray | None
    age_myr: np.ndarray
    px_m: float
    info: dict[str, Any]


def coarse_inputs(
    canvas: _Canvas,
    config: CanvasSurfaceConfig,
    teff_cells_myr: np.ndarray,
    cell_xyz: np.ndarray,
) -> CoarseInputs:
    from dreamulator.media.canvas_pipeline import _geological_ocean, _mesh_sea_lake_interior

    b = config.block
    z = _block_surface(canvas, b)
    per = PX_PER_CELL // b
    geo = _coarse_to_grid(_geological_ocean(canvas.root, canvas.geometry, 0.0), z.shape, per) > 0
    msl = _mesh_sea_lake_interior(canvas.root, canvas.geometry)
    msl_g = None if msl is None else _coarse_to_grid(msl, z.shape, per) > 0
    sea, mesh_basin = coarse_sea(z, geo, msl_g)
    valid = np.isfinite(z)
    frame = np.zeros(z.shape, bool)
    frame[[0, -1], :] = True
    frame[:, [0, -1]] = True
    land = valid & ~sea & ~frame
    clim = canvas.root / "climate"

    def channel(name: str) -> np.ndarray:
        return _coarse_to_grid(np.load(clim / f"{name}.npy"), z.shape, per)

    lake_path = clim / "lake_evaporation.mm.npy"
    open_water = np.nan_to_num(channel("lake_evaporation.mm")) if lake_path.exists() else None
    ice = np.nan_to_num(channel("ice.m")) if (clim / "ice.m.npy").exists() else np.zeros(z.shape)
    age = coarse_incision_age_myr(canvas, z.shape, b, teff_cells_myr, cell_xyz, config)
    zz = np.where(valid, z, 0.0).astype(np.float64)
    zz[sea] = 0.0
    info = {
        "grid": list(z.shape),
        "px_m": canvas.geometry.px_km * b * 1000.0,
        "land_cells": int(land.sum()),
        "mesh_basin_cells": int(mesh_basin.sum()),
        "mesh_sea_lake": msl is not None,
        "lake_evaporation": "open-water channel" if open_water is not None else "Hamon fallback",
        "age_myr": {
            "median_land": round(float(np.median(age[land])), 2) if land.any() else None,
            "max": round(float(age.max()), 2),
        },
    }
    return CoarseInputs(
        z=zz,
        land=land,
        erodible=land & (ice <= ICE_FREE_MAX_M),
        mesh_basin=mesh_basin,
        runoff=channel("runoff.mm"),
        precip=channel("precipitation.mm"),
        temp=channel("temperature.C"),
        open_water=open_water,
        age_myr=age,
        px_m=canvas.geometry.px_km * b * 1000.0,
        info=info,
    )


def _upsampled_increment(dh: np.ndarray, ci: int, cj: int, tile: int, b: int) -> np.ndarray:
    """Bilinear sample of the coarse increment at one chunk's native pixel centres."""
    from scipy import ndimage

    rr = (ci * tile + np.arange(tile) + 0.5) / b - 0.5
    cc = (cj * tile + np.arange(tile) + 0.5) / b - 0.5
    rg, cg = np.meshgrid(rr, cc, indexing="ij")
    return np.asarray(ndimage.map_coordinates(dh, [rg, cg], order=1, mode="nearest"))


def _apply_increment(native: np.ndarray, inc: np.ndarray) -> np.ndarray:
    """Land keeps its sign (at least 1 m); sea pixels are untouched; integer metres."""
    out = np.where(native > 0, np.maximum(native + inc, 1.0), native)
    return np.asarray(np.round(out).astype(np.int16))


# ---------------------------------------------------------------------------
# native level (per chunk, in a process pool)
# ---------------------------------------------------------------------------


@dataclass
class _NativeContext:
    work: Path
    tile: int
    halo: int
    chunks: set[tuple[int, int]]
    px_m: float
    t_yr: float
    params: SurfaceProcessParams
    climate: dict[str, np.ndarray]
    ice: np.ndarray | None


_NATIVE: _NativeContext | None = None


def _init_native(ctx: _NativeContext) -> None:
    global _NATIVE
    import numba

    numba.set_num_threads(1)  # type: ignore[no-untyped-call]  # the pool is the parallelism
    _NATIVE = ctx


def _stage1_path(work: Path, ci: int, cj: int) -> Path:
    return work / "stage1" / f"r{ci:03d}_c{cj:03d}.npy"


def _window(ctx: _NativeContext, ci: int, cj: int) -> np.ndarray:
    t, h = ctx.tile, ctx.halo
    n = t + 2 * h
    z = np.full((n, n), np.nan, dtype=np.float32)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            key = (ci + di, cj + dj)
            if key not in ctx.chunks:
                continue
            a = np.load(_stage1_path(ctx.work, *key)).astype(np.float32)
            r0, c0 = h + di * t, h + dj * t
            rs, re = max(r0, 0), min(r0 + t, n)
            cs, ce = max(c0, 0), min(c0 + t, n)
            z[rs:re, cs:ce] = a[rs - r0 : re - r0, cs - c0 : ce - c0]
    return z


def _native_chunk(key: tuple[int, int]) -> tuple[tuple[int, int], float, float, float]:
    """Solve one chunk window at native resolution; saves the window increment (float32)."""
    ctx = _NATIVE
    assert ctx is not None
    ci, cj = key
    out = ctx.work / "native" / f"r{ci:03d}_c{cj:03d}.npy"
    core = np.load(_stage1_path(ctx.work, ci, cj))
    if not (core > 0).any():
        return key, 0.0, 0.0, 0.0
    z = _window(ctx, ci, cj)
    valid = np.isfinite(z)
    land = valid & (z > 0)
    zz = np.where(valid, z, 0.0).astype(np.float64)
    zz[~land] = np.minimum(zz[~land], 0.0)
    n = zz.shape[0]
    r0, c0 = ci * ctx.tile - ctx.halo, cj * ctx.tile - ctx.halo
    rows = np.clip((r0 + np.arange(n)) // PX_PER_CELL, 0, None)
    cols = np.clip((c0 + np.arange(n)) // PX_PER_CELL, 0, None)

    def tile_of(a: np.ndarray) -> np.ndarray:
        rr = np.minimum(rows, a.shape[0] - 1)
        cc = np.minimum(cols, a.shape[1] - 1)
        return np.asarray(a[np.ix_(rr, cc)], dtype=np.float64)

    clim = {k: tile_of(v) for k, v in ctx.climate.items()}
    erodible = land if ctx.ice is None else land & (tile_of(ctx.ice) <= ICE_FREE_MAX_M)
    t0 = time.time()
    r = run_surface_process(
        zz,
        land,
        clim["runoff"],
        clim["precip"],
        clim["temp"],
        ctx.px_m,
        ctx.t_yr,
        ctx.params,
        erodible=erodible,
        anchor=zz,
        open_water_mm=clim.get("open_water"),
    )
    np.save(out, np.where(land, r.h - zz, 0.0).astype(np.float32))
    led = r.ledger
    return key, time.time() - t0, led["sediment_residual_rel"], led["topography_residual_rel"]


def _ramp(n: int, halo: int) -> np.ndarray:
    """Window weight along one axis: 0 at the window edge, 1 from 2·halo inside."""
    d = np.minimum(np.arange(n) + 0.5, n - np.arange(n) - 0.5)
    return np.asarray(np.clip(d / (2.0 * halo), 0.0, 1.0), dtype=np.float32)


def _blend(ctx: _NativeContext, ci: int, cj: int) -> np.ndarray:
    """Partition-of-unity blend of the window increments covering one chunk core."""
    t, h = ctx.tile, ctx.halo
    n = t + 2 * h
    w1 = _ramp(n, h)
    weight = np.outer(w1, w1)
    acc = np.zeros((t, t), np.float32)
    wsum = np.zeros((t, t), np.float32)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            key = (ci + di, cj + dj)
            f = ctx.work / "native" / f"r{key[0]:03d}_c{key[1]:03d}.npy"
            if key not in ctx.chunks or not f.exists():
                continue
            inc = np.load(f)
            r0, c0 = h - di * t, h - dj * t
            rs, re = max(r0, 0), min(r0 + t, n)
            cs, ce = max(c0, 0), min(c0 + t, n)
            if rs >= re or cs >= ce:
                continue
            tr, tc = rs - r0, cs - c0
            acc[tr : tr + re - rs, tc : tc + ce - cs] += inc[rs:re, cs:ce] * weight[rs:re, cs:ce]
            wsum[tr : tr + re - rs, tc : tc + ce - cs] += weight[rs:re, cs:ce]
    return np.asarray(np.where(wsum > 0, acc / np.maximum(wsum, 1e-9), 0.0))


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def run_canvas_surface_process(
    canvas_dir: Path,
    teff_cells_myr: np.ndarray,
    cell_xyz: np.ndarray,
    config: CanvasSurfaceConfig | None = None,
    *,
    workers: int | None = None,
    source: dict[str, Any] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run both levels on a canvas and write ``surface_process/``; returns the manifest."""
    import shutil

    from dreamulator.media.canvas_pipeline import _start_method
    from dreamulator.utils.resources import worker_budget

    cfg = config or CanvasSurfaceConfig()
    canvas = _Canvas.load(canvas_dir)
    out = canvas_dir / SURFACE_PROCESS_DIR
    work = out / "work"
    for sub in ("stage1", "native", "increments"):
        (out if sub == "increments" else work).joinpath(sub).mkdir(parents=True, exist_ok=True)
    manifest_path = out / MANIFEST
    if manifest_path.exists():
        manifest_path.unlink()  # an interrupted run never leaves a "complete" manifest behind
    t0 = time.time()

    # 1. coarse level
    ci_ = coarse_inputs(canvas, cfg, teff_cells_myr, cell_xyz)
    t_yr = float(ci_.age_myr[ci_.land].max()) * 1e6 if ci_.land.any() else 0.0
    log(
        f"[erode] coarse grid {ci_.z.shape} at {ci_.px_m:.0f} m, land {ci_.info['land_cells']} "
        f"cells, T {t_yr / 1e6:.1f} Myr, lake evaporation: {ci_.info['lake_evaporation']}"
    )
    basin_info: dict[str, Any] | None = None
    if cfg.by_basin:
        from dreamulator.map.surface_process_basins import run_surface_process_by_basin

        coarse, basin_info = run_surface_process_by_basin(
            ci_.z,
            ci_.land,
            ci_.runoff,
            ci_.precip,
            ci_.temp,
            ci_.px_m,
            cfg.params,
            age_yr=ci_.age_myr * 1e6,
            erodible=ci_.erodible,
            anchor=ci_.z,
            two_sided_mask=ci_.mesh_basin,
            open_water_mm=ci_.open_water,
            workers=workers,
            log=log,
        )
    else:
        coarse = run_surface_process(
            ci_.z,
            ci_.land,
            ci_.runoff,
            ci_.precip,
            ci_.temp,
            ci_.px_m,
            t_yr,
            cfg.params,
            age_yr=ci_.age_myr * 1e6,
            erodible=ci_.erodible,
            anchor=ci_.z,
            two_sided_mask=ci_.mesh_basin,
            open_water_mm=ci_.open_water,
            log=log,
        )
    dh = np.where(ci_.land, coarse.h - ci_.z, 0.0).astype(np.float32)
    log(f"[erode] coarse level done in {time.time() - t0:.0f} s ({coarse.steps} steps)")

    # 2. stage 1 on the native chunks: TD + upsampled coarse increment
    for ci, cj in canvas.chunks:
        native = canvas.chunk(ci, cj)
        inc = _upsampled_increment(dh, ci, cj, canvas.tile, cfg.block)
        np.save(_stage1_path(work, ci, cj), _apply_increment(native.astype(np.float64), inc))

    # 3. native level
    native_info: dict[str, Any] = {"enabled": cfg.native}
    ctx: _NativeContext | None = None
    if cfg.native:
        clim_dir = canvas_dir / "climate"
        climate = {
            "runoff": np.load(clim_dir / "runoff.mm.npy"),
            "precip": np.load(clim_dir / "precipitation.mm.npy"),
            "temp": np.load(clim_dir / "temperature.C.npy"),
        }
        if (clim_dir / "lake_evaporation.mm.npy").exists():
            climate["open_water"] = np.load(clim_dir / "lake_evaporation.mm.npy")
        ice = np.load(clim_dir / "ice.m.npy") if (clim_dir / "ice.m.npy").exists() else None
        steps = max(1, round(cfg.native_time_myr * 1000.0 / cfg.native_step_kyr))
        coarse_km = canvas.geometry.px_km * cfg.block
        nparams = SurfaceProcessParams(
            **{
                **asdict(cfg.params),
                "fixed_steps": steps,
                "threshold": False,
                "anchor_sigma_km": 2.0 * coarse_km,
                "parallel_flood": False,
            }
        )
        ctx = _NativeContext(
            work=work,
            tile=canvas.tile,
            halo=cfg.halo_px,
            chunks=set(canvas.chunks),
            px_m=canvas.geometry.px_km * 1000.0,
            t_yr=cfg.native_time_myr * 1e6,
            params=nparams,
            climate={k: np.nan_to_num(np.asarray(v, dtype=np.float64)) for k, v in climate.items()},
            ice=None if ice is None else np.nan_to_num(np.asarray(ice, dtype=np.float64)),
        )
        window = (canvas.tile + 2 * cfg.halo_px) ** 2
        n = worker_budget(SOLVER_BYTES_PER_CELL * window) if workers is None else max(1, workers)
        log(f"[erode] native level: {len(canvas.chunks)} chunks on {n} processes")
        worst = 0.0
        t1 = time.time()
        if n == 1 or len(canvas.chunks) < 2:
            _init_native(ctx)
            results = [_native_chunk(k) for k in canvas.chunks]
        else:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor

            with ProcessPoolExecutor(
                max_workers=min(n, len(canvas.chunks)),
                mp_context=mp.get_context(_start_method()),
                initializer=_init_native,
                initargs=(ctx,),
            ) as pool:
                results = list(pool.map(_native_chunk, canvas.chunks, chunksize=1))
        for _key, _sec, rs, rt in results:
            worst = max(worst, rs, rt)
        native_info.update(
            steps=steps,
            time_myr=cfg.native_time_myr,
            anchor_sigma_km=round(2.0 * coarse_km, 3),
            halo_px=cfg.halo_px,
            worst_ledger_residual=worst,
            seconds=round(time.time() - t1),
        )
        log(f"[erode] native level done in {time.time() - t1:.0f} s, worst residual {worst:.1e}")

    # 4. increments: final surface minus the TD chunk
    changed = 0
    for ci, cj in canvas.chunks:
        native = canvas.chunk(ci, cj).astype(np.int32)
        stage1 = np.load(_stage1_path(work, ci, cj)).astype(np.float64)
        if ctx is not None:
            final = _apply_increment(stage1, _blend(ctx, ci, cj))
        else:
            final = stage1.astype(np.int16)
        inc = (final.astype(np.int32) - native).astype(np.int16)
        changed += int(np.count_nonzero(inc))
        np.save(out / "increments" / f"r{ci:03d}_c{cj:03d}.npy", inc)
    shutil.rmtree(work)
    manifest = {
        "format": PRODUCT_FORMAT,
        "status": "complete",
        "increments": "increments/rXXX_cYYY.npy, int16 metres, final surface minus the TD chunk",
        "config": {**asdict(cfg), "params": asdict(cfg.params)},
        "coarse": {
            **ci_.info,
            "steps": coarse.steps,
            "t_myr": t_yr / 1e6,
            "ledger": coarse.ledger,
            "by_basin": basin_info,
        },
        "native": native_info,
        "changed_pixels": changed,
        "source": source or {},
        "seconds": round(time.time() - t0),
    }
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"[erode] done in {time.time() - t0:.0f} s; {changed} native pixels changed")
    return manifest


#: Installed-surface choices every canvas reader accepts.
SURFACES = ("auto", "td", "surface-process")


def resolve_increments(canvas_dir: Path, surface: str = "auto") -> Path | None:
    """Increment directory the readers add to the TD chunks, or None for the TD surface.

    ``"td"`` is the TD chunks; ``"surface-process"`` requires a complete product;
    ``"auto"`` uses the product when it is complete.  S2 (``CanvasStore``), the
    window crop (``CanvasSource``), the seam check and the mosaic all decide here,
    so hydrology and rendering always see the same surface.
    """
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface!r}; use one of {', '.join(SURFACES)}")
    if surface == "td":
        return None
    complete = surface_process_complete(canvas_dir)
    if surface == "surface-process" and not complete:
        raise FileNotFoundError(f"{canvas_dir / SURFACE_PROCESS_DIR} holds no complete product")
    return canvas_dir / SURFACE_PROCESS_DIR / "increments" if complete else None


def surface_tag(canvas_dir: Path, increments: Path | None) -> str:
    """Label of an installed surface, recorded with every S2 product built on it.

    ``"td"`` for the TD chunks; ``"surface-process:<manifest sha>"`` for the eroded
    surface, so re-running the erosion invalidates hydrology built on the old one.
    """
    if increments is None:
        return "td"
    digest = hashlib.sha256((canvas_dir / SURFACE_PROCESS_DIR / MANIFEST).read_bytes())
    return f"surface-process:{digest.hexdigest()[:12]}"


def read_surface_tag(directory: Path) -> str | None:
    """The surface tag ``directory/surface.json`` records (None when absent)."""
    path = directory / "surface.json"
    if not path.exists():
        return None
    return str(json.loads(path.read_text(encoding="utf-8")).get("surface"))


def write_surface_tag(directory: Path, tag: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "surface.json").write_text(json.dumps({"surface": tag}), encoding="utf-8")


def surface_process_complete(canvas_dir: Path) -> bool:
    """True when ``surface_process/`` holds a complete product."""
    path = canvas_dir / SURFACE_PROCESS_DIR / MANIFEST
    if not path.exists():
        return False
    meta = json.loads(path.read_text(encoding="utf-8"))
    return bool(meta.get("format") == PRODUCT_FORMAT and meta.get("status") == "complete")
