#!/usr/bin/env python3
"""Rebuild worlds in-place on ``data/worlds`` and publish the data to a GitHub Release.

Target architecture (post-LFS): git tracks only authored input + code. The generated
maps (large, slow) and derived YAML (small, fast) are gitignored
(``data/worlds/**/maps/`` + ``data/worlds/**/derived/``) and published as a single
tarball on a fixed GitHub Release tag ``worlds-data``; the Pages deploy workflow
downloads that tarball before running the static export.

This script performs the whole "rebuild + publish" loop in one command:

  1. Rebuild each world in-place on ``data/worlds`` (the default data dir; the output
     is gitignored, so it does not dirty the working tree). Procedural worlds run
     ``dreamulator build``; imported (real-data) worlds such as ``earth`` run their
     importer scripts instead.
  2. Package the generated maps + derived into a tarball.
  3. Upload the tarball to the ``worlds-data`` release.

Usage::

    uv run python scripts/release/publish_world_data.py                 # rebuild all + publish
    uv run python scripts/release/publish_world_data.py --worlds nacrea # rebuild one world
    uv run python scripts/release/publish_world_data.py --skip-build    # publish only (built)
    uv run python scripts/release/publish_world_data.py --dry-run       # build+package, no upload
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

DEFAULT_TAG = "worlds-data"
TARBALL_NAME = "worlds-data.tar.gz"
DEFAULT_WORLDS = ("nacrea", "earth")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dreamulator_cli() -> Path:
    """The ``dreamulator`` console script next to the running interpreter.

    Invoking it directly (rather than ``uv run dreamulator``) avoids the package
    rebuild that ``uv run`` triggers on every source change, and so avoids the
    ``.exe`` file-lock problem when an IDE holds the venv open.
    """
    name = "dreamulator.exe" if sys.platform == "win32" else "dreamulator"
    return Path(sys.executable).with_name(name)


def _build_world(world: str, worlds_dir: Path) -> None:
    cli = _dreamulator_cli()
    if cli.exists():
        cmd = [str(cli), "build", world, "--force", "--data-dir", str(worlds_dir)]
    else:
        # Fallback: uv run (slower, but works if the console script is missing).
        cmd = ["uv", "run", "dreamulator", "build", world, "--force", "--data-dir", str(worlds_dir)]
    print(f"Building '{world}' ...")
    subprocess.run(cmd, check=True)


# Real-data (imported) worlds are not procedurally generated — their ``maps/``
# comes from dedicated import scripts, not ``dreamulator build``.  Each entry
# lists the importer modules to run, in dependency order (see
# docs/design/pipelines/earth-real-data.md §3).  The raw data is cached in the
# system temp dir and re-downloaded automatically when missing.
_IMPORTED_WORLDS: dict[str, list[tuple[str, list[str]]]] = {
    "earth": [
        ("import_earth_elevation", ["--resolution", "4096x2048", "--mesh-nodes", "200000",
                                    "--seed", "42", "--skip-download"]),
        ("import_earth_tectonics", []),
        ("import_earth_watermask", []),
        ("import_earth_climate", []),
    ],
}


def _import_world(world: str, worlds_dir: Path) -> None:
    """Rebuild an imported world by running its importer scripts in order.

    The elevation importer's default ``--output-dir`` is a legacy layer path, so
    the real ``maps/<planet>/`` dir is always passed explicitly; the remaining
    importers read the mesh already written there.
    """
    out_dir = worlds_dir / world / "maps" / "planet_earth"
    out_dir.mkdir(parents=True, exist_ok=True)
    py = str(Path(sys.executable))
    scripts_dir = _project_root() / "scripts" / "earth"  # importers live in scripts/earth/
    for module, extra_args in _IMPORTED_WORLDS[world]:
        script = scripts_dir / f"{module}.py"
        cmd = [py, str(script), "--output-dir", str(out_dir), *extra_args]
        print(f"Importing '{world}' via {module} ...")
        subprocess.run(cmd, check=True, cwd=str(_project_root()))


def _is_generated_maps_dir(path: Path) -> bool:
    """A generated ``maps`` dir never sits under ``layers/`` (that is the
    import-elevation staging area ``layers/geological/input/maps/``)."""
    return path.name == "maps" and "layers" not in path.parts


def _is_derived_dir(path: Path) -> bool:
    """A ``derived`` dir must live at ``layers/<layer>/derived``."""
    return path.name == "derived" and path.parent.parent.name == "layers"


def _is_scratch(path: Path) -> bool:
    """Dev-scratch / backup artifacts that must not be published (climate_diff
    baselines like ``_baseline``, pickle caches like ``_cache``, ``*.bak``)."""
    if path.suffix == ".bak":
        return True
    return any(part.startswith("_") for part in path.parts)


def collect_generated(worlds_dir: Path) -> list[Path]:
    """Collect generated files: ``maps/**`` and ``layers/*/derived/**``, including
    branch subtrees (``branches/<b>/maps/...``, ``branches/<b>/layers/*/derived/...``)."""
    files: list[Path] = []
    for world in sorted(worlds_dir.iterdir()):
        if not world.is_dir() or world.name.startswith("."):
            continue
        for maps_dir in world.rglob("maps"):
            if maps_dir.is_dir() and _is_generated_maps_dir(maps_dir):
                files.extend(p for p in maps_dir.rglob("*") if p.is_file() and not _is_scratch(p))
        for derived_dir in world.rglob("derived"):
            if derived_dir.is_dir() and _is_derived_dir(derived_dir):
                files.extend(
                    p for p in derived_dir.rglob("*") if p.is_file() and not _is_scratch(p)
                )
    return files


def _package(worlds_dir: Path, tar_path: Path) -> int:
    files = collect_generated(worlds_dir)
    if not files:
        print(f"No generated data found under {worlds_dir}", file=sys.stderr)
        return 0
    with tarfile.open(tar_path, "w:gz") as tar:
        for path in files:
            tar.add(path, arcname=str(path.relative_to(worlds_dir)))
    print(f"Packaged {len(files)} file(s) into {tar_path}")
    return len(files)


def _upload(tar_path: Path, tag: str) -> None:
    # Create the release if it does not exist yet (a non-zero exit on an
    # existing tag is expected and harmless); then upload with overwrite.
    subprocess.run(
        [
            "gh",
            "release",
            "create",
            tag,
            "--title",
            "World build data",
            "--notes",
            "Generated maps + derived data for the static site. Published by "
            "scripts/release/publish_world_data.py.",
            "--prerelease",
        ],
        check=False,
    )
    subprocess.run(["gh", "release", "upload", tag, str(tar_path), "--clobber"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worlds",
        nargs="*",
        default=list(DEFAULT_WORLDS),
        help="Worlds to rebuild (default: nacrea earth)",
    )
    parser.add_argument(
        "--worlds-dir",
        type=Path,
        default=None,
        help="Worlds directory (default: data/worlds)",
    )
    parser.add_argument("--tag", default=DEFAULT_TAG, help="Release tag")
    parser.add_argument(
        "--skip-build", action="store_true", help="Publish only, skip the build step"
    )
    parser.add_argument("--dry-run", action="store_true", help="Build + package, but do not upload")
    args = parser.parse_args()

    root = _project_root()
    worlds_dir = (args.worlds_dir or (root / "data" / "worlds")).resolve()

    if not args.skip_build:
        for world in args.worlds:
            if world in _IMPORTED_WORLDS:
                _import_world(world, worlds_dir)
            else:
                _build_world(world, worlds_dir)

    if not worlds_dir.is_dir():
        print(f"Worlds directory not found: {worlds_dir}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / TARBALL_NAME
        if _package(worlds_dir, tar_path) == 0:
            sys.exit(1)
        if args.dry_run:
            print("Dry run: not uploading.")
            return
        _upload(tar_path, args.tag)
        print(f"Uploaded to release '{args.tag}'")


if __name__ == "__main__":
    main()
