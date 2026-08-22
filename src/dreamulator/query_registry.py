"""查询注册表——守护轴「原语」的集中管理与 schema 生成（harness-p2-queries.md）。

原语（供 harness 检测 / agent 调用）通过 ``@query`` decorator 在此注册。注册表是
「有哪些查询」的**单一数据源**，自动产出 JSON Schema（供前端 + LLM function-calling）。

**中性模块**：``engine/`` 与 ``map/`` 都 import 这里的 ``@query``，本模块不 import
它们——避免 engine ↔ guard 循环依赖。decorator 不改函数行为：被装饰的函数仍是
纯函数，可直接调用、可直接单测。

**标记约定**：decorated = 可查询原语；undecorated = 内部实现。``dimension`` 挂
harness.md §9.2 维度（sky / anchor / …），是「有哪些查询」的索引。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

__all__ = ["QuerySpec", "get_query", "list_queries", "query"]


@dataclass(frozen=True)
class QuerySpec:
    """一个可查询原语的元数据 + 纯函数（harness-p2-queries.md §3.1）。"""

    name: str
    description: str
    dimension: str
    context: str | None  # "entities" | "mesh" | None（无世界上下文）
    params_schema: dict[str, Any]
    result_schema: dict[str, Any] | None
    fn: Callable[..., Any]


_QUERIES: dict[str, QuerySpec] = {}


def query(
    *,
    name: str,
    description: str,
    dimension: str,
    context: str | None = None,
    params_model: type[BaseModel],
    result_model: type[BaseModel] | None = None,
) -> Callable[..., Any]:
    """标记一个纯函数为「原语」并注册（不改函数行为，返回原函数）。"""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        _QUERIES[name] = QuerySpec(
            name=name,
            description=description,
            dimension=dimension,
            context=context,
            params_schema=params_model.model_json_schema(),
            result_schema=result_model.model_json_schema() if result_model else None,
            fn=fn,
        )
        return fn

    return deco


def get_query(name: str) -> QuerySpec:
    """按稳定 ID 取一个原语（未注册则 ``KeyError``）。"""
    return _QUERIES[name]


def list_queries() -> list[dict[str, Any]]:
    """所有已注册原语，JSON 可序列化的 schema 列表（供 agent tools / 前端）。

    结构即 Claude API function-calling 的 ``tools`` 数组：``name`` /
    ``description`` / ``parameters``（JSON Schema）。
    """
    return [
        {
            "name": s.name,
            "description": s.description,
            "dimension": s.dimension,
            "context": s.context,
            "parameters": s.params_schema,
            "returns": s.result_schema,
        }
        for s in sorted(_QUERIES.values(), key=lambda q: q.name)
    ]
