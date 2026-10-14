# 植被/群系制图与卫星遥感着色

群系（biome）可视化的两条路线的参考依据与制图惯例。落地代码：
制图风 = `src/dreamulator/media/biome_render.py`（`export carto --style biome`），
遥感风 = `src/dreamulator/media/satellite_color.py` 的纹理 pass
（`export colorize --texture`，默认开）。

## 路线一：分类群系图（制图风）

**标杆参考**：Wikipedia 的 `Vegetation.png`（Olson et al. 2001 为 WWF
Global 200 做的 14 群系分类图，BioScience 51:933–938）。它是「群系图」
这一图种的事实标准，惯例如下：

- **分类平色填充**：每类一个平色，类内不做渐变；同类族（森林/草原/
  荒漠）用同色相不同深浅区分（森林系深绿、草原系黄绿、荒漠系黄褐、
  苔原/高山系灰褐紫）。
- **海洋留白**：海面不填色（纸白），只画海岸线细墨线。海洋不是陆地
  群系，入图例会误导读者。
- **图例只列图内出现的类**，配中文名；类顺序按色表规范序。
- **可加弱晕渲**（强度 ≤0.3）保持地形可读性，但类色色相必须主导——
  晕渲是底衬不是主体。

本库实现：色表取 `palettes.json` 的 `categorical.whittaker`（与前端
biome 图层同一事实源），类界用栅格发线（邻域异类像素压暗 0.72），
河流通用矢量链渲染，湖泊用淡水浅蓝平色。

## 路线二：卫星遥感风（真彩色）

**标杆参考**：NASA Blue Marble Next Generation（MODIS 月度合成，
5400×2700 全球）与 EOX Sentinel-2 cloudless（10 m 全球无云镶嵌，
s2maps.eu，CC BY 4.0）。两者都是「大气校正后的真彩色地表反射率」
风格，要点：

- **色相族由植被类型决定，明暗由长势决定**：真实卫星色 = 群系给色相
  族，NDVI/长势给明暗。对应本链 = 群系基色 + NPP 亮度调制
  （satellite_color 的 NPP_MOD_STRENGTH=0.22）。
- **地表永远有纹理**：森林冠层是公里级的细密斑驳（亚马逊 z10 瓦片
  实测），荒漠是数公里的沙丘场条带（撒哈拉瓦片），冰原几乎均匀。
  纯平色填充在放大后读作矢量图，不是遥感影像。
- 本链纹理参数（`TEXTURE_PARAMS`，每群系 波长km/振幅）：森林
  1.0–1.5 km / 0.12–0.16，草原/萨瓦纳 2.2 km / 0.10–0.11，荒漠
  4.5 km / 0.08–0.09，苔原 2.5 km / 0.07，冰 6 km / 0.03；另加
  全陆地 3 px 细颗粒（振幅 0.025）。振幅是亮度调制深度，色相不动
  （色彩权威仍在气候层）。
- **河流水色带泥沙**：亚马逊河的泥浆棕（而非海蓝）是大河的真实
  遥感色；本链目前河流用深度分级蓝色，泥沙色是登记差距。

## 已否证/不采用

- **假彩色红外（植被染红）**：是遥感分析行业的工具色，不是大众认知
  的「卫星图」，视频素材用真彩色。
- **群系图上海面填蓝色渐变**：那是地形图的测深惯例（本库 survey
  风格的做法），分类群系图的惯例是留白——两图种并存时各自遵守。

## 参考资料

- Olson, D. M., et al. (2001). *Terrestrial Ecoregions of the World: A New
  Map of Life on Earth*. BioScience 51(11):933–938.（WWF 14 群系分类）
- Wikipedia「Biome」条目配图 `Vegetation.png`（分类群系图标杆）
- NASA Blue Marble Next Generation（eoimages.gsfc.nasa.gov，公开领域）
- EOX Sentinel-2 cloudless（s2maps.eu / tiles.maps.eox.at，CC BY 4.0；
  本库参考瓦片存 private/video/reference/biome/）
