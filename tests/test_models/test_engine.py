"""Tests for engine pipeline."""

import pytest

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.pipeline import run_pipeline, topological_sort
from dreamulator.models.layers import Layer


class DummyEngineA(BaseEngine):
    name = "engine_a"
    version = "0.1.0"
    layer = Layer.PHYSICS
    requires = []
    input_files = []
    output_files = ["a.json"]

    def run(self, parameters=None):
        out = self.output_path("a.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}", encoding="utf-8")
        return EngineResult(
            engine_name=self.name, success=True, output_files=["a.json"]
        )


class DummyEngineB(BaseEngine):
    name = "engine_b"
    version = "0.1.0"
    layer = Layer.PHYSICS
    requires = ["engine_a"]
    input_files = ["a.json"]
    output_files = ["b.json"]

    def run(self, parameters=None):
        out = self.output_path("b.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}", encoding="utf-8")
        return EngineResult(
            engine_name=self.name, success=True, output_files=["b.json"]
        )


class TestTopologicalSort:
    def test_sort_order(self):
        result = topological_sort([DummyEngineB, DummyEngineA])
        names = [e.name for e in result]
        assert names.index("engine_a") < names.index("engine_b")

    def test_circular_dependency(self):
        class CircularA(BaseEngine):
            name = "circ_a"
            requires = ["circ_b"]
            input_files = []
            output_files = []

            def run(self, parameters=None):
                return EngineResult(engine_name=self.name, success=True)

        class CircularB(BaseEngine):
            name = "circ_b"
            requires = ["circ_a"]
            input_files = []
            output_files = []

            def run(self, parameters=None):
                return EngineResult(engine_name=self.name, success=True)

        with pytest.raises(ValueError, match="Circular"):
            topological_sort([CircularA, CircularB])


class TestRunPipeline:
    def test_pipeline_runs_in_order(self, tmp_path):
        results = run_pipeline([DummyEngineB, DummyEngineA], tmp_path, seed=42)
        assert len(results) == 2
        assert all(r.success for r in results)
        layer_derived = tmp_path / "layers" / "physics" / "derived"
        assert (layer_derived / "a.json").exists()
        assert (layer_derived / "b.json").exists()

    def test_pipeline_skip_existing(self, tmp_path):
        layer_derived = tmp_path / "layers" / "physics" / "derived"
        layer_derived.mkdir(parents=True)
        (layer_derived / "a.json").write_text("{}", encoding="utf-8")
        (layer_derived / "b.json").write_text("{}", encoding="utf-8")

        results = run_pipeline([DummyEngineA, DummyEngineB], tmp_path, seed=42)
        # All skipped because outputs exist
        assert len(results) == 0

    def test_pipeline_force(self, tmp_path):
        layer_derived = tmp_path / "layers" / "physics" / "derived"
        layer_derived.mkdir(parents=True)
        (layer_derived / "a.json").write_text("{}", encoding="utf-8")
        (layer_derived / "b.json").write_text("{}", encoding="utf-8")

        results = run_pipeline(
            [DummyEngineA, DummyEngineB], tmp_path, seed=42, force=True
        )
        assert len(results) == 2
