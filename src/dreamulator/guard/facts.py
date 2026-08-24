"""事实上下文（Fact Context）——守护轴的事实库（harness.md §5）。

``build_fact_context`` 把「模板渲染上下文」从角色键（``body`` / ``star`` /
``orbit`` / ``derived`` / ``satellite``）升级为「实体系统上的物化视图」，是
``doc_render`` 的扩展，也是 griller/answerer 子代理取证（防幻觉）的单一事实源。

设计要点：

- **实体寻址**：天体按稳定 ID 从 ``system_catalog.yaml`` 建表（``entities``）。
  body 的 ``physical`` / ``orbit`` / ``derived`` 拍平到顶层（
  ``entities.satellite_nacrea.axial_tilt_deg``），``atmosphere`` /
  ``hydrosphere`` / ``lithosphere`` 作为子系统保留嵌套（含 ``composition`` /
  ``crust_composition`` 等嵌套映射）。恒星原样键控。
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

from dreamulator.models.layers import Layer
from dreamulator.resolver import LayerResolver

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["build_fact_context"]

# body 顶层保留键（不参与拍平，避免被 physical/orbit/derived 覆盖）。
_BODY_IDENTITY_KEYS = (
    "id",
    "name",
    "body_type",
    "parent_id",
    "in_planets_yaml",
    "magnetic_field_strength_ut",
    "description",
)

# 拍平到实体顶层的子块（纯标量键，与顶层无冲突）。
_FLAT_SECTIONS = ("physical", "orbit", "derived")

# 作为嵌套子系统保留的子块（含嵌套映射，如 composition / crust_composition）。
_NESTED_SECTIONS = ("atmosphere", "hydrosphere", "lithosphere")


def _read_yaml(path: Path) -> dict[str, Any] | None:
    """Read a YAML file as a mapping, or ``None`` on any failure."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Failed to read fact context file %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _flatten_body(body: dict[str, Any]) -> dict[str, Any]:
    """Flatten a system_catalog body entry into an entity attribute mapping.

    ``physical`` / ``orbit`` / ``derived`` are promoted to the top level so
    ``entities.<id>.axial_tilt_deg`` / ``.solar_day_days`` / ``.period_days``
    address naturally; ``atmosphere`` / ``hydrosphere`` / ``lithosphere`` stay
    nested (they carry nested ``composition`` / ``crust_composition`` maps).
    """
    entity: dict[str, Any] = {k: body[k] for k in _BODY_IDENTITY_KEYS if k in body}
    for section in _FLAT_SECTIONS:
        sub = body.get(section)
        if isinstance(sub, dict):
            entity.update(sub)
    for section in _NESTED_SECTIONS:
        sub = body.get(section)
        if isinstance(sub, dict):
            entity[section] = sub
    entity["is_satellite"] = entity.get("body_type") == "natural_satellite"
    return entity


def _load_entities(catalog: dict[str, Any]) -> dict[str, Any]:
    """Key celestial bodies by stable ID (stars as-is, bodies flattened)."""
    entities: dict[str, Any] = {}
    for star in catalog.get("stars") or []:
        if isinstance(star, dict) and star.get("id") is not None:
            entities[str(star["id"])] = star
    for body in catalog.get("bodies") or []:
        if isinstance(body, dict) and body.get("id") is not None:
            entities[str(body["id"])] = _flatten_body(body)
    return entities


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
        "entities": _load_entities(catalog),
        "aggregates": _load_aggregates(resolver),
        "spatial": {},
    }
