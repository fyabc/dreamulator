"""Narrator — generate conversational world descriptions via Claude API."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models.layers import LAYER_ORDER
from .resolver import LayerResolver
from .world_manager import WorldManager

# Type alias for the streaming text callback.
# Called with each incremental text delta as it arrives.
StreamCallback = Callable[[str], None]

_DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass
class _ApiConfig:
    """Resolved API configuration (key + optional base URL + model)."""

    api_key: str
    base_url: str | None = None
    model: str = _DEFAULT_MODEL


def _read_claude_settings() -> dict:
    """Read ~/.claude/settings.json if it exists."""
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        with settings_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _resolve_api_config(model_override: str | None = None) -> _ApiConfig:
    """Resolve API key, base URL, and model.

    Priority for each field:
      1. Explicit override (model only) or environment variables
      2. ~/.claude/settings.json → env.* fields, then top-level "model"

    Args:
        model_override: Explicit model from CLI (takes highest priority).

    Raises:
        RuntimeError: If no API key can be found.
    """
    settings = _read_claude_settings()
    env = settings.get("env", {})

    # API key: env vars → settings.json env
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        api_key = env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        raise RuntimeError(
            "未找到 API 密钥。请通过以下任一方式设置：\n"
            "  1. 环境变量: export ANTHROPIC_API_KEY=your-key\n"
            "  2. 配置文件: ~/.claude/settings.json 中的 env.ANTHROPIC_API_KEY\n"
            "     或 env.ANTHROPIC_AUTH_TOKEN"
        )

    # Base URL: env var → settings.json env
    base_url = os.environ.get("ANTHROPIC_BASE_URL") or env.get("ANTHROPIC_BASE_URL")

    # Model: CLI override → env var → settings.json env → settings.json top-level → default
    resolved_model = (
        model_override
        or os.environ.get("ANTHROPIC_MODEL")
        or env.get("ANTHROPIC_MODEL")
        or settings.get("model")
        or _DEFAULT_MODEL
    )

    return _ApiConfig(api_key=api_key, base_url=base_url, model=resolved_model)

# ruff: noqa: E501
_SYSTEM_PROMPT = """\
你是一位架空世界设定顾问。你的任务是使用正式、流畅的中文，系统性地描述一个虚构世界的主要特征。

风格要求：
- 语言风格：正式、客观、严谨，类似学术报告或设定集。避免口语化表达、网络用语、语气词（如"嘛""啦""呢"）和第一人称对话体
- 结构清晰：按层级顺序组织叙述——恒星系 → 行星轨道 → 地质与卫星 → 气候 → 生态 → 文明
- 参数呈现：对数值型数据使用括号补充说明（如"地球表面约 71% 被水覆盖（平均深度约 3.7 公里）"），避免逐条罗列
- 未设定内容：若某些层级尚未设定，简要注明"该层面尚待设定"即可，不要编造数据
- 分支世界：先说明其与基础世界的分叉层级，再重点描述差异
- 输出格式：使用 Markdown，适当使用标题（##、###）和加粗（**关键词**）以增强可读性
"""


def collect_world_summary(world_name: str, branch: str | None = None) -> str:
    """Collect all configured layer data for a world/branch as YAML text.

    Args:
        world_name: Name of the world.
        branch: Optional branch name.

    Returns:
        Formatted string containing all world data.

    Raises:
        FileNotFoundError: If the world does not exist.
    """
    mgr = WorldManager()
    world_dir = mgr.world_dir(world_name)
    config = mgr.load_world(world_name)

    parts: list[str] = []

    # World metadata
    parts.append(f"# 世界: {config.metadata.name}")
    if config.metadata.description:
        parts.append(f"描述: {config.metadata.description}")
    parts.append("")

    # Branch metadata
    if branch is not None:
        from .branch_manager import BranchManager

        branch_mgr = BranchManager(world_dir)
        branch_meta = branch_mgr.get_branch(branch)
        parts.append(f"## 分支: {branch_meta.name}")
        parts.append(f"分叉层: {branch_meta.fork_layer.value if branch_meta.fork_layer else '-'}")
        if branch_meta.description:
            parts.append(f"分支描述: {branch_meta.description}")
        if branch_meta.tags:
            parts.append(f"标签: {', '.join(branch_meta.tags)}")
        parts.append("")

    # Layer data
    resolver = LayerResolver(world_dir, branch)
    has_any_data = False

    for layer in LAYER_ORDER:
        source = resolver.resolve_layer(layer)
        if source.input_dir is None:
            continue

        # Read all YAML files in the input directory
        yaml_files = sorted(source.input_dir.glob("*.yaml"))
        if not yaml_files:
            continue

        has_any_data = True
        layer_label = layer.value
        source_label = source.source
        parts.append(f"## {layer_label} 层 (来源: {source_label})")

        for yaml_file in yaml_files:
            with yaml_file.open("r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                parts.append(f"### {yaml_file.name}")
                parts.append("```yaml")
                parts.append(content)
                parts.append("```")
                parts.append("")

    if not has_any_data:
        parts.append("（该世界尚未配置任何层级数据）")

    return "\n".join(parts)


def build_prompt(summary: str) -> list[dict[str, str]]:
    """Build the message list for the Claude API call.

    Args:
        summary: World data summary text.

    Returns:
        List of message dicts with 'role' and 'content'.
    """
    return [
        {"role": "user", "content": f"请描述以下架空世界：\n\n{summary}"},
    ]


def narrate(
    world_name: str,
    branch: str | None = None,
    model: str | None = None,
    stream_callback: StreamCallback | None = None,
) -> str:
    """Generate a conversational description of a world using Claude.

    Args:
        world_name: Name of the world.
        branch: Optional branch name.
        model: Claude model ID. If None, resolved from environment /
               settings.json / default.
        stream_callback: Optional callback function that receives text deltas
                         as they arrive. If provided, enables streaming mode.

    Returns:
        Generated description text.

    Raises:
        FileNotFoundError: If the world does not exist.
        ImportError: If the anthropic package is not installed.
        RuntimeError: If no API key can be found.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "narrate 功能需要 anthropic 包。请运行: uv sync --extra narrate"
        ) from None

    api_config = _resolve_api_config(model_override=model)

    summary = collect_world_summary(world_name, branch)
    messages = build_prompt(summary)

    client_kwargs: dict[str, str] = {"api_key": api_config.api_key}
    if api_config.base_url:
        client_kwargs["base_url"] = api_config.base_url

    client = anthropic.Anthropic(**client_kwargs)

    if stream_callback:
        # Streaming mode
        text_parts: list[str] = []
        with client.messages.stream(
            model=api_config.model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                text_parts.append(text)
                stream_callback(text)
        return "".join(text_parts)
    else:
        # Non-streaming mode
        response = client.messages.create(
            model=api_config.model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        # Filter for text blocks only (skip thinking blocks)
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "".join(text_parts)
