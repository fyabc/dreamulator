"""查询分发——注入世界上下文后调用注册表原语（harness-p2-queries.md）。

``query_registry`` 只做「标记 + schema」；本模块做「分发」：把世界上下文
（entities / mesh）注入原语并调用，供 API / agent 使用。

import 原语模块以触发 ``@query`` 注册（模块导入一次，幂等）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import dreamulator.engine.sky_geometry  # noqa: F401 触发注册
import dreamulator.map.query  # noqa: F401 触发注册
from dreamulator.guard.facts import build_fact_context
from dreamulator.query_registry import get_query, list_queries

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["list_queries", "run_query"]


def run_query(
    world_dir: Path, branch: str | None, name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """按稳定 ID 调用一个原语，注入世界上下文，返回 JSON 可序列化结果。

    ``context`` 决定注入什么（见 QuerySpec）：None → 无；"entities" → 事实上下文；
    "mesh" → (cvt_mesh, KD-tree)。结果统一序列化为 dict。
    """
    spec = get_query(name)
    context = _build_context(world_dir, branch, spec.context)
    result = spec.fn(*context, **params)
    return _serialize(result)


def _build_context(world_dir: Path, branch: str | None, context: str | None) -> tuple[Any, ...]:
    if context is None:
        return ()
    if context == "entities":
        ctx = build_fact_context(world_dir, branch)
        return (ctx["entities"],) if ctx is not None else ({},)
    if context == "mesh":
        return _load_mesh_tree(world_dir, branch)
    raise ValueError(f"unknown context: {context}")


def _load_mesh_tree(world_dir: Path, branch: str | None) -> tuple[Any, ...]:
    """加载目标行星的 cvt_mesh + KD-tree（mesh 上下文）。"""
    import yaml
    from pydantic import TypeAdapter

    from dreamulator.map.export import build_export_tree
    from dreamulator.map.models import CVTMesh
    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)
    derived_dir = resolver.get_derived_dir("astronomy")
    assert derived_dir is not None
    with (derived_dir / "system_catalog.yaml").open(encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    planet_id = catalog["target_body_id"]

    mesh_path = world_dir / "maps" / planet_id / "cvt_mesh.json"
    from dreamulator.map.export import decompress_mesh_bytes

    mesh = TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(mesh_path.read_bytes()))
    return mesh, build_export_tree(mesh)


def _serialize(result: Any) -> dict[str, Any]:
    """把原语结果统一序列化为 dict（Pydantic model / dict / 标量）。"""
    if hasattr(result, "model_dump"):
        return cast("dict[str, Any]", result.model_dump())
    if isinstance(result, dict):
        return result
    return {"value": result}
