"""Monsoon ΔP shape diagnosis vs NCEP SLP (monsoon-amplitude round, Stage C).

Runs *offline* on archived build outputs (no rebuild) to answer one question:
is the model's seasonal pressure anomaly ΔP wrong in *global amplitude* (fix:
rescale f_deep) or in *shape* (fix: a regional reweighting), and if shape, what
signal separates the over- from the under-projected boxes?

Method — three NCEP references, because the choice matters:
  A = land-only seasonal anomaly   SLP_box,m − SLP_box,annual
  D = land-vs-ocean *contrast* anomaly  [SLP_box − SLP_oceanZonal]_m − annual
      — matches the model's ΔP construction exactly (``pressure_anomaly_
      monthly`` references each land cell to the same-latitude OCEAN mean and
      removes the annual mean of that contrast).  D is the primary reference.

The pre-flight (2026-09-13) reported "dry interiors over-strong (Kazakhstan
2.84×, Siberia 3.91×) → fix with a moisture coupling g(W)".  That was a
calendar-convention bug, reproduced exactly: it indexed the NCEP array with
the *model's* month convention (month 0 = vernal equinox = March, so Jul = 4,
Jan = 10), but NCEP's month 0 = January — so it compared the model's JULY ΔP
against NCEP's MAY SLP, and JANUARY against NOVEMBER.  May/November are
shoulder seasons (monsoon low undeveloped, Siberian high still building), so
the NCEP reference came out ~half-size and every box looked over-strong.
(The model side was correct; the NCEP annual mean was correctly the mean of
the 12 months.  Every other monthly-validation script handles this offset —
only the pre-flight's throwaway code did not.)  With the correct months this
script *falsifies* both candidate regional reweightings:

  • g(W) column-water damping — Siberia (W≈1.5) needs ×0.41 while Mongolia
    (W≈1.4) needs ×1.29: equal W, opposite corrections.  No monotonic g(W)
    separates them.  And the model's Sahara W is biased *high* (the wet-P
    bias), so g(W) would under-damp the single worst box.
  • 4.2-① aridity-keep damping — the model's keep over India/华南 is biased
    *high* (0.88 / 1.00) by the same monsoon P dry bias this round targets,
    so damping by keep would crush the correctly-calibrated monsoon lows
    (India ratioD 1.00 → 0.22).

Both fail because they gate on model fields (W, P-derived keep) corrupted by
the very precip bias under study.  A third candidate — gating the warm-anomaly
ΔP on the Stage-1 ``_dt_subsidence`` increment (temperature-derived, pre-precip,
hence non-circular) — is falsified too (section 5): ``_dt_subsidence`` = 1-D-EBM
zonal T(lat) × the zonal Hadley-descent weight, so it is *zonally symmetric*
over land — Sahara / India / 华南 (same latitude band) get near-identical
values and cannot be separated.  The only thing that gives it regional structure
is the 4.2-① gate, which reads the model P (circular).

Conclusion: the monsoon ΔP is calibrated; the Sahara (5×) / Siberia (2.4×)
residual is the *missing subtropical anticyclone* — the model adds a thermal
low over hot land but has no stationary-wave high side (roadmap ④), a
structural gap no amplitude reweighting fills.  §5 subsidence drying stays
valid on the PRECIPITATION side (Sahara over-wet); it has no ΔP-side twin.

Usage:
    uv run python scripts/climate/diagnose_monsoon_dp_shape.py
    uv run python scripts/climate/diagnose_monsoon_dp_shape.py --branch climate-dev
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.engine.climate_physics import (  # noqa: E402
    aridity_index_keep,
    dryness_offset_mm,
    dryness_threshold_mm,
    potential_evapotranspiration_hamon,
)
from dreamulator.engine.climate_seasonality import (  # noqa: E402
    SOLAR_CONSTANT,
    solve_1d_ebm_temperature,
    warm_cold_half_precip,
)
from dreamulator.engine.monsoon_circulation import zonal_mean_monthly  # noqa: E402
from dreamulator.map.export import decompress_mesh_bytes  # noqa: E402
from dreamulator.validate_climate import build_earth_validation_config  # noqa: E402

# 4.2-① highland exemption (m): cells above this always keep (subsidence gate).
_SUBSIDENCE_GATE_ELEV_MAX_M = 1500.0

_ROOT = Path(__file__).resolve().parents[2]
_NCEP_SLP = _ROOT / "private" / "tmp" / "climatology" / "ncep_slp.mon.ltm.nc"

# Column-water proxy: W = P/k_rain with τ = 9 d residence (climate_simulator's
# _MOISTURE_RESIDENCE_DAYS).  p_monthly is mm/month → monthly steady-state
# annualised rate = 12·p; W [kg/m²] = 12·p [mm/yr] · 9/365.25 [yr].
_TAU_DAYS = 9.0
_W_FROM_P = 12.0 * _TAU_DAYS / 365.25

# Boxes: (name, lat_lo, lat_hi, lon_lo, lon_hi, ncep_month) with month in NCEP
# index (Jan=0 … Jul=6).  Model month = (ncep_month + 10) % 12 (month 0 =
# March): Jul(6) → 4, Jan(0) → 10.
_BOXES = [
    ("印度低压", 22.0, 30.0, 75.0, 90.0, 6),
    ("哈萨克/图兰", 42.0, 48.0, 60.0, 75.0, 6),
    ("华南", 22.0, 28.0, 108.0, 118.0, 6),
    ("撒哈拉", 20.0, 28.0, 5.0, 25.0, 6),
    ("西伯利亚", 55.0, 65.0, 80.0, 110.0, 0),
    ("蒙古", 42.0, 50.0, 95.0, 115.0, 0),
]


def _model_month(ncep_month: int) -> int:
    return (ncep_month + 10) % 12


def _aridity_keep(
    t_monthly_sel: np.ndarray, p_monthly_sel: np.ndarray, elev_sel: np.ndarray
) -> np.ndarray:
    """4.2-① subsidence-gate keep-fraction, recomputed offline (per cell).

    keep ≈ 1 hyper-arid (subsidence warming kept), keep ≈ 0 humid (released).
    Mirrors ``subsidence_aridity_gate``: keep = max(Köppen-r keep, UNEP-AI
    keep), highlands always keep.  NOTE: this is computed from the *model's*
    P, so over the monsoon margins it inherits the model's dry bias (keep
    biased high) — exactly why aridity-keep damping is falsified below.
    """
    p_annual = p_monthly_sel.sum(axis=1)
    t_mean = t_monthly_sel.mean(axis=1)
    p_warm, p_cold = warm_cold_half_precip(t_monthly_sel, p_monthly_sel)
    pet = potential_evapotranspiration_hamon(t_monthly_sel, 365.25 / 12.0)
    offset = dryness_offset_mm(p_warm, p_cold, p_annual)
    threshold = dryness_threshold_mm(t_mean, offset)
    r = p_annual / threshold
    keep_k = np.clip((1.0 - r) / 0.5, 0.0, 1.0)
    keep_ai = aridity_index_keep(p_annual, pet)
    keep = np.maximum(keep_k, keep_ai)
    return np.where(elev_sel >= _SUBSIDENCE_GATE_ELEV_MAX_M, 1.0, keep)


def _load_model(branch: str) -> dict[str, np.ndarray]:
    """Decode the archived monthly fields + mesh geometry for earth."""
    import msgpack

    base = _ROOT / "data" / "worlds" / "earth"
    map_dir = base / (Path("branches") / branch if branch else Path()) / "maps" / "planet_earth"
    mesh = json.loads(decompress_mesh_bytes((map_dir / "cvt_mesh.json").read_bytes()))
    cells = mesh["cells"]
    lat = np.array([c["lat"] for c in cells], dtype=np.float64)
    lon = np.array([c["lon"] for c in cells], dtype=np.float64)
    elev = np.array([c["elevation"] for c in cells], dtype=np.float64)

    blob = msgpack.unpackb((map_dir / "climate_monthly.msgpack").read_bytes())
    n = blob["num_cells"]

    def _dec(name: str) -> np.ndarray:
        stem = name.split("_monthly")[0]
        q = np.frombuffer(blob[name], dtype="<i2").reshape(n, 12).astype(np.float64)
        return q * blob[f"{stem}_scale"] + blob[f"{stem}_offset"]

    return {
        "lat": lat,
        "lon": lon,
        "elev": elev,
        "t_monthly": _dec("t_monthly"),
        "p_monthly": _dec("p_monthly"),
        "dp": _dec("pressure_monthly"),
    }


def _load_ncep() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """NCEP SLP climatology → (slp [12, lat, lon] hPa, lat, lon)."""
    import xarray as xr

    ds = xr.open_dataset(_NCEP_SLP, decode_times=False)
    slp = np.asarray(ds["slp"].values, dtype=np.float64)  # millibars = hPa
    lat = np.asarray(ds["lat"].values, dtype=np.float64)
    lon = np.asarray(ds["lon"].values, dtype=np.float64)
    ds.close()
    return slp, lat, lon


def _ncep_box(
    slp: np.ndarray,
    nlat: np.ndarray,
    nlon: np.ndarray,
    box: tuple,
    ocean: np.ndarray,
) -> tuple[float, float, float, float, float]:
    """(Jan raw, Jul raw, annual raw, A land-only, D contrast) over the box."""
    _, la0, la1, lo0, lo1, m = box
    lat_m = (nlat >= la0) & (nlat <= la1)
    lon_m = (nlon >= lo0) & (nlon <= lo1)
    sub = slp[:, lat_m][:, :, lon_m]  # (12, nla, nlo)
    land_m = sub.mean(axis=(1, 2))  # (12,) box land mean per month
    a_anom = float(land_m[m] - land_m.mean())
    # Same-latitude ocean zonal mean (crude ocean mask: cells whose annual SLP
    # sits within 4 hPa of the latitude's median — excludes the large land
    # thermal extremes), averaged over the box's latitude band.
    oc = np.where(ocean[lat_m], slp[:, lat_m], np.nan)  # (12, nla, nlon)
    oc_zon = np.nanmean(oc, axis=2).mean(axis=1)  # (12,)
    contrast = land_m - oc_zon
    d_anom = float((contrast - contrast.mean())[m])
    return float(sub[0].mean()), float(sub[6].mean()), float(land_m.mean()), a_anom, d_anom


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default="climate-dev")
    args = parser.parse_args()

    mdl = _load_model(args.branch)
    lat, lon, elev = mdl["lat"], mdl["lon"], mdl["elev"]
    t_monthly, p_monthly, dp = mdl["t_monthly"], mdl["p_monthly"], mdl["dp"]
    is_ocean = elev < 0.0
    w_proxy = p_monthly * _W_FROM_P  # (N, 12) kg/m²

    # Engine-exact land-vs-ocean ΔT (B2 reference): ocean-masked zonal mean,
    # annual-mean-removed.
    t_zonal = zonal_mean_monthly(t_monthly, lat, mask=is_ocean)
    dt = t_monthly - t_zonal
    dt = dt - dt.mean(axis=1, keepdims=True)

    slp, nlat, nlon = _load_ncep()
    ann_slp = slp.mean(axis=0)
    ocean_ncep = np.abs(ann_slp - np.median(ann_slp, axis=1, keepdims=True)) < 4.0

    # ── 1. NCEP reference sanity ──
    print("\n=== NCEP SLP box means (hPa) + references A / D ===")
    print(f"{'box':<14}{'Jan':>8}{'Jul':>8}{'annual':>8}{'A':>8}{'D':>8}")
    ncep_ref: dict[str, tuple[float, float]] = {}
    for box in _BOXES:
        jan, jul, ann, a_anom, d_anom = _ncep_box(slp, nlat, nlon, box, ocean_ncep)
        ncep_ref[box[0]] = (a_anom, d_anom)
        print(f"{box[0]:<14}{jan:>8.1f}{jul:>8.1f}{ann:>8.1f}{a_anom:>8.2f}{d_anom:>8.2f}")

    # ── 2. Model ΔP vs NCEP (D primary) ──
    print("\n=== Model ΔP vs NCEP — ratio = model/ref (target 0.8–1.25) ===")
    print(
        f"{'box':<12}{'mon':>4}{'model':>8}{'ratioD':>8}{'ratioA':>8}{'ΔT':>7}{'W':>7}{'keep':>6}"
    )
    rows: list[tuple[str, np.ndarray, int, float, float]] = []
    for box in _BOXES:
        name, la0, la1, lo0, lo1, m = box
        lon_c = np.where(lon < 0.0, lon + 360.0, lon)
        sel = (lat >= la0) & (lat <= la1) & (lon_c >= lo0) & (lon_c <= lo1) & ~is_ocean
        if sel.sum() == 0:
            print(f"{name:<12}  no land cells")
            continue
        mm = _model_month(m)
        a_ref, d_ref = ncep_ref[name]
        mdl_dp = float(dp[sel, mm].mean())
        dt_box = float(dt[sel, mm].mean())
        w_box = float(w_proxy[sel, mm].mean())
        keep_box = float(np.mean(_aridity_keep(t_monthly[sel], p_monthly[sel], elev[sel])))
        rd = mdl_dp / d_ref if abs(d_ref) > 1e-9 else float("nan")
        ra = mdl_dp / a_ref if abs(a_ref) > 1e-9 else float("nan")
        print(
            f"{name:<12}{m + 1:>4}{mdl_dp:>8.2f}{rd:>8.2f}{ra:>8.2f}"
            f"{dt_box:>7.1f}{w_box:>7.1f}{keep_box:>6.2f}"
        )
        rows.append((name, sel, mm, d_ref, mdl_dp))

    # ── 3. g(W) falsification ──
    print("\n=== g(W) falsification: multiplier needed vs W (equal W, opposite need = dead) ===")
    print(f"{'box':<12}{'W':>8}{'ratioD':>8}{'need×':>8}")
    for name, sel, mm, d_ref, mdl_dp in rows:
        w_box = float(w_proxy[sel, mm].mean())
        rd = mdl_dp / d_ref if abs(d_ref) > 1e-9 else float("nan")
        need = d_ref / mdl_dp if abs(mdl_dp) > 1e-9 else float("nan")
        print(f"{name:<12}{w_box:>8.1f}{rd:>8.2f}{need:>8.2f}")

    # ── 4. Aridity-keep damping falsification ──
    # ΔP' = ΔP·(1−keep) on warm anomalies only.  keep is the model's (P-biased).
    print("\n=== Aridity-keep damping (ΔP·(1−keep) on ΔT>0) — monsoon lows crushed ===")
    print(f"{'box':<12}{'ratioD_now':>11}{'ratioD_gated':>13}")
    for name, sel, mm, d_ref, mdl_dp in rows:
        keep = _aridity_keep(t_monthly[sel], p_monthly[sel], elev[sel])
        warm = dt[sel, mm] > 0.0
        g = np.where(warm, 1.0 - keep, 1.0)
        dp_gated = float((dp[sel, mm] * g).mean())
        rn = mdl_dp / d_ref if abs(d_ref) > 1e-9 else float("nan")
        rg = dp_gated / d_ref if abs(d_ref) > 1e-9 else float("nan")
        print(f"{name:<12}{rn:>11.2f}{rg:>13.2f}")

    # ── 5. _dt_subsidence zonal-symmetry falsification (the ΔP-cap signal) ──
    # Reproduce the Stage-1 subsidence increment offline.  solve_1d_ebm is a
    # pure zonal solver T(|lat|); the global-mean level (Legendre T_0) cancels
    # in (t_cell − t_mean), so any t_global reproduces _dt_subsidence exactly —
    # no full rebuild needed.  Demonstrates it carries no longitude structure.
    print("\n=== _dt_subsidence zonal symmetry (ΔP-cap signal falsification) ===")
    cfg = build_earth_validation_config(len(lat))
    lat_rad = np.radians(lat)
    solar_const = SOLAR_CONSTANT * cfg.stellar_luminosity_sol / cfg.orbital_distance_au**2
    d_scaled = cfg.ebm_diffusion_land_wm2k * (cfg.rotation_period_days**0.3)
    land = elev >= 0.0

    def _dt_sub(t_global: float) -> np.ndarray:
        t_zonal = solve_1d_ebm_temperature(
            lat_rad,
            t_global,
            albedo=cfg.albedo,
            obliquity_deg=cfg.axial_tilt_deg,
            solar_constant=solar_const,
            orbital_period_days=cfg.orbital_period_days,
            eccentricity=cfg.eccentricity,
            perihelion_day=cfg.perihelion_day,
            olr_b_wm2k=cfg.ebm_olr_b_wm2k,
            diffusion_wm2k=d_scaled,
        )
        phi_h = np.radians(cfg.hadley_extent_deg)
        cell = np.abs(lat_rad) < phi_h
        t_cell = float(np.average(t_zonal[cell], weights=np.cos(lat_rad[cell])))
        edge = np.radians(8.0)
        w = np.clip((phi_h + edge - np.abs(lat_rad)) / edge, 0.0, 1.0)
        out = np.zeros(len(lat))
        out[land] = cfg.subsidence_warming_c * w[land] * (t_cell - t_zonal[land])
        return out

    dsub = _dt_sub(15.0)
    cancel = float(np.abs(dsub - _dt_sub(25.0)).max())
    print(f"  global-mean level cancels: max|Δ(t_global 15 vs 25)| = {cancel:.2e} °C")
    # Rigorous zonal proof: bin land cells by |lat|; if _dt_subsidence = f(|lat|)
    # the within-bin spread (across ALL longitudes) shrinks → 0 as the bin narrows.
    # Any longitude structure would instead plateau at a nonzero floor.
    abs_lat = np.abs(lat[land])
    dsub_land = dsub[land]
    print("  zonal proof — max within-|lat|-bin std (all longitudes) vs bin width:")
    for bw in (0.10, 0.05, 0.02, 0.01):
        bins = np.round(abs_lat / bw).astype(np.int64)
        within = [dsub_land[bins == b].std() for b in np.unique(bins) if (bins == b).sum() >= 4]
        print(f"    bin {bw:.2f}°: {max(within):.2e} °C")
    print("    std → 0 as bin → 0 ⇒ pure f(|lat|), zero longitude structure.")
    print(f"  {'box':<12}{'lat_mid':>8}{'_dt_sub':>9}")
    for name, sel, *_ in rows:
        if name in ("印度低压", "华南", "撒哈拉"):
            print(f"  {name:<12}{lat[sel].mean():>8.1f}{dsub[sel].mean():>9.3f}")
    print("  → boxes track LATITUDE, not identity (India 4.69 > Sahara 3.59): gating")
    print("    ΔP on _dt_subsidence would damp India MORE than Sahara — backwards.")
    print("    Zonal (latitude-only) ⇒ cannot separate Sahara from India/华南.")


if __name__ == "__main__":
    main()
