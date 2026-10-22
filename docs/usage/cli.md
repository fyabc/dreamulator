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

`--climate-source gcm` 建立固定气候分支：分支必须在 climate 层分叉，气候层直接使用一次
ExoPlaSim GCM 运行的结果，`build` 只导入预先算好的逐格字段，不做模拟。建法和校验规则见
[exoplasim-gcm.md](exoplasim-gcm.md) §9。

```bash
dreamulator branch create nacrea gcm-t42-712 --at climate --climate-source gcm
```

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
dreamulator build nacrea --data-dir data/worlds
```

按 DAG 拓扑序执行所有引擎：`astronomy → geological → climate`。每层输出保存到对应的 `layers/<layer>/derived/` 目录。

### 按层构建

```bash
dreamulator build nacrea --only geological   # 只跑地质层（地形生成）
dreamulator build nacrea --only climate      # 只跑气候层
dreamulator build nacrea --layer climate     # 从气候层开始（跳过已完成的层）
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

### 解码 UCC 简码

```bash
dreamulator ucc decode "Dp-Slgmo-H" "Ct-Smo" "An"   # 多码同查，表格输出
dreamulator ucc decode "Dt-H" --json                 # 机器可读（脚本/校验用）
```

解析 v2 区域语法简码为完整分类（热量带·供需·修饰语·形态·相位），并校验
语法——非法码给出原因并以退出码 1 结束。语法与字母表见
`docs/ucc/specification.md` §5.4。

### 查看气候状态

```bash
dreamulator climate info nacrea --data-dir data/worlds
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

## 数据包（data）

`data fetch` 从**版本化开发数据包**下载并安装某个世界的「基础地形」（被 git 忽略、导入自真实数据的
高程 + 板块 + 水陆分类），是新机器从干净 checkout 构建 `earth`（或其分支）的首选入口。

```bash
# 首选路径：一次下载基础地形，之后直接构建
dreamulator data fetch earth --branch climate-dev --data-dir data/worlds
dreamulator build earth --branch climate-dev --only climate

# 从本地包安装（网络受限 / 断网时）
dreamulator data fetch earth --branch climate-dev --from /path/to/earth-terrain-base-*.tar.gz
```

行为：

- 按世界/分支的 `terrain_import` 配方（分辨率 / mesh 节点数 / seed）计算**兼容性指纹**，在
  `data/dev-data/index.json`（git 提交的固定索引）里查匹配包；找不到就明确报错并给出原始导入恢复命令。
- 下载后校验包 SHA-256 与 manifest 内逐文件 SHA-256，拒绝越界路径 / 链接，先在临时目录解包再原子安装，
  只写 `maps/<planet>/` 下的四个基础地形文件（不覆盖 YAML 源配置）。
- 本地已有**不同参数**的基础地形时明确拒绝（不静默替换）；重复 fetch 幂等。

`build` 在缺少已导入地形时，若索引确有匹配包，会提示 `data fetch` 命令（否则给原始导入命令）。
没有 `data fetch` 的机器仍可用 `climate import-elevation` 走真实数据导入（见上一节「导入真实高程」）。

---

## AI 叙述

```bash
dreamulator narrate earth                  # 生成世界描述
dreamulator narrate earth --branch pangea  # 分支描述
```

需要 Anthropic API key。OpenAI 兼容接口通过 `ANTHROPIC_BASE_URL` 环境变量指定。

---

## 守护轴（guard）

守护轴（Harness）是校验 / 审计 / 设定维护的**第三条轨道**（总纲见 `docs/design/proposals/harness.md`）。
`guard` 命令组做两件事：**过期检测**（`check`）与**决策记录（ADR）台账管理**
（`accept` / `supersede` / `deprecate`）。

### 过期检测

```bash
dreamulator guard check nacrea [--branch <b>] [--data-dir <dir>]
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
dreamulator guard accept nacrea 0001              # proposed → accepted（写 checked_against + 基线）
dreamulator guard supersede nacrea 0001 --by 0002 # 标记被 0002 取代（正文不动）
dreamulator guard deprecate nacrea 0001           # 弃用（前提失效但历史保留）
dreamulator guard archive nacrea --limit 20       # 归档最旧的 accepted，直至 ≤ 上限
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

## 导出（export）

`export` 按「成品动作」组织，共六个命令：

| 命令 | 用途 |
|---|---|
| `export layers` | 地图图层烘焙为 PNG（前端同色，守护轴取证） |
| `export region` | 建区域数据包（Gaea/Blender 链的 `input/`） |
| `export build` | 区域包的高清地形：`--method td`（terrain-diffusion）/ `spl`（程序化侵蚀） |
| `export render` | 区域包出图：`--style satellite`（卫星真彩）或制图 `survey/relief/biome/hand/medieval/all` |
| `export globe` | 太空俯瞰镜头：地表/云纹理 + 双层云 + 大气 + 圆盘静帧（`clouds` 为历史别名） |
| `export canvas` | 全球画布链：外存水文 + 裁窗，产出可直接 `export render` 的窗口包 |

headless 烘焙地图图层为彩色 PNG，颜色与前端渲染逐字节一致（配色单源 `palettes.json`，
前后端共读）。支撑 `/read-map` skill、`ai civ`、CI 审计——守护轴的取证腿。

```bash
dreamulator export layers nacrea                                # 全部 5 层，分辨率取 map.yaml
dreamulator export layers nacrea --layers terrain,koppen        # 指定图层（逗号分隔）
dreamulator export layers nacrea --grid 4096x2048               # 指定输出分辨率 WxH
dreamulator export layers nacrea -l terrain --graticule 30      # 叠加经纬网（每 30°，带标注；默认不叠加，与前端逐字节一致）
dreamulator export layers nacrea --output out/ --data-dir data/worlds
dreamulator export layers nacrea -l temperature,precipitation,pressure    # 气候图层
dreamulator export layers nacrea -l koppen,temperature --mesh <其他网格>    # 渲染另一份网格（如 GCM 投影）
dreamulator export layers nacrea -l temperature_diff,koppen_agreement \
    --mesh <网格A> --compare-mesh <网格B>                                  # 差值图层：A − B
```

| 图层 | 类型 | 字段 | 说明 |
|------|------|------|------|
| `terrain` | 自适应高程色带 | `elevation` | NOAA ETOPO1 海洋 + ESRI 陆地，水深加深 |
| `koppen` | 分类（Beck 2018） | `koppen_class` | 海洋回退 `Ocean` |
| `biome` | 分类（Whittaker） | `biome` | 未匹配处透明 |
| `agriculture` | 0–100 连续 | `agriculture_score` | 仅陆地 |
| `habitability` | 0–100 连续 | `habitability_score` | 仅陆地 |
| `plate_motion` | 板块速度 | 欧拉极 | 需要 `plates.json` |
| `temperature` | −40…+40 °C 连续 | `temperature_C` | 仅陆地，与前端温度图层同色标同区间 |
| `precipitation` | 对数连续 | `precipitation_mm` | 仅陆地，log10(P+1)/log10(30001)，与前端一致 |
| `pressure` | ±5 hPa 发散 | `pressure_anomaly_annual_hpa` | 陆地与海洋；`slp_reduction_unreliable` 的格点透明 |
| `temperature_diff` | ±20 K 发散 | `temperature_C` 之差 | 需要 `--compare-mesh`；仅陆地，区间同前端误差图层 |
| `precipitation_diff` | ±2000 mm/年 发散 | `precipitation_mm` 之差 | 需要 `--compare-mesh`；仅陆地 |
| `koppen_agreement` | 三类 | `koppen_class` | 需要 `--compare-mesh`；绿＝同一类，黄＝同一大组，红＝不同大组 |

`--mesh` 渲染指定的网格文件而不是世界的构建产物，地图元数据（分辨率、海平面）仍取自世界；
`--compare-mesh` 指定差值图层的参照网格，两者必须是同一套格点。

输出为 RGBA PNG（未着色处透明），文件名 `<layer>.png`。

### 区域数据包（export region）

裁剪一个以千米为边长的正方形区域，产出外部渲染器（Gaea / Blender 链）直接消费的数据包：

```bash
dreamulator export region nacrea --lat 0 --lon 0 --span-km 2350
# → data/worlds/nacrea/packs/nacrea-0_0_2350km/input/{height.meters.npy, height.png, height.gaea.png,
#    color.png, precipitation.mm.*, temperature.C.*, ice.m.*, npp.gc_m2_yr.*,
#    headwaters.png, koppen.*, biome.*, meta.json}
# pack 根目录布局：input/（引擎通道）+ gaea-out/（Gaea 产物）+ color/（着色产物）
dreamulator export region nacrea --lat 30 --lon -40 --span-km 1200 --output data/worlds/nacrea/packs/my-shot
dreamulator export region nacrea --no-climate   # 只出高度 + 配色（旧行为）
dreamulator export region nacrea --seafloor-clamp -800   # height.gaea.png 的海底压平深度
dreamulator export region nacrea --out-res 4096   # 数据包栅格分辨率（默认 2048，正方形）
```

数据包的栅格分辨率与引擎导出网格解耦：标量通道（高程/降水/温度/冰厚）在 cell
中心的 Delaunay 三角网上 Clough-Tocher C1 插值（cell 中心保真，消除 Voronoi 平台与折痕），类别通道
最近邻，所有通道共用同一正方形输出网格。

高度主通道是 float32 米值的 `.npy`（精确无编码损失）；配色 PNG 与前端同一调色板单源；
`meta.json` 记录物理范围、千米/像素与源 mesh 指纹。pack v4 起区域窗口是局部方位等距
投影（`meta.json` 的 `projection` 字段；与全球画布链共用 `map/td_canvas.py` 的换算单源）：
窗口在任意纬度都是真实千米正方形，极区中心与跨 ±180° 经线的窗口都可直接导出，
只有 span 触及对跖点（πR）才会被拒绝。

`height.gaea.png` 是 Gaea 2 专用的高程变体：海底按 `--seafloor-clamp`（默认 −400 m）
预压平后按新量程归一（记录在 meta 的 `height_gaea_png_range_m`），因为 Gaea 2.3 的
Terrain Definition 有 Height ≤ 10 km、Width ≤ 2400 km 上限，深海沟不压平就装不下。
喂给 Gaea 时区域 span 建议 ≤ 2350 km；操作配方见
[gaea-video-chain.md](gaea-video-chain.md)。

### 画布裁窗（export canvas）

高分画布链：一张全球画布（S1，90 m int16 分块 + 粗格气候）→ 外存水文（S2）→
裁出区域窗口（S3）。窗口包与 `export region` 的 `input/ + refined-out/` 词汇相同，
可直接交给 `export render` 出图：

```bash
dreamulator export canvas <canvas_dir> --lat 15 --lon -100 --span-km 550   # 缺省：水文 + 裁窗
dreamulator export canvas <canvas_dir> --stage hydrology                   # 只跑水文（调试）
dreamulator export canvas <canvas_dir> --lat 15 --lon -100 --span-km 550 --stage window
dreamulator export render <窗口包> --style all                             # topo + relief + biome
```

水文结果缓存在 `<canvas>/hydro-work/`（每个分块校验和，支持断点续算；`--force` 重跑）。
河网起始阈值 `--threshold-cells` 默认 27000，对应区域链校准的约 2.1 m³/s 平均流量
（90 m 像素）；需要更密的小溪网时可调低。水文算法与输出契约见
[画布链技术参考](../design/pipelines/canvas-hydrology.md)。

### 卫星真彩合成（export render --style satellite）

视频素材链第 ③ 步：读取区域数据包 + Gaea 构建产物，合成卫星真彩色贴图：

```bash
uv sync --extra media        # 首次需要（OpenEXR）
dreamulator export render data/worlds/nacrea/packs/nacrea-15_90_2350km --style satellite
# 默认读 <pack>/gaea-out/，写 <pack>/color/{albedo.png, preview.png}
# --gaea / --output 可覆盖；--no-texture 关闭植被纹理（默认开）
```

基色由引擎群系驱动（气候权威），Gaea 掩膜只做质感调制；`albedo.png` 供
Blender 当贴图（不烘焙光照），`preview.png` 叠软 hillshade 供肉眼快检。
植被纹理 pass 按群系参数化 fBm 斑驳（森林细密 / 荒漠宽场 / 冰原微起伏，
参数在 `TEXTURE_PARAMS`）。色表与调制权重在
`src/dreamulator/media/satellite_color.py` 顶部常量。

默认附带同分辨率气候通道（卫星影像契约，`--no-climate` 关闭）：年降水量
`precipitation.mm`（float32 `.npy` 为主，16-bit PNG 按区域最大值归一，供 Gaea 2 作
降雨 mask）、年均温 `temperature.C`、冰川厚度 `ice.m`（无冰格为 0，雪线 mask 由下游
从冰厚与温度导出）、NPP `npp.gc_m2_yr`（着色器的连续植被密度通道）、河源掩膜
`headwaters.png`（陆地且 P > Hamon PET，接 Gaea Rivers 的 Headwaters 输入）、
Köppen 与群系各一份 uint8 类别码 `.npy` 加调色板配色 PNG。
类别码在全网格上按类名字典序分配，同一世界不同区域的同类同码；`meta.json` 的
`climate.*.legend` 只列本窗口出现的类，`missing` 字段给出缺值像素数。所有通道与高度
共用同一次全网格索引切片的像素盒，套准由构造保证。设计文档见
[design/proposals/blender-render-pipeline.md](../design/proposals/blender-render-pipeline.md)。

### 程序化侵蚀（export build --method spl）

视频链第②步的程序化变体（一条命令替代 Gaea 手动构建）：

```bash
dreamulator export build data/worlds/nacrea/packs/nacrea-15_-100_2350km --method spl
# 写 <pack>/prog-out/（gaea-out 文件词汇，渲染腿 --gaea 指向它即可）
# --steps 30 / --dt 5e4 / --k 2e-7 / --river-threshold 3000（默认即定版）
```

Priority-Flood 排水（Barnes 2014）+ 隐式流水功率侵蚀（Braun & Willett
2013），吃 pack 的降水场。参数语义见 [usage/terrain-chain.md](terrain-chain.md) 与
[knowledge/cartography/](../knowledge/cartography/README.md)。

### terrain-diffusion 细化 + 水文（export build）

地形链第②步的主方法（引擎粗条件场 → 90 m 地貌重生成 → 排水/河网/湖）：

```bash
dreamulator export build data/worlds/nacrea/packs/nacrea-15_-100_550km     --td <terrain-diffusion-repo>
# 写 <pack>/refined-out/；推理在外部 td venv（安装见 terrain-chain 手册）
```

550 km 约 2.5 分钟。模型机制与能力边界见
[usage/terrain-chain.md](terrain-chain.md) 第②步。

### 制图（export render --style survey|relief|biome|hand|medieval）

视频素材链的制图变体腿（共用 ①pack → ②构建目录的产物），所有风格走一个
命令（`--style`）：

```bash
dreamulator export render <pack> --style survey                # 分层设色测绘图 topo.png（默认）
dreamulator export render <pack> --style relief                # 遥感自然色晕渲 relief.png
dreamulator export render <pack> --style biome                 # 群系图 biome.png
dreamulator export render <pack> --style all                   # 一键出 topo + relief + biome 三张
dreamulator export render <pack> --style hand                  # 旧印刷质感 topo.hand.png
dreamulator export render <pack> --style medieval --title "珠母星 · 未知海域"
# 读 <pack>/input + <pack>/gaea-out（或 --gaea 指向 refined-out/prog-out）
# survey → carto/{topo.svg, topo.png}；relief → carto/{relief.svg, relief.png}；
# biome → carto/{biome.svg, biome.png}；hand → carto/topo.hand.png；medieval → carto/medieval.png
# --title 自定义标题（默认「Nacrea —— 15°N 100°W 附近」式）
# --res 网格分辨率（默认 2048） / --dpi PNG 输出 DPI
# --contour-labels 等高线 inline 高程标注（默认关，仅 survey/hand）
```

survey = 分层设色（前端 terrain 同源色阶）+ hillshade + 两级等高线 +
自适应经纬网 + 海部平色 + 河流 + 高程色阶图例/比例尺/指北针。
hand = survey 叠印刷伪影（水彩晕/套色偏移/墨线重描/楷体/磨白）。
medieval = 羊皮纸插画（山峰/树群符号、粗河流、绶带标题、罗盘玫瑰，
无图例无等高线；画风迭代中，暂搁置）。
biome = 分类群系图（whittaker 色表平色填充 + 类界发线 + 海洋留白 +
群系图例；不需要构建产物，无 --gaea 时自动回退
refined-out → gaea-out → input/）。操作细节见
[usage/gaea-video-chain.md](gaea-video-chain.md) 第③'步；色表与等高距
在 `src/dreamulator/media/carto_render.py` 顶部常量。

### 太空俯瞰镜头（export globe；旧名 export clouds）

这条链从已构建的世界地图生成三类产物，全部以同一份 `export globe` 输出目录为输入：

1. **全球纹理与圆盘静帧**：`dreamulator export globe`（`clouds` 是历史别名，命令行为完全相同）；
2. **全球旋转视频**：`scripts/media/spin_video.py`；
3. **云系演化视频**：`scripts/media/cloud_flow_video.py`（L4 原型）。

前置条件：世界已构建（`dreamulator build <world> [--branch ...]`）；媒体/噪声依赖随项目环境安装；视频编码需要 ffmpeg，脚本会自动调用 `imageio-ffmpeg`，按下面的方式运行即可。

#### 1. 纹理与静帧：export globe

```bash
dreamulator export globe nacrea --branch gcm-t42-712 --grid 8192x4096 --globe-res 1600 --cyclones
```

`export globe` 的完整参数（`clouds` 为别名）：

| 选项 | 默认 | 说明 |
|---|---|---|
| `WORLD` | — | 世界名（位置参数） |
| `--planet, -p` | 自动 | 行星/卫星 ID；默认取第一张地图 |
| `--branch, -b` | root | 读取的分支 |
| `--config` | 无 | YAML 配置文件；显式命令行参数覆盖文件 |
| `--grid, -g` | `8192x4096` | 等距圆柱纹理分辨率 `WxH`；16K×8K 内存开销较大 |
| `--seed` | 7 | 噪声种子；同场 + 同 seed = 逐位相同 |
| `--output, -o` | `<export-dir>/globe/<world>[-<branch>]/` | 输出目录 |
| `--globe-res` | 1600 | 正交圆盘预览分辨率（方形） |
| `--center-lon/--center-lat` | 90/15 | 视图中心经纬度 |
| `--sun-lon/--sun-lat` | 中心−25°/20° | 次太阳点 |
| `--cover-scale` | 1.0 | 云量倍率；0 = 跳过纹理合成，只出地表与无云圆盘 |
| `--cyclones` | 关 | 叠加 L3 气旋模板（合成占位轨迹） |
| `--cyclone-seed` | 31 | 合成轨迹种子 |
| `--atmosphere/--no-atmosphere` | 开 | L5 物理大气壳；关闭退回旧版边缘光晕预览 |
| `--data-dir` | 环境默认 | 覆盖世界数据目录 |

输出文件：

| 文件 | 内容 |
|---|---|
| `surface.png` | 等距圆柱地表底图（sRGB） |
| `clouds.png` | 合并云不透明度（RGBA straight alpha，兼容旧调用） |
| `clouds_low.png` | 低/中云壳 + 薄霾（4 km 层） |
| `clouds_cirrus.png` | 高壳卷云（9 km 层，带对比曲线） |
| `cloud_cover.png` | 大尺度云量场（占位） |
| `cyclone_template.png` / `cyclone_envelope.png` | L3 模板与包络（仅 `--cyclones`） |
| `globe.png` | 正交圆盘静帧（地表 + 双层云 + 大气 + 高光） |
| `meta.json` | 网格、种子、机位、气旋轨迹、大气参数、食影参数与 provenance |

#### 2. YAML 配置

推荐把一次镜头用 YAML 固定下来；命令行显式参数会覆盖文件。完整字段：

```yaml
grid: 8192x4096
seed: 7
globe_res: 1600
center_lon: 60
center_lat: 15
sun_lon: 45
sun_lat: 15
cover_scale: 1.0
cyclones:
  enabled: true
  seed: 31
  tropical_per_hemisphere: 1
  extratropical_per_hemisphere: 2
  tropical_scale: 1.0
  extratropical_scale: 1.0
  tracks:                     # 可选：显式轨迹表，覆盖合成占位轨迹
    - lat_deg: 5
      lon_deg: -5
      kind: tropical          # tropical | extratropical
      central_pressure_hpa: 950
      rmax_km: 180
      outer_radius_km: 2600
      motion_east_m_s: 6
      shape_seed: 201
atmosphere:
  enabled: true
  cloud_altitude_km: 4.0      # 低/中云壳；L1 云顶高度到达后替换
  cirrus_altitude_km: 9.0     # 高壳卷云（必须高于低云壳）
  cirrus_shadow_strength: 0.6 # 高壳卷云对低云/地表的投影强度
  exposure: white_balance     # white_balance | physical
  cloud_shadows: true
  sun_glint: true
  water_roughness: 0.08
  multiple_scattering: true
  mie_scale: 1.0
  ozone_scale: 1.0
  # star_temperature_k: 4365  # 覆盖世界输入（QA）
  # surface_pressure_atm: 1.0
eclipse:                      # 卫星食影子（通用接口；天文层提供几何）
  enabled: false
  center_lon_deg: 50
  center_lat_deg: 10
  umbra_radius_deg: 90        # Aegis 的本影覆盖整个可见半球（见第 5 节）
  penumbra_radius_deg: 90
  depth: 0.9
```

#### 3. 全球旋转视频

相机与恒星固定、晨昏线不动；地表与云纹理旋转一整圈，末尾定格。大气只预计算一次，每帧只重采样纹理，720p 240 帧约数分钟。

```bash
uv run --with imageio-ffmpeg python scripts/media/spin_video.py <globe_dir> -o exports/spin/nacrea_spin_720p.mp4 --res 720 --seconds 8 --fps 30
```

| 选项 | 默认 | 说明 |
|---|---|---|
| `<globe_dir>` | — | `export globe` 的输出目录（含 `surface.png`、`clouds_low.png`/`clouds_cirrus.png`、`meta.json`） |
| `--res` | 720 | 方形球面渲染分辨率 |
| `--seconds` / `--fps` | 8 / 30 | 片长与帧率 |
| `--rotation-seconds` | `seconds − 1` | 转一整圈的时间；剩余时间定格 |
| `--width` / `--height` | 1280 / 720 | 输出画幅；方形球面居中，两侧留黑 |
| `--crf` | 18 | H.264 质量（越小越好） |
| `--no-ocean` | 关 | 跳过海洋掩膜与太阳高光 |
| `--poster` | 无 | 额外保存首末帧 PNG |

云系随行星刚性旋转，不做时间演化；两层云壳都会读取。

#### 4. 云系演化视频（L4 原型）

同一份输出目录，把低云与卷云沿年均风场做半拉格朗日平流（BFECC 抑制扩散），固定机位、晨昏线不动；热带气旋叠加 Holland 涡旋，温带逗号默认只随环境风/锋面切变。

```bash
uv run --with imageio-ffmpeg python scripts/media/cloud_flow_video.py <globe_dir> -o exports/spin/nacrea_cloudflow_720p.mp4 --res 720 --seconds 8 --fps 30 --sim-hours 24 --texture-width 2048
```

| 选项 | 默认 | 说明 |
|---|---|---|
| `<globe_dir>` | — | 同旋转视频 |
| `--res` / `--seconds` / `--fps` | 720 / 8 / 30 | 渲染分辨率、片长、帧率 |
| `--sim-hours` | 24 | 模拟的云演化时长；与片长解耦 |
| `--texture-width` | 2048 | 平流网格宽度（高度 = 宽度/2） |
| `--substeps` | 自动 | 每帧子步数（按位移自动，封顶 8） |
| `--no-bfecc` | 关 | 关闭前后误差补偿（更糊，作对照） |
| `--no-vortex` | 关 | 只用环境风，不叠加风暴 Holland 涡旋 |
| `--crf` / `--no-ocean` / `--poster` | 18 / 关 / 无 | 同旋转视频 |

风场暂用年均值占位，等 L1 的 6 小时风场到达后替换；只输运现有纹理，不做凝结/蒸发。更长时段会累积插值扩散，需更强的低扩散格式或 L1 帧间插值。

#### 5. 卫星食影子

`eclipse` 块是渲染侧的通用接口：天文层算好次食点、本影/半影角半径与最大暗化，渲染器在表面与云壳的直接日光上乘一个平滑圆形剖面；大气入射散射按地表次点做同样的局部衰减。`umbra_radius_deg = 0` 表示环形/偏食（掩食体小于恒星），只留下半影式变暗。

Aegis 掩食 Nacrea 的实算（Nacrea 半径 6817 km、轨道 723,300 km、Aegis 半径 71,355 km、Ignis 4365 K）：

- Aegis 角半径 5.66°，恒星角半径 0.447°（角半径比 12.65）；本影锥长 `L = R_Aegis·d★/(R★ − R_Aegis)` ≈ 10.98M km，在 Nacrea 轨道处收束到约 66,653 km（9.78 个 Nacrea 半径），半影约 77,948 km（11.43 个半径）；
- 中心食时本影半径大于行星半径，食界不落在行星表面上，整个可见半球都在本影内；接口中取本影与半影角半径 90° 表示全覆盖（角半径在 90° 处饱和），画面是**全球均匀变暗**，不是一个小圆斑；
- 偏食时阴影不是以次食点为中心的圆斑，而是沿掩食轴的带。设掩食轴偏离行星中心 $b$，表面上法线为 $\mathbf{n}$ 的点到轴的距离为 $\rho^2 = R_p^2 + b^2 - 2bR_p(\mathbf{n}\cdot\mathbf{u}) - R_p^2(\mathbf{n}\cdot\mathbf{s})^2$，其中 $\mathbf{s}$ 是次食点方向、$\mathbf{u}$ 是轴的偏移方向；局部遮蔽率是恒星盘（角半径 0.447°）与 Aegis 盘（5.66°）在角距 $\delta=\arctan(\rho/d)$ 下的重叠面积。最靠近轴的点落在晨昏线上（与次食点相差 90°），所以影子从晨昏线一侧进入昼半球。当前 `EclipseShadow` 的圆形剖面是中心食与局部近似接口，真实偏食需要按上式逐点计算；
- 小卫星（Cadence/Vigil）角半径约 0.07°/0.02°，小于恒星，只有环形/偏食，对应 `umbra_radius_deg: 0` 的半影式变暗。

限制：大气入射散射按地表次点做局部衰减，不是三维遮蔽输运；阴影为圆形且静态，真实椭圆/移动食影需天文层逐帧提供参数。

#### 6. 复现与分辨率

同场 + 同 seed 逐位相同；`meta.json` 记录全部参数。16K×8K 纹理内存开销大，预览以 8K×4K/1600² 为主；需要 4K 全圆盘时按镜头加细。区域数据包的 Blender 静帧是另一条链，见 `export render` 与地形链手册。

---

## 种子探索（explore-seeds）

批量生成多个 seed 的地形，对比关键指标 + 缩略图，落盘种子目录。回应技术债 #16
（Cortial-2019 对 seed 高度敏感：不同 seed 产出完全不同的星球，需工具链辅助选种子）。

```bash
dreamulator explore-seeds nacrea --seeds 42,123,456         # 指定 seed
dreamulator explore-seeds nacrea --count 10 --nodes 50000   # 随机 10 个 seed，5 万节点
dreamulator explore-seeds nacrea --raw                      # 纯 seed（跳过 geography 锚定）
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

**关键配置项**（小节 `planet:` / `terrain:` / `plates:` / `noise:` / `climate:` / `export:`
与扁平顶层键都支持，加载时自动展平；真实完整示例见
`data/worlds/nacrea/layers/geological/input/terrain_config.yaml`）：

```yaml
terrain:
  num_nodes: 100000         # CVT 分辨率（默认 10 万 cell；现行标准 20 万，如 nacrea）
  lloyd_iterations: 8       # Lloyd 松弛迭代
  hotspot_count: 3          # 热点链数量（默认 3；nacrea 覆写 9）
  mountain_asymmetry: 0.4   # 山脉不对称度（0=对称， 1=强不对称）
  shelf_width_km: 150.0     # 大陆架宽度
  target_land_fraction: 0.29  # 陆地占比目标；缺省从 planets.yaml 的
                              # hydrosphere.water_coverage 推导（1 − 水覆盖率），
                              # 显式值与之偏差 >20% 时保留并告警
  terrain_algorithm: cortial2019_asymmetric  # 地形合成策略

plates:
  num_plates: 20            # 板块数量
  continental_fraction_min: 0.38   # 大陆地壳配额下限；地壳面积必须大于出露陆地
  continental_fraction_max: 0.48   # 目标（1 − 水覆盖率），否则海平面压到克拉通
                                   # 基座之下、洋中脊出露成陆（引擎会告警）
  crust_noise_freq_scale: 4.0  # 地壳分配噪声频率倍率；默认 1.0 海岸线会呈
                               # 大圆式长直线段（逐板块得分场过低频所致）
  plate_algorithm: cortial2019
  tectonic_algorithm: cortial2019   # 默认启用时间演化；"" = 静态板块
  tectonic_steps: 0         # 演化步数（0 = 跳过演化；nacrea 覆写 50）
  tectonic_dt_my: 0.0       # 步长 Myr（0 = 自动缩放）

noise:
  noise_anisotropy: 0.3     # 各向异性噪声
```

**算法选择**（策略模式）：

| 配置项 | 可选值 |
|--------|--------|
| `plate_algorithm` | `cortial2019` |
| `terrain_algorithm` | `cortial2019_gaussian`, `cortial2019_asymmetric` |
| `tectonic_algorithm` | `cortial2019`（默认，时间演化）, `""`（静态板块） |

---

## 目录结构

```
data/worlds/<name>/
├── world.yaml                    # 世界元数据
├── maps/<planet>/                # 地图产物（构建输出，已 gitignore）
│   ├── elevation.png             # 高度图
│   ├── cvt_mesh.json             # CVT 网格
│   ├── plates.json               # 板块数据
│   ├── temperature.png           # 气候图层（+ precipitation.png / koppen.json …）
│   └── climate_monthly.msgpack   # 月度气候场
├── layers/
│   ├── astronomy/input/          # 恒星系参数
│   ├── geological/input/         # 行星参数 + terrain_config.yaml + geography.yaml
│   └── civilization/input/       # 文明设定
└── branches/<name>/
    ├── branch.yaml               # 分支元数据
    ├── layers/                   # 仅分叉层及之后
    └── maps/<planet>/            # 分支自己的地图产物（存在时优先于父世界）
```

分支地图解析顺序（`map/manager.py`）：分支 `maps/<planet>/` → 父世界 `maps/<planet>/`
→ 旧版层级路径回退（`layers/*/derived|input/maps/`，仅为兼容保留）。
