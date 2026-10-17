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
#: Minimum mapping unit (MMU) for lakes, in ground km²: lakes smaller than
#: this neither render nor interrupt the channel network — the channel
#: draws straight across (the same invisibility argument as
#: LAKE_MIN_CELLS, one notch up at sheet scale).  Sheet anchor: a 550 km
#: window on the 12 in figure gives 1 mm ≈ 1.8 km, so 1 mm² ≈ 3.3 km²;
#: the value below is 256 cells × (550 km / 4096 px)² exactly — 256 cells
#: (≈ 4.6 km², ~2.1 km across) on the refined 4096 grid (0.134 km/px),
#: 64 cells on the pack grid; other resolutions convert via
#: lake_mmu_cells(km_per_px).  The same
#: threshold classifies inland h≤0 water bodies (heal_inland_water):
#: smaller = TD quantisation noise healed to land so rivers continue,
#: larger = endorheic terminal lake where rivers legitimately end.
LAKE_MMU_KM2 = 4.616
#: Minimum extent (bounding-box side, km) for a lake to render and to break
#: the channel network: a lake thinner than ~1.6x the widest river symbol
#: (0.49 mm ≈ 0.9 km on the 550 km sheet) cannot visually "receive" the
#: rivers that feed it — a thick river line ending in a sliver of pixels
#: reads as a break, whatever the sliver's area (2026-10-16 user ruling:
#: align the render scales of rivers and lakes).  Narrower closed basins
#: are river valleys: healed to land, the channel keeps flowing.
LAKE_MIN_WIDTH_KM = 1.5
#: Below-sea-level inland depressions within this causeway width of the
#: ocean merge back into it (stay water, render sea, rivers ending there
#: reach the sea): a depression behind a bar a couple of kilometres wide is
#: the ocean in all but name — storm overwash keeps such bars breached, and
#: on nacrea the tidal range (±18–57 m quiescent) overtops them outright.
#: Wider causeways keep genuine endorheic lagoons terminal.
OCEAN_MERGE_CAUSEWAY_KM = 3.0


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
    field = sum((0.5**o) * rng.noise2array(xs * (2.0**o), xs * (2.0**o)) for o in range(3))
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

    return _priority_flood_numba(
        np.ascontiguousarray(dem, dtype=np.float64),
        np.ascontiguousarray(land, dtype=np.uint8),
        eps,
        breach,
    )


def flow_accumulation(order: np.ndarray, receiver: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Upstream sum of ``weight`` along receivers (downstream-first order)."""
    from ._erosion_kernels import _accumulate_numba

    return _accumulate_numba(
        np.ascontiguousarray(order, dtype=np.int64),
        np.ascontiguousarray(receiver, dtype=np.int64),
        np.ascontiguousarray(weight, dtype=np.float64),
    )


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
        _spl_step_numba(
            h, land8, order, receiver, acc, dt_yr, k_spl, SPL_M, uplift_m_yr, sea_level_m
        )
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
    h: np.ndarray,
    land8: np.ndarray,
    eps: float,
    filled: np.ndarray,
    order: np.ndarray,
    receiver: np.ndarray,
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


def lake_mmu_cells(km_per_px: float) -> int:
    """Lake MMU (LAKE_MMU_KM2) converted to grid cells at this pixel size."""
    return max(1, int(round(LAKE_MMU_KM2 / (km_per_px * km_per_px))))


def keep_large_lakes(
    lake: np.ndarray,
    min_cells: int,
    min_width_km: float = 0.0,
    km_per_px: float = 1.0,
) -> np.ndarray:
    """Lake mask reduced to components that pass BOTH gates — at least
    ``min_cells`` cells (the MMU) and, when ``min_width_km`` > 0, a minimum
    bounding-box extent of that many kilometres.  This is the rendered /
    chain-breaking set: a lake the channel network may visibly terminate in
    must be able to visually "receive" the river — a sliver narrower than
    ~1.6x the widest river symbol cannot (LAKE_MIN_WIDTH_KM), whatever its
    area.  Failing lakes stay internal: channels cross them and the sheet
    never shows them."""
    from scipy.ndimage import find_objects, label

    out = np.zeros_like(lake, dtype=bool)
    lbl, n = label(lake)
    if n:
        sizes = np.bincount(lbl.ravel())
        big = np.nonzero(sizes >= max(min_cells, 1))[0]
        big = big[big > 0]
        if min_width_km > 0.0:
            slices = find_objects(lbl)
            min_px = min_width_km / max(km_per_px, 1e-9)
            big_list = [
                int(i)
                for i in big
                if min(
                    slices[i - 1][0].stop - slices[i - 1][0].start,
                    slices[i - 1][1].stop - slices[i - 1][1].start,
                )
                >= min_px
            ]
        else:
            big_list = [int(i) for i in big]
        if big_list:
            out[np.isin(lbl, big_list)] = True
    return out


def heal_inland_water(
    h: np.ndarray,
    land: np.ndarray,
    min_cells: int,
    sea_level_m: float = 0.0,
    km_per_px: float = 1.0,
    min_width_km: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Classify non-land water: the ocean is the component touching the
    frame edge; every other water body is inland water.

    TD-generated DEMs scatter 1–6-cell bodies at or just below sea level
    (quantisation noise — 858 bodies over 72 km² on the 25N-100W window,
    2026-10-16).  Priority-Flood seeds *every* non-land cell as an outlet,
    so rivers terminated in these invisible pits — including the window's
    two largest trunks — reading on the sheet as "rivers vanish in the
    plain".  Three classes come back:

    - **healed to land** (returned via the new ``h``/``land``): bodies below
      ``min_cells`` (the MMU), frame-edge specks below it as well (same
      noise on the window border), and — when ``min_width_km`` > 0 —
      slivers of any area narrower than that width (a below-sea trench
      that thin is a river valley, not a water body).  Healed cells sit at
      ``sea_level_m`` and the drainage walk continues through them.
    - **``inland_big``**: genuine below-sea-level depressions of MMU area
      and width — endorheic terminal lakes (Dead Sea style), rendered as
      lakes — minus those within ``OCEAN_MERGE_CAUSEWAY_KM`` of the ocean,
      which merge back into it: a below-sea lagoon behind a bar a couple of
      kilometres wide is the sea in all but name (storm overwash; on nacrea
      the tidal range overtops such bars outright), and a river ending
      there reaches the sea, not a puddle.

    Returns ``(h, land, inland_big)`` with the noise healed.
    """
    from scipy.ndimage import distance_transform_edt, find_objects, label

    water_lbl, n = label(~land)
    inland_big = np.zeros_like(land, dtype=bool)
    small = np.zeros_like(land, dtype=bool)
    if n:
        edge = (
            set(water_lbl[0, :])
            | set(water_lbl[-1, :])
            | set(water_lbl[:, 0])
            | set(water_lbl[:, -1])
        )
        edge.discard(0)
        sizes = np.bincount(water_lbl.ravel())
        slices = find_objects(water_lbl)
        min_px = min_width_km / max(km_per_px, 1e-9) if min_width_km > 0 else 0.0
        for i in range(1, n + 1):
            body = water_lbl == i
            on_edge = i in edge
            # The width gate applies to inland bodies only — a narrow bay
            # arm or strait touching the frame edge is the ocean, however
            # thin; a narrow inland sliver is a river valley, not a lake.
            narrow = (
                not on_edge
                and min_px > 0
                and slices[i - 1] is not None
                and min(
                    slices[i - 1][0].stop - slices[i - 1][0].start,
                    slices[i - 1][1].stop - slices[i - 1][1].start,
                )
                < min_px
            )
            if sizes[i] < min_cells or narrow:
                # Sub-MMU anywhere (border specks included) and inland
                # slivers of any area: noise / river valleys, not water.
                small |= body
            elif not on_edge:
                inland_big |= body
        # Near-ocean below-sea bodies merge back into the ocean: drop them
        # from inland_big (they stay non-land, so every downstream mask and
        # the chain walk treat them as sea).
        if inland_big.any():
            ocean = ~land & ~inland_big & ~small
            dist_ocean = distance_transform_edt(~ocean, sampling=(km_per_px, km_per_px))
            for i in range(1, n + 1):
                body = water_lbl == i
                if (inland_big & body).any() and dist_ocean[body].min() <= OCEAN_MERGE_CAUSEWAY_KM:
                    inland_big &= ~body
    h2 = np.where(small, sea_level_m, h)
    return h2, land | small, inland_big


def _chaikin(pts: np.ndarray, rounds: int = 2) -> np.ndarray:
    """Chaikin corner-cutting: polylines become smooth curves, endpoints kept.

    Works on (N, K) points — extra columns beyond xy (e.g. per-cell flow)
    ride along and interpolate linearly through the cut."""
    for _ in range(rounds):
        a = pts[:-1]
        b = pts[1:]
        cut = np.empty((2 * (len(pts) - 1), pts.shape[1]), dtype=np.float64)
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

    D8 walks step cell-by-step in 8 directions; rendered raw they read as
    45°/90° zigzags.  Chains are aggregated from channel heads, collinear
    runs merged, then Chaikin-smoothed (2 rounds) into survey-curve rivers.

    Lake semantics are MMU-gated: the mask is first reduced to components
    of at least ``lake_mmu_cells(km_per_px)`` (LAKE_MMU_KM2).  Channels
    cross smaller lakes — invisible at sheet scale; they stop only at MMU
    lakes, ending one cell *into* the water (the line visibly touches the
    shore; stopping one cell short read as a gap at render scale) and
    resume at the lake's spill point — the straight crossing on the filled
    surface was the "river cuts through hills" artefact.  Short chains are
    kept: a legitimate final reach to the sea/lake/frame can be two cells
    long, and dropping it erased whole trunks (their cells were already
    marked visited, so nothing ever redrew them).

    Returns (segments (M, 2, 2) in km, row 0 north, flows (M,) per segment
    in accumulation units — the mean of the interpolated end flows, so the
    width grading grows downstream within a chain instead of jumping at
    confluences).
    """
    h, w = rivers.shape
    riv_flat = rivers.reshape(-1)
    riv_cells = np.nonzero(riv_flat)[0]
    riv_set = set(riv_cells.tolist())
    if lake is not None:
        lake_big = keep_large_lakes(lake, lake_mmu_cells(km_per_px), LAKE_MIN_WIDTH_KM, km_per_px)
    else:
        lake_big = np.zeros(h * w, dtype=bool)
    lake_flat = lake_big.reshape(-1)
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

    acc_flat = accumulation.reshape(-1)

    def cell_xyz_km(c: int) -> tuple[float, float, float]:
        y, x = c // w, c % w
        return (x * km_per_px, (h - 1 - y) * km_per_px, float(acc_flat[c]))

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
        # Always connect the chain's end to its downstream cell: the
        # junction when a tributary meets an already-traced trunk (missing
        # this link left every tributary one segment short: "broken
        # rivers"), the sea/frame outlet, or the shore cell of the lake it
        # ends in (drawn one cell into the water so the line touches it).
        if c >= 0 and len(chain) >= 1:
            chain.append(c)
        # Two cells = a legal short reach (e.g. a trunk's final step into
        # the sea); only a genuinely empty chain is dropped.
        if len(chain) < 2:
            continue
        pts = np.asarray([cell_xyz_km(c) for c in chain], dtype=np.float64)
        # The appended outlet can be a sea cell (accumulation ≈ 0) or a
        # lake shore — its flow coordinate must not sag at the mouth, or
        # the final reach renders thinner than the channel above it.
        np.maximum.accumulate(pts[:, 2], out=pts[:, 2])
        # Merge collinear runs (the 8-direction walks have long straight bits).
        d = np.diff(pts[:, :2], axis=0)
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
            flows.append(float(0.5 * (a[2] + b[2])))

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
    km_pp = float(meta["extent_km"]["x"]) / dem.shape[0]
    # Sub-MMU inland water bodies (h≤0, not connected to the ocean) are
    # quantisation noise: heal to land so rivers continue through; larger
    # ones stay water as endorheic terminal lakes.
    dem, land, inland_big = heal_inland_water(
        dem,
        land,
        lake_mmu_cells(km_pp),
        float(meta["sea_level_m"]),
        km_per_px=km_pp,
        min_width_km=LAKE_MIN_WIDTH_KM,
    )
    rain_w = rain / rain[land].mean()

    h, acc = spl_erode(
        dem,
        land,
        rain_w,
        steps=steps,
        dt_yr=dt_yr,
        k_spl=k_spl,
        sea_level_m=float(meta["sea_level_m"]),
    )
    rivers = river_mask(acc, land, river_threshold)

    out = pack_dir / "prog-out"
    out.mkdir(exist_ok=True)
    lo, hi = float(h.min()), float(h.max())
    span = hi - lo or 1.0
    np.save(out / "height.meters.npy", h.astype(np.float32))
    export_elevation_png(h, out / "height.gaea.png", min_m=lo, max_m=hi)
    filled2, _order2, receiver = priority_flood(h, land)
    lakes = lake_mask(filled2, h)
    mmu = lake_mmu_cells(km_pp)
    lakes_draw = keep_large_lakes(lakes, mmu, LAKE_MIN_WIDTH_KM, km_pp) | inland_big
    segs, flows = river_segments(rivers, receiver, acc, km_pp, lake=lakes_draw)
    np.save(out / "rivers.line.npy", segs)
    np.save(out / "rivers.flow.npy", flows)
    rivers = rivers & ~lakes_draw
    Image.fromarray((rivers * 255).astype(np.uint8)).save(out / "rivers.png")
    Image.fromarray((lakes_draw * 255).astype(np.uint8)).save(out / "lake.png")
    Image.fromarray(((~land & ~inland_big) * 255).astype(np.uint8)).save(out / "sea-water.png")
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
        json.dumps(
            {
                "height_gaea_png_range_m": [lo, hi],
                "sea_level_m": meta["sea_level_m"],
                "steps": steps,
                "dt_yr": dt_yr,
                "k_spl": k_spl,
                "river_threshold": river_threshold,
                "lake_mmu_cells": mmu,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "steps": steps,
        "river_cells": int(rivers.sum()),
        "river_pct_of_land": round(float(rivers.sum() / land.sum() * 100), 2),
        "height_range_m": [round(lo, 1), round(hi, 1)],
        "sea_pct": round(float((~land).mean()) * 100, 2),
    }
