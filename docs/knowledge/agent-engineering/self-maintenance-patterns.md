# 自维护系统模式：Agent 框架与架空世界托管平台

> 学科定位：软件工程 / agent 工程。这是 Dreamulator「守护轴」（`docs/design/harness.md`）的
> **工程参照来源**——不是世界构建科学，而是「如何让一个持续演化的系统不腐烂」的方法。
> Dreamulator 把这些经验从「agent 记忆 / 世界托管平台」的层面，提升到「有引擎 derived 数据
> 可校验」的层面（见「超越点」一节）。

## 核心问题：silent drift + stale memory

三个阵营（agent 框架、世界托管平台）都撞上同一堵墙，且都把它当作头号敌人：

- **Hermes Agent**（Nous Research）明说：「**过期记忆是 agent 异常行为的头号原因**」。
- **OpenClaw 生态的 Genesis 框架**把使命直接写成「防止 **hallucination、silent drift、stale repo memory**」。
- **Claude Code** 官方指引反复强调「把『必须每次都成立』的规则做成 hook，而非提示词」。

---

## 一、Agent 框架

### 1.1 Claude Code：分层记忆 + 确定性 hook vs 建议

**分层记忆**（`public-architecture-claude-code` 等公开架构）：WARM（14 天）/ HOT 自动加载，COLD
按需 Read，L4 语义搜索查更旧内容；`handoff.md` 只载最近 ~10 条会话日志，节省 token。cron 脚本自动
轮换压缩（Sonnet 压缩性价比约为 Opus 的 1/4）。

**hook vs 建议**（官方 [Steering 指南](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more)）：
`CLAUDE.md` 是建议（~80% 遵从），hook 是强制（100%）。「如果一条规则必须每次都成立，把它做成 hook，
而不是写进提示词。」常见护栏 hook：`block-dangerous.sh`（拦 `rm -rf`）、`protect-files.sh`（保护密钥）、
`log-commands.sh`（记录每条命令）。自维护 hook：SessionStart 加载最近教训、检查 inbox、设心跳。

**关键取舍表**（官方）："每次 X 都做 Y" → hook；"永远别做这个" → hook/权限；30 行流程 → skill；
"必须每次都发生" → hook。

### 1.2 OpenClaw：AGENTS.md + 自维护仓库实验

**`AGENTS.md`**（[官方仓库](https://github.com/openclaw/openclaw/blob/fde87f475f74/AGENTS.md)）把
agent 贡献仓库的规则写成文件：PR 需 Summary+Verification、附本地命令/CI run ID/前后证据、代码质量
标准、永不提交凭据、CHANGELOG 由发版管理。

**自维护实验**：
- **AgentKeeper**（[实验](http://www.diginfo.me/autonomous-agent-experiment-openclaw)）：cron 技能
  30 分钟循环自主维护 GitHub 仓库（pull → fetch+search → execute → return → organize），35+ commit、
  20+ 文章，产出 HISTORY.md / REPORT.md / state.json。
- **Thoth**（`openclaw-superagent`）：自愈 watchdog + 交接系统（「永不遗忘」）+ 3 自动 cron。
- **Anbao**（`openclaw-agent-showcase`）：自进化环 `reflect → attribute → rule update`，44 任务
  100% 成功，知识图谱 56 概念 862 链接 0 孤立。

### 1.3 Hermes Agent：容量上限 + 强制剪枝

[源码剖析](https://www.alibabacloud.com/blog/603216)、[六大技术支柱](https://cloud.tencent.com.cn/developer/article/2663646)：

- **持久记忆两个纯文本**：`USER.md`（用户偏好/禁忌）+ `MEMORY.md`（环境事实/约定），每次会话加载。
- **容量上限 + 超限写入失败**：`MEMORY.md` ~2200 字符上限，超限时 `MemoryStore` **拒绝 add** 并
  返回当前全部条目，强制模型显式 `replace`/`remove`——「有限容量迫使优先高密度事实，防止 append-only
  无限膨胀」。
- **热/冷分离**：实时可写条目 + 会话启动时的冻结快照（缓存感知的 system prompt 快照）。
- **Curator 定期剪枝**过期 skill/记忆；**skill 自修补**（模糊匹配 + 失败回滚）；**Nudge Engine**
  周期性提示反思。

---

## 二、世界托管平台

### 2.1 World Anvil：Variables + Autolinker + 模板

- **Variables**（[使用](https://www.worldanvil.com/learn/variables/tips-variables)）：BBCode 标签
  持有可复用内容，改一处处处同步。用于「快速变化的数字（人口/当前日期）」「术语」「外链」。**这是
  Dreamulator `doc_render` 模板的直接类比——但 World Anvil 的变量是手动打的文本。**
- **Autolinker**（[公告](https://blog.worldanvil.com/worldanvil/dev-news/world-anvils-most-requested-new-feature-the-autolinker/)）：
  自动把关键词超链接到已写文章（三种模式：自动/仅首现/逐条人工审）。
- **模板**（25+ 文章模板 + Creative Studio 自定义）保证结构一致。
- **天花板**：变量/链接都是**文本**——防笔误漂移，不防逻辑漂移。没有任何东西检查「人口 6000 是否
  与承载力物理矛盾」。

---

## 三、自洽性 vs 创造性（世界构建的硬度光谱）

「自洽性」和「创造性」不是对立的——业界共识是它们是一个**光谱**上的取舍，且**约束反而激发创造力**。

### 3.1 Hard vs Soft Worldbuilding（光谱，非优劣）

[World Anvil 学院指南](https://academy.worldanvil.com/blog/hard-versus-soft-worldbuilding)：
- **Hard**：预先规划、内部一致极好、可给读者「规则书」；风险是「写无聊」、约束过多扼杀灵感。
- **Soft**：即兴、自由、让读者参与想象；风险是 lore drift、连续性错误、deus ex machina。
- 主流共识：**大部分创作者落在中间，混用**——不是「这个世界是硬的还是软的」，而是「这一条设定你要多硬」。

### 3.2 Sanderson 三条定律（自洽性的「成本」模型）

[Sanderson's Laws of Magic](https://coppermind.net/wiki/Sanderson%27s_Laws_of_Magic)：

1. **第一定律**：「用魔法解决冲突的能力，正比于读者对该魔法的理解。」→ 软魔法（未解释）可以存在，
   但**不能解决关键冲突**（否则 = deus ex machina）。对应 Dreamulator：软设定的**机制**可以未知，
   但**后果必须映射到状态变量**才能推演。
2. **第二定律**：限制 > 力量（「不能做什么」比「能做什么」更有趣）。→ 反驳「守护轴扼杀创造力」：
   约束在受限空间里激发替代方案。
3. **第三定律**：先深挖再新增（深度 > 广度）。→ 守护轴的改进环帮用户在已有设定上展开，而非无限堆新设定。

### 3.3 Canon 管理工具（lore drift 的解法）

新兴工具（[CanonGuard](https://peerpush.com/p/canonguard)、[LitMemo](https://www.producthunt.com/p/litmemo)）
都在解决 **lore drift**，解法高度一致：`Status: Canon` 元数据标记、scratchpad 隔离非 canon 想法、
canon ledger + 证据链接、AI consistency guardian 扫描矛盾。→ 全部映射到 Dreamulator 决策记录的
`status` / `private/tmp` / 台账 / `/grill-world`。

---

## 四、对 Dreamulator 守护轴的映射

| 经验 | 守护轴对应物（`harness.md`） |
|---|---|
| Claude Code 分层记忆 + cron 轮换 | 决策记录台账分层 + 定时巡检 |
| Claude Code hook vs 建议 | 硬/软分层：引擎 derived+checksum+渲染断链 = 100% 强制；文档 = 建议 |
| Hermes 容量上限 + 强制剪枝 | 决策记录台账容量上限 + 超限强制归档 |
| Hermes Curator | `guard check` 过期检测 |
| World Anvil Variables | `doc_render` 事实上下文（但变量是引擎算的） |
| Anbao reflect→attribute→rule | 改进环：决策记录 → 参数处置 → 引擎不变式 |
| Claude Code 金丝雀 | 守护轴自检（合成已知矛盾的拷问，测 guard 管线本身） |
| OpenClaw AgentKeeper cron | 守护轴 cron 巡检（「文档漂移机器人」） |
| hard/soft worldbuilding 光谱 | 硬度光谱 + 约束分级（Hard/Soft/Preference/Override，layer-control-model） |
| Sanderson 第一定律 | 后果映射校验维度（软魔法后果须映射到状态变量） |
| canon `Status` 标记 | 决策记录 `status` + `divergence: intentional`（区分故意覆写 vs 漂移） |

## 超越点：文本↔文本一致 vs 文本↔物理一致

竞品的自维护都在做「**文本与文本一致**」：agent 记忆是 agent 自己写的文本（无 ground truth，只能判断
「旧不旧」不能判断「错没错」）；World Anvil 变量是手动打的文本（防笔误，不防逻辑漂移）。

**Dreamulator 的变量锚定引擎确定性推演的 derived 数据**：能防「物理漂移」，能判断「这条设定**错了**」。
> World Anvil 的变量是「打字一次，处处同步」；Dreamulator 的变量是「引擎推演一次，处处同步且处处可验证」。

## 参考资料

- [Claude Code: Steering with skills, hooks, rules, subagents](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more)
- [Extend Claude Code — features overview](https://code.claude.com/docs/en/features-overview)
- [OpenClaw 官方仓库 AGENTS.md](https://github.com/openclaw/openclaw/blob/fde87f475f74/AGENTS.md)
- [OpenClaw coding-agent SKILL](https://github.com/openclaw/openclaw/blob/main/skills/coding-agent/SKILL.md)
- [Open-Genesis framework（防 hallucination/silent drift/stale memory）](https://github.com/boygotflames/Open-Genesis-for-Claude-code-Openclaw-Codex-Cursor-or-any-agent)
- [AgentKeeper 实验：OpenClaw 自主维护仓库](http://www.diginfo.me/autonomous-agent-experiment-openclaw)
- [Hermes Agent 自我改进源码剖析](https://www.alibabacloud.com/blog/603216)
- [Hermes Agent 六大技术支柱](https://cloud.tencent.com.cn/developer/article/2663646)
- [World Anvil Variables 使用](https://www.worldanvil.com/learn/variables/tips-variables)
- [World Anvil Autolinker 公告](https://blog.worldanvil.com/worldanvil/dev-news/world-anvils-most-requested-new-feature-the-autolinker/)
- [World Anvil Academy — Hard vs Soft Worldbuilding](https://academy.worldanvil.com/blog/hard-versus-soft-worldbuilding)
- [Sanderson's Laws of Magic — Coppermind](https://coppermind.net/wiki/Sanderson%27s_Laws_of_Magic)
- [CanonGuard（lore/rule drift 检测）](https://peerpush.com/p/canonguard)
- [LitMemo（AI consistency guardian）](https://www.producthunt.com/p/litmemo)
