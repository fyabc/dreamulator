# 超大陆旋回周期的标度估算

## 核心概念

超大陆旋回指大陆反复拼成一个超大陆、再裂解分散的过程。一次旋回包括四个阶段：超大陆完整存续，
裂解，各大陆分散漂移，最后重新拼合。地球上公认的超大陆有凯诺兰（约 27–25 亿年前）、努纳（约
18–16 亿年前）、罗迪尼亚（约 10–9 亿年前）和盘古（约 3.3 亿年前拼成，约 2 亿年前开始裂解），
旋回周期约 3–7 亿年（Nance 等 2014）。

地幔对流模型能自发产生超大陆旋回，周期由地幔翻转时间控制（Yoshida & Santosh 2011；Rolf 等
2014）。翻转时间等于对流单元的尺度除以对流速度，地表上的体现就是大陆横穿一个大洋所需的时间。
所以一阶估算可以把周期写成几何尺度与板块速度之比，用地球标定：

$$T = T_\oplus \cdot \frac{R}{R_\oplus} \cdot \frac{v_\oplus}{v}$$

其中 R 是行星半径，v 是板块的典型速度（面积加权的均方根），v⊕ ≈ 5 cm/yr。

## 板块速度从哪里来

板块速度可以取引擎现状板块的欧拉极，也可以由内热流推出。由热流推速度用
`tidal_plate_speed.md` 的幂律 v = v⊕ (q / q⊕)^β，q⊕ ≈ 0.087 W/m²，β 的文献范围约 0.5–1。
地幔对流的响应时间是千万年量级，所以 q 应取百万年以上的平均热流，不取某一时刻的瞬时值。

## 阶段比例

超大陆完整存续的时间约占一个旋回的四分之一：盘古从拼成到开始裂解约 1.2–1.5 亿年，周期约 5–6
亿年。拼合本身也不是一次完成的，盘古的主要碰撞前后延续了数千万年（Nance 等 2014）。由此，已知一个世界的周期 T
和这次裂解的开始时间 t_rift，就能估出上一次拼合的时间：拼合完成于约 t_rift + T/4，拼合碰撞分布
在此前约 T/4 的窗口里。

## 裂谷沿古缝合带张开

超大陆裂解时，裂谷常沿上一次拼合留下的缝合带张开，因为那里的岩石圈已被削弱。大西洋大体沿更早关闭的
古大洋缝合带重新张开，这是威尔逊旋回概念的出发点（Wilson 1966）；多数被动陆缘与古缝合带重合或平行
（Buiter & Torsvik 2014）。因此现状的陆连裂谷可以作为上一次拼合缝合带的位置线索。

## 不确定度与适用范围

- 这个标度只给量级。T⊕ 本身有 2 倍以上的范围，β 的不确定在热流远高于地球时会被放大。
- 大陆面积占比越高，大洋越窄，横穿所需时间越短，周期越短；这一项约 20% 量级，未计入公式。
- 公式假定板块构造已经在运行，并且旋回由大陆横穿大洋的时间主导。热管火山或停滞盖状态下没有
  超大陆旋回。
- 认识论类别：几何标度属近似推导，T⊕、v⊕ 与阶段比例属地球观测拟合，β 的取值见
  `tidal_plate_speed.md`。

## 在本项目（dreamulator）中的应用

nacrea 的半径为 1.07 R⊕，取 T⊕ = 3–7 亿年：

| 板块速度的来源 | v | 周期 T |
|---|---|---|
| 百万年平均热流约 1.03 W/m²（潮汐约 1 加放射性约 0.03），β = 0.5 | 约 17 cm/yr | 约 0.9–2.2 亿年 |
| 同上，β = 1 | 约 59 cm/yr | 约 0.3–0.6 亿年 |
| 引擎现状欧拉极（面积加权均方根） | 约 13 cm/yr | 约 1.2–2.9 亿年 |
| 正典显生宙板块速度 | 15–25 cm/yr | 约 0.6–2.5 亿年 |

几种来源合起来，理论范围约 0.3–2.5 亿年。正典的现行周期约 1.2 亿年落在范围中段，与理论相容。
古地理倒推用到的阶段推算：nacrea 现状最老的一批陆连裂谷张裂于约 48–62 Myr 前，取 T ≈ 120 Myr，
超大陆约在 90 Myr 前拼成，拼合碰撞落在约 90–120 Myr。这就是
`data/worlds/nacrea/layers/geological/input/plate_history.yaml` 中拼合缝合带的年龄窗口。

## 参考资料

- Nance R.D., Murphy J.B., Santosh M. 2014, The supercontinent cycle: a retrospective essay.
  Gondwana Research 25:4. doi:10.1016/j.gr.2012.12.026
- Yoshida M., Santosh M. 2011, Supercontinents, mantle dynamics and plate tectonics: a perspective
  based on conceptual vs. numerical models. Earth-Science Reviews 105:1. doi:10.1016/j.earscirev.2010.12.002
- Rolf T., Coltice N., Tackley P.J. 2014, Statistical cyclicity of the supercontinent cycle.
  Geophysical Research Letters 41:2351. doi:10.1002/2014GL059595
- Buiter S.J.H., Torsvik T.H. 2014, A review of Wilson Cycle plate margins: a role for mantle
  plumes in continental break-up along sutures? Gondwana Research 26:627. doi:10.1016/j.gr.2014.02.007
- Wilson J.T. 1966, Did the Atlantic close and then re-open? Nature 211:676. doi:10.1038/211676a0
