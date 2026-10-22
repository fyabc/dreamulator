"""Tests for the fast full-disk spin renderer."""

from __future__ import annotations

import numpy as np

from dreamulator.media.atmosphere_render import AtmosphereModel, render_globe_atmosphere
from dreamulator.media.globe_spin import SpinRenderer


def _textures() -> tuple[np.ndarray, np.ndarray]:
    height, width = 32, 64
    lat = np.linspace(90.0, -90.0, height)[:, None]
    lon = np.linspace(-180.0, 180.0, width)[None, :]
    surface = np.zeros((height, width, 3), dtype=np.float64)
    surface[..., 0] = 0.35 + 0.10 * np.cos(np.radians(lon * 3.0))
    surface[..., 1] = 0.45 + 0.10 * np.sin(np.radians(lat * 2.0))
    surface[..., 2] = 0.55 + 0.05 * np.cos(np.radians(lon * 2.0 + lat))
    cloud = np.clip(0.5 + 0.45 * np.sin(np.radians(lon * 4.0)), 0.0, 1.0)
    cloud = cloud * np.ones((height, 1))
    return surface, cloud


def _model() -> AtmosphereModel:
    return AtmosphereModel(planet_radius_km=6371.0, star_temperature_k=5772.0)


def test_frame_zero_matches_static_renderer() -> None:
    surface, cloud = _textures()
    ocean = np.ones_like(cloud)
    kwargs = dict(
        res=96,
        center_lon_deg=20.0,
        center_lat_deg=10.0,
        sun_lon_deg=30.0,
        sun_lat_deg=10.0,
        model=_model(),
        ocean_mask=ocean,
        view_samples=4,
    )
    reference = render_globe_atmosphere(surface, cloud, **kwargs)
    spin = SpinRenderer(surface, cloud, **kwargs)
    np.testing.assert_array_equal(spin.frame(0.0), reference)


def test_rotation_wraps_and_moves() -> None:
    surface, cloud = _textures()
    spin = SpinRenderer(
        surface,
        cloud,
        res=96,
        center_lon_deg=20.0,
        center_lat_deg=10.0,
        sun_lon_deg=30.0,
        sun_lat_deg=10.0,
        model=_model(),
        view_samples=4,
    )
    first = spin.frame(0.0)
    wrapped = spin.frame(360.0)
    quarter = spin.frame(90.0)
    np.testing.assert_array_equal(first, wrapped)
    assert not np.array_equal(first, quarter)
    assert first.shape == (96, 96, 3)
    assert first.dtype == np.uint8
