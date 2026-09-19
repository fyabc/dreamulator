#!/usr/bin/env python3
"""Build Nacrea→Earth bridging counterfactual branches (Phase 2 of the bridge experiment).

Fixed Nacrea geography (the authored ``satellite_nacrea`` mesh), one physical
parameter moved toward Earth's value per branch, so the Nacrea→Earth climate
difference is attributed mechanism by mechanism — the mirror of
``build_bridge_branches.py`` (Earth→Nacrea).  Branches fork at ``astronomy``,
override a single field in ``stellar.yaml`` (flux / year) or ``planets.yaml``
(rotation / obliquity / greenhouse), and share the parent's generated mesh
(no re-import — ``_materialize_writable_mesh`` materialises a branch copy).

Axes (Nacrea value → Earth value, fixed Nacrea geography):

- ``tilt`` — obliquity 9.0 → 23.44 deg (planets.yaml)
- ``rotation`` — rotation 3.147 → 0.9973 d (planets.yaml; the 90° single-cell
  Hadley pin stays, so this isolates rotation's *direct* effect — Coriolis,
  thermal wind — not the circulation-regime flip, which is a separate axis)
- ``greenhouse`` — greenhouse 62 → 33 K (planets.yaml)
- ``flux`` — luminosity 0.0761 → 0.1250 L☉ (flux 0.61 → 1.0 × Earth at fixed
  a=0.3536; year unchanged)
- ``year`` — Aegis's orbit a 0.3536 → 0.8387 AU (99.98 → 365.25 d) with
  luminosity 0.0761 → 0.4282 L☉ so the received flux stays 0.61 × Earth
  ("保通量").  This breaks the 1:2:4 resonance chain (Aegis overtakes Boreal),
  which is harmless here: the climate engine reads only Aegis's heliocentric
  orbit and Ignis's luminosity/mass.

**``spectrum`` is deliberately omitted.**  The astronomy engine derives
``computed_temperature`` from mass + luminosity (Stefan–Boltzmann), ignoring an
explicit ``temperature`` field, so T_eff cannot be varied independently of
flux/year (at fixed flux + year it is fully determined by M).  The Earth-side
``spectrum`` axis was therefore a no-op (its explicit ``temperature: 4055`` was
recomputed back to 5772 by the bootstrap); mirroring it here would be too.

Nacrea specifics that stay fixed in every branch (not sensitivity axes):
``sub_planet_warming_c`` / ``sub_planet_longitude_deg`` (sub-Aegis warming),
``ice_albedo_max_cooling_c`` 3.0 (K-dwarf ice albedo), ``hadley_extent_deg`` 90
(single-cell), ``ebm_1d`` true.

The branches are gitignored (``data/worlds/nacrea/branches/bridge-*/``) — they
are diagnostic counterfactuals, not authored worlds.

Usage::

    uv run python scripts/climate/build_bridge_branches_nacrea.py --create  # create branches + YAML
    uv run python scripts/climate/build_bridge_branches_nacrea.py --build year  # build one
    uv run python scripts/climate/build_bridge_branches_nacrea.py           # create + build all
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

# Nacrea → Earth year: P = a^(3/2)/sqrt(M).  For M=0.59, P=365.25 d → a ≈ 0.8387 AU.
# Keep flux L/a^2 = 0.61 → L = 0.0761 × (0.8387/0.3536)^2 ≈ 0.4282.
_YEAR_SMA_AU = 0.8387
_YEAR_LUM = 0.4282
# Flux 0.61 → 1.0 × Earth at fixed a=0.3536: L = a^2 = 0.3536^2.
_FLUX_LUM = 0.1250

_PLANET_ID = "satellite_nacrea"
_HOST_ID = "planet_aegis"

_AXES: list[str] = ["tilt", "rotation", "greenhouse", "flux", "year"]

_AXIS_DESC: dict[str, str] = {
    "tilt": "obliquity 9.0 -> 23.44 deg",
    "rotation": "rotation 3.147 -> 0.9973 d (90 deg Hadley pin kept)",
    "greenhouse": "greenhouse 62 -> 33 K",
    "flux": "luminosity 0.0761 -> 0.1250 Lsun (flux 0.61 -> 1.0)",
    "year": "year 99.98 -> 365.25 d (flux kept)",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _nacrea_dir() -> Path:
    return _project_root() / "data" / "worlds" / "nacrea"


def _load(rel: str) -> Any:
    with (_nacrea_dir() / rel).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_planets() -> Any:
    return _load("layers/geological/input/planets.yaml")


def _load_stellar() -> Any:
    return _load("layers/astronomy/input/stellar.yaml")


# file -> (filename in the branch input dir, layer)
_FILE_LAYOUT: dict[str, tuple[str, str]] = {
    "planets": ("planets.yaml", "geological"),
    "stellar": ("stellar.yaml", "astronomy"),
}


def _overrides(axis: str) -> dict[str, Any]:
    """Return {file: doc} for every input file this branch overrides."""
    planets = _load_planets()
    stellar = _load_stellar()

    p0 = planets["planets"][0]  # satellite_nacrea is the first planets.yaml entry
    star = stellar["stars"][0]  # star_ignis

    if axis == "tilt":
        p0["axial_tilt_deg"] = 23.44
        return {"planets": planets}
    if axis == "rotation":
        p0["rotation_period_days"] = 0.9973
        return {"planets": planets}
    if axis == "greenhouse":
        p0["atmosphere"]["greenhouse_factor"] = 33.0
        return {"planets": planets}
    if axis == "flux":
        star["luminosity"] = _FLUX_LUM
        return {"stellar": stellar}
    if axis == "year":
        for orb in stellar["orbits"]:
            if orb.get("body_id") == _HOST_ID:
                orb["semi_major_axis_au"] = _YEAR_SMA_AU
        star["luminosity"] = _YEAR_LUM
        return {"stellar": stellar}
    raise ValueError(f"unknown axis: {axis}")


def create_branches(axes: list[str], *, force: bool = False) -> None:
    mgr = BranchManager(_nacrea_dir())
    for axis in axes:
        name = f"bridge-{axis}"
        try:
            mgr.create_branch(name, "astronomy", description=f"bridge (nacrea): {_AXIS_DESC[axis]}")
        except FileExistsError:
            if not force:
                print(f"  {name}: exists, skipping create (use --force to recreate)")
                continue
            raise
        overrides = _overrides(axis)
        for file, doc in overrides.items():
            fname, layer = _FILE_LAYOUT[file]
            out = _nacrea_dir() / "branches" / name / "layers" / layer / "input"
            out.mkdir(parents=True, exist_ok=True)
            with (out / fname).open("w", encoding="utf-8") as fh:
                yaml.safe_dump(doc, fh, allow_unicode=True, sort_keys=False)
        files = ", ".join(overrides)
        print(f"  {name}: created ({files} override)")


def build_branches(axes: list[str]) -> None:
    engines = get_all_engines()
    world_dir = _nacrea_dir()
    for axis in axes:
        name = f"bridge-{axis}"
        print(f"\n=== building {name} ===")
        run_pipeline(engines, world_dir, 42, only_engine="climate", branch=name)
        _copy_base_terrain(name)


def _copy_base_terrain(branch: str) -> None:
    """Copy the parent's base-terrain siblings into the branch's maps dir.

    The climate engine materialises only ``cvt_mesh.json`` into a branch that
    forked before geological (``_materialize_writable_mesh``); the frontend's
    ``meta``/``elevation``/``plates`` endpoints also need ``elevation.png`` /
    ``map.yaml`` / ``plates.json``, which are read-only here, so copy them once
    (idempotent).
    """
    src = _nacrea_dir() / "maps" / _PLANET_ID
    dst = _nacrea_dir() / "branches" / branch / "maps" / _PLANET_ID
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
