import type { TFunction } from 'i18next'
import type { MonthlyClimateData } from '../../api/monthlyClimate'

export function climateWindowLabel(t: TFunction<'map'>, data: MonthlyClimateData | null, index: number) {
  if (data?.month0 === 'vernal_equinox') {
    const months = t('months', { returnObjects: true }) as unknown as string[]
    if (months[index]) return months[index]
  }
  return t('time.windowNumber', { number: index + 1 })
}
