"""Surface process on a regular grid: incision, threshold hillslopes, sediment, lake infill.

The physics of the canvas erosion-deposition stage (design and calibration in
``docs/design/proposals/canvas-erosion-deposition.md``; knowledge in
``docs/knowledge/geology/hydrology.md``).  Each time step:

1. **Routing.**  Priority-Flood from the outlets (non-land cells and the grid
   frame), D8 receivers on the filled surface, discharge Q = Σ runoff × area.
   Lakes are cells the fill raises more than ``lake_eps_m`` above the ground
   (8-connected).  The terminal-lake verdict is the hydrology water balance
   (``prog_erosion._lake_balances``); a terminal lake's outlet is cut, so its
   water and its base level stay inland.
2. **Incision.**  Implicit stream-power step dh = −K Q^m S dt with n = 1
   (Braun & Willett 2013) on the filled surface; lake cells keep their
   ground.  Cells erode only during their own surface age.
3. **Hillslopes.**  No mutable cell may stand more than tan(S_c) × distance
   above any neighbour (threshold slope, Burbank et al. 1996).
4. **Sediment.**  Removed material becomes sediment at its cell and travels
   downstream; river cells deposit D = λ · Qs / Q (Davy & Lague 2009), never
   above the lowest donor; a lake traps everything that reaches it, filling
   bottom-up towards its spill from the outlet cell, the excess moving on (a
   terminal lake keeps it as an aggrading playa).  Spillways breach by
   themselves: the rim below an outlet carries the whole lake discharge.
5. **Anchoring.**  The long-wavelength mean is the mesh's canon: a Gaussian
   low-pass of the surface (σ ``anchor_sigma_km``) is pulled back to that of
   ``anchor``.  One-sided anchoring only refills the erosional deficit, so
   sediment infill of sub-grid pits is kept; inside ``two_sided_mask`` (basins
   the mesh itself has) the infill surplus is compensated too.  No land cell
   is pushed below its initial sea-level side.

The sediment and topography ledgers close to round-off (both residuals are
returned).  Pure computation: no IO.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import ndimage

from . import _surface_process_kernels as kern
from . import prog_erosion as pe

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class SurfaceProcessParams:
    """Solver constants, with their epistemic class.

    * ``k`` (stream-power erodibility, discharge in m³/yr): observational fit,
      calibrated on the Ethiopian Plateau, held out on SE Tibet and the Yungas
      (relief and valley depth within ±20 %).
    * ``m_exp`` = 0.5 with n = 1: observational fit (Earth concavity 0.4–0.6).
    * ``lambda_m_yr`` (deposition, D = λ Qs/Q): observational fit; one value
      fits all three Earth samples, results move < 15 % between 0.4 and 0.8.
    * ``slope_deg``: observational (active ranges 30–35°).
    * ``max_cells_per_step`` / ``fixed_steps``: numerical stabilisation (the
      implicit step is stable; the cap keeps knickpoints from jumping cells).
    * ``anchor_sigma_km``: the mesh's resolution scale (long-wavelength canon).
    * ``lake_eps_m``: numerical (separates lake water from the ε ramp).
    """

    k: float = 7e-7
    m_exp: float = 0.5
    lambda_m_yr: float = 0.4
    slope_deg: float = 33.0
    max_cells_per_step: float = 5.0
    fixed_steps: int = 0
    anchor_sigma_km: float = 25.0
    one_sided: bool = True
    threshold: bool = True
    lake_eps_m: float = 0.01
    parallel_flood: bool = True


@dataclass
class SurfaceProcessResult:
    """Final surface, routing state on it, and the ledgers (km³)."""

    h: np.ndarray
    steps: int
    ledger: dict[str, float]
    lake: np.ndarray
    terminal: np.ndarray
    discharge_m3_yr: np.ndarray
    snaps: list[tuple[float, np.ndarray]] = field(default_factory=list)


def route(
    h: np.ndarray,
    land: np.ndarray,
    runoff_m3: np.ndarray,
    precip_mm: np.ndarray,
    temp_c: np.ndarray,
    rbar_mm: float,
    area_m2: float,
    params: SurfaceProcessParams,
    open_water_mm: np.ndarray | None = None,
) -> dict[str, Any]:
    """Fill, lakes, terminal verdict (cutting only the terminal lake's outlet) and discharge.

    ``runoff_m3`` must be zero off land.  Returns the filled surface,
    downstream-first ``order``, receivers ``rec``, discharge ``q`` (m³/yr) and
    the lake bookkeeping the sediment kernel needs.
    """
    filled, order, rec = pe.priority_flood(h, land, parallel=params.parallel_flood)
    filled = filled.reshape(h.shape)
    lake = land & (filled - h > params.lake_eps_m)
    weight = runoff_m3.ravel()
    q = pe.flow_accumulation(order, rec, weight).reshape(h.shape)
    lbl, nl = ndimage.label(lake, structure=np.ones((3, 3), bool))
    lf = lbl.ravel()
    outlet = np.zeros(lf.size, bool)
    idx = np.flatnonzero(lf > 0)
    r_ = rec[idx]
    outlet[idx] = (r_ < 0) | (lf[np.where(r_ >= 0, r_, 0)] != lf[idx])
    term_lake = np.zeros(nl, bool)
    if nl and rbar_mm > 0:
        deep = land & (filled - h > 0.5)
        lb2, _n2, inflow, evap_sum, p_sum = pe._lake_balances(
            deep,
            rec.reshape(h.shape),
            q,
            precip_mm,
            temp_c,
            rbar_mm,
            pe.LAKE_EVAPORATION_FACTOR,
            open_water_mm=open_water_mm,
        )
        demand_m3 = (evap_sum - p_sum) * 1e-3 * area_m2
        is_term = (demand_m3 > 0) & (inflow < demand_m3)
        is_term[0] = False
        is_term[np.unique(np.concatenate([lb2[0], lb2[-1], lb2[:, 0], lb2[:, -1]]))] = False
        tcell = is_term[lb2].ravel()
        if tcell.any():
            tl = np.unique(lf[tcell])
            tl = tl[tl > 0]
            term_lake[tl - 1] = True
            cut = outlet & (lf > 0) & term_lake[np.maximum(lf, 1) - 1]
            rec = rec.copy()
            rec[cut] = -1
            q = pe.flow_accumulation(order, rec, weight).reshape(h.shape)
    if nl:
        cells, ptr, level = kern._lake_lists(lf, idx, h.ravel(), filled.ravel(), nl)
        term_cells = np.empty(h.shape, bool)
        kern._terminal_cells(lbl, term_lake, term_cells)
    else:
        cells = np.zeros(0, np.int64)
        ptr = np.zeros(1, np.int64)
        level = np.zeros(0)
        term_cells = np.zeros(h.shape, bool)
    return {
        "filled": filled,
        "order": order,
        "rec": rec,
        "q": q,
        "lake": lake,
        "terminal": term_cells,
        "lbl": lf,
        "ptr": ptr,
        "cells": cells,
        "level": level,
        "outlet": outlet,
        "term_lake": term_lake,
    }


class _LowPass:
    """Masked Gaussian low-pass, evaluated on a grid decimated by about σ/3.

    Block means, a Gaussian of σ/f on the decimated grid, one bilinear
    upsampling of the result.  The same operator acts on the target and on the
    surface, so the anchor holds exactly for that kernel.
    """

    def __init__(self, mask: np.ndarray, sigma_px: float) -> None:
        self.shape = mask.shape
        self.f = max(1, int(sigma_px // 3))
        self.sigma = sigma_px / self.f
        self.mf = mask.astype(np.float64)
        self.norm = np.maximum(ndimage.gaussian_filter(self._dec(self.mf), self.sigma), 1e-9)

    def _dec(self, x: np.ndarray) -> np.ndarray:
        if self.f == 1:
            return x
        return kern._block_mean(np.ascontiguousarray(x, dtype=np.float64), self.f)

    def up(self, c: np.ndarray) -> np.ndarray:
        if self.f == 1:
            return c
        return kern._upsample(np.ascontiguousarray(c), self.f, self.shape[0], self.shape[1])

    def coarse(self, a: np.ndarray) -> np.ndarray:
        return np.asarray(ndimage.gaussian_filter(self._dec(a * self.mf), self.sigma) / self.norm)


def run_surface_process(
    z0: np.ndarray,
    land: np.ndarray,
    runoff_mm: np.ndarray,
    precip_mm: np.ndarray,
    temp_c: np.ndarray,
    px_m: float,
    t_yr: float,
    params: SurfaceProcessParams | None = None,
    *,
    age_yr: np.ndarray | None = None,
    erodible: np.ndarray | None = None,
    anchor: np.ndarray | None = None,
    two_sided_mask: np.ndarray | None = None,
    open_water_mm: np.ndarray | None = None,
    snap_times: tuple[float, ...] = (),
    max_steps: int = 100_000,
    log: Callable[[str], None] | None = None,
) -> SurfaceProcessResult:
    """Evolve ``z0`` for ``t_yr`` years; all grids share ``z0``'s shape.

    ``land`` cells take part (others are outlets at their own height, as is
    the grid frame); ``erodible`` restricts which land cells change;
    ``age_yr`` is each cell's incision time (it erodes only during its last
    ``age_yr`` years); ``anchor`` is the surface whose long-wavelength mean
    is kept; ``open_water_mm`` is the annual lake evaporation (else Hamon).
    """
    p = params or SurfaceProcessParams()
    area = px_m * px_m
    h = np.ascontiguousarray(z0, dtype=np.float64).copy()
    # multiplied in this order (not by ``area``): the discharge is bit-stable across versions
    runoff_m3 = np.where(land, np.nan_to_num(runoff_mm) * 1e-3 * px_m * px_m, 0.0)
    rbar = float(np.nanmean(np.where(land, runoff_mm, np.nan))) if land.any() else 0.0
    pr = np.nan_to_num(precip_mm).astype(np.float64)
    tc = np.nan_to_num(temp_c).astype(np.float64)
    age = np.full(h.shape, t_yr) if age_yr is None else np.minimum(age_yr, t_yr)
    s_m = float(np.tan(np.radians(p.slope_deg)) * px_m)
    frame = np.zeros(h.shape, bool)
    frame[0] = frame[-1] = True
    frame[:, 0] = frame[:, -1] = True
    mutable = land & ~frame if erodible is None else land & ~frame & erodible
    routed = land & ~frame
    lowpass = _LowPass(mutable, p.anchor_sigma_km * 1000.0 / px_m)
    target_c = None if anchor is None else lowpass.coarse(np.asarray(anchor, dtype=np.float64))
    if target_c is not None:
        h += np.where(mutable, lowpass.up(target_c) - lowpass.up(lowpass.coarse(h)), 0.0)
    if p.threshold:
        kern._threshold(h, mutable, s_m)
    vol0 = float(h[land].sum())
    z_floor = np.ascontiguousarray(z0, dtype=np.float64)
    ts_mask = np.ascontiguousarray(two_sided_mask if two_sided_mask is not None else mutable)
    led = dict.fromkeys(
        ("eroded", "dep_river", "dep_lake", "exported", "playa", "uplift", "anchor_withheld"), 0.0
    )
    t, step, t0, u_last = 0.0, 0, time.time(), 0.0
    snaps: list[tuple[float, np.ndarray]] = []
    active = np.empty(h.shape, bool)
    a_km3 = area / 1e9
    while t < t_yr - 1e-6 and step < max_steps:
        r = route(h, land, runoff_m3, pr, tc, rbar, area, p, open_water_mm)
        q = r["q"]
        qmax = float(q[mutable].max()) if mutable.any() else 0.0
        if p.fixed_steps:
            dt = t_yr / p.fixed_steps
        else:
            dt = p.max_cells_per_step * px_m / (p.k * max(qmax, 1e-12) ** p.m_exp)
        dt = min(dt, t_yr - t)
        kern._active_mask(mutable, age, t + dt, t_yr, active)
        hf = r["filled"].astype(np.float64).copy()
        kern._spl(
            hf,
            r["lake"].ravel() | ~mutable.ravel(),
            active.ravel(),
            r["order"],
            r["rec"],
            q.ravel(),
            dt,
            p.k,
            p.m_exp,
            px_m,
        )
        src = np.empty(h.shape)
        kern._apply_incision(h, hf, r["lake"], src)
        if p.threshold:
            removed = np.zeros(h.shape)
            kern._threshold_map(h, mutable & active, s_m, removed)
            src += removed
        led["eroded"] += float(src.sum())
        hflat = h.ravel()  # view: the kernel deposits in place
        min_donor = kern._min_donor(hflat, r["rec"])
        dr, dl, ex, pl = kern._route_sediment(
            hflat,
            r["order"],
            r["rec"],
            q.ravel(),
            src.ravel(),
            r["lbl"],
            r["ptr"],
            r["cells"],
            r["level"],
            r["outlet"],
            r["term_lake"],
            mutable.ravel(),
            routed.ravel(),
            p.lambda_m_yr,
            1.0,
            area,
            min_donor,
        )
        led["dep_river"] += dr
        led["dep_lake"] += dl
        led["exported"] += ex
        led["playa"] += pl
        if target_c is not None:
            u_in = lowpass.up(target_c - lowpass.coarse(h))
            uc = np.empty(h.shape)
            wh = np.empty(h.shape)
            if p.one_sided:
                kern._apply_anchor(
                    h, u_in, mutable, active, ts_mask, two_sided_mask is not None, z_floor, uc, wh
                )
            else:
                kern._apply_anchor_two(h, u_in, mutable, active, z_floor, uc, wh)
            led["anchor_withheld"] += float(wh.sum())
            du = float(uc.sum())
            led["uplift"] += du
            u_last = du / max(int(np.count_nonzero(active)), 1) / dt * 1e3
        t += dt
        step += 1
        if log is not None and (step % 20 == 0 or t >= t_yr - 1e-6):
            log(
                f"step {step} t={t / 1e6:.2f} Myr dt={dt:.0f} yr lakes {int(r['lake'].sum())} "
                f"eroded {led['eroded'] * a_km3:.0f} km3 river {led['dep_river'] * a_km3:.0f} "
                f"lake {led['dep_lake'] * a_km3:.0f} out {led['exported'] * a_km3:.0f} "
                f"uplift {u_last:.3f} mm/yr {time.time() - t0:.0f} s"
            )
        for st in snap_times:
            if t - dt < st <= t:
                snaps.append((st, h.astype(np.float32)))
    r = route(h, land, runoff_m3, pr, tc, rbar, area, p, open_water_mm)
    ledger = {f"{k}_km3": v * a_km3 for k, v in led.items()}
    sed_in = ledger["eroded_km3"]
    sed_out = (
        ledger["dep_river_km3"]
        + ledger["dep_lake_km3"]
        + ledger["exported_km3"]
        + ledger["playa_km3"]
    )
    ledger["sediment_residual_rel"] = abs(sed_in - sed_out) / max(sed_in, 1e-12)
    ledger["volume_change_km3"] = (float(h[land].sum()) - vol0) * a_km3
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
    ledger["uplift_rate_last_mm_yr"] = u_last
    return SurfaceProcessResult(
        h=h,
        steps=step,
        ledger=ledger,
        lake=r["lake"],
        terminal=r["terminal"],
        discharge_m3_yr=r["q"],
        snaps=snaps,
    )
