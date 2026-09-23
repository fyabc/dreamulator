"""Tests for build bootstrap (M1-P0 / audit BUILD-01/02, 2026-09-17).

Covers:

1. **Astronomy auto-bootstrap** — a branch forking at climate excludes the
   astronomy engine; when the source-context derived inputs are missing
   (fresh checkout), the pipeline builds them in the *root* world context
   instead of failing with an opaque "Missing input file".
2. **Imported-terrain honest failure** — ``elevation_source: imported`` with
   no mesh on disk fails with recovery instructions, never a silent success.
3. **Planet-scoped mesh selection** — the exact ``maps/{planet_id}/`` mesh is
   preferred over the first glob hit; ``_``-prefixed scratch dirs are skipped.
4. **Branch mesh isolation** — a branch build inheriting the root world's
   mesh materializes a branch-local copy; the parent mesh file is never
   modified by the branch's field write-backs.
"""

from pathlib import Path

import yaml

from dreamulator.engine.astronomy import AstronomyEngine
from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.climate import (
    _load_cvt_mesh_from_geological,
    _materialize_writable_mesh,
)
from dreamulator.engine.geological import GeologicalEngine
from dreamulator.engine.pipeline import run_pipeline
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.models.layers import Layer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_stellar_yaml(world_dir: Path) -> None:
    """Minimal solar-type stellar.yaml in the astronomy input layer."""
    input_dir = world_dir / "layers" / "astronomy" / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    stellar_data = {
        "name": "Test System",
        "stars": [
            {
                "id": "star_test",
                "name": "Test Star",
                "spectral_class": "G2",
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
            }
        ],
    }
    with (input_dir / "stellar.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(stellar_data, f, encoding="utf-8")


def _write_planets_yaml(world_dir: Path, planet_id: str = "planet_test") -> None:
    """Minimal planets.yaml in the geological input layer."""
    geo_dir = world_dir / "layers" / "geological" / "input"
    geo_dir.mkdir(parents=True, exist_ok=True)
    planets_data = {
        "planets": [
            {
                "id": planet_id,
                "name": planet_id,
                "orbits": "star_test",
                "mass": 1.0,
                "radius": 1.0,
                "rotation_period_days": 0.997,
                "axial_tilt_deg": 23.44,
                "albedo": 0.3,
            }
        ]
    }
    with (geo_dir / "planets.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(planets_data, f, encoding="utf-8")


def _write_branch(world_dir: Path, branch: str, fork_layer: str) -> None:
    """branch.yaml for a branch forking at the given layer."""
    branch_dir = world_dir / "branches" / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    with (branch_dir / "branch.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(
            {
                "name": branch,
                "parent": None,
                "fork_layer": fork_layer,
                "created": "2026-09-17",
                "description": "test branch",
            },
            f,
            encoding="utf-8",
        )


def _write_mesh(path: Path, seed: int = 42, lon: float = 1.0) -> None:
    """Write a minimal one-cell CVT mesh (plain JSON — decompression is transparent)."""
    mesh = CVTMesh(seed=seed, num_cells=1, cells=[VoronoiCell(id=0, lon=lon, lat=2.0)])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mesh.model_dump_json(), encoding="utf-8")


class _DownstreamEngine(BaseEngine):
    """Stand-in for the climate engine: requires astronomy-derived input."""

    name = "downstream"
    layer = Layer.CLIMATE
    requires: list[str] = ["astronomy"]
    input_files = ["stellar_derived.yaml"]
    output_files = ["downstream_out.yaml"]

    def run(self, parameters=None, *, force: bool = False) -> EngineResult:
        out = self.output_path("downstream_out.yaml")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}", encoding="utf-8")
        return EngineResult(
            engine_name=self.name, success=True, output_files=["downstream_out.yaml"]
        )


# ---------------------------------------------------------------------------
# 1. Astronomy auto-bootstrap on a forked branch
# ---------------------------------------------------------------------------


class TestAstronomyBootstrap:
    def test_climate_fork_bootstraps_root_astronomy(self, tmp_path: Path) -> None:
        world = tmp_path / "world"
        _write_stellar_yaml(world)
        _write_planets_yaml(world)
        _write_branch(world, "cl-fork", "climate")

        # Fresh checkout: no astronomy derived anywhere.
        assert not (world / "layers" / "astronomy" / "derived").exists()

        results = run_pipeline(
            [AstronomyEngine, _DownstreamEngine], world, seed=42, branch="cl-fork"
        )

        # The downstream engine ran and succeeded (bootstrap results are not
        # part of the main-loop result list — only its side effect is).
        assert [r.engine_name for r in results] == ["downstream"]
        assert all(r.success for r in results)

        # Derived astronomy data was built in the ROOT context …
        root_derived = world / "layers" / "astronomy" / "derived"
        assert (root_derived / "stellar_derived.yaml").exists()
        # … never in the branch.
        assert not (world / "branches" / "cl-fork" / "layers" / "astronomy").exists()
        # Downstream output lands in the branch.
        branch_out = (
            world
            / "branches"
            / "cl-fork"
            / "layers"
            / "climate"
            / "derived"
            / "downstream_out.yaml"
        )
        assert branch_out.exists()

    def test_no_bootstrap_when_derived_exists(self, tmp_path: Path) -> None:
        world = tmp_path / "world"
        _write_stellar_yaml(world)
        _write_planets_yaml(world)
        _write_branch(world, "cl-fork", "climate")

        # Pre-build astronomy at the root, recording its output timestamp.
        run_pipeline([AstronomyEngine], world, seed=42)
        derived = world / "layers" / "astronomy" / "derived" / "stellar_derived.yaml"
        first_mtime = derived.stat().st_mtime

        results = run_pipeline(
            [AstronomyEngine, _DownstreamEngine], world, seed=42, branch="cl-fork"
        )

        # No astronomy result: nothing was re-run (only downstream ran).
        assert [r.engine_name for r in results] == ["downstream"]
        assert derived.stat().st_mtime == first_mtime

    def test_root_build_is_unaffected(self, tmp_path: Path) -> None:
        """Root builds run astronomy normally — no bootstrap path involved."""
        world = tmp_path / "world"
        _write_stellar_yaml(world)
        _write_planets_yaml(world)

        results = run_pipeline([AstronomyEngine, _DownstreamEngine], world, seed=42)
        assert [r.engine_name for r in results] == ["astronomy", "downstream"]
        assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# 2. Imported-terrain honest failure
# ---------------------------------------------------------------------------


class TestImportedGuard:
    def _make_engine(self, world: Path) -> GeologicalEngine:
        return GeologicalEngine(
            world,
            seed=42,
            layer_input_dirs={
                Layer.ASTRONOMY.value: world / "layers" / "astronomy" / "input",
                Layer.GEOLOGICAL.value: world / "layers" / "geological" / "input",
            },
            layer_derived_dirs={},
            layer_output_dir=world / "layers" / "geological" / "derived",
            maps_output_dir=world / "maps",
        )

    def test_missing_imported_mesh_fails_with_recovery(self, tmp_path: Path) -> None:
        world = tmp_path / "world"
        _write_stellar_yaml(world)
        _write_planets_yaml(world, planet_id="earth_x")
        geo_input = world / "layers" / "geological" / "input"
        with (geo_input / "terrain_config.yaml").open("w", encoding="utf-8") as f:
            yaml.dump({"elevation_source": "imported"}, f)

        result = self._make_engine(world).run()

        assert result.success is False
        message = "\n".join(result.warnings)
        assert "imported" in message.lower()
        assert "import_earth_elevation.py" in message  # actionable recovery command

    def test_existing_imported_mesh_still_skips_successfully(self, tmp_path: Path) -> None:
        world = tmp_path / "world"
        _write_stellar_yaml(world)
        _write_planets_yaml(world, planet_id="earth_x")
        geo_input = world / "layers" / "geological" / "input"
        with (geo_input / "terrain_config.yaml").open("w", encoding="utf-8") as f:
            yaml.dump({"elevation_source": "imported"}, f)
        _write_mesh(world / "maps" / "earth_x" / "cvt_mesh.json")

        result = self._make_engine(world).run()

        assert result.success is True
        assert result.metadata.get("elevation_source") == "imported"

    def test_branch_inherits_root_imported_mesh(self, tmp_path: Path) -> None:
        """A branch forking at geological may use the root world's imported mesh."""
        world = tmp_path / "world"
        _write_stellar_yaml(world)
        _write_planets_yaml(world, planet_id="earth_x")
        geo_input = world / "layers" / "geological" / "input"
        with (geo_input / "terrain_config.yaml").open("w", encoding="utf-8") as f:
            yaml.dump({"elevation_source": "imported"}, f)
        _write_mesh(world / "maps" / "earth_x" / "cvt_mesh.json")
        _write_branch(world, "geo-fork", "geological")

        engine = GeologicalEngine(
            world,
            seed=42,
            layer_input_dirs={
                Layer.GEOLOGICAL.value: world / "layers" / "geological" / "input",
            },
            layer_derived_dirs={},
            layer_output_dir=world / "branches" / "geo-fork" / "layers" / "geological" / "derived",
            maps_output_dir=world / "branches" / "geo-fork" / "maps",
        )
        result = engine.run()

        assert result.success is True  # inherited from the root world


# ---------------------------------------------------------------------------
# 3. Planet-scoped mesh selection
# ---------------------------------------------------------------------------


class TestMeshSelection:
    def test_exact_planet_match_wins_over_first_glob(self, tmp_path: Path) -> None:
        maps = tmp_path / "maps"
        _write_mesh(maps / "alpha" / "cvt_mesh.json", seed=1, lon=10.0)
        _write_mesh(maps / "beta" / "cvt_mesh.json", seed=2, lon=20.0)

        mesh, source, warnings = _load_cvt_mesh_from_geological({}, maps_dir=maps, planet_id="beta")
        assert mesh is not None and not warnings
        assert source == maps / "beta" / "cvt_mesh.json"
        assert mesh.cells[0].lon == 20.0

    def test_scratch_dirs_are_skipped(self, tmp_path: Path) -> None:
        maps = tmp_path / "maps"
        _write_mesh(maps / "_baseline_alpha" / "cvt_mesh.json", seed=1, lon=10.0)
        _write_mesh(maps / "alpha" / "cvt_mesh.json", seed=2, lon=20.0)

        mesh, source, _ = _load_cvt_mesh_from_geological({}, maps_dir=maps, planet_id="alpha")
        assert source == maps / "alpha" / "cvt_mesh.json"
        assert mesh is not None and mesh.cells[0].lon == 20.0

    def test_no_mesh_reports_searched_paths(self, tmp_path: Path) -> None:
        mesh, source, warnings = _load_cvt_mesh_from_geological(
            {}, maps_dir=tmp_path / "maps", world_dir=tmp_path
        )
        assert mesh is None and source is None
        assert any("No mesh file" in w for w in warnings)


# ---------------------------------------------------------------------------
# 4. Branch mesh isolation (no parent write-back)
# ---------------------------------------------------------------------------


class TestBranchMeshIsolation:
    def test_inherited_root_mesh_is_materialized_into_branch(self, tmp_path: Path) -> None:
        world = tmp_path / "world"
        root_mesh = world / "maps" / "planet_x" / "cvt_mesh.json"
        _write_mesh(root_mesh, seed=7, lon=5.0)
        root_bytes = root_mesh.read_bytes()

        branch_maps = world / "branches" / "cl-fork" / "maps"

        # Loader inherits the root mesh when the branch has none.
        mesh, source, warnings = _load_cvt_mesh_from_geological(
            {}, maps_dir=branch_maps, planet_id="planet_x", world_dir=world
        )
        assert mesh is not None and not warnings
        assert source == root_mesh

        # Materialization copies it into the branch (canonical name); the
        # root file is untouched.
        target = _materialize_writable_mesh(source, branch_maps, "planet_x")
        assert target == branch_maps / "planet_x" / "cvt_mesh.msgpack.gz"
        assert target.exists()
        assert root_mesh.read_bytes() == root_bytes

        # Simulated branch write-back hits the copy, not the parent.
        target.write_bytes(b'{"seed": 99}')
        assert root_mesh.read_bytes() == root_bytes

    def test_own_mesh_is_not_copied(self, tmp_path: Path) -> None:
        maps = tmp_path / "maps"
        own = maps / "planet_x" / "cvt_mesh.msgpack.gz"
        _write_mesh(own)

        target = _materialize_writable_mesh(own, maps, "planet_x")
        assert target == own

    def test_own_legacy_mesh_redirects_to_canonical(self, tmp_path: Path) -> None:
        """A legacy-named mesh inside the build dir redirects to the canonical
        sibling so the write-back converts instead of writing msgpack into a
        ``.json`` file."""
        maps = tmp_path / "maps"
        legacy = maps / "planet_x" / "cvt_mesh.json"
        _write_mesh(legacy)

        target = _materialize_writable_mesh(legacy, maps, "planet_x")
        assert target == maps / "planet_x" / "cvt_mesh.msgpack.gz"

    def test_missing_source_returns_target_path(self, tmp_path: Path) -> None:
        """Degenerate case (loader already failed) — still returns a sane path."""
        target = _materialize_writable_mesh(None, tmp_path / "maps", "planet_x")
        assert target == tmp_path / "maps" / "planet_x" / "cvt_mesh.msgpack.gz"
