# 坡面输运的物理尺度与体积收支

线性坡面模型将单位宽度的土体通量写作 $q_s=-D\nabla h$，其中高程 $h$ 的单位为 m，
扩散系数 $D$ 的单位为 m²/yr。连续方程给出 $\partial h/\partial t=D\nabla^2h$。
这一闭合用于具有可搬运风化物的坡面，扩散系数由独立观测或作者给定的过程参数约束。
在相同密度和固定孔隙率近似下，几何体积收支对应物质收支；岩性、风化供应和临界坡度另由过程模型描述。

`map/surface_transport.py` 的 `hillslope_transport` 采用有限体积交换。
均匀方格的相邻格在一步内交换 $D\Delta t(h_i-h_j)$ 的体积，成对通量等量反向。
边框采用零通量；海洋边界以水面高程为基准，输出体积单独计账，原海底高程保持。
稳定步满足 $D\Delta t/\Delta x^2\leq1/4$，大步长通过内部细分满足该条件。
在正系数条件下，格值是原值与相邻值的加权平均，保持高程范围和常量表面的平衡。
参考海面平移时，高程与海面共同平移，通量保持原值。

扩散长度满足 $\sigma^2=2D\Delta t$，二维单位脉冲的径向二阶矩为 $4D\Delta t$。
固定像素宽度的平滑在分辨率改变后对应不同的 $D$，多尺度地形计算应明确物理系数和步长。
按连续高斯函数的格心采样，在扩散长度远小于格距时会丢失邻格交换；有限体积通量仍表示其小量输运。

扩散系数的适用域随材料和地貌记录。Struble 与 Roering（2021）第 3.3.1 节在俄勒冈海岸山地采用
$D=0.003$ m²/yr 的土壤坡面估计。该值在 10 万年内对应约 24.5 m 的扩散长度，
可用于这一地貌类比的尺度诊断。数千米网格上的跨格谷地、山前盆地和低地宽度还需要河流输运、
沉积与构造来源。临界坡度附近的非线性输运按相应材料模型另行约束。

河流侵蚀使用既有 Braun–Willett 隐式核。面积指数 $m=0.5$、坡度指数 $n=1$ 时，
物理汇水面积写作 $A=\Delta x^2a$，坡长写作 $l=\Delta x\,l_g$，因此
$\sqrt{A}/l=\sqrt{a}/l_g$。这一相消适用于均匀格距和一致的面积权重口径；
降水权重的参考单位、抬升率、侵蚀时长及地表边界分别记录。
SPL 的侵蚀效率属于过程参数，单纯的量纲与数值核验用于验证离散算子，其地质标定另行进行。

填洼后的水面用于计算流路，基岩面用于计算剥蚀，两种表面在湖盆内分别保存。
Braun–Willett 的线性更新在下游基岩高于上游基岩时可能产生正高程变化，
因此前置过程应明确湖盆作用域与沉积来源，并分别记账剥蚀、储存和边界输运。
Landlab 的 `StreamPowerEroder` 提供 `erode_flooded_nodes` 以声明淹没格的处理；
其文档也要求瞬态解核对时间步收敛。共用核的复用以这些适用条件为接口约束。

参考资料：

- Braun, J. & Willett, S. D. (2013). A very efficient O(n), implicit and parallel method to solve the stream power equation governing fluvial incision and landscape evolution. *Geomorphology*, 180–181, 170–179. doi:10.1016/j.geomorph.2012.10.008。
- Roering, J. J., Kirchner, J. W. & Dietrich, W. E. (1999). Evidence for nonlinear, diffusive sediment transport on hillslopes and implications for landscape morphology. *Water Resources Research*, 35(3), 853–870. doi:10.1029/1998WR900090。
- Struble, W. T. & Roering, J. J. (2021). Hilltop curvature as a proxy for erosion rate: wavelets enable rapid computation and reveal systematic underestimation. *Earth Surface Dynamics*, 9, 1279–1300. [正文第 3.3.1 节](https://esurf.copernicus.org/articles/9/1279/2021/)。[2022 年勘误](https://esurf.copernicus.org/articles/9/1279/2021/esurf-9-1279-2021-corrigendum.pdf)涉及第 3.2 节的尺度公式，坡面扩散系数按正文的地貌适用域引用。
- Landlab. [StreamPowerEroder](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.stream_power.stream_power.html) 的淹没格接口与瞬态时间步说明。
