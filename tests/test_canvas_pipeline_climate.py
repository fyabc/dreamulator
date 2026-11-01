"""Climate-grid alignment on the canvas chunk bounding box.

The climate channels span the whole canvas (``ncell`` cells of 256 px); the
assembled pixel array covers only the chunk bounding box, which usually
stops short of the canvas edge.  Tiling must crop the grid and repeat at the
true cell size — rescaling by ``h // ncell`` shears every field, which broke
canvases whose chunk box is smaller than their canvas grid.
"""

from __future__ import annotations

import numpy as np

from dreamulator.map.td_canvas import PX_PER_CELL
from dreamulator.media.canvas_pipeline import _climate_on_grid


def test_coarse_grid_larger_than_the_chunk_box_is_cropped() -> None:
    coarse = np.arange(16, dtype=np.float64).reshape(4, 4)
    h = 2 * PX_PER_CELL  # the box covers two coarse rows
    w = 1 * PX_PER_CELL  # and one coarse column
    out = _climate_on_grid(coarse, h, w)
    assert out.shape == (h, w)
    # Row block 0 is coarse[0], block 1 is coarse[1]; only column 0 is used.
    assert np.allclose(out[:PX_PER_CELL, :], coarse[0, 0])
    assert np.allclose(out[PX_PER_CELL:, :], coarse[1, 0])


def test_full_canvas_grid_tiles_identically() -> None:
    coarse = np.arange(4, dtype=np.float64).reshape(2, 2)
    out = _climate_on_grid(coarse, 2 * PX_PER_CELL, 2 * PX_PER_CELL)
    assert out.shape == (2 * PX_PER_CELL, 2 * PX_PER_CELL)
    assert np.allclose(out[:PX_PER_CELL, :PX_PER_CELL], coarse[0, 0])
    assert np.allclose(out[PX_PER_CELL:, PX_PER_CELL:], coarse[1, 1])
