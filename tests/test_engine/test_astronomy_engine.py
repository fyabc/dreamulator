"""Integration tests for the AstronomyEngine."""

from pathlib import Path

import pytest
import yaml

from dreamulator.engine.astronomy import AstronomyEngine
from dreamulator.models.layers import Layer


@pytest.fixture
def earth_like_world(tmp_path: Path) -> Path:
    """Create a temporary world with a solar-type star."""
    world_dir = tmp_path / "test_world"
    input_dir = world_dir / "layers" / "astronomy" / "input"
    input_dir.mkdir(parents=True)

    stellar_data = {
        "name": "Test System",
        "stars": [
            {
                "id": "star_test",
                "name": "Test Star",
                "spectral_class": "G",
                "luminosity_class": "V",
                "mass": 1.0,
                "luminosity": 1.0,
                "temperature": 5778.0,
                "radius": 1.0,
                "metallicity": 0.0,
                "age_gyr": 4.6,
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            }
        ],
        "orbits": [
            {
                "body_id": "planet_test",
                "parent_id": "star_test",
                "semi_major_axis_au": 1.0,
                "eccentricity": 0.017,
                "inclination_deg": 0.0,
                "longitude_ascending_node_deg": 0.0,
                "argument_of_periapsis_deg": 102.9,
                "mean_anomaly_epoch_deg": 357.5,
                "epoch_year": 0.0,
            }
        ],
    }

    with (input_dir / "stellar.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(stellar_data, f, encoding="utf-8")

    return world_dir


@pytest.fixture
def luminosity_only_world(tmp_path: Path) -> Path:
    """Create a temporary world with luminosity-only star (hybrid mode)."""
    world_dir = tmp_path / "lum_world"
    input_dir = world_dir / "layers" / "astronomy" / "input"
    input_dir.mkdir(parents=True)

    stellar_data = {
        "name": "Luminosity System",
        "stars": [
            {
                "id": "star_lum",
                "name": "Lum Star",
                "spectral_class": "M",
                "luminosity_class": "V",
                "mass": None,
                "luminosity": 0.027,
                "metallicity": 0.0,
                "age_gyr": 5.0,
            }
        ],
        "orbits": [],
    }

    with (input_dir / "stellar.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(stellar_data, f)

    return world_dir


@pytest.fixture
def inconsistent_world(tmp_path: Path) -> Path:
    """Create a world with inconsistent mass and luminosity."""
    world_dir = tmp_path / "inc_world"
    input_dir = world_dir / "layers" / "astronomy" / "input"
    input_dir.mkdir(parents=True)

    stellar_data = {
        "name": "Inconsistent System",
        "stars": [
            {
                "id": "star_inc",
                "name": "Inc Star",
                "spectral_class": "G",
                "luminosity_class": "V",
                "mass": 1.0,
                "luminosity": 5.0,  # Way too high for M=1
                "metallicity": 0.0,
                "age_gyr": 4.6,
            }
        ],
        "orbits": [],
    }

    with (input_dir / "stellar.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(stellar_data, f)

    return world_dir


def _make_engine(world_dir: Path) -> AstronomyEngine:
    """Helper to create an engine with proper paths."""
    input_dir = world_dir / "layers" / "astronomy" / "input"
    output_dir = world_dir / "layers" / "astronomy" / "derived"
    return AstronomyEngine(
        world_dir=world_dir,
        seed=42,
        layer_input_dirs={"astronomy": input_dir},
        layer_derived_dirs={},
        layer_output_dir=output_dir,
    )


class TestAstronomyEngine:
    def test_solar_type_star(self, earth_like_world: Path):
        """Engine computes correct derived params for a solar-type star."""
        engine = _make_engine(earth_like_world)
        result = engine.run()

        assert result.success
        assert result.engine_name == "astronomy"
        assert len(result.warnings) == 0
        assert result.metadata["num_stars"] == 1

        # Check output files exist
        derived_path = earth_like_world / "layers" / "astronomy" / "derived"
        assert (derived_path / "stellar_derived.yaml").exists()
        assert (derived_path / "habitable_zones.yaml").exists()

        # Validate stellar_derived.yaml content
        with (derived_path / "stellar_derived.yaml").open(encoding="utf-8") as f:
            derived = yaml.safe_load(f)
        star = derived["stars"][0]
        assert star["id"] == "star_test"
        assert star["computed_luminosity"] == pytest.approx(1.0, rel=0.01)
        assert star["computed_temperature"] == pytest.approx(5772.0, rel=0.01)
        assert star["input_mode"] == "both"

    def test_habitable_zone_output(self, earth_like_world: Path):
        """HZ boundaries are written correctly."""
        engine = _make_engine(earth_like_world)
        engine.run()

        hz_path = earth_like_world / "layers" / "astronomy" / "derived" / "habitable_zones.yaml"
        with hz_path.open(encoding="utf-8") as f:
            hz = yaml.safe_load(f)

        star_hz = hz["stars"][0]
        assert star_hz["id"] == "star_test"
        assert "runaway_greenhouse_au" in star_hz["habitable_zone"]
        assert "water_snow_line_au" in star_hz["condensation_lines"]

    def test_luminosity_only_mode(self, luminosity_only_world: Path):
        """Hybrid mode: luminosity-only input inverts to mass."""
        engine = _make_engine(luminosity_only_world)
        result = engine.run()

        assert result.success
        assert len(result.warnings) == 0

        derived_path = luminosity_only_world / "layers" / "astronomy" / "derived"
        with (derived_path / "stellar_derived.yaml").open(encoding="utf-8") as f:
            derived = yaml.safe_load(f)
        star = derived["stars"][0]
        assert star["input_mode"] == "luminosity"
        assert star["computed_mass"] is not None
        assert star["computed_mass"] > 0

    def test_inconsistent_mass_luminosity_warns(self, inconsistent_world: Path):
        """Mass=1 with L=5 triggers a consistency warning."""
        engine = _make_engine(inconsistent_world)
        result = engine.run()

        assert result.success
        assert len(result.warnings) == 1
        assert "deviation" in result.warnings[0].lower()

    def test_missing_input_fails(self, tmp_path: Path):
        """Engine fails gracefully when stellar.yaml is missing."""
        engine = AstronomyEngine(
            world_dir=tmp_path,
            seed=42,
            layer_input_dirs={},
            layer_derived_dirs={},
            layer_output_dir=tmp_path / "derived",
        )
        result = engine.run()
        assert not result.success
        assert "not found" in result.warnings[0].lower()
