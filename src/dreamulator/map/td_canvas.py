"""td_canvas — continent canvases for terrain-diffusion 90 m terrain.

Geometry, layout and conditioning of the 90 m canvases that terrain-diffusion (TD)
generates continent by continent, and that downstream hydrology, window cropping and
rendering consume.  This module is the single source of the canvas coordinate conventions;
consumers import it instead of re-deriving them.

* **Projection.** Each canvas is an azimuthal-equidistant plane on the sphere of the planet's
  real radius, x east and y north in km.  Row 0 is the north edge, column 0 the west edge.
* **Grid.** ``ncell`` × ``ncell`` coarse cells of ``TD_COARSE_KM`` (the 90 m model's fixed
  conditioning scale), each split into ``PX_PER_CELL`` × ``PX_PER_CELL`` output pixels
  (about 89.8 m).  Coarse cell (i, j) covers pixels ``[256 i, 256 i + 256)`` — corner
  aligned, as upstream ``tiff_export`` writes its affine transform — and pixel (r, c) is
  centred at ``x = -half + (c + 0.5) px``, ``y = half - (r + 0.5) px``.
* **Chunks.** Generation and storage unit of ``CHUNK_CELLS`` × ``CHUNK_CELLS`` coarse cells
  (2048 px); chunk (ci, cj) covers coarse cells ``[8 ci, 8 ci + 8)``.
* **Layout.** One canvas per land group: land components of at least one chunk's area,
  largest first; a component within two buffer widths of an existing group joins it when
  the merged canvas stays under ``MAX_ANISOTROPY``.  The canvas centre is the minimax
  (smallest covering cap) centre of its land, which minimises edge distortion.  A continent
  too large for one canvas is split by author-placed ``LandCut`` discs (e.g. across an
  isthmus): land inside a disc belongs to no piece, and ownership then runs through it.  A
  disc wider than the buffer (a neck too broad for a small disc) must ``reattach``: its land
  only breaks the connectivity, then joins the nearest piece as member land, so every piece
  still generates it and the ownership line runs across the disc on land.
* **Ownership.** Where canvases overlap, a point belongs to the canvas whose member land is
  geodesically nearest (``owner_of``) — a mesh-free partition evaluated from the layout's
  land points, so every consumer resolves an overlap identically.
* **Blending.** Across an ownership line two independent generations meet; consumers blend
  them with ``blend_overlap`` (a two-band mix that keeps one side's fine detail, falling back
  to a plain linear mix where the two canvases disagree on land and sea).  Chunk files stay
  the raw generation.
"""

from __future__ import annotations

import math
import warnings
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from .models import CVTMesh

#: Coarse conditioning cell (km) of the 90 m model — fixed upstream (= terrain_refine's).
TD_COARSE_KM = 23.0
#: Output pixels per coarse cell edge — fixed upstream (tiff_export PIXELS_PER_CELL).
PX_PER_CELL = 256
#: Coarse cells per chunk edge (2048 px chunks, as in the 2026-10-16 prototype).
CHUNK_CELLS = 8
#: Generated coastal buffer around member land (km), author ruling 2026-10-18.
BUFFER_KM = 200.0
#: Edge anisotropy cap of the azimuthal-equidistant canvas (tangential / radial scale).
MAX_ANISOTROPY = 1.15
#: Coarse-channel sampling: nearest CVT cell on a grid this much finer, then block mean.
OVERSAMPLE = 4
#: Overlap blending (author rulings 2026-10-24, from the two World Island land seams): the
#: low-pass skeleton (Gaussian sigma) mixes over a wide band, the residual detail over a narrow
#: one, and a plain mix over ``BLEND_LINEAR_KM`` is used where the canvases disagree on land/sea.
#: The wide bands spread the tens-of-metres systematic offset two generations can have on flat
#: lowland, which a 23 km band left as a straight contour along the seam.  Rendering choices
#: fitted on two seams (numerical/visual, not physics).
BLEND_LOWPASS_SIGMA_KM = 15.0
BLEND_LOW_BAND_KM = 92.0
BLEND_DETAIL_BAND_KM = 4.0
BLEND_LINEAR_KM = 92.0


def unit_vectors(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    """(lat, lon) in degrees → unit vectors (..., 3), z toward the north pole."""
    la, lo = np.radians(lat_deg), np.radians(lon_deg)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def _to_latlon(v: np.ndarray) -> tuple[float, float]:
    return float(np.degrees(np.arcsin(np.clip(v[2], -1, 1)))), float(
        np.degrees(np.arctan2(v[1], v[0]))
    )


def anisotropy(angular_radius_rad: float) -> float:
    """Tangential / radial scale of the azimuthal-equidistant projection at that distance."""
    c = angular_radius_rad
    return c / math.sin(c) if c > 1e-12 else 1.0


@dataclass(frozen=True)
class CanvasGeometry:
    """Projection and pixel grid of one canvas (all conversions are vectorised)."""

    center_lat: float
    center_lon: float
    radius_km: float
    ncell: int

    @property
    def px_km(self) -> float:
        return TD_COARSE_KM / PX_PER_CELL

    @property
    def half_km(self) -> float:
        return self.ncell * TD_COARSE_KM / 2

    @property
    def size_px(self) -> int:
        return self.ncell * PX_PER_CELL

    @property
    def nchunk(self) -> int:
        return self.ncell // CHUNK_CELLS

    def xy_to_latlon(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Plane (km, y north) → (lat, lon) in degrees, lon in [-180, 180)."""
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        p0, l0 = math.radians(self.center_lat), math.radians(self.center_lon)
        rho = np.hypot(x, y)
        c = rho / self.radius_km
        safe = np.where(rho > 0, rho, 1.0)
        lat = np.arcsin(
            np.clip(np.cos(c) * math.sin(p0) + y * np.sin(c) * math.cos(p0) / safe, -1, 1)
        )
        lon = l0 + np.arctan2(
            x * np.sin(c), rho * math.cos(p0) * np.cos(c) - y * math.sin(p0) * np.sin(c)
        )
        lat = np.where(rho > 0, lat, p0)
        lon = np.where(rho > 0, lon, l0)
        return np.degrees(lat), (np.degrees(lon) + 180.0) % 360.0 - 180.0

    def latlon_to_xy(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(lat, lon) in degrees → plane (km, y north); the antipode maps to rho = pi R."""
        p, dl = np.radians(lat), np.radians(np.asarray(lon) - self.center_lon)
        p0 = math.radians(self.center_lat)
        cos_c = np.clip(math.sin(p0) * np.sin(p) + math.cos(p0) * np.cos(p) * np.cos(dl), -1, 1)
        c = np.arccos(cos_c)
        k = np.where(c > 1e-12, c / np.where(c > 1e-12, np.sin(c), 1.0), 1.0)
        x = self.radius_km * k * np.cos(p) * np.sin(dl)
        y = self.radius_km * k * (math.cos(p0) * np.sin(p) - math.sin(p0) * np.cos(p) * np.cos(dl))
        return x, y

    def pixel_to_latlon(self, row: np.ndarray, col: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Fractional pixel coordinates (centre of pixel r = r + 0.5) → (lat, lon)."""
        x = -self.half_km + np.asarray(col, dtype=np.float64) * self.px_km
        y = self.half_km - np.asarray(row, dtype=np.float64) * self.px_km
        return self.xy_to_latlon(x, y)

    def latlon_to_pixel(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(lat, lon) → fractional pixel coordinates (row, col); floor() gives the pixel."""
        x, y = self.latlon_to_xy(lat, lon)
        return (self.half_km - y) / self.px_km, (x + self.half_km) / self.px_km

    def coarse_centres_latlon(self, oversample: int = 1) -> tuple[np.ndarray, np.ndarray]:
        """(lat, lon) of the coarse-cell centres (row 0 north), optionally on a finer grid."""
        nf = self.ncell * oversample
        s = (np.arange(nf) + 0.5) / nf * 2 * self.half_km - self.half_km
        xx, yy = np.meshgrid(s, s[::-1])
        return self.xy_to_latlon(xx, yy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection": "azimuthal_equidistant",
            "center_lat": self.center_lat,
            "center_lon": self.center_lon,
            "radius_km": self.radius_km,
            "coarse_km": TD_COARSE_KM,
            "px_per_cell": PX_PER_CELL,
            "px_km": self.px_km,
            "ncell": self.ncell,
            "half_km": self.half_km,
            "size_px": self.size_px,
            "chunk_cells": CHUNK_CELLS,
            "chunk_px": CHUNK_CELLS * PX_PER_CELL,
        }


@dataclass
class CanvasPlan:
    """One canvas of the layout: geometry, member land and the chunks to generate."""

    canvas_id: str
    geometry: CanvasGeometry
    components: list[int]
    land_km2: float
    max_anisotropy: float
    chunks: list[tuple[int, int]] = field(default_factory=list)


@dataclass(frozen=True)
class LandCut:
    """A disc whose land cells are removed from the component graph (splits a continent).

    With ``reattach`` the disc's land is given back afterwards to the nearest resulting
    piece (by great-circle distance to its land cells), so the disc may exceed the buffer.
    """

    lat: float
    lon: float
    radius_km: float
    reattach: bool = False


@dataclass
class LandModel:
    """Land components of a mesh with per-cell geometry.

    ``labels`` is the component index, -1 for ocean and -2 for land inside a cut disc.
    """

    xyz: np.ndarray
    area_km2: np.ndarray
    labels: np.ndarray
    component_km2: np.ndarray
    radius_km: float
    cuts: tuple[LandCut, ...] = ()


def land_components(mesh: CVTMesh, radius_km: float, cuts: tuple[LandCut, ...] = ()) -> LandModel:
    """Label the mesh's connected land components (water_class != "ocean")."""
    cells = mesh.cells
    n = len(cells)
    xyz = unit_vectors(np.array([c.lat for c in cells]), np.array([c.lon for c in cells]))
    area = np.array([c.area_km2 for c in cells], dtype=np.float64)
    is_land = np.array([c.water_class != "ocean" for c in cells])
    in_cut = np.zeros(n, dtype=bool)
    in_reattach = np.zeros(n, dtype=bool)
    for cut in cuts:
        v = unit_vectors(np.array(cut.lat), np.array(cut.lon))
        disc = np.arccos(np.clip(xyz @ v, -1, 1)) * radius_km <= cut.radius_km
        in_cut |= disc
        if cut.reattach:
            in_reattach |= disc
    land = is_land & ~in_cut
    labels = np.where(is_land & in_cut, -2, -1).astype(np.int64)
    k = 0
    for s in np.nonzero(land)[0]:
        if labels[s] >= 0:
            continue
        labels[s] = k
        q = deque([int(s)])
        while q:
            i = q.popleft()
            for j in cells[i].neighbors:
                if land[j] and labels[j] < 0:
                    labels[j] = k
                    q.append(j)
        k += 1
    back = is_land & in_reattach
    if back.any() and land.any():
        from scipy.spatial import cKDTree

        donors = np.nonzero(land)[0]
        _, j = cKDTree(xyz[donors]).query(xyz[back])
        labels[back] = labels[donors[j]]
        land = land | back
    sizes = np.bincount(labels[land], weights=area[land], minlength=k)
    return LandModel(xyz, area, labels, sizes, radius_km, tuple(cuts))


def minimax_centre(points: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, float]:
    """Centre of the smallest spherical cap covering ``points`` and its angular radius.

    Nelder–Mead on (lat, lon) from a few starts around the weighted centroid (the cap
    radius is a non-smooth max, which the simplex handles); deterministic.
    """
    from scipy.optimize import minimize

    v = (points * weights[:, None]).sum(0)
    v /= np.linalg.norm(v)

    def reach(p: np.ndarray) -> float:
        u = unit_vectors(np.degrees(p[0]), np.degrees(p[1]))
        return float(np.arccos(np.clip(points @ u, -1, 1)).max())

    lat0, lon0 = math.asin(v[2]), math.atan2(v[1], v[0])
    starts = [(lat0 + a, lon0 + b) for a in (-0.2, 0.0, 0.2) for b in (-0.3, 0.0, 0.3)]
    best = min(
        (
            minimize(
                reach, np.array(s), method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-8}
            )
            for s in starts
        ),
        key=lambda r: (r.fun, tuple(r.x)),
    )
    return unit_vectors(np.degrees(best.x[0]), np.degrees(best.x[1])), float(best.fun)


def _gap_km(a: np.ndarray, b: np.ndarray, radius_km: float) -> float:
    from scipy.spatial import cKDTree

    d, _ = cKDTree(a).query(b)
    return float(2 * radius_km * math.asin(min(1.0, float(d.min()) / 2)))


def plan_layout(
    land: LandModel,
    *,
    buffer_km: float = BUFFER_KM,
    max_anisotropy: float = MAX_ANISOTROPY,
    names: dict[int, str] | None = None,
    joins: dict[int, int] | None = None,
) -> tuple[list[CanvasPlan], list[int]]:
    """Group land components into canvases; returns (plans, components over the cap).

    Components smaller than one chunk get no canvas (they are generated only where they
    fall inside some canvas's buffer).  A group whose single component already exceeds
    ``max_anisotropy`` is still planned, and reported in the second return value so the
    caller can refuse it or ask for a split.  ``joins`` maps a component to the (larger)
    component whose group it must join regardless of the gap rule (an author override, e.g.
    for an island just beyond the merge distance).
    """
    if any(c.radius_km > buffer_km and not c.reattach for c in land.cuts):
        # cut land must lie inside both pieces' buffers, or nobody generates it
        raise ValueError(f"cut radius exceeds the {buffer_km:g} km buffer")
    chunk_km2 = (CHUNK_CELLS * TD_COARSE_KM) ** 2
    r = land.radius_km
    order = [int(c) for c in np.argsort(-land.component_km2, kind="stable")]
    order = [c for c in order if land.component_km2[c] >= chunk_km2]
    groups: list[list[int]] = []
    centres: list[tuple[np.ndarray, float]] = []
    joins = joins or {}
    for c in order:
        pc = land.xyz[land.labels == c]
        joined = False
        target = joins.get(c)
        if target is not None:
            for g, members in enumerate(groups):
                if target in members:
                    members.append(c)
                    m = np.isin(land.labels, members)
                    centres[g] = minimax_centre(land.xyz[m], land.area_km2[m])
                    joined = True
                    break
        if joined:
            continue
        for g, members in enumerate(groups):
            pg = land.xyz[np.isin(land.labels, members)]
            if _gap_km(pg, pc, r) > 2 * buffer_km:
                continue
            m = np.isin(land.labels, [*members, c])
            u, reach = minimax_centre(land.xyz[m], land.area_km2[m])
            if anisotropy(reach + buffer_km / r) <= max_anisotropy:
                members.append(c)
                centres[g] = (u, reach)
                joined = True
                break
        if not joined:
            m = land.labels == c
            groups.append([c])
            centres.append(minimax_centre(land.xyz[m], land.area_km2[m]))

    plans, over = [], []
    for members, (u, reach) in zip(groups, centres, strict=True):
        lat0, lon0 = _to_latlon(u)
        half = reach * r + buffer_km
        ncell = 2 * CHUNK_CELLS * math.ceil(half / (TD_COARSE_KM * CHUNK_CELLS))
        geom = CanvasGeometry(round(lat0, 6), round(lon0, 6), r, ncell)
        aniso = anisotropy(reach + buffer_km / r)
        if aniso > max_anisotropy:
            over.extend(members)
        head = members[0]
        cid = (names or {}).get(head) or f"land_{lat0:+05.1f}_{lon0:+06.1f}".replace(".", "p")
        m = np.isin(land.labels, members)
        plan = CanvasPlan(cid, geom, members, float(land.area_km2[m].sum()), aniso)
        plan.chunks = chunks_near_land(geom, land.xyz[m], buffer_km)
        plans.append(plan)
    return plans, over


def chunks_near_land(
    geom: CanvasGeometry, land_xyz: np.ndarray, buffer_km: float
) -> list[tuple[int, int]]:
    """Chunks (row-major) with any coarse-cell centre within ``buffer_km`` of the land."""
    from scipy.spatial import cKDTree

    la, lo = geom.coarse_centres_latlon()
    d, _ = cKDTree(land_xyz).query(unit_vectors(la, lo).reshape(-1, 3))
    dist = 2 * geom.radius_km * np.arcsin(np.clip(d / 2, 0, 1))
    near = (dist <= buffer_km).reshape(geom.ncell, geom.ncell)
    nch = geom.nchunk
    want = near.reshape(nch, CHUNK_CELLS, nch, CHUNK_CELLS).any(axis=(1, 3))
    return [(int(i), int(j)) for i, j in zip(*np.nonzero(want), strict=True)]


def owner_of(
    lat: np.ndarray, lon: np.ndarray, owner_points: np.ndarray, owner_canvas: np.ndarray
) -> np.ndarray:
    """Index of the owning canvas for each point: the canvas of the nearest member land.

    ``owner_points`` (n, 3) are the unit vectors of every canvas's member-land cells and
    ``owner_canvas`` (n,) their canvas index — the layout's ``owner_points.npy`` table.
    """
    from scipy.spatial import cKDTree

    _, idx = cKDTree(owner_points).query(unit_vectors(lat, lon).reshape(-1, 3))
    return np.asarray(np.asarray(owner_canvas)[idx]).reshape(np.shape(lat))


def blend_weight(dist_a_km: np.ndarray, dist_b_km: np.ndarray, band_km: float) -> np.ndarray:
    """Weight of canvas A across its ownership line with B (1 = A, 0 = B); band 0 = hard.

    A smoothstep (3t² − 2t³) of the distance difference across the band, not a linear ramp:
    its slope vanishes at both band edges, so a systematic height offset between the two
    generations does not leave a crease (a straight slope break) along the band edge.
    """
    if band_km <= 0:
        return (np.asarray(dist_a_km) <= np.asarray(dist_b_km)).astype(np.float64)
    t = np.clip(0.5 + (dist_b_km - dist_a_km) / (2.0 * band_km), 0.0, 1.0)
    return np.asarray(t * t * (3.0 - 2.0 * t))


def blend_overlap(
    h_a: np.ndarray,
    h_b: np.ndarray,
    dist_a_km: np.ndarray,
    dist_b_km: np.ndarray,
    px_km: float,
    *,
    sea_level_m: float = 0.0,
) -> np.ndarray:
    """Blend two canvases' heights on one common grid across their ownership line (pure).

    ``h_a``, ``h_b`` are the two generations resampled onto the same (rows, cols) grid of
    ``px_km`` pixels; ``dist_*_km`` the great-circle distances of each pixel to each canvas's
    member land (the ``owner_points`` table).  Each height splits into a Gaussian low-pass
    skeleton (``BLEND_LOWPASS_SIGMA_KM``) and the residual detail; the skeleton mixes over
    ``BLEND_LOW_BAND_KM``, the detail over ``BLEND_DETAIL_BAND_KM``, so the step vanishes and
    the texture is one canvas's, not an average of two uncorrelated ones.  Where the two
    disagree on land and sea inside the low band (grown by one coarse cell) a plain linear mix
    over ``BLEND_LINEAR_KM`` takes over, with one coarse cell of smooth hand-over, so the hard
    detail switch cannot cut a straight coastline.  NaN in either input falls back to the
    other.
    """
    from scipy.ndimage import binary_dilation, gaussian_filter

    a = np.asarray(h_a, dtype=np.float64)
    b = np.asarray(h_b, dtype=np.float64)
    a, b = np.where(np.isnan(a), b, a), np.where(np.isnan(b), a, b)
    if np.isnan(a).all():
        return a
    fill = float(np.nanmean(a))
    a0, b0 = np.nan_to_num(a, nan=fill), np.nan_to_num(b, nan=fill)
    sigma = BLEND_LOWPASS_SIGMA_KM / px_km
    low_a, low_b = gaussian_filter(a0, sigma), gaussian_filter(b0, sigma)
    w_low = blend_weight(dist_a_km, dist_b_km, BLEND_LOW_BAND_KM)
    w_det = blend_weight(dist_a_km, dist_b_km, BLEND_DETAIL_BAND_KM)
    two_band = (
        w_low * low_a + (1 - w_low) * low_b + w_det * (a0 - low_a) + (1 - w_det) * (b0 - low_b)
    )
    w_lin = blend_weight(dist_a_km, dist_b_km, BLEND_LINEAR_KM)
    linear = w_lin * a0 + (1 - w_lin) * b0
    band = np.abs(np.asarray(dist_a_km) - np.asarray(dist_b_km)) <= BLEND_LOW_BAND_KM
    disagree = band & ((a0 > sea_level_m) != (b0 > sea_level_m))
    cell_px = max(1, round(TD_COARSE_KM / px_km))
    disagree = binary_dilation(disagree, iterations=cell_px)
    mix = np.clip(gaussian_filter(disagree.astype(np.float64), cell_px / 2.0) * 2.0, 0.0, 1.0)
    out = (1 - mix) * two_band + mix * linear
    return np.asarray(np.where(np.isnan(a), np.nan, out))


def sample_mesh_field(
    geom: CanvasGeometry,
    values_per_cell: np.ndarray,
    cell_xyz: np.ndarray,
    *,
    categorical: bool = False,
    oversample: int = OVERSAMPLE,
) -> np.ndarray:
    """Sample a per-CVT-cell column onto the canvas coarse grid (ncell, ncell), row 0 north.

    The conditioning recipe: nearest cell on an ``oversample``-times finer grid, then the
    block mean (NaN-aware, so ocean-NaN land fields keep coastal land values).  Categorical
    columns take the nearest cell at each coarse-cell centre instead.  ``values_per_cell``
    may carry trailing axes (e.g. (n, 12) monthly); they come out leading: (12, ncell, ncell).
    ``cell_xyz`` are the cells' unit vectors (``unit_vectors``, z north).
    """
    from scipy.spatial import cKDTree

    tree = cKDTree(cell_xyz)
    n = geom.ncell
    vals = np.asarray(values_per_cell)
    if categorical:
        la, lo = geom.coarse_centres_latlon()
        _, idx = tree.query(unit_vectors(la, lo).reshape(-1, 3))
        return np.asarray(vals[idx]).reshape(n, n)
    la, lo = geom.coarse_centres_latlon(oversample)
    _, idx = tree.query(unit_vectors(la, lo).reshape(-1, 3))
    fine = vals[idx].astype(np.float64)  # (nf*nf, ...)
    fine = np.moveaxis(fine, 0, -1).reshape(*vals.shape[1:], n, oversample, n, oversample)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN blocks stay NaN
        return np.asarray(np.nanmean(fine, axis=(-3, -1)))
