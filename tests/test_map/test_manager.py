"""Tests for MapManager map discovery and branch overlay ordering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dreamulator.map.manager import MapManager

if TYPE_CHECKING:
    from pathlib import Path


def _make_map(maps_dir: Path, planet_id: str) -> None:
    """Create a minimal map directory (only elevation.png is checked)."""
    map_dir = maps_dir / planet_id
    map_dir.mkdir(parents=True)
    (map_dir / "elevation.png").write_bytes(b"\x89PNG fake")


def test_list_planets_root_sorted(tmp_path: Path) -> None:
    world_dir = tmp_path / "myworld"
    _make_map(world_dir / "maps", "earth_reference")
    _make_map(world_dir / "maps", "earth")

    mgr = MapManager(world_dir)
    assert mgr.list_planets_with_maps() == ["earth", "earth_reference"]


def test_list_planets_branch_own_maps_first(tmp_path: Path) -> None:
    """A branch's own maps precede inherited root maps (matches _maps_dir priority)."""
    world_dir = tmp_path / "myworld"
    _make_map(world_dir / "maps", "earth")
    _make_map(world_dir / "maps", "earth_reference")
    _make_map(world_dir / "branches" / "climate-dev" / "maps", "planet_earth")

    mgr = MapManager(world_dir, branch="climate-dev")
    assert mgr.list_planets_with_maps() == [
        "planet_earth",
        "earth",
        "earth_reference",
    ]


def test_list_planets_branch_dedup_overlay(tmp_path: Path) -> None:
    """A branch map with the same ID as a root map is listed once, branch-first."""
    world_dir = tmp_path / "myworld"
    _make_map(world_dir / "maps", "earth")
    _make_map(world_dir / "maps", "earth_reference")
    _make_map(world_dir / "branches" / "terrain-dev" / "maps", "earth")

    mgr = MapManager(world_dir, branch="terrain-dev")
    assert mgr.list_planets_with_maps() == ["earth", "earth_reference"]


def test_list_planets_branch_without_own_maps_falls_back_to_root(
    tmp_path: Path,
) -> None:
    world_dir = tmp_path / "myworld"
    _make_map(world_dir / "maps", "earth")
    (world_dir / "branches" / "l4-companion").mkdir(parents=True)

    mgr = MapManager(world_dir, branch="l4-companion")
    assert mgr.list_planets_with_maps() == ["earth"]


def test_list_planets_ignores_dirs_without_elevation(tmp_path: Path) -> None:
    world_dir = tmp_path / "myworld"
    _make_map(world_dir / "maps", "earth")
    # A map dir missing elevation.png is not yet a usable map.
    (world_dir / "maps" / "wip").mkdir(parents=True)

    mgr = MapManager(world_dir)
    assert mgr.list_planets_with_maps() == ["earth"]
