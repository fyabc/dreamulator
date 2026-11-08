# 行星发电机标度律（气巨磁场估算）

> 从 `src/dreamulator/engine/planet_dynamo.py` 抽取。实现参考：
> `planet_dynamo.py::estimate_magnetic_field_ut()`（估算）、
> `physical_inputs.py::_annotate_magnetic_fields()`（catalog 注记与一致性校验）。
> 用途：`system_catalog.yaml` 的 `derived.magnetic_field_estimate_ut` /
> `magnetic_dipole_moment_am2` / `parent_magnetic_field_at_orbit_ut`，
> 与 `planets.yaml` 手写 `magnetic_field_strength`（μT）互为对照——手写值权威，
> 偏差超 20% 出 warning（与恒星质量-光度校验同一纪律）。

## 物理来源

Christensen, Holzwarth & Reiners (2009, Nature 457, 167) 的能量通量标度律：快速
自转（饱和、偶极主导）区里，发电机均方根场强由**对流可用能流**与密度决定，
与自转率、磁扩散率无关：

$$\langle B\rangle^2 / (2\mu_0) = c \cdot f_{\rm ohm} \cdot \langle\rho\rangle^{1/3} \cdot (F q_0)^{2/3}, \quad c = 0.63$$

以体密度 $\langle\rho\rangle \approx 3M/(4\pi R^3)$、发电机顶对流通量
$q_0 \propto L/R^2$ 代入，相对木星化为比值式：

$$B / B_J = (M/M_J)^{1/6} \, (L/L_J)^{1/3} \, (R_J/R)^{7/6}$$

**木星单点锚定**（B_J = 428 μT，Connerney 1993）把结构效率因子 F 与内部场→
表面偶极换算（⟨B⟩/B_dip ≈ 7、发电机顶 0.84R）全部吸收进一个标定点，因此只有
光度表的**比值**进入计算——COND03 表对木星整体偏亮 ~5× 的零点误差在比值中
精确抵消。

## 常数表

| 常数 | 值 | 来源 |
|------|-----|------|
| 木星表面赤道偶极场 B_J | 428 μT | Connerney 1993（论文 ref 18） |
| 木星半径 R_J | 69,911 km | IAU 名义平均半径 |
| 木星质量 M_J | 317.8 M⊕ | IAU 名义值比 |
| 标度常数 c | 0.63 | Christensen 2009 数值模拟拟合 |
| 内部/偶极场比 | ≈ 7 | 地球型功率谱发电机模拟 |
| 内禀光度表 | COND03 5×5 log-L 网格 | Baraffe et al. 2003（0.5–10 M_J × 0.1–10 Gyr，双对数双线性插值，域外钳边） |

光度表精度约 ×2（热启动、无云模型）；标度律取 L^(1/3)，传播到场强约 ±25%。

## 适用域（文档化，不静默施加）

- **适用**：快速自转流体发电机——气巨行星。catalog 侧门 = `planet_type ==
  gas_giant` 且自转周期 ≤ 3 天；类地核发电机（地球、Nacrea）在域外，保持纯手写。
- **排除**：土星型稳定分层导电层、天/海型薄壳发电机（原文明确排除）；单点锚定
  无法表达这些结构。
- **已知偏低**：锚定不含发电机深度随质量的变化，5–10 M_J 年轻巨行星估算比
  原文预测（5–12× 木星）低约 1.5×——实测横检 5 M_J @ 1 Gyr 得 3.7×。

## 验证锚点

| 检验 | 结果 |
|------|------|
| 木星锚定回归 | 表内一致木星输入 → 428 μT 精确复现（构造性） |
| 文献横检 | 5 M_J @ 1 Gyr → 3.7× 木星（原文 5–12×，低端符合预期偏差） |
| nacrea 手算复核 | 400 μT @ 71,355 km → 偶极矩 1.453×10²⁷ A·m²；Nacrea 轨道处 0.384 μT——均与 `coupled_magnetic.md` 手推导逐位一致 |
| nacrea 实测 | Aegis（1.6 M_J、5.9 Gyr）估算 **650 μT**，作者 2026-11-09 采纳为正典（planets.yaml 同步 650，偏差 0.08% 无警告） |

## 学术参考

- Christensen, U. R., Holzwarth, V., & Reiners, A. (2009). Energy flux
  determines magnetic field strength of planets and stars. *Nature*, 457,
  167-169. doi:10.1038/nature07626
- Baraffe, I., Chabrier, G., Barman, T. S., Allard, F., & Hauschildt, P. H.
  (2003). Evolutionary models for cool brown dwarfs and extrasolar giant
  planets. *A&A*, 402, 701-712.（COND 等时线；数字化表
  <https://perso.ens-lyon.fr/isabelle.baraffe/COND03_models>）
- Connerney, J. E. P. (1993). Magnetic fields of the outer planets.
  *J. Geophys. Res.*, 98, 18659-18679.
