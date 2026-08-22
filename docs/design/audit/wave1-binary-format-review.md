# 审计第一波 T6：前端二进制化前架构审视

> 日期：2026-08-15 · 目的：为 roadmap §七 P0「前端加载性能优化」③④ 动工前做
> 数据结构与 Worker 边界评审（audit-plan 第一波第 6 项）。

---

## 一、结论速览

1. **MessagePack + Worker 已经完整落地**（不是"待做"）——后端 `maps.py:172` 的
   `fmt=msgpack`、前端 `client.ts:24` 的 `fetchCvtMeshMsgPack` + `msgpack.worker.ts`，
   针对的是最大负载 `cvt_mesh`。`getCvtMesh` 已"MessagePack 优先、JSON 回退"。
2. **FlatBuffers 不需要**：MessagePack 体积与 parse 成本已满足需求，且已集成、
   有 JSON 回退。引入 FlatBuffers 是负收益（复杂 schema + 无 schema 演进 + 需
   前后端同步编译）。
3. **roadmap P0 ③ 未标 ✅ 是 doc↔code 不一致**：③ 里"MessagePack"部分已完成，
   应改为"MessagePack ✅ / FlatBuffers 放弃"，否则会误导后续排期。
4. **真正的剩余瓶颈是「几何/气候数据分离」（§七 P1 ★★★★）**，而非二进制格式：
   `VoronoiCell` 把几何（lon/lat/x/y/z/plate_id/crust_type）与气候/生态
   （temperature_C/precipitation_mm/biome/npp/soil）混在**同一个结构**里，
   气候重算后要整包重传几何。
5. **静态模式（GitHub Pages）仍是 JSON**：`staticClient.ts:301` 读 `cvt_mesh.json`，
   MessagePack 未导出到静态站。200k 下 gzip ~50 MB 可接受，500k 会成为问题。

## 二、五个评审项

### ② 序列化格式对比（先评，因为它决定其他项）

| 维度 | MessagePack | FlatBuffers |
|---|---|---|
| 体积 | 比 JSON 小 30–40%（浮点二进制编码） | 比 MessagePack 略小（零拷贝，但需对齐 padding） |
| 解码 | 需整体解析（Worker 内 `@msgpack/msgpack`） | 零拷贝随机访问（无需整体解析） |
| schema | 无 schema（`packb`/`decode` 直接映射） | 需 .fbs schema + 前后端 codegen 同步 |
| 现状 | **已集成**（后端 msgpack + 前端 worker） | 未集成 |
| 回退 | 已有 JSON 回退 | 需另做回退 |

**结论**：`cvt_mesh` 是"一次性整体加载"的负载（前端要全量构建 KD-tree/烘焙图层），
**用不到 FlatBuffers 的零拷贝随机访问优势**。MessagePack 已满足，且已集成。
**放弃 FlatBuffers。**

### ① 数据结构切分（几何 vs 气候/生态）

当前 `VoronoiCell`（`models.py:127` 起）把三组字段混在一起：

- **几何（静态）**：lon/lat/x/y/z、neighbors、plate_id、crust_type、boundary_type、
  distance_to_boundary_km、convergence_rate_cm_yr、elevation（地形层后固定）；
- **气候（动态）**：temperature_C、precipitation_mm、koppen_class、wind/ocean 分量；
- **生态（动态）**：biome、npp_gc_m2_yr、soil_type、soil_fertility、
  domesticable_tags、biogeographic_province。

**问题**：几何与气候/生态被同一个 `cvt_mesh.json` 承载。气候层重算后，几何
（~80 MB @ 200k，占大头）也要整包重传——违背 §七"几何只加载一次、气候/生态增量
更新"的意图。

**建议**（P1 数据分离的落地方向）：
- 拆成 `cvt_mesh.geometry`（几何 + 地形，静态）与 `cvt_mesh.climate`/`cvt_mesh.ecology`
  （动态字段），或按字段名白名单在前端增量 patch；
- 几何负载走 MessagePack（已有），气候/生态增量走轻量 JSON patch；
- 前端 `adaptCvtMesh` 已集中处理字段映射（`client.ts:61`），切分改动收敛在此处。

### ③ Worker 边界

现状：`msgpack.worker.ts` 只做"fetch + decode MessagePack"，解码后 `postMessage` 回
主线程，主线程再做 `adaptCvtMesh`（类型转换 + KD-tree 构建）。

**建议**：
- Worker 边界清晰（解析在线程外、渲染在主线程），当前够用；
- 后续若做几何/气候分离，可将"增量 patch 合并进几何对象"也放进 Worker，主线程
  只接收最终对象；
- 注意：`adaptCvtMesh` 中的 KD-tree 构建仍可能阻塞主线程（500k 时 O(N log N)），
  可与数据分离一并评估移入 Worker。

### ④ 静态模式兼容性

现状：静态模式（`staticClient.ts:301`）读 `cvt_mesh.json`（JSON），**不走 MessagePack**；
`export_static.py` 只导出 `cvt_mesh.json`（JSON）。

**评估**：200k 下 gzip ~50 MB，JSON.parse 在主线程约 100–300 ms，可接受；
500k（570 MB 未压缩）会重演技术债 #18 的 OOM。

**建议**（二选一，视是否上 500k）：
- 不上 500k → 静态模式维持 JSON，无需动；
- 上 500k → `export_static.py` 额外导出一份 `cvt_mesh.msgpack`，静态前端复用
  `msgpack.worker.ts`（同一 worker，仅数据源从 API 换成静态文件）。

### ⑤ 迁移顺序与回退点

1. **先把 P0 ③ 标正确**（roadmap 同步：MessagePack ✅ / FlatBuffers 放弃）——零成本、
   消除误导；
2. **几何/气候分离**（P1）：先拆字段、前端 `adaptCvtMesh` 收敛，再评估 Worker 内
   patch 合并；
3. **纹理分辨率匹配**（P0 ④）：500k 时才需要，与数据分离独立；
4. **回退点**：MessagePack 已有 JSON 回退（`client.ts:484` catch）；数据分离可保留
   "单文件 cvt_mesh.json"作为静态模式回退，直到 msgpack 静态导出就绪。

## 三、给 P0 加载优化的最终方向

| 项 | 建议 |
|---|---|
| P0 ③ MessagePack | ✅ 已完成，roadmap 标 ✅ |
| P0 ③ FlatBuffers | 放弃（无收益） |
| P0 ④ 纹理分辨率 | 独立小项，500k 时做 |
| P1 几何/气候分离 | **真正的剩余主项**，聚焦这里 |
| 静态模式 msgpack | 视 500k 目标决定 |

> 本质结论：**"二进制化"这个 P0 已经被 MessagePack 提前完成了一大部分**；
> 剩下的加载性能工作不在"换格式"，而在"分离数据结构 + 增量更新"。

## 出处

- 后端 msgpack：`src/dreamulator/api_routes/maps.py:153-176`（`fmt=msgpack`）
- 前端 msgpack：`frontend/src/api/client.ts:24-43`、`frontend/src/workers/msgpack.worker.ts`
- 静态模式 JSON：`frontend/src/api/staticClient.ts:301-316`
- 几何/气候/生态混合：`src/dreamulator/map/models.py:127-190`（`VoronoiCell`）
- roadmap §七 P0 ③④（第 229 行）、§八 #18（500k JSON OOM）
