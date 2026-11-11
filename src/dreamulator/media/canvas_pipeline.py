"""canvas_pipeline — disk-backed S2 hydrology driver (production path).

Runs the Barnes 2016 three-stage fill over an S1 canvas *on disk*: stage 1
processes one chunk at a time (local watershed flood, writes the local fill,
labels and a compact summary), stage 2 builds the global spillover graph from
the summaries (small) and floods it, stage 3 re-reads each chunk and raises
its cells to the global watershed level.  Memory is one chunk plus the
summaries, independent of the canvas size.

Work directory layout::

    <canvas>/hydro-work/
        fill/r<ci:03d>_c<cj:03d>.i16.npy      stage-1 local fill
        labels/r<ci:03d>_c<cj:03d>.i32.npy    local watershed labels
        summary/r<ci:03d>_c<cj:03d>.npz       spill edges + edge labels
        final/r<ci:03d>_c<cj:03d>.i16.npy     stage-3 filled surface
        chunks.sha256                         output checksums (resume)

The streaming path uses ``_local_flood`` from
:mod:`dreamulator.media.canvas_hydrology_tiled` (pure Python for now; the
numba kernel is a performance follow-up).  eps > 0 ramp grading is not yet
applied by the streaming path (the in-memory path has it); see the design doc.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.map.td_canvas import PX_PER_CELL, CanvasGeometry
from dreamulator.media.canvas_hydrology_tiled import _local_flood

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from dreamulator.map.canvas_marine import SeaConnectivity

__all__ = ["CanvasStore", "run_canvas_fill"]

#: 8-connectivity offsets (same fixed order as the fill kernels).
_NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@dataclass
class CanvasStore:
    """Canvas chunks + work directory with checksums and resume."""

    root: Path
    geometry: CanvasGeometry
    chunks: list[tuple[int, int]]
    tile: int
    work: Path
    _checked: dict[str, str] = field(default_factory=dict)
    #: ``surface_process/increments`` when S2 runs on the eroded surface
    increments: Path | None = None
    #: label of the installed surface, recorded in ``hydro-work/`` and ``hydro/``
    surface: str = "td"

    @classmethod
    def load(cls, root: Path, *, work: Path | None = None, surface: str = "auto") -> CanvasStore:
        """Open a canvas for S2.

        ``surface`` picks the installed surface: ``"td"`` the TD chunks,
        ``"surface-process"`` chunks plus the erosion-deposition increments
        (``media.canvas_surface_process``), ``"auto"`` the latter when that
        product is complete.  The work directory and ``hydro/`` keep their
        names; both record the surface they were built on (``surface.json``)
        and the fill refuses to resume on a different surface.
        """
        from dreamulator.media.canvas_surface_process import resolve_increments, surface_tag

        increments = resolve_increments(root, surface)
        meta = json.loads((root / "canvas.json").read_text(encoding="utf-8"))
        geom = meta["geometry"]
        geometry = CanvasGeometry(
            float(geom["center_lat"]),
            float(geom["center_lon"]),
            float(geom["radius_km"]),
            int(geom["ncell"]),
        )
        chunks = [(int(c[0]), int(c[1])) for c in meta.get("chunks", [])]
        if not chunks:
            chunks = sorted(
                (
                    int(p.stem.removeprefix("r").split("_c")[0]),
                    int(p.stem.split("_c")[1]),
                )
                for p in (root / "chunks").glob("r*_c*.npy")
            )
        first = root / "chunks" / f"r{chunks[0][0]:03d}_c{chunks[0][1]:03d}.npy"
        tile = int(np.load(first, mmap_mode="r").shape[0])
        work = work or (root / "hydro-work")
        for sub in ("fill", "labels", "summary", "final"):
            (work / sub).mkdir(parents=True, exist_ok=True)
        store = cls(
            root=root,
            geometry=geometry,
            chunks=chunks,
            tile=tile,
            work=work,
            increments=increments,
            surface=surface_tag(root, increments),
        )
        sums = work / "chunks.sha256"
        if sums.exists():
            for line in sums.read_text(encoding="utf-8").splitlines():
                digest, name = line.split()
                store._checked[name] = digest
        return store

    def raw(self, ci: int, cj: int) -> np.ndarray:
        name = f"r{ci:03d}_c{cj:03d}.npy"
        dem = np.asarray(np.load(self.root / "chunks" / name), dtype=np.float64)
        if self.increments is not None:
            dem += np.load(self.increments / name)
        return dem

    def path(self, sub: str, ci: int, cj: int, ext: str) -> Path:
        return self.work / sub / f"r{ci:03d}_c{cj:03d}.{ext}"

    def done(self, name: str, path: Path, *, check: bool = True) -> bool:
        if not path.exists():
            return False
        if not check:
            return True
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expect = self._checked.get(name)
        return expect is None or expect == digest

    def record(self, name: str, path: Path) -> None:
        self.record_digest(name, hashlib.sha256(path.read_bytes()).hexdigest())

    def record_digest(self, name: str, digest: str) -> None:
        self._checked[name] = digest
        sums = self.work / "chunks.sha256"
        with sums.open("a", encoding="utf-8") as fh:
            fh.write(f"{digest}  {name}\n")


#: Connected-sea product version this consumer understands (canvas contract,
#: handoff 2026-10-31 §3): sea = surface at or below 0 m that connects to the
#: geological ocean; sub-sea-level pixels without that connection are dry
#: inland lows recorded in ``surface/inland_low/``.
SEA_MASK_VERSION = "connected-sea-inland-low-20261031-v1"


def _declares_sea_mask(store: CanvasStore) -> bool:
    """True when the canvas ships the connected-sea determination."""
    meta = json.loads((store.root / "canvas.json").read_text(encoding="utf-8"))
    sea_mask = meta.get("sea_mask") or {}
    return isinstance(sea_mask, dict) and str(sea_mask.get("version", "")) == SEA_MASK_VERSION


@dataclass(frozen=True)
class AnchoredSea:
    """Sea of the installed surface: boundary-linked and geologically oceanic,
    or inside a closed water body the mesh upgraded to sea class.

    ``boundary`` holds the water bodies that reach the canvas's open boundary,
    ``geological`` the bodies that contain a pixel inside a 23 km
    geological-ocean cell, and ``mesh`` (when the canvas ships the mesh
    sea-lake field) the bodies that contain a pixel inside the interior of a
    mesh lake upgraded to ``water_class == "ocean"``.  All passes run on the same water mask, so
    they partition it into the same bodies.
    """

    boundary: SeaConnectivity
    geological: SeaConnectivity
    mesh: SeaConnectivity | None = None

    def mask(self, key: tuple[int, int], water: np.ndarray) -> np.ndarray:
        """Sea pixels of a chunk, from the same water mask used to connect it."""
        sea = self.boundary.mask(key, water) & self.geological.mask(key, water)
        if self.mesh is not None:
            sea = sea | self.mesh.mask(key, water)
        return np.asarray(sea, dtype=bool)


def _geological_ocean(root: Path, geometry: CanvasGeometry, sea_level: float) -> np.ndarray:
    """23 km geological-ocean cells of the canvas conditioning (True = ocean)."""
    path = root / "conditioning" / "heightmap.npy"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing: the canvas declares the connected-sea product, "
            "and the geological-ocean anchor needs the conditioning heightmap. "
            "Ship conditioning/heightmap.npy with the canvas."
        )
    grid = np.asarray(np.load(path))
    ncell = geometry.ncell
    if grid.shape != (ncell, ncell):
        raise ValueError(
            f"conditioning heightmap {path} has shape {grid.shape}, expected "
            f"{(ncell, ncell)} (one value per 23 km cell)"
        )
    return grid <= sea_level


#: Canvas field with the mesh's sea-class lakes (closed water upgraded to
#: ``water_class == "ocean"``) on the 23 km grid; written by S1.
MESH_SEA_LAKE_FILE = "geometry_fields/mesh_sea_lake.npy"


def _mesh_sea_lake_interior(root: Path, geometry: CanvasGeometry) -> np.ndarray | None:
    """23 km cells well inside the mesh's sea-class lakes, or None without the field.

    The mesh treats the closed water bodies it upgraded to sea class
    (``upgrade_large_endorheic_lakes``) as sea at sea level, and the GCM does
    the same.  The global ocean is not in the field: there the boundary and
    geological tests stay in charge, so closed shelf ponds and ice-dammed
    hollows inside ocean cells remain inland lows.  One 3 x 3 erosion keeps the
    coarse cells that the nearest-cell sampling put on a lake shore from
    reaching across into a land hollow next to it.
    """
    from scipy.ndimage import binary_erosion

    path = root / MESH_SEA_LAKE_FILE
    if not path.exists():
        return None
    grid = np.asarray(np.load(path)).astype(bool)
    ncell = geometry.ncell
    if grid.shape != (ncell, ncell):
        raise ValueError(
            f"mesh sea-lake field {path} has shape {grid.shape}, expected {(ncell, ncell)}"
        )
    return np.asarray(binary_erosion(grid, np.ones((3, 3), bool), border_value=1))


def _cell_span(start: int, stop: int) -> tuple[np.ndarray, np.ndarray]:
    """23 km cell indices covering pixels [start, stop) and their pixel counts."""
    ks = np.arange(start // PX_PER_CELL, -(-stop // PX_PER_CELL))
    counts = np.minimum((ks + 1) * PX_PER_CELL, stop) - np.maximum(ks * PX_PER_CELL, start)
    return ks, counts


def _anchored_sea(
    keys: list[tuple[int, int]],
    load: Callable[[tuple[int, int]], np.ndarray],
    tile: int,
    geo: np.ndarray,
    sea_level: float,
    *,
    mesh_interior: np.ndarray | None = None,
    workers: int = 8,
) -> AnchoredSea:
    """The connectivity passes of the anchored sea over one chunk list.

    ``load`` returns a chunk's raw surface and is called once per pass.  The
    boundary pass seeds the open boundary the fill itself honours — the outer
    edges of the chunk grid and the edges facing a missing chunk; the
    geological pass seeds the pixels inside 23 km geological-ocean cells of
    ``geo``, upsampled to native resolution; with ``mesh_interior`` a third
    pass seeds the pixels inside those 23 km cells the same way.
    """
    from dreamulator.map.canvas_marine import connect_sea

    present = set(keys)
    rows = {ci for ci, _ in keys}
    cols = {cj for _, cj in keys}
    rmin, rmax, cmin, cmax = min(rows), max(rows), min(cols), max(cols)

    def read_boundary(key: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        ci, cj = key
        water = load(key) <= sea_level
        seed = np.zeros_like(water)
        if ci == rmin:
            seed[0, :] = True
        if ci == rmax:
            seed[-1, :] = True
        if cj == cmin:
            seed[:, 0] = True
        if cj == cmax:
            seed[:, -1] = True
        for di, dj, sl in (
            (-1, 0, (0, slice(None))),
            (1, 0, (-1, slice(None))),
            (0, -1, (slice(None), 0)),
            (0, 1, (slice(None), -1)),
        ):
            if (ci + di, cj + dj) not in present:
                seed[sl] = True
        return water, water & seed

    def cell_seed(grid: np.ndarray) -> Callable[[tuple[int, int]], tuple[np.ndarray, np.ndarray]]:
        def read(key: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
            ci, cj = key
            water = load(key) <= sea_level
            rk, rcount = _cell_span(ci * tile, (ci + 1) * tile)
            ck, ccount = _cell_span(cj * tile, (cj + 1) * tile)
            px = np.repeat(np.repeat(grid[np.ix_(rk, ck)], rcount, axis=0), ccount, axis=1)
            return water, water & px

        return read

    mesh = None
    if mesh_interior is not None and mesh_interior.any():
        mesh = connect_sea(keys, cell_seed(mesh_interior), workers=workers)
    return AnchoredSea(
        boundary=connect_sea(keys, read_boundary, workers=workers),
        geological=connect_sea(keys, cell_seed(geo), workers=workers),
        mesh=mesh,
    )


def canvas_anchored_sea(
    root: Path,
    geometry: CanvasGeometry,
    keys: list[tuple[int, int]],
    load: Callable[[tuple[int, int]], np.ndarray],
    tile: int,
    sea_level: float,
    *,
    workers: int = 8,
) -> AnchoredSea:
    """The anchored sea of a canvas directory — the one rule S2, the seam check
    and the window renderer share."""
    return _anchored_sea(
        keys,
        load,
        tile,
        _geological_ocean(root, geometry, sea_level),
        sea_level,
        mesh_interior=_mesh_sea_lake_interior(root, geometry),
        workers=workers,
    )


def surface_sea(store: CanvasStore, sea_level: float, *, workers: int = 8) -> AnchoredSea:
    """Connected sea on the installed surface, anchored to the geological ocean.

    Water is every pixel at or below sea level.  Two out-of-core connectivity
    passes run on that same water mask:

    * the boundary pass seeds the open boundary the fill itself honours — the
      outer edges of the chunk grid and the edges facing a missing chunk;
    * the geological pass seeds the pixels inside 23 km geological-ocean cells
      (``conditioning/heightmap.npy`` at or below sea level, upsampled to native
      resolution).

    A water body is sea when it passes both tests, or when it contains a pixel
    inside a closed water body the mesh upgraded to sea class
    (``geometry_fields/mesh_sea_lake.npy``, 3 x 3-eroded).  Boundary reach alone would
    make a sea out of an inland closed basin that happens to touch the canvas's
    artificial edge — canvases overlap, so one canvas's boundary runs through
    another's interior.  Geological contact alone is the coarse-seed rule,
    which misjudges ice-dammed hollows and ponds inside shallow shelf cells.
    Each condition closes the other's failure mode, with no new parameter.
    The mesh rule follows the long-wavelength canon: closed water bodies the
    mesh upgraded to sea class share sea level with the global ocean there and
    in the GCM, so S2 does not fill them to their sill.  A canvas planned
    before the field existed keeps the two-test rule (``canvas mesh-sea-lake``
    backfills it).

    The canvas's own water, not its bed: hydrology runs on the installed
    surface, where grounded ice can close a basin that the sub-ice bed links
    to the ocean.
    """
    return canvas_anchored_sea(
        store.root,
        store.geometry,
        list(store.chunks),
        lambda key: store.raw(*key),
        store.tile,
        sea_level,
        workers=workers,
    )


def chunk_ocean(
    store: CanvasStore,
    key: tuple[int, int],
    dem: np.ndarray,
    sea_level: float,
    *,
    sea: SeaConnectivity | AnchoredSea | None = None,
) -> np.ndarray:
    """Open sea per pixel.

    With ``sea`` (the canvas's anchored surface connectivity) the outlet is
    water that reaches the canvas's open boundary inside a geologically oceanic
    body, minus the product's inland lows.  Without it — a canvas that does
    not declare the connected-sea product — the legacy rule keeps every pixel
    at or below sea level as an outlet.
    """
    water = dem <= sea_level
    if sea is None:
        return water
    from dreamulator.map.canvas_marine import read_inland_low

    ci, cj = key
    ocean = np.asarray(sea.mask(key, water), dtype=bool) & water
    inland = read_inland_low(store.root, f"r{ci:03d}_c{cj:03d}", dem.shape)
    return np.asarray(ocean & ~inland)


def _external_mask(
    store: CanvasStore,
    key: tuple[int, int],
    dem: np.ndarray,
    sea_level: float,
    *,
    healed: np.ndarray | None = None,
    sea: SeaConnectivity | AnchoredSea | None = None,
) -> np.ndarray:
    ci, cj = key
    # Connected sea is the outlet; dry inland lows below sea level are not.
    ext = chunk_ocean(store, key, dem, sea_level, sea=sea)
    if healed is not None and healed.any():
        # Healed pit cells sit AT sea level but are land the fill must
        # flood (the region chain's heal→PF order); leaving them in the
        # seed mask would keep them outlets and rivers would still sink.
        ext &= ~healed
    rows = {ci for ci, _ in store.chunks}
    cols = {cj for _, cj in store.chunks}
    if ci == min(rows):
        ext[0, :] = True
    if ci == max(rows):
        ext[-1, :] = True
    if cj == min(cols):
        ext[:, 0] = True
    if cj == max(cols):
        ext[:, -1] = True
    present = set(store.chunks)
    for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        if (ci + di, cj + dj) in present:
            continue
        if di == -1:
            ext[0, :] = True
        elif di == 1:
            ext[-1, :] = True
        elif dj == -1:
            ext[:, 0] = True
        else:
            ext[:, -1] = True
    return ext


def _ensure_heal_delta(
    store: CanvasStore, sea_level: float, *, verbose: bool = True
) -> tuple[dict[str, np.ndarray], bool]:
    """Compute (or load) the whole-canvas inland-water heal delta.

    ``heal_inland_water`` needs whole-canvas connectivity and ocean
    distance, so it runs once on the assembled DEM; its sparse result
    (healed pit cells + genuine endorheic bodies) is stored under
    ``hydro-work/heal.npz`` and applied chunk by chunk by the tiled fill.
    This keeps the on-disk fill pipeline in the region chain's exact
    heal→priority-flood order.  NaN cells (missing chunks / neighbour
    canvases) are excluded from the water labelling via the land input.
    Chunks are part of the stored fingerprint: a changed chunk list means
    the delta is stale — clear ``hydro-work`` and rerun (the fill caches
    predate the heal generation).
    """
    from dreamulator.map.prog_erosion import LAKE_MIN_WIDTH_KM, heal_inland_water, lake_mmu_cells

    if _declares_sea_mask(store):
        # The canvas ships the connectivity verdict, so there is no sub-sea
        # water body left to classify: pixels at or below sea level that are
        # not connected sea are dry inland lows (ordinary terrain for the
        # fill) and the connected sea is the outlet.  Healing existed to
        # remove sub-sea-level TD noise pits that made rivers terminate; the
        # product now identifies them at the production scale, and the lake
        # criteria decide whether any of them holds water.
        empty_idx = np.zeros(0, dtype=np.int64)
        if verbose:
            print("[hydrology] heal: skipped (connected-sea product)")
        return (
            {"idx": empty_idx, "h": np.zeros(0, dtype=np.float32), "inland_idx": empty_idx},
            False,
        )

    path = store.work / "heal.npz"
    if path.exists():
        data = np.load(path)
        if str(data["chunks"]) != str(store.chunks):
            raise RuntimeError(
                "hydro-work/heal.npz was built for a different chunk list — "
                "clear hydro-work and rerun the fill"
            )
        return {"idx": data["idx"], "h": data["h"], "inland_idx": data["inland_idx"]}, False

    t = store.tile
    nrow = (max(ci for ci, _ in store.chunks) + 1) * t
    ncol = (max(cj for _, cj in store.chunks) + 1) * t
    dem = np.full((nrow, ncol), np.nan, dtype=np.float64)
    for ci, cj in store.chunks:
        dem[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t] = store.raw(ci, cj)
    finite = np.isfinite(dem)
    # Same foreshore-floor rule as canvas_flow_fields: 0..−2 m strips are
    # hydrology land (rivers must flow across), not water to heal.
    from dreamulator.map.td_canvas_mosaic import INTERTIDAL_M

    land_floor = sea_level if INTERTIDAL_M is None else sea_level + INTERTIDAL_M[0]
    land0 = finite & (dem >= land_floor)
    healed, land, inland_big = heal_inland_water(
        dem,
        land0 | ~finite,
        lake_mmu_cells(store.geometry.px_km),
        sea_level,
        km_per_px=store.geometry.px_km,
        min_width_km=LAKE_MIN_WIDTH_KM,
    )
    changed = finite & ((healed != dem) | (land & ~land0))
    idx = np.flatnonzero(changed.reshape(-1))
    inland_idx = np.flatnonzero(inland_big.reshape(-1))
    flat_h = healed.reshape(-1)[idx].astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        chunks=np.array(str(store.chunks)),
        idx=idx.astype(np.int64),
        h=flat_h,
        inland_idx=inland_idx.astype(np.int64),
    )
    if verbose:
        print(
            f"[hydrology] heal: {len(idx)} pit cells → land, "
            f"{len(inland_idx)} endorheic-water cells"
        )
    return {"idx": idx, "h": flat_h, "inland_idx": inland_idx}, True


#: Watershed node ids: chunk index times this stride plus the local label
#: (label 0 is the tile's external basin, merged into node 0).
_NODE_STRIDE = 1_000_000


def _node_id(chunk_index: int, lab: int) -> int:
    return chunk_index * _NODE_STRIDE + lab


def default_workers(cap: int = 16) -> int:
    """Worker processes for per-chunk stages: the CPUs this process may use, capped.

    Each stage-1 worker holds a few float64 copies of one chunk (about 0.3 GB
    for 2048 x 2048 tiles), so the cap bounds memory as well as contention.
    """
    import os

    try:
        n = len(os.sched_getaffinity(0))
    except AttributeError:  # not on Linux
        n = os.cpu_count() or 1
    return max(1, min(cap, n))


@dataclass
class _FillContext:
    """Read-only state every per-chunk worker gets once at start-up.

    Inherited through fork, pickled once per worker under spawn (Windows), so
    it holds only per-canvas state; per-chunk data travels with each task.
    """

    store: CanvasStore
    sea_level: float
    sea: AnchoredSea | None
    healed: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]]


_WORKER_CTX: _FillContext | None = None


def _bucket_healed(
    idx: np.ndarray,
    h: np.ndarray,
    ncol: int,
    tile: int,
    keys: list[tuple[int, int]],
) -> dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Healed pit cells grouped by chunk: (local rows, local cols, heights)."""
    out: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    if not idx.size or not keys:
        return out
    r = idx // ncol
    c = idx % ncol
    ci, cj = r // tile, c // tile
    wanted = set(keys)
    order = np.lexsort((cj, ci))
    ci, cj, r, c, hh = ci[order], cj[order], r[order], c[order], h[order]
    breaks = np.flatnonzero((np.diff(ci) != 0) | (np.diff(cj) != 0)) + 1
    for lo, hi in zip(np.r_[0, breaks], np.r_[breaks, ci.size], strict=True):
        key = (int(ci[lo]), int(cj[lo]))
        if key in wanted:
            out[key] = (r[lo:hi] - key[0] * tile, c[lo:hi] - key[1] * tile, hh[lo:hi])
    return out


def _init_worker(ctx: _FillContext) -> None:
    global _WORKER_CTX
    _WORKER_CTX = ctx


def _stage1_chunk(task: Any) -> tuple[tuple[int, int], dict[str, np.ndarray], str]:
    """Local flood of one chunk; writes fill, labels and summary, returns the summary."""
    key: tuple[int, int] = task
    ctx = _WORKER_CTX
    assert ctx is not None
    store, sea_level = ctx.store, ctx.sea_level
    ci, cj = key
    fill_path = store.path("fill", ci, cj, "i16.npy")
    dem = store.raw(ci, cj)
    healed_mask = np.zeros(dem.shape, dtype=bool)
    if key in ctx.healed:
        rr, cc, hh = ctx.healed[key]
        dem[rr, cc] = hh
        healed_mask[rr, cc] = True
    ext = _external_mask(store, key, dem, sea_level, healed=healed_mask, sea=ctx.sea)
    labels, filled, spill = _local_flood(dem, ext)
    np.save(fill_path, np.rint(filled).astype(np.int16))
    np.save(store.path("labels", ci, cj, "i32.npy"), labels.astype(np.int32))
    edge = {
        "top_lab": labels[0, :].astype(np.int32),
        "top_z": np.rint(dem[0, :]).astype(np.int16),
        "bottom_lab": labels[-1, :].astype(np.int32),
        "bottom_z": np.rint(dem[-1, :]).astype(np.int16),
        "left_lab": labels[:, 0].astype(np.int32),
        "left_z": np.rint(dem[:, 0]).astype(np.int16),
        "right_lab": labels[:, -1].astype(np.int32),
        "right_z": np.rint(dem[:, -1]).astype(np.int16),
    }
    if spill:
        spill_ab = np.array(list(spill.keys()), dtype=np.int64)
        spill_levels = np.array(list(spill.values()), dtype=np.float64)
    else:
        spill_ab = np.zeros((0, 2), dtype=np.int64)
        spill_levels = np.zeros(0, dtype=np.float64)
    np.savez(
        store.path("summary", ci, cj, "npz"),
        spill_ab=spill_ab,
        spill_level=spill_levels,
        **edge,
    )
    summary = {"spill_ab": spill_ab, "spill_level": spill_levels, **edge}
    return key, summary, hashlib.sha256(fill_path.read_bytes()).hexdigest()


def _level_table(
    level: dict[int, float], chunk_index: int, summary: dict[str, np.ndarray]
) -> np.ndarray:
    """Global water level of each local label of one chunk (-inf: keep the fill).

    Local labels start only at tile-edge cells, so the edge arrays bound them;
    label 0 (the external basin) keeps its fill.
    """
    top = max(
        int(summary[name].max(initial=0))
        for name in ("top_lab", "bottom_lab", "left_lab", "right_lab")
    )
    table = np.full(top + 1, -np.inf)
    for lab in range(1, top + 1):
        lv = level.get(_node_id(chunk_index, lab))
        if lv is not None:
            table[lab] = lv
    return table


def _stage3_chunk(task: Any) -> tuple[tuple[int, int], dict[str, np.ndarray], str]:
    """Raise one chunk's cells to their watershed level (one table lookup per pixel)."""
    key, table = task
    ctx = _WORKER_CTX
    assert ctx is not None
    store = ctx.store
    ci, cj = key
    labels = np.load(store.path("labels", ci, cj, "i32.npy"))
    filled = np.load(store.path("fill", ci, cj, "i16.npy")).astype(np.float64)
    top = int(labels.max())
    if top >= table.size:  # defensive: a label beyond the edge bound has no level
        table = np.concatenate([table, np.full(top + 1 - table.size, -np.inf)])
    out = np.maximum(filled, table[labels])
    final_path = store.path("final", ci, cj, "i16.npy")
    np.save(final_path, np.rint(out).astype(np.int16))
    return key, {}, hashlib.sha256(final_path.read_bytes()).hexdigest()


def _start_method() -> str:
    """fork where available (Linux), else spawn (Windows, macOS default).

    ``DREAMULATOR_START_METHOD`` overrides it, so the spawn path can be
    exercised on Linux too.
    """
    import multiprocessing as mp
    import os

    wanted = os.environ.get("DREAMULATOR_START_METHOD")
    methods = mp.get_all_start_methods()
    if wanted:
        if wanted not in methods:
            raise ValueError(f"start method {wanted!r} is not available here ({methods})")
        return wanted
    return "fork" if "fork" in methods else "spawn"


def _map_chunks(
    fn: Callable[[Any], tuple[tuple[int, int], dict[str, np.ndarray], str]],
    ctx: _FillContext,
    tasks: list[Any],
    workers: int | None,
) -> Iterator[tuple[tuple[int, int], dict[str, np.ndarray], str]]:
    """Run ``fn`` over per-chunk tasks in a process pool (results in task order).

    Each worker receives ``ctx`` once through its initializer — inherited under
    fork, pickled under spawn — and per-chunk data with each task.
    """
    n = default_workers() if workers is None else max(1, workers)
    if n == 1 or len(tasks) < 2:
        _init_worker(ctx)
        try:
            for task in tasks:
                yield fn(task)
        finally:
            _init_worker_clear()
        return
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(
        max_workers=min(n, len(tasks)),
        mp_context=mp.get_context(_start_method()),
        initializer=_init_worker,
        initargs=(ctx,),
    ) as pool:
        yield from pool.map(fn, tasks, chunksize=1)


def _init_worker_clear() -> None:
    global _WORKER_CTX
    _WORKER_CTX = None


def _chunk_max_label(summary: dict[str, np.ndarray]) -> int:
    top = max(
        int(summary[name].max(initial=0))
        for name in ("top_lab", "bottom_lab", "left_lab", "right_lab")
    )
    ab = summary["spill_ab"]
    return max(top, int(ab.max(initial=0)) if ab.size else 0)


def _seam_edges(
    lab_a: np.ndarray,
    z_a: np.ndarray,
    lab_b: np.ndarray,
    z_b: np.ndarray,
    off_a: int,
    off_b: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Edges between two facing chunk edges (8-neighbourhood across the seam)."""
    n = lab_a.size
    ea, eb, ew = [], [], []
    for d in (-1, 0, 1):
        i = np.arange(max(0, -d), min(n, n - d))
        j = i + d
        la, lb = lab_a[i].astype(np.int64), lab_b[j].astype(np.int64)
        ea.append(np.where(la > 0, la + off_a, 0))
        eb.append(np.where(lb > 0, lb + off_b, 0))
        ew.append(np.maximum(z_a[i], z_b[j]).astype(np.float64))
    return np.concatenate(ea), np.concatenate(eb), np.concatenate(ew)


def _watershed_levels(
    keys: list[tuple[int, int]],
    summaries: dict[tuple[int, int], dict[str, np.ndarray]],
    t: int,
) -> tuple[dict[tuple[int, int], np.ndarray], int]:
    """Stage 2: per-chunk water-level tables and the number of watersheds that drain.

    Local labels get compact global node ids (node 0 = every chunk's external
    basin).  Edges are the chunks' spill pairs plus the seams between
    neighbouring chunks, built per seam with numpy: the right and bottom
    neighbours and the two diagonal corners, each unordered pair once.  The
    minimax Priority-Flood over that graph runs in numba
    (:func:`dreamulator.map._parallel_flood.minimax_levels`).  Levels are the
    unique minimax spill heights, so the tables equal the dict-and-heapq
    reference bit for bit.
    """
    from dreamulator.map._parallel_flood import minimax_levels

    tops = {key: _chunk_max_label(summaries[key]) for key in keys}
    off: dict[tuple[int, int], int] = {}
    nn = 1
    for key in keys:
        off[key] = nn - 1  # node = off + lab for lab >= 1
        nn += tops[key]
    ea: list[np.ndarray] = []
    eb: list[np.ndarray] = []
    ew: list[np.ndarray] = []
    for key in keys:
        s = summaries[key]
        ab = s["spill_ab"].astype(np.int64).reshape(-1, 2)
        if ab.size:
            ea.append(np.where(ab[:, 0] > 0, ab[:, 0] + off[key], 0))
            eb.append(np.where(ab[:, 1] > 0, ab[:, 1] + off[key], 0))
            ew.append(s["spill_level"].astype(np.float64))
        ci, cj = key
        right, down = (ci, cj + 1), (ci + 1, cj)
        if right in summaries:
            r = summaries[right]
            e = _seam_edges(
                s["right_lab"], s["right_z"], r["left_lab"], r["left_z"], off[key], off[right]
            )
            ea.append(e[0])
            eb.append(e[1])
            ew.append(e[2])
        if down in summaries:
            d = summaries[down]
            e = _seam_edges(
                s["bottom_lab"], s["bottom_z"], d["top_lab"], d["top_z"], off[key], off[down]
            )
            ea.append(e[0])
            eb.append(e[1])
            ew.append(e[2])
        for corner, (ya, xa), (yb, xb) in (
            ((ci + 1, cj + 1), (t - 1, t - 1), (0, 0)),
            ((ci + 1, cj - 1), (t - 1, 0), (0, t - 1)),
        ):
            if corner not in summaries:
                continue
            la, za = _edge_cell(s, ya, xa, t)
            lb, zb = _edge_cell(summaries[corner], yb, xb, t)
            ea.append(np.array([la + off[key] if la else 0], np.int64))
            eb.append(np.array([lb + off[corner] if lb else 0], np.int64))
            ew.append(np.array([max(za, zb)], np.float64))
    a = np.concatenate(ea) if ea else np.zeros(0, np.int64)
    b = np.concatenate(eb) if eb else np.zeros(0, np.int64)
    w = np.concatenate(ew) if ew else np.zeros(0, np.float64)
    keep = a != b
    level = minimax_levels(nn, a[keep], b[keep], w[keep])
    drained = int(np.count_nonzero(np.isfinite(level[1:])))
    level = np.where(np.isfinite(level), level, -np.inf)  # unreached labels keep their fill
    tables = {}
    for key in keys:
        table = np.full(tops[key] + 1, -np.inf)
        table[1:] = level[off[key] + 1 : off[key] + tops[key] + 1]
        tables[key] = table
    return tables, drained


def _edge_cell(summary: dict[str, np.ndarray], y: int, x: int, t: int) -> tuple[int, float]:
    if y == 0:
        return int(summary["top_lab"][x]), float(summary["top_z"][x])
    if y == t - 1:
        return int(summary["bottom_lab"][x]), float(summary["bottom_z"][x])
    if x == 0:
        return int(summary["left_lab"][y]), float(summary["left_z"][y])
    return int(summary["right_lab"][y]), float(summary["right_z"][y])


def _watershed_levels_reference(
    keys: list[tuple[int, int]],
    summaries: dict[tuple[int, int], dict[str, np.ndarray]],
    t: int,
) -> tuple[dict[tuple[int, int], np.ndarray], int]:
    """Pure-Python stage 2 (dict graph and heapq), the oracle for :func:`_watershed_levels`."""
    pairs = {key: i for i, key in enumerate(keys)}

    def node_id(key: tuple[int, int], lab: int) -> int:
        return _node_id(pairs[key], lab)

    edges: dict[int, dict[int, float]] = {}

    def add_edge(a: int, b: int, spill: float) -> None:
        if a == b:
            return
        ea = edges.setdefault(a, {})
        if b not in ea or spill < ea[b]:
            ea[b] = spill
        eb = edges.setdefault(b, {})
        if a not in eb or spill < eb[a]:
            eb[a] = spill

    for key in keys:
        s = summaries[key]
        for (a, b), spill_value in zip(s["spill_ab"], s["spill_level"], strict=True):
            a, b = int(a), int(b)
            add_edge(
                node_id(key, a) if a else 0,
                node_id(key, b) if b else 0,
                float(spill_value),
            )
    # Cross-tile border pairs: each border cell against its 8-neighbours.

    def edge_lab_z(summary: dict[str, np.ndarray], y: int, x: int) -> tuple[int, float]:
        if y == 0:
            return int(summary["top_lab"][x]), float(summary["top_z"][x])
        if y == t - 1:
            return int(summary["bottom_lab"][x]), float(summary["bottom_z"][x])
        if x == 0:
            return int(summary["left_lab"][y]), float(summary["left_z"][y])
        return int(summary["right_lab"][y]), float(summary["right_z"][y])

    border: list[tuple[int, int]] = [(0, x) for x in range(t)]
    border += [(t - 1, x) for x in range(t)]
    border += [(y, 0) for y in range(1, t - 1)]
    border += [(y, t - 1) for y in range(1, t - 1)]
    for key in keys:
        ci, cj = key
        s = summaries[key]
        for y, x in border:
            lab, z = edge_lab_z(s, y, x)
            for dy, dx in _NEIGHBOURS:
                ny, nx = y + dy, x + dx
                if 0 <= ny < t and 0 <= nx < t:
                    continue
                nci, ncj = ci, cj
                nny, nnx = ny, nx
                if ny < 0:
                    nci, nny = ci - 1, t - 1
                elif ny >= t:
                    nci, nny = ci + 1, 0
                if nx < 0:
                    ncj, nnx = cj - 1, t - 1
                elif nx >= t:
                    ncj, nnx = cj + 1, 0
                nkey = (nci, ncj)
                if nkey not in summaries:
                    continue
                nlab, nz = edge_lab_z(summaries[nkey], nny, nnx)
                add_edge(
                    node_id(key, lab) if lab else 0,
                    node_id(nkey, nlab) if nlab else 0,
                    max(z, nz),
                )

    level: dict[int, float] = {0: float("-inf")}
    heap: list[tuple[float, int]] = [(float("-inf"), 0)]
    while heap:
        cur_level, node = heapq.heappop(heap)
        if cur_level != level.get(node):
            continue
        for nb, w in edges.get(node, {}).items():
            cand = max(cur_level, w)
            if nb not in level or cand < level[nb]:
                level[nb] = cand
                heapq.heappush(heap, (cand, nb))

    tables = {key: _level_table(level, pairs[key], summaries[key]) for key in keys}
    return tables, len(level) - 1


def run_canvas_fill(
    store: CanvasStore,
    *,
    sea_level: float = 0.0,
    resume: bool = True,
    verbose: bool = True,
    workers: int | None = None,
) -> dict[str, float]:
    """Run the three-stage fill on disk; returns timing/statistics.

    Stages 1 and 3 are per chunk and run on ``workers`` processes (default:
    :func:`default_workers`); the result does not depend on the worker count.
    """
    t = store.tile
    keys = store.chunks
    ncol = (max(cj for _, cj in store.chunks) + 1) * t
    stats = {"cells": 0.0, "watersheds": 0.0, "stages_seconds": 0.0}
    t0 = time.time()
    from dreamulator.media.canvas_surface_process import read_surface_tag, write_surface_tag

    done_on = read_surface_tag(store.work)
    if done_on is not None and done_on != store.surface:
        if resume:
            raise RuntimeError(
                f"{store.work} was filled on surface {done_on!r}, not {store.surface!r}: "
                "rerun without resume (canvas hydrology --force)"
            )
        for sub in ("fill", "labels", "summary", "final"):
            for stale in (store.work / sub).glob("r*_c*.*"):
                stale.unlink()
        (store.work / "chunks.sha256").unlink(missing_ok=True)
        (store.work / "heal.npz").unlink(missing_ok=True)
        store._checked.clear()
    write_surface_tag(store.work, store.surface)
    heal, heal_fresh = _ensure_heal_delta(store, sea_level, verbose=verbose)
    if heal_fresh and any((store.work / "fill").glob("r*_c*.i16.npy")):
        # Fill caches predating the heal generation treat pit cells as flood
        # seeds; a first-time heal next to surviving caches means heal.npz
        # was removed by hand — refuse rather than resume stale semantics.
        raise RuntimeError(
            "heal.npz was rebuilt but pre-heal fill caches remain — clear hydro-work and rerun"
        )
    healed_idx, healed_h = heal["idx"], heal["h"]
    # Canvases that ship the connected-sea product determine the sea on the
    # installed surface: water that reaches the canvas's open boundary.  One
    # out-of-core pass over the chunks, reused by every stage-1 chunk.
    sea = None
    if _declares_sea_mask(store):
        sea = surface_sea(store, sea_level)
        if verbose:
            rule = "boundary connectivity anchored to the geological ocean"
            if sea.mesh is not None:
                rule += ", plus the mesh's sea-class lakes"
            elif not (store.root / MESH_SEA_LAKE_FILE).exists():
                rule += f" ({MESH_SEA_LAKE_FILE} missing: mesh sea-class lakes not applied)"
            print(f"[hydrology] sea: {rule}")
    if verbose:
        surface = "TD chunks + surface_process increments" if store.increments else "TD chunks"
        print(f"[hydrology] surface: {surface} ({store.surface})")

    # Stage 1: local flood per chunk; summaries on disk.  Chunks are
    # independent, so they run in a process pool; the parent alone appends to
    # the checksum ledger.
    summaries: dict[tuple[int, int], dict[str, np.ndarray]] = {}
    todo: list[tuple[int, int]] = []
    for ci, cj in keys:
        fill_path = store.path("fill", ci, cj, "i16.npy")
        sum_path = store.path("summary", ci, cj, "npz")
        if resume and store.done(f"fill/{ci:03d}_{cj:03d}", fill_path) and sum_path.exists():
            data = np.load(sum_path)
            summaries[(ci, cj)] = {name: data[name] for name in data.files}
        else:
            todo.append((ci, cj))
    healed_by_chunk = _bucket_healed(healed_idx, healed_h, ncol, t, todo)
    ctx = _FillContext(store, sea_level, sea, healed_by_chunk)
    for key, summary, digest in _map_chunks(_stage1_chunk, ctx, todo, workers):
        ci, cj = key
        store.record_digest(f"fill/{ci:03d}_{cj:03d}", digest)
        summaries[key] = summary
        stats["cells"] += float(t * t)
    if verbose:
        print(f"[hydrology] stage 1 (local floods): {len(keys)} chunks")

    # Stage 2: global watershed spillover graph.
    tables, drained = _watershed_levels(list(keys), summaries, t)
    stats["watersheds"] = float(drained)
    if verbose:
        print(f"[hydrology] stage 2 (watershed graph): {drained} watersheds")

    # Stage 3: raise each chunk's cells to its watershed level.  Stage 2
    # already cut the levels into per-chunk tables; the workers get one each.
    tasks = [
        ((ci, cj), tables[(ci, cj)])
        for ci, cj in keys
        if not (
            resume
            and store.done(f"final/{ci:03d}_{cj:03d}", store.path("final", ci, cj, "i16.npy"))
        )
    ]
    del tables, summaries
    ctx = _FillContext(store, sea_level, None, {})
    for (ci, cj), _summary, digest in _map_chunks(_stage3_chunk, ctx, tasks, workers):
        store.record_digest(f"final/{ci:03d}_{cj:03d}", digest)
    stats["stages_seconds"] = time.time() - t0
    if verbose:
        print(f"[hydrology] done in {stats['stages_seconds']:.1f} s")
    return stats


def _shift(f: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Neighbour view ``out[y, x] = f[y + dy, x + dx]`` (+inf outside)."""
    h, w = f.shape
    out = np.full_like(f, np.inf)
    src_r = slice(max(0, dy), h + min(0, dy))
    src_c = slice(max(0, dx), w + min(0, dx))
    dst_r = slice(max(0, -dy), h + min(0, -dy))
    dst_c = slice(max(0, -dx), w + min(0, -dx))
    out[dst_r, dst_c] = f[src_r, src_c]
    return out


def _grade_flats(filled: np.ndarray, sea_level: float, eps: float) -> np.ndarray:
    """PF+ε ramp for flow routing: equal-value flats grade toward their outlets.

    Numba kernel fast path (semantics identical to
    :func:`_grade_flats_reference`, the pure-Python oracle): multi-source
    Dijkstra over each flat level, seeds are outlets and cells touching a
    strictly lower level.  The result is used only for flow directions, not
    written back.
    """
    from dreamulator.media._hydrology_kernels import _grade_flats_kernel

    # Banded in place: the previous whole-canvas float64 twin plus the
    # np.where/np.maximum temporaries peaked at four f64 fields and ran the
    # 654M-cell canvas out of memory.
    level = _grade_flats_kernel(np.ascontiguousarray(filled), sea_level, eps).reshape(filled.shape)
    out = np.empty(filled.shape, dtype=np.float32)
    h = filled.shape[0]
    band = max(1, min(2048, h))
    for r0 in range(0, h, band):
        r1 = min(h, r0 + band)
        lv = level[r0:r1]
        fl = filled[r0:r1]
        finite = np.isfinite(lv)
        np.maximum(lv, fl, out=lv)
        lv[~finite] = fl[~finite]
        out[r0:r1] = lv
    return out


def _grade_flats_reference(filled: np.ndarray, sea_level: float, eps: float) -> np.ndarray:
    """PF+ε ramp for flow routing: equal-value flats grade toward their outlets.

    Mirrors the in-memory fill's ramp (multi-source Dijkstra over each flat
    level: seeds are outlets and cells touching a strictly lower level).
    The result is used only for flow directions, not written back.
    """
    h, w = filled.shape
    flat = filled.ravel().astype(np.float64)
    level = np.full(flat.size, np.inf)
    hq: list[tuple[float, int]] = []
    for c in range(flat.size):
        v = flat[c]
        if not np.isfinite(v):
            continue
        r, col = divmod(c, w)
        if v <= sea_level:
            level[c] = v
            hq.append((v, c))
            continue
        low = False
        for dy, dx in _NEIGHBOURS:
            nr, nc = r + dy, col + dx
            if 0 <= nr < h and 0 <= nc < w and filled[nr, nc] < v - 1e-9:
                low = True
                break
        if low:
            level[c] = v
            hq.append((v, c))
    heapq.heapify(hq)
    while hq:
        lv, c = heapq.heappop(hq)
        if lv != level[c]:
            continue
        r, col = divmod(c, w)
        for dy, dx in _NEIGHBOURS:
            nr, nc = r + dy, col + dx
            if not (0 <= nr < h and 0 <= nc < w):
                continue
            nid = nr * w + nc
            if filled[nr, nc] != filled[r, col]:
                continue
            nl = lv + eps
            if nl < level[nid]:
                level[nid] = nl
                heapq.heappush(hq, (nl, nid))
    out = np.where(np.isfinite(level), np.maximum(level, flat), flat)
    return out.reshape(h, w).astype(np.float32)


def _climate_on_grid(coarse: np.ndarray, h: int, w: int) -> np.ndarray:
    """Tile a canvas climate grid onto the assembled chunk-bbox pixel grid.

    The climate grid spans the whole canvas (``ncell`` cells of
    ``PX_PER_CELL`` pixels); the assembled array starts at canvas pixel 0
    and usually stops short of the canvas edge.  The grid is therefore
    cropped to the array's extent and each cell repeated ``PX_PER_CELL``
    times.  Scaling by ``h // ncell`` is wrong whenever the chunk bounding
    box does not reach the far canvas edge — it shears every field.
    """
    f = PX_PER_CELL
    rows = min(coarse.shape[0], h // f)
    cols = min(coarse.shape[1], w // f)
    out = np.zeros((h, w), dtype=coarse.dtype)
    for i in range(rows):
        out[i * f : (i + 1) * f, : cols * f] = np.repeat(coarse[i, :cols], f)[None, :]
    return out


_FlowFields = tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
]


def canvas_flow_fields(store: CanvasStore, *, sea_level: float = 0.0) -> _FlowFields:
    """Assembled (filled, dem, receiver, accumulation, land, order, weight,
    inland_big) for QA/extraction.

    Applies the PF+ε flat grading before the D8 receivers so depressions have
    defined flow directions.  ``weight`` (runoff-weighted, reference-
    normalised) feeds the terminal-lake verdict alongside the accumulation;
    ``inland_big`` is the endorheic-water mask from the fill's heal delta.
    Memory scales with the canvas (QA/demo path): the D8 loop is banded and
    the runoff weights are tiled per coarse row, so beyond the returned
    full-canvas arrays no whole-canvas temporaries remain.  ``order`` is the
    downstream-first (ascending filled) sort used by accumulation — NaN cells
    sort last, matching the ``nan_to_num(1e30)`` order of previous versions
    without the full-size copy.
    """
    from dreamulator.map.prog_erosion import RUNOFF_REFERENCE_MM, flow_accumulation

    t = store.tile
    nrow = (max(ci for ci, _ in store.chunks) + 1) * t
    ncol = (max(cj for _, cj in store.chunks) + 1) * t
    filled = np.full((nrow, ncol), np.nan, dtype=np.float32)
    for ci, cj in store.chunks:
        filled[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t] = np.load(
            store.path("final", ci, cj, "i16.npy")
        ).astype(np.float32)
    h, w = filled.shape
    filled = _grade_flats(filled, sea_level, 1e-3)
    # int32 receivers: cell indices < 2^31 on every canvas, half the int64
    # footprint — the accumulation kernel specialises per dtype.
    rec2d = np.full((h, w), -1, dtype=np.int32)
    diag = 2**0.5
    cc = np.arange(w, dtype=np.int32)[None, :]
    # Banded D8: ``best`` and the receiver candidates are band-local, so the
    # per-neighbour temporaries scale with the band, not the whole canvas
    # (the previous full-size int64 mgrid/where chain peaked > 20 GiB here).
    band_rows = max(1, min(2048, h))
    for r0 in range(0, h, band_rows):
        r1 = min(h, r0 + band_rows)
        fb = filled[r0:r1]
        best = np.zeros(fb.shape, dtype=np.float64)  # slope: keep f64 for tie determinism
        recb = np.full(fb.shape, -1, dtype=np.int32)
        rr = np.arange(r0, r1, dtype=np.int32)[:, None]
        for dy, dx in _NEIGHBOURS:
            # Neighbour values via one row of band context: _shift on the
            # context slice reproduces the global out[y,x]=f[y+dy,x+dx] with
            # +inf outside the canvas, at band-sized cost.
            ctx0 = max(0, r0 - 1)
            ctx1 = min(h, r1 + 1)
            shifted = _shift(filled[ctx0:ctx1], dy, dx)
            nb = shifted[r0 - ctx0 : r1 - ctx0]
            slope = (fb - nb) / (diag if dy and dx else 1.0)
            better = np.isfinite(slope) & (nb < fb) & (slope > best)
            best = np.where(better, slope, best)
            recb = np.where(better, (rr + dy) * w + (cc + dx), recb)
        rec2d[r0:r1] = recb
    # Hydrology land reaches down to the drying foreshore's low edge
    # (INTERTIDAL_M's lower bound).  A tidal flat is dry for part of the
    # cycle and water crosses it, so a channel's receiver must be able to
    # continue across the band to the open sea; reading the band as sea
    # ended chains mid-flat.  The render masks keep their own elevation
    # rules, so the shore still paints as water under the line.
    from dreamulator.map.td_canvas_mosaic import INTERTIDAL_M

    land_floor = sea_level if INTERTIDAL_M is None else sea_level + INTERTIDAL_M[0]
    land = np.isfinite(filled) & (filled >= land_floor)
    # A canvas with the connected-sea product has no heal delta (its inland
    # lows are ordinary terrain); a stale heal.npz from an older generation
    # must not be applied to it.
    heal_path = store.work / "heal.npz"
    if heal_path.exists() and not _declares_sea_mask(store):
        healed_idx = np.load(heal_path)["idx"]
        land.reshape(-1)[healed_idx] = True
    rec = rec2d.reshape(-1)
    rec[~land.reshape(-1)] = -1
    del rec2d
    # NaN sorts after every real value (same stable order nan_to_num(1e30)
    # produced) — skips a full-canvas copy per sort.  int32 twin of the
    # argsort output (values < 2^31): the int64 intermediate is transient.
    order = np.argsort(filled.ravel(), kind="stable").astype(np.int32)
    runoff_path = store.root / "climate" / "runoff.mm.npy"
    if runoff_path.exists():
        coarse = np.nan_to_num(np.load(runoff_path).astype(np.float32), nan=0.0)
        # The climate grid spans the whole canvas; the chunk bounding box
        # may stop short of the canvas edge, so crop and tile at the true
        # cell size instead of rescaling (see _climate_on_grid).
        weight = _climate_on_grid(np.maximum(coarse, 0.0), h, w) / RUNOFF_REFERENCE_MM
        weight[~land] = 0.0
    else:
        weight = land.astype(np.float32)
    acc = flow_accumulation(order, rec, weight.ravel()).reshape(h, w)
    dem = np.full((nrow, ncol), np.nan, dtype=np.float32)
    for ci, cj in store.chunks:
        dem[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t] = store.raw(ci, cj).astype(np.float32)
    inland_big = np.zeros((h, w), dtype=bool)
    heal_path = store.work / "heal.npz"
    if heal_path.exists() and not _declares_sea_mask(store):
        idx = np.load(heal_path)["inland_idx"]
        flat = inland_big.reshape(-1)
        flat[idx] = True
    return filled, dem, rec, acc, land, order, weight, inland_big


def run_canvas_rivers(
    store: CanvasStore,
    *,
    sea_level: float = 0.0,
    threshold_cells: int = 27000,  # same onset as the CLI default (about 2.1 m3/s at 90 m)
    verbose: bool = True,
) -> dict[str, object]:
    """Extract channel mask and vector river segments from the final fill.

    Runs the region chain's full hydrology post-processing, shared verbatim:
    geometry lakes + healed endorheic bodies → the terminal-lake annual
    water-balance cascade (``terminal_equilibrium_routing``) → equilibrium
    rewrite with chain stops and shrunk-fringe descent trees → segment
    extraction with the complete lake semantics.  Writes the river products
    plus the lake tables (``lakes.json``, ``terminal_lakes.json``,
    ``lakes.sparse/``) that S3 windows consume instead of re-deriving.
    """
    from dreamulator.map.prog_erosion import (
        LAKE_MIN_WIDTH_KM,
        RUNOFF_REFERENCE_MM,
        lake_mmu_cells,
        month_active_counts,
        regime_active_cells,
        renderable_lakes,
        river_mask,
        river_segments,
        terminal_equilibrium_routing,
    )

    filled, dem, rec, _acc0, land, order, weight, inland_big = canvas_flow_fields(
        store, sea_level=sea_level
    )
    # The terminal chain re-accumulates from scratch — free the flow-fields
    # accumulation before the cascade's own whole-canvas peaks (a 377M-cell
    # canvas runs these dels at ~9 GB of headroom).
    del _acc0
    h, w = filled.shape
    km = store.geometry.px_km
    mmu = lake_mmu_cells(km)
    climate = store.root / "climate"
    weight_source = "runoff.mm" if (climate / "runoff.mm.npy").exists() else "uniform"

    # Terminal-lake verdict chain: without a temperature/precipitation basis
    # (or without runoff weighting) the routing degrades to the geometry
    # lake with no verdicts — the region chain's same degenerate mode.
    lakes_draw0 = renderable_lakes(filled, dem, inland_big, mmu, km)
    del filled, inland_big
    temp_path = climate / "temperature.C.npy"
    precip_path = climate / "precipitation.mm.npy"
    # The water-balance verdict needs runoff weighting AND a temperature
    # basis (the region chain's rule: no temperature → balance off).  The
    # climate grids stay COARSE and the balances look lake cells up per
    # block — the values equal a full tiling without canvas-sized fields.
    has_basis = weight_source == "runoff.mm" and temp_path.exists() and precip_path.exists()
    run_norm = RUNOFF_REFERENCE_MM if has_basis else 0.0
    precip = np.zeros((1, 1), dtype=np.float32)
    temp_c = np.zeros((1, 1), dtype=np.float32)
    climate_block = 1
    if has_basis:
        precip = np.nan_to_num(np.load(precip_path).astype(np.float32), nan=0.0)
        temp_c = np.nan_to_num(np.load(temp_path).astype(np.float32), nan=0.0)
        climate_block = PX_PER_CELL  # one climate cell = PX_PER_CELL pixels
    # Lake-surface demand: the energy-based open-water channel S1 writes
    # (engine/lake_evaporation.py); canvases planned before it fall back to
    # the Hamon demand, which underestimates cold clear plateaus severalfold.
    open_water = None
    lake_path = climate / "lake_evaporation.mm.npy"
    if has_basis and lake_path.exists():
        open_water = np.nan_to_num(np.load(lake_path).astype(np.float32), nan=0.0)
    if verbose and has_basis:
        source = (
            "open-water energy balance"
            if open_water is not None
            else ("Hamon fallback (no lake_evaporation.mm channel; re-plan the canvas)")
        )
        print(f"[hydrology] lake evaporation: {source}")
    (
        _h_rewritten,
        land,
        lakes_draw,
        chain_stop,
        fringe_desc,
        rec_route,
        acc,
        _term_water,
        lake_stats,
        lake_records,
    ) = terminal_equilibrium_routing(
        dem,
        land,
        lakes_draw0,
        order,
        rec,
        weight.ravel(),
        precip_mm=precip,
        temp_c=temp_c,
        runoff_land_mean_mm=run_norm,
        mmu_cells=mmu,
        km_per_px=km,
        sea_level_m=sea_level,
        climate_block=climate_block,
        open_water_mm=open_water,
        consume_receiver=True,
        keep_rewritten_h=False,
    )
    # Routing consumed them; the regime pass and segment extraction below
    # work from order/rec_route/acc (and the monthly pack's own weights).
    del dem, weight
    rivers = river_mask(acc, land, threshold_cells)

    # Monthly regime on the FINAL routing (terminal footprints cut; the
    # demand verdict is annual, see month_active_counts).
    month_active = None
    monthly_path = climate / "runoff_monthly.mm.npy"
    if monthly_path.exists():
        monthly = np.load(monthly_path).astype(np.float32)
        if monthly.ndim == 3:
            monthly = np.moveaxis(monthly, 0, -1)  # (12,n,n) -> (n,n,12)
            active = regime_active_cells(km)
            factor = PX_PER_CELL
            month_active = month_active_counts(
                order, rec_route, monthly, land, active, factor=factor
            )

    segs, flows, regimes = river_segments(
        rivers,
        rec_route,
        acc,
        km,
        lake=chain_stop,
        lake_descend=fringe_desc,
        month_active=month_active,
        pixel_rows=store.geometry.size_px,
    )
    hydro = store.root / "hydro"
    hydro.mkdir(exist_ok=True)
    from dreamulator.media.canvas_surface_process import write_surface_tag

    write_surface_tag(hydro, store.surface)
    np.save(hydro / "rivers.line.npy", segs.astype(np.float32))
    np.save(hydro / "rivers.flow.npy", flows.astype(np.float32))
    np.save(hydro / "rivers.regime.npy", regimes.astype(np.uint8))
    from PIL import Image

    Image.fromarray(((rivers & ~lakes_draw).astype(np.uint8) * 255), mode="L").save(
        hydro / "rivers.png"
    )

    _write_lake_tables(store, lakes_draw, lake_records, lake_stats, mmu, km)

    heal_path = store.work / "heal.npz"
    healed_cells = (
        int(np.load(heal_path)["idx"].size)
        if heal_path.exists() and not _declares_sea_mask(store)
        else 0
    )
    meta = {
        "threshold_cells": threshold_cells,
        "weight_source": weight_source,
        "km_per_px": km,
        "segments": int(len(flows)),
        "perennial": int((regimes == 0).sum()),
        "non_perennial": int((regimes == 1).sum()),
        "regime_source": "monthly-runoff" if month_active is not None else "annual-default",
        "terminal_lakes": lake_stats,
        "sea_source": (
            "surface-boundary-connectivity" if _declares_sea_mask(store) else "sea-level"
        ),
        "healed_pit_cells": healed_cells,
        "lake_mmu_cells": mmu,
        "lake_min_width_km": LAKE_MIN_WIDTH_KM,
    }
    (hydro / "rivers.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if verbose:
        print(
            f"[hydrology] rivers: {len(flows)} segments "
            f"({int((regimes == 0).sum())} perennial / {int((regimes == 1).sum())} non-perennial); "
            f"terminal {lake_stats.get('terminal', 0)} "
            f"(dry playas {lake_stats.get('dry_playas', 0)}, shrunk {lake_stats.get('shrunk', 0)})"
        )
    return {
        "segments": float(len(flows)),
        "perennial": float((regimes == 0).sum()),
        "non_perennial": float((regimes == 1).sum()),
    }


def _write_lake_tables(
    store: CanvasStore,
    lakes_draw: np.ndarray,
    lake_records: list[dict[str, object]],
    lake_stats: dict[str, int],
    mmu: int,
    km: float,
) -> None:
    """Write the lake products S3 windows consume: ``lakes.sparse/`` (per
    chunk sparse pixels + lake ids), ``lakes.json`` (per-lake geometry and
    verdict record), ``terminal_lakes.json`` (verdict statistics and the
    method provenance).  The presence of these tables is the canvas's
    "lake production done" signal (asset_status semantics) — their absence
    is not a zero-lake claim."""
    import json

    from scipy import ndimage

    hydro = store.root / "hydro"
    sparse_dir = hydro / "lakes.sparse"
    sparse_dir.mkdir(exist_ok=True)
    t = store.tile
    counts: np.ndarray
    if lakes_draw.any():
        lbl, _n = ndimage.label(lakes_draw)
        counts = np.bincount(lbl.ravel(), minlength=_n + 1)
    else:
        lbl = np.zeros(lakes_draw.shape, dtype=np.int32)
        counts = np.zeros(1, dtype=np.int64)
    for ci, cj in store.chunks:
        block = lbl[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t]
        ids = [int(k) for k in np.unique(block) if k > 0]
        if not ids:
            continue
        flat_block = block.ravel()
        idx = np.flatnonzero(flat_block)
        np.savez(
            sparse_dir / f"lake.r{ci:03d}_c{cj:03d}.npz",
            idx=idx.astype(np.uint32),
            lake_id=flat_block[idx].astype(np.uint16),
        )
    area_km2 = km * km

    def _record(rec: dict[str, object]) -> dict[str, object]:
        label = int(rec["label"])  # type: ignore[call-overload]
        return {
            "id": label,
            "area_km2": round(float(counts[label]) * area_km2, 3),
            **{k: v for k, v in rec.items() if k != "label"},
        }

    records = [_record(rec) for rec in lake_records]
    (hydro / "lakes.json").write_text(
        json.dumps(
            {
                "schema": "canvas-lakes-v1",
                "pixel_area_km2": round(area_km2, 6),
                "lakes": records,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (hydro / "terminal_lakes.json").write_text(
        json.dumps(
            {
                "schema": "canvas-terminal-lakes-v1",
                "stats": lake_stats,
                "method": "terminal-equilibrium-routing-v1",
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
