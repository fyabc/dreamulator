# 行星与卫星表面资产：程序化生成、现成素材与大气

> 面向视频链的行星/卫星表面制作。回答三个问题：现成素材能不能直接用；
> 程序化贴图怎么做才不像固体；大气边缘怎么做出体积感。本文只写与具体世界
> 无关的方法与坑，配色与温度判据见 `../planetary_science/giant_planet_colors.md`，
> 天空/相机部分见 `blender_sky_rendering.md`。

## 1. 两条路线：烘焙贴图 vs 节点程序化

| | 烘焙等距圆柱贴图 | 节点程序化材质 |
|---|---|---|
| 做法 | Python/NumPy 生成 4K–8K albedo、height、normal，Blender 只用 `Image Texture` | 在着色器里用 Noise/Voronoi/Wave + 向量扭曲实时生成 |
| 优点 | 可离线反复打磨、可版本化参数、渲染时不吃节点计算；同一套贴图给不同引擎 | 无需展开 UV、任意分辨率、改动即时 |
| 缺点 | 改一次要重生成（8K 约几分钟）；球面放大后纹理分辨率有上限 | 大镜头下噪声细节容易「糊」；Cycles 里每个像素都要算节点 |
| 适用 | 长镜头、可复用资产、需要精确控制带/坑位置 | 快速预演、远景、风格化 |

实践上两者互补：先用节点快速试带数与配色，定稿后把同一套参数搬进烘焙脚本。
本项目采用烘焙路线（8K 等距圆柱 + 物理法线），因为它可复现、可参数化、
且能保证同一资产在多个镜头里一致。

## 2. 现成素材与许可

- **NASA 3D Resources**（<https://science.nasa.gov/3d-resources/>，GitHub 有镜像）
  —— NASA 官方模型/贴图，多数是航天器；行星模型多为低模。素材基本无版权限制
  （遵循 NASA 使用规范），适合做尺度与镜头参考。
- **Solar System Scope 贴图**（<https://www.solarsystemscope.com/textures/>）——
  真实太阳系行星的等距圆柱贴图，基于 NASA 影像，**CC BY 4.0**：可商用、可改编，
  需署名 “Copyright (c) 2010-2017, Solar System Scope”。
- **BlenderKit** 有免费的气巨模型；商业的 Planet/Procedural Real-Time Planet
  Shader 提供现成的带、云、大气预设。
- **关键判断**：真实行星的贴图不能直接贴到虚构行星上——木星的带纹、大红斑、
  土星的环都会把「另一个世界」变成「太阳系副本」。真实贴图的正确用途是
  **对照基准**（同一光照、同一相位下并排看）和**技法参考**。

## 3. 气态巨行星表面

### 3.1 带数由物理定，不由手感定

气巨的纬向急流条数受 Rhines 尺度约束：\(N \approx R\sqrt{\beta/(2U)}\)，其中
\(\beta = 2\Omega/R\)，\(U\) 是特征风速。自转越快、风速越低，带越多。木星约
12 条；自转 4.5 h 级的巨行星大约 12–24 条。先按这个数定带数，再用带宽随纬度
调制、逐带颜色噪声打破「斑马纹」。

### 3.2 纬向拉伸：拉伸噪声，不要缩放波数

云细节要沿经度拉长。有两种写法，结果完全不同：

- **正确**：在低分辨率网格上生成各向同性噪声，再沿经度做平滑重采样放大
  （例如 819×4096 放大到 8192×4096）。特征被拉长，频谱形状不变。
- **错误**：直接在频域里除以经度波数（`kx / aspect`）。这会**放大**经度高频，
  云细节被拉成经向细丝；放到球面近极点处投影，就是一圈「放射状白纹」。

同理，**不要只沿纬度做单向平滑**。单向平滑会让场只剩经度方向的变化，同样产生
经向拉丝。需要压制纬向高频时，用各向同性滤波，或者先降采样再拉伸。

### 3.3 风暴椭圆不要用 sin(半径)

用 \(0.5+0.5\sin(k\theta + c r)\) 调制风暴内部，在整颗行星远景下看着像旋涡，
一旦镜头推到 10° 盘面就会变成同心靶心。更稳的做法是用同一张湍流噪声调制椭圆
内部（`sw = 0.85 + 0.15·noise`），并限制椭圆尺度：真实涡旋直径约
1000–5000 km（大红斑约 16000 km），不要做出覆盖整个盘面的「风暴」。

### 3.4 纹理分辨率与盘面张角

等距圆柱贴图每度只有 `NY/180` 行。若镜头里盘面占 \(P\) 像素、角直径 \(D\)
度，则每度需要 `P/D` 像素；当 `NY/180 < P/D` 时贴图就在放大。本机 8K
（4096 行）给出 22.8 行/度：11° 盘面在 4K 画面里约 1800 像素（163 像素/度），
放大约 7 倍。这不是 bug，但意味着**贴图里不能有接近像素级的高频**，否则放大后
就是条纹。云细节的最小尺度应保持在 2–3 个纹素以上。

## 4. 岩质与冰卫星

### 4.1 撞击坑

- 尺寸服从幂律：小坑多、大坑少；在 2K 贴图上画几百到上千个。
- 剖面用「碗底 + 抬升的坑缘」两段：`bowl = 1/(1+exp((r-0.85)/0.15))`，
  `rim = exp(-((r-1)/0.18)²)`；新鲜坑再加坑缘亮环和放射状溅射纹。
- 5 Gyr 且无改造的表面应是**饱和撞击**；年轻表面（几十 Myr）只叠加少量新坑。

### 4.2 大型撞击盆地

用一个解析剖面即可：平底 + 抬升的环形山 + 中央峰 + 内环 + 溅射毯。尺度要算，
不要拍脑袋。撞击坑直径的 π 标度（Collins et al. 2005）：

\[
D_{tc} = 1.161 \left(\frac{\rho_i}{\rho_t}\right)^{1/3}
L^{0.78} v^{0.44} g^{-0.22} \sin^{1/3}\theta
\]

其中 \(D_{tc}\) 是瞬态坑直径、\(L\) 是撞击体直径、\(v\) 是撞击速度、\(g\) 是
表面重力、\(\theta\) 是入射角。最终坑直径约为瞬态坑的 1.2–1.3 倍。例：197 km
的撞击体以 15 km/s 撞上半径 1437 km、g≈1.16 m/s² 的岩质卫星，瞬态坑约
820 km、最终盆地约 1030 km——占卫星直径的七成，就是「半球级盆地」。

### 4.3 法线要按物理坡度算

高度图用公里存，法线由 `dh / 地面距离` 得到，而不是 `np.gradient(height)`
直接乘一个常数。等距圆柱上每像素对应的地面距离随纬度变化
（`dlon = 2πR·cos(lat)/NX`），只按像素梯度算会让极区的坑变成拉长的椭圆，
赤道与极区的起伏强度也不一致。

## 5. 大气边缘

- **薄壳 + Fresnel**：一个略大的球，`Layer Weight → Facing` 做边缘带，
  内侧暖色、外侧蓝灰两层混合。便宜、可控，适合远景与快节奏镜头。
- **体积散射**：用球面 Gradient 限制体积范围（Mapping 的 scale 取
  \(\sqrt{\text{球半径}}\)，否则体积会溢出球外），Scatter/Absorb 近似瑞利与
  米氏散射，各向异性取 0.25 左右能在掠射角出现边缘增亮。适合特写与
  「巨物压顶」的镜头，代价是渲染时间。
- 地球型大气的散射系数常用：Absorb (0.995, 0.088, 0.024)（蓝光吸收最强），
  Scatter (0.224, 0.454, 0.950)（蓝光散射最强）。气巨的水/氨云大气可在此基础上
  调整，但相函数与光学厚度要跟着改。

## 6. 参考

- Collins, G. S., Melosh, H. J., & Marcus, R. A. (2005). *Earth Impact Effects
  Program: A Web-based computer program for calculating the regional
  environmental consequences of a meteoroid impact on Earth*. Meteoritics &
  Planetary Science 40, 817. <https://doi.org/10.1111/j.1945-5100.2005.tb00157.x>
- NASA 3D Resources. <https://science.nasa.gov/3d-resources/>
- Solar System Scope Textures（CC BY 4.0）.
  <https://www.solarsystemscope.com/textures/>
- Blender Artists. *A set of nodes to make a texture for gas giant planets*.
  <https://blenderartists.org/t/a-set-of-nodes-to-make-a-texture-for-gas-giant-planets/1639335>
- Taliesin River. *Fully procedural exoplanets*.
  <https://taliesinriver.com/fully-procedural-exoplanets>
- Blender Stack Exchange. *Atmosphere (Rayleigh/Mie) Scattering in Cycles*.
  <https://blender.stackexchange.com/posts/15821/revisions>
- 巨行星的颜色判据：`../planetary_science/giant_planet_colors.md`
- 天空与相机工程：`blender_sky_rendering.md`
