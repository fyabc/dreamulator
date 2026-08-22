"""拷问编排——griller/answerer 的事实库与维度清单（harness.md §9）。

P3 的**确定性内核**：把 §9.2 维度清单编码为机器可读数据，并提供 ``gather_facts``
取证入口（事实上下文 + 可调用原语）。实际的 griller/answerer 子代理互审由
``/grill-world`` skill 编排（Claude Code，Workflow 需用户显式授权）。

**防幻觉优先级**（§9.1）：事实上下文 > 维度清单 > 证据锚定 > 多代理。本模块交付
前两者——answerer 只许从 ``gather_facts`` 返回的事实库取证。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from dreamulator.guard.facts import build_fact_context
from dreamulator.query_registry import list_queries

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["DIMENSIONS", "Dimension", "gather_facts"]


@dataclass(frozen=True)
class Dimension:
    """一条拷问维度（harness.md §9.2）——「有哪些查询」的索引。"""

    name: str  # slug：sky / anchor / climate / …
    label: str  # 中文标签
    check: str  # 检查什么
    queries: tuple[str, ...]  # 服务该维度的原语（query_registry 的 name）


# §9.2 维度清单。queries 空 = 目前靠事实上下文的 aggregates 覆盖（无独立原语）。
DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        "sky",
        "天空现象/轨道几何",
        "凌/食/视直径/地平线可见性/天体亮度；光污染 vs 观测条件",
        (
            "angular_size",
            "apparent_illuminance",
            "hill_radius",
            "sky_position",
            "tidal_amplitude",
            "transit_classification",
        ),
    ),
    Dimension("anchor", "地理锚点", "文明锚点 vs 实际地形/海岸/板块", ("cell_facts",)),
    Dimension("climate", "气候一致性", "农业/生活方式 vs Köppen/降水/季节", ()),
    Dimension("ecology", "生态一致性", "驯化潜力 vs 作物/役畜/大型草食动物", ()),
    Dimension("internal", "层内逻辑", "同层设定自相矛盾", ()),
    Dimension("cross_layer", "跨层因果", "上层是否依赖已推翻的下层设定", ()),
    Dimension("numeric", "数值", "文档手抄数字 vs 引擎输出", ()),
    Dimension("edge", "边缘条件", "极昼夜/日食季/潮汐极值是否被考虑", ()),
    Dimension(
        "consequence",
        "后果映射",
        "外生变量/软魔法是否把后果映射到状态变量（Sanderson 第一定律）",
        (),
    ),
)


def gather_facts(world_dir: Path, branch: str | None = None) -> dict[str, Any]:
    """取证：给 answerer 的**事实库**（防幻觉的根本，优先级最高）。

    Returns:
        ``{"fact_context": …, "queries": …, "dimensions": …}`` —— answerer 只许
        从这里取证，每条结论必须附 ``文件:行号`` / ``derived 字段`` / 文献出处。
    """
    return {
        "fact_context": build_fact_context(world_dir, branch),
        "queries": list_queries(),
        "dimensions": [
            {"name": d.name, "label": d.label, "check": d.check, "queries": list(d.queries)}
            for d in DIMENSIONS
        ],
    }
