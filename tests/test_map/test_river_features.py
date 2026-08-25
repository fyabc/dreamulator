"""Tests for river vector-layer extraction (map/river_generator.py)."""

from __future__ import annotations

from dreamulator.map.models import CVTMesh, FeatureType, VoronoiCell
from dreamulator.map.pipeline_types import lonlat_to_xyz
from dreamulator.map.river_generator import extract_river_features


def _cell(
    i: int,
    lon: float,
    lat: float = 0.0,
    *,
    flow: int | None = None,
    order: int = 0,
    river_id: str | None = None,
) -> VoronoiCell:
    x, y, z = lonlat_to_xyz(lon, lat)
    return VoronoiCell(
        id=i,
        lon=lon,
        lat=lat,
        x=float(x),
        y=float(y),
        z=float(z),
        area_km2=1.0,
        elevation=10.0,
        neighbors=[],
        flow_direction=flow,
        river_order=order,
        river_id=river_id,
    )


def _mesh(cells: list[VoronoiCell]) -> CVTMesh:
    return CVTMesh(seed=0, num_cells=len(cells), cells=cells)


def test_y_network_splits_by_order_and_confluence():
    """Trunk 0→1→2→3→4→ocean(5), tributary 6→7 joining at 2.

    Expect three polylines: [0,1] (order 1), [6,7] (order 1), [2,3,4]
    (order 2, starts at the confluence where the order increases).
    """
    cells = [
        _cell(0, 0.0, flow=1, order=1, river_id="river_0000"),
        _cell(1, 1.0, flow=2, order=1, river_id="river_0000"),
        _cell(2, 2.0, flow=3, order=2, river_id="river_0000"),
        _cell(3, 3.0, flow=4, order=2, river_id="river_0000"),
        _cell(4, 4.0, flow=5, order=2, river_id="river_0000"),
        _cell(5, 5.0, flow=None, order=0),  # ocean
        _cell(6, 2.0, lat=2.0, flow=7, order=1, river_id="river_0001"),
        _cell(7, 2.0, lat=1.0, flow=2, order=1, river_id="river_0001"),
    ]
    feats = extract_river_features(_mesh(cells))
    assert len(feats) == 3
    by_order = sorted(feats, key=lambda f: (f.order, f.coordinates[0][0]))
    # two order-1 branches
    assert by_order[0].order == 1 and by_order[1].order == 1
    seg0 = [c for c in by_order[0].coordinates]
    seg1 = [c for c in by_order[1].coordinates]
    assert seg0 == [(0.0, 0.0), (1.0, 0.0)]
    assert seg1 == [(2.0, 2.0), (2.0, 1.0)]
    # order-2 trunk starts at the confluence
    trunk = by_order[2]
    assert trunk.order == 2
    assert trunk.coordinates == [(2.0, 0.0), (3.0, 0.0), (4.0, 0.0)]
    assert all(f.type == FeatureType.RIVER for f in feats)
    assert trunk.name == "river_0000"


def test_antimeridian_split():
    """A channel crossing ±180° is split into two polylines."""
    cells = [
        _cell(0, 178.0, flow=1, order=1, river_id="r"),
        _cell(1, 179.5, flow=2, order=1, river_id="r"),
        _cell(2, -179.5, flow=3, order=1, river_id="r"),
        _cell(3, -178.0, flow=None, order=1, river_id="r"),
    ]
    feats = extract_river_features(_mesh(cells))
    assert len(feats) == 2
    lons = sorted({pt[0] for f in feats for pt in f.coordinates})
    assert lons == [-179.5, -178.0, 178.0, 179.5]
    for f in feats:
        assert len(f.coordinates) == 2


def test_min_order_filter():
    cells = [
        _cell(0, 0.0, flow=1, order=1, river_id="r"),
        _cell(1, 1.0, flow=None, order=2, river_id="r"),
    ]
    feats = extract_river_features(_mesh(cells), min_order=2)
    assert feats == []  # cell 0 excluded; cell 1 alone is <2 points


def test_mesh_without_rivers():
    cells = [_cell(0, 0.0, flow=None, order=0), _cell(1, 1.0, flow=None, order=0)]
    assert extract_river_features(_mesh(cells)) == []
