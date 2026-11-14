"""S2 outlet rule: the sea is boundary-linked water in a geologically oceanic body.

Hydrology runs on the installed surface, so the outlet is the connected sea of
that surface — every pixel at or below sea level that joins the canvas edge or
a missing-chunk boundary AND whose body holds a pixel inside a 23 km
geological-ocean cell.  The boundary reach alone would make a sea out of an
inland closed basin touching the artificial canvas edge (canvases overlap);
the geological contact alone is the coarse-seed rule that misjudges
ice-dammed hollows and shelf-cell ponds.  A sub-sea-level hollow failing either
test is an inland low: it takes part in the fill as a closed basin and the lake
criteria decide whether water stands in it.  Canvases that do not declare the
connected-sea product keep the legacy "at or below sea level drains" rule.

Closed water bodies the mesh upgraded to sea class are sea as well: a water
body holding a pixel inside the 3 x 3-eroded ``geometry_fields/mesh_sea_lake.npy``
shares sea level with the ocean.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_pipeline import (
    GEOLOGICAL_OCEAN_FILE,
    MESH_SEA_LAKE_FILE,
    SEA_MASK_VERSION,
    CanvasStore,
    _external_mask,
    canvas_anchored_sea,
    chunk_ocean,
    surface_sea,
)

if TYPE_CHECKING:
    from pathlib import Path

TILE = 8
NCELL = 16


def _default_conditioning() -> np.ndarray:
    """Geological ocean in the west (coarse column 0), land elsewhere."""
    height = np.full((NCELL, NCELL), 100.0, dtype=np.float32)
    height[:, 0] = -100.0
    return height


def _make_store(
    root: Path,
    *,
    sea_mask: dict[str, Any] | None,
    connected_basin: bool = False,
    mark_inland: bool = False,
    dem: np.ndarray | None = None,
    conditioning_height: np.ndarray | None = None,
    with_conditioning: bool = True,
    mesh_sea_lake: np.ndarray | None = None,
) -> CanvasStore:
    (root / "chunks").mkdir(parents=True)
    if dem is None:
        dem = np.full((TILE, TILE), 100.0, dtype=np.int16)
        dem[:, :2] = -50  # western sea column, touching the canvas edge
        dem[3:5, 3:5] = -80  # enclosed sub-sea-level basin
        if connected_basin:
            dem[4, 2] = -60  # one-pixel channel from the sea into the basin
    np.save(root / "chunks" / "r000_c000.npy", dem)
    meta: dict[str, Any] = {
        "geometry": CanvasGeometry(10.0, 20.0, 6816.97, NCELL).to_dict(),
        "chunks": [[0, 0]],
    }
    if sea_mask is not None:
        meta["sea_mask"] = sea_mask
    if mark_inland:
        low_dir = root / "surface" / "inland_low"
        low_dir.mkdir(parents=True)
        basin = np.zeros(dem.shape, dtype=bool)
        basin[3:5, 3:5] = True
        np.savez_compressed(
            low_dir / "r000_c000.npz",
            packed=np.packbits(basin, axis=1),
            shape=np.array(basin.shape),
        )
    if with_conditioning:
        height = conditioning_height if conditioning_height is not None else _default_conditioning()
        cond_dir = root / "conditioning"
        cond_dir.mkdir(parents=True)
        np.save(cond_dir / "heightmap.npy", height)
    if mesh_sea_lake is not None:
        (root / MESH_SEA_LAKE_FILE).parent.mkdir(parents=True, exist_ok=True)
        np.save(root / MESH_SEA_LAKE_FILE, mesh_sea_lake.astype(np.uint8))
    (root / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
    return CanvasStore.load(root)


def _ocean(root: Path, **kwargs: Any) -> tuple[np.ndarray, CanvasStore]:
    store = _make_store(root, sea_mask={"version": SEA_MASK_VERSION}, **kwargs)
    dem = store.raw(0, 0)
    sea = surface_sea(store, 0.0)
    return chunk_ocean(store, (0, 0), dem, 0.0, sea=sea), store


def test_enclosed_basin_is_not_an_outlet(tmp_path: Path) -> None:
    ocean, store = _ocean(tmp_path / "canvas")
    assert ocean[:, :2].all()  # the edge sea stays sea
    assert not ocean[3:5, 3:5].any()  # the enclosed hollow is land for the fill

    ext = _external_mask(store, (0, 0), store.raw(0, 0), 0.0, sea=surface_sea(store, 0.0))
    assert ext[:, :2].all()
    assert not ext[4, 4]


def test_a_channel_to_the_edge_makes_the_basin_sea(tmp_path: Path) -> None:
    ocean, _ = _ocean(tmp_path / "canvas", connected_basin=True)
    assert ocean[4, 4]


def test_product_inland_low_is_honoured(tmp_path: Path) -> None:
    ocean, _ = _ocean(tmp_path / "canvas", connected_basin=True, mark_inland=True)
    # A channel-connected basin the product marks as inland low stays land.
    assert not ocean[3:5, 3:5].any()
    assert ocean[4, 2]  # the channel itself is not marked


def test_canvas_without_the_product_keeps_the_sea_level_rule(tmp_path: Path) -> None:
    store = _make_store(tmp_path / "canvas", sea_mask=None)
    dem = store.raw(0, 0)
    ocean = chunk_ocean(store, (0, 0), dem, 0.0)
    assert ocean[3:5, 3:5].all()  # every sub-sea pixel drains


def test_edge_basin_in_land_cells_is_not_sea(tmp_path: Path) -> None:
    # The mirror failure of the coarse-seed rule: a closed basin that happens
    # to touch the canvas's open boundary sits in geological-land cells, so the
    # anchor rejects it even though the boundary pass alone would take it.
    tile = 512
    dem = np.full((tile, tile), 100.0, dtype=np.int16)
    dem[:, :2] = -50  # western sea inside the geological-ocean column
    dem[200:300, -32:] = -80  # closed basin touching the canvas's east edge
    ocean, _ = _ocean(tmp_path / "canvas", dem=dem)
    assert ocean[:, :2].all()  # the geologically anchored sea stays sea
    assert not ocean[200:300, -32:].any()  # the boundary basin stays land


def test_enclosed_basin_in_ocean_cells_is_not_sea(tmp_path: Path) -> None:
    # Geological contact alone must not become the coarse-seed rule either:
    # an enclosed basin inside ocean cells still fails the boundary test.
    height = np.full((NCELL, NCELL), -100.0, dtype=np.float32)
    ocean, _ = _ocean(tmp_path / "canvas", conditioning_height=height)
    assert ocean[:, :2].all()
    assert not ocean[3:5, 3:5].any()


def test_missing_conditioning_heightmap_is_an_error(tmp_path: Path) -> None:
    store = _make_store(
        tmp_path / "canvas", sea_mask={"version": SEA_MASK_VERSION}, with_conditioning=False
    )
    with pytest.raises(FileNotFoundError, match="conditioning"):
        surface_sea(store, 0.0)


def _rift_dem() -> np.ndarray:
    """Four 23 km cells per side: a western edge sea and a deep closed basin in the middle."""
    tile = 1024
    dem = np.full((tile, tile), 300.0, dtype=np.int16)
    dem[:, :2] = -50  # edge sea inside the geological-ocean column
    dem[300:700, 300:700] = -1400  # closed basin behind a sill, below sea level
    return dem


def _rift_conditioning() -> np.ndarray:
    height = _default_conditioning()
    height[1:3, 1:3] = -1400.0  # the basin is geologically oceanic on the mesh, too
    return height


def test_mesh_sea_class_basin_is_sea(tmp_path: Path) -> None:
    # A closed basin the mesh upgraded to sea class shares sea level with the
    # ocean: S2 must not fill it to its sill.
    mesh = np.zeros((NCELL, NCELL), bool)
    mesh[:, :6] = True  # a sea-class lake covering the basin and its surroundings
    ocean, store = _ocean(
        tmp_path / "canvas",
        dem=_rift_dem(),
        conditioning_height=_rift_conditioning(),
        mesh_sea_lake=mesh,
    )
    assert ocean[300:700, 300:700].all()
    assert ocean[:, :2].all()
    assert not ocean[100, 900]  # land stays land
    assert surface_sea(store, 0.0).mesh is not None


def test_mesh_coastal_cells_do_not_seed_the_sea(tmp_path: Path) -> None:
    # A lone sea-class cell vanishes under the 3 x 3 erosion, so a land hollow
    # next to a mesh coastline is not pulled into the sea.
    mesh = np.zeros((NCELL, NCELL), bool)
    mesh[1:3, 1:3] = True
    ocean, _ = _ocean(
        tmp_path / "canvas",
        dem=_rift_dem(),
        conditioning_height=_rift_conditioning(),
        mesh_sea_lake=mesh,
    )
    assert not ocean[300:700, 300:700].any()


def test_without_the_mesh_field_the_basin_stays_closed(tmp_path: Path) -> None:
    ocean, store = _ocean(
        tmp_path / "canvas", dem=_rift_dem(), conditioning_height=_rift_conditioning()
    )
    assert not ocean[300:700, 300:700].any()
    assert surface_sea(store, 0.0).mesh is None


def test_mesh_sea_lake_field_has_the_canvas_grid_shape(tmp_path: Path) -> None:
    store = _make_store(
        tmp_path / "canvas",
        sea_mask={"version": SEA_MASK_VERSION},
        mesh_sea_lake=np.ones((NCELL // 2, NCELL // 2), bool),
    )
    with pytest.raises(ValueError, match="mesh sea-lake"):
        surface_sea(store, 0.0)


def test_ice_bed_uses_the_original_geological_surface_anchor(tmp_path: Path) -> None:
    rock = _make_store(
        tmp_path / "rock",
        sea_mask=None,
        conditioning_height=np.full((NCELL, NCELL), -100.0, dtype=np.float32),
    )
    original = _make_store(
        tmp_path / "original",
        sea_mask=None,
        conditioning_height=np.full((NCELL, NCELL), 100.0, dtype=np.float32),
    )

    def load(key: tuple[int, int]) -> np.ndarray:
        return rock.raw(*key)

    sea = canvas_anchored_sea(
        rock.root,
        rock.geometry,
        rock.chunks,
        load,
        rock.tile,
        0.0,
        geological_root=original.root,
    )
    # The exposed sub-ice bed touches the artificial boundary but has no
    # geological ocean contact in the ice-including reference surface.
    assert not sea.mask((0, 0), load((0, 0)) <= 0).any()
    assert surface_sea(rock, 0.0).mask((0, 0), load((0, 0)) <= 0)[:, :2].all()


def test_ice_bed_keeps_mesh_sea_lakes_from_its_own_canvas(tmp_path: Path) -> None:
    mesh = np.zeros((NCELL, NCELL), bool)
    mesh[:, :6] = True
    rock = _make_store(
        tmp_path / "rock",
        sea_mask=None,
        dem=_rift_dem(),
        mesh_sea_lake=mesh,
    )
    original = _make_store(tmp_path / "original", sea_mask=None)
    water = rock.raw(0, 0) <= 0
    sea = canvas_anchored_sea(
        rock.root,
        rock.geometry,
        rock.chunks,
        lambda key: rock.raw(*key),
        rock.tile,
        0.0,
        geological_root=original.root,
    )
    assert sea.mask((0, 0), water)[300:700, 300:700].all()


def test_ice_surface_recomputes_water_after_a_channel_closes(tmp_path: Path) -> None:
    store = _make_store(tmp_path / "rock", sea_mask=None, connected_basin=True)
    bed = store.raw(0, 0)
    ice = np.zeros_like(bed)
    ice[4, 2] = 100
    before = canvas_anchored_sea(
        store.root,
        store.geometry,
        store.chunks,
        lambda key: bed,
        store.tile,
        0.0,
    )
    after = canvas_anchored_sea(
        store.root,
        store.geometry,
        store.chunks,
        lambda key: bed + ice,
        store.tile,
        0.0,
    )
    assert before.mask((0, 0), bed <= 0)[4, 4]
    assert not after.mask((0, 0), bed + ice <= 0)[4, 4]


def test_ice_geological_anchor_must_share_the_canvas_geometry(tmp_path: Path) -> None:
    store = _make_store(tmp_path / "rock", sea_mask=None)
    original = _make_store(tmp_path / "original", sea_mask=None)
    path = original.root / "canvas.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["geometry"]["center_lon"] += 1.0
    path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError, match="same geometry"):
        canvas_anchored_sea(
            store.root,
            store.geometry,
            store.chunks,
            lambda key: store.raw(*key),
            store.tile,
            0.0,
            geological_root=original.root,
        )


def test_retained_geological_anchor_precedes_rock_conditioning(tmp_path: Path) -> None:
    store = _make_store(
        tmp_path / "rock",
        sea_mask=None,
        conditioning_height=np.full((NCELL, NCELL), -100.0, dtype=np.float32),
    )
    retained = store.root / GEOLOGICAL_OCEAN_FILE
    retained.parent.mkdir(parents=True, exist_ok=True)
    np.save(retained, np.full((NCELL, NCELL), 100.0, dtype=np.float32))
    water = store.raw(0, 0) <= 0
    assert not surface_sea(store, 0.0).mask((0, 0), water).any()


def test_retained_geological_anchor_must_be_finite(tmp_path: Path) -> None:
    store = _make_store(tmp_path / "rock", sea_mask=None)
    retained = store.root / GEOLOGICAL_OCEAN_FILE
    retained.parent.mkdir(parents=True, exist_ok=True)
    height = _default_conditioning()
    height[0, 0] = np.nan
    np.save(retained, height)
    with pytest.raises(ValueError, match="non-finite"):
        surface_sea(store, 0.0)


def test_declared_geological_anchor_cannot_fall_back_when_missing(tmp_path: Path) -> None:
    store = _make_store(
        tmp_path / "rock",
        sea_mask={"version": SEA_MASK_VERSION, "anchor": GEOLOGICAL_OCEAN_FILE},
    )
    with pytest.raises(FileNotFoundError, match="declared geological ocean anchor"):
        surface_sea(store, 0.0)


def test_write_mesh_sea_lake_samples_the_nearest_cell(tmp_path: Path) -> None:
    from dreamulator.map import td_canvas as tc
    from dreamulator.map.td_canvas_build import MESH_SEA_LAKE_PATH, write_mesh_sea_lake

    geom = CanvasGeometry(0.0, 0.0, 6371.0, NCELL)
    lat = np.array([0.0, 0.0])
    lon = np.array([-30.0, 30.0])  # western cell a sea-class lake, eastern cell land
    meta = write_mesh_sea_lake(tmp_path, geom, np.array([True, False]), tc.unit_vectors(lat, lon))
    grid = np.load(tmp_path / MESH_SEA_LAKE_PATH)
    assert meta["path"] == MESH_SEA_LAKE_PATH
    assert grid.shape == (NCELL, NCELL) and grid.dtype == np.uint8
    assert grid[:, 0].all() and not grid[:, -1].any()
