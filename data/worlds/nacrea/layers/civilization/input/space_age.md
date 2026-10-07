---
title: "太空时代发展推演"
type: thematic
tags: [space-age, technology, magsail]
---

# 太空时代发展推演

## 核心轨道约束

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 逃逸速度 v_e | **11.85 km/s** | √(2GM_s/R_s)；地球 11.2 km/s |
| 第一宇宙速度 v₁ | **8.38 km/s** | √(GM_s/R_s)；地球 7.9 km/s |
| 同步轨道半径 r_sync | **{{ entities.satellite_nacrea.synchronous_orbit_radius_km | group }} km**（高度 {{ (entities.satellite_nacrea.synchronous_orbit_radius_km - entities.satellite_nacrea.radius_km) | group }} km） | (GM_sT_rot²/4π²)^(1/3) |
| Nacrea 希尔半径 R_H_s | **{{ entities.satellite_nacrea.hill_radius_km | group }} km**（{{ (entities.satellite_nacrea.hill_radius_km / entities.satellite_nacrea.radius_km) | round1 }} R_s） | a_m × (M_s/3M_p)^(1/3) |
| **GEO 存在性** | **❌ 不存在** | r_sync ({{ entities.satellite_nacrea.synchronous_orbit_radius_km | group }} km) > R_H_s ({{ entities.satellite_nacrea.hill_radius_km | group }} km)；任何超出希尔边界的卫星被 Aegis 潮汐力剥夺 |
| r_sync / R_H_s | **{{ entities.satellite_nacrea.synchronous_over_hill }}** | 同步轨道在希尔球外 44% |

## 科技树总表（地球对比框架见 design-notes/0011）

| 发展维度 | Nacrea | 核心物理根源 |
|---------|--------|-------------|
| **通信卫星架构** | **大椭圆轨道 / 低轨巨型星座** | GEO 物理不存在（r_sync > R_H_s） |
| **早期航天动力** | **核热推进 (NTR) 极早商用** | 1.05g 重力井 + 11.85 km/s 逃逸速度 + 强辐射带要求大防辐射屏蔽质量 |
| **抗辐射电子学** | **碳化硅 (SiC) 基抗辐射芯片 / 光学计算** | 巨行星辐射带狂暴，硅芯片频繁单粒子翻转 |
| **巨行星探测** | **磁帆 (Magsail) 悬停与无工质减速** | 距离极近（{{ (sky.planet_aegis.distance_km / 10000) | round1 }} 万 km，通信延迟 ~2.4 s）+ Aegis 强磁场：超导线圈与磁层等离子体相互作用实现无工质减速 |
| **内行星探测** | **红外帆 + Aegis 逆向引力弹弓** | 橙矮星光度弱（偏橙光峰值）但内行星距离近（0.26–0.32 AU）；去内行星需大幅减速 |
| **外行星探测** | **常态化通约链"引力弹弓列车"** | 1:2:4 周期通约链 → 极规律的低能量转移窗口；多目标飞掠成为常态 |
| **深空探索动机** | **纯粹资源开采与基础物理验证** | 主序寿命 {{ entities.star_ignis.ms_lifetime_gyr | round1 }} Gyr → 无生存焦虑，文明心态极度从容 |
| **航空技术** | **平流层巨型飞艇 / 太阳能滑翔机** | 弱科氏力 → 全球无台风 → 大气极其稳定；弥补 GEO 缺失的通信/气象中继需求 |

## 航空与低轨时代

- **航空**：自转缓慢（恒星自转周期 {{ entities.satellite_nacrea.period_days | hours | round1 }} 小时）使科氏力极弱，
  全球不存在任何热带气旋，大气长期保持极稳定的层流状态。翼展数百米的巨型
  平流层飞艇与太阳能滑翔机因此可以长期驻留在 20 km 高空，承担通信与气象
  中继（GEO 缺失的补偿）。
- **低轨航天**：Aegis 辐射带环境狂暴，早期硅基芯片在轨频繁发生单粒子翻转，
  倒逼碳化硅抗辐射芯片与光学计算在航天时代初期即成熟。
- **推进**：1.05g 重力井与 11.85 km/s 逃逸速度的组合使化学火箭运力严重
  不足，核热推进（NTR）在航天时代之初即被迫商用。

## Aegis 探测与磁帆技术

- Aegis 距离仅 {{ (sky.planet_aegis.distance_km / 10000) | round1 }} 万 km，单向通信延迟约
  2.4 秒，**实时遥控探测**在航天时代之初即可实现。
- Aegis 深层辐射带极强，催生了**磁层帆（Magsail）**：展开超导线圈产生人工
  磁场，与 Aegis 磁层的高速等离子体相互作用，实现无工质减速与轨道悬停。
- 借助磁帆，探测器可以深入 Aegis 极区磁层和光环系统。

## 星际探测

- **内行星**：Ember 的凌星以约 4.9 天的会合周期重现，地基望远镜借凌星光谱
  早已摸清 Crucible 的大气成分，探测目标极其明确；到达内行星依靠红外帆与
  Aegis 逆向引力弹弓减速。
- **外行星**：Aegis–Boreal–Glacis 处于 1:2:4 周期通约，相对位置极有规律，
  一条**低能量星际高速公路**贯穿整个系统；离子推进与核聚变推进成为深空
  运输主力。
- **外围天体**：墟带（主带 1.4–2.7 AU）、外散射盘与奥尔特云（~10³–6×10⁴ AU）
  是纯资源开采区（水冰、He-3），也是长基线引力波干涉测量的天然台址。
- **系外探索**：整个系统的尺度极小，突破摄星级纳米光帆阵列所需的加速轨道
  很短，文明可以向邻近恒星系发射大量微型探测器，构建传感器网络。
