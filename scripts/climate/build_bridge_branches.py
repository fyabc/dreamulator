#!/usr/bin/env python3
"""Build Earth–Nacrea bridging counterfactual branches (audit shared-physics §8).

Fixed Earth geography, one physical parameter changed toward Nacrea's value per
branch, so the Earth→Nacrea climate difference can be attributed mechanism by
mechanism.  The branches fork at ``astronomy`` (the earliest layer owning the
physical inputs), override a single field in either ``stellar.yaml`` (spectrum /
flux / year) or ``planets.yaml`` (rotation / obliquity / greenhouse), and share
the parent's imported ETOPO1 mesh (no re-import).

Two combination branches go beyond a single axis:

- ``year-tilt`` — year 99.98 d AND obliquity 9° together (tests whether the
  combined short-year + low-obliquity reproduces Nacrea's absent D class).
- ``rotation-derived`` — rotation 3.147 d with ``hadley_extent_deg=0`` (Held-Hou
  derivation instead of the Earth validation config's pinned 30°), so the
  circulation-cell expansion with slower spin is actually visible (audit §6).

The branches are gitignored (``data/worlds/earth/branches/bridge-*/``) — they are
diagnostic counterfactuals, not authored worlds.

Usage::

    uv run python scripts/climate/build_bridge_branches.py --create        # create branches + YAML
    uv run python scripts/climate/build_bridge_branches.py --build year-tilt  # build one
    uv run python scripts/climate/build_bridge_branches.py                 # create + build all
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

# Earth → Nacrea year: P = a^(3/2)/sqrt(M).  For M=1.0, P=99.98 d → a ≈ 0.4218 AU.
# Keep flux L/a^2 = 1.0 → L = a^2 ≈ 0.1779.
_YEAR_SMA_AU = 0.4218
_YEAR_LUM = 0.1779

_AXES: list[str] = [
    "rotation",
    "tilt",
    "greenhouse",
    "spectrum",
    "flux",
    "year",
    "year-tilt",
    "rotation-derived",
]

_AXIS_DESC: dict[str, str] = {
    "rotation": "rotation 0.9973 -> 3.147 d",
    "tilt": "obliquity 23.44 -> 9.0 deg",
    "greenhouse": "greenhouse 33 -> 62 K",
    "spectrum": "T_eff 5772 -> 4055 K (flux kept)",
    "flux": "luminosity 1.0 -> 0.61 (spectrum kept)",
    "year": "year 365.25 -> 99.98 d (flux kept)",
    "year-tilt": "year 99.98 d + obliquity 9 deg",
    "rotation-derived": "rotation 3.147 d + hadley_extent derived",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _earth_dir() -> Path:
    return _project_root() / "data" / "worlds" / "earth"


def _load(rel: str) -> Any:
    with (_earth_dir() / rel).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_planets() -> Any:
    return _load("layers/geological/input/planets.yaml")


def _load_stellar() -> Any:
    return _load("layers/astronomy/input/stellar.yaml")


def _load_terrain() -> Any:
    return _load("layers/geological/input/terrain_config.yaml")


def _set_year(stellar: Any) -> None:
    """Year 365.25 → 99.98 d (orbit a) with flux kept (luminosity compensation)."""
    for orb in stellar["orbits"]:
        if orb.get("body_id") == "planet_earth":
            orb["semi_major_axis_au"] = _YEAR_SMA_AU
    for star in stellar["stars"]:
        if star.get("id") == "star_sol":
            star["luminosity"] = _YEAR_LUM


# file -> (filename in the branch input dir, layer)
_FILE_LAYOUT: dict[str, tuple[str, str]] = {
    "planets": ("planets.yaml", "geological"),
    "stellar": ("stellar.yaml", "astronomy"),
    "terrain": ("terrain_config.yaml", "geological"),
}


def _overrides(axis: str) -> dict[str, Any]:
    """Return {file: doc} for every input file this branch overrides."""
    planets = _load_planets()
    stellar = _load_stellar()
    terrain = _load_terrain()

    if axis == "rotation":
        planets["planets"][0]["rotation_period_days"] = 3.147
        return {"planets": planets}
    if axis == "tilt":
        planets["planets"][0]["axial_tilt_deg"] = 9.0
        return {"planets": planets}
    if axis == "greenhouse":
        planets["planets"][0]["atmosphere"]["greenhouse_factor"] = 62.0
        return {"planets": planets}
    if axis == "spectrum":
        stellar["stars"][0]["temperature"] = 4055.0
        return {"stellar": stellar}
    if axis == "flux":
        stellar["stars"][0]["luminosity"] = 0.61
        return {"stellar": stellar}
    if axis == "year":
        _set_year(stellar)
        return {"stellar": stellar}
    if axis == "year-tilt":
        _set_year(stellar)
        planets["planets"][0]["axial_tilt_deg"] = 9.0
        return {"stellar": stellar, "planets": planets}
    if axis == "rotation-derived":
        planets["planets"][0]["rotation_period_days"] = 3.147
        terrain["climate"]["hadley_extent_deg"] = 0.0
        return {"planets": planets, "terrain": terrain}
    raise ValueError(f"unknown axis: {axis}")


def create_branches(axes: list[str], *, force: bool = False) -> None:
    mgr = BranchManager(_earth_dir())
    for axis in axes:
        name = f"bridge-{axis}"
        try:
            mgr.create_branch(name, "astronomy", description=f"bridge: {_AXIS_DESC[axis]}")
        except FileExistsError:
            if not force:
                print(f"  {name}: exists, skipping create (use --force to recreate)")
                continue
            raise
        overrides = _overrides(axis)
        for file, doc in overrides.items():
            fname, layer = _FILE_LAYOUT[file]
            out = _earth_dir() / "branches" / name / "layers" / layer / "input"
            out.mkdir(parents=True, exist_ok=True)
            with (out / fname).open("w", encoding="utf-8") as fh:
                yaml.safe_dump(doc, fh, allow_unicode=True, sort_keys=False)
        files = ", ".join(overrides)
        print(f"  {name}: created ({files} override)")


def build_branches(axes: list[str]) -> None:
    engines = get_all_engines()
    world_dir = _earth_dir()
    for axis in axes:
        name = f"bridge-{axis}"
        print(f"\n=== building {name} ===")
        run_pipeline(engines, world_dir, 42, only_engine="climate", branch=name)
        _copy_base_terrain(name)


def _copy_base_terrain(branch: str) -> None:
    """Copy the parent's base-terrain siblings into the branch's maps dir.

    The climate engine materializes only ``cvt_mesh.json`` into a branch that
    forked before geological (``_materialize_writable_mesh``); the frontend's
    ``meta``/``elevation``/``plates`` endpoints also need ``elevation.png`` /
    ``map.yaml`` / ``plates.json``, which are read-only here, so copy them once
    (idempotent).
    """
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
        metavar="AXIS",
        help="Build the given bridge branches (default: all)",
    )
    parser.add_argument("--force", action="store_true", help="Recreate existing branches")
    args = parser.parse_args()

    do_all = args.build is None and not args.create
    axes = _AXES if do_all else (args.build or _AXES)

    unknown = [a for a in axes if a not in _AXES]
    if unknown:
        parser.error(f"unknown axis(es): {', '.join(unknown)} (choose from {', '.join(_AXES)})")

    if args.create or do_all:
        create_branches(axes, force=args.force)
    if args.build or do_all:
        build_branches(axes)


if __name__ == "__main__":
    main()
