#!/usr/bin/env python3
"""Convert Beck et al. (2018) Köppen GeoTIFF to per-CVT-cell JSON.

Samples the 5-arc-minute Beck Köppen map at each CVT mesh cell's (lon, lat)
and produces a JSON file mapping cell_id → Köppen class code.

Usage:
    uv run python scripts/convert_koppen_map.py [--tif PATH] [--mesh PATH] [--output PATH]

Requirements:
    uv pip install tifffile
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np

# Beck class code → Köppen string (from legend.txt)
BECK_LEGEND: dict[int, str] = {
    0: "N/A",
    1: "Af",
    2: "Am",
    3: "Aw",
    4: "BWh",
    5: "BWk",
    6: "BSh",
    7: "BSk",
    8: "Csa",
    9: "Csb",
    10: "Csc",
    11: "Cwa",
    12: "Cwb",
    13: "Cwc",
    14: "Cfa",
    15: "Cfb",
    16: "Cfc",
    17: "Dsa",
    18: "Dsb",
    19: "Dsc",
    20: "Dsd",
    21: "Dwa",
    22: "Dwb",
    23: "Dwc",
    24: "Dwd",
    25: "Dfa",
    26: "Dfb",
    27: "Dfc",
    28: "Dfd",
    29: "ET",
    30: "EF",
}


def load_beck_array(tif_path: Path) -> np.ndarray:
    """Load Beck Köppen GeoTIFF as a numpy array.

    Handles both raw .tif and .zip-wrapped .tif (figshare download format).

    Args:
        tif_path: Path to .tif file or .zip containing it.

    Returns:
        2D uint8 array (rows=lat N→S, cols=lon W→E), values 0–30.
    """
    import tifffile

    if tif_path.suffix == ".zip" or _is_zip(tif_path):
        # Extract from ZIP
        tmp_dir = Path(tempfile.gettempdir()) / "dreamulator_koppen"
        tmp_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(tif_path) as zf:
            # Find the present-day 0p083 file
            target = None
            for name in zf.namelist():
                if "present_0p083" in name and name.endswith(".tif"):
                    target = name
                    break
            if target is None:
                raise FileNotFoundError("No present_0p083.tif found in ZIP")
            zf.extract(target, tmp_dir)
            tif_path = tmp_dir / target

    arr = tifffile.imread(str(tif_path))
    print(f"  Loaded Beck map: {arr.shape[1]}x{arr.shape[0]} (5 arc-min)")
    return arr


def _is_zip(path: Path) -> bool:
    """Check if file starts with PK (ZIP magic bytes)."""
    with path.open("rb") as f:
        return f.read(2) == b"PK"


def sample_beck_at_cells(
    beck: np.ndarray,
    cells: list,
) -> dict[str, str]:
    """Sample Beck Köppen class at each CVT cell's geographic coordinates.

    Args:
        beck: 2D uint8 array from load_beck_array().
        cells: List of VoronoiCell objects with .lon and .lat attributes.

    Returns:
        Dict mapping str(cell_id) → Köppen class code string.
    """
    h, w = beck.shape
    result: dict[str, str] = {}

    for c in cells:
        # Convert (lon, lat) to pixel coordinates
        # Beck grid: row 0 = 90°N, row h-1 = 90°S
        #            col 0 = 180°W, col w-1 = 180°E
        row = int((90.0 - c.lat) / 180.0 * h)
        col = int((c.lon + 180.0) / 360.0 * w)
        row = max(0, min(h - 1, row))
        col = max(0, min(w - 1, col))

        class_code = int(beck[row, col])
        result[str(c.id)] = BECK_LEGEND.get(class_code, "N/A")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Beck et al. (2018) Köppen map to per-cell JSON",
    )
    parser.add_argument(
        "--tif",
        default=None,
        help="Path to Beck GeoTIFF or ZIP (auto-downloads if not specified)",
    )
    parser.add_argument(
        "--mesh",
        default="data/worlds/earth/branches/climate-dev/maps/planet_earth/cvt_mesh.json",
        help="Path to CVT mesh JSON (Earth baseline, default 200k in climate-dev)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="data/worlds/earth/branches/climate-dev/maps/planet_earth/koppen_obs.json",
        help="Output JSON path (stored alongside the mesh)",
    )
    args = parser.parse_args()

    # Find project root
    project_root = _find_project_root()
    mesh_path = project_root / args.mesh
    output_path = project_root / args.output

    if not mesh_path.exists():
        print(f"ERROR: CVT mesh not found: {mesh_path}", file=sys.stderr)
        print("Run: uv run python scripts/import_earth_elevation.py first", file=sys.stderr)
        sys.exit(1)

    # Load Beck data
    if args.tif:
        tif_path = Path(args.tif)
    else:
        # Auto-download
        tif_path = _auto_download_beck()

    print(f"Loading Beck Koppen map from: {tif_path}")
    beck = load_beck_array(tif_path)

    # Load CVT mesh
    print(f"Loading CVT mesh from: {mesh_path}")
    from dreamulator.map.models import CVTMesh

    from dreamulator.map.export import decompress_mesh_bytes

    mesh = CVTMesh(**json.loads(decompress_mesh_bytes(mesh_path.read_bytes())))
    print(f"  Mesh: {mesh.num_cells} cells")

    # Sample
    print("Sampling Beck classes at cell locations...")
    obs_classes = sample_beck_at_cells(beck, mesh.cells)

    # Statistics
    from collections import Counter

    counts = Counter(obs_classes.values())
    n_land = sum(v for k, v in counts.items() if k != "N/A")
    print(f"  Sampled: {n_land} land cells, {counts.get('N/A', 0)} ocean/N/A cells")
    print(f"  Top classes: {counts.most_common(10)}")

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_data = {
        "source": "Beck et al. (2018), Present Köppen-Geiger at 5 arc-min",
        "source_url": "https://doi.org/10.1038/sdata.2018.214",
        "resolution": "5 arc-minute (2160x4320)",
        "num_cells": mesh.num_cells,
        "seed": mesh.seed,
        "mesh_path": str(mesh_path.relative_to(project_root)),
        "cells": obs_classes,
        "class_distribution": dict(counts.most_common()),
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=1)
    print(f"  Saved: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")


def _auto_download_beck() -> Path:
    """Download Beck et al. 2018 from figshare if not cached."""
    cache_dir = Path(tempfile.gettempdir()) / "dreamulator_koppen"
    zip_path = cache_dir / "Beck_KG_V1.zip"

    if zip_path.exists() and zip_path.stat().st_size > 1_000_000:
        print(f"  Using cached: {zip_path}")
        return zip_path

    cache_dir.mkdir(exist_ok=True)
    url = "https://ndownloader.figshare.com/files/12407516"
    print(f"  Downloading from {url} ...")

    import urllib.request

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({"https": proxy, "http": proxy})
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)

    req = urllib.request.Request(url, headers={"User-Agent": "dreamulator/0.8"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with zip_path.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    print(
                        f"\r  {downloaded / (1024 * 1024):.0f}/{total / (1024 * 1024):.0f} MB",
                        end="",
                        flush=True,
                    )
    print()
    return zip_path


def _find_project_root() -> Path:
    d = Path.cwd()
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


if __name__ == "__main__":
    main()
