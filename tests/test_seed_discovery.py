"""Tests for seed discovery — connected components, ranking, feature extraction."""

from dreamulator.engine.seed_discovery import (
    _longitude_zone,
    cradle_score,
    discover_seed_candidates,
    label_agricultural_regions,
    region_features,
)
from dreamulator.map.models import CVTMesh, VoronoiCell


def _agri_cell(
    i: int,
    n: int,
    *,
    coastal: bool = False,
    koppen: str = "Cfb",
    npp: float = 1000.0,
    fert: str = "high",
    dist: float = 10.0,
) -> VoronoiCell:
    """An agricultural land cell on a linear chain of ``n`` cells."""
    return VoronoiCell(
        id=i,
        lon=float(i),
        lat=0.0,
        elevation=100.0,
        crust_type="continental",
        area_km2=1000.0,
        neighbors=[j for j in (i - 1, i + 1) if 0 <= j < n],
        temperature_C=15.0,
        precipitation_mm=1000.0,
        koppen_class=koppen,
        npp_gc_m2_yr=npp,
        soil_fertility=fert,
        domesticable_tags=["staple_crops_high"],
        distance_to_coast_km=dist,
        habitable_coast=coastal,
        agricultural_core=True,
    )


def _ocean_cell(i: int, n: int) -> VoronoiCell:
    """A non-agricultural ocean cell."""
    return VoronoiCell(
        id=i,
        lon=float(i),
        lat=0.0,
        elevation=-100.0,
        crust_type="oceanic",
        area_km2=1000.0,
        neighbors=[j for j in (i - 1, i + 1) if 0 <= j < n],
        habitable_coast=False,
        agricultural_core=False,
    )


def _mesh(cells: list[VoronoiCell]) -> CVTMesh:
    adjacency = {str(c.id): list(c.neighbors) for c in cells}
    return CVTMesh(seed=42, num_cells=len(cells), cells=cells, adjacency=adjacency)


# ---------------------------------------------------------------------------
# cradle_score
# ---------------------------------------------------------------------------


def test_cradle_score() -> None:
    assert cradle_score(1000.0, 500.0, 1.0) == 500_000.0
    assert cradle_score(1000.0, None, 1.0) == 1000.0  # missing NPP → area × fert
    assert cradle_score(1000.0, 500.0, 0.25) == 125_000.0


# ---------------------------------------------------------------------------
# longitude zone
# ---------------------------------------------------------------------------


def test_longitude_zone() -> None:
    assert _longitude_zone(0.0, 0.0) == "sub_planet"
    assert _longitude_zone(59.0, 0.0) == "sub_planet"
    assert _longitude_zone(60.0, 0.0) == "twilight"
    assert _longitude_zone(90.0, 0.0) == "twilight"
    assert _longitude_zone(120.0, 0.0) == "twilight"
    assert _longitude_zone(121.0, 0.0) == "anti_planet"
    assert _longitude_zone(180.0, 0.0) == "anti_planet"
    assert _longitude_zone(-170.0, 0.0) == "anti_planet"  # wraps the antimeridian


# ---------------------------------------------------------------------------
# label_agricultural_regions
# ---------------------------------------------------------------------------


def test_label_agricultural_regions() -> None:
    # 0-2 agricultural (region A), 3 ocean, 4-5 agricultural (region B).
    cells = [
        _agri_cell(0, 6),
        _agri_cell(1, 6),
        _agri_cell(2, 6),
        _ocean_cell(3, 6),
        _agri_cell(4, 6, coastal=True),
        _agri_cell(5, 6, coastal=True),
    ]
    mesh = _mesh(cells)

    regions = label_agricultural_regions(mesh, min_cells=1)
    assert {tuple(sorted(r)) for r in regions} == {(0, 1, 2), (4, 5)}

    # min_cells filters the 2-cell region B.
    regions = label_agricultural_regions(mesh, min_cells=3)
    assert [tuple(sorted(r)) for r in regions] == [(0, 1, 2)]


# ---------------------------------------------------------------------------
# region_features
# ---------------------------------------------------------------------------


def test_region_features() -> None:
    cells = [_agri_cell(0, 3, coastal=True), _agri_cell(1, 3, coastal=True), _agri_cell(2, 3)]
    mesh = _mesh(cells)

    feats = region_features(mesh, [0, 1, 2])
    assert feats["cell_count"] == 3
    assert feats["area_km2"] == 3000.0
    assert feats["is_coastal"] is True
    assert feats["dominant_koppen"] == "Cfb"
    assert feats["mean_npp_gc_m2_yr"] == 1000.0
    assert feats["dominant_soil_fertility"] == "high"
    # score = area × mean NPP × fertility weight = 3000 × 1000 × 1.0
    assert feats["score"] == 3_000_000.0


# ---------------------------------------------------------------------------
# discover_seed_candidates
# ---------------------------------------------------------------------------


def test_discover_seed_candidates_ranks_by_score() -> None:
    # Region A (0-2): large, coastal, high NPP. Region B (4-5): small, inland, low NPP.
    cells = [
        _agri_cell(0, 6, coastal=True),
        _agri_cell(1, 6, coastal=True),
        _agri_cell(2, 6, coastal=True),
        _ocean_cell(3, 6),
        _agri_cell(4, 6, koppen="BSk", npp=300.0, fert="low", dist=500.0),
        _agri_cell(5, 6, koppen="BSk", npp=300.0, fert="low", dist=500.0),
    ]
    mesh = _mesh(cells)

    candidates = discover_seed_candidates(mesh, min_cells=1)
    assert len(candidates) == 2

    top = candidates[0]
    assert top["id"] == "cradle_01"
    assert top["rank"] == 1
    assert top["is_coastal"] is True
    assert top["dominant_koppen"] == "Cfb"

    second = candidates[1]
    assert second["id"] == "cradle_02"
    assert second["is_coastal"] is False
    assert second["dominant_koppen"] == "BSk"

    # A (3000 km² × 1000 NPP × 1.0) > B (2000 km² × 300 NPP × 0.25).
    assert top["score"] > second["score"]


def test_discover_seed_candidates_deterministic() -> None:
    cells = [_agri_cell(0, 3), _agri_cell(1, 3), _agri_cell(2, 3)]
    mesh = _mesh(cells)
    assert discover_seed_candidates(mesh, min_cells=1) == discover_seed_candidates(
        mesh, min_cells=1
    )
