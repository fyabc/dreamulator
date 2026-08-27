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

## 6 200K 输出 → 出版级高清地形图：完整链路（2026-08 调研）

参照物是群友制作的成品图（Photoshop + WorldMachine + Gaea 2 + QGIS，4000×4150 的
国家级地形图，山脉有分形细节、河网完整、海岸复杂）。调研的核心结论先说：这套商业链路里
WorldMachine/Gaea 真正干的活，是「保持大尺度地形不变，用噪声加水力侵蚀合成中尺度细节、
雕刻出河谷」——这件事既有商业交互工具可做，也有可程序化的开源替代（Landlab/Fastscape）。
开源路线还有一个商业链给不了的优势：可以用我们引擎自己的降水场给侵蚀加权（真实的空间
降雨差异），而不是商业软件默认的均匀降雨。

下面按制作顺序给出推荐链路，每步注明商业与开源两种选项。

**第 0 步：导出升级（引擎侧，前置条件）。** 当前 `export.py` 输出最近邻采样的
4096×2048 栅格，只够当草图。要做高清图，首先应导出 16-bit 以上的 GeoTIFF 或 EXR 高程
（8-bit 高程在全球 -11 km 到 +9 km 范围内每级约 78 m，做山体阴影会出现严重色带），
同时分层导出气候/生态色图，并写入球面经纬坐标参考。

**第 1 步：上采样 + 细节合成。** 几何插值用双三次——最近邻和双线性都会在山体阴影下
露出网格伪影。插值只解决「平滑放大」，分形细节要靠合成补：自然地形的高程功率谱近似
1/f^2.4–3，可以按低分辨率 DEM 实测的谱生成高频分形噪声（ridged 变体出山脊），并用坡度/
山地 mask 调制振幅（山区强、平原和洋底接近零——这个 mask 引擎现成）。商业工具里这对应
Gaea 的 File 节点导入后接 Combine（MAX 或 BLEND 0.3–0.5）、WorldMachine 的 File Input 接
Combiner。GAN/扩散模型如果要用，只当作「细节层生成器」、输出叠加到基底上，且必须用 mask
限定区域；**Real-ESRGAN 这类图像超分不要碰高程数据**——它会「画」出油彩状假纹理、破坏
高程保真，只适合放大已经渲染好的彩色地图。

**第 2 步：侵蚀造型。** 目的不是重塑山脉位置，而是把第 1 步的噪声「造型」成自然的山脊和
河谷网络。做法是低强度水力侵蚀：Gaea 的 Erosion 节点 Duration 2–5、低 Strength、
用 Selective Processing 限定只对山区降雨；WorldMachine 用高 Rock hardness、低 Filter
strength，分块构建时必须勾 Scale Independence，否则瓦片间结果不一致。开源替代是 Landlab 的
FastscapeEroder/SPACE 加 LinearDiffuser，在低分辨率 DEM 上跑数步即可——它可脚本化进管线，
且能接引擎降水场做非均匀降雨侵蚀。

**第 3 步：河网。** 逼真的树状河网必须在侵蚀之后的高分辨率 DEM 上提取，而不是在 50 km 的
Voronoi 数据上（那只有干流级骨架），更不是 PS 手绘（手绘几乎必然犯支流逆流、汇合缺失这类
水文学错误）。开源工具链：WhiteboxTools 的 `breach_depressions` 破洼（比填洼更自然）→
`d8_flow_accum` 汇流累积 → 阈值提河道（或 GRASS `r.watershed` + `r.stream.order` 做
Strahler 分级）→ 矢量化 + Chaiken 平滑 → 渲染时按河道级别变宽。若第 2 步用了侵蚀，其自带的
flow mask 与提取的河网天然自洽（河一定在谷底）。

**第 4 步：着色与阴影（QGIS/GDAL）。** `gdaldem hillshade` 做多方位、多尺度山体阴影
（注意经纬度坐标下必须做 z-factor 校正，1°≈111 km，否则阴影全平）；`gdaldem color-relief`
按高程停靠表做 hypso 着色（`palettes.py` 的色带可直接导出成停靠表），再叠生态栅格的植被色；
海岸线矢量化后平滑，消除栅格锯齿。

**第 5 步：标注排版（QGIS Layout）。** 中文注记（思源黑体加晕圈）、经纬网格与刻度、图例、
指北针、比例尺，导出高分辨率成图。

**第 6 步：Photoshop 收尾。** PS 只负责呈现层，不负责地形内容：多层山体阴影按混合模式
叠加、海洋渐变与海岸辉光、全图 Gradient Map 统一色调、纸张纹理、标题图廓。

**主要坑位**：等距圆柱投影在极地像素地面距离趋零，全球栅格上直接跑侵蚀/水文会在高纬失真
（应分区处理）；WorldMachine 分块构建有瓦片缝（加大 blending、勾 Scale Independence）；
位深 16-bit 是底线，要回炉 Gaea 再侵蚀的建议 32-bit EXR。

**哪些活应该由引擎做，而不是后期补**：侵蚀应迁到栅格上跑（50 km 的 Voronoi 细胞产不出
视觉意义的脊谷细节）；降水→侵蚀耦合是引擎独有优势；海岸线复杂度应在地形合成阶段高分辨率
生成，而不是靠下游平滑修锯齿；生态/气候色图应与地形同分辨率重栅格化。留给后期的只有标注
排版和制图风格这类呈现层工作。

**预算**：全开源路线 $0；最小商业组合是 Gaea Indie $99（8K 上限，对 4K 成图够用）或
WorldMachine Indie $119；全套商业工具约 $500 一次性（不含 PS 订阅）。
