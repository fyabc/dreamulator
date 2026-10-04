---
title: "UCC 迁移语义夹具：ucc-v1 应用于 Nacrea"
type: fixture
tags: [ucc, climate, classification, fixture, migration]
date: 2026-09-29
status: accepted
---

# 0010 · UCC 迁移语义夹具（ucc-v1 × Nacrea）——解读与维护

> 手写解读文档；数据表（全局分布 / 预期 vs 实际 / 代表地点 / 极值点）在
> [`nacrea-data.md`](nacrea-data.md)，由
> `scripts/climate/ucc_examples_nacrea.py` 生成、勿手改。
> nacrea 侧叙事设定的权威源是 `data/worlds/nacrea/design-notes/`（0009
> 卫星架构等）；本文只谈 UCC 夹具语义。

## 1. 夹具目的

分类阈值全局共享（绝不按世界取分位数），所以把同一 profile 应用到慢自转
（自转约为地球的三成，大气环流是覆盖到两极的单圈哈德莱体制——引擎侧的
文档化覆写，见 astra 台账）、短年（约 100 地球日；精确值以
`layers/astronomy/derived/system_catalog.yaml` 为准）、强温室（+62 K）的
Nacrea 上，必须产出**语义正确而非地球样**的标签。数据表记录 ucc-v1 在
当前正典气候态上的结果，作为将来 profile / 引擎 / 设定变更的对照基线：
其中任何数字的移动都是需要有意接受或排查的语义变化，不是可以静默发生
的漂移。

时间契约迁移点：12 个分箱是**参考年**（365.25 地球日）的等长切片，每箱
约 0.37 个 Nacrea 本地年——月箱序列不是「本地月份」；`p_total` 按参考年
报告，不等于一个本地年累计。AI 是窗口不变量，可直接跨世界比较
（规格书 §2）。

## 2. 读数据表的三个入口

- **§1 全局分布**：看主类组合与状态份额。慢自转 + 单圈环流的直接后果是
  continental 修饰语构造性为零（seasonal t_range 全域 ≤ 12 °C，够不到
  25 °C 阈值）——这不是「nacrea 没有季节」，而是温度季节振幅小；降水
  季节性（water_stress 覆盖约三分之一陆地）照常被表达。
- **§2 预期 vs 实际**：UCC-01 计划时按 v0 记录的迁移预期逐条核对——现实
  与预期的差异正是夹具的价值，不是要藏的东西。
- **§3/§4 代表地点与极值点**：geography.yaml 命名锚点上的逐点月序列，
  以及最干 / 最湿 / 最冷 / 最热 / 季节最强的极值 cell。

## 3. 夹具维护

- 正典气候重建后（`uv run dreamulator build nacrea --only climate` 或
  全量）重跑本脚本刷新数据表；数值移动应能与构建改动对应。
- profile 升级（v2 等）时：数据表的标题/元数据随
  `climate_yearly.msgpack` 的 `profile` 字段自动更新，预期表需人工重述。
- 本文档是**语义夹具**（记录当前正典的正确行为），不是设定文档；设定
  变更走 ADR 流程，数据表只在重建后刷新。

2026-10-04 随文档结构重构（手写/生成分离）重新生成过一次数据表，此后
基准 = 09-30 终产品气候态（深海 clamp + 温室 62 K 重建）。
