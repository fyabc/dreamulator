#!/usr/bin/env python3
"""Build the UCC L2 external-climate-state dataset from earth root observations
(UCC-01 第三步前置 — ucc-review §6.2 L2).

The earth root world's climate is *observation*, not engine output
(earth-real-data.md §2.4): NCEP/NCAR R1 monthly temperature (2.5°), GPCP v2.3
monthly precipitation (2.5°), Beck et al. 2018 Köppen-Geiger (5 arc-min) — all
sampled onto the 200k-cell CVT mesh.  This makes it the natural L2 substrate:
descriptor semantics are checked against real climate states, decoupled from
engine error, with Beck Köppen as the reference classification column.

The reference demand Eref is Hamon-1961 computed from the *observed* monthly
temperature — the same demand model the engine-side descriptors use, so the
two stay comparable (ucc-review §2.3: record the demand model; do not claim
FAO-56 calibration).  A FAO-56 ET0 cross-check (e.g. Zomer 2022) is a possible
later sensitivity pass, not part of this dataset.

Output: ``private/reviews/ucc-l2-earth-obs-<date>.msgpack`` with per-cell
descriptors + lat/lon/water_class/Beck Köppen + provenance metadata, plus a
stdout coverage summary (Köppen regime tally × descriptor medians).

Usage:
    uv run python scripts/climate/ucc_obs_descriptors.py
    uv run python scripts/climate/ucc_obs_descriptors.py --out private/reviews/foo.msgpack
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
    potential_evapotranspiration_hamon_monthly,
)
from dreamulator.map.export import decompress_mesh_bytes  # noqa: E402
from dreamulator.map.ucc import compute_descriptors  # noqa: E402
from dreamulator.result_contract import REFERENCE_MONTH_DAYS  # noqa: E402

_EARTH_MAP = Path("data/worlds/earth/maps/planet_earth")


def _load_monthly(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Decode the int16-quantized climate_monthly.msgpack → (t, p), both (N, 12)."""
    with path.open("rb") as f:
        d = msgpack.unpackb(f.read())
    n, m = d["num_cells"], d["months"]

    def deq(name: str) -> np.ndarray:
        q = np.frombuffer(d[name], dtype=np.int16).astype(np.float64)
        return (
            q.reshape(n, m) * d[name.removesuffix("_monthly") + "_scale"]
            + d[name.removesuffix("_monthly") + "_offset"]
        )

    return deq("t_monthly"), deq("p_monthly")


def _load_mesh_fields(path: Path) -> dict[str, np.ndarray]:
    """Read the (gzip) mesh JSON, keeping only the fields this dataset needs."""
    mesh = json.loads(decompress_mesh_bytes(path.read_bytes()))
    cells = mesh["cells"]
    return {
        "lat": np.array([c["lat"] for c in cells], dtype=np.float32),
        "lon": np.array([c["lon"] for c in cells], dtype=np.float32),
        "water_class": np.array([c.get("water_class") or "" for c in cells], dtype=str),
        "koppen_obs": np.array([c.get("koppen_class") or "" for c in cells], dtype=str),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map-dir",
        type=Path,
        default=_EARTH_MAP,
        help="Earth root map dir with climate_monthly.msgpack + cvt_mesh.json",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out = args.out
    if out is None:
        stamp = datetime.date.today().isoformat()
        out = Path(f"private/reviews/ucc-l2-earth-obs-{stamp}.msgpack")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Reading monthly obs from {args.map_dir}/climate_monthly.msgpack …")
    t_monthly, p_monthly = _load_monthly(args.map_dir / "climate_monthly.msgpack")
    n = t_monthly.shape[0]

    print(f"Reading mesh fields from {args.map_dir}/cvt_mesh.json …")
    mesh = _load_mesh_fields(args.map_dir / "cvt_mesh.json")
    assert len(mesh["lat"]) == n, "mesh/monthly cell-count mismatch"

    # Monthly Hamon reference demand from *observed* temperature — same demand
    # model as the engine-side descriptors (ucc-review §2.3: declared, not
    # FAO-56-calibrated).
    et_monthly = potential_evapotranspiration_hamon_monthly(t_monthly, REFERENCE_MONTH_DAYS)

    print(f"Computing UCC descriptors for {n} cells …")
    desc: dict[str, np.ndarray] = {
        "t_mean_c": np.empty(n, np.float32),
        "t_min_c": np.empty(n, np.float32),
        "t_max_c": np.empty(n, np.float32),
        "t_range_c": np.empty(n, np.float32),
        "t_below_frac": np.empty(n, np.float32),
        "p_mean_mm_per_month": np.empty(n, np.float32),
        "p_total_mm": np.empty(n, np.float32),
        "ai": np.full(n, np.nan, np.float32),
        "deficit": np.full(n, np.nan, np.float32),
        "concentration": np.full(n, np.nan, np.float32),
        "ai_status": np.empty(n, np.uint8),
        "deficit_status": np.empty(n, np.uint8),
    }
    status_codes = ["valid", "missing_input", "not_applicable", "no_positive_demand"]
    status_index = {s: i for i, s in enumerate(status_codes)}
    for i in range(n):
        d = compute_descriptors(t_monthly[i], p_monthly[i], et_monthly[i])
        desc["t_mean_c"][i] = d.t_mean
        desc["t_min_c"][i] = d.t_min
        desc["t_max_c"][i] = d.t_max
        desc["t_range_c"][i] = d.t_range
        desc["t_below_frac"][i] = d.t_below_frac
        desc["p_mean_mm_per_month"][i] = d.p_mean_rate
        desc["p_total_mm"][i] = d.p_total
        if d.ai is not None:
            desc["ai"][i] = d.ai
        if d.deficit is not None:
            desc["deficit"][i] = d.deficit
        if d.concentration is not None:
            desc["concentration"][i] = d.concentration
        desc["ai_status"][i] = status_index[d.ai_status]
        desc["deficit_status"][i] = status_index[d.deficit_status]

    payload = {
        "provenance": {
            "temperature": "NCEP/NCAR R1 air.mon.ltm (2.5°, monthly climatology)",
            "precipitation": "GPCP v2.3 precip.mon.mean (2.5°, monthly climatology)",
            "koppen_obs": "Beck et al. 2018 present-day Köppen-Geiger (5 arc-min)",
            "demand_model": "hamon-1961 (12 h daylength, from observed T)",
            "reference_month_days": REFERENCE_MONTH_DAYS,
            "note": "Observational L2 substrate for UCC-01 step 3; NOT engine output.",
        },
        "num_cells": n,
        "months": 12,
        "month_0": "vernal_equinox",
        "status_codes": status_codes,
        # Raw monthly series: step-3 experiments (shape diagnostics, threshold
        # perturbation) need the sequences, not just their descriptors.
        "t_monthly": t_monthly.astype(np.float32).tobytes(),
        "p_monthly": p_monthly.astype(np.float32).tobytes(),
        **{k: v.tobytes() for k, v in desc.items()},
        "lat": mesh["lat"].tobytes(),
        "lon": mesh["lon"].tobytes(),
        "water_class": mesh["water_class"].tolist(),
        "koppen_obs": mesh["koppen_obs"].tolist(),
    }
    with out.open("wb") as f:
        f.write(msgpack.packb(payload))
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")

    # --- Coverage summary (ucc-review §6.2 L2: regime coverage × descriptors) ---
    land = mesh["water_class"] == "land"
    koppen = mesh["koppen_obs"]
    groups = np.array([k[0] if k else "?" for k in koppen])
    print("\nKöppen main-group coverage (land cells):")
    for g, count in sorted(Counter(groups[land].tolist()).items()):
        sel = land & (groups == g)
        ai = desc["ai"][sel]
        print(
            f"  {g}: {count:6d} cells | t_mean {np.median(desc['t_mean_c'][sel]):6.1f} °C | "
            f"t_range {np.median(desc['t_range_c'][sel]):5.1f} | "
            f"P {np.median(desc['p_total_mm'][sel]):6.0f} mm | "
            f"AI {np.nanmedian(ai):5.2f} | deficit {np.nanmedian(desc['deficit'][sel]):4.2f} | "
            f"C_TV {np.nanmedian(desc['concentration'][sel]):4.2f}"
        )
    n_b = int((land & (groups == "B")).sum())
    b_low_ai = float(np.mean(desc["ai"][land & (groups == "B")] < 0.5)) if n_b else 0.0
    print(f"\nCross-check: Beck arid (B) cells with AI < 0.5: {b_low_ai:.1%}")


if __name__ == "__main__":
    main()
