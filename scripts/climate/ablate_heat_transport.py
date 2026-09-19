#!/usr/bin/env python3
"""Ablate Earth's heat-transport mechanisms to quantify double-counting (audit §2.6).

The climate engine expresses meridional heat transport through several
mechanisms at once (audit ``climate-pipeline-rethinking`` §2.6 line 102 —
"总热扩散、沿海弛豫、向风平流、洋流 SST 修正" all active simultaneously):

- ``ebm_1d`` — the diffusive EBM, the *baseline* meridional transport (NOT
  ablated here; it is the reference against which the others are measured);
- ``ocean_currents_enabled`` — Stommel-gyre SST correction + the ocean→land
  anomaly advection ("洋流 SST 修正" + "向风平流");
- ``maritime_advection_scale_km`` — directional coastal relaxation ("沿海弛豫");
- ``ocean_upwelling_enabled`` — upwelling SST cooling.

This script disables each non-baseline mechanism one at a time (fork at
``astronomy``, override ``terrain_config.yaml`` in the branch's geological
layer, build ``--only climate`` so the terrain is inherited) and reports the
global/land temperature + precipitation, so each mechanism's contribution —
and any overlap between them — is measured rather than assumed.

The branches are gitignored (``data/worlds/earth/branches/bridge-*/``) — they
are diagnostic counterfactuals, not authored worlds.

Usage::

    uv run python scripts/climate/ablate_heat_transport.py --create  # create branches + YAML
    uv run python scripts/climate/ablate_heat_transport.py --build   # build all
    uv run python scripts/climate/ablate_heat_transport.py           # create + build all
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

import yaml

from dreamulator.branch_manager import BranchManager
from dreamulator.engine import get_all_engines
from dreamulator.engine.pipeline import run_pipeline

# Mechanism -> {climate-section key: disabling value}.  The EBM diffusion is the
# baseline and is deliberately absent from this table.
_MECHANISMS: dict[str, dict[str, Any]] = {
    "ocean-currents": {"ocean_currents_enabled": False},
    "upwelling": {"ocean_upwelling_enabled": False},
    "maritime": {"maritime_advection_scale_km": 0.0},
}

_AXES: list[str] = list(_MECHANISMS)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _earth_dir() -> Path:
    return _project_root() / "data" / "worlds" / "earth"


def _load_terrain() -> dict[str, Any]:
    p = _earth_dir() / "layers" / "geological" / "input" / "terrain_config.yaml"
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _override(mechanism: str) -> dict[str, Any]:
    doc = _load_terrain()
    climate = doc.setdefault("climate", {})
    climate.update(_MECHANISMS[mechanism])
    return doc


def create_branches(mechanisms: list[str], *, force: bool = False) -> None:
    mgr = BranchManager(_earth_dir())
    for mech in mechanisms:
        name = f"bridge-{mech}"
        try:
            mgr.create_branch(name, "astronomy", description=f"ablate heat transport: {mech}")
        except FileExistsError:
            if not force:
                print(f"  {name}: exists, skipping create (use --force to recreate)")
                continue
            raise
        out = _earth_dir() / "branches" / name / "layers" / "geological" / "input"
        out.mkdir(parents=True, exist_ok=True)
        with (out / "terrain_config.yaml").open("w", encoding="utf-8") as fh:
            yaml.safe_dump(_override(mech), fh, allow_unicode=True, sort_keys=False)
        print(f"  {name}: created ({', '.join(_MECHANISMS[mech])})")


def build_branches(mechanisms: list[str]) -> None:
    engines = get_all_engines()
    world_dir = _earth_dir()
    for mech in mechanisms:
        name = f"bridge-{mech}"
        print(f"\n=== building {name} ===")
        run_pipeline(engines, world_dir, 42, only_engine="climate", branch=name)
        _copy_base_terrain(name)


def _copy_base_terrain(branch: str) -> None:
    """Copy the parent's base-terrain siblings into the branch's maps dir."""
    src = _earth_dir() / "maps" / "planet_earth"
    dst = _earth_dir() / "branches" / branch / "maps" / "planet_earth"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("elevation.png", "map.yaml", "plates.json"):
        s, d = src / name, dst / name
        if s.exists() and not d.exists():
            shutil.copyfile(s, d)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", help="Create branches + YAML overrides")
    parser.add_argument(
        "--build",
        nargs="*",
        default=None,
        metavar="MECH",
        help="Build the given ablation branches (default: all)",
    )
    parser.add_argument("--force", action="store_true", help="Recreate existing branches")
    args = parser.parse_args()

    do_all = args.build is None and not args.create
    mechs = _AXES if do_all else (args.build or _AXES)

    unknown = [m for m in mechs if m not in _AXES]
    if unknown:
        parser.error(f"unknown mechanism(s): {', '.join(unknown)} (choose from {', '.join(_AXES)})")

    if args.create or do_all:
        create_branches(mechs, force=args.force)
    # `--build` with no value gives an empty list (falsy), so test for "passed"
    # rather than truthiness — `--build` alone should build all, like the bare call.
    if args.build is not None or do_all:
        build_branches(mechs)


if __name__ == "__main__":
    main()
