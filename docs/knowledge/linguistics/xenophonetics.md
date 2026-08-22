# 异星语音学（Xenophonetics）与生物声学（Bioacoustics）

> 领域：为架空/异星世界设计"从发声器官推导语言"的科学依据。
> 关联：`docs/design/language-phylogeny.md` §6（异星发声模式）、
> `docs/design/ecology-layer.md` §四（生态→文明接口）。
> 调研来源：`private/plans/video/alien-biosphere-analysis.md`（Biblaridion 方法论）的补充。

---

## 一、核心理论

### 1.1 Source-filter theory（源-滤波器理论）

语音 = **声源**（喉/鸣管）信号 × **声道滤波**，放大频段即共振峰（formants F1/F2…）。
这是人类语音声学的基础，**已广泛推广到动物**（生物声学的通用框架）。

- Fant (1960)，*Acoustic Theory of Speech Production*。
- 关键可参数化量：**声道长度/形状 → 共振峰 → 元音空间**；动物用共振峰识别个体/体型。

### 1.2 动物发声器官谱系（现成的"异类发声"案例）

| 类群 | 器官 | 关键约束 |
|---|---|---|
| 哺乳类 | 喉 + 声带（与人类同源，继承自肺鱼） | 变异：蝙蝠高频声带、狮吼低频声带 |
| 鸟类 | 鸣管 syrinx（两对薄膜 + 12 对肌肉） | **双声源**、纯哨音、极快音高变化 |
| 鲸/海豚 | 鼻囊系统（phonic lips） | 非喉发声 |
| 蛙 | 喉（非哺乳同源） | — |
| 蟋蟀 | 摩擦发声（stridulation） | 非声带 |

- **声音学习（vocal learning）**：极少数物种（人、鲸、海豹、鸣禽），是口语进化的关键前提。

### 1.3 音变的理论基础（强理论）

音变源自 **articulatory constraints（发音约束）+ 感知过滤**：

- **Ohala（listener-based sound change，1981/1989/1993）**：音变 = 听者**误解析**
  （misperception）发音约束产生的连续信号，非说话者故意。三机制：混淆 / 低校正（→同化）/
  高校正（→异化）。
- **Blevins《Evolutionary Phonology》(2004)**：CHANGE（误听）/ CHANCE（歧义切分）/
  CHOICE（语速变体）三类，把 Ohala 系统化。
- **推论**：发声器官不同 → articulatory constraints 不同 → 可能的误听/音变不同 →
  **语言变迁规律不同**。

---

## 二、异星语音学（xenophonetics）实践

### 2.1 核心原则

> **"grammar and phonology grow from physiology"** —— 生理塑造音系，而非把音系强加到身体上。

### 2.2 发声器官 → 音位库存的映射

- 声源类型 → 发声机制（喉 / 鸣管 / 鼻囊）→ 音高范围、能否双声源
- 调音器 → 音位库存（无唇 → 无双唇音；喙 → 无唇塞音；声道长度 → 元音空间）
- **通信器官不必是进食器官**（Linguisten.de）

### 2.3 现成案例

- **Tâ-Wâ**（四通道：口腔声=词根 + 喉声=情态 + 鼻音流=热源 + 皮肤变色=体貌）
- **Rpizenq**（发声器官在嘴上方，自制记音字母 RPL）
- **"Alien Autopsy" 练习**（刚性舌头 + 铰接下颌 + 双重喉 → 逐项推音位可能性）

**关键约束**：**无 IPA 等价物**——IPA 是有限符号清单（人类器官），异星发声必须自制
记音系统（特征化记音，如 YPA 的"编号特征 + 字母符号"）。

### 2.4 记音系统评估（对应 asciipa）

ASCIIPA 的「特征即代码」哲学（base + 修饰符 = 特征束，`@bind` 作用域隔离）比 IPA
更适合异星——IPA 是清单式（inventory-based），ASCIIPA 是组合式（compositional）。
扩展路径见 `language-phylogeny.md` §6.4（新增声源/调音器特征；双声源/多通道需「声道层」记法）。

---

## 三、权威著作

- Bradbury & Vehrencamp，*Principles of Animal Communication*（2nd ed. 2011, Sinauer）— 动物通讯教科书（信号产生/传播/接收、信号设计规则、信号演化）
- Vakoch & Punske (eds.)，*Xenolinguistics: Towards a Science of Extraterrestrial Language*（Routledge 2023，ISBN 9781032399607）— 首本异星语言学学术论文集（Chomsky / Pepperberg / Herzing 等 18 章）
- Fant (1960)，*Acoustic Theory of Speech Production* — source-filter theory 奠基
- Blevins (2004)，*Evolutionary Phonology* — 音变 CHANGE/CHANCE/CHOICE 分类
- Ohala (1981/1989/1993) — listener-based sound change 系列论文
- Fitch (2000)，"The evolution of speech: a comparative review"（*Trends in Cognitive Sciences*）— 声道演化比较

## 四、网络资源

### B 站（推测生物学 / 外星生物圈）

- Biblaridion《外星生物圈》熟肉合集 BV1wmiXYEEeg / 生肉 BV1U3411t7Ya
- 入坑推测演化冰山分析 BV1ZAdABVEh3（转译 Anthöny Pain 项目全谱）
- Furaha 星球 BV1W46PBQEQW（推测生物学"科学与艺术的平衡"）

### 海外关键线索

- **Anthöny Pain**：推测演化圈的「项目盘点者」，系统梳理全网推测演化项目清单。
- Biblaridion（YouTube）：conlang + 推测生物学创作者。

详见 `private/plans/video/alien-biosphere-analysis.md` §五（参考资料）。
