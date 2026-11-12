"""Surface process run basin by basin: each drainage basin takes its own time step, in parallel.

The single-grid solver (:func:`dreamulator.map.surface_process.run_surface_process`) takes one
time step for the whole grid, set by the largest river (``max_cells_per_step`` cells of
knickpoint travel per step), and runs every cell for the longest incision time.  On a
continent-sized canvas the biggest river then forces thousands of steps on every small basin.

Here the initial surface is routed once, every land cell is labelled with the outlet its water
reaches, and each basin is evolved on its own crop with the unchanged solver: its time step
follows its own largest discharge and its run time its own longest incision time.  Basins are
independent, so they run in parallel.  Small basins are packed by tile into one crop each.

Approximation (one closure, numerical class): the drainage divides of the initial surface stay
fixed for the run.  Cells of other basins inside a crop are walls the water cannot enter, so
river capture across a divide, hillslope adjustment across it and the anchoring low-pass across
it are not represented; the anchor is a masked low-pass over the basin's own cells.  The
validation against the single-grid run (lake share, lake density, relief) is in the canvas
erosion proposal.

Pure computation: no IO.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import ndimage

from . import prog_erosion as pe
from .surface_process import SurfaceProcessParams, SurfaceProcessResult, route, run_surface_process

if TYPE_CHECKING:
    from collections.abc import Callable

#: Basins with at least this many mutable cells get a crop of their own; smaller ones are
#: packed by ``TILE`` x ``TILE`` tiles (numerical: task granularity only).
BIG_BASIN_CELLS = 20_000
TILE = 512
#: Time-step bound of a basin run when the parameters set none (numerical: the native level's
#: validated fixed step).  A small basin alone would otherwise take one step for its whole run.
DEFAULT_MAX_DT_YR = 80_000.0
#: Default pool: few processes with many threads each, because the largest basin sets the
#: wall-clock time and its routing runs threaded; the threads share out the CPU quota.
DEFAULT_WORKERS = 4
MAX_THREADS = 16
#: Peak memory of one solver process per cell of its crop (see canvas_surface_process).
SOLVER_BYTES_PER_CELL = 1400
#: Height of the walls standing in for other basins' cells inside a crop.
WALL_M = 1.0e5

_LEDGER_KEYS = (
    "eroded_km3",
    "dep_river_km3",
    "dep_lake_km3",
    "exported_km3",
    "playa_km3",
    "uplift_km3",
    "anchor_withheld_km3",
    "volume_change_km3",
)


def _label_basins(order: np.ndarray, rec: np.ndarray) -> np.ndarray:
    from ._surface_process_kernels import _outlet_labels

    return np.asarray(_outlet_labels(np.ascontiguousarray(order), np.ascontiguousarray(rec)))


@dataclass(frozen=True)
class _Task:
    rows: slice
    cols: slice
    members: np.ndarray  # bool, crop shape: the basin cells evolved here


def plan_tasks(
    z: np.ndarray, land: np.ndarray, mutable: np.ndarray, *, parallel_flood: bool = True
) -> tuple[list[_Task], dict[str, Any]]:
    """Basin crops of the initial surface, largest first."""
    _filled, order, rec = pe.priority_flood(z, land, parallel=parallel_flood)
    lab = _label_basins(order, rec).reshape(z.shape)
    lab = np.where(mutable, lab, -1)
    uniq, compact = np.unique(lab, return_inverse=True)
    compact = compact.reshape(z.shape).astype(np.int64)
    if uniq[0] == -1:
        compact -= 1  # non-mutable -> -1, basins 0..n-1
        uniq = uniq[1:]
    n = uniq.size
    sizes = np.bincount(compact[compact >= 0], minlength=n)
    boxes = ndimage.find_objects(compact + 1)
    h, w = z.shape

    def padded(sl: tuple[slice, slice]) -> tuple[slice, slice]:
        return (
            slice(max(sl[0].start - 1, 0), min(sl[0].stop + 1, h)),
            slice(max(sl[1].start - 1, 0), min(sl[1].stop + 1, w)),
        )

    tasks: list[_Task] = []
    big = np.flatnonzero(sizes >= BIG_BASIN_CELLS)
    for b in big[np.argsort(-sizes[big])]:
        r, c = padded(boxes[b])
        tasks.append(_Task(r, c, compact[r, c] == b))
    small = np.flatnonzero(sizes < BIG_BASIN_CELLS)
    groups: dict[tuple[int, int], list[int]] = {}
    for b in small:
        sl = boxes[b]
        key = ((sl[0].start + sl[0].stop) // (2 * TILE), (sl[1].start + sl[1].stop) // (2 * TILE))
        groups.setdefault(key, []).append(int(b))
    for members in groups.values():
        r0 = min(boxes[b][0].start for b in members)
        r1 = max(boxes[b][0].stop for b in members)
        c0 = min(boxes[b][1].start for b in members)
        c1 = max(boxes[b][1].stop for b in members)
        r, c = padded((slice(r0, r1), slice(c0, c1)))
        tasks.append(_Task(r, c, np.isin(compact[r, c], members)))
    tasks.sort(key=lambda t: -int(t.members.sum()))
    info = {
        "basins": int(n),
        "big_basins": int(big.size),
        "tasks": len(tasks),
        "largest_basin_share": float(sizes.max() / max(sizes.sum(), 1)) if n else 0.0,
    }
    return tasks, info


@dataclass
class _Shared:
    z: np.ndarray
    land: np.ndarray
    runoff: np.ndarray
    precip: np.ndarray
    temp: np.ndarray
    age: np.ndarray
    erodible: np.ndarray
    anchor: np.ndarray | None
    two_sided: np.ndarray | None
    open_water: np.ndarray | None
    px_m: float
    params: SurfaceProcessParams
    threads: int


_SHARED: _Shared | None = None


def _init(shared: _Shared) -> None:
    global _SHARED
    _SHARED = shared
    import numba

    numba.set_num_threads(max(1, min(shared.threads, int(numba.config.NUMBA_NUM_THREADS))))  # type: ignore[no-untyped-call,attr-defined]


def _run_task(task: _Task) -> tuple[_Task, np.ndarray, dict[str, float], int, float]:
    s = _SHARED
    assert s is not None
    r, c, m = task.rows, task.cols, task.members
    land_c = s.land[r, c]
    others = land_c & ~m  # other basins: walls
    z = np.where(others, WALL_M, s.z[r, c])
    land = land_c & m
    runoff = np.where(m, s.runoff[r, c], np.nan)
    age = s.age[r, c]
    t_yr = float(age[m & s.erodible[r, c]].max()) if (m & s.erodible[r, c]).any() else 0.0
    t0 = time.time()
    if t_yr <= 0.0:
        return task, s.z[r, c].copy(), dict.fromkeys(_LEDGER_KEYS, 0.0), 0, 0.0
    res = run_surface_process(
        z,
        land,
        runoff,
        s.precip[r, c],
        s.temp[r, c],
        s.px_m,
        t_yr,
        s.params,
        age_yr=age,
        erodible=s.erodible[r, c] & m,
        anchor=None if s.anchor is None else np.where(others, WALL_M, s.anchor[r, c]),
        two_sided_mask=None if s.two_sided is None else s.two_sided[r, c] & m,
        open_water_mm=None if s.open_water is None else s.open_water[r, c],
    )
    led = {k: float(res.ledger.get(k, 0.0)) for k in _LEDGER_KEYS}
    return task, res.h, led, res.steps, time.time() - t0


def run_surface_process_by_basin(
    z0: np.ndarray,
    land: np.ndarray,
    runoff_mm: np.ndarray,
    precip_mm: np.ndarray,
    temp_c: np.ndarray,
    px_m: float,
    params: SurfaceProcessParams | None = None,
    *,
    age_yr: np.ndarray,
    erodible: np.ndarray | None = None,
    anchor: np.ndarray | None = None,
    two_sided_mask: np.ndarray | None = None,
    open_water_mm: np.ndarray | None = None,
    workers: int | None = None,
    threads_per_worker: int | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[SurfaceProcessResult, dict[str, Any]]:
    """Basin-by-basin counterpart of :func:`run_surface_process` (fixed divides).

    Each cell runs for its own ``age_yr`` as in the single-grid solver; a basin's run ends at
    its longest age.  Returns the result on the whole grid (lakes, terminal cells and
    discharge from one final routing) and a summary of the basin tasks.
    """
    p = params or SurfaceProcessParams()
    z = np.ascontiguousarray(z0, dtype=np.float64)
    frame = np.zeros(z.shape, bool)
    frame[0] = frame[-1] = True
    frame[:, 0] = frame[:, -1] = True
    ero = np.ones(z.shape, bool) if erodible is None else erodible
    t0 = time.time()
    tasks, info = plan_tasks(z, land, land & ~frame, parallel_flood=p.parallel_flood)
    if log is not None:
        log(
            f"[basins] {info['basins']} basins, {info['big_basins']} with own crops, "
            f"{info['tasks']} tasks; largest basin "
            f"{100 * info['largest_basin_share']:.1f}% of cells "
            f"({time.time() - t0:.0f} s)"
        )
    from dreamulator.utils.resources import cpu_quota, worker_budget

    largest = max((t.members.size for t in tasks), default=0)
    n = (
        worker_budget(SOLVER_BYTES_PER_CELL * largest, cap=DEFAULT_WORKERS)
        if workers is None
        else max(1, workers)
    )
    threads = threads_per_worker or max(1, min(MAX_THREADS, cpu_quota() // n))
    shared = _Shared(
        z=z,
        land=land,
        runoff=np.asarray(runoff_mm, dtype=np.float64),
        precip=np.nan_to_num(np.asarray(precip_mm, dtype=np.float64)),
        temp=np.nan_to_num(np.asarray(temp_c, dtype=np.float64)),
        age=np.asarray(age_yr, dtype=np.float64),
        erodible=ero,
        anchor=None if anchor is None else np.asarray(anchor, dtype=np.float64),
        two_sided=two_sided_mask,
        open_water=None if open_water_mm is None else np.asarray(open_water_mm, dtype=np.float64),
        px_m=px_m,
        params=replace(
            p,
            parallel_flood=p.parallel_flood and threads > 1,
            max_dt_yr=p.max_dt_yr if p.max_dt_yr > 0 else DEFAULT_MAX_DT_YR,
        ),
        threads=threads,
    )
    h = z.copy()
    ledger = dict.fromkeys(_LEDGER_KEYS, 0.0)
    max_steps, total_steps, slowest = 0, 0, 0.0
    done = 0

    def collect(out: tuple[_Task, np.ndarray, dict[str, float], int, float]) -> None:
        nonlocal max_steps, total_steps, slowest, done
        task, hc, led, steps, sec = out
        view = h[task.rows, task.cols]
        view[task.members] = hc[task.members]
        for k in _LEDGER_KEYS:
            ledger[k] += led[k]
        max_steps = max(max_steps, steps)
        total_steps += steps
        slowest = max(slowest, sec)
        done += 1
        if log is not None and (done <= 10 or done % 200 == 0 or done == len(tasks)):
            log(
                f"[basins] task {done}/{len(tasks)}: {int(task.members.sum())} cells, "
                f"{steps} steps, "
                f"{sec:.0f} s ({time.time() - t0:.0f} s elapsed)"
            )

    if n == 1 or len(tasks) < 2:
        _init(shared)
        for t in tasks:
            collect(_run_task(t))
    else:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor

        from dreamulator.media.canvas_pipeline import _start_method

        with ProcessPoolExecutor(
            max_workers=min(n, len(tasks)),
            mp_context=mp.get_context(_start_method()),
            initializer=_init,
            initargs=(shared,),
        ) as pool:
            for out in pool.map(_run_task, tasks, chunksize=1):
                collect(out)
    area = px_m * px_m
    rbar = float(np.nanmean(np.where(land, runoff_mm, np.nan))) if land.any() else 0.0
    runoff_m3 = np.where(land, np.nan_to_num(runoff_mm) * 1e-3 * px_m * px_m, 0.0)
    r = route(h, land, runoff_m3, shared.precip, shared.temp, rbar, area, p, open_water_mm)
    sed_in = ledger["eroded_km3"]
    sed_out = (
        ledger["dep_river_km3"]
        + ledger["dep_lake_km3"]
        + ledger["exported_km3"]
        + ledger["playa_km3"]
    )
    ledger["sediment_residual_rel"] = abs(sed_in - sed_out) / max(sed_in, 1e-12)
    expect = (
        -sed_in
        + ledger["dep_river_km3"]
        + ledger["dep_lake_km3"]
        + ledger["playa_km3"]
        + ledger["uplift_km3"]
    )
    ledger["topography_residual_rel"] = abs(ledger["volume_change_km3"] - expect) / max(
        sed_in, 1e-12
    )
    info.update(
        max_steps=max_steps,
        total_steps=total_steps,
        slowest_task_s=round(slowest, 1),
        workers=n,
        threads_per_worker=threads,
        seconds=round(time.time() - t0),
        unchanged_off_land=bool(np.array_equal(h[~(land & ~frame)], z[~(land & ~frame)])),
        # lake infill fills every lake cell, non-erodible (ice) ones included, as in the
        # single-grid solver
        non_erodible_cells_filled=int(np.count_nonzero((h != z) & land & ~frame & ~ero)),
    )
    result = SurfaceProcessResult(
        h=h,
        steps=max_steps,
        ledger=ledger,
        lake=r["lake"],
        terminal=r["terminal"],
        discharge_m3_yr=r["q"],
    )
    return result, info
