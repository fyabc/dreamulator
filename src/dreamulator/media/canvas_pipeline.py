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
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_hydrology_tiled import _local_flood
from dreamulator.media.lake_masks import lake_footprint

if TYPE_CHECKING:
    from pathlib import Path

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

    @classmethod
    def load(cls, root: Path, *, work: Path | None = None) -> CanvasStore:
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
        store = cls(root=root, geometry=geometry, chunks=chunks, tile=tile, work=work)
        sums = work / "chunks.sha256"
        if sums.exists():
            for line in sums.read_text(encoding="utf-8").splitlines():
                digest, name = line.split()
                store._checked[name] = digest
        return store

    def raw(self, ci: int, cj: int) -> np.ndarray:
        return np.asarray(
            np.load(self.root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy"), dtype=np.float64
        )

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
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self._checked[name] = digest
        sums = self.work / "chunks.sha256"
        with sums.open("a", encoding="utf-8") as fh:
            fh.write(f"{digest}  {name}\n")


def _external_mask(
    store: CanvasStore, key: tuple[int, int], dem: np.ndarray, sea_level: float
) -> np.ndarray:
    ci, cj = key
    ext = dem <= sea_level
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


def run_canvas_fill(
    store: CanvasStore,
    *,
    sea_level: float = 0.0,
    resume: bool = True,
    verbose: bool = True,
) -> dict[str, float]:
    """Run the three-stage fill on disk; returns timing/statistics."""
    t = store.tile
    keys = store.chunks
    pairs: dict[tuple[int, int], int] = {(ci, cj): i for i, (ci, cj) in enumerate(keys)}
    stats = {"cells": 0.0, "watersheds": 0.0, "stages_seconds": 0.0}
    t0 = time.time()

    # Stage 1: local flood per chunk; summaries on disk.
    summaries: dict[tuple[int, int], dict[str, np.ndarray]] = {}
    for ci, cj in keys:
        key = (ci, cj)
        fill_path = store.path("fill", ci, cj, "i16.npy")
        label_path = store.path("labels", ci, cj, "i32.npy")
        sum_path = store.path("summary", ci, cj, "npz")
        if resume and store.done(f"fill/{ci:03d}_{cj:03d}", fill_path) and sum_path.exists():
            data = np.load(sum_path)
            summaries[key] = {name: data[name] for name in data.files}
            continue
        dem = store.raw(ci, cj)
        ext = _external_mask(store, key, dem, sea_level)
        labels, filled, spill = _local_flood(dem, ext)
        np.save(fill_path, np.rint(filled).astype(np.int16))
        np.save(label_path, labels.astype(np.int32))
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
        np.savez(sum_path, spill_ab=spill_ab, spill_level=spill_levels, **edge)
        store.record(f"fill/{ci:03d}_{cj:03d}", fill_path)
        summaries[key] = {
            "spill_ab": spill_ab,
            "spill_level": spill_levels,
            **edge,
        }
        stats["cells"] += float(t * t)
    if verbose:
        print(f"[hydrology] stage 1 (local floods): {len(keys)} chunks")

    # Stage 2: global watershed spillover graph.
    def node_id(key: tuple[int, int], lab: int) -> int:
        return pairs[key] * 1_000_000 + lab  # 0 = external per tile

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
    stats["watersheds"] = float(len(level) - 1)
    if verbose:
        print(f"[hydrology] stage 2 (watershed graph): {len(level) - 1} watersheds")

    # Stage 3: raise each chunk's cells to its watershed level.
    for ci, cj in keys:
        key = (ci, cj)
        final_path = store.path("final", ci, cj, "i16.npy")
        if resume and store.done(f"final/{ci:03d}_{cj:03d}", final_path):
            continue
        labels = np.load(store.path("labels", ci, cj, "i32.npy"))
        filled = np.load(store.path("fill", ci, cj, "i16.npy")).astype(np.float64)
        out = filled.copy()
        for lab in np.unique(labels):
            if int(lab) == 0:
                continue
            lv = level.get(node_id(key, int(lab)))
            if lv is None or lv == float("-inf"):
                continue
            mask = labels == lab
            out[mask] = np.maximum(out[mask], lv)
        np.save(final_path, np.rint(out).astype(np.int16))
        store.record(f"final/{ci:03d}_{cj:03d}", final_path)
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

    flat = filled.ravel().astype(np.float64)
    level = _grade_flats_kernel(np.ascontiguousarray(filled), sea_level, eps)
    out = np.where(np.isfinite(level), np.maximum(level, flat), flat)
    return out.reshape(filled.shape).astype(np.float32)


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


def canvas_flow_fields(
    store: CanvasStore, *, sea_level: float = 0.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Assembled (filled, dem, receiver, accumulation, land, order) for
    QA/extraction.

    Applies the PF+ε flat grading before the D8 receivers so depressions have
    defined flow directions.  Memory scales with the canvas (QA/demo path):
    the D8 loop is banded and the runoff weights are tiled per coarse row, so
    beyond the six returned full-canvas arrays no whole-canvas temporaries
    remain.  ``order`` is the downstream-first (ascending filled) sort used by
    accumulation — NaN cells sort last, matching the ``nan_to_num(1e30)``
    order of previous versions without the full-size copy.
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
    # NOTE: the raw DEM is a pure return value (nothing above reads it), so it
    # loads only after the accumulation's whole-canvas allocation — the peak
    # moment for commit on large canvases.
    h, w = filled.shape
    filled = _grade_flats(filled, sea_level, 1e-3)
    rec2d = np.full((h, w), -1, dtype=np.int64)
    diag = 2**0.5
    cc = np.arange(w)[None, :]
    # Banded D8: ``best`` and the receiver candidates are band-local, so the
    # per-neighbour temporaries scale with the band, not the whole canvas
    # (the previous full-size int64 mgrid/where chain peaked > 20 GiB here).
    band_rows = max(1, min(2048, h))
    for r0 in range(0, h, band_rows):
        r1 = min(h, r0 + band_rows)
        fb = filled[r0:r1]
        best = np.zeros(fb.shape, dtype=np.float64)
        recb = np.full(fb.shape, -1, dtype=np.int64)
        rr = np.arange(r0, r1, dtype=np.int64)[:, None]
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
    land = np.isfinite(filled) & (filled > sea_level)
    rec = rec2d.reshape(-1)
    rec[~land.reshape(-1)] = -1
    # NaN sorts after every real value (same stable order nan_to_num(1e30)
    # produced) — skips a full-canvas copy per sort.
    order = np.argsort(filled.ravel(), kind="stable")
    runoff_path = store.root / "climate" / "runoff.mm.npy"
    if runoff_path.exists():
        coarse = np.nan_to_num(np.load(runoff_path).astype(np.float64), nan=0.0)
        factor = h // coarse.shape[0]
        # Tile the coarse runoff per row block: same values as
        # kron(coarse, ones(f, f))[:h, :w] without two whole-canvas temporaries.
        weight = np.zeros((h, w), dtype=np.float64)
        ncr = coarse.shape[0]
        for i in range(ncr):
            r0, r1 = i * factor, min(h, (i + 1) * factor)
            row = np.maximum(np.repeat(coarse[i], factor)[:w], 0.0) / RUNOFF_REFERENCE_MM
            weight[r0:r1] = row[None, :]
        weight[~land] = 0.0
    else:
        weight = land.astype(np.float64)
    acc = flow_accumulation(order, rec, weight.ravel()).reshape(h, w)
    dem = np.full((nrow, ncol), np.nan, dtype=np.float32)
    for ci, cj in store.chunks:
        dem[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t] = store.raw(ci, cj).astype(np.float32)
    return filled, dem, rec, acc, land, order


def run_canvas_rivers(
    store: CanvasStore,
    *,
    sea_level: float = 0.0,
    threshold_cells: int = 7000,
    verbose: bool = True,
) -> dict[str, object]:
    """Extract channel mask and vector river segments from the final fill."""
    from dreamulator.map.prog_erosion import (
        lake_mask,
        month_active_counts,
        regime_active_cells,
        river_mask,
        river_segments,
    )

    filled, dem, rec, acc, land, order = canvas_flow_fields(store, sea_level=sea_level)
    h, w = filled.shape
    t = store.tile
    weight_source = (
        "runoff.mm" if (store.root / "climate" / "runoff.mm.npy").exists() else "uniform"
    )
    rivers = river_mask(acc, land, threshold_cells)

    lake = np.zeros((h, w), dtype=bool)
    sparse_dir = store.root / "hydro" / "lakes.sparse"
    if sparse_dir.is_dir():
        for ci, cj in store.chunks:
            path = sparse_dir / f"lake.r{ci:03d}_c{cj:03d}.npz"
            if not path.exists():
                continue
            data = np.load(path)
            idx = data["idx"].astype(np.int64)
            lake[(idx // t + ci * t).astype(int), (idx % t + cj * t).astype(int)] = True
    if not lake.any() and np.isfinite(dem).any():
        filled_n = np.nan_to_num(filled, nan=0.0)
        dem_n = np.nan_to_num(dem, nan=0.0)
        lake = lake_footprint(lake_mask(filled_n, dem_n), filled_n, dem_n)

    # Monthly regime (canvas climate has runoff_monthly per the contract).
    month_active = None
    monthly_path = store.root / "climate" / "runoff_monthly.mm.npy"
    if monthly_path.exists():
        monthly = np.load(monthly_path).astype(np.float64)
        if monthly.ndim == 3:
            monthly = np.moveaxis(monthly, 0, -1)  # (12,n,n) -> (n,n,12)
            active = regime_active_cells(store.geometry.px_km)
            factor = h // monthly.shape[0]
            month_active = month_active_counts(order, rec, monthly, land, active, factor=factor)

    segs, flows, regimes = river_segments(
        rivers, rec, acc, store.geometry.px_km, lake=lake, month_active=month_active
    )
    hydro = store.root / "hydro"
    hydro.mkdir(exist_ok=True)
    np.save(hydro / "rivers.line.npy", segs.astype(np.float32))
    np.save(hydro / "rivers.flow.npy", flows.astype(np.float32))
    np.save(hydro / "rivers.regime.npy", regimes.astype(np.uint8))
    from PIL import Image

    Image.fromarray((rivers.astype(np.uint8) * 255), mode="L").save(hydro / "rivers.png")
    meta = {
        "threshold_cells": threshold_cells,
        "weight_source": weight_source,
        "km_per_px": store.geometry.px_km,
        "segments": int(len(flows)),
        "perennial": int((regimes == 0).sum()),
        "non_perennial": int((regimes == 1).sum()),
        "regime_source": "monthly-runoff" if month_active is not None else "annual-default",
    }
    (hydro / "rivers.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if verbose:
        print(
            f"[hydrology] rivers: {len(flows)} segments "
            f"({int((regimes == 0).sum())} perennial / {int((regimes == 1).sum())} non-perennial)"
        )
    return {
        "segments": float(len(flows)),
        "perennial": float((regimes == 0).sum()),
        "non_perennial": float((regimes == 1).sum()),
    }
