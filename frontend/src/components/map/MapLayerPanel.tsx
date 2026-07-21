/**
 * MapLayerPanel — layer visibility and color mode controls.
 * Organized into conceptual groups: 地理, 地质.
 */

import type { ColorMode } from '../../viewers/map/TerrainPlane'

interface LayerState {
  colorMode: ColorMode
}

interface MapLayerPanelProps {
  state: LayerState
  onChange: (state: LayerState) => void
}

// ---------------------------------------------------------------------------
// Grouped mode definitions
// ---------------------------------------------------------------------------

interface ModeItem {
  id: ColorMode
  label: string
  description: string
}

interface ModeGroup {
  title: string
  items: ModeItem[]
}

const MODE_GROUPS: ModeGroup[] = [
  {
    title: '地理',
    items: [
      { id: 'terrain', label: '地形', description: '自适应海拔着色 + 山体阴影，模拟自然地貌外观' },
      { id: 'landsea', label: '海陆', description: '二值着色，区分海洋和陆地，查看海陆比例' },
    ],
  },
  {
    title: '地质',
    items: [
      { id: 'plates', label: '板块', description: '按构造板块 ID 着色，区分不同板块区域' },
      { id: 'boundaries', label: '边界类型', description: '显示板块边界类型：汇聚(红) · 离散(绿) · 转换(黄)' },
    ],
  },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MapLayerPanel({
  state,
  onChange,
}: MapLayerPanelProps) {
  return (
    <div className="space-y-4">
      {/* Grouped color modes */}
      {MODE_GROUPS.map((group) => (
        <div key={group.title}>
          <h3 className="text-[10px] font-medium text-gray-600 uppercase tracking-widest mb-1.5">
            {group.title}
          </h3>
          <div className="space-y-1">
            {group.items.map((mode) => (
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
      ))}
    </div>
  )
}

export type { LayerState }
