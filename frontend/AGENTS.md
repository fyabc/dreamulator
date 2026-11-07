# 前端（frontend/）开发规则

本文件是 `frontend/` 目录的作用域规则，补充根目录 `AGENTS.md`。在前端写代码前先读它；Codex 只在从 `frontend/`
或其子目录启动时自动加载本文件，Claude Code 在操作本目录文件时加载同目录的 `CLAUDE.md` 导入。
前端的开发、构建、静态模式与类型检查命令见根目录 `AGENTS.md` 的「TypeScript 前端」一节。

## 3D 球面矢量可视化（风场/洋流箭头）

1. **切空间投影不要用数值差分**。`atan2(v,u)` 在局部切空间是对的，但映射到屏幕
   必须通过相机矩阵。数值偏移 `project(lon+de, lat)` 依赖偏移量选择（不同缩放/视角下
   偏移量对应的屏幕像素数不同，极地附近经度偏移退化），会产生方向跳变。正确做法是让
   `project()` 返回切空间基底在屏幕的像（`ex,ey,nx,ny`），在 `GlobeViewer.tsx` 中
   用 THREE.js `camera.project()` 解析计算，不与缩放耦合。

2. **速度和方向要分离**。洋流速度（~0.002 m/s）和风速（~5 m/s）差 2500 倍。
   直接将 (u,v) 乘以切空间基底 → 洋流矢量趋近零被后续阈值过滤。方向用单位向量、
   长度用速度，两者独立。

## i18n：多语言字符串

项目使用 `react-i18next` 做国际化。配置入口 `src/i18n/index.ts`，locale 文件在 `src/i18n/locales/<lang>/`。

**命名空间**：`common`（通用 UI）、`map`（地图/球面）、`worlds`（世界管理）、`civmap`（文明地图）、`help`（帮助页内容）。

**新增可翻译字符串时**：
1. 选择正确的命名空间 JSON 文件
2. 添加 key（中文值写到 `zh-CN/`，英文写到 `en/`）
3. 在组件中使用 `useTranslation()` hook：`const { t } = useTranslation('map')`
4. 硬编码中文是技术债——新代码一律走 `t()`。

**约定（2026-08 i18n 扫尾后确立）**：
- **自包含命名空间**：每个 namespace 自带它需要的 action/status/label，不跨 ns 复用
  （`worlds.action.create` 与 `common.action.create` 并存是约定，不是重复）。
- **词典表 → i18n key**：Köppen 群系/土纲这类「code → 中文名」的模块级映射表存 i18n
  key（如 `'koppen.Af'`），在使用处 `t(key)` 解析——不能模块级直接 `t()`，否则语言切换不生效。
- **类组件用 `i18n.t()`**（import i18n 单例），函数组件用 `useTranslation`。
- **跨命名空间引用**：用绝对 key `t('help:layer.terrain.label')`（`ns:` 前缀）。
- **扫描命令**：`grep -rnE '[一-龥]' frontend/src --include='*.ts' --include='*.tsx'`
  （注释、语言名、死代码除外）。
- **语言切换器**：Sidebar 页脚（`components/LanguageSwitcher.tsx`），localStorage
  `dreamulator-lang` + 浏览器语言兜底。

**添加新语言**：复制 `zh-CN/` → `<code>/`，翻译 JSON 值（key 结构保持不变），在 `index.ts` 的 `resources` 中注册。

## React StrictMode + Three.js/R3F 纹理上传（2026-08 调试经验）

React StrictMode 开发模式下对函数组件体、state updater、useMemo/useReducer 等双重调用。与 R3F/Three.js 交互时存在以下反模式：

1. **`texture.needsUpdate` 被 StrictMode 消耗**：第一次 mount 时 Three.js 检测到 `needsUpdate=true` → 上传纹理到 GPU → 设 `needsUpdate=false`。StrictMode 卸载 WebGL 上下文后第二次 mount（真正的渲染），纹理对象被缓存复用但 `needsUpdate=false` → 纹理永远不再上传 → 显示 fallback 色。

   **解决**：不依赖 `needsUpdate`。要么确保 GlobeViewer 只在纹理数据完全就绪后才挂载（避免材质切换），要么用 `key` 强制 Canvas 重建 WebGL 上下文。

2. **R3F `<meshStandardMaterial>` 三元切换不可靠**：`{tex ? <M map={tex}/> : <M color/>}` 从 null→Texture 切换时，R3F 卸载旧材料挂载新材料，但纹理的 `needsUpdate` 状态可能已被前次渲染消耗。

3. **`useGPUTerrain` 返回 1px 占位纹理**：该 hook 在真实地形烘焙完成前先返回一个 1px DataTexture。若在此阶段挂载 GlobeViewer，会先渲染黑球（占位纹理），真纹理到达后再切换材料——受 #1 和 #2 影响几乎必定失败。

   **调试方法**：用 `performance.now()` 打时间戳日志追踪异步事件顺序。`[Violation] 'message' handler took Xms` 是 React scheduler 用 `MessageChannel.postMessage` 调度同步 work loop 的标志——这段时间内 KD-tree 构建和纹理烘焙在主线程阻塞执行。

4. **生产模式无 StrictMode** → 本地开发通过不代表生产通过。`npm run build` 后的构建产物不会双重调用。

## React Hooks 规则

React 组件中的 hooks（`useState`、`useEffect`、`useMemo`、`useQuery` 等）**必须在每次渲染中以相同顺序调用**。禁止在 hooks 之间放置条件 `return`：

```tsx
// ❌ 错误：hooks 之间有 early return，导致 hook 调用顺序不一致
if (!data) return null
const computed = useMemo(() => ..., [data])  // 当 data 为 null 时不会被调用

// ✅ 正确：所有 hooks 在 early return 之前调用
const computed = useMemo(() => ..., [data])
if (!data) return null
```
