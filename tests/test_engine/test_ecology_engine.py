"""Integration test for EcologyEngine.run() on a small synthetic mesh."""

from pydantic import TypeAdapter

from dreamulator.engine.ecology import EcologyEngine
from dreamulator.map.models import CVTMesh, VoronoiCell


def _build_mesh_with_climate() -> CVTMesh:
    """Four-cell mesh: two adjacent land cells (forest + grassland) + two ocean."""
    cells = [
        VoronoiCell(
            id=0,
            lon=0.0,
            lat=10.0,
            elevation=200.0,
            crust_type="continental",
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
            temperature_C=8.0,
            precipitation_mm=500.0,
            neighbors=[0, 2],
        ),
        VoronoiCell(
            id=2,
            lon=20.0,
            lat=10.0,
            elevation=-500.0,
            crust_type="oceanic",
            temperature_C=15.0,
            precipitation_mm=1000.0,
            neighbors=[1, 3],
        ),
        VoronoiCell(
            id=3,
            lon=30.0,
            lat=10.0,
            elevation=-500.0,
            crust_type="oceanic",
            temperature_C=15.0,
            precipitation_mm=1000.0,
            neighbors=[0, 2],
        ),
    ]
    adjacency = {str(c.id): c.neighbors for c in cells}
    return CVTMesh(seed=42, num_cells=4, cells=cells, adjacency=adjacency)


def _write_world(tmp_path):
    """Write a minimal world dir: maps/<planet>/cvt_mesh.json + planets.yaml."""
    planet_dir = tmp_path / "maps" / "satellite_gaiam"
    planet_dir.mkdir(parents=True)
    mesh = _build_mesh_with_climate()
    (planet_dir / "cvt_mesh.json").write_bytes(TypeAdapter(CVTMesh).dump_json(mesh))

    geo_input = tmp_path / "layers" / "geological" / "input"
    geo_input.mkdir(parents=True)
    (geo_input / "planets.yaml").write_text(
        "planets:\n"
        "  - id: satellite_gaiam\n"
        "    name: Gaiam\n"
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
    from dreamulator.map.export import decompress_mesh_bytes

    mesh = TypeAdapter(CVTMesh).validate_json(
        decompress_mesh_bytes((world / "maps" / "satellite_gaiam" / "cvt_mesh.json").read_bytes())
    )
    land = [c for c in mesh.cells if c.crust_type == "continental"]
    ocean = [c for c in mesh.cells if c.crust_type != "continental"]
    assert len(land) == 2 and len(ocean) == 2
    for c in land:
        assert c.soil_type is not None
        assert c.soil_fertility is not None
        assert c.biogeographic_province is not None
    for c in ocean:
        assert c.soil_type is None
        assert c.biogeographic_province is None

    # Summary YAML written.
    assert (world / "layers" / "ecology" / "derived" / "ecology_summary.yaml").exists()
