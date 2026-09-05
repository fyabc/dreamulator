"""Tests for water_bodies land/ocean classification helpers."""

from dreamulator.map.models import VoronoiCell
from dreamulator.map.water_bodies import (
    compute_land_mask,
    upgrade_large_endorheic_lakes,
)


def _cell(
    cid: int,
    elev: float,
    neighbors: list[int],
    *,
    is_lake: bool = False,
    area_km2: float = 1000.0,
) -> VoronoiCell:
    return VoronoiCell(
        id=cid,
        lon=float(cid),
        lat=0.0,
        elevation=elev,
        crust_type="oceanic" if elev < 0 else "continental",
        neighbors=neighbors,
        area_km2=area_km2,
        is_lake=is_lake,
    )


def _toy_world() -> list[VoronoiCell]:
    """A 1D strip world:

    cells 0-2   global ocean (elev -1000, connected)
    cells 3-5   land rim (elev +100)
    cells 6-8   LARGE endorheic lake (elev -100, is_lake, 25k km² each = 75k ≥ 60k)
    cells 9-10  SMALL endorheic lake (elev -50, is_lake, 10k each = 20k < 60k)
    cells 11-12 DRY endorheic basin (elev -100, NOT is_lake, 40k each = 80k)
    """
    cells = [
        _cell(0, -1000.0, [1]),
        _cell(1, -1000.0, [0, 2]),
        _cell(2, -1000.0, [1, 3]),
        _cell(3, 100.0, [2, 4]),
        _cell(4, 100.0, [3, 5]),
        _cell(5, 100.0, [4, 6, 9, 11]),
        _cell(6, -100.0, [5, 7], is_lake=True, area_km2=25_000.0),
        _cell(7, -100.0, [6, 8], is_lake=True, area_km2=25_000.0),
        _cell(8, -100.0, [7], is_lake=True, area_km2=25_000.0),
        _cell(9, -50.0, [5, 10], is_lake=True, area_km2=10_000.0),
        _cell(10, -50.0, [9], is_lake=True, area_km2=10_000.0),
        _cell(11, -100.0, [5, 12], area_km2=40_000.0),
        _cell(12, -100.0, [11], area_km2=40_000.0),
    ]
    return cells


class TestComputeLandMask:
    def test_only_global_ocean_is_water(self):
        cells = _toy_world()
        land = compute_land_mask(cells, sea_level_m=0.0)
        # Global ocean cells (0-2) are water; everything else land — including
        # the endorheic basins (dry or lake) which connectivity treats as land.
        assert not land[0] and not land[1] and not land[2]
        assert land[3:].all()


class TestUpgradeLargeEndorheicLakes:
    def _prepare(self) -> list[VoronoiCell]:
        cells = _toy_world()
        land = compute_land_mask(cells, sea_level_m=0.0)
        for i, c in enumerate(cells):
            c.water_class = "land" if bool(land[i]) else "ocean"
        return cells

    def test_large_endorheic_lake_upgraded(self):
        cells = self._prepare()
        n = upgrade_large_endorheic_lakes(cells, sea_level_m=0.0)
        assert n == 3  # the large lake's cells
        assert all(cells[i].water_class == "ocean" for i in (6, 7, 8))

    def test_small_lake_stays_land(self):
        cells = self._prepare()
        upgrade_large_endorheic_lakes(cells, sea_level_m=0.0)
        assert all(cells[i].water_class == "land" for i in (9, 10))

    def test_dry_endorheic_basin_stays_land(self):
        # A below-sea-level basin that is NOT a lake (Turpan analogue) is dry
        # land regardless of size — only is_lake water bodies upgrade.
        cells = self._prepare()
        upgrade_large_endorheic_lakes(cells, sea_level_m=0.0)
        assert all(cells[i].water_class == "land" for i in (11, 12))

    def test_global_ocean_untouched(self):
        cells = self._prepare()
        upgrade_large_endorheic_lakes(cells, sea_level_m=0.0)
        assert all(cells[i].water_class == "ocean" for i in (0, 1, 2))

    def test_zero_upgraded_when_no_large_lakes(self):
        cells = [
            _cell(0, -1000.0, [1]),
            _cell(1, -1000.0, [0, 2]),
            _cell(2, 100.0, [1]),
        ]
        land = compute_land_mask(cells, sea_level_m=0.0)
        for i, c in enumerate(cells):
            c.water_class = "land" if bool(land[i]) else "ocean"
        assert upgrade_large_endorheic_lakes(cells, sea_level_m=0.0) == 0
