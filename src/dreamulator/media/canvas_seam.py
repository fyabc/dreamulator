"""canvas_seam — S4: cross-canvas seam consistency check.

Adjacent canvases are generated independently: each owns a set of CVT cells
and its terrain inside its own square.  Where two owners meet, the two TD
generations must still describe one continuous landscape before the blend
(``td_canvas.blend_overlap``) is applied, otherwise the sheet shows a step in
elevation, a river that stops at the boundary, or a lake that exists on one
side only.

``seam_pairs.json`` lists the sample points (one per pair of adjacent land
cells with different owners) and gives, for every point, its canvas pixel
coordinates in both owners.  This module reads those points, samples each
canvas's products at the recorded position, and reports the disagreement:

* **surface elevation** — the DEM value of each side, in metres
  (``surface_delta_m``);
* **bedrock elevation** — surface minus ice thickness (``bed_delta_m``), with
  both sides' ice thickness; on ice-free points it equals the surface delta;
* **land/sea** — the anchored sea determination (the same rule S2 and S3 use)
  at each side, reported as its own category: a point the two canvases
  disagree is a generation fault that no elevation tolerance covers, because
  the ice-margin refinement closes on the sea side only and amplifies such
  disagreements;
* **water** — whether the point is a lake cell on each side;
* **river** — whether a river segment passes within ``river_reach_km`` on
  each side, and the flow of the nearest segment;
* **coordinates** — the recorded pixel position re-derived from the
  latitude/longitude through the canvas geometry, as a pairing-integrity
  check.

Every sample is graded per product, and a product with no data on one side is
reported as *unavailable* rather than as agreement: an absent hydro product
is not a zero-flow claim (the canvas contract's own rule for lake tables).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import numpy as np

from dreamulator.map.td_canvas import CanvasGeometry

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.media.canvas_pipeline import AnchoredSea

__all__ = [
    "PairReport",
    "SeamPair",
    "SeamSample",
    "SeamLocation",
    "load_seam_pairs",
    "run_seam_check",
]

#: Canvas chunk edge in pixels (contract §3), used when no chunk exists yet.
DEFAULT_TILE = 2048
#: A pixel position and the one re-derived from lat/lon should agree this
#: closely; a larger gap means the pairing file and the geometry disagree.
COORD_TOLERANCE_PX = 1.0
#: River presence is tested against this distance from the sample point (the
#: segment grid is one 90 m cell; a seam point sits between two cell centres).
DEFAULT_RIVER_REACH_KM = 0.5


@dataclass(frozen=True)
class SeamLocation:
    """One canvas's pixel coordinates for a seam sample."""

    canvas: str
    row_px: float
    col_px: float
    chunk: tuple[int, int]


@dataclass(frozen=True)
class SeamSample:
    """One geographic point owned by two different canvases."""

    cell_ids: tuple[int, ...]
    latitude_deg: float
    longitude_deg: float
    locations: tuple[SeamLocation, ...]


@dataclass(frozen=True)
class SeamPair:
    """The samples shared by one canvas pair."""

    canvases: tuple[str, ...]
    samples: tuple[SeamSample, ...]


@dataclass
class PairReport:
    """Everything measured for one canvas pair.

    ``counts`` holds how many samples produced a value for each product, so a
    pair with no terrain says "0 of 23" instead of silently passing.
    """

    canvases: tuple[str, ...]
    samples: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    surface_delta_m: list[float] = field(default_factory=list)
    bed_delta_m: list[float] = field(default_factory=list)
    landsea_disagree: int = 0
    landsea_points: list[dict[str, object]] = field(default_factory=list)
    water_disagree: int = 0
    river_disagree: int = 0
    flow_ratios: list[float] = field(default_factory=list)
    coord_mismatch_px: float = 0.0
    worst: list[dict[str, object]] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        def stats(values: list[float]) -> dict[str, object] | None:
            d = np.asarray(values, dtype=np.float64)
            if not d.size:
                return None
            return {
                "n": int(d.size),
                "median_abs_m": float(np.median(np.abs(d))),
                "p95_abs_m": float(np.percentile(np.abs(d), 95)),
                "max_abs_m": float(np.max(np.abs(d))),
            }

        ratios = np.asarray(self.flow_ratios, dtype=np.float64)
        return {
            "canvases": list(self.canvases),
            "samples": self.samples,
            "counts": dict(self.counts),
            "surface_delta": stats(self.surface_delta_m),
            "bed_delta": stats(self.bed_delta_m),
            "landsea_disagree": self.landsea_disagree,
            "landsea_points": self.landsea_points,
            "water_disagree": self.water_disagree,
            "river_disagree": self.river_disagree,
            "flow_ratio": (
                {
                    "n": int(ratios.size),
                    "median": float(np.median(ratios)),
                    "max": float(np.max(ratios)),
                }
                if ratios.size
                else None
            ),
            "coord_mismatch_px": round(self.coord_mismatch_px, 3),
            "worst": self.worst,
        }


def load_seam_pairs(canvases_root: Path) -> tuple[list[SeamPair], str]:
    """Read ``seam_pairs.json`` from a canvases directory."""

    path = canvases_root / "seam_pairs.json"
    if not path.exists():
        raise FileNotFoundError(f"no seam pairing file at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    pairs: list[SeamPair] = []
    for entry in data.get("pairs", []):
        samples = []
        for raw in entry.get("samples", []):
            locs = tuple(
                SeamLocation(
                    canvas=str(loc["canvas"]),
                    row_px=float(loc["row_px"]),
                    col_px=float(loc["col_px"]),
                    chunk=(int(loc["chunk"][0]), int(loc["chunk"][1])),
                )
                for loc in raw["locations"]
            )
            samples.append(
                SeamSample(
                    cell_ids=tuple(int(c) for c in raw.get("cell_ids", ())),
                    latitude_deg=float(raw["latitude_deg"]),
                    longitude_deg=float(raw["longitude_deg"]),
                    locations=locs,
                )
            )
        pairs.append(
            SeamPair(canvases=tuple(str(c) for c in entry["canvases"]), samples=tuple(samples))
        )
    return pairs, str(data.get("format", ""))


def _canvas_geometry(canvas_root: Path) -> CanvasGeometry:
    meta = json.loads((canvas_root / "canvas.json").read_text(encoding="utf-8"))
    geom = meta["geometry"]
    return CanvasGeometry(
        float(geom["center_lat"]),
        float(geom["center_lon"]),
        float(geom["radius_km"]),
        int(geom["ncell"]),
    )


def _tile_size(canvas_root: Path) -> int:
    chunk_dir = canvas_root / "chunks"
    for path in sorted(chunk_dir.glob("r*_c*.npy")):
        return int(np.load(path, mmap_mode="r").shape[0])
    return DEFAULT_TILE


def _local_index(loc: SeamLocation, tile: int) -> tuple[int, int]:
    """Fractional canvas pixel position → (row, col) inside its chunk."""
    ci, cj = loc.chunk
    row = int(np.floor(loc.row_px)) - ci * tile
    col = int(np.floor(loc.col_px)) - cj * tile
    return row, col


def _chunk_path(canvas_root: Path, loc: SeamLocation) -> Path:
    ci, cj = loc.chunk
    return canvas_root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy"


def sample_elevation(canvas_root: Path, loc: SeamLocation, tile: int) -> float | None:
    """DEM metres at the sample point, or None when the chunk is absent."""
    path = _chunk_path(canvas_root, loc)
    if not path.exists():
        return None
    row, col = _local_index(loc, tile)
    if not (0 <= row < tile and 0 <= col < tile):
        return None
    chunk = np.load(path, mmap_mode="r")
    return float(chunk[row, col])


def sample_ice(canvas_root: Path, loc: SeamLocation, tile: int) -> float | None:
    """Ice thickness metres at the sample point; 0 when the block has no ice.

    None means the canvas ships no ice product at all (no
    ``surface/ice_chunks/``), which leaves the bedrock caliber *unverified*
    rather than identical-to-surface — a missing product is not a zero-ice
    claim.
    """
    ice_dir = canvas_root / "surface" / "ice_chunks"
    if not ice_dir.is_dir():
        return None
    ci, cj = loc.chunk
    path = ice_dir / f"r{ci:03d}_c{cj:03d}.npy"
    if not path.exists():
        return 0.0
    row, col = _local_index(loc, tile)
    if not (0 <= row < tile and 0 <= col < tile):
        return 0.0
    return float(np.load(path, mmap_mode="r")[row, col])


def _anchored_sea_of(
    canvas_root: Path, cache: dict[Path, AnchoredSea | None]
) -> AnchoredSea | None:
    """The canvas's anchored sea, or None when its data does not allow it.

    Read-only: builds the connectivity straight from the chunk files (no
    CanvasStore, no work directory).  A canvas without the conditioning grid
    or with unreadable chunks leaves the land/sea caliber unverified.
    """
    if canvas_root in cache:
        return cache[canvas_root]
    sea: AnchoredSea | None = None
    try:
        from dreamulator.media.canvas_pipeline import _anchored_sea, _geological_ocean

        keys = [
            (int(c[0]), int(c[1]))
            for c in json.loads((canvas_root / "canvas.json").read_text(encoding="utf-8")).get(
                "chunks", []
            )
        ]
        if not keys:
            keys = sorted(
                (int(p.stem.removeprefix("r").split("_c")[0]), int(p.stem.split("_c")[1]))
                for p in (canvas_root / "chunks").glob("r*_c*.npy")
            )
        tile = _tile_size(canvas_root)

        def load(key: tuple[int, int]) -> np.ndarray:
            ci, cj = key
            return np.asarray(np.load(canvas_root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy"))

        sea = _anchored_sea(
            keys,
            load,
            tile,
            _geological_ocean(canvas_root, _canvas_geometry(canvas_root), 0.0),
            0.0,
            workers=4,
        )
    except (OSError, ValueError, KeyError):
        sea = None
    cache[canvas_root] = sea
    return sea


def sample_sea(
    sea: AnchoredSea | None, canvas_root: Path, loc: SeamLocation, tile: int
) -> bool | None:
    """Sea membership at the sample point; None when undeterminable."""
    if sea is None:
        return None
    path = _chunk_path(canvas_root, loc)
    if not path.exists():
        return None
    row, col = _local_index(loc, tile)
    water = np.asarray(np.load(path)) <= 0.0
    return bool(sea.mask(loc.chunk, water)[row, col])


def sample_lake(canvas_root: Path, loc: SeamLocation, tile: int) -> bool | None:
    """True/False when the canvas has lake tables, None when it does not."""
    sparse = canvas_root / "hydro" / "lakes.sparse"
    if not sparse.is_dir():
        return None
    ci, cj = loc.chunk
    path = sparse / f"lake.r{ci:03d}_c{cj:03d}.npz"
    if not path.exists():
        return False  # the chunk is covered but carries no lake cells
    row, col = _local_index(loc, tile)
    data = np.load(path)
    flat = row * tile + col
    return bool(np.isin(flat, data["idx"]).any())


def sample_river(
    canvas_root: Path, loc: SeamLocation, reach_km: float
) -> tuple[float, float] | None:
    """(distance_km, flow) of the nearest river segment, or None without hydro.

    The returned distance is unbounded — callers compare it with the reach to
    decide presence; the flow is reported so the two sides can be compared.
    """
    line_path = canvas_root / "hydro" / "rivers.line.npy"
    if not line_path.exists():
        return None
    geom = _canvas_geometry(canvas_root)
    segs = np.load(line_path).astype(np.float64)
    if segs.size == 0:
        return None
    # Same SW-origin canvas km frame as the product (cell_xyz_km).
    px = geom.px_km
    x = loc.col_px * px
    y = (geom.size_px - 1.0 - loc.row_px) * px
    a, b = segs[:, 0], segs[:, 1]
    ab = b - a
    length2 = np.einsum("ij,ij->i", ab, ab)
    safe = np.where(length2 > 0.0, length2, 1.0)
    t = np.clip(np.einsum("ij,ij->i", np.asarray([x, y]) - a, ab) / safe, 0.0, 1.0)
    proj = a + t[:, None] * ab
    dist = np.hypot(proj[:, 0] - x, proj[:, 1] - y)
    nearest = int(np.argmin(dist))
    flows_path = canvas_root / "hydro" / "rivers.flow.npy"
    flow = float(np.load(flows_path)[nearest]) if flows_path.exists() else float("nan")
    return float(dist[nearest]), flow


def _pair_report(
    pair: SeamPair,
    canvases_root: Path,
    *,
    river_reach_km: float,
    sea_cache: dict[Path, AnchoredSea | None],
) -> PairReport:
    report = PairReport(canvases=pair.canvases, samples=len(pair.samples))
    counts = {"elevation": 0, "bedrock": 0, "landsea": 0, "water": 0, "river": 0}
    for sample in pair.samples:
        if len(sample.locations) != 2:
            continue
        left, right = sample.locations
        roots = [canvases_root / left.canvas, canvases_root / right.canvas]
        tiles = [_tile_size(root) if (root / "chunks").is_dir() else DEFAULT_TILE for root in roots]

        # Pairing integrity: the recorded pixel position must match the one
        # the canvas geometry derives from the same lat/lon.
        for loc, root in zip((left, right), roots, strict=True):
            if not (root / "canvas.json").exists():
                continue
            geom = _canvas_geometry(root)
            row, col = geom.latlon_to_pixel(
                np.asarray([sample.latitude_deg]), np.asarray([sample.longitude_deg])
            )
            err = float(
                np.hypot(float(np.ravel(row)[0]) - loc.row_px, float(np.ravel(col)[0]) - loc.col_px)
            )
            report.coord_mismatch_px = max(report.coord_mismatch_px, err)

        elevations = [
            sample_elevation(root, loc, tile)
            for root, loc, tile in zip(roots, (left, right), tiles, strict=True)
        ]
        ices = [
            sample_ice(root, loc, tile)
            for root, loc, tile in zip(roots, (left, right), tiles, strict=True)
        ]
        if all(v is not None for v in elevations):
            counts["elevation"] += 1
            surf_l, surf_r = (float(v) for v in elevations)  # type: ignore[arg-type]
            surface_delta = surf_l - surf_r
            report.surface_delta_m.append(surface_delta)
            bed_delta: float | None = None
            ice_pair: list[float] | None = None
            if all(v is not None for v in ices):
                counts["bedrock"] += 1
                ice_l, ice_r = (float(v) for v in ices)  # type: ignore[arg-type]
                bed_delta = (surf_l - ice_l) - (surf_r - ice_r)
                report.bed_delta_m.append(bed_delta)
                ice_pair = [round(ice_l, 1), round(ice_r, 1)]
            report.worst.append(
                {
                    "lat": round(sample.latitude_deg, 4),
                    "lon": round(sample.longitude_deg, 4),
                    "surface_delta_m": round(surface_delta, 1),
                    "bed_delta_m": None if bed_delta is None else round(bed_delta, 1),
                    "ice_m": ice_pair,
                }
            )

        seas = [
            sample_sea(_anchored_sea_of(root, sea_cache), root, loc, tile)
            for root, loc, tile in zip(roots, (left, right), tiles, strict=True)
        ]
        if all(v is not None for v in seas):
            counts["landsea"] += 1
            if bool(seas[0]) != bool(seas[1]):
                report.landsea_disagree += 1
                report.landsea_points.append(
                    {
                        "lat": round(sample.latitude_deg, 4),
                        "lon": round(sample.longitude_deg, 4),
                        "sides": [bool(seas[0]), bool(seas[1])],
                    }
                )

        lakes = [
            sample_lake(root, loc, tile)
            for root, loc, tile in zip(roots, (left, right), tiles, strict=True)
        ]
        if all(v is not None for v in lakes):
            counts["water"] += 1
            if bool(lakes[0]) != bool(lakes[1]):
                report.water_disagree += 1

        rivers = [
            sample_river(root, loc, river_reach_km)
            for root, loc in zip(roots, (left, right), strict=True)
        ]
        if all(v is not None for v in rivers):
            counts["river"] += 1
            (d0, f0), (d1, f1) = rivers  # type: ignore[misc]
            present = [d0 <= river_reach_km, d1 <= river_reach_km]
            if present[0] != present[1]:
                report.river_disagree += 1
            if all(present) and f0 > 0.0 and f1 > 0.0:
                report.flow_ratios.append(max(f0 / f1, f1 / f0))
    report.counts = counts
    report.worst.sort(key=lambda w: -abs(cast("float", w["surface_delta_m"])))
    report.worst = report.worst[:5]
    return report


def run_seam_check(
    canvases_root: Path,
    *,
    river_reach_km: float = DEFAULT_RIVER_REACH_KM,
) -> dict[str, object]:
    """Check every seam pair; returns the aggregated report.

    The report always carries a ``coverage`` block naming which canvases have
    terrain chunks on disk, so "no measured disagreement" and "nothing to
    measure" cannot be confused.
    """

    pairs, fmt = load_seam_pairs(canvases_root)
    have_chunks = sorted(
        child.name
        for child in canvases_root.iterdir()
        if child.is_dir()
        and (child / "chunks").is_dir()
        and any((child / "chunks").glob("r*_c*.npy"))
    )
    sea_cache: dict[Path, AnchoredSea | None] = {}
    reports = [
        _pair_report(pair, canvases_root, river_reach_km=river_reach_km, sea_cache=sea_cache)
        for pair in pairs
    ]
    return {
        "format": fmt,
        "canvases_with_chunks": have_chunks,
        "pairs": [report.summary() for report in reports],
    }
