import { useTranslation } from 'react-i18next'
import type { MappingDiagnostic } from '../../api/elevationImport'

type Translate = (key: string, options?: Record<string, unknown>) => string

const roundM = (value: number) => Math.round(value).toString()
const pct = (value: number) => `${Math.round(value * 100)}%`
const fraction = (value: number) => value.toFixed(3)
const num = (d: MappingDiagnostic, key: string) => Number(d[key])

/**
 * Localized "how to adjust the mapping" advice built from the import diagnostics.
 *
 * The backend (and, for the browser creation flow, `heightmapDiagnostics`) reports
 * situations and their numbers; the sentences live in the `importer` namespace so
 * both import journeys share one wording.  Nothing here changes the mapping: every
 * suggestion names a value the author can type into the form.
 */
export default function ElevationAdvice({ diagnostics }: { diagnostics?: MappingDiagnostic[] }) {
  const { t } = useTranslation('importer')
  if (!diagnostics?.length) return null
  return (
    <ul className="space-y-1 text-sm text-amber-300 list-disc pl-5" data-testid="mapping-advice">
      {diagnostics.map((d) => {
        const message = advice(d, t)
        return message ? <li key={String(d.code)}>{message}</li> : null
      })}
    </ul>
  )
}

function advice(d: MappingDiagnostic, t: Translate): string | null {
  switch (d.code) {
    case 'range_all_sea': {
      const params = {
        brightest: pct(num(d, 'brightest')),
        top: roundM(num(d, 'top_m')),
        sea: roundM(num(d, 'sea_m')),
        black: roundM(num(d, 'min_m')),
        white: roundM(num(d, 'max_m')),
      }
      if (d.suggested_white_m === undefined) return t('diagnostic.range_all_sea_flat', params)
      return t('diagnostic.range_all_sea', { ...params, suggested: roundM(num(d, 'suggested_white_m')) })
    }
    case 'range_all_land':
      return t('diagnostic.range_all_land', {
        bottom: roundM(num(d, 'bottom_m')),
        sea: roundM(num(d, 'sea_m')),
      })
    case 'range_grey_use':
      return t('diagnostic.range_grey_use', {
        low: pct(num(d, 'low')),
        high: pct(num(d, 'high')),
        top: roundM(num(d, 'top_m')),
        white: roundM(num(d, 'max_m')),
        suggested: roundM(num(d, 'suggested_white_m')),
      })
    case 'range_darkest_share':
      return t('diagnostic.range_darkest_share', {
        level: String(Math.round(num(d, 'level'))),
        levels: String(Math.round(num(d, 'levels'))),
        share: pct(num(d, 'share')),
      })
    case 'threshold_all_sea': {
      const levels = num(d, 'levels')
      if (levels > 1) {
        return t('diagnostic.threshold_all_sea_grey', {
          brightest: Math.round(num(d, 'brightest') * levels),
          thresh: Math.round(num(d, 'thresh') * levels),
          levels,
        })
      }
      return t('diagnostic.threshold_all_sea', {
        brightest: fraction(num(d, 'brightest')),
        thresh: fraction(num(d, 'thresh')),
      })
    }
    case 'threshold_all_land': {
      const levels = num(d, 'levels')
      if (levels > 1) {
        return t('diagnostic.threshold_all_land_grey', {
          darkest: Math.round(num(d, 'darkest') * levels),
          thresh: Math.round(num(d, 'thresh') * levels),
          levels,
        })
      }
      return t('diagnostic.threshold_all_land', {
        darkest: fraction(num(d, 'darkest')),
        thresh: fraction(num(d, 'thresh')),
      })
    }
    case 'threshold_reach':
      return t('diagnostic.threshold_reach', {
        reach: roundM(num(d, 'reach_m')),
        white: roundM(num(d, 'max_m')),
        share: pct(num(d, 'reach_share')),
        suggested: roundM(num(d, 'suggested_white_m')),
      })
    case 'metres_all_sea':
      return t('diagnostic.metres_all_sea', {
        highest: roundM(num(d, 'highest_m')),
        sea: roundM(num(d, 'sea_m')),
      })
    case 'metres_all_land':
      return t('diagnostic.metres_all_land', {
        lowest: roundM(num(d, 'lowest_m')),
        sea: roundM(num(d, 'sea_m')),
      })
    default:
      return null
  }
}
