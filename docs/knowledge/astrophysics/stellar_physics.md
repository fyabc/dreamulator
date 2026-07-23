# 恒星物理

> 从 `src/dreamulator/engine/stellar_physics.py` 抽取。  
> 实现参考：`stellar_physics.py:mass_luminosity_zams()`, `stellar_physics.py:mass_radius_zams()`

---

## IAU 2015 太阳参考常数

| 常数 | 符号 | 值 | 来源 |
|------|------|-----|------|
| 太阳有效温度 | $T_\odot$ | 5772 K | Prša et al. (2016) |
| 太阳光度 | $L_\odot$ | $3.828 \times 10^{26}$ W | IAU 2015 B3 |
| 太阳常数 (1 AU) | $S_\odot$ | 1361 W/m² | IAU 2015 B3 |
| 天文单位 | AU | $1.496 \times 10^{11}$ m | IAU 2015 B3 |
| Stefan-Boltzmann 常数 | $\sigma$ | $5.670 \times 10^{-8}$ W m⁻² K⁻⁴ | — |

---

## 质光关系（ZAMS）

> 实现：`stellar_physics.py::mass_luminosity_zams()`  
> 参考：Kippenhahn & Weigert (2012), *Stellar Structure and Evolution*

四段分段幂律近似（Kippenhahn 四段 MLR）：

$$L/L_\odot = \begin{cases} 0.23 \cdot M^{2.3} & M < 0.43 M_\odot \\ M^{4.0} & 0.43 \leq M < 2.0 M_\odot \\ 1.4 \cdot M^{3.5} & 2.0 \leq M < 20 M_\odot \\ 3200 \cdot M & M \geq 20 M_\odot \end{cases}$$

### 主序星年龄修正

$$L(M, t) = L_{\text{ZAMS}}(M) \cdot (1 + 0.4 \cdot \tau / \tau_\odot) / 1.184$$

其中 $\tau_\odot = 0.46$ 为太阳演化进度参数，分母 1.184 确保太阳在当前年龄的输出为 1。

---

## 质径关系（ZAMS）

> 实现：`stellar_physics.py::mass_radius_zams()`  
> 参考：Demircan & Kahraman (1991), Ap&SS, 181(2), 313-322

$$R/R_\odot = \begin{cases} 0.85 \cdot M^{0.8} & M < 1.0 M_\odot \\ M^{0.57} & M \geq 1.0 M_\odot \end{cases}$$

年龄修正：
$$R(M, t) = R_{\text{ZAMS}}(M) \cdot (1 + 0.3 \cdot \tau / \tau_\odot) / 1.138$$

---

## 主序星寿命

$$t_{\text{MS}} = 10^{10} \cdot \frac{M}{L} \text{ 年}$$

其中 $M, L$ 以太阳单位表示。大质量恒星寿命远短于小质量恒星。

---

## 有效温度

$$T_{\text{eff}} = T_\odot \cdot \left(\frac{L}{R^2}\right)^{1/4}$$

由 Stefan-Boltzmann 定律 $L = 4\pi R^2 \sigma T_{\text{eff}}^4$ 反推。

---

## 宜居带

> 实现：`stellar_physics.py::habitable_zone_bounds()`  
> 参考：Kopparapu et al. (2013), ApJ, 765(2), 131

基于 Kopparapu 2013 模型的宜居带边界拟合：

| 边界 | 说明 |
|------|------|
| Recent Venus | 内边缘 — 失控温室效应阈值 |
| Runaway Greenhouse | 保守内边缘 |
| Maximum Greenhouse | 外边缘 — CO₂ 最大温室效应极限 |
| Early Mars | 保守外边缘 |

边界位置 $d = \sqrt{L/L_\odot \cdot S_{\text{eff}}}$，其中 $S_{\text{eff}}$ 为各边界的有效恒星通量（由多项式拟合恒星温度）。

### 谱型-温度映射

| 光谱型 | $T_{\text{eff}}$ (K) |
|--------|---------------------|
| O | ≥ 30000 |
| B | 10000 – 30000 |
| A | 7500 – 10000 |
| F | 6000 – 7500 |
| G | 5200 – 6000 |
| K | 3700 – 5200 |
| M | 2400 – 3700 |

---

## 相关文档

- `knowledge/astrophysics/orbital_mechanics.md`（待创建）
- `knowledge/planetary_science/`（待创建）
- 代码：`src/dreamulator/engine/stellar_physics.py`

## 参考资料

- Kippenhahn, R., Weigert, A., & Weiss, A. (2012). *Stellar Structure and Evolution*. Springer.
- Demircan, O., & Kahraman, G. (1991). *Ap&SS*, 181(2), 313-322.
- Kopparapu, R. K., et al. (2013). *ApJ*, 765(2), 131.
- Prša, A., et al. (2016). IAU 2015 Resolution B3. *AJ*, 151(5), 123.
