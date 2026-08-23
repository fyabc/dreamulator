# 三波审计计划

> 最后更新：2026-08-15（v0.27.0 发布节点起草）
> 背景：项目规模已大（200k 网格全链路、前后端 + 知识库文档群），需要全面审计。
> 但气候引擎仍在高频调参、简化 GCM PoC 刚启动，一次性全审会"审完即过期"。
> 本计划按**变化速率**把审计拆成三波，各波有明确的启动判据与交付物。

---

## 一、总体原则

1. **按变化速率分层**：正在被高频重写的部分（气候旋钮、气候文档）最后审；
   稳定部分（工程卫生、架构、API/IO）先审。
2. **审计先造工具**：`derive_world_parameters()`（技术债 #22）等工具本身
   就是审计手段——先落地工具，后续审计尽量自动化而非人肉核对。
3. **每一波有可验收交付物**：清单、测试套件、修复 commit，而非"看过了"。
4. **证据锚定**：审计发现的每一条矛盾/缺陷必须附 `文件:行号` 或文献出处；
   给不出出处的分歧标记 OPEN 升级给用户裁决。

---

## 二、三波安排

### 第一波：工程卫生 + 一致性审计（v0.27.0 节点即可启动）

气候调参碰不到这些层，不会白审。

| 条目 | 内容 | 交付物 |
|------|------|--------|
| 文档↔代码数值一致性扫描 | 抽取 `docs/` 中所有数值声明（参数值、物理常数、性能数字），逐一对照代码/配置值。根因是技术债 #22（参数手抄进 7+ 文档）；先落地 `derive_world_parameters()` 消除参数型矛盾，再扫描残余的物理声明型矛盾（earth_gradient_c 即此类） | 矛盾清单 + 修复 commit |
| 自由参数清点造册 | 枚举全部引擎配置字段（`TerrainPipelineConfig`、气候配置、生态配置……），只清点不处置。分类见 §三 | 参数清单表 |
| 技术债 #4：build dirty 判定 | 输入 mtime 指纹替代"输出存在即跳过"（8/6、8/13 两次踩中） | `pipeline._is_dirty()` + 测试 |
| 技术债 #22：`derive_world_parameters()` ✅（2026-08-15 交付） | build 时输出 `world_parameters.yaml`（原始 + 衍生参数），杜绝手算手抄 | 纯函数 + YAML 导出 + 测试（已完成） |
| 静态导出同步检查 | `export_static.py` / `staticClient.ts` / `client.ts` 三件套与当前 API 端点逐一比对（v0.10.0 地图 404 教训） | 差异清单 |
| i18n 硬编码扫描 | 组件中的硬编码中文 → `t()`（CLAUDE.md 约定） | 修复 commit |
| 前端二进制化前架构审视 ✅（评审见 `audit/wave1-binary-format-review.md`） | JSON→MessagePack/FlatBuffers（§七 P0）动工前的数据结构与 Worker 边界评审 | 评审纪要（已完成，MessagePack 落地） |

### 第二波：物理审计（判据：Phase 3A 验收 M4 达成 **且** 简化 GCM PoC 出结论）

**必须等的理由**：PoC 结论可能是"用 ExoPlaSim 替换/混合现有引擎"，届时现有
旋钮清单整体作废；M4（空间准确率 >55%、Kappa >0.4，v0.27.0 为 53.6%）未达成
前参数表每天都在变。

| 条目 | 内容 | 交付物 |
|------|------|--------|
| 自由参数处置 | 按 §三 分类逐旋钮裁决：替换 / 保留文档化 / 补文献 | 处置记录 + 代码变更 |
| 各引擎层物理正确性审查 | 逐层核对公式实现与 `docs/knowledge/` 引用的一致性 | 审查报告 |
| 物理不变式测试套件 | 见 §四 第 1 条 | `tests/test_invariants.py` |
| 低阶模型差分测试 | 见 §四 第 2 条 | 参考解 + 阈值报警测试 |

### 第三波：架构审计（判据：Phase 3B 启动前）

3B 侵蚀将引入 `surface_evolution_steps` + `climate_coupling` + 地貌降水代理，
是对 DAG 与四层控制模型（[layer-control-model.md](proposals/layer-control-model.md)）的
结构性改动；3C 文明层要新增整层。**在加新结构之前审，成本最低。**

| 条目 | 内容 |
|------|------|
| DAG 边界 | 层间数据流、`find_input()` 继承链、proxy/full 耦合模式的环依赖检查 |
| manifest / 可复现性 | `ComputationManifest` 接入状态、校验和链路完整性 |
| 分支继承逻辑 | 分支层解析、`_inherit` 合并的边界情况 |
| 四层控制模型落地差距 | 约束/引擎/校验/覆写四层的已实现 vs 纸面差距 |

> ✅ **已执行（2026-08-20，Phase 3B 启动前）**，结论与约束见
> [audit/wave3-architecture.md](audit/wave3-architecture.md)。要点：proxy 默认
> 耦合不破坏 DAG；`full` 耦合单趟不可行（留接口位）；发现两处实施坑——地质分叉
> 分支静默丢失 geography.yaml、`TerrainCache` 未覆盖 erosion/rivers 阶段。

---

## 三、自由参数处置分类

清点后每个参数归入三类之一：

| 类别 | 定义 | 处置 |
|------|------|------|
| **A 可推导** | 存在严格公式或经验公式可从上游物理量推出 | 用物理规律替换，删除旋钮，丰富 `docs/knowledge/` 说明 |
| **B 创意旋钮** | 世界构建工具的合法创意控制（如 geography 锚定强度） | 保留，但文档化合理范围、默认值依据（创意旋钮是特性不是债） |
| **C 经验常数** | 文献中的经验取值 | 保留，补文献引用到 `docs/knowledge/` |

**先例证明此路可行**（参数→物理的替换史）：

| 版本 | 替换 |
|------|------|
| v0.27.0 | 季节 EBM 删除 3 个旋钮：`seasonal_amplitude_c`/`0.25`/`f_ocean` → North & Coakley 1979 的 ΔQ_ω + 热容量 C |
| v0.24+ | `lat_gradient_c` 手动调参 → ΔT(Ω) 参数化（`lat_gradient_from_omega`）；BFS 步数固定值 → Ω^(−1/3) 理论标度 |
| v0.24+ | Föhn 效应：Clausius–Clapeyron 零自由参数实现 |
| v0.2x | 板块速度硬编码 15/6 cm/yr → 潮汐加热幂律 v ∝ q^β（`tidal_physics.py`） |
| v0.14.0 | 硬编码 1.0 AU / 1.0 L☉ → `physical_inputs.py` 统一解析 |

---

## 四、引擎高频 bug 的治本方案

 changelog 复盘：绝大多数 bug 是**工程型**（硬编码地球值、`_baseline` 被当地图、
 死代码 `dry_offset`、缺导出字段、`np.maximum` 误伤陆地），而非物理求解错误。
 换更高级的求解器一个也防不住。中间路线四条腿：

1. **物理不变式测试套件**（与调参无关，调参翻车立刻报警）：
   - 守恒：全球水量平衡、能量平衡残差
   - 单调性：赤道→极地温度梯度方向
   - 非负性：降水 ≥ 0
   - 自洽性：用 T/P 重算 Köppen 必须等于分类字段
   - 端元：已有 T2（Venus/Mars）+ T3 物理合理性，扩展为套件
2. **低阶模型差分测试**：0D/1D 解析 EBM 作为廉价参考解，全球均值偏离超阈值即报警。
3. **GCM 当离线 oracle，不当运行时引擎**——"GCM 太贵"的正解：
   用 ExoPlaSim 在行星参数空间（Ω / 倾角 / 光度 / CO₂）上扫描，把结果拟合成
   参数化公式回填进 dreamulator 旋钮。成本一次性离线支付，运行时仍 5 分钟量级。
   **简化 GCM PoC 的验收目标应定为"能否产出可回填的参数化"，而非"能否替换引擎"。**
4. **诊断四件套补全**（§七 P1）：完成 ②纬度带 T/P 剖面、③混淆矩阵，
   把"引擎 bug vs 参数待调"分离流程化（地球基准是唯一标准答案）。

---

## 五、grill-me 拷问的使用规范

- `~/.claude/skills/grill-me/` 是拷问**计划**的技能，不适合系统性代码/文档审计
  （一次一问、无清点能力）。适合**每波启动前** grill 该波的计划本身，以及
  重大设计决策点（如 3B 的 DAG 方案）。
- 该技能 `disable-model-invocation: true`：只能由用户输入 `/grill-me` 启动；
  可带提示词（`/grill-me 方案描述...`）。
- **子代理互审模式**（用户无法回答专业问题时）：
  - griller agent：按 grill-me 维度清单（需求完整性/边界异常/隐含假设/依赖集成/
    范围取舍/验收标准/风险回退）生成问题
  - answerer agent：只许从代码/文档找证据作答，**每个回答必须附 `文件:行号`
    或文献出处**
  - 给不出出处的分歧标记 OPEN，升级给用户裁决
  - 用 Workflow 编排两者交替（需用户明确授权）

---

## 六、相关文档

- [roadmap.md](roadmap.md) §七 优先级、§八 技术债务（#4、#22 为第一波前置；#23 天体双文件重复已由 system_catalog 化解）
- [competitor-analysis.md](competitor-analysis.md) — 简化 GCM 探索（ExoPlaSim PoC）
- [climate-validation.md](pipelines/climate-validation.md) — 多线证据策略
- [layer-control-model.md](proposals/layer-control-model.md) — 第三波架构审计对象
