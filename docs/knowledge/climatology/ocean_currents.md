# 洋流物理学

表层洋流的两大驱动机制（风生与热盐）、海峡"闸门"动力学与年际变率。
本文是 roadmap 3A.3（洋流 + 温度精细化）的科学底座。

## 1. 风生环流

### 1.1 Ekman 层

风应力通过科氏力驱动表层流：表面流偏向风向 **45°**（北半球右偏、南半球左偏），
深度积分的 Ekman 输运偏风向 **90°**；表层流速约为风速的 **2%**。

```
u_surface ≈ 0.02 · |wind|,  direction = rotate(wind, ±45°·sign(φ))
```

源码：`engine/climate_physics.py:ekman_current_direction()`（已实现、当前零引用——
3A.3 的接入点）。

### 1.2 Sverdrup 平衡与西边界强化

大洋内部经向输运由风应力旋度控制（Sverdrup 1947）：

```
β · V = curl_z(τ) / ρ₀        β = df/dy（Rossby 参数）
```

Sverdrup 输运在西岸集中返回，形成**西边界强化**暖流（Gulf Stream / 黑潮型，
Stommel 1948 的 β 项 + 底摩擦机制；宽度 ~100 km、流速 ×3–10）。
3A.3 参数化方向：环流圈西侧流速 ×3（见 roadmap §4 3A.3 表）。

### 1.3 环流圈形态

副热带环流圈（信风 + 西风驱动）约以 ±30° 为中心；高纬为副极地环流。
慢自转行星（科氏力弱）环流圈尺度更大、西边界更宽——gaia-m（Ω=0.31 Ω⊕）
的环流形态不应照地球五圈模板。

## 2. 热盐环流（温盐环流）

密度差（温度 + 盐度）驱动的深层环流，时间尺度千年。对世界构建而言重要的不是
环流本身，而是它的**多稳态**：

### 2.1 Stommel 两盒模型

两个互通水盒（赤道暖盒 / 极地冷盒），温度与盐度对密度的贡献相反时，存在
**两个稳定分支**（温度主导的"强环流"与盐度主导的"弱/反转环流"），
 freshwater 微扰可触发跃迁（Stommel 1961；Cessi 1994 给出含噪声的跃迁阈值）。

**世界构建用途**：气候临界态的现成机制——海峡开合 / 冰盖融水 = 微扰源，
环流"开/关" = 两种气候态（年轻地球事件、Heinrich 事件的类比）。

## 3. 海峡"闸门"动力学

地形约束的通道能通过少量但关键的热/盐输送，且对几何与海平面高度敏感：

| 地球案例 | 机制 | 气候后果 |
|----------|------|----------|
| **印尼贯穿流（ITF）** | 太平洋→印度洋唯一低纬通道，~15 Sv 暖水；流量受海峡宽度/深度与两侧压差控制 | 调制两大洋 SST 梯度与 ENSO/IOD 耦合（Wijffels et al. 2008） |
| **巴拿马地峡闭合**（~3 Ma） | 切断太平洋-大西洋表层交换 | 湾流强化 → 北欧变暖加湿 + 北半球冰期启动的争论案例 |
| **德雷克海峡开启**（~34 Ma） | 环极通道 → 绕极流（ACC）隔离南极 | 南极冰盖形成 |
| **冰期海平面闸门** | 海平面 −120 m → 巽他陆架暴露、ITF 通道近乎关闭 | 通道截面积对海平面呈非线性响应 |

**临界性三要素**（构造"小因大果"剧情的检查单）：
1. 几何瓶颈——流量 ∝ 通道截面积，浅峡（<200 m）对海平面/沉积/火山岛敏感；
2. 双稳态背景——热盐或风生环流存在两种构型；
3. 微扰放大器——周期性强迫（潮汐、季节）或单事件（地震、岛弧火山）触发跃迁。

源码/设计接口：geography.yaml 的 `isthmus`/`shallow_sea` feature + 高程锚定
（需 `depth_m` 级浅海控制，见 `private/plans/heightmap-import-vs-geography-config.md` §4）。

## 4. 年际变率：ENSO 类振荡

海气耦合反馈（Bjerknes 1969）：信风减弱 → 东太平洋暖水东涌 → 信风进一步减弱。
产生 2–7 年准周期振荡，无需外部强迫（自激振荡）。**大陆把大洋割裂成半孤立水体时，
振荡幅度放大、周期失谐**——虚构先例：乐意 Ajax《季风世界》的"涛动期"
（洋流翻转周期 4 月–10 年不可预测，见
`private/plans/video/leyi-ajax-monsoon-world-analysis.md`）。

对 dreamulator：稳态 EBM 无年际模态；最小可行版 = 风应力与温度梯度博弈的
双驱动表层流 + 海峡水力学约束流（roadmap 3A.3）。

## 5. 与引擎的对应关系

| 知识 | 引擎模块 / 计划 | 状态 |
|------|----------------|------|
| Ekman 偏转 45° / 流速 2% | `climate_physics.py:ekman_current_direction()` | ✅ 已实现、待接入 |
| 西边界强化 / 沿岸热输送 | roadmap 3A.3 子任务表 | 📋 |
| 上升流（东边界离岸风） | roadmap 3A.3 子任务表 | 📋 |
| 海峡水力学约束流 | 问题 1 方案 §4（临界洋流） | 📋 设计 |
| 海洋省份子省（WBC/EBC/GYRE…） | 3A.5 Phase 2，见 `ocean_provinces.md` | 📋 |
| 热盐多稳态 / ENSO 时变 | 长期愿景（简化 GCM 之后） | ❌ |

## 参考资料

- Stommel, H. (1948). "The theory of the electric field induced in deep ocean currents."
- Stommel, H. (1961). "Thermohaline convection with two stable regimes." *Tellus 13*.
- Cessi, P. (1994). "A simple box model of stochastically forced thermohaline flow." *JPO 24*.
- Sverdrup, H. (1947). "Wind-driven currents in a baroclinic ocean." *PNAS 33*.
- Wijffels, S. et al. (2008). "Changing Exchanges in the Maritime Continent." *Oceanography 21*.
- Bjerknes, J. (1969). "Atmospheric teleconnections from the equatorial Pacific." *MWR 97*.
