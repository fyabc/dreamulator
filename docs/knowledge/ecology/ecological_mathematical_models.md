# 生态学数学模型参考

> 为 dreamulator 生态引擎的数学骨架提供参考。从个体/种群到生态系统，按层级组织。
> 每个模型标注：核心方程、适用场景、在 dreamulator 中的可能用途。

---

## 一、种群动力学（Population Dynamics）

### 1.1 逻辑斯谛增长（Logistic Growth）

$$\frac{dN}{dt} = rN\left(1 - \frac{N}{K}\right)$$

| 符号 | 含义 |
|------|------|
| N | 种群数量 |
| r | 内禀增长率（intrinsic growth rate） |
| K | 环境承载力（carrying capacity） |

**在 dreamulator 中的用途**：最基础的种群模型。K 由气候引擎 + 生态 NPP 决定；
r 由代谢理论（体型+温度）参数化。是构建更复杂模型（捕食、竞争、收获）的零阶近似。

### 1.2 r/K 选择理论

| 策略 | 特征 | 典型环境 |
|------|------|---------|
| **r-策略** | 高繁殖率、短世代、小体型、低亲代投资 | 不稳定/扰动环境（荒漠、季风区） |
| **K-策略** | 低繁殖率、长世代、大体型、高亲代投资 | 稳定环境（热带雨林、深海） |

**在 dreamulator 中的用途**：根据气候稳定性（季节变化幅度、洋流振荡频率）自动偏置物种策略。
gaia-m 的"掏洞期"（气候振荡）→ 偏 r-策略；"结率期"（气候稳定）→ 偏 K-策略。

### 1.3 Allee 效应

$$\frac{dN}{dt} = rN\left(1 - \frac{N}{K}\right)\left(\frac{N}{A} - 1\right)$$

其中 A 是 Allee 阈值——种群低于 A 时增长率为负（配偶难觅、合作捕食失效等）。

**用途**：模拟小种群灭绝风险，对文明层的物种驯化/资源枯竭有直接影响。

---

## 二、物种间相互作用

### 2.1 Lotka-Volterra 捕食者-猎物模型

$$\frac{dN}{dt} = rN - aNP \qquad \frac{dP}{dt} = eaNP - mP$$

| 符号 | 含义 |
|------|------|
| N | 猎物数量 |
| P | 捕食者数量 |
| a | 攻击率 |
| e | 转换效率（猎物生物量→捕食者生物量） |
| m | 捕食者死亡率 |

**用途**：最经典的捕食动力学。dreamulator 中可用于食物网的 tier-1 耦合。

### 2.2 广义 Lotka-Volterra 竞争模型

$$\frac{dN_i}{dt} = r_i N_i\left(1 - \frac{\sum_j \alpha_{ij} N_j}{K_i}\right)$$

其中 $\alpha_{ij}$ 是物种 j 对物种 i 的竞争系数（$\alpha_{ii}=1$）。

**高维版本**（现代理论生态学关注的核心）：

$$\frac{dx_i}{dt} = x_i\left(r_i + \sum_{j=1}^S A_{ij} x_j\right)$$

其中 A 是群落矩阵（community matrix），S 是物种数。

**稳定性判据（May 界）**：对于随机群落矩阵，若 $S \cdot \sigma^2 > 1$（σ 为相互作用强度的标准差），
系统以概率 1 不稳定。

**用途**：dreamulator 的食物网动力学核心。大 S 系统的稳定性条件是设计生态引擎的关键约束。
**启示**：高维系统天然不稳定——生态引擎不能天真地生成 100 个物种然后耦合，需要结构化
（模块化食物网、弱相互作用为主、捕食者-猎物不对称性）。

### 2.3 消费者-资源模型（MacArthur 型）

$$\frac{dN_i}{dt} = N_i\left(\sum_{\mu} w_{\mu} c_{i\mu} R_{\mu} - m_i\right) \qquad \frac{dR_{\mu}}{dt} = R_{\mu}\left(r_{\mu} - \frac{R_{\mu}}{K_{\mu}}\right) - \sum_i c_{i\mu} N_i R_{\mu}$$

**优势**：相互作用是**涌现性质**而非直接参数——竞争通过共享资源自然产生。
优于直接写 $\alpha_{ij}$ 的经典 Lotka-Volterra。

**用途**：当 dreamulator 需要超越"静态群系"进入动态食物网时，这是更坚实的数学基础。

---

## 三、代谢标度理论（Metabolic Scaling Theory）

### 3.1 Kleiber 定律

$$B = B_0 M^{3/4}$$

其中 B 为基础代谢率，M 为体重。

**更一般地**，几乎所有生物速率（生长率、死亡率、摄食率）都按 $M^{-1/4}$ 标度：

$$r \propto M^{-1/4} \quad \text{（单位质量代谢率）}$$
$$t \propto M^{1/4} \quad \text{（生物时间——世代长度、寿命）}$$

### 3.2 温度依赖性（Arrhenius-van't Hoff）

$$B(T) = B_0 M^{3/4} e^{-E/kT}$$

其中 E ≈ 0.6–0.7 eV（呼吸作用的活化能），k 为 Boltzmann 常数。

**在 dreamulator 中的用途（关键！）**：代谢理论是连接 climate 层和 ecology 层的桥梁。
给定 cell 的温度 T，直接算出该 cell 内给定体型生物的代谢率、增长率、摄食率——不需要逐物种设定参数。

### 3.3 代谢理论推论

| 推论 | 公式 | 含义 |
|------|------|------|
| 种群密度 | $N \propto M^{-3/4}$ | 大象比老鼠少 |
| 世代长度 | $t_{gen} \propto M^{1/4} e^{E/kT}$ | 冷环境 + 大体型 = 长世代 |
| 最大种群增长率 | $r_{max} \propto M^{-1/4} e^{-E/kT}$ | 小体型 + 热环境 = 高增长 |
| 承载力 | $K \propto M^{-3/4} \cdot NPP$ | 生态学"能量等效"规则 |

**能量等效规则（Energetic Equivalence Rule）**：一个生态系统中，不同体型级别的总能量通量近似相等。
即小鼠的生物量 × 小鼠的代谢率 ≈ 大象的生物量 × 大象的代谢率。

---

## 四、食物网与营养动力学

### 4.1 Lindeman 营养效率（10% 定律）

$$P_{n+1} \approx 0.1 \times P_n$$

其中 $P_n$ 是第 n 营养级的净生产力。实际范围 5%–20%，平均约 10%。

**更精确的模型**：

$$P_{n+1} = \varepsilon \cdot P_n$$

其中 ε 取决于同化效率（assimilation efficiency）和净生产效率。

### 4.2 营养级联（Trophic Cascade）

$$\frac{dP}{dt} = f(P, H, C)$$

三个营养级的耦合 ODE 系统——捕食者 (P) 控制食草者 (H) 控制生产者 (C)。
**顶级掠食者的波动通过奇数级联放大到底层**。

### 4.3 食物网拓扑规律

| 规律 | 描述 |
|------|------|
| 链路密度 | 平均每个物种 2–5 条营养连接 |
| 连接度 | connectance ≈ 2/S（随物种数减少） |
| 杂食性限制 | 真正的杂食者（跨多个营养级）稀少 |
| 级联模型 | 体型大的吃体型小的（95% 的链路遵循此规则） |

**用途**：生成合理的食物网结构。不需要逐个指定"谁吃谁"——给定体型分布，自动按体型排序生成营养连接。

---

## 五、群落生态学

### 5.1 种-面积关系

$$S = cA^z$$

| 参数 | 典型值 | 含义 |
|------|--------|------|
| z | 0.15–0.35（大陆）; 0.25–0.35（岛屿） | 面积增加 10 倍，物种数增加 ~2 倍 |

**用途**：dreamulator 中岛屿 vs 大陆的物种丰富度差异。

### 5.2 MacArthur-Wilson 岛屿生物地理学

$$\frac{dS}{dt} = I - E$$

其中迁入率 $I = I_0 e^{-d}$（随离大陆距离 d 衰减），灭绝率 $E \propto 1/A$（随面积减小）。

**平衡物种数**：$S_{eq} = \frac{cA^z}{1 + k \cdot d}$ ——面积越大、离大陆越近，物种越多。

**用途**：前导点褶皱山系的物种分布。gaia-m 的前导点褶皱山系（~90°E）天然适合应用此模型。

### 5.3 中性理论（Hubbell 2001）

核心假设：**所有个体在生态上等价**——出生、死亡、迁移、物种形成的概率对所有物种相同。
群落结构是随机漂变 + 迁移 + 物种形成的产物，而非生态位分化的结果。

$$\theta = 2J_m \nu$$

其中 θ 为基本生物多样性数，$J_m$ 为元群落大小，ν 为物种形成率。

**用途**：作为零假设/null model。当观测的物种分布偏离中性预测时，说明生态位/选择在起作用。

### 5.4 竞争排斥原理（Gause）

**完全生态位重叠的两个物种不能共存**。共存需要生态位分化（资源、空间、时间）。

**在 dreamulator 中的含义**：一个 cell 不能有 10 个完全相同的"食草动物"——需要体型差异化或食性分化。

---

## 六、生态系统级

### 6.1 净初级生产力（NPP）模型

**Miami 模型**（Lieth 1975）——已在生态层设计方案中给出。

**Thornthwaite Memorial 模型**（更精确）：

$$NPP = 3000[1 - e^{-0.0009695(E - 20)}]$$

其中 E 为实际蒸散量（mm/yr），由温度 + 降水共同决定。

### 6.2 碳周转模型

$$\frac{dC}{dt} = NPP - k \cdot C$$

其中 C 为土壤/生物量碳库，k 为分解速率（温度依赖：$k \propto e^{-E/kT}$）。

**用途**：不仅是生态学——碳循环直接关联气候引擎（反照率、温室气体）。

---

## 七、演化动力学

### 7.1 适应动力学（Adaptive Dynamics）

性状演化速度：

$$\frac{dx}{dt} = \mu \cdot \sigma^2 \cdot N \cdot \frac{\partial f}{\partial x'}\bigg|_{x'=x}$$

| 符号 | 含义 |
|------|------|
| μ | 突变率 |
| σ² | 突变效应方差 |
| N | 种群大小 |
| ∂f/∂x' | 适应度梯度（fitness gradient） |

**用途**：性状在适应度景观上的爬坡速度。体型、耐热性、食性特化等连续性状的演化。

### 7.2 多样化率模型

$$\frac{dS}{dt} = \lambda S - \mu S$$

其中 λ 为物种形成率，μ 为灭绝率。

**环境依赖性**：
- 气候振荡期 → μ 增大（灭绝）、碎裂化 → λ 增大（异域物种形成）
- 稳定温暖期 → λ 减小、S 接近平衡

### 7.3 红皇后假说（Van Valen 1973）

**灭绝概率与物种年龄无关**——物种的灭绝风险是恒定的，不因"已经活了很久"就降低。

在 dreamulator 中的数学表达：物种的灭绝等待时间服从指数分布 $P(T > t) = e^{-\mu t}$。

---

## 八、跨层整合——dreamulator 生态引擎的方程体系

### 8.1 零阶方案：静态映射（近期）

```
(T_cell, P_cell, lat_cell) → Whittaker biome → NPP(Miami)
    → K (carrying capacity, from metabolic scaling)
    → domesticable_species_pool (标签查表)
```

纯函数，无 ODE。输入气候的逐 cell 输出，输出逐 cell 的生态标签。

### 8.2 一阶方案：区域种群动力学（中期）

对每个生物群系区域（连续同群系 cell 的连通分量），求解：

$$\frac{dB_i}{dt} = r_i(T) B_i \left(1 - \frac{B_i}{K_i(NPP, A)}\right) - \sum_j a_{ij} B_i B_j$$

其中 $B_i$ 是功能群 i（如"大型食草动物""中型捕食者"）的生物量，而非具体物种。
$r_i(T)$ 由代谢理论给出（Arrhenius 温度依赖）。

### 8.3 二阶方案：全食物网（远期）

基于体型排序自动生成食物网拓扑 → MacArthur 消费者-资源模型求解平衡态 → 
食物网稳健性分析（移除关键种的影响）。

---

## 九、关键文献

| 模型 | 来源 |
|------|------|
| Logistic 增长 | Verhulst (1838) |
| Lotka-Volterra | Lotka (1925); Volterra (1926) |
| MacArthur 消费者-资源 | MacArthur (1970) |
| 代谢标度理论 | Kleiber (1932); West, Brown & Enquist (1997); Brown et al. (2004) |
| 岛屿生物地理学 | MacArthur & Wilson (1967) |
| 中性理论 | Hubbell (2001) |
| Miami NPP | Lieth (1975) |
| 适应动力学 | Dieckmann & Law (1996); Geritz et al. (1998) |
| 高维生态系统稳定性 | May (1972); Allesina & Tang (2012) |
| 红皇后假说 | Van Valen (1973) |
| HANDY 模型（文明-生态耦合） | Motesharrei, Rivas & Kalnay (2014) |

---

## 十、与文明动力学模型的连接

生态引擎输出直接作为文明层 ODE 的参数：

```
生态输出                    →  文明模型参数
─────────────────────────────────────────────
NPP (gC/m²/yr)             →  HANDY: γ（资源再生率）
K (carrying capacity)      →  HANDY: carrying_capacity
r_max (种群增长率)          →  HANDY: β_C（平民出生率上限）
domesticable_species_pool   →  初始文明标签（agricultural / pastoral / maritime）
keystone_resources          →  文明经济基础（trade_goods）
灭绝风险（Allee 阈值）       →  SDT: 文明崩溃触发器
```

这使文明模型从"手工设定参数"升级为"气候→生态→文明参数自动推导"——DAG 管线全链路打通。
