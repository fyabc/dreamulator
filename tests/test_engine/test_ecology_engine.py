"""Integration test for EcologyEngine.run() on a small synthetic mesh."""

import pytest
from pydantic import TypeAdapter

from dreamulator.engine.ecology import EcologyEngine
from dreamulator.map.models import CVTMesh, VoronoiCell


def _build_mesh_with_climate() -> CVTMesh:
    """Six-cell mesh: two land, one lake (land-class), three ocean.

    water_class is written explicitly — the authoritative water split — so the
    lake cell (water_class="land" + is_lake=True, elevation below sea level)
    exercises the inland-water semantics that a bare elevation sign misses.
    """
    cells = [
        VoronoiCell(
            id=0,
            lon=0.0,
            lat=10.0,
            elevation=200.0,
            crust_type="continental",
            water_class="land",
            temperature_C=12.0,
            precipitation_mm=800.0,
            neighbors=[1, 3],
        ),
        VoronoiCell(
            id=1,
            lon=10.0,
            lat=10.0,
            elevation=100.0,
            crust_type="continental",
            water_class="land",
            temperature_C=8.0,
            precipitation_mm=500.0,
            neighbors=[0, 2],
        ),
        VoronoiCell(
            id=2,
            lon=20.0,
            lat=10.0,
            elevation=-50.0,
            crust_type="continental",
            water_class="land",
            is_lake=True,
            temperature_C=10.0,
            precipitation_mm=600.0,
            neighbors=[1, 3],
        ),
        VoronoiCell(
            id=3,
            lon=30.0,
            lat=10.0,
            elevation=-500.0,
            crust_type="oceanic",
            water_class="ocean",
            temperature_C=15.0,
            precipitation_mm=1000.0,
            neighbors=[0, 2],
        ),
    ]
    adjacency = {str(c.id): c.neighbors for c in cells}
    return CVTMesh(seed=42, num_cells=4, cells=cells, adjacency=adjacency)


def _write_world(tmp_path):
    """Write a minimal world dir: maps/<planet>/cvt_mesh.json + planets.yaml."""
    planet_dir = tmp_path / "maps" / "satellite_nacrea"
    planet_dir.mkdir(parents=True)
    mesh = _build_mesh_with_climate()
    (planet_dir / "cvt_mesh.json").write_bytes(TypeAdapter(CVTMesh).dump_json(mesh))

    geo_input = tmp_path / "layers" / "geological" / "input"
    geo_input.mkdir(parents=True)
    (geo_input / "planets.yaml").write_text(
        "planets:\n"
        "  - id: satellite_nacrea\n"
        "    name: Nacrea\n"
        "    orbits: star_a\n"
        "    mass: 1.0\n"
        "    radius: 1.0\n",
        encoding="utf-8",
    )
    return tmp_path


def test_ecology_engine_populates_p1_fields(tmp_path) -> None:
    world = _write_world(tmp_path)
    engine = EcologyEngine(
        world,
        seed=42,
        layer_input_dirs={"geological": world / "layers" / "geological" / "input"},
        layer_derived_dirs={"ecology": world / "layers" / "ecology" / "derived"},
        layer_output_dir=world / "layers" / "ecology" / "derived",
        maps_output_dir=world / "maps",
    )
    result = engine.run()
    assert result.success, result.warnings

    # Reload the mesh and assert P1 fields are populated on land, None on ocean.
    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model

    mesh_file = find_mesh_file(world / "maps" / "satellite_nacrea")
    if mesh_file is None:
        pytest.skip("nacrea mesh not available (LFS not pulled or not built)")
    mesh = load_cvt_mesh_model(mesh_file)
    land = [c for c in mesh.cells if c.water_class == "land" and not c.is_lake]
    lake = [c for c in mesh.cells if c.is_lake]
    ocean = [c for c in mesh.cells if c.water_class == "ocean" and not c.is_lake]
    assert len(land) == 2 and len(ocean) == 1 and len(lake) == 1
    for c in land:
        assert c.soil_type is not None
        assert c.soil_fertility is not None
        assert c.biogeographic_province is not None
        assert c.biome != "ocean"
        assert c.npp_gc_m2_yr is not None
    for c in ocean:
        assert c.soil_type is None
        assert c.biogeographic_province is None
        assert c.biome == "ocean"
    # Inland-water invariants: a lake cell never materialises the chimeric
    # state (water_class=land + biome=ocean + NPP/soil=None + habitability=0
    # with no lake semantics) — it is an explicit lake surface instead.
    for c in lake:
        assert c.biome == "lake"
        assert c.npp_gc_m2_yr is None
        assert c.soil_type is None
        assert c.biogeographic_province is None

    # Summary YAML written.
    assert (world / "layers" / "ecology" / "derived" / "ecology_summary.yaml").exists()

    # Summary water-split stats follow water_class (not crust_type), with the
    # lake broken out: 2 land + 1 lake + 1 ocean here.
    import yaml

    summary = yaml.safe_load(
        (world / "layers" / "ecology" / "derived" / "ecology_summary.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert summary["n_land"] == 2
    assert summary["n_ocean"] == 1
    assert summary["n_lake"] == 1
    assert summary["biome_counts"].get("lake") == 1
