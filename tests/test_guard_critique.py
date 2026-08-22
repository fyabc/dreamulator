"""Tests for dreamulator.guard.critique — the interrogation fact library (P3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dreamulator.guard import DIMENSIONS, gather_facts

if TYPE_CHECKING:
    from pathlib import Path


def test_dimensions_count() -> None:
    assert len(DIMENSIONS) == 9  # 对齐 harness.md §9.2 的九维


def test_dimensions_are_consistent() -> None:
    names = [d.name for d in DIMENSIONS]
    assert names == [
        "sky",
        "anchor",
        "climate",
        "ecology",
        "internal",
        "cross_layer",
        "numeric",
        "edge",
        "consequence",
    ]


def test_gather_facts_structure(tmp_path: Path) -> None:
    facts = gather_facts(tmp_path)  # 未构建世界 → fact_context 为 None
    assert set(facts) == {"fact_context", "queries", "dimensions"}
    # queries 来自注册表（7 个原语，与具体世界无关）
    assert len(facts["queries"]) == 7
    assert len(facts["dimensions"]) == 9


def test_dimension_queries_index() -> None:
    """「维度即索引」：sky 维度应挂上全部 6 个天空原语，anchor 挂 cell_facts。"""
    by_name = {d.name: d for d in DIMENSIONS}
    assert set(by_name["sky"].queries) == {
        "angular_size",
        "apparent_illuminance",
        "hill_radius",
        "sky_position",
        "tidal_amplitude",
        "transit_classification",
    }
    assert by_name["anchor"].queries == ("cell_facts",)
