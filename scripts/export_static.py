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

# Ensure dreamulator package is importable when running as a script
_SCRIPT_DIR = Path(__file__).resolve().parent


def _ensure_importable() -> None:
    """Add src/ to sys.path so we can import dreamulator."""
    root = _SCRIPT_DIR.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_ensure_importable()

from dreamulator.resolver import LayerResolver  # noqa: E402


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
    if "description" in body:
        normalized["description"] = body["description"]
    return normalized


def _export_layer_data(
    world_dir: Path, branch: str | None = None
) -> dict:
    """Export layer data for a world or branch using the resolver.

    Handles _inherit: true merge for input files.
    Returns a dict with keys: stellar, habitable_zones, planets, climate, ecology, civilizations.
    """
    resolver = LayerResolver(world_dir, branch)
    result: dict = {}

    # 1. Stellar system (input + derived merged)
    stellar_input = resolver.load_layer_yaml("astronomy", "stellar.yaml")
    if stellar_input and isinstance(stellar_input, dict):
        stellar = dict(stellar_input)

        # Merge derived star data if available
        derived_dir = resolver.get_derived_dir("astronomy")
        if derived_dir is not None:
            stellar_derived = load_yaml(derived_dir / "stellar_derived.yaml")
            if stellar_derived and "stars" in stellar_derived:
                derived_by_id = {
                    s["id"]: s for s in stellar_derived["stars"] if "id" in s
                }
                if "stars" in stellar:
                    for star in stellar["stars"]:
                        star_id = star.get("id")
                        if star_id and star_id in derived_by_id:
                            star["derived"] = derived_by_id[star_id]

        result["stellar"] = stellar

        # Normalize bodies (moons, asteroids) to planet-compatible format
        bodies = stellar.get("bodies", [])
        if bodies:
            orbit_lookup = {
                o["body_id"]: o for o in stellar.get("orbits", []) if "body_id" in o
            }
            stellar["bodies"] = [_normalize_body(b, orbit_lookup) for b in bodies]

    # 2. Habitable zones (derived only — no inheritance)
    derived_dir = resolver.get_derived_dir("astronomy")
    if derived_dir is not None:
        hz_data = load_yaml(derived_dir / "habitable_zones.yaml")
        if hz_data:
            result["habitable_zones"] = hz_data

    # 3. Planets
    planets_data = resolver.load_layer_yaml("geological", "planets.yaml")
    if planets_data and isinstance(planets_data, dict) and "planets" in planets_data:
        result["planets"] = planets_data["planets"]

    # 4. Climate
    climate_data = resolver.load_layer_yaml("climate", "climate.yaml")
    if climate_data:
        result["climate"] = climate_data

    # 5. Ecology
    ecology_data = resolver.load_layer_yaml("ecology", "ecology.yaml")
    if ecology_data:
        result["ecology"] = ecology_data

    # 6. Civilizations
    civ_data = resolver.load_layer_yaml("civilization", "civilizations.yaml")
    if civ_data:
        result["civilizations"] = civ_data

    return result


def _export_map_data(
    world_dir: Path,
    maps_out_dir: Path,
    branch: str | None = None,
) -> list[str]:
    """Export map data for a world or branch.

    Scans the geological input directory for planets with maps and copies
    their data (elevation PNG, metadata, voronoi, plates, features) to the
    static output directory.

    Args:
        world_dir: Path to the world root directory.
        maps_out_dir: Output directory for map data.
        branch: Branch name (None for root world).

    Returns:
        List of planet IDs that have map data.
    """
    resolver = LayerResolver(world_dir, branch)
    input_dir = resolver.get_input_dir("geological")
    if input_dir is None:
        return []

    # For branches, only export if the geological data is branch-owned,
    # not inherited from root — avoids duplicating the same map files.
    if branch is not None:
        branch_dir = world_dir / "branches" / branch
        try:
            input_dir.relative_to(branch_dir)
        except ValueError:
            # Resolved to root or parent — maps already exported there
            return []

    maps_dir = input_dir / "maps"
    if not maps_dir.exists():
        return []

    planets_with_maps: list[str] = []

    for planet_dir in sorted(maps_dir.iterdir()):
        if not planet_dir.is_dir():
            continue
        elevation_png = planet_dir / "elevation.png"
        if not elevation_png.exists():
            continue

        planet_id = planet_dir.name
        planets_with_maps.append(planet_id)

        planet_out = maps_out_dir / planet_id
        planet_out.mkdir(parents=True, exist_ok=True)

        # Copy elevation PNG (binary)
        planet_out.joinpath("elevation.png").write_bytes(
            elevation_png.read_bytes()
        )

        # Export map metadata (map.yaml → meta.json)
        map_yaml = planet_dir / "map.yaml"
        if map_yaml.exists():
            meta = load_yaml(map_yaml)
            if meta:
                with planet_out.joinpath("meta.json").open(
                    "w", encoding="utf-8"
                ) as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2, default=str)

        # Export JSON map files (voronoi, plates, features).
        # Each is read-validated-rewritten to catch LFS pointers or corrupt
        # files early instead of crashing the whole export.
        for filename in ("voronoi.json", "plates.json", "features.json"):
            src_path = planet_dir / filename
            if not src_path.exists():
                continue
            try:
                with src_path.open("r", encoding="utf-8") as src:
                    data = json.load(src)
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(
                    f"\n  WARNING: {src_path} is not valid JSON "
                    f"(possible LFS pointer) — skipping",
                )
                continue
            with planet_out.joinpath(filename).open("w", encoding="utf-8") as dst:
                json.dump(data, dst, ensure_ascii=False, indent=2)

    # Write maps index
    if planets_with_maps:
        maps_out_dir.mkdir(parents=True, exist_ok=True)
        with maps_out_dir.joinpath("maps.json").open("w", encoding="utf-8") as f:
            json.dump(planets_with_maps, f, ensure_ascii=False, indent=2)

    return planets_with_maps


def export_world(world_dir: Path) -> dict:
    """Export all data for a single world (root, no branch).

    Returns a dict with keys:
      - world: world.yaml contents
      - branches: list of branch metadata
      - stellar, habitable_zones, planets, climate, ecology, civilizations (from _export_layer_data)
    """
    result: dict = {}

    # 1. World config (world.yaml)
    world_data = load_yaml(world_dir / "world.yaml")
    if world_data is None:
        print(f"  WARNING: {world_dir.name}/world.yaml not found, skipping")
        return result
    result["world"] = world_data

    # 2. Branches metadata
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

    # 3. Layer data (root world, no branch)
    result.update(_export_layer_data(world_dir, branch=None))

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

    import os

    root = find_project_root()
    env_dir = os.environ.get("DREAMULATOR_DATA_DIR")
    worlds_dir = Path(env_dir).resolve() if env_dir else root / "data" / "worlds"
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

        # Export root map data (elevation PNG + metadata)
        maps_out_dir = world_out_dir / "maps"
        map_planets = _export_map_data(world_dir, maps_out_dir, branch=None)

        # Export per-branch data (with _inherit: true merge)
        branch_count = 0
        branches_dir = world_dir / "branches"
        if branches_dir.exists():
            for branch_dir in sorted(branches_dir.iterdir()):
                if not branch_dir.is_dir():
                    continue
                branch_name = branch_dir.name
                branch_data = _export_layer_data(world_dir, branch=branch_name)
                branch_out_dir = world_out_dir / "branches" / branch_name
                if branch_data:
                    branch_out_dir.mkdir(parents=True, exist_ok=True)
                    for key, value in branch_data.items():
                        out_file = branch_out_dir / f"{key}.json"
                        with out_file.open("w", encoding="utf-8") as f:
                            json.dump(value, f, ensure_ascii=False, indent=2, default=str)
                # Export branch-specific map data
                branch_maps_out = branch_out_dir / "maps"
                branch_map_planets = _export_map_data(
                    world_dir, branch_maps_out, branch=branch_name
                )
                if branch_data or branch_map_planets:
                    branch_count += 1

        print(
            f"OK ({len(data)} files, {len(map_planets)} map(s), "
            f"{branch_count} branch(es))"
        )

    # Write worlds index
    index_file = output_dir / "worlds.json"
    with index_file.open("w", encoding="utf-8") as f:
        json.dump(all_worlds, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Worlds index: {index_file}")
    print(f"Total: {len(all_worlds)} world(s) exported.")


if __name__ == "__main__":
    main()
