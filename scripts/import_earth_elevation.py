#!/usr/bin/env python3
"""Import real Earth elevation data into dreamulator's CVT mesh format.

Downloads ETOPO1 (1 arc-minute global relief model) from NOAA, resamples to
the configured equirectangular resolution, and produces:

    - elevation.png       — 16-bit PNG heightmap
    - metadata.json       — encoding parameters + data provenance
    - cvt_mesh.json       — CVT mesh with elevation assigned to cells
    - map.yaml            — map metadata for the frontend

Usage:
    uv run python scripts/import_earth_elevation.py [--resolution 2048x1024] [--mesh 32768]
    uv run python scripts/import_earth_elevation.py --output-dir data/worlds/earth/layers/geological/input/maps/earth

Requirements:
    uv pip install xarray netCDF4
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ETOPO1 ice-surface, grid-registered, NetCDF format
_ETOPO1_URL = (
    "https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO1/data/"
    "ice_surface/grid_registered/netcdf/ETOPO1_Ice_g_gmt4.grd.gz"
)

# Expected file size (~400 MB compressed)
_ETOPO1_EXPECTED_SIZE_MB = 420

# Default output resolution (equirectangular)
_DEFAULT_WIDTH = 2048
_DEFAULT_HEIGHT = 1024

# Default CVT mesh node count
_DEFAULT_MESH_NODES = 32768

# Earth radius in km
_EARTH_RADIUS_KM = 6371.0

# Elevation range for PNG encoding (metres)
_ELEV_MIN_M = -11_000.0
_ELEV_MAX_M = 9_000.0

# Output directories relative to project root
_DEFAULT_OUTPUT_DIR = "data/worlds/earth/layers/geological/input/maps/earth"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_etopo1(target_path: Path, chunk_size: int = 1024 * 1024) -> None:
    """Download ETOPO1 NetCDF (gzipped) with progress reporting.

    Args:
        target_path: Where to save the downloaded file.
        chunk_size: Download chunk size in bytes.
    """
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

    if proxy_url:
        import ssl

        ctx = ssl.create_default_context()
        proxy_handler = None
        if proxy_url.startswith("http://"):
            from urllib.request import ProxyHandler, build_opener, install_opener

            proxy_handler = ProxyHandler({"https": proxy_url})
            opener = build_opener(proxy_handler)
            opener.addheaders = [("User-Agent", "dreamulator/0.8")]
            install_opener(opener)

    print(f"Downloading ETOPO1 from {_ETOPO1_URL} ...")
    req = Request(_ETOPO1_URL, headers={"User-Agent": "dreamulator/0.8"})
    with urlopen(req, timeout=300) as response:  # noqa: S310
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        with target_path.open("wb") as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    mb = downloaded / (1024 * 1024)
                    print(f"\r  {mb:.1f} MB ({pct:.0f}%)", end="", flush=True)
    print()
    print(f"  Download complete: {target_path.stat().st_size / (1024*1024):.1f} MB")


# ---------------------------------------------------------------------------
# ETOPO1 → equirectangular raster
# ---------------------------------------------------------------------------


def extract_etopo1_to_raster(
    etopo1_gz_path: Path,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> tuple[np.ndarray, dict]:
    """Extract ETOPO1 elevation data and resample to equirectangular grid.

    ETOPO1 is 10801 rows × 21601 columns (1 arc-minute).
    Rows: 90°N (row 0) → 90°S (row 10800).
    Cols: 180°W (col 0) → 180°E (col 21600).

    Args:
        etopo1_gz_path: Path to downloaded ETOPO1 .grd.gz file.
        width: Target raster width.
        height: Target raster height.

    Returns:
        (elevation_grid, metadata) where grid is (height, width) in metres
        and metadata is a dict with provenance info.
    """
    import xarray as xr

    print(f"Reading ETOPO1 from {etopo1_gz_path} ...")

    # Decompress to a temporary file (netCDF4 can't read from gzip stream)
    tmp_nc = etopo1_gz_path.with_suffix("")  # remove .gz
    if not tmp_nc.exists():
        print(f"  Decompressing to {tmp_nc} ...")
        with gzip.open(etopo1_gz_path, "rb") as gz:
            with tmp_nc.open("wb") as out:
                shutil.copyfileobj(gz, out)
        print(f"  Decompressed: {tmp_nc.stat().st_size / (1024*1024):.0f} MB")

    ds = xr.open_dataset(str(tmp_nc), engine="netcdf4")
    # ETOPO1 uses 'x' (lon), 'y' (lat), 'z' (elevation)
    lon_var = "x" if "x" in ds.dims else "lon"
    lat_var = "y" if "y" in ds.dims else "lat"
    z_var = "z" if "z" in ds.variables else "Band1"

    elevation = ds[z_var].values.astype(np.float64)
    # elevation shape: (10801, 21601) — rows=lat (S→N ascending), cols=lon (W→E)

    # Get source grid coordinates
    src_lats = ds[lat_var].values  # -90° → +90° (ascending, CF convention)
    src_lons = ds[lon_var].values  # -180° → +180°

    print(f"  Source: {elevation.shape[1]}×{elevation.shape[0]} "
          f"({elevation.nbytes / (1024*1024):.0f} MB)")
    ds.close()

    # Remove temporary decompressed file to save disk space
    if tmp_nc.exists() and tmp_nc != etopo1_gz_path:
        tmp_nc.unlink()
        print(f"  Removed temporary decompressed file")

    # --- Resample to target resolution using simple bilinear ---
    print(f"  Resampling to {width}×{height} ...")

    src_h, src_w = elevation.shape  # 10801, 21601
    result = np.zeros((height, width), dtype=np.float64)

    # Map target pixel centers to source fractional coordinates
    # Target grid: lat from +90° (row 0) to -90° (row H-1), lon from -180° to +180°
    for y in range(height):
        target_lat = 90.0 - y * 180.0 / (height - 1) if height > 1 else 0.0
        # ETOPO1 lat axis is ascending: row 0 = -90°S, row src_h-1 = +90°N
        src_row_f = (target_lat + 90.0) / 180.0 * (src_h - 1)
        r0 = max(int(np.floor(src_row_f)), 0)
        r1 = min(r0 + 1, src_h - 1)
        wr1 = src_row_f - r0  # weight for r1
        wr0 = 1.0 - wr1

        for x in range(width):
            target_lon = -180.0 + x * 360.0 / width  # pixel center
            # source col: -180° → col 0, +180° → col src_w-1
            src_col_f = (target_lon + 180.0) / 360.0 * (src_w - 1)
            c0 = max(int(np.floor(src_col_f)), 0)
            c1 = min(c0 + 1, src_w - 1)
            wc1 = src_col_f - c0
            wc0 = 1.0 - wc1

            # Bilinear: interpolate between 4 corners
            result[y, x] = (
                wr0 * (wc0 * elevation[r0, c0] + wc1 * elevation[r0, c1]) +
                wr1 * (wc0 * elevation[r1, c0] + wc1 * elevation[r1, c1])
            )

    metadata = {
        "source": "ETOPO1 Ice Surface (grid-registered)",
        "source_url": _ETOPO1_URL,
        "source_resolution": "1 arc-minute (~1.8 km at equator)",
        "target_resolution": f"{width}×{height} (equirectangular)",
        "elevation_units": "metres",
        "sea_level": 0.0,
        "note": "Ice surface — Antarctica and Greenland show ice sheet surface elevation",
    }

    print(f"  Resampled range: [{result.min():.0f}, {result.max():.0f}] m")
    return result, metadata


# ---------------------------------------------------------------------------
# Export as PNG + metadata
# ---------------------------------------------------------------------------


def save_elevation_png(
    elevation: np.ndarray,
    output_dir: Path,
    min_m: float = _ELEV_MIN_M,
    max_m: float = _ELEV_MAX_M,
) -> None:
    """Save elevation as 16-bit PNG with encoding metadata.

    Args:
        elevation: 2D array (height, width) in metres.
        output_dir: Output directory.
        min_m: Minimum elevation for normalization.
        max_m: Maximum elevation for normalization.
    """
    # Clamp and normalize
    actual_min = float(elevation.min())
    actual_max = float(elevation.max())

    # Expand range slightly for safety
    png_min = min(min_m, actual_min)
    png_max = max(max_m, actual_max)

    normalized = np.clip((elevation - png_min) / (png_max - png_min), 0.0, 1.0)
    data_16 = (normalized * 65535).astype(np.uint16)

    img = Image.fromarray(data_16, mode="I;16")
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / "elevation.png"
    img.save(str(png_path))
    print(f"  Saved elevation PNG: {png_path} ({img.size[0]}×{img.size[1]})")


def save_yaml_map(
    output_dir: Path, width: int, height: int, elev_min: float, elev_max: float,
    provenance: dict | None = None, planet_id: str | None = None,
) -> None:
    """Save map.yaml with elevation range and generation metadata."""
    import yaml

    # Infer planet_id from output directory name if not specified
    if planet_id is None:
        planet_id = output_dir.name

    map_data = {
        "planet_id": planet_id,
        "projection": "equirectangular",
        "width": width,
        "height": height,
        "elevation_min_m": elev_min,
        "elevation_max_m": elev_max,
        "sea_level_m": 0.0,
        "elevation_range_m": [round(elev_min, 1), round(elev_max, 1)],
        "pipeline_version": "etopo1-import",
    }
    if provenance:
        map_data["source"] = provenance.get("source", "")
        map_data["source_resolution"] = provenance.get("source_resolution", "")
    yaml_path = output_dir / "map.yaml"
    with yaml_path.open("w", encoding="utf-8") as f:
        yaml.dump(map_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"  Saved map.yaml: {yaml_path}")


# ---------------------------------------------------------------------------
# CVT mesh generation from elevation grid
# ---------------------------------------------------------------------------


def build_cvt_mesh_from_grid(
    elevation_grid: np.ndarray,
    num_nodes: int = _DEFAULT_MESH_NODES,
    seed: int = 42,
) -> object:
    """Generate a CVT mesh with real Earth elevation assigned to cells.

    Uses the terrain pipeline's Fibonacci + Lloyd CVT generation, then
    samples the elevation grid at each cell's geographic coordinates.

    Args:
        elevation_grid: 2D array (height, width) in metres.
        num_nodes: Number of CVT cells.
        seed: RNG seed for reproducibility.

    Returns:
        CVTMesh with elevation field populated from the real Earth grid.
    """
    from dreamulator.map.cvt_mesh import generate_cvt_mesh
    from dreamulator.map.elevation_codec import lon_lat_to_pixel
    from dreamulator.map.models import CVTMesh, VoronoiCell
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

    height, width = elevation_grid.shape

    config = TerrainPipelineConfig(
        seed=seed,
        num_nodes=num_nodes,
        lloyd_iterations=8,
        jitter_sigma=0.3,
        radius_km=_EARTH_RADIUS_KM,
    )

    print(f"  Generating CVT mesh with {num_nodes} nodes ...")
    mesh = generate_cvt_mesh(config)

    # Sample elevation from the real Earth grid at each cell center
    n_land = 0
    for c in mesh.cells:
        x, y = lon_lat_to_pixel(c.lon, c.lat, width, height)
        c.elevation = float(elevation_grid[y, x])
        if c.elevation >= 0.0:
            n_land += 1

    land_pct = n_land / num_nodes * 100
    print(f"  Sampled elevation: {n_land}/{num_nodes} land cells ({land_pct:.1f}%)")
    print(f"  Earth actual land fraction: ~29%")

    return mesh


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import real Earth elevation (ETOPO1) into dreamulator format",
    )
    parser.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {_DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--resolution",
        default=f"{_DEFAULT_WIDTH}x{_DEFAULT_HEIGHT}",
        help="Output resolution WxH (default: 2048x1024)",
    )
    parser.add_argument(
        "--mesh-nodes",
        type=int,
        default=_DEFAULT_MESH_NODES,
        help=f"Number of CVT mesh nodes (default: {_DEFAULT_MESH_NODES})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed (default: 42)",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download if ETOPO1 file already exists in temp dir",
    )
    parser.add_argument(
        "--skip-mesh",
        action="store_true",
        help="Skip CVT mesh generation (only produce elevation.png)",
    )
    args = parser.parse_args()

    res_w, res_h = map(int, args.resolution.split("x"))

    project_root = _find_project_root()
    output_dir = project_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Download ---
    tmp_dir = Path(tempfile.gettempdir()) / "dreamulator_etopo1"
    tmp_dir.mkdir(exist_ok=True)
    etopo1_gz = tmp_dir / "ETOPO1_Ice_g_gmt4.grd.gz"

    if args.skip_download and etopo1_gz.exists():
        print(f"Using cached ETOPO1: {etopo1_gz}")
    else:
        download_etopo1(etopo1_gz)

    # --- Extract → raster ---
    elevation, provenance = extract_etopo1_to_raster(etopo1_gz, res_w, res_h)

    elev_min = float(elevation.min())
    elev_max = float(elevation.max())

    # --- Save PNG + metadata ---
    save_elevation_png(elevation, output_dir, elev_min, elev_max)
    save_yaml_map(output_dir, res_w, res_h, elev_min, elev_max, provenance)

    # --- Build CVT mesh ---
    if not args.skip_mesh:
        mesh = build_cvt_mesh_from_grid(elevation, args.mesh_nodes, args.seed)

        mesh_json = mesh.model_dump()
        mesh_path = output_dir / "cvt_mesh.json"
        with mesh_path.open("w", encoding="utf-8") as f:
            json.dump(mesh_json, f, indent=2, default=str)
        print(f"  Saved CVT mesh: {mesh_path} ({mesh_path.stat().st_size / (1024*1024):.1f} MB)")

    print("\nDone! Real Earth elevation imported successfully.")
    print(f"  Output: {output_dir}")
    print(f"  Next: uv run python scripts/validate_climate.py earth")


def _find_project_root() -> Path:
    """Find the project root directory (with pyproject.toml)."""
    d = Path.cwd()
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


if __name__ == "__main__":
    main()
