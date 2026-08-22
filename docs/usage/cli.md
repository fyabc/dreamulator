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
dreamulator branch promote earth pangea                  # 将分支提升为独立世界
```

分支类似 Git——在某一层分叉，共享上层数据，仅存储分叉层及之后的数据。

### 其他基础命令

```bash
dreamulator version                 # 显示版本号
dreamulator schema                  # 从 Pydantic 模型生成 JSON Schema
dreamulator delete earth            # 删除世界（--branch 可删分支）
```

---

## 人工语言（conlang）

```bash
dreamulator conlang evolve <world> <lang>   # 对词汇表运行 SCA 音变
dreamulator conlang tokenize <word>         # 显示 ASCIIPA 词的 token 分解
```

---

## 地形

地形生成由 `dreamulator build` 统一管理（见 [build 命令](#构建)）。`terrain` 子命令组现在只提供查看/导出工具。

### 生成地形

```bash
# 完整构建（含地形）
dreamulator build <world>

# 仅跑地质层
dreamulator build <world> --only geological
```

地形参数（`num_nodes`、`num_plates`、`tectonic_steps`、`seed`）通过 `terrain_config.yaml` 配置。

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

## 构建（Build）

### 完整构建

```bash
dreamulator build gaia-m --data-dir data/worlds
```

按 DAG 拓扑序执行所有引擎：`astronomy → geological → climate`。每层输出保存到对应的 `layers/<layer>/derived/` 目录。

### 按层构建

```bash
dreamulator build gaia-m --only geological   # 只跑地质层（地形生成）
dreamulator build gaia-m --only climate      # 只跑气候层
dreamulator build gaia-m --layer climate     # 从气候层开始（跳过已完成的层）
```

### 分支构建

```bash
dreamulator build earth --branch climate-dev --only climate
```

在分支上构建，输出保存到 `branches/<branch>/layers/<layer>/derived/`。

### 选项

| 选项 | 说明 | 示例 |
|------|------|------|
| `--only, -o` | 只运行指定引擎 | `--only climate` |
| `--layer, -l` | 从指定层开始 | `--layer climate` |
| `--force, -f` | 强制重算（跳过输出存在检查 + 禁用子阶段缓存） | `--force` |
| `--seed` | 覆盖随机种子 | `--seed 123` |
| `--data-dir` | 自定义数据目录 | `--data-dir data/worlds` |

> **v0.25+**: `terrain generate` 已移除，管线执行统一归 `dreamulator build`。
> 开发调试时使用 `build --only geological`；地形参数在 `terrain_config.yaml` 中配置。

### `--force` 使用场景

| 场景 | 命令 | 行为 |
|------|------|------|
| 只改 `geography.yaml` | `build`（无 `--force`） | 引擎级检查输出存在→地质引擎运行；子阶段缓存自动失效 geography 依赖阶段（plates/tectonics/terrain），mesh 从缓存加载 |
| 改引擎代码（地质/气候） | `build --force` | 跳过输出存在检查，禁用所有子阶段缓存，全量重算 |
| 只想重跑气候 | `build --force --only climate` | 地质引擎正常缓存，仅气候引擎强制重算 |
| 什么都没改，再次构建 | `build`（无 `--force`） | 引擎级跳过（输出已存在）

---

## 气候工具

### 查看气候状态

```bash
dreamulator climate info gaia-m --data-dir data/worlds
dreamulator climate info earth --branch climate-dev
```

显示温度/降水范围、Koppen 分类分布、输出文件列表。

### 验证气候精度

```bash
dreamulator climate validate earth --branch climate-dev
dreamulator climate validate earth --branch climate-dev --spatial  # 含逐 cell 空间对比
```

对比 ERA5 温度、GPCP 降水、Beck et al. Koppen 参考数据。输出 RMSE、R²、匹配率。

需要验证依赖：`uv sync --extra validation`

### 导入真实高程

```bash
dreamulator climate import-elevation earth --branch climate-dev
dreamulator climate import-elevation earth --branch climate-dev -n 100000  # 更多节点
```

下载 ETOPO1 全球 DEM（~400 MB，首次），重采样为等距矩形栅格 + CVT mesh。

### 典型工作流

```bash
# 1. 创建气候开发分支
dreamulator branch create earth climate-dev --at geological

# 2. 导入真实高程
dreamulator climate import-elevation earth --branch climate-dev

# 3. 构建气候层
dreamulator build earth --branch climate-dev --only climate

# 4. 验证精度
dreamulator climate validate earth --branch climate-dev --spatial

# 5. 查看结果
dreamulator climate info earth --branch climate-dev
```

---

## AI 叙述

```bash
dreamulator narrate earth                  # 生成世界描述
dreamulator narrate earth --branch pangea  # 分支描述
```

需要 Anthropic API key。OpenAI 兼容接口通过 `ANTHROPIC_BASE_URL` 环境变量指定。

---

## 守护轴（guard）

守护轴（Harness）是校验 / 审计 / 设定维护的**第三条轨道**（总纲见 `docs/design/harness.md`）。
`guard` 命令组做两件事：**过期检测**（`check`）与**决策记录（ADR）台账管理**
（`accept` / `supersede` / `deprecate`）。

### 过期检测

```bash
dreamulator guard check gaia-m [--branch <b>] [--data-dir <dir>]
```

三级检测，从粗到精（harness.md §7）：

| 级别 | 检测什么 | 判定 |
|------|---------|------|
| ① 模板断链 | 渲染文档/ADR 后残留 `{{ ... }}` | 字段被删/改名 → 硬约束 |
| ② 输入指纹 | ADR frontmatter `checked_against` vs 当前层 yaml 哈希 | 输入改了 → 需复核 |
| ③ 渲染 diff | ADR 定量声明（模板）重渲染 vs 基线 | 事实漂移 → 结论需复核 |

意图感知：`divergence: intentional` 的记录报 info（已知覆写），不报 stale。

### 决策记录台账（ADR）

```bash
dreamulator guard accept gaia-m 0001              # proposed → accepted（写 checked_against + 基线）
dreamulator guard supersede gaia-m 0001 --by 0002 # 标记被 0002 取代（正文不动）
dreamulator guard deprecate gaia-m 0001           # 弃用（前提失效但历史保留）
dreamulator guard archive gaia-m --limit 20       # 归档最旧的 accepted，直至 ≤ 上限
```

- ADR 落在 `data/worlds/<world>/design-notes/00NN-<slug>.md`，frontmatter 带 `status` 字段。
- 状态机：`proposed → accepted / deprecated / superseded by <编号>`。
- **永不编辑 accepted 的结论正文**——推翻走 `supersede`（git 记历史，文档不写「旧值→新值」）。
- `accept` 自动写入 `checked_against`（astronomy + geological 的 yaml 指纹）与渲染基线
  `design-notes/.guard-baseline.json`（③ 的比对基准）。

**容量上限 + 强制剪枝**（harness.md §8.2，借鉴 Hermes）：台账默认上限 **20 条 accepted**
（`accept --limit` / `archive --limit` 可调）。`accept` 在台账已满时**拒绝写入**（而非静默追加），
先 `guard archive` 把最旧的 accepted 标 `deprecated` 归档腾位。

---

## 地图图层导出（export）

headless 烘焙地图图层为彩色 PNG，颜色与前端渲染逐字节一致（配色单源 `palettes.json`，
前后端共读）。支撑 `/read-map` skill、`ai civ`、CI 审计——守护轴的取证腿。

```bash
dreamulator export layers gaia-m                                # 全部 5 层，分辨率取 map.yaml
dreamulator export layers gaia-m --layers terrain,koppen        # 指定图层（逗号分隔）
dreamulator export layers gaia-m --grid 4096x2048               # 指定输出分辨率 WxH
dreamulator export layers gaia-m --output out/ --data-dir private/worlds
```

| 图层 | 类型 | 字段 | 说明 |
|------|------|------|------|
| `terrain` | 自适应高程色带 | `elevation` | NOAA ETOPO1 海洋 + ESRI 陆地，水深加深 |
| `koppen` | 分类（Beck 2018） | `koppen_class` | 海洋回退 `Ocean` |
| `biome` | 分类（Whittaker） | `biome` | 未匹配处透明 |
| `agriculture` | 0–100 连续 | `agriculture_score` | 仅陆地 |
| `habitability` | 0–100 连续 | `habitability_score` | 仅陆地 |

输出为 RGBA PNG（未着色处透明），文件名 `<layer>.png`。

---

## 种子探索（explore-seeds）

批量生成多个 seed 的地形，对比关键指标 + 缩略图，落盘种子目录。回应技术债 #16
（Cortial-2019 对 seed 高度敏感：不同 seed 产出完全不同的星球，需工具链辅助选种子）。

```bash
dreamulator explore-seeds gaia-m --seeds 42,123,456         # 指定 seed
dreamulator explore-seeds gaia-m --count 10 --nodes 50000   # 随机 10 个 seed，5 万节点
dreamulator explore-seeds gaia-m --raw                      # 纯 seed（跳过 geography 锚定）
```

| 选项 | 说明 | 默认 |
|------|------|------|
| `--seeds, -s` | 逗号分隔的 seed 列表 | 无（用 `--count`） |
| `--count, -n` | 随机 seed 数量（固定 RNG，可复现） | 5 |
| `--nodes` | 分辨率（num_nodes） | 50000 |
| `--raw` | 跳过 geography.yaml 锚定 | 关 |
| `--width` | 缩略图宽度 | 512 |
| `--output, -o` | 目录输出路径 | `<world>/seed_catalog/` |

对比指标：海洋/陆地占比、均陆高、最大海拔、最大洋深、大陆数、板块数。
输出 `seed-catalog.json` + `thumbnails/<seed>.png`（地形 RGBA，配色与前端一致）。

---

## 服务端

```bash
dreamulator serve                    # 启动 API + 前端
dreamulator serve --reload           # 开发模式（热重载）
dreamulator serve --open             # 启动并打开浏览器
dreamulator serve --data-dir data/worlds  # 自定义数据目录
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
