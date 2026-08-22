"""Tests for dreamulator.map.query — nearest-cell spatial queries."""

from __future__ import annotations

import math

import pytest

from dreamulator.map.export import build_export_tree
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.query import cell_facts, lonlat_to_xyz, nearest_cell


def _make_cell(cell_id: int, lon_deg: float, lat_deg: float, **kwargs: object) -> VoronoiCell:
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    return VoronoiCell(
        id=cell_id,
        lon=lon_deg,
        lat=lat_deg,
        x=math.cos(lat) * math.cos(lon),
        y=math.sin(lat),
        z=math.cos(lat) * math.sin(lon),
        **kwargs,
    )


@pytest.fixture
def mesh_tree() -> tuple[CVTMesh, object]:
    mesh = CVTMesh(
        seed=0,
        num_cells=3,
        cells=[
            _make_cell(
                0,
                0.0,
                0.0,
                elevation=100.0,
                koppen_class="Af",
                biome="tropical_rainforest",
                distance_to_coast_km=50.0,
                domesticable_tags=["staple_crops_high"],
            ),
            _make_cell(1, 90.0, 0.0),
            _make_cell(2, 0.0, 90.0),
        ],
    )
    return mesh, build_export_tree(mesh)


def test_lonlat_to_xyz() -> None:
    x, y, z = lonlat_to_xyz(0.0, 0.0)
    assert (x, y, z) == pytest.approx((1.0, 0.0, 0.0))


def test_nearest_cell(mesh_tree: tuple[CVTMesh, object]) -> None:
    mesh, tree = mesh_tree
    assert nearest_cell(mesh, tree, 1.0, 1.0).id == 0
    assert nearest_cell(mesh, tree, 89.0, 0.0).id == 1
    assert nearest_cell(mesh, tree, 0.0, 89.0).id == 2


def test_cell_facts(mesh_tree: tuple[CVTMesh, object]) -> None:
    mesh, tree = mesh_tree
    facts = cell_facts(mesh, tree, 1.0, 1.0)
    assert facts["cell_id"] == 0
    assert facts["elevation"] == 100.0
    assert facts["koppen_class"] == "Af"
    assert facts["biome"] == "tropical_rainforest"
    assert facts["distance_to_coast_km"] == 50.0
    assert facts["domesticable_tags"] == ["staple_crops_high"]
