"""Frequency, coast, cache and adopted-terrain contracts of region modes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from dreamulator.cli import app
from dreamulator.media import terrain_refine as tr
from dreamulator.media.terrain_blend import (
    RefinementMode,
    blend_height,
    cap_depression_depth,
    detail_difference,
)
from tests import test_region_inputs as ri
from tests.test_region_inputs import make_local

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def input_files(tmp_path: Path) -> tuple[Path, Path]:
    return ri.local_files.__wrapped__(tmp_path)


def test_difference_replaces_short_wave_without_double_counting() -> None:
    n = 128
    x = (np.arange(n) + 0.5) * np.pi / n
    long = np.broadcast_to(40 * np.cos(2 * x), (n, n))
    short = np.broadcast_to(np.cos(80 * x), (n, n))
    source = (300 + long + 6 * short).astype(np.float32)
    donor = (700 + 10 * short).astype(np.float32)
    merged = source + detail_difference(source, donor, 0.1, 1.6)
    np.testing.assert_allclose(merged, 300 + long + 10 * short, atol=1e-4)


def test_coast_seabed_and_float32_mask_contract(tmp_path: Path) -> None:
    source = np.full((64, 64), 0.03, np.float32)
    source[:, :16] = -4000
    delta = np.full(source.shape, -100, np.float32)
    result = blend_height(source, delta, 0.1, 0.8, 0)
    np.testing.assert_array_equal(result[source <= 0], source[source <= 0])
    np.testing.assert_array_equal(result > 0, source > 0)
    np.testing.assert_array_equal(result[[0, -1]], source[[0, -1]])
    # Integer metre exports erase sub-metre sign: the explicit classification
    # mask must survive PNG round-trip independently of those levels.
    mask = (result > 0).astype(np.uint8) * 255
    Image.fromarray(mask).save(tmp_path / "land.png")
    np.testing.assert_array_equal(np.asarray(Image.open(tmp_path / "land.png")) > 0, source > 0)
    assert np.any((result > 0) & (np.rint(result) == 0))


def test_depth_cap_is_explicit_and_leaves_seabed() -> None:
    source = np.full((48, 48), 100, np.float32)
    source[:, 0] = -20
    donor = source.copy()
    donor[10:30, 10:30] = 10
    capped = cap_depression_depth(donor, source, 0)
    np.testing.assert_array_equal(capped, source)


def fake_donor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr, "_td_revision", lambda _: "test-revision")
    monkeypatch.setattr(tr, "_td_python", lambda _: "unused-python")
    monkeypatch.setattr(tr, "_run_td", lambda *args: None)

    def export(pack: Path, fields: Path, **kwargs: object) -> int:
        fields.mkdir(parents=True)
        return 2

    def convert(args: list[str], **kwargs: object) -> None:
        target = int(args[-1])
        x = np.arange(target, dtype=np.float32)
        donor = np.broadcast_to(250 + 200 * np.cos(x), (target, target)).copy()
        np.save(args[-2], donor)

    monkeypatch.setattr(tr, "_export_conditioning", export)
    monkeypatch.setattr(tr.subprocess, "run", convert)


def test_modes_cache_and_routing_use_adopted_bed(
    tmp_path: Path, input_files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    pack, _ = make_local(tmp_path, input_files)
    fake_donor(monkeypatch)
    import dreamulator.map.prog_erosion as erosion

    original_flood = erosion.priority_flood
    routed = []

    def capture(height: np.ndarray, land: np.ndarray):
        routed.append(height.copy())
        return original_flood(height, land)

    monkeypatch.setattr(erosion, "priority_flood", capture)
    result = tr.refine_region_pack(pack, tmp_path, mode=RefinementMode.BLEND)
    assert result["mode"] == "blend"
    out = pack / "refined-out"
    adopted = np.load(out / "height.meters.npy")
    np.testing.assert_array_equal(adopted, routed[-1])
    np.testing.assert_array_equal(adopted, np.load(out / "height.blended.npy"))
    np.testing.assert_array_equal(adopted, np.load(out / "height.pre-equilibrium.npy"))
    manifest = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert manifest["cache_contract"]["native_resolution_km"] == 2
    assert manifest["cache_contract"]["preserve_wavelength_km"] == 8
    tr.refine_region_pack(pack, None, mode=RefinementMode.BLEND, reuse_height=True)
    np.testing.assert_array_equal(adopted, np.load(out / "height.meters.npy"))
    for kwargs in (
        {"mode": RefinementMode.REDRAW},
        {"mode": RefinementMode.BLEND, "native_resolution_km": 4},
    ):
        with pytest.raises(ValueError, match="cached mode, input or scale changed"):
            tr.refine_region_pack(pack, None, reuse_height=True, **kwargs)
    donor = out / "height.donor.npy"
    donor.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="damaged"):
        tr.refine_region_pack(pack, None, mode=RefinementMode.BLEND, reuse_height=True)
    np.testing.assert_array_equal(adopted, np.load(out / "height.meters.npy"))
    tr.refine_region_pack(pack, None, mode=RefinementMode.HYDROLOGY)
    np.testing.assert_array_equal(
        np.load(out / "height.source.npy"), np.load(out / "height.meters.npy")
    )
    assert not donor.exists()  # a new mode does not retain stale stage products


def test_hydrology_cli_needs_no_td_and_rejects_broken_forcing(
    tmp_path: Path, input_files: tuple[Path, Path]
) -> None:
    pack, _ = make_local(tmp_path, input_files)
    result = CliRunner().invoke(app, ["region", "build", str(pack), "--mode", "hydrology"])
    assert result.exit_code == 0, result.output
    assert (pack / "refined-out/height.meters.npy").exists()
    path = pack / "input/refinement/elevation_m.npy"
    path.unlink()
    result = CliRunner().invoke(app, ["region", "build", str(pack), "--mode", "hydrology"])
    assert result.exit_code == 2 and "rejected" in result.output


def test_parent_crop_overlap_is_identical_and_independent_blends_differ() -> None:
    rng = np.random.default_rng(12)
    source = rng.uniform(100, 400, (96, 96)).astype(np.float32)
    donor = rng.uniform(100, 400, source.shape).astype(np.float32)
    delta = detail_difference(source, donor, 0.1, 1.6)
    parent = blend_height(source, delta, 0.1, 0.8, 0)
    a, b = parent[:, :64].copy(), parent[:, 32:].copy()
    np.testing.assert_array_equal(a[:, 32:], b[:, :32])
    # The negative control prevents calling whole-window DCT a tile-local method.
    cropped_delta = detail_difference(source[:, :64], donor[:, :64], 0.1, 1.6)
    assert np.max(np.abs(cropped_delta - delta[:, :64])) > 1


def test_depth_cap_adoption_and_failed_build_keep_previous_product(
    tmp_path: Path, input_files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    pack, _ = make_local(tmp_path, input_files)
    fake_donor(monkeypatch)
    tr.refine_region_pack(pack, tmp_path, mode=RefinementMode.BLEND, depth_cap=True)
    out = pack / "refined-out"
    adopted = np.load(out / "height.meters.npy")
    np.testing.assert_array_equal(adopted, np.load(out / "height.depth-capped.npy"))
    np.testing.assert_array_equal(adopted, np.load(out / "height.pre-equilibrium.npy"))
    import dreamulator.map.prog_erosion as erosion

    def fail(*args: object, **kwargs: object) -> None:
        raise ValueError("forcing failed after preparing the new terrain")

    monkeypatch.setattr(erosion, "terminal_equilibrium_routing", fail)
    with pytest.raises(ValueError, match="forcing failed"):
        tr.refine_region_pack(pack, tmp_path, mode=RefinementMode.REDRAW)
    np.testing.assert_array_equal(adopted, np.load(out / "height.meters.npy"))
    manifest = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "blend"
