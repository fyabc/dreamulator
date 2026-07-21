/**
 * MapLayerPanel — layer visibility and color mode controls.
 */

import type { ColorMode } from '../../viewers/map/TerrainPlane'
import { PROJECTIONS, type ProjectionType } from '../../viewers/map/utils/projection'

interface LayerState {
  colorMode: ColorMode
  showVoronoi: boolean
  showPlates: boolean
  showFeatures: boolean
}

interface MapLayerPanelProps {
  state: LayerState
  onChange: (state: LayerState) => void
  /** Current projection type. */
  projection?: ProjectionType
  /** Called when the user selects a different projection. */
  onProjectionChange?: (projection: ProjectionType) => void
}

const COLOR_MODES: { id: ColorMode; label: string; description: string }[] = [
  { id: 'terrain', label: '地形', description: '海拔着色 + 山体阴影，模拟自然地貌外观' },
  { id: 'elevation', label: '海拔', description: '灰度梯度，黑色为低处、白色为高处' },
  { id: 'landsea', label: '海陆', description: '二值着色，区分海洋和陆地，查看海陆比例' },
  { id: 'slope', label: '坡度', description: '坡度梯度，蓝(平坦) → 绿(缓坡) → 红(陡峭)' },
  { id: 'plates', label: '板块', description: '按构造板块 ID 随机着色，区分不同板块区域' },
  { id: 'boundaries', label: '边界类型', description: '显示板块边界类型：汇聚(红) · 离散(绿) · 转换(黄)' },
]

const VECTOR_LAYERS: { key: keyof LayerState; label: string; description: string; disabled?: boolean }[] = [
  { key: 'showVoronoi', label: 'Voronoi 网格', description: '显示语义网格单元格，悬停可查看属性' },
  { key: 'showPlates', label: '板块边界', description: '显示构造板块交界线（红色），板块内半透明着色' },
  { key: 'showFeatures', label: '河流 / 山脊', description: '显示从高度图提取的河流（蓝）和山脊线（橙）', disabled: true },
]

export default function MapLayerPanel({
  state,
  onChange,
  projection = 'equirectangular',
  onProjectionChange,
}: MapLayerPanelProps) {
  return (
    <div className="space-y-4">
      {/* Projection selector */}
      {onProjectionChange && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
            投影方式
          </h3>
          <p className="text-[10px] text-gray-600 mb-2">
            选择地图的球面投影方式
          </p>
          <select
            value={projection}
            onChange={(e) => onProjectionChange(e.target.value as ProjectionType)}
            className="w-full px-2 py-1.5 rounded text-sm bg-space-surface/60 text-gray-300 border border-space-border focus:border-neon-cyan/40 outline-none"
          >
            {PROJECTIONS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Color mode */}
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
          着色模式
        </h3>
        <p className="text-[10px] text-gray-600 mb-2">
          切换地形的可视化方式
        </p>
        <div className="space-y-1">
          {COLOR_MODES.map((mode) => (
            <button
              key={mode.id}
              onClick={() => onChange({ ...state, colorMode: mode.id })}
              title={mode.description}
              className={`w-full text-left px-3 py-1.5 rounded text-sm transition-colors ${
                state.colorMode === mode.id
                  ? 'bg-neon-cyan/20 text-neon-cyan'
                  : 'text-gray-400 hover:bg-space-surface/40 hover:text-gray-300'
              }`}
            >
              {mode.label}
            </button>
          ))}
        </div>
      </div>

      {/* Vector overlays */}
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
          矢量叠加
        </h3>
        <p className="text-[10px] text-gray-600 mb-2">
          开关叠加在地图上的矢量数据层
        </p>
        <div className="space-y-1">
          {VECTOR_LAYERS.map((layer) =>
            layer.disabled ? (
              <div
                key={layer.key}
                title={layer.description}
                className="flex items-center gap-2 px-3 py-1.5 rounded text-sm text-gray-600 cursor-not-allowed opacity-50"
              >
                <input type="checkbox" disabled className="accent-neon-cyan" />
                {layer.label}
                <span className="text-[10px] text-gray-600 ml-auto">即将推出</span>
              </div>
            ) : (
              <label
                key={layer.key}
                title={layer.description}
                className="flex items-center gap-2 px-3 py-1.5 rounded text-sm text-gray-400 hover:bg-space-surface/40 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={state[layer.key] as boolean}
                  onChange={(e) =>
                    onChange({ ...state, [layer.key]: e.target.checked })
                  }
                  className="accent-neon-cyan"
                />
                {layer.label}
              </label>
            ),
          )}
        </div>
      </div>

    </div>
  )
}

export type { LayerState }
