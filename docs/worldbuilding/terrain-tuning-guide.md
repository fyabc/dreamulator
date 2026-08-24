# 地形微调诊断指南

> 基于 nacrea 实际迭代经验（2026-08）总结。面向设计了 geography.yaml 后需要
> 对照生成结果反复微调的场景。

---

## 一、诊断第一问：预设还是生成？

看到不理想的地形，**先判断来源**——这决定了修改方向完全不同：

| 来源 | 识别方法 | 修改方式 |
|------|---------|---------|
| **geography.yaml 预设** | 搜索 feature 坐标是否匹配 | 调参数或删除 feature |
| **板块构造生成** | 边界处、未预设 region | 调 plate/tectonic 参数 |
| **fBm 噪声** | 板块内部、无明显边界特征 | 调 noise 参数 |
| **高程钉扎副作用** | 出现在有 `elevation_target_m` 的 feature 附近 | 调 pin_strength/exponent |

**操作习惯**：打开地图 → 右键 cell → 看右侧面板的板块 ID + 经纬度 → 对比 geography.yaml 坐标。

---

## 二、海拔问题诊断链

cell 海拔由五层叠加：

```
elevation = base(850m+板块偏移+大陆起伏)
          + boundary_delta (构造边界抬升/沉降)
          + regional_noise (区域 fBm × 1200m)
          + detail_noise (细节 fBm × 600m × interior_factor)
          + geography_pins (高程钉扎, 最后应用)
```

### 症状 → 原因速查

| 症状 | 最可能原因 | 调参方向 |
|------|-----------|---------|
| 大片均匀高原（板块内部） | `regional_noise_scale` 太小 | 增大 → 产生板块级起伏 |
| 海拔整体偏高 | `continental_elevation_m` + regional 偏置 | 降低 base 或加 elevation_target |
| 靠海仍是高原 | 底座太高, noise 挖不动 | 降 base 或提升 noise_amplitude |
| 海岸线太平直 | 缺少海岸带海洋倾向 | 加 weak shallow_sea feature |
| 海峡消失 | 大陆 feature 的高程钉扎盖过了裂谷 | 给裂谷段加 elevation_target_m |
| 某区域海拔特别高/低 | 板块偏移或构造边界叠加 | 用 elevation_target_m 精准调整 |

### noise_scale 与波长的换算

```
波长(km) ≈ 行星半径(km) / noise_scale
```

| scale | nacrea 波长 | 地形含义 |
|-------|------------|---------|
| 0.5 | ~13,600 km | 全球级——全行星仅 2-3 波，同板块内几乎常数 |
| 2.0 | ~3,400 km | 大陆级——单个大陆 2-3 个起伏区 |
| 3.0 | ~2,300 km | 板块级——板块内部山脊/盆地/丘陵分化 |
| 5.0 | ~1,400 km | 区域级——单个山脉/盆地尺度 |

**经验法则**：想让大陆内部有地形分化 → regional_noise_scale ≥ 2.0；想保持大陆内部平坦 → ≤ 1.0。

---

## 三、高程钉扎 (elevation pins) 使用模式

### 什么时候用

高程钉扎是**最后手段**——在所有程序化阶段完成后应用。适合：
- 压低特定大陆的平均海拔
- 强制保持海峡/裂谷深度
- 制造陆桥/地峡的精确高度
- 削平过高山脉

### 三个参数的配合

| 参数 | 作用 | 经验范围 |
|------|------|---------|
| `elevation_target_m` | 目标海拔（相对海平面） | 大陆: 500-800m，浅海: -200~-100m |
| `pin_strength` | 拉近力度 [0-1] | 大陆: 0.2-0.4，关键瓶颈: 0.5-0.8 |
| `pin_exponent` | 偏差非线性 | 削峰: 1.5-2.0，保高山: 0.5-0.7 |

### 模式速查

| 目的 | strength | exponent | 效果 |
|------|:---:|:---:|------|
| 压低大陆平均海拔 | 0.25-0.35 | 0.5-0.7 | 保高山，拉平低区 → 高原平台 |
| 削平山脉 | 0.3-0.5 | 1.5-2.0 | 山峰强力下压，平原几乎不动 |
| 强制海峡深度 | 0.5-0.8 | 1.0 | 线性强拉，确保水道连通 |
| 制造陆桥 | 0.6-1.0 | 1.0 | 硬钳到精确高度 |

### 注意事项

- **pin 在构造阶段之后应用**，不会被板块运动覆盖——但不能拯救海陆格局层面的错误
- **弱 pin (strength 0.1-0.3) 几乎看不出来**——需要用极端的 exponent 配合或直接提高 strength
- **pin 只影响高程，不影响地壳类型**——把大陆压到海平面以下不会自动变成海洋地壳
- **多个 pin 重叠时按 kernel weight 加权平均**

---

## 四、海岸线微调

### 增加海岸曲折度

```yaml
# 模式：弱 shallow_sea，不强制成海，只增加海洋倾向
- name: 某海岸浅海
  kind: shallow_sea
  lon: <经度>
  lat: <纬度>
  radius_deg: 6-10        # 覆盖海岸带
  strength: -0.2 ~ -0.35  # 弱负偏置——配合噪声自然形成曲折
  elongation: 1.5-2.5     # 沿海岸线走向拉长
  bearing_deg: <海岸走向>
```

**原理**：弱的负偏置不会把整个区域变成海，而是让噪声中的"低谷"更容易被判定为海洋。结果就是自然曲折的海岸线 + 零星内海/潟湖。

### 修复被堵住的海峡

在堵住的点加一个小型 `rift_sea` segment：

```yaml
- name: 连接段
  kind: rift_sea
  lon: <堵点经度>
  lat: <堵点纬度>
  radius_deg: 1-2          # 小型，刚好切开
  strength: -1.5 ~ -2.0    # 中等负偏置
  elongation: 1.5-2.5
  bearing_deg: <裂谷走向>
```

如果还不够 → 追加 `elevation_target_m: -200 ~ -300` + `pin_strength: 0.5-0.7`。

---

## 五、迭代工作流

### 正确流程

1. 编辑 `private/worlds/<world>/layers/geological/input/geography.yaml`
2. `uv run dreamulator build nacrea --force --data-dir private/worlds`
3. 刷新前端验证
4. 满意后同步回 `data/worlds/`

### 常见陷阱

- ❌ 在 data/worlds 编辑 → 构建用 private/worlds → 改动没生效
- ❌ 改了 geography.yaml 但没用 `--force` → 地质层被跳过
- ❌ strength 设太弱（|s| < 0.3）→ 被世界岛或其他大 feature 盖过
- ❌ pin_strength 设太小（< 0.2）→ 肉眼看不出来 → 以为 bug
- ❌ 调了 `noise_amplitude` 忘记这是**全局参数** → 影响所有大陆

### 快速验证

观察 build log 中的这些指标：
- `Water calibration: target X% land` — 如果陆地比例偏离目标太多, 海陆格局有问题
- `Geography pins: N cells pulled` — 确认 pin 确实生效了
- `T=min~max C, N land cells, M Koppen classes` — 气候输出摘要
