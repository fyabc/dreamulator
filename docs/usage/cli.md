# CLI 命令参考

> 完整命令行接口文档。快速入门见 [README.md](../../README.md)。

---

## 基础命令

### 创建世界

```bash
dreamulator init <name> --template earthlike
```

从模板创建新世界。可选模板：`minimal`（最小）、`earthlike`（类地）。

### 查看世界

```bash
dreamulator list                    # 列出所有世界
dreamulator info earth              # 查看 earth 详情
dreamulator validate earth          # 校验数据完整性
```

### 分支管理

```bash
dreamulator branch create earth pangea --at geological   # 在地质层分叉
dreamulator branch list earth                            # 列出分支
dreamulator branch info earth pangea                     # 分支详情
dreamulator branch delete earth pangea                   # 删除分支
```

分支类似 Git——在某一层分叉，共享上层数据，仅存储分叉层及之后的数据。

---

## 地形生成

### 生成地形

```bash
dreamulator terrain generate earth --planet earth --branch terrain-dev
```

完整管线（9 阶段）：CVT 网格 → 板块剖分 → 时间演化 → 边界检测 → 地形合成 → 导出。

**常用选项**：

| 选项 | 说明 | 示例 |
|------|------|------|
| `-n, --num-nodes` | CVT 节点数（分辨率） | `-n 4096`（快速）/ `-n 100000`（精细） |
| `--num-plates` | 板块数量 | `--num-plates 20` |
| `--tectonic-steps` | 时间演化步数 | `--tectonic-steps 50` |
| `--seed` | 随机种子 | `--seed 42` |
| `--stages, -s` | 仅运行指定阶段 | `-s mesh,plates` |
| `--benchmark` | 保存基准测试文件 | `--benchmark` |
| `-v, --verbose` | 详细日志 | `-v` |

**示例**：

```bash
# 快速迭代（4096 节点，静态板块）
dreamulator terrain generate earth -p earth -b terrain-dev -n 4096 --seed 42

# 精细模拟（100K 节点，125 步时间演化）
dreamulator terrain generate earth -p earth -b terrain-dev -n 100000 --tectonic-steps 125

# 只重新生成板块和地形（跳过网格和时间演化）
dreamulator terrain generate earth -p earth -b terrain-dev -s plates,boundaries,terrain,export
```

### 查看地形

```bash
dreamulator terrain info earth --planet earth --branch terrain-dev
```

显示高程范围、板块数、种子、节点数等摘要信息。

### 打开输出目录

```bash
dreamulator terrain open earth --planet earth --branch terrain-dev
```

在文件资源管理器中打开地形输出目录。

### 验证地形基准

```bash
dreamulator terrain validate earth --planet earth --branch terrain-dev
```

用种子 42 重新生成地形，与 `benchmark.json` 对比。偏差超阈值时退出码非零。

---

## AI 叙述

```bash
dreamulator narrate earth                  # 生成世界描述
dreamulator narrate earth --branch pangea  # 分支描述
```

需要 Anthropic API key。OpenAI 兼容接口通过 `ANTHROPIC_BASE_URL` 环境变量指定。

---

## 服务端

```bash
dreamulator serve                    # 启动 API + 前端
dreamulator serve --reload           # 开发模式（热重载）
dreamulator serve --open             # 启动并打开浏览器
dreamulator serve --data-dir private/worlds  # 自定义数据目录
```

前端访问 `http://localhost:8000`，API 文档访问 `http://localhost:8000/docs`。

---

## 全局选项

| 选项 | 说明 |
|------|------|
| `--data-dir` | 覆盖默认数据目录（所有命令） |
| `DREAMULATOR_DATA_DIR` | 环境变量等效 `--data-dir` |

---

## 配置

地形管线配置通过 YAML 文件管理，路径：`layers/geological/input/terrain_config.yaml`

**关键配置项**：

```yaml
terrain:
  num_nodes: 4096           # CVT 分辨率

plates:
  num_plates: 15            # 板块数量
  plate_algorithm: cortial2019
  tectonic_algorithm: ""    # ""=静态, "cortial2019"=演化
  tectonic_steps: 0         # 演化步数
  tectonic_dt_my: 0.0       # 步长 My（0=自动缩放）

terrain_algorithm: cortial2019_asymmetric  # 地形算法
hotspot_count: 3            # 热点链数量
mountain_asymmetry: 0.4     # 山脉不对称度
shelf_width_km: 120.0       # 大陆架宽度

noise:
  noise_anisotropy: 0.3     # 各向异性噪声
```

**算法选择**（策略模式）：

| 配置项 | 可选值 |
|--------|--------|
| `plate_algorithm` | `cortial2019` |
| `terrain_algorithm` | `cortial2019_gaussian`, `cortial2019_asymmetric` |
| `tectonic_algorithm` | `""` (无), `cortial2019` |

---

## 目录结构

```
data/worlds/<name>/
├── world.yaml                    # 世界元数据
├── layers/
│   ├── astronomy/input/          # 恒星系参数
│   ├── geological/input/         # 行星参数 + 地形配置
│   │   └── maps/<planet>/
│   │       ├── elevation.png     # 高度图
│   │       ├── cvt_mesh.json     # CVT 网格
│   │       ├── plates.json       # 板块数据
│   │       └── benchmark.json    # 基准测试
│   └── civilization/input/       # 文明设定
└── branches/<name>/
    ├── branch.yaml               # 分支元数据
    └── layers/                   # 仅分叉层及之后
```
