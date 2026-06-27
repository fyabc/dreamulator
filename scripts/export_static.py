"""Export world data as static JSON for GitHub Pages deployment.

Reads all worlds from data/worlds/ and exports their data as JSON files
to frontend/public/data/ for static site hosting.

Usage:
    python scripts/export_static.py
    python scripts/export_static.py --output frontend/public/data
    python scripts/export_static.py --worlds earth gaia-m
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def find_project_root() -> Path:
    """Find the project root (contains pyproject.toml)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find project root (no pyproject.toml found)")


def load_yaml(path: Path) -> dict | list | None:
    """Load a YAML file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_KM_PER_EARTH_RADIUS = 6371.0


def _normalize_body(body: dict, orbit_lookup: dict) -> dict:
    """Normalize an OrbitingBody to PlanetData-compatible format for frontend."""
    orbit = orbit_lookup.get(body.get("id", ""), {})
    normalized = {
        "id": body.get("id"),
        "name": body.get("name"),
        "planet_type": body.get("body_type", "natural_satellite"),
        "mass": body.get("mass_earth", 0),
        "radius": body.get("radius_km", 0) / _KM_PER_EARTH_RADIUS,
        "orbits": orbit.get("parent_id", ""),
    }
    for key in ("rotation_period_days", "axial_tilt_deg", "albedo"):
        if key in body and body[key] is not None:
            normalized[key] = body[key]
    if "surface" in body:
        normalized["surface"] = body["surface"]
    return normalized


def export_world(world_dir: Path) -> dict:
    """Export all data for a single world.

    Returns a dict with keys:
      - world: world.yaml contents
      - branches: list of branch metadata
      - stellar: stellar system data (input + derived merged)
      - habitable_zones: habitable zone data (if computed)
      - planets: list of planet definitions
    """
    result: dict = {}

    # 1. World config (world.yaml)
    world_data = load_yaml(world_dir / "world.yaml")
    if world_data is None:
        print(f"  WARNING: {world_dir.name}/world.yaml not found, skipping")
        return result
    result["world"] = world_data

    # 2. Branches
    branches: list[dict] = []
    branches_dir = world_dir / "branches"
    if branches_dir.exists():
        for branch_dir in sorted(branches_dir.iterdir()):
            if not branch_dir.is_dir():
                continue
            branch_yaml = branch_dir / "branch.yaml"
            if branch_yaml.exists():
                branch_data = load_yaml(branch_yaml)
                if branch_data:
                    branches.append(branch_data)
    result["branches"] = branches

    # 3. Stellar system (merge input + derived)
    stellar_input = load_yaml(world_dir / "layers" / "astronomy" / "input" / "stellar.yaml")
    stellar_derived = load_yaml(
        world_dir / "layers" / "astronomy" / "derived" / "stellar_derived.yaml"
    )
    if stellar_input:
        # Merge derived data into input for a complete view
        stellar = dict(stellar_input)
        if stellar_derived and "stars" in stellar_derived:
            # Create a lookup of derived star data by id
            derived_by_id = {s["id"]: s for s in stellar_derived["stars"] if "id" in s}
            if "stars" in stellar:
                for star in stellar["stars"]:
                    star_id = star.get("id")
                    if star_id and star_id in derived_by_id:
                        star["derived"] = derived_by_id[star_id]
        result["stellar"] = stellar

        # Normalize bodies (moons, asteroids) to planet-compatible format
        bodies = stellar.get("bodies", [])
        if bodies:
            orbit_lookup = {o["body_id"]: o for o in stellar.get("orbits", []) if "body_id" in o}
            stellar["bodies"] = [_normalize_body(b, orbit_lookup) for b in bodies]

    # 4. Habitable zones
    hz_data = load_yaml(world_dir / "layers" / "astronomy" / "derived" / "habitable_zones.yaml")
    if hz_data:
        result["habitable_zones"] = hz_data

    # 5. Planets
    planets_input = load_yaml(world_dir / "layers" / "geological" / "input" / "planets.yaml")
    if planets_input and "planets" in planets_input:
        result["planets"] = planets_input["planets"]

    # 6. Civilization data (if exists)
    civ_input = load_yaml(world_dir / "layers" / "civilization" / "input" / "civilizations.yaml")
    if civ_input:
        result["civilizations"] = civ_input

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export world data as static JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: frontend/public/data)",
    )
    parser.add_argument(
        "--worlds",
        nargs="*",
        default=None,
        help="Specific worlds to export (default: all)",
    )
    args = parser.parse_args()

    root = find_project_root()
    worlds_dir = root / "data" / "worlds"
    output_dir = args.output or (root / "frontend" / "public" / "data")

    if not worlds_dir.exists():
        print(f"ERROR: worlds directory not found at {worlds_dir}", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover worlds
    all_worlds = sorted(
        d.name for d in worlds_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
    )

    if args.worlds:
        # Filter to requested worlds
        selected = set(args.worlds)
        unknown = selected - set(all_worlds)
        if unknown:
            print(f"WARNING: unknown worlds: {unknown}", file=sys.stderr)
        all_worlds = [w for w in all_worlds if w in selected]

    if not all_worlds:
        print("No worlds to export.")
        sys.exit(0)

    print(f"Exporting {len(all_worlds)} world(s) to {output_dir}/")

    # Export each world
    for world_name in all_worlds:
        world_dir = worlds_dir / world_name
        print(f"  {world_name}...", end=" ")

        data = export_world(world_dir)
        if not data:
            print("SKIPPED (no world.yaml)")
            continue

        # Write each data type as a separate JSON file
        world_out_dir = output_dir / "worlds" / world_name
        world_out_dir.mkdir(parents=True, exist_ok=True)

        for key, value in data.items():
            out_file = world_out_dir / f"{key}.json"
            with out_file.open("w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, indent=2, default=str)

        print(f"OK ({len(data)} files)")

    # Write worlds index
    index_file = output_dir / "worlds.json"
    with index_file.open("w", encoding="utf-8") as f:
        json.dump(all_worlds, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Worlds index: {index_file}")
    print(f"Total: {len(all_worlds)} world(s) exported.")


if __name__ == "__main__":
    main()
