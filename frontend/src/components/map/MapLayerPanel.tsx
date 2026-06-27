/**
 * MapLayerPanel — layer visibility and color mode controls.
 */

import type { ColorMode } from '../../viewers/map/TerrainPlane'

interface LayerState {
  colorMode: ColorMode
  showVoronoi: boolean
  showPlates: boolean
  showFeatures: boolean
  hillshadeStrength: number
}

interface MapLayerPanelProps {
  state: LayerState
  onChange: (state: LayerState) => void
}

const COLOR_MODES: { id: ColorMode; label: string }[] = [
  { id: 'terrain', label: '地形' },
  { id: 'elevation', label: '海拔' },
  { id: 'landsea', label: '海陆' },
  { id: 'slope', label: '坡度' },
]

const VECTOR_LAYERS: { key: keyof LayerState; label: string }[] = [
  { key: 'showVoronoi', label: 'Voronoi 网格' },
  { key: 'showPlates', label: '板块边界' },
  { key: 'showFeatures', label: '河流 / 山脊' },
]

export default function MapLayerPanel({ state, onChange }: MapLayerPanelProps) {
  return (
    <div className="space-y-4">
      {/* Color mode */}
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          着色模式
        </h3>
        <div className="space-y-1">
          {COLOR_MODES.map((mode) => (
            <button
              key={mode.id}
              onClick={() => onChange({ ...state, colorMode: mode.id })}
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
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          矢量叠加
        </h3>
        <div className="space-y-1">
          {VECTOR_LAYERS.map((layer) => (
            <label
              key={layer.key}
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
          ))}
        </div>
      </div>

      {/* Hillshade strength */}
      <div>
        <label className="text-xs text-gray-400 flex justify-between">
          <span>山体阴影</span>
          <span className="font-mono">{Math.round(state.hillshadeStrength * 100)}%</span>
        </label>
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(state.hillshadeStrength * 100)}
          onChange={(e) =>
            onChange({
              ...state,
              hillshadeStrength: parseInt(e.target.value) / 100,
            })
          }
          className="w-full h-1 accent-neon-cyan"
        />
      </div>
    </div>
  )
}

export type { LayerState }
