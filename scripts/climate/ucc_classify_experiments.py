#!/usr/bin/env python3
"""UCC-01 step 3: compare classification candidates on the L2 observational
dataset (ucc-review §4.3 / §6.4 / §7 第二步).

Same external climate states for every candidate — the L2 earth-obs dataset
(monthly NCEP R1 T + GPCP v2.3 P + Hamon(obs T) reference demand + Beck 2018
Köppen reference column, built by ``ucc_obs_descriptors.py``).  Köppen is
computed in parallel (the engine's own ``koppen_classify`` on the observed
monthly series) as a *reference*, never an agreement target: divergences are
recorded, not forced away (ucc-review §1).

Candidates (§4.3: main class = temperature background × reference
supply–demand grade; seasonal range / same-period deficit / concentration are
optional modifiers, ablated one at a time):

- ``base-mean3xAI3``  — the simple baseline (§6.4: 均温 + 年 AI), 3×3 classes.
- ``nodes4xAI3``      — Köppen thermal nodes (empirical, declared) × AI 3-band.
- ``nodes4xAI4``      — same thermal nodes × AI 4-band (finer aridity split).
- ``koppen``          — full engine Köppen on the obs series (reference).

Evaluation axes (§6.4): compression loss (within-class IQR of descriptors the
candidate does NOT use), stability (systematic-perturbation ensemble: per-cell
T shift σ=0.75 °C + lognormal P factor σ=12 %, R realizations; class-flip
rate; near-threshold fraction), coverage (valid / not-applicable), complexity
(classes / thresholds).  All thresholds are declared empirical candidates —
none is claimed to be cross-world physics (§4.3).

Output: ``private/reviews/ucc-l2-classify-<date>.json`` + stdout summary.

Usage:
    uv run python scripts/climate/ucc_classify_experiments.py
    uv run python scripts/climate/ucc_classify_experiments.py --realizations 8
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

import msgpack
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.engine.climate_physics import (  # noqa: E402
    koppen_classify,
    potential_evapotranspiration_hamon_monthly,
)
from dreamulator.engine.climate_seasonality import (  # noqa: E402
    seasonal_precip_extremes,
    warm_cold_half_precip,
)
from dreamulator.map.ucc import compute_descriptors  # noqa: E402
from dreamulator.result_contract import REFERENCE_MONTH_DAYS  # noqa: E402

_L2_GLOB = "ucc-l2-earth-obs-*.msgpack"

# Declared empirical candidate thresholds (ucc-review §4.3: 地球经验节点可以
# 保留为候选，但不得标成跨世界物理定律).
T_NODE_POLAR_C = 10.0  # t_max below → polar (Köppen E node)
T_NODE_COLD_C = -3.0  # t_min below → cold/continental (Köppen D node)
T_NODE_TROPICAL_C = 18.0  # t_min above → tropical (Köppen A node)
T_MEAN_BANDS_C = (0.0, 18.0)  # baseline: freeze point + tropical node on t_mean
AI_BANDS_3 = (0.5, 1.0)  # arid / transitional / humid
AI_BANDS_4 = (0.2, 0.5, 1.0)  # + arid/semi-arid split
MOD_T_RANGE_C = 25.0  # strong temperature seasonality modifier
MOD_DEFICIT = 0.5  # seasonal water-stress modifier
MOD_CONCENTRATION = 0.5  # highly concentrated precipitation modifier

# Perturbation ensemble (systematic, climatology-bias-like; Beck 2023 §2.5
# motivates reporting boundary sensitivity, not calibrated probabilities).
PERT_T_SIGMA_C = 0.75  # per-cell constant shift, all months
PERT_P_SIGMA = 0.12  # per-cell lognormal multiplicative factor

# Panel of descriptors for compression-loss measurement.
PANEL = ("t_mean_c", "t_range_c", "t_below_frac", "p_total_mm", "ai", "deficit", "concentration")


def _load_l2(path: Path) -> dict[str, np.ndarray]:
    with path.open("rb") as f:
        d = msgpack.unpackb(f.read())
    n, m = d["num_cells"], d["months"]
    out: dict[str, np.ndarray] = {
        "t_monthly": np.frombuffer(d["t_monthly"], np.float32).reshape(n, m).astype(np.float64),
        "p_monthly": np.frombuffer(d["p_monthly"], np.float32).reshape(n, m).astype(np.float64),
        "lat": np.frombuffer(d["lat"], np.float32),
        "lon": np.frombuffer(d["lon"], np.float32),
        "water_class": np.array(d["water_class"]),
        "koppen_obs": np.array(d["koppen_obs"]),
    }
    return out


def _descriptors_vectorized(t: np.ndarray, p: np.ndarray, et: np.ndarray) -> dict[str, np.ndarray]:
    """(N,12) → descriptor arrays; mirrors ``compute_descriptors`` with equal
    bins (dt=1) and freeze threshold 0 °C.  Vectorized so the perturbation
    ensemble (R × N cells) stays cheap; cross-checked against the scalar
    contract in ``_check_vectorized_consistency``."""
    t_mean = t.mean(axis=1)
    t_min = t.min(axis=1)
    t_max = t.max(axis=1)
    p_total = p.sum(axis=1)
    et_total = et.sum(axis=1)
    pos_demand = et_total > 0.0
    safe_et = np.maximum(et_total, 1e-12)
    ai = np.where(pos_demand, p_total / safe_et, np.nan)
    deficit = np.where(pos_demand, np.maximum(et - p, 0.0).sum(axis=1) / safe_et, np.nan)
    safe_p = np.maximum(p_total, 1e-12)
    q = p / safe_p[:, None]
    concentration = np.where(p_total > 0.0, 0.5 * np.abs(q - 1.0 / t.shape[1]).sum(axis=1), np.nan)
    # Demand-model validity domain (compute_descriptors): no bin above freezing
    # → Hamon reference demand undefined → supply–demand stats out of domain.
    out_of_domain = t_max < 0.0
    ai = np.where(out_of_domain, np.nan, ai)
    deficit = np.where(out_of_domain, np.nan, deficit)
    return {
        "t_mean_c": t_mean,
        "t_min_c": t_min,
        "t_max_c": t_max,
        "t_range_c": t_max - t_min,
        "t_below_frac": (t < 0.0).mean(axis=1),
        "p_total_mm": p_total,
        "ai": ai,
        "deficit": deficit,
        "concentration": concentration,
    }


def _check_vectorized_consistency(t: np.ndarray, p: np.ndarray, et: np.ndarray) -> None:
    """Spot-check the vectorized formulas against the scalar L0 contract."""
    vec = _descriptors_vectorized(t, p, et)
    rng = np.random.default_rng(0)
    for i in rng.choice(t.shape[0], size=200, replace=False):
        d = compute_descriptors(t[i], p[i], et[i])
        assert np.isclose(vec["t_mean_c"][i], d.t_mean)
        assert np.isclose(vec["t_range_c"][i], d.t_range)
        assert np.isclose(vec["t_below_frac"][i], d.t_below_frac)
        assert np.isclose(vec["p_total_mm"][i], d.p_total)
        if d.ai is None:
            assert np.isnan(vec["ai"][i])
        else:
            assert np.isclose(vec["ai"][i], d.ai)
        if d.deficit is None:
            assert np.isnan(vec["deficit"][i])
        else:
            assert np.isclose(vec["deficit"][i], d.deficit)
        if d.concentration is None:
            assert np.isnan(vec["concentration"][i])
        else:
            assert np.isclose(vec["concentration"][i], d.concentration)


# ---------------------------------------------------------------------------
# Classifiers — each returns (N,) int codes; -1 = not applicable (ocean on the
# supply–demand axis).  Combined code = temp_band * 10 + (ai_band + 1).
# ---------------------------------------------------------------------------

T_NODE_NAMES = ["polar", "cold", "temperate", "tropical"]
T_MEAN3_NAMES = ["frigid", "mild", "warm"]
AI3_NAMES = ["arid", "transitional", "humid"]
AI4_NAMES = ["arid", "semi_arid", "transitional", "humid"]


def _temp_nodes(t_min: np.ndarray, t_max: np.ndarray) -> np.ndarray:
    return np.select(
        [t_max < T_NODE_POLAR_C, t_min < T_NODE_COLD_C, t_min < T_NODE_TROPICAL_C],
        [0, 1, 2],
        default=3,
    )


def _temp_mean3(t_mean: np.ndarray) -> np.ndarray:
    return np.select([t_mean < T_MEAN_BANDS_C[0], t_mean < T_MEAN_BANDS_C[1]], [0, 1], default=2)


def _ai_bands(ai: np.ndarray, edges: tuple[float, ...]) -> np.ndarray:
    bands = np.digitize(ai, list(edges)).astype(int)  # nan → len(edges) digitize? no:
    bands = np.where(np.isnan(ai), -1, bands)  # undefined demand → not applicable
    return bands


def _combine(temp: np.ndarray, ai_band: np.ndarray) -> np.ndarray:
    return temp * 10 + (ai_band + 1)  # ai_band -1 (ocean/undefined) → …0 suffix


def _class_labels(
    temp: np.ndarray, ai_band: np.ndarray, t_names: list[str], ai_names: list[str]
) -> list[str]:
    labels = []
    for tb, ab in zip(temp, ai_band, strict=True):
        if ab < 0:
            labels.append(f"{t_names[tb]}/n-a")
        else:
            labels.append(f"{t_names[tb]}/{ai_names[ab]}")
    return labels


# ---------------------------------------------------------------------------
# Köppen reference: engine classifier on the observed monthly series.
# ---------------------------------------------------------------------------


def _koppen_parallel(t: np.ndarray, p: np.ndarray, is_land: np.ndarray) -> list[str]:
    p_warm, p_cold = warm_cold_half_precip(t, p)
    p_ds, p_ww, p_dw, p_ws = seasonal_precip_extremes(t, p)
    return koppen_classify(
        t_mean_c=t.mean(axis=1),
        t_cold_c=t.min(axis=1),
        t_hot_c=t.max(axis=1),
        p_annual_mm=p.sum(axis=1),
        p_dry_mm=p.min(axis=1),
        p_wet_mm=p.max(axis=1),
        is_land=is_land,
        p_warm_mm=p_warm,
        p_cold_mm=p_cold,
        p_dry_summer_mm=p_ds,
        p_wet_winter_mm=p_ww,
        p_dry_winter_mm=p_dw,
        p_wet_summer_mm=p_ws,
        t_months_ge10=(t >= 10.0).sum(axis=1),
    )


# ---------------------------------------------------------------------------
# Metrics (ucc-review §6.4).
# ---------------------------------------------------------------------------


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    return float(v[np.searchsorted(np.cumsum(w), 0.5 * w.sum())])


def _compression(
    codes: np.ndarray, desc: dict[str, np.ndarray], used: set[str], land: np.ndarray
) -> dict[str, float]:
    """Weighted-median within-class IQR per panel descriptor (land cells), plus
    the compression ratio vs the one-class global IQR.  Descriptors the profile
    uses in its own definition are reported but flagged downstream — the fair
    cross-profile comparison is on the *unused* panel."""
    out: dict[str, float] = {}
    classes, counts = np.unique(codes[land], return_counts=True)
    for name in PANEL:
        x = desc[name][land]
        code_l = codes[land]
        finite = np.isfinite(x)
        iqrs, ws = [], []
        for c, cnt in zip(classes, counts, strict=True):
            if cnt < 30:
                continue
            sel = (code_l == c) & finite
            if sel.sum() < 30:
                continue
            q75, q25 = np.percentile(x[sel], [75, 25])
            iqrs.append(q75 - q25)
            ws.append(float(sel.sum()))
        xf = x[finite]
        global_iqr = float(np.subtract(*np.percentile(xf, [75, 25])))
        med = _weighted_median(np.array(iqrs), np.array(ws)) if iqrs else float("nan")
        out[name] = med
        out[name + "__ratio"] = med / global_iqr if global_iqr > 0 else float("nan")
    out["__used__"] = float("nan")  # placeholder kept out of JSON noise below
    return {k: v for k, v in out.items() if k != "__used__"} | {"_used_axes": sorted(used)}  # type: ignore[dict-item]


def _near_threshold(
    desc: dict[str, np.ndarray], land: np.ndarray, temp_kind: str, ai_edges: tuple[float, ...]
) -> dict[str, float]:
    """Fraction of cells sitting next to a classification threshold — the
    boundary-sensitivity exposure (Beck 2023, §2.5)."""
    t_min, t_max, t_mean = desc["t_min_c"], desc["t_max_c"], desc["t_mean_c"]
    if temp_kind == "nodes":
        nodes_tmin = np.minimum(np.abs(t_min - T_NODE_COLD_C), np.abs(t_min - T_NODE_TROPICAL_C))
        nodes = np.minimum(nodes_tmin, np.abs(t_max - T_NODE_POLAR_C))
    else:
        nodes = np.minimum(np.abs(t_mean - T_MEAN_BANDS_C[0]), np.abs(t_mean - T_MEAN_BANDS_C[1]))
    ai = desc["ai"]
    valid = land & np.isfinite(ai)
    log_ai = np.log(np.maximum(ai[valid], 1e-6))
    log_dist = np.min(np.abs(log_ai[:, None] - np.log(np.array(ai_edges))[None, :]), axis=1)
    return {
        "thermal_within_0.75C": float(np.mean(nodes[land] < 0.75)),
        "ai_within_15pct": float(np.mean(log_dist < np.log(1.15))) if valid.any() else float("nan"),
    }


def _crosstab_temp_beck(
    temp: np.ndarray, t_names: list[str], koppen_obs: np.ndarray, land: np.ndarray
) -> dict[str, dict[str, int]]:
    groups = np.array([k[0] if k and k != "N/A" else "?" for k in koppen_obs])
    table: dict[str, dict[str, int]] = {}
    for tb in range(len(t_names)):
        sel = land & (temp == tb) & (groups != "?")
        if sel.sum() == 0:
            continue
        table[t_names[tb]] = dict(Counter(groups[sel].tolist()))
    return table


def _crosstab_ai_beck(
    ai_band: np.ndarray, ai_names: list[str], koppen_obs: np.ndarray, land: np.ndarray
) -> dict[str, dict[str, int]]:
    groups = np.array([k[0] if k and k != "N/A" else "?" for k in koppen_obs])
    arid = groups == "B"
    table: dict[str, dict[str, int]] = {}
    for ab in range(len(ai_names)):
        sel = land & (ai_band == ab) & (groups != "?")
        if sel.sum() == 0:
            continue
        table[ai_names[ab]] = {
            "beck_arid_B": int((sel & arid).sum()),
            "beck_not_B": int((sel & ~arid).sum()),
        }
    return table


# ---------------------------------------------------------------------------
# Main experiment.
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--l2", type=Path, default=None, help="L2 dataset msgpack")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--realizations", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()

    l2 = args.l2
    if l2 is None:
        candidates = sorted(Path("private/reviews").glob(_L2_GLOB))
        if not candidates:
            sys.exit("No L2 dataset found; run scripts/climate/ucc_obs_descriptors.py first")
        l2 = candidates[-1]
    stamp = datetime.date.today().isoformat()
    out = args.out or Path(f"private/reviews/ucc-l2-classify-{stamp}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading L2 dataset {l2} …")
    data = _load_l2(l2)
    t, p = data["t_monthly"], data["p_monthly"]
    n = t.shape[0]
    land = data["water_class"] == "land"
    koppen_obs = data["koppen_obs"]
    print(f"  {n} cells, {int(land.sum())} land")

    et = potential_evapotranspiration_hamon_monthly(t, REFERENCE_MONTH_DAYS)
    _check_vectorized_consistency(t, p, et)
    desc = _descriptors_vectorized(t, p, et)

    print("Computing parallel Köppen reference (engine classifier on obs series) …")
    koppen_codes = _koppen_parallel(t, p, land)
    koppen_main = np.array([k[0] if k not in ("", "Ocean") else "?" for k in koppen_codes])
    beck_main = np.array([k[0] if k and k != "N/A" else "?" for k in koppen_obs])
    both = land & (koppen_main != "?") & (beck_main != "?")
    koppen_beck_agree = (
        float(np.mean(koppen_main[both] == beck_main[both])) if both.any() else float("nan")
    )

    # --- Candidate profiles -------------------------------------------------
    profiles: dict[str, dict] = {}
    temp_nodes = _temp_nodes(desc["t_min_c"], desc["t_max_c"])
    temp_mean3 = _temp_mean3(desc["t_mean_c"])
    temp_kinds = {
        "base-mean3xAI3": ("mean3", temp_mean3, T_MEAN3_NAMES, AI_BANDS_3, AI3_NAMES),
        "nodes4xAI3": ("nodes", temp_nodes, T_NODE_NAMES, AI_BANDS_3, AI3_NAMES),
        "nodes4xAI4": ("nodes", temp_nodes, T_NODE_NAMES, AI_BANDS_4, AI4_NAMES),
    }
    used_axes = {
        "base-mean3xAI3": {"t_mean_c", "ai"},
        "nodes4xAI3": {"t_min_c", "t_max_c", "ai"},
        "nodes4xAI4": {"t_min_c", "t_max_c", "ai"},
    }
    for name, (kind, temp, t_names, ai_edges, ai_names) in temp_kinds.items():
        ai_band = _ai_bands(desc["ai"], ai_edges)
        codes = _combine(temp, ai_band)
        labels = _class_labels(temp, ai_band, t_names, ai_names)
        land_labels = [lab for lab, is_l in zip(labels, land, strict=True) if is_l]
        n_classes = len(set(land_labels))
        profiles[name] = {
            "temp": temp,
            "ai_band": ai_band,
            "codes": codes,
            "labels": labels,
            "n_classes_land": n_classes,
            "n_thresholds": (len(T_MEAN_BANDS_C) if kind == "mean3" else 3) + len(ai_edges),
            "temp_kind": kind,
            "t_names": t_names,
            "ai_names": ai_names,
            "ai_edges": ai_edges,
            "used": used_axes[name],
        }

    # --- Compression / coverage / complexity / divergence -------------------
    results: dict[str, dict] = {
        "_config": {
            "l2_dataset": str(l2),
            "realizations": args.realizations,
            "seed": args.seed,
            "pert_t_sigma_c": PERT_T_SIGMA_C,
            "pert_p_sigma": PERT_P_SIGMA,
            "thresholds": {
                "t_node_polar_c": T_NODE_POLAR_C,
                "t_node_cold_c": T_NODE_COLD_C,
                "t_node_tropical_c": T_NODE_TROPICAL_C,
                "t_mean_bands_c": T_MEAN_BANDS_C,
                "ai_bands_3": AI_BANDS_3,
                "ai_bands_4": AI_BANDS_4,
                "mod_t_range_c": MOD_T_RANGE_C,
                "mod_deficit": MOD_DEFICIT,
                "mod_concentration": MOD_CONCENTRATION,
            },
            "note": "All thresholds are declared empirical candidates (ucc-review §4.3).",
        }
    }

    for name, prof in profiles.items():
        print(f"Evaluating {name} …")
        comp = _compression(prof["codes"], desc, prof["used"], land)
        used = prof["used"]
        unused_panel = [d for d in PANEL if d not in used and not d.startswith(("t_min", "t_max"))]
        results[name] = {
            "n_classes_land": prof["n_classes_land"],
            "n_thresholds": prof["n_thresholds"],
            "coverage": {
                "land_ai_valid": float(np.mean(np.isfinite(desc["ai"][land]))),
                "ocean_share": float(np.mean(~land)),
            },
            "compression": comp,
            "compression_unused_mean_ratio": float(
                np.nanmean([comp[d + "__ratio"] for d in unused_panel])
            ),
            "near_threshold": _near_threshold(desc, land, prof["temp_kind"], prof["ai_edges"]),
            "crosstab_temp_beck": _crosstab_temp_beck(
                prof["temp"], prof["t_names"], koppen_obs, land
            ),
            "crosstab_ai_beck": _crosstab_ai_beck(
                prof["ai_band"], prof["ai_names"], koppen_obs, land
            ),
        }

    # Köppen reference row (compression vs the descriptors it never uses).
    koppen_code_int = np.array([hash(k) % 100000 for k in koppen_codes])
    results["koppen"] = {
        "n_classes_land": len({k for k, is_l in zip(koppen_codes, land, strict=True) if is_l}),
        "n_thresholds": None,  # full Köppen rule set; not a single number
        "main_group_agreement_vs_beck": koppen_beck_agree,
        "compression": _compression(
            koppen_code_int, desc, {"t_min_c", "t_max_c", "p_total_mm"}, land
        ),
    }

    # --- Ablation: modifiers on nodes4xAI3 (§6.4: 加季节范围 / 供需错配 / 集中度
    # 各自的增益) ----------------------------------------------------------------------
    print("Ablation: modifiers on nodes4xAI3 …")
    base = profiles["nodes4xAI3"]
    ablation: dict[str, dict] = {}
    mods = {
        "+t_range": (desc["t_range_c"] >= MOD_T_RANGE_C, "t_range_c"),
        "+deficit": ((desc["deficit"] >= MOD_DEFICIT) & np.isfinite(desc["deficit"]), "deficit"),
        "+concentration": (
            (desc["concentration"] >= MOD_CONCENTRATION) & np.isfinite(desc["concentration"]),
            "concentration",
        ),
    }
    base_comp = results["nodes4xAI3"]["compression"]
    for mod_name, (flag, axis) in mods.items():
        codes_mod = base["codes"] * 2 + flag.astype(int)
        comp = _compression(codes_mod, desc, base["used"] | {axis}, land)
        n_classes = len({c for c, is_l in zip(codes_mod, land, strict=True) if is_l})
        ablation[mod_name] = {
            "n_classes_land": n_classes,
            "axis_iqr_before": base_comp[axis],
            "axis_iqr_after": comp[axis],
            "axis_iqr_reduction": (
                1.0 - comp[axis] / base_comp[axis] if base_comp[axis] > 0 else float("nan")
            ),
            "flagged_share_land": float(np.mean(flag[land])),
        }
    results["ablation"] = ablation

    # --- Stability: systematic-perturbation ensemble -------------------------
    print(f"Stability: {args.realizations} perturbed realizations …")
    rng = np.random.default_rng(args.seed)
    flip_counts = {name: np.zeros(n, int) for name in profiles}
    koppen_flip = np.zeros(n, int)
    for r in range(args.realizations):
        t_p = t + rng.normal(0.0, PERT_T_SIGMA_C, size=(n, 1))
        p_p = p * np.exp(rng.normal(0.0, PERT_P_SIGMA, size=(n, 1)))
        et_p = potential_evapotranspiration_hamon_monthly(t_p, REFERENCE_MONTH_DAYS)
        d_p = _descriptors_vectorized(t_p, p_p, et_p)
        for name, prof in profiles.items():
            temp_p = (
                _temp_mean3(d_p["t_mean_c"])
                if prof["temp_kind"] == "mean3"
                else _temp_nodes(d_p["t_min_c"], d_p["t_max_c"])
            )
            codes_p = _combine(temp_p, _ai_bands(d_p["ai"], prof["ai_edges"]))
            flip_counts[name] += (codes_p != prof["codes"]) & land
        koppen_p = _koppen_parallel(t_p, p_p, land)
        flips = np.array([a != b for a, b in zip(koppen_p, koppen_codes, strict=True)])
        koppen_flip += flips & land
        if (r + 1) % 4 == 0:
            print(f"  {r + 1}/{args.realizations} done")
    results["stability"] = {
        name: {"land_class_flip_rate": float(np.mean(flip_counts[name][land]) / args.realizations)}
        for name in profiles
    }
    results["stability"]["koppen"] = {
        "land_class_flip_rate": float(np.mean(koppen_flip[land]) / args.realizations)
    }

    with out.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out}")

    # --- Stdout summary -------------------------------------------------------
    print("\n=== Profiles: complexity / coverage / stability ===")
    print(
        f"{'profile':<16}{'classes':>8}{'thresh':>7}{'flip%':>7}{'nearT%':>7}{'nearAI%':>8}{'unusedIQR':>10}"
    )
    for name, res in results.items():
        if name.startswith("_") or name in ("ablation", "stability"):
            continue
        stab = results["stability"].get(name, {}).get("land_class_flip_rate", float("nan"))
        near = res.get("near_threshold", {})
        print(
            f"{name:<16}{res['n_classes_land']:>8}{str(res['n_thresholds']):>7}"
            f"{stab * 100:>6.1f}%{near.get('thermal_within_0.75C', float('nan')) * 100:>6.1f}%"
            f"{near.get('ai_within_15pct', float('nan')) * 100:>7.1f}%"
            f"{res.get('compression_unused_mean_ratio', float('nan')):>10.3f}"
        )
    print("\n=== Ablation (modifiers on nodes4xAI3) ===")
    for mod_name, a in ablation.items():
        print(
            f"  {mod_name:<16} classes {a['n_classes_land']:>3} | axis IQR "
            f"{a['axis_iqr_before']:.3f} → {a['axis_iqr_after']:.3f} "
            f"({a['axis_iqr_reduction'] * 100:.1f}% reduction) | "
            f"flagged {a['flagged_share_land'] * 100:.1f}% of land"
        )
    print(f"\nEngine-Köppen vs Beck main-group agreement (context): {koppen_beck_agree:.1%}")


if __name__ == "__main__":
    main()
