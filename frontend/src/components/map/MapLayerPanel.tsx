/**
 * MapLayerPanel — grouped layer tree with slot semantics.
 *
 * Every layer has a KIND (see helpContent.ts) that defines how it stacks:
 *  - `base`     — opaque canvas, exactly one active (radio, slot:base)
 *  - `thematic` — whole-map coloring over the base, at most one active
 *                 (radio with a "none" option, slot:thematic)
 *  - `fill` / `feature` — freely stackable overlays (eye toggle + opacity
 *                 slider, GIS-style), grouped with a tri-state group checkbox
 *
 * Groups (地形·海陆 / 地质构造 / 气候 / …) are thematic UI organisation
 * only; compositing z-order is kind-driven: base → thematic → fill → feature.
 *
 * The flat `layers: Record<ColorMode, number>` opacity map remains the single
 * source of truth — this panel enforces the slot constraints on change, so
 * downstream (renderer, URL-free state, static mode) is unaffected.
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

/** A group with its member layers, split by interaction style. */
interface LayerGroup {
  id: string
  label: string
  /** base + thematic members (radio rows). */
  radioMembers: LayerHelpEntry[]
  /** fill + feature members (eye toggle + slider rows). */
  toggleMembers: LayerHelpEntry[]
}

/** True when the layer kind participates in a single-slot (radio) UI. */
function isRadioKind(l: LayerHelpEntry): boolean {
  return l.kind === 'base' || l.kind === 'thematic'
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

  const groups = useMemo<LayerGroup[]>(
    () =>
      LAYER_GROUPS.map((g) => {
        const members = LAYER_HELP.filter((l) => l.group === g.id)
        return {
          ...g,
          radioMembers: members.filter(isRadioKind),
          toggleMembers: members.filter((l) => !isRadioKind(l)),
        }
      }).filter((g) => g.radioMembers.length > 0 || g.toggleMembers.length > 0),
    [],
  )

  const opacityOf = useCallback(
    (l: LayerHelpEntry) => state.layers[l.id] ?? l.defaultOpacity,
    [state.layers],
  )

  /**
   * Apply an opacity patch enforcing slot constraints: turning ON a
   * base/thematic layer turns OFF every other layer of the same kind.
   * fill/feature layers are unconstrained.
   */
  const applyPatch = useCallback(
    (patch: Partial<LayerOpacities>) => {
      const next: LayerOpacities = { ...state.layers, ...patch }
      for (const [id, v] of Object.entries(patch)) {
        if (!v || v <= 0) continue
        const entry = LAYER_HELP.find((l) => l.id === id)
        if (!entry || !isRadioKind(entry)) continue
        for (const other of LAYER_HELP) {
          if (other.kind === entry.kind && other.id !== id) {
            next[other.id] = 0
          }
        }
      }
      onChange({ layers: next })
    },
    [state.layers, onChange],
  )

  /** Groups with nothing visible start collapsed; the rest start open. */
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    for (const g of groups) {
      const members = [...g.radioMembers, ...g.toggleMembers]
      const anyVisible = members.some((l) => (state.layers[l.id] ?? l.defaultOpacity) > 0)
      init[g.id] = !anyVisible
    }
    return init
  })

  /** Select a base/thematic layer into its slot. */
  const selectSlotLayer = useCallback(
    (l: LayerHelpEntry) => {
      const op = l.defaultOpacity > 0 ? l.defaultOpacity : l.kind === 'base' ? 1 : 0.85
      applyPatch({ [l.id]: op })
    },
    [applyPatch],
  )

  const setLayerOpacity = useCallback(
    (id: ColorMode, v: number) => {
      if (v > 0) lastNonZero.current[id] = v
      applyPatch({ [id]: v })
    },
    [applyPatch],
  )

  /** Eye toggle (fill/feature): 0 ↔ last non-zero opacity. */
  const toggleLayer = useCallback(
    (l: LayerHelpEntry) => {
      const cur = state.layers[l.id] ?? l.defaultOpacity
      const next = cur > 0 ? 0 : (lastNonZero.current[l.id] ?? (l.defaultOpacity > 0 ? l.defaultOpacity : 0.8))
      setLayerOpacity(l.id, next)
    },
    [state.layers, setLayerOpacity],
  )

  /** Group tri-state (fill/feature members only): all-visible → hide all;
   *  else → show all. Ctrl/Cmd+click resets members to defaults. */
  const toggleGroup = useCallback(
    (g: LayerGroup, e: React.MouseEvent) => {
      const visCount = g.toggleMembers.filter((l) => (state.layers[l.id] ?? l.defaultOpacity) > 0).length
      const allVisible = visCount === g.toggleMembers.length
      const patch: Partial<LayerOpacities> = {}
      for (const l of g.toggleMembers) {
        if (e.ctrlKey || e.metaKey) {
          patch[l.id] = l.defaultOpacity
        } else if (allVisible) {
          patch[l.id] = 0
        } else {
          patch[l.id] = lastNonZero.current[l.id] ?? (l.defaultOpacity > 0 ? l.defaultOpacity : 0.8)
        }
      }
      applyPatch(patch)
    },
    [state.layers, applyPatch],
  )

  const toggleCollapse = useCallback((gid: string) => {
    setCollapsed((c) => ({ ...c, [gid]: !c[gid] }))
  }, [])

  /** One-line summary for radio-only group headers (active member or 无). */
  const radioSummary = (g: LayerGroup): string =>
    g.radioMembers.find((l) => opacityOf(l) > 0)?.label ?? '无'

  return (
    <div className="space-y-4">
      {groups.map((g) => {
        const hasToggles = g.toggleMembers.length > 0
        const visCount = g.toggleMembers.filter((l) => (state.layers[l.id] ?? l.defaultOpacity) > 0).length
        const checkState = visCount === 0 ? 'none' : visCount === g.toggleMembers.length ? 'all' : 'some'
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
              {hasToggles && (
                <button
                  type="button"
                  onClick={(e) => toggleGroup(g, e)}
                  className="p-0.5 rounded hover:bg-gray-700/40"
                  title="整组开/关（Ctrl/⌘+点击：重置为默认）"
                >
                  <GroupCheck state={checkState} />
                </button>
              )}
              <button
                type="button"
                onClick={() => toggleCollapse(g.id)}
                className="flex-1 text-left text-xs text-gray-300 hover:text-white"
              >
                {g.label}
              </button>
              {hasToggles ? (
                <span className="text-[10px] font-mono tabular-nums text-gray-600">
                  {visCount}/{g.toggleMembers.length}
                </span>
              ) : (
                <span className="text-[10px] text-gray-600 truncate max-w-[72px]">
                  {radioSummary(g)}
                </span>
              )}
            </div>

            {open && (
              <div className="mt-1.5 ml-[7px] pl-2.5 border-l border-gray-800 space-y-1.5">
                {/* Radio rows (thematic slots). */}
                {g.radioMembers.map((l) => {
                  const active = opacityOf(l) > 0
                  return (
                    <label key={l.id} className="flex items-center gap-1.5 cursor-pointer" title={l.desc}>
                      <input
                        type="radio"
                        name={`layerslot-${l.kind}`}
                        checked={active}
                        onChange={() => selectSlotLayer(l)}
                        className="h-3 w-3 accent-neon-cyan cursor-pointer"
                      />
                      <span className={`text-[11px] ${active ? 'text-gray-200' : 'text-gray-500'}`}>
                        {l.label}
                      </span>
                    </label>
                  )
                })}

                {/* Eye + slider rows (fill / feature overlays). */}
                {g.toggleMembers.map((l) => {
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
