"""地图空间查询原语（harness-p2-queries.md）。

``nearest_cell`` / ``cell_facts`` 是锚点空间查询的通用工具：给定 (lon, lat)，
用 KD-tree（``build_export_tree``）找最近 cell，返回其事实。**纯函数、显式依赖**
（mesh + tree 由调用方传入），缓存由调用方（skill/CLI/API）管理——不在这里隐式
加载 cvt_mesh.json。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from dreamulator.query_registry import query

if TYPE_CHECKING:
    from scipy.spatial import cKDTree

    from dreamulator.map.models import CVTMesh, VoronoiCell

__all__ = ["cell_facts", "lonlat_to_xyz", "nearest_cell"]


def lonlat_to_xyz(lon_deg: float, lat_deg: float) -> tuple[float, float, float]:
    """等距圆柱 (lon, lat) 度 → 单位球 XYZ（与 ``export.py`` 网格同约定）。"""
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    cos_lat = math.cos(lat)
    return (cos_lat * math.cos(lon), math.sin(lat), cos_lat * math.sin(lon))


def nearest_cell(mesh: CVTMesh, tree: cKDTree, lon_deg: float, lat_deg: float) -> VoronoiCell:
    """最近 cell：给定 (lon, lat) 度，返回球面上最近的 ``VoronoiCell``。

    ``tree`` 由 ``build_export_tree(mesh)`` 构建（``export.py``），调用方缓存。
    """
    import numpy as np

    x, y, z = lonlat_to_xyz(lon_deg, lat_deg)
    _, indices = tree.query(np.array([[x, y, z]], dtype=np.float64))
    return mesh.cells[int(indices[0])]


class CellFactsParams(BaseModel):
    """``cell_facts`` 的入参（mesh + tree 由分发器注入）。"""

    lon_deg: float
    lat_deg: float


@query(
    name="cell_facts",
    description="锚点空间查询：最近 cell 的事实（koppen/驯化/离岸/海拔/biome）",
    dimension="anchor",
    context="mesh",
    params_model=CellFactsParams,
)
def cell_facts(mesh: CVTMesh, tree: cKDTree, lon_deg: float, lat_deg: float) -> dict[str, Any]:
    """锚点空间查询：最近 cell 的事实（koppen/驯化/离岸/海拔/biome/…）。

    返回的字段对齐 harness.md §9.2 的三个维度：地理锚点（海拔/离岸/地壳）、
    气候一致性（koppen/温/降水）、生态一致性（biome/驯化/NPP/土壤）。
    """
    cell = nearest_cell(mesh, tree, lon_deg, lat_deg)
    return {
        "cell_id": cell.id,
        "lon": cell.lon,
        "lat": cell.lat,
        "elevation": cell.elevation,
        "crust_type": cell.crust_type,
        "plate_id": cell.plate_id,
        "koppen_class": cell.koppen_class,
        "biome": cell.biome,
        "distance_to_coast_km": cell.distance_to_coast_km,
        "domesticable_tags": cell.domesticable_tags,
        "temperature_C": cell.temperature_C,
        "precipitation_mm": cell.precipitation_mm,
        "soil_type": cell.soil_type,
        "soil_fertility": cell.soil_fertility,
        "npp_gc_m2_yr": cell.npp_gc_m2_yr,
    }
