"""Civilization seed discovery — derive candidate cradle regions from physical layers.

Pure mesh-level functions (no IO, no RNG).  Connected-component labeling over the
``agricultural_core`` mask yields contiguous farmable regions; each is ranked by a
carrying-capacity proxy and annotated with features aggregated from the climate /
ecology / geography layers.  The candidates are **deterministic** (same mesh → same
candidates): the RNG seed enters only upstream (terrain/climate/ecology generation)
and downstream (Phase 3C actualisation / 3D Monte Carlo), never here.

The candidates are the *derived skeleton* that hand-authored seeds (or ``ai civ``)
select from — mirroring the ecology layer's "relationship skeleton → instantiator"
split (see ``docs/design/ecology-layer.md`` §1).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, cast

from dreamulator.engine.habitability import FERTILITY_WEIGHT

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dreamulator.map.models import CVTMesh

#: Minimum component size (cells) below which a farmable patch is too small to
#: sustain a civilisation cradle (~51 km/cell at 200k → 20 cells ≈ 5×10⁴ km²).
MIN_REGION_CELLS: int = 20


def label_agricultural_regions(mesh: CVTMesh, min_cells: int = MIN_REGION_CELLS) -> list[list[int]]:
    """Connected components of ``agricultural_core`` land cells (mesh indices).

    Components smaller than ``min_cells`` are dropped as noise (isolated islets
    cannot host a cradle).  Deterministic — no RNG.
    """
    n = mesh.num_cells
    cells = mesh.cells
    adj, _ = _adjacency(mesh)
    mask = [bool(c.agricultural_core) for c in cells]

    visited = [False] * n
    regions: list[list[int]] = []
    for i in range(n):
        if not mask[i] or visited[i]:
            continue
        visited[i] = True
        region = [i]
        stack = [i]
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if mask[v] and not visited[v]:
                    visited[v] = True
                    region.append(v)
                    stack.append(v)
        if len(region) >= min_cells:
            regions.append(region)

    return regions


def region_features(
    mesh: CVTMesh,
    region: list[int],
    *,
    sub_planet_longitude_deg: float = 0.0,
) -> dict[str, object]:
    """Aggregate physical features of a farmable region into a YAML-safe dict.

    Every feature is read directly from per-cell fields already computed by the
    upstream climate / ecology / geology engines, so the seed candidate
    "inherits" its physical base automatically rather than by hand-specification.
    """
    cells = mesh.cells
    n = len(region)
    idx = region

    # ---- geometry ----
    area_km2 = sum(cells[i].area_km2 for i in idx)
    lons = [cells[i].lon for i in idx]
    lats = [cells[i].lat for i in idx]
    lon_rad = [math.radians(lo) for lo in lons]
    lon_mean = math.degrees(
        math.atan2(sum(math.sin(r) for r in lon_rad), sum(math.cos(r) for r in lon_rad))
    )
    lat_mean = sum(lats) / n

    # ---- climate ----
    mean_temp = _mean(cells[i].temperature_C for i in idx)
    mean_precip = _mean(cells[i].precipitation_mm for i in idx)
    koppen = Counter(cells[i].koppen_class for i in idx if cells[i].koppen_class)
    dominant_koppen = koppen.most_common(1)[0][0] if koppen else None

    # ---- ecology ----
    mean_npp = _mean(cells[i].npp_gc_m2_yr for i in idx)
    fertility = Counter(cells[i].soil_fertility for i in idx if cells[i].soil_fertility)
    dominant_fertility = fertility.most_common(1)[0][0] if fertility else None
    fertility_weight = FERTILITY_WEIGHT.get(dominant_fertility or "", 0.5)
    domesticable = {
        "staple_crops_high": sum(
            1 for i in idx if "staple_crops_high" in cells[i].domesticable_tags
        )
        / n,
        "large_herbivores_high": sum(
            1 for i in idx if "large_herbivores_high" in cells[i].domesticable_tags
        )
        / n,
        "draft_animals_high": sum(
            1 for i in idx if "draft_animals_high" in cells[i].domesticable_tags
        )
        / n,
    }

    # ---- settlement / geography ----
    coastal = sum(1 for i in idx if cells[i].habitable_coast)
    mean_dist = _mean(cells[i].distance_to_coast_km for i in idx)
    landform = Counter(cells[i].landform for i in idx if cells[i].landform)

    score = cradle_score(area_km2, mean_npp, fertility_weight)

    return {
        "cell_count": n,
        "area_km2": round(area_km2, 1),
        "score": round(score, 2),
        "centroid_lon_deg": round(lon_mean, 2),
        "centroid_lat_deg": round(lat_mean, 2),
        "is_coastal": coastal > 0,
        "coastal_fraction": round(coastal / n, 4),
        "mean_distance_to_coast_km": round(mean_dist, 1) if mean_dist is not None else None,
        "mean_temperature_c": round(mean_temp, 2) if mean_temp is not None else None,
        "mean_precipitation_mm": round(mean_precip, 1) if mean_precip is not None else None,
        "dominant_koppen": dominant_koppen,
        "koppen_breakdown": dict(koppen.most_common(5)),
        "mean_npp_gc_m2_yr": round(mean_npp, 1) if mean_npp is not None else None,
        "dominant_soil_fertility": dominant_fertility,
        "fertility_weight": fertility_weight,
        "domesticable_fraction": {k: round(v, 4) for k, v in domesticable.items()},
        "landforms": dict(landform),
        "longitude_zone": _longitude_zone(lon_mean, sub_planet_longitude_deg),
    }


def cradle_score(area_km2: float, mean_npp: float | None, fertility_weight: float) -> float:
    """Carrying-capacity proxy for a region (the HANDY model's K driver).

    ``score = area × mean NPP × soil-fertility weight`` — a monotonic proxy for
    how many people the region can support (Motesharrei et al. 2014, HANDY).
    Regions with missing NPP fall back to area × fertility weight.
    """
    return area_km2 * (mean_npp if mean_npp is not None else 1.0) * fertility_weight


def discover_seed_candidates(
    mesh: CVTMesh,
    *,
    min_cells: int = MIN_REGION_CELLS,
    sub_planet_longitude_deg: float = 0.0,
) -> list[dict[str, object]]:
    """Full seed-candidate pipeline: label → feature → rank.

    Returns candidates sorted by carrying-capacity score (descending), each with
    a ``rank`` and ``id``.  Deterministic for a given mesh.
    """
    regions = label_agricultural_regions(mesh, min_cells=min_cells)
    candidates: list[dict[str, object]] = []
    for region in regions:
        candidates.append(
            region_features(mesh, region, sub_planet_longitude_deg=sub_planet_longitude_deg)
        )

    candidates.sort(key=lambda c: cast("float", c["score"]), reverse=True)
    for rank, c in enumerate(candidates, 1):
        c["rank"] = rank
        c["id"] = f"cradle_{rank:02d}"
    return candidates


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _mean(values: Iterable[float | None]) -> float | None:
    """Mean of non-None values, or ``None`` when empty."""
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _adjacency(mesh: CVTMesh) -> tuple[list[list[int]], dict[int, int]]:
    """Index-based adjacency and id→index map."""
    n = mesh.num_cells
    id_to_index = {c.id: i for i, c in enumerate(mesh.cells)}
    adj: list[list[int]] = [[] for _ in range(n)]
    for i, c in enumerate(mesh.cells):
        for nid in c.neighbors:
            j = id_to_index.get(nid)
            if j is not None:
                adj[i].append(j)
    return adj, id_to_index


def _longitude_zone(lon_mean: float, sub_planet_longitude_deg: float) -> str:
    """Coarse astronomical zone: sub-planet / anti-planet / twilight.

    The sub-planet (向星) point is the hemisphere permanently facing the host
    body (only meaningful for tidally-locked satellites / worlds); the anti-planet
    (背星) side never sees it; the twilight (边缘) band is the day/night terminator.
    """
    d = (lon_mean - sub_planet_longitude_deg + 180.0) % 360.0 - 180.0
    if abs(d) < 60.0:
        return "sub_planet"
    if abs(d) > 120.0:
        return "anti_planet"
    return "twilight"
