"""Import real Earth tectonic plate data (PB2002) onto an imported ETOPO1 mesh.

The elevation importer (``import_earth_elevation.py``) produces a CVT mesh with
real ETOPO1 elevation but no plates / crust classification (``crust_type`` left
``oceanic``, ``plate_id`` unset).  This module fills in the tectonic layer from
real data:

- **Plates** — PB2002 (Bird 2003, doi:10.1029/2001GC000252), the standard global
  plate-boundary model (52 plates).  Assigns each cell a ``plate_id`` by a
  point-in-polygon test against the plate outlines.
- **Crust type** — CRUST1.0 (Laske et al. 2013), the real seismic-derived crustal
  type: 36 crustal types mapped to continental / oceanic / transitional, sampled
  from the 1° grid at cell centres.
- **Boundaries** — PB2002 ``steps.dat``, the manually-classified boundary steps
  (Bird 2003's 7 classes SUB/OSR/OTF/CRB/CTF/OCB/CCB), mapped to
  convergent/divergent/transform and assigned to cells within ~200 km of a step.

The Euler poles come from ``PB2002_poles.dat`` (pole latitude / longitude /
degrees-per-Ma CCW), converted to the model's ``EulerPole`` (unit rotation axis +
``omega_rad_yr``).

Usage mirrors the elevation importer::

    uv run python scripts/import_earth_tectonics.py \
        --output-dir private/worlds/earth/maps/planet_earth

Inputs (downloaded on first run, cached under ``tempfile.gettempdir()/
dreamulator_pb2002``):
- ``PB2002_plates.json`` — plate outlines (GeoJSON, fraxen/tectonicplates on
  GitHub, ODC-BY licence; plate names and polygons only).
- ``PB2002_poles.dat.txt`` — Euler poles (pyrocko mirror of peterbird.name).

Data provenance: Bird, P. (2003), An updated digital model of plate boundaries,
Geochemistry, Geophysics, Geosystems, 4(3), 1027, doi:10.1029/2001GC000252.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.request import Request, urlopen

import numpy as np

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh

# A parsed plate outline: ``{"name": str, "rings": [[(lon, lat), ...], ...]}``.
PlateEntry = dict[str, Any]
# Euler pole triple: ``(pole_lat_deg, pole_lon_deg, deg_per_ma)``.
Pole = tuple[float, float, float]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# PB2002 plate outlines (GeoJSON, ODC-BY) — pinned to the fraxen/tectonicplates
# GitHub repository (raw master).  Provides plate name + polygon geometry.
_PB2002_PLATES_URL = (
    "https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/PB2002_plates.json"
)

# PB2002 Euler poles (mirror of peterbird.name, original ASCII data).
_PB2002_POLES_URL = "https://mirror.pyrocko.org/peterbird.name/oldFTP/PB2002/PB2002_poles.dat.txt"

# PB2002 boundary steps — the manually-classified boundary classes (SUB/OSR/OTF/…),
# the real "boundary type" observation (vs the euler-pole derivation in
# detect_boundaries).
_PB2002_STEPS_URL = "https://mirror.pyrocko.org/peterbird.name/oldFTP/PB2002/PB2002_steps.dat.txt"

# CRUST1.0 crustal-type add-on (Laske et al. 2013) — the real crust classification.
_CRUST1_URL = "https://igppweb.ucsd.edu/~gabi/crust1/crust1.0-addon.tar.gz"

_CACHE_DIR_NAME = "dreamulator_pb2002"

# Ocean–continent boundary (OCB).  PB2002's own criterion: a plate-boundary step
# is "oceanic" when sea floor age < 180 Ma *or* water depth > 2000 m, so 2000 m
# is the physical continental/oceanic crust divide on passive margins.
_OCB_DEPTH_M = -2000.0
# Base of the continental slope — the "transitional" (ocean–continent transition
# / rifted margin) band between slope and abyssal plain.
_TRANSITIONAL_DEPTH_M = -3000.0

# Plate-type thresholds (area-weighted continental-crust fraction).  A plate is
# "continental"/"oceanic" when decisively one type, "mixed" otherwise.
_CONTINENTAL_FRACTION_CONTINENTAL = 0.6
_CONTINENTAL_FRACTION_OCEANIC = 0.4

_EARTH_RADIUS_KM = 6371.0

_USER_AGENT = "dreamulator/0.34"


# ---------------------------------------------------------------------------
# Download / cache
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / _CACHE_DIR_NAME


def _download(url: str, target: Path) -> None:
    """Download a URL to *target* (with proxy support from the environment)."""
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy_url and proxy_url.startswith("http://"):
        from urllib.request import ProxyHandler, build_opener, install_opener

        opener = build_opener(ProxyHandler({"https": proxy_url, "http": proxy_url}))
        opener.addheaders = [("User-Agent", _USER_AGENT)]
        install_opener(opener)

    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=120) as response:  # noqa: S310
        target.write_bytes(response.read())


def ensure_pb2002(cache: Path | None = None) -> tuple[Path, Path]:
    """Download (if needed) and return (plates_geojson, poles_txt) paths."""
    cache = cache or _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    plates = cache / "PB2002_plates.json"
    poles = cache / "PB2002_poles.dat.txt"
    if not plates.exists():
        print(f"Downloading PB2002 plates: {_PB2002_PLATES_URL}")
        _download(_PB2002_PLATES_URL, plates)
    if not poles.exists():
        print(f"Downloading PB2002 poles: {_PB2002_POLES_URL}")
        _download(_PB2002_POLES_URL, poles)
    return plates, poles


def ensure_pb2002_steps(cache: Path | None = None) -> Path:
    """Download (if needed) and return the PB2002 boundary-steps path."""
    cache = cache or _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    steps = cache / "PB2002_steps.dat.txt"
    if not steps.exists():
        print(f"Downloading PB2002 steps: {_PB2002_STEPS_URL}")
        _download(_PB2002_STEPS_URL, steps)
    return steps


def ensure_crust1(cache: Path | None = None) -> Path:
    """Download (if needed) and return the CRUST1.0 type-grid path."""
    import tarfile

    cache = cache or _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    grid = cache / "CNtype1-1.txt"
    if not grid.exists():
        tarball = cache / "crust1.0-addon.tar.gz"
        if not tarball.exists():
            print(f"Downloading CRUST1.0: {_CRUST1_URL}")
            _download(_CRUST1_URL, tarball)
        with tarfile.open(tarball, "r:gz") as tf:
            member = tf.extractfile("CNtype1-1.txt")
            assert member is not None
            grid.write_bytes(member.read())
    return grid


# ---------------------------------------------------------------------------
# PB2002 parsing
# ---------------------------------------------------------------------------


def parse_pb2002_plates(geojson_path: Path) -> dict[str, PlateEntry]:
    """Parse ``PB2002_plates.json`` → ``{code: {"name": str, "rings": [...]}}``.

    Each ring is a list of ``(lon, lat)`` float pairs in degrees.  A plate may be
    represented by several polygons (MultiPolygon, or duplicated features); all
    exterior rings are collected under the same plate code.
    """
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    plates: dict[str, PlateEntry] = {}
    for feature in data["features"]:
        code = feature["properties"]["Code"]
        name = feature["properties"]["PlateName"]
        geom = feature["geometry"]
        rings: list[list[tuple[float, float]]] = []
        if geom["type"] == "Polygon":
            rings.append([(float(p[0]), float(p[1])) for p in geom["coordinates"][0]])
        elif geom["type"] == "MultiPolygon":
            for poly in geom["coordinates"]:
                rings.append([(float(p[0]), float(p[1])) for p in poly[0]])
        else:
            continue
        entry = plates.setdefault(code, {"name": name, "rings": []})
        entry["rings"].extend(rings)
        # Keep the first-seen name (duplicated features share the same name).
    return plates


def parse_pb2002_poles(txt_path: Path) -> dict[str, Pole]:
    """Parse ``PB2002_poles.dat.txt`` → ``{code: (lat, lon, deg_per_ma)}``.

    The file's fixed-width columns are ``ID, NLat, ELon, Deg/Ma CCW`` (see the
    trailing header comment in the file itself).
    """
    poles: dict[str, Pole] = {}
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        code = parts[0]
        try:
            lat = float(parts[1])
            lon = float(parts[2])
            deg_per_ma = float(parts[3])
        except ValueError:
            continue
        poles[code] = (lat, lon, deg_per_ma)
    return poles


# ---------------------------------------------------------------------------
# Geometry — plate assignment (2-D even-odd point-in-polygon)
# ---------------------------------------------------------------------------


def points_in_ring(
    lons: np.ndarray, lats: np.ndarray, ring: list[tuple[float, float]]
) -> np.ndarray:
    """Vectorised even-odd point-in-polygon over all cells for one ring.

    Args:
        lons: Cell longitudes (deg), shape (N,).
        lats: Cell latitudes (deg), shape (N,).
        ring: Ring as a list of ``(lon, lat)`` pairs (closed or not).

    Returns:
        Boolean array, shape (N,), True where the cell is inside the ring.
    """
    n = len(ring)
    if n < 3:
        return np.zeros(lons.shape, dtype=bool)
    inside = np.zeros(lons.shape, dtype=bool)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        # Cells whose latitude lies strictly between the edge's two endpoints.
        cond = (yi > lats) != (yj > lats)
        # x-coordinate of the edge at the cell's latitude.
        denom = yj - yi
        with np.errstate(divide="ignore", invalid="ignore"):
            x_int = xj - (xj - xi) * (yj - lats) / denom
        hit = cond & (lons < x_int)
        inside[hit] = ~inside[hit]
        j = i
    return inside


def assign_plate_ids(
    lons: np.ndarray,
    lats: np.ndarray,
    plates: dict[str, PlateEntry],
) -> np.ndarray:
    """Assign each cell to a PB2002 plate code.

    Cells inside no plate (digitisation gaps at boundaries) are assigned to the
    nearest plate by polygon-centroid great-circle distance.

    Returns:
        Array of plate codes (str), shape (N,).
    """
    n = len(lons)
    plate_id = np.full(n, "", dtype=object)

    for code, entry in plates.items():
        inside = np.zeros(n, dtype=bool)
        for ring in entry["rings"]:
            # Raw even-odd: the fraxen GeoJSON already splits antimeridian-
            # crossing plates into MultiPolygon parts; the only plates left with
            # a single-ring ±180° jump are the polar caps (Antarctica, North
            # America), whose jump lies along the pole cut at lat ±90°, which the
            # even-odd rule skips automatically (no cell is below lat −90).
            inside |= points_in_ring(lons, lats, ring)
        plate_id[inside] = code

    unassigned = np.flatnonzero(plate_id == "")
    if unassigned.size:
        # Fallback: nearest plate centroid (great-circle) for any cell in a gap.
        centroids: list[tuple[str, float, float]] = []
        for code, entry in plates.items():
            ring_lons = [p[0] for ring in entry["rings"] for p in ring]
            ring_lats = [p[1] for ring in entry["rings"] for p in ring]
            centroids.append((code, float(np.mean(ring_lons)), float(np.mean(ring_lats))))
        cent_lons = np.array([c[1] for c in centroids])
        cent_lats = np.array([c[2] for c in centroids])
        for i in unassigned:
            d = np.hypot(
                (lons[i] - cent_lons) * np.cos(np.radians(lats[i])),
                lats[i] - cent_lats,
            )
            plate_id[i] = centroids[int(np.argmin(d))][0]
    return plate_id


# ---------------------------------------------------------------------------
# Crust type (OCB from ETOPO1 bathymetry)
# ---------------------------------------------------------------------------


def crust_type_from_elevation(elevation_m: np.ndarray) -> np.ndarray:
    """Classify per-cell crust from bathymetry via the ocean–continent boundary.

    - ``continental``: elevation ≥ −2000 m (land + shelf + upper slope; the
      PB2002 "not oceanic" criterion).
    - ``transitional``: −3000 m ≤ elevation < −2000 m (continental slope).
    - ``oceanic``: elevation < −3000 m (abyssal plain).

    Args:
        elevation_m: Cell elevation in metres, shape (N,).

    Returns:
        Array of crust-type strings, shape (N,).
    """
    crust = np.full(elevation_m.shape, "oceanic", dtype=object)
    crust[elevation_m >= _OCB_DEPTH_M] = "continental"
    crust[(elevation_m >= _TRANSITIONAL_DEPTH_M) & (elevation_m < _OCB_DEPTH_M)] = "transitional"
    return crust


# ---------------------------------------------------------------------------
# PB2002 boundary steps — real boundary-type observation
# ---------------------------------------------------------------------------

# PB2002 step class → model boundary_type (Bird 2003's 7 boundary classes).
_PB2002_STEP_TO_BOUNDARY: dict[str, str] = {
    "SUB": "convergent",  # subduction
    "OSR": "divergent",  # oceanic spreading ridge
    "CRB": "divergent",  # continental rift boundary
    "OTF": "transform",  # oceanic transform fault
    "CTF": "transform",  # continental transform fault
    "OCB": "convergent",  # oceanic convergent boundary
    "CCB": "convergent",  # continental convergent boundary
}

# Boundary-zone width (km): cells within this distance of a step get its class.
_BOUNDARY_ZONE_KM = 200.0


def parse_pb2002_steps(text: str) -> list[tuple[float, float, float, float, str]]:
    """Parse ``PB2002_steps.dat.txt`` → ``[(lon1, lat1, lon2, lat2, class), ...]``."""
    steps: list[tuple[float, float, float, float, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            lon1, lat1, lon2, lat2 = (
                float(parts[2]),
                float(parts[3]),
                float(parts[4]),
                float(parts[5]),
            )
        except ValueError:
            continue
        # Strip the ":" orientation prefix and the "*" orogen marker (PB2002
        # suffixes e.g. "CCB*" — still a continental convergent boundary).
        cls = parts[-1].lstrip(":").rstrip("*")
        steps.append((lon1, lat1, lon2, lat2, cls))
    return steps


def assign_pb2002_boundaries(mesh: CVTMesh, steps_text: str) -> None:
    """Assign ``boundary_type`` per cell from the nearest PB2002 step's class.

    The steps are the manually-classified plate-boundary segments (Bird 2003);
    each cell within ``_BOUNDARY_ZONE_KM`` of a step gets that step's class
    (convergent/divergent/transform).  Cells far from any step keep None.
    """
    from scipy.spatial import cKDTree

    # Clear any previous boundary assignment so far-from-boundary cells don't
    # keep stale values from an earlier run.
    for c in mesh.cells:
        c.boundary_type = None
        c.convergence_rate_cm_yr = 0.0

    steps = parse_pb2002_steps(steps_text)
    step_xyz = np.empty((len(steps), 3), dtype=np.float64)
    step_cls = np.empty(len(steps), dtype=object)
    for k, (lon1, lat1, lon2, lat2, cls) in enumerate(steps):
        # Midpoint of the short step (~44.7 km) — a good proxy for its location.
        mlon = 0.5 * (lon1 + lon2)
        mlat = 0.5 * (lat1 + lat2)
        mlat_r = np.radians(mlat)
        mlon_r = np.radians(mlon)
        step_xyz[k] = (
            np.cos(mlat_r) * np.cos(mlon_r),
            np.sin(mlat_r),
            np.cos(mlat_r) * np.sin(mlon_r),
        )
        step_cls[k] = cls

    cell_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    tree = cKDTree(step_xyz)
    chord, idx = tree.query(cell_xyz, k=1)
    dist_km = _EARTH_RADIUS_KM * 2.0 * np.arcsin(np.clip(chord / 2.0, 0.0, 1.0))

    n_boundary = 0
    for i, c in enumerate(mesh.cells):
        if dist_km[i] <= _BOUNDARY_ZONE_KM:
            c.boundary_type = _PB2002_STEP_TO_BOUNDARY.get(str(step_cls[idx[i]]))
            n_boundary += 1
    print(f"  Assigned PB2002 boundary types: {n_boundary}/{len(mesh.cells)} cells")


# ---------------------------------------------------------------------------
# Euler pole conversion
# ---------------------------------------------------------------------------


def euler_pole_from_latlon_rate(
    lat_deg: float, lon_deg: float, deg_per_ma: float
) -> dict[str, float]:
    """Convert a PB2002 pole (lat, lon, deg/Ma CCW) to the model's EulerPole dict.

    The outward unit vector at (lat, lon) is the rotation axis; the magnitude is
    deg/Ma converted to rad/yr.  Positive rate = counter-clockwise as seen from
    outside the Earth (the same convention as ``boundary_detector``).
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    cos_lat = math.cos(lat)
    axis = (cos_lat * math.cos(lon), math.sin(lat), cos_lat * math.sin(lon))
    omega_rad_yr = deg_per_ma * (math.pi / 180.0) / 1.0e6
    return {
        "x": axis[0],
        "y": axis[1],
        "z": axis[2],
        "omega_rad_yr": omega_rad_yr,
    }


# ---------------------------------------------------------------------------
# Plate assembly
# ---------------------------------------------------------------------------


def build_tectonic_plates(
    mesh_cells: list[Any],
    plate_id: np.ndarray,
    plates: dict[str, PlateEntry],
    poles: dict[str, Pole],
) -> list[dict[str, Any]]:
    """Build ``TectonicPlate`` dicts (real names/types/euler poles/cell_ids)."""
    from dreamulator.map.models import EulerPole, PlateType, TectonicPlate

    by_plate: dict[str, list[int]] = {}
    for i, code in enumerate(plate_id):
        by_plate.setdefault(code, []).append(i)

    result: list[dict[str, Any]] = []
    for code, cell_ids in by_plate.items():
        name = plates[code]["name"]
        # Area-weighted continental fraction (cells are ~equal-area on a CVT).
        area = np.array([mesh_cells[i].area_km2 for i in cell_ids])
        is_cont = np.array([mesh_cells[i].crust_type == "continental" for i in cell_ids])
        cont_frac = float(np.sum(area[is_cont]) / np.sum(area)) if area.sum() > 0 else 0.0
        if cont_frac >= _CONTINENTAL_FRACTION_CONTINENTAL:
            ptype = PlateType.CONTINENTAL
        elif cont_frac <= _CONTINENTAL_FRACTION_OCEANIC:
            ptype = PlateType.OCEANIC
        else:
            ptype = PlateType.MIXED

        if code in poles:
            lat, lon, deg_per_ma = poles[code]
            euler = EulerPole(**euler_pole_from_latlon_rate(lat, lon, deg_per_ma))
        else:
            # Missing pole (shouldn't happen) — zero rotation placeholder.
            euler = EulerPole(x=0.0, y=1.0, z=0.0, omega_rad_yr=0.0)

        plate = TectonicPlate(
            id=code,
            name=name,
            type=ptype,
            cell_ids=sorted(cell_ids),
            euler_pole=euler,
            growth_speed_multiplier=1.0,
        )
        result.append(plate.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _load_mesh(mesh_path: Path) -> CVTMesh:
    """Load a compressed CVT mesh file as a ``CVTMesh`` model."""
    from dreamulator.map.export import decompress_mesh_bytes
    from dreamulator.map.models import CVTMesh

    data = mesh_path.read_bytes()
    return CVTMesh.model_validate(json.loads(decompress_mesh_bytes(data)))


def _save_mesh(mesh: CVTMesh, mesh_path: Path) -> None:
    """Write a ``CVTMesh`` model back, gzip-compressed (same as the pipeline)."""
    from dreamulator.map.export import compress_mesh_bytes

    mesh_path.write_bytes(
        compress_mesh_bytes(json.dumps(mesh.model_dump(mode="json")).encode("utf-8"))
    )


def import_earth_tectonics(output_dir: Path, *, cache: Path | None = None) -> None:
    """Assign real plates + crust + boundaries onto an imported-elevation mesh.

    Reads ``cvt_mesh.json`` / ``map.yaml`` from *output_dir*, writes
    ``plates.json`` and updates ``cvt_mesh.json`` / ``map.yaml`` in place.
    """
    mesh_path = output_dir / "cvt_mesh.json"
    if not mesh_path.exists():
        raise FileNotFoundError(f"{mesh_path} not found — run the ETOPO1 elevation importer first.")

    plates_geojson, poles_txt = ensure_pb2002(cache)
    plates = parse_pb2002_plates(plates_geojson)
    poles = parse_pb2002_poles(poles_txt)
    print(f"Parsed PB2002: {len(plates)} plates, {len(poles)} Euler poles")

    mesh = _load_mesh(mesh_path)
    n = len(mesh.cells)
    lons = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    lats = np.array([c.lat for c in mesh.cells], dtype=np.float64)

    # 1. plate_id per cell
    plate_id = assign_plate_ids(lons, lats, plates)
    n_assigned = int(np.count_nonzero(plate_id != ""))
    print(f"Assigned plates: {n_assigned}/{n} cells ({len(set(plate_id))} plates)")

    # 2. crust_type per cell — real CRUST1.0 crustal type (not the OCB heuristic).
    from dreamulator.map.crust1 import parse_crust1_type, sample_crust1

    crust1_path = ensure_crust1(cache)
    crust1_grid = parse_crust1_type(crust1_path.read_text(encoding="utf-8"))
    crust = sample_crust1(crust1_grid, lats, lons)
    for i, c in enumerate(mesh.cells):
        c.crust_type = str(crust[i])
        c.plate_id = str(plate_id[i])

    # 3. Build the TectonicPlate list (plates.json) — plate names/types/poles.
    plate_dicts = build_tectonic_plates(mesh.cells, plate_id, plates, poles)

    # 4. boundary_type per cell — real PB2002 boundary-step classes (not the
    #    euler-pole derivation in detect_boundaries).
    steps_path = ensure_pb2002_steps(cache)
    assign_pb2002_boundaries(mesh, steps_path.read_text(encoding="utf-8"))

    # 4. Write outputs
    from dreamulator.map.models import sanitize_nonfinite

    plates_path = output_dir / "plates.json"
    plates_path.write_text(json.dumps(sanitize_nonfinite(plate_dicts), indent=2), encoding="utf-8")
    print(f"  Saved plates.json: {plates_path} ({len(plate_dicts)} plates)")

    _save_mesh(mesh, mesh_path)
    print(f"  Updated cvt_mesh.json: {mesh_path}")

    _update_map_yaml(output_dir, len(plate_dicts))
    print(f"  Updated map.yaml: {output_dir / 'map.yaml'}")


def _update_map_yaml(output_dir: Path, num_plates: int) -> None:
    """Merge plate metadata (num_plates, plate_source) into map.yaml."""
    import yaml

    map_yaml_path = output_dir / "map.yaml"
    data: dict[str, Any] = {}
    if map_yaml_path.exists():
        data = yaml.safe_load(map_yaml_path.read_text(encoding="utf-8")) or {}
    data["num_plates"] = num_plates
    data["plate_source"] = "PB2002 (Bird 2003, doi:10.1029/2001GC000252)"
    with map_yaml_path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import real Earth tectonic plates (PB2002) onto an ETOPO1 mesh",
    )
    parser.add_argument(
        "--output-dir",
        default="data/worlds/earth/maps/planet_earth",
        help="Map output directory (must already contain cvt_mesh.json from the elevation import)",
    )
    args = parser.parse_args()

    project_root = _find_project_root()
    output_dir = project_root / args.output_dir
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
    import_earth_tectonics(output_dir)
    print("\nDone! Real Earth tectonic data imported.")


def _find_project_root() -> Path:
    d = Path.cwd()
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


if __name__ == "__main__":
    main()
