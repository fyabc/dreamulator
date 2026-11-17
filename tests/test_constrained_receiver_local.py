"""Independent geometry and budget controls for the two-ring research prototype."""

import numpy as np
import pytest

from scripts.media.compare_constrained_receivers import window_crossings
from scripts.media.compare_dinf_routing import frame
from scripts.media.constrained_receiver_local import (
    accumulate,
    bilinear,
    candidates,
    clear_descent,
    crosses,
    prune_crossings,
)
from scripts.media.dinf_original import prepare


def test_rotated_plane_uses_new_direction_without_crossing_ridge() -> None:
    row, col = np.indices((9, 11))
    height = 100.0 - 2 * row - col
    prepared = prepare(height, frame(height.shape))
    rec = candidates(prepared.height_m, prepared.absorbing, prepared.d8_receiver)
    assert divmod(int(rec[4 * 11 + 5]), 11) == (6, 6)
    assert clear_descent(height, prepared.absorbing, 4, 5, 2, 1)


def test_intermediate_ridge_blocks_lower_far_endpoint() -> None:
    height = np.full((7, 7), 10.0)
    height[2, 2], height[4, 3] = 2, 0
    height[3, 2], height[3, 3] = 9, 9
    assert not clear_descent(height, np.zeros_like(height, dtype=bool), 2, 2, 2, 1)


def test_exact_derivative_rejects_hidden_uphill_between_three_decreasing_samples() -> None:
    height = np.zeros((7, 7))
    height[2:4, 2:4] = [[5, 4], [2, 5]]
    samples = [bilinear(height, 2 + 2 * t, 2 + t) for t in (0, 0.25, 0.5)]
    assert samples[0] > samples[1] > samples[2]
    assert bilinear(height, 2.875, 2.4375) < samples[2]
    assert not clear_descent(height, np.zeros_like(height, dtype=bool), 2, 2, 2, 1)


@pytest.mark.parametrize("water_cell", [(3, 2), (3, 3), (4, 3)])
def test_new_connection_cannot_skip_intermediate_or_terminal_water(water_cell) -> None:
    row, col = np.indices((7, 7))
    height = 100.0 - 2 * row - col
    stop = np.zeros_like(height, dtype=bool)
    stop[water_cell] = True
    assert not clear_descent(height, stop, 2, 2, 2, 1)


def test_flat_connections_keep_original_prepared_receivers() -> None:
    height = np.ones((9, 11))
    height[:, -1] = 0
    prepared = prepare(height, frame(height.shape))
    rec = candidates(prepared.height_m, prepared.absorbing, prepared.d8_receiver)
    flat = prepared.flat_rank.ravel() > 0
    assert flat.any()
    np.testing.assert_array_equal(rec[flat], prepared.d8_receiver.ravel()[flat])


def test_crossing_is_rejected_but_shared_receiver_is_a_valid_junction() -> None:
    nc = 7
    a, b, c, d = 2 * nc + 2, 4 * nc + 3, 3 * nc + 2, 3 * nc + 3
    assert crosses(a, b, c, d, nc)
    assert not crosses(a, b, 2 * nc + 4, b, nc)
    base = np.full(7 * nc, -1, dtype=np.int64)
    base[a], base[c] = c, d
    proposed = base.copy()
    proposed[a] = b
    actual, rejected = prune_crossings(base, proposed, np.arange(base.size), nc)
    assert rejected == 1 and actual[a] == c


def test_joined_sources_and_skipped_cells_are_counted_once() -> None:
    receiver = np.array([2, 2, 3, -1])
    source = np.array([[2.0, 3.0], [5.0, 0.0]])
    actual = accumulate(receiver, source)
    np.testing.assert_array_equal(actual, [[2, 3], [10, 10]])
    assert actual.ravel()[receiver < 0].sum() == source.sum()


def test_accumulation_rejects_cycle() -> None:
    with pytest.raises(ValueError, match="cycle"):
        accumulate(np.array([1, 0]), np.ones((1, 2)))


def test_display_audit_detects_interior_crossing_and_accepts_shared_endpoint() -> None:
    segments = np.array([[[0.0, 0], [2, 2]], [[0, 2], [2, 0]], [[2, 2], [3, 3]]])
    np.testing.assert_allclose(window_crossings(segments), [[1, 1]])
