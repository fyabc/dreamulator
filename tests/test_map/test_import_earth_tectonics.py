"""Tests for the PB2002 Earth tectonic-plate importer (pure functions)."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.import_earth_tectonics import (
    assign_plate_ids,
    crust_type_from_elevation,
    euler_pole_from_latlon_rate,
    parse_pb2002_plates,
    parse_pb2002_poles,
    points_in_ring,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Crust type (OCB from bathymetry)
# ---------------------------------------------------------------------------


def test_crust_type_from_elevation_thresholds() -> None:
    elev = np.array([100.0, -500.0, -2500.0, -4000.0, -10000.0])
    crust = crust_type_from_elevation(elev)
    assert list(crust) == [
        "continental",  # land
        "continental",  # shelf
        "transitional",  # continental slope (−3000..−2000)
        "oceanic",  # abyssal plain
        "oceanic",
    ]


def test_crust_type_from_elevation_matches_real_fraction() -> None:
    """The OCB split should give ~40% continental / ~60% oceanic on ETOPO1-like
    hypsometry (real Earth: ~41% continental crust incl. shelves)."""
    rng = np.random.default_rng(0)
    # Coarse synthetic hypsometry: 29% land, ~11% shelf/slope, ~60% abyss.
    elev = np.concatenate(
        [
            rng.uniform(0.0, 8000.0, 2900),  # land
            rng.uniform(-3000.0, 0.0, 1100),  # shelf + slope
            rng.uniform(-11000.0, -3000.0, 6000),  # abyss
        ]
    )
    crust = crust_type_from_elevation(elev)
    continental = float(np.count_nonzero(crust == "continental"))
    assert continental / len(elev) == pytest.approx(0.40, abs=0.05)


# ---------------------------------------------------------------------------
# Euler pole conversion
# ---------------------------------------------------------------------------


def test_euler_pole_axis_is_unit_vector() -> None:
    pole = euler_pole_from_latlon_rate(59.16, -73.174, 0.927)
    norm = math.sqrt(pole["x"] ** 2 + pole["y"] ** 2 + pole["z"] ** 2)
    assert norm == pytest.approx(1.0)
    assert pole["omega_rad_yr"] == pytest.approx(0.927 * math.pi / 180.0 / 1.0e6)


def test_euler_pole_equatorial_axis() -> None:
    # lat=0, lon=90° → axis points along +z (outward at the equator on lon 90).
    pole = euler_pole_from_latlon_rate(0.0, 90.0, 1.0)
    assert pole["x"] == pytest.approx(0.0)
    assert pole["y"] == pytest.approx(0.0)
    assert pole["z"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Point-in-polygon (2-D even-odd)
# ---------------------------------------------------------------------------


def test_points_in_ring_square() -> None:
    ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    lons = np.array([5.0, 15.0, -5.0, 5.0])
    lats = np.array([5.0, 5.0, 5.0, 20.0])
    inside = points_in_ring(lons, lats, ring)
    assert list(inside) == [True, False, False, False]


def test_assign_plate_ids_two_plates() -> None:
    plates = {
        "A": {"name": "Plate A", "rings": [[(0.0, 20.0), (20.0, 20.0), (20.0, 40.0), (0.0, 40.0)]]},
        "B": {
            "name": "Plate B",
            "rings": [[(0.0, -40.0), (20.0, -40.0), (20.0, -20.0), (0.0, -20.0)]],
        },
    }
    lons = np.array([10.0, 10.0, 50.0])
    lats = np.array([30.0, -30.0, 0.0])
    plate_id = assign_plate_ids(lons, lats, plates)
    assert list(plate_id) == ["A", "B", "A"]  # (50, 0) → nearest centroid fallback (A)


# ---------------------------------------------------------------------------
# PB2002 parsing
# ---------------------------------------------------------------------------


def test_parse_pb2002_plates_merges_multipolygon(tmp_path: Path) -> None:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {"Code": "XX", "PlateName": "Example"},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
                        [[[10.0, 10.0], [11.0, 10.0], [11.0, 11.0], [10.0, 10.0]]],
                    ],
                },
            }
        ],
    }
    path = tmp_path / "plates.json"
    path.write_text(json.dumps(geojson), encoding="utf-8")
    plates = parse_pb2002_plates(path)
    assert set(plates) == {"XX"}
    assert plates["XX"]["name"] == "Example"
    assert len(plates["XX"]["rings"]) == 2


def test_parse_pb2002_poles(tmp_path: Path) -> None:
    txt = (
        "AF   59.160   -73.174   0.9270  DeMets et al. [1994]\n"
        "EU   61.066   -85.819   0.8591  DeMets et al. [1994]\n"
    )
    path = tmp_path / "poles.txt"
    path.write_text(txt, encoding="utf-8")
    poles = parse_pb2002_poles(path)
    assert poles["AF"] == (59.160, -73.174, 0.9270)
    assert poles["EU"] == (61.066, -85.819, 0.8591)
