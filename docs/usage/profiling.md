# 性能分析工作流（Profiling）

> M0 性能仪表套件用法（2026-08-03 建立）。优化计划与基线数字见
> `private/plans/perf-profiling-and-optimization.md`。

## 1. 结构化构建档案（自动）

每次 `dreamulator build` 结束会写入 `<world>/build_profile.json`：

```json
{
  "world": "gaia-m", "seed": 42, "total_wall_seconds": 328.2,
  "engines": [
    {"engine": "geological", "wall_seconds": 212.9,
     "stages": {"mesh": 8.1, "plates": 45.0, "tectonics": 95.0, "terrain": 50.8, "export": 13.0}},
    {"engine": "climate", "wall_seconds": 113.7,
     "stages": {"temperature": 0.1, "wind": 14.2, "precipitation": 86.8, "koppen": 0.1, "writeback": 0.2}}
  ]
}
```

构建结束时的控制台也会打印各引擎/阶段耗时占比表。

## 2. scripts/profile_build.py

```bash
uv run python scripts/profile_build.py gaia-m                    # 子进程构建 + 阶段表
uv run python scripts/profile_build.py gaia-m --memory           # 进程内跑 + tracemalloc 前 15 分配点
uv run python scripts/profile_build.py earth --data-dir private/worlds
```

## 3. 火焰图（py-spy，首选热点分析）

采样式、~1–5% 开销、Windows 原生支持、无需改代码：

```bash
uv add --dev py-spy                     # 一次性
uv run py-spy record -o private/prof/gaia-flame.svg -- uv run dreamulator build gaia-m --force
uv run py-spy record --format speedscope -o private/prof/gaia.json -- uv run dreamulator build gaia-m --force
```

SVG 可直接浏览器打开；speedscope 格式可在 https://speedscope.app 缩放分析。

## 4. 行级分析（Scalene）

区分 **Python 时间 vs C/numpy 原生时间**（numpy 重代码的关键差异点）：

```bash
uv run scalene src/dreamulator/cli.py build gaia-m --force
```

注意：Windows 上 Scalene 仅 CPU/GPU（内存 profiling 需 WSL）；GPU 侧仅限 NVIDIA CUDA
（本机 AMD 核显不适用）。内存问题在 Windows 上用 `--memory` 模式（tracemalloc）。

## 5. DAG 时序（VizTracer）

多阶段调用顺序的确定性时间线（Chrome trace 格式）：

```bash
uv run viztracer -- uv run dreamulator build gaia-m --force
uv run viztracer --open    # 查看 result.json
```

## 6. 基准测试（benchmarks/）

pytest-benchmark 微基准 + 宏基准，默认套件排除（`benchmark` marker）：

```bash
uv run pytest benchmarks -m benchmark                       # 全部基准
uv run pytest benchmarks/micro -m benchmark                 # 仅微基准
uv run pytest benchmarks -m benchmark --benchmark-compare   # 对比已保存基线
```

微基准尺寸参数化（n=10k/100k）用于暴露意外 O(n²)（log-log 斜率）。
CI 回归跟踪：`.github/workflows/benchmarks.yml`（github-action-benchmark，
数据推送 `perf-dashboard` 分支，1.2× 提醒、2× 告警；噪声问题严重时迁 CodSpeed）。

## 7. 方法学要点

- **先测后改**：任何优化前后都要有基准数字（写入计划文档）
- **分离算法与 IO**：profile 时对比有无导出阶段的差异，隔离序列化开销
- **可复现性**：构建对相同 seed 必须比特一致（tests/validation/test_determinism.py
  回归防线；发现 `hash()` 盐化类 bug 立即修）
