# GCM 气候统计口径

全球近地面气温是球面积分。ExoPlaSim 使用高斯纬度和等间距经度，纬度行的面积权重为
Gauss–Legendre 求积权重。若纬向平均为 \(T_j\)、权重为 \(w_j\)，则
\(\overline T=\sum_j w_jT_j/\sum_jw_j\)。这来自球面面积元
\(dA=R^2d\lambda\,d\sin\phi\)；等权平均纬度行会高估高纬的贡献。

近地面气温取 `tas`，赤道和极地统计也使用这一变量。整层大气平均另行定义，
因为它包含较冷的高层空气。缺少 `tas` 时，最低模式层的 `ta` 作为近地面代理并记录其来源。

模式月份和轨道季节属于两个时钟。输出的 `time` 以积分步数计量，物理时间由实际
`MPSTEP` 换算。跨世界统计按十二个轨道相位箱分别平均，再对季节等权平均；
未覆盖全部季节的短运行保留相位覆盖信息。多年的月平均结果适合描述长期气候，
瞬时日照与天气过程仍须读取相应时序。

分辨率会改变地表取样、湿度和雨率的分布。PlaSim 的云诊断对相对湿度使用阈值及平方响应，
对对流雨率使用对数响应，再由云和地表反照率共同影响短波吸收。因此，提高分辨率可能改变
平衡温度。两种截断尺度的差值属于模型差异；晴空辐射与共同配置干预分别用于判断云、冰和
环流的成因份额。全球均值偏差不能直接作为向另一世界加减温度的依据。

实现见 `gcm/diagnostics.py` 的 `summarize` 与 `scripts/climate/gcm/run_exoplasim.py`。
参考 Paradise et al.（2022），*ExoPlaSim: Extending the Planet Simulator for Exoplanets*，
[论文](https://arxiv.org/abs/2107.07685)；Hartmann（2016），*Global Physical Climatology*。
