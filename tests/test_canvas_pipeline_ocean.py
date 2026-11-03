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
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_pipeline import (
    SEA_MASK_VERSION,
    CanvasStore,
    _external_mask,
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
