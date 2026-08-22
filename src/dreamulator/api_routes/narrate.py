"""Narrate API route — SSE streaming world narration."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from dreamulator.narrator import NarrateResult

router = APIRouter(prefix="/api/worlds", tags=["narrate"])


class NarrateRequest(BaseModel):
    """Request body for narrating a world."""

    branch: str | None = Field(default=None, description="Branch name")
    model: str | None = Field(default=None, description="Claude model ID (auto-resolved if None)")
    max_tokens: int = Field(default=32768, description="Maximum output tokens")


@router.post("/{world_name}/narrate")
async def narrate_world(world_name: str, req: NarrateRequest) -> StreamingResponse:
    """Stream a narration of a world via Server-Sent Events.

    SSE event types:
      - ``delta``: ``{"text": "..."}`` — incremental text chunk
      - ``done``: ``{"input_tokens": N, "output_tokens": N, "total_tokens": N}``
      - ``error``: ``{"detail": "..."}``
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        q: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        def stream_callback(text: str) -> None:
            loop.call_soon_threadsafe(q.put_nowait, ("delta", text))

        async def run_narrate() -> None:
            try:
                from dreamulator import narrator

                result = await loop.run_in_executor(
                    None,
                    lambda: narrator.narrate(
                        world_name,
                        branch=req.branch,
                        model=req.model,
                        max_tokens=req.max_tokens,
                        stream_callback=stream_callback,
                    ),
                )
                q.put_nowait(("done", result))
            except Exception as exc:
                q.put_nowait(("error", exc))

        task = asyncio.create_task(run_narrate())

        while not task.done() or not q.empty():
            try:
                kind, payload = await asyncio.wait_for(q.get(), timeout=15.0)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue

            if kind == "delta":
                chunk = json.dumps({"text": payload}, ensure_ascii=False)
                yield f"event: delta\ndata: {chunk}\n\n"
            elif kind == "done":
                result: NarrateResult = payload  # type: ignore[assignment]
                usage = {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                }
                yield f"event: done\ndata: {json.dumps(usage)}\n\n"
            elif kind == "error":
                exc = payload
                if isinstance(exc, ImportError):
                    detail = "narrate 功能需要 anthropic 包。请运行: uv sync --extra narrate"
                elif isinstance(exc, (RuntimeError, FileNotFoundError)):
                    detail = str(exc)
                else:
                    detail = f"叙述生成失败: {exc}"
                error_data = json.dumps({"detail": detail}, ensure_ascii=False)
                yield f"event: error\ndata: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
