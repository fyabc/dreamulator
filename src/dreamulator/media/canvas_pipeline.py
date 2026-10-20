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
