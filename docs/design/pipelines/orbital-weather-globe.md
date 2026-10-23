# 太空俯瞰星球链：L2 云纹理、L3 气旋与 L5 大气

> 本文描述已实现的「太空俯瞰旋转星球」媒体链：从引擎网格生成全球云不透明度贴图，
> 叠加参数化气旋，再用物理大气壳合成正交圆盘预览。气象图层的第一层 L1（GCM 高频
> 输出与气旋轨迹表）仍待交付，本文在相应位置注明占位接口。
>
> 源码：`src/dreamulator/media/cloud_render.py`（L2 纹理与球面合成）、
> `cyclone_render.py`（L3 模板）、`atmosphere_render.py`（L5 大气）、
> `cloud_config.py`（YAML 配置）。命令行入口是
> `src/dreamulator/cli_export.py` 的 `export globe` 子命令。

## 1. 数据流与命令

一条命令完成纹理、气旋与预览：

```bash
dreamulator export globe nacrea --branch gcm-t42-712 --grid 8192x4096 \
    --cyclones --atmosphere
```

数据流是单向的：

1. 从地图网格栅格化降水、海平面气压距平、风场、海陆掩膜；
2. `large_scale_cover` 把降水与 SLP 距平组合成占位的大尺度云量场；
3. `cloud_texture_equirect` 在球面逐点采样 3D 噪声，生成等距圆柱云不透明度；
4. `warp_cyclone_texture` 与 `cyclone_alpha` 按轨迹表叠加气旋模板；
5. `render_globe_atmosphere` 把地表、云壳与大气壳合成为正交圆盘。

输出目录包含 `clouds.png`（合并 RGBA 直通 alpha）、`clouds_low.png`（低/中云+霾）、
`clouds_cirrus.png`（高壳卷云）、`cloud_cover.png`、`surface.png`、`cyclone_template.png`、
`cyclone_envelope.png`、`globe.png` 与 `meta.json`。
同一份输入与种子逐位可复现；`meta.json` 记录种子、机位、气旋数量与大气参数。

## 2. L1 接口（待交付）

L1 是 GCM 气象图层包，负责给出每 6 小时一帧的分层云量、云顶高度、云层风场、涡度
与降水，以及由涡度或海平面气压追踪出的气旋轨迹表。当前代码用年降水与 SLP 距平
构造占位云量场，用合成轨迹（热带每半球 1 个、温带每半球 2 个）代替真实轨迹；
这两处是唯一的占位点，噪声、扭曲、气旋模板与大气渲染都是永久部分。

气旋轨迹表的字段已经确定为 `Cyclone` 的构造参数：纬度、经度、类型、中心气压、
环境气压、最大风速半径、外围半径、移动矢量与形态种子。`cyclones.tracks` 非空时
直接使用显式轨迹，是 L1 轨迹表的接入口。

## 3. L2 程序化云纹理

云不透明度在等距圆柱网格上生成，但所有噪声都在像素的球面三维坐标处采样，因此
反日界线无缝、极点没有收缩。形状层用长波 fBm 决定「哪里有云」，细节层用高频
fBm 侵蚀云缘；两套尺度按低频场交叉淡化，避免固定尺度带来的重复感。风场做域
扭曲（flow noise），卷云沿风向拉丝。不透明度的全局秩映射到截断指数分布，空间谱
按 −5/3 标定；统计依据见
[cloud_field_statistics.md](../../knowledge/climatology/cloud_field_statistics.md)。

## 4. L3 气旋模板

热带气旋按 Holland 1980 风廓线由中心气压与环境气压定强度，形态由眼、眼墙、主
次对数螺旋雨带与卷云层组成；主/次雨带用较窄的高斯和软阈值取边，相位叠加细噪声，
避免整圈均匀的白色晕。温带气旋用 Shapiro–Keyser 概念模型：`_comma_twist` 把局地
坐标按 `1.10·ln r` 做差分旋转，并在旋转角与采样点上叠加低频噪声，然后在扭转后的
坐标系里取一个填充云头与一条冷锋尾——云头因此沿低压卷成逗号，而不是一个椭圆盘；
干槽在未扭转的角坐标里切成锐利楔形，云街沿扭转后的锋面展开，边缘再做一次轻度
unsharp。云头的破洞不另造一套噪声：`cloud_erosion_field` 从 L2 低云场取局部高通，
作为形状/侵蚀分离（Frostbite 思路）中的侵蚀项，让 L3 继承周围云系的 detail/grain/
MCC/Worley 质感；温带气旋在包络内用 lerp 替换底云，而不是 screen 叠加，避免云头
被推到纯白，同时保留侵蚀孔洞。气旋不是外加的白盘：`warp_cyclone_texture` 先把
L2 纹理按风暴轴做螺旋扭曲，眼区主动清除底云。尺度按 Nacrea 的设定取值：
热带外围 1500–2500 km、温带 2500–4000 km；真实轨迹到达后复核数量与频率。

## 5. L5 大气渲染

`atmosphere_render.py` 实现瑞利、米氏与臭氧大气。单次散射为基线，另加 Hillaire
多次散射近似。所有系数按世界自己的恒星光谱与行星物理定标：瑞利散射系数按波长的
−4 次幂变化，米氏气溶胶为灰体前向散射，
臭氧只吸收并取 25 km 帐篷剖面。标高由流体静力学平衡推出，光学厚度按柱质量缩放；
透射率用高度×太阳天顶角二维表预计算。视线在两个云壳高度分成三段：9 km 的卷云壳、
4 km 的低/中云壳与地表；半透明云能正确透出其后的大气，云影由低云壳沿太阳方向
与地表求交得到。卷云层按 9 km 处的太阳透射率单独照明，并向低云/地表投一层薄衰减
（见下）。`cloud_texture_equirect` 把低/中云、卷云与薄霾分开输出，另给一层更易读
的高壳卷云（`alpha_cirrus_high`）；它不进入已标定的合并 `alpha`，只作用于 9 km
壳。高壳卷云再按全局 p60–p98 拉伸、幂 1.4、增益 0.55 的对比曲线处理，保留亮丝缕、
去掉均匀薄纱（2026-10-22 作者选定的 A/B）。高壳卷云还向低云与地表投影：从低壳/
地表沿太阳方向与 9 km 壳求交，按交点处的卷云不透明度乘 `1 − strength·α`（默认
0.6）；这是直接日光的衰减，卷云自身不做自阴影。全圆盘下 5 km 的高度差只有约
1 px 视差，双层的主要收益是卷云与低云各自的照明/遮挡，而不是明显的立体错位。
全圆盘地表底图另用一套更深的海洋色（`SURFACE_SEA_*`，仅限 L2/L5 预览）；区域
制图/carto 链沿用原来的海色，不受影响。

卫星食使用 `EclipseShadow` 接口：中心经纬度、本影/半影角半径与最大暗化深度
（圆形近似）。角半径以度计；影半径大于行星半径且居中时取 90° 饱和。渲染器在表面与云壳的直接日光上乘一个平滑的圆形剖面；
大气入射散射按地表次点做同样的局部衰减。天文层负责从轨道数据算出这些量，
渲染器不依赖具体的食源。Aegis 掩食 Nacrea 的实算本影半径约 66,653 km（9.78
个行星半径）、半影 77,948 km（11.43 个行星半径）。本影半径大于行星半径，中心食
时食界在行星表面之外，整个可见半球都在本影内（接口取 90° 饱和），画面是全球
均匀变暗。偏食时阴影不是以次食点为中心的圆斑，而是沿掩食轴的带：设轴偏离行星
中心 $b$，表面上法线为 $\mathbf{n}$ 的点到轴的距离为
$\rho^2 = R_p^2 + b^2 - 2bR_p(\mathbf{n}\cdot\mathbf{u}) - R_p^2(\mathbf{n}\cdot\mathbf{s})^2$，
其中 $\mathbf{s}$ 是次食点方向、$\mathbf{u}$ 是轴的偏移方向；局部遮蔽率是恒星盘
（角半径 0.447°）与 Aegis 盘（5.66°）在角距 $\delta=\arctan(\rho/d)$ 下的重叠
面积。最靠近轴的点落在晨昏线上（与次食点相差 90°），所以影子从晨昏线一侧进入
昼半球。当前 `EclipseShadow` 的圆形剖面只是中心食与局部近似的接口；真实偏食的
带形遮蔽场需要按上式逐点计算。4°/6° 的小阴影只是通用接口演示；小卫星
（Cadence/Vigil）小于恒星角直径，用 `umbra_radius_deg = 0` 的环形/偏食剖面。

多次散射用 Hillaire (2020) 的局部查找表近似：每个格点对一组均匀方向积分单次
散射的角平均并乘以 1/(1−f_ms) 的几何级数，主光线步进在每个采样点叠加这一源项。
它把白天散射大气的亮度提高约一倍，但不能把日侧的光输运到深夜侧。

颜色按线性光计算：地表与云色先做 sRGB 解码，辐射传输在线性空间完成，最后编码
回 sRGB。默认的 `white_balance` 曝光按画面内直射日光逐通道平衡，保持地表调色板
的中性观感；`physical` 保留恒星白点，K 型星的暖色会进入整幅画面。海洋像元另有
GGX 微表面太阳高光（水菲涅耳、波面粗糙度可配），高光受云影与云层遮挡。恒星温度、
气压与组成在运行时从 `stellar.yaml` 和 `planets.yaml` 读取，缺失时回退地球值。
物理模型、系数来源与已知限制见
[atmospheric_scattering.md](../../knowledge/climatology/atmospheric_scattering.md)。

## 6. L4 云系平流原型

`media/cloud_advection.py` 实现等距圆柱网格上的半拉格朗日平流：风场（东向/北向，
m/s）先换成角位移，经度项除以 `cos(latitude)`，经度周期采样、纬度在极点夹取；
每步之后用前后误差补偿（BFECC）扣掉一半往返误差，压低半拉格朗日插值的数值扩散。
采样默认是双线性；`interp="cubic"` 改用 Catmull–Rom 四点插值，进一步保边，代价约
为双线性的 3 倍。`cloud_flow_video.py` 默认使用三次插值，可用 `--interp linear`
换回快速版。`advection_substeps` 按每步位移不超过约 8 个格子给出子步数上限。

`scripts/media/cloud_flow_video.py` 从 `export globe` 输出目录读取云纹理与网格，
用 `conditioning_grids` 取逐格年均风场，把云不透明度重采样到平流网格后逐帧推进，
再用 `SpinRenderer.set_cloud` 更新云场、渲染固定机位的全圆盘；相机与恒星不动，
晨昏线固定。平流速度是环境风加上每个风暴的 Holland 涡旋风：`cyclone_wind_field`
按风暴当前中心、Rmax、中心/环境气压与半球旋向给出切向风，在 0.9–1.25 倍外围
半径之间平滑收敛到零。热带气旋因此随引导气流平移、内部云带绕中心旋转；温带
逗号是锋面驱动的，轨迹里的 `rmax` 不是闭合核心尺度，`cyclone_wind_field` 默认
把温带涡旋压到零，让环境风切变锋面，避免把逗号当圆盘旋转。风暴中心按环境风做
拉格朗日推进。轨迹从 `meta.json` 的 `cyclones.tracks` 读取（导出时写入）；
`--no-vortex` 可退回纯环境风对照。模拟时长与
片长解耦（例如 12 小时演化压进 8 秒），便于先看运动方向与纹理稳定性：

```bash
uv run --with imageio-ffmpeg python scripts/media/cloud_flow_video.py \
    <clouds_dir> -o exports/spin/nacrea_cloudflow_720p.mp4 \
    --res 720 --seconds 8 --sim-hours 24 --texture-width 2048
```

这是原型：风场是年均值占位，等 L1 的 6 小时风场到达后替换；只输运现有纹理，不做
凝结/蒸发与云量再生，也不更新大尺度云量场。热带气旋由涡旋风保持旋转；温带逗号
默认不叠加涡旋，随环境风与锋面切变。极区经度位移被 `cos(latitude)` 下限保护。
12 小时版本保留了热带风暴眼，24 小时版本运动更明显但累积插值的扩散也更明显；
BFECC + Catmull–Rom 三次采样明显减缓但未完全消除长时间积分后的细节损失，更长
时段仍需要更强的保守/低扩散格式或按 L1 帧间插值。凝结/蒸发与云量再生尚未接入。

## 7. 旋转视频

`media/globe_spin.py` 的 `SpinRenderer` 利用一个几何事实：相机与恒星固定时，球对称
大气的视线散射、透射率和云壳光照都不随行星自转变化，只有地表与云纹理在转。因此
大气只算一次，每一帧只按经度偏移重采样纹理并重新合成；`frame(0)` 与静态
`render_globe_atmosphere` 逐位一致。

`scripts/media/spin_video.py` 读取一次 `export globe` 的输出目录（`surface.png`、
`clouds_low.png`、`clouds_cirrus.png`、`meta.json`），从 `meta.json` 还原大气模型与海洋掩膜，渲染一整圈旋转
加一段定格，按 16:9 画布居中并编码 H.264：

```bash
uv run --with imageio-ffmpeg python scripts/media/spin_video.py \
    <clouds_dir> -o exports/spin/nacrea_spin_720p.mp4 --res 720 --seconds 8
```

经度偏移从 0 递减到 −360°，行星按自转方向（向东）转动；相机与太阳不动，所以
晨昏线在画面中保持固定。云系随行星刚性旋转，不做时间演化（L4 才引入风场平流）。
720p、30 fps、8 秒（7 秒转一圈 + 1 秒定格）的样片准备约 12 秒、240 帧约 160 秒，
输出约 6 MB。

## 8. 状态与后续

已实现：L2 纹理、L3 气旋模板、L4 云系平流原型（年均风占位）、L5 单次与多次
散射大气、双层云壳与高壳卷云投影、海面太阳高光、卫星食通用接口与演示，以及
全圆盘旋转与云流视频。待办按依赖顺序排列：

1. L1 气象图层包与真实气旋轨迹表（等图层包交付）；
2. L4 接入 L1 的 6 小时风场，替换年均风占位；
3. L5 夜面城市灯光（文明层）；卫星食的真实椭圆/移动几何由天文层逐帧提供；
4. 云顶高度分布、多层云与次网格云尺寸分布。

全圆盘 4K 的定版贴图是 16K×8K；这一分辨率的纹理合成内存开销较大，当前预览以
8K×4K 为主，需要 4K 全圆盘时再按镜头加细分辨率。L2 纹理与大气渲染都是确定性
计算，不受预览分辨率影响。

## 9 参考

- Shapiro, M. A., & Keyser, D. (1990). Fronts, jet streams and the tropopause. In
  *Extratropical Cyclones: The Erik Palmén Memorial Volume* (pp. 167–191). American
  Meteorological Society. 用于云头、干槽、弯回锋面与逗号尾的概念模型。
- Blier, W. (1986). A case study of comma cloud development in the eastern Pacific.
  *Monthly Weather Review*, 114(9), 1681–1695. 逗号云从对流组织到成熟的结构。
- Reed, R. J., & Blier, W. (1986). A further study of comma cloud development in the
  eastern Pacific. *Monthly Weather Review*, 114(9), 1696–1708. 逗号云尺度约
  1000–1500 km，以及海气感热/潜热通量对发展的作用。
- Böttger, H., Eckardt, M., & Katergiannakis, U. (1975). Forecasting extratropical
  storms with hurricane intensity using satellite information. *Journal of Applied
  Meteorology*, 14(7), 1259–1265. 云头（cloud head）术语与卫星云型描述。
  Browning, K. A., & Roberts, N. M. (1994). Structure of a frontal cyclone.
  *Quarterly Journal of the Royal Meteorological Society*, 120, 1535–1557. 云头尖端
  与弯回锋面的观测描述。
- 程序化实现的思路参考（只借鉴概念/公式，不复制代码）：Terragen/Planetside 论坛的
  “按半径旋转坐标后采样 Perlin” 涡旋做法；Lygia `spiralSDF` 与 OpenProcessing
  “Generative Hurricane” 的多螺旋 SDF/差分旋转参数。链接：
  <https://www.planetside.co.uk/forums/index.php/topic,3227.msg33361.html>、
  <https://openprocessing.org/@kfahn/2923986>。
- Kim, B., Liu, Y., Llamas, I., & Rossignac, J. (2005). Flowfixer: Using BFECC for
  fluid simulation. *Symposium on Computer Animation*. L4 前后误差补偿的来源。
- Catmull, E., & Rom, R. (1974). A class of local interpolating splines. 三次采样
  使用 Catmull–Rom 权重；实现中只做四点局部插值，结果裁剪回 [0, 1]。
