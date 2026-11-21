import { useId, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import { precipitationBasisKey, type YearlyClimateData } from '../../api/yearlyClimate'
import type { TemperaturePreview } from '../../playground/temperaturePreview'
import { DEFAULT_WATER_DEPTH_FACTOR, makeTerrainColor } from '../../viewers/map/layerBakes'
import { isScalarLayer, scalarFields, scalarMonthValues, scalarScale, scalarValue } from '../../viewers/map/scalarLayers'
import type { ColorMode, CVTMesh, MapMetadata } from '../../viewers/map/types'
import { scaleGradient } from '../../viewers/map/utils/colorScales'
import { climateWindowLabel } from './climateTime'

interface ClimateLegendProps {
  layer: ColorMode | null
  mesh: CVTMesh | null
  displayingMonthly: boolean
  monthlyMode: boolean
  monthlyLoading: boolean
  monthlyData: MonthlyClimateData | null
  monthIndex: number
  yearlyData: YearlyClimateData | null
  meta?: MapMetadata
  grayTerrain?: boolean
  preview?: TemperaturePreview | null
}

export default function ClimateLegend({
  layer, mesh, displayingMonthly, monthlyMode, monthlyLoading, monthlyData, monthIndex, yearlyData, meta, grayTerrain, preview,
}: ClimateLegendProps) {
  const { t, i18n } = useTranslation(['map', 'help'])
  const helpId = useId()
  const [helpOpen, setHelpOpen] = useState(false)
  const seaLevel = preview?.terrain.params.seaLevelM ?? meta?.sea_level_m ?? 0
  const minElev = preview?.terrain.params.elevMinM ?? meta?.elevation_min_m
  const maxElev = preview?.terrain.params.elevMaxM ?? meta?.elevation_max_m
  const scale = useMemo(() => {
    if (layer === 'terrain' && minElev != null && maxElev != null && minElev < maxElev) {
      const color = makeTerrainColor(minElev, maxElev, seaLevel, DEFAULT_WATER_DEPTH_FACTOR)
      const stops = Array.from({ length: 33 }, (_, index) => {
        const value = index / 32
        const elevation = minElev + value * (maxElev - minElev)
        const shade = Math.round(value * 255)
        const rgb: [number, number, number] = grayTerrain && !preview ? [shade, shade, shade] : color(elevation, elevation < seaLevel)
        return { value, color: rgb }
      })
      return { min: minElev, max: maxElev, unit: 'm', stops, log: false }
    }
    if (!isScalarLayer(layer)) return null
    const values = displayingMonthly ? scalarMonthValues(layer, monthlyData) : undefined
    if (!(layer === 'temperature' && preview) && !mesh?.cells.some((cell, index) => Number.isFinite(
      scalarValue(layer, cell, seaLevel, values, index * (monthlyData?.months ?? 0) + monthIndex, monthIndex),
    ))) return null
    return scalarScale(layer, displayingMonthly, mesh?.cells, seaLevel)
  }, [layer, minElev, maxElev, seaLevel, grayTerrain, preview, displayingMonthly, monthlyData, mesh, monthIndex])

  if (!scale || !layer) return null
  const windowName = climateWindowLabel(t, monthlyData, monthIndex)
  const basis = displayingMonthly
    ? monthlyData?.binDays != null ? t('time.windowWithDuration', { window: windowName, days: monthlyData.binDays }) : windowName
    : t(precipitationBasisKey(yearlyData), { days: yearlyData?.windowDays })
  const name = t(`layer.${layer}.label`, { ns: 'help' })
  const label = layer === 'temperature'
    ? preview && typeof preview.period === 'number' ? `${t('inspector.windowTemp')} · ${preview.label}`
      : displayingMonthly ? `${t('inspector.windowTemp')} · ${basis}` : t('inspector.periodTemp')
    : layer === 'precipitation' ? t('precipWindow.total', { basis })
      : layer === 'terrain' ? t('legend.elevationScale') : displayingMonthly ? `${name} · ${basis}` : name
  const help = [label, scale.log ? t('legend.logScale') : null,
    !preview && monthlyMode && !displayingMonthly && isScalarLayer(layer) && 'monthly' in scalarFields[layer]
      ? t(monthlyLoading ? 'legend.monthlyLoading' : 'legend.monthlyMissing') : null].filter(Boolean).join(' · ')
  const format = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 })
  const clamped = layer !== 'terrain' && layer !== 'habitable' && layer !== 'agriculture' && layer !== 'npp'

  return (
    <div className="group absolute left-3 top-3 z-30 max-w-[calc(100%-1.5rem)]">
      <button type="button" data-testid="climate-legend" aria-label={t('legend.colorScale', { layer: name })}
        aria-describedby={helpId} onClick={() => setHelpOpen(value => !value)} onBlur={() => setHelpOpen(false)}
        onKeyDown={event => { if (event.key === 'Escape') { setHelpOpen(false); event.currentTarget.blur() } }}
        className="flex min-h-9 max-w-full items-center gap-2 rounded-md border border-space-border bg-space-panel px-2.5 py-1 text-[11px] tabular-nums text-gray-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan">
        <span className="whitespace-nowrap">{clamped && scale.min !== 0 ? '≤ ' : ''}{format.format(scale.min)}</span>
        <span aria-hidden="true" className="h-2 w-20 min-w-8 rounded sm:w-28" style={{ background: scaleGradient(scale.stops) }} />
        <span className="whitespace-nowrap">{clamped ? '≥ ' : ''}{format.format(scale.max)} {scale.unit}</span>
      </button>
      <span id={helpId} role="tooltip"
        className={`${helpOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'} pointer-events-none absolute left-0 top-full mt-1 w-max max-w-[min(16rem,80vw)] rounded border border-space-border bg-space-panel px-2.5 py-1.5 text-xs text-gray-200`}>
        {help}
      </span>
    </div>
  )
}
