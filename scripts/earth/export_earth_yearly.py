#!/usr/bin/env python3
"""Export UCC yearly descriptors + classification for the earth reference root —
from OBSERVED monthly climate, never from the engine.

The earth root world is the real-data anchor and is never built (CLAUDE.md
"模型态 vs obs 态分离").  This importer-side script is the obs-derived
counterpart of the engine's ``export_climate_layers`` yearly block: it reads
the root's ``climate_monthly.msgpack`` (NCEP/NCAR R1 temperature + GPCP v2.3
precipitation, written by ``import_earth_climate``) and the mesh's
``water_class``, computes UCC descriptors (``compute_descriptors``) and the
the current profile's classification (``classify_v1``), and writes
``climate_yearly.msgpack`` into the root maps dir.

Epistemic status: a declared, frozen transformation of observations — the same
class as the Beck 2018 Köppen column already on root (a published algorithm
over observed T/P), NOT engine output.  The file says so itself via
``data_source: "observation"`` + the ``provenance`` block; engine-built exports
carry ``data_source: "model"`` instead.

Usage:
    uv run python scripts/earth/export_earth_yearly.py
    uv run python scripts/earth/export_earth_yearly.py --output-dir <maps dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import msgpack
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.engine.climate_physics import (  # noqa: E402
    potential_evapotranspiration_hamon_monthly,
)
from dreamulator.map.export import decompress_mesh_bytes  # noqa: E402
from dreamulator.map.ucc import (  # noqa: E402
    PROFILE_CURRENT,
    STATUS_CODES,
    SUPPLY_BANDS_CURRENT,
    THERMAL_BANDS_CURRENT,
    classify_v1,
    compute_descriptors,
)
from dreamulator.result_contract import REFERENCE_MONTH_DAYS, result_metadata  # noqa: E402

_DEFAULT_MAP = Path("data/worlds/earth/maps/planet_earth")


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


def _load_water_class(map_dir: Path, n: int) -> np.ndarray:
    mesh = json.loads(decompress_mesh_bytes((map_dir / "cvt_mesh.json").read_bytes()))
    wc = np.array([c.get("water_class") or "" for c in mesh["cells"]], dtype=str)
    assert len(wc) == n, "mesh/monthly cell-count mismatch"
    return wc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_MAP,
        help="Earth root map dir containing climate_monthly.msgpack + cvt_mesh.json",
    )
    args = parser.parse_args()
    map_dir = args.output_dir

    print(f"Reading observed monthly series from {map_dir}/climate_monthly.msgpack …")
    t_monthly, p_monthly = _load_monthly(map_dir / "climate_monthly.msgpack")
    n = t_monthly.shape[0]
    water_class = _load_water_class(map_dir, n)

    # Same demand model as the engine-side descriptors (declared, not FAO-56) —
    # keeping engine and observation directly comparable.
    et_monthly = potential_evapotranspiration_hamon_monthly(t_monthly, REFERENCE_MONTH_DAYS)

    status_codes = list(STATUS_CODES)
    status_index = {s: i for i, s in enumerate(status_codes)}
    thermal_index = {s: i for i, s in enumerate(THERMAL_BANDS_CURRENT)}
    supply_index = {s: i for i, s in enumerate(SUPPLY_BANDS_CURRENT)}

    desc_f32: dict[str, np.ndarray] = {
        k: np.empty(n, np.float32)
        for k in (
            "t_mean_c",
            "t_min_c",
            "t_max_c",
            "t_range_c",
            "t_below_frac",
            "p_mean_mm_per_month",
            "p_total_mm",
        )
    }
    ai = np.full(n, np.nan, np.float32)
    deficit = np.full(n, np.nan, np.float32)
    concentration = np.full(n, np.nan, np.float32)
    ai_status = np.empty(n, np.uint8)
    deficit_status = np.empty(n, np.uint8)
    ucc_thermal = np.empty(n, np.uint8)
    ucc_supply = np.empty(n, np.uint8)
    ucc_supply_status = np.empty(n, np.uint8)
    ucc_modifiers = np.empty(n, np.uint8)

    print(f"Computing descriptors + {PROFILE_CURRENT} classification for {n} cells …")
    for i in range(n):
        d = compute_descriptors(t_monthly[i], p_monthly[i], et_monthly[i])
        desc_f32["t_mean_c"][i] = d.t_mean
        desc_f32["t_min_c"][i] = d.t_min
        desc_f32["t_max_c"][i] = d.t_max
        desc_f32["t_range_c"][i] = d.t_range
        desc_f32["t_below_frac"][i] = d.t_below_frac
        desc_f32["p_mean_mm_per_month"][i] = d.p_mean_rate
        desc_f32["p_total_mm"][i] = d.p_total
        if d.ai is not None:
            ai[i] = d.ai
        ai_status[i] = status_index[d.ai_status]
        if d.deficit is not None:
            deficit[i] = d.deficit
        deficit_status[i] = status_index[d.deficit_status]
        if d.concentration is not None:
            concentration[i] = d.concentration
        c = classify_v1(d, is_land=bool(water_class[i] == "land"))
        ucc_thermal[i] = thermal_index[c.thermal]
        ucc_supply[i] = supply_index[c.supply] if c.supply is not None else 255
        ucc_supply_status[i] = status_index[c.supply_status]
        ucc_modifiers[i] = (1 if c.continental else 0) | (2 if c.water_stress else 0)

    payload = {
        **result_metadata(),
        "num_cells": n,
        "months": 12,
        "dtype": "float32",
        "demand_model": "hamon-1961",
        "demand_daylength_h": 12.0,
        "freeze_threshold_c": 0.0,
        "status_codes": status_codes,
        "profile": PROFILE_CURRENT,
        "thermal_bands": list(THERMAL_BANDS_CURRENT),
        "supply_bands": list(SUPPLY_BANDS_CURRENT),
        # This file is derived from OBSERVED climate (root = real-data anchor),
        # not from the engine — the distinction the reference-anchor rule cares
        # about.  Engine-built exports carry "model".
        "data_source": "observation",
        "provenance": {
            "temperature": "NCEP/NCAR R1 air.mon.ltm (2.5°, monthly climatology)",
            "precipitation": "GPCP v2.3 precip.mon.mean (2.5°, monthly climatology)",
            "note": "UCC descriptors + profile-v0 classification computed from the "
            "observed monthly series; no engine output involved.",
        },
        **{k: v.tobytes() for k, v in desc_f32.items()},
        "ai": ai.tobytes(),
        "ai_status": ai_status.tobytes(),
        "deficit": deficit.tobytes(),
        "deficit_status": deficit_status.tobytes(),
        "concentration": concentration.tobytes(),
        "ucc_thermal": ucc_thermal.tobytes(),
        "ucc_supply": ucc_supply.tobytes(),
        "ucc_supply_status": ucc_supply_status.tobytes(),
        "ucc_modifiers": ucc_modifiers.tobytes(),
    }
    out = map_dir / "climate_yearly.msgpack"
    with out.open("wb") as f:
        f.write(msgpack.packb(payload))
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")

    land = water_class == "land"
    combos = {}
    for i in range(n):
        t = THERMAL_BANDS_CURRENT[ucc_thermal[i]]
        s = SUPPLY_BANDS_CURRENT[ucc_supply[i]] if ucc_supply[i] != 255 else "n-a"
        combos[f"{t}/{s}"] = combos.get(f"{t}/{s}", 0) + 1
    print("Class distribution (top 8):")
    for k, v in sorted(combos.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {k:<24} {v:7d} ({v / n * 100:.1f}%)")
    print(f"Land cells: {int(land.sum())} ({land.mean() * 100:.1f}%)")


if __name__ == "__main__":
    main()
