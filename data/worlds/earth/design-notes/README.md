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
| [ucc-worked-examples.md](ucc-worked-examples.md) | Earth（NCEP/GPCP/Beck 观测） | UCC v1 × 33 真实地点 + 类中心点补位（4b 审阅清单，用户已通过） | `scripts/climate/ucc_examples_earth.py` |
| [ucc-worked-examples-mars.md](ucc-worked-examples-mars.md) | Mars（MOLA + MCD v6.1，L4） | 全行星 Pn（OOD 门全域）、continental 68%、P≡0 声明 | `scripts/solar/ucc_examples_solar.py --planet mars` |
| [ucc-worked-examples-moon.md](ucc-worked-examples-moon.md) | Moon（LDEM + Diviner GCP，观测态例外） | 地方时分箱、Cn/Pn 无热带、surface 温度契约声明 | `--planet moon` |
| [ucc-worked-examples-venus.md](ucc-worked-examples-venus.md) | Venus（Magellan + VCD v2.3，L4） | 全行星 Ra-w = 热侧外推缺口活体演示、近等温 | `--planet venus` |
| [ucc-worked-examples-titan.md](ucc-worked-examples-titan.md) | Titan（TAM 水文 run，L4，CC-BY） | bin=896 地球日时间契约极端案例、甲烷海 Po、MI 拒绝 | `--planet titan` |

均为脚本生成，勿手改。导入管线：`scripts/earth/`（地球）+ `scripts/solar/`
（四天体；数据缓存 `private/tmp/solar/`，LMD 抓取用 `fetch_lmd_slices.py`）。
