# 地壳均衡与高程极限

> 为 dreamulator 地形合成（`terrain_synthesizer.py`）提供物理上界约束的依据。
> 当前 nacrea 无高程限制：陆 Max=10770 m、海 Max=16593 m——均远超均衡极限。

---

## 1. 均衡理论概述

### 1.1 Airy 均衡（1855）

地壳像木筏"漂浮"在更致密的地幔上。山脉有深的"山根"（低密度地壳增厚入地幔）：

```
山根深度 r = h · ρc / (ρm − ρc)
```

其中 h = 地表高程，ρc = 地壳密度 (~2800 kg/m³)，ρm = 地幔密度 (~3300 kg/m³)。

**数值例**：5 km 高原（如青藏）→ 山根 r = 5 × 2800/(3300−2800) ≈ 28 km → 总地壳厚 ~35（正常）+ 28 = **63 km**。
这与现代地震测量（青藏高原南缘 75–85 km 地壳厚度）一致。

### 1.2 Pratt 均衡（1859）

地壳密度侧向变化——高地由低密度物质组成，海底由高密度物质组成。补偿面在同一深度。

两种模型的差异在实践中被**弹性挠曲**统一——岩石圈有限强度使其不完全均衡，而是部分支撑荷载。

---

## 2. 大陆最大高程：强度极限

### 2.1 基本公式

山脉高度的物理上限由**岩石强度 vs 重力应力**的平衡决定（Scheuer 1981）：

```
h_max ∝ Y / (ρ g)
```

| 参数 | 含义 | 地球值 |
|------|------|--------|
| Y | 屈服强度（岩石支撑应力） | ~100–200 MPa（地壳岩石） |
| ρ | 地壳密度 | ~2800 kg/m³ |
| g | 表面重力 | 9.81 m/s² |

数值系数取决于山体几何（方锥/长脊/缓丘），量级 O(1–10)。

**关键结论**：`h_max ∝ 1/g`——重力越高，极限高度越低。同种岩石，0.5g 的行星可以支撑 2× 高度的山。

### 2.2 地球的极限 ≈ 8.8 km

珠穆朗玛峰 8848 m 接近物理极限。进一步的高度受限于：
- 岩石圈在荷载下的屈服和蠕变
- 冰川侵蚀（"冰川锯"假说：冰川平衡线高度(ELA)压制山脉最大高程）在高纬区限制更显著
- 山根达到地幔熔融深度 → 相变浮力消失

### 2.3 对 nacrea 的计算

nacrea 参数：g = 10.28 m/s²（1.05 g⊕），R = 6817 km。

```
h_max(nacrea) ≈ h_max(Earth) × (g⊕ / g_gaia) × 修正因子

基准：8848 × (9.81 / 10.28) ≈ 8440 m  （仅考虑重力差，−5%）

修正因子（下调）：
  - 更高地质活动 → 更高地温梯度 → 更薄岩石圈 → 更低 Y → −10% ~ −25%
  - 综上：h_max 预计在 ~6300–8000 m 范围
```

**当前 nacrea 最高 10770 m → 超出预期上限约 35–70%。**

---

## 3. 大洋最大深度：挠曲极限

### 3.1 双层结构

大洋深度由两个机制叠加：

| 机制 | 深度范围 | 物理 |
|------|---------|------|
| **稳态（均衡）沉降** | ≤ 5.5–6 km | 大洋岩石圈随年龄冷却增厚沉降（半空间/板块冷却模型） |
| **动态俯冲挠曲** | 额外 3–5 km | 俯冲板片负浮力 → 板块弹性弯曲下凹 → 海沟超深 |

总深度 ≈ 6 km（基准） + 海沟挠曲量。

### 3.2 海沟深度极限

由**板片的弯曲强度 + 负浮力**平衡决定：

- 板片负浮力 ∝ Δρ（板片−地幔密度差）× g × 板片体积
- 弯曲抵抗 ∝ 弹性厚度 Te（~20–30 km）× 杨氏模量
- **高 g 行星：负浮力更强 → 海沟可更深**
- **高热梯度行星：Te 更薄 → 弯曲抵抗更弱 → 海沟更浅**

两种效应竞争。地球海沟最深 ~11 km（马里亚纳），已接近理论极限（研究发现挑战者深度的板片弯曲异常紧——"bending is unusually tight"——说明不能再深太多）。

### 3.3 对 nacrea 的计算

```
h_trench(nacrea) ≈ 6 km（均衡基准）+ Δh_flexure × (g_gaia/g⊕ 竞争)
```

- 高 g → 板片负浮力 +5%（更深）↔ 高热梯度 → Te 变薄 + 弯曲更弱（更浅）
- 净效应不确定，但 **16.6 km 的海沟深度在物理上不成立**——这需要 ~10 km 的挠曲量，对应地幔密度差远超岩石物理

**当前 nacrea 海最深 16593 m → 超出地球海沟约 50%，物理上不可信。**

---

## 4. 实现建议

### 4.1 均衡补偿上限（soft cap）

在 `terrain_synthesizer.py` 中增加可选的高程裁剪：

```python
# 大陆均衡上限
max_elevation_m = config.isostasy.max_continental_elevation_m  # 默认 9000, nacrea ~7500
elevation = np.clip(elevation, None, max_elevation_m)

# 海沟挠曲上限
max_trench_depth_m = config.isostasy.max_ocean_depth_m  # 默认 11500, nacrea ~12000
elevation = np.clip(elevation, -max_trench_depth_m, None)
```

**默认值不加裁剪**（保持旧行为），只在配置主动设置时生效。

### 4.2 物理裁剪（推荐，P2）

不只是硬 clip，而是用**均衡应力过载时加速侵蚀/崩塌**来软限制：

```python
isostatic_support = Y / (ρ * g)  # 强度极限
excess = np.maximum(elevation - isostatic_support, 0)  # 超出均衡的高度
# 超出部分按 rate 消减（模拟蠕变/崩塌/冰川削蚀）
elevation -= excess * config.isostasy.relaxation_rate  # 默认 0.1–0.3
```

此方式更物理——不会出现"突然截止"的平顶山。

### 4.3 配置接口

```yaml
# terrain_config.yaml 新段落（可选，默认关 = 保持旧行为）
isostasy:
  enabled: false
  crustal_density_kg_m3: 2800
  mantle_density_kg_m3: 3300
  max_continental_elevation_m: 9000    # 地球基准
  max_ocean_depth_m: 11500             # 地球基准
  relaxation_rate: 0.1                 # 超出均衡部分的消减率
```

### 4.4 nacrea 推荐值

基于 g=10.28 m/s² 和较高地质活动：
- `max_continental_elevation_m: 7500`（~1.05×重力削减 + 高热修正）
- `max_ocean_depth_m: 12000`（~1.05×高重力的更深板片 pull − 高热 Te 变薄）

---

## 5. 与地形的其他质量限制的兼容性

- **fBm 噪声幅度**（`noise_amplitude`）：当前 1200 m / 600 m——在均衡限内安全
- **geography.yaml 钉扎**（`elevation_target_m` + `pin_strength`）：钉扎值本身不会产生超高程，但可能与被 clip 的噪声叠加后冲突——均衡裁剪必须在钉扎**之后**执行
- **3B 侵蚀管线**（远期）：流水侵蚀自然削峰填谷——但如果 DEM 上有 10 km 的山，河流下切方程会算出荒谬的侵蚀速率。均衡上限应该**先于侵蚀**实施

---

## 参考

- Airy, G.B. (1855). "On the computation of the effect of the attraction of mountain-masses." *Phil. Trans. R. Soc. 145*.
- Scheuer, T. (1981). "How high can a mountain be?" *Journal of Astrophysics and Astronomy 2*.
- Stüwe, K. (2007). *Geodynamics of the Lithosphere* (2nd ed.). Springer. (Chapter 4: Isostasy)
- Turcotte, D.L. & Schubert, G. (2014). *Geodynamics* (3rd ed.). Cambridge. (Chapter 5: Flexure of the Lithosphere)
- Zhang, F. et al. (2026). "Unusually tight bending of subducting Pacific plate causes the extreme depth of Challenger Deep." *EPSL*.
- continuum-alpha issue #204 (GitHub): "Max elevation and plate thickness range are Earth-specific."
