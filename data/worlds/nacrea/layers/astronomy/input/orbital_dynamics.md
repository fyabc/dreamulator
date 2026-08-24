---
title: "Nacrea 轨道动力学"
type: orbital
tags: [orbit, eclipse, seasons, resonance]
---

# 卫星 Nacrea — 轨道动力学

### 自变量

| 参数 | 值 | 备注 |
|------|-----|------|
| 卫星轨道倾角 i | {{ entities.satellite_nacrea.axial_tilt_deg }}° | 卫星轨道面与黄道面夹角（黄道面 = Aegis 绕恒星轨道面，系统参考平面） |
| 轨道偏心率 e | **0.002** | 由 Cadence/Vigil 卫星拉普拉斯共振链泵浦维持（受迫偏心率，见 satellite_architecture.md） |
| 1:2:4 行星共振 | 三颗巨行星构成拉普拉斯共振 | 防止巨行星坠入主星，维持巨行星偏心率不衰减 |

### 因变量

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 黄赤交角 | {{ entities.satellite_nacrea.axial_tilt_deg }}° | 卫星被巨行星潮汐锁定 → 自转轴垂直于轨道面 |
| 回归线 | 南北纬 {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° | |
| 极圈（极昼极夜界限） | 南北纬 {{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}° | 极点极昼/极夜各约 **{{ entities.satellite_nacrea.polar_day_at_pole_days | round1 }} 天**（半年各半） |
| 季节周期 | **{{ entities.planet_aegis.period_days | round0 }} 天** | 等于巨行星公转周期（轨道内移至 {{ entities.planet_aegis.semi_major_axis_au }} AU 后）；每季约 **{{ entities.satellite_nacrea.season_length_days | round2 }} 天** |
| 太阳日 | **{{ entities.satellite_nacrea.solar_day_days | round2 }} 天（{{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 小时）** | 1/(1/{{ entities.satellite_nacrea.rotation_period_days }} − 1/{{ entities.planet_aegis.period_days | round0 }})；自转与周年运动同向 |
| 一年太阳日数 | **{{ entities.satellite_nacrea.days_per_year | round1 }} 个** | 季节嵌在"天气尺度"：昼夜 {{ entities.satellite_nacrea.solar_day_days | round1 }} 天 / 季节 {{ entities.satellite_nacrea.season_length_days | round2 }} 天 / 年 {{ entities.planet_aegis.period_days | round0 }} 天三重嵌套 |
| 视差摆动 | ±1.04°（视太阳时 ±14 分钟） | 绕 Aegis 公转半径 74 万 km 对恒星方向的调制，周期 {{ entities.satellite_nacrea.rotation_period_days }} 天 |
| 最大垂直偏移 | 115,722 km | 倾角导致卫星在轨道最高点距黄道面的垂直距离 |
| 日食遮蔽率 | 2.1% | 全年 {{ entities.planet_aegis.period_days | round0 }} 天中约 48 天无日食 |
| 日全食季 | 每年 2 次，每次 ~11 天 | 每 {{ entities.satellite_nacrea.period_days | hours | round0 }}h 穿过本影一次，约 3–4 次日全食（每次~2.3h，全向星半球同时入夜） |
| 日偏食季 | 每年约 2 次 | |
| 外侧行星 2 轨道 | **0.3975 AU** | 共振 2:1 → 0.2504 × 2^(2/3) |
| 外侧行星 3 轨道 | **0.631 AU** | 共振 4:1 → 0.2504 × 4^(2/3) |
| 卫星轨道外迁速率 | ~1.7 m/年 | 角动量正向传递（巨行星自转快于卫星公转） |

---
