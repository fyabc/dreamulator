# 性能优化

> 本文记录性能优化的**当前状态与 backlog**：已完成项只留一行「结论 + 效果」，
> 详细的设计与实验过程在 git 历史与 CHANGELOG。性能分析工作流见 [profiling.md](profiling.md)。

## 当前基线

nacrea 200k seed=42 全量构建（v0.36.0，roadmap §一快照）：~391 s = 地质 238 s +
气候 147 s + 生态 5 s。二次构建命中子阶段缓存时地质段降到 ~16 s（15×）。

## 已完成优化（按主题）

- **地质层子阶段缓存**（`terrain_cache.py`）：5 个阶段中间产物 + 指纹
  （seed | config | geography_hash | upstream）；二次构建地质 244 s → 16 s（15×），
  `--force` 禁用。
- **构建跳过上游传播**（`engine/pipeline.py`）：`upstream_ran` 标志 + Climate
  `outputs_exist()`，未改动层全部跳过。
- **Ocean GMRES Jacobi 预条件子**（`ocean_circulation.py`）：ocean 60.2 → 55.6 s。
- **Terrain 合成向量化**（`terrain_synthesizer.py`）：边界效应批量 falloff、
  interior landforms 大圆面预过滤（O(n) dot 预筛掉 >95% 远离 cell）、
  `CVTMesh.cell_xyz/lon/lat` 坐标缓存、海平面校准排序+前缀和——terrain
  114 → 59.8 s（-47.7%）。
- **前端代码分割**（`App.tsx`/`vite.config.ts`）：React.lazy 拆 8 页 + vendor
  chunks + `gcTime: 1min`——首页 JS -60%。
- **MessagePack + Web Worker**（`client.ts`）：cvt_mesh 传输 -50%，解析不阻塞主线程。
- **Tectonic BFS → scipy 稀疏图**（`tectonic_simulator.py`）：预建 CSR 邻接。
- **Numba JIT 噪声内核**（`noise_kernels.py`，`numba>=0.61`）：逐 cell
  `opensimplex.noise3`（~44 µs）→ 编译 3D Perlin（~0.1 µs），确定性保持
  （显式种子排列表、逐点独立求值；换后端不逐位一致是已记录口径）。

## Backlog（未完成）

| 优先级 | 目标 | 文件 | 预期 |
|--------|------|------|------|
| P1 | 布尔 mask listcomp → 向量化 | terrain_synthesizer.py | 1.5-2×（`[c.crust_type == ... for c in cells]` 族） |
| P2 | Ocean 并行 basin 求解 | climate_simulator.py | 有限（主海盆 139k cells 占 99% 时间） |
| P2 | useCellIdMap Web Worker | useCellIdMap.ts | KD-tree 构建不阻塞主线程 |
| P2 | Progressive cvt_mesh loading | 前端 | 首帧渲染提前 2-5 s |
