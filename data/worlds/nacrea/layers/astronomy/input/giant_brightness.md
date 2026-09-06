---
title: "巨行星亮度与光照参数"
type: stellar
tags: [illumination, eclipse, albedo]
---

# 巨行星亮度与光照参数

### 自变量

| 参数 | 值 | 备注 |
|------|-----|------|
| Aegis 几何反照率 A_g | 0.228 | Sudarsky et al. (2000) Class II/III 过渡区；碱金属（Na, K）蒸气在可见光波段强吸收，近红外水冰/氨冰云散射较高 |
| 地球满月参考照度 | 0.0034 W/m² | 亮满月 −12.74 等、太阳 −26.74 等、太阳常数 1361 W/m² 反推 |

### 因变量

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 恒星在 Aegis 处的辐照度 | **{{ entities.satellite_nacrea.instellation_w_m2 | round0 }} W/m²** | L_star / (4πa_p²)；L={{ entities.star_ignis.luminosity_sol }} L☉, a={{ entities.planet_aegis.semi_major_axis_au }} AU |
| Aegis 满相照度（Nacrea 表面） | **{{ sky.planet_aegis.illuminance_full_w_m2 | round2 }} W/m²** | F_star × A_g × (R_p/a_m)²，A_g = 0.228 |
| 满相 = 地球满月倍数 | **约 {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034) | round0 }} 倍** | {{ sky.planet_aegis.illuminance_full_w_m2 | round2 }} / 0.0034 |
| 半相（90°）= 地球满月倍数 | **约 {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034 * 0.318) | round0 }} 倍** | × 朗伯相位函数 Φ(90°)=0.318 |
| 极细相（170°）= 地球满月倍数 | **约 0.3 倍** | × Φ(170°)≈5.7×10⁻⁴ |
| Aegis 视直径 | **{{ sky.planet_aegis.angular_diameter_deg | round2 }}°** | 2 arctan(R_p/a_m)；地球月球仅 0.52°，面积比 ~{{ ((sky.planet_aegis.angular_diameter_deg / 0.52) ** 2) | round0 }} 倍 |
| 满相可见光照度（估算） | **~111 lux** | 民用暮光 ~10 lux；足以投射清晰阴影，支持微弱光合作用 |

### 日食可见性的地理隔离

由于 Nacrea 被 Aegis 潮汐锁定，Aegis 在天空中的位置由经度**绝对固定**：

| 区域 | 经度范围 | Aegis 天空位置 | 日食可见性 |
|------|---------|---------------|-----------|
| **向星区 (Sub-Jovian)** | −45° ~ 45° | 天顶附近 | ✅ 食季内每个公转周期一次全食（每次最长 ~{{ sky.eclipse.max_total_eclipse_hours | round1 }}h） |
| **边缘区 (Limb)** | 45° ~ 90° / −45° ~ −90° | 贴近地平线 | ✅ 带食日出/日落 |
| **背星区 (Anti-Jovian)** | 90° ~ 180° / −90° ~ −180° | 永远在天底 | ❌ **物理上绝对无日食**（Aegis 永远在观测者背面） |

---
