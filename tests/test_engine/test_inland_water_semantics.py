"""Cross-layer inland-water invariants (water_class × is_lake semantics).

The chimeric-state bug (water_class=land + is_lake=True + biome=ocean +
NPP/soil=None + habitability=0) came from downstream engines using a bare
``elevation < 0`` as the land/ocean test.  These tests pin the semantics:

- land-class lake cells are explicit lake surfaces (biome="lake", no soil,
  no province, uninhabitable), never "ocean";
- land cells near a lake get the freshwater habitability bonus;
- ``resolve_land_mask`` falls back to connectivity when water_class was
  never written (legacy meshes deserialize as all-"ocean" defaults).
"""

from __future__ import annotations

from pydantic import TypeAdapter

from dreamulator.engine.civilization import CivilizationEngine
from dreamulator.engine.habitability import FRESHWATER_BONUS, habitability_score
from dreamulator.map.biogeography import partition_biogeographic_provinces
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.water_bodies import resolve_land_mask


def _cell(
    cid: int,
    lon: float,
    elev: float,
    *,
    water_class: str = "land",
    is_lake: bool = False,
    temperature: float = 12.0,
    precip: float = 800.0,
    neighbors: list[int] | None = None,
) -> VoronoiCell:
    return VoronoiCell(
        id=cid,
        lon=lon,
        lat=10.0 + 0.01 * cid,
        elevation=elev,
        crust_type="continental",
        water_class=water_class,
        is_lake=is_lake,
        temperature_C=temperature,
        precipitation_mm=precip,
        temperature_hottest_month_C=temperature + 10.0,
        distance_to_coast_km=0.0 if water_class == "ocean" else 500.0,
        neighbors=neighbors or [],
    )


# ---------------------------------------------------------------------------
# resolve_land_mask — water_class authoritative + connectivity fallback
# ---------------------------------------------------------------------------


def test_resolve_land_mask_reads_water_class() -> None:
    # Land-class lake (below sea level) is land; ocean-class anything is ocean.
    cells = [
        _cell(0, 0.0, 200.0, water_class="land"),
        _cell(1, 10.0, -50.0, water_class="land", is_lake=True),
        _cell(2, 20.0, -500.0, water_class="ocean"),
        _cell(3, 30.0, 5.0, water_class="ocean"),  # shallow "ocean" class
    ]
    mask = resolve_land_mask(cells)
    assert list(mask) == [True, True, False, False]


def test_resolve_land_mask_fallback_for_legacy_mesh() -> None:
    # No water_class written anywhere (model default "ocean"): the mask must
    # fall back to connectivity, not leave everything ocean.  Mesh = one big
    # water basin (ids 1..2) + land ring, so ids 1,2 are the global ocean.
    cells = [
        _cell(0, 0.0, 100.0, neighbors=[1]),
        _cell(1, 10.0, -500.0, neighbors=[0, 2]),
        _cell(2, 20.0, -500.0, neighbors=[1, 3]),
        _cell(3, 30.0, 100.0, neighbors=[2]),
    ]
    for c in cells:
        c.water_class = "ocean"  # simulate the unclassified default
    mask = resolve_land_mask(cells)
    assert list(mask) == [True, False, False, True]


# ---------------------------------------------------------------------------
# Ecology lake semantics (via pure function) + civilization integration
# ---------------------------------------------------------------------------


def test_habitability_score_freshwater_bonus() -> None:
    base = habitability_score(temperature_c=12.0, precipitation_mm=800.0)
    near = habitability_score(temperature_c=12.0, precipitation_mm=800.0, near_freshwater=True)
    assert base > 0
    assert near == min(100.0, base * FRESHWATER_BONUS)
    # Ocean cells never get the bonus.
    assert (
        habitability_score(
            temperature_c=12.0, precipitation_mm=800.0, is_ocean=True, near_freshwater=True
        )
        == 0.0
    )


def _build_lake_world_mesh() -> CVTMesh:
    """5 cells: land(0) — land(1) — lake(2) — land(3) — ocean(4).

    Cell 1 is adjacent to the lake (gets the freshwater bonus), cell 0 is not
    (same climate, so any score difference is the bonus alone).  Cells 1 and 3
    are direct neighbours (a real Voronoi mesh gives shore cells on opposite
    sides of a narrow lake a shared edge), so removing the lake cell does not
    split the landmass.
    """
    cells = [
        _cell(0, 0.0, 200.0, temperature=12.0, precip=800.0, neighbors=[1]),
        _cell(1, 10.0, 150.0, temperature=12.0, precip=800.0, neighbors=[0, 2, 3]),
        _cell(2, 20.0, -50.0, is_lake=True, neighbors=[1, 3]),
        _cell(3, 30.0, 180.0, temperature=12.0, precip=800.0, neighbors=[1, 2, 4]),
        _cell(4, 40.0, -500.0, water_class="ocean", neighbors=[3]),
    ]
    adjacency = {str(c.id): c.neighbors for c in cells}
    return CVTMesh(seed=7, num_cells=len(cells), cells=cells, adjacency=adjacency)


def test_civilization_lake_semantics_and_freshwater_bonus(tmp_path) -> None:
    mesh = _build_lake_world_mesh()
    planet_dir = tmp_path / "maps" / "p"
    planet_dir.mkdir(parents=True)
    (planet_dir / "cvt_mesh.json").write_bytes(TypeAdapter(CVTMesh).dump_json(mesh))
    geo_input = tmp_path / "layers" / "geological" / "input"
    geo_input.mkdir(parents=True)
    (geo_input / "planets.yaml").write_text(
        "planets:\n  - id: p\n    name: P\n    orbits: star_a\n    mass: 1.0\n    radius: 1.0\n",
        encoding="utf-8",
    )
    eco_derived = tmp_path / "layers" / "ecology" / "derived"
    eco_derived.mkdir(parents=True)

    engine = CivilizationEngine(
        tmp_path,
        seed=7,
        layer_input_dirs={"geological": geo_input},
        layer_derived_dirs={"geological": geo_input, "ecology": eco_derived},
        layer_output_dir=tmp_path / "layers" / "civilization" / "derived",
        maps_output_dir=tmp_path / "maps",
    )
    result = engine.run()
    assert result.success, result.warnings

    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model

    mesh_file = find_mesh_file(planet_dir)
    assert mesh_file is not None
    out = load_cvt_mesh_model(mesh_file)
    by_id = {c.id: c for c in out.cells}

    # Lake surface: uninhabitable, not agricultural.
    assert by_id[2].habitability_score == 0.0
    assert by_id[2].habitable_coast is False
    assert by_id[2].agricultural_core is False
    assert by_id[2].agriculture_score == 0.0

    # Freshwater bonus: cell 1 borders the lake, cell 0 does not; identical
    # climate → the only difference is the bonus.
    s0 = by_id[0].habitability_score
    s1 = by_id[1].habitability_score
    assert s0 > 0
    assert s1 == min(100.0, s0 * FRESHWATER_BONUS)

    # Land near the ocean only (cell 3) gets no freshwater bonus from the
    # lake through the ocean cell — but it does border the lake directly, so
    # it also gets the bonus.  Cell 0 is the clean control.
    s3 = by_id[3].habitability_score
    assert s3 == min(100.0, s0 * FRESHWATER_BONUS)


def test_biogeography_lake_excluded_but_realm_connected() -> None:
    mesh = _build_lake_world_mesh()
    # Give every land cell the same biome so provinces don't split by biome.
    for c in mesh.cells:
        if c.water_class == "land" and not c.is_lake:
            c.biome = "temperate_forest"
    province_ids, meta = partition_biogeographic_provinces(mesh)

    by_id = {c.id: i for i, c in enumerate(mesh.cells)}
    # Lake + ocean cells carry no province.
    assert province_ids[by_id[2]] is None
    assert province_ids[by_id[4]] is None
    # Land on both sides of the lake is one realm (the lake is a basin inside
    # the landmass, not an ocean barrier) — same realm number.
    land_ids = [0, 1, 3]
    realms = {meta[province_ids[by_id[i]]]["realm"] for i in land_ids}
    assert len(realms) == 1


def test_lake_biome_via_classify_cell_ecology() -> None:
    from dreamulator.engine.ecology_physics import classify_cell_ecology

    # Land-class lake: is_lake short-circuits regardless of is_ocean.
    eco = classify_cell_ecology(
        temperature_c=10.0, precipitation_mm=600.0, elevation_m=-50.0, is_lake=True
    )
    assert eco.biome.value == "lake"
    assert eco.npp_gc_m2_yr is None

    # Ocean-class lake (Caspian semantics): is_lake still wins over ocean.
    eco2 = classify_cell_ecology(
        temperature_c=10.0,
        precipitation_mm=600.0,
        elevation_m=-50.0,
        is_ocean=True,
        is_lake=True,
    )
    assert eco2.biome.value == "lake"

    # A dry below-sea-level basin (Turpan): land class, not lake, not ocean.
    eco3 = classify_cell_ecology(temperature_c=12.0, precipitation_mm=100.0, elevation_m=-154.0)
    assert eco3.biome.value == "temperate_desert"
    assert eco3.npp_gc_m2_yr is not None
