"""Fixed-statistics refinement IO and worker provenance checks."""

from __future__ import annotations

import hashlib
import json
import shutil
from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.canvas_refinement import prepare_refined_canvas
from dreamulator.map.td_canvas_worker import (
    prepare_coarse_statistics,
    read_coarse_source,
    translate_coarse_mean,
    validate_coarse_statistics,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_coarse_mean_translation_preserves_zero_response_and_climate_bytes() -> None:
    reference = np.random.default_rng(42).normal(size=(6, 16, 16)).astype(np.float32) * 10
    reference[1, 0, 0] = -0.0
    before = reference.tobytes()
    # Reconstructing p5 through two subtractions changes rounding at zero shift.
    round_trip = reference[0] - (reference[0] - reference[1])
    assert round_trip.tobytes() != reference[1].tobytes()
    unchanged = translate_coarse_mean(reference, reference[0])
    assert unchanged.tobytes() == before
    mean = reference[0].copy()
    mean[4:8, 4:8] += 3
    shifted = translate_coarse_mean(reference, mean)
    changed = mean != reference[0]
    assert shifted[:, ~changed].tobytes() == reference[:, ~changed].tobytes()
    assert shifted[2:].tobytes() == reference[2:].tobytes()
    np.testing.assert_array_equal(shifted[0], mean)
    np.testing.assert_allclose(
        shifted[0] - shifted[1], reference[0] - reference[1], rtol=0, atol=8e-6
    )
    assert reference.tobytes() == before
    with pytest.raises(ValueError, match="float32 footprint"):
        translate_coarse_mean(reference, mean.astype(np.float64))
    mean[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        translate_coarse_mean(reference, mean)


def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "reference"
    (root / "conditioning").mkdir(parents=True)
    (root / "climate").mkdir()
    np.save(root / "climate/temperature.C.npy", np.arange(64).reshape(8, 8))
    hashes = {}
    for name, value in [
        ("heightmap", 100.0),
        ("temperature", 20.0),
        ("temperature_std", 2.0),
        ("precipitation", 1200.0),
        ("precipitation_cv", 40.0),
    ]:
        path = root / "conditioning" / f"{name}.npy"
        np.save(path, np.full((8, 8), value, dtype=np.float32))
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "canvas.json").write_text(
        json.dumps(
            {
                "id": "test",
                "geometry": {"ncell": 8},
                "generation": {"edge_padding_cells": 4},
                "conditioning_sha256": hashes,
                "structure": {"fixed": True},
                "chunks": [[0, 0]],
            }
        ),
        encoding="utf-8",
    )
    reference = np.ones((6, 16, 16), dtype=np.float32)
    reference[0] = 0  # A signed negative spread is allowed by the existing encoding.
    candidate = reference.copy()
    candidate[:2] += 3
    a, b = tmp_path / "candidate.npy", tmp_path / "reference.npy"
    np.save(a, candidate)
    np.save(b, reference)
    return root, a, b


def test_refinement_preserves_reference_and_climate_and_restores_coarse_field(
    tmp_path: Path,
) -> None:
    root, candidate, reference = inputs(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    delta = np.linspace(-200, 200, 64).reshape(8, 8)
    out = prepare_refined_canvas(
        root,
        tmp_path / "new",
        delta,
        candidate,
        reference,
        source={"id": "test-source"},
        quadrature=16,
    )
    assert all((root / p).read_bytes() == value for p, value in before.items())
    for path in (
        "climate/temperature.C.npy",
        "conditioning/temperature.npy",
        "conditioning/precipitation.npy",
    ):
        assert (out / path).read_bytes() == (root / path).read_bytes()
    np.testing.assert_array_equal(
        np.load(out / "conditioning/heightmap.npy"),
        (100 + delta).astype(np.float32),
    )
    meta = json.loads((out / "canvas.json").read_text(encoding="utf-8"))
    assert meta["coarse_source"]["query_policy"] == "last-prefix-result-v1"
    np.testing.assert_array_equal(read_coarse_source(out, meta), np.load(candidate))
    assert meta["structure"] == {"fixed": True}
    assert (
        meta["height_refinement"]["reference_canvas_sha256"]
        == hashlib.sha256((root / "canvas.json").read_bytes()).hexdigest()
    )
    with pytest.raises(FileExistsError):
        prepare_refined_canvas(
            root, out, delta, candidate, reference, source={"id": "test"}, quadrature=16
        )


class ArrayTensor:
    """CPU tensor operations used to read an already generated model result."""

    def __init__(self, value: np.ndarray) -> None:
        self.value = value

    def __getitem__(self, key):
        return ArrayTensor(self.value[key])

    def __truediv__(self, other):
        return ArrayTensor(self.value / other.value)

    def numpy(self):
        return self.value


class PreparedModelResults:
    """Install independent, precomputed outputs when the tile cache is rebuilt."""

    def __init__(self, fields: list[np.ndarray]) -> None:
        self.fields = fields
        self.installs = []
        self.rebuilds = 0
        self.coarse = None

    def set_custom_conditioning_import(self, channel, values, i, j, **kwargs):
        assert kwargs["rebuild"] is False
        self.installs.append((channel, values.copy()))

    def rebuild(self):
        value = self.fields[self.rebuilds]
        self.coarse = ArrayTensor(value)
        self.rebuilds += 1


def candidate_conditions(tmp_path: Path) -> tuple[Path, Path]:
    root, _, _ = inputs(tmp_path)
    candidate = tmp_path / "candidate-inputs"
    shutil.copytree(root, candidate)
    height = candidate / "conditioning/heightmap.npy"
    np.save(height, np.full((8, 8), 110.0, dtype=np.float32))
    meta = json.loads((candidate / "canvas.json").read_text(encoding="utf-8"))
    meta["conditioning_sha256"]["heightmap"] = hashlib.sha256(height.read_bytes()).hexdigest()
    (candidate / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
    return root, candidate


def model_output(mean: float, spread: float, climate: float) -> np.ndarray:
    field = np.ones((7, 16, 16), np.float32)
    field[0] = mean
    field[1] = mean - spread
    field[2:6] = climate
    return field


def test_statistical_preparation_freezes_reference_spread_and_climate_outputs(
    tmp_path: Path,
) -> None:
    reference, candidate = candidate_conditions(tmp_path)
    before = {
        p: p.read_bytes() for d in (reference, candidate) for p in d.rglob("*") if p.is_file()
    }
    world = PreparedModelResults([model_output(1, 0.5, 2), model_output(3, 2, 17)])
    field, baseline = prepare_coarse_statistics(world, reference, candidate)
    np.testing.assert_array_equal(field[0], 3)
    np.testing.assert_array_equal(field[1], 2.5)
    np.testing.assert_array_equal(field[2:], 2)
    assert world.rebuilds == 2 and len(world.installs) == 10
    np.testing.assert_array_equal(world.installs[0][1], 100)
    np.testing.assert_array_equal(world.installs[5][1], 110)
    np.testing.assert_array_equal(world.installs[2][1], 200)  # temperature std in TD units
    assert baseline.tobytes() == model_output(1, 0.5, 2)[:-1].tobytes()
    assert all(p.read_bytes() == value for p, value in before.items())


def test_statistical_preparation_uses_existing_frozen_reference_directly(tmp_path: Path) -> None:
    original, candidate_field, reference_field = inputs(tmp_path)
    frozen = prepare_refined_canvas(
        original,
        tmp_path / "frozen",
        np.zeros((8, 8)),
        candidate_field,
        reference_field,
        source={"id": "accepted"},
        quadrature=8,
    )
    candidate = tmp_path / "candidate-inputs"
    shutil.copytree(original, candidate)
    height = candidate / "conditioning/heightmap.npy"
    np.save(height, np.full((8, 8), 110, np.float32))
    meta = json.loads((candidate / "canvas.json").read_text(encoding="utf-8"))
    meta["conditioning_sha256"]["heightmap"] = hashlib.sha256(height.read_bytes()).hexdigest()
    (candidate / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
    world = PreparedModelResults([model_output(7, 2, 17)])
    field, baseline = prepare_coarse_statistics(world, frozen, candidate)
    assert baseline.tobytes() == np.load(candidate_field).tobytes()
    assert world.rebuilds == 1
    np.testing.assert_array_equal(field[0], 7)
    validate_coarse_statistics(field, baseline)


def test_new_climate_rebuilds_shared_conditions_with_accepted_spread(tmp_path: Path) -> None:
    reference, candidate = candidate_conditions(tmp_path)
    # Climate must trigger a query even when the accepted terrain input is unchanged.
    height = candidate / "conditioning/heightmap.npy"
    shutil.copy2(reference / "conditioning/heightmap.npy", height)
    temperature = candidate / "conditioning/temperature.npy"
    np.save(temperature, np.full((8, 8), 25.0, dtype=np.float32))
    meta = json.loads((candidate / "canvas.json").read_text(encoding="utf-8"))
    for name in ("heightmap", "temperature"):
        meta["conditioning_sha256"][name] = hashlib.sha256(
            (candidate / "conditioning" / f"{name}.npy").read_bytes()
        ).hexdigest()
    (candidate / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
    world = PreparedModelResults([model_output(1, 0.5, 2), model_output(3, 2, 17)])
    field, baseline = prepare_coarse_statistics(world, reference, candidate, refresh_climate=True)
    np.testing.assert_array_equal(field[0], 3)
    np.testing.assert_array_equal(field[0] - field[1], 0.5)
    np.testing.assert_array_equal(field[2:], 17)
    np.testing.assert_array_equal(baseline[2:], 17)
    assert world.rebuilds == 2
    validate_coarse_statistics(field, baseline)


def test_unchanged_height_keeps_entire_reference_field_without_candidate_query(
    tmp_path: Path,
) -> None:
    reference, _, _ = inputs(tmp_path)
    candidate = tmp_path / "same-inputs"
    shutil.copytree(reference, candidate)
    world = PreparedModelResults([model_output(1, 0.5, 2)])
    field, baseline = prepare_coarse_statistics(world, reference, candidate)
    assert field.tobytes() == baseline.tobytes()
    assert world.rebuilds == 1
