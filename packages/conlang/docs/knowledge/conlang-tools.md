# Conlang 工具与学术资源调研

人造语言（conlang）社区的工具生态分两类：面向人类创作者的辅助工具
（音变应用器、词典管理、程序化生成器）和面向学术的计算历史语言学
工具（同源推断、谱系建树）。前者提供音变规则 DSL 的设计参照，
后者提供校验回路（"比较法往返"）的算法来源。

> 调研来源：2026-08-15 interlude 调研（完整版含全部链接见主仓
> `private/research/2026-08-15-conlang-methodology-tools.md`）。

---

## 一、音变应用器（Sound Change Applier，SCA）对比

| 工具 | 实现 | 开源 | 特点 |
|---|---|---|---|
| SCA²（zompist.com） | C + JS 网页版 | ❌（免费） | 事实标准语法 `a > e / _i`；多字母音位支持弱 |
| **Lexurgy** | Kotlin（JVM），CLI + 网页版 | ✅ GPL-3.0 | 社区首选；支持**区别特征**、变音符号、过滤规则、规则起止点控制 |
| Brassica | Haskell，网页版 | ✅ | 多字母音位支持好、语法高亮、特征系统（2024-10 发布 1.0.0） |
| ASCA | Web | 部分 | 原生 IPA（含搭嘴音、内爆音、挤喉音）、双元音/变音符 |
| TriSCA | Web | ✅ | SCA² 语法 + 增强 |
| rsca | Web | ✅ | **可逆音变**（正反向应用——对"从女儿语反推祖语"的调试有用） |
| erickcan/sound-change-applier | Python CLI | ✅ | 易嵌入 Python 管线 |

**对本包的含义**：本包 `phonology/sca.py` 属于同一赛道，差异化在于
① Python 原生、可播种可复现（与 dreamulator 引擎范式一致）；
② 概率规则 + 词频加权 + 世代模拟（多数 SCA 不支持）；
③ 与词源数据库（etymology.py）集成。特征规则语义可参照
Lexurgy/Brassica（两者均已实现区别特征）。

## 二、程序化生成器与词典工具

- **Vulgarlang**（vulgarlang.com）：最完整的"一键生成 conlang"商业产品。
  内部 IPA 管理、音节约束、约 2000 词词表、强音变 DSL（支持特征、
  量词、IF/ELSE 条件、例外、"音变反映在拼写"）。**闭源**；
  "Evolve language" 功能被社区批评缺少谱系树管理与多分支自动化——
  这正是 dreamulator 语言谱系子系统的差异化空间。
- **PolyGlot**（github.com/DraqueT/PolyGlot，Java）：桌面 conlang 工具包。
  亮点是**词表对音系模式的一致性自动检查**与变位/变格自动生成——
  "规则校验词表"模式值得借鉴为引擎的输出一致性校验。
- **Awkwords**：经典模式词生成器（已停止维护，复刻 nai888/awkwords）。
  局限：复杂音系配列下易产生乱码感输出。同类：Logopoeist、WordMage。

## 三、计算历史语言学工具（学术侧）

| 工具 | 用途 |
|---|---|
| **LingPy**（Python） | 序列比较、语音对齐（SCA/ALD 算法）、同源词检测（LexStat）、词表处理——**校验回路的首选依赖** |
| **LingRex** | 基于 LingPy 的祖语构词/重建辅助 |
| **EDICTOR** | 网页端词源数据编辑器（TSV）：同源标注、语音对应、树推断与可视化 |
| **Lexibank / CLDF** | 标准化跨语言词库与数据格式（词表序列化可参考 CLDF 规范） |
| **BEAST / BEAST2** | 贝叶斯系统发生推断（分化时间 + 地理扩散）——真实研究用它反推历史；本包是正向问题，可用作"给定词表反推语族树"的调试工具 |
| **D-PLACE** | 语言谱系与文化数据库 |

**Bouckaert et al. (2012)** 用 BEAST 分析 103 种印欧语基本词汇支持
安纳托利亚起源（*Science* 337: 957–960）；Chang et al. (2015) 用
祖先约束法支持草原假说（*Language* 91(1)）——**谱系推断对模型假设
敏感，这是"争议理论"的又一实例**。

## 四、程序化语言生成的学术先例

1. **GenLang**（Cai & Martens, EXAG @ AIIDE 2023；github.com/AkaiGameDev/GenLang）：
   分层生成——音位清单规模按 WALS 分布采样、音段按 PHOIBLE 频率采样、
   音节模板 + Zipfian 分布、语序按 WALS 加权（修饰语序独立采样）。
   论文明确批评 Dwarf Fortress 四语互为 relex。
2. **Ultima Ratio Regum**（Mark R. Johnson, PCG 2016）：为程序生成的
   文明生成方言、命名法、口语句子与双向词典；方言从共同基础经
   音系规则分化——与 dreamulator 语言谱系的目标最接近。
3. **James Ryan (PCG 2016)**：主张从世界内因果（diegesis）驱动语言演化。
4. **ConlangCrafter (2025, arXiv:2508.06094)**：LLM 多跳管线
   （音系→形态→句法→词表）。LLM 适合创意设定生成，但可复现性与
   一致性校验应交给确定性规则引擎（dreamulator 的 input/derived 原则）。
5. **Dwarf Fortress**：约 2195 词根 + 前后缀派生 + 文明-语言绑定；
   词根系统的组织方式值得参考，但四语互为 relex 是反面教材。

## 五、类型学数据库（生成的真实性先验）

- **PHOIBLE 2.0**（phoible.org）：2000+ 语言音位清单；
- **WALS Online**（wals.info）：约 192 个结构特征 × 2600+ 语言；
- **Glottolog**（glottolog.org）：世界语言谱系目录（语族结构的参照分类学）；
- **ASJP**（asjp.clld.org）：跨语言 40 词核心词表 + 自动相似度。

## 六、教程资源（方法论底本）

- Rosenfelder, M. *The Language Construction Kit*（zompist.com/kit.html）——
  **Language families 章专讲从父语经系统音变派生女儿语言**；
  同作者 *The Planet Construction Kit* 的"从物理到文明"层级组织
  与 dreamulator 的 DAG 架构理念一致。
- Peterson, D. J. *The Art of Language Invention* (2015)——"先文化后语言"
  的设计次序；Dothraki 采用"先构拟原始语再历时演化"的工作方式。
- Biblaridion《How to Make a Language》系列（YouTube）——教学顺序
  印证"历史优先"路线（先祖语词表，再音变演化）。
- 反面教材：J.S. Bangs《How to fail at conlanging》——relex 陷阱等。

## 七、对本包的结论

1. 音变引擎不必另起炉灶：现有 sca.py 的能力（概率、词频、世代）
   已超过多数开源 SCA；补齐**特征规则**（对标 Lexurgy）即可覆盖
   社区最佳实践（设计稿见 `docs/design/feature-rules.md`）。
2. 校验回路借力 LingPy：生成女儿语后做同源检测往返验证
   （设计见主仓 `docs/design/language-phylogeny.md`）。
3. 差异化空间明确：谱系树管理、借用建模、与世界状态（人口/迁徙/地图）
   耦合——Vulgarlang 等现有工具均不具备，而 dreamulator 全部具备。
