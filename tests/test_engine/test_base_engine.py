"""Tests for BaseEngine.find_input per-file root fallback."""

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.models.layers import Layer


class _StubEngine(BaseEngine):
    """Minimal concrete engine — only find_input behaviour is under test."""

    name = "stub"

    def run(
        self, parameters: dict[str, object] | None = None, *, force: bool = False
    ) -> EngineResult:
        raise NotImplementedError


def test_find_input_falls_back_to_root_when_branch_shadows(tmp_path):
    # Root world provides terrain_config.yaml in the geological input layer.
    root_geo = tmp_path / "layers" / "geological" / "input"
    root_geo.mkdir(parents=True)
    (root_geo / "terrain_config.yaml").write_text("root: true", encoding="utf-8")

    # A branch build resolves geological to its own (non-empty) input dir,
    # shadowing the root dir in layer_input_dirs — but files the branch does
    # not override are still inherited from the root world.
    branch_geo = tmp_path / "branches" / "pangea" / "layers" / "geological" / "input"
    branch_geo.mkdir(parents=True)
    (branch_geo / "planets.yaml").write_text("bodies: []", encoding="utf-8")

    engine = _StubEngine(
        tmp_path,
        seed=1,
        layer_input_dirs={"geological": branch_geo},
    )
    engine.layer = Layer.GEOLOGICAL

    assert engine.find_input("planets.yaml") == branch_geo / "planets.yaml"
    assert engine.find_input("terrain_config.yaml") == root_geo / "terrain_config.yaml"
    assert engine.find_input("nonexistent.yaml") is None


def test_find_input_branch_file_wins_over_root(tmp_path):
    root_geo = tmp_path / "layers" / "geological" / "input"
    root_geo.mkdir(parents=True)
    (root_geo / "terrain_config.yaml").write_text("root: true", encoding="utf-8")

    branch_geo = tmp_path / "branches" / "pangea" / "layers" / "geological" / "input"
    branch_geo.mkdir(parents=True)
    (branch_geo / "terrain_config.yaml").write_text("branch: true", encoding="utf-8")

    engine = _StubEngine(
        tmp_path,
        seed=1,
        layer_input_dirs={"geological": branch_geo},
    )
    engine.layer = Layer.GEOLOGICAL

    assert engine.find_input("terrain_config.yaml") == branch_geo / "terrain_config.yaml"
