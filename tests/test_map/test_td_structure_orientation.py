"""Structure-field crest orientation: strike-parallel ridges versus transverse spurs."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map import td_canvas as tc
from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.map.td_canvas_structure import structure_anomaly


def _belt() -> tuple[CanvasGeometry, np.ndarray, np.ndarray, np.ndarray]:
    """Fibonacci cells around a canvas at the equator; elevation rises eastward (contours N-S)."""
    n = 60000
    i = np.arange(n) + 0.5
    lat = np.degrees(np.arcsin(1 - 2 * i / n))
    lon = np.degrees(np.pi * (1 + 5**0.5) * i) % 360 - 180
    xyz = tc.unit_vectors(lat, lon)
    elev = np.where(np.abs(lat) < 20, 500.0 + 150.0 * (lon + 20.0), -3000.0)
    elev = np.clip(elev, -3000.0, 4000.0)
    mu = np.where(elev > 0, 600.0, np.nan)
    return CanvasGeometry(0.0, 0.0, 6371.0, 64), xyz, elev, mu


def _east_west_share(orientation: str) -> float:
    geom, xyz, elev, mu = _belt()
    anomaly, _ = structure_anomaly(geom, "test", xyz, elev, mu, orientation=orientation)
    gy, gx = np.gradient(anomaly[16:48, 16:48])
    return float(np.mean(gx**2) / np.mean(gy**2))


def test_strike_crests_follow_contours_and_transverse_cross_them() -> None:
    # Contours run north-south: strike-parallel crests vary east-west, transverse spurs north-south.
    strike, transverse = _east_west_share("strike"), _east_west_share("transverse")
    assert strike > 1.0 > transverse
    assert strike / transverse > 1.2


def test_unknown_orientation_is_rejected() -> None:
    geom, xyz, elev, mu = _belt()
    with pytest.raises(ValueError, match="orientation"):
        structure_anomaly(geom, "test", xyz, elev, mu, orientation="diagonal")
