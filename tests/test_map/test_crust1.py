"""Tests for CRUST1.0 crustal-type parsing + PB2002 boundary-step parsing."""

from __future__ import annotations

import numpy as np

from dreamulator.import_earth_tectonics import (
    _PB2002_STEP_TO_BOUNDARY,
    parse_pb2002_steps,
)
from dreamulator.map.crust1 import parse_crust1_type, sample_crust1


def _make_grid_text() -> str:
    """A 180×360 grid of "A1" (normal oceanic), with a small continental patch."""
    rows = []
    for i in range(180):
        codes = ["A1"] * 360
        if 40 <= i <= 44:
            for j in range(180, 185):
                codes[j] = "D-"  # continental patch at lat ~49.5N, lon ~0.5
        rows.append(" ".join(codes))
    return "\n".join(rows)


def test_parse_crust1_type_shape() -> None:
    grid = parse_crust1_type(_make_grid_text())
    assert grid.shape == (180, 360)


def test_sample_crust1_continental_and_oceanic() -> None:
    grid = parse_crust1_type(_make_grid_text())
    lats = np.array([49.5, 49.5, 0.0])
    lons = np.array([0.5, 10.5, 0.0])
    out = sample_crust1(grid, lats, lons)
    # (0.5, 49.5) → the D- patch (continental); (10.5, 49.5) and (0, 0) → A1 (oceanic).
    assert list(out) == ["continental", "oceanic", "oceanic"]


def test_parse_pb2002_steps() -> None:
    text = (
        "1 AF-AN -0.438 -54.852 -0.039 -54.677 OTF\n"
        "2 :AF-AN -0.039 -54.677 0.443 -54.451 :OTF\n"
        "3 :AF-AN 0.443 -54.451 0.965 -54.832 OSR\n"
        "4 IN-EU 70.1 29.8 70.2 30.4 CCB*\n"
    )
    steps = parse_pb2002_steps(text)
    assert len(steps) == 4
    assert steps[0] == (-0.438, -54.852, -0.039, -54.677, "OTF")
    assert steps[1][-1] == "OTF"  # ":" prefix stripped
    assert steps[2][-1] == "OSR"
    assert steps[3][-1] == "CCB"  # "*" orogen marker stripped


def test_boundary_class_mapping() -> None:
    assert _PB2002_STEP_TO_BOUNDARY["SUB"] == "convergent"
    assert _PB2002_STEP_TO_BOUNDARY["OSR"] == "divergent"
    assert _PB2002_STEP_TO_BOUNDARY["CRB"] == "divergent"
    assert _PB2002_STEP_TO_BOUNDARY["OTF"] == "transform"
    assert _PB2002_STEP_TO_BOUNDARY["CTF"] == "transform"
    assert _PB2002_STEP_TO_BOUNDARY["OCB"] == "convergent"
    assert _PB2002_STEP_TO_BOUNDARY["CCB"] == "convergent"
