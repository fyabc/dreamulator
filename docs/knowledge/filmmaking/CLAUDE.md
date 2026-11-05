# filmmaking — 影视手法与渲染工程知识

本目录收录与本项目视频链相关的影视技法与 Blender 渲染工程知识。技法条目
给出术语、代表作出处与本项目适用性；工程条目给出相机、天空、行星盘面与
无界面渲染的可复用做法和踩坑。

## 文档

- [`visual-narrative-techniques.md`](visual-narrative-techniques.md) — 影视视觉
  叙事手法目录：FUI、匹配剪辑、天体运动转场、声桥、尺度穿行、档案质感等。
- [`blender_sky_rendering.md`](blender_sky_rendering.md) — Blender 5.x headless
  天空与天体渲染：世界着色器方向约定、相机基向量、等距圆柱程序化纹理、
  大地形网格、合成器 API、运动模糊与帧序列编码；§11 深空场景生态
  （星场/星云/碎石/星系 addon 与真星表扩展、视图变换对自发光天体的影响、
  衍射芒与 bloom 的 headless 可行做法、agent skill 与连接器纪律）。
- [`blender_scripting_basics.md`](blender_scripting_basics.md) — Blender 脚本
  入门：`-b -P` 调用、最小脚本、`bpy.data/context/ops` 三个入口、常用对象、
  后台运行的坑与中文学习资料。
- [`planet_asset_rendering.md`](planet_asset_rendering.md) — 行星/卫星表面资产：
  烘焙贴图与节点程序化的取舍、现成素材与许可（NASA、Solar System Scope 等）、
  气巨纬向拉伸与风暴的正确做法、撞击坑与盆地的 π 标度、物理坡度法线、
  体积大气散射。

## 关联

- 区域地形渲染链：`docs/design/proposals/blender-render-pipeline.md`
- 全球画布与图像导出：`docs/design/pipelines/canvas-chain.md`
- 太空俯瞰星球媒体链：`docs/design/pipelines/orbital-weather-globe.md`
