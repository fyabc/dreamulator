# 潮汐加热 → 板块速度标度律

## 核心概念

潮汐加热（或任何内部热源）通过驱动地幔对流来驱动板块运动。物理链：

$$\text{潮汐加热 }\dot{E} \;\to\; \text{地幔热流 } q \;\to\; \text{瑞利数 } Ra \;\to\; \text{对流强度} \;\to\; \text{板块速度 } v$$

经典边界层理论给出 `Nu ∝ Ra^(1/3)`（热流 `q ∝ Ra^(1/3)`）与 `v ∝ Ra^(2/3)`。
消去 Ra 即得**热流与板块速度的幂律**：

$$v = v_\oplus \left(\frac{q}{q_\oplus}\right)^{\beta}$$

其中 `v_⊕ ≈ 5 cm/yr`（地球平均板块速度）、`q_⊕ ≈ 0.09 W/m²`（地球总表面热流，47 TW）。

## β 的取值范围与争议

**β 不存在唯一"官方"值，跨文献从 0.5 到 2 不等：**

| β | 出处 | 说明 |
|---|------|------|
| 2 | 纯边界层理论（自由对流，忽略板块强度） | `v ∝ Ra^(2/3) ∝ q²`；对真实板块偏高 |
| ~1 | 多数热演化 / 有限强度板块模型 | 线性标度，本项目默认 |
| 0.5 | 含板块形变耗散的模型 | 板块强度削弱对流-热流耦合 |
| <1/3 或失效 | 粘性弯曲 / 脆性剪切耗散主导时 | 简单参数化对流幂律不再成立 |

关键因素（Foley & Bercovici 2014）：颗粒损伤（grain-damage）使 β **大于** 1/3（更多损伤
→ 更强对流），而板块形变耗散使 β **小于** 1/3 甚至失效。因此标度律是**区域依赖**的
（静止盖 / 迟缓盖 / 活动盖 / 过渡态各不相同）。

## 争论：Valencia vs O'Neill & Lenardic

这是系外行星板块构造领域一场著名的方向性分歧（均针对"更大行星是否更易有板块构造"，
但其核心——热流如何映射到板块活动——直接关系本标度律）：

- **Valencia & O'Connell (2009)**：用解析标度律，认为行星越大（质量越大）→ 热流越高 →
  对流应力越强 → 岩石圈相对更薄 → **板块构造更易维持**。结论：驱动/阻力之比随质量增大。

- **O'Neill & Lenardic (2007)**：用数值模拟，认为大质量行星的**压力随深度增加更快** →
  断层强度更高 → 岩石圈更强 → **倾向静止盖**。结论与 Valencia 相反。

- **van Heck & Tackley (2011)** 用解析 + 3D 数值（StagYY）调和：对**内部加热对流**，
  板块构造对行星大小**同等可能**；对**基底加热对流**则随大小**更可能**。并指出压力依赖的
  粘度/热膨胀/热导率可能反向作用。综述共识：除 O'Neill & Lenardic 外，多数研究认为
  **更大行星（其它条件相当，尤其有表面液态水）更有利于板块构造**（Korenaga 2010、
  Foley et al. 2012 支持此方向）。

**对本项目的教训**：热流只是**必要条件**，不是**充分条件**。

## 三个必须牢记的陷阱

1. **金星悖论**：金星热流 0.07 W/m² ≈ 地球，却是静止盖（无板块）。板块构造是否发生还取决于
   水（降低屈服强度）、岩石圈强度、地表温度。**幂律只在"板块构造已运行"的前提下成立**——
   对 Gaia-M 这本身是外推假设。

2. **太阳系无"潮汐加热的岩石行星有板块构造"的观测先例**：木卫一（Io）潮汐热流 2.4 W/m²，
   是"热管火山"而非板块。所以「潮汐加热 → 板块构造」是从地幔对流理论外推的假设，
   不是观测事实。

3. **β 与归一化均不确定（因子 2–3）**：`v_⊕` 取平均（5）还是最快（10）板、`q_⊕` 取总热流
   （0.09）还是地幔对流热流（~0.06），都改变结果。潮汐加热深部集中（挠曲耗散），
   可能比放射性加热（分散）更有效地驱动对流——这是支持 β 偏高的论点，但未定论。

## 在本项目（dreamulator）中的应用

- 实现：`src/dreamulator/engine/tidal_physics.py`（纯函数）+ `physical_inputs.py:resolve_tidal_heating`
  （读 stellar.yaml 的 e、a、母体质量 → 算 Ė → 算 v）。
- 默认参数：β=1.0、`v_⊕`=5 cm/yr、`q_⊕`=0.09 W/m²，v 以 0.5 cm/yr 粒度取整。
- **gaia-m**：q_tidal ≈ 0.27 W/m² = 3× 地球 → v = 5 × 3 = **15 cm/yr**（β=1.0 自然给出，
  保持手写终值不变）；半扩张速率 = 0.4 × 15 = 6 cm/yr。
- 定位：**自洽性校验 + 可调参数**，非精确预测。3.3× 与 3.0× 的 10% 差异远小于 Q（±50%）
  与 β 的不确定，故不为追求整数倍数而微调参数。

## 参考资料

- Foley, B. J., & Bercovici, D. (2014). Scaling laws for convection with temperature-dependent
  viscosity and grain-damage. *Geophysical Journal International*, 199(1), 580.
  https://academic.oup.com/gji/article/199/1/580/733317 （arXiv:1410.7652）
- Valencia, D., & O'Connell, R. J. (2009). Convection scaling and subduction on Earth and
  super-Earths. *Earth and Planetary Science Letters*, 286(3–4), 492.
  https://ui.adsabs.harvard.edu/abs/2009E%26PSL.286..492V/abstract
- van Heck, H. J., & Tackley, P. J. (2011). Plate tectonics on super-Earths: Equally or more
  likely than on Earth. *Earth and Planetary Science Letters*, 310(3–4), 252.
  https://www.sciencedirect.com/science/article/abs/pii/S0012821X11004559
- O'Neill, C., & Lenardic, A. (2007). Geological consequences of super-sized Earths.
  *Geophysical Research Letters*, 34(19).（Valencia 争论的对立面）
- Turcotte, D. L., & Schubert, G. (2014). *Geodynamics* (3rd ed.). Cambridge University Press.
  （边界层理论：`Nu ∝ Ra^(1/3)`、`v ∝ Ra^(2/3)`）
