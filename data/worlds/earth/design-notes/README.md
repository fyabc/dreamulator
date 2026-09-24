---
title: "现实世界参照锚 · 派生文档"
type: overview
---

# Earth design-notes（现实世界参照锚）

`earth` 名字是历史遗留——这个世界实际是**现实世界数据锚**（reference anchor，
永不 build）：地球观测基线（NCEP/GPCP/Beck）+ 太阳系真实天体（Mars / Moon /
Venus / Titan，UCC-01 4d，作为额外 planet_ids 并入本世界而非单开伪世界；
天体 ID 沿用 stellar.yaml 约定，卫星用 `satellite_*`）。本目录存放从观测/
GCM 气候态数据读出的派生文档，不是架空设定 ADR（nacrea 的 design-notes/ 是
ADR 目录，两者定位不同）。

各天体 mesh cell 数按数据源精度定（声明于 world.yaml 注释）：
Earth 200k（2.5° obs）· Moon 100k（GCP 0.5°）· Mars 10k（MCD ~5.7°）·
Venus 10k（VCD ~1.9°）· Titan 3k（TAM T21 5.6°）。

| 文档 | 天体 / 数据源 | 内容 | 重生成 |
|------|--------------|------|--------|
| UCC worked examples（Earth/Mars/Moon/Venus/Titan） | — | **已迁至 `docs/ucc/examples/`**（2026-09-24 文档收拢） | `scripts/climate/ucc_examples_earth.py` / `scripts/solar/ucc_examples_solar.py` |

均为脚本生成，勿手改。导入管线：`scripts/earth/`（地球）+ `scripts/solar/`
（四天体；数据缓存 `private/tmp/solar/`，LMD 抓取用 `fetch_lmd_slices.py`）。
