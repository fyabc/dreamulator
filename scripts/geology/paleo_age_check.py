#!/usr/bin/env python3
"""Geological timeline G3, step 1: check the synthetic seafloor ages on the earth map.

Synthesises seafloor ages from the present plates and poles of a built map
(``paleo_kinematics.synthesize_seafloor_age``, engine poles), samples an observed
age grid at the same cells, and reports the error for all seafloor and for the
particles that do and do not pass the solver's isochron self-consistency check
(``paleo_solver.build_setup``).  The check is meant to keep the seafloor whose
synthetic age can be trusted; on the earth map (PB2002 plates) this is
measurable against observation (§9, item 1).

The observed grid is a netCDF ``lon``/``lat``/``z`` grid in Myr, e.g. Seton et al.
2020 (https://www.earthbyte.org/webdav/ftp/earthbyte/agegrid/2020/Grids/
age.2020.1.GeeK2007.6m.nc); reading it needs the ``validation`` extra.

Usage::

    uv run python scripts/geology/paleo_age_check.py data/worlds/earth/maps/planet_earth \\
        --observed-age age.2020.1.GeeK2007.6m.nc --out-dir /tmp/age_check
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from paleo_rewind import World, sample_observed_age

from dreamulator.map.paleo_blocks import build_blocks
from dreamulator.map.paleo_kinematics import (
    boundary_cells,
    continental_speed_poles,
    ridge_half_rates,
    synthesize_seafloor_age,
)
from dreamulator.map.paleo_solver import SolverConfig, build_setup
from dreamulator.map.paleo_walk import continental_rifts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path)
    ap.add_argument("--observed-age", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--ocean-particles", type=int, default=20000)
    args = ap.parse_args()

    w = World(args.map_dir)
    kin = replace(w.kin, omega=continental_speed_poles(w.kin))
    _, onsets = continental_rifts(kin, 300.0)
    blocks = build_blocks(kin, [], onsets)
    half, offset = ridge_half_rates(w.kin, boundary_cells(w.kin))
    age, source = synthesize_seafloor_age(w.kin, half, offset)
    config = SolverConfig(n_ocean_particles=args.ocean_particles)
    setup = build_setup(kin, blocks, w.kin.omega, kin.omega, age, source, half, config)

    cells = setup.tree.query(setup.p0)[1]
    obs = sample_observed_age(args.observed_age, w.lon[cells], w.lat[cells])
    sea = setup.ocean & np.isfinite(obs)
    on_ridge = sea & np.isin(cells, np.flatnonzero(setup.cell_ridge >= 0))
    groups = {
        "all_seafloor_within_memory": sea,
        "ridge_passes_check": on_ridge & (setup.ridge >= 0),
        "ridge_fails_check": on_ridge & (setup.ridge < 0),
    }
    out: dict[str, dict[str, float]] = {}
    for name, m in groups.items():
        err = np.abs(setup.age[m] - obs[m])
        out[name] = {
            "particles": int(m.sum()),
            "age_p50_myr": round(float(np.median(setup.age[m])), 1),
            "age_p90_myr": round(float(np.percentile(setup.age[m], 90)), 1),
            "abs_err_p50_myr": round(float(np.median(err)), 1),
            "abs_err_p90_myr": round(float(np.percentile(err, 90)), 1),
        }
        print(name, out[name])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "age_check.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
