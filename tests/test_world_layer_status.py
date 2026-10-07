"""Tests for world_layer_status.compute_layer_status (LayerDag freshness)."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from dreamulator.world_layer_status import compute_layer_status, enrich_layer_summaries

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, text: str = "x: 1\n", *, mtime_offset: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime_offset is not None:
        stamp = time.time() + mtime_offset
        os.utime(path, (stamp, stamp))


def _mini_world(tmp_path: Path) -> Path:
    """World with an astronomy input (yaml + md) and derived products."""
    world = tmp_path / "w"
    _write(world / "layers" / "astronomy" / "input" / "stellar.yaml")
    _write(world / "layers" / "astronomy" / "input" / "notes.md", "# notes\n")
    _write(world / "layers" / "astronomy" / "derived" / "stellar_derived.yaml")
    return world


def test_status_fresh_when_derived_newer_than_input(tmp_path: Path) -> None:
    world = _mini_world(tmp_path)
    # Input older, derived newer → fresh.
    status = compute_layer_status(world, "astronomy")
    assert status["derived_fresh"] == "fresh"
    assert status["input_source"] == "root"
    assert status["input_doc_count"] == 1
    assert isinstance(status["last_build_time"], str)


def test_status_stale_when_input_yaml_newer(tmp_path: Path) -> None:
    world = _mini_world(tmp_path)
    # Re-write the input yaml with a *future* mtime → stale.
    _write(
        world / "layers" / "astronomy" / "input" / "stellar.yaml",
        mtime_offset=60.0,
    )
    status = compute_layer_status(world, "astronomy")
    assert status["derived_fresh"] == "stale"


def test_status_md_edit_does_not_mark_stale(tmp_path: Path) -> None:
    world = _mini_world(tmp_path)
    # Narrative .md edit (future mtime) must NOT mark the layer stale —
    # mirrors the guard fingerprint philosophy.
    _write(
        world / "layers" / "astronomy" / "input" / "notes.md",
        "# edited later\n",
        mtime_offset=60.0,
    )
    status = compute_layer_status(world, "astronomy")
    assert status["derived_fresh"] == "fresh"


def test_status_absent_without_derived(tmp_path: Path) -> None:
    world = _mini_world(tmp_path)
    status = compute_layer_status(world, "climate")  # no input anywhere
    assert status["derived_fresh"] == "absent"
    assert status["input_source"] is None
    assert status["input_doc_count"] == 0
    assert status["last_build_time"] is None


def test_geological_uses_maps_products(tmp_path: Path) -> None:
    # Geological layer's real products live in maps/<planet>/, not derived/.
    world = tmp_path / "w"
    _write(world / "layers" / "geological" / "input" / "planets.yaml")
    _write(world / "maps" / "sat_p" / "cvt_mesh.msgpack.gz")
    status = compute_layer_status(world, "geological")
    assert status["derived_fresh"] == "fresh"
    # And stale when the input yaml is newer than the mesh.
    _write(
        world / "layers" / "geological" / "input" / "planets.yaml",
        mtime_offset=60.0,
    )
    status = compute_layer_status(world, "geological")
    assert status["derived_fresh"] == "stale"


def test_enrich_layer_summaries_attaches_fields(tmp_path: Path) -> None:
    world = _mini_world(tmp_path)
    layers: dict[str, dict[str, object]] = {
        "astronomy": {"configured": False, "engine": "astronomy"},
        "climate": {"configured": False},
    }
    out = enrich_layer_summaries(world, layers)
    assert out["astronomy"]["derived_fresh"] == "fresh"  # type: ignore[index]
    assert out["astronomy"]["input_doc_count"] == 1  # type: ignore[index]
    assert out["climate"]["derived_fresh"] == "absent"  # type: ignore[index]
    # Unknown layer keys pass through untouched.
    out2 = enrich_layer_summaries(world, {"not-a-layer": {"a": 1}})
    assert out2["not-a-layer"] == {"a": 1}
