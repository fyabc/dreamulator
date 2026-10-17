"""prog_erosion — programmatic SPL erosion on a region-pack DEM.

Replaces the manual Gaea leg with a seeded, scriptable one: Priority-Flood
drainage (Barnes et al. 2014) + implicit stream-power erosion (Braun &
Willett 2013) on the regular pack grid.  Two water-weighting doctrines on
purpose: the erosion physics runs on the pack's precipitation field (storm
runoff is the erosion agent, same doctrine as the Gaea chain), while the
channel extraction accumulates the pack's annual runoff field (the
Turc–Pike water balance) so channels start where the water balance
allows and endorheic lakes can be terminal.

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
#: Open-water evaporation factor on Hamon PET in the terminal-lake balance
#: (terminal_lakes).  Deep-lake annual evaporation lands at roughly
#: 0.9–1.3 × a reference ET surface; 1.0 keeps the verdict conservative
#: exactly in the arid belt where it must not misfire — a lake stays
#: terminal only if it truly cannot fill and spill.
LAKE_EVAPORATION_FACTOR = 1.0
#: Reference land runoff anchoring the channel-onset threshold, mm/yr:
#: Earth's land-surface mean annual runoff ≈ 300 mm/yr (global land P
#: ≈ 800 mm/yr, R ≈ 306 — the literature value).  The runoff weight is
#: normalised by this FIXED reference, not the window's land mean, so the
#: river threshold reads as an absolute minimum mean discharge in every
#: window: a hyperarid window must not re-denominate its few trickles
#: into rivers (at its own R̄ ≈ 20 mm/yr the threshold would fall to
#: ~0.1 m³/s and wadis would sprawl — the 2026-10-17 desert-window lesson).
RUNOFF_REFERENCE_MM = 300.0
#: Channel-onset threshold, in reference-runoff-cell units on the PACK grid
#: (refine scales it by factor² for the finer raster).  Three layers of
#: rationale.  The ×factor² scaling keeps a window's network
#: resolution-invariant: the threshold counts cells, and cells per unit
#: area grow as res².  The 3000 base was calibrated 2026-10 against
#: Natural Earth-style sheet density — "the smallest permanently drawn
#: river".  With the runoff weight normalised by RUNOFF_REFERENCE_MM it
#: reads physically as a fixed minimum mean annual discharge
#: Q ≈ thr × R₀ × cell_area ≈ 2.1 m³/s at the 2048/550 km pack grid —
#: the headwater scale of the finest (0.09 mm) river symbol; denser
#: headwaters mean lowering it (halve it ≈ 1 m³/s).
RIVER_THRESHOLD_CELLS = 3000


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


def hydrology_weight(input_dir: Path, res: int, land: np.ndarray) -> tuple[np.ndarray, float, str]:
    """Extraction accumulation weight on the ``res``×``res`` grid + its normaliser.

    Source chain, first that works: ``runoff.mm.npy`` (the pack's annual
    Turc–Pike runoff — channels start where the water balance allows, arid
    interiors stop generating headwaters), then ``precipitation.mm.npy``
    (legacy packs; a printed notice, never a silent behaviour change), then
    a uniform land weight.  The chosen grid is NaN-scrubbed and
    ``np.kron``-upsampled by ``res // grid.shape[0]``.  The normaliser is
    ``RUNOFF_REFERENCE_MM`` for the runoff source — a FIXED reference, so
    the river threshold reads as an absolute minimum discharge in every
    window (a window's own land mean would re-denominate the threshold in
    dry country: at R̄ ≈ 20 mm/yr the 3000-cell onset falls to ~0.1 m³/s
    and wadis sprawl); the legacy precipitation fallback keeps its
    land-mean convention.  Returns ``(weight, normaliser_mm, source)``;
    ``normaliser_mm`` is the divisor in mm/yr (0.0 for the uniform
    fallback) and is shared with the terminal-lake water balance.
    """
    from pathlib import Path

    input_dir = Path(input_dir)
    candidates: list[tuple[str, Path]] = [
        ("runoff", input_dir / "runoff.mm.npy"),
        ("precipitation", input_dir / "precipitation.mm.npy"),
    ]
    if not candidates[0][1].exists():
        print(f"[hydrology] no runoff.mm.npy under {input_dir}; trying precipitation")
    for source, path in candidates:
        if not path.exists():
            continue
        grid = np.nan_to_num(np.load(path).astype(np.float64), nan=0.0)
        factor = res // grid.shape[0]
        if factor > 1:
            grid = np.kron(grid, np.ones((factor, factor)))[:res, :res]
        if source == "runoff":
            print(
                f"[hydrology] weight source runoff "
                f"(land mean {float(grid[land].mean()) if land.any() else 0.0:.1f} mm/yr, "
                f"normaliser = RUNOFF_REFERENCE_MM {RUNOFF_REFERENCE_MM:.0f})"
            )
            return grid / RUNOFF_REFERENCE_MM, RUNOFF_REFERENCE_MM, source
        mean_mm = float(grid[land].mean()) if land.any() else 0.0
        if mean_mm <= 1e-9:
            # Hyperarid window: normalising on a ~zero land mean would
            # explode the weights — degrade down the chain instead.
            print(f"[hydrology] {path.name} land mean ~0 mm; uniform land weight")
            continue
        print(f"[hydrology] weight source {source} (land mean {mean_mm:.1f} mm/yr)")
        return grid / mean_mm, mean_mm, source
    print(f"[hydrology] no usable climate channel under {input_dir}; uniform land weight")
    return np.where(land, 1.0, 0.0), 0.0, "uniform-land"


def _lake_balances(
    lake: np.ndarray,
    receiver: np.ndarray,
    accumulation: np.ndarray,
    precip_mm: np.ndarray,
    temp_c: np.ndarray,
    runoff_land_mean_mm: float,
    evaporation_factor: float,
) -> tuple[np.ndarray, int, np.ndarray, np.ndarray, np.ndarray]:
    """Per-component water-balance terms of a lake mask.

    Returns ``(labels, n, inflow_acc, pet_sum_mm_cells, p_sum_mm_cells)``:
    ``inflow_acc[k]`` is the runoff accumulation entering component k (in
    reference-cell units), the sums are Hamon annual PET and annual
    precipitation over the component's cells (mm·cells).  Entry
    accounting: any cell OUTSIDE the component whose receiver is inside it
    delivers its whole upstream accumulation — a land shore cell, and the
    SPILL CELL OF AN UPSTREAM LAKE alike (a pass-through lake chain
    delivers its water via its spill cell; counting only land donors
    starved chained basins and dried them falsely — a 164 m³/s trunk once
    "ended" at an invisible playa this way, 2026-10-17).  Distinct donor
    cells have disjoint upstream sets in the drainage tree, so one
    vectorised pass sums each component's inflow exactly once.
    """
    from scipy.ndimage import label

    from dreamulator.engine.climate_physics import potential_evapotranspiration_hamon

    lbl, n = label(lake)
    lake_flat = lbl.reshape(-1)
    lake_mask_flat = lake.reshape(-1)
    acc_flat = accumulation.reshape(-1)
    rec_flat = receiver.reshape(-1)
    r_all = np.where(rec_flat >= 0, rec_flat, 0)
    enters = (rec_flat >= 0) & (lake_flat[r_all] > 0) & (lake_flat[r_all] != lake_flat)
    cand = np.nonzero(enters)[0]
    inflow = np.bincount(lake_flat[r_all[cand]], weights=acc_flat[cand], minlength=n + 1)

    lake_idx = np.nonzero(lake_mask_flat)[0]
    t_lake = np.where(np.isnan(temp_c.reshape(-1)[lake_idx]), 0.0, temp_c.reshape(-1)[lake_idx])
    t12 = np.repeat(t_lake.reshape(-1, 1), 12, axis=1)
    pet_lake = np.asarray(potential_evapotranspiration_hamon(t12, 365.25 / 12))
    p_cells = precip_mm.reshape(-1)[lake_idx]
    p_lake = np.where(np.isnan(p_cells), 0.0, p_cells)
    pet_sum = np.bincount(lake_flat[lake_idx], weights=pet_lake, minlength=n + 1)
    p_sum = np.bincount(lake_flat[lake_idx], weights=p_lake, minlength=n + 1)
    return lbl, n, inflow, pet_sum, p_sum


def terminal_lakes(
    lake: np.ndarray,
    receiver: np.ndarray,
    accumulation: np.ndarray,
    *,
    land: np.ndarray,
    precip_mm: np.ndarray,
    temp_c: np.ndarray,
    runoff_land_mean_mm: float,
    evaporation_factor: float = LAKE_EVAPORATION_FACTOR,
) -> np.ndarray:
    """Lakes whose water balance never overflows — terminal drains.

    A drawn lake is **terminal** (it cannot fill to its spill level) when
    the evaporation demand over its area exceeds what the rivers and the
    sky deliver::

        Σ_in acc × R̄  <  f·Σ_lake PET − Σ_lake P

    Both sides are mm·cells: the weight is land-mean-normalised runoff, so
    ``acc`` reads in average land cells and ``R̄`` (``runoff_land_mean_mm``)
    restores mm/yr, while the demand side is mm/yr summed over lake cells —
    the cell area appears on both sides and cancels; no km constant enters.
    PET is Hamon on the annual-mean temperature (the documented annual
    approximation, same as the headwaters mask; by convexity of the Magnus
    ``e_s`` it slightly *underestimates`` the monthly-mean demand, biasing
    the verdict toward pass-through — the conservative direction).
    Components touching the frame edge are forced pass-through: their
    catchment is truncated by the window, so resumption is the safer
    reading.  A degenerate normaliser (uniform fallback weight, R̄ ≤ 0)
    disables the balance: every lake passes through.
    """
    out = np.zeros_like(lake, dtype=bool)
    if runoff_land_mean_mm <= 0.0:
        return out
    lbl, n, inflow, pet_sum, p_sum = _lake_balances(
        lake,
        receiver,
        accumulation,
        precip_mm,
        temp_c,
        runoff_land_mean_mm,
        evaporation_factor,
    )
    if not n:
        return out
    edge_lbl = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
    edge_lbl.discard(0)

    for i in range(1, n + 1):
        if i in edge_lbl:
            continue
        demand = evaporation_factor * pet_sum[i] - p_sum[i]
        if demand <= 0.0:
            continue
        if inflow[i] * runoff_land_mean_mm < demand:
            out[lbl == i] = True
    return out


def _equilibrium_water(
    h: np.ndarray,
    land: np.ndarray,
    lake_terminal: np.ndarray,
    inflow_cells: np.ndarray,
    demand_cells: np.ndarray,
    *,
    mmu_cells: int,
    sea_level_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, int]]:
    """Rewrite terminal lakes to their equilibrium water surface.

    Takes per-label inflow and net-demand in reference-cell units (the
    caller's cascade verdict).  A terminal lake cannot fill to its spill
    level; it settles where the annual balance closes, at area
    ``A* = inflow / demand_per_cell`` cells.  The water surface becomes
    the ``ceil(A*)`` deepest cells of the depression (by DEM); the exposed
    floor becomes land (below-sea floors raised to ``sea_level_m``, the
    heal convention).  ``A*`` below the render MMU cannot hold a visible
    surface — a dry playa — but its deepest cell stays a 1-cell non-land
    sink: sub-MMU water is invisible in every render mask, yet the river
    network and the accumulation must END at the playa (rivers to Lake
    Eyre's bed do not walk across it to the sea).  The returned water is
    marked NON-LAND (the ``inland_big`` mechanism) for the render masks.

    Returns ``(h, land, water, stats)``.
    """
    import math

    from scipy.ndimage import label

    out_h = h.copy()
    out_land = land.copy()
    water = np.zeros_like(land, dtype=bool)
    stats = {"terminal": 0, "dry_playas": 0, "shrunk": 0}
    lbl, n = label(lake_terminal)
    if not n:
        return out_h, out_land, water, stats
    sizes = np.bincount(lbl.ravel(), minlength=n + 1)
    for i in range(1, n + 1):
        stats["terminal"] += 1
        ys, xs = np.nonzero(lbl == i)
        n_cells = int(sizes[i])
        demand = demand_cells[i]
        if demand <= 0.0:
            continue  # balance-positive: keep as drawn (verdict disagreed — skip)
        a_star = inflow_cells[i] / demand * n_cells
        k = min(int(math.ceil(a_star)), n_cells)
        if k < mmu_cells:
            k = 1  # dry playa: the deepest cell remains the sink
            stats["dry_playas"] += 1
        else:
            stats["shrunk"] += 1
        deepest = np.argsort(h[ys, xs])[:k]
        wy, wx = ys[deepest], xs[deepest]
        water[wy, wx] = True
        out_land[wy, wx] = False
        rest = np.ones(n_cells, dtype=bool)
        rest[deepest] = False
        ry, rx = ys[rest], xs[rest]
        out_land[ry, rx] = True
        out_h[ry, rx] = np.maximum(out_h[ry, rx], sea_level_m)
    return out_h, out_land, water, stats


def apply_terminal_equilibrium(
    h: np.ndarray,
    land: np.ndarray,
    lake_terminal: np.ndarray,
    receiver: np.ndarray,
    accumulation: np.ndarray,
    *,
    precip_mm: np.ndarray,
    temp_c: np.ndarray,
    runoff_land_mean_mm: float,
    mmu_cells: int,
    sea_level_m: float,
    evaporation_factor: float = LAKE_EVAPORATION_FACTOR,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, int]]:
    """Rewrite terminal lakes from a single (receiver, accumulation) pair.

    Convenience wrapper around :func:`_equilibrium_water` computing the
    per-label balances in place (``_lake_balances``); the routing helper
    uses the cascaded verdicts instead — lake-to-lake re-entry makes a
    single-pair accounting overcount (the dendritic-arm lesson).
    """

    lbl, n, inflow, pet_sum, p_sum = _lake_balances(
        lake_terminal,
        receiver,
        accumulation,
        precip_mm,
        temp_c,
        runoff_land_mean_mm,
        evaporation_factor,
    )
    demand = (evaporation_factor * pet_sum - p_sum) / runoff_land_mean_mm
    return _equilibrium_water(
        h,
        land,
        lake_terminal,
        inflow,
        demand,
        mmu_cells=mmu_cells,
        sea_level_m=sea_level_m,
    )


def terminal_equilibrium_routing(
    h: np.ndarray,
    land: np.ndarray,
    lakes_draw: np.ndarray,
    order: np.ndarray,
    receiver: np.ndarray,
    weight: np.ndarray,
    *,
    precip_mm: np.ndarray,
    temp_c: np.ndarray,
    runoff_land_mean_mm: float,
    mmu_cells: int,
    km_per_px: float,
    sea_level_m: float,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    dict[str, int],
]:
    """Terminal-lake equilibrium with an exact lake-graph cascade.

    A lake's water balance is NOT readable from a single accumulation
    pass: dendritic lakes re-enter themselves (water leaves one arm,
    crosses land, comes back through another), so every shore touch would
    add the same flood again — the 2026-10-17 21.5N/95.5E sheet measured
    a lake "receiving" 2.5x the window's total water this way, and the
    falsely-pass-through verdicts let a desert trunk punch out of an
    endorheic district.  The exact accounting is a cascade on the lake
    graph (the receiver forest contracted over lake components — a DAG):

    1. **First-touch inflow**: with EVERY lake cut into a sink, each land
       cell's water is credited exactly once, to the first lake its path
       reaches (or to the sea/frame).
    2. **Cascade** in topological order:
       ``total(L) = external(L) + Σ outflow(A)`` over lakes A draining
       into L; ``demand(L) = (f·PET − P)·cells``; overflow keeps
       ``outflow(L) = total(L) − demand(L)``, deficit makes L terminal
       with equilibrium area ``A* = external-equivalent inflow / demand
       per cell``.
    3. Pass-through lakes deduct their demand from the through-flow as a
       negative point weight on their exit cells (Landlab's documented
       transmission-loss mechanism), so river widths and downstream
       onsets see the depleted water.

    Routing stays on the PRE-rewrite drainage tree throughout (terminal
    footprints cut into sinks); re-routing on a rewritten field is
    unstable — a dried basin's sink captures big rivers that never fed it
    pre-verdict.

    Returns ``(h, land, lakes_render, chain_stop, fringe_desc, rec_route,
    acc, term_water, stats)``: the rewritten field and render mask, the
    chain-stopping mask (render water plus dry-playa footprints), the
    in-footprint descent tree for chain extraction across shrunk fringes
    (see ``lake_fringe_descend``), receivers with terminal sinks cut, the
    final (depleted, cut) accumulation, the equilibrium water mask (kept
    surfaces plus playa sinks — exclude it from the sea masks), and the
    component counts.
    """

    stats = {"terminal": 0, "dry_playas": 0, "shrunk": 0}
    empty = np.zeros_like(lakes_draw, dtype=bool)
    empty_desc = np.full(h.size, -1, dtype=np.int64)
    if runoff_land_mean_mm <= 0.0:
        acc = flow_accumulation(order, receiver, weight)
        return h, land, lakes_draw, lakes_draw, empty_desc, receiver, acc, empty, stats

    lbl, n, _i, _ps, _pp = _lake_balances(
        lakes_draw,
        receiver,
        flow_accumulation(order, receiver, weight),
        precip_mm,
        temp_c,
        runoff_land_mean_mm,
        LAKE_EVAPORATION_FACTOR,
    )
    if not n:
        acc = flow_accumulation(order, receiver, weight)
        return h, land, lakes_draw, lakes_draw, empty_desc, receiver, acc, empty, stats
    lake_flat = lbl.reshape(-1)
    rec_flat = receiver.reshape(-1)

    # 1) first-touch inflow: all lakes as sinks.
    rec_all = receiver.copy()
    rec_all[np.nonzero(lakes_draw.reshape(-1))[0]] = -1
    acc_all = flow_accumulation(order, rec_all, weight)
    r_all = np.where(rec_all >= 0, rec_all, 0)
    enters = (rec_all >= 0) & (lake_flat[r_all] > 0)
    donors = np.nonzero(enters)[0]
    external = np.bincount(
        lake_flat[r_all[donors]], weights=acc_all.reshape(-1)[donors], minlength=n + 1
    )

    # 2) lake-graph edges: each component's exits, walked to the next
    #    lake / the sea / the frame sink along the receiver forest.
    r_orig = np.where(rec_flat >= 0, rec_flat, 0)
    is_exit = (rec_flat >= 0) & (lake_flat[r_orig] != lake_flat) & (lake_flat > 0)
    exits = np.nonzero(is_exit)[0]
    downstream_of = np.zeros(n + 1, dtype=np.int64)  # 0 = sea/frame
    for e in exits:
        src_lbl = int(lake_flat[e])
        if downstream_of[src_lbl] == 0:
            t = int(rec_flat[e])
            while t >= 0 and lake_flat[t] == 0:
                t = int(rec_flat[t])
            tgt = int(lake_flat[t]) if t >= 0 else 0
            if tgt != src_lbl:  # self re-entry (dendritic arm) is internal
                downstream_of[src_lbl] = tgt
    # Kahn topological order over the (forest-contracted, hence acyclic) graph.
    indeg = np.zeros(n + 1, dtype=np.int64)
    for a in range(1, n + 1):
        b = int(downstream_of[a])
        if b > 0:
            indeg[b] += 1
    from collections import deque

    dq = deque(a for a in range(1, n + 1) if indeg[a] == 0)
    topo = []
    while dq:
        a = dq.popleft()
        topo.append(a)
        b = int(downstream_of[a])
        if b > 0:
            indeg[b] -= 1
            if indeg[b] == 0:
                dq.append(b)

    _l2, _n2, _in2, pet_sum, p_sum = _lake_balances(
        lakes_draw,
        receiver,
        acc_all,
        precip_mm,
        temp_c,
        runoff_land_mean_mm,
        LAKE_EVAPORATION_FACTOR,
    )
    demand = (LAKE_EVAPORATION_FACTOR * pet_sum - p_sum) / runoff_land_mean_mm
    total = external.copy()
    is_term = (demand > 0.0) & (total < demand)
    for a in topo:  # predecessors first: total[a] is final when popped
        if is_term[a]:
            continue  # terminal lakes hand nothing on
        b = int(downstream_of[a])
        if b > 0:
            total[b] += total[a] - demand[a]  # outflow (demand<0 adds net water)
    lake_term = np.isin(lbl, np.nonzero(is_term)[0])

    # 3) rewrite the terminal footprints; depletion at pass-through exits.
    h_rw, land_rw, term_water, stats = _equilibrium_water(
        h,
        land,
        lake_term,
        total,
        demand,
        mmu_cells=mmu_cells,
        sea_level_m=sea_level_m,
    )
    water_kept = keep_large_lakes(term_water, mmu_cells, LAKE_MIN_WIDTH_KM, km_per_px)
    lakes_render = (lakes_draw & ~lake_term) | water_kept
    chain_stop = lakes_render | lake_term
    # Descent across dried fringes toward the kept water, on the field as
    # it was BEFORE the rewrite (flattened playa floors erased the slope).
    fringe_desc = lake_fringe_descend(h, chain_stop, lakes_render)
    rec_route = receiver.copy()
    rec_route[lake_term.reshape(-1)] = -1
    weight_depl = weight.copy()
    for a in topo:
        if is_term[a] or demand[a] == 0.0:
            continue
        # Pass-through: deduct the net demand at the component's exits,
        # split evenly (the accumulation carries inflow through the lake
        # interior to these cells; a negative demand adds the lake's own
        # water surplus).
        ex = exits[lake_flat[exits] == a]
        if ex.size:
            weight_depl.reshape(-1)[ex] -= demand[a] / ex.size
    acc = flow_accumulation(order, rec_route, weight_depl)
    return h_rw, land_rw, lakes_render, chain_stop, fringe_desc, rec_route, acc, term_water, stats


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


def lake_fringe_descend(h: np.ndarray, footprint: np.ndarray, water: np.ndarray) -> np.ndarray:
    """Flat-index descent tree inside terminal footprints, toward the water.

    Chain extraction stops where a channel meets a terminal footprint, but
    a shrunk lake's visible surface can sit kilometres inside its
    pre-verdict basin (the dried fringe is exposed lake bed) — stopping at
    the outer edge reads as a broken river on the sheet.  Inside
    water-bearing footprints this array gives each cell's descent
    neighbour on the PRE-rewrite surface, resolved lowest-first: a cell
    points at the lowest already-resolved neighbour (water counts as
    resolved).  Processing in height order makes the tree acyclic by
    construction AND able to cross the near-flat rim band a lake floor
    carries at its spill elevation — one-step steepest descent dead-ends
    there (no strictly lower neighbour), which is exactly where channels
    enter the basin.  Water cells self-loop (``descend[c] == c``) so a
    walk stops one cell into the visible surface; dry-playa footprints
    (no visible water) and everything outside footprints get −1, keeping
    the chain at the playa's outer edge — sub-MMU surfaces must stay
    unreached.
    """
    desc = np.full(h.size, -1, dtype=np.int64)
    if not water.any():
        return desc
    from scipy.ndimage import label

    lbl, _n = label(footprint)
    water_lbl = set(int(v) for v in np.unique(lbl[water]) if v > 0)
    if not water_lbl:
        return desc
    hgt, wid = h.shape
    hflat = h.reshape(-1)
    water_flat = water.reshape(-1)
    done = np.zeros(h.size, dtype=bool)  # resolved: water or desc assigned
    for wl in sorted(water_lbl):
        cells = np.nonzero((lbl == wl).reshape(-1) & water_flat)[0]
        desc[cells] = cells
        done[cells] = True
        fringe = np.nonzero((lbl == wl).reshape(-1) & ~water_flat)[0]
        for c in fringe[np.argsort(hflat[fringe], kind="stable")].tolist():
            y, x = divmod(c, wid)
            best, best_key = -1, (np.inf, np.inf, -1)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < hgt and 0 <= nx < wid:
                        nc = ny * wid + nx
                        if done[nc]:
                            key = (hflat[nc], (dy * dy + dx * dx) ** 0.5, nc)
                            if key < best_key:
                                best_key, best = key, nc
            desc[c] = best
            if best >= 0:
                done[c] = True
    return desc


def river_segments(
    rivers: np.ndarray,
    receiver: np.ndarray,
    accumulation: np.ndarray,
    km_per_px: float,
    lake: np.ndarray | None = None,
    lake_descend: np.ndarray | None = None,
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
    surface was the "river cuts through hills" artefact.  Terminal lakes
    (the water-balance verdict of ``terminal_lakes`` /
    ``apply_terminal_equilibrium``) hold non-land equilibrium water, so
    chains end at their shore and nothing resumes downstream — endorheic
    drain semantics by construction.  A shrunk lake's visible surface sits
    inside its pre-verdict basin behind a fringe of dried lake bed: with
    ``lake_descend`` (see ``lake_fringe_descend``) the chain keeps
    descending the pre-rewrite bathymetry across that fringe and stops one
    cell into the visible water, while dry playas (no visible surface)
    still stop at the footprint's outer edge.  Short chains are
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
    # chain resumes just downstream of them.  (Terminal lakes carry no
    # spill cell: their equilibrium water is non-land and receiver-less, so
    # nothing resumes below them by construction.)
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
        # Always connect the chain's end to its downstream cell: the
        # junction when a tributary meets an already-traced trunk (missing
        # this link left every tributary one segment short: "broken
        # rivers"), the sea/frame outlet, or the shore cell of the lake it
        # ends in (drawn one cell into the water so the line touches it).
        if c >= 0 and len(chain) >= 1:
            chain.append(c)
        # Terminal footprint entered: descend the pre-rewrite bathymetry
        # across a shrunk lake's dried fringe to the visible water (the
        # cut receiver ends the walk at the basin's outer edge, which read
        # as a broken river when the water sits kilometres inside).  Dry
        # playas descend nowhere (-1) and keep the outer-edge semantics.
        if lake_descend is not None and chain and chain[-1] in lake_set:
            c = chain[-1]
            while True:
                dn = int(lake_descend[c])
                if dn < 0 or dn == c:
                    break
                chain.append(dn)
                c = dn
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
    river_threshold: int = RIVER_THRESHOLD_CELLS,
) -> dict[str, object]:
    """CLI entry: erode a region pack's DEM, write ``prog-out/``.

    Writes the gaea-out file vocabulary (height PNG plus ``rivers.png``/
    ``sea-water.png`` masks and a float32 metres ``height.meters.npy``) so
    the colorize/carto legs consume it without changes.  Erosion uses the
    precipitation weight; channel extraction uses the runoff weight
    (``hydrology_weight``), land-mean-normalised so the river threshold
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
    # Two water-weighting doctrines on purpose (module docstring): erosion
    # runs on the precipitation weight (storm runoff carves), extraction on
    # the water balance (runoff) so the channel network obeys the climate.
    rain_w = rain / rain[land].mean()
    weight, run_norm_mm, weight_src = hydrology_weight(inp, dem.shape[0], land)

    h, _acc_erosion = spl_erode(
        dem,
        land,
        rain_w,
        steps=steps,
        dt_yr=dt_yr,
        k_spl=k_spl,
        sea_level_m=float(meta["sea_level_m"]),
    )

    out = pack_dir / "prog-out"
    out.mkdir(exist_ok=True)
    filled2, order2, receiver = priority_flood(h, land)
    lakes = lake_mask(filled2, h)
    mmu = lake_mmu_cells(km_pp)
    lakes_draw0 = keep_large_lakes(lakes, mmu, LAKE_MIN_WIDTH_KM, km_pp) | inland_big
    temp_c: np.ndarray | None = None
    t_path = inp / "temperature.C.npy"
    if t_path.exists():
        temp_c = np.nan_to_num(np.load(t_path).astype(np.float64), nan=0.0)
    else:
        print(f"[erode] no temperature.C.npy under {inp}; terminal-lake balance off")
    # Terminal-lake equilibrium with through-flow depletion (the shared
    # helper): pass-through lakes deduct their net evaporation from the
    # through-flow; routing stays on the pre-rewrite tree.
    h, land, lakes_draw, chain_stop, fringe_desc, rec_route, acc, term_water, lake_stats = (
        terminal_equilibrium_routing(
            h,
            land,
            lakes_draw0,
            order2,
            receiver,
            weight,
            precip_mm=rain if temp_c is not None else np.zeros_like(land, dtype=np.float64),
            temp_c=temp_c if temp_c is not None else np.zeros_like(land, dtype=np.float64),
            runoff_land_mean_mm=run_norm_mm
            if (temp_c is not None and weight_src == "runoff")
            else 0.0,
            mmu_cells=mmu,
            km_per_px=km_pp,
            sea_level_m=float(meta["sea_level_m"]),
        )
    )
    lo, hi = float(h.min()), float(h.max())
    span = hi - lo or 1.0
    np.save(out / "height.meters.npy", h.astype(np.float32))
    export_elevation_png(h, out / "height.gaea.png", min_m=lo, max_m=hi)
    rivers = river_mask(acc, land, river_threshold)
    segs, flows = river_segments(
        rivers, rec_route, acc, km_pp, lake=chain_stop, lake_descend=fringe_desc
    )
    np.save(out / "rivers.line.npy", segs)
    np.save(out / "rivers.flow.npy", flows)
    rivers = rivers & ~lakes_draw
    Image.fromarray((rivers * 255).astype(np.uint8)).save(out / "rivers.png")
    Image.fromarray((lakes_draw * 255).astype(np.uint8)).save(out / "lake.png")
    not_sea = term_water  # equilibrium water (kept surfaces + playa sinks)
    Image.fromarray(((~land & ~not_sea & ~lakes_draw) * 255).astype(np.uint8)).save(
        out / "sea-water.png"
    )
    # True post-erosion depth (Gaea-mask vocabulary: 0..1 over the span) —
    # without it render legs read zero depth and tint the sea at the
    # shoreline band instead of the ocean ramp.
    sea_depth = np.clip(float(meta["sea_level_m"]) - h, 0.0, None) / span
    sea_depth[not_sea] = 0.0
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
                "hydrology_weight": weight_src,
                "runoff_normalizer_mm": round(run_norm_mm, 3),
                "terminal_lakes": lake_stats["terminal"],
                "dry_playas": lake_stats["dry_playas"],
                "shrunk_lakes": lake_stats["shrunk"],
                "lake_balance": {
                    "pet": "hamon-annual",
                    "evaporation_factor": LAKE_EVAPORATION_FACTOR,
                },
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
