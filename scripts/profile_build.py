"""World build profiler: stage breakdown + optional tracemalloc allocations.

Two modes:
  default   — run ``dreamulator build`` in a subprocess, then display the
              structured build_profile.json (per-engine / per-stage wall clock).
  --memory  — run the pipeline in-process under tracemalloc and additionally
              display the top allocation sites.

Flame graphs (sampling profiler, recommended for hotspot analysis):

    uv run py-spy record -o private/prof/flame.svg -- \
        uv run dreamulator build WORLD --force

See docs/usage/profiling.md for the full workflow.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _print_profile(world_dir: Path) -> None:
    profile_path = world_dir / "build_profile.json"
    if not profile_path.exists():
        print(f"No build_profile.json found at {profile_path}")
        return
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    total = float(profile["total_wall_seconds"])
    branch = profile.get("branch")
    label = profile["world"] + (f" [{branch}]" if branch else "")
    print(f"\nBuild profile: {label} (seed={profile['seed']}, total {total:.1f}s)")
    for rec in profile["engines"]:
        share = 100.0 * rec["wall_seconds"] / max(total, 1e-9)
        status = "ok" if rec["success"] else "FAILED"
        print(f"  {rec['engine']:<12} {rec['wall_seconds']:8.1f}s  {share:4.0f}%  {status}")
        for name, secs in sorted((rec.get("stages") or {}).items(), key=lambda kv: -kv[1]):
            if secs >= 0.02 * total:
                print(f"    {name:<24} {secs:8.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile a dreamulator world build.",
    )
    parser.add_argument("world", help="World name")
    parser.add_argument("--data-dir", default="data/worlds", help="Worlds data directory")
    parser.add_argument("--branch", default=None, help="Branch to build")
    parser.add_argument(
        "--memory",
        action="store_true",
        help="In-process run under tracemalloc (shows top allocations)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    world_dir = data_dir / args.world
    if not world_dir.exists():
        sys.exit(f"World not found: {world_dir}")

    if args.memory:
        import tracemalloc

        import yaml  # type: ignore[import-untyped]

        from dreamulator.engine import get_all_engines
        from dreamulator.engine.pipeline import run_pipeline

        wdata = yaml.safe_load((world_dir / "world.yaml").read_text(encoding="utf-8")) or {}
        seed = int(wdata.get("seed", 42))

        tracemalloc.start()
        results = run_pipeline(
            get_all_engines(), world_dir, seed, force=True, branch=args.branch
        )
        snapshot = tracemalloc.take_snapshot()
        print("\nTop allocation sites (tracemalloc):")
        for stat in snapshot.statistics("lineno")[:15]:
            print(" ", stat)
        if any(not r.success for r in results):
            sys.exit(1)
    else:
        cmd = ["dreamulator", "build", args.world, "--force", "--data-dir", str(data_dir)]
        if args.branch:
            cmd += ["--branch", args.branch]
        completed = subprocess.run(cmd)
        if completed.returncode != 0:
            sys.exit(completed.returncode)

    _print_profile(world_dir)


if __name__ == "__main__":
    main()
