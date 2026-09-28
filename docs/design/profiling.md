# 性能分析工作流（Profiling）

本文档描述 dreamulator 项目**实际可执行的** profiling 流程，覆盖后端（Python）和前端（TypeScript/React）两端。

> 多分辨率基准数据（100k/200k/500k/1M 缩放对比）见 [roadmap §七-11](../design/roadmap.md#七已知技术债务)。

---

## 1. 日常开发：构建耗时档案（自动，零配置）

每次 `dreamulator build` 结束后自动写入 `<world_dir>/build_profile.json`，
控制台同步打印阶段耗时占比表。**每次引擎改动后检查此文件即是最低成本的性能验证。**

### 1.1 读取当前数据

```bash
# 直接查看 JSON
cat data/worlds/nacrea/build_profile.json

# 或用脚本格式化打印
uv run python scripts/dev/profile_build.py nacrea --data-dir data/worlds
```

输出示例（nacrea 200k，seed=42，本机）：

```
Build profile: nacrea (seed=42, total 347.4s)

  astronomy      0.6s   0%  ok
  geological   213.8s  62%  ok
    mesh                 34.2s
    tectonics            77.0s
    terrain              80.6s
    export               12.5s
    plates                4.6s
    boundaries            4.6s
  climate      121.8s  35%  ok
    ocean                60.2s
    precipitation        25.8s
    wind                  8.1s
    temperature           5.9s
  ecology       11.3s   3%  ok
```

### 1.2 关注指标

| 关注点 | 看什么 |
|--------|--------|
| 地质总耗时 | tectonics + terrain 之和。地形合成（terrain）通常最重 |
| 气候总耗时 | ocean (GMRES) 是唯一超线性项，其他 O(N) |
| 阶段突增 | 改动前后同一阶段耗时翻倍 → 立即排查算法回归 |

---

## 2. 内存诊断：profile_build.py --memory

```bash
uv run python scripts/dev/profile_build.py nacrea --data-dir data/worlds --memory
```

进程内运行管线 + `tracemalloc`，输出 Top 15 内存分配点。用于排查：
- 构建 OOM（500k+ 节点时）
- 不必要的中间数组复制
- numpy/scipy 大对象泄漏

> **注意**：`--memory` 模式仅诊断 Python 对象层分配——**看不见 numpy/SuperLU
> 等自管分配器的大块**（2026-09-27 实测 top 位点全是 import 碎片），且本管线
> 上放大严重（GMRES 段 ~10×、地质段 ~4.5×），其计时数据不可用。进程级内存
> 分解改用 RSS 轮询（见 §2.1 工具教训）。

### 2.1 OpenBLAS 线程上限（大网格构建的内存稳定性）

**现象**（2026-09-24，200k 网格湿槽实验首跑实测）：构建进程以
`OpenBLAS error: Memory allocation still failed after 10 retries, giving up`
中止——机器尚有 14.7 GB 空闲。根因：numpy/scipy 链接的 scipy-openblas64
（编译上限 MAX_THREADS=24）在 **DLL 加载时**按线程数预分配工作缓冲；与
200k×12 的多个大数组叠加后把分配顶爆。两个重任务并跑（构建 + 实验）时最易触发。

**处置**：在启动构建/实验的 shell 里设线程上限——

```powershell
$env:OPENBLAS_NUM_THREADS="4"; $env:OMP_NUM_THREADS="4"; uv run dreamulator build ...
```

```bash
OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 uv run dreamulator build ...
```

**必须在进程启动前设**：OpenBLAS 线程池在库加载时初始化，Python 运行时再改
`os.environ` 无效（运行时限流需 threadpoolctl 一类工具，评估后未引入——
失败模式仅出现在内存紧张/并发场景，不值得加依赖；如未来产品化大网格构建
再议）。

**对速度影响 ≈ 0，这不是速度旋钮**：构建热点是 scipy 稀疏 LU（SuperLU，
单线程、不经 BLAS）、洋流 GMRES（稀疏迭代）与逐元素 numpy（内存带宽受限）；
走 LAPACK/BLAS 的只有定常波求解器的小块稠密运算与带状求解（本质串行）。
24 线程不会更快，4 线程不会更慢。

**建议**：≤32 GB 内存机器跑 200k 网格、或两个重任务并跑时设 4；空闲机器
单发构建可不设。

**GW6 默认开（湿槽 3 pass × pickup 门）的当前构建耗时**（2026-09-27 S 速度轮
+ S5-lite 后，200k 网格，OPENBLAS=4，同机）：

| 世界 | 气候段 | 其中降水 | 总构建 | 对照轮前 |
|---|---|---|---|---|
| nacrea（全量含地质） | 512.8 s | 356.9 s | ~803 s | 气候 1120 s（**−54%**） |
| earth/climate-dev | 537.1 s | 397.7 s | 593.8 s（不含地质） | 气候 2738 s（含并跑竞争；**约 −80%**） |

> **S 速度轮（2026-09-27）**：py-spy 行级归因重排靶点——原计划 S1（风链
> 线性增量）/S2（波网格 4°）实测合计 <15 s **销项**；真热点 = ① 水汽预算
> 40 趟 Jacobi 风平滑的 `np.add.at` 无缓冲散射（单行 262.5 s = 全构建
> 18%），② `splu` 列排序（482 s）。三刀：全库 9 处 add.at → bincount/CSR
> 算子；`splu(permc_spec="MMD_AT_PLUS_A", options={"SymmetricMode": True})`
> ——预算矩阵模式结构对称（扩散项保证邻接双向非零），对称排序大幅削填充
> （降水段 −40%）；mesh gzip 9→6。**指标三度逐位一致**（4 位存储截断吸收
> 浮点差），earth 全电池（T R² 0.991 / P R² 0.46 / κ 68.9% / 账本 −0.20%）
> 与 GW6 收口包逐项同值。GW6 对 flag-off 倍率 ~1.4×（≤2× 门槛重新可达）。
> flag-off 基线（同机 441.6 s / 气候 ~450 s）同受 add.at 修复惠益。
>
> **S5-lite（2026-09-27，`plans/s5-coarse-grid-budget.md` 文末）**：预算调用
> 不变量外提（平滑算子/边几何/cell 场挂 `mesh._budget_cache`）+ CSC 装配
> 结构复用（探针取槽序，矩阵逐位不变）→ 气候段再 −6.7%（550→512.8 s）；
> 地质 add.at 清尾无计时收益。**小代码量级的可回收池已榨干**——剩余大头 =
> LU 结构性成本 ~210 s（降水段 60%），再往下只有 S5-full 粗网格（登记）或
> GPU 服务器实验。
>
> **内存画像**（进程树 RSS 轮询，`private/research/2026-09-27-rss-poll.py`）：
> 健康构建峰值 **3.3 GB**（降水 Picard 段，含单次 LU 因子 ~0.5 GB 瞬态）；
> 每层 mesh 全量重存有 ~2.4-2.8 GB 尖峰（S4 削减对象）。MMD 排序下单 LU
> 因子 <1 GB。
>
> **工具教训**：① `--memory`（tracemalloc）看不见 numpy/SuperLU 自管分配器，
> 且事后快照错过峰值——内存分解用进程级 RSS 轮询；② tracemalloc「~10%
> 开销」在本管线不实（GMRES 段 10×、地质段 4.5× 放大），其计时数据不可用；
> ③ splu 的 MMD_* 排序必须配 `SymmetricMode=True`，否则 `gstrf invalid
> arguments`——且崩溃态进程会膨胀到 ~12 GB，勿据其判断内存画像；④ 本机
> 构建进程链四层（uv → dreamulator.exe → venv python → anaconda python），
> 单 PID 采样会采到壳，需进程树遍历。

---

## 3. 热点分析：py-spy 火焰图

采样式 profiler，~1–5% 开销，无需改代码。用于定位 CPU 热点（哪个函数/哪行耗时最多）。

```bash
# 一次性安装（非项目依赖，dev 环境按需装）
uv add --dev py-spy

# 生成 SVG 火焰图
uv run py-spy record -o private/prof/nacrea-flame.svg -- \
    uv run dreamulator build nacrea --data-dir data/worlds --force

# 生成 speedscope 格式（可在 https://speedscope.app 缩放分析）
uv run py-spy record --format speedscope -o private/prof/nacrea.json -- \
    uv run dreamulator build nacrea --data-dir data/worlds --force
```

SVG 用浏览器打开即可交互式浏览；speedscope 适合长构建（>5 min）的时间线分析。

### 3.1 典型使用场景

- **"地质为什么慢？"** → 火焰图看 `tectonic_simulator` vs `terrain_synthesizer` 占比
- **"ocean GMRES 为什么超线性？"** → 按时间线分段：海盆切分 vs 独立求解 vs 汇合
- **"改动前后对比"** → 生成两张火焰图，肉眼对比函数条宽度

> py-spy 是 Windows 原生支持的 Python 采样 profiler（不依赖 `perf`），本机 AMD 核显环境可用。

---

## 4. CI 基准：pytest-benchmark

### 4.1 本地运行

```bash
# 全部基准（排除 slow marker）
uv run pytest benchmarks -m "benchmark and not slow" -v

# 微基准（纯算法，无 IO）
uv run pytest benchmarks/micro -m benchmark -v

# 宏基准（端到端构建阶段，较慢）
uv run pytest benchmarks/macro -m benchmark -v

# 对比已保存基线（需要先跑一次保存 JSON）
uv run pytest benchmarks -m benchmark --benchmark-json bench.json
uv run pytest benchmarks -m benchmark --benchmark-compare
```

### 4.2 基准套件一览

| 分类 | 文件 | 测试内容 | 典型耗时 |
|------|------|---------|---------|
| micro | `test_cvt_mesh.py` | Fibonacci + Lloyd 松弛 (4096 nodes) | ~2s |
| micro | `test_noise.py` | fBm 噪声生成 | <1s |
| micro | `test_climate.py` | 气候模拟 (256 cells) | <1s |
| micro | `test_mesh_io.py` | CVT mesh JSON 读写 | ~1s |
| macro | `test_terrain_build.py` | 地形管线端到端 | ~30s |

### 4.3 CI 自动跟踪

`.github/workflows/benchmarks.yml`：
- PR 推送时自动运行微基准，与 `perf-dashboard` 分支基线对比
- 1.2× 退化 → PR 评论警告；2× 退化 → 告警
- main 推送时自动更新基线数据

---

## 5. 前端性能分析

### 5.1 加载性能：perf 打点 + CDP 测量

```bash
# 启动开发服务器
uv run dreamulator serve --data-dir data/worlds --reload
```

**打点体系**（`frontend/src/utils/perf.ts`）：`mark('x-start'/'x-end')` 自动配对成 measure；
重复阶段记 `#N` 序号；`recordExternal` 记 worker 侧时长；`measureFromStart('first-frame')`
= 导航 → 首帧渲染完成（交互就绪口径，`GlobeViewer.tsx` 首个 useFrame）。加载完成时控制台
输出分组瀑布（⏱ dreamulator load）。CDP 自动化采集 = `private/research/2026-09-29-fe-load-profile/cdp-profile.mjs`
（零依赖 Node 脚本，Chrome --remote-debugging-port，采集 measures/resources/longtasks/堆）。

**当前 200k 基线**（2026-09-29，earth root，冷缓存，本机；含同日优化轮 ①voronoi gate
②ETag/304 ③kd-tree 重写 ④几何 transferable）：

| 场景 | first-frame（交互就绪） | 传输总量 | JS 堆 used |
|------|----:|----:|----:|
| globe 页 | **14.4 s** | ~64 MB（冷） | 271 MB |
| 2D 地图页 | — | **~25 MB** | ~290 MB |
| globe 页（热缓存，304） | ~14 s | **3.6 MB** | ~270 MB |

globe 冷加载瀑布（主线程阻塞加 ★）：mesh fetch（`cvt_mesh.msgpack.gz`，`application/gzip`
+ ETag）0.57 s 净传 → worker gunzip 0.54 s → msgpack 解码 2.1 s → cells 克隆 ~1.9 s
（序列化 0.98 + 反序列化 ~0.97；vertices/regions 已 transferable 零拷贝、adjacency 已丢弃）
→ adapt 0.16 s → **kd-tree + 8.4M 查询 3.6 s★** → **layer-bake 3.4 s★** → 纹理就绪 →
R3F/WebGL 初始化 + 首帧 ~1.4 s★。剩余大头 = cells 对象图（克隆 80%）与 bake——前者归
P1「几何/气候数据分离存储」。完整数据、优化判词与已否证方向 →
`private/research/2026-09-29-fe-load-profile.md`。

注意：**手工声明 `Content-Encoding: gzip` 的响应 Chrome 不复用 HTTP 缓存条目**（同 URL
二次仍全量拉取；实测对照见上文 research 文档 §九.2）——大二进制端点要缓存就走
`application/gzip` + 客户端 DecompressionStream，或裸体 + ETag。各端点除 mesh 外均
裸传（无 GZipMiddleware）；JS chunk 中 spatialReference.ts 内嵌观测数据占 2.1 MB（FE-01）。

### 5.2 渲染性能：React Developer Tools Profiler

1. 安装 [React Developer Tools](https://react.dev/learn/react-developer-tools) 浏览器扩展
2. 打开地图页 → Components 标签 → ⚙️ 勾选 "Highlight updates when components render"
3. Profiler 标签 → 录制 3–5 秒操作（拖拽/缩放/图层切换）
4. 查看 flamegraph：找重复渲染或耗时最长的 commit

**常见问题**：
- 图层切换触发全量重渲染 → 检查 `useMemo` / `React.memo` 是否失效
- 拖拽时每帧触发 state 更新 → 确认 RAF throttle 生效

### 5.3 包体积：Vite Bundle Visualizer

```bash
cd frontend
npm run build                    # 正常构建

# 分析包体积（需要 rollup-plugin-visualizer）
npx vite build --debug           # 查看模块大小
```

或使用 `source-map-explorer`：

```bash
npm install -g source-map-explorer
source-map-explorer dist/assets/*.js
```

---

## 6. 跨版本对比流程

引擎改动后，**必须保留改前基线数字**才能判断性能变化：

```bash
# 1. 改前：保存基线
cp data/worlds/nacrea/build_profile.json /tmp/baseline_profile.json

# 2. 改代码 → 构建
uv run dreamulator build nacrea --data-dir data/worlds --force

# 3. 对比
uv run python -c "
import json
old = json.load(open('/tmp/baseline_profile.json'))
new = json.load(open('data/worlds/nacrea/build_profile.json'))
old_t = old['total_wall_seconds']
new_t = new['total_wall_seconds']
print(f'Before: {old_t:.1f}s  After: {new_t:.1f}s  Δ: {new_t-old_t:+.1f}s ({100*(new_t-old_t)/old_t:+.1f}%)')
for e_new in new['engines']:
    e_old = next((e for e in old['engines'] if e['engine']==e_new['engine']), None)
    if e_old:
        d = e_new['wall_seconds'] - e_old['wall_seconds']
        pct = 100*d/max(e_old['wall_seconds'], 1e-9)
        print(f'  {e_new[\"engine\"]:<12} {e_old[\"wall_seconds\"]:6.1f}s → {e_new[\"wall_seconds\"]:6.1f}s  Δ: {d:+.1f}s ({pct:+.1f}%)')
"
```

---

## 7. 方法学要点

- **先测后改**：任何优化前后都要有数字，不能凭感觉
- **分离算法与 IO**：对比有无导出阶段的耗时，区分计算 vs 序列化
- **可复现性**：构建对相同 seed 必须 bit-identical（`tests/validation/test_determinism.py` 回归防线）
- **警惕噪声**：墙钟 ±5% 波动正常（OS 调度/GC），>10% 持续差异才可信
- **关注缩放**：O(N²) bug 在小 N 下不明显，通过 `benchmarks/micro` 的尺寸参数化（n=10k/100k）暴露
