"""Tests for biogeographic partitioning (realm → province)."""

from dreamulator.map.biogeography import partition_biogeographic_provinces
from dreamulator.map.models import CVTMesh, VoronoiCell


def _build_linear_mesh() -> CVTMesh:
    """Build an 8-cell linear mesh.

    Layout (index → elevation/biome):
        0-2 : continent A, forest (connected)
        3   : continent A, grassland (adjacent to forest, different biome)
        4   : ocean
        5-7 : continent B, forest (connected)
    """
    spec = [
        (100.0, "forest", "continental"),  # 0
        (100.0, "forest", "continental"),  # 1
        (100.0, "forest", "continental"),  # 2
        (100.0, "grassland", "continental"),  # 3
        (-100.0, None, "oceanic"),  # 4  ocean
        (100.0, "forest", "continental"),  # 5
        (100.0, "forest", "continental"),  # 6
        (100.0, "forest", "continental"),  # 7
    ]
    n = len(spec)
    cells: list[VoronoiCell] = []
    adjacency: dict[str, list[int]] = {}
    for i, (elev, biome, crust) in enumerate(spec):
        neighbors = [j for j in (i - 1, i + 1) if 0 <= j < n]
        cells.append(
            VoronoiCell(
                id=i,
                lon=float(i),
                lat=0.0,
                elevation=elev,
                crust_type=crust,
                biome=biome,
                neighbors=neighbors,
            )
        )
        adjacency[str(i)] = neighbors
    return CVTMesh(seed=42, num_cells=n, cells=cells, adjacency=adjacency)


def test_partition_realms_and_provinces() -> None:
    mesh = _build_linear_mesh()
    ids, meta = partition_biogeographic_provinces(mesh, target_provinces_per_realm=2)

    # Ocean cell → None
    assert ids[4] is None
    # Continent A: forest cells (0-2) share a province; grassland (3) differs
    assert ids[0] == ids[1] == ids[2]
    assert ids[3] != ids[0]
    # Continent B: forest cells (5-7) share a province, distinct from A's forest
    assert ids[5] == ids[6] == ids[7]
    assert ids[5] != ids[0]
    # Three provinces total
    assert len(meta) == 3
    # Realm numbering: A → realm 1, B → realm 2
    assert {meta[ids[0]]["realm"], meta[ids[3]]["realm"]} == {1}
    assert meta[ids[5]]["realm"] == 2
    # Representative biome recorded correctly
    assert meta[ids[0]]["biome"] == "forest"
    assert meta[ids[3]]["biome"] == "grassland"


def test_partition_merges_to_one_per_realm() -> None:
    mesh = _build_linear_mesh()
    ids, meta = partition_biogeographic_provinces(mesh)

    # 3 raw provinces → 2 after merging the smallest (grassland) into forest A
    assert len(meta) == 2
    assert ids[3] == ids[0]  # grassland merged into forest A


def test_partition_deterministic() -> None:
    mesh = _build_linear_mesh()
    ids1, meta1 = partition_biogeographic_provinces(mesh)
    ids2, meta2 = partition_biogeographic_provinces(mesh)
    assert ids1 == ids2
    assert meta1 == meta2
