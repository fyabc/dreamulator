"""Seeded random number generator for reproducible simulations."""

import numpy as np
from numpy.random import Generator


def create_rng(seed: int) -> Generator:
    """Create a seeded numpy random generator.

    Uses PCG64 bit generator for high-quality randomness and reproducibility.

    Args:
        seed: Integer seed value.

    Returns:
        A numpy random Generator instance.
    """
    return np.random.default_rng(seed)
