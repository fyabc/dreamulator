import { useTranslation } from 'react-i18next'
import { MapLayerTree, type PanelLayer } from '../../components/map/MapLayerPanel'
import { regionFieldLabel, regionFields, regionPackBaseLayers, type RegionPackBaseLayer, type RegionRasterSource } from './regionPackLayers'

interface Overlay {
  opacity: number
  onChange: (opacity: number) => void
  disabled?: boolean
}

type RegionLayerId = RegionPackBaseLayer | 'graticule' | 'rivers'
const terrainOnly: ReadonlySet<RegionPackBaseLayer> = new Set(['terrain'])
const groups = [
  { id: 'conditions', label: 'packs.conditions.title' },
  { id: 'hydrology', label: 'packs.conditions.hydrology' },
  { id: 'reference', label: 'packs.conditions.reference' },
]
const catalog: readonly PanelLayer<RegionLayerId>[] = [
  ...regionPackBaseLayers.map(id => ({ id, label: regionFieldLabel(id), desc: `packs.conditions.hint.${id}`,
    kind: 'thematic' as const, group: id === 'runoff' ? 'hydrology' : 'conditions', defaultOpacity: 1 })),
  { id: 'rivers', label: 'packs.layers.rivers', desc: 'packs.layers.regionalRivers', kind: 'feature', group: 'hydrology', defaultOpacity: 1 },
  { id: 'graticule', label: 'packs.graticule', desc: 'packs.hint.graticule', kind: 'feature', group: 'reference', defaultOpacity: 1 },
]

export default function RegionLayerPanel({ availableBase = terrainOnly, value = 'terrain', onSelect, compare, graticule, rivers, raster, notice, surfaceTemperatureOnly }: {
  availableBase?: ReadonlySet<RegionPackBaseLayer>; value?: RegionPackBaseLayer; onSelect?: (id: RegionPackBaseLayer) => void
  compare?: { original: boolean; onChange: (original: boolean) => void }
  graticule?: Overlay
  rivers?: Overlay
  raster?: { source: RegionRasterSource; choices: RegionRasterSource[]; onChange: (source: RegionRasterSource) => void; size?: string }
  notice?: 'elevationOnly' | 'missingGrid'
  surfaceTemperatureOnly?: boolean
}) {
  const { t } = useTranslation('map')
  const available = new Set<RegionLayerId>(availableBase)
  if (graticule) available.add('graticule')
  if (rivers && !rivers.disabled) available.add('rivers')
  const layers = Object.fromEntries(catalog.map(layer => [layer.id, Number(layer.id === value)])) as Record<RegionLayerId, number>
  if (graticule) layers.graticule = graticule.opacity
  if (rivers) layers.rivers = rivers.opacity
  const { range, colors, unit } = regionFields[value]
  const visibleCatalog = surfaceTemperatureOnly || (value === 'temperature' && raster?.source === 'source')
    ? catalog.map(layer => layer.id === 'temperature' ? { ...layer, label: regionFieldLabel('temperature', 'source') } : layer) : catalog
  return <div className="space-y-2">
    {notice && <p className="rounded border border-space-border px-2 py-1.5 text-[11px] leading-relaxed text-gray-400">{t(`packs.conditions.${notice}`)}</p>}
    <MapLayerTree catalog={visibleCatalog} groupCatalog={groups} available={available} state={{ layers }} isEarth={false} expandGroups
    onChange={({ layers: next }) => {
      const selected = regionPackBaseLayers.find(id => availableBase.has(id) && next[id] > 0)
      if (selected && selected !== value) onSelect?.(selected)
      if (graticule && next.graticule !== graticule.opacity) graticule.onChange(next.graticule)
      if (rivers && !rivers.disabled && next.rivers !== rivers.opacity) rivers.onChange(next.rivers)
    }} layerControls={id => id === value && <div className="mt-2 ml-[18px] space-y-2">
      {raster && raster.choices.length > 1 && <div role="group" aria-label={t('packs.conditions.rasterSource')}
        className="flex flex-wrap rounded border border-space-border bg-space-bg p-0.5">
        {raster.choices.map(source => <button key={source} type="button" aria-pressed={raster.source === source}
          onClick={() => raster.onChange(source)} className="min-h-10 flex-1 rounded px-1.5 text-[11px] text-gray-400 hover:text-white aria-pressed:bg-space-surface aria-pressed:text-neon-cyan lg:min-h-7">
          {t(`packs.conditions.${source}`)}
        </button>)}
      </div>}
      {raster && raster.source !== 'map' && raster.size && <div className="space-y-1 text-[10px] tabular-nums text-gray-400">
        <p>{t(`packs.conditions.${raster.source}`)} · {raster.size}</p>
        <div className="h-1.5 rounded" aria-hidden="true" style={{ background: `linear-gradient(to right, ${colors.join(', ')})` }} />
        <div className="flex justify-between"><span>{range[0]}</span><span>{range[1]} {unit}</span></div>
      </div>}
      {id === 'terrain' && (!raster || raster.source === 'map') && compare && <div role="group" aria-label={t('packs.refinement.compare')}
      className="flex rounded border border-space-border bg-space-bg p-0.5">
      {([true, false] as const).map(original => <button key={String(original)} type="button" aria-pressed={compare.original === original}
        onClick={() => compare.onChange(original)}
        className="min-h-10 flex-1 rounded px-1.5 text-[11px] text-gray-400 hover:text-white aria-pressed:bg-space-surface aria-pressed:text-neon-cyan lg:min-h-7">
        {t(original ? 'packs.refinement.original' : 'packs.refinement.adopted')}
      </button>)}
      </div>}
    </div>} />
  </div>
}
