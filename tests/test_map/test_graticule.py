"""Graticule overlay of headless map exports (map/export.py ``draw_graticule``)."""

from __future__ import annotations

import numpy as np

from dreamulator.map.export import draw_graticule


def test_graticule_draws_equator_and_meridians() -> None:
    rgba = np.zeros((180, 360, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    out = draw_graticule(rgba, 30.0)
    assert out.shape == rgba.shape and out.dtype == np.uint8
    eq = int(round(89.5))  # row of latitude 0 in an H = 180 image
    assert out[eq, 100, :3].sum() > 0  # equator line
    assert out[45, 180, :3].sum() > 0  # prime meridian at column W/2
    assert out[45, 195, :3].sum() == 0  # off-grid pixel left untouched (between 0° and 30°E)
    assert (out[..., 3] == 255).all()
