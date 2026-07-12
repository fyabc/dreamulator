#!/usr/bin/env python3
"""Download and prepare real-world admin boundary GeoJSON for the CivMap system.

Data sources:
  - Natural Earth (public domain, province-level): via GitHub mirror
  - geoBoundaries (CC BY 4.0, up to district-level): via REST API / GitHub

Usage:
    python scripts/prepare_civmap_data.py \
        [--source natural-earth|geoboundaries] \
        [--level adm0|adm1|adm2] \
        [--output-dir DIR] [--simplify TOLERANCE]

Examples:
    # Download Natural Earth admin-0 + admin-1 (small, public domain)
    python scripts/prepare_civmap_data.py --source natural-earth

    # Download geoBoundaries ADM1 (larger, CC BY 4.0)
    python scripts/prepare_civmap_data.py --source geoboundaries --level adm1

    # With geometry simplification (requires geopandas + shapely)
    python scripts/prepare_civmap_data.py --source natural-earth --simplify 0.01
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "data" / "worlds" / "earth" / "layers" / "geological" / "input" / "maps" / "earth_reference"
)

# Natural Earth GeoJSON (public domain) — official vector repo
NE_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
NE_SOURCES = {
    "adm0": f"{NE_BASE}/ne_10m_admin_0_countries.geojson",
    "adm1": f"{NE_BASE}/ne_10m_admin_1_states_provinces.geojson",
}

# geoBoundaries CGAZ global composites (CC BY 4.0)
# See: https://github.com/wmgeolab/geoBoundaries
GB_SOURCES = {
    "adm0": "https://raw.githubusercontent.com/wmgeolab/geoBoundaries/main/releaseData/gbOpen/CGAZ_ADM0.geojson",
    "adm1": "https://raw.githubusercontent.com/wmgeolab/geoBoundaries/main/releaseData/gbOpen/CGAZ_ADM1.geojson",
    "adm2": "https://raw.githubusercontent.com/wmgeolab/geoBoundaries/main/releaseData/gbOpen/CGAZ_ADM2.geojson",
}


def download_json(url: str, desc: str) -> dict[str, Any]:
    """Download a JSON file from a URL."""
    import urllib.request

    print(f"  Downloading {desc}...")
    print(f"    URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "dreamulator/0.2"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
        print(f"    Size: {len(data) / 1024 / 1024:.1f} MB")
        return json.loads(data)


def simplify_geojson(
    geojson: dict[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    """Simplify GeoJSON geometry using Douglas-Peucker algorithm.

    Requires geopandas and shapely.
    """
    try:
        from shapely.geometry import mapping, shape  # type: ignore[import-untyped]
    except ImportError:
        print("  WARNING: geopandas/shapely not installed. Skipping simplification.")
        print("  Install with: uv pip install geopandas shapely")
        return geojson

    import copy

    result = copy.deepcopy(geojson)
    simplified_count = 0

    for feature in result.get("features", []):
        geom = feature.get("geometry")
        if geom is None:
            continue
        try:
            s = shape(geom)
            s_simplified = s.simplify(tolerance, preserve_topology=True)
            feature["geometry"] = mapping(s_simplified)
            simplified_count += 1
        except Exception as e:
            print(f"  WARNING: Failed to simplify feature: {e}")

    print(f"  Simplified {simplified_count} features with tolerance={tolerance}")
    return result


def strip_properties(
    geojson: dict[str, Any],
    keep_props: list[str],
) -> dict[str, Any]:
    """Strip non-essential properties from GeoJSON features to reduce file size."""
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        feature["properties"] = {k: v for k, v in props.items() if k in keep_props}
    return geojson


def assign_stable_ids(geojson: dict[str, Any], id_field: str) -> dict[str, Any]:
    """Assign stable IDs to features based on a property field.

    If the field is missing, falls back to a sequential index.
    """
    for i, feature in enumerate(geojson.get("features", [])):
        props = feature.get("properties", {})
        stable_id = props.get(id_field)
        if stable_id:
            feature["id"] = stable_id
        else:
            feature["id"] = f"feature_{i}"
    return geojson


def prepare_natural_earth(
    output_dir: Path,
    levels: list[str],
    simplify_tolerance: float | None,
) -> dict[str, Any]:
    """Download and prepare Natural Earth admin boundaries."""
    metadata: dict[str, Any] = {
        "source": "Natural Earth",
        "license": "Public Domain",
        "url": "https://www.naturalearthdata.com",
        "levels": {},
    }

    for level in levels:
        if level not in NE_SOURCES:
            print(f"  Skipping {level}: not available from Natural Earth")
            continue

        url = NE_SOURCES[level]

        geojson = download_json(url, f"Natural Earth {level}")
        feature_count = len(geojson.get("features", []))
        print(f"  Features: {feature_count}")

        # Assign stable IDs — must be unique per feature
        # ADM0: ISO_A2 is unique per country (258 countries)
        # ADM1: adm1_code is unique per province (4596/4596), format "ARG-1309"
        id_field = "ISO_A2" if level == "adm0" else "adm1_code"
        geojson = assign_stable_ids(geojson, id_field)

        # Keep essential properties (UPPERCASE for adm0, lowercase for adm1)
        if level == "adm0":
            keep = [
                "ISO_A2", "ISO_A3", "NAME", "NAME_LONG", "CONTINENT",
                "POP_EST", "GDP_MD", "TYPE", "ADMIN", "SOVEREIGNT",
            ]
        else:
            keep = [
                "adm1_code", "iso_a2", "name", "name_en", "name_zh",
                "admin", "name_local", "type_en", "region",
                "latitude", "longitude",
            ]
        geojson = strip_properties(geojson, keep)

        # Simplify if requested
        if simplify_tolerance:
            geojson = simplify_geojson(geojson, simplify_tolerance)

        # Write output
        out_path = output_dir / f"{level}.geojson"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
        print(f"  Written: {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")

        metadata["levels"][level] = {
            "features": feature_count,
            "file_size_mb": round(out_path.stat().st_size / 1024 / 1024, 1),
        }

    return metadata


def prepare_geoboundaries(
    output_dir: Path,
    levels: list[str],
    simplify_tolerance: float | None,
) -> dict[str, Any]:
    """Download and prepare geoBoundaries admin boundaries."""
    metadata: dict[str, Any] = {
        "source": "geoBoundaries",
        "license": "CC BY 4.0",
        "url": "https://www.geoboundaries.org",
        "levels": {},
    }

    for level in levels:
        if level not in GB_SOURCES:
            print(f"  Skipping {level}: not available from geoBoundaries")
            continue

        url = GB_SOURCES[level]
        geojson = download_json(url, f"geoBoundaries {level}")
        feature_count = len(geojson.get("features", []))
        print(f"  Features: {feature_count}")

        # geoBoundaries uses shapeID as stable ID
        geojson = assign_stable_ids(geojson, "shapeID")

        # Keep essential properties
        keep = ["shapeID", "shapeName", "shapeISO", "shapeGroup", "shapeType"]
        geojson = strip_properties(geojson, keep)

        # Simplify if requested
        if simplify_tolerance:
            geojson = simplify_geojson(geojson, simplify_tolerance)

        # Write output
        out_path = output_dir / f"{level}.geojson"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False)
        print(f"  Written: {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")

        metadata["levels"][level] = {
            "features": feature_count,
            "file_size_mb": round(out_path.stat().st_size / 1024 / 1024, 1),
        }

    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and prepare admin boundary GeoJSON for CivMap",
    )
    parser.add_argument(
        "--source",
        choices=["natural-earth", "geoboundaries"],
        default="natural-earth",
        help="Data source (default: natural-earth)",
    )
    parser.add_argument(
        "--level",
        nargs="+",
        default=["adm0", "adm1"],
        choices=["adm0", "adm1", "adm2"],
        help="Admin levels to download (default: adm0 adm1)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--simplify",
        type=float,
        default=None,
        help="Douglas-Peucker tolerance in degrees (e.g. 0.01). Requires geopandas.",
    )

    args = parser.parse_args()
    output_dir: Path = args.output_dir

    print("CivMap Data Preparation")
    print(f"  Source: {args.source}")
    print(f"  Levels: {args.level}")
    print(f"  Output: {output_dir}")
    if args.simplify:
        print(f"  Simplify: {args.simplify}°")
    print()

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Download and prepare
    if args.source == "natural-earth":
        metadata = prepare_natural_earth(output_dir, args.level, args.simplify)
    else:
        metadata = prepare_geoboundaries(output_dir, args.level, args.simplify)

    # Write metadata
    meta_path = output_dir / "metadata.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"\nMetadata written: {meta_path}")
    print("Done!")


if __name__ == "__main__":
    main()
