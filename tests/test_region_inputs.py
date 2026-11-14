"""Standalone import, portable refinement and strict forcing validation."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import yaml
from PIL import Image
from typer.testing import CliRunner

from dreamulator.cli import app
from dreamulator.map.models import ElevationMapping
from dreamulator.map.region_export import export_region_pack, region_window
from dreamulator.map.region_import import import_region_pack, load_local_climate
from dreamulator.map.region_inputs import (
    CONDITIONING_UNITS,
    file_sha256,
    read_refinement_inputs,
)
from dreamulator.media import terrain_refine as tr
from dreamulator.result_contract import REFERENCE_MONTH_DAYS
from tests.test_region_export import _clim_kwargs, _patch_mesh

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def local_files(tmp_path: Path) -> tuple[Path, Path]:
    image = tmp_path / "local.png"
    levels = np.tile(np.arange(32, dtype=np.uint16), (32, 1)) * 2000
    Image.fromarray(levels).save(image)
    climate = tmp_path / "climate.yaml"
    climate.write_text(
        yaml.safe_dump(
            {
                "temperature_basis": "surface",
                "description": "Synthetic seasonal forcing.",
                "temperature_C": [float(10 + 8 * np.cos(m * np.pi / 6)) for m in range(12)],
                "precipitation_mm": [30.0] * 6 + [180.0] * 6,
            }
        ),
        encoding="utf-8",
    )
    return image, climate


def make_local(tmp_path: Path, files: tuple[Path, Path]) -> tuple[Path, dict[str, Any]]:
    pack = tmp_path / "pack"
    meta = import_region_pack(
        *files,
        ElevationMapping(min_m=-200.0, max_m=1800.0),
        px_km=2.0,
        out_dir=pack / "input",
        out_res=31,
    )
    return pack, meta


def test_standalone_pack_after_moving_and_removing_sources(
    tmp_path: Path, local_files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    pack, meta = make_local(tmp_path, local_files)
    moved = tmp_path / "delivery"
    shutil.move(pack, moved)
    for path in local_files:
        path.unlink()
    monkeypatch.setattr(tr, "_pack_map_dir", lambda *_: pytest.fail("opened a mother world"))
    n = tr._export_conditioning(moved, tmp_path / "fields")
    monthly = tr._pack_monthly_runoff(moved)
    assert monthly is not None and monthly.shape == (31, 31, 12)
    assert n >= 2
    annual = np.load(moved / "input/runoff.mm.npy")
    np.testing.assert_allclose(monthly.sum(axis=-1), annual, rtol=2e-6, atol=1e-4)
    assert meta["span_km"] == 64.0  # source pixels, not output pixels
    assert meta["km_per_px"]["x"] == pytest.approx(64 / 31)
    assert meta["source"]["seafloor_assumed"] is False
    assert not meta["source"]["warnings"]
    assert not (moved / "input/ice.m.npy").exists()  # ice thickness was not calculated


def test_world_snapshot_matches_legacy_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mesh = _patch_mesh()
    rng = np.random.default_rng(132)
    t = rng.uniform(-10, 25, (mesh.num_cells, 12)).astype(np.float32)
    p = rng.uniform(0, 250, t.shape).astype(np.float32)
    pack = tmp_path / "pack"
    meta = export_region_pack(
        mesh,
        out_dir=pack / "input",
        climate_monthly=(t, p),
        source={"world": "world", "planet": "planet", "branch": "child"},
        **_clim_kwargs(),  # type: ignore[arg-type]
    )
    snapshot = read_refinement_inputs(pack / "input", meta["refinement_inputs"])
    meta.pop("refinement_inputs")
    (pack / "input/meta.json").write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(tr, "_mesh_and_window", lambda *_: (mesh, region_window(0, 0, 500, 6371)))
    monkeypatch.setattr(tr, "_pack_map_dir", lambda *_: tmp_path)
    monkeypatch.setattr("dreamulator.map.export.find_mesh_file", lambda *_: tmp_path / "mesh")
    monkeypatch.setattr("dreamulator.map.export.load_climate_monthly", lambda *_: (t, p))
    tr._export_conditioning(pack, tmp_path / "legacy")
    for name in CONDITIONING_UNITS:
        np.testing.assert_array_equal(np.load(tmp_path / "legacy" / f"{name}.npy"), snapshot[name])
    np.testing.assert_array_equal(tr._pack_monthly_runoff(pack), snapshot["runoff_monthly_mm"])


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "checksum",
        "shape",
        "units",
        "time",
        "annual",
        "negative",
        "path",
        "window",
        "forcing",
    ],
)
def test_declared_snapshot_corruption_fails(
    tmp_path: Path, local_files: tuple[Path, Path], corruption: str
) -> None:
    pack, meta = make_local(tmp_path, local_files)
    descriptor = meta["refinement_inputs"]
    record = descriptor["fields"]["precipitation_total_mm"]
    path = pack / "input" / record["path"]
    if corruption == "missing":
        descriptor["fields"].pop("elevation_m")
    elif corruption == "checksum":
        record["sha256"] = "0" * 64
    elif corruption == "shape":
        record["shape"] = [1, 1]
    elif corruption == "units":
        record["units"] = "m"
    elif corruption == "time":
        descriptor["days_per_month"] = 30
    elif corruption == "annual":
        np.save(pack / "input/runoff.mm.npy", np.ones((31, 31)))
    elif corruption == "negative":
        np.save(path, -np.ones(record["shape"], dtype=np.float32))
        record["sha256"] = file_sha256(path)
    elif corruption == "path":
        record["path"] = "../../outside.npy"
    elif corruption == "window":
        meta["span_km"] += 1
    else:
        np.save(pack / "input/climate_monthly_T.npy", np.full((2, 2, 12), 99.0))
    (pack / "input/meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError):
        tr._export_conditioning(pack, tmp_path / "fields")
    with pytest.raises(ValueError):
        tr._pack_monthly_runoff(pack)


def test_spatial_climate_and_legacy_external_noninteger_ratio(
    tmp_path: Path, local_files: tuple[Path, Path]
) -> None:
    image, config = local_files
    t = np.full((7, 7, 12), 12.0)
    t[:, :, :3] = -3
    p = np.full_like(t, 150.0)
    p[:3, :, :6] = 0
    np.save(tmp_path / "t.npy", t)
    np.save(tmp_path / "p.npy", p)
    config.write_text(
        yaml.safe_dump(
            {
                "temperature_basis": "surface",
                "description": "Spatial test climate.",
                "temperature_C": "t.npy",
                "precipitation_mm": "p.npy",
            }
        ),
        encoding="utf-8",
    )
    pack, meta = make_local(tmp_path, (image, config))
    expected = tr._pack_monthly_runoff(pack)
    meta.pop("refinement_inputs")
    (pack / "input/meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert tr._export_conditioning(pack, tmp_path / "coarse") == 7
    np.testing.assert_array_equal(tr._pack_monthly_runoff(pack), expected)
    assert np.unique(np.load(pack / "input/lake_ice.months.npy")).tolist() == [3]


@pytest.mark.parametrize("bad", ["negative", "months", "time", "basis", "grid", "nan"])
def test_invalid_climate(tmp_path: Path, local_files: tuple[Path, Path], bad: str) -> None:
    _, path = local_files
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if bad == "negative":
        spec["precipitation_mm"][2] = -1
    elif bad == "months":
        spec["temperature_C"] = [10] * 11
        spec["precipitation_mm"] = [100] * 11
    elif bad == "time":
        spec["days_per_month"] = 30
    elif bad == "basis":
        spec["temperature_basis"] = "sea-level"
    elif bad == "nan":
        spec["temperature_C"][0] = float("nan")
    else:
        np.save(tmp_path / "bad.npy", np.zeros((3, 4, 12)))
        spec["temperature_C"] = spec["precipitation_mm"] = "bad.npy"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    with pytest.raises(ValueError):
        load_local_climate(path, 4)


def test_cli_import_and_mutually_exclusive_world(
    tmp_path: Path, local_files: tuple[Path, Path]
) -> None:
    args = [
        "region",
        "pack",
        "--from-image",
        str(local_files[0]),
        "--px-km",
        "2",
        "--z-range=-200,1800",
        "--climate-file",
        str(local_files[1]),
        "--out-res",
        "31",
        "-o",
        str(tmp_path / "cli-pack"),
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "cli-pack/input/refinement/runoff_monthly_mm.npy").exists()
    for extra in (["world"], ["--branch", "child"], ["--span-km", "64"], ["--no-climate"]):
        result = CliRunner().invoke(app, [*args, *extra])
        assert result.exit_code != 0


def test_local_import_deterministic_and_no_stale_reuse(
    tmp_path: Path, local_files: tuple[Path, Path]
) -> None:
    a, _ = make_local(tmp_path / "a", local_files)
    b, _ = make_local(tmp_path / "b", local_files)
    for file in (a / "input").rglob("*"):
        if file.is_file():
            assert file.read_bytes() == (b / "input" / file.relative_to(a / "input")).read_bytes()
    with pytest.raises(ValueError, match="empty"):
        make_local(tmp_path / "a", local_files)


def test_local_threshold_retains_seafloor_assumption(
    tmp_path: Path, local_files: tuple[Path, Path]
) -> None:
    meta = import_region_pack(
        *local_files,
        ElevationMapping(mode="threshold", sea_level=0.2, max_m=3000, seafloor_m=-2000),
        px_km=2,
        out_dir=tmp_path / "threshold",
        out_res=31,
    )
    assert meta["source"]["seafloor_assumed"] is True
    assert meta["elevation_m"]["min"] == -2000
    assert meta["refinement_inputs"]["days_per_month"] == REFERENCE_MONTH_DAYS


def test_legacy_map_lookup_uses_custom_data_directory_and_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DREAMULATOR_DATA_DIR", str(tmp_path))
    root = tmp_path / "world/maps/planet"
    branch = tmp_path / "world/branches/child/maps/planet"
    for directory in (root, branch):
        directory.mkdir(parents=True)
        (directory / "placeholder").write_text("map", encoding="utf-8")
    meta = {"source": {"world": "world", "planet": "planet", "branch": "child"}}
    assert tr._pack_map_dir(meta) == branch
    meta["source"]["branch"] = None  # type: ignore[assignment]
    assert tr._pack_map_dir(meta) == root


def test_monthly_total_mismatch_is_rejected_even_with_updated_checksum(
    tmp_path: Path, local_files: tuple[Path, Path]
) -> None:
    pack, meta = make_local(tmp_path, local_files)
    descriptor = meta["refinement_inputs"]
    record = descriptor["fields"]["runoff_monthly_mm"]
    path = pack / "input" / record["path"]
    monthly = np.load(path)
    monthly[..., 0] += 10
    np.save(path, monthly)
    record["sha256"] = file_sha256(path)
    with pytest.raises(ValueError, match="sum to annual"):
        read_refinement_inputs(pack / "input", descriptor)


def test_td_condition_driver_converts_surface_temperature_once(
    tmp_path: Path, local_files: tuple[Path, Path]
) -> None:
    import tifffile

    pack, _ = make_local(tmp_path, local_files)
    fields = tmp_path / "fields"
    n = tr._export_conditioning(pack, fields)
    driver = tmp_path / "driver.py"
    driver.write_text(tr._TD_DRIVER, encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(driver),
            "condition",
            str(fields),
            str(tmp_path / "tiffs"),
            "64",
            str(n),
        ],
        check=True,
    )
    from scipy.ndimage import zoom

    t = np.load(fields / "temperature_mean_c.npy").astype(float)
    z = np.load(fields / "elevation_m.npy").astype(float)
    p = np.load(fields / "precipitation_total_mm.npy").astype(float)
    expected = t - np.clip(-6.5 + 0.0015 * p, -9.8, -4.0) / 1000 * np.maximum(0, z)
    rows = max(2, round(64 / tr.TD_COARSE_KM))
    expected = zoom(expected, rows / n, order=1).astype(np.float32)
    np.testing.assert_array_equal(tifffile.imread(tmp_path / "tiffs/temperature.tif"), expected)


def test_standalone_render_inputs_keep_ecology_missing(
    tmp_path: Path, local_files: tuple[Path, Path]
) -> None:
    from dreamulator.media.satellite_color import load_inputs

    pack, _ = make_local(tmp_path, local_files)
    build = pack / "refined-out"
    build.mkdir()
    height = np.load(pack / "input/height.meters.npy")
    np.save(build / "height.meters.npy", np.repeat(np.repeat(height, 2, axis=0), 2, axis=1))
    inputs = load_inputs(pack / "input", build)
    assert inputs.biome_legend == {}
    assert not inputs.biome_codes.any()
    assert np.isnan(inputs.npp_gc_m2_yr).all()
    assert not inputs.ice_m.any()
