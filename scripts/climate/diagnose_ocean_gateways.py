#!/usr/bin/env python3
"""Sea-level-sensitive ocean gateways (straits and land bridges) on a CVT mesh.

Finds the straits whose sill lies inside a sea-level window, so that a plausible
sea-level change opens, closes or chokes them.  Two kinds are reported:

* **separator** — the only connection of a water body to the world ocean.  Found by
  flooding the whole mesh from the deepest cell upward (union-find over cells
  sorted by elevation): when two water bodies that are both at least
  ``--min-area`` large first merge, the merge elevation is the sill.  Below the
  sill the smaller body is cut off.
* **shortcut** — the two sides stay connected the long way round, and closing the
  strait only forces a detour.  Found by flooding local windows
  (``--window-km``) around shallow cells, then comparing the ocean path between the
  two sides through the whole mesh with the strait open (sea level 0, or just
  above a positive sill) and closed (just below the sill).  Kept when the detour
  adds at least ``--min-detour-km``.

Per gateway the report gives the sill (m, relative to the current sea level; a
positive sill is a land bridge that floods when the sea rises), the location,
the size of the cut-off body or the detour ratio, and a channel-width estimate at
several sea levels: the ocean area within ``R_WIDTH_KM`` of the sill divided by
``2 R_WIDTH_KM`` (valid for widths below about 2 R; cells narrower than the mesh
spacing are not resolved).

Caveat: sill depths inherit the terrain pipeline's shelf profile.  On a coarse
mesh the first ocean ring next to a coast sits at one depth (about -30 m at the
default 200k-cell nacrea mesh), so many narrow straits share that sill.

Outputs ``gateways.json`` and, with ``--plot``, ``gateways_map.png`` into
``--out-dir``.

Usage::

    uv run python scripts/climate/diagnose_ocean_gateways.py \
        data/worlds/nacrea/maps/satellite_nacrea --out-dir /tmp/gateways --plot
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model

if TYPE_CHECKING:
    from collections.abc import Callable

R_WIDTH_KM = 110.0
WIDTH_LEVELS_M = (-150, -120, -90, -60, -30, 0, 20, 50)


@dataclass
class Gateway:
    kind: str  # "separator" | "shortcut"
    cell: int
    lon: float
    lat: float
    sill_m: float
    feature: str = ""
    cut_off_km2: float | None = None  # separator: area of the smaller body
    cut_off_centroid: list[float] | None = None  # separator: [lon, lat]
    path_open_km: float | None = None  # shortcut
    path_closed_km: float | None = None
    detour_ratio: float | None = None
    width_km: dict[str, int] = field(default_factory=dict)


class Mesh:
    """Flat arrays of the cell fields this diagnostic needs."""

    def __init__(self, path: Path) -> None:
        mesh = load_cvt_mesh_model(path)
        cells = mesh.cells
        self.n = len(cells)
        self.z = np.array([c.elevation for c in cells])
        self.area = np.array([c.area_km2 for c in cells])
        self.lon = np.array([c.lon for c in cells])
        self.lat = np.array([c.lat for c in cells])
        la, lo = np.radians(self.lat), np.radians(self.lon)
        self.xyz = np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])
        self.nbrs = [list(c.neighbors) for c in cells]
        # the cell areas tile the sphere, so they fix the radius without metadata
        self.radius_km = float(np.sqrt(self.area.sum() / (4 * np.pi)))
        self.spacing_km = float(np.sqrt(np.median(self.area)))
        rows = np.repeat(np.arange(self.n), [len(nb) for nb in self.nbrs])
        cols = np.fromiter((j for nb in self.nbrs for j in nb), dtype=np.int64, count=len(rows))
        dots = np.clip(np.einsum("ij,ij->i", self.xyz[rows], self.xyz[cols]), -1.0, 1.0)
        self.rows, self.cols = rows, cols
        self.edge_km = self.radius_km * np.arccos(dots)

    def dist_km(self, i: int) -> np.ndarray:
        d: np.ndarray = self.radius_km * np.arccos(np.clip(self.xyz @ self.xyz[i], -1.0, 1.0))
        return d

    def ocean_path_km(self, level: float, a: int, b: int) -> float:
        """Shortest ocean path (km) between cells a and b with the sea at ``level``."""
        wet = self.z < level
        keep = wet[self.rows] & wet[self.cols]
        g = csr_matrix(
            (self.edge_km[keep], (self.rows[keep], self.cols[keep])), shape=(self.n, self.n)
        )
        return float(dijkstra(g, indices=a, min_only=True)[b])

    def width_km(self, i: int) -> dict[str, int]:
        ring = self.dist_km(i) < R_WIDTH_KM
        return {
            str(lv): round(float(self.area[ring & (self.z < lv)].sum()) / (2 * R_WIDTH_KM))
            for lv in WIDTH_LEVELS_M
        }


def _find(parent: np.ndarray, i: int) -> int:
    root = i
    while parent[root] != root:
        root = parent[root]
    while parent[i] != root:
        parent[i], i = root, parent[i]
    return root


def _flood(
    m: Mesh,
    cells: np.ndarray,
    zmin: float,
    zmax: float,
    min_area: float,
    on_merge: Callable[[int, int, int, np.ndarray, np.ndarray, np.ndarray], None],
) -> None:
    """Flood ``cells`` upward to ``zmax``; call ``on_merge`` for qualifying merges.

    ``on_merge(cell, small, big, area, deepest, xyz_sum)`` receives local component
    indices; ``deepest`` holds the deepest global cell of each component and
    ``xyz_sum`` the area-weighted position sum.
    """
    local = {int(k): t for t, k in enumerate(cells)}
    parent = np.arange(len(cells))
    area = m.area[cells].copy()
    deepest = cells.copy()
    xyz_sum = m.xyz[cells] * area[:, None]
    active = np.zeros(len(cells), dtype=bool)
    for t in np.argsort(m.z[cells], kind="stable"):
        zc = m.z[cells[t]]
        if zc > zmax:
            break
        active[t] = True
        for j in sorted(
            (local[j] for j in m.nbrs[cells[t]] if j in local and active[local[j]]),
            key=lambda u: -area[_find(parent, u)],
        ):
            ri, rj = _find(parent, int(t)), _find(parent, j)
            if ri == rj:
                continue
            small, big = (ri, rj) if area[ri] < area[rj] else (rj, ri)
            if zc >= zmin and area[small] >= min_area:
                on_merge(int(cells[t]), small, big, area, deepest, xyz_sum)
            parent[small] = big
            area[big] += area[small]
            xyz_sum[big] += xyz_sum[small]
            if m.z[deepest[small]] < m.z[deepest[big]]:
                deepest[big] = deepest[small]


def _lonlat(v: np.ndarray) -> list[float]:
    v = v / np.linalg.norm(v)
    return [
        round(float(np.degrees(np.arctan2(v[1], v[0]))), 1),
        round(float(np.degrees(np.arcsin(v[2]))), 1),
    ]


def find_separators(m: Mesh, zmin: float, zmax: float, min_area: float) -> list[Gateway]:
    out: list[Gateway] = []

    def on_merge(
        c: int, small: int, big: int, area: np.ndarray, _d: np.ndarray, xs: np.ndarray
    ) -> None:
        out.append(
            Gateway(
                kind="separator",
                cell=c,
                lon=round(float(m.lon[c]), 2),
                lat=round(float(m.lat[c]), 2),
                sill_m=round(float(m.z[c]), 1),
                cut_off_km2=round(float(area[small])),
                cut_off_centroid=_lonlat(xs[small]),
                width_km=m.width_km(c),
            )
        )

    _flood(m, np.arange(m.n), zmin, zmax, min_area, on_merge)
    return out


def find_shortcuts(
    m: Mesh, zmin: float, zmax: float, window_km: float, min_side_km2: float, min_detour_km: float
) -> list[Gateway]:
    # window centres: shallow cells, thinned greedily (shallowest first)
    shallow = np.nonzero((m.z > zmin) & (m.z < zmax))[0]
    taken = np.zeros(m.n, dtype=bool)
    centres = []
    for i in shallow[np.argsort(m.z[shallow])]:
        if not taken[i]:
            centres.append(int(i))
            taken |= m.dist_km(int(i)) < 0.3 * window_km

    merges: list[tuple[int, float, int, int]] = []
    for c in centres:
        win = np.nonzero(m.dist_km(c) < window_km)[0]

        def on_merge(
            cell: int, small: int, big: int, area: np.ndarray, deep: np.ndarray, _x: np.ndarray
        ) -> None:
            merges.append((cell, float(area[small]), int(deep[small]), int(deep[big])))

        _flood(m, win, zmin, zmax, min_side_km2, on_merge)

    # one gateway per cluster: the merge with the largest smaller side
    merges.sort(key=lambda t: -t[1])
    kept: list[tuple[int, float, int, int]] = []
    for mg in merges:
        if all(m.dist_km(mg[0])[k[0]] > 0.5 * window_km for k in kept):
            kept.append(mg)

    out: list[Gateway] = []
    for cell, _a, da, db in kept:
        sill = float(m.z[cell])
        d_open = m.ocean_path_km(max(0.0, sill + 1.0), da, db)
        d_closed = m.ocean_path_km(sill - 1.0, da, db)
        if math.isinf(d_open) or math.isinf(d_closed) or d_closed - d_open < min_detour_km:
            continue  # unconnected or minor; separators come from the global flood
        out.append(
            Gateway(
                kind="shortcut",
                cell=cell,
                lon=round(float(m.lon[cell]), 2),
                lat=round(float(m.lat[cell]), 2),
                sill_m=round(sill, 1),
                path_open_km=round(d_open),
                path_closed_km=round(d_closed),
                detour_ratio=round(d_closed / d_open, 1),
                width_km=m.width_km(cell),
            )
        )
    return out


def name_features(m: Mesh, gateways: list[Gateway], geography: Path | None) -> None:
    """Tag each gateway with the nearest geography.yaml feature covering it (if any)."""
    if geography is None or not geography.exists():
        return
    feats = yaml.safe_load(geography.read_text(encoding="utf-8")).get("features", []) or []
    for g in gateways:
        p = np.radians([g.lat, g.lon])
        v = np.array(
            [math.cos(p[0]) * math.cos(p[1]), math.cos(p[0]) * math.sin(p[1]), math.sin(p[0])]
        )
        best, bd = "", math.inf
        for f in feats:
            q = np.radians([f["lat"], f["lon"]])
            w = np.array(
                [math.cos(q[0]) * math.cos(q[1]), math.cos(q[0]) * math.sin(q[1]), math.sin(q[0])]
            )
            d = m.radius_km * math.acos(min(1.0, float(v @ w)))
            reach = math.radians(f.get("radius_deg", 1.0)) * m.radius_km + 250.0
            if d < reach and d < bd:
                best, bd = str(f.get("name", "")), d
        g.feature = best


def plot(m: Mesh, gateways: list[Gateway], window_m: float, label_top: int, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PathCollection

    fig, ax = plt.subplots(figsize=(16, 8.6), dpi=130)
    bg = "#fcfcfb"
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    z = m.z
    layers: list[tuple[Any, str, str]] = [
        (z < -window_m, "#e4ebf2", "ocean"),
        ((z >= -window_m) & (z < 0), "#3987e5", f"shelf exposed by a {window_m:.0f} m fall"),
        ((z >= 0) & (z < window_m), "#eb6834", f"lowland flooded by a {window_m:.0f} m rise"),
        (z >= window_m, "#d6d3c9", "land"),
    ]
    for mask, col, lab in layers:
        ax.scatter(
            m.lon[mask],
            m.lat[mask],
            s=1.1,
            c=col,
            marker="s",
            linewidths=0,
            label=lab,
            rasterized=True,
        )
    # Label the most significant half-and-half (largest cut-off bodies, largest added
    # detours); the rest are small dots.  Numbers match the printed table / JSON order.
    seps = sorted(
        (k for k, g in enumerate(gateways) if g.cut_off_km2 is not None),
        key=lambda k: -(gateways[k].cut_off_km2 or 0.0),
    )
    cuts = sorted(
        (k for k, g in enumerate(gateways) if g.cut_off_km2 is None),
        key=lambda k: -((gateways[k].path_closed_km or 0.0) - (gateways[k].path_open_km or 0.0)),
    )
    labeled = set(seps[: (label_top + 1) // 2] + cuts[: label_top // 2])
    others = [g for k, g in enumerate(gateways) if k not in labeled]
    ax.scatter(
        [g.lon for g in others],
        [g.lat for g in others],
        s=14,
        facecolor="#1f1f1d",
        linewidths=0,
        zorder=4,
        label="other gateways (see table)",
    )
    for k, g in enumerate(gateways, 1):
        if k - 1 not in labeled:
            continue
        if g.cut_off_km2 is not None:
            text = f"{g.sill_m:+.0f} m, cuts off {g.cut_off_km2 / 1e6:.1f} M km²"
        else:
            text = f"{g.sill_m:+.0f} m, detour ×{g.detour_ratio:.0f}"
        ax.scatter(
            [g.lon], [g.lat], s=150, facecolor=bg, edgecolor="#1f1f1d", linewidth=1.6, zorder=5
        )
        ax.text(
            g.lon,
            g.lat,
            str(k),
            ha="center",
            va="center",
            fontsize=7.5,
            weight="bold",
            color="#1f1f1d",
            zorder=6,
        )
        ax.annotate(
            text,
            (g.lon, g.lat),
            xytext=(7, 7),
            textcoords="offset points",
            fontsize=8.5,
            color="#3b3b38",
            zorder=6,
            bbox=dict(boxstyle="round,pad=0.15", fc="#fcfcfbcc", ec="none"),
        )
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_xticks(range(-180, 181, 30))
    ax.set_yticks(range(-90, 91, 30))
    ax.tick_params(colors="#6b6a64", labelsize=8)
    for s in ax.spines.values():
        s.set_color("#c9c7bd")
    ax.grid(color="#c9c7bd", lw=0.4, alpha=0.6)
    ax.set_title(
        "Sea-level-sensitive gateways: sill depth and type "
        "(separator = only outlet; shortcut = detour factor when closed)",
        fontsize=12,
        color="#1f1f1d",
        loc="left",
    )
    lg = ax.legend(loc="lower left", markerscale=9, fontsize=9, facecolor=bg, edgecolor="#c9c7bd")
    dot = lg.legend_handles[-1]
    if isinstance(dot, PathCollection):
        dot.set_sizes([14])  # the gateway dot keeps its map size
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mesh", type=Path, help="mesh file or map directory (maps/<planet>)")
    ap.add_argument("--out-dir", type=Path, default=Path("."))
    ap.add_argument(
        "--geography", type=Path, help="geography.yaml for feature names (auto-detected)"
    )
    ap.add_argument("--zmin", type=float, default=-150.0, help="lowest sill considered (m)")
    ap.add_argument("--zmax", type=float, default=50.0, help="highest sill considered (m)")
    ap.add_argument("--min-area", type=float, default=1e5, help="separator: min cut-off area (km²)")
    ap.add_argument("--window-km", type=float, default=400.0, help="shortcut: local flood radius")
    ap.add_argument(
        "--min-side-km2", type=float, default=2.5e4, help="shortcut: min local side area"
    )
    ap.add_argument("--min-detour-km", type=float, default=2500.0, help="shortcut: min added path")
    ap.add_argument("--plot", action="store_true", help="also write gateways_map.png")
    ap.add_argument(
        "--shade-m", type=float, default=45.0, help="map: shade shelf/lowland within ±this"
    )
    ap.add_argument("--label-top", type=int, default=14, help="map: label this many gateways")
    a = ap.parse_args()

    mesh_path = a.mesh if a.mesh.is_file() else find_mesh_file(a.mesh)
    if mesh_path is None:
        raise SystemExit(f"no mesh file under {a.mesh}")
    geography = a.geography
    if geography is None:
        # maps/<planet>/ → world root → layers/geological/input/geography.yaml
        for parent in Path(mesh_path).resolve().parents:
            cand = parent / "layers/geological/input/geography.yaml"
            if cand.exists():
                geography = cand
                break

    m = Mesh(Path(mesh_path))
    print(
        f"{m.n} cells, spacing {m.spacing_km:.0f} km, sill window [{a.zmin:+.0f}, {a.zmax:+.0f}] m"
    )
    seps = find_separators(m, a.zmin, a.zmax, a.min_area)
    cuts = find_shortcuts(m, a.zmin, a.zmax, a.window_km, a.min_side_km2, a.min_detour_km)
    # a shortcut on top of a separator is the same strait
    cuts = [c for c in cuts if all(m.dist_km(c.cell)[s.cell] > 0.5 * a.window_km for s in seps)]
    gateways = sorted(seps + cuts, key=lambda g: g.sill_m)
    name_features(m, gateways, geography)

    a.out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "mesh": str(mesh_path),
        "spacing_km": round(m.spacing_km, 1),
        "gateways": [asdict(g) for g in gateways],
    }
    (a.out_dir / "gateways.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for k, g in enumerate(gateways, 1):
        if g.cut_off_km2 is not None:
            extra = f"cuts off {g.cut_off_km2 / 1e6:.2f} M km² at {g.cut_off_centroid}"
        else:
            extra = f"detour {g.path_open_km:.0f} -> {g.path_closed_km:.0f} km (×{g.detour_ratio})"
        where = f"{g.lon:8.2f} {g.lat:7.2f}"
        print(f"{k:3d} {g.kind:9s} {where} sill {g.sill_m:+7.1f} m  {extra}  {g.feature}")
    if a.plot:
        plot(m, gateways, a.shade_m, a.label_top, a.out_dir / "gateways_map.png")
        print(f"wrote {a.out_dir / 'gateways_map.png'}")


if __name__ == "__main__":
    main()
