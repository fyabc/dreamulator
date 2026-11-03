# 观测者天球框架（observer sky frames）

从「天体 + (lat, lon) + 时刻」到「天上有什么」的坐标系与约定。实现单一事实源 =
`src/dreamulator/engine/ephemeris.py`（sky-ephemeris 提案 M1）；本文记录其中的物理与
约定决策，供后续消费方（渲染、FUI、前端星图、历法）对齐口径。

## 1. 框架栈

| 框架 | 定义 | 用途 |
|------|------|------|
| 黄道框架 | catalog 参考面（`stellar.yaml`），右手系，+z 黄道北，恒星在其 `position`；内部单位 km | 轨道传播的公共坐标系 |
| 本体赤道框架 | z = 自转轴，x = 本赤道对黄道的**升交点**，y = z × x | 赤经/赤纬（RA 0 = 本体「春分方向」——地球春分点约定的推广） |
| 站心 ENU | up = (lat, lon) 球面径向（catalog 天体为球），north = 自转轴切面投影，east = north × up | 高度/方位（方位 0 = 北，顺时针向东） |

黄道→赤道的升交点取 `ẑ_ecl × z_axis` 归一；倾角为零时升交点退化，x 取黄道 x 轴
（赤纬仍精确）。黄道→ENU 的基向量见 `ephemeris.observer_frame_km`；高度/方位与
方向矢量的往返公式为 `alt = asin(d̂·up)`、`az = atan2(d̂·east, d̂·north)`。

## 2. 自转轴阶梯（-spin axis ladder）

按优先级解析，每级都是物理推导或声明的约定，不引入自由参数：

1. **潮汐锁定**（`derived.tidally_locked`）：轴 = 自轨道法向
   `n = (sin i · sin Ω, −sin i · cos Ω, cos i)`（角动量侧为北，逆行轨道同样如此），
   本初子午线 = **瞬时**指向主星的方向（Cassini 态 1，与
   `physical_inputs._synchronous_satellite_pole` 同物理）。关键纪律：**锁定天体忽略
   `rotation_period_days`**——catalog 的自转值可以与轨道周期漂移（nacrea 实测
   3.1336 vs 3.1383 d，catalog 自带漂移警告），锁定而非表格自转决定框架。本初子午线
   **瞬时**指向主星是声明的约定（对应「永耀」正典语义），不是近似声明：真实阻尼锁定
   做均匀自转，主星盘心按中心差摆动（光学经度天平动 ±2e，nacrea ≈ ±0.28°）而恒星
   均匀旋转；本约定反过来钉死主星，把 ±2e 振荡归入其他天体的视运动——两视图相差整
   个天球绕自转轴 ±2e 的刚体转动，低于现有消费方的分辨需求（均匀自转约定是 M4 候选
   修正；物理天平动需要 catalog 未携带的 (B−A)/C，弧秒级）。
2. **自转轴方位已知**（`derived.spin_axis_ecliptic_longitude_deg`，由赤道参考卫星
   按 `(Ω_ref − 90) % 360` 派生）：轴 = (sin ε · cos λ, sin ε · sin λ, cos ε)；自转
   相位 θ = 2π·t / `rotation_period_days`，**历元约定：t = 0 本初子午线指向本赤道对
   黄道的升交点**。catalog 历元不含自转相位信息，这是声明约定而非推导。
3. **非锁定卫星兜底**：`axial_tilt_deg` 为 0 或缺省时取自轨道法向，相位用同一
   「升交点锚定」约定（以轨道升交点为 t = 0 子午线）。其余情况（如缺方位的行星）
   **报错不猜**——catalog 本就把这些天体标记为「自转轴方位不可导出」
   （nacrea 的 Aegis 即如此，从其表面观测被明确拒绝）。

## 3. 两体传播

开普勒方程 `E − e·sin E = M(t)` 用牛顿迭代（E₀ = M，步长 < 1e-12 rad 收敛，50 次
上限，不收敛即报错；e ∉ [0,1) 拒绝——超双曲轨道不在范围）。真近点角与向径用半角
公式，perifocal → 黄道用标准 (Ω, i, ω) 旋转（法向即上式 n，与 catalog 的
极方位约定一致）。周期取 `bodies.orbit.period_days`——catalog 写入方与消费方共同
认定的值，不在查询路径重算开普勒第三定律。分层叠加：卫星位置 = 行星位置 + 自身
轨道偏移；恒星用 catalog `position`（AU → km）。

## 4. 相位与照度

- **相位角** α = 目标处的 (观测者方向)·(恒星方向) 夹角。
- **两种「照亮」不可混用**：盘面照亮比 `(1 + cos α)/2`（日历/UI 的「几分之几月」）
  与 Lambert 流量比 `Φ(α) = [sin α + (π−α)cos α]/π`（光度链，见
  `sky_geometry.lambert_phase` 与 sky_phenomena.md 相位表）在 α = 90° 差 0.2。
- 星等/照度复用 `sky_geometry.reflected_*`；**一处记录在案的偏离**：本链的反射
  照度用**目标处**星流量（`stellar_physics.instellation`），catalog 写入方
  `_sky_observation` 用观测者处——在 nacrea 锚点两者等价，跨行星目标时本链才是
  第一性。
- 黎明关系 α = 90° + h★ 成立到恒星视差项 asin(a/D★)（nacrea ≈ 0.76°）。

## 5. 升落

窗口 `W = min(观测者年, max(太阳日项, 同父兄弟会合周期项))`：锁定卫星上的恒星与
非兄弟天体按 ~太阳日循环，兄弟卫星按会合周期；观测者年封顶避免跨年误判。720 均匀
采样 + 一步余量判号变化分类 rises_sets / never_sets / never_rises，穿越点二分细化。
锁定观测者看主星高度恒定 → 永不落下。跨年分类（慢自转世界的极夜起始）归 M4 事件
搜索。高度变化率 = 采样步长的中心差分（度/小时）。

## 6. 参考与源码

- Murray, C. D., & Dermott, S. F. (1999). *Solar System Dynamics*. Cambridge
  University Press. ch. 1–2（开普勒方程、根数旋转、自转-轨道共振态）。
- *Explanatory Supplement to the Astronomical Almanac* (1992). ch. 4（地平/赤道
  框架、春分点-升交点约定）。
- 源码：`src/dreamulator/engine/ephemeris.py`（全部实现与约定文本）、
  `engine/sky_geometry.py`（光度原语）、`engine/stellar_physics.py`
  （周期/日照）、`engine/physical_inputs.py`（catalog 角度约定）。
- 测试锚点：`tests/test_ephemeris.py`（EP1 冻结时刻 t = 61.979 d 的太阳高度、
  Cadence/Vigil 距离与视直径、锁定主星天顶、满相扫描 −20.02 等）。
