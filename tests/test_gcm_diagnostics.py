"""Tests for gcm.diagnostics pure helpers (no NetCDF fixtures needed)."""

from __future__ import annotations

import numpy as np

from dreamulator.gcm.diagnostics import equinox_day_from_declination, orbital_phase_of_records


def test_phase_wraps_within_orbital_year() -> None:
    # nacrea: 32 steps/day, orbital year 99.8 d, model calendar 120 d/yr.
    # Records every 30 model days (960 steps) over 2 model years (2400 d):
    # phase must wrap ~24 times, not follow the model-calendar month index.
    time_axis = np.arange(480, 24 * 960 + 481, 960, dtype=float)  # mid-window
    phase = orbital_phase_of_records(time_axis, orbital_year_days=99.8)
    assert phase.shape == time_axis.shape
    assert ((phase >= 0.0) & (phase < 1.0)).all()
    # consecutive 30-day windows advance phase by 30/99.8 ≈ 0.3006 (mod 1)
    d = np.diff(phase) % 1.0
    assert np.allclose(d, 30.0 / 99.8, atol=1e-9)


def test_perihelion_offset_shifts_phase_origin() -> None:
    time_axis = np.array([7168.0])  # day 224 = e.g. perihelion at 22.9 d
    raw = orbital_phase_of_records(time_axis, orbital_year_days=99.8)
    shifted = orbital_phase_of_records(time_axis, orbital_year_days=99.8, perihelion_day=22.9)
    assert np.isclose((raw[0] - shifted[0]) % 1.0, 22.9 / 99.8)


def test_equinox_day_recovers_declination_phase() -> None:
    year, spd = 99.8, 32.0
    days = np.arange(0.0, 5 * year, 10.0) + 3.0
    equinox = 37.0
    zdec = 20.0 * np.sin(2 * np.pi * (days - equinox) / year)
    got = equinox_day_from_declination(
        days * spd, zdec, orbital_year_days=year, steps_per_model_day=spd
    )
    assert abs(got - equinox) < 1e-6
