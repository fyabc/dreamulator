# 审计第一波 T4：静态导出同步差异清单

> 日期：2026-08-15 · 方法：枚举 `src/dreamulator/api_routes/` 全部读端点（GET），
> 逐一核对三件套 `scripts/export_static.py` / `frontend/src/api/staticClient.ts` /
> `frontend/src/api/client.ts` 的覆盖情况。
> 判据：读端点在静态模式（GitHub Pages）是否可用 = 导出脚本有对应产物 **且**
> staticClient 有读取方法 **且** client.ts 静态分支正确委托。

> **处理结果（2026-08-15，commit af8c8f1）**：F1（`/civilizations`）、F2
> （`/civmap/boundaries-meta`）两个孤端点已删除；F3（`getMapLayer` + layer PNG
> 端点 + `get_layer_image`）已清理（温度/降水图层由 cell 字段客户端烘焙）。

---

## 一、结论速览

共核对 **33 个读端点**（worlds 17 / maps 8 / civmap 8，narrate 仅写）。其中：

- **29 个已覆盖**（无缺口）；
- **2 个孤端点**（API 存在但前端无调用、静态无导出）→ 待决策：删除 or 补齐；
- **1 处死代码**（遗留 layer PNG 端点 + 前端 getMapLayer，实际已被 cell 字段烘焙取代）；
- **1 处已确认无缺口**（civmap countries/snapshots/assignments 在静态模式有意合并进 civ_territory.json）。

## 二、差异清单

### 2.1 已覆盖（无缺口）

| 端点 | 导出产物 | staticClient 方法 | client.ts 委托 |
|---|---|---|---|
| GET /worlds（列表） | worlds.json | listWorlds | ✓ |
| GET /worlds/{name} | world.json | getWorld | ✓ |
| GET /worlds/{name}/branches | branches.json | listBranches | ✓ |
| GET /worlds/{name}/stellar | stellar.json | getStellarSystem | ✓ |
| GET /worlds/{name}/planets | planets.json | getPlanets | ✓ |
| GET /worlds/{name}/system-catalog | system_catalog.json | getSystemCatalog | ✓ |
| GET /worlds/{name}/habitable-zones | habitable_zones.json | getHabitableZones | ✓ |
| GET /worlds/{name}/climate | climate.json | getClimate | ✓ |
| GET /worlds/{name}/ecology | ecology.json | getEcology | ✓ |
| GET /worlds/{name}/layer-documents/{layer} | {layer}_documents.json | listLayerDocuments | ✓ |
| GET /worlds/{name}/layer-documents/{layer}/{f} | 同上（内联查找） | getLayerDocument | ✓ |
| GET /worlds/{name}/design-documents | design-notes_documents.json | listDesignDocuments | ✓ |
| GET /worlds/{name}/design-documents/{f} | 同上 | getDesignDocument | ✓ |
| GET /worlds/{name}/civilization-documents | 委托 layer-documents | listCivilizationDocuments | ✓ |
| GET /worlds/{name}/civilization-documents/{f} | 同上 | getCivilizationDocument | ✓ |
| GET /worlds/{name}/maps | maps/maps.json | listMapPlanets | ✓ |
| GET /maps/{planet}/meta | maps/{planet}/meta.json | getMapMeta | ✓ |
| GET /maps/{planet}/elevation | maps/{planet}/elevation.png | getElevationBlob | ✓ |
| GET /maps/{planet}/voronoi | cvt_mesh.json（优先）/voronoi.json | getVoronoi | ✓ |
| GET /maps/{planet}/plates | maps/{planet}/plates.json | getPlates | ✓ |
| GET /maps/{planet}/features | maps/{planet}/features.json | getFeatures | ✓ |
| GET /maps/{planet}/cvt-mesh | maps/{planet}/cvt_mesh.json | getCvtMesh | ✓ |
| GET /civmap/boundaries/{level} | civmap/{level}.geojson | getCivBoundaries | ✓（组件级分支） |
| GET /civmap/available-levels | civmap/metadata.json（levels 字段） | getCivAvailableLevels | ✓ |
| GET /civmap/boundaries-mapping | civmap/mapping.json | getCivMapping | ✓ |
| GET /civmap/territory | civ_territory.json | getCivTerritory | ✓ |

### 2.2 孤端点（待决策）

**F1. `GET /worlds/{name}/civilizations`** —— `api_routes/worlds.py:301`
- 读 `layers/civilization/input/civilizations.yaml`，返回文明列表；
- `scripts/export_static.py:137` 的 `_export_layer_data` docstring 声称输出
  `civilizations` 键，但函数体（146–225 行）**从未 emit 该键**——docstring 过时；
- `staticClient.ts` 无 `getCivilizations`；`client.ts` 无 `getCivilizations`；
- 前端无调用（grep `getCivilizations`/`civilizations` 仅命中
  `getCivilizationDocument` 文档方法，非本数据端点）。
- **处置（OPEN）**：二选一——
  (a) 补齐：`_export_layer_data` 增加 `civilizations` 导出 + staticClient/client
  增加 `getCivilizations`（为未来文明面板铺路）；
  (b) 删除端点 + 修正 docstring（若 civilizations.yaml 只由 narrate 后端直接读）。

**F2. `GET /worlds/{name}/civmap/boundaries-meta`** —— `api_routes/civmap.py:62`
- 返回 reference metadata（source / version / feature counts）；
- `civmapClient.ts` 无 `getBoundariesMeta`；前端无调用；
- 静态导出 `_export_civmap_reference` 有 metadata.json 产物，但
  `staticApi.getCivAvailableLevels` 只读 `meta.levels`，无完整 metadata 读取方法。
- **处置（OPEN）**：二选一——删除端点，或补齐 getCivBoundariesMeta（若前端需要
  显示数据来源/版本/要素数）。

### 2.3 死代码（可选清理）

**F3. `GET /maps/{planet}/layer/{layer_type}` + 前端 `getMapLayer`**
- `api_routes/maps.py:110` 服务 terrain/temperature/precipitation/biome PNG；
- `client.ts:476` `getMapLayer` 在静态模式 reject（"Derived map layers not
  available in static mode"）；
- **前端实际不用 PNG 端点**：温度/降水图层由 `layerBakes.ts:390/399` 从
  `cell.temperature_C` / `cell.precipitation_mm` 客户端烘焙（这些字段在
  cvt_mesh.json 中，静态导出已覆盖）——所以温度/降水图层**在静态模式可用**，
  本端点属遗留；
- 导出脚本不导出 layer PNG（正确，因为前端不用）。
- **处置**：非静态模式功能缺口；遗留端点 + 死代码，可选清理（删端点 + 删
  getMapLayer，或保留作 API 模式备用）。

### 2.4 已确认无缺口

**F4. civmap countries/snapshots/assignments GET 端点** —— 静态模式有意合并：
- `staticApi.getCivTerritory` 读单个 `civ_territory.json`（内含 countries +
  snapshots + active_snapshot + assignments）；
- 组件层 `CivMapPreview.tsx:40/50/60`、`CivMapEditorPage.tsx:58/68/78` 已用
  `isStaticMode()` 分支走 staticApi；`civmapClient.ts` 的读函数仅 API 模式使用。
- **结论**：属有意为之的静态合并，无缺口。

## 三、建议

1. F1、F2 属"孤端点"，删除还是补齐取决于是否计划前端消费 civilizations 数据 /
   参考数据元信息——建议用户裁决（倾向：F1 补齐，为文明层前端铺路；F2 视需要）。
2. F3 属遗留死代码，可在本波顺手清理（低风险），也可留待前端二进制化重构（T6）
   时一并处置。
3. 本清单无"静态模式会 404/白屏"的硬缺口——当前 Pages 部署的主路径（地图/气候/
   生态/文档/文明地图预览）均有覆盖。

## 出处

- 端点清单：`api_routes/worlds.py`、`maps.py`、`civmap.py`（grep `@router.get`）
- 导出流程：`scripts/export_static.py`（`_export_layer_data` 146–225、
  `_export_map_data` 228–330、`_export_civmap_reference` 363–413）
- 静态客户端：`frontend/src/api/staticClient.ts`（方法清单见 §2.1）
- 统一 API：`frontend/src/api/client.ts`（readApi 334–496）
- civmap 客户端：`frontend/src/api/civmapClient.ts`（无静态分支，组件层处理）
- 图层烘焙（证明 F3 死代码）：`frontend/src/viewers/map/layerBakes.ts:390/399`
