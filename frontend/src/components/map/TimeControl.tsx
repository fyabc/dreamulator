import { memo, useId, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import type { TemperaturePreview } from '../../playground/temperaturePreview'
import { MODEL_JANUARY_INDEX } from '../../playground/temperatureDraft'
import type { CVTMesh, VoronoiCell } from '../../viewers/map/types'
import AtlasIcon from '../AtlasIcon'
import { cellMonthlySeries, climateWindowLabel, isMonthlyLayer, monthlyLayers, officialMonthlyMeans, trialLandTemperatureMeans, type MonthlyLayer } from './climateTime'

interface TimeControlProps {
  monthlyMode: boolean
  onMonthlyModeChange: (mode: boolean) => void
  monthIndex: number
  onSelectMonth: (index: number) => void
  climateAvailable: boolean
  loading?: boolean
  hideModeToggle?: boolean
  series?: {
    layer: MonthlyLayer
    means: readonly number[]
    labelAt: (index: number) => string
    first: number
    scope: 'cell' | 'layer'
    cell?: { lat: number; lon: number }
  }
}

function TimeControl({ monthlyMode, onMonthlyModeChange, monthIndex, onSelectMonth, climateAvailable, loading, series, hideModeToggle = false }: TimeControlProps) {
  const { t } = useTranslation('map')
  const hintId = useId()
  const plot = series?.means.some(Number.isFinite) ? series : undefined
  const spec = plot ? monthlyLayers[plot.layer] : undefined
  const layerLabel = plot ? t(plot.layer === 'winds' ? 'time.windSpeed' : `help:layer.${plot.layer}.label`) : ''
  const name = plot && spec ? plot.scope === 'cell' && plot.cell
    ? t('time.cellValue', { layer: layerLabel, lat: plot.cell.lat.toFixed(1), lon: plot.cell.lon.toFixed(1) })
    : t(spec.landOnly ? 'time.landMean' : 'time.globalMean', { layer: layerLabel })
    : undefined
  const formatValue = (value: number) => Number.isFinite(value) ? `${value.toFixed(1)} ${spec?.unit}` : '—'
  const max = plot ? Math.max(1, ...plot.means.filter(Number.isFinite).map(Math.abs)) : 1
  const signed = plot?.means.some(value => value < 0)

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-gray-400" title={t('time.titleHint')}>{t('time.title')}</span>
        <a href="/help#map-time" target="_blank" rel="noreferrer" className="p-0.5 text-gray-500 hover:text-neon-cyan"
          aria-label={t('control.helpButton')} title={t('control.helpButton')}><AtlasIcon name="help" className="size-3.5" /></a>
      </div>
      {!hideModeToggle && <div className="flex rounded-md border border-gray-700 text-[11px]">
        <button type="button" onClick={() => onMonthlyModeChange(false)} aria-pressed={!monthlyMode}
          title={t('time.annualHint')} className={`flex-1 rounded-l-md px-2 py-1 transition-colors ${
            !monthlyMode ? 'bg-neon-cyan/20 text-gray-100' : 'text-gray-400 hover:text-gray-200'}`}>
          {t('time.annual')}
        </button>
        <button type="button" onClick={() => onMonthlyModeChange(true)} aria-pressed={monthlyMode} disabled={!climateAvailable}
          data-tutorial-anchor="monthly"
          title={t('time.monthlyHint')} className={`flex-1 rounded-r-md border-l border-gray-700 px-2 py-1 transition-colors disabled:opacity-50 ${
            monthlyMode ? 'bg-neon-cyan/20 text-gray-100' : 'text-gray-400 hover:text-gray-200'}`}>
          {t('time.monthly')}
        </button>
      </div>}
      {loading && !plot && <p role="status" className="text-[11px] text-gray-400">{t('time.loading')}</p>}
      {plot && spec && <div className="space-y-1" data-testid="monthly-layer-chart" data-layer={plot.layer}>
        <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-[11px] text-gray-300">
          <span>{name}</span>
          {monthlyMode && plot.means[monthIndex] != null && <span className="tabular-nums text-amber-200">
            {plot.labelAt(monthIndex)} · {formatValue(plot.means[monthIndex])}
          </span>}
        </div>
        <p id={hintId} className="text-[11px] text-gray-400">{t('time.chartHint')}</p>
        <div className="flex gap-0.5" role="group" aria-label={name} aria-describedby={hintId}>
          {plot.means.map((_, slot) => {
            const index = (plot.first + slot) % plot.means.length
            const value = plot.means[index]
            const valid = Number.isFinite(value)
            const active = monthlyMode && monthIndex === index
            const label = `${plot.labelAt(index)} · ${formatValue(value)}`
            return <button key={index} type="button" aria-pressed={active} aria-label={label} title={label}
              disabled={!valid} onClick={() => onSelectMonth(index)}
              className={`min-w-0 flex-1 rounded-sm px-px pb-0.5 text-[9px] tabular-nums hover:bg-neon-cyan/10 focus-visible:outline focus-visible:outline-neon-cyan disabled:opacity-40 ${active ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-gray-400'}`}>
              <span className="relative block h-11" aria-hidden="true">
                <span className={`absolute inset-x-0 h-px bg-space-border ${signed ? 'top-1/2' : 'bottom-0'}`} />
                {valid && <span className="absolute inset-x-0.5 rounded-[1px]" style={{
                  height: `${Math.max(3, Math.abs(value) / max * (signed ? 48 : 96))}%`,
                  [value < 0 ? 'top' : 'bottom']: signed ? '50%' : 0, backgroundColor: `rgb(${spec.color(value).join(',')})`,
                }} />}
              </span>
              {slot + 1}
            </button>
          })}
        </div>
      </div>}
    </div>
  )
}

export const MapTimeControl = memo(function MapTimeControl({ trialMode, preview, mesh, layer, monthlyData, cell, ...official }:
  Omit<TimeControlProps, 'climateAvailable' | 'series' | 'hideModeToggle'> & {
    trialMode: boolean; preview: TemperaturePreview | null; mesh: CVTMesh | null
    layer: string | null; monthlyData: MonthlyClimateData | null
    /** Hovered or pinned cell: the chart follows it instead of the layer mean. */
    cell?: VoronoiCell | null
  }) {
  const { t } = useTranslation('map')
  const monthlyLayer = isMonthlyLayer(layer) ? layer : null
  const means = useMemo(() => !trialMode && monthlyData && mesh && monthlyLayer
    ? officialMonthlyMeans(monthlyLayer, monthlyData, mesh.cells) : undefined, [trialMode, monthlyData, mesh, monthlyLayer])
  const cellValues = useMemo(() => !trialMode && monthlyData && mesh && monthlyLayer && cell
    ? cellMonthlySeries(monthlyLayer, monthlyData, mesh.cells, cell) : undefined,
  [trialMode, monthlyData, mesh, monthlyLayer, cell])
  if (trialMode) return <TrialTimeControl preview={preview} layer={layer} />
  const values = cellValues ?? means
  const scope = cellValues ? 'cell' as const : 'layer' as const
  return <TimeControl {...official} climateAvailable hideModeToggle loading={official.loading && monthlyLayer != null} series={values && monthlyLayer ? {
    layer: monthlyLayer, means: values, scope, cell: scope === 'cell' && cell ? { lat: cell.lat, lon: cell.lon } : undefined,
    labelAt: index => climateWindowLabel(t, monthlyData, index),
    first: monthlyData?.month0 === 'vernal_equinox' && values.length === 12 ? MODEL_JANUARY_INDEX : 0,
  } : undefined} />
})

function TrialTimeControl({ preview, layer }: { preview: TemperaturePreview | null; layer: string | null }) {
  const [lastMonth, setLastMonth] = useState(0)
  const monthly = preview?.monthly
  const terrain = preview?.terrain
  const periods = preview?.periods
  const means = useMemo(() => layer === 'temperature' && monthly && terrain && periods
    ? trialLandTemperatureMeans(periods.map(({ modelIndex }) => monthly[modelIndex]), terrain) : undefined,
  [layer, monthly, terrain, periods])
  const index = periods?.findIndex(({ modelIndex }) => modelIndex === preview?.period) ?? -1
  const selectMonth = (month: number) => {
    const period = periods?.[month]
    if (period) {
      setLastMonth(month)
      preview?.selectPeriod(period.modelIndex)
    }
  }
  return <TimeControl monthlyMode={index >= 0} monthIndex={index} climateAvailable={Boolean(periods?.length)}
    onMonthlyModeChange={monthlyMode => {
      if (monthlyMode && index < 0) selectMonth(lastMonth)
      if (!monthlyMode) preview?.selectPeriod('annual')
    }} onSelectMonth={selectMonth} series={means && periods ? {
      layer: 'temperature', means, labelAt: month => periods[month].label, first: 0, scope: 'layer',
    } : undefined} />
}
