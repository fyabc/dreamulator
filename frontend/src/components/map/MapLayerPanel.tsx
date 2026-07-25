/**
 * MapLayerPanel — per-layer opacity controls (toggle + slider).
 *
 * Each of the 4 layers (terrain, landsea, plates, boundaries) can be
 * independently shown at any opacity.  Layers are composited in order.
 *
 * Click the 👁 toggle to instantly switch between 0% and 100% opacity.
 * Drag the slider for fine-grained control.
 */

import { useCallback, useRef } from 'react'
import type { ColorMode } from '../../viewers/map/TerrainPlane'
import { LAYER_HELP } from './helpContent'

type LayerOpacities = Record<ColorMode, number>

interface LayerState {
  layers: LayerOpacities
}

interface MapLayerPanelProps {
  state: LayerState
  onChange: (state: LayerState) => void
}

/* Inline SVG icons — avoids an icon-library dependency for two tiny paths. */

function EyeOpen() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function EyeClosed() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  )
}

export default function MapLayerPanel({ state, onChange }: MapLayerPanelProps) {
  /* Remember the last explicit non-zero opacity so the toggle can restore it. */
  const lastNonZero = useRef<Record<string, number>>({})

  const toggle = useCallback(
    (id: ColorMode) => {
      const current = state.layers[id] ?? 0
      const next = current > 0 ? 0 : (lastNonZero.current[id] ?? 1)
      onChange({ layers: { ...state.layers, [id]: next } })
    },
    [state, onChange],
  )

  return (
    <div className="space-y-3">
      {LAYER_HELP.map(({ id, label, desc, defaultOpacity }) => {
        const opacity = state.layers[id] ?? defaultOpacity
        const pct = Math.round(opacity * 100)
        const isVisible = opacity > 0

        // Track last non-zero for restore
        if (isVisible) lastNonZero.current[id] = opacity

        return (
          <div key={id} className="space-y-1">
            <div className="flex items-center gap-1.5">
              {/* ---- visibility toggle ---- */}
              <button
                type="button"
                onClick={() => toggle(id)}
                className={`shrink-0 p-0.5 rounded transition-colors ${
                  isVisible
                    ? 'text-neon-cyan hover:text-white hover:bg-neon-cyan/20'
                    : 'text-gray-600 hover:text-gray-400 hover:bg-gray-700/50'
                }`}
                title={isVisible ? `隐藏 ${label}` : `显示 ${label}`}
              >
                {isVisible ? <EyeOpen /> : <EyeClosed />}
              </button>

              <span className="text-xs text-gray-400">{label}</span>
              <span className={`text-[10px] font-mono tabular-nums ml-auto ${opacity > 0 ? 'text-neon-cyan' : 'text-gray-600'}`}>
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
