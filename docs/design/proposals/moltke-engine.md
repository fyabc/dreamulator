# Moltke Engine — 独立实体引擎

> 来源：2026-07-25 讨论记录。远期规划，实体规模到达瓶颈前可推迟。

---

## 1. 定位

Dreamulator 下属的独立 Python 包，专门处理百万级实体网络的性能问题。

## 2. 技术方向

| 技术 | 来源 | 适用场景 |
|------|------|---------|
| **ECS**（Entity-Component-System） | UE5 Mass、《城市：天际线》 | 气候/生态网格的高频并行计算 |
| **差分数据流**（Differential Dataflow） | Microsoft Naiad、Materialize | 修改上游参数后仅传播 Delta |
| **知识图谱 k-hop 遍历优化** | 图数据库 | 家族血缘、国家同盟等复杂关系查询 |

## 3. 创新方向

1. **增量分支计算**：基于 main 分支快照 + 差分数据流，平行宇宙的计算成本从 O(N) 降到 O(log N)
2. **时空批处理引擎**：NumPy/GPU Compute Shader 矩阵化时间步进，一次性求解 10000 个城邦 × 100 年
3. **双模存储**：空间实体（ECS 连续内存数组）+ 抽象实体（图数据库/内存邻接表）

## 4. 命名

**MOLTKE** = **M**ulti-scale **O**ntology and **L**ogic **T**raversal **K**nowledge **E**ngine

致敬老毛奇（Helmuth von Moltke the Elder）与现代总参谋部制度，与 P 社 Clausewitz Engine 形成军事哲学对仗。
