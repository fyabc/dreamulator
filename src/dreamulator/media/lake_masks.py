"""Shared lake-surface masks for the hydrology chains.

The filled surface is the water level.  ``lake_mask`` detects closed basins
deeper than 5 m as lake *seeds* (the TD-noise gate); the actual water body of
an accepted lake is the filled-surface component containing those seeds, which
includes the shallow rim.  Using the seeds alone for drawing or for breaking
the channel network leaves drainage routing along the deep-core edge, which
reads on the sheet as rivers hugging the lake shore.
"""

from __future__ import annotations

import numpy as np

__all__ = ["lake_footprint"]


def lake_footprint(
    seeds: np.ndarray,
    filled: np.ndarray,
    dem: np.ndarray,
    min_fill_m: float = 0.5,
) -> np.ndarray:
    """Grow lake seed cores to their full filled-surface footprint.

    ``filled`` and ``dem`` are on the same grid (metres).  The footprint is
    the connected component of ``filled - dem > min_fill_m`` that contains a
    seed cell, so shallow basins that never reach the core threshold stay
    excluded while an accepted lake keeps its shallow rim.
    """
    from scipy.ndimage import label

    wet = (filled - dem) > min_fill_m
    lab, n = label(wet)
    ids = np.unique(lab[seeds])
    ids = ids[ids > 0]
    if ids.size == 0 or n == 0:
        return seeds
    return np.asarray(np.isin(lab, ids))
