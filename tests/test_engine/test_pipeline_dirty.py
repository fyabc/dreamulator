"""Tests for the build dirty check (tech debt #4: mtime-based skip)."""

import os

from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.pipeline import _input_paths, _is_dirty, run_pipeline
from dreamulator.models.layers import Layer


class _DirtyEngine(BaseEngine):
    name = "dirty_engine"
    layer = Layer.PHYSICS
    requires: list[str] = []
    input_files = ["input.yaml"]
    optional_input_files = ["optional.yaml"]
    output_files = ["output.yaml"]

    def run(self, parameters=None, *, force=False):
        out = self.output_path("output.yaml")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{}", encoding="utf-8")
        return EngineResult(engine_name=self.name, success=True, output_files=["output.yaml"])


def _make_engine(tmp_path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    engine = _DirtyEngine(
        world_dir=tmp_path,
        seed=1,
        layer_input_dirs={Layer.PHYSICS.value: input_dir},
        layer_derived_dirs={},
        layer_output_dir=output_dir,
    )
    return engine, input_dir, output_dir


def _write(path, contents="{}"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _touch_newer(path, reference):
    newest = os.path.getmtime(reference) + 10.0
    os.utime(path, (newest, newest))


class TestIsDirty:
    def test_no_output_is_dirty(self, tmp_path):
        engine, _, _ = _make_engine(tmp_path)
        assert _is_dirty(engine) is True

    def test_output_newer_than_input_is_clean(self, tmp_path):
        engine, input_dir, output_dir = _make_engine(tmp_path)
        _write(input_dir / "input.yaml")
        _write(output_dir / "output.yaml")
        assert _is_dirty(engine) is False

    def test_input_newer_than_output_is_dirty(self, tmp_path):
        engine, input_dir, output_dir = _make_engine(tmp_path)
        _write(input_dir / "input.yaml")
        _write(output_dir / "output.yaml")
        _touch_newer(input_dir / "input.yaml", output_dir / "output.yaml")
        assert _is_dirty(engine) is True

    def test_missing_optional_input_is_clean(self, tmp_path):
        engine, input_dir, output_dir = _make_engine(tmp_path)
        _write(input_dir / "input.yaml")
        _write(output_dir / "output.yaml")
        # optional.yaml is absent — must not affect the dirty check.
        assert len(_input_paths(engine)) == 1
        assert _is_dirty(engine) is False

    def test_no_inputs_not_dirty(self, tmp_path):
        engine, _, output_dir = _make_engine(tmp_path)
        engine.input_files = []
        engine.optional_input_files = []
        _write(output_dir / "output.yaml")
        assert _is_dirty(engine) is False


class TestPipelineDirtySkip:
    def test_pipeline_reruns_when_input_changes(self, tmp_path):
        world = tmp_path
        input_file = world / "layers" / "physics" / "input" / "input.yaml"
        derived = world / "layers" / "physics" / "derived"
        _write(input_file)

        # First run: no outputs → engine runs.
        results = run_pipeline([_DirtyEngine], world, seed=42)
        assert len(results) == 1
        assert (derived / "output.yaml").exists()

        # Second run: input unchanged → skipped.
        results = run_pipeline([_DirtyEngine], world, seed=42)
        assert len(results) == 0

        # Touch the input → engine re-runs.
        _touch_newer(input_file, derived / "output.yaml")
        results = run_pipeline([_DirtyEngine], world, seed=42)
        assert len(results) == 1
