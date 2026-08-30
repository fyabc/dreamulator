"""Import real Earth land/ocean/water data (GSHHG) as a per-cell water class.

The elevation importer (ETOPO1) fills cell elevation, and the tectonic importer
(PB2002) fills plates + crust; neither distinguishes *dry* below-sea-level
basins (Turpan, −154 m) from *water*.  This module fills the ``water_class``
field from GSHHG (Global Self-consistent Hierarchical High-resolution
Geography, Wessel & Smith 1996), which carries a 5-level hierarchy:

    ocean (0) → land (1) → lake (2) → island-in-lake (3) → pond (4)

We use level 1 (land polygons, the ocean/land shoreline) and level 2 (lakes).
A cell is classified via ``water_bodies.classify_ocean_land``: land if inside a
land polygon, ocean otherwise — except that inland lakes are size-split: lakes
larger than the maritime-moderation area (Caspian, ~371 000 km²) are "ocean",
smaller ones (Dead Sea, ~600 km²) are "land".

Crucially, the GSHHG shoreline already includes marginal seas connected through
narrow straits (Red Sea via Bab-el-Mandeb, Black Sea via the Bosphorus) as
*ocean*, so the 200k-mesh strait-resolution problem never arises.

Usage mirrors the other importers::

    uv run python scripts/import_earth_watermask.py \
        --output-dir private/worlds/earth/maps/planet_earth

Data provenance: Wessel, P. & Smith, W. H. F. (1996), A global, self-consistent,
hierarchical, high-resolution shoreline database, J. Geophys. Res. 101(B4).
Downloaded from https://www.soest.hawaii.edu/pwessel/gshhg/ (LGPL-3).
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np

from dreamulator.map.water_bodies import classify_ocean_land, read_shp_polygons

# GSHHG shapefile bundle (LGPL-3).  We use the "intermediate" resolution L1
# (shoreline) and L2 (lakes) — a good accuracy/size balance for a ~1° mesh.
_GSHHG_URL = "https://www.soest.hawaii.edu/pwessel/gshhg/gshhg-shp-2.3.7.zip"
_GSHHG_RESOLUTION = "i"  # c/ l/ i/ h/ f (coarse → full)
_CACHE_DIR_NAME = "dreamulator_gshhg"

_USER_AGENT = "dreamulator/0.34"


def _cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / _CACHE_DIR_NAME


def _download(url: str, target: Path) -> None:
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy_url and proxy_url.startswith("http://"):
        from urllib.request import ProxyHandler, build_opener, install_opener

        opener = build_opener(ProxyHandler({"https": proxy_url, "http": proxy_url}))
        opener.addheaders = [("User-Agent", _USER_AGENT)]
        install_opener(opener)
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=300) as response:  # noqa: S310
        target.write_bytes(response.read())


def ensure_gshhg(cache: Path | None = None) -> tuple[Path, Path, Path]:
    """Download (if needed) and return (land_shp, lake_shp, ice_shp) paths.

    ``land`` is GSHHS level 1 (bedrock shoreline), ``lake`` level 2, and ``ice``
    level 5 (Antarctic ice front).  Antarctica's ice-covered continent is *not*
    in level 1 — its bedrock shoreline is mostly below sea level — so the ice
    front (L5) must be added back as land, otherwise the whole continent is
    misclassified as ocean.
    """
    cache = cache or _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    land = cache / f"GSHHS_{_GSHHG_RESOLUTION}_L1.shp"
    lake = cache / f"GSHHS_{_GSHHG_RESOLUTION}_L2.shp"
    ice = cache / f"GSHHS_{_GSHHG_RESOLUTION}_L5.shp"
    if not (land.exists() and lake.exists() and ice.exists()):
        zip_path = cache / "gshhg-shp-2.3.7.zip"
        if not zip_path.exists():
            print(f"Downloading GSHHG: {_GSHHG_URL}")
            _download(_GSHHG_URL, zip_path)
        print("Extracting GSHHG L1/L2/L5 shapefiles ...")
        with zipfile.ZipFile(zip_path) as z:
            for name, target in (
                (f"GSHHS_shp/{_GSHHG_RESOLUTION}/GSHHS_{_GSHHG_RESOLUTION}_L1.shp", land),
                (f"GSHHS_shp/{_GSHHG_RESOLUTION}/GSHHS_{_GSHHG_RESOLUTION}_L2.shp", lake),
                (f"GSHHS_shp/{_GSHHG_RESOLUTION}/GSHHS_{_GSHHG_RESOLUTION}_L5.shp", ice),
            ):
                target.write_bytes(z.read(name))
    return land, lake, ice


def import_earth_watermask(output_dir: Path, *, cache: Path | None = None) -> None:
    """Classify each cell's ``water_class`` from GSHHG and write it back."""
    from dreamulator.map.export import compress_mesh_bytes, decompress_mesh_bytes
    from dreamulator.map.models import CVTMesh

    mesh_path = output_dir / "cvt_mesh.json"
    if not mesh_path.exists():
        raise FileNotFoundError(f"{mesh_path} not found — run the ETOPO1 elevation importer first.")

    land_shp, lake_shp, ice_shp = ensure_gshhg(cache)
    land_polys = read_shp_polygons(land_shp.read_bytes())
    lake_polys = read_shp_polygons(lake_shp.read_bytes())
    ice_polys = read_shp_polygons(ice_shp.read_bytes())
    # Antarctica is an ice-covered polar cap: its land is delimited by the ice
    # front (L5), not the bedrock shoreline (L1).  Merge L5 into the land polygons.
    land_polys = land_polys + ice_polys
    print(f"Parsed GSHHG: {len(land_polys)} land polygons (+ice front), {len(lake_polys)} lakes")

    mesh = CVTMesh.model_validate(json.loads(decompress_mesh_bytes(mesh_path.read_bytes())))
    lons = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    lats = np.array([c.lat for c in mesh.cells], dtype=np.float64)

    land = classify_ocean_land(lons, lats, land_polys, lake_polys)
    for i, c in enumerate(mesh.cells):
        c.water_class = "land" if bool(land[i]) else "ocean"

    n_land = int(land.sum())
    land_pct = 100 * n_land / len(mesh.cells)
    print(f"Assigned water_class: {n_land}/{len(mesh.cells)} land ({land_pct:.1f}%)")

    mesh_path.write_bytes(
        compress_mesh_bytes(json.dumps(mesh.model_dump(mode="json")).encode("utf-8"))
    )
    print(f"  Updated cvt_mesh.json: {mesh_path}")


def _find_project_root() -> Path:
    d = Path.cwd()
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import real Earth water mask (GSHHG) as per-cell water_class",
    )
    parser.add_argument(
        "--output-dir",
        default="data/worlds/earth/maps/planet_earth",
        help="Map output directory (must contain cvt_mesh.json from the elevation import)",
    )
    args = parser.parse_args()
    output_dir = _find_project_root() / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    import_earth_watermask(output_dir)
    print("\nDone! Real Earth water mask imported.")


if __name__ == "__main__":
    main()
