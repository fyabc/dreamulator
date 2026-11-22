"""Star catalog geometry: HYG slice, unit directions, rotation and look mapping."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.media.starfield import (
    PALETTE,
    equatorial_directions,
    from_arrays,
    load_hyg,
    palette_from_ci,
    sky_orientation,
)

CSV = """ra_deg,dec_deg,vmag,ci
0,0,-1.0,-0.3
90,0,3.0,0.7
180,0,9.0,1.2
0,90,5.0,1.7
"""


def _write(tmp_path, text=CSV):
    path = tmp_path / "hyg.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_hyg_filters_by_magnitude(tmp_path) -> None:
    geometry = load_hyg(_write(tmp_path), mag_limit=6.0)
    assert len(geometry.strength) == 3  # vmag 9 is outside the slice
    assert geometry.directions.shape == (3, 3)


def test_directions_are_unit_vectors(tmp_path) -> None:
    geometry = load_hyg(_write(tmp_path))
    np.testing.assert_allclose(np.linalg.norm(geometry.directions, axis=1), 1.0)


def test_centre_star_lands_on_view_direction(tmp_path) -> None:
    geometry = load_hyg(_write(tmp_path), center_ra_dec=(0.0, 0.0), view_dir=(0.0, 0.0, 1.0))
    # The RA=0/Dec=0 star is first; after rotation it must point along +Z.
    np.testing.assert_allclose(geometry.directions[0], [0.0, 0.0, 1.0], atol=1e-12)


def test_rotation_matrix_is_orthonormal() -> None:
    rot = sky_orientation((84.0, -1.0), (0.0, 0.0, 1.0), up_hint=(0.0, 1.0, 0.0))
    np.testing.assert_allclose(rot @ rot.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(rot) == pytest.approx(1.0)


def test_brighter_stars_are_larger_and_stronger(tmp_path) -> None:
    geometry = load_hyg(_write(tmp_path))
    # Order follows the CSV: -1 mag, 3 mag, 5 mag.
    assert geometry.strength[0] > geometry.strength[1] > geometry.strength[2]
    assert geometry.radius_px[0] >= geometry.radius_px[1] >= geometry.radius_px[2]
    assert geometry.radius_px.min() >= 0.85
    assert geometry.radius_px.max() <= 12.0


def test_palette_endpoints_and_buckets() -> None:
    colours = palette_from_ci(np.array([-0.3, 1.7]))
    np.testing.assert_allclose(colours[0], PALETTE[0])
    np.testing.assert_allclose(colours[1], PALETTE[-1])


def test_empty_or_mismatched_arrays_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        from_arrays(np.array([]), np.array([]), np.array([]), np.array([]))
    with pytest.raises(ValueError, match="same length"):
        from_arrays(np.array([0.0]), np.array([0.0]), np.array([1.0, 2.0]), np.array([0.0]))


def test_equatorial_directions_axes() -> None:
    dirs = equatorial_directions(np.array([0.0, 90.0, 0.0]), np.array([0.0, 0.0, 90.0]))
    np.testing.assert_allclose(dirs[0], [1.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(dirs[1], [0.0, 1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(dirs[2], [0.0, 0.0, 1.0], atol=1e-12)
