"""Region pack export — crop a square world region for external renderers.

Produces the data pack consumed by the Blender minimal render chain
(``scripts/media/blender/region_still.py``) and the Gaea 2 erosion leg:

* ``height.meters.npy`` — float32 height in metres, the primary data channel
  (exact round-trip, no colour-space pitfalls in ``bpy``'s bundled Python);
* ``height.png`` — 16-bit height normalised to the REGION's own min/max, for
  human inspection (the numeric channel stays authoritative);
* ``color.png`` — hypsometric terrain tint from the same grid, using
  the frontend's palette single source (``build_adaptive_terrain_lut``);
* ``height.gaea.png`` — Gaea-ready 16-bit height with the seafloor
  pre-clamped at ``seafloor_clamp_m`` (Gaea 2.3 caps Terrain Definition
  Height at 10 km and Width at 2400 km; clamping the invisible deep
  seafloor shrinks the vertical span to fit, and gives the land full
  16-bit precision).  Its normalisation range is recorded in meta as
  ``height_gaea_png_range_m``;
* ``meta.json`` — physical extents, scaling and provenance for the builder.

With ``include_climate=True`` (the default) the pack also carries the
same-resolution climate channels of the satellite-imagery contract
(``docs/design/proposals/gaea-refinement.md`` §6 step 0 + §7):

* ``precipitation.mm.npy`` — float32 annual precipitation (mm), the Gaea 2
  rainfall-mask channel; ``precipitation.mm.png`` is the 16-bit visual twin,
  normalised to ``[0, region max]`` (range recorded in meta);
* ``temperature.C.npy`` / ``temperature.C.png`` — float32 / 16-bit mean
  annual temperature (°C), normalised to the region's own [min, max];
* ``runoff.mm.npy`` / ``runoff.mm.png`` — float32 annual land runoff (mm/yr)
  from the Turc–Pike (Budyko, n = 2) curve on annual P vs Hamon annual PET,
  written when the caller passes the monthly climate series; the hydrology
  legs weight their flow accumulation by this channel so channels start
  where the water balance allows, not on bare slopes;
* ``ice.m.npy`` / ``ice.m.png`` — float32 glacier ice thickness (m, ice-free
  cells = 0.0); the snowline mask is derived downstream from this channel and
  ``temperature.C.npy`` rather than baked here;
* ``npp.gc_m2_yr.npy`` / ``npp.gc_m2_yr.png`` — Miami net primary productivity
  (gC/m²/yr), the continuous vegetation-density channel the colorizer uses
  for within-biome modulation;
* ``headwaters.png`` — 8-bit mask of water-surplus land (P > Hamon PET),
  the Gaea Rivers node's Headwaters input: rivers originate where the water
  balance allows, not on bare slopes (Gaea itself is hydrology-blind);
* ``koppen.codes.npy`` / ``koppen.png`` — uint8 class codes (0 = missing)
  plus a palette-baked colour PNG; the code → class legend lives in meta;
* ``biome.codes.npy`` / ``biome.png`` — same contract for Whittaker biomes.

Sampling (pack v3): the pack rasters are a SQUARE ``out_res`` × ``out_res``
grid covering the snapped window, decoupled from the engine's export grid.
Scalar channels use Clough-Tocher (cubic, C1) interpolation over the Delaunay
triangulation of the cell centres — a cell centre keeps its exact value, and
smooth gradients matter because the downstream erosion is gradient-driven
(linear C0 kinks are mesh artefacts that would seed spurious channels).
Categorical channels (codes) and the terrain tint stay
nearest-cell.  Hull-exterior and degenerate windows fall back to the nearest
cell's value.  Missing cell values become NaN in the numeric ``.npy``
channels and 0 in the PNGs; the per-channel ``missing`` counts in meta make
gaps auditable.

Region selection is a centre + physical span in km on the planet's real
radius.  The equirectangular crop compensates the cos(lat) east–west stretch
exactly at the centre latitude; polar regions (|lat| > 75°) and antimeridian
crossings are rejected — those need the stereographic leg of the Gaea chain
(``docs/design/proposals/gaea-refinement.md`` §3).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.map.export import (
    build_export_tree,
    export_cell_index_grid,
    export_elevation_png,
    export_layer_png,
    render_categorical_layer,
    render_terrain_layer,
    save_rgba_png,
)
from dreamulator.map.palettes import (
    build_adaptive_terrain_lut,
    koppen_colors,
    whittaker_colors,
)
from dreamulator.result_contract import REFERENCE_MONTH_DAYS

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.map.models import CVTMesh

#: Hard latitude band the equirectangular crop supports (cos-distortion guard).
MAX_ABS_LAT = 75.0


class RegionWindowError(ValueError):
    """Region rejected by the equirectangular crop guards."""


@dataclass(frozen=True)
class RegionWindow:
    """Accepted square region: geographic bounds + pixel box on the export grid.

    Pixel mapping follows ``make_equirect_grid`` exactly: column ``x`` ↔
    ``lon = −180 + 360·x/W`` (edge-aligned), row ``y`` ↔
    ``lat = 90 − 180·y/(H−1)`` (endpoint linspace).  ``x1``/``y1`` are
    exclusive, so the crop is ``indices[y0:y1, x0:x1]``.
    """

    #: Requested geographic window (degrees) before floor/ceil snapping.
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    x0: int
    y0: int
    x1: int
    y1: int
    #: Physical pixel size at the centre latitude (km per pixel, both axes).
    km_per_px_x: float
    km_per_px_y: float

    @property
    def grid_w(self) -> int:
        return self.x1 - self.x0

    @property
    def grid_h(self) -> int:
        return self.y1 - self.y0


def region_window(
    center_lat: float,
    center_lon: float,
    span_km: float,
    radius_km: float,
    grid_width: int,
    grid_height: int,
) -> RegionWindow:
    """Compute the square-in-km region window on the equirectangular grid.

    The north-south half-extent uses the planet's real meridian scale
    (1° = πR/180 km); the east-west half-extent is divided by cos(lat) so the
    crop stays square in kilometres at the centre latitude.

    Raises:
        RegionWindowError: span not positive, polar band exceeded, antimeridian
            crossing, or the window collapsed to zero pixels.
    """
    if span_km <= 0:
        raise RegionWindowError(f"span_km must be positive, got {span_km}")
    if not -90.0 <= center_lat <= 90.0 or not -180.0 <= center_lon <= 180.0:
        raise RegionWindowError(f"centre ({center_lat}, {center_lon}) outside lat/lon bounds")

    deg_per_km = 180.0 / (math.pi * radius_km)
    half_lat = span_km * deg_per_km / 2.0
    cos_c = math.cos(math.radians(center_lat))
    if abs(cos_c) < 1e-4:
        raise RegionWindowError("centre latitude too close to a pole for an equirect crop")
    half_lon = span_km * deg_per_km / (2.0 * cos_c)

    lat_min, lat_max = center_lat - half_lat, center_lat + half_lat
    lon_min, lon_max = center_lon - half_lon, center_lon + half_lon
    if max(abs(lat_min), abs(lat_max)) > MAX_ABS_LAT:
        raise RegionWindowError(
            f"window reaches |lat| {max(abs(lat_min), abs(lat_max)):.1f}° "
            f"(limit {MAX_ABS_LAT}°) — use the stereographic leg for polar regions"
        )
    if lon_min < -180.0 or lon_max > 180.0:
        raise RegionWindowError(
            f"window crosses the antimeridian ({lon_min:.1f}..{lon_max:.1f}°) — "
            "not supported by the equirect crop"
        )

    # Snap outwards (floor/ceil) so the pixel box fully covers the request.
    x0 = max(0, math.floor((lon_min + 180.0) / 360.0 * grid_width))
    x1 = min(grid_width, math.ceil((lon_max + 180.0) / 360.0 * grid_width))
    y0 = max(0, math.floor((90.0 - lat_max) / 180.0 * (grid_height - 1)))
    y1 = min(grid_height, math.ceil((90.0 - lat_min) / 180.0 * (grid_height - 1)))
    if x1 <= x0 or y1 <= y0:
        raise RegionWindowError("region collapsed to zero pixels on this grid")

    km_per_px_y = math.pi * radius_km / (grid_height - 1)
    km_per_px_x = 2.0 * math.pi * radius_km * cos_c / grid_width
    return RegionWindow(
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        km_per_px_x=km_per_px_x,
        km_per_px_y=km_per_px_y,
    )


def probe_alignment(
    mesh: CVTMesh,
    window: RegionWindow,
    indices_full: np.ndarray,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Alignment guard: sample cells inside the window and check that the pixel
    at each cell's centre resolves (via the full index grid) to a nearby cell.

    A transposed or offset crop fails this with a large nearest-distance; a
    healthy grid shows every probe within about one cell diameter.
    """
    height, width = indices_full.shape
    inside = [
        c
        for c in mesh.cells
        if window.lon_min <= c.lon <= window.lon_max and window.lat_min <= c.lat <= window.lat_max
    ]
    if not inside:
        return []
    step = max(1, len(inside) // n)
    probes: list[dict[str, Any]] = []
    for cell in inside[::step][:n]:
        x = min(width - 1, max(0, int((cell.lon + 180.0) / 360.0 * width)))
        y = min(height - 1, max(0, int((90.0 - cell.lat) / 180.0 * (height - 1))))
        nearest = mesh.cells[int(indices_full[y, x])]
        d_lon = abs(nearest.lon - cell.lon)
        d_lon = min(d_lon, 360.0 - d_lon)
        d_lat = abs(nearest.lat - cell.lat)
        probes.append(
            {
                "cell_id": cell.id,
                "nearest_cell_id": nearest.id,
                "offset_deg": round(max(d_lon, d_lat), 3),
            }
        )
    return probes


def read_radius_km(map_dir: Path, world_dir: Path | None = None) -> float:
    """Planet radius from ``map.yaml`` (extra field dropped by MapMetadata).

    Branch maps dirs hold build products only — the hand-written
    ``map.yaml`` stays in the root maps dir.  When ``map_dir`` is a
    branch's (no ``map.yaml`` of its own), fall back to the same planet's
    root map via ``world_dir`` before defaulting to Earth.
    """
    import yaml

    candidates = [map_dir / "map.yaml"]
    if world_dir is not None:
        candidates.append(world_dir / "maps" / map_dir.name / "map.yaml")
    for map_yaml in candidates:
        if map_yaml.exists():
            raw = yaml.safe_load(map_yaml.read_text(encoding="utf-8")) or {}
            if raw.get("radius_km"):
                return float(raw["radius_km"])
    return 6371.0


def mesh_fingerprint(mesh_file: Path) -> dict[str, Any]:
    """Deterministic provenance for the pack (content hash, no timestamps)."""
    digest = hashlib.sha256()
    with open(mesh_file, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "mesh_file": mesh_file.name,
        "mesh_size_bytes": mesh_file.stat().st_size,
        "mesh_sha256_12": digest.hexdigest()[:12],
    }


#: Pack format version — 2 added the climate channels (precipitation /
#: temperature / ice / köppen / biome); 3 decoupled the raster resolution
#: from the engine export grid (square ``out_res`` grid, Clough-Tocher C1
#: scalar interpolation) and added ``height.gaea.png``.
PACK_VERSION = 3

#: Default resolution of the pack's square output rasters.
DEFAULT_OUT_RES = 2048


def _window_out_grid(window: RegionWindow, out_res: int) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-centre (lon, lat) meshgrid of the square output raster.

    Row 0 is the north edge (``lat_max``), matching the PNG/npy row order.
    """
    fr = (np.arange(out_res) + 0.5) / out_res
    lons = window.lon_min + fr * (window.lon_max - window.lon_min)
    lats = window.lat_max - fr * (window.lat_max - window.lat_min)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    return lon_grid, lat_grid


def _window_cells(
    mesh: CVTMesh, window: RegionWindow, margin_deg: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(indices, unwrapped lon, lat) of cells inside the window plus margin.

    Cell longitudes are unwrapped around the window centre so the margin can
    reach across the ±180° line without tearing the triangulation.
    """
    lon_c = 0.5 * (window.lon_min + window.lon_max)
    clon = np.fromiter((c.lon for c in mesh.cells), dtype=np.float64, count=mesh.num_cells)
    clat = np.fromiter((c.lat for c in mesh.cells), dtype=np.float64, count=mesh.num_cells)
    lon_u = (clon - lon_c + 180.0) % 360.0 - 180.0 + lon_c
    mask = (
        (clat >= window.lat_min - margin_deg)
        & (clat <= window.lat_max + margin_deg)
        & (lon_u >= window.lon_min - margin_deg)
        & (lon_u <= window.lon_max + margin_deg)
    )
    (idx,) = np.nonzero(mask)
    return idx, lon_u[idx], clat[idx]


def _interpolate_window(
    mesh: CVTMesh,
    window: RegionWindow,
    out_res: int,
    field_values: np.ndarray,
    nearest: np.ndarray,
) -> np.ndarray:
    """Clough-Tocher (cubic, C1) interpolation of a per-cell scalar field.

    Cell centres keep their exact values; everything between is smooth.
    Linear Delaunay interpolation is C0 — its constant-gradient triangles show
    as visible facets between sparse cells (they surfaced on the npp channel
    and on the seafloor, where they banded the sea-depth colouring).
    NaN entries in ``field_values`` mark missing cells (excluded from the
    triangulation).

    Cubic patches are not bounded by the data: next to steep gradients (coast
    cells at +10 m beside abyss cells at −10 000 m) the interpolant dips far
    below every surrounding cell, carving phantom below-sea basins that a
    downstream sea-level flood turns into fake coastal lakes.  The result is
    therefore clipped to the [min, max] of each pixel's own triangle vertices
    (the same boundedness guarantee that linear and natural-neighbour
    interpolation give by construction), plus a global clip to the source
    value range.  Hull-exterior pixels — and windows with fewer than three
    valid cells — fall back to ``nearest`` (the nearest cell's own value,
    itself NaN where that cell is missing, preserving the missing semantics).
    """
    from scipy.interpolate import CloughTocher2DInterpolator

    margin = 1.0
    points: np.ndarray | None = None
    values: np.ndarray | None = None
    for _ in range(4):
        idx, clon, clat = _window_cells(mesh, window, margin)
        v = field_values[idx]
        ok = ~np.isnan(v)
        if int(ok.sum()) >= 3:
            points = np.column_stack([clon[ok], clat[ok]])
            values = v[ok]
            break
        margin *= 3.0
    if points is None or values is None:
        return nearest
    lon_grid, lat_grid = _window_out_grid(window, out_res)
    interp = CloughTocher2DInterpolator(points, values)
    out = interp(lon_grid, lat_grid)
    # Local boundedness clip (see docstring).  Values outside the convex hull
    # come back NaN; only interior pixels take part.
    simplex = interp.tri.find_simplex(np.column_stack([lon_grid.ravel(), lat_grid.ravel()]))
    inside = (simplex >= 0) & ~np.isnan(out.ravel())
    if inside.any():
        verts = values[interp.tri.simplices[simplex[inside]]]  # (N, 3)
        flat = out.ravel()
        flat[inside] = np.clip(flat[inside], verts.min(axis=1), verts.max(axis=1))
    out = np.clip(out, values.min(), values.max())
    return np.where(np.isnan(out), nearest, out)


def _nearest_indices_on_grid(tree: Any, lon_grid: np.ndarray, lat_grid: np.ndarray) -> np.ndarray:
    """Nearest-cell index per output pixel (same XYZ convention as the exporter)."""
    la = np.radians(lat_grid)
    lo = np.radians(lon_grid)
    cos_lat = np.cos(la)
    xyz = np.column_stack(
        [
            (cos_lat * np.cos(lo)).ravel(),
            np.sin(la).ravel(),
            (cos_lat * np.sin(lo)).ravel(),
        ]
    )
    _, idx = tree.query(xyz)
    return np.asarray(idx).reshape(lon_grid.shape)


def _cell_column_f32(mesh: CVTMesh, field: str, *, none_as: float = math.nan) -> np.ndarray:
    """Per-cell numeric field as float32 (missing → ``none_as``)."""
    return np.fromiter(
        (float(v) if (v := getattr(c, field, None)) is not None else none_as for c in mesh.cells),
        dtype=np.float32,
        count=mesh.num_cells,
    )


def _export_scalar_channel(
    values: np.ndarray,
    out_dir: Path,
    stem: str,
    *,
    png_min: float,
    png_max: float,
) -> dict[str, Any]:
    """Write one numeric channel as float32 ``.npy`` + 16-bit PNG twin.

    NaN (missing cell values) maps to 0 in the PNG; the normalisation range is
    returned so meta can record it verbatim.
    """
    np.save(out_dir / f"{stem}.npy", values.astype(np.float32))
    png_values = np.where(np.isnan(values), 0.0, values)
    export_layer_png(png_values, out_dir / f"{stem}.png", min_val=png_min, max_val=png_max)
    return {
        "png_range": [round(float(png_min), 4), round(float(png_max), 4)],
        "missing": int(np.isnan(values).sum()),
    }


def _export_headwaters(
    height: np.ndarray,
    precip: np.ndarray,
    temp: np.ndarray,
    sea_level_m: float,
    out_dir: Path,
) -> dict[str, Any]:
    """Rivers-node headwaters mask: land pixels with positive water balance.

    Rivers should originate where water surplus exists (P > PET), not merely
    where slopes permit flow — Gaea's Rivers node is slope-only by design
    ("...whether it can sustain rivers or not").  PET uses the engine's Hamon
    form (``climate_physics.potential_evapotranspiration_hamon``) evaluated on
    the annual-mean temperature (N = 12 h daylength; the documented annual
    approximation).  Output is an 8-bit mask (255 = headwater) for Gaea's
    Rivers Headwaters input.
    """
    from PIL import Image

    from dreamulator.engine.climate_physics import potential_evapotranspiration_hamon

    n = height.shape[0]
    t = np.where(np.isnan(temp), 0.0, temp)
    t12 = np.repeat(t.reshape(-1, 1), 12, axis=1)
    pet = np.asarray(potential_evapotranspiration_hamon(t12, 365.25 / 12)).reshape(n, n)
    surplus = (height > sea_level_m) & ~np.isnan(precip) & (precip > pet)
    # 16-bit, not 8-bit: Gaea 2.3.1 misreads 8-bit mask PNGs (quarter-size +
    # inverted — 0xFF lands at 255/65535 ≈ black).
    Image.fromarray(surplus.astype(np.uint16) * 65535).save(out_dir / "headwaters.png")
    return {
        "count": int(surplus.sum()),
        "criterion": "land & precipitation_mm > PET_hamon(temperature_C)",
    }


def _categorical_code_grid(
    mesh: CVTMesh, indices: np.ndarray, field: str
) -> tuple[np.ndarray, dict[str, int]]:
    """Per-pixel uint8 class codes on the output grid + the name→code map.

    Code 0 is reserved for missing values; classes get deterministic
    (alphabetical) codes assigned over the whole mesh, so a class keeps the
    same code in every region of the same world.
    """
    cell_values = [getattr(c, field, None) for c in mesh.cells]
    code_of = {name: i + 1 for i, name in enumerate(sorted({v for v in cell_values if v}))}
    codes = np.fromiter(
        (code_of.get(v, 0) for v in cell_values),
        dtype=np.uint8,
        count=mesh.num_cells,
    )[indices]
    return codes, code_of


def _export_categorical_channel(
    mesh: CVTMesh,
    indices: np.ndarray,
    out_dir: Path,
    stem: str,
    field: str,
    palette: dict[str, str],
    *,
    ocean_fallback: str | None = None,
) -> tuple[dict[str, Any], np.ndarray]:
    """Write one categorical channel as uint8 codes + colour PNG + legend.

    Returns the meta block and the code grid (the glacier mask needs it).
    The legend lists only the classes actually present in this window.
    """
    codes, code_of = _categorical_code_grid(mesh, indices, field)
    present_in_window = sorted(int(c) for c in np.unique(codes) if c > 0)
    name_of = {code: name for name, code in code_of.items()}
    legend = {code: name_of[code] for code in present_in_window}
    np.save(out_dir / f"{stem}.codes.npy", codes)
    rgba = render_categorical_layer(mesh, indices, field, palette, ocean_fallback=ocean_fallback)
    save_rgba_png(rgba, out_dir / f"{stem}.png")
    return {
        "legend": legend,
        "missing": int((codes == 0).sum()),
    }, codes


def _export_glacier_mask(
    ice: np.ndarray,
    biome_codes: np.ndarray,
    biome_legend: dict[int, str],
    out_dir: Path,
) -> dict[str, Any]:
    """Glacier-activity mask for Gaea's Glacier node (Reference input).

    Union of both evidence channels: observed/modelled ice thickness where
    available (earth) and the engine's ice biome (worlds like nacrea carry the
    EF ice-cap classification without a thickness field).  8-bit mask.
    """
    from PIL import Image

    ice_code = next((c for c, nm in biome_legend.items() if nm == "ice"), None)
    mask = ice > 0
    if ice_code is not None:
        mask = mask | (biome_codes == ice_code)
    # 16-bit, not 8-bit: Gaea 2.3.1 misreads 8-bit mask PNGs (see headwaters).
    Image.fromarray(mask.astype(np.uint16) * 65535).save(out_dir / "glacier.mask.png")
    return {
        "count": int(mask.sum()),
        "criterion": "ice_thickness_m > 0 | biome == ice",
    }


def _export_climate_channels(
    mesh: CVTMesh,
    indices: np.ndarray,
    out_dir: Path,
    scalars: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Write the satellite-imagery climate channels; returns their meta block.

    ``scalars`` holds the already-interpolated float32 grids for
    ``precipitation_mm`` / ``temperature_C`` / ``ice_thickness_m``; the
    categorical channels are sampled nearest-cell via ``indices``.
    """
    precip = scalars["precipitation_mm"]
    temp = scalars["temperature_C"]
    ice = scalars["ice_thickness_m"]
    npp = scalars["npp_gc_m2_yr"]

    precip_max = float(np.nanmax(precip)) if not np.isnan(precip).all() else 0.0
    t_min = float(np.nanmin(temp)) if not np.isnan(temp).all() else 0.0
    t_max = float(np.nanmax(temp)) if not np.isnan(temp).all() else 0.0
    ice_max = float(ice.max()) if ice.size else 0.0
    npp_max = float(np.nanmax(npp)) if not np.isnan(npp).all() else 0.0

    koppen_meta, _ = _export_categorical_channel(
        mesh,
        indices,
        out_dir,
        "koppen",
        "koppen_class",
        koppen_colors(),
        ocean_fallback="Ocean",
    )
    biome_meta, biome_codes = _export_categorical_channel(
        mesh, indices, out_dir, "biome", "biome", whittaker_colors()
    )
    channels: dict[str, Any] = {
        "precipitation_mm": _export_scalar_channel(
            precip, out_dir, "precipitation.mm", png_min=0.0, png_max=precip_max
        ),
        "temperature_C": _export_scalar_channel(
            temp, out_dir, "temperature.C", png_min=t_min, png_max=t_max
        ),
        "ice_m": _export_scalar_channel(ice, out_dir, "ice.m", png_min=0.0, png_max=ice_max),
        "npp_gc_m2_yr": _export_scalar_channel(
            npp, out_dir, "npp.gc_m2_yr", png_min=0.0, png_max=npp_max
        ),
        "koppen": koppen_meta,
        "biome": biome_meta,
        "glacier_mask": _export_glacier_mask(ice, biome_codes, biome_meta["legend"], out_dir),
    }
    runoff = scalars.get("runoff_mm")
    if runoff is not None:
        from dreamulator.engine.climate_physics import SOIL_WATER_CAPACITY_MM

        runoff_max = float(np.nanmax(runoff)) if not np.isnan(runoff).all() else 0.0
        runoff_meta = _export_scalar_channel(
            runoff, out_dir, "runoff.mm", png_min=0.0, png_max=runoff_max
        )
        runoff_meta.update(
            capacity_mm=SOIL_WATER_CAPACITY_MM,
            demand_model="hamon-1961",
            criterion="Turc-Pike (Budyko n=2) annual runoff (annual P vs Hamon annual PET)",
        )
        channels["runoff_mm"] = runoff_meta
    return channels


def export_region_pack(
    mesh: CVTMesh,
    *,
    center_lat: float,
    center_lon: float,
    span_km: float,
    radius_km: float,
    grid_width: int,
    grid_height: int,
    elev_min_m: float,
    elev_max_m: float,
    sea_level_m: float,
    out_dir: Path,
    source: dict[str, Any] | None = None,
    include_climate: bool = True,
    climate_monthly: tuple[np.ndarray, np.ndarray] | None = None,
    seafloor_clamp_m: float = -400.0,
    out_res: int = DEFAULT_OUT_RES,
) -> dict[str, Any]:
    """Export the region data pack; returns the written ``meta`` dict."""
    window = region_window(
        center_lat,
        center_lon,
        span_km,
        radius_km,
        grid_width,
        grid_height,
    )

    # The base-grid slice survives only as provenance (pixel_box) and as the
    # alignment probe's subject; pack rasters live on the square output grid.
    tree = build_export_tree(mesh)
    indices_full = export_cell_index_grid(mesh, grid_width, grid_height, tree=tree)

    lon_grid, lat_grid = _window_out_grid(window, out_res)
    indices_fine = _nearest_indices_on_grid(tree, lon_grid, lat_grid)

    cell_elev = np.fromiter(
        (c.elevation for c in mesh.cells),
        dtype=np.float64,
        count=mesh.num_cells,
    )
    height = _interpolate_window(mesh, window, out_res, cell_elev, cell_elev[indices_fine])

    lut = build_adaptive_terrain_lut(elev_min_m, elev_max_m, sea_level_m)
    color = render_terrain_layer(
        mesh,
        indices_fine,
        lut,
        elev_min_m,
        elev_max_m,
        sea_level_m,
    )

    water = np.fromiter(
        (c.water_class for c in mesh.cells),
        dtype="U6",
        count=mesh.num_cells,
    )
    ocean_frac = float((water[indices_fine] == "ocean").mean())

    h_min, h_max = float(height.min()), float(height.max())

    # Gaea-ready variant: seafloor pre-clamped so the vertical span fits
    # Gaea 2.3's Terrain Definition Height cap (10 km).  Only underwater
    # cells are clamped; land keeps the true values.
    gaea_min = max(h_min, seafloor_clamp_m)
    height_gaea = np.where(height < sea_level_m, np.maximum(height, gaea_min), height)

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "height.meters.npy", height.astype(np.float32))
    export_elevation_png(height, out_dir / "height.png", min_m=h_min, max_m=h_max)
    export_elevation_png(height_gaea, out_dir / "height.gaea.png", min_m=gaea_min, max_m=h_max)
    save_rgba_png(color, out_dir / "color.png")

    probes = probe_alignment(mesh, window, indices_full)
    meta: dict[str, Any] = {
        "pack_version": PACK_VERSION,
        "center_lat": center_lat,
        "center_lon": center_lon,
        "span_km": span_km,
        "radius_km": radius_km,
        "grid": {"w": out_res, "h": out_res},
        "sampling": (
            "scalar channels: Clough-Tocher C1 over cell centres, clipped to the "
            "local triangle vertex range (centres exact, no cubic undershoot); "
            "categorical channels and colour tint: nearest cell"
        ),
        # Exact pixel box on the full export grid (x1/y1 exclusive) — lets
        # consumers crop the global rasters identically instead of guessing
        # the floor/ceil snapping.
        "pixel_box": [window.x0, window.y0, window.x1, window.y1],
        # Actual cropped extents (the snapped pixel box, slightly ≥ span_km).
        "extent_km": {
            "x": round(window.grid_w * window.km_per_px_x, 2),
            "y": round(window.grid_h * window.km_per_px_y, 2),
        },
        "km_per_px": {
            "x": round(window.grid_w * window.km_per_px_x / out_res, 4),
            "y": round(window.grid_h * window.km_per_px_y / out_res, 4),
        },
        # Mean CVT cell spacing (km) — downstream consumers (e.g. the media
        # colorizer's boundary warp) scale their cell-relative effects by it.
        "cell_pitch_km": round(math.sqrt(4.0 * math.pi * radius_km**2 / mesh.num_cells), 2),
        "elevation_m": {"min": h_min, "max": h_max},
        # Planet-wide elevation range: consumers that must agree across
        # windows (e.g. the shared hypsometric palette — same elevation,
        # same colour on every sheet) anchor their lookup on this, not the
        # window range.
        "elevation_m_global": [float(cell_elev.min()), float(cell_elev.max())],
        "height_png_range_m": [h_min, h_max],
        "height_gaea_png_range_m": [gaea_min, h_max],
        "seafloor_clamp_m": seafloor_clamp_m,
        "sea_level_m": sea_level_m,
        "ocean_fraction": round(ocean_frac, 4),
        "alignment_probe_max_offset_deg": max(
            (p["offset_deg"] for p in probes),
            default=0.0,
        ),
        "source": source or {},
    }
    if include_climate:
        clim_scalars: dict[str, np.ndarray] = {}
        for field, none_as in (
            ("precipitation_mm", math.nan),
            ("temperature_C", math.nan),
            ("ice_thickness_m", 0.0),
            ("npp_gc_m2_yr", math.nan),
        ):
            column = _cell_column_f32(mesh, field, none_as=none_as).astype(np.float64)
            clim_scalars[field] = _interpolate_window(
                mesh, window, out_res, column, column[indices_fine]
            )
        if climate_monthly is not None:
            # Annual land runoff — the hydrology legs' accumulation weight.
            # Turc–Pike (Budyko) on the annual totals: the monthly bucket
            # underestimates annual yield in strongly seasonal climates
            # (annual_runoff_turc_pike docstring).  Computed per cell (mesh
            # order, matching every other column) then interpolated C1 like
            # the other scalars.
            from dreamulator.engine.climate_physics import (
                annual_runoff_turc_pike,
                potential_evapotranspiration_hamon,
            )

            t_monthly, p_monthly = climate_monthly
            pet_annual = potential_evapotranspiration_hamon(t_monthly, REFERENCE_MONTH_DAYS)
            runoff_col = annual_runoff_turc_pike(p_monthly.sum(axis=1), pet_annual)
            clim_scalars["runoff_mm"] = _interpolate_window(
                mesh, window, out_res, runoff_col, runoff_col[indices_fine]
            )
        meta["climate"] = _export_climate_channels(mesh, indices_fine, out_dir, clim_scalars)
        meta["climate"]["headwaters"] = _export_headwaters(
            height,
            clim_scalars["precipitation_mm"],
            clim_scalars["temperature_C"],
            sea_level_m,
            out_dir,
        )
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return meta
