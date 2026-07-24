/**
 * MapLayerPanel — per-layer opacity controls (sliders).
 *
 * Each of the 4 layers (terrain, landsea, plates, boundaries) can be
 * independently shown at any opacity.  Layers are composited in order.
 */

import type { ColorMode } from '../../viewers/map/TerrainPlane'

type LayerOpacities = Record<ColorMode, number>

interface LayerState {
  layers: LayerOpacities
}

interface MapLayerPanelProps {
  state: LayerState
  onChange: (state: LayerState) => void
}

const LAYERS: { id: ColorMode; label: string; desc: string; defaultOpacity: number }[] = [
  { id: 'terrain', label: '地形', desc: '自适应海拔着色', defaultOpacity: 1 },
  { id: 'landsea', label: '海陆', desc: '二值海陆着色', defaultOpacity: 0 },
  { id: 'plates', label: '板块', desc: '按构造板块着色', defaultOpacity: 0 },
  { id: 'boundaries', label: '边界类型', desc: '汇聚(红)·离散(绿)·转换(黄)', defaultOpacity: 0 },
]

export default function MapLayerPanel({ state, onChange }: MapLayerPanelProps) {
  return (
    <div className="space-y-3">
      {LAYERS.map(({ id, label, desc, defaultOpacity }) => {
        const opacity = state.layers[id] ?? defaultOpacity
        const pct = Math.round(opacity * 100)
        return (
          <div key={id} className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">{label}</span>
              <span className={`text-[10px] font-mono tabular-nums ${opacity > 0 ? 'text-neon-cyan' : 'text-gray-600'}`}>
                {pct}%
              </span>
            </div>
            <input
              type="range"
              min="0" max="100" value={pct}
              onChange={(e) => {
                const v = parseInt(e.target.value) / 100
                onChange({ layers: { ...state.layers, [id]: v } })
              }}
              className="w-full h-1 accent-neon-cyan cursor-pointer"
              title={desc}
            />
          </div>
        )
      })}
    </div>
  )
}

export type { LayerState, LayerOpacities }
