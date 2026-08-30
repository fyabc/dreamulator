/**
 * Single source of truth for map help content.
 *
 * Layer descriptions, control shortcuts, and concept explanations are defined
 * here (as i18n keys under the `help` namespace) and imported by both the UI
 * layer panel and the HelpPage. All keys use the absolute `help:` prefix so any
 * consumer can resolve them regardless of its own namespace.
 *
 * When adding a new layer or feature, update this file — the UI and help docs
 * stay in sync automatically.
 */

import type { ColorMode } from '../../viewers/map/TerrainPlane'

/** Minimal translation function shape (matches i18next's `t`). */
type TFunc = (key: string, options?: Record<string, unknown>) => string

// ---------------------------------------------------------------------------
// Random loading tip — shown during the ~10 s globe loading to surface
// shortcuts and features users might not know about.
// ---------------------------------------------------------------------------

function buildTips(t: TFunc): string[] {
  return CONTROL_HELP.map((c) => `💡 ${t(c.action)}：${t(c.description)}`)
}

/** Return a random tip from the help system.  Stable across re-renders
 *  (the caller should memoize / pick once). */
export function getRandomTip(t: TFunc): string {
  const tips = buildTips(t)
  return tips[Math.floor(Math.random() * tips.length)]
}

// ---------------------------------------------------------------------------
// Layers
// ---------------------------------------------------------------------------

/**
 * Layer taxonomy — mirrors the slot-based compositing model (§3.1):
 *
 *   Slot 1  base     底图     exactly 1 active (radio), opaque canvas
 *   Slot 2  thematic  专题着色   0 or 1 active (radio), alpha-blended over base
 *   Slot 3  fill      分类填充   0..N (stackable), semi-transparent cell-fill
 *   Slot 4  feature   特征标注   0..N (stackable), always on top
 *
 * Groups below are UI organisation only.  Azgaar, Paradox, and Gleba all follow
 * the same pattern: ONE "map mode" (our thematic slot) active at a time, plus
 * optional overlays.
 */
export type LayerKind = 'base' | 'thematic' | 'fill' | 'feature'

/** UI layer groups (organisation only — not compositing order). */
export const LAYER_GROUPS: { id: string; label: string; icon: string }[] = [
  { id: 'terrain', label: 'help:layerGroup.terrain', icon: '⛰️' },
  { id: 'climate', label: 'help:layerGroup.climate', icon: '🌦️' },
  { id: 'ecology', label: 'help:layerGroup.ecology', icon: '🌿' },
  { id: 'civilization', label: 'help:layerGroup.civilization', icon: '🏛️' },
]

export interface LayerHelpEntry {
  id: ColorMode
  label: string
  desc: string         // one-liner for tooltip / slider (i18n key)
  detail: string       // full description for help panel (i18n key)
  defaultOpacity: number
  kind: LayerKind
  /** Group id from LAYER_GROUPS. */
  group: string
  /** Layer varies month-to-month (temperature/precipitation/pressure/wind). */
  monthlyCapable?: boolean
  /** Layer exists only in monthly mode — no annual counterpart (e.g. pressure
   *  anomaly, whose annual-mean ΔP ≈ 0). Selecting it auto-enables monthly. */
  monthlyOnly?: boolean
}

export const LAYER_HELP: LayerHelpEntry[] = [
  {
    id: 'terrain',
    label: 'help:layer.terrain.label',
    desc: 'help:layer.terrain.desc',
    detail: 'help:layer.terrain.detail',
    defaultOpacity: 1,
    kind: 'thematic',
    group: 'terrain',
  },
  {
    id: 'landsea',
    label: 'help:layer.landsea.label',
    desc: 'help:layer.landsea.desc',
    detail: 'help:layer.landsea.detail',
    defaultOpacity: 1,
    kind: 'thematic',
    group: 'terrain',
  },
  {
    id: 'plates',
    label: 'help:layer.plates.label',
    desc: 'help:layer.plates.desc',
    detail: 'help:layer.plates.detail',
    defaultOpacity: 0.8,
    kind: 'fill',
    group: 'terrain',
  },
  {
    id: 'boundaries',
    label: 'help:layer.boundaries.label',
    desc: 'help:layer.boundaries.desc',
    detail: 'help:layer.boundaries.detail',
    defaultOpacity: 0.8,
    kind: 'feature',
    group: 'terrain',
  },
  {
    id: 'flow',
    label: 'help:layer.flow.label',
    desc: 'help:layer.flow.desc',
    detail: 'help:layer.flow.detail',
    defaultOpacity: 0.7,
    kind: 'feature',
    group: 'terrain',
  },
  {
    id: 'koppen',
    label: 'help:layer.koppen.label',
    desc: 'help:layer.koppen.desc',
    detail: 'help:layer.koppen.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'climate',
  },
  {
    id: 'temperature',
    label: 'help:layer.temperature.label',
    desc: 'help:layer.temperature.desc',
    detail: 'help:layer.temperature.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'climate',
    monthlyCapable: true,
  },
  {
    id: 'precipitation',
    label: 'help:layer.precipitation.label',
    desc: 'help:layer.precipitation.desc',
    detail: 'help:layer.precipitation.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'climate',
    monthlyCapable: true,
  },
  {
    id: 'pressure',
    label: 'help:layer.pressure.label',
    desc: 'help:layer.pressure.desc',
    detail: 'help:layer.pressure.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'climate',
    monthlyCapable: true,
    monthlyOnly: true,
  },
  {
    id: 'biomes',
    label: 'help:layer.biomes.label',
    desc: 'help:layer.biomes.desc',
    detail: 'help:layer.biomes.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'ecology',
  },
  {
    id: 'npp',
    label: 'help:layer.npp.label',
    desc: 'help:layer.npp.desc',
    detail: 'help:layer.npp.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'ecology',
  },
  {
    id: 'domesticable',
    label: 'help:layer.domesticable.label',
    desc: 'help:layer.domesticable.desc',
    detail: 'help:layer.domesticable.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'ecology',
  },
  {
    id: 'soil',
    label: 'help:layer.soil.label',
    desc: 'help:layer.soil.desc',
    detail: 'help:layer.soil.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'ecology',
  },
  {
    id: 'provinces',
    label: 'help:layer.provinces.label',
    desc: 'help:layer.provinces.desc',
    detail: 'help:layer.provinces.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'ecology',
  },
  {
    id: 'habitable',
    label: 'help:layer.habitable.label',
    desc: 'help:layer.habitable.desc',
    detail: 'help:layer.habitable.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'civilization',
  },
  {
    id: 'agriculture',
    label: 'help:layer.agriculture.label',
    desc: 'help:layer.agriculture.desc',
    detail: 'help:layer.agriculture.detail',
    defaultOpacity: 0.85,
    kind: 'thematic',
    group: 'civilization',
  },
  {
    id: 'currents',
    label: 'help:layer.currents.label',
    desc: 'help:layer.currents.desc',
    detail: 'help:layer.currents.detail',
    defaultOpacity: 0.75,
    kind: 'feature',
    group: 'climate',
  },
  {
    id: 'winds',
    label: 'help:layer.winds.label',
    desc: 'help:layer.winds.desc',
    detail: 'help:layer.winds.detail',
    defaultOpacity: 0.6,
    kind: 'feature',
    group: 'climate',
    monthlyCapable: true,
  },
  {
    id: 'coastlines',
    label: 'help:layer.coastlines.label',
    desc: 'help:layer.coastlines.desc',
    detail: 'help:layer.coastlines.detail',
    defaultOpacity: 0.6,
    kind: 'feature',
    group: 'terrain',
  },
  {
    id: 'rivers',
    label: 'help:layer.rivers.label',
    desc: 'help:layer.rivers.desc',
    detail: 'help:layer.rivers.detail',
    defaultOpacity: 0.9,
    kind: 'feature',
    group: 'terrain',
  },
]

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

export interface ControlHelpEntry {
  action: string
  description: string
}

export const CONTROL_HELP: ControlHelpEntry[] = [
  { action: 'help:control.drag.action', description: 'help:control.drag.description' },
  { action: 'help:control.rightDrag.action', description: 'help:control.rightDrag.description' },
  { action: 'help:control.scroll.action', description: 'help:control.scroll.description' },
  { action: 'help:control.nKey.action', description: 'help:control.nKey.description' },
  { action: 'help:control.timeMode.action', description: 'help:control.timeMode.description' },
  { action: 'help:control.timeSeason.action', description: 'help:control.timeSeason.description' },
  { action: 'help:control.sunTime.action', description: 'help:control.sunTime.description' },
  { action: 'help:control.sunToggle.action', description: 'help:control.sunToggle.description' },
  { action: 'help:control.debugReproject.action', description: 'help:control.debugReproject.description' },
  { action: 'help:control.hoverCell.action', description: 'help:control.hoverCell.description' },
  { action: 'help:control.hoverLeave.action', description: 'help:control.hoverLeave.description' },
  { action: 'help:control.ctrlClick.action', description: 'help:control.ctrlClick.description' },
  { action: 'help:control.dblClick.action', description: 'help:control.dblClick.description' },
  { action: 'help:control.esc.action', description: 'help:control.esc.description' },
  { action: 'help:control.clickPlanet.action', description: 'help:control.clickPlanet.description' },
  { action: 'help:control.dblClickPlanet.action', description: 'help:control.dblClickPlanet.description' },
]

// ---------------------------------------------------------------------------
// Projections
// ---------------------------------------------------------------------------

export interface ProjectionHelpEntry {
  id: string
  label: string
  description: string
}

export const PROJECTION_HELP: ProjectionHelpEntry[] = [
  { id: 'equirectangular', label: 'help:projection.equirectangular.label', description: 'help:projection.equirectangular.description' },
  { id: 'mollweide', label: 'help:projection.mollweide.label', description: 'help:projection.mollweide.description' },
  { id: 'robinson', label: 'help:projection.robinson.label', description: 'help:projection.robinson.description' },
]

// ---------------------------------------------------------------------------
// Core concepts
// ---------------------------------------------------------------------------

export interface ConceptHelpEntry {
  title: string
  summary: string
}

export const CONCEPT_HELP: ConceptHelpEntry[] = [
  { title: 'help:concept.dag.title', summary: 'help:concept.dag.summary' },
  { title: 'help:concept.branch.title', summary: 'help:concept.branch.summary' },
  { title: 'help:concept.cvt.title', summary: 'help:concept.cvt.summary' },
  { title: 'help:concept.cortial.title', summary: 'help:concept.cortial.summary' },
]

// ---------------------------------------------------------------------------
// Help page sections — navigation tree consumed by HelpPage.tsx.
// Each section has an `id` used as the URL hash fragment (`/help#map-layers`).
// `title` is an i18n key; `render(t)` returns fully-localized entries.
// ---------------------------------------------------------------------------

export interface HelpSection {
  id: string
  title: string
  icon: string
  render: (t: TFunc) => { title: string; content: string }[]
}

/** Generate the i18n key references for a section's static entries. */
function entryKeys(sectionId: string, count: number): { title: string; content: string }[] {
  return Array.from({ length: count }, (_, i) => ({
    title: `help:section.${sectionId}.entries.${i}.title`,
    content: `help:section.${sectionId}.entries.${i}.content`,
  }))
}

function kindKey(kind: LayerKind): string {
  switch (kind) {
    case 'thematic': return 'help:kindThematic'
    case 'fill': return 'help:kindFill'
    case 'feature': return 'help:kindFeature'
    default: return 'help:kindBase'
  }
}

/** All help sections in sidebar order. */
export const HELP_SECTIONS: HelpSection[] = [
  {
    id: 'cli',
    title: 'help:section.cli.title',
    icon: '💻',
    render: (t) => entryKeys('cli', 7).map(({ title, content }) => ({ title: t(title), content: t(content) })),
  },
  {
    id: 'worlds',
    title: 'help:section.worlds.title',
    icon: '🌍',
    render: (t) => entryKeys('worlds', 4).map(({ title, content }) => ({ title: t(title), content: t(content) })),
  },
  ...LAYER_GROUPS.map((g) => ({
    id: `map-${g.id}`,
    title: g.label,
    icon: g.icon,
    render: (t: TFunc) => LAYER_HELP.filter((l) => l.group === g.id).map((l) => ({
      title: t(l.label),
      content: `${t(l.detail)}\n\n${t('help:layerEntrySuffix', { opacity: Math.round(l.defaultOpacity * 100), kind: t(kindKey(l.kind)) })}`,
    })),
  })),
  {
    id: 'map-controls',
    title: 'help:section.mapControls.title',
    icon: '🖱️',
    render: (t) => CONTROL_HELP.map((c) => ({ title: t(c.action), content: t(c.description) })),
  },
  {
    id: 'map-time',
    title: 'help:section.mapTime.title',
    icon: '🕒',
    render: (t) => entryKeys('mapTime', 2).map(({ title, content }) => ({ title: t(title), content: t(content) })),
  },
  {
    id: 'map-projections',
    title: 'help:section.mapProjections.title',
    icon: '📐',
    render: (t) => PROJECTION_HELP.map((p) => ({ title: t(p.label), content: t(p.description) })),
  },
  {
    id: 'stellar-viewer',
    title: 'help:section.stellarViewer.title',
    icon: '🔭',
    render: (t) => entryKeys('stellarViewer', 4).map(({ title, content }) => ({ title: t(title), content: t(content) })),
  },
  {
    id: 'globe-viewer',
    title: 'help:section.globeViewer.title',
    icon: '🌐',
    render: (t) => entryKeys('globeViewer', 3).map(({ title, content }) => ({ title: t(title), content: t(content) })),
  },
  {
    id: 'civmap',
    title: 'help:section.civmap.title',
    icon: '🏛️',
    render: (t) => entryKeys('civmap', 2).map(({ title, content }) => ({ title: t(title), content: t(content) })),
  },
  {
    id: 'concepts',
    title: 'help:section.concepts.title',
    icon: '💡',
    render: (t) => CONCEPT_HELP.map((c) => ({ title: t(c.title), content: t(c.summary) })),
  },
  {
    id: 'docs',
    title: 'help:section.docs.title',
    icon: '📚',
    render: (t) => entryKeys('docs', 4).map(({ title, content }) => ({ title: t(title), content: t(content) })),
  },
]
