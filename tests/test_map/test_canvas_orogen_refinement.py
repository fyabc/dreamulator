"""Native source selection, footprint bounds and complete independent batch installation."""

from __future__ import annotations

import hashlib
import json
import shutil

import numpy as np
import pytest

from dreamulator.map.canvas_orogen_refinement import (
    CanvasRefinementConfig,
    OrogenSelection,
    integrate_orogen_correction,
    refine_canvas_layout,
)
from dreamulator.map.orogen_source import (
    CollisionProfileField,
    FrozenOrogenReplacement,
    PaleoProfileField,
)
from dreamulator.map.paleo_sutures import AuthorSuture, lonlat_to_xyz
from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.map.td_canvas_worker import read_coarse_source, translate_coarse_mean


def frozen(profile, *, points=None, selected=None):
    if points is None:
        points = lonlat_to_xyz(np.array([[0.0, 0.0]]))
    n = len(points)
    return FrozenOrogenReplacement(
        profile,
        points,
        np.ones(n, bool),
        np.zeros(n) if selected is None else selected,
        np.zeros(n),
        np.zeros(n),
        reference_id="fixture",
    )


class ConstantProfile:
    def __call__(self, xyz):
        return np.full(xyz.shape[:-1], 12.0)

    @property
    def metadata(self):
        return {"kind": "constant-test-profile"}


def collision(*, zero=False):
    points = lonlat_to_xyz(np.array([[0.0, -1.0], [0.0, 1.0]]))
    return CollisionProfileField(
        np.array([points]),
        np.array([90.0]),
        6371,
        9.80665,
        1e8 if zero else 650.0,
        300.0,
        segment_id="test",
    )


def test_old_source_support_uses_nearest_cell_difference_across_large_gaps():
    points = lonlat_to_xyz(np.array([[90.0, 0.0], [100.0, 0.0], [180.0, 0.0]]))
    source = frozen(collision(zero=True), points=points, selected=np.array([500.0, 0.0, 0.0]))
    support = source.footprint_support(np.zeros(3), np.array([95.0, 95.4, 180.0]), 10.0, 6371.0)
    np.testing.assert_array_equal(support, [True, False, False])
    # The positive reference cell can own a footprint even hundreds of km from its centre.
    value, _ = source.evaluate(np.array([0.0]), np.array([94.99]))
    assert value[0] == -500.0


@pytest.mark.parametrize("kind", ["collision", "paleo"])
def test_excluded_source_footprints_are_zero_at_independent_points(kind):
    profile = (
        collision()
        if kind == "collision"
        else PaleoProfileField(
            AuthorSuture("old", "old", 53.0, np.array([[0.0, -1.0], [0.0, 1.0]])), 2000.0, 6371.0
        )
    )
    source = frozen(profile)
    rng = np.random.default_rng(863)
    lat = np.r_[rng.uniform(-80, 80, 80), 0.0]
    lon = np.r_[rng.uniform(-180, 180, 80), 0.0]
    support = source.footprint_support(lat, lon, 20.0, 6371.0)
    assert support.any() and (~support).any()
    offsets = np.array([-1.0, 0.0, 1.0]) * 20 / np.sqrt(2)
    x, y = np.meshgrid(offsets, offsets)
    for latitude, longitude in zip(lat[~support], lon[~support], strict=True):
        geometry = CanvasGeometry(float(latitude), float(longitude), 6371.0, 8)
        la, lo = geometry.xy_to_latlon(x, y)
        delta, _ = source.evaluate(la, lo)
        np.testing.assert_array_equal(delta, 0)


def test_narrow_source_is_retained_when_footprint_centre_is_outside_profile():
    profile = PaleoProfileField(
        AuthorSuture("old", "old", 0.0, np.array([[0.0, -1.0], [0.0, 1.0]])), 1.0, 6371.0
    )
    source = frozen(profile)
    value, _ = source.evaluate(np.array([0.0]), np.array([0.01]))
    assert value[0] == 0
    assert source.footprint_support(np.array([0.0]), np.array([0.01]), 20.0, 6371.0)[0]


def test_integration_retains_spherical_area_mean_and_records_convergence():
    source = frozen(ConstantProfile())
    correction, receipt = integrate_orogen_correction(
        source, CanvasGeometry(60.0, 100.0, 6371.0, 8), (2, 4)
    )
    np.testing.assert_allclose(correction, 12.0, rtol=0, atol=1e-12)
    assert receipt["quadrature"] == 4 and receipt["support_footprints"] == 64


def original_layout(tmp_path):
    reference = tmp_path / "original"
    reference.mkdir()
    np.save(reference / "owner_points.npy", np.eye(3))
    np.save(reference / "owner_canvas.npy", np.array([0, 1, 2], np.int16))
    geometry = CanvasGeometry(0.0, 0.0, 6371.0, 8).to_dict()
    for name in ["a", "b", "c"]:
        folder = reference / name
        (folder / "conditioning").mkdir(parents=True)
        (folder / "climate").mkdir()
        (folder / "chunks").mkdir()
        np.save(folder / "chunks/r000_c000.npy", np.ones((2, 2), np.int16))
        hashes = {}
        for field in [
            "heightmap",
            "temperature",
            "temperature_std",
            "precipitation",
            "precipitation_cv",
        ]:
            path = folder / "conditioning" / f"{field}.npy"
            np.save(path, np.full((8, 8), 100, np.float32))
            hashes[field] = hashlib.sha256(path.read_bytes()).hexdigest()
        np.save(folder / "climate/temperature.C.npy", np.full((8, 8), 20, np.float32))
        meta = {
            "id": name,
            "geometry": geometry,
            "generation": {"edge_padding_cells": 4},
            "structure": {"fixed": True},
            "conditioning_sha256": hashes,
            "chunks": [[0, 0]],
        }
        (folder / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
    (reference / "layout.json").write_text(
        json.dumps({"canvases": [{"id": name} for name in ["a", "b", "c"]]}), encoding="utf-8"
    )
    return reference


class NativeFixture:
    metadata = {"radius_km": 6371.0}
    provenance = {"planet": "fixture"}

    def source(self, selection):
        return frozen(ConstantProfile())


def statistics(reference, candidate, output):
    output.mkdir()
    meta = json.loads((reference / "canvas.json").read_text(encoding="utf-8"))
    old = (
        read_coarse_source(reference, meta)
        if "coarse_source" in meta
        else np.ones((6, 16, 16), np.float32)
    )
    new = translate_coarse_mean(old, old[0] + np.float32(3))
    receipt = {
        "reference_canvas_sha256": hashlib.sha256(
            (reference / "canvas.json").read_bytes()
        ).hexdigest(),
        "candidate_canvas_sha256": hashlib.sha256(
            (candidate / "canvas.json").read_bytes()
        ).hexdigest(),
    }
    for name, value in [("field", new), ("reference", old)]:
        np.save(output / f"{name}.npy", value)
        receipt[name] = {
            "sha256": hashlib.sha256((output / f"{name}.npy").read_bytes()).hexdigest()
        }
    (output / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


def selections():
    return CanvasRefinementConfig(
        orogens={name: OrogenSelection(paleo_suture_ids=("old",)) for name in ["a", "b"]},
        quadrature_orders=(2, 4),
    )


def test_batch_retains_reference_and_unselected_inputs_and_installs_complete_layout(tmp_path):
    reference = original_layout(tmp_path)
    before = {p.relative_to(reference): p.read_bytes() for p in reference.rglob("*") if p.is_file()}
    output = refine_canvas_layout(
        reference, tmp_path / "new", selections(), NativeFixture(), prepare_statistics=statistics
    )
    assert all((reference / p).read_bytes() == value for p, value in before.items())
    np.testing.assert_array_equal(np.load(output / "a/conditioning/heightmap.npy"), 112.0)
    for name in [
        "owner_points.npy",
        "owner_canvas.npy",
        "c/canvas.json",
        "c/conditioning/heightmap.npy",
        "a/climate/temperature.C.npy",
    ]:
        assert (output / name).read_bytes() == (reference / name).read_bytes()
    assert not (output / "c/chunks").exists()
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in layout["canvases"]] == ["a", "b", "c"]
    assert set(layout["height_refinement"]["canvases"]) == {"a", "b"}
    assert (output / "a/preparation/statistics.json").is_file()


@pytest.mark.parametrize(
    "failure",
    [
        "second_producer",
        "bad_receipt",
        "existing_output",
        "already_refined",
        "bad_unselected_input",
    ],
)
def test_batch_failure_preserves_original_inputs_and_leaves_no_partial_output(tmp_path, failure):
    reference = original_layout(tmp_path)
    output = tmp_path / "new"
    if failure == "existing_output":
        output.mkdir()
        (output / "keep.txt").write_text("keep", encoding="utf-8")
    elif failure == "already_refined":
        path = reference / "b/canvas.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta["height_refinement"] = {"existing": True}
        path.write_text(json.dumps(meta), encoding="utf-8")
    elif failure == "bad_unselected_input":
        (reference / "c/conditioning/temperature.npy").write_bytes(b"invalid")
    before = {p.relative_to(reference): p.read_bytes() for p in reference.rglob("*") if p.is_file()}

    def producer(original, candidate, out):
        if original.name == "b" and failure == "second_producer":
            raise ValueError("second producer failed")
        statistics(original, candidate, out)
        if failure == "bad_receipt":
            (out / "receipt.json").write_text(
                '{"reference_canvas_sha256":"wrong","candidate_canvas_sha256":"wrong"}',
                encoding="utf-8",
            )

    with pytest.raises((ValueError, FileExistsError)):
        refine_canvas_layout(
            reference, output, selections(), NativeFixture(), prepare_statistics=producer
        )
    assert all((reference / p).read_bytes() == value for p, value in before.items())
    if failure == "existing_output":
        assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"
    else:
        assert not output.exists()
    assert not list(tmp_path.glob(".canvas-refine-*"))


def accepted_statistics(reference, tmp_path):
    """A historical mean-minus-p5 differs from the original S3 statistics."""
    accepted = tmp_path / "accepted"
    shutil.copytree(reference / "a", accepted)
    meta = json.loads((accepted / "canvas.json").read_text(encoding="utf-8"))
    (accepted / "coarse_source").mkdir()
    field = np.ones((6, 16, 16), np.float32)
    field[1] = -7
    descriptors = {}
    for name in ("field", "reference"):
        path = accepted / "coarse_source" / f"{name}.npy"
        np.save(path, field)
        descriptors[name] = {
            "path": f"coarse_source/{name}.npy",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    meta["coarse_source"] = {
        "format": "fixed-coarse-statistics-v1",
        **descriptors,
        "shape": [6, 16, 16],
        "query_prefix": [[0, 0]],
    }
    (accepted / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
    return accepted, field


def test_declared_accepted_statistics_keep_their_spread_and_query_prefix(tmp_path):
    reference = original_layout(tmp_path)
    accepted, field = accepted_statistics(reference, tmp_path)
    before = {p: p.read_bytes() for p in accepted.rglob("*") if p.is_file()}
    cfg = CanvasRefinementConfig(
        orogens={"a": OrogenSelection(paleo_suture_ids=("old",), statistics_reference=accepted)},
        quadrature_orders=(2, 4),
    )
    output = refine_canvas_layout(
        reference, tmp_path / "new", cfg, NativeFixture(), prepare_statistics=statistics
    )
    meta = json.loads((output / "a/canvas.json").read_text(encoding="utf-8"))
    result = read_coarse_source(output / "a", meta)
    np.testing.assert_array_equal(result[0] - result[1], field[0] - field[1])
    np.testing.assert_array_equal(result[2:], field[2:])
    np.testing.assert_array_equal(np.load(output / "a/coarse_source/reference.npy"), field)
    assert meta["coarse_source"]["query_prefix"] == [[0, 0]]
    provenance = meta["height_refinement"]["source"]["statistics_reference"]
    assert (
        provenance["canvas_sha256"] == hashlib.sha256(before[accepted / "canvas.json"]).hexdigest()
    )
    assert (
        meta["height_refinement"]["reference_canvas_sha256"]
        == hashlib.sha256((reference / "a/canvas.json").read_bytes()).hexdigest()
    )
    assert all(p.read_bytes() == value for p, value in before.items())
    assert not list(tmp_path.glob(".canvas-refine-*"))
