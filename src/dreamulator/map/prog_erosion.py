"""prog_erosion — programmatic SPL erosion on a region-pack DEM.

Replaces the manual Gaea leg with a seeded, scriptable one: Priority-Flood
drainage (Barnes et al. 2014) + implicit stream-power erosion (Braun &
Willett 2013) on the regular pack grid, driven by the pack's own
precipitation field (same physical doctrine as the Gaea chain: storm
runoff is the erosion agent).

    pack input (height + precipitation)  →  eroded height + tree-shaped
    river network (flow accumulation)

Outputs land in ``<pack>/prog-out/`` in the gaea-out file vocabulary
(height PNG + mask PNGs) so the existing render legs can consume them
unchanged.

The algorithm follows the public papers (Barnes 2014; Braun & Willett
2013); implementation is original (regular-grid, numba).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path


# --- solver constants (physics / numerics, not tuning knobs) ----------------
#: epsilon gradient for Priority-Flood routing (metres per cell): small
#: enough not to alter relief, large enough to break flat-lake ties.
PF_EPS_M = 1e-4
#: SPL exponents: m = 0.5, n = 1 is the classic steady-state channel
#: geometry (whipple & tucker 1999); we solve n = 1 (linear in h, which
#: the implicit scheme requires).
SPL_M = 0.5
#: Sub-metre deterministic roughness injected before routing: a smooth
#: interpolated DEM makes D8 steepest descent run along grid/45° lines;
#: ~1.5 m of fBm at ~12-cell wavelength breaks the symmetry without
#: touching any contour interval (documented, far below data resolution).
NOISE_AMPLITUDE_M = 1.5
NOISE_WAVELENGTH_CELLS = 12.0
NOISE_SEED = 42
#: Hillslope transport as linear diffusion, applied as an equivalent
#: Gaussian smoothing per step (σ² = 2·D·dt on the metre grid): rounds
#: spl-etched channel walls into real valley sides.  Land only, sea fixed.
HILLSLOPE_SIGMA_PX = 0.5
#: Closed basins deeper than this fill become lakes (endorheic water
#: bodies — the Barnes 2014 semantic: filled surface is the water level,
#: the channel network enters the lake and resumes at its spill point).
LAKE_MIN_FILL_M = 5.0
#: Minimum lake area in cells — smaller closed basins stay on the river
#: path (the fill there is local; a straight crossing spans tens of metres
#: and is invisible at sheet scale), which keeps TD-generated DEMs from
#: shattering into micro-lakes (13.7% of land lake-ised before this).
LAKE_MIN_CELLS = 64


def _roughness(
    n: int,
    seed: int = NOISE_SEED,
    amplitude: float = NOISE_AMPLITUDE_M,
    wavelength: float = NOISE_WAVELENGTH_CELLS,
) -> np.ndarray:
    """Deterministic fBm roughness in ±amplitude (metres)."""
    import opensimplex

    rng = opensimplex.OpenSimplex(seed)
    xs = np.arange(n) / wavelength
    field = sum(
        (0.5**o) * rng.noise2array(xs * (2.0**o), xs * (2.0**o))
        for o in range(3)
    )
    return np.asarray(amplitude * field / np.abs(field).max(), dtype=np.float64)


def apply_terrain_roughness(dem: np.ndarray, land: np.ndarray) -> np.ndarray:
    """DEM plus deterministic sub-metre roughness (grid-anisotropy break for
    interpolated engine DEMs; refined diffusion DEMs carry their own natural
    roughness — measured σ 31 m on plains — and skip this)."""
    return np.asarray(dem + _roughness(dem.shape[0]) * land, dtype=np.float64)


def priority_flood(
    dem: np.ndarray, land: np.ndarray, eps: float = PF_EPS_M, breach: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fill depressions from the sea inward; return (filled, order, receiver).

    ``order`` lists cells downstream-first (a cell's receiver always appears
    earlier); ``receiver`` is the D8 steepest-descent neighbour on the
    filled surface (-1 for ocean).  Numba-jitted heap walk, O(n log n).
    """
    from ._erosion_kernels import _priority_flood_numba

    return _priority_flood_numba(np.ascontiguousarray(dem, dtype=np.float64),
                                 np.ascontiguousarray(land, dtype=np.uint8), eps, breach)


def flow_accumulation(
    order: np.ndarray, receiver: np.ndarray, weight: np.ndarray
) -> np.ndarray:
    """Upstream sum of ``weight`` along receivers (downstream-first order)."""
    from ._erosion_kernels import _accumulate_numba

    return _accumulate_numba(np.ascontiguousarray(order, dtype=np.int64),
                             np.ascontiguousarray(receiver, dtype=np.int64),
                             np.ascontiguousarray(weight, dtype=np.float64))


def spl_erode(
    dem: np.ndarray,
    land: np.ndarray,
    rain_m: np.ndarray,
    *,
    steps: int = 40,
    dt_yr: float = 5e4,
    k_spl: float = 2e-6,
    uplift_m_yr: float = 0.0,
    sea_level_m: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Erode ``dem`` in place by implicit SPL; returns (dem, accumulation).

    dh/dt = U − K·A^m·S with S solved linearly between a cell and its
    receiver (n = 1): the Braun–Willett implicit update is unconditionally
    stable and processes cells in drainage order.  Sea cells are fixed
    (base level).  ``rain_m`` is each cell's own runoff weight (metres of
    storm runoff per step scaling — only its relative pattern matters).
    """
    from ._erosion_kernels import _spl_step_numba

    h = np.ascontiguousarray(dem, dtype=np.float64).copy()
    # Break grid anisotropy before routing (see NOISE_*/PLAIN_* constants) —
    # the noise rides the DEM through erosion, so the channels inherit it.
    # Land only: sea cells stay exact (base level + clean depth masks).
    h = apply_terrain_roughness(h, land)
    land8 = np.ascontiguousarray(land, dtype=np.uint8)
    rain = np.ascontiguousarray(rain_m, dtype=np.float64)
    acc = np.zeros_like(h)
    filled = np.empty_like(h)
    order = np.empty(h.size, dtype=np.int64)
    receiver = np.empty(h.size, dtype=np.int64)
    for _ in range(steps):
        _priority_flood_inplace(h, land8, PF_EPS_M, filled, order, receiver)
        acc = flow_accumulation(order, receiver, rain)
        _spl_step_numba(h, land8, order, receiver, acc, dt_yr, k_spl,
                        SPL_M, uplift_m_yr, sea_level_m)
        _hillslope_step(h, land8, HILLSLOPE_SIGMA_PX)
    return h, acc


def _hillslope_step(h: np.ndarray, land8: np.ndarray, sigma_px: float) -> None:
    """Linear-diffusion hillslope pass (equivalent Gaussian, land only)."""
    if sigma_px <= 0.0:
        return
    from scipy.ndimage import gaussian_filter

    smoothed = gaussian_filter(h, sigma=sigma_px)
    h[...] = np.where(land8.astype(bool), smoothed, h)


def _priority_flood_inplace(
    h: np.ndarray, land8: np.ndarray, eps: float,
    filled: np.ndarray, order: np.ndarray, receiver: np.ndarray,
) -> None:
    from ._erosion_kernels import _priority_flood_into

    _priority_flood_into(h, land8, eps, filled, order, receiver)


def river_mask(
    accumulation: np.ndarray, land: np.ndarray, threshold_cells: int = 200
) -> np.ndarray:
    """Channels: land cells whose upstream runoff exceeds ``threshold_cells``."""
    return land & (accumulation > threshold_cells)


def lake_mask(
    filled: np.ndarray,
    dem: np.ndarray,
    min_fill_m: float = LAKE_MIN_FILL_M,
    min_cells: int = LAKE_MIN_CELLS,
) -> np.ndarray:
    """Endorheic lakes: land cells where the filled surface sits above the
    ground by ``min_fill_m`` (closed basins — TD-generated DEMs have plenty;
    the engine chain gets them where interpolation sinks below spill).
    Basins smaller than ``min_cells`` are not lakes: the channel keeps
    crossing them (fill there is local and the crossing is invisible at
    sheet scale) — without this, generated DEMs shatter into micro-lakes
    and the river network reads as broken.
    """
    from scipy.ndimage import label

    deep = (filled - dem) > min_fill_m
    out = np.zeros_like(deep)
    lbl, n = label(deep)
    if n:
        sizes = np.bincount(lbl.ravel())
        big = np.nonzero(sizes >= max(min_cells, 1))[0]
        big = big[big > 0]
        out[np.isin(lbl, big)] = True
    return np.asarray(out, dtype=bool)


def _chaikin(pts: np.ndarray, rounds: int = 2) -> np.ndarray:
    """Chaikin corner-cutting: polylines become smooth curves, endpoints kept."""
    for _ in range(rounds):
        a = pts[:-1]
        b = pts[1:]
        cut = np.empty((2 * (len(pts) - 1), 2), dtype=np.float64)
        cut[0::2] = 0.75 * a + 0.25 * b
        cut[1::2] = 0.25 * a + 0.75 * b
        pts = np.vstack([pts[:1], cut, pts[-1:]])
    return pts


def river_segments(
    rivers: np.ndarray,
    receiver: np.ndarray,
    accumulation: np.ndarray,
    km_per_px: float,
    lake: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Channel polylines for vector rendering, smoothed.

    D8 walks step cell-by-cell in 8 directions; rendered raw they read as
    45°/90° zigzags.  Chains are aggregated from channel heads, collinear
    runs merged, then Chaikin-smoothed (2 rounds) into survey-curve rivers.
    Channels never cross lakes: a chain stops where it enters one (the
    inflow) and resumes at the lake's spill point — the straight crossing
    on the filled surface was the "river cuts through hills" artefact.
    Returns (segments (M, 2, 2) in km, row 0 north, flows (M,) in
    accumulation units) for width grading.
    """
    h, w = rivers.shape
    riv_flat = rivers.reshape(-1)
    riv_cells = np.nonzero(riv_flat)[0]
    riv_set = set(riv_cells.tolist())
    lake_flat = (lake.reshape(-1) if lake is not None else np.zeros(h * w, dtype=bool))
    lake_set = {int(c) for c in np.nonzero(lake_flat)[0]}
    # Spill points: lake cells draining into a non-lake cell — the outlet
    # chain resumes just downstream of them.
    spill_next = set()
    for c in lake_set:
        r = int(receiver[c])
        if r >= 0 and r not in lake_set:
            spill_next.add(r)

    # Channel heads: no other channel cell drains into them.
    has_upstream = set()
    for c in riv_cells.tolist():
        r = int(receiver[c])
        if r in riv_set:
            has_upstream.add(r)
    heads = [c for c in riv_cells.tolist() if c not in has_upstream]
    # Downstream resumptions at lake spill points (their receiver leads out).
    heads += [c for c in spill_next if c in riv_set]

    def cell_xy_km(c: int) -> tuple[float, float]:
        y, x = c // w, c % w
        return (x * km_per_px, (h - 1 - y) * km_per_px)

    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    flows: list[float] = []
    visited: set[int] = set()
    for head in heads:
        chain = []
        c = head
        while c in riv_set and c not in visited and c not in lake_set:
            visited.add(c)
            chain.append(c)
            c = int(receiver[c])
        # Always connect the chain's end to its downstream cell — the
        # junction when a tributary meets an already-traced trunk (missing
        # this link left every tributary one segment short: "broken rivers")
        # or the sea/frame outlet.  Lakes stay unconnected (rivers end at
        # the shore).
        if c >= 0 and c not in lake_set and len(chain) >= 1:
            chain.append(c)
        if len(chain) < 3:
            continue
        pts = np.asarray([cell_xy_km(c) for c in chain], dtype=np.float64)
        # Merge collinear runs (the 8-direction walks have long straight bits).
        d = np.diff(pts, axis=0)
        keep = np.ones(len(pts), dtype=bool)
        for i in range(1, len(pts) - 1):
            v0, v1 = d[i - 1], d[i]
            cross = v0[0] * v1[1] - v0[1] * v1[0]
            if abs(cross) < 1e-9:
                keep[i] = False
        pts = pts[keep]
        if len(pts) < 2:
            continue
        # Two points after the merge = one long straight run — a legal
        # channel (dropping <3-point chains erased whole straight rivers
        # and left region-scale gaps).
        smooth = _chaikin(pts) if len(pts) >= 3 else pts
        for a, b in zip(smooth[:-1], smooth[1:], strict=True):
            segs.append(((a[0], a[1]), (b[0], b[1])))
        flows.extend([float(accumulation.reshape(-1)[chain[-1]])] * (len(smooth) - 1))

    return (
        np.asarray(segs, dtype=np.float64).reshape(-1, 2, 2),
        np.asarray(flows, dtype=np.float64),
    )


def erode_region_pack(
    pack_dir: Path,
    *,
    steps: int = 30,
    dt_yr: float = 5e4,
    k_spl: float = 2e-7,
    river_threshold: int = 3000,
) -> dict[str, object]:
    """CLI entry: erode a region pack's DEM, write ``prog-out/``.

    Writes the gaea-out file vocabulary (height PNG plus ``rivers.png``/
    ``sea-water.png`` masks and a float32 metres ``height.meters.npy``) so
    the colorize/carto legs consume it without changes.  Rain weight is
    normalised to mean-land-precipitation-per-cell so the river threshold
    reads in units of upstream cells.
    """
    import json

    from PIL import Image

    from .export import export_elevation_png

    inp = pack_dir / "input"
    meta = json.loads((inp / "meta.json").read_text(encoding="utf-8"))
    dem = np.load(inp / "height.meters.npy").astype(np.float64)
    rain = np.nan_to_num(np.load(inp / "precipitation.mm.npy").astype(np.float64), nan=0.0)
    land = dem > float(meta["sea_level_m"])
    rain_w = rain / rain[land].mean()

    h, acc = spl_erode(dem, land, rain_w, steps=steps, dt_yr=dt_yr, k_spl=k_spl,
                       sea_level_m=float(meta["sea_level_m"]))
    rivers = river_mask(acc, land, river_threshold)


    out = pack_dir / "prog-out"
    out.mkdir(exist_ok=True)
    lo, hi = float(h.min()), float(h.max())
    span = hi - lo or 1.0
    np.save(out / "height.meters.npy", h.astype(np.float32))
    export_elevation_png(h, out / "height.gaea.png", min_m=lo, max_m=hi)
    filled2, _order2, receiver = priority_flood(h, land)
    lakes = lake_mask(filled2, h)
    segs, flows = river_segments(
        rivers, receiver, acc, float(meta["extent_km"]["x"]) / h.shape[0], lake=lakes
    )
    np.save(out / "rivers.line.npy", segs)
    np.save(out / "rivers.flow.npy", flows)
    rivers = rivers & ~lakes
    Image.fromarray((rivers * 255).astype(np.uint8)).save(out / "rivers.png")
    Image.fromarray((lakes * 255).astype(np.uint8)).save(out / "lake.png")
    Image.fromarray(((~land) * 255).astype(np.uint8)).save(out / "sea-water.png")
    # True post-erosion depth (Gaea-mask vocabulary: 0..1 over the span) —
    # without it render legs read zero depth and tint the sea at the
    # shoreline band instead of the ocean ramp.
    sea_depth = np.clip(float(meta["sea_level_m"]) - h, 0.0, None) / span
    Image.fromarray(np.clip(sea_depth * 65535.0, 0, 65535).astype(np.uint16)).save(
        out / "sea-depth.png"
    )
    Image.fromarray(np.clip(acc / max(acc.max(), 1.0) * 65535.0).astype(np.uint16)).save(
        out / "flow-accum.png"
    )
    (out / "meta.json").write_text(
        json.dumps({"height_gaea_png_range_m": [lo, hi], "sea_level_m": meta["sea_level_m"],
                    "steps": steps, "dt_yr": dt_yr, "k_spl": k_spl,
                    "river_threshold": river_threshold},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    return {
        "steps": steps,
        "river_cells": int(rivers.sum()),
        "river_pct_of_land": round(float(rivers.sum() / land.sum() * 100), 2),
        "height_range_m": [round(lo, 1), round(hi, 1)],
        "sea_pct": round(float((~land).mean()) * 100, 2),
    }
