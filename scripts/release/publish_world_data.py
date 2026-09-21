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
# comes from dedicated import scripts, not ``dreamulator build``.  Each step is
# ``(scripts subdir, module, cli style, extra args)``; two CLI conventions exist:
#   "output-dir" — scripts/earth importers take ``--output-dir <maps/<planet_id>>``
#   "data-dir"   — scripts/solar importers take ``--data-dir <worlds root>`` and
#                  register their own planet_id (import_solar_common.register_solar_planet)
# The raw data is cached (system temp dir for earth; ``private/tmp/solar/`` for
# the solar bodies).  DEMs auto-download when missing; the climate sources
# (MCD/VCD ASCII slices, Diviner GCP bands, TAM nc) do NOT — they must be
# pre-fetched per docs/knowledge/planetary_science/solar_system_data_sources.md.
_IMPORTED_WORLDS: dict[str, list[tuple[str, str, str, list[str]]]] = {
    "earth": [
        (
            "earth",
            "import_earth_elevation",
            "output-dir",
            [
                "--resolution",
                "4096x2048",
                "--mesh-nodes",
                "200000",
                "--seed",
                "42",
                "--skip-download",
            ],
        ),
        ("earth", "import_earth_tectonics", "output-dir", []),
        ("earth", "import_earth_watermask", "output-dir", []),
        ("earth", "import_earth_climate", "output-dir", []),
        # UCC yearly descriptors + profile-v0 classification derived from the
        # OBSERVED monthly climate (the root is never built — this importer-side
        # script is the obs counterpart of the engine's yearly export block).
        ("earth", "export_earth_yearly", "output-dir", []),
        # Solar-system reference bodies live inside the earth world as planet
        # maps (UCC-01 4d).  Mesh sizes follow each body's climate-data
        # resolution (Mars 10k / Moon 100k / Venus 10k / Titan 3k — defaults
        # baked into the importers).
        ("solar", "import_mars", "data-dir", []),
        ("solar", "import_moon", "data-dir", []),
        ("solar", "import_venus", "data-dir", []),
        ("solar", "import_titan", "data-dir", []),
    ],
}

# Imported worlds whose astronomy derived layer must also be refreshed before
# packaging: the static site's body selector reads the derived system catalog
# (merged stellar.yaml), so a newly added satellite is invisible on Pages until
# this layer is rebuilt.  Astronomy only — the earth-root-never-built anchor
# rule targets the climate/model layers, not input-derived catalogs.
_IMPORT_DERIVED_LAYERS: dict[str, list[str]] = {"earth": ["astronomy"]}


def _build_layers(world: str, layers: list[str], worlds_dir: Path) -> None:
    """``dreamulator build <world> --only <layer> --force`` for each layer."""
    cli = _dreamulator_cli()
    for layer in layers:
        if cli.exists():
            cmd = [
                str(cli),
                "build",
                world,
                "--only",
                layer,
                "--force",
                "--data-dir",
                str(worlds_dir),
            ]
        else:
            cmd = [
                "uv",
                "run",
                "dreamulator",
                "build",
                world,
                "--only",
                layer,
                "--force",
                "--data-dir",
                str(worlds_dir),
            ]
        print(f"Building '{world}' layer '{layer}' ...")
        subprocess.run(cmd, check=True)


def _import_world(world: str, worlds_dir: Path, proxy: str | None = None) -> None:
    """Rebuild an imported world: refresh declared derived layers, then run the
    importer chain in order.

    The earth elevation importer's default ``--output-dir`` is a legacy layer
    path, so output-dir steps always get the real ``maps/<planet_id>/`` dir
    passed explicitly; data-dir steps (solar bodies) register their own
    planet_id and write under ``maps/`` themselves.  ``proxy`` is forwarded to
    the importers' curl downloads (they also honor HTTP(S)_PROXY env).
    """
    _build_layers(world, _IMPORT_DERIVED_LAYERS.get(world, []), worlds_dir)
    py = str(Path(sys.executable))
    for subdir, module, style, extra_args in _IMPORTED_WORLDS[world]:
        script = _project_root() / "scripts" / subdir / f"{module}.py"
        if style == "output-dir":
            out_dir = worlds_dir / world / "maps" / "planet_earth"
            out_dir.mkdir(parents=True, exist_ok=True)
            cmd = [py, str(script), "--output-dir", str(out_dir), *extra_args]
        else:
            cmd = [py, str(script), "--data-dir", str(worlds_dir), *extra_args]
            if proxy:
                cmd += ["--proxy", proxy]
        print(f"Importing '{world}' via {subdir}/{module} ...")
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
    branch subtrees (``branches/<b>/maps/...``, ``branches/<b>/layers/*/derived/...``).

    Gitignored local-only branches (``bridge-*`` diagnostic experiments — see
    ``local_branches``) are excluded: they must not reach the release tarball
    or the public site.
    """
    from local_branches import local_only_branches, under_local_only_branch

    root = _project_root()
    files: list[Path] = []
    for world in sorted(worlds_dir.iterdir()):
        if not world.is_dir() or world.name.startswith("."):
            continue
        local_only = local_only_branches(root, world)
        if local_only:
            print(f"  {world.name}: excluding local-only branches: {', '.join(sorted(local_only))}")

        def _keep(p: Path, world: Path = world, local_only: set[str] = local_only) -> bool:
            return not _is_scratch(p) and not under_local_only_branch(p, world, local_only)

        for maps_dir in world.rglob("maps"):
            if maps_dir.is_dir() and _is_generated_maps_dir(maps_dir):
                files.extend(p for p in maps_dir.rglob("*") if p.is_file() and _keep(p))
        for derived_dir in world.rglob("derived"):
            if derived_dir.is_dir() and _is_derived_dir(derived_dir):
                files.extend(p for p in derived_dir.rglob("*") if p.is_file() and _keep(p))
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
    parser.add_argument(
        "--proxy",
        default=None,
        help="HTTP proxy forwarded to the importer scripts' curl downloads "
        "(e.g. http://127.0.0.1:PORT).  Omit to rely on curl's HTTP(S)_PROXY "
        "env handling; never hardcode a local proxy address in the repo.",
    )
    args = parser.parse_args()

    root = _project_root()
    worlds_dir = (args.worlds_dir or (root / "data" / "worlds")).resolve()

    if not args.skip_build:
        for world in args.worlds:
            if world in _IMPORTED_WORLDS:
                _import_world(world, worlds_dir, proxy=args.proxy)
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
