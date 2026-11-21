import { useTranslation } from 'react-i18next'
import type { LonLat } from '../map/utils/mapCoords'
import type { ElevationRaster } from './elevationRaster'
import type { PackWindow } from './packCoords'
import { regionFieldAt, regionFieldLabel, regionFields, type RegionPackBaseLayer, type RegionRasterSource } from './regionPackLayers'
import type { ProbeResult } from './types'
import { CoordinateFields, FieldGroup, FieldValue } from '../../components/map/MapInspectorFields'

interface ProbePanelProps {
  point: LonLat | null
  probe: ProbeResult | null
  loading: boolean
  error: string | null
  condition?: { layer: RegionPackBaseLayer; source: RegionRasterSource; window: PackWindow; raster?: ElevationRaster }
}

export default function ProbePanel({ point, probe, loading, error, condition }: ProbePanelProps) {
  const { t } = useTranslation('map')

  if (!point) {
    return (
      <p className="text-xs leading-relaxed text-gray-400">
        {t('packs.probePrompt')}
      </p>
    )
  }

  const sample = condition?.raster && regionFieldAt(point, condition.window, condition.raster)
  const regimeLabel = (regime: number | null): string => {
    if (regime === null) return '—'
    return regime === 0 ? t('packs.regime.perennial') : t('packs.regime.nonPerennial')
  }

  return (
    <div className="space-y-2">
      <FieldGroup icon="compass" label={t('inspector.position')} defaultOpen>
        <CoordinateFields point={point} digits={4} />
        {sample && <FieldValue label={t('packs.field.cell')}>[{sample.row}, {sample.col}]</FieldValue>}
        {!condition && probe && !loading && <FieldValue label={t('packs.field.cell')}>[{probe.row}, {probe.col}]</FieldValue>}
      </FieldGroup>

      {loading && <div role="status" className="text-xs text-gray-400">{t('packs.probing')}</div>}
      {error && <div role="alert" className="break-words text-xs text-red-400">{error}</div>}

      {condition && sample && <FieldGroup icon={condition.layer === 'terrain' ? 'geology' : 'climate'}
        label={t(`packs.conditions.${condition.source}`)} defaultOpen>
        <FieldValue label={t(regionFieldLabel(condition.layer, condition.source))}>
          {sample.value.toFixed(2)} {regionFields[condition.layer].unit}
        </FieldValue>
      </FieldGroup>}
      {!condition && probe && !loading && (
        <>
          {(probe.height_m !== null || probe.input_height_m !== undefined || probe.river_flow_accum !== null) &&
          <FieldGroup icon="geology" label={t('layer.terrain')} defaultOpen>
            {probe.input_height_m !== undefined && <FieldValue label={t('packs.refinement.original')}>
              {probe.input_height_m.toFixed(1)} m
            </FieldValue>}
            {probe.height_m !== null && <FieldValue label={t(probe.input_height_m === undefined ? 'packs.field.height' : 'packs.refinement.adopted')}>
              {probe.height_m.toFixed(1)} m
            </FieldValue>}
            {probe.height_m !== null && probe.input_height_m !== undefined && <FieldValue label={t('packs.layers.heightChange')}>
              {probe.height_m >= probe.input_height_m ? '+' : ''}{(probe.height_m - probe.input_height_m).toFixed(1)} m
            </FieldValue>}
          </FieldGroup>}
          {probe.river_flow_accum !== null && <FieldGroup icon="climate" label={t('packs.conditions.hydrology')} defaultOpen>
            <FieldValue label={t('packs.field.riverFlow')}>
              {probe.river_flow_accum.toFixed(0)} · {regimeLabel(probe.river_regime)}
            </FieldValue>
          </FieldGroup>}
        </>
      )}

    </div>
  )
}
