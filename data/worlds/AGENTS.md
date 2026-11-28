# 世界数据（data/worlds/）规则

本目录是所有世界实例的数据根。本文件承接根目录 `AGENTS.md` 拆出的世界内容
写作规则；世界目录结构、层级/分支系统与构建命令见根目录。

## 模型态 vs obs 态分离（earth root = 真实数据锚，永不 build）

`earth` 是**真实地球参照世界**（reference baseline），不是「模型的地球」。硬规则：

- **root 的 `maps/planet_earth/cvt_mesh.json` 绝对只含真实地球数据**：ETOPO1 高程、
  真实板块边界、海陆掩膜，以及 `import_earth_climate` 导入的真实观测 obs 态字段
  （ERA5 / GPCP / Beck / SODA）。
- **所有模型算出的字段**（`temperature_C` / `precipitation_mm` / `koppen_class` 等）
  **只写在分支上**（`earth/branches/climate-dev` 等），绝不写进 root。
- **earth root 永不 build**：模型字段宁可空缺，也绝不用生成值填充。前端/验证
  读不到 root 的模型字段时，报「缺失」并指向分支，而不是触发一次 root build。

## 对外设定 vs 设计笔记的划分（作者 2026-10-07 裁决）

**对外设定** = `layers/*/input/*.md` 全文 + yaml 的 `description` 等叙事字段
（会渲染给读者/前端/视频）。标准：

1. 只写世界内现行状态，平实完整句、解释术语、忌电报体；
2. **现实天体/地球类比不入文**（太阳系/地球专名只进设计笔记）；面向读者的
   **单位参照**合法（「0.69× 满月宽」这类换算帮助，不是世界内命名）；
3. **豁免/审计叙事不入文**：被叙事豁免覆盖的事件（死期、失稳、末世天象）与
   工程过程语（REBOUND、抽签、认证跑、MEGNO 等）只进设计笔记；对外只写正面
   正典 + 一句 design-notes 指针；
4. **数值优先模板化**：引擎目录有字段的量用 `{{ entities.* }}`/`{{ sky.* }}`
   渲染；目录没有的允许硬编码，但正典变更时必须全库同步；yaml 注释不留
   历史叙事。

**设计笔记**（design-notes/、docs/design/、docs/knowledge/）承载决策理由、
实验记录、类比、审计值与工程红线；旧结果只留在文首「更新历史」块；文风
同样平实完整句（根目录 AGENTS.md「文风」节）。
