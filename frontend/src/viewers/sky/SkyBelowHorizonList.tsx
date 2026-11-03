/** SkyBelowHorizonList — the quantitative home for bodies under the ground:
 *  names + next-rise countdown, shared by the pan view and the all-sky disc.
 */

import { useTranslation } from 'react-i18next'

import type { TargetPosition } from './types'

export interface SkyBelowHorizonListProps {
  rows: TargetPosition[]
  selectedId: string | null
}

export default function SkyBelowHorizonList({ rows, selectedId }: SkyBelowHorizonListProps) {
  const { t } = useTranslation('sky')
  if (rows.length === 0) return null
  return (
    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500">
      <span className="text-gray-600">{t('chart.belowHorizon')}:</span>
      {rows.map((row) => (
        <span
          key={row.body_id}
          className={row.body_id === selectedId ? 'text-amber-300' : undefined}
        >
          {row.name ?? row.body_id}
          {row.next_rise_days !== null && row.next_rise_days !== undefined
            ? ` ↑${row.next_rise_days.toFixed(1)}d`
            : ''}
        </span>
      ))}
    </div>
  )
}
