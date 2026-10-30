"""Marine boundary of canvas ice: connected sea, channel width and grounding.

Sea water exists only where pixels at or below sea level connect to the
geological ocean. Sub-sea-level pixels without that connection are dry
inland lows; under an ice sheet they are part of the grounded bed.
Ice in sea water is grounded when its thickness exceeds the floatation
thickness rho_w / rho_i times the water depth (Cuffey & Paterson 2010,
ch. 11; PISM floatation criterion). Floating ice is not retained here:
ice shelves need their own stress balance.

Connectivity runs out of core over storage chunks. Each chunk labels its
4-connected water once; a union-find over shared chunk edges joins labels,
and a second pass maps the same deterministic labels to the result.
Four-connectivity keeps water from crossing a diagonal land corner.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.ndimage import distance_transform_edt, label

from .canvas_ice_surface import SECONDS_PER_YEAR, TEMPERATE_RATE_FACTOR_PA3_S
from .ice_sheets import RHO_ICE_KG_M3, RHO_SEAWATER_KG_M3

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

ChunkKey = tuple[int, int]
FLOATATION_RATIO = RHO_SEAWATER_KG_M3 / RHO_ICE_KG_M3


def grounded_ice(ice_m: np.ndarray, bed_m: np.ndarray) -> np.ndarray:
    """Return where ice rests on its bed rather than floating in sea water.

    A bed at or above sea level always supports the ice. A sub-sea-level bed
    supports it once the column outweighs the displaced water. Callers pass
    only marine pixels; inland lows hold no sea water to float on.
    """
    ice = np.asarray(ice_m, dtype=float)
    bed = np.asarray(bed_m, dtype=float)
    if ice.shape != bed.shape or np.any(ice < 0):
        raise ValueError("ice thickness must be nonnegative and aligned with the bed")
    return np.asarray((bed >= 0) | (ice >= FLOATATION_RATIO * np.maximum(-bed, 0)))


def channel_fill_fraction(
    mean_ice_m: np.ndarray,
    depth_below_surface_m: np.ndarray,
    width_m: np.ndarray,
    *,
    elapsed_yr: float,
    gravity_m_s2: float,
) -> np.ndarray:
    """Single-mode SIA infill of an unresolved channel below the ice surface.

    A channel of width w is half a wavelength, k = pi / w, and its surface
    deficit d is a cosine of amplitude d / 2. This is the closure of
    ``subgrid_ice_relaxation_fraction`` evaluated at the channel's own
    wavenumber: the retained deficit is (1 + 3 C H^5 k^4 sigma^2 t)^(-1/2),
    with sigma^2 = d^2 / 8. Narrow channels beside thick ice close; open
    water at the resolved scale (infinite width) receives nothing.
    """
    coefficient = 2.0 / 5.0 * TEMPERATE_RATE_FACTOR_PA3_S * (RHO_ICE_KG_M3 * gravity_m_s2) ** 3
    width = np.asarray(width_m, dtype=float)
    wavenumber = np.divide(np.pi, width, out=np.zeros_like(width), where=np.isfinite(width))
    response = (
        3
        * coefficient
        * np.asarray(mean_ice_m, dtype=float) ** 5
        * wavenumber**4
        * np.asarray(depth_below_surface_m, dtype=float) ** 2
        / 8
        * elapsed_yr
        * SECONDS_PER_YEAR
    )
    return np.asarray(1 - 1 / np.sqrt(1 + response))


def water_width_px(water: np.ndarray, max_radius_px: int) -> np.ndarray:
    """Local width of each water pixel, as the widest inscribed disc covering it.

    D is the Euclidean distance from a water pixel centre to the nearest dry
    centre. A disc of integer radius r around a centre with D >= r stays in
    water and spans 2 r - 1 pixels. The width of a pixel is the largest such
    span that covers it (morphological local thickness, Hildebrand &
    Ruegsegger 1997). Pixels in discs of radius max_radius_px are reported
    as infinite: wider water belongs to the resolved scale. Dry pixels are 0.
    """
    wet = np.asarray(water, dtype=bool)
    if wet.ndim != 2 or max_radius_px < 1:
        raise ValueError("water must be a 2D mask and the radius cap positive")
    width = np.zeros(wet.shape)
    if not wet.any():
        return width
    distance = distance_transform_edt(wet)
    for radius in range(1, max_radius_px + 1):
        centres = distance >= radius
        if not centres.any():
            break
        covered = distance_transform_edt(~centres) < radius
        width[covered & wet] = np.inf if radius == max_radius_px else 2 * radius - 1
    return width


@dataclass(frozen=True)
class SeaConnectivity:
    """Global sea membership of each chunk's deterministic water labels."""

    offsets: dict[ChunkKey, int]
    marine: np.ndarray

    def mask(self, key: ChunkKey, water: np.ndarray) -> np.ndarray:
        """Sea pixels of a chunk, from the same water mask used to connect it."""
        labels, _ = label(np.asarray(water, dtype=bool))
        ids = np.where(labels > 0, labels + self.offsets[key], 0)
        return np.asarray(self.marine[ids])


def connect_sea(
    keys: Iterable[ChunkKey],
    read: Callable[[ChunkKey], tuple[np.ndarray, np.ndarray]],
    *,
    workers: int = 8,
) -> SeaConnectivity:
    """Join sub-sea-level water across chunks and mark what reaches the ocean.

    ``read`` returns a chunk's water mask and its ocean seed mask; seeds lie
    in water known to be open sea, such as geological ocean cells. Chunks
    share edges with their row and column neighbours; absent neighbours
    contribute nothing. The result is independent of worker scheduling.
    """
    ordered = sorted(set(keys))
    borders: dict[ChunkKey, tuple[np.ndarray, ...]] = {}
    seeded: dict[ChunkKey, np.ndarray] = {}
    counts: dict[ChunkKey, int] = {}

    def first(key: ChunkKey) -> tuple[ChunkKey, int, np.ndarray, tuple[np.ndarray, ...]]:
        water, seed = (np.asarray(a, dtype=bool) for a in read(key))
        if water.shape != seed.shape or water.ndim != 2:
            raise ValueError("water and seed masks must share a 2D chunk")
        labels, count = label(water)
        hit = np.zeros(count + 1, bool)
        hit[labels[water & seed]] = True
        edges = (labels[0].copy(), labels[-1].copy(), labels[:, 0].copy(), labels[:, -1].copy())
        return key, count, hit, edges

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, count, hit, edges in pool.map(first, ordered):
            counts[key], seeded[key], borders[key] = count, hit, edges
    offsets, total = {}, 0
    for key in ordered:
        offsets[key] = total
        total += counts[key]
    parent = np.arange(total + 1)

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = int(parent[root])
        while parent[x] != root:
            parent[x], x = root, int(parent[x])
        return root

    for key in ordered:
        ci, cj = key
        top, bottom, left, right = borders[key]
        for other, mine, theirs in (((ci + 1, cj), bottom, 0), ((ci, cj + 1), right, 2)):
            if other not in borders:
                continue
            a = np.where(mine > 0, mine + offsets[key], 0)
            b = np.where(borders[other][theirs] > 0, borders[other][theirs] + offsets[other], 0)
            joined = (a > 0) & (b > 0)
            for x, y in set(zip(a[joined].tolist(), b[joined].tolist(), strict=True)):
                rx, ry = find(x), find(y)
                if rx != ry:
                    parent[max(rx, ry)] = min(rx, ry)
    roots = np.array([find(i) for i in range(total + 1)])
    seed_ids = np.concatenate([[False]] + [seeded[key][1:] for key in ordered])
    marine_root = np.zeros(total + 1, bool)
    marine_root[roots[seed_ids]] = True
    marine = marine_root[roots]
    marine[0] = False
    return SeaConnectivity(offsets, marine)
