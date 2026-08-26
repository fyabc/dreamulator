# Gaea 局部精细化

> **状态**：设计提案（未实现）——本文档的函数与配置 schema 均为伪代码，尚无实现代码。
> 2026-08-27 从 `pipelines/` 迁至 `proposals/`。

> 本文档描述「Gaea 局部精细化」——在跑完全球管线（地质 → 气候 → 生态）拿到
> **地形 / 气候 / 土壤 / 植被** 四个场之后，选取一个固定区域，用 Gaea 做高分辨率
> 细化，再把结果回导到 CVT 网格。
>
> 本阶段是**全局管线之后的区域后处理**，不是独立层级。在
> [world-generation-pipeline.md](../pipelines/world-generation-pipeline.md) 的阶段目录中位于生态层之后。

## 1 何时使用

在以下场景使用 Gaea 精细化：

- 需要**米级**地形细节（如河谷剖面、悬崖纹理）
- 需要**逼真侵蚀纹理**（Gaea Erosion2 的物理模拟质量远超简化版）
- 生成用于**叙事描写**的地形细节（`/narrate` 技能引用）
- 导出高分辨率**纹理贴图**给 3D 渲染

## 2 区域选择

通过经纬度边界框选择精细化区域：

```yaml
# data/worlds/myworld/layers/geological/input/gaea_refine.yaml
refine_regions:
  - id: "grand_canyon_area"
    name: "大峡谷区域"
    lat_min: 35.0
    lat_max: 37.5
    lon_min: -113.5
    lon_max: -111.0
    target_resolution: 4096   # Gaea output resolution
    erosion_passes: 3

  - id: "himalaya_region"
    name: "喜马拉雅区域"
    lat_min: 26.0
    lat_max: 32.0
    lon_min: 78.0
    lon_max: 90.0
    target_resolution: 8192
    erosion_passes: 5
```

## 3 球极平面投影

将球面区域投影到平面高度图（用于 Gaea 导入）：

**球极平面投影 (Stereographic Projection)**：

```
设投影中心为 (φ₀, λ₀)，球面点为 (φ, λ)：

k = 2R / (1 + sin(φ₀)·sin(φ) + cos(φ₀)·cos(φ)·cos(λ - λ₀))

x = k · cos(φ) · sin(λ - λ₀)
y = k · (cos(φ₀)·sin(φ) - sin(φ₀)·cos(φ)·cos(λ - λ₀))
```

**优点**：
- 保角（conformal）：局部形状不变
- 圆变圆：圆形特征保持圆形
- 适合小区域（< ~30° 跨度）

```python
def stereographic_project(
    mesh: CVTMesh,
    elevation_m: np.ndarray,
    center_lat_deg: float,
    center_lon_deg: float,
    radius_deg: float,
    resolution: int = 4096,
) -> tuple[np.ndarray, dict]:
    """Project a spherical region to stereographic plane.

    Returns:
        (heightmap_2d, projection_params) for Gaea import.
    """
    lat0 = radians(center_lat_deg)
    lon0 = radians(center_lon_deg)

    # Select nodes within radius
    dist = angular_distance_from_center(mesh.nodes, lat0, lon0)
    mask = dist < radians(radius_deg)

    selected_nodes = mesh.nodes[mask]
    selected_elev = elevation_m[mask]

    # Stereographic projection
    lat = arcsin(clip(selected_nodes[:, 1], -1, 1))
    lon = arctan2(selected_nodes[:, 2], selected_nodes[:, 0])

    cos_c = sin(lat0)*sin(lat) + cos(lat0)*cos(lat)*cos(lon - lon0)
    k = 2 / (1 + cos_c)

    x = k * cos(lat) * sin(lon - lon0)
    y = k * (cos(lat0)*sin(lat) - sin(lat0)*cos(lat)*cos(lon - lon0))

    # Interpolate to regular grid
    grid_x = linspace(-x.max(), x.max(), resolution)
    grid_y = linspace(-y.max(), y.max(), resolution)
    heightmap = griddata(
        stack([x, y], axis=-1),
        selected_elev,
        meshgrid(grid_x, grid_y),
        method='cubic',
    )

    params = {
        "center_lat": center_lat_deg,
        "center_lon": center_lon_deg,
        "radius_deg": radius_deg,
        "resolution": resolution,
        "x_range": (float(-x.max()), float(x.max())),
        "y_range": (float(-y.max()), float(y.max())),
    }

    return heightmap, params
```

## 4 Gaea 处理

Gaea 图（graph）配置：

```
File (import heightmap)
  → Math (normalize to 0-1)
  → Erode (thermal + hydraulic)
  → Rivers (flow simulation)
  → Sea (water level)
  → Export (16-bit PNG + flow data)
```

Gaea 处理通过 CLI 或 Python API 自动化（如果 Gaea 提供 API）。
否则，导出高度图后手动在 Gaea 中处理，再导入结果。

## 5 回导

将 Gaea 输出的精细化高度图反向投影回 CVT 网格：

```python
def import_gaea_refinement(
    mesh: CVTMesh,
    gaea_heightmap: np.ndarray,
    projection_params: dict,
    elevation_m: np.ndarray,
    blend_radius_deg: float = 2.0,
) -> np.ndarray:
    """Import Gaea-refined data back into CVT mesh.

    Uses feathered blending at the boundary of the refined region
    to avoid sharp discontinuities.

    Returns:
        Updated elevation array.
    """
    lat0 = radians(projection_params["center_lat"])
    lon0 = radians(projection_params["center_lon"])

    # For each CVT node in the region, inverse-project and sample
    dist = angular_distance_from_center(mesh.nodes, lat0, lon0)
    in_region = dist < radians(projection_params["radius_deg"])

    refined_elev = elevation_m.copy()

    for i in np.where(in_region)[0]:
        # Inverse stereographic projection
        lat, lon = inverse_stereographic(
            mesh.nodes[i], lat0, lon0, projection_params
        )
        # Sample Gaea heightmap
        gaea_val = sample_heightmap(gaea_heightmap, lat, lon, projection_params)
        refined_elev[i] = gaea_val

    # Feathered blending at boundary
    blend_mask = (dist > radians(projection_params["radius_deg"] - blend_radius_deg)) & \
                 (dist < radians(projection_params["radius_deg"] + blend_radius_deg))
    for i in np.where(blend_mask)[0]:
        d = dist[i]
        r = radians(projection_params["radius_deg"])
        br = radians(blend_radius_deg)
        alpha = smoothstep((d - (r - br)) / (2 * br))
        refined_elev[i] = (1 - alpha) * refined_elev[i] + alpha * elevation_m[i]

    return refined_elev
```
