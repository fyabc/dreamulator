/**
 * Single source of truth for map help content.
 *
 * Layer descriptions, control shortcuts, and concept explanations
 * are defined here and imported by both the UI layer panel (for
 * tooltips/labels) and the HelpPage/HelpPanel (for full reference).
 *
 * When adding a new layer or feature, update this file — the UI
 * and help docs stay in sync automatically.
 */

import type { ColorMode } from '../../viewers/map/TerrainPlane'

// ---------------------------------------------------------------------------
// Layers
// ---------------------------------------------------------------------------

/**
 * Layer taxonomy — mirrors the slot-based compositing model (§3.1):
 *
 *   Slot 1  base      底图     exactly 1 active (radio), opaque canvas
 *   Slot 2  thematic  专题着色   0 or 1 active (radio), alpha-blended over base
 *   Slot 3  fill      分类填充   0..N (stackable), semi-transparent cell-fill
 *   Slot 4  feature   特征标注   0..N (stackable), always on top
 *
 * Groups below are UI organisation only.  Azgaar, Paradox, and Gleba all follow
 * the same pattern: ONE "map mode" (our thematic slot) active at a time, plus
 * optional overlays.
 */
export type LayerKind = 'base' | 'thematic' | 'fill' | 'feature'

/** UI layer groups (organisation only — not compositing order). */
export const LAYER_GROUPS: { id: string; label: string }[] = [
  { id: 'thematic', label: '地图模式' },
  { id: 'geology', label: '地质构造' },
  { id: 'overlay', label: '叠加标注' },
]

export interface LayerHelpEntry {
  id: ColorMode
  label: string
  desc: string         // one-liner for tooltip / slider
  detail: string       // full description for help panel
  defaultOpacity: number
  kind: LayerKind
  /** Group id from LAYER_GROUPS. */
  group: string
}

export const LAYER_HELP: LayerHelpEntry[] = [
  {
    id: 'terrain',
    label: '地形',
    desc: '自适应海拔着色（默认专题图层）',
    detail: '基于 hypsometric tint 的自适应海拔着色。深海蓝 → 浅海青 → 低地绿 → 高地棕 → 雪山白。与其他专题层互斥。默认开启。',
    defaultOpacity: 1,
    kind: 'thematic',
    group: 'thematic',
  },
  {
    id: 'landsea',
    label: '海陆',
    desc: '二值海陆着色（蓝色=海洋，绿色=陆地）',
    detail: '二值蓝／绿着色，快速区分海洋和陆地。与其他专题层互斥。',
    defaultOpacity: 1,
    kind: 'thematic',
    group: 'thematic',
  },
  {
    id: 'plates',
    label: '板块',
    desc: '按构造板块着色',
    detail: '每个构造板块用一种颜色标识。板块由 Cortial (2019) 球面 Voronoi 剖分生成，Poisson-disc 种子 + 同步 BFS。颜色从 15 色调色板循环分配。可叠加在任意底图/专题层之上。',
    defaultOpacity: 0.8,
    kind: 'fill',
    group: 'geology',
  },
  {
    id: 'boundaries',
    label: '地壳与边界',
    desc: '大陆(褐)·海洋(蓝)·汇聚(红)·离散(绿)·转换(黄)',
    detail: '板块内部按地壳类型着色：大陆 = 暖褐，海洋 = 灰蓝，过渡带 = 橄榄绿。热点火山链 = 品红。古造山带 = 暗金。裂谷 = 青。板块边界按类型着色：汇聚 = 红（俯冲/碰撞），离散 = 绿（洋中脊/裂谷），转换 = 黄（水平错动）。特征线永远置顶。',
    defaultOpacity: 0.8,
    kind: 'feature',
    group: 'geology',
  },
  {
    id: 'koppen',
    label: 'Köppen 气候',
    desc: '气候分类着色（Beck 2018 标准色）',
    detail: '按 Köppen-Geiger 气候分类着色。A=热带(蓝)·B=干旱(红/橙)·C=温带(绿/黄)·D=大陆性(紫/青)·E=极地(灰)·海洋=深蓝。与下方三个生态专题互斥（同一专题槽位，四选一）。',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'thematic',
  },
  {
    id: 'biomes',
    label: 'Whittaker 群系',
    desc: '温度-降水生物群系分类（12 类 + 海洋）',
    detail: '基于 Whittaker (1975) 温度-降水二维分类。热带雨林=深绿·热带草原=浅黄绿·荒漠=米色·温带森林=中绿·温带草原=金黄·北方针叶林=蓝灰·冻原=灰褐·冰原=白·海洋=深蓝。与 Köppen 互斥，四选一。',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'thematic',
  },
  {
    id: 'npp',
    label: '净初级生产力',
    desc: 'NPP 热力图（Miami 模型，暖米→深绿）',
    detail: 'Miami 模型 (Lieth 1975) 估算的净初级生产力。暖米色=低产（荒漠 <200）→ 深绿=高产（雨林 >2000）。归一化到 0–3000 gC/m²/yr。',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'thematic',
  },
  {
    id: 'domesticable',
    label: '文明摇篮',
    desc: '高驯化潜力区域高亮（食草动物/作物/役用）',
    detail: '基于 Whittaker 群系查表标注驯化潜力（Diamond 1997 框架）。金色=高食草动物+高作物·橙色=仅高食草动物·浅绿=仅高作物·透明=低潜力。温带草原为全高。',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'thematic',
  },
  {
    id: 'currents',
    label: '洋流',
    desc: '表层洋流箭头（品红=暖·青绿=寒，SVG矢量）',
    detail: 'Stommel 风生环流模型解算的表面流场。方向=流向、长度∝流速、品红=暖流·青绿=寒流。按 ~8° 网格空间采样，任意缩放清晰。可自由叠加。',
    defaultOpacity: 0.75,
    kind: 'feature',
    group: 'overlay',
  },
  {
    id: 'coastlines',
    label: '海岸线',
    desc: '海岸线轮廓（默认开启）',
    detail: '海平面附近 ±200m 范围的 cell 渲染为浅灰蓝轮廓线。叠加在所有专题层之上，帮助在 NPP/文明摇篮等缺少地形参考的图层中定位海陆边界。默认开启。',
    defaultOpacity: 0.6,
    kind: 'feature',
    group: 'overlay',
  },
]

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

export interface ControlHelpEntry {
  action: string
  description: string
}

export const CONTROL_HELP: ControlHelpEntry[] = [
  { action: '拖拽', description: '平移地图（2D）/ 旋转球体（3D）' },
  { action: '右拖 / Ctrl+拖', description: '平移 3D 球体视图' },
  { action: '滚轮', description: '缩放' },
  { action: 'N 键', description: '3D 球面视图：重置为默认视角（北极在画面上方，正视赤道）。仿《戴森球计划》。' },
  { action: '光照·时刻滑块', description: '调整太阳直射经度（周日变化，0° = 本初子午线正午），即昼夜明暗界线的位置。需先打开光照开关（默认关）。' },
  { action: '光照·季节滑块', description: '调整轨道位置（周年变化，0° = 春分，90° = 北半球夏至）。结合地轴倾角改变太阳直射纬度，使明暗界线随季节倾斜（极地出现极昼/极夜）。无倾角的行星无季节变化。2D 三种投影（等距圆柱 / Mollweide / Robinson）与 3D 球面均支持。' },
  { action: '光照开关', description: '2D/3D 左侧面板：开/关昼夜光照（默认关，不影响常规阅图）。2D 三种投影（等距圆柱 / Mollweide / Robinson）与 3D 均走 GPU、拖动顺滑。设置经 URL（?sun=&season=&night=）在 2D↔3D 间同步、可分享。' },
  { action: '调试·CPU 重投影', description: 'URL 加 ?reproject=cpu 强制 Mollweide/Robinson 走旧的 CPU 重投影，用于与 GPU 结果对照验证。仅调试用途——主地图显示始终依赖 WebGL，这不是无 GPU 兜底。' },
  { action: '悬停 cell', description: '右侧面板显示 cell 属性（坐标、海拔、地壳类型、板块、边界）' },
  { action: '悬停离开', description: '指针移出球面/地图后，右侧面板恢复行星摘要' },
  { action: '双击 cell', description: '选中 cell（Ctrl+双击切换选中状态）' },
  { action: '单击行星', description: '3D 恒星系视图中，弹出信息面板。如有地形数据，可展开"🌍 地形数据"查看摘要。' },
  { action: '双击行星', description: '3D 恒星系视图中，相机飞向该行星' },
]

// ---------------------------------------------------------------------------
// Projections
// ---------------------------------------------------------------------------

export interface ProjectionHelpEntry {
  id: string
  label: string
  description: string
}

export const PROJECTION_HELP: ProjectionHelpEntry[] = [
  { id: 'equirectangular', label: '等距圆柱', description: '经纬线正交，极区拉伸。最简单的投影，适合数据处理。' },
  { id: 'mollweide', label: '摩尔威德', description: '等面积伪圆柱投影，椭圆外形。适合面积对比。' },
  { id: 'robinson', label: '罗宾逊', description: '折中方案，视觉舒适。国家地理等出版物的常用投影。' },
]

// ---------------------------------------------------------------------------
// Core concepts
// ---------------------------------------------------------------------------

export interface ConceptHelpEntry {
  title: string
  summary: string
}

export const CONCEPT_HELP: ConceptHelpEntry[] = [
  {
    title: 'DAG 层级架构',
    summary: '世界数据按学科层级组织：physics → chemistry → astronomy → geological → climate → ecology → civilization。上游层级的输入决定下游层级的输出，形成有向无环图（DAG）推演管线。',
  },
  {
    title: '分支系统',
    summary: '类似 Git branch。在某一 DAG 层分叉，共享上层数据，仅存储分叉层及之后的数据。同一行星的不同分支可以有不同的海陆分布、气候或文明演化。',
  },
  {
    title: 'CVT 球面网格',
    summary: 'Centroidal Voronoi Tessellation — 使用 Fibonacci 螺旋 + Lloyd 松弛生成的球面均匀网格。所有模拟（构造、气候、水文）直接在球面网格上运行，仅在最终可视化时投影为 2D 栅格。',
  },
  {
    title: 'Cortial 2019 板块构造',
    summary: '板块剖分和时间演化遵循 Cortial et al. (2019) Procedural Tectonic Planets 的方法：Poisson-disc 种子 → 球面 Voronoi 剖分 → Euler 极旋转 → 边界重检测 → 俯冲/碰撞/侵蚀。参考文献见 terrain-pipeline.md。',
  },
]
