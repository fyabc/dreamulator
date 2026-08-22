# 审计第一波 T5：i18n 硬编码扫描 — 批次进度与残余清单

> 日期：2026-08-15 · 方法：`grep -rlnE '[一-龥]' frontend/src --include='*.ts' --include='*.tsx'`
> 约定（CLAUDE.md i18n 节）：命名空间 common/map/worlds/civmap（help 待迁移）；
> 硬编码中文是技术债，新代码一律走 `t()`。本清单只处理 **UI 组件/页面/可视化器**；
> 叙述性 Markdown、知识库、注释、语言名（如"简体中文"）不入范围。

---

## 一、结论速览

- 全仓共 **35 个源文件**含硬编码中文（约 **600 处**），仅 **7 个文件已接入 `useTranslation`**
  （属半成品，其余 28 个完全未接入）。
- **规模约为计划估算（0.5–1 天）的 4–5 倍**，按计划约定"超 1 天即切出残余清单另排"。
- 已完成样板：`WorldList.tsx`（13 处，含 locale key 增补 zh-CN/en 双语）。
- 剩余约 **33 个文件 / ~470 处**，按文件族分批推进（见 §三）。

## 二、已完成

| 文件 | 处置 |
|---|---|
| `pages/WorldList.tsx` | ✅ 13 处转 `t()`；`i18n/locales/{zh-CN,en}/worlds.json` 增补 action/status/label/dialog/confirm 共 11 个新 key |

## 三、残余清单（按文件族，待分批）

### A. 页面（8 文件，~196 处）
| 文件 | 处数 | 备注 |
|---|---|---|
| `pages/WorldDetail.tsx` | 86 | 最大；已部分接 i18n |
| `pages/CivMapEditorPage.tsx` | 37 | 已部分接 |
| `pages/HomePage.tsx` | 22 | 已部分接 |
| `pages/MapViewerPage.tsx` | 16 | 已部分接 |
| `pages/WorldInfo.tsx` | 14 | |
| `pages/GlobeViewerPage.tsx` | 10 | 已部分接 |
| `pages/StellarSystemViewerPage.tsx` | 8 | |
| `pages/HelpPage.tsx` | 3 | help 命名空间待建 |

### B. 地图组件（7 文件，~150 处）
| 文件 | 处数 | 备注 |
|---|---|---|
| `components/map/MapCellInspector.tsx` | 130 | 最大组件；含大量单位标签（°C/mm 等），需区分"文案 vs 单位" |
| `components/map/SunControl.tsx` | 15 | |
| `components/map/MapStatusBar.tsx` | 11 | |
| `components/map/MapLayerPanel.tsx` | 7 | |
| `components/map/GeographyRasterButton.tsx` | 3 | |
| `components/map/ImportElevationButton.tsx` | 3 | |
| `components/map/MapPreviewCanvas.tsx` | 1 | "无地图数据"（worlds.status.noMapData 已存在，可直接复用） |

### C. helpContent（1 文件，~115 处）
| 文件 | 处数 | 备注 |
|---|---|---|
| `components/map/helpContent.ts` | 115 | 结构化帮助文案数据文件；memory「help-content-sync」要求 UI 功能新增须同步此文件。转 i18n 需决定：走 `help` 命名空间（index.ts 已预留）还是保留为数据文件按语言导出 |

### D. 可视化器（6 文件，~54 处）
| 文件 | 处数 |
|---|---|
| `viewers/InfoPanel.tsx` | 31 |
| `viewers/StellarSystemViewer.tsx` | 8 |
| `viewers/PlanetMesh.tsx` | 5 |
| `viewers/utils/solar.ts` | 4 |
| `viewers/GlobeViewer.tsx` | 3 |
| `viewers/map/utils/projection.ts` | 3 |

### E. 布局/导航/杂项（7 文件，~57 处）
| 文件 | 处数 | 备注 |
|---|---|---|
| `components/LayerDocuments.tsx` | 23 | 已部分接 |
| `components/BranchSelector.tsx` | 14 | |
| `components/LayerDag.tsx` | 12 | |
| `components/NarratorPanel.tsx` | 5 | |
| `components/ErrorBoundary.tsx` | 3 | |
| `components/Sidebar.tsx` | 1 | 已有 t()，仅残留 aria 三元分支 |
| `components/Layout.tsx` | 1 | aria-label |

### F. civmap（2 文件，~6 处）
| 文件 | 处数 |
|---|---|
| `components/civmap/CivMapPreview.tsx` | 5 |
| `components/civmap/CivLeafletMap.tsx` | 1 |

### G. 非组件（1 文件，1 处）
| 文件 | 处数 | 备注 |
|---|---|---|
| `api/client.ts` | 1 | `narrateWorldStream` 内 `'服务器返回空响应'`；需 import i18n 用 `i18n.t()`（非组件内） |

## 四、排除项（非 UI 硬编码，不入范围）

| 文件 | 处数 | 理由 |
|---|---|---|
| `i18n/index.ts` | 1 | `label: '简体中文'` 是语言自名，不能走 t()（循环） |
| `viewers/map/utils/colorScales.ts` | 1 | 注释（`docs/... § 配色方案`），非 UI 字符串 |

## 五、建议批次顺序

1. **批次 1（已完成）**：WorldList.tsx（样板，确立 key 命名 + 双语增补模式）。
2. **批次 2**：A 组页面（WorldDetail 独立一批因其最大；其余页面一批）。
3. **批次 3**：B 组地图组件（MapCellInspector 独立一批；其余一批）。
4. **批次 4**：C 组 helpContent（先定 `help` 命名空间 vs 按语言导出两份数据的方案）。
5. **批次 5**：D/E/F/G 组收尾。

每批次 = 1 个 commit（代码 + locale 增补），提交前 `npx tsc --noEmit` + `npm run lint`
+ `grep -nE '[一-龥]'` 确认无残留。

## 六、T5 收尾后：语言切换器（用户确认，2026-08-15）

T5 硬编码扫完后**直接做语言切换器**，便于前端验收中英双语。

- **位置**：顶栏/Layout 一个语言下拉（或设置入口）；
- **实现**：`i18n.changeLanguage(lng)` + `localStorage` 持久化 + 首次按
  `navigator.language` 取默认（`SUPPORTED_LANGUAGES` 已在 index.ts 就位）；
- **前置**：en 覆盖率到位（即 T5 扫完），否则 en 模式中英混杂；
- **交付**：切换器 UI + zh-CN/en 双语切换验证。
