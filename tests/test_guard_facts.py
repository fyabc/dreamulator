"""Tests for dreamulator.guard.facts — the fact context builder (harness.md §5).

Covers entity flattening (physical/orbit/derived promoted, subsystems nested,
is_satellite), aggregate loading from per-layer summaries, the None degradation
contract, and branch inheritance (own derived / no fallback / inherit root) —
mirroring the branch-inheritance edge cases previously pinned in
``test_doc_render.py`` for the role-keyed ``world_parameters.yaml``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from dreamulator.guard.facts import build_fact_context

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

# Minimal system_catalog.yaml: 1 star, 1 planet, 1 tidally-locked satellite.
_CATALOG: dict[str, object] = {
    "stars": [
        {"id": "star_sol", "name": "Sol", "luminosity_sol": 1.0},
    ],
    "bodies": [
        {
            "id": "planet_terra",
            "name": "Terra",
            "body_type": "planet",
            "parent_id": "star_sol",
            "physical": {
                "mass_earth": 1.0,
                "radius_km": 6371.0,
                "axial_tilt_deg": 23.4,
                "albedo": 0.3,
            },
            "orbit": {"semi_major_axis_au": 1.0, "period_days": 365.25},
            "derived": {"instellation_w_m2": 1361.0, "tidally_locked": False},
        },
        {
            "id": "satellite_luna",
            "name": "Luna",
            "body_type": "natural_satellite",
            "parent_id": "planet_terra",
            "physical": {
                "mass_earth": 0.0123,
                "radius_km": 1737.0,
                "axial_tilt_deg": 6.7,
            },
            "orbit": {"semi_major_axis_au": 0.00257, "period_days": 27.3},
            "atmosphere": {"surface_pressure_atm": None},
            "derived": {"tidally_locked": True, "solar_day_days": 29.5},
        },
    ],
}


def _write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def _make_world(root: Path, *, catalog: object | None = _CATALOG) -> Path:
    """Create a minimal world with astronomy input (and optionally derived)."""
    world = root / "test-world"
    _write_yaml(world / "layers" / "astronomy" / "input" / "stellar.yaml", {"stars": []})
    if catalog is not None:
        _write_yaml(world / "layers" / "astronomy" / "derived" / "system_catalog.yaml", catalog)
    return world


def _add_summary(world: Path, layer: str, filename: str, data: object) -> None:
    # The resolver only exposes a layer's derived dir once the layer has input
    # (see LayerResolver.resolve_layer) — write a marker so it resolves.
    _write_yaml(world / "layers" / layer / "input" / "note.md", "placeholder")
    _write_yaml(world / "layers" / layer / "derived" / filename, data)


# ---------------------------------------------------------------------------
# Entity flattening
# ---------------------------------------------------------------------------


def test_entities_keyed_by_stable_id(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    ctx = build_fact_context(world)
    assert ctx is not None
    assert set(ctx["entities"]) == {"star_sol", "planet_terra", "satellite_luna"}


def test_body_flat_sections_promoted(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    ctx = build_fact_context(world)
    assert ctx is not None
    luna = ctx["entities"]["satellite_luna"]
    assert luna["axial_tilt_deg"] == 6.7  # from physical
    assert luna["period_days"] == 27.3  # from orbit
    assert luna["solar_day_days"] == 29.5  # from derived
    assert luna["tidally_locked"] is True  # from derived
    assert luna["mass_earth"] == 0.0123  # from physical
    assert luna["parent_id"] == "planet_terra"  # identity preserved


def test_nested_subsystems_preserved(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    ctx = build_fact_context(world)
    assert ctx is not None
    luna = ctx["entities"]["satellite_luna"]
    assert luna["atmosphere"] == {"surface_pressure_atm": None}


def test_is_satellite_flag(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    ctx = build_fact_context(world)
    assert ctx is not None
    assert ctx["entities"]["satellite_luna"]["is_satellite"] is True
    assert ctx["entities"]["planet_terra"]["is_satellite"] is False


def test_star_entity_passthrough(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    ctx = build_fact_context(world)
    assert ctx is not None
    assert ctx["entities"]["star_sol"]["luminosity_sol"] == 1.0


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def test_aggregates_loaded(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _add_summary(
        world, "climate", "climate_summary.yaml", {"temperature_C": {"land": {"mean": 12.0}}}
    )
    _add_summary(world, "ecology", "ecology_summary.yaml", {"n_land": 100})
    _add_summary(
        world,
        "civilization",
        "habitability_summary.yaml",
        {"habitable_coast": {"n_cells": 10}},
    )
    _add_summary(
        world,
        "civilization",
        "civilization_seed_candidates.yaml",
        {"n_candidates": 3, "candidates": []},
    )

    ctx = build_fact_context(world)
    assert ctx is not None
    assert ctx["aggregates"]["climate"]["temperature_C"]["land"]["mean"] == 12.0
    assert ctx["aggregates"]["ecology"]["n_land"] == 100
    civ = ctx["aggregates"]["civilization"]
    assert civ["habitable_coast"]["n_cells"] == 10
    assert civ["seed_candidates"]["n_candidates"] == 3


def test_aggregates_absent_without_summaries(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    ctx = build_fact_context(world)
    assert ctx is not None
    assert ctx["aggregates"] == {}


def test_spatial_placeholder_empty(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    ctx = build_fact_context(world)
    assert ctx is not None
    assert ctx["spatial"] == {}


# ---------------------------------------------------------------------------
# Degradation (None) contract
# ---------------------------------------------------------------------------


def test_none_when_no_catalog(tmp_path: Path) -> None:
    world = _make_world(tmp_path, catalog=None)
    assert build_fact_context(world) is None


def test_none_when_catalog_non_mapping(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    path = world / "layers" / "astronomy" / "derived" / "system_catalog.yaml"
    with path.open("w", encoding="utf-8") as f:
        f.write("- just\n- a list\n")
    assert build_fact_context(world) is None


def test_none_when_catalog_deleted(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    (world / "layers" / "astronomy" / "derived" / "system_catalog.yaml").unlink()
    assert build_fact_context(world) is None


def test_nonexistent_branch(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    assert build_fact_context(world, "ghost") is None


# ---------------------------------------------------------------------------
# Branch inheritance
# ---------------------------------------------------------------------------


def _make_branch(world: Path, name: str, fork_layer: str) -> Path:
    branch_dir = world / "branches" / name
    _write_yaml(branch_dir / "branch.yaml", {"name": name, "fork_layer": fork_layer})
    return branch_dir


def test_branch_with_own_derived(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    branch_dir = _make_branch(world, "b1", "astronomy")
    _write_yaml(branch_dir / "layers" / "astronomy" / "input" / "stellar.yaml", {"stars": []})
    branch_catalog = {
        "stars": [{"id": "star_b", "luminosity_sol": 2.0}],
        "bodies": [],
    }
    _write_yaml(
        branch_dir / "layers" / "astronomy" / "derived" / "system_catalog.yaml", branch_catalog
    )
    ctx = build_fact_context(world, "b1")
    assert ctx is not None
    assert ctx["entities"]["star_b"]["luminosity_sol"] == 2.0


def test_branch_input_without_derived_does_not_fall_back(tmp_path: Path) -> None:
    """Branch overrides astronomy input but has no derived → None (no root fallback)."""
    world = _make_world(tmp_path)
    branch_dir = _make_branch(world, "b2", "astronomy")
    _write_yaml(branch_dir / "layers" / "astronomy" / "input" / "stellar.yaml", {"stars": []})
    assert build_fact_context(world, "b2") is None


def test_branch_inherits_root_when_no_override(tmp_path: Path) -> None:
    """Branch forking after astronomy inherits root astronomy derived."""
    world = _make_world(tmp_path)
    branch_dir = _make_branch(world, "b3", "climate")
    _write_yaml(branch_dir / "layers" / "climate" / "input" / "note.md", "hello")
    ctx = build_fact_context(world, "b3")
    assert ctx is not None
    assert "star_sol" in ctx["entities"]
