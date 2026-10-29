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

比较分辨率时还需读取模式实际打印的参数。ExoPlaSim 3.4.2 的 `plasim.f90`
对 T42 预设四次幂水平扩散，临界波数为 16；其他截断尺度沿用 `plasimmod.f90`
的二次幂扩散和临界波数 15。两套温度、涡度和散度扩散时间也不同。这些量属于
数值闭合，直接影响已解析尺度的方差及湿度分布。运行配置没有显式填写这些量时，
仅比较 Python 的配置字典会漏掉差异。

这套线性扩散在球谐波数 \(n\) 上的名义衰减率为
\(D(n)=\max(0,n-n_0)^p/[(N-n_0)^p\tau]\)，其中 \(N\) 是截断波数，
\(n_0\) 是临界波数，\(p\) 是扩散幂次，\(\tau\) 是截断尺度处的扩散时间。
固定 \(n_0\) 和 \(p\)，把一个算子转移到另一截断尺度时，使用
\(\tau_2=\tau_1[(N_1-n_0)/(N_2-n_0)]^p\) 可保持共同已解析波数上的衰减率。
这一换算用于隔离数值算子的诊断，具体生产设置仍需收敛验证。

指数物理滤波与水平扩散分别核对。`legmod.f90` 的指数滤波单次变换增益为
\(F(n)=\exp[-\kappa(n/N)^r]\)，因此相同的 `gp|exp|sp` 配置在不同截断尺度上
保留的共同波数方差也不同。滤波、时间步进、地表取样和新解析出的环流尺度均属于
分辨率比较的分析范围；固定其中一项的实验只隔离该项响应。

晴空辐射是对同一状态去掉云的辐射贡献后重算通量。PlaSim 的 `NDIAGCF=1`
在正常辐射计算前执行这一诊断，并恢复云和两波段地表反照率；`outmod.f90`
以原生变量代码 101–107 输出相应通量。净短波的云辐射效应定义为
\(CRE_{SW}=ASR_{all}-ASR_{clear}\)，两次运行的短波差异可精确分为晴空吸收差异
和云辐射效应差异。晴空项同时含地表反照率、水汽和其他吸收变化，云辐射效应
也随模式状态变化，因此这一预算分解仍与干预实验的因果归因有别。

更换步长的暖启动需要保留物理时刻。PlaSim 重启文件的 `nstep` 保存积分步数，
模式用这个数和新步长计算轨道位置。读取不同步长的终态时，需换算时钟并记录舍入
误差，保持物理状态数组；直接保留原步数会跳到另一轨道时刻。短诊断还需留出初期
调整段，并使用相同的物理时长和完整季节覆盖。

实现见 `gcm/diagnostics.py` 的 `summarize` 与 `scripts/climate/gcm/run_exoplasim.py`。
分辨率对照工具见 `scripts/climate/gcm/compare_resolution.py`。
参考 Paradise et al.（2022），*ExoPlaSim: Extending the Planet Simulator for Exoplanets*，
[论文](https://arxiv.org/abs/2107.07685)；Hartmann（2016），*Global Physical Climatology*；
[PlaSim Reference Manual，§3.2](https://www.mi.uni-hamburg.de/en/arbeitsgruppen/theoretische-meteorologie/modelle/sources/psreferencemanual-1.pdf)；
[ExoPlaSim 配置说明](https://exoplasim.readthedocs.io/en/stable/source/exoplasim.html)。
具体预设、衰减率和晴空诊断按 ExoPlaSim 3.4.2 的 `plasim.f90`、`plasimmod.f90`、
`legmod.f90`、`radmod.f90`、`outmod.f90` 与 `restartmod.f90` 核对。
