"""Tests for dreamulator.query_registry — the query registry (P2c)."""

from __future__ import annotations

import json

import pytest

from dreamulator.engine import sky_geometry  # noqa: F401 触发 @query 注册
from dreamulator.map import query as map_query  # noqa: F401 触发 @query 注册
from dreamulator.query_registry import get_query, list_queries


def test_list_queries_has_all_primitives() -> None:
    names = {q["name"] for q in list_queries()}
    assert names == {
        "angular_size",
        "apparent_illuminance",
        "cell_facts",
        "hill_radius",
        "sky_position",
        "tidal_amplitude",
        "transit_classification",
    }


def test_query_schema_is_json_serializable() -> None:
    # list_queries() 输出必须 JSON 可序列化（供 agent tools / 前端）。
    json.dumps(list_queries())


def test_query_dimensions() -> None:
    by_name = {q["name"]: q for q in list_queries()}
    assert by_name["angular_size"]["dimension"] == "sky"
    assert by_name["sky_position"]["dimension"] == "sky"
    assert by_name["transit_classification"]["dimension"] == "sky"
    assert by_name["cell_facts"]["dimension"] == "anchor"


def test_query_contexts() -> None:
    by_name = {q["name"]: q for q in list_queries()}
    assert by_name["angular_size"]["context"] is None
    assert by_name["sky_position"]["context"] == "entities"
    assert by_name["transit_classification"]["context"] == "entities"
    assert by_name["cell_facts"]["context"] == "mesh"


def test_get_query_returns_spec() -> None:
    spec = get_query("sky_position")
    assert spec.name == "sky_position"
    assert spec.context == "entities"
    assert "observer_id" in spec.params_schema["properties"]
    # result_model 提供了出参 schema
    assert spec.result_schema is not None
    assert "altitude_deg" in spec.result_schema["properties"]


def test_decorator_preserves_function() -> None:
    # 被装饰函数仍是原纯函数（可直接调用、可单测）。
    assert sky_geometry.angular_size(71355.2, 0.00494 * 149_597_870.7) == pytest.approx(
        11.0, abs=0.1
    )
