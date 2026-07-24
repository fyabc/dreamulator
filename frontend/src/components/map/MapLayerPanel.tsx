/**
 * MapLayerPanel — layer visibility and color mode controls.
 *
 * Base layer: terrain / landsea (radio — mutually exclusive).
 * Overlays:   plates, boundaries (checkboxes — composite on top).
 */

import type { ColorMode } from '../../viewers/map/TerrainPlane'

interface LayerState {
  colorMode: ColorMode
  /** Show plate colours as semi-transparent overlay on terrain. */
  showPlateOverlay: boolean
  /** Show boundary-type colours as semi-transparent overlay on terrain. */
  showBoundaryOverlay: boolean
}

interface MapLayerPanelProps {
  state: LayerState
  onChange: (state: LayerState) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MapLayerPanel({ state, onChange }: MapLayerPanelProps) {
  const isOverlay = state.colorMode === 'terrain'

  return (
    <div className="space-y-4">
      {/* Base layer — radio style */}
      <div>
        <h3 className="text-[10px] font-medium text-gray-600 uppercase tracking-widest mb-1.5">基底图层</h3>
        <div className="space-y-1">
          {(['terrain', 'landsea'] as const).map((mode) => {
            const label = mode === 'terrain' ? '地形' : '海陆'
            const desc = mode === 'terrain' ? '自适应海拔着色' : '二值海陆着色'
            return (
              <button
                key={mode}
                onClick={() => onChange({ ...state, colorMode: mode, showPlateOverlay: false, showBoundaryOverlay: false })}
                title={desc}
                className={`w-full text-left px-3 py-1.5 rounded text-sm transition-colors ${
                  state.colorMode === mode ? 'bg-neon-cyan/20 text-neon-cyan' : 'text-gray-400 hover:bg-space-surface/40 hover:text-gray-300'
                }`}
              >
                {label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Overlays — checkboxes (only available when terrain is base) */}
      <div>
        <h3 className="text-[10px] font-medium text-gray-600 uppercase tracking-widest mb-1.5">
          叠加图层{!isOverlay && <span className="text-neon-cyan/50 ml-1">（需地形基底）</span>}
        </h3>
        <div className="space-y-1">
          {([
            ['plates', '板块', '按构造板块着色，半透明叠加'],
            ['boundaries', '边界类型', '汇聚(红) · 离散(绿) · 转换(黄)'],
          ] as const).map(([key, label, desc]) => {
            const checked = key === 'plates' ? state.showPlateOverlay : state.showBoundaryOverlay
            return (
              <label
                key={key}
                title={desc}
                className={`flex items-center gap-2 px-3 py-1.5 rounded text-sm cursor-pointer transition-colors ${
                  !isOverlay ? 'opacity-40 pointer-events-none text-gray-600' :
                  checked ? 'bg-neon-cyan/10 text-neon-cyan' : 'text-gray-400 hover:bg-space-surface/40'
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!isOverlay}
                  onChange={() => {
                    if (key === 'plates') onChange({ ...state, showPlateOverlay: !state.showPlateOverlay })
                    else onChange({ ...state, showBoundaryOverlay: !state.showBoundaryOverlay })
                  }}
                  className="accent-neon-cyan"
                />
                {label}
              </label>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export type { LayerState }
