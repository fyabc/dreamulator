#!/usr/bin/env python3
"""Publish generated world build output (maps + derived) to a GitHub Release.

Target architecture (post-LFS): git tracks only authored input + code. The
generated maps (large, slow) and derived YAML (small, fast) are packaged into a
single tarball and uploaded to a fixed GitHub Release tag ``worlds-data``; the
Pages deploy workflow downloads that tarball before running the static export.
This keeps the git working tree clean (no build-output churn) and drops git LFS.

Flow:

  1. Build the worlds locally in ``private/worlds`` (as usual).
  2. Run this script to package maps + derived and upload them.
  3. Commit any input-doc changes — the next Pages deploy then picks up the
     newly published data.

Usage::

    uv run python scripts/publish_world_data.py                # package + upload
    uv run python scripts/publish_world_data.py --dry-run      # package only, no upload
    uv run python scripts/publish_world_data.py --tag v0.36.0  # custom release tag
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


def _find_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _is_generated_maps_dir(path: Path) -> bool:
    """A generated ``maps`` dir never sits under ``layers/`` (that is the
    import-elevation staging area ``layers/geological/input/maps/``, already
    gitignored and NOT part of the published output)."""
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
                files.extend(
                    p for p in maps_dir.rglob("*") if p.is_file() and not _is_scratch(p)
                )
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
            "scripts/publish_world_data.py.",
            "--prerelease",
        ],
        check=False,
    )
    subprocess.run(
        ["gh", "release", "upload", tag, str(tar_path), "--clobber"], check=True
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worlds-dir",
        type=Path,
        default=None,
        help="Worlds directory (default: private/worlds)",
    )
    parser.add_argument("--tag", default=DEFAULT_TAG, help="Release tag")
    parser.add_argument(
        "--dry-run", action="store_true", help="Package but do not upload"
    )
    args = parser.parse_args()

    root = _find_project_root()
    worlds_dir = args.worlds_dir or (root / "private" / "worlds")
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
