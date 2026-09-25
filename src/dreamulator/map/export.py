"""Export CVT mesh data to equirectangular raster grids.

Converts scattered CVT cell data (on the sphere) to regular lat/lon grids
suitable for PNG export, map visualization, and Gaea import.

See ``docs/design/pipelines/geological-pipeline.md`` §10 for algorithm details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Union

import numpy as np
from PIL import Image

from .palettes import ColorStop, hex_to_rgb, sequential_color
from .pipeline_types import TerrainPipelineConfig, make_equirect_grid

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from scipy.spatial import cKDTree

    from .models import CVTMesh, TectonicPlate

logger = logging.getLogger(__name__)

# Mesh payloads are either a validated model or the plain dict form used by
# the importers (which assemble cell dicts before any model validation).
CVTMeshLike = Union["CVTMesh", dict[str, Any]]


# ---------------------------------------------------------------------------
# Equirectangular interpolation
# ---------------------------------------------------------------------------


def build_export_tree(mesh: CVTMesh) -> cKDTree:
    """Build the unit-sphere KD-tree for equirectangular export.

    Callers exporting multiple fields for the same mesh should build this
    once and pass it to ``export_equirectangular`` (Stage 0.3: avoids
    rebuilding the tree per field).
    """
    from scipy.spatial import cKDTree

    cell_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells])
    return cKDTree(cell_xyz)


def export_cell_index_grid(
    mesh: CVTMesh,
    width: int = 4096,
    height: int = 2048,
    tree: cKDTree | None = None,
) -> np.ndarray:
    """Map each equirectangular pixel to the index of its nearest CVT cell.

    Returns a 2D integer array of shape ``(height, width)``.  This is the
    shared rasterization primitive for numeric fields (see
    ``export_equirectangular``) and coloured/categorical layer export.
    """
    if tree is None:
        tree = build_export_tree(mesh)

    # Create output grid
    lat_grid, lon_grid = make_equirect_grid(width, height)

    # Convert grid to Cartesian on unit sphere
    cos_lat = np.cos(lat_grid)
    grid_x = cos_lat * np.cos(lon_grid)
    grid_y = np.sin(lat_grid)
    grid_z = cos_lat * np.sin(lon_grid)

    # Flatten for KD-tree query
    grid_flat = np.column_stack(
        [
            grid_x.ravel(),
            grid_y.ravel(),
            grid_z.ravel(),
        ]
    )

    # Query nearest cell for each grid point
    _, indices = tree.query(grid_flat)
    return np.asarray(indices).reshape(height, width)


def export_equirectangular(
    mesh: CVTMesh,
    width: int = 4096,
    height: int = 2048,
    field: str = "elevation",
    tree: cKDTree | None = None,
) -> np.ndarray:
    """Interpolate CVT cell data onto a regular equirectangular grid.

    Uses scipy's nearest-neighbor interpolation on the sphere (via
    SphericalVoronoi-based lookup or angular distance).

    Args:
        mesh: The CVT mesh.
        width: Output grid width in pixels.
        height: Output grid height in pixels.
        field: Cell attribute to export (e.g. "elevation", "temperature_C").

    Returns:
        2D array of shape (height, width).
    """
    logger.info(
        "Exporting '%s' to equirectangular grid (%d×%d)",
        field,
        width,
        height,
    )

    indices = export_cell_index_grid(mesh, width, height, tree=tree)

    # Extract field values
    cell_values = np.array(
        [getattr(mesh.cells[i], field, 0.0) for i in range(mesh.num_cells)],
        dtype=np.float64,
    )
    result = cell_values[indices]

    logger.info(
        "  Export complete: range [%.2f, %.2f]",
        np.min(result),
        np.max(result),
    )
    return np.asarray(result)


def export_multiple_fields(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    fields: list[str] | None = None,
) -> dict[str, np.ndarray]:
    """Export multiple cell fields to equirectangular grids.

    Args:
        mesh: The CVT mesh.
        config: Pipeline configuration.
        fields: List of field names. Defaults to ["elevation"].

    Returns:
        Dict of field_name → 2D grid.
    """
    if fields is None:
        fields = ["elevation"]

    tree = build_export_tree(mesh)
    results = {}
    for field_name in fields:
        results[field_name] = export_equirectangular(
            mesh,
            config.export_width,
            config.export_height,
            field=field_name,
            tree=tree,
        )
    return results


# ---------------------------------------------------------------------------
# Coloured layer export (single-source palettes, shared with the frontend)
# ---------------------------------------------------------------------------


def render_categorical_layer(
    mesh: CVTMesh,
    indices: np.ndarray,
    field: str,
    palette: dict[str, str],
    ocean_fallback: str | None = None,
) -> np.ndarray:
    """Render a categorical cell field (str) to an RGBA ``(h, w, 4)`` uint8 array.

    Cells whose field value is absent/unknown are transparent (alpha 0).  When
    ``ocean_fallback`` is given, ocean cells (``elevation < 0``, matching the
    frontend hardcoded threshold) with no class get that palette entry.
    """
    cell_colors = np.zeros((mesh.num_cells, 4), dtype=np.uint8)
    for i, cell in enumerate(mesh.cells):
        value = getattr(cell, field, None)
        if value is not None and value in palette:
            rgb = hex_to_rgb(palette[value])
        elif ocean_fallback is not None and cell.elevation < 0:
            rgb = hex_to_rgb(palette[ocean_fallback])
        else:
            continue
        cell_colors[i, 0], cell_colors[i, 1], cell_colors[i, 2] = rgb
        cell_colors[i, 3] = 255
    return np.asarray(cell_colors[indices])


def render_continuous_layer(
    mesh: CVTMesh,
    indices: np.ndarray,
    field: str,
    scale: list[ColorStop],
    normalize: Callable[[float], float],
    land_only: bool = True,
    sea_level: float = 0.0,
) -> np.ndarray:
    """Render a numeric cell field through a continuous scale to RGBA.

    ``normalize`` maps the raw field value to ``[0, 1]``.  With ``land_only``,
    ocean cells (``elevation < sea_level``) stay transparent.
    """
    cell_colors = np.zeros((mesh.num_cells, 4), dtype=np.uint8)
    for i, cell in enumerate(mesh.cells):
        value = getattr(cell, field, None)
        if value is None:
            continue
        if land_only and cell.elevation < sea_level:
            continue
        rgb = sequential_color(normalize(float(value)), scale)
        cell_colors[i, 0], cell_colors[i, 1], cell_colors[i, 2] = rgb
        cell_colors[i, 3] = 255
    return np.asarray(cell_colors[indices])


def render_terrain_layer(
    mesh: CVTMesh,
    indices: np.ndarray,
    lut: np.ndarray,
    min_elev: float,
    max_elev: float,
    sea_level: float,
    water_depth_factor: float = 0.5,
) -> np.ndarray:
    """Render the adaptive hypsometric terrain tint to an RGBA array.

    ``lut`` is the ``(lut_size, 3)`` uint8 RGB table from
    ``build_adaptive_terrain_lut``.  Ocean depths are darkened in place,
    matching the frontend ``waterDepthFactor`` behaviour.
    """
    lut_size = lut.shape[0]
    elev_range = max_elev - min_elev or 1.0
    cell_colors = np.zeros((mesh.num_cells, 4), dtype=np.uint8)
    for i, cell in enumerate(mesh.cells):
        elev = float(cell.elevation)
        idx = int((elev - min_elev) / elev_range * (lut_size - 1) + 0.5)
        idx = max(0, min(lut_size - 1, idx))
        r, g, b = int(lut[idx, 0]), int(lut[idx, 1]), int(lut[idx, 2])
        if elev < sea_level:
            depth_frac = min(1.0, (sea_level - elev) / max(1.0, sea_level - min_elev))
            f = 1.0 - water_depth_factor * depth_frac
            r, g, b = int(r * f + 0.5), int(g * f + 0.5), int(b * f + 0.5)
        cell_colors[i, 0], cell_colors[i, 1], cell_colors[i, 2] = r, g, b
        cell_colors[i, 3] = 255
    return np.asarray(cell_colors[indices])


def save_rgba_png(rgba: np.ndarray, path: Path) -> None:
    """Write an RGBA ``(h, w, 4)`` uint8 array to a colour PNG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(str(path))


def plate_velocity_east_north(
    mesh: CVTMesh,
    omega_by_plate: dict[str, tuple[np.ndarray, float]],
    radius_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-cell surface velocity (east, north) in cm/yr from Euler poles.

    Rigid plate motion ``v(P) = ω × P`` with ``ω = axis · omega_rad_yr`` (unit
    axis, rad/yr), scaled to cm/yr at the surface by the planet radius.  This
    is the same field the tectonic simulator uses to classify boundary types,
    so it is exactly the quantity one wants to see when debugging coherent vs
    diverse plate motion.  Returns ``(v_east, v_north)`` in mesh cell order.
    """
    radius_cm = radius_km * 1e5
    xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells])
    lon = np.radians(np.array([c.lon for c in mesh.cells]))
    lat = np.radians(np.array([c.lat for c in mesh.cells]))
    plate_ids = [c.plate_id for c in mesh.cells]

    v = np.zeros_like(xyz)
    for pid, (axis, omega_rad_yr) in omega_by_plate.items():
        mask = np.array([p == pid for p in plate_ids])
        if mask.any():
            v[mask] = np.cross(axis, xyz[mask]) * (omega_rad_yr * radius_cm)

    e_east = np.stack([-np.sin(lon), np.zeros_like(lon), np.cos(lon)], axis=1)
    e_north = np.stack(
        [-np.sin(lat) * np.cos(lon), np.cos(lat), -np.sin(lat) * np.sin(lon)], axis=1
    )
    v_east = np.einsum("ij,ij->i", v, e_east)
    v_north = np.einsum("ij,ij->i", v, e_north)
    return v_east, v_north


def render_plate_motion_layer(
    mesh: CVTMesh,
    indices: np.ndarray,
    omega_by_plate: dict[str, tuple[np.ndarray, float]],
    radius_km: float,
    *,
    step: int = 96,
    max_arrow_px: float = 24.0,
    speed_max_cm_yr: float | None = None,
    background: tuple[int, int, int, int] = (0, 0, 0, 255),
) -> np.ndarray:
    """Render plate velocity arrows (``v = ω × r``) to an RGBA array.

    Arrows are drawn on a subsampled equirectangular grid (every ``step`` px),
    length ∝ speed (capped at ``max_arrow_px`` at ``speed_max_cm_yr``), hue by
    direction.  East components are divided by ``cos(lat)`` so arrows keep their
    true bearing despite the equirectangular east-west compression.
    """
    import colorsys
    import math

    from PIL import Image, ImageDraw

    v_east, v_north = plate_velocity_east_north(mesh, omega_by_plate, radius_km)
    height, width = indices.shape

    ve_grid = v_east[indices]
    vn_grid = v_north[indices]
    speed = np.hypot(ve_grid, vn_grid)
    if speed_max_cm_yr is None:
        speed_max_cm_yr = float(np.percentile(speed[speed > 0], 95)) if (speed > 0).any() else 1.0
    speed_max_cm_yr = max(speed_max_cm_yr, 1e-6)

    # latitude per row (row 0 = +90°), for east compression + pole guard
    lat_grid = np.radians(np.linspace(90.0, -90.0, height))
    cos_lat = np.cos(lat_grid)

    img = Image.new("RGBA", (width, height), background)
    draw = ImageDraw.Draw(img)
    scale = max_arrow_px / speed_max_cm_yr
    for y in range(step // 2, height, step):
        cy = cos_lat[y]
        if abs(cy) < 0.2:  # near poles, east direction is ill-defined
            continue
        for x in range(step // 2, width, step):
            ve = ve_grid[y, x] / cy  # correct equirect east compression
            vn = -vn_grid[y, x]  # north → up (−y)
            s = math.hypot(ve, vn)
            if s < 0.02 * speed_max_cm_yr:
                continue
            length = min(s * scale, max_arrow_px)
            ux, uy = ve / s, vn / s
            dx, dy = ux * length, uy * length
            ex, ey = x + dx * 0.5, y + dy * 0.5
            sx, sy = x - dx * 0.5, y - dy * 0.5
            hue = (math.atan2(vn, ve) % (2 * math.pi)) / (2 * math.pi)
            r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 1.0)
            color = (int(r * 255), int(g * 255), int(b * 255), 255)
            width_px = max(1, int(length * 0.10))
            draw.line([(sx, sy), (ex, ey)], fill=color, width=width_px)
            # arrowhead — two short segments back from the head
            hx, hy = -ux, -uy
            px, py = -uy, ux
            hl = max(3.0, length * 0.35)
            draw.line(
                [(ex, ey), (ex + hx * hl + px * hl, ey + hy * hl + py * hl)],
                fill=color,
                width=width_px,
            )
            draw.line(
                [(ex, ey), (ex + hx * hl - px * hl, ey + hy * hl - py * hl)],
                fill=color,
                width=width_px,
            )
    return np.asarray(img)


# ---------------------------------------------------------------------------
# PNG export
# ---------------------------------------------------------------------------


def export_elevation_png(
    elevation: np.ndarray,
    path: Path,
    min_m: float = -11_000.0,
    max_m: float = 9_000.0,
) -> None:
    """Export elevation grid as 16-bit PNG.

    Elevation is normalized to [0, 65535] using the given range.

    Args:
        elevation: 2D elevation grid in metres.
        path: Output file path.
        min_m: Minimum elevation for normalization.
        max_m: Maximum elevation for normalization.
    """
    # Normalize to [0, 1]
    normalized = np.clip((elevation - min_m) / (max_m - min_m), 0, 1)

    # Convert to 16-bit (uint16 array maps natively to Pillow's I;16 mode;
    # explicit mode= is deprecated and removed in Pillow 13)
    data_16 = (normalized * 65535).astype(np.uint16)

    img = Image.fromarray(data_16)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    logger.info("  Saved elevation PNG: %s", path)


def export_layer_png(
    data: np.ndarray,
    path: Path,
    min_val: float = 0.0,
    max_val: float = 1.0,
) -> None:
    """Export a generic layer as 16-bit PNG.

    Args:
        data: 2D data grid.
        path: Output file path.
        min_val: Minimum value for normalization.
        max_val: Maximum value for normalization.
    """
    if max_val - min_val < 1e-12:
        normalized = np.zeros_like(data)
    else:
        normalized = np.clip((data - min_val) / (max_val - min_val), 0, 1)

    data_16 = (normalized * 65535).astype(np.uint16)
    img = Image.fromarray(data_16)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    logger.info("  Saved layer PNG: %s", path)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

# Floats with more than SIG_DIGITS decimal places are truncated in-place.
# At 71 km/cell, 4 decimal digits of lat/lon ≈ 7.8 m, far below the
# mesh resolution; for elevation / temperature / precipitation this is
# also well under any meaningful precision.  Reduces file size ~20–30%.
_SIG_DIGITS = 4
_FLOAT_TRUNC_RE = __import__("re").compile(rb"(-?\d+\.\d{" + str(_SIG_DIGITS).encode() + rb"})\d+")


def _truncate_float_precision(data: bytes) -> bytes:
    """Truncate excessive float precision in JSON to ``_SIG_DIGITS`` places."""
    return _FLOAT_TRUNC_RE.sub(rb"\1", data)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# CVT mesh serialization — gzip-framed MessagePack (canonical), with
# transparent reads of legacy gzip-JSON / plain-JSON files
# ---------------------------------------------------------------------------

MESH_FILENAME = "cvt_mesh.msgpack.gz"
LEGACY_MESH_FILENAME = "cvt_mesh.json"
_MESH_GZIP_LEVEL = 9


def _mesh_json_bytes(mesh: CVTMeshLike) -> bytes:
    """Canonical JSON text for *mesh* — the serialization intermediate.

    Float truncation and pydantic's non-finite→null semantics live in the
    JSON layer; the packed representation just re-encodes that text.
    """
    import json

    if isinstance(mesh, dict):
        return _truncate_float_precision(json.dumps(mesh, default=str).encode("utf-8"))
    from pydantic import TypeAdapter

    from .models import CVTMesh

    return _truncate_float_precision(TypeAdapter(CVTMesh).dump_json(mesh))


def save_cvt_mesh(path: Path, mesh: CVTMeshLike, *, backup_existing: bool = False) -> None:
    """Write *mesh* as gzip-framed MessagePack (``cvt_mesh.msgpack.gz``).

    gzip is the size win (the mesh is field-name/string heavy — measured
    2026-09-23: msgpack alone is ~2/3 of plain JSON, gzip on top lands within
    ±20% of the old gzip-JSON depending on string density); msgpack is the
    regularization win — one canonical binary the API can stream unparsed
    and the frontend decodes in a worker.  A legacy ``cvt_mesh.json``
    sibling is removed so a planet never carries two divergent meshes.

    ``backup_existing=True`` rotates the file being replaced to
    ``cvt_mesh.msgpack.gz.prev`` (1 generation, same directory) before the
    overwrite — for real-data root meshes that are expensive to re-import
    (earth root: external source datasets + a single on-disk copy; lost to a
    self-destruct overwrite 2026-09-25).  Generated/branch meshes stay at the
    default: reproducible from seed, and a per-build copy buys nothing.  The
    ``.prev`` keeps whatever bytes were on disk (legacy gzip-JSON included);
    :func:`decode_mesh_bytes` sniffs content, so it loads regardless of name.
    """
    import gzip
    import json
    import shutil

    import msgpack

    obj = json.loads(_mesh_json_bytes(mesh))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == LEGACY_MESH_FILENAME:
        # Never write *into* the legacy name: the sibling cleanup below would
        # then delete what was just written (root earth re-import lost its
        # mesh this way, 2026-09-25).  Canonicalize to the msgpack.gz name.
        path = path.with_name(MESH_FILENAME)
    if backup_existing:
        previous = path if path.exists() else path.with_name(LEGACY_MESH_FILENAME)
        if previous.exists():
            shutil.copy2(previous, path.with_name(MESH_FILENAME + ".prev"))
    path.write_bytes(
        gzip.compress(msgpack.packb(obj, use_bin_type=True), compresslevel=_MESH_GZIP_LEVEL)
    )
    legacy = path.with_name(LEGACY_MESH_FILENAME)
    if legacy.exists():
        legacy.unlink()


def decode_mesh_bytes(raw: bytes) -> dict[str, Any]:
    """Decode mesh bytes of any on-disk generation.

    Sniffs in order: gzip framing (containing legacy JSON or msgpack),
    plain JSON, raw msgpack.  This is what makes the format migration
    zero-rebuild — old worlds keep loading until their next build.
    """
    import gzip
    import json

    import msgpack

    if raw[:2] == b"\x1f\x8b":  # gzip magic number
        raw = gzip.decompress(raw)
    if raw.lstrip()[:1] in (b"{", b"["):
        data: dict[str, Any] = json.loads(raw)
        return data
    unpacked: dict[str, Any] = msgpack.unpackb(raw, raw=False)
    return unpacked


def load_cvt_mesh(path: Path) -> dict[str, Any]:
    """Load a mesh file as a dict, regardless of on-disk generation."""
    return decode_mesh_bytes(path.read_bytes())


def load_cvt_mesh_model(path: Path) -> CVTMesh:
    """Load a mesh file as a validated :class:`~dreamulator.map.models.CVTMesh`.

    Legacy JSON bytes take the pydantic-core ``validate_json`` fast path
    (Rust parser); msgpack bytes unpack (C extension) then validate.
    """
    import gzip

    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    from .models import CVTMesh

    if raw.lstrip()[:1] == b"{":
        from pydantic import TypeAdapter

        return TypeAdapter(CVTMesh).validate_json(raw)
    import msgpack

    return CVTMesh.model_validate(msgpack.unpackb(raw, raw=False))


def find_mesh_file(directory: Path) -> Path | None:
    """Mesh file inside a planet map dir — canonical name first, legacy fallback."""
    canonical = directory / MESH_FILENAME
    if canonical.exists():
        return canonical
    legacy = directory / LEGACY_MESH_FILENAME
    return legacy if legacy.exists() else None


def iter_mesh_files(base: Path) -> list[Path]:
    """All planet mesh files under ``base/<planet_id>/`` (both generations,
    canonical preferred per planet), excluding ``_``-prefixed scratch dirs."""
    by_planet: dict[str, Path] = {}
    if not base.exists():
        return []
    for name in (MESH_FILENAME, LEGACY_MESH_FILENAME):
        for p in sorted(base.glob(f"*/{name}")):
            if p.parent.name.startswith("_"):
                continue
            by_planet.setdefault(p.parent.name, p)
    return list(by_planet.values())


def save_outputs(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    elevation_grid: np.ndarray,
    output_dir: Path,
    config: TerrainPipelineConfig,
) -> None:
    """Save all pipeline outputs to the given directory.

    Output files:
        - elevation.png (16-bit PNG)
        - cvt_mesh.msgpack.gz (full CVT mesh, gzip-framed MessagePack)
        - plates.json (tectonic plates)
        - metadata.json (generation parameters)

    Args:
        mesh: The CVT mesh.
        plates: List of TectonicPlate.
        elevation_grid: 2D elevation grid.
        output_dir: Output directory.
        config: Pipeline configuration.
    """
    import json

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Elevation PNG
    elev_min = float(np.min(elevation_grid))
    elev_max = float(np.max(elevation_grid))
    # Round to nice values for PNG encoding
    png_min = min(-11_000, elev_min)
    png_max = max(9_000, elev_max)
    export_elevation_png(elevation_grid, output_dir / "elevation.png", png_min, png_max)

    # 2. CVT Mesh — gzip-framed MessagePack via the canonical serializer
    #    (float truncation + non-finite→null semantics preserved through the
    #    JSON intermediate inside save_cvt_mesh).  Terrain export runs once
    #    per generation/import (not per climate build), so the 1-generation
    #    backup is cheap insurance for real-data root re-imports.
    save_cvt_mesh(output_dir / MESH_FILENAME, mesh, backup_existing=True)
    logger.info("  Saved CVT mesh: %s", output_dir / MESH_FILENAME)

    # 3. Plates JSON
    from .models import sanitize_nonfinite

    plates_data = sanitize_nonfinite([p.model_dump() for p in plates])
    with open(output_dir / "plates.json", "w", encoding="utf-8") as f:
        json.dump(plates_data, f, indent=2, default=str)
    logger.info("  Saved plates: %s", output_dir / "plates.json")

    # 4. Write map.yaml with full generation metadata (replaces metadata.json).
    #    All identity/provenance fields are (re)written on every export:
    #    regenerating a world from scratch must produce a map.yaml that
    #    satisfies MapMetadata on its own (the old "update-only" behaviour
    #    left out planet_id etc. when no prior map.yaml existed, crashing
    #    the API with a pydantic ValidationError).
    import yaml as _yaml

    map_yaml_path = output_dir / "map.yaml"
    map_data: dict[str, Any] = {}
    if map_yaml_path.exists():
        with map_yaml_path.open("r", encoding="utf-8") as _f:
            map_data = _yaml.safe_load(_f) or {}

    # Identity + generation provenance (output_dir is maps/<planet_id>/)
    map_data["planet_id"] = output_dir.name
    map_data["projection"] = "equirectangular"
    map_data["width"] = config.export_width
    map_data["height"] = config.export_height
    map_data["voronoi_seed"] = config.seed
    map_data["voronoi_num_cells"] = config.num_nodes
    map_data["cvt_jitter_sigma"] = config.jitter_sigma
    map_data["cvt_lloyd_iterations"] = config.lloyd_iterations
    # Sync PNG encoding range (frontend uses these to decode elevation.png)
    map_data["elevation_min_m"] = png_min
    map_data["elevation_max_m"] = png_max
    map_data["sea_level_m"] = 0.0
    # Generation provenance (formerly metadata.json)
    # Actual plate count (post tectonic evolution), not the requested seed
    # count — plates.json is the single source of truth for plate facts.
    map_data["num_plates"] = len(plates)
    map_data["radius_km"] = config.radius_km
    map_data["elevation_range_m"] = [round(elev_min, 1), round(elev_max, 1)]
    map_data["pipeline_version"] = "2.0-cvt"

    with map_yaml_path.open("w", encoding="utf-8") as _f:
        _yaml.dump(map_data, _f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    logger.info("  Updated map.yaml (elevation range + metadata)")

    # 5. Climate layers (if available)
    if _climate_data_available(mesh):
        export_climate_layers(mesh, output_dir, config)


# ---------------------------------------------------------------------------
# Climate layer export (Phase 3A)
# ---------------------------------------------------------------------------


def _climate_data_available(mesh: CVTMesh) -> bool:
    """Check if climate simulation has populated the mesh cells."""
    if mesh.num_cells == 0:
        return False
    return mesh.cells[0].temperature_C is not None


def export_climate_layers(
    mesh: CVTMesh,
    output_dir: Path,
    config: TerrainPipelineConfig,
) -> None:
    """Export climate raster and vector layers.

    Produces:
        - temperature.png (16-bit PNG, range [-40, +50] °C)
        - precipitation.png (16-bit PNG, range [0, 6000] mm/yr)
        - koppen.json (per-cell Köppen class codes)
        - climate_metadata.json
        - climate_monthly.msgpack (per-cell monthly series, when present)
        - climate_yearly.msgpack (per-cell UCC descriptors, when present)

    Args:
        mesh: CVT mesh with climate fields populated.
        output_dir: Output directory.
        config: Pipeline configuration.
    """
    import json

    width = config.export_width
    height = config.export_height
    tree = build_export_tree(mesh)  # Stage 0.3: shared across both rasters

    # 1. Temperature raster
    temp_grid = export_equirectangular(mesh, width, height, field="temperature_C", tree=tree)
    t_min, t_max = _nice_range(
        float(np.nanmin(temp_grid)), float(np.nanmax(temp_grid)), -40.0, 50.0
    )
    export_layer_png(temp_grid, output_dir / "temperature.png", t_min, t_max)
    logger.info("  Exported temperature.png [%.0f, %.0f] °C", t_min, t_max)

    # 2. Precipitation raster
    precip_grid = export_equirectangular(mesh, width, height, field="precipitation_mm", tree=tree)
    p_min, p_max = _nice_range(
        float(np.nanmin(precip_grid)), float(np.nanmax(precip_grid)), 0.0, 6000.0
    )
    export_layer_png(precip_grid, output_dir / "precipitation.png", p_min, p_max)
    logger.info("  Exported precipitation.png [%.0f, %.0f] mm/yr", p_min, p_max)

    # 3. Köppen classification vector data (per cell)
    koppen_by_cell = {}
    for c in mesh.cells:
        if c.koppen_class is not None:
            koppen_by_cell[str(c.id)] = c.koppen_class

    # Aggregate Köppen class counts for climate summary
    from collections import Counter

    koppen_counter = Counter(koppen_by_cell.values())

    koppen_data = {
        "cells": koppen_by_cell,
        "summary": dict(koppen_counter),
        "num_cells": mesh.num_cells,
    }
    koppen_path = output_dir / "koppen.json"
    with koppen_path.open("w", encoding="utf-8") as _f:
        json.dump(koppen_data, _f, indent=2)
    logger.info("  Exported koppen.json (%d classes)", len(koppen_counter))

    # 4. Climate metadata
    climate_meta = {
        "temperature_range_c": [t_min, t_max],
        "precipitation_range_mm": [p_min, p_max],
        "koppen_classes": sorted(koppen_counter.keys()),
        "export_resolution": [width, height],
        "stellar_luminosity_sol": config.stellar_luminosity_sol,
        "orbital_distance_au": config.orbital_distance_au,
        "orbital_period_days": config.orbital_period_days,
        "axial_tilt_deg": config.axial_tilt_deg,
        "greenhouse_warming_K": config.greenhouse_warming_K,
        "rotation_period_days": config.rotation_period_days,
        "albedo": config.albedo,
        "eccentricity": config.eccentricity,
    }
    meta_path = output_dir / "climate_metadata.json"
    with meta_path.open("w", encoding="utf-8") as _f:
        json.dump(climate_meta, _f, indent=2)
    logger.info("  Exported climate_metadata.json")

    # 5. Monthly climate (Phase 4 monthly display) — compact MessagePack of the
    # per-cell monthly temperature + precipitation in mesh cell order, so the
    # frontend can bake it with the existing cell-ID map.  Raw bytes keep the
    # file compact (gzip ~10 MB vs JSON text ~40 MB).  Tech debt 24 adds the
    # monthly wind vector (east/north components) and the monthly monsoon
    # pressure anomaly ΔP.  All five N×12 fields are quantized to int16 + a
    # per-field (scale, offset) — halving the file (~48 MB → ~24 MB) with a
    # resolution far below each field's own precision (see `_quantize_int16`).
    t_monthly = getattr(mesh, "_t_monthly_c", None)
    p_monthly = getattr(mesh, "_p_monthly_mm", None)
    if t_monthly is not None and p_monthly is not None:
        import msgpack

        _t_q, _t_scale, _t_offset = _quantize_int16(t_monthly)
        _p_q, _p_scale, _p_offset = _quantize_int16(p_monthly)
        monthly = {
            "num_cells": mesh.num_cells,
            "months": 12,
            "dtype": "int16",
            "t_monthly": _t_q,
            "t_scale": _t_scale,
            "t_offset": _t_offset,
            "p_monthly": _p_q,
            "p_scale": _p_scale,
            "p_offset": _p_offset,
            "temperature_range_c": [float(np.min(t_monthly)), float(np.max(t_monthly))],
            "precipitation_range_mm": [float(np.min(p_monthly)), float(np.max(p_monthly))],
            "month_0": "vernal_equinox",
        }

        we_monthly = getattr(mesh, "_wind_east_monthly", None)
        wn_monthly = getattr(mesh, "_wind_north_monthly", None)
        if we_monthly is not None and wn_monthly is not None:
            _we_q, _we_scale, _we_offset = _quantize_int16(we_monthly)
            _wn_q, _wn_scale, _wn_offset = _quantize_int16(wn_monthly)
            monthly["wind_east_monthly"] = _we_q
            monthly["wind_east_scale"] = _we_scale
            monthly["wind_east_offset"] = _we_offset
            monthly["wind_north_monthly"] = _wn_q
            monthly["wind_north_scale"] = _wn_scale
            monthly["wind_north_offset"] = _wn_offset
            _we64 = we_monthly.astype(np.float64)
            _wn64 = wn_monthly.astype(np.float64)
            monthly["wind_max_speed_m_s"] = float(np.sqrt(_we64**2 + _wn64**2).max())
        pr_monthly = getattr(mesh, "_pressure_monthly", None)
        if pr_monthly is not None:
            _pr_q, _pr_scale, _pr_offset = _quantize_int16(pr_monthly)
            monthly["pressure_monthly"] = _pr_q
            monthly["pressure_scale"] = _pr_scale
            monthly["pressure_offset"] = _pr_offset
            monthly["pressure_range_hpa"] = [float(np.min(pr_monthly)), float(np.max(pr_monthly))]

        monthly_path = output_dir / "climate_monthly.msgpack"
        with monthly_path.open("wb") as _f:
            _f.write(msgpack.packb(monthly))
        logger.info("  Exported climate_monthly.msgpack (%d×%d)", mesh.num_cells, 12)

        # 6. Yearly climate descriptors (UCC-01 step 2) — the continuous
        # UCC descriptions (ucc-review §4.2) computed per cell from the
        # monthly series above, plus the monthly Hamon reference demand the
        # supply–demand statistics need.  Value arrays are raw float32 with
        # NaN wherever the descriptor is undefined — the *status* arrays
        # carry why (§4.4), so no placeholder value is ever read as data.
        # Time basis: 12 equal reference months (365.25/12 d), so p_total is
        # mm per reference year and AI is window-invariant (M2-A0④).
        from dreamulator.engine.climate_physics import (
            potential_evapotranspiration_hamon_monthly,
        )
        from dreamulator.result_contract import REFERENCE_MONTH_DAYS, result_metadata

        from .ucc import (
            PROFILE_CURRENT,
            STATUS_CODES,
            SUPPLY_BANDS_CURRENT,
            THERMAL_BANDS_CURRENT,
            classify_v1,
            compute_descriptors,
        )

        _et_monthly = potential_evapotranspiration_hamon_monthly(t_monthly, REFERENCE_MONTH_DAYS)
        _status_codes = list(STATUS_CODES)
        _status_index = {name: i for i, name in enumerate(_status_codes)}
        _thermal_index = {name: i for i, name in enumerate(THERMAL_BANDS_CURRENT)}
        _supply_index = {name: i for i, name in enumerate(SUPPLY_BANDS_CURRENT)}
        _n = mesh.num_cells
        _t_mean = np.empty(_n, dtype=np.float32)
        _t_min = np.empty(_n, dtype=np.float32)
        _t_max = np.empty(_n, dtype=np.float32)
        _t_range = np.empty(_n, dtype=np.float32)
        _t_below = np.empty(_n, dtype=np.float32)
        _p_rate = np.empty(_n, dtype=np.float32)
        _p_total = np.empty(_n, dtype=np.float32)
        _ai = np.full(_n, np.nan, dtype=np.float32)
        _ai_status = np.empty(_n, dtype=np.uint8)
        _deficit = np.full(_n, np.nan, dtype=np.float32)
        _deficit_status = np.empty(_n, dtype=np.uint8)
        _concentration = np.full(_n, np.nan, dtype=np.float32)
        # Classification under the frozen profile v0 (UCC-01 step 4a).  Codes are
        # indices into thermal_bands/supply_bands; 255 in ucc_supply = the
        # supply–demand axis does not apply (ocean or invalid AI) — the why is in
        # ucc_supply_status.  ucc_modifiers bit 0 = continental, bit 1 = water_stress.
        _ucc_thermal = np.empty(_n, dtype=np.uint8)
        _ucc_supply = np.empty(_n, dtype=np.uint8)
        _ucc_supply_status = np.empty(_n, dtype=np.uint8)
        _ucc_modifiers = np.empty(_n, dtype=np.uint8)
        for i in range(_n):
            d = compute_descriptors(t_monthly[i], p_monthly[i], _et_monthly[i])
            _t_mean[i] = d.t_mean
            _t_min[i] = d.t_min
            _t_max[i] = d.t_max
            _t_range[i] = d.t_range
            _t_below[i] = d.t_below_frac
            _p_rate[i] = d.p_mean_rate
            _p_total[i] = d.p_total
            if d.ai is not None:
                _ai[i] = d.ai
            _ai_status[i] = _status_index[d.ai_status]
            if d.deficit is not None:
                _deficit[i] = d.deficit
            _deficit_status[i] = _status_index[d.deficit_status]
            if d.concentration is not None:
                _concentration[i] = d.concentration
            _cls = classify_v1(d, is_land=mesh.cells[i].water_class == "land")
            _ucc_thermal[i] = _thermal_index[_cls.thermal]
            _ucc_supply[i] = _supply_index[_cls.supply] if _cls.supply is not None else 255
            _ucc_supply_status[i] = _status_index[_cls.supply_status]
            _ucc_modifiers[i] = (1 if _cls.continental else 0) | (2 if _cls.water_stress else 0)

        yearly = {
            **result_metadata(),
            "num_cells": _n,
            "months": 12,
            "dtype": "float32",
            "demand_model": "hamon-1961",
            "demand_daylength_h": 12.0,
            "freeze_threshold_c": 0.0,
            "status_codes": _status_codes,
            "profile": PROFILE_CURRENT,
            "thermal_bands": list(THERMAL_BANDS_CURRENT),
            "supply_bands": list(SUPPLY_BANDS_CURRENT),
            # Engine output — the earth root's obs-derived counterpart (written
            # by scripts/earth/export_earth_yearly.py) carries "observation".
            "data_source": "model",
            "t_mean_c": _t_mean.tobytes(),
            "t_min_c": _t_min.tobytes(),
            "t_max_c": _t_max.tobytes(),
            "t_range_c": _t_range.tobytes(),
            "t_below_frac": _t_below.tobytes(),
            "p_mean_mm_per_month": _p_rate.tobytes(),
            "p_total_mm": _p_total.tobytes(),
            "ai": _ai.tobytes(),
            "ai_status": _ai_status.tobytes(),
            "deficit": _deficit.tobytes(),
            "deficit_status": _deficit_status.tobytes(),
            "concentration": _concentration.tobytes(),
            "ucc_thermal": _ucc_thermal.tobytes(),
            "ucc_supply": _ucc_supply.tobytes(),
            "ucc_supply_status": _ucc_supply_status.tobytes(),
            "ucc_modifiers": _ucc_modifiers.tobytes(),
        }
        yearly_path = output_dir / "climate_yearly.msgpack"
        with yearly_path.open("wb") as _f:
            _f.write(msgpack.packb(yearly))
        logger.info("  Exported climate_yearly.msgpack (%d cells)", _n)


def _nice_range(
    data_min: float,
    data_max: float,
    fallback_min: float,
    fallback_max: float,
) -> tuple[float, float]:
    """Round a data range to nice round numbers for PNG encoding.

    Args:
        data_min: Actual minimum value.
        data_max: Actual maximum value.
        fallback_min: Floor if data is within this range.
        fallback_max: Ceiling if data is within this range.

    Returns:
        (nice_min, nice_max) rounded to the nearest 10.
    """
    import math

    rmin = math.floor(min(data_min, fallback_min) / 10.0) * 10.0
    rmax = math.ceil(max(data_max, fallback_max) / 10.0) * 10.0
    return rmin, rmax


def _quantize_int16(arr: np.ndarray) -> tuple[bytes, float, float]:
    """Quantize a float32 array to int16 bytes + (scale, offset) for compact storage.

    Linear map ``float_value = int16_value * scale + offset`` spans the full int16
    range [−32768, 32767] over [min, max].  Resolution is (max−min)/65535 — far
    below the data's own precision for every monthly field (temperature ~0.001 °C,
    precipitation ~0.04 mm, wind ~0.001 m/s, pressure ~0.0005 hPa) — so the loss is
    negligible while halving the file size.  Little-endian, matching the frontend's
    Int16Array decode.
    """
    a = arr.astype(np.float64)
    lo = float(a.min())
    hi = float(a.max())
    span = hi - lo
    if span <= 0.0:
        # Constant field — zeros quantize to 0 and decode back to `lo`.
        return np.zeros(arr.shape, dtype=np.int16).tobytes(), 1.0, lo
    scale = span / 65535.0
    offset = lo + 32768.0 * scale  # lo → −32768, hi → 32767
    q = np.clip(np.round((a - offset) / scale), -32768, 32767).astype(np.int16)
    return q.tobytes(), float(scale), float(offset)
