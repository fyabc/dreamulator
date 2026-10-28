"""Generation inputs used to decide whether existing canvas chunks can be reused."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from dreamulator import cli_export_canvas as cli
from dreamulator.cli_export_canvas import _stale_reason
from dreamulator.map import td_canvas_build as tb
from dreamulator.world_manager import WorldManager

if TYPE_CHECKING:
    from pathlib import Path


def _canvas_metadata() -> dict[str, Any]:
    return {
        "geometry": {"ncell": 8},
        "conditioning_sha256": {"heightmap": "unchanged-height-condition"},
        "generation": {"seed": 42},
        "structure": {"fixed": True},
        "coarse_source": {
            "format": "fixed-coarse-statistics-v1",
            "field": {"sha256": "accepted-field"},
            "reference": {"sha256": "accepted-statistical-reference"},
            "query_prefix": [[0, 0]],
        },
    }


@pytest.mark.parametrize(
    "changed", ["field", "reference", "query_prefix", "query_policy", "added", "removed"]
)
def test_shared_field_changes_invalidate_existing_chunks(tmp_path: Path, changed: str) -> None:
    """Equal height conditions alone do not imply equal TD generation inputs."""
    (tmp_path / "chunks").mkdir()
    (tmp_path / "chunks/r000_c000.npy").write_bytes(b"existing-generated-chunk")
    old = _canvas_metadata()
    new = copy.deepcopy(old)
    if changed in ("field", "reference"):
        new["coarse_source"][changed]["sha256"] = "different-shared-field"
    elif changed == "query_prefix":
        new["coarse_source"]["query_prefix"] = [[1, 0]]
    elif changed == "query_policy":
        new["coarse_source"]["query_policy"] = "last-prefix-result-v1"
    elif changed == "added":
        del old["coarse_source"]
    else:
        del new["coarse_source"]
    assert _stale_reason(old, new, tmp_path) == "coarse_source"


def _stub_plan_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_second: bool = False,
    stale_second: bool = True,
) -> Path:
    """Exercise the command's batch IO with two deterministic input producers."""
    from dreamulator.map import export

    world = tmp_path / "world"
    world.mkdir()
    root = tmp_path / "canvases"
    root.mkdir()
    plans = [
        SimpleNamespace(
            canvas_id=name,
            chunks=[[0, 0]],
            max_anisotropy=1.0,
            land_km2=100.0,
            geometry=SimpleNamespace(center_lat=0.0, center_lon=0.0, ncell=8),
        )
        for name in ("first", "second")
    ]
    old_metadata = {}
    (root / "layout.json").write_text('{"previous_layout": true}', encoding="utf-8")
    (root / "owner_points.npy").write_bytes(b"old-owner-points")
    (root / "owner_canvas.npy").write_bytes(b"old-owner-canvases")
    for plan in plans:
        out = root / plan.canvas_id
        for folder in ("conditioning", "climate", "chunks"):
            (out / folder).mkdir(parents=True)
        meta = _canvas_metadata()
        if plan.canvas_id == "first":
            del meta["coarse_source"]
        old_metadata[plan.canvas_id] = meta
        (out / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
        (out / "conditioning/heightmap.npy").write_bytes(b"unchanged-height")
        (out / "climate/temperature.C.npy").write_bytes(b"old-climate")
        (out / "chunks/r000_c000.npy").write_bytes(b"accepted-height-chunk")
        (out / "chunks.sha256").write_bytes(b"accepted-checksums")

    def write_layout(path: Path, *_args: Any) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "layout.json").write_text(
            json.dumps({"canvases": [{"id": p.canvas_id} for p in plans]}), encoding="utf-8"
        )
        (path / "owner_points.npy").write_bytes(b"new-owner-points")
        (path / "owner_canvas.npy").write_bytes(b"new-owner-canvases")

    def write_inputs(path: Path, plan: Any, *_args: Any, **_kwargs: Any) -> Path:
        if fail_second and plan.canvas_id == "second":
            raise ValueError("second input producer failed")
        out = path / plan.canvas_id
        for folder in ("conditioning", "climate"):
            (out / folder).mkdir(parents=True, exist_ok=True)
        meta = copy.deepcopy(old_metadata[plan.canvas_id])
        if stale_second and plan.canvas_id == "second":
            del meta["coarse_source"]
        (out / "conditioning/heightmap.npy").write_bytes(b"unchanged-height")
        (out / "climate/temperature.C.npy").write_bytes(b"new-climate")
        (out / "canvas.json").write_text(json.dumps(meta), encoding="utf-8")
        return out

    monkeypatch.setattr(WorldManager, "world_dir", lambda *_args: world)
    monkeypatch.setattr(
        cli,
        "_plan_world",
        lambda *_args: (None, SimpleNamespace(plans=plans), 6371.0, world, world, {"world": "toy"}),
    )
    monkeypatch.setattr(export, "load_climate_monthly", lambda *_args: (None, None))
    monkeypatch.setattr(tb.MeshColumns, "from_mesh", lambda *_args: None)
    monkeypatch.setattr(tb, "write_layout", write_layout)
    monkeypatch.setattr(tb, "write_canvas_inputs", write_inputs)
    return root


def _file_contents(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_rejected_plan_preserves_all_existing_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale second canvas must also leave the first canvas and ownership files intact."""
    root = _stub_plan_inputs(tmp_path, monkeypatch)
    before = _file_contents(root)
    result = CliRunner().invoke(cli.canvas_app, ["plan", "toy", "--root", str(root)])
    assert result.exit_code == 1, result.output
    assert "coarse_source" in result.output
    assert _file_contents(root) == before


def test_matching_plan_updates_inputs_and_preserves_generated_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _stub_plan_inputs(tmp_path, monkeypatch, stale_second=False)
    result = CliRunner().invoke(cli.canvas_app, ["plan", "toy", "--root", str(root)])
    assert result.exit_code == 0, result.output
    for canvas in ("first", "second"):
        assert (root / canvas / "climate/temperature.C.npy").read_bytes() == b"new-climate"
        assert (root / canvas / "chunks/r000_c000.npy").read_bytes() == b"accepted-height-chunk"
        assert (root / canvas / "chunks.sha256").read_bytes() == b"accepted-checksums"
    assert (root / "owner_points.npy").read_bytes() == b"new-owner-points"


def test_planning_replaces_input_symlink_without_overwriting_its_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _stub_plan_inputs(tmp_path, monkeypatch, stale_second=False)
    archive = tmp_path / "accepted-climate.npy"
    archive.write_bytes(b"old-climate")
    target = root / "first/climate/temperature.C.npy"
    target.unlink()
    target.symlink_to(archive)
    result = CliRunner().invoke(cli.canvas_app, ["plan", "toy", "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert archive.read_bytes() == b"old-climate"
    assert not target.is_symlink()
    assert target.read_bytes() == b"new-climate"
