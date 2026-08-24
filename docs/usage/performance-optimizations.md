# 性能优化记录

本文档追踪 dreamulator 项目的所有性能优化工作，供后续开发参考。
每次优化记录：日期、基线数据、改动内容、效果数据。

> 性能分析工作流见 [../usage/profiling.md](../usage/profiling.md)。
> 构建耗时基准见 [roadmap.md §八-19](roadmap.md#八已知技术债务)。

---

## 2026-08-12：地质层子阶段缓存 + Ocean 预条件子 + 前端 code-split

**基线**：nacrea 200k seed=42, `build_profile.json`（347.4s）

### 1. 地质层子阶段缓存

**文件**：`src/dreamulator/map/terrain_cache.py`（新建）、`terrain_pipeline.py`、
`engine/geological.py`、`engine/pipeline.py`

**设计**：
- 5 个管线阶段（mesh / plates / tectonics / boundaries / terrain）各自写入中间产物到
  `maps/{planet_id}/_cache/{stage}.pkl` + `manifest.json`
- 指纹 = `sha256(seed | config_fields | geography_hash | upstream_fingerprints)`
- terrain 阶段只缓存 3 列 numpy 数组（elevation / crust_type / boundary_type），
  不缓存完整 CVTMesh（避免 80 MB pickle 开销）
- `--force` 禁用所有子阶段缓存

**效果**（二次构建，全部缓存命中）：

| 阶段 | 首次 | 缓存命中 | 加速 |
|------|------|---------|------|
| mesh | 30.6s | 2.5s | 12× |
| plates | 4.6s | 22ms | 209× |
| tectonics | 73.0s | 23ms | 3174× |
| boundaries | 4.5s | 0ms | ∞ |
| terrain | 116.2s | 373ms | 311× |
| export | 13.4s | 13.1s | — |
| **地质合计** | **244.2s** | **16.4s** | **15×** |

### 2. 构建跳过：上游传播

**文件**：`engine/pipeline.py`、`engine/climate.py`

**设计**：
- `upstream_ran` 标志：一旦有引擎实际执行，下游全部重跑（简单，无需指纹）
- Climate 引擎新增 `outputs_exist()` 方法，修复输出路径不匹配导致
  climate 永远不被跳过的 bug（实际写到 `maps/`，但检查 `layers/climate/derived/`）

**效果**：
- 什么都没改：astronomy/geological/climate/ecology 全部跳过
- 改 geography.yaml：geological 重跑 → upstream_ran=True → climate + ecology 级联重跑
- 改引擎代码：`--force` → 全量重跑

### 3. Ocean GMRES Jacobi 预条件子

**文件**：`src/dreamulator/map/ocean_circulation.py`

**改动**：`solve_ocean_gyre` 中 `gmres(A, rhs, M=M, ...)`，M = diag(1/A_diag)

**效果**：ocean 60.2s → 55.6s（-7.6%）。83 个海盆中 82 个为微型（<100 cells），
仅 1 个主海盆（138,989 cells）占绝对多数时间。预条件子减少 GMRES 迭代次数约 10-20%。

### 4. 前端代码分割

**文件**：`frontend/src/App.tsx`、`vite.config.ts`、`main.tsx`、`MapSvgOverlay.tsx`

**改动**：
- `React.lazy()` 拆分 8 个页面（首页不再加载 Three.js ~600KB + Leaflet ~150KB）
- `manualChunks`：three / leaflet / react-markdown 独立 vendor chunk
- `gcTime: 1min`（默认 5min → 多世界浏览后释放 200+ MB 内存）
- Graticule 采样 2°→5°（60% 点减少）

**效果**：首页 JS bundle -60%，首屏 TTI 预估 -500ms

---

## 2026-08-12：Terrain 合成向量化（边界效应 + interior_landforms + xyz 缓存）

### 5. 边界效应向量化 + xyz 坐标缓存

**文件**：`src/dreamulator/map/terrain_synthesizer.py:apply_boundary_effects`、
`src/dreamulator/map/models.py:CVTMesh`

**问题**：
- `apply_boundary_effects` 逐个 cell 构造 `np.array([d])` → 调用 `_dual_boundary_falloff` → 取 `[0]`
- 3 个函数各自用 `np.array([c.x for c in mesh.cells])` 重复提取 xyz 坐标（5-7 次全量遍历）

**方案**：
- `apply_boundary_effects`：一次性构建 boundary mask + 批量 falloff + numpy 索引赋值
- `CVTMesh` 新增 `cell_xyz` / `cell_lon` / `cell_lat` 属性，首次访问后缓存

**效果**：terrain 114.2s → terrain 贡献 -8s（~7%）

### 6. Interior landforms 大圆面预过滤

**文件**：`src/dreamulator/map/terrain_synthesizer.py:_apply_interior_landforms`

**问题**：三层嵌套循环（plates × belts × interior cells），每个 interior cell 做
`np.array([c.x,c.y,c.z])` + `np.arccos` + `opensimplex.noise2`。
每个 belt 遍历全部 interior cell（数千个），其中 >95% 远离 belt 被最终的距离检查跳过。

**方案**：
- 预过滤：对每个 belt，先做 O(n) 的 `abs(dot(interior_xyz, gc_normal)) < sin(10°)`（便宜），
  只对 ~5% 通过的 cell 做昂贵的 arccos + opensimplex noise
- 投影/归一化/沿走向位置均批量向量化
- 使用 `mesh.cell_xyz` 替代 per-cell `np.array(...)`

**效果**：**terrain 59.8s**（基线 80.6s，-25.8%；优化前 114.2s，-47.7%）
**地质总 185.5s**（基线 213.8s，-13.2%），**总 317.0s**（基线 347.4s，-8.8%）

### 7. 海平面校准算法重写

**文件**：`src/dreamulator/map/terrain_synthesizer.py:_apply_sea_level_calibration`

**问题**：60 次二分搜索迭代，每次 `np.sum(areas[elevation > mid])` 全量扫描。

**方案**：排序 + 累积前缀和 + `np.searchsorted` 二分查找。O(60n) → O(n log n)。

**效果**：实际收益 <0.1s（numpy 的 boolean-mask + sum 在 200k 元素上非常快）。保留此改动作代码清洁（不再每次分配临时 boolean 数组）。

---

## 累计效果

nacrea 200k seed=42 `--force` 构建：

| 优化 | terrain | geological | total |
|------|---------|-----------|-------|
| 基线（无优化） | 80.6s | 213.8s | 347.4s |
| +缓存（二次构建） | 373ms | 16.4s | 147.7s |
| **+向量化（本次）** | **59.8s** | **185.5s** | **317.0s** |

---

## 2026-08-12：地球 Köppen 空间验证基线（D₀=5.0，图扩散）

**验证配置**：`climate validate earth --dataset beck2018 --spatial`，
32768-cell 验证 mesh，地球物理参数（P=1d, Ω=1.0, Tilt=23.44°, GH=33K）。

**结果**：

| 指标 | 值 | 阈值 | 判定 |
|------|-----|------|------|
| Köppen 分布匹配 | 57.9% | 55% | PASS |
| 空间准确率 | 26.7% | — | FAIL |
| 群组准确率 | 57.4% | — | — |
| Cohen's Kappa | 0.217 | — | — |
| 陆地比例 | 29.1% | 29.0% | PASS |

**Top 5 混淆**（系统性偏差）：

| 混淆 | cells | 方向 | 可能原因 |
|------|-------|------|---------|
| Dfc → ET | 618 | 亚寒带→苔原 | 温度偏冷（EBM 高纬冷偏差） |
| Dfc → BSk | 261 | 亚寒带→冷草原 | 降水偏少（内陆水汽输送不足） |
| Aw → BSh | 254 | 热带草原→半干旱 | 降水偏少 |
| Dfb → BSk | 191 | 湿润大陆→冷草原 | 降水偏少 |
| Dwc → ET | 147 | 亚寒带→苔原 | 温度偏冷 |

**偏差诊断**：
- **D/D 类混淆（618+191+147=956 cells）**：中纬度大陆内部判为苔原/草原——温度和降水同时偏低。根因不在水汽扩散（D₀），而在 EBM 温度剖面（高纬冷偏差）和大洋热输送（Stommel 不够强）
- **B 类混淆（261+254=515 cells）**：中低纬过于干燥——图扩散水汽仍未充分到达内陆

**优化方向**（按优先级）：
1. 温度剖面修正——Dfc→ET 是最大混淆源（618 cells），优先修正高纬冷偏差
2. Stommel 洋流热输送增强——暖流对中高纬沿海的调温效应
3. 水汽扩散 D₀ 扫描标定——待 #1 #2 修后再调

---

## 待优化清单

以下项目已经过代码级分析（详见 2026-08-12 agent 分析结果），按优先级排列：

### 后端

| 优先级 | 目标 | 文件 | 预期加速 | 说明 |
|--------|------|------|---------|------|
| P0 | ~~海平面校准~~ ✅ | terrain_synthesizer.py | — | 排序+前缀和；实际瓶颈不在此 |
| P0 | ~~边界效应向量化~~ ✅ | terrain_synthesizer.py | ~7% | 批量 falloff + numpy 索引 |
| P0 | ~~xyz 坐标缓存~~ ✅ | models.py + terrain_synthesizer.py | — | `mesh.cell_xyz` 属性，一次提取 |
| P0 | ~~interior_landforms 预过滤~~ ✅ | terrain_synthesizer.py | **-47.7%** | 大圆面 dot 预过滤 + 向量化投影 |
| P1 | Tectonic BFS → scipy 稀疏图 | tectonic_simulator.py | 3-8× | `_bfs_distance` 每步 4+ 次调用 |
| P1 | 布尔 mask listcomp → 向量化 | terrain_synthesizer.py | 1.5-2× | `[c.crust_type == "oceanic" for c in mesh.cells]` 等 |
| P2 | ~~MessagePack + Web Worker~~ ✅ | client.ts | 传输 -50% | cvt_mesh 已落地（`msgpack.worker.ts` + JSON 回退） |
| P2 | Ocean 并行 basin 求解 | climate_simulator.py | 有限 | 主海盆 139k cells 占 99% 时间 |
| P2 | useCellIdMap Web Worker | useCellIdMap.ts | 主线程不阻塞 | KD-tree 构建 + 像素查询 |

### 前端

| 优先级 | 目标 | 预期 |
|--------|------|------|
| P0 | ~~代码分割~~ ✅ | 首页 JS -60% |
| P0 | ~~gcTime~~ ✅ | 内存及时释放 |
| P1 | ~~MessagePack + Web Worker~~ ✅ | 传输 -50%，解析不阻塞主线程 |
| P2 | Progressive cvt_mesh loading | 首帧渲染提前 2-5s |

---

*此文档将随优化工作持续更新。*
