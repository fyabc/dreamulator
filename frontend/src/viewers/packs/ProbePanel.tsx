import { useTranslation } from 'react-i18next'
import { CoordinateFields, FieldGroup, FieldValue } from '../../components/map/MapInspectorFields'
import type { LonLat } from '../map/utils/mapCoords'
import type { ElevationRaster } from './elevationRaster'
import type { PackWindow } from './packCoords'
import { regionConditionLayers, regionFieldAt, regionFieldLabel, regionFields,
  type RegionFieldLayer, type RegionPackBaseLayer, type RegionRasterSource } from './regionPackLayers'
import type { ProbeResult } from './types'

export type RegionInspectorFields = Partial<Record<RegionFieldLayer, {
  source: RegionRasterSource; raster?: ElevationRaster; loading: boolean; failed: boolean
}>>

export default function ProbePanel({ point, window, active = 'mapElevation', source, fields, original, refined, probe, river, showingOriginal }: {
  point: LonLat | null; window: PackWindow; active?: RegionPackBaseLayer; source?: RegionRasterSource
  fields?: RegionInspectorFields; original?: ElevationRaster; refined?: ElevationRaster
  probe?: ProbeResult; river?: { flow: number; regime?: number }; showingOriginal?: boolean
}) {
  const { t } = useTranslation('map')
  const sample = (raster?: ElevationRaster) => point && raster ? regionFieldAt(point, window, raster) : undefined
  const originalSample = sample(original)
  const refinedSample = sample(refined)
  const before = probe?.input_height_m ?? (probe?.height_source === 'input' ? probe.height_m : null) ?? originalSample?.value
  const after = (probe?.height_source === 'refined' ? probe.height_m : null) ?? refinedSample?.value
  const activeSample = active === 'mapElevation' ? showingOriginal ? originalSample : refinedSample ?? originalSample : sample(fields?.[active]?.raster)
  const cell = active === 'mapElevation' && probe && !showingOriginal && probe.height_source !== null ? probe : activeSample
  const reading = (value: number | null | undefined, unit: string, digits = 1) => value == null ? '—' : `${value.toFixed(digits)} ${unit}`
  const fieldValue = (layer: RegionFieldLayer) => {
    const data = fields?.[layer]
    const value = sample(data?.raster)?.value
    return <FieldValue label={t(regionFieldLabel(layer, data?.source ?? source))}>
      {!point ? '—' : data?.loading ? t('status.loading') : data?.failed ? t('packs.conditions.readError')
        : reading(value ?? null, regionFields[layer].unit, 2)}
    </FieldValue>
  }

  return <div className="space-y-2">
    {!point && <p className="text-xs leading-relaxed text-gray-400">
      <span className="[@media(pointer:coarse)]:hidden">{t('packs.probePrompt')}</span>
      <span className="hidden [@media(pointer:coarse)]:inline">{t('packs.entry.tapToProbe')}</span>
    </p>}
    <FieldGroup icon="compass" label={t('inspector.position')} alwaysOpen>
      {point ? <CoordinateFields point={point} digits={4} /> : <>
        <FieldValue label={t('inspector.longitude')}>—</FieldValue>
        <FieldValue label={t('inspector.latitude')}>—</FieldValue>
      </>}
      {cell && <FieldValue label={t('packs.field.cell')}>[{cell.row}, {cell.col}]</FieldValue>}
    </FieldGroup>
    <FieldGroup key={`height-${active}`} icon="geology" label={t(regionFieldLabel('mapElevation'))} defaultOpen={active === 'mapElevation'}>
      <FieldValue label={t('packs.refinement.original')}>{reading(before, 'm')}</FieldValue>
      {(refined || after != null) && <>
        <FieldValue label={t('packs.refinement.adopted')}>{reading(after, 'm')}</FieldValue>
        <FieldValue label={t('packs.layers.heightChange')}>
          {before == null || after == null ? '—' : `${after >= before ? '+' : ''}${(after - before).toFixed(1)} m`}
        </FieldValue>
      </>}
    </FieldGroup>
    {regionConditionLayers.map(layer => <FieldGroup key={`${layer}-${active}`} icon={layer === 'terrain' ? 'geology' : 'climate'}
      label={t(layer === 'terrain' ? 'packs.conditions.inputElevation' : regionFieldLabel(layer, source))} defaultOpen={active === layer}>
      {fieldValue(layer)}
    </FieldGroup>)}
    <FieldGroup key={`hydrology-${active}`} icon="climate" label={t('packs.conditions.hydrology')} defaultOpen={active === 'runoff'}>
      {fieldValue('runoff')}
      <FieldValue label={t('packs.field.riverFlow')}>
        {river ? <>{river.flow.toFixed(0)}{river.regime == null ? '' : ` · ${t(river.regime === 0 ? 'packs.regime.perennial' : 'packs.regime.nonPerennial')}`}</> : '—'}
      </FieldValue>
    </FieldGroup>
  </div>
}
