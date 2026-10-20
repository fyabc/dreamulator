# 程序化云生成竞品调研（游戏引擎 / 卫星图叠加 / 行星渲染）

本文登记云纹理与云渲染方向的竞品实现，供太空俯瞰镜头链（L2 程序化云纹理、
L5 渲染）决策时对照。统计律依据（光学厚度分布与空间谱）见同目录
`cloud_field_statistics.md`。

## 一、游戏引擎的实时体积云（Guerrilla Decima / EA Frostbite）

**Guerrilla Games《Horizon: Zero Dawn》云系统**（Schneider, SIGGRAPH 2015 Advances
课程；后续 GPU Pro 7、SIGGRAPH 2017 Nubis、GDC 2022《Forbidden West》超级风暴、
SIGGRAPH 2023 Nubis³ 体素化）是实时体积云的奠基实现，要点：

- **weather map 三通道**：一张低分辨率世界贴图编码 R=coverage、G=precipitation、
  B=cloud type（0 层云 / 0.5 层积 / 1 积云，选高度剖面；降水信号在 70% 覆盖度时
  过渡到积雨云）。天气由一个可艺术干预的模拟推进。**这正是我们 L1 气象图层包的
  游戏界对应物**——我们的 coverage 场将来直接来自 GCM 而非手绘；
- **Perlin-Worley 形状噪声 + 高频 Worley 侵蚀噪声 + curl noise 细节**：形状噪声定
  云体，侵蚀噪声雕边缘（花椰菜状碎边），两级 LOD；
- 光线步进 + Beer 定律透射 + Henyey-Greenstein 相位函数 + 「powder」边缘暗化；
  PS4 上目标 2 ms；
- 过场镜头可**逐镜头手绘覆盖 weather map**（艺术总监通道）。

**Frostbite（EA, SIGGRAPH 2016 课程）** 的独立贡献是把形状噪声与侵蚀噪声明确分离、
并把 RGBA 打包噪声压缩为单通道体积纹理省带宽——「形状/侵蚀分离」这一约定我们
在 2D 纹理里以「billow 形状 + detail 边缘侵蚀」继承。

**对本项目的取舍**：全圆盘镜头按需求裁决走「地表球 + 透明度云壳」2D 路线，体积
光线步进只留给推近镜头（L5）；但形状/侵蚀分离、weather map 契约、逐镜头覆盖
三个思想已吸收。

## 二、卫星图视角的 2D 云叠加（与我们最同构）

**SatelliteCloudGenerator**（strath-ai，PyTorch，GitHub 开源）为卫星影像生成云
掩膜叠加，参数设计与我们的问题一一对应：Perlin 噪声为主发生器；`decay_factor`
控制高频衰减（大→糊云）；`locality_degree` 把多个随机云形状**相乘**得到局部化、
尺度多变的云团；`const_scale` 按图幅归一空间频率。**我们的「尺寸交叉淡化」
（两尺度 billow 场按低频场混合）是 locality 思想的无坐标剪切版本**——直接相乘
或坐标变频都会产生伪影（见 `cloud_field_statistics.md` 与代码注释的 proto11–14
教训）。

**Gaia Sky（行星可视化器）** 的程序化行星含独立云层：多倍频噪声（Perlin/Simplex/
Voronoi）在**球面 3D 采样**保证无缝无极点收缩——与我们的球面逐点采样同法。

## 三、噪声工程与 ML 路线

- **Perlin-Worley 可平铺体积噪声**的工程实现（Fewes/CloudNoiseGen；lightbulbbox
  教程）：格点坐标取模实现周期化。我们不需要平铺体积（球面采样天然无缝），
  但其「Worley 反相出蓬松团块」提示：若将来云团块感不足，可加 Worley 成分；
- **Unreal 机器学习体积云**（arXiv 2502.08107）：双噪声层（基础形状 + 快动画细节）
  取代手绘 weather map。对应我们需求书 L2 路线三「生成式降尺度」（CorrDiff 类），
  归 GPU 侧评估，原型阶段不采用。

## 四、到本项目管线的映射表

| 竞品思想 | 本项目落点 | 状态 |
|---|---|---|
| weather map（coverage/type/precip） | L1 GCM 图层包契约；占位 cover 场（降水×SLP 距平） | 占位已实现，待 L1 替换 |
| 形状/侵蚀噪声分离 | billow 形状 + detail 边缘侵蚀（`DETAIL_ERODE`） | 已实现 |
| locality 尺度多变 | 尺寸交叉淡化（`SIZE_*` 常量） | 已实现 |
| 球面 3D 采样无缝 | 全链球面逐点 fBm | 已实现 |
| 云元群体指数厚度 | 秩→截断指数逆 CDF（`cloud_field_statistics.md`） | 已实现 |
| 体积光线步进 + 相位函数 | L5 推近镜头 | 未开工 |
| Worley 团块成分 | 候选（团块感不足时加） | 登记 |
| ML 降尺度 | L2 路线三，GPU 侧 | 登记 |

## 参考链接

- Horizon Zero Dawn 云系统讲义：https://advances.realtimerendering.com/s2015/The%20Real-time%20Volumetric%20Cloudscapes%20of%20Horizon%20-%20Zero%20Dawn%20-%20ARTR.pdf
- Frostbite 物理天空与云：https://media.contentapi.ea.com/content/dam/eacom/frostbite/files/s2016-pbs-frostbite-sky-clouds-new.pdf
- SatelliteCloudGenerator：https://github.com/strath-ai/SatelliteCloudGenerator
- Gaia Sky 程序化行星文档：https://gaia.ari.uni-heidelberg.de/gaiasky/docs/master/Procedural-planets.html
- CloudNoiseGen（Perlin-Worley 平铺）：https://github.com/Fewes/CloudNoiseGen
- Unreal 机器学习体积云：https://arxiv.org/pdf/2502.08107
- GDC 2022 Forbidden West 超级风暴：https://media.gdcvault.com/GDC 2022/Speaker Slides/TheReal-timeVolumetricSuperstormsOfHorizonForbiddenWest_Schneider_Andrew.pdf
