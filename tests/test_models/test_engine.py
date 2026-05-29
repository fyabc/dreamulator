"""Tests for engine pipeline."""

from pathlib import Path

import pytest

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.pipeline import run_pipeline, topological_sort


class DummyEngineA(BaseEngine):
    name = "engine_a"
    version = "0.1.0"
    requires = []
    input_files = []
    output_files = ["derived/a.json"]

    def run(self, parameters=None):
        out = self.world_dir / "derived" / "a.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}", encoding="utf-8")
        return EngineResult(
            engine_name=self.name, success=True, output_files=["derived/a.json"]
        )


class DummyEngineB(BaseEngine):
    name = "engine_b"
    version = "0.1.0"
    requires = ["engine_a"]
    input_files = ["derived/a.json"]
    output_files = ["derived/b.json"]

    def run(self, parameters=None):
        out = self.world_dir / "derived" / "b.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}", encoding="utf-8")
        return EngineResult(
            engine_name=self.name, success=True, output_files=["derived/b.json"]
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
        (tmp_path / "derived").mkdir()
        results = run_pipeline([DummyEngineB, DummyEngineA], tmp_path, seed=42)
        assert len(results) == 2
        assert all(r.success for r in results)
        assert (tmp_path / "derived" / "a.json").exists()
        assert (tmp_path / "derived" / "b.json").exists()

    def test_pipeline_skip_existing(self, tmp_path):
        (tmp_path / "derived").mkdir()
        (tmp_path / "derived" / "a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "derived" / "b.json").write_text("{}", encoding="utf-8")

        results = run_pipeline([DummyEngineA, DummyEngineB], tmp_path, seed=42)
        # All skipped because outputs exist
        assert len(results) == 0

    def test_pipeline_force(self, tmp_path):
        (tmp_path / "derived").mkdir()
        (tmp_path / "derived" / "a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "derived" / "b.json").write_text("{}", encoding="utf-8")

        results = run_pipeline(
            [DummyEngineA, DummyEngineB], tmp_path, seed=42, force=True
        )
        assert len(results) == 2
