"""Sub-grid island catalogue (map/island_catalog.py, proposals/island-catalog.md)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from dreamulator.map.island_catalog import (
    IslandCatalog,
    Volcano,
    _cone,
    build_island_catalog,
    catalog_to_json,
    edifice_subsidence_m,
    summarise_islands,
    volcano_cell_mean,
)
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline

TINY = dict(num_nodes=6000, lloyd_iterations=1, num_plates=8, seed=7, tectonic_duration_my=20.0)


def test_cone_keeps_volume_and_caps_relief() -> None:
    relief, radius = _cone(50000.0, 9.80665)  # a Mauna-Loa-sized shield
    assert 6000.0 < relief < 9000.0
    assert math.pi * radius**2 * relief / 1000.0 / 3.0 == pytest.approx(50000.0, rel=1e-6)
    relief_big, radius_big = _cone(2.0e6, 9.80665)  # beyond the strength cap: wider, not taller
    assert relief_big == pytest.approx(9000.0)
    assert math.pi * radius_big**2 * relief_big / 1000.0 / 3.0 == pytest.approx(2.0e6, rel=1e-6)
    assert _cone(2.0e6, 2 * 9.80665)[0] == pytest.approx(4500.0)  # cap ∝ 1/g


def test_edifice_subsidence() -> None:
    assert edifice_subsidence_m(0.0) == 0.0
    assert edifice_subsidence_m(0.1) / 0.1e6 * 1e3 == pytest.approx(2.4, abs=0.3)  # ~2.5 mm/yr
    assert edifice_subsidence_m(20.0) == pytest.approx(2000.0, abs=1.0)


def test_catalogue_exports_background_and_relief_in_the_same_sea_level_datum() -> None:
    import json

    mesh = CVTMesh(
        seed=1,
        num_cells=1,
        cells=[VoronoiCell(id=0, lon=0, lat=0, elevation=-1800, area_km2=3000)],
    )
    volcano = Volcano("test", "hotspot", "source", 0, 0, 0, 0, 1000, 20, 4000)
    cat = IslandCatalog([volcano])
    # A cached catalogue predating the background field has an explicit missing value.
    record = catalog_to_json(cat)[0]
    assert record["floor_elevation_m"] is None
    summarise_islands(mesh, cat, np.array([200.0]), sea_level_m=100)
    record = catalog_to_json(cat)[0]
    assert record["floor_elevation_m"] == -2100
    assert record["built_relief_m"] == 4000
    assert record["summit_m"] == 1900
    assert record["present_relief_m"] == 4000
    json.dumps(record, allow_nan=False)


@pytest.fixture(scope="module")
def built():
    cfg = TerrainPipelineConfig(**TINY)
    res = run_terrain_pipeline(
        cfg, stages=["mesh", "plates", "tectonics", "boundaries", "terrain"], cache=None
    )
    return cfg, res


def test_catalogue_chains_and_summaries(built) -> None:
    cfg, res = built
    cat = build_island_catalog(res.mesh, res.plates, cfg)
    hot = [v for v in cat.volcanoes if v.kind == "hotspot"]
    assert hot and any(v.kind == "seamount" for v in cat.volcanoes)
    # deterministic
    again = build_island_catalog(res.mesh, res.plates, cfg)
    assert [(v.id, v.cell) for v in again.volcanoes] == [(v.id, v.cell) for v in cat.volcanoes]
    # ages increase along each chain and stay within the back-track window
    by_src: dict[str, list[float]] = {}
    for v in hot:
        by_src.setdefault(v.source, []).append(v.age_myr)
    for ages in by_src.values():
        assert ages == sorted(ages) and ages[0] == 0.0 and ages[-1] <= 20.0 + 1e-9
    contrib = volcano_cell_mean(res.mesh, cat, cfg.radius_km)
    assert (contrib >= 0.0).all() and contrib.max() <= max(v.relief_m for v in hot) + 1e-6
    summ = summarise_islands(res.mesh, cat, contrib, cfg.sea_level_offset_m)
    islands = [v for v in cat.volcanoes if v.status in ("volcanic island", "low island")]
    cell_km = {v.cell: np.sqrt(res.mesh.cells[v.cell].area_km2) for v in islands}
    subgrid = [
        v for v in islands if v.summit_m / v.relief_m * v.base_radius_km <= 0.5 * cell_km[v.cell]
    ]
    assert int(summ["island_count"].sum()) == len(subgrid)
    emerged = islands
    assert (summ["island_area_frac"] >= 0).all() and (summ["island_area_frac"] <= 1).all()
    for v in emerged:
        assert v.emergent_area_km2 > 0 and v.status in ("volcanic island", "low island")
    assert np.all(np.isnan(summ["island_peak_m"][summ["island_count"] == 0]))


def test_disabled_catalogue_is_empty(built) -> None:
    cfg, res = built
    from dataclasses import replace

    off = replace(cfg, island_catalog_enabled=False)
    assert build_island_catalog(res.mesh, res.plates, off).volcanoes == []


def test_island_arc_on_overriding_plate(built) -> None:
    from dreamulator.map.island_catalog import _ARC_TRENCH_KM, _arc_geometry, arc_platform

    cfg, res = built
    dist, age, over = _arc_geometry(res.mesh, res.plates, cfg.radius_km)
    assert over.any()
    plat = arc_platform(res.mesh, res.plates, cfg)
    reach = np.isfinite(dist)
    # the platform lives only on the overriding plate's arc belt and peaks near the arc axis
    assert (plat[~reach] == 0.0).all() and plat.max() > 0.0
    top = np.flatnonzero(plat > 0.8 * plat.max())
    assert np.all(np.abs(dist[top] - _ARC_TRENCH_KM) < 150.0)
    cat = build_island_catalog(res.mesh, res.plates, cfg)
    arcs = [v for v in cat.volcanoes if v.kind == "arc"]
    assert arcs and all(reach[v.cell] for v in arcs)
    assert all(0.0 <= v.age_myr <= 1.0 for v in arcs)
    # arc edifices enter the cell mean like hotspot volcanoes
    only_arcs = type(cat)(volcanoes=arcs)
    assert volcano_cell_mean(res.mesh, only_arcs, cfg.radius_km).max() > 0.0
