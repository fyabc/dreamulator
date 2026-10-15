# 新手教程：创建你的第一个世界

> 本教程带你从空仓库出发，走到「在浏览器里看到自己星球的地图，并导出高清图像」。
> 全程约 30 分钟，其中约 15 分钟是引擎在后台计算。你只需要基本的命令行操作经验，
> 不需要天文学背景。卡住时先看该节末尾的「如果出错」，再查 [CLI 命令参考](cli.md)，
> 或到 GitHub Issues 提问。

## 0. 你将构建什么

一颗围绕 0.9 倍太阳质量恒星运行的类地行星。你会亲手设定它的恒星、轨道和自转轴
倾角，然后让引擎依次推演出地形、气候与生态，最后在浏览器里查看地图并导出图像。

整条链路是：`init` 创建世界 → 编辑 input 设定 → `build` 推演 → `serve` 查看 →
`export` 出图。

Dreamulator 有一条核心规则，教程全程都会体会到它：**你只写创意设定（各层
`input/` 目录里的 YAML），所有物理结果都由引擎计算（写到 `derived/` 目录）**。
设定与计算结果严格分离，引擎输出永远不需要、也不应该手工修改。

## 1. 安装与环境自检

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)（Python 包管理器）、
Node.js 20+ 和 npm。

```bash
git clone https://github.com/fyabc/dreamulator.git
cd dreamulator
uv sync --all-extras          # 安装 Python 依赖
cd frontend && npm ci && npm run build && cd ..   # 构建前端（serve 要用）
```

验证安装：

```bash
uv run dreamulator version
```

预期输出：打印版本号，例如 `dreamulator 0.39.0`。

**如果出错**：`uv sync` 报 Python 版本问题时，uv 会提示并可以自动下载 3.12；
`npm ci` 失败时先确认 `node --version` 不低于 20。

## 2. 创建世界

从 `earthlike` 模板创建一个叫 `myworld` 的世界（模板提供一套类地默认设定，我们
在它基础上改）：

```bash
uv run dreamulator init myworld --template earthlike
```

验证：

```bash
uv run dreamulator list
```

预期输出（表格中多出 myworld 一行）：

```
│ myworld │ Earth-like world — G2V star, rocky planet │ 0        │ 2026-10-14 │
```

看看生成了什么：

```
data/worlds/myworld/
├── world.yaml                          # 世界元数据：名称、随机种子
└── layers/
    ├── astronomy/input/stellar.yaml    # 恒星系设定 ← 下一节编辑它
    ├── geological/input/planets.yaml   # 行星设定（自转、大气、海洋…）
    ├── geological/input/terrain_config.yaml  # 地形生成参数（分辨率、板块、演化步数）
    └── civilization/input/             # 文明设定（本教程不涉及）
```

每个层级的 `input/` 是你写的设定，`derived/` 是引擎算出的结果（构建后才出现）。
现在还没有任何 `derived/` 目录——这正是我们要做的事。

**如果出错**：`init` 提示世界已存在时，换一个名字，或先
`uv run dreamulator delete myworld`。

## 3. 设置天文参数

打开 `data/worlds/myworld/layers/astronomy/input/stellar.yaml`，做三处改动：

1. 把恒星的 `mass: 1.0` 改成 `mass: 0.9`——一颗比太阳稍小、稍暗的恒星。
2. **删掉** `luminosity: 1.0` 这一行。引擎遵循「自变量/因变量」约定：你给质量，
   它用质光关系推导光度；两个都给，它会做一致性校验。删掉手写光度，让引擎自己算。
3. 把行星轨道的 `semi_major_axis_au: 1.0` 改成 `0.75`。0.9 倍太阳质量的恒星只有
   约 0.57 倍太阳光度，行星轨道要内移才能保持宜居。

恒星变了，世界的自我介绍也该跟上：打开 `data/worlds/myworld/world.yaml`，把
`metadata.description` 里「G2V star」的描述改成与 0.9 倍太阳质量恒星相符的
说法（描述只是叙事文本，不影响计算，但会显示在 `list` 和前端里）。

构建天文层：

```bash
uv run dreamulator build myworld --only astronomy
```

预期输出：

```
>> astronomy  (astronomy)
  done (0.0s)

Results: 1 succeeded, 0 failed, 4 skipped
```

验证：打开构建产出的 `layers/astronomy/derived/stellar_derived.yaml`，可以看到
引擎从质量推出的结果：

```yaml
  input_mode: mass
  computed_mass: 0.9
  computed_luminosity: 0.569665    # 引擎推导的光度（太阳光度 = 1）
```

同目录的 `habitable_zones.yaml` 给出这颗恒星的宜居带为 0.72–1.27 AU——我们定的
0.75 AU 在宜居带内侧，行星仍然是宜居的。

## 4. 配置行星与地形

打开 `data/worlds/myworld/layers/geological/input/planets.yaml`，做两处改动：

1. `axial_tilt_deg: 23.4` 改成 `37.0`——更大的自转轴倾角意味着更极端的季节。
2. `hydrosphere` 下的 `water_coverage: 0.708` 改成 `0.65`——海洋覆盖率 65%，
   陆地比地球略多但保留开阔大洋。地形引擎的海平面校准目标默认就取
   「1 − 水覆盖率」：设定里写多少水，生成的地图上就有多少水，两者不会脱节
   （细节见 [地质管线](../design/pipelines/geological-pipeline.md) §7.5）。

再改世界种子。`init` 给每个世界随机分配了一个种子（`world.yaml` 里的
`seed.seed`），而引擎遵守「相同输入 + 相同种子 = 相同结果」。为了让你得到和本教程
完全一致的地形，把 `world.yaml` 里的种子改成 `42`：

```yaml
seed:
  seed: 42
```

日常创作时不必固定种子——保持随机，换个种子就是另一颗星球。

（地形生成的更多旋钮——网格分辨率、板块数量、构造演化步数——在同目录的
`terrain_config.yaml` 里，本教程保持模板值；完整参数表见
[CLI 参考](cli.md) 的「配置」一节。）

构建地质层（地形管线：球面网格 → 板块 → 构造演化 → 地形合成 → 河流 → 冰盖 →
导出，约 3–4 分钟）：

```bash
uv run dreamulator build myworld --only geological
```

验证：

```bash
uv run dreamulator terrain info myworld --planet planet_gaia
```

预期输出（关键几行）：

```
Terrain Data: myworld / planet_gaia
  Seed: 42
  Nodes: 200,000
  Plates: 22
  Elevation: [-11575, 6206] m
  ...
  Emergent land:       185,542,461 km2 (36.4%)
```

陆地占比 36.4%，正是我们设定的 1 − 0.65 该有的样子；板块数 22 是
50 步构造演化（裂解）后的实际数量，多于初始请求的 20。

**如果出错**：改了 input 之后重跑同一层需要加 `--force`
（`build myworld --only geological --force`）——引擎默认跳过已有输出的层。

## 5. 构建气候

```bash
uv run dreamulator build myworld --only climate
```

这一步约 9 分钟：引擎计算温度场、风场、水汽输送、降水，最后做气候分类
（[气候管线](../design/pipelines/climate-pipeline.md)）。

验证：

```bash
uv run dreamulator climate info myworld
```

预期输出：

```
             Climate Summary
┌─────────────────────┬───────────────────┐
│ Metric              │ Value             │
├─────────────────────┼───────────────────┤
│ Mean Temperature    │ 17.2 C            │
│ Temperature Range   │ -19 to 28 C       │
│ Mean Precipitation  │ 933 mm/yr         │
│ Precipitation Range │ 58 to 4850 mm/yr  │
│ Koppen Classes      │ 29 types          │
└─────────────────────┴───────────────────┘
```

均温 17.2 °C、29 种气候类型——0.75 AU 的补偿轨道让这颗行星保持了和地球相近的
能量收支，而 37° 的轴倾角会给它带来比地球更剧烈的季节。

## 6. 在浏览器里看你的世界

```bash
uv run dreamulator serve --open
```

浏览器自动打开 `http://localhost:8000`。进入 **myworld** → 选择行星 **Gaia**，
可以切换到 2D 地图查看器（等距圆柱 / Mollweide / Robinson 投影，可叠加地形、
气候分类、温度、降水等图层）或 3D 球体视图。按 Ctrl+C 停止服务。

**如果出错**：页面空白时先确认第 1 步执行过 `npm run build`——`serve` 提供的是
前端构建产物；端口 8000 被占用时用 `--port` 换端口。

## 7. 导出图像

无需打开浏览器，直接把地图图层导出成 PNG（配色与前端完全同源）：

```bash
uv run dreamulator export layers myworld --layers terrain,koppen --output export/
```

预期输出：

```
        Exported layers — myworld/planet_gaia
┌─────────┬─────────────────────────┬────────────────┐
│ Layer   │ File                    │ Size           │
├─────────┼─────────────────────────┼────────────────┤
│ terrain │ export/terrain.png      │ 2138 KB · 0.9s │
│ koppen  │ export/koppen.png       │ 379 KB · 0.6s  │
└─────────┴─────────────────────────┴────────────────┘
```

可用图层与选项（降水、温度、双网格差值等）见 [CLI 参考](cli.md) 的「地图图层
导出」一节。

## 8. 下一步

至此你走通了「设定 → 推演 → 查看 → 出图」的完整链路。可以从这些方向继续：

- **分支与假设实验**：`dreamulator branch create myworld hot-house --at climate`
  在气候层分叉，探索「如果温室效应更强会怎样」，不影响主线
  （[CLI 参考](cli.md) 分支节）。
- **精细地形与高清渲染**：区域裁剪 + 外部渲染器出影视级图像，见
  [CLI 参考](cli.md)「区域数据包」一节与
  [Blender 渲染管线设计](../design/proposals/blender-render-pipeline.md)。
- **地图迭代与地理锚定**：手绘大陆形状引导地形生成，见
  [地图工作流](map-workflow.md)。
- **AI 叙述**：`uv run dreamulator narrate myworld` 让世界自己开口
  （需要 Anthropic API key）。
- **对照真实地球**：用观测数据校验气候引擎的精度，见
  [气候验证工作流](climate-validation-workflow.md)。
