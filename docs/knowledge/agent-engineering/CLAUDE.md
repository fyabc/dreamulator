# Agent 工程知识库

本目录存放「自维护系统」的工程参照——agent 框架与世界托管平台如何防止系统随演化腐烂。
供 Dreamulator「守护轴」（`docs/design/harness.md`）设计时查阅。

## 目录结构

```
agent-engineering/
└── self-maintenance-patterns.md   # 自维护系统模式：Claude Code / OpenClaw / Hermes / World Anvil
```

## 关键概念

| 概念 | 说明 | 守护轴对应 |
|------|------|-----------|
| silent drift / stale memory | 系统随演化静默漂移、记忆过期——守护轴的头号敌人 | 三级过期检测 |
| 分层记忆 + 容量上限强删 | Hermes：超限写入失败，强制 replace/remove | 决策记录台账容量上限 |
| hook（强制）vs 建议 | Claude Code：必须每次都成立的规则做成 hook | 硬/软分层 |
| 变量单点更新 | World Anvil：改一处处处同步（但变量是手动文本） | doc_render 事实上下文 |
| 自进化环 | Anbao：reflect → attribute → rule update | 改进环 |
| hard/soft worldbuilding | 自洽性 vs 创造性是一个光谱；约束反而激发创造力 | 硬度旋钮 + 约束分级 |
| Sanderson 第一定律 | 软设定机制可未知，但后果须映射到状态变量 | 后果映射校验维度 |
| canon `Status` 标记 | 区分 canon / 非 canon 想法，防 lore drift | 决策记录 status + divergence 标记 |

## 交叉引用

- `docs/design/harness.md` — 守护轴总纲（本知识库的「应用方」）
- `docs/design/audit-plan.md` — 守护轴之「守护引擎」实例
- `docs/design/vision.md` — 愿景（Fantasy Harness 隐喻的来源）
