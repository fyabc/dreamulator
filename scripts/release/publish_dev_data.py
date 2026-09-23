#!/usr/bin/env python3
"""Produce the versioned Earth base-terrain dev-data package (M1-P1).

Runs a *controlled* base-terrain generation — the elevation + tectonics +
watermask importers only, NOT import_earth_climate and NOT the climate build —
into a clean staging directory, then writes a manifest (per-file SHA-256 + the
import-recipe fingerprint), tarballs the four base-terrain files, and upserts a
content-addressed entry into the git-committed index.

This is deliberately separate from ``publish_world_data.py``: that script
packages the climate-polluted mesh for the website; this one packages the clean
base terrain a new machine needs before any climate step runs (audit
github-data-bootstrap-evaluation §推荐的包边界).

Usage::

    uv run python scripts/release/publish_dev_data.py            # build + package + index
    uv run python scripts/release/publish_dev_data.py --upload   # also upload to GitHub

Upload is opt-in and gated behind ``--upload`` (outward-facing, requires review).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

DEFAULT_TAG = "dev-data"
INDEX_PATH = Path("data/dev-data/index.json")
ARTIFACTS_DIR = Path("data/dev-data/artifacts")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_recipe() -> tuple[object, str, str]:
    """Return (TerrainPipelineConfig, planet_id, world)."""
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

    root = _project_root()
    cfg = TerrainPipelineConfig.from_yaml(
        root / "data" / "worlds" / "earth" / "layers" / "geological" / "input" / "terrain_config.yaml"
    )
    # Earth's only terrestrial planet (matches engine load_planets -> planets[0]).
    planets_path = root / "data" / "worlds" / "earth" / "layers" / "geological" / "input" / "planets.yaml"
    data = yaml.safe_load(planets_path.read_text(encoding="utf-8")) or {}
    planet_id = data["planets"][0]["id"]
    return cfg, planet_id, "earth"


def _run_importers(staging_maps: Path, recipe: object) -> None:
    scripts_dir = _project_root() / "scripts" / "earth"
    py = sys.executable
    staging_maps.mkdir(parents=True, exist_ok=True)
    commands = [
        [
            py,
            str(scripts_dir / "import_earth_elevation.py"),
            "--output-dir",
            str(staging_maps),
            "--resolution",
            recipe.resolution,
            "--mesh-nodes",
            str(recipe.mesh_nodes),
            "--seed",
            str(recipe.seed),
            "--skip-download",
        ],
        [py, str(scripts_dir / "import_earth_tectonics.py"), "--output-dir", str(staging_maps)],
        [py, str(scripts_dir / "import_earth_watermask.py"), "--output-dir", str(staging_maps)],
    ]
    for cmd in commands:
        print(f"Running {Path(cmd[1]).name} ...")
        subprocess.run(cmd, check=True, cwd=str(_project_root()))


def _verify_clean_mesh(mesh_path: Path) -> None:
    """Assert the produced mesh carries no climate-derived fields."""
    from dreamulator.map.export import load_cvt_mesh

    data = load_cvt_mesh(mesh_path)
    polluted = 0
    for cell in data.get("cells", []):
        if cell.get("temperature_C") is not None or cell.get("koppen_class") is not None:
            polluted += 1
    if polluted:
        raise RuntimeError(
            f"staging mesh has {polluted} cells with climate fields — the base "
            "terrain must come from the importers only, not a climate step"
        )
    print("Verified: staging mesh carries no climate-derived fields.")


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, cwd=str(_project_root())
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=DEFAULT_TAG, help="GitHub Release tag")
    parser.add_argument("--upload", action="store_true", help="Upload the package to GitHub")
    args = parser.parse_args()

    from dreamulator.datapkg import (
        DevDataIndex,
        DevDataManifest,
        IndexEntry,
        MESH_FORMAT_VERSION,
        PackageFile,
        file_sha256,
        recipe_fingerprint,
    )

    root = _project_root()
    cfg, planet_id, world = _load_recipe()
    recipe = cfg.terrain_import
    if recipe is None:
        print("Earth terrain_config.yaml has no terrain_import recipe", file=sys.stderr)
        sys.exit(1)

    fingerprint = recipe_fingerprint(recipe, MESH_FORMAT_VERSION)

    with tempfile.TemporaryDirectory(prefix="dreamulator-dev-data-") as tmp:
        staging = Path(tmp)
        staging_maps = staging / "maps" / planet_id
        _run_importers(staging_maps, recipe)
        from dreamulator.map.export import MESH_FILENAME

        _verify_clean_mesh(staging_maps / MESH_FILENAME)

        base_files = ["elevation.png", MESH_FILENAME, "plates.json", "map.yaml"]
        files = []
        for name in base_files:
            p = staging_maps / name
            rel = f"maps/{planet_id}/{name}"
            files.append(PackageFile(path=rel, sha256=file_sha256(p), size_bytes=p.stat().st_size))

        manifest = DevDataManifest(
            world=world,
            planet_id=planet_id,
            recipe=recipe.to_dict(),
            mesh_format_version=MESH_FORMAT_VERSION,
            input_fingerprint=fingerprint,
            code_revision=_git_revision(),
            files=files,
        )
        (staging / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        asset_name = f"{world}-terrain-base-{fingerprint[:12]}.tar.gz"
        artifacts = root / ARTIFACTS_DIR
        artifacts.mkdir(parents=True, exist_ok=True)
        tar_path = artifacts / asset_name
        with tarfile.open(tar_path, "w:gz") as tar:
            for name in base_files:
                tar.add(staging_maps / name, arcname=f"maps/{planet_id}/{name}")
            tar.add(staging / "manifest.json", arcname="manifest.json")

        package_sha256 = file_sha256(tar_path)
        manifest_sha256 = file_sha256(staging / "manifest.json")
        size_bytes = tar_path.stat().st_size

        entry = IndexEntry(
            world=world,
            planet_id=planet_id,
            input_fingerprint=fingerprint,
            mesh_format_version=MESH_FORMAT_VERSION,
            tag=args.tag,
            asset_name=asset_name,
            package_sha256=package_sha256,
            manifest_sha256=manifest_sha256,
            size_bytes=size_bytes,
            recipe=recipe.to_dict(),
        )

        index_path = root / INDEX_PATH
        index = DevDataIndex.load(index_path)
        index.upsert(entry)
        index.save(index_path)

        print(f"Packaged {asset_name} ({size_bytes / (1024 * 1024):.1f} MB)")
        print(f"  fingerprint: {fingerprint}")
        print(f"  package SHA-256: {package_sha256}")
        print(f"  index updated: {index_path}")

    if args.upload:
        subprocess.run(
            ["gh", "release", "create", args.tag, "--title", "Development data", "--prerelease"],
            check=False,
        )
        subprocess.run(["gh", "release", "upload", args.tag, str(tar_path)], check=True)
        print(f"Uploaded {asset_name} to release '{args.tag}'")
    else:
        print("Not uploading (use --upload to publish).")


if __name__ == "__main__":
    main()
