# 大陆边缘：陆架、坡折与陆坡

本文整理大陆边缘（陆架、陆架坡折、陆坡）的形成机制与地球观测值，以及它们在地形引擎里的对应实现。

## 1. 陆架是被淹没的大陆地壳

大陆地壳厚约 35 km、密度低，按地壳均衡浮得高；洋壳厚约 7 km、密度高，处在 4–6 km 深的洋底。大陆边缘
被海水淹没的那一部分大陆地壳就是陆架：海浪和水流把它削平，沉积物把低处填到浪基面附近，形成平缓的
平台。陆架的外缘是陆架坡折，坡折以外是陆坡；陆坡的坡脚大致对应大陆–大洋地壳边界（continent–ocean
boundary，下称陆洋边界），再往外是陆隆和深海平原。

地球上大陆地壳约占地表 41%，陆地约占 29%，两者之差约 12% 的地表就是淹没的大陆地壳，包括陆架、陆坡和
海底高原（Cogley 1984）。

## 2. 陆架坡折深度

坡折是陆架平台的外缘。陆架在长期最低海面附近被海浪削平、被沉积物填平，所以坡折深度首先由低海面幅度决定：

```
h_坡折 ≈ |A_低海面|（加上低海面期浪和流仍能改造海底的深度）
```

| 量 | 地球值 | 出处 |
|---|---|---|
| 末次冰盛期全球海平面 | 约 −134 m（距今 2.9–2.1 万年） | Lambeck et al. 2014 |
| 陆架坡折平均水深 | 132 m | Shepard 1963 |

两者几乎相等，说明在地球上浪基面附加的深度很小，坡折基本就在长期最低海面的位置。浪基面约为海浪的半个波长
（Peters & Loss 2012）；深水波长 `λ = gT²/2π`，充分成长海况的周期正比于风速除以重力，所以浪基面正比于 U²/g。
浪基面随海况和陆架开阔程度连续变化，没有固定深度，风暴浪在开阔海岸可深于 100 m（Peters & Loss 2012）。潮差大的
海岸，潮流在整个陆架上都能搬运沉积物，形成潮流沙脊，但不改变坡折由低海面控制这一点。

## 3. 陆架宽度与坡度

陆架宽度大致等于坡折深度除以陆架平均坡度：`W ≈ h_坡折 / tan θ`。全球陆架平均宽约 80 km、坡折平均水深约
130 m（Shepard 1973；Emery 1981；见 Helland-Hansen et al. 2012 的综述），对应平均坡度约 0.1°（约 1.6 m/km）。宽度的空间
变化由陆缘类型决定；Harris et al. (2014) 的全球海底地貌图给出被动陆缘陆架平均宽 88 km、主动陆缘 31 km：

| 陆缘类型 | 陆架宽度 | 机制 |
|---|---|---|
| 被动陆缘 | 几十至上千公里（西伯利亚约 1500 km） | 裂解时被拉薄的陆壳随岩石圈冷却热沉降（McKenzie 1978，时间常数约 60 Myr），沉积物填平沉降空间；陆缘越老、沉积物越多，陆架越宽 |
| 俯冲型主动陆缘 | 通常窄于 20–30 km，许多地方没有陆架 | 弧前区陡峭、持续变形，沉积空间被构造侵蚀 |
| 转换型陆缘 | 窄 | 走滑边界陡直 |

陆架约占全球海底面积的 8.9%（Harris et al. 2014）。在 20 万格的 CVT 网格上（格距约
50 km）对 ETOPO1 取样，0 至 −200 m 且与海岸相连的海底约 2620 万 km²，约一半的海岸格外侧不足一个格距就深于
200 m。

## 4. 陆坡

陆坡平均坡度约 4°（约 70 m/km；Brothers et al. 2018 引述的全球平均值）。Harris et al. (2014) 统计的陆坡平均宽度
为被动陆缘 46 km、主动陆缘 36 km。

## 5. 引擎实现

`map/terrain_synthesizer.py` 的 `_shelf_profile`：

- 陆架铺在与海岸相连的淹没大陆地壳上，宽度取海岸线到该陆壳陆洋边界的距离；地壳划分只有正常陆壳与洋壳两档、
  陆壳面积约等于陆地面积，缺少拉薄陆缘，所以每段海岸另补一条按陆缘类型取宽的淹没陆缘带（被动 88 km、主动
  31 km，取 Harris et al. 2014 的全球平均），陆架取两者中较远的一个；
- 陆架平台从岸边线性降到坡折深度 `shelf_break_depth_m`，世界输入参数，按该世界的长期低海面幅度推导
  （地球式默认 130 m）；
- 坡折以外按约 4° 下降，直到与原有海底相交，原有海底更浅时保留原值；
- 距离从海陆格之间的 Voronoi 边量起，每格取剖面在本格范围内的平均值。

已知局限：陆缘带宽度在同一陆缘类型内是常数，真实陆架宽度还随陆缘年龄与沉积物供应变化很大；在约 54 km 的
格距上，被动海岸的第一环格子因此得到几乎相同的格内平均深度，深度分布在 −20 至 −30 m 留有尖峰。以后由
「历史契约」提供陆缘年龄后，宽度改由年龄推出。

## 参考资料

- Shepard, F. P. (1963). *Submarine Geology*, 2nd ed. Harper & Row.
- Lambeck, K., Rouby, H., Purcell, A., Sun, Y., & Sambridge, M. (2014). Sea level and global ice volumes from the Last Glacial Maximum to the Holocene. *PNAS*, 111(43), 15296–15303.
- Peters, S. E., & Loss, D. P. (2012). Storm and fair-weather wave base: A relevant distinction? *Geology*, 40(6), 511–514.
- Harris, P. T., Macmillan-Lawler, M., Rupp, J., & Baker, E. K. (2014). Geomorphology of the oceans. *Marine Geology*, 352, 4–24.
- McKenzie, D. (1978). Some remarks on the development of sedimentary basins. *Earth and Planetary Science Letters*, 40, 25–32.
- Helland-Hansen, W., Steel, R. J., & Sømme, T. O. (2012). Shelf genesis revisited. *Journal of Sedimentary Research*, 82(3), 133–148.（引 Shepard 1973、Emery 1981 的全球平均宽度与坡折水深）
- Brothers, D. S., et al. (2018). Slope failure and mass transport processes along the Queen Charlotte Fault, southeastern Alaska. *Geological Society, London, Special Publications*, 477.（引述大陆坡平均坡度约 4°）
- Cogley, J. G. (1984). Continental margins and the extent and number of the continents. *Reviews of Geophysics*, 22(2), 101–122.
