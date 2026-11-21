import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import { precipitationBasisKey, type YearlyClimateData } from '../../api/yearlyClimate'
import type { CVTMesh } from '../../viewers/map/types'
import { climateWindowLabel } from './climateTime'
import {
  PRECIP_SCALE, PRECIP_TOTAL_LIMIT_MM, PRECIP_WINDOW_LIMIT_MM,
  TEMPERATURE_LIMIT_C, TEMPERATURE_SCALE, scaleGradient,
} from '../../viewers/map/utils/colorScales'

interface ClimateLegendProps {
  layer: string | null
  mesh: CVTMesh | null
  monthlyMode: boolean
  monthlyLoading: boolean
  monthlyData: MonthlyClimateData | null
  monthIndex: number
  yearlyData: YearlyClimateData | null
}

export default function ClimateLegend({
  layer, mesh, monthlyMode, monthlyLoading, monthlyData, monthIndex, yearlyData,
}: ClimateLegendProps) {
  const { t } = useTranslation('map')
  const field = layer === 'temperature' ? 'temperature_C' : layer === 'precipitation' ? 'precipitation_mm' : null
  const hasTotal = useMemo(() => !!field && mesh?.cells.some((cell) =>
    (cell.water_class != null ? cell.water_class !== 'ocean' : cell.elevation >= 0) && Number.isFinite(cell[field]),
  ), [field, mesh])
  if (!field) return null

  const monthly = monthlyMode && monthlyData != null
  const temp = field === 'temperature_C'
  const min = temp ? -TEMPERATURE_LIMIT_C : 0
  const max = temp ? TEMPERATURE_LIMIT_C : monthly ? PRECIP_WINDOW_LIMIT_MM : PRECIP_TOTAL_LIMIT_MM
  const scale = temp ? TEMPERATURE_SCALE : PRECIP_SCALE
  const gradient = scaleGradient(scale)
  const windowName = climateWindowLabel(t, monthlyData, monthIndex)
  const basis = monthly
    ? monthlyData.binDays != null ? t('time.windowWithDuration', { window: windowName, days: monthlyData.binDays }) : windowName
    : t(precipitationBasisKey(yearlyData), { days: yearlyData?.windowDays })
  const label = temp
    ? monthly ? `${t('inspector.windowTemp')} · ${basis}` : t('inspector.periodTemp')
    : t('precipWindow.total', { basis })

  return (
    <div className="flex shrink-0 flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-space-border bg-space-panel px-4 py-2 text-xs text-gray-300" data-testid="climate-legend">
      {monthly || hasTotal ? (
        <>
          <span>{label}</span>
          <span>{temp ? '≤ ' : ''}{min}</span>
          <span className="h-2 w-28 rounded" style={{ background: gradient }} />
          <span>≥ {max.toLocaleString()} {temp ? '°C' : 'mm'}</span>
          {!temp && <span className="text-gray-400">{t('legend.logScale')}</span>}
        </>
      ) : <span>{t('legend.climateMissing')}</span>}
      {monthlyMode && !monthly && (
        <span className="text-amber-200">{t(monthlyLoading ? 'legend.monthlyLoading' : 'legend.monthlyMissing')}</span>
      )}
    </div>
  )
}
