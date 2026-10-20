"""Lake footprint expansion (seed cores -> filled-surface water body)."""

from __future__ import annotations

import numpy as np

from dreamulator.media.lake_masks import lake_footprint


def test_footprint_grows_core_through_shallow_rim() -> None:
    # A bowl: 3 m rim around a 10 m core, plus an unrelated shallow puddle.
    dem = np.zeros((40, 60), dtype=np.float64)
    yy, xx = np.mgrid[0:40, 0:60]
    core = (yy - 20) ** 2 + (xx - 20) ** 2 <= 6**2
    rim = (yy - 20) ** 2 + (xx - 20) ** 2 <= 12**2
    dem[rim] = 97.5
    dem[core] = 94.0
    puddle = (yy - 32) ** 2 + (xx - 48) ** 2 <= 3**2
    dem[puddle] = 98.0
    filled = dem.copy()
    filled[rim] = 100.0  # water level: 100 m over the bowl, 2.5 m deep rim
    filled[core] = 100.0
    filled[puddle] = 99.5  # 1.5 m deep, but not connected to a seeded core

    seeds = np.zeros_like(core)
    seeds[core] = True
    foot = lake_footprint(seeds, filled, dem)
    assert foot[rim].all()  # shallow rim joins the water body
    assert not foot[puddle].any()  # unseeded shallow basin stays dry
    assert int(foot.sum()) == int(rim.sum())
