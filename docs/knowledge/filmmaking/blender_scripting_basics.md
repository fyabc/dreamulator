# Blender 脚本基础（headless / bpy）

> 面向第一次写 Blender 脚本的人：怎么调用、脚本长什么样、`bpy` 的几个核心入口，
> 以及无界面运行（`-b`）时的坑。天空/行星渲染的具体做法见
> [`blender_sky_rendering.md`](blender_sky_rendering.md)；区域地形链见
> `docs/design/proposals/blender-render-pipeline.md`。
> 本机实测：Blender 5.2.2 LTS，Windows 11。

## 1. 调用方式

```bash
blender -b -P path/to/script.py -- --out renders/test.png --samples 64
```

- `-b` / `--background`：无界面后台运行，不弹 GUI。批量渲染和自动化都用它。
- `-P` / `--python`：启动后执行指定的 Python 文件。脚本里的 `import bpy` 由
  Blender 自带的 Python 提供，不需要 pip 安装。
- `--`：分隔符。它之后的内容 Blender 自己不管，脚本用 `sys.argv` 读取。
  **顺序很重要**：`--` 之前是 Blender 的参数，之后是脚本的参数。
- 其他常用：`--factory-startup`（不加载用户配置和插件，排除干扰）、
  `--python-expr "..."`（直接执行一行）、`-o`（输出路径）、`-f N`（只渲第 N 帧）、
  `-a`（渲染动画）、`-E CYCLES`（指定引擎）。

相对路径的基准不是 shell 的当前目录，而是 Blender 自己的上下文；脚本里一律
`Path(...).resolve()` 后用绝对路径。

## 2. 最小脚本

```python
import sys
from pathlib import Path
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]          # 只取 -- 之后的参数
out = Path(argv[argv.index("--out") + 1]).resolve()

bpy.ops.wm.read_factory_settings(use_empty=True)   # 清空场景
bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0))
sphere = bpy.context.active_object

bpy.ops.object.camera_add(location=(0, -4, 0), rotation=(1.5708, 0, 0))
bpy.context.scene.camera = bpy.context.active_object

bpy.ops.object.light_add(type="SUN", location=(0, 0, 4))

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"                        # 本机 OptiX
scene.cycles.samples = 64
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.filepath = str(out)
bpy.ops.render.render(write_still=True)
```

运行：

```bash
blender -b -P script.py -- --out renders/test.png
```

## 3. 三个核心入口

| 入口 | 是什么 | 什么时候用 |
|------|--------|-----------|
| `bpy.data` | blend 文件里的所有数据块（objects、meshes、materials、images、worlds…） | 创建、删除、查找数据；**后台脚本首选**，不依赖界面上下文 |
| `bpy.context` | 当前运行时状态（活动对象、选中对象、模式、场景） | 读取当前场景；后台模式下很多字段是只读或为空 |
| `bpy.ops` | 界面按钮背后的“操作符” | 快速建几何、渲染、导入导出；依赖上下文，后台脚本能少用就少用 |

`bpy.data` 是“文件里有什么”，`bpy.context` 是“界面上现在选中/激活什么”，
`bpy.ops` 是“按一下按钮”。后台脚本没有界面，所以 `bpy.data` 最可靠。

## 4. 常用对象

- **场景与集合**：`bpy.context.scene`、`scene.collection`；对象放在集合里才参与渲染。
- **对象**：`bpy.data.objects.new(name, data)`；`obj.location` / `rotation_euler`
  / `rotation_quaternion` / `scale` / `matrix_world`；父子关系 `obj.parent`。
- **网格**：`bpy.data.meshes.new()`；顶点/面可以用 `vertices.add()` +
  `vertices.foreach_set("co", ...)` 批量写，千级以上的网格不要用 Python 逐点 `from_pydata`。
- **材质与着色器**：`mat = bpy.data.materials.new(); mat.use_nodes = True`；
  `mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")`；贴图用
  `ShaderNodeTexImage`，法线用 `ShaderNodeNormalMap`。
- **世界背景**：`scene.world`；`ShaderNodeOutputWorld` + `ShaderNodeBackground`；
  方向用 `ShaderNodeNewGeometry` 的 `Incoming`。
- **相机与灯**：`bpy.data.cameras.new()`、`bpy.data.lights.new(type="SUN")`；
  相机的 `data.lens`/`sensor_fit`；太阳灯的 `energy`（W/m²）与 `angle`。
- **图像**：`bpy.data.images.load(path)`；生成图像用
  `bpy.data.images.new(name, width, height, alpha=True)` + `pixels.foreach_set`
  （连续 float32；像素缓冲自下而上）。
- **渲染**：`scene.render.engine = "CYCLES"` 或 `"BLENDER_EEVEE_NEXT"`；
  `scene.cycles.device = "GPU"`、`samples`、`use_denoising`；
  `scene.view_settings.view_transform = "AgX"`；`scene.render.filepath` +
  `bpy.ops.render.render(write_still=True)`。
- **合成器**：Blender 5.x 用 `scene.compositing_node_group`（节点组），
  不是旧版的 `scene.node_tree`；输出接 `NodeGroupOutput`。
- **关键帧**：`obj.keyframe_insert("location", frame=1)`；相机镜头用
  `cam.data.keyframe_insert("lens", frame=1)`。
- **Python 控制台**：控制台里 `C` 是 `bpy.context`、`D` 是 `bpy.data`，适合
  交互探索 API（`bpy.data.objects` 后按 Tab 看成员）。

## 5. 后台脚本的坑

| 现象 | 原因 | 处理 |
|------|------|------|
| 相对路径找不到文件 | 基准不是 shell CWD | `Path(...).resolve()` |
| `context is incorrect` | 后台没有界面上下文 | 优先 `bpy.data` 构造，少用 ops |
| 用户插件干扰结果 | 加载了用户配置 | `--factory-startup` |
| 参数读错 | 读了全部 `sys.argv` | 只取 `--` 之后的部分 |
| GPU 不生效 | 只设了 `scene.cycles.device` | 还要选 `prefs.compute_device_type`（OptiX/CUDA） |
| 渲染产物是黑的 | 没设置相机/世界/灯 | 检查 `scene.camera`、`scene.world`、光源 |
| 动画每帧很慢 | 每帧都重新构建场景 | 场景构建一次，关键帧驱动变化；预览可隔帧/降采样 |

## 6. 学习路径与中文资料

1. **官方手册（简体中文）**：<https://docs.blender.org/manual/zh-hans/latest/>
   —— 右上角切换语言；先看「脚本与扩展 Blender → 简介」与「Python 控制台」。
2. **Python 控制台（中文）**：
   <https://docs.blender.org/manual/zh-hans/5.4/editors/python_console.html>
   —— `C` / `D` 快捷键，交互探索。
3. **官方 Python API（英文，最权威）**：
   <https://docs.blender.org/api/current/> 与快速入门
   <https://docs.blender.org/api/current/info_quickstart.html>。
4. **中文辅助阅读**：知乎《Blender Python 编程：关键概念》
   <https://zhuanlan.zhihu.com/p/106406087>；书栈网《Blender 5.0 参考手册》中文
   <https://www.bookstack.cn/read/blender-5.0-zh/6e78faef6f708f98.md>；
   CSDN《Python + Blender 实现 3D 动画自动化》
   <https://blog.csdn.net/poliseed/article/details/156509620>。
5. **本仓库实例**：`scripts/media/blender/region_still.py`（区域地形静帧，
   含 Cycles 设备选择、网格构建、材质与渲染参数）；天空/行星渲染的工程笔记见
   [`blender_sky_rendering.md`](blender_sky_rendering.md)。

## 7. 参考

- Blender 5.2 Python API：`bpy.data`、`bpy.context`、`bpy.ops`、`bpy.types`
- Blender 官方手册「脚本与扩展 Blender」与「Python 控制台」
- 本仓库：`scripts/media/blender/region_still.py`、
  `docs/knowledge/filmmaking/blender_sky_rendering.md`
