# 全球画布链：画布生成、外存水文与区域裁窗

> 本文描述已实现的全球高清地形链：S1 把每块大陆整块生成为一张 terrain-diffusion（下称 TD）分块画布，
> S2 在画布上做外存水文，S3 裁出区域数据包交给现有渲染腿，另有一张整画布的超高清总览图。
>
> 源码：S1 在 `src/dreamulator/map/td_canvas.py`（几何、布局、归属、混合与取样）、`td_canvas_build.py`
> （布局配置与每张画布的输入）、`td_canvas_worker.py`（TD 虚拟环境里的生成进程）与 `td_canvas_mosaic.py`
> （总览图）；S2 与 S3 在 `src/dreamulator/media/canvas_hydrology.py`（全局前沿参照实现）、
> `canvas_hydrology_tiled.py`（三段式填平与分块汇流）、`canvas_lakes.py`（洼地层级与湖级联）、
> `canvas_pipeline.py`（磁盘驱动与矢量河段）、`canvas_window.py`（裁窗）与 `lake_masks.py`（湖面足迹）。
> 命令行是 `export canvas` 子命令组（`cli_export_canvas.py`）。湖与河道判定的制图背景见
> [drainage_cartography.md](../../knowledge/cartography/drainage_cartography.md)，TD 模型本身的能力边界见
> [terrain_diffusion.md](../../knowledge/cartography/terrain_diffusion.md)。

## 1. 数据流与命令

```bash
# S1：布局与输入（读世界目录下的 canvas_layout.yaml），然后逐张画布生成分块
dreamulator export canvas plan nacrea                     # 默认写到 <世界>/canvases/<分支>/
dreamulator export canvas generate data/worlds/nacrea/canvases/gcm-t42-712 \
    --td <terrain-diffusion 克隆> --gpus 0-7
dreamulator export canvas status data/worlds/nacrea/canvases/gcm-t42-712 --verify

# S2 与 S3：外存水文，然后裁出区域窗口包（水文没做完时 window 先补跑）
dreamulator export canvas hydrology <canvas_dir>
dreamulator export canvas window <canvas_dir> --lat 15 --lon -100 --span-km 550
dreamulator export render <窗口包> --style all

# 整张画布的超高清总览图（默认每 4 像素取平均，约 360 m 一像素）
dreamulator export canvas mosaic <canvas_dir> --step 2
```

一张画布由 `ncell × ncell` 个粗格组成，粗格边长 23 km，每个粗格含 256 × 256 个像素，像素边长约
89.84 m。画布按 8 × 8 粗格分块，每块 2048 × 2048 像素，存成 int16 米值的 `.npy`，并以 `canvas.json`
记录几何、分块清单、生成参数与气候编码表。海平面固定为 0 m。裁出的窗口包使用与 `export region`
完全相同的 `input/` 与 `refined-out/` 词汇，可以直接交给 `export render` 出图。

## 2. S1：画布生成

### 2.1 投影与坐标

画布是方位等距平面，投影中心取所含陆地的最小覆盖圆心（`minimax_centre`，能盖住全部成员陆地的最小
球冠的中心），球半径取行星真实半径。平面坐标 x 向东、y 向北，单位 km；从中心出发的平面距离等于球面
大圆距离，方位角也保持不变。径向比例尺处处为 1，切向比例尺为 c / sin c（c 为到中心的角距离），两者之比
称为各向异性（`anisotropy`）。经纬度、平面与像素坐标的换算集中在 `CanvasGeometry`，支持数组输入；
所有消费者共用这一份换算，不另写公式。

像素坐标以角点为原点，第 0 行是北边缘，第 0 列是西边缘；像素 (r, c) 的中心为 `x = −half + (c + 0.5) × px`、
`y = half − (r + 0.5) × px`。粗格 (i, j) 覆盖行 `[256i, 256i+256)` 与列 `[256j, 256j+256)`，分块 (ci, cj)
覆盖粗格行 `[8ci, 8ci+8)` 与列 `[8cj, 8cj+8)`。这里采用角点对齐，与上游 `tiff_export` 写出的仿射变换
一致；按格心理解会整体偏移约 11.5 km，是整套坐标里最容易出错的一处。

### 2.2 布局

布局规则在 `td_canvas.py`，作者的选择写在世界目录的 `canvas_layout.yaml`（`CanvasLayoutConfig`）：

1. **陆块**（`land_components`）：CVT 网格上的陆地格按邻接连成陆块。面积不小于一个分块（约 3.39 万 km²）
   的陆块参与分组；更小的陆块只在落入某张画布的生成范围时随之生成。
2. **分组**（`plan_layout`）：陆块按面积从大到小处理。离已有组的陆地不超过两倍缓冲宽度（400 km），
   并且合并后边缘各向异性不超过 1.15，就并入该组，否则自成一组。画布半边长等于最小覆盖圆半径加 200 km
   缓冲，再取整到偶数个分块；陆架延伸（2.3 节）需要更大时随之放大。
3. **切割圆**（`LandCut`）：单个陆块就超过各向异性上限时，作者放一个切割圆，通常在地峡上。圈内陆地格
   暂时从邻接图上去掉，陆块断成几片。普通切割圆的半径不得超过缓冲宽度，圈内陆地不属于任何一片；
   颈部比缓冲带宽时用**归还型**切割圆（`reattach`），切开后把圈内陆地按最近距离还给各片作为成员陆地，
   代价是陆上多一条穿过圆内的归属分界。
4. **固定编号与强制合并**：配置的 `names` 用「一个陆上种子点对应一个编号」给主要画布固定编号，其余画布
   按投影中心自动命名（形如 `land_-31p8_+135p9`，会随地形微调而变）；`joins` 把一个陆块强制并入另一个
   陆块所在的画布，不受合并距离限制。

nacrea 当前是 19 张画布、9259 个分块、约 388 亿像素，int16 存储约 78 GB。世界岛用两个切割圆切成三片：
南北地峡（37.0°N 70.0°W，半径 120 km）切下的东北角并入北极大陆的画布，78°W 10°N 东北侧的宽颈
（12.0°N 74.0°W，半径 250 km，归还型）把其余部分分成 `world-west` 与 `world-southeast`。

### 2.3 生成范围

一个分块入选画布的清单，只要它至少有一个粗格满足下面两条之一（`chunks_near_land`）：

1. 粗格中心离本画布成员陆地不超过 200 km；
2. 粗格中心最近的网格格是本画布的**陆架格**（`shelf_cells`）：海洋格，水深浅于 2500 m，离本画布
   成员陆地不超过 600 km，并且按 2.4 节的规则归本画布所有。

第二条的依据是 TD 会把近海平面的浅陆架抬成陆地：只有缓冲带时，这类陆地在缓冲带外缘被分块边缘截断。
归属条件保证画布不会伸进邻居的地盘。600 km 与 2500 m 是覆盖范围的选择（大陆坡坡脚的典型深度），
不是物理参数。

### 2.4 归属与过渡带

相邻画布的生成范围会重叠。重叠区里同一地点有两份 TD 高程，消费者一律用同一条规则取舍：**一个地点
归属于成员陆地离它最近的那张画布**（`owner_of`，按球面大圆距离）。布局目录附带全部成员陆地点的单位
向量表与所属画布表，求值不依赖 CVT 网格。这条规则让每块陆地都归属于自己的画布，海岸线与流域完整
落在单张画布内，分界线落在海峡或海洋中间；世界岛上的两个切割圆是仅有的陆上分界。

分界线两侧是两次独立生成，消费者用 `blend_overlap` 混合，分块文件保持 TD 原样输出：

1. **默认两频段。** 两张画布各自分成低频骨架（高斯低通，σ = 15 km）与细节；骨架按到两侧成员陆地的
   距离差在 92 km 宽的带内混合，细节在 4 km 宽的带内混合，权重是距离差的平滑阶跃（`blend_weight`，
   3t² − 2t³）。这样分界处没有台阶，带内又保留一侧的完整细节。
2. **海陆不一致处改整体混合。** 两张画布一张高于 0 m、另一张不高于 0 m 的像素，外扩一个粗格后改用
   92 km 宽的整体混合，避免细节层的硬切切出笔直的海岸。

带宽取 92 km 而不更窄，是因为平坦低地上两次生成可以整体相差几十米，窄带会把这段高差压成一条平行于
分界的直线。这组带宽是在世界岛两处陆上分界上目视标定的渲染选择。

### 2.5 条件场与气候通道

每张画布的输入由 `write_canvas_inputs` 写出，全部气候取自布局配置指定的分支（nacrea 为 GCM 固定气候分支 `gcm-t42-712`）。产品分两组：`conditioning/` 是 TD 生成地形的五个条件场，`climate/` 是供水文与渲染消费的气候通道。

#### 条件场

- **五个输入**：引擎高程、订正到海平面的年均气温（递减率随降水在 −9.8 到 −4.0 K/km 之间取值，与区域链相同）、月均气温的标准差、年降水与月降水的变异系数。
- **常规取样**：四个气候条件在 4 倍细网格上取最近 CVT 格，再按 4 × 4 求块平均（`sample_mesh_field`）。
- **抗混叠高程取样**（`antialiased_height`）：4 倍细网格上的数值取网格格高程的 Clough–Tocher 插值并截断到三角形顶点范围；海陆正负取到网格海岸（高程大于 0 m）的有符号距离、经半个网格间距（格心最近邻距离的中位数）高斯低通后的符号，每个网格格心四分之一格距以内保持该格自己的海陆（单格岛屿不会消失），符号与数值冲突的像素取 ±1 m，再求块平均。这样可以减少条件场的格子平台与海岸锯齿，但不保证沿岸低地带宽度或山地形状摆脱网格影响；海陆标签在外扩三倍标准差的网格上求取，网格不完整时插值凸包之外退回最近格。代价是格子平均高程不再严格不变；海平面气温订正仍参照格子平均高程。
- **一致性账本**：条件场逐位相同是两次生成得到同一地形的前提，`canvas.json` 记录每个条件场的 sha256 与高程底场的取样方法（`height_sampling`）。格心保号描述当前实现，不是所有粗格都应作为地理锚点的物理要求；约束范围与沿岸平原的后续验收见 `proposals/canvas-conditioning-structure.md` 4.2 节。

#### 气候通道

年均与月均气温、年降水与月降水、年径流（Turc–Pike，n = 2）、Hamon 年潜在蒸散、月径流（土壤水桶加基流给出月形状，乘以年径流）、冰厚、NPP、柯本与群系编码。公式派生的量先在 CVT 格上算好再取样，不在粗格上重算非线性量；连续场用 Clough–Tocher 插值（`clough_tocher`）并截断到所在三角形的顶点取值范围，月径流与类别编码用 `sample_mesh_field`。海洋粗格上的陆地专属量记为 NaN；编码通道取粗格中心的最近格，在海岸会与高程判定的海陆不一致——消费者判定海陆一律以高程是否大于 0 m 为准。

#### 原生降水覆盖

`--precipitation-field` 读取 `NativePrecipitationField` 的完整原生高斯降水档案（大尺度与对流分量各十二个月，父格覆盖全部陆海面积，读取时核对面积水量预算）。此路径的降水条件与气候降水使用 `canvas_precipitation.canvas_precipitation_coverage` 提供的完整粗格球面足迹：曲边在经度与纬度正弦构成的等面积平面中细分并裁切，面积与交叠权重的相邻细分变化均检验收敛（相对几何容差 2e-6）；源降水在积分单元内保持常量，目标月值为交叠水量除以覆盖面积。`precipitation/` 保存双精度面积和与稀疏交叠权重，`canvas.json` 记录几何、校验和与两分量的十二个月覆盖水量；原生父格的完整预算与单张画布足迹中的水量分别核验，跨画布所有权积分按其分区另行处理。径流与潜在蒸散在此路径由相同的粗格月温度与降水重算，类别编码沿用 CVT 分类取样；水文计算先按导出格式量化月温度与月降水再转双精度运算，下游直接读取月度文件可复现这些派生通道；缺少有效来源的 NPP 连续场保存为 NaN。

GCM 到 CVT 的降水面积输出由 `gcm/cvt_area.py` 提供：接口从有序经纬度重建完整球面 Voronoi 分区，将大圆边界细分到等面积坐标并与原生积分单元裁切；独立球面面积与两次细分的交叠变化共同检查收敛，几何检查通过后权重列归一到各原生积分单元的面积。GCM 字段保存双精度目标积分面积及原始几何面积，格心指纹绑定取样顺序，缓存读取重新检查源列与目标行的面积预算；降水统计使用对应积分面积，温度、风场和气压仍按各自既有取样规则输出；跨画布归属分区与完整 CVT 分区分别验收。

#### 气候版本更新

更新有两种消费范围。`refresh_canvas_climate` 默认只更新附带的气候与水文输入：用于独立暂存批次，保留当前 `conditioning/`、生成参数和高清分块；`canvas.json` 将新气候来源与地形生成来源分别保存并注明水文产物需要重算，调用者可复用同几何的 `CanvasPrecipitationCoverage`，更新入口核对原生分区和目标画布几何。在独立、尚未生成的画布批次中设置 `refresh_conditioning=True` 时，同时更新海平面年均气温、月气温标准差、年降水和月降水变异系数，高程条件继续使用已接受来源；随后用 worker 的 `--prepare-coarse --refresh-climate` 入口准备共享统计场（新模型查询提供均值与气候编码，均值和低分位之差保留接受参照），全部高清块使用新条件和新共享场重新生成，原地形块的校验和用于记录上一版本，两档高清导图消费同一批新块。迎风和背风降水的亚格子差异、局地温度变化及天气驱动方法，继续按提案 4.1 节的候选范围验收。

### 2.5.1 条件场的构造结构与 TD 的细节幅度

布局配置打开 `structure` 后，`write_canvas_inputs` 在高程条件上叠加零均值的构造结构场（`structure_anomaly`，
`td_canvas_structure.py`）：沿等高线方向排列横切谷与山嘴，初始幅度系数为网格亚格子起伏的 0.52 倍（地球 Copernicus 拟合）。
之后的格内均值校正、陆地截断和 23 km 聚合继续改变实际起伏，最终条件场的幅度须按相应尺度统计。
谷间距按 Hovius（1996）的山脉半宽之半，每个网格格内零均值（残差在亚格子起伏的 5% 以内）；叠加后保持底场的海陆
不变，陆地至少 1 m、海洋至多 −1 m。海平面气温订正仍用格子平均高程。配合使用的生成参数是高程通道条件信噪比 0.05（数值越小条件越强），
以及 TD 输出细节系数 `residual_std` 取上游值的 2.0 倍（在地球十个地点上标定与检验，经 `pipeline_kwargs` 传给生成
进程）。设计与验证见 [canvas-conditioning-structure.md](../proposals/canvas-conditioning-structure.md)。

### 2.5.2 连续地形来源

常规布局的高程底场用上节的抗混叠取样；连续来源入口则让每个 23 km 条件格独立积分一份显式来源。`write_canvas_inputs` 接收 `height_source`，经 `terrain_source.sample_canvas` 对各条件格求值；来源实现 `TerrainSource.evaluate` 按经纬度返回高程和海陆指示值。积分采用 Gauss–Legendre 求积并用方位等距投影的球面面积因子修正权重，高程均值与陆地覆盖率分别累计；求积阶数通过逐级加密（8、16、32、64、128）比较确定，相邻阶差的第 95 百分位 ≤ 2 m、最大 ≤ 10 m，源函数覆盖不足时报错、由调用者补齐来源范围（`FootprintTerrainSource` 提供匹配目标形状的布尔支持范围）。采用该入口时 `canvas.json` 的 `height_sampling` 为 `continuous-source-v1`，`height_source` 记录来源、求积阶数和覆盖率文件校验和；`geometry_fields/land_fraction.npy` 保存结构增量叠加前的陆地覆盖率，下游海陆判定继续使用最终高程。当前常规布局沿用抗混叠入口，连续来源由显式传入的局部试验使用。

来源对象分六族。全部对象的支持范围和参数在取样前确定，裁窗使用相同的来源；替换类来源只返回高程差额，对应下游过程的实际响应由相应算子另行验收，调用方在来源记录中保存端点哈希。

| 族 | 入口 / 类 | 职责与关键语义 |
|----|----------|----------------|
| 基础场与投影 | `ProjectedTerrainSource`、`PointTerrainField`、`RasterTerrainField`、`PolylineGeometry` | 查询转换到固定来源投影；点场保存支持点与插值面，栅格场保存固定来源栅格，折线几何提供地物距离。 |
| 古山带 | `paleo_orogens.paleo_orogen_field`（网格端 `paleo_orogen_relief`）、`paleo_source_from_history` | 已有古山带剖面开放为任意球面点查询（网格单位向量系，y 轴向北）；作者路径、碰撞年龄及现有衰减和宽度关系决定贡献，陆壳范围由调用方提供。替换前后山带组合仍取最大值，差值按冻结端点传递；准备时先逐值重放完整参考场，须复现归档包络。 |
| 火山锥 | `VolcanicConeField.surface_m`、`VolcanicCone`、`FrozenVolcanicReplacement`、`FrozenVolcanicDeposit` | 球面短弧距离上查询目录锥体、与背景取最大；锥体几何由峰顶、背景与建成坡度确定。替换族冻结接受的最终表面与重算背景，全部背景响应随差额传递；沉积族将当前剖面作为背景上的连续厚度，单体体积按球面面积积分。`volcano_cell_mean_m` 保留原贡献，替换、后续阶段响应和重叠体积分别记账。 |
| 冻结阶段替换 | `FrozenStageTerrainField` | 冻结一段参考过程的高程变化用于替代输入：参考后高程 +（替代输入 − 参考前高程），各端点先完成重建与限幅再作差；替代输入等于参考输入时准确返回参考后高程。保留参考过程的差额，过程对新输入的实际响应另行检验。 |
| 造山剖面与包络 | `ConservativeArcField`、`orogen_source.CollisionProfileField`、`collision_source_from_contract`、`orogen_source_from_native`、`OrogenEnvelopeProfileField`、`with_continuous_arc_envelope`（诊断用 `with_continuous_endcaps`） | 沿弧保守场按弧长测度映射到共享节点、隐式图扩散平滑（零端点通量）；碰撞剖面接入现有 Airy 截面、地球粗格翼坡标定与力平衡高程上限；组合来源按显式分段/缝合带编号准备，所选剖面先取包络最大值再与其余冻结贡献合成、最后减去旧包络（保留重叠山带的主导关系），准备接口检查来源唯一性与完整参考场重放。连续弧包络为每条有限弧准备方向距离剖面，端部策略与连接度随来源元数据记录，几何定义见 [造山剖面 4.1](../../knowledge/geology/orogen_topography.md#41-有限山带端部的数值延拓)。 |
| 岸坡与陆架 | `coastal_source_from_native`、`CoastalPlainDifferenceSource`（`footprint_support`）、`ShelfEnvelopeDifferenceSource`、`ShelfCoastalDifferenceSource`、`shelf_source_from_native` | 从 `terrain_sources.npz` 的实际陆架输出与冻结低地目标准备连续岸坡差额（入口核对档案类型、格数、地形指纹与阶段连接；宽度、平原高程分界、山岸比例由调用方显式提供）。`footprint_support` 合并新剖面宽度与旧阶段改变顶点的实际岸距，覆盖旧端点重建的全部可能差额；`protection_policy="source-weight"` 将原生资格放入同一三角网按正权重组合。这些入口供连续地物试点显式使用，生产布局的采用范围另行验收。 |

`FrozenOrogenReplacement.continuous_reconstruction` 为连续背景组合准备独立的 `ContinuousOrogenReplacement`：所选来源、其余活动山带、古山带和冻结地壳指示量共用正权球面三角形重建，地壳覆盖作为原指示量的连续数值比例，两份最大值包络在贡献重建后分别求值再作差，原阶段的包络重建残差保持冻结；来源记录保存独立重建哈希、覆盖策略与源三角形最大边长支持范围。

**原生来源档案**（`terrain-source-fields-v1`）保留地形组合至作者高程约束之间的实际表面，连续来源从中读取原山带包络、地壳覆盖及岸坡阶段端点；档案的地形指纹与生成参考态共同核对，实际亚格子精度按原来源登记，导出入口和缓存规则见 [地质管线 7.6](geological-pipeline.md#76-参数表)。关键字段：`cell_area_km2`（与 `xyz` 同源格的实际球面面积，供体积账本与保守传递）；`shelf_continental_crust_mask` / `land_crust_mask`（陆架入口实际 `crust_type == "continental"` 的指示量 / 造山来源 `crust_type != "oceanic"` 资格，两项判据及地表海陆分类分别使用，构造阶段快照标签按实际年代读取）；高程阶段端点 `combined_elevation_m`、`after_initial_sea_level_m`、`orogen_cap_m`、`after_orogen_cap_m`、`after_interior_lowlands_m`、`interior_lowland_clamped_mask`、`after_deposition_fill_m`、`final_forearc_surface_m`、`after_forearc_m`、`after_deep_ocean_clamp_m`、`after_final_sea_level_m`、`after_overlay_archipelago_m` 依次记录初次海面校准、高程上限、内部低地、沉积、前弧、限深、末次海面校准与岛群纹理，`final_elevation_m` 为作者高程约束后的表面。各字段保持原生地质网格精度，单位与参考基准随档案记录；连续来源按同一阶段顺序消费这些约束。

### 2.5.3 来源细化工作流

`export canvas refine` 通过 `canvas_orogen_refinement.refine_canvas_layout` 完成来源选择、条件积分和共享统计场的整批准备；`canvas_refinement.prepare_refined_canvas` 将已积分的来源差额加到参考 S3 高程条件，写入独立输入批次并保留参考结构、生成参数及气候通道（元数据保存来源、参考端点哈希与求积阶数）。`CanvasRefinementConfig` 按画布声明唯一的活动分段和古缝合带编号；`load_native_inputs` 按分支解析作者配置、来源档案和造山契约，核对物理半径并记录输入哈希。整批在临时目录准备并核对条件和统计回执，完成后安装新目录；布局与归属表保持，未选输入按原值复制，原高清块保留在原批次。每张所选画布的 `preparation/statistics.json` 保存准备时间和文件哈希，根 `layout.json.height_refinement` 保存选择、来源指纹及积分收敛记录；`integrate_source_correction`（原 `integrate_orogen_correction` 是其别名，岸坡同规则）执行上述求积与收敛检查。

**统计参照**：`coarse_source` 按 `fixed-coarse-statistics-v1` 保存新条件与已接受统计参照的相对路径、哈希和形状——统计采用参考的均值减第五百分位之差，四个气候编码通道逐值保留；`td_canvas_worker.translate_coarse_mean` 按编码均值差同步平移低分位，均值响应为零的格点逐字节保留参考通道（低尾差按现有 TD 编码保留符号，float32 差额重算误差容限 8×10⁻⁶ 个编码单位）；`td_canvas_worker.prepare_coarse_statistics` 在同一固定模型、种子和条件 SNR 下生成候选均值，读取参考批次的冻结共享场或从所声明的原 S3 条件生成参照（准备时核对两批的几何、生成配置、结构声明与五个条件文件的哈希，四个气候条件输入逐字节相同；每次安装条件后重建 tile 缓存，查询完整含边界的六通道编码场）。这项固定气候政策用于地质来源实验；明确刷新气候的批次按 2.5 节更新四个气候输入及共享场的气候编码。所选来源可通过 `statistics_reference` 指定已接受的统计参照画布目录（其画布编号、几何、模型、结构声明和四个气候条件须与本次 S3 参考一致；条件高程与参照逐字节相同时直接复用其六通道场；参照路径、画布哈希与共享场哈希保存在来源及整批回执，查询前缀传入高清阶段；省略时用原始 S3 的统计政策）。

**查询复现**：`generation_queries` 保留历史序列中的全部查询，目标块在其最后一次历史查询时写出；预热和生成均出现的目标用最后记录的结果，已完成目标继续参与历史上下文准备，序列之外的新目标按声明顺序生成——`coarse_source.query_policy=last-prefix-result-v1` 保存这一语义并参与已有块复用检查。统计准备和高清生成均按 `generation.model_revision` 加载对应的本地模型快照（实际版本与模型种子、SNR、解码参数及查询前缀共同记录）。CLI 的已有块检查同时比较 `coarse_source`：共享场、统计参照或查询前缀改变时已有高清块须按新的生成输入更新，相同高程条件的校验和单独不足以证明共享场一致。

```yaml
branch: gcm-t42-712
planet: satellite_nacrea
orogens:
  aurora:
    collision_segment_ids: [seg_064]
    statistics_reference: accepted-statistics/aurora
  land_-24p4_+132p6:
    paleo_suture_ids: [suture_p4]
    statistics_reference: accepted-statistics/southern
  world-southeast:
    collision_segment_ids: [seg_068]
    collision_parameter_policy: known_contact_vertices
    statistics_reference: accepted-statistics/world-southeast
```

```bash
dreamulator export canvas refine nacrea ORIGINAL_S3 NEW_LAYOUT \
  --config selections.yaml --td /path/to/terrain-diffusion --gpu 0
```

默认来源 map 按地质层继承分支解析，独立重算的来源可由 `--source-map` 指定。所选碰撞来源可声明 `collision_parameter_policy`：默认 `conservative_arc` 用完整有效接触的沿弧保守场；`known_contact_vertices` 沿用已接受的正贡献接触平滑、共享顶点均值和反距离平方延拓（重建使用完整界线计算横向距离与侧别，历史缺值仅提供界线几何），该策略在所选画布配置中显式记录，来源元数据保存缺史格、参数顶点与几何的独立哈希；两种剖面共用现行 Airy 截面、翼坡与高程上限，分别按原接受范围验收。板块对的明确极性与年代来源由地质契约保存，海沟、岛弧和陆架作用域使用地壳准备完成后的共同快照；接口时点、默认近似和缓存恢复见 [地质管线 6.1](geological-pipeline.md#61-历史契约汇聚边界段orogen_contractpy)。沿轴保守传递、西岸连续岸坡与暮光实际阶段响应已获局部效果接受（固定 S3 统计幅度及方向），常规非对称地质合成已将已有挠曲作用域传入陆架阶段，连续岸坡与沿轴来源的常规画布接入分别推进。

### 2.5.4 球面几何与海岸曲线

`SphericalPointTerrainField` 冻结全球粗格点值，用球面三角形及正重心权重连续重建；`basis` 返回同一次查询的顶点与正权重（供带无限非激活边界的局部约束响应使用），密集曲线控制可显式用 `stable_weights=True`（在三角形局部边坐标中求射线与面片的交点并沿邻接面定位细长三角形，该数值路径有独立来源指纹，已冻结来源沿用默认路径）。`SphericalCoastGeometry` 从同一场的海平面交线取岸线并按有限大圆弧求精确岸距，显式 `project` 查询另返回最近线段、弧内位置、距离和侧别；`contour_paths` 保存有序路径与闭合环，分叉处形成独立路径。地质单位球 y 轴朝北，曲线的地理左侧法向为负叉积，通用投影的叉积侧别单独保留。`terrain_curve.SphericalTerrainCurve` 分别记录几何、高程及左右端坡度的来源、信息尺度、垂直基准、参考年代与缺值（几何取样间距和来源信息精度分别声明）；`SphericalCurveBoundary` 对明确连接的曲线集合查询边界（连接分区由来源调用方提供）；`save_terrain_curves` / `load_terrain_curves` 保存 NPZ 数组与 JSON 证据侧记，读取时核对参考标识与包含连接和来源的哈希。岸坡及陆架来源可显式调用 `terrain_curves` 导出其冻结参考场的海岸曲线（坡度按缺值记录），该导出入口按需运行、曲线档案供来源诊断使用。

### 2.6 生成、续算与校验

TD 在一张画布上是无缝的：上游的 InfiniteDiffusion 把画布当作只由种子和坐标索引的数组，按需计算互相重叠的去噪窗口，
所以逐块取出的分块之间没有接缝，生成顺序与进程划分也不影响结果；原理与实测见
[terrain_diffusion.md](../../knowledge/cartography/terrain_diffusion.md) 的「大画布上的无缝分块生成」。

`export canvas generate` 为每张 GPU 启动一个 `td_canvas_worker.py` 进程，用 TD 虚拟环境的解释器运行，
工作目录是 TD 克隆；这个进程不导入本库。worker k 取分块清单（行优先）的第 k 段连续切片，使相邻分块
共享缓存的隐变量（`worker_slice`）。每个分块先写临时文件再改名，然后把 sha256 加锁追加到
`chunks.sha256`；重启时文件存在且校验和匹配的分块直接跳过。`export canvas plan` 先在独立临时目录生成
所选画布的布局与输入，再检查已有分块的几何、条件场、生成参数、结构及 `coarse_source` 共享场描述。
输入生成或复用检查失败时，原布局、输入、高清块和校验清单保持原值。全部检查通过后，
`td_canvas_build.install_planned_inputs` 按文件替换输入，并保留已有分块与其他资产。
单个输入文件的符号链接由新文件替换，其原指向文件保持原值；输出目录内部的目录链接在安装前检查。
`--force` 允许改写会使旧分块失效的输入，后续生成前应移开旧 `chunks` 与 `chunks.sha256`。
安装中的磁盘错误可能留下已写入的部分文件，恢复时核对输入与元数据再续算。

生成参数记录在 `layout.json` 与每张 `canvas.json`：模型 `xandergos/terrain-diffusion-90m` 的快照号、
TD 代码提交号、种子 42、条件信噪比（0.2, 0.2, 1.0, 0.2, 1.0）、fp32、条件场 64 个粗格的边缘值延拓。
任何一项变化都会生成一张不同的世界。同一画布在不同进程上生成，只有约 0.3–3% 的像素因 GPU 浮点运算
顺序不同而相差 1 m，其余逐位一致；所以 `chunks.sha256` 只校验传输与存储是否完整，不能比较两台机器各自
的结果。

### 2.7 目录

```
<root>/                               # 默认 data/worlds/<世界>/canvases/<分支>/
├── layout.json                       # 画布列表、编号、布局参数、生成参数、数据来源
├── owner_points.npy                  # (n, 3) float64，全部成员陆地格中心的单位向量
├── owner_canvas.npy                  # (n,) int16，各点所属画布在 layout.json 列表中的序号
└── <canvas_id>/
    ├── canvas.json                   # 几何、分块清单、成员陆块、编码表、校验和、生成参数
    ├── conditioning/*.npy            # 五个条件场
    ├── climate/*.npy                 # 水文与渲染通道
    ├── chunks/r<ci:03d>_c<cj:03d>.npy  # int16 分块，例如 r012_c034.npy
    └── chunks.sha256                 # 每行「sha256  文件名」，只列出已完成的分块
```

### 2.8 总览图

`export canvas mosaic` 把一张画布的原始分块拼成一张图（`render_mosaic`），裁到实际生成的范围。画法、陆地颜色与
海洋颜色是三个独立的选项：

- `--style` 选画法，缺省 `relief`。`carto` 与 `export render` 的地形图相同，是只乘在陆地上的双尺度晕渲加饱和度提升；`relief`
  是印刷用的立体晕渲，把高程放大（缺省倍数为像素边长除以 90 m，让平均后的像素与原生像素明暗相当）后用四个方向
  的光照合成，海岸外加一圈柔和的阴影。
- `--palette` 选陆地颜色：`adaptive` 是 `export render` 的自适应地形色表（锚定在固定的 ±9000 m，`carto` 的缺省），
  其余取自 `map/hypsometric_palettes.json`：`pastel`（本项目的浅色分层，`relief` 的缺省）、`gmt-etopo1`、
  `gmt-globe`、`gmt-relief`（GMT 的原始色表）、`wikipedia`（维基百科地形图规范）与 `cross-blended`。每套色表
  记录来源与许可，断点是绝对高程，各大陆的图可以直接并排比较。
- `--intertidal` 选潮间带：高程落在给定区间（缺省 −2 到 +2 m）的像素画成潮间带色，取 IHO S-52 电子海图标准的
  潮间带色 `DEPIT`（日间表，RGB 131、178、149），沿用海图把干出滩单独着色的惯例；这只是成图分类，海陆判定仍以
  高于 0 m 为陆。`off` 关闭。
- `--sea` 选海洋：`carto`（自适应色表的水深蓝，缺省）、`palette`（色表自带的水深色）或 `grey`（统一的灰色，
  清单外也填灰色）。

`cross-blended` 是 Patterson 与 Jenny（2011）的交叉混合分层设色：低地颜色随自然环境变化。逐像素的混合权重取自
画布的粗格气候通道（`cross_blend_weights`）：干旱指数（年降水除以 Hamon 潜在蒸散）从 0.65 降到 0.2 时过渡到
干旱色，年均温从 8 °C 升到 18 °C 时由湿冷色过渡到湿热色，最暖月低于 10 °C 或有冰处用极地色。这些界线取自
干湿分级与柯本 E 类的惯例，是渲染选择。

图按一行分块为一条带、带上下留出晕渲所需的重叠区，并行
着色后拼接，内存随单条带而非整张画布增长。结构晕渲的平滑尺度固定在约 34.5 km 的地面距离，所以大图的
局部与小总览读起来一致；细晕渲是输出像素尺度上的真实坡度。清单外的分块（邻居画布的地盘、远海）留成
纸色。输出 `.jpg`（每边不超过 65535 像素，JPEG 的格式上限）、`.png` 或分块压缩的 BigTIFF（`.tif`），
旁边附一份 `<图>.json` 记录画布、步长、像素尺寸与几何；默认路径在 `exports/mosaic/<画布根目录名>/`，不同配方的画布根目录各占一个子目录。

最终图像产品同时提供 `--step 2` 和 `--step 4` 两档图，实际格距为 179.6875 m 和 359.375 m。
每对图从同一批原生块取样，范围、配色和高程放大倍数保持一致。
批次清单记录画布元数据、原图哈希、尺寸及来源版本，预览与原图分别保存。

## 3. S2：外存水文

### 3.1 边界

画布内每个像素按归属分三类：本画布所有的像素参与计算；其他画布所有的像素，以及分块清单
之外或缺失的像素，一律按开放边界处理（水到达即离开本画布流域，不再抬升）。海岸线与流域
按归属规则完整落在单张画布内，世界岛的两处陆上分界是例外，由联合前沿处理。

### 3.2 填平

Priority-Flood 的算法本体、物理判据与文献讲解在知识库
[hydrology.md](../../knowledge/geology/hydrology.md)；洼地 fill/breach 两种语义的制图
后果与湖判定的渲染门槛见
[drainage_cartography.md](../../knowledge/cartography/drainage_cartography.md)。

填平按 Barnes 2016 的三段式分块方案实现（`fill_canvas_tiled`）：

1. 每块独立跑带分水岭标签的 Priority-Flood，记录局部填平面、分水岭标签与溢出图；
2. 协调端合并标签、拼接溢出图，在分水岭溢出图上再跑一次 Priority-Flood；
3. 重新读取每块，把像元抬升到所属分水岭的全局水位。

填平不 breach。画布外存版本由 `run_canvas_fill` 驱动：阶段一逐块写 `fill/`、`labels/`、
`summary/`，阶段二只读摘要构建全局图，阶段三逐块写 `final/`；内存占用与分块大小同阶，
与画布总像素数无关。时间上三阶段共 O(N log N)（N 为画布像素数）：阶段一与阶段二的堆
操作每格常数次，阶段三是单遍改写。`canvas_hydrology.py` 另有一套全局前沿 Dijkstra 实现
（`flood_canvas`），作为正确性参照（oracle）：两者在合成 DEM 上逐位一致，包括带海与
多分块的情形。

阶段一的逐块洪水自 2026-10-30 起走 numba 内核（`_hydrology_kernels` 模块的
`_local_flood_kernel`）：平坦数组二叉堆按（水位，格号）字典序弹出，复刻纯 Python 参照
`_local_flood_reference` 的全部细节语义——种子扫描顺序、`max(地形, 水位 + ε)` 在
float64 中计算并存回地形自身 dtype（堆携带**存回后**的值，float32 下才有位级一致）、
溢流图取两流域相遇的最小水位。等价性由测试逐位断言（float32/float64、带海、ε > 0），
因此内核与参照在任何输入上可互换。实测单块（2048² float32）约 3.6 s，比纯 Python
快约两个数量级；纯 Python 版在海洋主导的画布上（种子为全部海洋格）会以元组堆耗尽
内存，这正是内核化的直接动因。

### 3.3 ε 坡道

填平面上的平地没有确定流向，因此路由前对每个等高连通区做一次多源 Dijkstra
（`_grade_flats`）：种子是出口格、紧邻更低值的格以及海平面以下的全部格，区内每步加
ε，得到朝出口单调下降的坡道。这是 Priority-Flood + ε（Barnes、Lehman 与 Mulla
2014）的形态，与 oracle 在 ε = 1e-3 下逐位一致。坡道只用于计算流向，不写回填平面。
该函数同样自 2026-10-30 起走 numba 内核（`_grade_flats_kernel`）：种子阶段是全图扫描，
海面以下全域做种子的设计使海洋主导画布的种子数与像素同阶，纯 Python 元组堆因此不可
用；内核用容量倍增的平坦数组堆与惰性删除（弹出时 `lv != level[c]` 即过期）复刻参照
`_grade_flats_reference` 的 Dijkstra 语义，等价性同样逐位断言。坡道是逐等高连通区的多源
Dijkstra，时间 O(M log M)、空间 O(M)，M 为平区格数，通常远小于画布像素数 N。

### 3.4 汇流

分块汇流按 Barnes 2017 的三段式方案实现（`accumulate_canvas_tiled`）：块内串行累积，
把跨块流量登记为转移事件，协调端按填平降序沿接收链求解事件图，最后把偏移量折回各块。
该实现只支持 D8 这类不分叉流向，与区域链语义一致。时间主导项是逐块的稳定排序与每格
常数次的累积和折回，与全局版同阶；跨块事件数以分块边界格数为上界，远小于像素数。

当前 `run_canvas_rivers` 的河段提取仍会把整张画布的填平面装入内存后计算 D8 与累积
（`canvas_flow_fields`），因此适用于试点画布尺寸；把河段提取也接到分块波次上是后续工作。
拼装路径的 D8 接收格计算自 2026-10-30 起分带执行：最陡坡与接收格候选都是带内局部量，
逐行带（默认 2048 行）配合一行上下文切片复用 `_shift` 取邻域值，使逐邻居临时数组与
带同阶而非与画布同阶——此前全图 `mgrid` 加 `np.where` 链在 20480×18432 画布上峰值
超过 20 GiB（int64 临时数组单发 2.81 GiB）而内存耗尽；分带后接收格与旧全图公式在
含海、平地与缺失块缺角的合成地形上逐位一致。分带不改变拼装路径的整体内存地板：填平
面、地形、接收格、排序、权重与累积各占一份全图数组（永耀岛尺度约 16.5 GiB），仍是
该路径的尺寸上限。

### 3.5 湖

湖的检测以填平面与原始地形之差为判据：差值大于 5 m 的封闭盆地成为**湖种子**
（`lake_mask`），再按连通面积、MMU 与最小宽度三个门槛筛选。种子成立后，湖体扩展到与
种子连通、填深大于 0.5 m 的整个填平足迹（`lake_footprint`）：填平面就是水面，浅水
边缘属于湖体。只按深核绘制与断链会让河道沿深核边缘绕行，图上读作河流贴着湖边走。

湖的收支用洼地层级与 Fill–Spill–Merge 级联（`canvas_lakes.py`）：升序扫描与并查集建立
父子关系，叶是坑、父是溢出，容量为溢出高程乘格数减去地形和；来水先蓄满叶，再经鞍部
流入兄弟，双方都满则合并到母洼，余量继续上行，水位由
`Σ max(0, 水位 − 地形) × 面积 = 水量` 求解。升序扫描带一次排序（O(N log N)），并查集
近线性。该模块目前作为算法实现与测试基准，湖表
（`lakes.json`、`lakes.sparse`）尚未接入磁盘管线；S3 在稀疏湖文件缺失时从填平面推导
湖掩膜。地表气候定版交付（2026-10-29）的 `asset_status.json` 把湖表三件
（`lakes.json`、`terminal_lakes.json`、`lakes.sparse/`）登记为「S2 生产待做」并明确
其 schema 与生产集成都归 S2 消费管线负责——缺失湖表不构成零湖声明，只表示该画布的
湖产品尚未生产。

### 3.6 矢量河段与情相

河道提取复用区域链的 `river_segments`：D8 最陡下降、Chaikin 平滑、湖岸停步与溢出口
续走、短链保留。河段以画布 SW 原点 km 输出，与区域链 `refined-out` 的坐标约定一致。
常流与非常流按 12 个月的累积流量判定：任一月低于 1 L/s 的活动门槛即记为非常流，连续
同类格合成一个情相段。

河道起始门槛采用“物理起始流量不变”原则：区域链的基数是 3000 个 2048/550 km 包格，
细化时按像素数平方换算到 4096²（12000 格），对应约 2.1 m³/s 的平均流量起点。画布
90 m 像素的同一起点约 27000 格，因此 `--threshold-cells` 默认 27000；需要更密的小溪网
时下调。

### 3.7 最终产品目录约定

最终产品使用第 2.7 节的画布根目录。共享几何文件位于根目录，各画布的资产状态与水文产品位于其子目录。

```
<root>/
├── layout.json                       # 画布布局与来源
├── owner_points.npy                  # 成员陆地点的球面坐标
├── owner_canvas.npy                  # 成员陆地点所属画布
├── seam_pairs.json                   # 跨所有权边界的共同取样点
└── <canvas_id>/
    ├── asset_status.json             # 地形、气候与水文产品的实际状态
    └── hydro/
        ├── rivers.line.npy           # 河段几何
        ├── rivers.flow.npy           # 河段流量
        ├── rivers.regime.npy         # 河段情相编码
        ├── rivers.png                # 河网栅格图
        ├── rivers.meta.json          # 河网元数据
        ├── lakes.json                # 湖表预留路径
        ├── terminal_lakes.json       # 终端湖表预留路径
        └── lakes.sparse/             # 稀疏湖面预留目录
```

`asset_status.json` 记录 S1 分块、气候文件、地质契约及 S2 湖表的实际完成状态。
地形、气候与地质来源分别记录版本，湖表按所采用的地形和月气候生成。
当前目录为湖表预留路径，S2 接入湖级联后写入这些产品并更新状态。

`seam_pairs.json` 提供实际 CVT 陆地邻接边上的跨所有权配对点。
每项记录两侧格 ID、同一地理点及两张画布的像素坐标，只包含双方已有地形块覆盖的点。
S4 结合布局与所有权文件对同一地点取样，检查接缝高程、河湖与流量的一致性。

水文中间结果保存于各画布的 `hydro-work/`，供断点续算使用，完成后可清理。

```
<canvas>/hydro-work/
├── fill/r<ci>_c<cj>.i16.npy           # 局部填平面
├── labels/r<ci>_c<cj>.i32.npy         # 局部分水岭标签
├── summary/r<ci>_c<cj>.npz           # 溢出图、四边标签与高程
├── final/r<ci>_c<cj>.i16.npy          # 全局填平面
└── chunks.sha256                     # 已完成分块的校验和
```

## 4. S3：区域裁窗

裁窗把方位等距平面上的一个正方形窗口逐像素换算成经纬度，再换算到画布像素坐标：

1. 高程对画布分块做双线性采样，块只按窗口包围盒读取，内存随窗口而非画布增长；
2. 海掩膜由高程小于等于 0 判定，并写出按高程跨度归一的 `sea-depth.png`，供制图腿
   做海深分层；
3. 湖掩膜优先读 `hydro/lakes.sparse/`；缺失时从画布填平面与原始地形之差推导完整
   填平足迹，补内部量化空洞，再套用与河链相同的 MMU 与宽度门槛；
4. 河流矢量先由画布 SW 原点坐标减去画布半宽，换算到经纬度，再换算到窗口平面，写成
   窗口 SW 原点 km；同一批段栅格化成一像素宽的 `rivers.png`；
5. 气候通道从粗格采样到窗口：标量双线性，类别最近邻；图例从 `canvas.json` 继承；
6. 窗口 meta 记录包版本、投影、精确窗口边长与像素边长、高程范围（含画布全域锚定范围）、
   海平面、气候图例与来源画布。

输出目录是 `input/`（区域数据包通道与 meta）与 `refined-out/`（高程、水体掩膜、河段矢量
与 meta），与 `export region` 加 `export build` 的产物同构，所以 colorize、carto、relief、
biome、Blender 各腿无需改动。

**渲染侧的河湖衔接**：河链会刻意把最后一段画进湖内一格，作为河与湖的可见连接。渲染载入
时只删除两端都在水中的河段（`_river_lake_keep`），岸线穿越段保留；按岸边缓冲距离裁剪会
把这段桥接删掉，重新打开入湖断口。

## 5. 验证

- S1 的布局与输入：库实现与生成曙光试点画布的脚本输出逐位一致（布局、归属表、五个条件场与十一个气候
  通道）；单元测试覆盖布局配置、玩具网格上的输入、续算记账与总览图裁剪。
- S1 的生成：曙光试点画布 1036 块齐全、校验和匹配；分块接缝处相邻像素差与块内相同（比值 1.02）；
  已知地标探针的最佳偏移为 (0, 0)；跨进程重生成的分块只有 0.3–3% 的像素差 1 m，最大差 1 m（新命令的 worker 重算 8 块实测）。
- 填平与汇流的分块实现与全局前沿 oracle 在合成地形上逐位一致：单块、2×2、2×3、3×2，
  含海与地峡拼合；ε = 1e-3 下的坡道同样逐位一致。
- 洼地层级与 Fill–Spill–Merge 级联有解析水位、两级坑、独立/溢出/合并三态与溢流截平的
  单元测试。
- 真实地形验收：从 nacrea 的 TD 细化地形采样出 368 km 画布（90 m 像素），填平 154 秒、
  11290 个分水岭；阈值 27000 下 38199 条河段，河网呈树枝状汇入海岸，湖面与诊断图一致。
- 裁窗验收：合成画布裁出 550 km 窗口，核对中心高程、海占比、湖与河掩膜、矢量 SW 坐标、
  气候图例；真实画布裁 150 km 后直接出测绘风图，海深、湖岸与河湖衔接正常。
- 可复现：同一画布重跑输出逐字节相同；`.npy` 分块与工作区校验和保证断点续算。

## 6. 已知限制与后续

- 河段提取与湖表仍未接上分块波次：填平是外存的，河段提取当前按整张画布装内存；湖表
  （终局湖、干盐滩、萎缩湖与稀疏湖像素）尚待接入。
- 世界岛两处陆上分界的生产版联合前沿尚未接入磁盘管线；oracle 已有接缝配对实现并通过逐位测试。
- 递归分块并行与 numba 热路径是性能后续项；当前试点画布尺寸可用，全球最大画布的运行
  时间与峰值内存仍需实测。
- S4（重叠窗口一致性验收）未实现；S5 目前只有单张画布的总览图（2.8 节），跨画布拼合的大陆与全球
  概览尚未实现。
- 当前 nacrea 海峡与陆桥接受 TD 地形，不做生成后钉扎；开合大势与叙事口径见设计笔记 0016。
  自动门槛审核仍未产品化，新配方需要重新目视核对关键位置，不能把旧配方的审核结果视为永久通过。

## 7. 文献与实现参照

- Barnes, Lehman & Mulla (2014)：Priority-Flood 填洼与分水岭标号，*Computers &
  Geosciences* 62:117–127；平面排水方向分配法见同卷 128–135。
- Barnes (2016)：三段式分块填平，*Computers & Geosciences* 96:56–68。
- Barnes (2017)：不分叉流向的分块汇流，*Environmental Modelling & Software* 92:202–212。
- Barnes, Callaghan & Wickert (2021)：Fill–Spill–Merge 洼地层级，*Earth Surface
  Dynamics* 9:105–121。
- RichDEM 是上述算法的开源参照实现（MIT）；WhiteboxTools 与 TauDEM 提供同类填洼与汇流
  方案，分块策略与画布不同，未作主参照。
