# Blender 天空与天体渲染（headless / Cycles）

> 适用对象：用 `blender -b -P` 无界面重建「地表仰望行星」「行星盘面」「星空」这类
> 天文镜头的脚本。本文只记录与具体世界无关的工程知识与踩坑，不绑定某一集的分镜。
> 本机实测环境：Blender 5.2.2 LTS、Cycles、RTX 3060 Laptop 6 GB、Windows 11。
> 通用的区域地形渲染链见 `docs/design/pipelines/region-pack.md` 与
> `scripts/media/blender/region_still.py`；本文补充的是天空、行星盘面与相机运动。

## 1. 场景尺度与渲染器

- 使用千米作为场景单位（1 unit = 1 km），与区域地形链一致。相机 `clip_start`
  取 0.01 km、`clip_end` 取 2×10⁷ km，可以同时容纳近处地形（几公里）、行星
  （约 7×10⁵ km）与卫星。
- 太阳用 `SUN` 灯近似，`energy` 单位是 W/m²；真实的恒星辐照度（如 1.25×10³ W/m²）
  会让被照面极亮，通常需要配合 AgX 视图变换与负曝光。若只是为了看清云带，
  可以按镜头需要缩放辐照度，但应把物理值保留在状态文件里，缩放只作为渲染参数。
- 行星与卫星用 UV 球 + 等距圆柱纹理。行星放在真实轨道距离处（例如 7×10⁵ km）
  时，磁盘的张角由几何自然给出；如果数值精度或裁剪面有麻烦，可以按同一比例
  同时缩放半径与距离，张角与相位不变。
- Cycles 设备选择沿用 `region_still.py` 的 `pick_cycles_device()`：优先 OptiX，
  其次 CUDA，最后 CPU。1080p、192 samples 的简单天空场景在 RTX 3060 上约 20 s。

### 1.1 GPU 与 CPU 的分工

Blender 的两条渲染路径都会用 GPU：

- **Cycles** 是路径追踪器，本机走 OptiX；脚本里显式设置
  `prefs.compute_device_type = "OPTIX"` 与 `scene.cycles.device = "GPU"`，
  渲染日志里的 `device=OPTIX` 就表示 RTX 3060 在算。CUDA 是备选，CPU 是最后兜底。
- **EEVEE** 是光栅化渲染器，直接用 GPU（OpenGL/Vulkan），不走 OptiX。

GPU 只负责采样；下面这些步骤通常在 CPU 上：

- Python 端的场景构建（程序化纹理、网格生成、状态读写）；
- OpenImageDenoise 降噪（`scene.cycles.denoiser = "OPENIMAGEDENOISE"`）；
  Cycles 也支持 OptiX 降噪器，那种情况降噪也在 GPU；
- 合成器里的部分节点与最终的 PNG 编码。

显存是贴图预算的硬顶：本机 6 GB，8K RGBA 约 268 MB、16K 约 1 GB。行星与
卫星的纹理按镜头分辨率分配（例如 11° 的行星盘用 4K–8K，0.07° 的卫星点用
1K–2K 就够），不要无脑上 16K。浏览器走 AMD 集显（ANGLE/D3D11），Blender 走
RTX 3060，二者不抢卡。

## 2. World shader 的方向约定

世界背景的 `Geometry → Incoming` 向量指向相机，即视线方向的反向。用它做
高度渐变时要取负号：

```python
altitude_factor = -incoming.z   # 0 = 地平线，1 = 天顶
```

太阳光晕用视方向与太阳方向的点积。因为 `Incoming` 是反向的，点积也要再取负：

```python
cos_sun = -dot(incoming, sun_dir)
glow = max(cos_sun, 0) ** power
```

只让相机光线看到完整天空，而让漫反射光线看到一层很暗的环境光，可以得到
干净的晨昏线，同时不把地形压成纯黑：

```python
is_camera_or_glossy = max(is_camera_ray, is_glossy_ray)
# Fac=1 → 完整天空（相机/镜面反射）；Fac=0 → 暗环境（漫反射）
```

海面需要镜面反射天空时，必须让 glossy 光线看到完整天空；否则水面会是一块
死黑的平面。漫反射的暗环境则给地形与行星夜面一点可见度。

## 3. 相机朝向：从高度角/方位角构造基向量

不要用 `to_track_quat` 直接对准接近天顶的方向：视线与世界上方向接近平行时
退化，滚转会跳变。用显式基向量更稳：

```python
d = altaz_to_vec(alt, az)          # 视线方向（相机沿 -Z 看）
right = d.cross(Vector((0, 0, 1)))
if right.length < 1e-6:            # 正对天顶的退化情形
    right = Vector((1, 0, 0))
right.normalize()
up = right.cross(d).normalized()
rot = Matrix(((right.x, up.x, -d.x),
              (right.y, up.y, -d.y),
              (right.z, up.z, -d.z)))
cam.rotation_mode = "QUATERNION"
cam.rotation_quaternion = rot.to_quaternion()
```

滚转是绕视线轴 `d` 旋转基向量，不要绕世界原点旋转相机矩阵（会把相机位置
也转走，几公里的位移在近景里是可见的）。

## 4. 程序化等距圆柱纹理（行星云带、星场）

Blender 自带 Python 有 NumPy，但没有 PIL/scipy；纹理可以直接在内存里生成并
赋给 `bpy.data.images`，避免外部依赖。

- **周期噪声**：对白噪声做二维 FFT，按 `k^-beta` 衰减频谱，逆变换得到可平铺
  的平滑噪声。`beta` 越大越平滑；气态巨行星的云带用 1.5–1.7，星场用白噪声点。
- **云带**：以纬度为主相位（`sin(n·lat + warp)`），用低频噪声做域扭曲，再叠
  一层纬向湍流；棕色/金色色带用 `np.interp` 做颜色查找。不要加入过高的
  频率：11° 的行星盘在 1080p 只有约 200 px，细噪声会变成闪烁的斑点。
- **星场**：随机星点 + 小十字晕，亮度按幂律分布（少量亮星、大量暗星）。
  用等距圆柱环境纹理（`ShaderNodeTexEnvironment`）贴合世界背景，行星会自然
  遮挡星空，暗面因此有剪影。
- **写入图像**：`img.pixels.foreach_set` 需要连续 float32 缓冲；Blender 的像素
  缓冲自下而上，数组第 0 行是北，写入前要翻转：

```python
flat = np.ascontiguousarray(rgba[::-1], dtype=np.float32).reshape(-1)
img.pixels.foreach_set(flat)
img.pack()
```

- **随机种子**：`hash("name")` 在 Python 进程间是随机化的，不能用于可复现纹理
  的种子；用固定整数或稳定校验和。

## 5. 大地形网格（从 `.npy` 高度场）

区域包（`region pack` / S3 窗口）给出 `height.meters.npy` 与 `meta.json`。
一千个格点的边长会产生百万顶点，逐点 `from_pydata` 很慢；用 `foreach_set`
批量写顶点、循环与面：

```python
mesh.vertices.add(n * n)
mesh.vertices.foreach_set("co", verts.ravel())
mesh.loops.add(nf * 4)
mesh.loops.foreach_set("vertex_index", quads.astype(np.int32))
mesh.polygons.add(nf)
mesh.polygons.foreach_set("loop_start", np.arange(nf, dtype=np.int32) * 4)
mesh.polygons.foreach_set("loop_total", np.full(nf, 4, dtype=np.int32))
mesh.update(calc_edges=True)
for poly in mesh.polygons:
    poly.use_smooth = True
```

- 相机位于地形中心时，把网格坐标减去相机的地面偏移，让相机保持在原点，
  天空物体就不需要跟着平移。
- 地形在海平面以下的部分保留原高度即可；海面用一个位于 z=0 的大平面遮挡，
  不要在网格上做 z 裁剪，否则海岸会出现 z-fighting。
- 海面材质用低粗糙度 Principled + 程序化 Bump；噪波坐标用 Object，尺度以
  公里计。这样晨光会在水面上形成一条反射光路，而不是一块平涂的蓝。

## 6. Blender 5.2 的合成器 API

Blender 5.x 把合成器改成了节点组数据块，旧的 `scene.node_tree` 不再存在：

```python
nt = bpy.data.node_groups.new("SkyCompositor", "CompositorNodeTree")
scene.compositing_node_group = nt
rl = nt.nodes.new("CompositorNodeRLayers")
gl = nt.nodes.new("CompositorNodeGlare")
gl.inputs["Type"].default_value = "Fog Glow"
gl.inputs["Quality"].default_value = "High"
gl.inputs["Threshold"].default_value = 0.8
gl.inputs["Strength"].default_value = 0.45
gl.inputs["Size"].default_value = 0.55
nt.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
out = nt.nodes.new("NodeGroupOutput")
nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
nt.links.new(gl.outputs["Image"], out.inputs["Image"])
```

Glare 节点也换了接口：旧版的 `glare_type` / `quality` / `mix` 属性不存在，
改为 `Type`、`Quality`、`Strength`、`Size` 等输入端口；输出端要接
`NodeGroupOutput`，不能再用 `CompositorNodeComposite`。

## 7. 相机运动与运动模糊

- 天文镜头的相机常从地平线附近快速上摇到天顶附近；如果匀速插值，中间会留出
  很长一段空白天空。用三个关键帧（起幅、中点偏后、收幅）可以让前半段快、后半段
  慢，减少空白。
- 四元数的 Bezier 插值在两端会平缓，但在大角度旋转时中间速度可能不均匀；
  如果发现节奏不对，改用自定义的关键帧手柄或按欧拉角/轴角插值。
- 快速摇镜开启运动模糊（`scene.render.use_motion_blur = True`，shutter 0.5），
  否则星点会逐帧跳动。运动模糊会增加渲染时间，预览可以关闭。
- 行星纹理的自转速度要与设定的自转周期一致。以 4.47 h 为例，8 s 的镜头只转
  0.18°，肉眼看不出运动；要看到云带漂移必须做延时（乘以时间压缩系数），
  这属于镜头语言选择，不是物理错误。

## 8. 帧序列与编码（Windows）

不要依赖 ffmpeg 的 `-pattern_type glob`：Windows 的 gyan 构建可能没有编译
glob 支持。用连续编号的帧序列，或把跳帧预览复制成连续序列后再编码：

```bash
ffmpeg -framerate 24 -i frames/frame_%04d.png \
       -c:v libx264 -pix_fmt yuv420p -crf 18 out.mp4
```

预览可以每 4 帧渲染一次（`scene.frame_step = 4`），再按 6 fps 编码成同样时长
的样片；正式版按 24 fps 全帧渲染。

## 9. 可复现性

- 把镜头的所有输入（观察点、天体高度角/视直径、相位、卫星位置、颜色、相机与
  FOV）写成一份 JSON 状态文件，脚本只消费状态文件，不写死正典数字。
- 每张静帧/每段动画旁边写同名 sidecar JSON：状态文件 sha256、分辨率、采样、
  曝光、辐照度缩放、Blender 版本、相机参数。工程可以从「状态 + 脚本 + 种子」
  完整重建。
- 纹理生成用固定种子；渲染用固定 `scene.cycles.seed`、OpenImageDenoise。
- 对没有观测真值的世界，相位与视直径等量应从世界目录的 catalog 推导；
  轨道没有存历元时，画面里的「连珠」只能算代表构型，不能冒充真实历表。

## 10. 常见坑速查

| 现象 | 原因 | 处理 |
|------|------|------|
| 天空渐变上下颠倒 | `Incoming` 是视线反向 | 高度用 `-z`，太阳点积取负 |
| 行星夜面被环境光洗白 | world 对漫反射光线全亮 | 用 Light Path 把漫反射降到暗环境 |
| 海面死黑、没有天空反射 | world 对 glossy 光线不可见 | 让 glossy 与 camera 看到完整天空 |
| 行星纹理是一块纯色 | UV 球极轴朝向相机 / 只看到一条纬带 | 极轴放到与视线垂直的方向 |
| 纹理写入报 `incorrect sequence item type` | `foreach_set` 要 float32 | `astype(np.float32)` |
| 近天顶相机滚转跳变 | `to_track_quat` 在视线≈世界上方向时退化 | 显式构造 right/up 基向量 |
| 合成器报 `Scene has no node_tree` | Blender 5.x 改为节点组 | `scene.compositing_node_group` |
| Glare 节点没有 `glare_type` | 5.x 改为输入端口 | `gl.inputs["Type"]` 等 |
| 1M 顶点地形构建极慢 | 逐点 `from_pydata` | `foreach_set` 批量写 |
| 星点逐帧闪烁 | 快速摇镜未开运动模糊 | 开 motion blur 或降速 |
| ffmpeg 报 glob 不支持 | Windows 构建缺 glob | 连续编号序列或 concat |

## 11. 深空场景生态（addon / 扩展 / agent skill，2026-11 调研）

手搓星场/星云/碎石带能跑通但审美上限低；社区现成件把「看起来贵」的层外包，
参数仍可脚本化回灌状态文件保持可重建。按用途选：

| 件 | 给什么 | 许可 |
|----|--------|------|
| Dust Particles+ | 3D 多层星场粒子——相机移动时的**真实视差星迹**（等距圆柱 env 贴图星场无视差，冲刺/推镜镜头的质感短板） | 免费 |
| Nebula Generator | 程序化星云 world/体积 shader，带控制面板与 Python 接口 | 免费（Cycles） |
| Astrofield Generator | cinematic 碎石/小行星带（替换手摆 icosphere 岩） | 付费 |
| SpiralForge | 几何节点程序化星系（旋臂/透镜/椭圆） | 付费 |
| StarGen / Starfield Generator | 几何节点星场+星云（与 Dust Particles+ 二选一） | 付费 |
| Physical Starlight & Atmosphere | 物理恒星光+大气散射（恒星特写镜头） | 免费 |
| synapticore-studio/astronomical | Blender 4.5+ 扩展：Astropy/FITS 导入、恒星 shader、星系节点——**真星表天空**（Gaia 位） | 开源 |
| OpenSpace | 天文馆级交互式 astroviz（NASA/ESA 支持，纪录片在用），可作真实宇宙段的渲染器/预演 | 开源 |
| 内置 Camera Rigs addon | dolly/crane 绑定，运镜设计 | 内置 |

**视图变换对深空的影响**：AgX 会把自发光天体的饱和色去饱和成灰（K/M 型星的
橙盘读作「沙滩球」的常见根因之一）；深空镜头常选 Standard（黑位纯、色饱和，
高光靠曝光与辉光控制）或 AgX + Punchy look 折中。选变换时先渲同一静帧三档对照。

**衍射芒与 bloom**：合成器 Glare 在 headless/脚本链里调参成本高且 5.x socket 化后
易接错（见 §10）；低成本替代是把十字芒**烘进星场纹理**（最亮 N 颗星画四向衰减
芒刺）、bloom 用相机朝向的加色辉光精灵（Mix Shader 以 alpha 为 Fac 的生产配方）。

**Agent skill 与连接器**：Anthropic 官方 Blender 连接器（2026-04，Claude for
Creative Work）让 Claude Code 驱动活 Blender 场景做目检精修；社区 skill 包
（el4cteo/blender-skills、RobLe3/cc-blender-skill）把建模/材质/烘焙/动画工作流
做成可装技能；ptrthomas/blender-agent 的「渲染→视觉自检→迭代」闭环与静帧把关
纪律同构。纪律建议：连接器/skill 只做交互精修，定稿参数回灌 headless 脚本与
状态文件——活场景与可重建链双轨不漂移。

方法论文献：[Visualizing Astronomical Data with Blender (arXiv:1306.3481)](https://arxiv.org/html/1306.3481v1)、
[BlenderProc](https://github.com/DLR-RM/BlenderProc)、
[awesome-cg-vfx-pipeline](https://github.com/cgwire/awesome-cg-vfx-pipeline)。

## 参考

- Blender 5.2 Python API：`bpy.data.node_groups`、`CompositorNodeGlare`、
  `ShaderNodeTexEnvironment`、`Image.pixels`
- 深空 addon 来源：[Nebula Generator docs](https://nebula-generator.readthedocs.io/)、
  [Dust Particles+ 教程](https://www.creativeshrimp.com/create-3d-starfield-in-blender-using-a-free-add-on.html)、
  [astronomical 扩展](https://github.com/synapticore-studio/astronomical)、
  [Nebula Generator Python 支持帖](https://blenderartists.org/t/nebula-generator/347516)
- 本仓库区域地形渲染：`scripts/media/blender/region_still.py`、
  `docs/design/pipelines/region-pack.md`
- Cycles 设备与硬件基线：`docs/design/pipelines/region-pack.md` 第 5 节
