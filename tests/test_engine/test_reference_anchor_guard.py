"""Reference-anchor guard: earth root never builds the model (climate) layer.

CLAUDE.md「模型态 vs obs 态分离」: a ``reference_anchor`` world's root holds
only real observation (import_earth_climate); the climate engine refuses to
write model fields (temperature/precipitation/koppen) to the root and points
at a branch instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from dreamulator.engine.climate import ClimateEngine, _is_reference_anchor

if TYPE_CHECKING:
    from pathlib import Path


def _write_world_yaml(world_dir: Path, reference_anchor: bool) -> None:
    world_dir.mkdir(parents=True, exist_ok=True)
    (world_dir / "world.yaml").write_text(
        yaml.safe_dump({"reference_anchor": reference_anchor}),
        encoding="utf-8",
    )


def _has_guard_warning(result) -> bool:
    return any("reference_anchor" in w or "真实数据" in w for w in result.warnings)


def test_is_reference_anchor_parses_flag(tmp_path: Path) -> None:
    _write_world_yaml(tmp_path, True)
    assert _is_reference_anchor(tmp_path) is True
    _write_world_yaml(tmp_path, False)
    assert _is_reference_anchor(tmp_path) is False
    # A world with no world.yaml (or malformed) is not an anchor.
    assert _is_reference_anchor(tmp_path / "missing") is False


def test_anchor_root_build_refused(tmp_path: Path) -> None:
    """reference_anchor + no branch → the climate engine refuses to run."""
    _write_world_yaml(tmp_path, True)
    engine = ClimateEngine(tmp_path, seed=42, maps_output_dir=tmp_path / "maps")
    result = engine.run()
    assert result.success is False
    assert _has_guard_warning(result)


def test_anchor_branch_build_allowed(tmp_path: Path) -> None:
    """reference_anchor + a branch → the guard does not fire (branch is writable)."""
    _write_world_yaml(tmp_path, True)
    engine = ClimateEngine(
        tmp_path,
        seed=42,
        maps_output_dir=tmp_path / "branches" / "climate-dev" / "maps",
    )
    result = engine.run()
    # The run proceeds past the guard and fails on the missing planets.yaml —
    # a different, expected failure for this synthetic directory.
    assert not _has_guard_warning(result)


def test_non_anchor_root_build_not_refused(tmp_path: Path) -> None:
    """A normal world (reference_anchor=false) builds on the root as usual."""
    _write_world_yaml(tmp_path, False)
    engine = ClimateEngine(tmp_path, seed=42, maps_output_dir=tmp_path / "maps")
    result = engine.run()
    assert not _has_guard_warning(result)
