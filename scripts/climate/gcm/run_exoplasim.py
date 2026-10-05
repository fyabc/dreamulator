#!/usr/bin/env python
"""Run ExoPlaSim for a dreamulator world (offline GCM oracle).

Maps world inputs to ExoPlaSim parameters (dreamulator.gcm.mapping), runs the
model for N continuous years, writes a provenance manifest, extracts
diagnostics and renders overview.png.  Needs the ``[gcm]`` extra and a
Fortran toolchain — see scripts/climate/gcm/bootstrap.sh.

Examples:
    # Nacrea, 2 sanity years (wind-aliveness smoke test)
    python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea \
        --planet satellite_nacrea --years 2 --workdir runs/nacrea_t21

    # Diagnose an existing run without re-running
    python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea \
        --planet satellite_nacrea --nc runs/nacrea_t21/MOST.00000.nc
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from a source checkout without installation.
SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dreamulator.gcm.diagnostics import summarize  # noqa: E402
from dreamulator.gcm.mapping import map_world  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--world", required=True, help="world directory or name (e.g. data/worlds/nacrea)"
    )
    ap.add_argument(
        "--planet", required=True, help="planet id in planets.yaml (e.g. satellite_nacrea)"
    )
    ap.add_argument(
        "--host",
        default=None,
        help="host body id for insolation (satellites: the host "
        "planet; default: resolved from 'orbits')",
    )
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--resolution", default="T21")
    ap.add_argument("--layers", type=int, default=10)
    ap.add_argument("--ncpus", type=int, default=1)
    ap.add_argument(
        "--workdir", default=None, help="run directory (default: gcm_runs/<planet>_<resolution>)"
    )
    ap.add_argument("--greenhouse-mode", choices=["none", "flux_boost", "pco2"], default="none")
    ap.add_argument("--flux-boost-factor", type=float, default=None)
    ap.add_argument("--pco2-bar", type=float, default=None)
    ap.add_argument(
        "--override",
        default="{}",
        help="JSON dict of ExoPlaSimParams field overrides, e.g. '{\"year\": 99.7}'",
    )
    ap.add_argument(
        "--landmap",
        default=None,
        help="path to a .sra land-mask file (see make_landmap.py); "
        "without it the run is an aquaplanet",
    )
    ap.add_argument("--nc", default=None, help="existing .nc to diagnose (skips the run)")
    ap.add_argument("--no-plot", action="store_true")
    return ap.parse_args(argv)


def resolve_world(world: str) -> Path:
    path = Path(world)
    if path.is_dir():
        return path
    default = Path(__file__).resolve().parents[3] / "data" / "worlds" / world
    if default.is_dir():
        return default
    raise SystemExit(f"world not found: {world!r} (also tried {default})")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    world = resolve_world(args.world)
    overrides = json.loads(args.override)
    params = map_world(
        world,
        args.planet,
        host_body_id=args.host,
        greenhouse_mode=args.greenhouse_mode,
        flux_boost_factor=args.flux_boost_factor,
        pco2_bar=args.pco2_bar,
        overrides=overrides,
    )
    print(f"[map] {args.planet}: {json.dumps(params.to_configure_kwargs(), indent=2)}")
    for warning in params.warnings:
        print(f"[warn] {warning}", file=sys.stderr)

    if args.nc:
        nc_path = Path(args.nc)
    else:
        from dreamulator.gcm.runner import run_gcm

        workdir = args.workdir or f"gcm_runs/{args.planet}_{args.resolution}"
        outputs = run_gcm(
            params,
            workdir,
            years=args.years,
            resolution=args.resolution,
            layers=args.layers,
            ncpus=args.ncpus,
            input_files={
                "planets": world / "layers/geological/input/planets.yaml",
                "stellar": world / "layers/astronomy/input/stellar.yaml",
            },
            landmap=args.landmap,
        )
        nc_path = outputs["nc"]

    summary = summarize(nc_path, radius_m=params.radius * 6_371_220.0, gravity=params.gravity)
    out_json = nc_path.parent / "summary.json"
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[summary] {json.dumps(summary, indent=2, ensure_ascii=False)}")

    if not args.no_plot:
        from dreamulator.gcm.plotting import plot_overview

        png = plot_overview(nc_path, radius_m=params.radius * 6_371_220.0, gravity=params.gravity)
        print(f"[plot] {png}")
    return 0 if summary.get("wind_alive", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
