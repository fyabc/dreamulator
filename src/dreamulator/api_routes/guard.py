"""Guard (harness) API routes — query registry 的原语查询（harness-p2-queries.md）。

- ``GET  /api/guard/queries``        列出所有原语 + JSON Schema（供前端/agent）
- ``POST /api/guard/queries/{name}`` 注入世界上下文后运行一个原语

ADR 状态机 + 过期检测仍走 CLI（``dreamulator guard ...``）；API 端点留待后续。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dreamulator.guard import list_queries, run_query
from dreamulator.world_manager import WorldManager

router = APIRouter(prefix="/api/guard", tags=["guard"])

_manager = WorldManager()


class RunQueryRequest(BaseModel):
    """运行一个原语的请求体。"""

    world: str = Field(description="世界名")
    branch: str | None = Field(default=None, description="分支名")
    params: dict[str, Any] = Field(default_factory=dict, description="原语入参")


@router.get("/queries")
def guard_list_queries() -> list[dict[str, Any]]:
    """列出所有可查询原语（name / description / dimension / parameters）。"""
    return list_queries()


@router.post("/queries/{name}")
def guard_run_query(name: str, req: RunQueryRequest) -> dict[str, Any]:
    """注入世界上下文后运行一个原语，返回 JSON 可序列化结果。"""
    try:
        world_dir = _manager.world_dir(req.world)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"World '{req.world}' not found") from None

    try:
        return run_query(world_dir, req.branch, name, req.params)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown query '{name}'") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"World data not built: {exc}") from None
