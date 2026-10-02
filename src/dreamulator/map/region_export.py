"""Region pack export — crop a square world region for external renderers.

Produces the data pack consumed by the Blender minimal render chain
(``scripts/media/blender/region_still.py``):

* ``height.meters.npy`` — float32 height in metres, the primary data channel
  (exact round-trip, no colour-space pitfalls in ``bpy``'s bundled Python);
* ``height.png`` — 16-bit height normalised to the REGION's own min/max, for
  human inspection (the numeric channel stays authoritative);
* ``color.png`` — hypsometric terrain tint cropped from the same grid, using
  the frontend's palette single source (``build_adaptive_terrain_lut``);
* ``meta.json`` — physical extents, scaling and provenance for the builder.

Region selection is a centre + physical span in km on the planet's real
radius.  The equirectangular crop compensates the cos(lat) east–west stretch
exactly at the centre latitude; polar regions (|lat| > 75°) and antimeridian
crossings are rejected — those need the stereographic leg of the Gaea chain
(``docs/design/proposals/gaea-refinement.md`` §3).

The crop is sliced from a full-grid ``export_cell_index_grid`` pass, so every
pack pixel is bit-identical to the corresponding pixel of a global export —
alignment by construction, never re-projected.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.map.export import (
    export_cell_index_grid,
    export_elevation_png,
    render_terrain_layer,
    save_rgba_png,
)
from dreamulator.map.palettes import build_adaptive_terrain_lut

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


def read_radius_km(map_dir: Path) -> float:
    """Planet radius from ``map.yaml`` (extra field dropped by MapMetadata)."""
    import yaml

    map_yaml = map_dir / "map.yaml"
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

    indices_full = export_cell_index_grid(mesh, grid_width, grid_height)
    indices = indices_full[window.y0 : window.y1, window.x0 : window.x1]

    cell_elev = np.fromiter(
        (c.elevation for c in mesh.cells),
        dtype=np.float64,
        count=mesh.num_cells,
    )
    height = cell_elev[indices]

    lut = build_adaptive_terrain_lut(elev_min_m, elev_max_m, sea_level_m)
    color = render_terrain_layer(
        mesh,
        indices,
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
    ocean_frac = float((water[indices] == "ocean").mean())

    h_min, h_max = float(height.min()), float(height.max())

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "height.meters.npy", height.astype(np.float32))
    export_elevation_png(height, out_dir / "height.png", min_m=h_min, max_m=h_max)
    save_rgba_png(color, out_dir / "color.png")

    probes = probe_alignment(mesh, window, indices_full)
    meta: dict[str, Any] = {
        "center_lat": center_lat,
        "center_lon": center_lon,
        "span_km": span_km,
        "radius_km": radius_km,
        "grid": {"w": window.grid_w, "h": window.grid_h},
        # Exact pixel box on the full export grid (x1/y1 exclusive) — lets
        # consumers crop the global rasters identically instead of guessing
        # the floor/ceil snapping.
        "pixel_box": [window.x0, window.y0, window.x1, window.y1],
        # Actual cropped extents (the snapped pixel box, slightly ≥ span_km).
        "extent_km": {
            "x": round(window.grid_w * window.km_per_px_x, 2),
            "y": round(window.grid_h * window.km_per_px_y, 2),
        },
        "km_per_px": {"x": window.km_per_px_x, "y": window.km_per_px_y},
        "elevation_m": {"min": h_min, "max": h_max},
        "height_png_range_m": [h_min, h_max],
        "sea_level_m": sea_level_m,
        "ocean_fraction": round(ocean_frac, 4),
        "alignment_probe_max_offset_deg": max(
            (p["offset_deg"] for p in probes),
            default=0.0,
        ),
        "source": source or {},
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return meta
