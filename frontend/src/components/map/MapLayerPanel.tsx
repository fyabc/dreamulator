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

import { useCallback, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import MapLayerRadio from './MapLayerRadio'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import type { ColorMode } from '../../viewers/map/types'
import { marineKoppenBands } from '../../viewers/map/koppenDownscale'
import { LAYER_HELP, LAYER_GROUPS, type LayerHelpEntry } from './helpContent'
import { useDevModeStore } from '../../stores/devModeStore'
import { useExperimentalStore } from '../../stores/experimentalStore'
import { climateWindowLabel } from './climateTime'

type LayerOpacities = Record<ColorMode, number>

interface LayerState<Id extends string = ColorMode> {
  layers: Record<Id, number>
  inspectedLayer?: Id | null
}

export interface MapLayerDetail {
  downscaled: boolean
  available: boolean
  pending?: boolean
  failed?: boolean
  observed?: boolean
  onChange: (enabled: boolean) => void
}

interface MapLayerPanelProps<Id extends string = ColorMode> {
  state: LayerState<Id>
  onChange: (state: LayerState<Id>) => void
  available?: ReadonlySet<Id>
  temperaturePeriodLabel?: string
  /** Monthly-climate mode (driven by TimeControl). When on, monthly-capable
   *  layers show a month badge, and monthly-only layers (pressure) are live. */
  monthlyMode?: boolean
  monthlyData?: MonthlyClimateData | null
  monthIndex?: number | null
  /** Called when a monthly-only layer is selected in annual mode, to
   *  auto-enable monthly mode. */
  onMonthlyModeChange?: (mode: boolean) => void
  detail?: MapLayerDetail
  /** True for the Earth reference world — gates the earth-only diagnostic
   *  layers (ΔT/ΔP vs observed zonal climatology) which are meaningless on
   *  fictional worlds. */
  isEarth: boolean
  /** Render wind/current layers as advected particle trails instead of arrows. */
  particleMode?: boolean
  onParticleModeChange?: (mode: boolean) => void
}

/** A group with its member layers, split by interaction style. */
export type PanelLayer<Id extends string> = Omit<LayerHelpEntry, 'id' | 'detail'> & { id: Id }

interface LayerGroup<Id extends string> {
  id: string
  label: string
  /** base + thematic members (radio rows). */
  radioMembers: PanelLayer<Id>[]
  /** fill + feature members (eye toggle + slider rows). */
  toggleMembers: PanelLayer<Id>[]
}

/** True when the layer kind participates in a single-slot (radio) UI. */
function isRadioKind(l: Pick<LayerHelpEntry, 'kind'>): boolean {
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

/** Help-circle icon — links to the layer reference in the help page. */
function HelpIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export default function MapLayerPanel(props: MapLayerPanelProps) {
  return <MapLayerTree {...props} catalog={LAYER_HELP} marineLegend />
}

export function MapLayerTree<Id extends string>({ state, onChange, available, temperaturePeriodLabel, monthlyMode = false,
  monthlyData = null, monthIndex = null, onMonthlyModeChange, detail, isEarth, particleMode = false, onParticleModeChange,
  catalog, layerControls, mainControls, groupCatalog = LAYER_GROUPS, expandGroups = false, marineLegend = false }: MapLayerPanelProps<Id> & {
  catalog: readonly PanelLayer<Id>[]; groupCatalog?: readonly { id: string; label: string }[]
  layerControls?: (id: Id) => ReactNode; mainControls?: ReactNode; expandGroups?: boolean; marineLegend?: boolean
}) {
  const { t } = useTranslation('map')
  const panelId = useId()
  const [section, setSection] = useState<'main' | 'overlays'>('main')
  /** Remember the last explicit non-zero opacity so toggles can restore it. */
  const lastNonZero = useRef<Record<string, number>>({})

  const monthName = monthlyMode && monthlyData && monthIndex != null
    ? climateWindowLabel(t, monthlyData, monthIndex) : null
  const monthlyValues: Partial<Record<ColorMode, Float32Array>> = {
    temperature: monthlyData?.tMonthly,
    precipitation: monthlyData?.pMonthly,
    pressure: monthlyData?.pressureMonthly,
    pressureError: monthlyData?.pressureMonthly,
    slp: monthlyData?.slpMonthly,
    winds: monthlyData?.windEastMonthly,
  }

  /** Small month badge for monthly-capable layers (dimmed with the row). */
  const monthBadge = (l: PanelLayer<Id>, dimmed: boolean) => {
    const label = l.id === 'temperature' && temperaturePeriodLabel
      ? temperaturePeriodLabel : l.monthlyCapable && monthlyValues[l.id as ColorMode]?.length ? monthName : null
    if (!label) return null
    return <span className={`shrink-0 text-[9px] ${dimmed ? 'text-amber-300/40' : 'text-amber-300/70'}`}>·{label}</span>
  }

  const devMode = useDevModeStore((s) => s.devMode)
  const experimental = useExperimentalStore((s) => s.experimental)
  const groups = useMemo<LayerGroup<Id>[]>(
    () =>
      groupCatalog.map((g) => {
        const members = catalog.filter(
          (l) =>
            l.group === g.id &&
            (!l.devOnly || devMode) &&
            (!l.experimentalOnly || experimental) &&
            (!l.earthOnly || isEarth),
        )
        return {
          ...g,
          radioMembers: members.filter(isRadioKind),
          toggleMembers: members.filter((l) => !isRadioKind(l)),
        }
      }).filter((g) => g.radioMembers.length > 0 || g.toggleMembers.length > 0),
    [catalog, groupCatalog, devMode, experimental, isEarth],
  )

  const opacityOf = useCallback(
    (l: PanelLayer<Id>) => available && !available.has(l.id) ? 0 : state.layers[l.id] ?? l.defaultOpacity,
    [state.layers, available],
  )

  /**
   * Apply an opacity patch enforcing slot constraints: turning ON a
   * base/thematic layer turns OFF every other layer of the same kind.
   * fill/feature layers are unconstrained.
   */
  const applyPatch = useCallback(
    (patch: Partial<Record<Id, number>>) => {
      const next: Record<Id, number> = { ...state.layers, ...patch }
      const ids = Object.keys(patch) as Id[]
      for (const id of ids) {
        const v = patch[id]
        if (!v || v <= 0) continue
        const entry = catalog.find((l) => l.id === id)
        if (!entry || !isRadioKind(entry)) continue
        for (const other of catalog) {
          if (other.kind === entry.kind && other.id !== id) {
            next[other.id] = 0
          }
        }
      }
      const selected = ids.filter(layer => (patch[layer] ?? 0) > 0)
      onChange({ layers: next, inspectedLayer: selected[selected.length - 1] ?? state.inspectedLayer })
    },
    [catalog, state.layers, state.inspectedLayer, onChange],
  )

  /** Groups with nothing visible start collapsed; the rest start open. */
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    for (const g of groups) {
      const members = [...g.radioMembers, ...g.toggleMembers]
      const anyVisible = members.some((l) => (state.layers[l.id] ?? l.defaultOpacity) > 0)
      init[g.id] = !expandGroups && !anyVisible
    }
    return init
  })

  /** Select a base/thematic layer into its slot. */
  const selectSlotLayer = useCallback(
    (l: PanelLayer<Id>) => {
      // Monthly-only layers (pressure anomaly) have no annual counterpart —
      // selecting one while in annual mode auto-enables monthly mode.
      if (l.monthlyOnly && !monthlyMode) onMonthlyModeChange?.(true)
      const op = l.defaultOpacity > 0 ? l.defaultOpacity : l.kind === 'base' ? 1 : 0.85
      applyPatch({ [l.id]: op } as Partial<Record<Id, number>>)
    },
    [applyPatch, monthlyMode, onMonthlyModeChange],
  )

  const setLayerOpacity = useCallback(
    (id: Id, v: number) => {
      if (v > 0) lastNonZero.current[id] = v
      applyPatch({ [id]: v } as Partial<Record<Id, number>>)
    },
    [applyPatch],
  )

  /** Eye toggle (fill/feature): 0 ↔ last non-zero opacity. */
  const toggleLayer = useCallback(
    (l: PanelLayer<Id>) => {
      const cur = state.layers[l.id] ?? l.defaultOpacity
      const next = cur > 0 ? 0 : (lastNonZero.current[l.id] ?? (l.defaultOpacity > 0 ? l.defaultOpacity : 0.8))
      setLayerOpacity(l.id, next)
    },
    [state.layers, setLayerOpacity],
  )

  /** Group tri-state (fill/feature members only): all-visible → hide all;
   *  else → show all. Ctrl/Cmd+click resets members to defaults. */
  const toggleGroup = useCallback(
    (g: LayerGroup<Id>, e: React.MouseEvent) => {
    const members = g.toggleMembers.filter(layer => !available || available.has(layer.id))
    const allVisible = members.every(layer => opacityOf(layer) > 0)
      const patch: Partial<Record<Id, number>> = {}
    for (const l of members) {
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
    [available, opacityOf, applyPatch],
  )

  const toggleCollapse = useCallback((gid: string) => {
    setCollapsed((c) => ({ ...c, [gid]: !c[gid] }))
  }, [])

  /** One-line summary for radio-only group headers (active member or 无). */
  const radioSummary = (g: LayerGroup<Id>): string => {
    const active = g.radioMembers.find((l) => opacityOf(l) > 0)
    return active ? t(active.label) : t('panel.none')
  }

  return (
    <div className="space-y-3">
      <div className="flex overflow-hidden rounded-md border border-space-border" role="group" aria-label={t('panel.layerType')}>
        {(['main', 'overlays'] as const).map(type => <button key={type} type="button"
          aria-pressed={section === type} onClick={() => setSection(type)}
          className={`flex-1 px-2 py-1.5 text-[11px] first:border-r first:border-space-border focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-neon-cyan ${section === type ? 'bg-neon-cyan/15 text-gray-100' : 'text-gray-400 hover:text-gray-100'}`}>
          {t(type === 'main' ? 'panel.mainLayers' : 'panel.overlayLayers')}
        </button>)}
      </div>
      {section === 'main' && mainControls}
      {section === 'main' && detail && <div className="space-y-1.5">
        <div role="group" aria-label={t('panel.detailTitle')} title={t(detail.observed ? 'panel.observedHint' : 'panel.detailHint')}
          className="flex rounded-md border border-space-border">
          {(detail.observed && !detail.available ? [false] : [false, true]).map(downscaled => <button key={String(downscaled)} type="button"
            aria-pressed={detail.downscaled === downscaled} disabled={downscaled && !detail.available}
            onClick={() => detail.onChange(downscaled)}
            className={`flex-1 px-2 py-1.5 text-[11px] first:rounded-l-md first:border-r first:border-space-border last:rounded-r-md focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-neon-cyan disabled:opacity-45 ${detail.downscaled === downscaled ? 'bg-neon-cyan/15 text-gray-100' : 'text-gray-400 hover:text-gray-100'}`}>
            {t(detail.observed ? (downscaled ? 'panel.observedRaster' : 'panel.observedGrid') : (downscaled ? 'panel.downscaled' : 'panel.modelGrid'))}
          </button>)}
        </div>
        {(detail.failed || (detail.downscaled && detail.available)) && <p role="status" className="text-[10px] text-gray-400">
          {t(detail.observed ? (detail.failed ? 'panel.observedFailed' : detail.pending ? 'panel.observedLoading' : 'panel.observedReadout')
            : detail.pending ? 'panel.downscaling' : 'panel.downscaledReadout')}
        </p>}
      </div>}
      {section === 'main' && marineLegend && !(detail?.observed && detail.downscaled && !detail.pending) && state.layers['koppen' as Id] > 0 && (!available || available.has('koppen' as Id)) && (
        <div role="group" aria-label={t('koppen.marineLegend')} title={t('koppen.marineHint')}
          className="flex flex-wrap gap-x-2 gap-y-1 text-[10px] text-gray-300">
          {Object.entries(marineKoppenBands).map(([code, color]) => (
            <span className="inline-flex items-center gap-1" key={code}>
              <span aria-hidden="true" className="size-2 rounded-sm" style={{ backgroundColor: color }} />
              {t(`koppen.${code}`)}
            </span>
          ))}
        </div>
      )}
      {/* Wind/current display style.  The layer opacities still control the
          strength; this switch only swaps arrows for advected particles. */}
      {section === 'overlays' && onParticleModeChange && (
        <div className="flex items-center justify-between gap-2 pb-2 border-b border-space-border">
          <div className="min-w-0 cursor-help" title={t('panel.particlesHint')}>
            <span className="text-xs text-gray-300">{t('panel.particles')}</span>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={particleMode}
            disabled={available != null && !available.has('winds' as Id) && !available.has('currents' as Id)}
            onClick={() => onParticleModeChange(!particleMode)}
            className={`relative shrink-0 w-8 h-4 rounded-full transition-colors ${
              particleMode ? 'bg-neon-cyan/60' : 'bg-gray-600'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
                particleMode ? 'translate-x-4' : ''
              }`}
            />
          </button>
        </div>
      )}
      {groups.map(group => section === 'main' ? { ...group, toggleMembers: [] } : { ...group, radioMembers: [] }).map((g) => {
        if (!g.radioMembers.length && !g.toggleMembers.length) return null
        const hasToggles = g.toggleMembers.length > 0
        const toggleCount = g.toggleMembers.filter(layer => !available || available.has(layer.id)).length
        const visCount = g.toggleMembers.filter(layer => opacityOf(layer) > 0).length
        const checkState = visCount === 0 ? 'none' : visCount === toggleCount ? 'all' : 'some'
        const open = !collapsed[g.id]
        return (
          <section key={g.id}>
            <div className="flex items-center gap-1 select-none">
              <button
                type="button"
                onClick={() => toggleCollapse(g.id)}
                aria-expanded={open}
                className="p-0.5 text-gray-500 hover:text-gray-300"
                title={open ? t('panel.collapse') : t('panel.expand')}
              >
                <Chevron open={open} />
              </button>
              {hasToggles && (
                <button
                  type="button"
                  onClick={(e) => toggleGroup(g, e)}
                  disabled={toggleCount === 0}
                  className="p-0.5 rounded hover:bg-gray-700/40 disabled:opacity-40"
                  title={t('panel.groupToggle')}
                >
                  <GroupCheck state={checkState} />
                </button>
              )}
              <button
                type="button"
                onClick={() => toggleCollapse(g.id)}
                className="flex-1 text-left text-xs text-gray-300 hover:text-white"
              >
                {t(g.label)}
              </button>
              {groupCatalog === LAYER_GROUPS && g.radioMembers.length > 0 && g.radioMembers.every((l) => l.kind === 'thematic') && (
                <a
                  href={`/help#map-${g.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="p-0.5 text-gray-500 hover:text-neon-cyan"
                  title={t('panel.layerHelp', { label: t(g.label) })}
                  onClick={(e) => e.stopPropagation()}
                >
                  <HelpIcon />
                </a>
              )}
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
                  const missing = available != null && !available.has(l.id)
                  // Monthly-only layers (pressure) are dimmed in annual mode —
                  // still selectable, and selecting one auto-enables monthly.
                  const dimmed = l.monthlyOnly && !monthlyMode
                  return (
                    <div key={l.id}><MapLayerRadio name={`${panelId}-${l.kind}`} checked={active} disabled={missing}
                      title={missing ? t('panel.layerUnavailable') : t(l.desc)} label={t(l.label)} dimmed={dimmed}
                      onChange={() => selectSlotLayer(l)} onClick={() => { if (active) onChange({ ...state, inspectedLayer: l.id }) }}>
                      {monthBadge(l, dimmed || !active)}
                    </MapLayerRadio>{active && layerControls?.(l.id)}</div>
                  )
                })}

                {/* Eye + slider rows (fill / feature overlays). */}
                {g.toggleMembers.map((l) => {
                  const op = opacityOf(l)
                  const missing = available != null && !available.has(l.id)
                  const pct = Math.round(op * 100)
                  const visible = op > 0
                  // Track last non-zero for restore (matches original behaviour).
                  if (visible) lastNonZero.current[l.id] = op
                  return (
                    <div key={l.id} className={`flex items-center gap-1.5 ${missing ? 'opacity-50' : ''}`}
                      title={missing ? t('panel.layerUnavailable') : undefined}>
                      <button
                        type="button"
                        disabled={missing}
                        onClick={() => toggleLayer(l)}
                        title={missing ? t('panel.layerUnavailable') : t(l.desc)}
                        aria-label={visible ? t('panel.hideLayer', { label: t(l.label) }) : t('panel.showLayer', { label: t(l.label) })}
                        aria-pressed={visible}
                        className={`shrink-0 p-0.5 rounded transition-colors ${
                          visible
                            ? 'text-neon-cyan hover:text-white hover:bg-neon-cyan/20'
                            : 'text-gray-600 hover:text-gray-400 hover:bg-gray-700/50'
                        }`}
                      >
                        {visible ? <EyeOpen /> : <EyeClosed />}
                      </button>
                      <span className={`shrink-0 text-[11px] ${visible ? 'text-gray-300' : 'text-gray-500'}`}>
                        {t(l.label)}
                      </span>
                      {monthBadge(l, !visible)}
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={pct}
                        disabled={missing}
                        onChange={(e) => setLayerOpacity(l.id, parseInt(e.target.value) / 100)}
                        className="flex-1 min-w-0 h-1 accent-neon-cyan cursor-pointer"
                        title={t(l.desc)}
                        aria-label={t('panel.opacity', { label: t(l.label) })}
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
