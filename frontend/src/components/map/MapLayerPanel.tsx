/**
 * MapLayerPanel — grouped, collapsible layer controls.
 *
 * Layers come in two kinds (see helpContent.ts):
 *  - basemaps — mutually-exclusive whole-map colorings (Paradox-style "map
 *    modes"), rendered as a single-select chip strip.
 *  - overlays — freely composable feature layers, grouped into collapsible
 *    sections with a tri-state (all / some / none) group checkbox (GIS-style).
 *
 * The flat `layers: Record<ColorMode, number>` opacity map remains the single
 * source of truth — this panel is a pure view over it, so it scales to the
 * 12–15 layers planned for climate / hydrology / civilization without the old
 * flat list overflowing the narrow sidebar.
 */

import { useCallback, useMemo, useRef, useState } from 'react'
import type { ColorMode } from '../../viewers/map/TerrainPlane'
import { LAYER_HELP, LAYER_GROUPS, type LayerHelpEntry } from './helpContent'

type LayerOpacities = Record<ColorMode, number>

interface LayerState {
  layers: LayerOpacities
}

interface MapLayerPanelProps {
  state: LayerState
  onChange: (state: LayerState) => void
}

/** An overlay group with its member layers. */
interface LayerGroup {
  id: string
  label: string
  layers: LayerHelpEntry[]
}

/* ------------------------------------------------------------------ */
/* Inline SVG icons (no icon-library dependency)                       */
/* ------------------------------------------------------------------ */

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
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7-0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  )
}

/** Collapse chevron — rotates 90° when the group is open. */
function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
         className={`transition-transform duration-150 ${open ? 'rotate-90' : ''}`}>
      <polyline points="9 6 15 12 9 18" />
    </svg>
  )
}

/** Tri-state group checkbox: check (all) / minus (some) / empty (none). */
function GroupCheck({ state }: { state: 'all' | 'some' | 'none' }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
         className={state === 'none' ? 'text-gray-600' : 'text-neon-cyan'}>
      <rect x="3.5" y="3.5" width="17" height="17" rx="4" />
      {state === 'all' && <polyline points="8 12.5 11 15.5 16.5 9" strokeWidth="2.5" />}
      {state === 'some' && <line x1="8" y1="12" x2="16" y2="12" strokeWidth="2.5" />}
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export default function MapLayerPanel({ state, onChange }: MapLayerPanelProps) {
  /** Remember the last explicit non-zero opacity so toggles can restore it. */
  const lastNonZero = useRef<Record<string, number>>({})

  const basemaps = useMemo(() => LAYER_HELP.filter((l) => l.kind === 'basemap'), [])
  const groups = useMemo<LayerGroup[]>(
    () =>
      LAYER_GROUPS.map((g) => ({
        ...g,
        layers: LAYER_HELP.filter((l) => l.kind === 'overlay' && l.group === g.id),
      })).filter((g) => g.layers.length > 0),
    [],
  )

  const opacityOf = useCallback(
    (l: LayerHelpEntry) => state.layers[l.id] ?? l.defaultOpacity,
    [state.layers],
  )

  /** The active basemap = the one with the highest non-zero opacity. */
  const activeBasemapId = useMemo(() => {
    let best: string | null = null
    let bestOp = 0
    for (const b of basemaps) {
      const op = opacityOf(b)
      if (op > bestOp) {
        best = b.id
        bestOp = op
      }
    }
    return best
  }, [basemaps, opacityOf])

  /** Groups with no visible layer start collapsed; the rest start open. */
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    for (const g of groups) {
      const anyVisible = g.layers.some((l) => (state.layers[l.id] ?? l.defaultOpacity) > 0)
      init[g.id] = !anyVisible
    }
    return init
  })

  /** Single-select a basemap: it gets its default opacity, all others → 0. */
  const selectBasemap = useCallback(
    (b: LayerHelpEntry) => {
      const next = { ...state.layers }
      for (const bm of basemaps) {
        next[bm.id] = bm.id === b.id ? (b.defaultOpacity > 0 ? b.defaultOpacity : 1) : 0
      }
      onChange({ layers: next })
    },
    [state.layers, basemaps, onChange],
  )

  const setLayerOpacity = useCallback(
    (id: ColorMode, v: number) => {
      if (v > 0) lastNonZero.current[id] = v
      onChange({ layers: { ...state.layers, [id]: v } })
    },
    [state.layers, onChange],
  )

  /** Eye toggle: 0 ↔ last non-zero opacity. */
  const toggleLayer = useCallback(
    (l: LayerHelpEntry) => {
      const cur = state.layers[l.id] ?? l.defaultOpacity
      const next = cur > 0 ? 0 : (lastNonZero.current[l.id] ?? (l.defaultOpacity > 0 ? l.defaultOpacity : 0.8))
      setLayerOpacity(l.id, next)
    },
    [state.layers, setLayerOpacity],
  )

  /** Group checkbox: all-visible → hide all; else → show all. Ctrl/Cmd+click resets to defaults. */
  const toggleGroup = useCallback(
    (g: LayerGroup, e: React.MouseEvent) => {
      const visCount = g.layers.filter((l) => (state.layers[l.id] ?? l.defaultOpacity) > 0).length
      const allVisible = visCount === g.layers.length
      const next = { ...state.layers }
      for (const l of g.layers) {
        if (e.ctrlKey || e.metaKey) {
          next[l.id] = l.defaultOpacity
        } else if (allVisible) {
          next[l.id] = 0
        } else {
          next[l.id] = lastNonZero.current[l.id] ?? (l.defaultOpacity > 0 ? l.defaultOpacity : 0.8)
        }
      }
      onChange({ layers: next })
    },
    [state.layers, onChange],
  )

  const toggleCollapse = useCallback((gid: string) => {
    setCollapsed((c) => ({ ...c, [gid]: !c[gid] }))
  }, [])

  return (
    <div className="space-y-4">
      {/* ---- basemap chip strip (single-select "map modes") ---- */}
      <section>
        <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
          底图
        </div>
        <div className="flex flex-wrap gap-1.5">
          {basemaps.map((b) => {
            const active = activeBasemapId === b.id
            return (
              <button
                key={b.id}
                type="button"
                onClick={() => selectBasemap(b)}
                title={b.desc}
                className={`px-2.5 py-1 rounded-full text-[11px] border transition-all duration-150 ${
                  active
                    ? 'bg-neon-cyan/15 border-neon-cyan/60 text-neon-cyan shadow-[0_0_8px_rgba(34,211,238,0.25)]'
                    : 'border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200'
                }`}
              >
                {b.label}
              </button>
            )
          })}
        </div>
      </section>

      {/* ---- overlay groups (collapsible, tri-state) ---- */}
      {groups.map((g) => {
        const visCount = g.layers.filter((l) => (state.layers[l.id] ?? l.defaultOpacity) > 0).length
        const checkState = visCount === 0 ? 'none' : visCount === g.layers.length ? 'all' : 'some'
        const open = !collapsed[g.id]
        return (
          <section key={g.id}>
            <div className="flex items-center gap-1 select-none">
              <button
                type="button"
                onClick={() => toggleCollapse(g.id)}
                className="p-0.5 text-gray-500 hover:text-gray-300"
                title={open ? '折叠' : '展开'}
              >
                <Chevron open={open} />
              </button>
              <button
                type="button"
                onClick={(e) => toggleGroup(g, e)}
                className="p-0.5 rounded hover:bg-gray-700/40"
                title="整组开/关（Ctrl/⌘+点击：重置为默认）"
              >
                <GroupCheck state={checkState} />
              </button>
              <button
                type="button"
                onClick={() => toggleCollapse(g.id)}
                className="flex-1 text-left text-xs text-gray-300 hover:text-white"
              >
                {g.label}
              </button>
              <span className="text-[10px] font-mono tabular-nums text-gray-600">
                {visCount}/{g.layers.length}
              </span>
            </div>

            {open && (
              <div className="mt-1.5 ml-[7px] pl-2.5 border-l border-gray-800 space-y-1.5">
                {g.layers.map((l) => {
                  const op = opacityOf(l)
                  const pct = Math.round(op * 100)
                  const visible = op > 0
                  // Track last non-zero for restore (matches original behaviour).
                  if (visible) lastNonZero.current[l.id] = op
                  return (
                    <div key={l.id} className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => toggleLayer(l)}
                        title={visible ? `隐藏 ${l.label}` : `显示 ${l.label}`}
                        className={`shrink-0 p-0.5 rounded transition-colors ${
                          visible
                            ? 'text-neon-cyan hover:text-white hover:bg-neon-cyan/20'
                            : 'text-gray-600 hover:text-gray-400 hover:bg-gray-700/50'
                        }`}
                      >
                        {visible ? <EyeOpen /> : <EyeClosed />}
                      </button>
                      <span className={`shrink-0 text-[11px] ${visible ? 'text-gray-300' : 'text-gray-500'}`}>
                        {l.label}
                      </span>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={pct}
                        onChange={(e) => setLayerOpacity(l.id, parseInt(e.target.value) / 100)}
                        className="flex-1 min-w-0 h-1 accent-neon-cyan cursor-pointer"
                        title={l.desc}
                      />
                      <span
                        className={`shrink-0 w-8 text-right text-[10px] font-mono tabular-nums ${
                          visible ? 'text-neon-cyan' : 'text-gray-600'
                        }`}
                      >
                        {pct}%
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}

export type { LayerState, LayerOpacities }
