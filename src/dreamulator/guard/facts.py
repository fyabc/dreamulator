"""事实上下文（Fact Context）——守护轴的事实库（harness.md §5）。

``build_fact_context`` 把「模板渲染上下文」从角色键（``body`` / ``star`` /
``orbit`` / ``derived`` / ``satellite``）升级为「实体系统上的物化视图」，是
``doc_render`` 的扩展，也是 griller/answerer 子代理取证（防幻觉）的单一事实源。

设计要点：

- **实体寻址**：天体按稳定 ID 从 ``system_catalog.yaml`` 建表（``entities``）。
  body 的 ``physical`` / ``orbit`` / ``derived`` 拍平到顶层（
  ``entities.satellite_nacrea.axial_tilt_deg``），``atmosphere`` /
  ``hydrosphere`` / ``lithosphere`` 作为子系统保留嵌套（含 ``composition`` /
  ``crust_composition`` 等嵌套映射）。恒星原样键控。``orbits:`` 顶层条目是
  根数的权威存储（全精度 + Ω/ω/M₀/历元），合入对应实体并覆盖 ``bodies.orbit``
  的圆整渲染值。
- **聚合统计**：各层 ``*_summary.yaml`` 作为命名归约（``aggregates``），带溯源
  但非实体（``climate`` / ``ecology`` / ``civilization``）。
- **空间锚点**：``spatial`` 为 §6 几何查询的预计算缓存，P0 留空，P2 由
  ``queries.py`` 填充。

三用（harness.md §5.1）：设定文档模板、决策记录定量声明、agent 事实库。

纯函数、无 RNG、无 IO 副作用（只读 derived 文件），可独立单测。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import yaml

from dreamulator.models.catalog import load_entities
from dreamulator.models.layers import Layer
from dreamulator.resolver import LayerResolver

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["build_fact_context", "load_entities"]


def _read_yaml(path: Path) -> dict[str, Any] | None:
    """Read a YAML file as a mapping, or ``None`` on any failure."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Failed to read fact context file %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _load_aggregates(resolver: LayerResolver) -> dict[str, Any]:
    """Load per-layer summary files as named reductions (non-entity facts)."""
    aggregates: dict[str, Any] = {}

    climate_dir = resolver.get_derived_dir(Layer.CLIMATE)
    if climate_dir is not None:
        climate = _read_yaml(climate_dir / "climate_summary.yaml")
        if climate is not None:
            aggregates["climate"] = climate

    ecology_dir = resolver.get_derived_dir(Layer.ECOLOGY)
    if ecology_dir is not None:
        ecology = _read_yaml(ecology_dir / "ecology_summary.yaml")
        if ecology is not None:
            aggregates["ecology"] = ecology

    civ_dir = resolver.get_derived_dir(Layer.CIVILIZATION)
    if civ_dir is not None:
        civilization: dict[str, Any] = {}
        habitability = _read_yaml(civ_dir / "habitability_summary.yaml")
        if habitability is not None:
            civilization.update(habitability)
        seeds = _read_yaml(civ_dir / "civilization_seed_candidates.yaml")
        if seeds is not None:
            civilization["seed_candidates"] = seeds
        if civilization:
            aggregates["civilization"] = civilization

    return aggregates


def build_fact_context(world_dir: Path, branch: str | None = None) -> dict[str, Any] | None:
    """Build the fact context for a world/branch.

    The context is a materialized view over the entity system (harness.md §5.3):
    entities keyed by stable ID from ``system_catalog.yaml``, plus per-layer
    ``*_summary.yaml`` named reductions.  ``spatial`` is a P0 placeholder filled
    by ``queries.py`` in P2.

    Returns:
        ``{"entities": {...}, "aggregates": {...}, "spatial": {...}}``, or
        ``None`` when ``system_catalog.yaml`` is unavailable (fresh clone,
        unbuilt branch, missing/corrupt file) — mirroring the degradation
        contract of ``doc_render.load_render_context``.
    """
    try:
        resolver = LayerResolver(world_dir, branch)
        astronomy_dir = resolver.get_derived_dir(Layer.ASTRONOMY)
    except FileNotFoundError:
        return None
    if astronomy_dir is None:
        return None

    catalog = _read_yaml(astronomy_dir / "system_catalog.yaml")
    if catalog is None:
        return None

    return {
        "entities": load_entities(catalog),
        "aggregates": _load_aggregates(resolver),
        "spatial": {},
        # The target body's sky view (angular diameters / magnitudes / eclipse),
        # keyed by stable id (``sky.planet_aegis.angular_diameter_deg``).  Empty
        # dict when the catalog has no sky section (older worlds / no satellite).
        "sky": catalog.get("sky") or {},
    }
