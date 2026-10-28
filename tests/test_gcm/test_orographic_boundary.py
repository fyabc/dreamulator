"""Datum and boundary semantics of the explicit buffered precipitation candidate."""

import numpy as np

from dreamulator.gcm.orographic import lt_parameters, orographic_precipitation_buffered

CORE = (slice(10, 30), slice(10, 30))
PARAMETERS = lt_parameters(280.0, 90000.0, 0.004, 9.80665)


def calculate(terrain, **kwargs):
    return orographic_precipitation_buffered(
        terrain, 20000.0, 15.0, 5.0, *PARAMETERS, core=CORE, **kwargs
    )


def test_flat_datum_has_zero_response():
    np.testing.assert_array_equal(calculate(np.full((40, 40), 500.0)), np.zeros((20, 20)))


def test_hill_response_preserves_datum_invariance_and_linearity():
    x, y = np.meshgrid(np.arange(40) - 20, np.arange(40) - 20)
    hill = 500 * np.exp(-(x**2 + y**2) / 80)
    a = calculate(hill)
    assert np.max(abs(a)) > 1e-6
    np.testing.assert_allclose(a, calculate(hill + 1500), rtol=0, atol=1e-12 / 3600)
    np.testing.assert_allclose(2 * a, calculate(2 * hill), rtol=0, atol=1e-12 / 3600)
