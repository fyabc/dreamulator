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

> **注意**：`--memory` 模式比子进程模式慢（tracemalloc 有 ~10% 开销），仅诊断时使用。

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

**湿槽+门开启（GW6 产品候选配置）的构建耗时**（200k 网格，OPENBLAS=4，
与 flag-off 基线 441.6 s 同机对照）：

| 世界 | 气候段 | 其中降水 | 总构建 | 相对基线 |
|---|---|---|---|---|
| earth/climate-dev | 2737.9 s | 2590.2 s | 2809.2 s | **6.4×**（基线 441.6 s / 降水 224.9 s = 11.5×） |
| nacrea（全量含地质） | 2841.8 s | 2673.5 s | 3162.1 s | **~4.1×**（基线 ≈770 s = 地质 255 + 气候 ~450 + 生态/文明 65；降水段 291→2674 s = **9.2×**，回归实验同机实测 11.4×） |

> **⚠ 速度裁决（2026-09-24）**：GW6 产品候选配置（湿槽 3 pass × pickup 门
> iterate-twice = 每构建 ~300 个稀疏 LU solve，基线 25）**总构建 6.4× 基线、
> 降水段 11.5×**——earth 47 min，**远超「发版门槛 ≤2× 基线（~10 min）」**。
> 成本是结构性的（solve 计数比 300/25 ≈ 降水段倍率 11.5，非并发竞争）。
> flag-on 默认因此**不满足发版速度门槛**，落地前必须走优化路径（下）或保持
> opt-in。earth 数字含与轮 7 实验并跑的轻度竞争，独占预计 ~40 min（仍 5×+）。

> 实验态参考（研究脚本、同机同 env）：flag-off 基线气候段 312 s；仅 pickup 门
> 638 s（iterate-twice = 3× solve/预算）；湿槽 3 pass 无门 ~660 s；湿槽+门
> （GW6 = 4 次预算 × 75 solve ≈ 9× 基线预算量）~2000 s。产品化压缩路径见
> `private/plans/w-supply-route.md` 速度账（S1 风链线性增量 / 波网格 4° /
> 预算组装向量化 / cell 重写合并 + pass 数评估）。

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

### 5.1 加载性能：Chrome DevTools Network

```bash
# 启动开发服务器
uv run dreamulator serve --data-dir data/worlds --reload
```

1. 打开 `http://localhost:8000` → F12 → Network 标签
2. 勾选 "Disable cache"，刷新页面
3. 按 Size 排序，找最大请求

**当前 200k 基线**（gzip 传输，来自 FastAPI 自动压缩）：

| 资源 | 原始大小 | gzip 后 | 说明 |
|------|---------|---------|------|
| `cvt_mesh.json` | ~220 MB | ~50 MB | 几何 + 气候字段，占加载时间 90%+ |
| `elevation.png` | ~2 MB | ~2 MB | 已压缩，gzip 无效 |
| JS bundle | ~1.5 MB | ~400 KB | Vite code-split |

**已落地**：MessagePack 二进制 + Web Worker 解析（FlatBuffers 放弃——无零拷贝需求，评审见 wave1-binary-format-review.md）。

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
